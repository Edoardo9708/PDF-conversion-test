"""Opt-in, local Docker-only recursive and atomic PDF archive conversion."""
from __future__ import annotations

import os
import stat
import tempfile
import threading
import time
from pathlib import Path

import fitz
from backend import MAX_BYTES, MAX_PAGES, optimize_pdf

ROOT = Path("/archive")
ENABLED = os.environ.get("PDF_OPTIMIZER_LOCAL_BATCH") == "1" and ROOT.is_dir()
MAX_FILES = 20000
_LOCK = threading.Lock()
_JOB = None
_CANCEL = False
_LOG = []


class BatchError(Exception):
    pass


def available():
    return ENABLED and ROOT.is_dir()


def folder(relative=""):
    if not available():
        raise BatchError("La gestione dell'archivio è disponibile solo nel Docker locale.")
    if not isinstance(relative, str) or len(relative) > 2048 or "\\" in relative or ":" in relative or relative.startswith("/"):
        raise BatchError("Percorso non valido.")
    if any(item in (".", "..") for item in relative.split("/") if item):
        raise BatchError("Percorso fuori dalla cartella condivisa.")
    try:
        root = ROOT.resolve(strict=True)
        selected = (root / relative).resolve(strict=True)
    except (OSError, RuntimeError):
        raise BatchError("Cartella non trovata.")
    if not selected.is_relative_to(root) or not selected.is_dir():
        raise BatchError("La cartella non è accessibile.")
    return selected


def rel(path):
    relative = path.relative_to(ROOT.resolve())
    return "" if relative == Path(".") else relative.as_posix()


def browse(relative=""):
    base = folder(relative)
    children = []
    for child in sorted(base.iterdir(), key=lambda p: p.name.casefold()):
        if not child.is_dir() or child.is_symlink():
            continue
        try:
            folder(rel(child))
            children.append({"name": child.name, "path": rel(child)})
        except BatchError:
            pass
    return {"path": rel(base), "parent": rel(base.parent) if base != ROOT.resolve() else "",
            "folders": children}


def gather(relative=""):
    base = folder(relative)
    output = []
    root = ROOT.resolve()
    for parent, dirs, filenames in os.walk(base, followlinks=False):
        here = Path(parent)
        dirs[:] = sorted((n for n in dirs if not (here / n).is_symlink()
                          and (here / n).resolve().is_relative_to(root)), key=str.casefold)
        for name in sorted(filenames, key=str.casefold):
            p = here / name
            if name.lower().endswith(".pdf") and not p.is_symlink() and p.resolve().is_relative_to(root):
                output.append(p)
                if len(output) > MAX_FILES:
                    raise BatchError("Oltre 20.000 PDF: scegli una sottocartella.")
    return output


def preview(relative=""):
    paths = gather(relative)
    size = 0
    for path in paths:
        try:
            size += path.stat().st_size
        except OSError:
            pass
    return {"path": relative, "count": len(paths), "bytes": size,
            "examples": [rel(p) for p in paths[:15]]}


def inspect(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink > 1:
        raise BatchError("Link o file non regolare.")
    if path.stat().st_size > MAX_BYTES:
        raise BatchError("Oltre 30 MB: originale conservato.")
    with path.open("rb") as inp:
        if inp.read(5) != b"%PDF-":
            raise BatchError("PDF non valido.")
    try:
        with fitz.open(path) as doc:
            if doc.needs_pass or not 1 <= doc.page_count <= MAX_PAGES:
                raise BatchError("PDF protetto, vuoto o oltre 12 pagine.")
            if "Internet Archive PDF" in ((doc.metadata or {}).get("producer") or ""):
                raise BatchError("Già ottimizzato con Internet Archive.")
            for page in doc:
                area = max(page.rect.get_area(), 1)
                if not any((fitz.Rect(im["bbox"]) & page.rect).get_area() >= area * .65
                           for im in page.get_image_info()):
                    raise BatchError("PDF non scannerizzato a pagina intera.")
            return doc.page_count
    except BatchError:
        raise
    except Exception as exc:
        raise BatchError("Struttura del PDF illeggibile.") from exc


def convert_one(path, quality, grayscale):
    pages = inspect(path)
    old = path.stat(follow_symlinks=False)
    source = path.read_bytes()
    if len(source) != old.st_size:
        raise BatchError("Il file è cambiato durante la lettura.")
    output, result_pages = optimize_pdf(source, quality, grayscale)
    if result_pages != pages or not output.startswith(b"%PDF-"):
        raise BatchError("Conversione non valida.")
    if len(output) >= len(source):
        return "skipped", 0, "Risultato non più piccolo."
    try:
        with fitz.open(stream=output, filetype="pdf") as doc:
            if doc.needs_pass or doc.page_count != pages:
                raise BatchError("Verifica PDF convertito non superata.")
    except BatchError:
        raise
    except Exception as exc:
        raise BatchError("PDF convertito illeggibile.") from exc
    fd, temp = tempfile.mkstemp(prefix=".__pdfopt_", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as dst:
            dst.write(output)
            dst.flush()
            os.fsync(dst.fileno())
        os.chmod(temp, stat.S_IMODE(old.st_mode))
        os.utime(temp, ns=(old.st_atime_ns, old.st_mtime_ns))
        now = path.stat(follow_symlinks=False)
        if (path.is_symlink() or now.st_ino != old.st_ino or
            now.st_mtime_ns != old.st_mtime_ns or now.st_size != old.st_size):
            raise BatchError("Il file è cambiato durante la conversione.")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return "converted", len(source) - len(output), ""


def active():
    with _LOCK:
        return _JOB is not None and _JOB["state"] in ("queued", "running")


def state():
    with _LOCK:
        if _JOB is None:
            return {"state": "idle", "done": 0, "total": 0, "converted": 0,
                    "skipped": 0, "failed": 0, "saved_bytes": 0, "recent": []}
        return dict(_JOB, recent=_LOG[-20:],
                    elapsed=round(time.monotonic() - _JOB["started"]))


def report():
    snapshot = state()
    with _LOCK:
        snapshot["records"] = list(_LOG)
    return snapshot


def stop():
    global _CANCEL
    with _LOCK:
        if _JOB is None or _JOB["state"] not in ("queued", "running"):
            raise BatchError("Nessuna coda da fermare.")
        _CANCEL = True
        _JOB["phase"] = "Interruzione dopo il PDF corrente."
    return state()


def _worker(paths, quality, grayscale):
    with _LOCK:
        _JOB["state"] = "running"
    for path in paths:
        with _LOCK:
            if _CANCEL:
                _JOB.update(state="stopped", phase="Coda fermata.", file="")
                return
            name = rel(path)
            _JOB["file"] = name
            _JOB["phase"] = "Elaboro il PDF " + str(_JOB["done"] + 1) + "/" + str(_JOB["total"])
        try:
            outcome, saved, message = convert_one(path, quality, grayscale)
        except BatchError as exc:
            outcome, saved, message = "skipped", 0, str(exc)
        except Exception as exc:
            outcome, saved, message = "failed", 0, "Conversione fallita (" + type(exc).__name__ + ")."
        with _LOCK:
            _LOG.append({"file": name, "result": outcome, "message": message,
                         "saved_bytes": saved})
            _JOB["done"] += 1
            _JOB[outcome] += 1
            _JOB["saved_bytes"] += saved
    with _LOCK:
        _JOB.update(state="done", phase="Archivio elaborato.", file="")


def start(relative, quality, grayscale, backup_confirmed):
    global _JOB, _CANCEL, _LOG
    if backup_confirmed is not True:
        raise BatchError("Devi confermare un backup separato dell'archivio.")
    if quality not in ("alta", "bilanciata", "compatta", "automatica"):
        raise BatchError("Qualità non valida.")
    paths = gather(relative)
    if not paths:
        raise BatchError("Non ho trovato PDF nella cartella.")
    with _LOCK:
        if _JOB is not None and _JOB["state"] in ("queued", "running"):
            raise BatchError("Una coda è già in esecuzione.")
        _CANCEL = False
        _LOG = []
        _JOB = {"state": "queued", "phase": "Preparo la coda", "file": "",
                "folder": relative, "started": time.monotonic(), "done": 0,
                "total": len(paths), "converted": 0, "skipped": 0,
                "failed": 0, "saved_bytes": 0}
        threading.Thread(target=_worker, args=(paths, quality, grayscale),
                         daemon=True, name="archive-batch").start()
    return state()
