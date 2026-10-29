#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BOT_HUB_SERVER_BOOTSTRAP: atualiza os componentes do servidor e inicia o instalador."""
from __future__ import annotations
import hashlib
import logging
import os
import platform
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "https://raw.githubusercontent.com/daniblockss/Bot-advanced/teste-2/teste%202"
ROOT = Path(__file__).resolve().parent
INSTALLER = ROOT / "add_cluster_server.py"
WORKER = ROOT / "bothub_firebase_worker.py"
LOG_FILE = ROOT / "server.log"

def configurar_logs():
    ROOT.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("bothub.server")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG)
    console.setFormatter(fmt)
    logger.addHandler(console)
    try:
        arquivo = logging.FileHandler(LOG_FILE, encoding="utf-8")
        arquivo.setLevel(logging.DEBUG)
        arquivo.setFormatter(fmt)
        logger.addHandler(arquivo)
    except Exception as exc:
        logger.error("Não consegui abrir o arquivo de log %s: %s", LOG_FILE, exc)
    logger.propagate = False
    return logger

log = configurar_logs()

def log_excecao_global(tipo, valor, tb):
    if issubclass(tipo, KeyboardInterrupt):
        log.warning("Interrupção solicitada pelo teclado.")
        return
    log.critical("Erro não tratado; traceback completo abaixo.", exc_info=(tipo, valor, tb))

sys.excepthook = log_excecao_global

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

def baixar_componente(item):
    log.info("Verificando atualização de %s em %s", item["name"], item["url"])
    req = urllib.request.Request(
        item["url"] + "?cachebust=" + str(int(time.time())),
        headers={"User-Agent": "BotHub-Server/1.1", "Cache-Control": "no-cache"},
    )
    inicio = time.monotonic()
    with urllib.request.urlopen(req, timeout=60) as response:
        data = response.read()
        status_http = getattr(response, "status", "desconhecido")
    log.debug("Download de %s terminou: HTTP %s, %d bytes, %.2fs",
              item["name"], status_http, len(data), time.monotonic() - inicio)
    if len(data) < item["minimum"] or not all(marker in data for marker in item["markers"]):
        raise RuntimeError(item["name"] + " baixado não passou na verificação de tamanho/marcadores.")
    try:
        compile(data.decode("utf-8"), item["name"], "exec")
    except Exception as exc:
        raise RuntimeError("O código baixado de " + item["name"] + " não compila: " + str(exc)) from exc
    atual = b""
    try:
        atual = item["path"].read_bytes()
    except OSError:
        pass
    if atual == data:
        log.info("%s já está atualizado (sha256=%s).", item["name"], hashlib.sha256(data).hexdigest())
        return
    tmp = item["path"].with_suffix(item["path"].suffix + ".download")
    try:
        tmp.write_bytes(data)
        validado = tmp.read_bytes()
        if len(validado) < item["minimum"] or not all(marker in validado for marker in item["markers"]):
            raise RuntimeError("Falha na validação temporária de " + item["name"])
        compile(validado.decode("utf-8"), item["name"], "exec")
        tmp.replace(item["path"])
        try:
            item["path"].chmod(0o700)
        except OSError:
            log.debug("Não foi possível alterar permissões de %s; seguindo.", item["path"], exc_info=True)
        log.info("%s atualizado com sucesso (sha256=%s).",
                 item["name"], hashlib.sha256(data).hexdigest())
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            log.warning("Não consegui remover o arquivo temporário %s.", tmp, exc_info=True)

def main():
    log.info("=" * 72)
    log.info("Inicialização do controlador BotHub")
    log.info("Versão do Python: %s", sys.version.replace("\\n", " "))
    log.info("Sistema: %s | plataforma: %s | executável: %s",
             platform.platform(), sys.platform, sys.executable)
    log.info("Diretório de trabalho: %s", ROOT)
    log.info("Arquivo de log detalhado: %s", LOG_FILE)
    log.info("PID: %s", os.getpid())

    if sys.version_info < (3, 10):
        log.critical("Python 3.10 ou superior é obrigatório; versão atual: %s", sys.version)
        return 2

    ROOT.mkdir(parents=True, exist_ok=True)
    falhas = []
    for item in COMPONENTS:
        try:
            baixar_componente(item)
        except Exception as exc:
            falhas.append((item, exc))
            log.exception("FALHA ao atualizar %s. O traceback abaixo contém os detalhes.", item["name"])
            if not item["path"].exists():
                log.critical("%s não existe localmente; não há cópia válida para usar. Inicialização cancelada.",
                             item["name"])
                return 1
            log.warning("Será usada a cópia local existente de %s. Ela pode estar desatualizada.",
                        item["name"])

    if falhas:
        log.warning("Resumo: %d componente(s) falharam na atualização: %s",
                    len(falhas), ", ".join(item["name"] for item, _ in falhas))
        log.warning("Verifique conexão com a internet, acesso ao GitHub e o arquivo %s.", LOG_FILE)
    else:
        log.info("Todos os componentes passaram pela verificação.")

    log.info("Transferindo execução para %s.", INSTALLER)
    log.info("As mensagens seguintes serão geradas pelo add_cluster_server.py e pelo worker.")
    try:
        os.execv(sys.executable, [sys.executable, str(INSTALLER)])
    except Exception:
        log.exception("Não foi possível iniciar o instalador %s.", INSTALLER)
        return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log.warning("Inicialização interrompida pelo usuário (Ctrl+C).")
        raise SystemExit(130)
    except Exception:
        log.exception("Falha fatal no server.py.")
        raise SystemExit(1)
