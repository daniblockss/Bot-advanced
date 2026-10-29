#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Instalador BotHub: instala e inicia o worker na pasta atual."""
from __future__ import annotations
import os, platform, subprocess, sys, urllib.request
from pathlib import Path

GITHUB_RAW = "https://raw.githubusercontent.com/daniblockss/Bot-advanced/teste-2/teste%202"
INSTALLER_URL = GITHUB_RAW + "/add_cluster_server.py"
WORKER_URL = GITHUB_RAW + "/bothub_firebase_worker.py"
ROOT = Path(__file__).resolve().parent
WORKER = ROOT / "bothub_firebase_worker.py"
VENV = ROOT / "venv"
PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
TERMUX = "com.termux" in str(Path.home()).lower() or "ANDROID_ROOT" in os.environ

def run(args):
    print("\n[BotHub Installer] $", " ".join(map(str, args)), flush=True)
    subprocess.check_call(args)

def update_installer():
    """Confere a cópia pública no GitHub e reinicia se houver versão mais nova."""
    if os.environ.get("BOTHUB_INSTALLER_REFRESHED") == "1":
        return
    current = Path(__file__).resolve()
    try:
        req = urllib.request.Request(
            INSTALLER_URL + "?cachebust=" + str(int(__import__("time").time())),
            headers={"User-Agent": "BotHub-Installer/3.0", "Cache-Control": "no-cache"}
        )
        with urllib.request.urlopen(req, timeout=45) as response:
            latest = response.read()
        if len(latest) < 1000 or b"def download()" not in latest or b"bothub_firebase_worker.py" not in latest:
            raise RuntimeError("O instalador público baixado não passou na verificação.")
        try:
            existing = current.read_bytes()
        except OSError:
            existing = b""
        if existing != latest:
            tmp = current.with_suffix(current.suffix + ".update.tmp")
            tmp.write_bytes(latest)
            tmp.replace(current)
            print("[BotHub Installer] Instalador atualizado a partir do GitHub público. Reiniciando...", flush=True)
            env = dict(os.environ)
            env["BOTHUB_INSTALLER_REFRESHED"] = "1"
            os.execve(sys.executable, [sys.executable, str(current)], env)
    except Exception as exc:
        print("[BotHub Installer] Não consegui conferir a atualização do instalador; continuando com a cópia atual:", str(exc)[:180], flush=True)

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

def configure_autostart():
    """Instala um serviço systemd quando a máquina permite; assim o worker volta após reboot."""
    if os.name == "nt" or TERMUX or not sys.platform.startswith("linux"):
        print("[BotHub Installer] Inicialização automática do sistema não configurada nesta plataforma.")
        return False
    if not Path("/run/systemd/system").exists():
        print("[BotHub Installer] systemd não está disponível. Configure o worker no gerenciador de processos do host.")
        return False
    try:
        if os.geteuid() == 0:
            unit_dir = Path("/etc/systemd/system")
        else:
            unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        unit_file = unit_dir / "bothub-worker.service"
        unit_file.write_text(
            "[Unit]\\n"
            "Description=BotHub persistent worker\\n"
            "After=network-online.target\\n"
            "Wants=network-online.target\\n\\n"
            "[Service]\\n"
            "Type=simple\\n"
            "WorkingDirectory=" + str(ROOT) + "\\n"
            "ExecStart=" + str(PYTHON) + " " + str(WORKER) + "\\n"
            "Restart=always\\n"
            "RestartSec=5\\n"
            "KillMode=mixed\\n"
            "TimeoutStopSec=15\\n\\n"
            "[Install]\\n"
            "WantedBy=multi-user.target\\n",
            encoding="utf-8",
        )
        if os.geteuid() == 0:
            subprocess.run(["systemctl", "daemon-reload"], check=True, timeout=30)
            subprocess.run(["systemctl", "enable", "--now", "bothub-worker.service"], check=True, timeout=45)
        else:
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, timeout=30)
            subprocess.run(["systemctl", "--user", "enable", "--now", "bothub-worker.service"], check=True, timeout=45)
            print("[BotHub Installer] Serviço de usuário configurado. Para iniciar sem sessão aberta, o host precisa permitir linger.")
        print("[BotHub Installer] Inicialização automática configurada: bothub-worker.service", flush=True)
        return True
    except Exception as exc:
        print("[BotHub Installer] Não consegui configurar o serviço automaticamente:", str(exc)[:180], flush=True)
        print("[BotHub Installer] Inicie manualmente com:", str(PYTHON), str(WORKER), flush=True)
        return False


def main():
    if sys.version_info < (3, 10):
        print("ERRO: é necessário Python 3.10 ou superior.")
        return 2
    update_installer()
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
    service_started = configure_autostart()
    if service_started:
        print("[BotHub Installer] O serviço cuidará de manter o worker ligado após reinicializações.")
        return 0
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
