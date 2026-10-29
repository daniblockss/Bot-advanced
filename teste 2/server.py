#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BOT_HUB_SERVER_BOOTSTRAP: atualiza os componentes do servidor e inicia o instalador."""
from __future__ import annotations
import hashlib
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "https://raw.githubusercontent.com/daniblockss/Bot-advanced/teste-2/teste%202"
ROOT = Path(__file__).resolve().parent
INSTALLER = ROOT / "add_cluster_server.py"
WORKER = ROOT / "bothub_firebase_worker.py"

COMPONENTS = (
    {
        "name": "add_cluster_server.py",
        "url": BASE_URL + "/add_cluster_server.py",
        "path": INSTALLER,
        "minimum": 1500,
        "markers": (b"def download()", b"bothub_firebase_worker.py", b"def main()"),
    },
    {
        "name": "bothub_firebase_worker.py",
        "url": BASE_URL + "/bothub_firebase_worker.py",
        "path": WORKER,
        "minimum": 10000,
        "markers": (b"workerTasks/", b"accounts:signUp", b"def main("),
    },
)

def baixar_componente(item):
    req = urllib.request.Request(
        item["url"] + "?cachebust=" + str(int(time.time())),
        headers={"User-Agent": "BotHub-Server/1.0", "Cache-Control": "no-cache"},
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        data = response.read()
    if len(data) < item["minimum"] or not all(marker in data for marker in item["markers"]):
        raise RuntimeError(item["name"] + " baixado não passou na verificação.")
    atual = b""
    try:
        atual = item["path"].read_bytes()
    except OSError:
        pass
    if atual == data:
        print("[BotHub Server] " + item["name"] + " já está atualizado.", flush=True)
        return
    tmp = item["path"].with_suffix(item["path"].suffix + ".download")
    tmp.write_bytes(data)
    # Confere novamente antes de trocar o arquivo ativo.
    validado = tmp.read_bytes()
    if len(validado) < item["minimum"] or not all(marker in validado for marker in item["markers"]):
        tmp.unlink(missing_ok=True)
        raise RuntimeError("Falha na validação temporária de " + item["name"])
    tmp.replace(item["path"])
    try:
        item["path"].chmod(0o700)
    except OSError:
        pass
    print("[BotHub Server] " + item["name"] + " atualizado (" + hashlib.sha256(data).hexdigest()[:12] + ").", flush=True)

def main():
    if sys.version_info < (3, 10):
        print("[BotHub Server] É necessário Python 3.10 ou superior.", file=sys.stderr)
        return 2
    ROOT.mkdir(parents=True, exist_ok=True)
    falhas = []
    for item in COMPONENTS:
        try:
            baixar_componente(item)
        except Exception as exc:
            falhas.append((item, exc))
            print("[BotHub Server] Erro ao atualizar " + item["name"] + ": " + str(exc)[:200], file=sys.stderr, flush=True)
            if not item["path"].exists():
                print("[BotHub Server] O arquivo não existe localmente; não é possível continuar.", file=sys.stderr, flush=True)
                return 1
    if falhas:
        print("[BotHub Server] Continuando com os arquivos locais válidos para não interromper o servidor.", flush=True)
    print("[BotHub Server] Iniciando add_cluster_server.py...", flush=True)
    os.execv(sys.executable, [sys.executable, str(INSTALLER)])

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
