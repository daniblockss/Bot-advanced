#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Instalador BotHub: instala e inicia o worker na pasta atual."""
from __future__ import annotations
import os, platform, shutil, subprocess, sys, urllib.request, shlex, time
from pathlib import Path

INSTALLER_VERSION = "2026.11.12.3"
GITHUB_RAW = "https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/teste%202"
INSTALLER_URL = GITHUB_RAW + "/add_cluster_server.py"
WORKER_URL = GITHUB_RAW + "/bothub_firebase_worker.py"
ROOT = Path(__file__).resolve().parent
WORKER = ROOT / "bothub_firebase_worker.py"
START_SCRIPT = ROOT / "start.py"
VENV = ROOT / "venv"
PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
TERMUX = "com.termux" in str(Path.home()).lower() or "ANDROID_ROOT" in os.environ

def run(args):
    print("\n[BotHub Installer] $", " ".join(map(str, args)), flush=True)
    subprocess.check_call(args)

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


def termux_package_installed(package_name):
    """Consulta o gerenciador de pacotes Android sem depender de permissões root."""
    commands = [
        ["/system/bin/pm", "path", package_name],
        ["pm", "path", package_name],
        ["cmd", "package", "path", package_name],
    ]
    for command in commands:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=8)
            if result.returncode == 0 and "package:" in (result.stdout or ""):
                return True
        except (OSError, subprocess.TimeoutExpired):
            continue
    return False


def remove_termux_boot_script():
    boot_script = Path.home() / ".termux" / "boot" / "00-bothub-start"
    marker = ROOT / ".bothub_termux_boot_ready"
    try:
        boot_script.unlink(missing_ok=True)
        marker.unlink(missing_ok=True)
        print("[BotHub Installer] start.py não existe; configuração automática de boot removida.", flush=True)
    except OSError as exc:
        print("[BotHub Installer] Não foi possível remover a configuração antiga de boot:", str(exc)[:160], flush=True)


def configure_termux_boot():
    """Instala Termux:Boot com confirmação humana e configura start.py no boot."""
    if not TERMUX:
        return False

    boot_dir = Path.home() / ".termux" / "boot"
    boot_script = boot_dir / "00-bothub-start"
    marker = ROOT / ".bothub_termux_boot_ready"
    if not START_SCRIPT.is_file():
        remove_termux_boot_script()
        return False

    if not termux_package_installed("com.termux.boot"):
        pkg = shutil.which("pkg")
        if not pkg:
            raise RuntimeError("Termux:Boot não está instalado e o comando pkg não está disponível.")
        curl = shutil.which("curl")
        if not curl:
            print("[BotHub Installer] Instalando curl para baixar o Termux:Boot...", flush=True)
            subprocess.check_call([pkg, "install", "-y", "curl"])
            curl = shutil.which("curl")
        if not curl:
            raise RuntimeError("Não foi possível localizar curl após a instalação.")

        apk_dir = ROOT / "downloads"
        apk_dir.mkdir(parents=True, exist_ok=True)
        apk = apk_dir / "termux-boot.apk"
        apk_url = "https://f-droid.org/repo/com.termux.boot_1000.apk"
        print("[BotHub Installer] Baixando Termux:Boot oficial do F-Droid com curl...", flush=True)
        subprocess.check_call([
            curl, "-fL", "--retry", "3", "--connect-timeout", "20",
            apk_url, "-o", str(apk)
        ])
        if not apk.is_file() or apk.stat().st_size < 10000 or apk.read_bytes()[:2] != b"PK":
            raise RuntimeError("O APK baixado não passou na verificação básica; instalação cancelada.")

        opener = shutil.which("termux-open")
        if not opener:
            raise RuntimeError("termux-open não está disponível para abrir o instalador Android.")
        print("[BotHub Installer] APK pronto. Confirme a instalação na tela do Android.", flush=True)
        subprocess.Popen([opener, str(apk)])

        print("[BotHub Installer] Aguardando você confirmar a instalação do Termux:Boot (até 10 minutos)...", flush=True)
        deadline = time.time() + 600
        while time.time() < deadline:
            if termux_package_installed("com.termux.boot"):
                print("[BotHub Installer] Termux:Boot instalado. Continuando a configuração...", flush=True)
                break
            time.sleep(3)
        else:
            raise RuntimeError(
                "O Termux:Boot ainda não foi detectado. Confirme a instalação e execute start.py novamente."
            )

    # O primeiro lançamento é necessário para habilitar o receptor de boot do complemento.
    if not marker.exists():
        monkey = shutil.which("monkey") or "/system/bin/monkey"
        try:
            subprocess.run([monkey, "-p", "com.termux.boot", "1"],
                           capture_output=True, text=True, timeout=15)
            time.sleep(2)
        except (OSError, subprocess.TimeoutExpired):
            print("[BotHub Installer] Abra o aplicativo Termux:Boot uma vez manualmente para ativar o boot.", flush=True)

    boot_dir.mkdir(parents=True, exist_ok=True)
    python_bin = shlex.quote(str(Path(sys.executable).resolve()))
    root_dir = shlex.quote(str(ROOT.resolve()))
    start_file = shlex.quote(str(START_SCRIPT.resolve()))
    script = (
        "#!/data/data/com.termux/files/usr/bin/sh\n"
        "# BotHub autostart - gerado automaticamente pelo instalador\n"
        "ROOT=" + root_dir + "\n"
        "START=" + start_file + "\n"
        "PYTHON=" + python_bin + "\n"
        'if [ ! -f "$START" ]; then\n'
        '  rm -f "$0"\n'
        '  exit 0\n'
        "fi\n"
        'cd "$ROOT" || exit 1\n'
        "termux-wake-lock >/dev/null 2>&1 || true\n"
        'exec "$PYTHON" "$START" >> "$ROOT/start.log" 2>&1\n'
    )
    temporary = boot_script.with_suffix(".tmp")
    temporary.write_text(script, encoding="utf-8")
    temporary.replace(boot_script)
    boot_script.chmod(0o700)
    boot_dir.chmod(0o700)
    marker.write_text(INSTALLER_VERSION, encoding="utf-8")
    print("[BotHub Installer] Inicialização automática configurada: start.py será executado após o boot do Android.", flush=True)
    print("[BotHub Installer] Termux:Boot precisa permanecer instalado; mantenha Termux e Termux:Boot liberados das restrições de bateria do Android.", flush=True)
    return True


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
        wanted_by = "multi-user.target" if os.geteuid() == 0 else "default.target"
        unit_file.write_text(
            "[Unit]\n"
            "Description=BotHub persistent worker\n"
            "After=network-online.target\n"
            "Wants=network-online.target\n\n"
            "[Service]\n"
            "Type=simple\n"
            "WorkingDirectory=\"" + str(ROOT).replace("\\\\", "\\\\\\\\").replace("\"", "\\\\\"") + "\"\n"
            "ExecStart=\"" + str(PYTHON).replace("\\\\", "\\\\\\\\").replace("\"", "\\\\\"") + "\" \"" + str(WORKER).replace("\\\\", "\\\\\\\\").replace("\"", "\\\\\"") + "\"\n"
            "Restart=always\n"
            "RestartSec=5\n"
            "KillMode=mixed\n"
            "TimeoutStopSec=15\n\n"
            "[Install]\n"
            "WantedBy=" + wanted_by + "\n",
            encoding="utf-8",
        )
        if os.geteuid() == 0:
            subprocess.run(["systemctl", "daemon-reload"], check=True, timeout=30)
            subprocess.run(["systemctl", "enable", "--now", "bothub-worker.service"], check=True, timeout=45)
        else:
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, timeout=30)
            subprocess.run(["systemctl", "--user", "enable", "--now", "bothub-worker.service"], check=True, timeout=45)
            try:
                subprocess.run(["loginctl", "enable-linger", __import__("getpass").getuser()], check=True, timeout=15)
            except Exception:
                print("[BotHub Installer] Atenção: o host não permitiu habilitar linger; confirme com o administrador se o serviço inicia após reboot.")
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
    if TERMUX:
        configure_termux_boot()
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
