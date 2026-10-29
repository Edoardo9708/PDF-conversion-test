"""Synthetic documents: never test with medical or other user files."""
from pathlib import Path
from unittest.mock import patch
import tempfile
import fitz
import batch

with tempfile.TemporaryDirectory() as rootdir:
    root=Path(rootdir)
    sub=root/"A"/"B"
    sub.mkdir(parents=True)
    original=sub/"scan.pdf"
    d=fitz.open()
    p=d.new_page()
    pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,100,150),0)
    pix.clear_with(210)
    p.insert_image(p.rect,pixmap=pix)
    original.write_bytes(d.tobytes())
    d.close()
    d=fitz.open()
    d.new_page().insert_text((40,50),"PDF born digital")
    (root/"A"/"native.pdf").write_bytes(d.tobytes())
    d.close()
    (root/"link").symlink_to("/tmp")
    with patch.object(batch,"ROOT",root),patch.object(batch,"ENABLED",True):
        assert batch.preview("A")["count"]==2
        assert batch.inspect(original)==1
        try:
            batch.inspect(root/"A"/"native.pdf")
            raise AssertionError("Digital PDFs must not be re-rasterized")
        except batch.BatchError:
            pass
        for invalid in ("/tmp", "../", "A/../../", "link"):
            try:
                batch.folder(invalid)
                raise AssertionError("Escaped root: "+invalid)
            except batch.BatchError:
                pass
        assert batch.browse("")["folders"][0]["name"]=="A"
        assert batch.gather("A")==[root/"A"/"native.pdf",original]

        # A genuinely smaller, still valid PDF with the same page is written
        # atomically. Here the converter is stubbed to isolate file handling.
        previous=original.read_bytes()
        with fitz.open(stream=previous,filetype="pdf") as src:
            smaller=src.tobytes(garbage=4,deflate=True)
        assert len(smaller)<len(previous), (len(smaller),len(previous))
        with patch.object(batch,"optimize_pdf",return_value=(smaller,1)):
            outcome,saved,_=batch.convert_one(original,"automatica",True)
        assert outcome=="converted" and saved==len(previous)-len(smaller)
        assert original.read_bytes()==smaller
        assert not list(sub.glob(".__pdfopt_*"))

        # Bad output never overwrites the original.
        with patch.object(batch,"optimize_pdf",return_value=(b"%PDF-bad",1)):
            try:
                batch.convert_one(original,"automatica",True)
                raise AssertionError("Invalid output must not overwrite source")
            except batch.BatchError:
                pass
        assert original.read_bytes()==smaller

print("Local archive traversal safety OK")
