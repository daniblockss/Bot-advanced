#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bootstrap único do BotHub: recupera os componentes e transfere o processo ao instalador."""
from __future__ import annotations

import hashlib
import logging
from logging.handlers import RotatingFileHandler
import os
import platform
import sys
import time
import urllib.request
from pathlib import Path

BASE_URL = "https://raw.githubusercontent.com/daniblockss/Bot-advanced/teste-2/teste%202"
ROOT = Path(__file__).resolve().parent
LOG_FILE = ROOT / "start.log"
INSTALLER = ROOT / "add_cluster_server.py"
WORKER = ROOT / "bothub_firebase_worker.py"

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
    logger.setLevel(logging.DEBUG)
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
    missing = [marker.decode("ascii", "replace") for marker in item["markers"] if marker not in data]
    if missing:
        raise RuntimeError(f'{item["name"]}: validação falhou; faltam marcadores: {", ".join(missing)}.')
    try:
        compile(data.decode("utf-8"), item["name"], "exec")
    except Exception as exc:
        raise RuntimeError(f'{item["name"]}: código Python inválido: {exc}') from exc

def download_component(item: dict) -> None:
    log.info("Verificando %s no GitHub.", item["name"])
    request = urllib.request.Request(
        item["url"] + "?cachebust=" + str(int(time.time())),
        headers={"User-Agent": "BotHub-Start/2.0", "Cache-Control": "no-cache"},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
            status = getattr(response, "status", "desconhecido")
        validate(data, item)
        log.info("Download de %s: HTTP %s, %d bytes, %.2fs, SHA-256 %s.",
                 item["name"], status, len(data), time.monotonic() - started,
                 hashlib.sha256(data).hexdigest())
        try:
            current = item["path"].read_bytes()
        except OSError:
            current = b""
        if current == data:
            log.info("%s já está atualizado.", item["name"])
            return
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
        log.info("%s foi atualizado com sucesso.", item["name"])
    except Exception as download_error:
        log.exception("Falha ao baixar/validar %s.", item["name"])
        try:
            local = item["path"].read_bytes()
            validate(local, item)
        except Exception as local_error:
            raise RuntimeError(
                f'{item["name"]} não pôde ser baixado e não existe uma cópia local válida. '
                "Inicialização cancelada para evitar executar um arquivo ausente/corrompido. "
                f"Download: {download_error}; cópia local: {local_error}"
            ) from download_error
        log.warning("Usando a cópia local validada de %s; ela pode estar desatualizada.",
                    item["name"])

def main() -> int:
    log.info("=" * 64)
    log.info("Inicialização BotHub pelo único ponto de entrada start.py.")
    log.info("Python: %s | plataforma: %s | executável: %s",
             sys.version.split()[0], platform.platform(), sys.executable)
    log.info("Diretório: %s | PID: %s | log: %s", ROOT, os.getpid(), LOG_FILE)
    if sys.version_info < (3, 10):
        log.critical("É necessário Python 3.10 ou superior.")
        return 2

    try:
        for item in COMPONENTS:
            download_component(item)
    except Exception:
        log.exception("Não foi possível preparar os arquivos necessários. Inicialização cancelada.")
        return 1

    if not INSTALLER.is_file():
        log.critical("O instalador não existe após a verificação. Inicialização cancelada.")
        return 1

    log.info("Preparação concluída. Substituindo este processo pelo instalador: %s", INSTALLER)
    # execv substitui o processo do start.py; não deixa um start.py extra rodando.
    try:
        os.execv(sys.executable, [sys.executable, str(INSTALLER)])
    except Exception:
        log.exception("Não foi possível executar o instalador.")
        return 1
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log.warning("Inicialização interrompida pelo usuário.")
        raise SystemExit(130)
    except Exception:
        log.exception("Falha fatal no start.py.")
        raise SystemExit(1)
