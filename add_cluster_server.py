#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Instalador BotHub: instala e inicia o worker na pasta atual."""
from __future__ import annotations
import os, platform, subprocess, sys, urllib.request
from pathlib import Path

WORKER_URL = "https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/bothub_firebase_worker.py"
ROOT = Path.cwd().resolve()
WORKER = ROOT / "bothub_firebase_worker.py"
VENV = ROOT / "venv"
PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
TERMUX = "com.termux" in str(Path.home()).lower() or "ANDROID_ROOT" in os.environ

def run(args):
    print("\n[BotHub Installer] $", " ".join(map(str, args)), flush=True)
    subprocess.check_call(args)

def download():
    print("[BotHub Installer] Baixando worker atualizado...", flush=True)
    req = urllib.request.Request(WORKER_URL, headers={"User-Agent":"BotHub-Installer/2.0"})
    with urllib.request.urlopen(req, timeout=45) as response:
        data = response.read()
    if len(data) < 1000 or b"workerTasks/" not in data or b"accounts:signUp" not in data:
        raise RuntimeError("O worker baixado não passou na verificação.")
    tmp = WORKER.with_suffix(".py.tmp")
    tmp.write_bytes(data)
    tmp.replace(WORKER)
    try:
        WORKER.chmod(0o700)
    except OSError:
        pass

def main():
    if sys.version_info < (3, 10):
        print("ERRO: é necessário Python 3.10 ou superior.")
        return 2
    ROOT.mkdir(parents=True, exist_ok=True)
    if not PYTHON.exists():
        print("[BotHub Installer] Criando ambiente Python dentro desta pasta...")
        try:
            run([sys.executable, "-m", "venv", str(VENV)])
        except subprocess.CalledProcessError:
            if platform.system() == "Linux":
                print("Ubuntu/Debian: instale python3-venv pelo gerenciador de pacotes.")
            raise
    run([str(PYTHON), "-m", "pip", "install", "--upgrade", "pip"])
    packages = ["requests", "discord.py", "aiohttp"]
    if not TERMUX:
        packages.append("psutil")
    else:
        print("[BotHub Installer] Termux detectado: não instala psutil; usa /proc como alternativa.")
    run([str(PYTHON), "-m", "pip", "install", "--upgrade", *packages])
    download()
    print("\n[BotHub Installer] Arquivos instalados em:", ROOT)
    print("[BotHub Installer] O worker vai gerar um ID e autenticar sem pedir e-mail/senha.")
    print("[BotHub Installer] Para iniciar novamente:")
    print(" ", str(PYTHON), str(WORKER))
    print("[BotHub Installer] Observação: ative Anonymous em Firebase Authentication > Sign-in method antes da primeira execução.")
    print("[BotHub Installer] O início automático após reiniciar o dispositivo depende do sistema operacional.")
    os.execv(str(PYTHON), [str(PYTHON), str(WORKER)])

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInstalação cancelada.")
        raise SystemExit(130)
    except Exception as exc:
        print("\n[BotHub Installer] ERRO:", str(exc), file=sys.stderr)
        raise SystemExit(1)
