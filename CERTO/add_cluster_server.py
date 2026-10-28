#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Instalador BotHub: instala o worker e configura supervisor/boot no Termux."""
from __future__ import annotations

import os
import platform
import subprocess
import sys
import urllib.request
from pathlib import Path

WORKER_URL = "https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/bothub_firebase_worker.py"
ROOT = Path.cwd().resolve()
WORKER = ROOT / "bothub_firebase_worker.py"
VENV = ROOT / "venv"
PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
TERMUX = "com.termux" in str(Path.home()).lower() or "ANDROID_ROOT" in os.environ
SUPERVISOR = ROOT / "bothub_supervisor.py"
LOG_DIR = ROOT / "logs"


def run(args):
    print("\n[BotHub Installer] $", " ".join(map(str, args)), flush=True)
    subprocess.check_call(args)


def download():
    print("[BotHub Installer] Baixando worker atualizado...", flush=True)
    req = urllib.request.Request(
        WORKER_URL, headers={"User-Agent": "BotHub-Installer/2.1"}
    )
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


def install_termux_autostart():
    """Cria supervisor e script Termux:Boot; não requer root."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    supervisor_code = r'''#!/usr/bin/env python3
# Supervisor BotHub: mantém o worker ativo e reinicia após encerramento.
import fcntl
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / "venv" / "bin" / "python"
WORKER = ROOT / "bothub_firebase_worker.py"
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG = LOG_DIR / "worker.log"
LOCK = ROOT / ".bothub-supervisor.lock"

def log(message):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
        f.flush()

def main():
    with LOCK.open("w") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("O supervisor BotHub já está em execução.")
            return 0

        while True:
            if not PYTHON.exists() or not WORKER.exists():
                log("Python do ambiente ou worker não encontrado; nova tentativa em 10s.")
                time.sleep(10)
                continue
            try:
                log("Iniciando worker.")
                with LOG.open("a", encoding="utf-8") as output:
                    process = subprocess.Popen(
                        [str(PYTHON), str(WORKER)],
                        cwd=str(ROOT),
                        stdin=subprocess.DEVNULL,
                        stdout=output,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                    code = process.wait()
                log(f"Worker encerrou (código {code}); reinício em 5 segundos.")
            except KeyboardInterrupt:
                log("Supervisor interrompido pelo usuário.")
                return 130
            except Exception as exc:
                log(f"Erro ao iniciar/monitorar worker: {exc!r}; nova tentativa em 10s.")
            time.sleep(5)

if __name__ == "__main__":
    raise SystemExit(main())
'''
    SUPERVISOR.write_text(supervisor_code, encoding="utf-8")
    SUPERVISOR.chmod(0o700)

    boot_dir = Path.home() / ".termux" / "boot"
    boot_dir.mkdir(parents=True, exist_ok=True)
    boot_script = boot_dir / "bothub-start.sh"
    boot_script.write_text(
        """#!/data/data/com.termux/files/usr/bin/bash
# Inicialização automática BotHub via Termux:Boot
ROOT=\"{root}\"
mkdir -p \"$ROOT/logs\"
termux-wake-lock >/dev/null 2>&1 || true
nohup \"$ROOT/venv/bin/python\" \"$ROOT/bothub_supervisor.py\" \
  >> \"$ROOT/logs/supervisor.log\" 2>&1 </dev/null &
""".format(root=str(ROOT)),
        encoding="utf-8",
    )
    boot_script.chmod(0o700)

    # O app Termux:API também precisa estar instalado no Android.
    # O pacote fornece o comando termux-wake-lock dentro do Termux.
    try:
        run(["pkg", "install", "-y", "termux-api"])
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print("[BotHub Installer] Aviso: não consegui instalar o pacote termux-api:", exc)
        print("[BotHub Installer] Se necessário, execute: pkg install termux-api")

    print("[BotHub Installer] Termux:Boot configurado:", boot_script)
    print("[BotHub Installer] Supervisor:", SUPERVISOR)
    print("[BotHub Installer] Logs:", LOG_DIR)
    print("[BotHub Installer] O app Termux:Boot precisa ter sido aberto ao menos uma vez.")
    print("[BotHub Installer] Desative a otimização/restrição de bateria para Termux e Termux:Boot.")
    return 0


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
    print("[BotHub Installer] Observação: ative Anonymous em Firebase Authentication > Sign-in method antes da primeira execução.")

    if TERMUX:
        install_termux_autostart()
        print("[BotHub Installer] Iniciando supervisor; ele reiniciará o worker se ele encerrar.")
        os.execv(str(PYTHON), [str(PYTHON), str(SUPERVISOR)])

    print("[BotHub Installer] Para iniciar novamente:")
    print(" ", str(PYTHON), str(WORKER))
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
