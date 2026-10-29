"""Asynchronous PDF optimizer API for a PRIVATE Codespace.

The upload request returns immediately after receipt. The worker continues even
when a phone suspends polling. PDFs are never written into the git working tree.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import threading
import time
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from backend import MAX_BYTES, OptimizationError, optimize_pdf

PORT = int(os.getenv("PORT", "8765"))
INDEX = (Path(__file__).parent / "index.html").read_bytes()
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()
RESULT_TTL = 30 * 60  # Keep completed results in memory for 30 minutes.
MAX_FINISHED = 4


def prune_jobs() -> None:
    with LOCK:
        current = time.monotonic()
        for key, job in list(JOBS.items()):
            if job["state"] in ("done", "error") and current - job["updated"] > RESULT_TTL:
                del JOBS[key]
        finished = sorted(
            ((key, job) for key, job in JOBS.items()
             if job["state"] in ("done", "error")),
            key=lambda entry: entry[1]["updated"]
        )
        for key, _ in finished[:-MAX_FINISHED]:
            del JOBS[key]


def update_job(job_id: str, **kwargs: object) -> None:
    with LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(kwargs, updated=time.monotonic())


def process_job(job_id: str, raw: bytes, quality: str, grayscale: bool) -> None:
    def report(stage: str, completed: int, total: int) -> None:
        update_job(job_id, phase=stage, completed=completed, total=total)
        print("PDF Optimizer:", stage, flush=True)

    try:
        update_job(job_id, state="running", phase="Analizzo il PDF originale")
        result, pages = optimize_pdf(raw, quality, grayscale, progress=report)
        update_job(job_id, state="done", phase="Conversione completata",
                   result=result, pages=pages, output_bytes=len(result))
    except OptimizationError as exc:
        print("PDF Optimizer: conversione non riuscita:", str(exc)[-200:], flush=True)
        update_job(job_id, state="error", phase="Conversione non riuscita",
                   error=str(exc)[:400])
    except Exception as exc:
        print("PDF Optimizer: eccezione", type(exc).__name__, str(exc)[-200:], flush=True)
        update_job(job_id, state="error", phase="Conversione non riuscita",
                   error="Errore interno di elaborazione. Controlla il log del server.")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        # Filenames, document content and job identifiers must not appear in logs.
        pass

    def send_data(self, status: int, data: bytes, content_type: str,
                  headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                         "style-src 'self' 'unsafe-inline'; object-src 'none'; frame-ancestors 'none'")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def json(self, status: int, data: dict) -> None:
        self.send_data(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/":
            self.send_data(200, INDEX, "text/html; charset=utf-8")
            return
        if path == "/health":
            self.json(200, {
                "ready": all(shutil.which(binary) for binary in
                             ("recode_pdf", "jbig2", "opj_compress",
                              "opj_decompress", "tesseract", "pdftoppm")),
                "engine": "Internet Archive archive-pdf-tools",
                "interface": "mobile-progress-v2"
            })
            return
        match = re.fullmatch(r"/jobs/([a-zA-Z0-9_-]{32})(/download)?", path)
        if not match:
            self.json(404, {"error": "Pagina non trovata"})
            return
        job_id, download = match.groups()
        prune_jobs()
        with LOCK:
            job = JOBS.get(job_id)
            if job is None:
                response = None
            else:
                result = job.get("result") if download else None
                now = time.monotonic()
                response = {
                    "state": job["state"],
                    "phase": job["phase"],
                    "completed": job["completed"],
                    "total": job["total"],
                    "elapsed": round(now - job["created"]),
                    "idle": round(now - job["updated"]),
                    "original_bytes": job["original_bytes"],
                    "output_bytes": job.get("output_bytes"),
                    "pages": job.get("pages"),
                    "error": job.get("error")
                }
        if response is None:
            self.json(404, {"error": "Lavoro scaduto o non trovato"})
        elif download:
            if response["state"] != "done" or result is None:
                self.json(409, {"error": "Il PDF non è ancora disponibile"})
            else:
                self.send_data(200, result, "application/pdf", {
                    "Content-Disposition": 'attachment; filename="pdf_ottimizzato.pdf"'
                })
        else:
            self.json(200, response)

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/jobs":
            self.json(404, {"error": "Funzione non trovata"})
            return
        prune_jobs()
        with LOCK:
            busy = any(job["state"] in ("queued", "running") for job in JOBS.values())
        if busy:
            self.json(429, {"error": "Una conversione è già in corso. Attendi che finisca."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BYTES + 1024 * 1024:
                self.json(413, {"error": "Il PDF supera il limite di caricamento (30 MB)"})
                return
            content_type = self.headers.get("Content-Type", "")
            if not content_type.startswith("multipart/form-data;"):
                self.json(400, {"error": "Il caricamento non è multipart"})
                return
            envelope = (
                b"MIME-Version: 1.0\r\nContent-Type: " +
                content_type.encode("ascii") + b"\r\n\r\n" +
                self.rfile.read(length)
            )
            message = BytesParser(policy=policy.default).parsebytes(envelope)
            raw: bytes | None = None
            quality = "bilanciata"
            grayscale = False
            for part in message.iter_parts():
                name = part.get_param("name", header="Content-Disposition")
                payload = part.get_payload(decode=True) or b""
                if name == "file":
                    raw = payload
                elif name == "quality":
                    quality = payload.decode("utf-8", errors="replace")
                elif name == "grayscale":
                    grayscale = payload == b"on"
            if raw is None or not raw.startswith(b"%PDF-") or len(raw) > MAX_BYTES:
                self.json(400, {"error": "Seleziona un PDF valido (massimo 30 MB)"})
                return
            if quality not in ("alta", "bilanciata", "compatta"):
                self.json(400, {"error": "Qualità sconosciuta"})
                return
            job_id = secrets.token_urlsafe(24)
            now = time.monotonic()
            with LOCK:
                # Second check avoids parallel requests starting two conversions.
                if any(job["state"] in ("queued", "running") for job in JOBS.values()):
                    self.json(429, {"error": "Una conversione è già in corso"})
                    return
                JOBS[job_id] = {
                    "state": "queued", "phase": "Caricamento ricevuto",
                    "completed": 0, "total": 0,
                    "created": now, "updated": now,
                    "original_bytes": len(raw)
                }
            threading.Thread(
                target=process_job, args=(job_id, raw, quality, grayscale),
                daemon=True, name="pdf-optimizer-worker"
            ).start()
            print("PDF Optimizer: documento ricevuto, elaborazione avviata", flush=True)
            self.json(202, {"id": job_id})
        except (ValueError, UnicodeError):
            self.json(400, {"error": "Richiesta non valida"})
        except Exception as exc:
            print("PDF Optimizer: errore upload", type(exc).__name__, flush=True)
            self.json(500, {"error": "Errore nel caricamento del PDF"})


if __name__ == "__main__":
    print(f"PDF Optimizer disponibile sulla porta {PORT} (mobile-progress-v2)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
