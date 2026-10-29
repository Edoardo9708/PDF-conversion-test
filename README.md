# PDF Optimizer — Internet Archive (Codespaces)

Applicazione web sperimentale per comprimere PDF scansionati utilizzando **il vero motore**
[archive-pdf-tools](https://github.com/internetarchive/archive-pdf-tools)
(`recode_pdf` 1.5.7, MRC/JPEG2000/JBIG2). Non è un'implementazione alternativa.

## Aprire nel Codespace già creato
1. Nel terminale di Codespaces eseguire `git pull origin main`.
2. Aprire la palette comandi (`Ctrl+Shift+P`) e selezionare **Codespaces: Rebuild Container**.
3. Terminata la ricostruzione, aprire la scheda **Ports**, cercare la porta **8765**, confermare **Private** e aprire il relativo link.
4. Caricare una COPIA del PDF, scegliere la qualità e scaricare il risultato.
5. Se la pagina non si apre, leggere `cat /tmp/pdf-optimizer-server.log` dal terminale.

## Cosa fa
- Renderizza il PDF a 250 DPI con Poppler.
- Rigenera hOCR con Tesseract (`ita+eng`): **il vecchio OCR non è mantenuto identico**.
- Comprime ciascuna pagina con `recode_pdf`, `-m 2`, JPEG2000/OpenJPEG, maschera JBIG2.
- La scelta di qualità varia il downsampling dello sfondo. Opzionalmente produce il PDF in grigio.
- Riunisce le pagine con `pdfunite`. Gli intermedi sono cancellati con `TemporaryDirectory`.

## Diagnostica
- `curl http://127.0.0.1:8765/health` deve restituire `"ready": true`.
- `recode_pdf --version`; `which jbig2 opj_compress opj_decompress tesseract`.
- `python tests/smoke.py` genera un documento **sintetico**, lo comprime e verifica il PDF risultante.

## Riservatezza e limiti
- **Repository pubblico:** contiene solo codice. Non caricare referti nel repository, nemmeno per prova.
- **Codespace cloud:** i PDF transitano nel server Codespaces; la porta 8765 va lasciata Private.
- I file temporanei sono cancellati al termine della richiesta, ma ciò non equivale a una certificazione di riservatezza o conformità sanitaria.
- Fino a 30 MB e 12 pagine; Codespaces può avere costi oltre la quota inclusa.
- La compressione è con perdita: firme, valori clinici e OCR vanno controllati. Conservare l'originale.

Motore terzo soggetto alla licenza AGPL-3.0. Questo prototipo è fornito a scopo di test.
