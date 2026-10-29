"""Long multi-page local path test without expensive OCR or private PDFs."""
import tempfile
from pathlib import Path
from unittest.mock import patch
import fitz
import backend


with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    source = root / "source.pdf"
    result = root / "result.pdf"
    doc = fitz.open()
    for i in range(14):
        doc.new_page(width=300, height=400).insert_text((10, 20), f"pagina {i}")
    doc.save(source)
    doc.close()

    def render_command(args, timeout=240):
        operation = args[0]
        if operation == "pdftoppm":
            Path(args[-1] + ".png").write_bytes(b"mock image")
        elif operation == "tesseract":
            Path(args[2] + ".hocr").write_text("<html></html>")
        elif operation in ("pdfinfo", "pdfunite"):
            return original_run(args, timeout=timeout)
        else:
            raise AssertionError(f"Unexpected command: {operation}")
        return ""

    def mrc_command(image, hocr, output, preset, grayscale):
        d = fitz.open()
        d.new_page(width=300, height=400).insert_text((10, 20), "output")
        d.save(output)
        d.close()

    original_run = backend._run
    with patch.object(backend, "_run", side_effect=render_command), \
         patch.object(backend, "_mrc", side_effect=mrc_command):
        count = backend.optimize_pdf_file(
            source, result, "alta", True, max_pages=50,
            max_bytes=2*1024*1024*1024)
    assert count==14
    with fitz.open(result) as output:
        assert output.page_count==14
print("Long document streaming page-by-page test OK")
