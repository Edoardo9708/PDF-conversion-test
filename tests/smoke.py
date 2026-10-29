"""Simple end-to-end smoke test of official archive-pdf-tools, no private documents."""
import fitz
from backend import optimize_pdf

doc = fitz.open()
page = doc.new_page(width=420, height=595)
page.insert_text((40, 80), "DOCUMENTO DI PROVA", fontsize=19)
page.insert_text((40, 120), "Risultato clinico fittizio: 12,34", fontsize=13)
page.insert_text((40, 150), "Questo documento non contiene dati personali.", fontsize=11)
source = doc.tobytes()
output, pages = optimize_pdf(source, "alta", True)
assert pages == 1 and len(output) > 1000
result = fitz.open(stream=output, filetype="pdf")
assert result.page_count == 1
assert result[0].rect.width > 0
print("Official recode_pdf smoke test OK:", len(source), "->", len(output), "bytes")
