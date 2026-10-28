#!/usr/bin/env python3
"""BotHub API central. Configuração por variáveis de ambiente; não coloque tokens no GitHub."""
import os, json, time, sqlite3, hashlib, asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

DB_PATH = Path(os.getenv("BOTHUB_DB", "bothub.sqlite3"))
WORKERS = json.loads(os.getenv("BOTHUB_WORKERS_JSON", "{}"))
ADMIN_TOKEN = os.getenv("BOTHUB_ADMIN_TOKEN", "")
DISCORD_BOT_TOKEN = os.getenv("BOTHUB_DISCORD_BOT_TOKEN", "")
DISCORD_USER_ID = os.getenv("BOTHUB_DISCORD_USER_ID", "")
MIN_DISK_GB = float(os.getenv("BOTHUB_MIN_DISK_GB", "1"))
MIN_RAM_MB = float(os.getenv("BOTHUB_MIN_RAM_MB", "200"))
OFFLINE_SECONDS = int(os.getenv("BOTHUB_OFFLINE_SECONDS", "100"))

def connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS workers (
          device_id TEXT PRIMARY KEY, hostname TEXT, platform TEXT, disk_free_bytes INTEGER,
          disk_total_bytes INTEGER, ram_free_bytes INTEGER, ram_total_bytes INTEGER,
          cpu_count INTEGER, cpu_percent REAL, status TEXT, last_seen INTEGER, payload TEXT)""")
        db.execute("""CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
        db.execute("INSERT OR IGNORE INTO state(key,value) VALUES('queue_count','0')")
        db.execute("INSERT OR IGNORE INTO state(key,value) VALUES('capacity_state','available')")
        db.execute("INSERT OR IGNORE INTO state(key,value) VALUES('last_alert','')")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
app = FastAPI(title="BotHub API", version="1.0.0", lifespan=lifespan)

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
    status: str = "online"
    timestamp: int = 0

def require_admin(auth: str | None):
    if not ADMIN_TOKEN or not auth or auth != "Bearer " + ADMIN_TOKEN:
        raise HTTPException(401, "Credenciais administrativas inválidas.")

async def send_discord_dm(message: str):
    if not DISCORD_BOT_TOKEN or not DISCORD_USER_ID:
        print("ALERTA BotHub (Discord não configurado):", message)
        return False
    headers = {"Authorization": "Bot " + DISCORD_BOT_TOKEN, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=12) as client:
        dm = await client.post("https://discord.com/api/v10/users/@me/channels",
                               headers=headers, json={"recipient_id": DISCORD_USER_ID})
        if dm.status_code >= 300:
            print("Falha ao abrir DM Discord:", dm.status_code, dm.text[:300]); return False
        channel_id = dm.json()["id"]
        sent = await client.post(f"https://discord.com/api/v10/channels/{channel_id}/messages",
                                 headers=headers, json={"content": message[:1900]})
        if sent.status_code >= 300:
            print("Falha ao enviar DM Discord:", sent.status_code, sent.text[:300]); return False
        return True

def capacity_snapshot():
    now = int(time.time())
    with connect() as db:
        rows = db.execute("SELECT * FROM workers").fetchall()
        queue = int(db.execute("SELECT value FROM state WHERE key='queue_count'").fetchone()[0])
    nodes = []
    for row in rows:
        d = dict(row)
        d["online"] = now - int(d["last_seen"]) <= OFFLINE_SECONDS
        d["capacity"] = bool(d["online"] and int(d["disk_free_bytes"] or 0) >= MIN_DISK_GB*1024**3
                             and int(d["ram_free_bytes"] or 0) >= MIN_RAM_MB*1024**2)
        d.pop("payload", None)
        nodes.append(d)
    available = [n for n in nodes if n["capacity"]]
    return {"queue_count": queue, "nodes": nodes, "available_nodes": len(available),
            "capacity_available": bool(available), "server_time": now}

async def check_transition():
    snap = capacity_snapshot()
    state = "available" if snap["capacity_available"] else "full"
    with connect() as db:
        queue = snap["queue_count"]
        old = db.execute("SELECT value FROM state WHERE key='capacity_state'").fetchone()[0]
        # Notify only when state changes while work is waiting.
        if queue <= 0:
            db.execute("UPDATE state SET value=? WHERE key='capacity_state'", (state,))
            return
        if state == old:
            return
        db.execute("UPDATE state SET value=? WHERE key='capacity_state'", (state,))
    if state == "full":
        message = ("🚨 **BotHub — servidores esgotados**\n"
                   f"Não há tablets com capacidade disponível. Bots aguardando na fila: **{queue}**.\n"
                   "Adicione capacidade ou aguarde um tablet liberar recursos.")
    else:
        message = ("✅ **BotHub — capacidade restaurada**\n"
                   f"Há {snap['available_nodes']} tablet(s) com capacidade disponível. "
                   f"Bots aguardando na fila: **{queue}**. A distribuição pode ser retomada.")
    try:
        await send_discord_dm(message)
    except Exception as exc:
        print("Erro ao enviar alerta Discord:", str(exc)[:300])

@app.post("/api/worker/heartbeat")
async def heartbeat(data: Heartbeat, authorization: str | None = Header(default=None)):
    expected = WORKERS.get(data.device_id)
    if not expected or not authorization or authorization != "Bearer " + str(expected):
        raise HTTPException(401, "Token do worker inválido.")
    now = int(time.time())
    payload = data.model_dump()
    with connect() as db:
        db.execute("""INSERT INTO workers(device_id,hostname,platform,disk_free_bytes,disk_total_bytes,
          ram_free_bytes,ram_total_bytes,cpu_count,cpu_percent,status,last_seen,payload)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(device_id) DO UPDATE SET hostname=excluded.hostname, platform=excluded.platform,
          disk_free_bytes=excluded.disk_free_bytes,disk_total_bytes=excluded.disk_total_bytes,
          ram_free_bytes=excluded.ram_free_bytes,ram_total_bytes=excluded.ram_total_bytes,
          cpu_count=excluded.cpu_count,cpu_percent=excluded.cpu_percent,status=excluded.status,
          last_seen=excluded.last_seen,payload=excluded.payload""",
          (data.device_id,data.hostname,data.platform,data.disk_free_bytes,data.disk_total_bytes,
           data.ram_free_bytes,data.ram_total_bytes,data.cpu_count,data.cpu_percent,"online",now,json.dumps(payload)))
    await check_transition()
    return {"ok": True, "message": "Heartbeat recebido", "server_time": now}

@app.get("/api/admin/status")
async def admin_status(authorization: str | None = Header(default=None)):
    require_admin(authorization)
    return capacity_snapshot()

class QueueUpdate(BaseModel):
    waiting_bots: int = Field(ge=0, le=100000)

@app.post("/api/admin/queue")
async def update_queue(data: QueueUpdate, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    with connect() as db:
        db.execute("UPDATE state SET value=? WHERE key='queue_count'", (str(data.waiting_bots),))
    await check_transition()
    return {"ok": True, **capacity_snapshot()}

@app.get("/health")
async def health():
    return {"ok": True, "service": "BotHub API", "version": "1.0.0"}
