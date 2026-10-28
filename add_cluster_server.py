#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Instalador BotHub P2P. Cria start.py na pasta atual e inicia o cluster."""
from __future__ import annotations

import os
import secrets
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path.cwd().resolve()
VENV = ROOT / "venv"
CLUSTER = ROOT / "bothub_cluster.py"
START = ROOT / "start.py"
CLUSTER_URL = "https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/bothub_cluster.py"

START_TEMPLATE = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inicializador do nó BotHub P2P. Todos os dados ficam na pasta atual."""
from __future__ import annotations
import json, os, secrets, subprocess, sys
from pathlib import Path
from getpass import getpass

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "cluster_config.json"
CLUSTER = ROOT / "bothub_cluster.py"
PYTHON = ROOT / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

def write_config(cfg):
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try: tmp.chmod(0o600)
    except OSError: pass
    tmp.replace(CONFIG)

def main():
    if not CLUSTER.exists():
        print("[BotHub] Não encontrei bothub_cluster.py na pasta:", ROOT)
        return 2
    cfg = {}
    if CONFIG.exists():
        try: cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        except Exception: cfg = {}
    if not cfg.get("node_id") or not cfg.get("secret") or not cfg.get("admin_token"):
        print("\n=== Configuração inicial do nó BotHub P2P ===")
        print("Use o MESMO segredo de cluster em todos os servidores que devem confiar uns nos outros.")
        node = input("Nome deste servidor (ex.: server1): ").strip() or ("server-" + secrets.token_hex(3))
        secret = getpass("Segredo compartilhado do cluster (mínimo 32 caracteres; guarde-o): ").strip()
        if len(secret) < 32:
            print("O segredo precisa ter pelo menos 32 caracteres.")
            return 2
        admin = secrets.token_urlsafe(32)
        print("\nToken administrativo local gerado (guarde-o):")
        print(admin)
        peers = {}
        print("\nPares conhecidos no formato ID=URL, por exemplo server1=http://192.168.1.10:47800")
        print("Deixe o ID vazio para terminar. Para internet, o nó remoto precisa estar acessível e a porta configurada.")
        while True:
            line = input("Par (ID=URL, vazio para terminar): ").strip()
            if not line: break
            if "=" not in line:
                print("Formato inválido; use ID=URL.")
                continue
            pid, url = line.split("=", 1)
            pid, url = pid.strip(), url.strip()
            if not pid or pid == node or not url.startswith(("http://", "https://")):
                print("ID/URL inválido ou ID igual ao deste nó.")
                continue
            peers[pid] = url
        cfg = {"node_id": node, "secret": secret, "admin_token": admin, "peers": peers}
        write_config(cfg)
    env = os.environ.copy()
    env.update({
        "BOTHUB_CLUSTER_HOME": str(ROOT),
        "BOTHUB_NODE_ID": cfg["node_id"],
        "BOTHUB_CLUSTER_SECRET": cfg["secret"],
        "BOTHUB_ADMIN_TOKEN": cfg["admin_token"],
        "BOTHUB_CLUSTER_PEERS_JSON": json.dumps(cfg.get("peers", {})),
    })
    print("\n[BotHub] Iniciando nó", cfg["node_id"], "na pasta", ROOT)
    print("[BotHub] Administração: execute novamente start.py e use o modo admin quando solicitado.")
    if len(sys.argv) > 1 and sys.argv[1] == "admin":
        return subprocess.call([str(PYTHON), str(CLUSTER), "admin"], cwd=str(ROOT), env=env)
    return subprocess.call([str(PYTHON), str(CLUSTER)], cwd=str(ROOT), env=env)

if __name__ == "__main__":
    raise SystemExit(main())
'''

def run(args: list[str], check: bool = True):
    print("\n[BotHub] $", " ".join(map(str, args)), flush=True)
    return subprocess.run(args, check=check, cwd=str(ROOT))

def download(url: str, destination: Path):
    print("[BotHub] Baixando", destination.name, "...", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "BotHub-P2P-Installer/1.0"})
    with urllib.request.urlopen(req, timeout=45) as response:
        data = response.read()
    if len(data) < 1000:
        raise RuntimeError("O arquivo baixado parece incompleto; nada será iniciado.")
    destination.write_bytes(data)
    try: destination.chmod(0o700)
    except OSError: pass

def main():
    if sys.version_info < (3, 10):
        print("[BotHub] ERRO: Python 3.10 ou superior é necessário.")
        return 2
    if START.exists():
        answer = input("[BotHub] start.py já existe. Substituir? [s/N] ").strip().lower()
        if answer != "s":
            print("[BotHub] Instalação cancelada para preservar o start.py existente.")
            return 1
    venv_python = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    run([sys.executable, "-m", "venv", str(VENV)], check=False)
    if not venv_python.exists():
        print("[BotHub] Não consegui criar o ambiente virtual. Em Debian/Ubuntu: sudo apt install python3-venv")
        return 2
    run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(venv_python), "-m", "pip", "install", "--upgrade", "discord.py", "aiohttp", "requests", "psutil"])
    download(CLUSTER_URL, CLUSTER)
    START.write_text(START_TEMPLATE, encoding="utf-8")
    try: START.chmod(0o700)
    except OSError: pass
    print("\n[BotHub] Arquivos preparados em:", ROOT)
    print("[BotHub] O instalador vai se apagar e executar start.py.")
    installer = Path(__file__).resolve()
    try:
        installer.unlink()
    except OSError as exc:
        print("[BotHub] Aviso: não consegui apagar o instalador:", exc)
    os.execv(str(venv_python), [str(venv_python), str(START)])

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[BotHub] Operação cancelada.")
        raise SystemExit(130)
    except Exception as exc:
        print("\n[BotHub] ERRO:", exc, file=sys.stderr)
        print("[BotHub] O instalador não será apagado se a preparação falhar.", file=sys.stderr)
        raise SystemExit(1)
