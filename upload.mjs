/**
 * Work around Chromium/Brave ERR_UPLOAD_FILE_CHANGED when the Android file
 * chooser returns a virtual file from Google Drive.
 *
 * Materialize the file's bytes in the browser BEFORE constructing the upload
 * multipart body. FormData must receive the detached Blob, NOT the original
 * potentially unstable cloud-provider File handle.
 *
 * This does not bypass provider permissions. If FileReader cannot read a
 * Drive document, the user must download it locally or use another browser.
 */
export function stagePdf(file, onProgress = () => {}) {
  if (!file) return Promise.reject(new Error("Seleziona un PDF."));
  if (file.size > 30 * 1024 * 1024) {
    return Promise.reject(new Error("Il PDF supera 30 MB."));
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onprogress = event => {
      if (event.lengthComputable && event.total > 0) {
        onProgress(event.loaded, event.total);
      } else {
        onProgress(0, file.size || 0);
      }
    };
    reader.onerror = () => reject(new Error(
      "Android non riesce a leggere il PDF da Google Drive o dal provider selezionato. " +
      "Apri Drive, scarica il file nella cartella Download e selezionalo da lì. " +
      "Puoi anche provare un altro browser."
    ));
    reader.onabort = () => reject(new Error("Lettura del documento interrotta."));
    reader.onload = () => {
      const buffer = reader.result;
      if (!(buffer instanceof ArrayBuffer) || buffer.byteLength === 0) {
        reject(new Error(
          "Il provider non ha fornito i dati del file. Scaricalo prima da Google Drive."
        ));
        return;
      }
      if (buffer.byteLength > 30 * 1024 * 1024) {
        reject(new Error("Il PDF supera 30 MB."));
        return;
      }
      // Cloud-backed File.size may be unknown or stale; trust the bytes read.
      const first = new Uint8Array(buffer, 0, Math.min(5, buffer.byteLength));
      if (first.length !== 5 || first[0] !== 37 || first[1] !== 80 ||
          first[2] !== 68 || first[3] !== 70 || first[4] !== 45) {
        reject(new Error(
          "Il file selezionato non contiene un PDF valido. " +
          "Se proviene da Drive, aprilo e scarica il PDF vero prima di selezionarlo."
        ));
        return;
      }
      onProgress(buffer.byteLength, buffer.byteLength);
      resolve(new Blob([buffer], { type: "application/pdf" }));
    };
    try {
      reader.readAsArrayBuffer(file);
    } catch (error) {
      reject(new Error(
        "Il browser non può accedere al file selezionato: scaricalo sul dispositivo e riprova."
      ));
    }
  });
}

export function makeUploadPayload(blob, filename, quality, grayscale) {
  const formData = new FormData();
  formData.append("file", blob, filename || "documento.pdf");
  formData.append("quality", quality);
  if (grayscale) formData.append("grayscale", "on");
  return formData;
}
