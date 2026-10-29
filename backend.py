"""PDF optimizer powered by Internet Archive's official MRC engine.

Automatic quality selection tests several combinations on the same raster and
the same hOCR. It compares rasterized candidates against the ORIGINAL page,
with greater weight around text. This is a heuristic, not visual certification
and not an OCR correctness test.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Callable
import re
import shutil
import subprocess
import tempfile

import fitz
import numpy as np
from scipy.ndimage import maximum_filter

MAX_BYTES = 30 * 1024 * 1024
MAX_PAGES = 12
DPI = 250
QUALITY = {
    "alta": ("Alta fedeltà", 2, 1),
    "bilanciata": ("Bilanciata", 3, 1),
    "compatta": ("Compatta", 4, 1),
    "extra": ("Primo piano ridotto", 4, 2),
}
AUTO_PRESETS = ("alta", "bilanciata", "compatta", "extra")
DOWNSAMPLE = {key: item[1] for key, item in QUALITY.items() if key != "extra"}

class OptimizationError(Exception):
    pass


def _run(args: list[str], timeout: int = 240) -> str:
    try:
        proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, errors="replace", timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OptimizationError(f"Errore durante l'esecuzione di {args[0]}") from exc
    if proc.returncode:
        lines = (proc.stderr or proc.stdout).strip().splitlines()
        raise OptimizationError(f"{args[0]} non riuscito: {' | '.join(lines[-3:])[:500]}")
    return proc.stdout


def _page_count(path: Path, max_pages: int = MAX_PAGES) -> int:
    info = _run(["pdfinfo", str(path)])
    match = re.search(r"(?m)^Pages:\s*(\d+)\s*$", info)
    if not match:
        raise OptimizationError("Non riesco a determinare il numero di pagine")
    count = int(match.group(1))
    if not 1 <= count <= max_pages:
        raise OptimizationError(f"Sono supportate da 1 a {max_pages} pagine")
    return count


def _raster_gray(pdf: Path, dpi: int = 100) -> np.ndarray:
    """Render a single-page PDF at exactly the same sampling for all candidates."""
    with fitz.open(pdf) as doc:
        if doc.page_count != 1:
            raise OptimizationError("Confronto qualità: il PDF non contiene una sola pagina")
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72),
                                colorspace=fitz.csGRAY, alpha=False)
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width).copy()


def _compare_raster(reference: np.ndarray, candidate: np.ndarray) -> float:
    """Small score is better: compare ink and nearby edges, not paper noise.

    The source scan may be noisy, so a cleaned white background is deliberately
    not heavily penalized. There is no universal objective perceptual measure.
    """
    if reference.shape != candidate.shape:
        return float("inf")
    a = reference.astype(np.int16)
    b = candidate.astype(np.int16)
    ink = reference < 205
    if not np.any(ink):
        # Blank or unusually light page: compare overall instead.
        return float(np.abs(a - b).mean())
    around_text = maximum_filter(ink, size=3)
    difference = np.abs(a - b)
    ink_error = float(difference[around_text].mean())
    # Penalize newly created dark spots on portions of the clean paper.
    paper = reference > 245
    spots = (245 - b[paper]).clip(min=0)
    new_spots = float(spots.mean()) if spots.size else 0.0
    return ink_error + 0.35 * new_spots


def _accepted(score: float, high_quality_score: float) -> bool:
    """Preserve appearance close to the highest-quality MRC candidate."""
    return np.isfinite(score) and score <= high_quality_score + max(
        2.0, high_quality_score * 0.08
    )


def _mrc(image: Path, hocr: Path, output: Path,
         preset: str, grayscale: bool) -> None:
    _label, background_downsample, foreground_downsample = QUALITY[preset]
    command = [
        "recode_pdf", "-J", "openjpeg",
        "--bg-downsample", str(background_downsample),
        "--fg-downsample", str(foreground_downsample),
        "--from-imagestack", str(image),
        "--hocr-file", str(hocr),
        "--dpi", str(DPI), "-m", "2",
        "--mask-compression", "jbig2",
        "-o", str(output)
    ]
    if grayscale:
        command.append("--grayscale-pdf")
    _run(command)
    if not output.exists() or output.stat().st_size < 100:
        raise OptimizationError("Internet Archive non ha prodotto il PDF")


def optimize_pdf_file(source_path: Path, output_path: Path,
                      quality: str = "bilanciata", grayscale: bool = False,
                      max_bytes: int = MAX_BYTES, max_pages: int = MAX_PAGES,
                      progress: Callable[[str, int, int], None] | None = None,
                      summary: Callable[[dict], None] | None = None) -> int:
    """Disk-to-disk MRC: only ONE rasterized page is in the workspace at a time.

    The source and final output are paths, never full PDF buffers. Completed
    compressed one-page PDFs accumulate on disk until a final pdfunite.
    The caller must give a distinct output path and handle atomic replacement.
    """
    if quality not in (*DOWNSAMPLE, "automatica"):
        raise OptimizationError("Qualità non supportata")
    source_path, output_path = Path(source_path), Path(output_path)
    if source_path.resolve() == output_path.resolve():
        raise OptimizationError("L'originale non può essere sovrascritto direttamente")
    size = source_path.stat().st_size
    if size <= 0 or size > max_bytes:
        raise OptimizationError(f"Il PDF supera il limite di {max_bytes // 1048576} MB")
    with source_path.open("rb") as source:
        if source.read(5) != b"%PDF-":
            raise OptimizationError("Il file non sembra un PDF")
    count = _page_count(source_path, max_pages=max_pages)
    presets = AUTO_PRESETS if quality == "automatica" else (quality,)
    report = progress or (lambda stage, done, total: None)
    total = count * (2 + len(presets)) + (1 if count > 1 else 0)
    completed = 0
    selected: Counter[str] = Counter()

    with tempfile.TemporaryDirectory(prefix="pdfopt_") as temp:
        directory = Path(temp)
        chosen_files: list[Path] = []
        for number in range(1, count + 1):
            # All high-memory/high-disk page intermediates disappear after
            # every page. Only the selected one-page PDF is retained.
            with tempfile.TemporaryDirectory(prefix="page_", dir=directory) as work:
                workspace = Path(work)
                prefix = workspace / "scan"
                image = prefix.with_suffix(".png")
                hocr = prefix.with_suffix(".hocr")
                report(f"Pagina {number}/{count}: preparo la scansione",
                       completed, total)
                _run(["pdftoppm", "-f", str(number), "-l", str(number),
                      "-singlefile", "-r", str(DPI), "-png",
                      str(source_path), str(prefix)])
                completed += 1
                report(f"Pagina {number}/{count}: riconoscimento del testo",
                       completed, total)
                _run(["tesseract", str(image), str(prefix), "-l", "ita+eng", "hocr"])
                if not hocr.is_file():
                    raise OptimizationError("Tesseract non ha prodotto il livello OCR")
                completed += 1

                reference = None
                if quality == "automatica":
                    reference_pdf = workspace / "source.pdf"
                    _run(["pdfseparate", "-f", str(number), "-l", str(number),
                          str(source_path), str(reference_pdf)])
                    reference = _raster_gray(reference_pdf)

                candidates: list[tuple[str, Path, float, int]] = []
                for index, preset in enumerate(presets, start=1):
                    name, _, _ = QUALITY[preset]
                    report(f"Pagina {number}/{count}: MRC "
                           f"{index}/{len(presets)} ({name})", completed, total)
                    candidate = workspace / f"candidate-{preset}.pdf"
                    _mrc(image, hocr, candidate, preset, grayscale)
                    score = (0.0 if reference is None else
                             _compare_raster(reference, _raster_gray(candidate)))
                    candidates.append(
                        (preset, candidate, score, candidate.stat().st_size))
                    completed += 1

                if quality == "automatica":
                    baseline = candidates[0][2]
                    eligible = [c for c in candidates if _accepted(c[2], baseline)]
                    best = min(eligible or [candidates[0]], key=lambda c: c[3])
                else:
                    best = candidates[0]

                selected_pdf = directory / f"page-{number:05d}.pdf"
                best[1].replace(selected_pdf)
                chosen_files.append(selected_pdf)
                selected[best[0]] += 1
                report(f"Pagina {number}/{count}: scelta {QUALITY[best[0]][0]}",
                       completed, total)

        if count == 1:
            shutil.copyfile(chosen_files[0], output_path)
        else:
            report("Unisco le pagine ottimizzate", completed, total)
            _run(["pdfunite", *map(str, chosen_files), str(output_path)],
                 timeout=max(240, count * 4))
            completed += 1

        if not output_path.is_file() or output_path.stat().st_size < 100:
            raise OptimizationError("Il PDF finale non è stato generato")
        if _page_count(output_path, max_pages=max_pages) != count:
            raise OptimizationError("Il PDF finale ha perso delle pagine")

    if summary:
        summary({
            "mode": quality,
            "tested": len(presets) * count,
            "selected": {QUALITY[key][0]: value for key, value in selected.items()},
            "assessment": "Confronto visivo euristico; verificare le scansioni deboli"
        })
    report("PDF pronto", completed, total)
    return count


def optimize_pdf(source: bytes, quality: str = "bilanciata",
                 grayscale: bool = False,
                 progress: Callable[[str, int, int], None] | None = None,
                 summary: Callable[[dict], None] | None = None) -> tuple[bytes, int]:
    """Existing small single-file web API (Codespaces): unchanged upload limits."""
    if not source.startswith(b"%PDF-"):
        raise OptimizationError("Il file non sembra un PDF")
    if len(source) > MAX_BYTES:
        raise OptimizationError("Il PDF supera il limite di 30 MB")
    with tempfile.TemporaryDirectory(prefix="pdfopt_upload_") as temp:
        original = Path(temp) / "original.pdf"
        result = Path(temp) / "result.pdf"
        original.write_bytes(source)
        pages = optimize_pdf_file(original, result, quality, grayscale,
                                  max_bytes=MAX_BYTES, max_pages=MAX_PAGES,
                                  progress=progress, summary=summary)
        return result.read_bytes(), pages
