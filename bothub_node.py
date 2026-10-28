#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BotHub worker single-file installer + bot process supervisor for Linux and Termux."""
from __future__ import annotations
import os, sys, json, time, shutil, subprocess, platform, socket, secrets, hashlib, urllib.request, urllib.error
from pathlib import Path

ROOT = Path.home() / ".bothub"
CONFIG = ROOT / "config.json"
WORKER = ROOT / "worker.py"
PY = ROOT / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
POLL = 20
BOT_PACKAGES = ["discord.py", "aiohttp", "Pillow"]
WORKER_SOURCE = r'''import os,sys,json,time,socket,platform,shutil,subprocess,hashlib
from pathlib import Path
import requests
try: import psutil
except ImportError: psutil=None
ROOT=Path.home()/".bothub"; CFG=json.loads((ROOT/"config.json").read_text(encoding="utf-8"))
API=CFG["api_url"].rstrip("/"); DEVICE=CFG["device_id"]; TOKEN=CFG["worker_token"]
INTERVAL=max(15,int(CFG.get("heartbeat_seconds",30))); POLL=max(10,int(CFG.get("poll_seconds",20)))
SESSION=requests.Session(); SESSION.headers.update({"Authorization":"Bearer "+TOKEN,"User-Agent":"BotHub-Worker/2.0"})
BOTS=ROOT/"bots"; BOTS.mkdir(parents=True,exist_ok=True); PROCS={}; LOGS={}
def resources():
 d=shutil.disk_usage(str(Path.home())); out={"device_id":DEVICE,"hostname":socket.gethostname(),"platform":platform.platform(),
 "disk_free_bytes":d.free,"disk_total_bytes":d.total,"cpu_count":os.cpu_count() or 1,"python":platform.python_version(),
 "status":"online","timestamp":int(time.time()),"running_bots":sum(1 for p in PROCS.values() if p.poll() is None)}
 if psutil:
  m=psutil.virtual_memory(); out["ram_total_bytes"]=m.total; out["ram_free_bytes"]=m.available; out["cpu_percent"]=psutil.cpu_percent(interval=0.1)
 else: out["ram_total_bytes"]=0; out["ram_free_bytes"]=0
 return out
def stop_bot(bot_id):
 p=PROCS.pop(bot_id,None); log=LOGS.pop(bot_id,None)
 if p and p.poll() is None:
  try: p.terminate(); p.wait(timeout=8)
  except Exception:
   try: p.kill(); p.wait(timeout=3)
   except Exception: pass
 if log:
  try: log.close()
  except Exception: pass
def safe_id(value): return "".join(c for c in str(value) if c.isalnum() or c in "-_")[:80] or "bot"
def download(url,dest):
 req=urllib.request.Request(url,headers={"User-Agent":"BotHub-Worker/2.0","Cache-Control":"no-cache"})
 with urllib.request.urlopen(req,timeout=30) as r: data=r.read()
 if len(data)<10000: raise RuntimeError("Arquivo do bot parece incompleto; download cancelado.")
 tmp=dest.with_suffix(dest.suffix+".tmp"); tmp.write_bytes(data); tmp.replace(dest)
def start_bot(task,source_url):
 bot_id=safe_id(task["bot_id"]); folder=BOTS/bot_id; folder.mkdir(parents=True,exist_ok=True)
 script=folder/"main8.py"; cfgpath=folder/"config.json"
 if not script.exists(): download(source_url,script)
 cfg=dict(task.get("config") or {}); cfg["discord_token"]=task["discord_token"]
 cfgpath.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding="utf-8")
 try: cfgpath.chmod(0o600)
 except OSError: pass
 running=PROCS.get(bot_id)
 if running and running.poll() is None: return
 log=open(folder/"bot.log","ab",buffering=0)
 try:
  p=subprocess.Popen([str(PY),"-u",str(script)],cwd=str(folder),stdin=subprocess.DEVNULL,
   stdout=log,stderr=subprocess.STDOUT,start_new_session=(os.name!="nt"))
 except Exception: log.close(); raise
 PROCS[bot_id]=p; LOGS[bot_id]=log
 print("[BotHub] Bot iniciado:",task.get("bot_name",bot_id),"PID",p.pid,flush=True)
def sync_tasks():
 r=SESSION.get(API+"/api/worker/tasks",params={"device_id":DEVICE},timeout=15)
 if r.status_code==401: raise RuntimeError("Token do worker recusado.")
 r.raise_for_status(); payload=r.json(); source=payload.get("bot_source_url","")
 desired={}
 for task in payload.get("tasks",[]):
  bid=safe_id(task.get("bot_id",""))
  if task.get("enabled"): desired[bid]=task
 for bid in list(PROCS):
  if bid not in desired: stop_bot(bid); print("[BotHub] Bot removido/desativado:",bid,flush=True)
 for bid,task in desired.items():
  p=PROCS.get(bid)
  if p and p.poll() is None: continue
  try: start_bot(task,source)
  except Exception as e: print("[BotHub] Falha iniciando",bid,repr(e),flush=True)
def main():
 print("[BotHub] Worker iniciado:",DEVICE,flush=True); last_sync=0
 while True:
  try:
   r=SESSION.post(API+"/api/worker/heartbeat",json=resources(),timeout=15)
   if r.status_code==401: print("[BotHub] Token inválido; confira config.json.",flush=True); time.sleep(60); continue
   r.raise_for_status()
   if time.time()-last_sync>=POLL:
    sync_tasks(); last_sync=time.time()
  except KeyboardInterrupt: break
  except Exception as e: print("[BotHub] Erro de conexão/tarefa:",str(e)[:250],flush=True)
  time.sleep(INTERVAL)
 for bid in list(PROCS): stop_bot(bid)
if __name__=="__main__": main()
'''
def ask(label,default=""):
 value=input(label+(f" [{default}]" if default else "")+": ").strip()
 return value or default
def run(cmd): print("+"," ".join(map(str,cmd))); subprocess.check_call(list(map(str,cmd)))
def main():
 print("\n=== BotHub Worker — instalador e supervisor ===")
 if sys.version_info<(3,9): raise SystemExit("Python 3.9+ é necessário.")
 ROOT.mkdir(parents=True,exist_ok=True)
 if not PY.exists(): run([sys.executable,"-m","venv",ROOT/"venv"])
 req=ROOT/"requirements.txt"; req.write_text("requests>=2.31,<3\npsutil>=5.9,<8\n",encoding="utf-8")
 run([PY,"-m","pip","install","--disable-pip-version-check","--upgrade","pip"])
 run([PY,"-m","pip","install","-r",req])
 old={}
 if CONFIG.exists():
  try: old=json.loads(CONFIG.read_text(encoding="utf-8"))
  except Exception: pass
 api=ask("URL HTTPS da API BotHub",old.get("api_url","")).rstrip("/")
 if not (api.startswith("https://") or api.startswith("http://127.0.0.1") or api.startswith("http://localhost")):
  raise SystemExit("Use HTTPS fora do próprio dispositivo.")
 device=ask("ID único deste tablet/servidor",old.get("device_id",platform.node() or secrets.token_hex(4)))
 token=ask("Token individual do worker (configurado pelo administrador)",old.get("worker_token",""))
 if len(token)<24: raise SystemExit("Token muito curto; use um token aleatório de pelo menos 24 caracteres.")
 CONFIG.write_text(json.dumps({"api_url":api,"device_id":device,"worker_token":token,"heartbeat_seconds":30,"poll_seconds":20},indent=2),encoding="utf-8")
 try: CONFIG.chmod(0o600)
 except OSError: pass
 WORKER.write_text(WORKER_SOURCE,encoding="utf-8")
 try: WORKER.chmod(0o700)
 except OSError: pass
 boot=Path.home()/".termux"/"boot"
 if "com.termux" in os.environ.get("PREFIX","") and boot.exists():
  script=boot/"bothub-start.sh"
  script.write_text("#!/data/data/com.termux/files/usr/bin/sh\ntermux-wake-lock\n"+f'"{PY}" "{WORKER}" >> "$HOME/.bothub/worker.log" 2>&1\n',encoding="utf-8")
  script.chmod(0o700); print("Termux:Boot configurado.")
 else:
  starter=ROOT/"iniciar.sh"; starter.write_text("#!/bin/sh\n"+f'exec "{PY}" "{WORKER}"\n',encoding="utf-8"); starter.chmod(0o700)
  print("Inicie com: sh ~/.bothub/iniciar.sh")
  print("Para iniciar após reiniciar Android, instale Termux:Boot e execute novamente com ~/.termux/boot existente.")
 print("Configuração salva em",CONFIG); print("Iniciando supervisor...")
 os.execv(str(PY),[str(PY),str(WORKER)])
if __name__=="__main__":
 try: main()
 except subprocess.CalledProcessError as e: raise SystemExit("Falha instalando dependências; confira internet e Python/pip.")
