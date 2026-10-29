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
print("Local archive traversal safety OK")
