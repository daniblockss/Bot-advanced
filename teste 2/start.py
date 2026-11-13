#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Supervisor permanente do BotHub: mantém start.py vivo e atualiza apenas os workers."""
from __future__ import annotations

import hashlib
import logging
from logging.handlers import RotatingFileHandler
import os
import platform
import signal
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE_URL = "https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/teste%202"
SUPERVISOR_VERSION = "2026.11.13.1"
ROOT = Path(__file__).resolve().parent
LOG_FILE = ROOT / "start.log"
INSTALLER = ROOT / "add_cluster_server.py"
WORKER = ROOT / "bothub_firebase_worker.py"
VENV = ROOT / "venv"
WORKER_PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
SUPERVISOR_POLL_INTERVAL = max(2, int(os.getenv("BOTHUB_SUPERVISOR_POLL_SECONDS", "3")))
RESTART_DELAY = 5
STOP_TIMEOUT = 20

COMPONENTS = (
    {
        "name": "add_cluster_server.py",
        "url": BASE_URL + "/add_cluster_server.py",
        "path": INSTALLER,
        "minimum": 1500,
        "markers": (b"def download()", b"bothub_firebase_worker.py", b"def main()"),
    },
    {
        "name": "bothub_firebase_worker.py",
        "url": BASE_URL + "/bothub_firebase_worker.py",
        "path": WORKER,
        "minimum": 10000,
        "markers": (b"workerTasks/", b"accounts:signUp", b"def main("),
    },
)

def setup_logger():
    ROOT.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("bothub.start")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)
    try:
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as exc:
        logger.error("Não foi possível abrir %s: %s", LOG_FILE, exc)
    return logger

log = setup_logger()
_CPU_WAKELOCK_ACTIVE = False


def termux_command(name: str) -> str | None:
    """Localiza comandos Termux mesmo quando o PATH do processo está incompleto."""
    found = shutil.which(name)
    if found:
        return found
    prefix = os.environ.get("PREFIX", "")
    candidate = Path(prefix) / "bin" / name if prefix else None
    return str(candidate) if candidate and candidate.is_file() else None

def manage_cpu_wakelock(enable: bool) -> None:
    """Altera o wakelock somente quando o estado solicitado difere do estado conhecido."""
    global _CPU_WAKELOCK_ACTIVE
    if not (os.environ.get("PREFIX", "").startswith("/data/data/com.termux")
            or "ANDROID_ROOT" in os.environ):
        return
    if enable and _CPU_WAKELOCK_ACTIVE:
        log.debug("Wakelock já está ativo; nenhuma nova chamada será feita.")
        return
    if not enable and not _CPU_WAKELOCK_ACTIVE:
        log.debug("Wakelock já está liberado; nenhuma nova chamada será feita.")
        return
    command = termux_command("termux-wake-lock" if enable else "termux-wake-unlock")
    if not command:
        log.warning("Comando Termux de wakelock não encontrado; a CPU poderá entrar em suspensão.")
        return
    try:
        result = subprocess.run([command], stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, text=True, timeout=10)
        if result.returncode == 0:
            _CPU_WAKELOCK_ACTIVE = bool(enable)
            log.info("Bloqueio de suspensão da CPU %s.",
                     "ativado" if enable else "liberado")
        else:
            log.warning("Não foi possível %s o wakelock: %s",
                        "ativar" if enable else "liberar",
                        (result.stderr or "").strip()[:160])
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("Falha no comando de wakelock: %s", str(exc)[:160])

def validate(data: bytes, item: dict) -> None:
    if len(data) < item["minimum"]:
        raise RuntimeError(f'{item["name"]}: arquivo incompleto ({len(data)} bytes).')
    missing = [m.decode("ascii", "replace") for m in item["markers"] if m not in data]
    if missing:
        raise RuntimeError(f'{item["name"]}: faltam marcadores: {", ".join(missing)}.')
    try:
        compile(data.decode("utf-8"), item["name"], "exec")
    except Exception as exc:
        raise RuntimeError(f'{item["name"]}: código Python inválido: {exc}') from exc

def fetch_component(item: dict) -> bytes:
    request = urllib.request.Request(
        item["url"] + "?cachebust=" + str(int(time.time())),
        headers={"User-Agent": "BotHub-Start/3.0", "Cache-Control": "no-cache"},
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        data = response.read()
    validate(data, item)
    return data

def install_component(item: dict, data: bytes) -> None:
    validate(data, item)
    temporary = item["path"].with_suffix(item["path"].suffix + ".download")
    try:
        temporary.write_bytes(data)
        validate(temporary.read_bytes(), item)
        temporary.replace(item["path"])
    finally:
        temporary.unlink(missing_ok=True)
    try:
        item["path"].chmod(0o700)
    except OSError:
        pass

def prepare_initial_files() -> None:
    """Valida os arquivos locais; baixa do GitHub somente no primeiro bootstrap."""
    for item in COMPONENTS:
        try:
            validate(item["path"].read_bytes(), item)
            log.info("%s local validado. Atualizações serão aplicadas somente por solicitação no painel.",
                     item["name"])
            continue
        except Exception as local_error:
            log.warning("%s ausente ou inválido (%s); tentando bootstrap pelo GitHub.",
                        item["name"], local_error)

        data = fetch_component(item)
        install_component(item, data)
        log.info("%s baixado no bootstrap (%d bytes; SHA-256 %s).",
                 item["name"], len(data), hashlib.sha256(data).hexdigest())

def stop_worker(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    log.info("Encerrando somente o worker PID %s; start.py continuará ativo.", process.pid)
    process.terminate()
    try:
        process.wait(timeout=STOP_TIMEOUT)
    except subprocess.TimeoutExpired:
        log.warning("Worker não encerrou no prazo; forçando encerramento do PID %s.", process.pid)
        process.kill()
        process.wait(timeout=10)

def start_worker() -> subprocess.Popen:
    if not WORKER_PYTHON.is_file():
        raise RuntimeError(f"Python do ambiente virtual não encontrado: {WORKER_PYTHON}")
    validate(WORKER.read_bytes(), COMPONENTS[1])
    log.info("Iniciando worker com %s.", WORKER_PYTHON)
    worker_env = os.environ.copy()
    # Informa ao atualizador do cluster que este worker já é gerenciado
    # por start.py; assim ele não inicia um segundo supervisor.
    worker_env["BOTHUB_SUPERVISED"] = "1"
    return subprocess.Popen(
        [str(WORKER_PYTHON), "-u", str(WORKER)],
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        stdout=sys.stdout,
        stderr=sys.stderr,
        env=worker_env,
    )

def setup_environment() -> None:
    env = os.environ.copy()
    env["BOTHUB_SUPERVISED"] = "1"
    log.info("Preparando ambiente e dependências pelo instalador (sem iniciar outro worker).")
    result = subprocess.run(
        [sys.executable, str(INSTALLER)],
        cwd=str(ROOT),
        env=env,
        stdin=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Instalador terminou com código {result.returncode}.")
    if not WORKER_PYTHON.is_file():
        raise RuntimeError("O instalador terminou, mas o Python do ambiente virtual não existe.")

def main() -> int:
    log.info("=" * 64)
    log.info("Supervisor BotHub iniciado; start.py permanecerá ativo.")
    log.info("VERSÃO DO SUPERVISOR: %s", SUPERVISOR_VERSION)
    log.info("Python: %s | plataforma: %s | executável: %s",
             sys.version.split()[0], platform.platform(), sys.executable)
    log.info("Diretório: %s | PID: %s | monitoramento do processo: %ss",
             ROOT, os.getpid(), SUPERVISOR_POLL_INTERVAL)
    if sys.version_info < (3, 10):
        log.critical("É necessário Python 3.10 ou superior.")
        return 2

    worker_process = None
    try:
        manage_cpu_wakelock(True)
        prepare_initial_files()
        setup_environment()
        worker_process = start_worker()
        log.info("Worker iniciado. start.py supervisiona a execução e reinicia o worker após atualizações solicitadas no painel.")

        while True:
            # Este monitor só recupera uma queda do processo. Não consulta o GitHub.
            time.sleep(SUPERVISOR_POLL_INTERVAL)
            if worker_process.poll() is not None:
                log.warning("Worker encerrou com código %s. Supervisor reiniciando em %ss.",
                            worker_process.returncode, RESTART_DELAY)
                time.sleep(RESTART_DELAY)
                worker_process = start_worker()
    except KeyboardInterrupt:
        log.info("Encerramento solicitado; finalizando apenas o worker.")
    except Exception:
        log.exception("Falha fatal no supervisor.")
        return 1
    finally:
        stop_worker(worker_process)
        manage_cpu_wakelock(False)
        log.info("Supervisor start.py encerrado.")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
