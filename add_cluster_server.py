#!/usr/bin/env python3
"""BotHub one-file cluster server installer.

Run with: python3 add_cluster_server.py
Requires Python 3.10+ and internet access. It prepares ~/.bothub/venv,
installs worker dependencies, downloads the official worker, then starts it.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
import urllib.request
from pathlib import Path

WORKER_URL = "https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/bothub_firebase_worker.py"
ROOT = Path.home() / ".bothub"
VENV = ROOT / "venv"
WORKER = ROOT / "bothub_firebase_worker.py"
PACKAGES = ["requests", "psutil", "discord.py", "aiohttp", "Pillow"]


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    print("\n[BotHub] $", " ".join(map(str, args)), flush=True)
    return subprocess.run(args, check=check)


def download(url: str, destination: Path) -> None:
    print(f"[BotHub] Baixando {destination.name}...", flush=True)
    request = urllib.request.Request(
        url, headers={"User-Agent": "BotHub-Cluster-Installer/1.0"}
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        data = response.read()
    if len(data) < 1000:
        raise RuntimeError("O arquivo baixado parece incompleto; nada foi executado.")
    destination.write_bytes(data)
    try:
        destination.chmod(0o700)
    except OSError:
        pass
    print(f"[BotHub] Download concluído ({len(data)} bytes).", flush=True)


def main() -> int:
    if sys.version_info < (3, 10):
        print("[BotHub] ERRO: instale Python 3.10 ou superior e rode este script novamente.")
        return 2

    if platform.system() == "Windows":
        vpy = VENV / "Scripts" / "python.exe"
        pip = VENV / "Scripts" / "pip.exe"
    else:
        vpy = VENV / "bin" / "python"
        pip = VENV / "bin" / "pip"

    ROOT.mkdir(parents=True, exist_ok=True)

    if not vpy.exists():
        print("[BotHub] Ambiente virtual não encontrado; criando...")
        result = run([sys.executable, "-m", "venv", str(VENV)], check=False)
        if result.returncode != 0:
            print("\n[BotHub] Não consegui criar o venv. Em Debian/Ubuntu, tente:")
            print("  sudo apt update && sudo apt install -y python3-venv python3-pip")
            print("Depois execute este instalador novamente.")
            return result.returncode or 1
    else:
        print("[BotHub] Ambiente virtual já existe; vou reutilizá-lo.")

    # Some Python installations create a venv without pip; bootstrap it if needed.
    if not pip.exists():
        print("[BotHub] pip não encontrado no venv; tentando instalar com ensurepip...")
        result = run([str(vpy), "-m", "ensurepip", "--upgrade"], check=False)
        if result.returncode != 0:
            print("[BotHub] Não foi possível ativar o pip automaticamente.")
            print("Em Debian/Ubuntu, instale python3-venv e python3-pip e rode novamente.")
            return result.returncode or 1

    print("[BotHub] Atualizando pip e verificando dependências...")
    run([str(vpy), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(vpy), "-m", "pip", "install", "--upgrade", *PACKAGES])

    download(WORKER_URL, WORKER)
    print("\n[BotHub] Preparação concluída. Iniciando o worker...")
    print("[BotHub] Na primeira execução, informe um ID exclusivo e as credenciais Firebase do worker.")
    os.execv(str(vpy), [str(vpy), str(WORKER)])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[BotHub] Instalação interrompida pelo usuário.")
        raise SystemExit(130)
    except Exception as exc:
        print(f"\n[BotHub] ERRO: {exc}", file=sys.stderr)
        print("[BotHub] Confira a conexão com a internet e tente novamente.", file=sys.stderr)
        raise SystemExit(1)
