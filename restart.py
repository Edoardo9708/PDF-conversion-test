"""Update/restart the PDF web server from the Codespaces terminal.

Run after git pull: python restart.py
Only stops python server.py processes belonging to this Codespace project.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import psutil

project = Path(__file__).resolve().parent
log = Path("/tmp/pdf-optimizer-server.log")
current_pid = os.getpid()

for process in psutil.process_iter(["pid", "name", "cmdline"]):
    try:
        if process.pid == current_pid:
            continue
        cmd = process.info["cmdline"] or []
        if len(cmd) < 2 or "python" not in Path(cmd[0]).name.lower():
            continue
        server_arg = next((s for s in cmd[1:] if s == "server.py" or s.endswith("/server.py")), None)
        if server_arg is None:
            continue
        cwd = Path(process.cwd())
        candidate = (cwd / server_arg).resolve()
        if candidate not in (project / "server.py", Path("/opt/pdf-optimizer/server.py")):
            continue
        print("Arresto il precedente PDF Optimizer...", flush=True)
        process.terminate()
        try:
            process.wait(timeout=4)
        except psutil.TimeoutExpired:
            process.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        continue

with log.open("ab") as output:
    process = subprocess.Popen(
        [sys.executable, str(project / "server.py")],
        cwd=str(project), stdin=subprocess.DEVNULL, stdout=output, stderr=output,
        start_new_session=True,
    )
print("Riavvio il server con la nuova interfaccia...", flush=True)
for _ in range(20):
    if process.poll() is not None:
        break
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=1) as response:
            result = response.read().decode()
        if "mobile-progress-v2" in result:
            print("✅ PDF Optimizer aggiornato, porta 8765 pronta!", flush=True)
            print("Apri la pagina della porta 8765 dalla scheda Ports.", flush=True)
            break
    except Exception:
        time.sleep(.3)
else:
    print("Il server non risponde. Leggi:", log, flush=True)
if process.poll() is not None:
    print("Server uscito: controlla", log, flush=True)
    sys.exit(1)
