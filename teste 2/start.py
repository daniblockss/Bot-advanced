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
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE_URL = "https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/teste%202"
ROOT = Path(__file__).resolve().parent
LOG_FILE = ROOT / "start.log"
INSTALLER = ROOT / "add_cluster_server.py"
WORKER = ROOT / "bothub_firebase_worker.py"
VENV = ROOT / "venv"
WORKER_PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
CHECK_INTERVAL = max(30, int(os.getenv("BOTHUB_UPDATE_INTERVAL", "60")))
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
    for item in COMPONENTS:
        log.info("Preparando %s pelo GitHub.", item["name"])
        try:
            data = fetch_component(item)
            current = item["path"].read_bytes() if item["path"].is_file() else b""
            if current != data:
                install_component(item, data)
                log.info("%s baixado/atualizado (%d bytes; SHA-256 %s).",
                         item["name"], len(data), hashlib.sha256(data).hexdigest())
            else:
                log.info("%s já está na versão atual.", item["name"])
        except Exception as download_error:
            log.exception("Falha ao preparar %s.", item["name"])
            try:
                validate(item["path"].read_bytes(), item)
            except Exception as local_error:
                raise RuntimeError(
                    f'{item["name"]} não pôde ser baixado e não há cópia local válida. '
                    f"Download: {download_error}; cópia local: {local_error}"
                ) from download_error
            log.warning("Usando a cópia local validada de %s.", item["name"])

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
    return subprocess.Popen(
        [str(WORKER_PYTHON), "-u", str(WORKER)],
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        stdout=sys.stdout,
        stderr=sys.stderr,
        env=os.environ.copy(),
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

def check_for_updates(process: subprocess.Popen) -> subprocess.Popen:
    # Primeiro baixa e valida tudo. Se a rede falhar, o worker atual continua funcionando.
    updates = []
    for item in COMPONENTS:
        latest = fetch_component(item)
        current = item["path"].read_bytes() if item["path"].is_file() else b""
        if latest != current:
            updates.append((item, latest))

    if not updates:
        log.info("Verificação concluída: scripts do worker já estão atualizados.")
        return process

    log.info("Nova versão detectada: %s.", ", ".join(item["name"] for item, _ in updates))
    stop_worker(process)
    try:
        for item, data in updates:
            # O arquivo antigo só é substituído depois de a versão nova ser baixada e validada.
            install_component(item, data)
            log.info("%s atualizado (%d bytes; SHA-256 %s).",
                     item["name"], len(data), hashlib.sha256(data).hexdigest())
        log.info("Atualização concluída. Reiniciando o worker; start.py permanece ligado.")
        return start_worker()
    except Exception:
        log.exception("Falha ao aplicar atualização; tentando iniciar a cópia local validada.")
        try:
            return start_worker()
        except Exception:
            log.exception("Não foi possível iniciar o worker após a atualização.")
            raise

def main() -> int:
    log.info("=" * 64)
    log.info("Supervisor BotHub iniciado; start.py permanecerá ativo.")
    log.info("Python: %s | plataforma: %s | executável: %s",
             sys.version.split()[0], platform.platform(), sys.executable)
    log.info("Diretório: %s | PID: %s | verificação: %ss",
             ROOT, os.getpid(), CHECK_INTERVAL)
    if sys.version_info < (3, 10):
        log.critical("É necessário Python 3.10 ou superior.")
        return 2

    worker_process = None
    try:
        prepare_initial_files()
        setup_environment()
        worker_process = start_worker()
        log.info("Worker iniciado. O supervisor verificará atualizações periodicamente.")

        while True:
            time.sleep(CHECK_INTERVAL)
            if worker_process.poll() is not None:
                exit_code = worker_process.returncode
                if exit_code == 75:
                    log.error(
                        "Outro controlador mantém o bloqueio do BotHub. "
                        "O supervisor vai parar aqui para evitar um ciclo infinito de reinicializações. "
                        "Verifique se existe um serviço antigo bothub-worker.service ou outro start.py ativo."
                    )
                    return 75
                if exit_code == 0:
                    log.warning(
                        "Worker encerrou normalmente (código 0), geralmente após atualização. "
                        "O supervisor iniciará uma nova instância em %ss.",
                        RESTART_DELAY,
                    )
                else:
                    log.warning("Worker encerrou com código %s. Reiniciando em %ss.",
                                exit_code, RESTART_DELAY)
                time.sleep(RESTART_DELAY)
                worker_process = start_worker()
                continue
            try:
                worker_process = check_for_updates(worker_process)
            except Exception:
                log.exception("Não foi possível verificar/aplicar atualização. O supervisor continuará ativo.")
                if worker_process.poll() is not None:
                    time.sleep(RESTART_DELAY)
                    worker_process = start_worker()
    except KeyboardInterrupt:
        log.info("Encerramento solicitado; finalizando apenas o worker.")
    except Exception:
        log.exception("Falha fatal no supervisor.")
        return 1
    finally:
        stop_worker(worker_process)
        log.info("Supervisor start.py encerrado.")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
