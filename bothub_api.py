#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BotHub private control API. Secrets are supplied only through environment variables."""
import os, json, time, sqlite3, asyncio, secrets, hashlib
from contextlib import asynccontextmanager
from pathlib import Path
import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

DB_PATH = Path(os.getenv("BOTHUB_DB", "bothub.sqlite3")).resolve()
WORKERS = json.loads(os.getenv("BOTHUB_WORKERS_JSON", "{}"))
ADMIN_TOKEN = os.getenv("BOTHUB_ADMIN_TOKEN", "")
DISCORD_BOT_TOKEN = os.getenv("BOTHUB_DISCORD_BOT_TOKEN", "")
DISCORD_USER_ID = os.getenv("BOTHUB_DISCORD_USER_ID", "")
MIN_DISK_GB = float(os.getenv("BOTHUB_MIN_DISK_GB", "1"))
MIN_RAM_MB = float(os.getenv("BOTHUB_MIN_RAM_MB", "200"))
OFFLINE_SECONDS = int(os.getenv("BOTHUB_OFFLINE_SECONDS", "100"))
MAX_BOTS_PER_WORKER = int(os.getenv("BOTHUB_MAX_BOTS_PER_WORKER", "3"))
BOT_SOURCE_URL = os.getenv("BOTHUB_BOT_SOURCE_URL", "https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/main8.py")

def connect():
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS workers (
          device_id TEXT PRIMARY KEY, hostname TEXT, platform TEXT, disk_free_bytes INTEGER DEFAULT 0,
          disk_total_bytes INTEGER DEFAULT 0, ram_free_bytes INTEGER DEFAULT 0, ram_total_bytes INTEGER DEFAULT 0,
          cpu_count INTEGER DEFAULT 1, cpu_percent REAL, status TEXT, last_seen INTEGER DEFAULT 0, payload TEXT)""")
        db.execute("""CREATE TABLE IF NOT EXISTS bots (
          bot_id TEXT PRIMARY KEY, bot_name TEXT NOT NULL, discord_token TEXT NOT NULL,
          config_json TEXT NOT NULL DEFAULT '{}', enabled INTEGER NOT NULL DEFAULT 1,
          worker_id TEXT, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)""")
        db.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT OR IGNORE INTO state(key,value) VALUES('capacity_state','unknown')")
        db.execute("INSERT OR IGNORE INTO state(key,value) VALUES('last_queue_count','0')")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
app = FastAPI(title="BotHub Private API", version="2.0.0", lifespan=lifespan)

class Heartbeat(BaseModel):
    device_id: str = Field(min_length=1, max_length=100)
    hostname: str = Field(default="", max_length=200)
    platform: str = Field(default="", max_length=300)
    disk_free_bytes: int = Field(ge=0)
    disk_total_bytes: int = Field(default=0, ge=0)
    ram_free_bytes: int = Field(default=0, ge=0)
    ram_total_bytes: int = Field(default=0, ge=0)
    cpu_count: int = Field(default=1, ge=1, le=1024)
    cpu_percent: float | None = None
    python: str = ""
    running_bots: int = Field(default=0, ge=0, le=10000)
    timestamp: int = 0

class BotCreate(BaseModel):
    bot_name: str = Field(min_length=1, max_length=100)
    discord_token: str = Field(min_length=30, max_length=300)
    config: dict = Field(default_factory=dict)

class BotUpdate(BaseModel):
    enabled: bool | None = None
    bot_name: str | None = Field(default=None, min_length=1, max_length=100)

def require_admin(auth: str | None):
    if not ADMIN_TOKEN or not auth or not secrets.compare_digest(auth, "Bearer " + ADMIN_TOKEN):
        raise HTTPException(401, "Acesso administrativo negado.")

def require_worker(device_id: str, auth: str | None):
    expected = WORKERS.get(device_id)
    if not expected or not auth or not secrets.compare_digest(auth, "Bearer " + str(expected)):
        raise HTTPException(401, "Token do worker inválido.")

def snapshot():
    now = int(time.time())
    with connect() as db:
        rows = db.execute("SELECT * FROM workers").fetchall()
        bots = db.execute("SELECT bot_id,bot_name,enabled,worker_id,created_at,updated_at FROM bots").fetchall()
    nodes = []
    for row in rows:
        d = dict(row)
        d["online"] = now - int(d.get("last_seen") or 0) <= OFFLINE_SECONDS
        d["capacity"] = bool(d["online"] and int(d.get("disk_free_bytes") or 0) >= MIN_DISK_GB*1024**3
                             and int(d.get("ram_free_bytes") or 0) >= MIN_RAM_MB*1024**2)
        d.pop("payload", None)
        nodes.append(d)
    active_bots = [dict(b) for b in bots if b["enabled"]]
    assigned_counts = {}
    for bot in active_bots:
        wid = bot["worker_id"]
        if wid:
            assigned_counts[wid] = assigned_counts.get(wid, 0) + 1
    online_capacity = [n for n in nodes if n["capacity"]]
    available_slots = [n for n in online_capacity if assigned_counts.get(n["device_id"], 0) < MAX_BOTS_PER_WORKER]
    queued = [b for b in active_bots if not b["worker_id"] or not any(n["device_id"] == b["worker_id"] and n["capacity"] for n in nodes)]
    return {"nodes": nodes, "bots": [dict(b) for b in bots],
            "available_nodes": len(available_slots), "online_capacity_nodes": len(online_capacity),
            "capacity_available": bool(available_slots), "active_bots": len(active_bots),
            "queued_bots": len(queued), "server_time": now}

def reconcile_assignments():
    """Assign enabled bots to healthy workers, respecting the configured per-worker slot limit."""
    now = int(time.time())
    with connect() as db:
        rows = db.execute("SELECT * FROM workers").fetchall()
        bots = db.execute("SELECT bot_id,enabled,worker_id FROM bots ORDER BY created_at,bot_id").fetchall()
        workers = []
        for r in rows:
            online = now - int(r["last_seen"] or 0) <= OFFLINE_SECONDS
            enough = int(r["disk_free_bytes"] or 0) >= MIN_DISK_GB*1024**3 and int(r["ram_free_bytes"] or 0) >= MIN_RAM_MB*1024**2
            if online and enough:
                workers.append(r["device_id"])
        counts = {w: 0 for w in workers}
        # Keep assignments when possible, then move unassigned/stranded bots to available slots.
        assignments = {}
        for b in bots:
            wid = b["worker_id"]
            if b["enabled"] and wid in counts and counts[wid] < MAX_BOTS_PER_WORKER:
                assignments[b["bot_id"]] = wid
                counts[wid] += 1
        for b in bots:
            if not b["enabled"]:
                assignments[b["bot_id"]] = None
            elif b["bot_id"] not in assignments:
                target = next((w for w in workers if counts[w] < MAX_BOTS_PER_WORKER), None)
                assignments[b["bot_id"]] = target
                if target:
                    counts[target] += 1
        for bot_id, wid in assignments.items():
            db.execute("UPDATE bots SET worker_id=?,updated_at=? WHERE bot_id=?", (wid, now, bot_id))

async def send_discord_dm(message: str):
    if not DISCORD_BOT_TOKEN or not DISCORD_USER_ID:
        print("ALERTA BotHub (Discord não configurado):", message)
        return False
    headers = {"Authorization": "Bot " + DISCORD_BOT_TOKEN, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=12) as client:
        dm = await client.post("https://discord.com/api/v10/users/@me/channels",
                               headers=headers, json={"recipient_id": DISCORD_USER_ID})
        if dm.status_code >= 300:
            print("Falha ao abrir DM Discord:", dm.status_code, dm.text[:200]); return False
        sent = await client.post(f"https://discord.com/api/v10/channels/{dm.json()['id']}/messages",
                                 headers=headers, json={"content": message[:1900]})
        if sent.status_code >= 300:
            print("Falha ao enviar DM Discord:", sent.status_code, sent.text[:200]); return False
        return True

async def check_transition():
    reconcile_assignments()
    snap = snapshot()
    state = "available" if snap["queued_bots"] == 0 else ("full" if not snap["capacity_available"] else "queued")
    with connect() as db:
        old = db.execute("SELECT value FROM state WHERE key='capacity_state'").fetchone()[0]
        db.execute("UPDATE state SET value=? WHERE key='capacity_state'", (state,))
    # Only DM on transitions into fully saturated queue and when it clears/has capacity again.
    if state == old:
        return
    if state == "full" and snap["queued_bots"] > 0:
        message = ("🚨 BotHub: servidores esgotados.\n"
                   f"{snap['queued_bots']} bot(s) aguardando. Novos bots ficam na fila até liberar capacidade.")
    elif old in ("full", "queued") and state == "available":
        message = ("✅ BotHub: capacidade disponível novamente.\n"
                   f"{snap['available_nodes']} worker(s) com capacidade; fila zerada.")
    elif old == "full" and state == "queued":
        message = ("ℹ️ BotHub: um servidor voltou a responder, mas ainda há bots na fila.\n"
                   f"Fila atual: {snap['queued_bots']}.")
    else:
        return
    try:
        await send_discord_dm(message)
    except Exception as exc:
        print("Erro ao enviar alerta Discord:", str(exc)[:200])

@app.get("/health")
async def health():
    return {"ok": True, "service": "BotHub Private API", "version": "2.0.0"}

@app.post("/api/worker/heartbeat")
async def heartbeat(data: Heartbeat, authorization: str | None = Header(default=None)):
    require_worker(data.device_id, authorization)
    now = int(time.time())
    payload = data.model_dump()
    with connect() as db:
        db.execute("""INSERT INTO workers(device_id,hostname,platform,disk_free_bytes,disk_total_bytes,
          ram_free_bytes,ram_total_bytes,cpu_count,cpu_percent,status,last_seen,payload)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(device_id) DO UPDATE SET hostname=excluded.hostname,platform=excluded.platform,
          disk_free_bytes=excluded.disk_free_bytes,disk_total_bytes=excluded.disk_total_bytes,
          ram_free_bytes=excluded.ram_free_bytes,ram_total_bytes=excluded.ram_total_bytes,
          cpu_count=excluded.cpu_count,cpu_percent=excluded.cpu_percent,status='online',
          last_seen=excluded.last_seen,payload=excluded.payload""",
          (data.device_id,data.hostname,data.platform,data.disk_free_bytes,data.disk_total_bytes,
           data.ram_free_bytes,data.ram_total_bytes,data.cpu_count,data.cpu_percent,"online",now,json.dumps(payload)))
    await check_transition()
    return {"ok": True, "server_time": now}

@app.get("/api/worker/tasks")
async def worker_tasks(device_id: str, authorization: str | None = Header(default=None)):
    require_worker(device_id, authorization)
    reconcile_assignments()
    with connect() as db:
        rows = db.execute("SELECT bot_id,bot_name,discord_token,config_json,enabled FROM bots WHERE worker_id=? OR (enabled=0 AND worker_id=?)",
                          (device_id, device_id)).fetchall()
    tasks = []
    for r in rows:
        try: cfg = json.loads(r["config_json"] or "{}")
        except Exception: cfg = {}
        tasks.append({"bot_id":r["bot_id"],"bot_name":r["bot_name"],"discord_token":r["discord_token"],
                      "config":cfg,"enabled":bool(r["enabled"])})
    return {"device_id": device_id, "tasks": tasks, "bot_source_url": BOT_SOURCE_URL,
            "poll_seconds": 20}

@app.get("/api/admin/status")
async def admin_status(authorization: str | None = Header(default=None)):
    require_admin(authorization)
    await check_transition()
    return snapshot()

@app.post("/api/admin/bots")
async def create_bot(data: BotCreate, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    bot_id = secrets.token_hex(12)
    now = int(time.time())
    # Keep config free of secrets; the Discord token is stored separately.
    config = dict(data.config)
    config.pop("discord_token", None)
    with connect() as db:
        db.execute("INSERT INTO bots(bot_id,bot_name,discord_token,config_json,enabled,worker_id,created_at,updated_at) VALUES(?,?,?,?,1,NULL,?,?)",
                   (bot_id,data.bot_name,data.discord_token,json.dumps(config,ensure_ascii=False),now,now))
    await check_transition()
    return {"ok":True,"bot_id":bot_id,"bot_name":data.bot_name,"message":"Bot cadastrado; será atribuído quando houver capacidade."}

@app.get("/api/admin/bots")
async def list_bots(authorization: str | None = Header(default=None)):
    require_admin(authorization)
    with connect() as db:
        rows = db.execute("SELECT bot_id,bot_name,enabled,worker_id,created_at,updated_at FROM bots ORDER BY created_at").fetchall()
    return {"bots":[dict(r) for r in rows]}

@app.patch("/api/admin/bots/{bot_id}")
async def update_bot(bot_id: str, data: BotUpdate, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    with connect() as db:
        row = db.execute("SELECT bot_id FROM bots WHERE bot_id=?", (bot_id,)).fetchone()
        if not row: raise HTTPException(404,"Bot não encontrado.")
        if data.enabled is not None:
            db.execute("UPDATE bots SET enabled=?,worker_id=CASE WHEN ?=0 THEN worker_id ELSE NULL END,updated_at=? WHERE bot_id=?",
                       (int(data.enabled),int(data.enabled),int(time.time()),bot_id))
        if data.bot_name is not None:
            db.execute("UPDATE bots SET bot_name=?,updated_at=? WHERE bot_id=?",(data.bot_name,int(time.time()),bot_id))
    await check_transition()
    return {"ok":True,"bot_id":bot_id}

@app.delete("/api/admin/bots/{bot_id}")
async def delete_bot(bot_id: str, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    with connect() as db:
        cur = db.execute("DELETE FROM bots WHERE bot_id=?", (bot_id,))
        if cur.rowcount == 0: raise HTTPException(404,"Bot não encontrado.")
    await check_transition()
    return {"ok":True,"deleted":bot_id}
