#!/usr/bin/env python3
# BotHub Firebase worker: each tablet/server runs bots; the HTML panel controls tasks through RTDB.
import os,sys,json,time,socket,platform,shutil,subprocess,urllib.parse
from pathlib import Path
import requests
ROOT=Path.home()/".bothub";ROOT.mkdir(parents=True,exist_ok=True)
CFGFILE=ROOT/"worker.json";TOKFILE=ROOT/"firebase-token.json"
API_KEY="AIzaSyDS_KvyPWGgzYqIVgkagw5DAwzlenNZtiE"
DB="https://bothub-bca02-default-rtdb.firebaseio.com"
PROCS={};LOGS={};S=requests.Session();WORKER_STARTED=time.time()
def setup():
 if CFGFILE.exists():return json.loads(CFGFILE.read_text())
 import getpass
 cfg={"device_id":input("ID único deste dispositivo: ").strip(),"email":input("E-mail Firebase deste worker: ").strip(),"password":getpass.getpass("Senha Firebase: ")}
 if not all(cfg.values()):raise SystemExit("ID, e-mail e senha são obrigatórios.")
 CFGFILE.write_text(json.dumps(cfg),encoding="utf-8")
 try:CFGFILE.chmod(0o600)
 except OSError:pass
 return cfg
def token(cfg):
 if TOKFILE.exists():
  try:
   t=json.loads(TOKFILE.read_text())
   if time.time()<t["expires"]-120:return t["idToken"]
  except Exception:pass
 r=S.post("https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword",params={"key":API_KEY},json={"email":cfg["email"],"password":cfg["password"],"returnSecureToken":True},timeout=20)
 r.raise_for_status();d=r.json();t={"idToken":d["idToken"],"expires":time.time()+int(d.get("expiresIn",3600))}
 TOKFILE.write_text(json.dumps(t))
 try:TOKFILE.chmod(0o600)
 except OSError:pass
 return t["idToken"]
def fb(method,path,tok,data=None):
 r=S.request(method,DB+"/"+path.strip("/")+".json",params={"auth":tok},json=data,timeout=20)
 if r.status_code>=300:raise RuntimeError("Firebase "+str(r.status_code)+": "+r.text[:200])
 return r.json() if r.text else None
def stats(cfg):
 d=shutil.disk_usage(str(Path.home()));running=[k for k,p in PROCS.items() if p.poll() is None];x={"deviceId":cfg["device_id"],"hostname":socket.gethostname(),"label":socket.gethostname(),"platform":platform.platform(),"diskFreeBytes":d.free,"diskTotalBytes":d.total,"cpuCount":os.cpu_count() or 1,"runningBots":len(running),"runningBotIds":running,"lastSeen":int(time.time()*1000),"uptimeSeconds":int(time.time()-WORKER_STARTED),"workerStartedAt":int(WORKER_STARTED*1000)}
 try:
  x["publicIp"]=S.get("https://api.ipify.org?format=json",timeout=4).json().get("ip","")
 except Exception:x["publicIp"]=""
 try:
  import psutil
  m=psutil.virtual_memory()
  x.update(ramFreeBytes=m.available,ramTotalBytes=m.total,cpuPercent=psutil.cpu_percent(.1),cpuCount=psutil.cpu_count() or (os.cpu_count() or 1))
 except Exception:
  # Android/Termux may not support psutil; use Linux procfs when available.
  try:
   mem={}
   for line in Path("/proc/meminfo").read_text().splitlines():
    key, value = line.split(":", 1)
    parts = value.strip().split()
    if parts and parts[0].isdigit():
     mem[key] = int(parts[0]) * (1024 if len(parts) > 1 and parts[1].lower() == "kb" else 1)
   total = mem.get("MemTotal", 0)
   available = mem.get("MemAvailable", mem.get("MemFree", 0) + mem.get("Buffers", 0) + mem.get("Cached", 0))
   x.update(ramFreeBytes=available, ramTotalBytes=total, cpuPercent=0, cpuCount=os.cpu_count() or 1)
  except Exception:
   x.update(ramFreeBytes=0, ramTotalBytes=0, cpuPercent=0, cpuCount=os.cpu_count() or 1)
 return x
def sid(v):return "".join(c for c in str(v) if c.isalnum() or c in "-_")[:80] or "bot"
def stop(k):
 p=PROCS.pop(k,None);l=LOGS.pop(k,None)
 if p and p.poll() is None:
  try:p.terminate();p.wait(timeout=5)
  except Exception:
   try:p.kill()
   except Exception:pass
 if l:
  try:l.close()
  except Exception:pass
def start(k,b):
 folder=ROOT/"bots"/sid(k);folder.mkdir(parents=True,exist_ok=True);script=folder/"main8.py"
 if not script.exists():
  url=os.getenv("BOTHUB_BOT_SOURCE_URL","https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/main8.py")
  r=S.get(url,timeout=30);r.raise_for_status()
  if len(r.content)<10000:raise RuntimeError("Download de main8.py incompleto.")
  script.write_bytes(r.content)
 cfg=dict(b.get("config") or {});cfg["discord_token"]=b["token"];cp=folder/"config.json";cp.write_text(json.dumps(cfg,ensure_ascii=False,indent=2))
 try:cp.chmod(0o600)
 except OSError:pass
 if k in PROCS and PROCS[k].poll() is None:return
 log=open(folder/"bot.log","ab",buffering=0);p=subprocess.Popen([sys.executable,"-u",str(script)],cwd=str(folder),stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=(os.name!="nt"));PROCS[k]=p;LOGS[k]=log
 print("[BotHub] iniciado",b.get("name",k),"PID",p.pid,flush=True)
def main():
 cfg=setup();v=ROOT/"venv";vp=v/("Scripts/python.exe" if os.name=="nt" else "bin/python")
 if not vp.exists():
  subprocess.check_call([sys.executable,"-m","venv",str(v)])
  subprocess.check_call([str(vp),"-m","pip","install","--upgrade","pip"])
  packages=["requests","discord.py","aiohttp"]
  subprocess.check_call([str(vp),"-m","pip","install",*packages])
  os.execv(str(vp),[str(vp),str(Path(__file__).resolve())])
 print("[BotHub] Worker Firebase ativo:",cfg["device_id"],flush=True)
 while True:
  try:
   t=token(cfg);did=urllib.parse.quote(cfg["device_id"],safe="")
   fb("PUT","workers/"+did,t,stats(cfg))
   queue=fb("GET","workerTasks/"+did,t) or {}
   desired={sid(k):b for k,b in queue.items() if isinstance(b,dict) and b.get("enabled",True)}
   for k in list(PROCS):
    if k not in desired:stop(k);print("[BotHub] parado",k,flush=True)
   for k,b in desired.items():
    if k not in PROCS or PROCS[k].poll() is not None:
     try:start(k,b)
     except Exception as e:print("[BotHub] falha no bot",k,str(e)[:220],flush=True)
  except KeyboardInterrupt:break
  except Exception as e:print("[BotHub] erro Firebase/worker:",str(e)[:300],flush=True)
  time.sleep(max(10,int(os.getenv("BOTHUB_POLL_SECONDS","15"))))
 for k in list(PROCS):stop(k)
if __name__=="__main__":
 try:main()
 except Exception as e:print("Erro fatal:",e,file=sys.stderr);raise
