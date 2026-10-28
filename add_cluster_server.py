#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Instalador BotHub Firebase Worker: grava todos os arquivos na pasta atual."""
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
    print("[BotHub Installer] Baixando worker Firebase atualizado…", flush=True)
    req = urllib.request.Request(WORKER_URL, headers={"User-Agent":"BotHub-Firebase-Installer/1.1"})
    with urllib.request.urlopen(req, timeout=45) as r:
        data = r.read()
    if len(data) < 1000 or b"workerTasks/" not in data:
        raise RuntimeError("O worker baixado não passou na verificação básica.")
    tmp = WORKER.with_suffix(".py.tmp")
    tmp.write_bytes(data)
    tmp.replace(WORKER)
    try: WORKER.chmod(0o700)
    except OSError: pass

def main():
    if sys.version_info < (3, 10):
        print("ERRO: instale Python 3.10 ou superior.")
        return 2
    ROOT.mkdir(parents=True, exist_ok=True)
    if not PYTHON.exists():
        print("[BotHub Installer] Criando ambiente Python isolado…")
        try:
            run([sys.executable, "-m", "venv", str(VENV)])
        except subprocess.CalledProcessError:
            if platform.system() == "Linux":
                print("Ubuntu/Debian: sudo apt install python3-venv")
            raise
    run([str(PYTHON), "-m", "pip", "install", "--upgrade", "pip"])
    packages = ["requests", "discord.py", "aiohttp"]
    if not TERMUX:
        packages.append("psutil")
    else:
        print("[BotHub Installer] Android/Termux detectado: pulando psutil; o worker usa /proc como alternativa.")
    run([str(PYTHON), "-m", "pip", "install", "--upgrade", *packages])
    download()
    print("\n[BotHub Installer] Instalação concluída.")
    print("O worker será iniciado agora. Na primeira execução, informe um ID único e as credenciais Firebase.")
    print("Pasta do worker e dos dados:", ROOT)
    print("Para iniciar novamente:", str(PYTHON), str(WORKER))
    print("Todos os arquivos ficam nesta pasta; nada é criado em ~/.bothub.")
    print("A inicialização automática no boot ainda precisa ser configurada separadamente.")
    os.execv(str(PYTHON), [str(PYTHON), str(WORKER)])

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInstalação cancelada.")
        raise SystemExit(130)
    except Exception as e:
        print("\n[BotHub Installer] ERRO:", str(e), file=sys.stderr)
        raise SystemExit(1)
