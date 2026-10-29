# PDF Optimizer — Internet Archive (Codespaces)

Applicazione web sperimentale per comprimere PDF scansionati utilizzando **il vero motore**
[archive-pdf-tools](https://github.com/internetarchive/archive-pdf-tools)
(`recode_pdf` 1.5.7, MRC/JPEG2000/JBIG2). Non è un'implementazione alternativa.

## Aggiornamento facile da smartphone
Nel terminale del Codespace basta **un solo comando**:

```bash
cd /workspaces/PDF-conversion-test && git pull origin main && python restart.py
```

Il comando riavvia il solo server PDF Optimizer. Poi aggiorna la scheda web della porta **8765**, lasciata **Private**. Nell'app ora sono visibili OCR, compressione e stato dettagliato. La conversione continua sul server anche se il telefono sospende il browser; ricaricando la pagina si recupera il lavoro della sessione, se il server è ancora attivo.

## Aprire nel Codespace già creato
1. Nel terminale di Codespaces eseguire `git pull origin main`.
2. Aprire la palette comandi (`Ctrl+Shift+P`) e selezionare **Codespaces: Rebuild Container**.
3. Terminata la ricostruzione, aprire la scheda **Ports**, cercare la porta **8765**, confermare **Private** e aprire il relativo link.
4. Caricare una COPIA del PDF, scegliere la qualità e scaricare il risultato.
5. Se la pagina non si apre, leggere `cat /tmp/pdf-optimizer-server.log` dal terminale.

## Caricamento da Google Drive su Android
Il browser tenta di leggere completamente il file selezionato con FileReader,
prima di costruire il modulo di caricamento. In questo modo evita di passare
direttamente al motore di upload il riferimento a un file virtuale, che su
Chromium/Brave può produrre `ERR_UPLOAD_FILE_CHANGED`.

**Limite:** se Android non concede l'accesso al contenuto di Google Drive,
nessuna funzione web può leggere il file. In quel caso l'app mostra un errore
esplicito: scarica il documento in **Download** e selezionalo localmente.
Il documento non deve essere reso pubblico.

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


## Modalità archivio locale Windows (Docker)

Quando il PC sarà disponibile, avvia Docker Desktop e crea prima una copia di backup dell'archivio fuori dalla cartella da elaborare.
Nel repository esegui:

```powershell
docker build -t pdf-optimizer .
$archivio = 'C:\ArchivioPDF' # Modifica con il percorso REALE della copia da elaborare
docker run -d --restart unless-stopped --name pdf-optimizer-local --mount "type=bind,source=$archivio,target=/archive" -e PDF_OPTIMIZER_LOCAL_BATCH=1 -p 127.0.0.1:8765:8765 pdf-optimizer
```

Apri http://127.0.0.1:8765 e usa la sezione Intero archivio, visibile solo nel Docker locale. Seleziona la cartella montata o una sottocartella, visualizza l'anteprima, conferma il backup e avvia la coda.

Le scansioni di una o più pagine vengono convertite una per volta e sostituite atomicamente soltanto quando il PDF è valido e più piccolo. Sottocartelle e nomi restano identici. Si saltano i PDF digitali, quelli già ottimizzati e protetti. **Solo in Docker locale** i limiti predefiniti sono 2 GiB e 2.000 pagine per PDF; la coda accetta fino a 100.000 file. Il backup deve stare fuori dalla cartella montata. Si può interrompere la coda fra due PDF e scaricare un report JSON. Dopo un riavvio la coda ricomincia ma salta i PDF riconosciuti come già ottimizzati; il report di sessione non persiste.

Per fermare/riavviare il container: `docker stop pdf-optimizer-local` e `docker start pdf-optimizer-local`. Su Windows il percorso selezionabile è il percorso del mount Docker, non una cartella arbitraria scelta dal browser.


### Elaborazione locale di documenti molto grandi

Solo nella **coda cartelle Docker** l'input è letto direttamente dal disco, senza
caricare l'intero PDF in RAM. Le scansioni vengono convertite **una pagina alla
volta**, mantenendo su disco soltanto il PDF compresso scelto per ogni pagina.
Raster PNG, hOCR e quattro candidati vengono rimossi prima della pagina seguente.
Al termine le pagine sono riunite su disco e il risultato verificato prima
della sostituzione atomica del file originale.

Limiti locali predefiniti: **2.048 MiB / 2.000 pagine per PDF** e
**100.000 PDF nella coda**. Opzionalmente si possono impostare al comando
\`docker run\` le variabili \`PDF_OPTIMIZER_LOCAL_MAX_MB\`,
\`PDF_OPTIMIZER_LOCAL_MAX_PAGES\` e \`PDF_OPTIMIZER_LOCAL_MAX_FILES\`
(fino rispettivamente a 10.240 MiB, 10.000 pagine e 1.000.000 file).
I limiti servono a prevenire errori, non garantiscono che ogni file entro
soglia sia elaborabile. Una singola pagina ad altissima risoluzione può
comunque richiedere molta RAM e il merge finale richiede spazio disco.

La modalità di **upload dal browser/Codespaces rimane 30 MB / 12 pagine**.
Il servizio non riceve accesso ad altre cartelle del computer.
