"""Private web wrapper for Internet Archive's real archive-pdf-tools CLI.

All user files are handled in a temporary directory, never committed to Git.
Tesseract REGENERATES the OCR; do not treat as a certified original document.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

MAX_BYTES = 30 * 1024 * 1024
MAX_PAGES = 12
DPI = 250
DOWNSAMPLE = {"alta": 2, "bilanciata": 3, "compatta": 4}


class OptimizationError(Exception):
    pass


def _run(args: list[str], timeout: int = 240) -> str:
    try:
        proc = subprocess.run(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors="replace", timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OptimizationError(f"Errore durante l'esecuzione di {args[0]}") from exc
    if proc.returncode:
        lines = (proc.stderr or proc.stdout).strip().splitlines()
        # Diagnostics contain temporary paths but never the document content.
        raise OptimizationError(f"{args[0]} non riuscito: {' | '.join(lines[-3:])[:500]}")
    return proc.stdout


def _page_count(path: Path) -> int:
    info = _run(["pdfinfo", str(path)])
    match = re.search(r"(?m)^Pages:\s*(\d+)\s*$", info)
    if not match:
        raise OptimizationError("Non riesco a determinare le pagine del PDF")
    count = int(match.group(1))
    if not 1 <= count <= MAX_PAGES:
        raise OptimizationError(f"Sono supportate da 1 a {MAX_PAGES} pagine")
    return count


def optimize_pdf(source: bytes, quality: str = "bilanciata",
                 grayscale: bool = False) -> tuple[bytes, int]:
    if quality not in DOWNSAMPLE:
        raise OptimizationError("Qualità non supportata")
    if not source.startswith(b"%PDF-"):
        raise OptimizationError("Il file non sembra un PDF")
    if len(source) > MAX_BYTES:
        raise OptimizationError("Il PDF supera il limite di 30 MB")

    with tempfile.TemporaryDirectory(prefix="pdfopt_") as temp:
        directory = Path(temp)
        original = directory / "original.pdf"
        original.write_bytes(source)
        count = _page_count(original)
        results = []

        for number in range(1, count + 1):
            print(f"DIAGNOSTICA MOTORE: pagina {number}/{count}, raster", flush=True)
            prefix = directory / f"page-{number:03d}"
            image = prefix.with_suffix(".png")
            hocr = prefix.with_suffix(".hocr")
            output = directory / f"optimized-{number:03d}.pdf"

            _run(["pdftoppm", "-f", str(number), "-l", str(number),
                  "-singlefile", "-r", str(DPI), "-png",
                  str(original), str(prefix)])
            print(f"DIAGNOSTICA MOTORE: pagina {number}/{count}, OCR", flush=True)
            _run(["tesseract", str(image), str(prefix), "-l", "ita+eng", "hocr"])
            if not hocr.is_file():
                raise OptimizationError("Tesseract non ha prodotto il livello OCR")

            command = [
                "recode_pdf", "-J", "openjpeg", "--bg-downsample",
                str(DOWNSAMPLE[quality]),
                "--from-imagestack", str(image),
                "--hocr-file", str(hocr),
                "--dpi", str(DPI), "-m", "2",
                "--mask-compression", "jbig2",
                "-o", str(output),
            ]
            if grayscale:
                command.append("--grayscale-pdf")
            print(f"DIAGNOSTICA MOTORE: pagina {number}/{count}, MRC ufficiale", flush=True)
            _run(command)
            print(f"DIAGNOSTICA MOTORE: pagina {number}/{count}, MRC completato", flush=True)
            if not output.exists() or output.stat().st_size < 100:
                raise OptimizationError("Il programma ufficiale non ha prodotto il PDF")
            results.append(output)

        if count == 1:
            encoded = results[0].read_bytes()
        else:
            merged = directory / "result.pdf"
            _run(["pdfunite", *map(str, results), str(merged)])
            if _page_count(merged) != count:
                raise OptimizationError("Il risultato ha un numero di pagine errato")
            encoded = merged.read_bytes()
        return encoded, count
