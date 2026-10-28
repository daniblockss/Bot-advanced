#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BotHub peer cluster: LAN task replication, majority leases and private local admin.

All trusted nodes share BOTHUB_CLUSTER_SECRET and discover members through the Firebase registry.
This is a small-cluster implementation, not a substitute for a mature consensus system.
Keep clocks synchronized. Every node stores replicated bot tokens, so only enroll
devices you fully trust.
"""
from __future__ import annotations
import hashlib, hmac, json, os, secrets, sqlite3, subprocess, sys, threading, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(os.getenv("BOTHUB_CLUSTER_HOME", str(Path.home() / ".bothub-cluster"))).expanduser()
DB = ROOT / "cluster.sqlite3"
NODE_ID = os.getenv("BOTHUB_NODE_ID", "").strip()
SECRET = os.getenv("BOTHUB_CLUSTER_SECRET", "").encode()
ADMIN_TOKEN = os.getenv("BOTHUB_ADMIN_TOKEN", "")
HOST = os.getenv("BOTHUB_CLUSTER_BIND", "0.0.0.0")
PORT = int(os.getenv("BOTHUB_CLUSTER_PORT", "47800"))
PEERS = json.loads(os.getenv("BOTHUB_CLUSTER_PEERS_JSON", "{}"))
LEASE_SECONDS = max(20, int(os.getenv("BOTHUB_LEASE_SECONDS", "60")))
HEARTBEAT_SECONDS = max(5, int(os.getenv("BOTHUB_CLUSTER_INTERVAL", "10")))
MAX_BOTS = max(1, int(os.getenv("BOTHUB_MAX_BOTS", "3")))
MIN_RAM_MB = max(0, int(os.getenv("BOTHUB_MIN_RAM_MB", "200")))
MIN_DISK_GB = max(0, int(os.getenv("BOTHUB_MIN_DISK_GB", "1")))
BOT_SOURCE_URL = os.getenv("BOTHUB_BOT_SOURCE_URL", "https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/main8.py")
STOP = threading.Event()
PROCS = {}
LOGS = {}
LOCK = threading.RLock()

FB_API_KEY = os.getenv("BOTHUB_FIREBASE_API_KEY", "")
FB_DB = os.getenv("BOTHUB_FIREBASE_DB", "")
FB_EMAIL = os.getenv("BOTHUB_FIREBASE_EMAIL", "")
FB_PASSWORD = os.getenv("BOTHUB_FIREBASE_PASSWORD", "")
FB_TOKEN = ""
FB_TOKEN_EXPIRES = 0
FB_LAST_REFRESH = 0
FALLBACK_PEERS = dict(PEERS)
FIREBASE_SERVERS = {}

def refresh_firebase_peers(force=False):
    """Refresh the peer directory from Firebase; keep offline members in membership for safe quorum."""
    global PEERS, FB_TOKEN, FB_TOKEN_EXPIRES, FB_LAST_REFRESH, FIREBASE_SERVERS
    if not (FB_API_KEY and FB_DB and FB_EMAIL and FB_PASSWORD):
        return
    if not force and time.time() - FB_LAST_REFRESH < 15:
        return
    try:
        if not FB_TOKEN or time.time() >= FB_TOKEN_EXPIRES - 120:
            payload = json.dumps({"email": FB_EMAIL, "password": FB_PASSWORD, "returnSecureToken": True}).encode()
            req = urllib.request.Request(
                "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=" + FB_API_KEY,
                data=payload, headers={"Content-Type":"application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=12) as response:
                auth_data = json.loads(response.read().decode())
            FB_TOKEN = auth_data["idToken"]
            FB_TOKEN_EXPIRES = time.time() + int(auth_data.get("expiresIn", 3600))
        url = FB_DB.rstrip("/") + "/clusterServers.json?auth=" + __import__("urllib.parse", fromlist=["quote"]).quote(FB_TOKEN, safe="")
        req = urllib.request.Request(url, headers={"User-Agent":"BotHub-Cluster/1.0"})
        with urllib.request.urlopen(req, timeout=12) as response:
            records = json.loads(response.read().decode()) or {}
        FIREBASE_SERVERS = records if isinstance(records, dict) else {}
        discovered = dict(FALLBACK_PEERS)
        for node_id, record in records.items():
            if not isinstance(record, dict) or node_id == NODE_ID:
                continue
            if record.get("cluster_id") != hashlib.sha256(SECRET).hexdigest()[:16]:
                continue
            peer_url = str(record.get("url", "")).strip()
            if peer_url.startswith(("http://", "https://")):
                discovered[str(node_id)] = peer_url
        PEERS = discovered
        FB_LAST_REFRESH = time.time()
        print("[BotHub] diretório Firebase atualizado:", len(PEERS), "pares conhecidos", flush=True)
    except Exception as exc:
        # Do not shrink membership on a Firebase outage; that could weaken quorum.
        FB_LAST_REFRESH = time.time()
        print("[BotHub] diretório Firebase indisponível; mantendo pares conhecidos:", str(exc)[:180], flush=True)


def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

def signature(data):
    return hmac.new(SECRET, canonical(data), hashlib.sha256).hexdigest()

def dbconn():
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    ROOT.mkdir(parents=True, exist_ok=True)
    try: ROOT.chmod(0o700)
    except OSError: pass
    with dbconn() as d:
        d.execute("PRAGMA journal_mode=WAL")
        d.execute("""CREATE TABLE IF NOT EXISTS tasks(
          task_id TEXT PRIMARY KEY, name TEXT NOT NULL, token TEXT NOT NULL,
          config TEXT NOT NULL, enabled INTEGER NOT NULL, updated INTEGER NOT NULL)""")
        d.execute("""CREATE TABLE IF NOT EXISTS votes(
          task_id TEXT PRIMARY KEY, owner TEXT NOT NULL, until_ts INTEGER NOT NULL)""")
        d.execute("""CREATE TABLE IF NOT EXISTS leases(
          task_id TEXT PRIMARY KEY, owner TEXT NOT NULL, until_ts INTEGER NOT NULL)""")
        d.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        d.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('created','1')")
    try: DB.chmod(0o600)
    except OSError: pass

def require_setup():
    if not NODE_ID or len(NODE_ID) > 100:
        raise SystemExit("Defina BOTHUB_NODE_ID com um ID único para este nó.")
    if len(SECRET) < 32:
        raise SystemExit("Defina BOTHUB_CLUSTER_SECRET com segredo aleatório de pelo menos 32 caracteres.")
    if not ADMIN_TOKEN or len(ADMIN_TOKEN) < 24:
        raise SystemExit("Defina BOTHUB_ADMIN_TOKEN (mínimo 24 caracteres) para a administração privada.")
    if NODE_ID in PEERS:
        raise SystemExit("O ID deste nó não pode aparecer em BOTHUB_CLUSTER_PEERS_JSON.")
    for pid, url in PEERS.items():
        if not pid or pid == NODE_ID or not str(url).startswith(("http://", "https://")):
            raise SystemExit("BOTHUB_CLUSTER_PEERS_JSON deve mapear IDs únicos para URLs http(s).")

def request(url, method="GET", payload=None, peer=True, timeout=3):
    body = canonical(payload or {}) if payload is not None else b""
    headers = {"User-Agent": "BotHub-Cluster/1.0"}
    if peer:
        stamp = str(int(time.time()))
        signed = stamp.encode() + b"\n" + body
        headers.update({"X-BotHub-Node": NODE_ID, "X-BotHub-Time": stamp,
                        "X-BotHub-Signature": hmac.new(SECRET, signed, hashlib.sha256).hexdigest()})
    else:
        headers["Authorization"] = "Bearer " + ADMIN_TOKEN
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body if payload is not None else None, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(2_000_000)
        return json.loads(raw.decode()) if raw else {}

def peer_request(peer_id, path, method="GET", payload=None):
    base = str(PEERS[peer_id]).rstrip("/")
    return request(base + path, method, payload, True, 3)

def node_status():
    # psutil is optional: it cannot be built on some Android/Termux Python installs.
    ram, cpu = 0, 0.0
    try:
        import psutil
        ram = int(psutil.virtual_memory().available)
        cpu = float(psutil.cpu_percent(interval=0.05))
    except Exception:
        # Linux and Termux expose available memory through /proc/meminfo.
        try:
            with open("/proc/meminfo", "r", encoding="ascii") as f:
                mem = {}
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and parts[0].endswith(":"):
                        mem[parts[0][:-1]] = int(parts[1]) * 1024
                ram = mem.get("MemAvailable", mem.get("MemFree", 0))
        except (OSError, ValueError):
            ram = 0
    import shutil
    disk = shutil.disk_usage(str(ROOT))
    with LOCK:
        running = sum(1 for p in PROCS.values() if p.poll() is None)
    resources_ok = ram >= MIN_RAM_MB*1024**2 and disk.free >= MIN_DISK_GB*1024**3
    return {"node_id": NODE_ID, "at": int(time.time()), "ram_free": ram,
            "disk_free": disk.free, "cpu": cpu, "running": running,
            "eligible": resources_ok, "available": resources_ok and running < MAX_BOTS}

def all_statuses():
    refresh_firebase_peers()
    out = {NODE_ID: node_status()}
    for pid in sorted(PEERS):
        try:
            s = peer_request(pid, "/v1/status")
            if int(time.time()) - int(s.get("at", 0)) <= 30:
                out[pid] = s
        except Exception:
            pass
    return out

def task_rows():
    with dbconn() as d:
        return [dict(r) for r in d.execute("SELECT * FROM tasks ORDER BY updated,task_id").fetchall()]

def merge_tasks(incoming):
    now = int(time.time())
    with dbconn() as d:
        for t in incoming:
            try:
                tid, name, token = str(t["task_id"]), str(t["name"]), str(t["token"])
                config, enabled, updated = t.get("config", {}), int(bool(t.get("enabled", True))), int(t["updated"])
                if isinstance(config, str):
                    try: config = json.loads(config)
                    except Exception: config = {}
                if not isinstance(config, dict): config = {}
                if not tid or len(tid) > 100 or len(name) > 100 or len(token) < 30 or updated > now + 300:
                    continue
                existing = d.execute("SELECT updated FROM tasks WHERE task_id=?", (tid,)).fetchone()
                if not existing or updated > int(existing["updated"]):
                    d.execute("""INSERT INTO tasks(task_id,name,token,config,enabled,updated) VALUES(?,?,?,?,?,?)
                       ON CONFLICT(task_id) DO UPDATE SET name=excluded.name,token=excluded.token,
                       config=excluded.config,enabled=excluded.enabled,updated=excluded.updated""",
                       (tid,name,token,json.dumps(config,ensure_ascii=False),enabled,updated))
            except (KeyError, TypeError, ValueError):
                continue

def gossip():
    refresh_firebase_peers()
    tasks = task_rows()
    for pid in sorted(PEERS):
        try: peer_request(pid, "/v1/replicate", "POST", {"tasks": tasks})
        except Exception: pass

def eligible_nodes(statuses):
    return sorted(k for k,v in statuses.items() if v.get("eligible"))

def candidate_for(task_id, statuses, existing_owner=None):
    if existing_owner in statuses and statuses[existing_owner].get("eligible"):
        return existing_owner
    nodes = sorted(k for k,v in statuses.items() if v.get("available", v.get("eligible", False)))
    if not nodes: return None
    return max(nodes, key=lambda n: hashlib.sha256((task_id + "\0" + n).encode()).digest())

def vote(task_id, owner):
    now = int(time.time())
    with dbconn() as d:
        row = d.execute("SELECT owner,until_ts FROM votes WHERE task_id=?", (task_id,)).fetchone()
        if row and int(row["until_ts"]) > now and row["owner"] != owner:
            return {"granted": False, "until": int(row["until_ts"])}
        until_ts = now + LEASE_SECONDS
        d.execute("""INSERT INTO votes(task_id,owner,until_ts) VALUES(?,?,?)
          ON CONFLICT(task_id) DO UPDATE SET owner=excluded.owner,until_ts=excluded.until_ts""",
          (task_id,owner,until_ts))
    return {"granted": True, "until": until_ts}

def current_lease_owner(task_id):
    refresh_firebase_peers()
    now = int(time.time())
    with dbconn() as d:
        row = d.execute("SELECT owner,until_ts FROM leases WHERE task_id=?", (task_id,)).fetchone()
    if row and int(row["until_ts"]) > now:
        return row["owner"]
    from urllib.parse import quote
    for pid in sorted(PEERS):
        try:
            result = peer_request(pid, "/v1/lease?task_id=" + quote(task_id, safe=""))
            if result.get("owner") and int(result.get("until_ts", 0)) > now:
                return str(result["owner"])
        except Exception:
            pass
    return None

def has_valid_local_lease(task_id):
    with dbconn() as d:
        row = d.execute("SELECT owner,until_ts FROM leases WHERE task_id=?", (task_id,)).fetchone()
    return bool(row and row["owner"] == NODE_ID and int(row["until_ts"]) > int(time.time()))

def acquire_lease(task_id):
    refresh_firebase_peers()
    # Membership means majority is computed against all configured members.
    # Fail closed if a majority is unavailable; do not silently reduce quorum.
    members = 1 + len(PEERS)
    quorum = members // 2 + 1
    local = vote(task_id, NODE_ID)
    granted = 1 if local["granted"] else 0
    expires = local.get("until", 0)
    for pid in sorted(PEERS):
        try:
            result = peer_request(pid, "/v1/vote", "POST", {"task_id": task_id, "owner": NODE_ID})
            if result.get("granted"):
                granted += 1
                expires = min(expires, int(result["until"])) if expires else int(result["until"])
        except Exception:
            continue
    if granted < quorum:
        return False
    with dbconn() as d:
        d.execute("""INSERT INTO leases(task_id,owner,until_ts) VALUES(?,?,?)
          ON CONFLICT(task_id) DO UPDATE SET owner=excluded.owner,until_ts=excluded.until_ts""",
          (task_id,NODE_ID,expires))
    return True

def stop_task(task_id):
    with LOCK:
        p = PROCS.pop(task_id, None)
        log = LOGS.pop(task_id, None)
    if p and p.poll() is None:
        try: p.terminate(); p.wait(timeout=6)
        except Exception:
            try: p.kill()
            except Exception: pass
    if log:
        try: log.close()
        except Exception: pass

def safe_id(value):
    return "".join(c for c in str(value) if c.isalnum() or c in "-_")[:80] or "bot"

def start_task(t):
    tid = safe_id(t["task_id"])
    folder = ROOT / "bots" / tid
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "main8.py"
    if not script.exists():
        req = urllib.request.Request(BOT_SOURCE_URL, headers={"User-Agent":"BotHub-Cluster/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r: data = r.read()
        if len(data) < 10000: raise RuntimeError("Arquivo de bot muito pequeno; download recusado.")
        script.write_bytes(data)
    config = json.loads(t["config"] or "{}")
    config["discord_token"] = t["token"]
    cp = folder / "config.json"
    cp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    try: cp.chmod(0o600)
    except OSError: pass
    with LOCK:
        p = PROCS.get(tid)
        if p and p.poll() is None: return
        log = open(folder / "bot.log", "ab", buffering=0)
        bot_env = os.environ.copy()
        # Do not expose Firebase login credentials or cluster administration secrets to bot code.
        for key in ("BOTHUB_FIREBASE_EMAIL", "BOTHUB_FIREBASE_PASSWORD", "BOTHUB_FIREBASE_API_KEY",
                    "BOTHUB_FIREBASE_DB", "BOTHUB_CLUSTER_SECRET", "BOTHUB_ADMIN_TOKEN",
                    "BOTHUB_FIREBASE_TOKEN"):
            bot_env.pop(key, None)
        p = subprocess.Popen([sys.executable, "-u", str(script)], cwd=str(folder), env=bot_env,
                             stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                             start_new_session=(os.name != "nt"))
        PROCS[tid], LOGS[tid] = p, log
    print("[BotHub] iniciando", t["name"], "PID", p.pid, flush=True)

def reconcile():
    gossip()
    statuses = all_statuses()
    tasks = task_rows()
    desired = set()
    for t in tasks:
        if not t["enabled"]: continue
        tid = t["task_id"]
        owner = candidate_for(tid, statuses, current_lease_owner(tid))
        if owner != NODE_ID: continue
        if not acquire_lease(tid):
            # Keep an already-running bot only while its previously quorum-granted lease is valid.
            # Once that lease expires without quorum, stop rather than risk split-brain.
            if has_valid_local_lease(tid) and safe_id(tid) in PROCS and PROCS[safe_id(tid)].poll() is None:
                desired.add(safe_id(tid))
            continue
        desired.add(safe_id(tid))
        try: start_task(t)
        except Exception as e: print("[BotHub] falha iniciando", tid, str(e)[:200], flush=True)
    for tid in list(PROCS):
        if tid not in desired:
            stop_task(tid)

def authorized_peer(handler, body):
    try:
        peer = handler.headers.get("X-BotHub-Node", "")
        stamp = int(handler.headers.get("X-BotHub-Time", "0"))
        sig = handler.headers.get("X-BotHub-Signature", "")
        if peer not in PEERS or abs(int(time.time()) - stamp) > 30: return False
        expected = hmac.new(SECRET, str(stamp).encode() + b"\n" + body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False

class Handler(BaseHTTPRequestHandler):
    server_version = "BotHubCluster/1.0"
    def log_message(self, fmt, *args): print("[http]", fmt % args)
    def send_json(self, code, obj):
        data = canonical(obj)
        self.send_response(code); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
    def body(self):
        size = int(self.headers.get("Content-Length","0"))
        if size < 0 or size > 2_000_000: raise ValueError("body too large")
        return self.rfile.read(size)
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/admin/ui":
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                return self.send_json(403, {"error":"private admin only"})
            panel = Path(__file__).with_name("bothub_panel.html")
            try:
                data = panel.read_bytes()
            except OSError:
                return self.send_json(404, {"error":"bothub_panel.html not found"})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/health":
            return self.send_json(200, {"ok":True,"node_id":NODE_ID})
        if path == "/v1/status":
            raw = b"{}"
            if not authorized_peer(self, raw): return self.send_json(401,{"error":"peer auth denied"})
            return self.send_json(200,node_status())
        if path == "/v1/tasks":
            raw = b"{}"
            if not authorized_peer(self, raw): return self.send_json(401,{"error":"peer auth denied"})
            return self.send_json(200,{"tasks":task_rows()})
        if path == "/v1/lease":
            raw = b"{}"
            if not authorized_peer(self, raw): return self.send_json(401,{"error":"peer auth denied"})
            from urllib.parse import parse_qs
            tid = parse_qs(urlparse(self.path).query).get("task_id", [""])[0]
            with dbconn() as d: row = d.execute("SELECT owner,until_ts FROM leases WHERE task_id=?", (tid,)).fetchone()
            return self.send_json(200, dict(row) if row else {})
        if path == "/admin/status":
            if self.client_address[0] not in ("127.0.0.1","::1") or self.headers.get("Authorization") != "Bearer "+ADMIN_TOKEN:
                return self.send_json(403,{"error":"private admin only"})
            refresh_firebase_peers(force=True)
            now_ms = int(time.time() * 1000)
            registry = []
            for server_id, record in FIREBASE_SERVERS.items():
                if not isinstance(record, dict):
                    continue
                last_seen = int(record.get("last_seen", 0) or 0)
                registry.append({
                    "node_id": str(server_id),
                    "hostname": str(record.get("hostname", "")),
                    "platform": str(record.get("platform", "")),
                    "status": "online" if record.get("status") == "online" and now_ms - last_seen <= 60000 else "offline",
                    "last_seen": last_seen,
                    "local_ip": str(record.get("local_ip", "")),
                    "public_ip": str(record.get("public_ip", "")),
                    "cluster_id": str(record.get("cluster_id", ""))
                })
            return self.send_json(200,{"node":node_status(),"peers":all_statuses(),"firebase_servers":registry,"tasks":[{k:v for k,v in t.items() if k!="token"} for t in task_rows()]})
        return self.send_json(404,{"error":"not found"})
    def do_POST(self):
        path = urlparse(self.path).path
        try: body = self.body(); data = json.loads(body or b"{}")
        except Exception: return self.send_json(400,{"error":"invalid body"})
        if path.startswith("/admin/"):
            if self.client_address[0] not in ("127.0.0.1","::1") or self.headers.get("Authorization") != "Bearer "+ADMIN_TOKEN:
                return self.send_json(403,{"error":"private admin only"})
            if path == "/admin/tasks":
                name, token = str(data.get("name","")).strip(), str(data.get("token","")).strip()
                if not name or len(name)>100 or len(token)<30: return self.send_json(400,{"error":"name/token invalid"})
                tid = secrets.token_hex(12); now = int(time.time())
                cfg = data.get("config",{})
                if not isinstance(cfg,dict): return self.send_json(400,{"error":"config must be an object"})
                with dbconn() as d:
                    d.execute("INSERT INTO tasks(task_id,name,token,config,enabled,updated) VALUES(?,?,?,?,1,?)",
                              (tid,name,token,json.dumps(cfg,ensure_ascii=False),now))
                return self.send_json(201,{"ok":True,"task_id":tid})
            if path == "/admin/disable":
                tid = str(data.get("task_id",""))
                with dbconn() as d: d.execute("UPDATE tasks SET enabled=0,updated=? WHERE task_id=?",(int(time.time()),tid))
                return self.send_json(200,{"ok":True})
            return self.send_json(404,{"error":"not found"})
        if not authorized_peer(self, body): return self.send_json(401,{"error":"peer auth denied"})
        if path == "/v1/replicate":
            tasks = data.get("tasks",[])
            if not isinstance(tasks,list): return self.send_json(400,{"error":"tasks must be a list"})
            merge_tasks(tasks)
            return self.send_json(200,{"ok":True})
        if path == "/v1/vote":
            tid, owner = str(data.get("task_id","")), str(data.get("owner",""))
            if not tid or owner not in (set(PEERS) | {NODE_ID}): return self.send_json(400,{"error":"invalid vote"})
            return self.send_json(200,vote(tid,owner))
        return self.send_json(404,{"error":"not found"})

def worker_loop():
    while not STOP.wait(HEARTBEAT_SECONDS):
        try: reconcile()
        except Exception as e: print("[BotHub] loop error:",str(e)[:250],flush=True)

def admin_cli():
    import getpass
    import urllib.parse
    base = "http://127.0.0.1:"+str(PORT)
    print("BotHub cluster admin (privado; roda apenas no próprio dispositivo)")
    print("Comandos: status | add | disable ID | sair")
    while True:
        try: line = input("bothub> ").strip()
        except (EOFError,KeyboardInterrupt): break
        if line in ("sair","exit","quit"): break
        if line == "status":
            try: print(json.dumps(request(base+"/admin/status",peer=False,timeout=4),indent=2,ensure_ascii=False))
            except Exception as e: print("Erro:",e)
        elif line == "add":
            name = input("Nome do bot: ").strip()
            token = getpass.getpass("Token Discord (não será exibido): ").strip()
            try:
                payload = {"name":name,"token":token,"config":{}}
                print(request(base+"/admin/tasks","POST",payload,peer=False,timeout=8))
            except Exception as e: print("Erro:",e)
        elif line.startswith("disable "):
            tid = line.split(" ",1)[1].strip()
            try: print(request(base+"/admin/disable","POST",{"task_id":tid},peer=False,timeout=8))
            except Exception as e: print("Erro:",e)
        elif line: print("Comando desconhecido.")

def main():
    require_setup(); init_db()
    refresh_firebase_peers(force=True)
    # Admin mode is a separate client process; it must not bind a second copy of the server port.
    if len(sys.argv)>1 and sys.argv[1]=="admin":
        admin_cli()
        return
    server = ThreadingHTTPServer((HOST,PORT),Handler)
    threading.Thread(target=server.serve_forever,daemon=True,name="bothub-http").start()
    print("[BotHub] nó",NODE_ID,"ouvindo",HOST,PORT,"pares:",", ".join(sorted(PEERS)) or "(nenhum)")
    threading.Thread(target=worker_loop,daemon=True,name="bothub-reconcile").start()
    print("[BotHub] Para administrar localmente, execute: python3 bothub_cluster.py admin")
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt: pass
    STOP.set(); server.shutdown()
    for tid in list(PROCS): stop_task(tid)

if __name__ == "__main__":
    main()
