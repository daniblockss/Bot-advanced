#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Instalador BotHub: instala e inicia o worker na pasta atual."""
from __future__ import annotations
import os, platform, shutil, subprocess, sys, urllib.request, shlex, time, json, zipfile, io
from pathlib import Path

INSTALLER_VERSION = "2026.11.12.5"
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


def termux_package_installed(package_name):
    """Detecta o pacote usando os comandos Android disponíveis no Termux."""
    commands = []
    for binary in (shutil.which("cmd"), "/system/bin/cmd",
                   shutil.which("pm"), "/system/bin/pm"):
        if binary and Path(binary).exists():
            commands.append([binary, "package", "path", package_name]
                            if Path(binary).name == "cmd"
                            else [binary, "path", package_name])
    for command in commands:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=12)
            output = (result.stdout or "") + "\\n" + (result.stderr or "")
            if result.returncode == 0 and "package:" in output:
                return True
        except (OSError, subprocess.TimeoutExpired):
            continue
    return False


def latest_termux_boot_apk():
    """Obtém o APK mais recente diretamente da página oficial de releases."""
    api = "https://api.github.com/repos/termux/termux-boot/releases/latest"
    request = urllib.request.Request(
        api, headers={"User-Agent": "BotHub-TermuxBoot-Installer/1.0",
                      "Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.loads(response.read().decode("utf-8"))
    assets = release.get("assets") or []
    apk_asset = next((a for a in assets if str(a.get("name", "")).lower().endswith(".apk")), None)
    if not apk_asset or not apk_asset.get("browser_download_url"):
        raise RuntimeError("A release oficial do Termux:Boot não contém APK disponível.")
    return apk_asset["browser_download_url"], apk_asset.get("name", "termux-boot.apk")


def download_termux_boot_apk(apk_path):
    url, filename = latest_termux_boot_apk()
    print("[BotHub Installer] Baixando APK oficial mais recente do Termux:Boot:", filename, flush=True)
    request = urllib.request.Request(
        url, headers={"User-Agent": "BotHub-TermuxBoot-Installer/1.0",
                      "Cache-Control": "no-cache"}
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        data = response.read()
    if len(data) < 10000:
        raise RuntimeError("O APK baixado está vazio ou incompleto.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as apk_zip:
            if apk_zip.testzip() is not None:
                raise RuntimeError("O arquivo APK está corrompido.")
            names = apk_zip.namelist()
            if "AndroidManifest.xml" not in names:
                raise RuntimeError("O download não parece ser um APK Android válido.")
    except zipfile.BadZipFile as exc:
        raise RuntimeError("O arquivo recebido não é um APK válido (download HTML ou corrompido).") from exc
    temporary = apk_path.with_suffix(".apk.tmp")
    temporary.write_bytes(data)
    temporary.replace(apk_path)
    return apk_path


def open_android_uninstall(package_name):
    """Abre a tela oficial de desinstalação; o Android exige confirmação do usuário."""
    am = shutil.which("am") or "/system/bin/am"
    try:
        result = subprocess.run(
            [am, "start", "-a", "android.intent.action.DELETE",
             "-d", "package:" + package_name],
            capture_output=True, text=True, timeout=15
        )
        print("[BotHub Installer] Solicitação para abrir a desinstalação no Android enviada.",
              flush=True)
        if result.returncode != 0:
            print("[BotHub Installer] O Android não abriu a tela automaticamente:",
                  (result.stderr or result.stdout or "")[:180], flush=True)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        print("[BotHub Installer] Não consegui abrir a desinstalação:", str(exc)[:160], flush=True)
        return False


def wait_for_termux_boot(expected, seconds=180):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if termux_package_installed("com.termux.boot") == expected:
            return True
        time.sleep(3)
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
    """Instala/repara Termux:Boot e configura start.py no boot do Android."""
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

        apk_dir = ROOT / "downloads"
        apk_dir.mkdir(parents=True, exist_ok=True)
        apk = apk_dir / "termux-boot.apk"
        opener = shutil.which("termux-open")
        if not opener:
            raise RuntimeError("termux-open não está disponível para abrir o instalador Android.")

        installed = False
        for attempt in (1, 2):
            try:
                # Baixa sempre uma cópia nova e valida a estrutura ZIP do APK.
                apk.unlink(missing_ok=True)
                download_termux_boot_apk(apk)
                print("[BotHub Installer] Abra a instalação e confirme Termux:Boot no Android.",
                      flush=True)
                subprocess.Popen([opener, str(apk)])
                print("[BotHub Installer] Aguardando o Android concluir a instalação (até 3 minutos)...",
                      flush=True)
                if wait_for_termux_boot(True, 180):
                    installed = True
                    print("[BotHub Installer] Termux:Boot instalado e detectado.", flush=True)
                    break
                raise RuntimeError("O Android não confirmou a instalação dentro do prazo.")
            except Exception as exc:
                print(f"[BotHub Installer] Tentativa {attempt}/2 falhou: {str(exc)[:220]}",
                      flush=True)
                if attempt == 1:
                    # Se uma instalação parcial/antiga existir, abre a tela de remoção.
                    if termux_package_installed("com.termux.boot"):
                        open_android_uninstall("com.termux.boot")
                        print("[BotHub Installer] Confirme a desinstalação do Termux:Boot, se solicitada.",
                              flush=True)
                        wait_for_termux_boot(False, 120)
                    apk.unlink(missing_ok=True)
                    print("[BotHub Installer] Limpando o APK anterior e tentando baixar novamente...",
                          flush=True)
                else:
                    raise RuntimeError(
                        "Não foi possível instalar Termux:Boot após baixar novamente. "
                        "Confira a confirmação do Android e execute start.py outra vez."
                    ) from exc

        if not installed:
            raise RuntimeError("Termux:Boot não foi instalado.")

    # O primeiro lançamento habilita o receptor de boot do complemento.
    if not marker.exists():
        monkey = shutil.which("monkey") or "/system/bin/monkey"
        try:
            subprocess.run([monkey, "-p", "com.termux.boot", "1"],
                           capture_output=True, text=True, timeout=15)
            time.sleep(2)
        except (OSError, subprocess.TimeoutExpired):
            print("[BotHub Installer] Abra Termux:Boot uma vez manualmente para ativar o boot.",
                  flush=True)

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
    print("[BotHub Installer] Inicialização automática configurada: start.py será executado após o boot do Android.",
          flush=True)
    print("[BotHub Installer] Mantenha Termux e Termux:Boot liberados das restrições de bateria do Android.",
          flush=True)
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
