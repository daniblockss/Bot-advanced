#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ponto de entrada permanente do servidor BotHub. Mantenha este arquivo no painel."""
from __future__ import annotations
import os
import sys
import time
import urllib.request
from pathlib import Path

BASE_URL = "https://raw.githubusercontent.com/daniblockss/Bot-advanced/teste-2/teste%202"
SERVER_URL = BASE_URL + "/server.py"
ROOT = Path(__file__).resolve().parent
SERVER = ROOT / "server.py"
MIN_BYTES = 500

def baixar_server():
    req = urllib.request.Request(
        SERVER_URL + "?cachebust=" + str(int(time.time())),
        headers={"User-Agent": "BotHub-Start/1.0", "Cache-Control": "no-cache"},
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        data = response.read()
    if len(data) < MIN_BYTES or b"BOT_HUB_SERVER_BOOTSTRAP" not in data or b"add_cluster_server.py" not in data:
        raise RuntimeError("O server.py baixado não passou na verificação.")
    tmp = SERVER.with_suffix(".py.download")
    tmp.write_bytes(data)
    tmp.replace(SERVER)
    try:
        SERVER.chmod(0o700)
    except OSError:
        pass

def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    try:
        baixar_server()
        print("[BotHub Start] server.py atualizado.", flush=True)
    except Exception as exc:
        if not SERVER.exists():
            print("[BotHub Start] Não foi possível baixar server.py e não existe cópia local:", str(exc), file=sys.stderr, flush=True)
            return 1
        print("[BotHub Start] Sem atualização de server.py; usando a cópia local:", str(exc)[:180], flush=True)
    os.execv(sys.executable, [sys.executable, str(SERVER)])

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
