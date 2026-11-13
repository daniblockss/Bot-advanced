#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Instalador BotHub: instala e inicia o worker na pasta atual."""
from __future__ import annotations
import os, platform, shutil, subprocess, sys, urllib.request, shlex, time, json, zipfile, io
from pathlib import Path

INSTALLER_VERSION = "2026.11.13.13"
GITHUB_RAW = "https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/teste%202"
INSTALLER_URL = GITHUB_RAW + "/add_cluster_server.py"
WORKER_URL = GITHUB_RAW + "/bothub_firebase_worker.py"
ROOT = Path(__file__).resolve().parent
WORKER = ROOT / "bothub_firebase_worker.py"
VENV = ROOT / "venv"
PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
TERMUX = ("com.termux" in (str(Path.home()) + " " + os.environ.get("PREFIX", "")).lower() or bool(os.environ.get("TERMUX_VERSION")) or "ANDROID_ROOT" in os.environ or "ANDROID_DATA" in os.environ)

def run(args):
    print("\n[BotHub Installer] $", " ".join(map(str, args)), flush=True)
    subprocess.check_call(args)


def wake_screen_once():
    """Solicita que o Android acenda a tela sem alternar para apagada."""
    if not TERMUX:
        return
    command = shutil.which("input") or "/system/bin/input"
    try:
        result = subprocess.run(
            [command, "keyevent", "224"],
            capture_output=True, text=True, timeout=8
        )
        if result.returncode == 0:
            print("[BotHub Installer] Solicitação para acender a tela enviada.", flush=True)
        else:
            print("[BotHub Installer] Não foi possível acender a tela automaticamente; "
                  "o Android pode bloquear esse comando.", flush=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print("[BotHub Installer] Comando de tela indisponível:", str(exc)[:120], flush=True)

def ensure_termux_api():
    """Garante o pacote de comandos Termux:API antes de instalar o worker."""
    if not TERMUX:
        return

    battery_command = shutil.which("termux-battery-status")
    if battery_command:
        print("[BotHub Installer] Termux:API detectada. Continuando...", flush=True)
        return

    pkg = shutil.which("pkg")
    if not pkg:
        raise RuntimeError(
            "Termux foi detectado, mas o comando 'pkg' não está disponível. "
            "Não foi possível instalar termux-api."
        )

    print("[BotHub Installer] Termux:API não encontrada. Instalando com 'pkg install -y termux-api'...", flush=True)
    subprocess.check_call([pkg, "install", "-y", "termux-api"])

    if not shutil.which("termux-battery-status"):
        raise RuntimeError(
            "O pacote termux-api foi instalado, mas 'termux-battery-status' "
            "não foi encontrado. Confira a instalação do Termux:API."
        )

    print("[BotHub Installer] Termux:API instalada e verificada.", flush=True)


def remove_legacy_autostart():
    """Remove configurações antigas de inicialização automática do BotHub."""
    if TERMUX:
        boot_script = Path.home() / ".termux" / "boot" / "00-bothub-start"
        marker = ROOT / ".bothub_termux_boot_ready"
        try:
            boot_script.unlink(missing_ok=True)
            marker.unlink(missing_ok=True)
            print("[BotHub Installer] Configuração antiga do Termux:Boot removida.", flush=True)
        except OSError as exc:
            print("[BotHub Installer] Não consegui remover o script antigo do Termux:Boot:", str(exc)[:160], flush=True)
    if os.name == "nt" or TERMUX or not sys.platform.startswith("linux"):
        return
    service_dirs = []
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        service_dirs.append(Path("/etc/systemd/system"))
    service_dirs.append(Path.home() / ".config" / "systemd" / "user")
    for unit_dir in service_dirs:
        unit_file = unit_dir / "bothub-worker.service"
        if not unit_file.exists():
            continue
        try:
            if Path("/run/systemd/system").exists():
                command = ["systemctl", "disable", "--now", "bothub-worker.service"]
                if unit_dir != Path("/etc/systemd/system"):
                    command.insert(1, "--user")
                subprocess.run(command, capture_output=True, timeout=30)
            unit_file.unlink(missing_ok=True)
            print("[BotHub Installer] Serviço automático antigo do BotHub removido.", flush=True)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print("[BotHub Installer] Não consegui remover o serviço automático antigo:", str(exc)[:160], flush=True)


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

def main():
    if sys.version_info < (3, 10):
        print("ERRO: é necessário Python 3.10 ou superior.")
        return 2
    wake_screen_once()
    update_installer()
    print("[BotHub Installer] Versão:", INSTALLER_VERSION, flush=True)
    ensure_termux_api()
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
    remove_legacy_autostart()
    print("\n[BotHub Installer] Arquivos instalados em:", ROOT)
    print("[BotHub Installer] O worker vai gerar um ID e autenticar sem pedir e-mail/senha.")
    print("[BotHub Installer] Para iniciar novamente:")
    print(" ", str(PYTHON), str(WORKER))
    print("[BotHub Installer] Observação: ative Anonymous em Firebase Authentication > Sign-in method antes da primeira execução.")
    # Quando chamado pelo start.py supervisor, este instalador apenas prepara
    # o ambiente. O supervisor é o único responsável por manter/reiniciar o worker.
    if os.environ.get("BOTHUB_SUPERVISED") == "1":
        print("[BotHub Installer] Modo supervisionado: ambiente pronto; start.py iniciará o worker.", flush=True)
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
