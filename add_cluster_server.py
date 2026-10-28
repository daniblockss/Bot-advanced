#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Instalador BotHub P2P. Cria start.py na pasta atual e inicia o cluster."""
from __future__ import annotations

import os
import secrets
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path.cwd().resolve()
VENV = ROOT / "venv"
CLUSTER = ROOT / "bothub_cluster.py"
START = ROOT / "start.py"
CLUSTER_URL = "https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/bothub_cluster.py"

START_TEMPLATE = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inicializador do nó BotHub P2P com registro e descoberta pelo Firebase."""
from __future__ import annotations
import json, os, secrets, subprocess, sys, time, socket, urllib.parse, urllib.request, threading
from pathlib import Path
from getpass import getpass

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "cluster_config.json"
CLUSTER = ROOT / "bothub_cluster.py"
PYTHON = ROOT / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
API_KEY = "AIzaSyDS_KvyPWGgzYqIVgkagw5DAwzlenNZtiE"
DB = "https://bothub-bca02-default-rtdb.firebaseio.com"
PORT = int(os.getenv("BOTHUB_CLUSTER_PORT", "47800"))
_session = {"token": "", "expires": 0, "uid": ""}

def write_config(cfg):
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try: tmp.chmod(0o600)
    except OSError: pass
    tmp.replace(CONFIG)

def auth(force=False):
    if not force and _session["token"] and time.time() < _session["expires"] - 120:
        return _session["token"], _session["uid"]
    body = json.dumps({"email": CFG["firebase_email"], "password": CFG["firebase_password"], "returnSecureToken": True}).encode()
    req = urllib.request.Request("https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=" + API_KEY, data=body, headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r: data = json.loads(r.read().decode())
    _session.update(token=data["idToken"], uid=data["localId"], expires=time.time()+int(data.get("expiresIn",3600)))
    return _session["token"], _session["uid"]

def fb(method, path, token, payload=None):
    url = DB + "/" + path.strip("/") + ".json?auth=" + urllib.parse.quote(token, safe="")
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type":"application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
        return json.loads(raw.decode()) if raw else None

def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()

def public_ip():
    try:
        req = urllib.request.Request("https://api.ipify.org?format=json", headers={"User-Agent":"BotHub-P2P/1.0"})
        with urllib.request.urlopen(req, timeout=5) as r: return json.loads(r.read().decode()).get("ip", "")
    except Exception:
        return ""

def register_server(cfg):
    token, uid = auth()
    servers = fb("GET", "clusterServers", token) or {}
    node = cfg.get("node_id", "")
    if not node or (node not in servers and cfg.get("firebase_uid") not in ("", uid)):
        node = ""
    if not node:
        for _ in range(12):
            candidate = "server-" + secrets.token_hex(4)
            if candidate not in servers:
                node = candidate
                break
        if not node: raise RuntimeError("Não consegui gerar um ID livre no Firebase; tente novamente.")
    ip = local_ip()
    pub = public_ip()
    url = ("http://" + pub + ":" + str(PORT)) if pub else ("http://" + ip + ":" + str(PORT))
    now = int(time.time() * 1000)
    entry = {
        "uid": uid, "node_id": node, "hostname": socket.gethostname(),
        "platform": sys.platform, "url": url, "local_url": "http://" + ip + ":" + str(PORT),
        "public_ip": pub, "local_ip": ip, "port": PORT,
        "created_at": int((servers.get(node) or {}).get("created_at", now)),
        "last_seen": now, "status": "online"
    }
    if node not in servers:
        fb("PUT", "clusterServers/" + node, token, entry)
    else:
        if str((servers[node] or {}).get("uid", "")) != uid:
            raise RuntimeError("Este ID já pertence a outra conta Firebase; gere outro ID.")
        fb("PUT", "clusterServers/" + node + "/last_seen", token, now)
        fb("PUT", "clusterServers/" + node + "/status", token, "online")
        fb("PUT", "clusterServers/" + node + "/url", token, url)
    cfg["node_id"] = node
    cfg["firebase_uid"] = uid
    write_config(cfg)
    print("[BotHub] ID automático registrado no Firebase:", node)
    print("[BotHub] Endereço anunciado:", url)
    if pub:
        print("[BotHub] Para conexões pela internet, a porta", PORT, "precisa estar acessível/encaminhada no roteador ou hospedagem.")
    return token

def heartbeat_loop(node):
    while True:
        try:
            token, _ = auth()
            now = int(time.time() * 1000)
            fb("PUT", "clusterServers/" + node + "/last_seen", token, now)
            fb("PUT", "clusterServers/" + node + "/status", token, "online")
        except Exception as e:
            print("[BotHub] Aviso: heartbeat Firebase:", str(e)[:160], flush=True)
        time.sleep(15)

def main():
    global CFG
    if not CLUSTER.exists():
        print("[BotHub] Não encontrei bothub_cluster.py na pasta:", ROOT)
        return 2
    CFG = {}
    if CONFIG.exists():
        try: CFG = json.loads(CONFIG.read_text(encoding="utf-8"))
        except Exception: CFG = {}
    if not CFG.get("secret") or not CFG.get("admin_token") or not CFG.get("firebase_email") or not CFG.get("firebase_password"):
        print("\n=== Configuração inicial do nó BotHub P2P ===")
        print("Cada servidor deve usar uma conta Firebase própria, com Email/Senha ativado.")
        email = input("E-mail da conta Firebase deste servidor: ").strip()
        password = getpass("Senha Firebase: ").strip()
        secret = getpass("Segredo compartilhado do cluster (mínimo 32 caracteres; igual em todos os nós): ").strip()
        if not email or not password or len(secret) < 32:
            print("[BotHub] E-mail/senha inválidos ou segredo curto.")
            return 2
        CFG = {"firebase_email":email, "firebase_password":password, "secret":secret, "admin_token":secrets.token_urlsafe(32), "peers":{}}
        try:
            auth(force=True)
        except Exception as e:
            print("[BotHub] Falha no login Firebase. Confira usuário, senha e Email/Password habilitado:", str(e)[:220])
            return 2
        print("[BotHub] Token administrativo local (guarde-o):")
        print(CFG["admin_token"])
    try:
        auth()
        register_server(CFG)
    except Exception as e:
        print("\n[BotHub] Não consegui registrar no Firebase:", str(e)[:300])
        print("[BotHub] Confira as regras de firebase_database.rules.json e a conta Firebase.")
        return 2
    write_config(CFG)
    env = os.environ.copy()
    env.update({
        "BOTHUB_CLUSTER_HOME": str(ROOT),
        "BOTHUB_NODE_ID": CFG["node_id"],
        "BOTHUB_CLUSTER_SECRET": CFG["secret"],
        "BOTHUB_ADMIN_TOKEN": CFG["admin_token"],
        "BOTHUB_CLUSTER_PEERS_JSON": json.dumps(CFG.get("peers", {})),
        "BOTHUB_FIREBASE_EMAIL": CFG["firebase_email"],
        "BOTHUB_FIREBASE_PASSWORD": CFG["firebase_password"],
        "BOTHUB_FIREBASE_API_KEY": API_KEY,
        "BOTHUB_FIREBASE_DB": DB,
    })
    print("\n[BotHub] Iniciando nó", CFG["node_id"], "na pasta", ROOT)
    if len(sys.argv) > 1 and sys.argv[1] == "admin":
        return subprocess.call([str(PYTHON), str(CLUSTER), "admin"], cwd=str(ROOT), env=env)
    threading.Thread(target=heartbeat_loop, args=(CFG["node_id"],), daemon=True).start()
    proc = subprocess.Popen([str(PYTHON), str(CLUSTER)], cwd=str(ROOT), env=env)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try: proc.wait(timeout=6)
        except Exception: proc.kill()
        return 130

if __name__ == "__main__":
    raise SystemExit(main())
'''

def run(args: list[str], check: bool = True):
    print("\n[BotHub] $", " ".join(map(str, args)), flush=True)
    return subprocess.run(args, check=check, cwd=str(ROOT))

def download(url: str, destination: Path):
    print("[BotHub] Baixando", destination.name, "...", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "BotHub-P2P-Installer/1.0"})
    with urllib.request.urlopen(req, timeout=45) as response:
        data = response.read()
    if len(data) < 1000:
        raise RuntimeError("O arquivo baixado parece incompleto; nada será iniciado.")
    destination.write_bytes(data)
    try: destination.chmod(0o700)
    except OSError: pass

def main():
    if sys.version_info < (3, 10):
        print("[BotHub] ERRO: Python 3.10 ou superior é necessário.")
        return 2
    if START.exists():
        answer = input("[BotHub] start.py já existe. Substituir? [s/N] ").strip().lower()
        if answer != "s":
            print("[BotHub] Instalação cancelada para preservar o start.py existente.")
            return 1
    venv_python = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    run([sys.executable, "-m", "venv", str(VENV)], check=False)
    if not venv_python.exists():
        print("[BotHub] Não consegui criar o ambiente virtual. Em Debian/Ubuntu: sudo apt install python3-venv")
        return 2
    run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(venv_python), "-m", "pip", "install", "--upgrade", "discord.py", "aiohttp", "requests"])
    download(CLUSTER_URL, CLUSTER)
    START.write_text(START_TEMPLATE, encoding="utf-8")
    try: START.chmod(0o700)
    except OSError: pass
    print("\n[BotHub] Arquivos preparados em:", ROOT)
    print("[BotHub] O instalador vai se apagar e executar start.py.")
    installer = Path(__file__).resolve()
    try:
        installer.unlink()
    except OSError as exc:
        print("[BotHub] Aviso: não consegui apagar o instalador:", exc)
    os.execv(str(venv_python), [str(venv_python), str(START)])

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[BotHub] Operação cancelada.")
        raise SystemExit(130)
    except Exception as exc:
        print("\n[BotHub] ERRO:", exc, file=sys.stderr)
        print("[BotHub] O instalador não será apagado se a preparação falhar.", file=sys.stderr)
        raise SystemExit(1)
