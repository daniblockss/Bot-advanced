#!/usr/bin/env python3
# BotHub Firebase worker: auto-registers this device using Firebase Anonymous Auth.
import os,sys,json,time,socket,platform,shutil,subprocess,urllib.parse,uuid,signal
from pathlib import Path
try:
    import fcntl
except ImportError:
    fcntl=None
import requests

ROOT=Path(__file__).resolve().parent
ROOT.mkdir(parents=True,exist_ok=True)
CFGFILE=ROOT/"worker.json"
TOKFILE=ROOT/"firebase-token.json"
API_KEY="AIzaSyDS_KvyPWGgzYqIVgkagw5DAwzlenNZtiE"
DB="https://bothub-bca02-default-rtdb.firebaseio.com"
PROCS={};LOGS={};S=requests.Session();WORKER_STARTED=time.time();WORKER_LOCK_HANDLE=None
LOCKFILE=ROOT/".bothub-worker.lock"

def save_json(path,data):
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(data,ensure_ascii=False),encoding="utf-8")
    tmp.replace(path)
    try:path.chmod(0o600)
    except OSError:pass

def setup():
    if CFGFILE.exists():
        try:
            cfg=json.loads(CFGFILE.read_text(encoding="utf-8"))
            if cfg.get("device_id"):return cfg
        except Exception:pass
    # A local random ID is generated automatically; no ID/email/password prompt.
    cfg={"device_id":"device-"+uuid.uuid4().hex[:16],"createdAt":int(time.time()*1000)}
    save_json(CFGFILE,cfg)
    print("[BotHub] ID automático criado:",cfg["device_id"],flush=True)
    return cfg

def token(cfg):
    cached={}
    if TOKFILE.exists():
        try:cached=json.loads(TOKFILE.read_text(encoding="utf-8"))
        except Exception:cached={}
    if cached.get("idToken") and time.time()<float(cached.get("expires",0))-120:
        return cached["idToken"]
    refresh=cached.get("refreshToken")
    if refresh:
        try:
            r=S.post("https://securetoken.googleapis.com/v1/token",
                params={"key":API_KEY},
                data={"grant_type":"refresh_token","refresh_token":refresh},timeout=20)
            r.raise_for_status();d=r.json()
            t={"idToken":d["id_token"],"refreshToken":d.get("refresh_token",refresh),
               "uid":d.get("user_id",cached.get("uid")),
               "expires":time.time()+int(d.get("expires_in",3600))}
            save_json(TOKFILE,t)
            if t.get("uid") and cfg.get("uid")!=t["uid"]:
                cfg["uid"]=t["uid"];save_json(CFGFILE,cfg)
            return t["idToken"]
        except Exception as e:
            print("[BotHub] Renovação da sessão falhou; tentando autenticar novamente:",str(e)[:160],flush=True)
    # Firebase Console must have Authentication > Sign-in method > Anonymous enabled.
    r=S.post("https://identitytoolkit.googleapis.com/v1/accounts:signUp",
        params={"key":API_KEY},json={"returnSecureToken":True},timeout=20)
    if r.status_code>=400:
        detail=r.text[:350]
        if "OPERATION_NOT_ALLOWED" in detail or "ADMIN_ONLY_OPERATION" in detail:
            raise RuntimeError("Ative Firebase Authentication > Sign-in method > Anonymous uma única vez no projeto BotHub.")
        raise RuntimeError("Falha na autenticação anônima Firebase: HTTP "+str(r.status_code)+" "+detail)
    d=r.json()
    t={"idToken":d["idToken"],"refreshToken":d["refreshToken"],"uid":d["localId"],
       "expires":time.time()+int(d.get("expiresIn",3600))}
    save_json(TOKFILE,t)
    cfg["uid"]=d["localId"]
    save_json(CFGFILE,cfg)
    return t["idToken"]

def fb(method,path,tok,data=None):
    r=S.request(method,DB+"/"+path.strip("/")+".json",params={"auth":tok},json=data,timeout=20)
    if r.status_code>=300:raise RuntimeError("Firebase "+str(r.status_code)+": "+r.text[:220])
    return r.json() if r.text else None

def stats(cfg):
    d=shutil.disk_usage(str(ROOT))
    running=[k for k,p in PROCS.items() if p.poll() is None]
    x={"deviceId":cfg["device_id"],"uid":cfg.get("uid",""),"hostname":socket.gethostname(),
       "label":socket.gethostname(),"platform":platform.platform(),"diskFreeBytes":d.free,
       "diskTotalBytes":d.total,"cpuCount":os.cpu_count() or 1,"runningBots":len(running),
       "runningBotIds":running,"lastSeen":int(time.time()*1000),
       "uptimeSeconds":int(time.time()-WORKER_STARTED),
       "workerUptimeSeconds":int(time.time()-WORKER_STARTED),
       "workerStartedAt":int(WORKER_STARTED*1000)}
    try:x["uptimeSeconds"]=int(float(Path("/proc/uptime").read_text().split()[0]))
    except Exception:pass
    try:x["publicIp"]=S.get("https://api.ipify.org?format=json",timeout=4).json().get("ip","")
    except Exception:x["publicIp"]=""
    try:
        import psutil
        m=psutil.virtual_memory()
        x.update(ramFreeBytes=m.available,ramTotalBytes=m.total,cpuPercent=psutil.cpu_percent(.1),
                 cpuCount=psutil.cpu_count() or (os.cpu_count() or 1))
    except Exception:
        try:
            mem={}
            for line in Path("/proc/meminfo").read_text().splitlines():
                key,value=line.split(":",1);parts=value.strip().split()
                if parts and parts[0].isdigit():
                    mem[key]=int(parts[0])*(1024 if len(parts)>1 and parts[1].lower()=="kb" else 1)
            total=mem.get("MemTotal",0)
            available=mem.get("MemAvailable",mem.get("MemFree",0)+mem.get("Buffers",0)+mem.get("Cached",0))
            x.update(ramFreeBytes=available,ramTotalBytes=total,cpuPercent=0,cpuCount=os.cpu_count() or 1)
        except Exception:x.update(ramFreeBytes=0,ramTotalBytes=0,cpuPercent=0,cpuCount=os.cpu_count() or 1)
    return x

def sid(v):
    return "".join(c for c in str(v) if c.isalnum() or c in "-_")[:80] or "bot"

def stop(k):
    p=PROCS.pop(k,None);l=LOGS.pop(k,None)
    if p and p.poll() is None:
        try:
            if os.name!="nt" and getattr(p,"pid",None):
                os.killpg(p.pid,signal.SIGTERM)
            else:
                p.terminate()
            p.wait(timeout=5)
        except Exception:
            try:
                if os.name!="nt" and getattr(p,"pid",None):
                    os.killpg(p.pid,signal.SIGKILL)
                else:
                    p.kill()
            except Exception:pass
    try:
        (ROOT/"bots"/sid(k)/".bothub.pid").unlink(missing_ok=True)
    except Exception:pass
    if l:
        try:l.close()
        except Exception:pass

def start(k,b):
    folder=ROOT/"bots"/sid(k);folder.mkdir(parents=True,exist_ok=True);script=folder/"main.py"
    if not script.exists():
        url=os.getenv("BOTHUB_BOT_SOURCE_URL","https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/main.py")
        r=S.get(url,timeout=30);r.raise_for_status()
        if len(r.content)<10000:raise RuntimeError("Download de main.py incompleto.")
        script.write_bytes(r.content)
    cfg=dict(b.get("config") or {});cfg["discord_token"]=b["token"]
    cp=folder/"config.json";save_json(cp,cfg)
    if k in PROCS and PROCS[k].poll() is None:return
    log=open(folder/"bot.log","ab",buffering=0)
    p=subprocess.Popen([sys.executable,"-u",str(script)],cwd=str(folder),stdin=subprocess.DEVNULL,
        stdout=log,stderr=subprocess.STDOUT,start_new_session=(os.name!="nt"))
    PROCS[k]=p;LOGS[k]=log
    try:(folder/".bothub.pid").write_text(str(p.pid),encoding="utf-8")
    except OSError:pass
    print("[BotHub] iniciado",b.get("name",k),"PID",p.pid,flush=True)


# File manager seguro: somente a pasta do bot selecionado; sem shell arbitrário.
EDITABLE_EXTS={".py",".txt",".md",".json",".html",".css",".js",".yaml",".yml",".toml",".ini",".sh"}
BLOCKED_NAMES={"config.json","firebase-token.json","worker.json","bot.log",".env"}
BLOCKED_DIRS={"venv",".venv","__pycache__",".git","node_modules"}

def bot_folder(bot_id):
    base=(ROOT/"bots"/sid(bot_id)).resolve()
    root=(ROOT/"bots").resolve()
    if root not in base.parents:
        raise ValueError("ID de bot inválido.")
    return base

def private_file_name(name):
    lower=str(name).lower()
    return lower in BLOCKED_NAMES or any(part in lower for part in
        ("token","secret","credential","apikey","api_key","private_key","password")) or lower.endswith(".env")

def safe_file_path(bot_id, relative, allow_directory=False):
    base=bot_folder(bot_id)
    raw=str(relative or "").replace("\\\\","/")
    parts=[p for p in raw.split("/") if p not in ("",".")]
    if any(p==".." or p.startswith(".") for p in parts):
        raise ValueError("Caminho inválido.")
    if parts and parts[0] in BLOCKED_DIRS:
        raise ValueError("Essa pasta é protegida.")
    path=base.joinpath(*parts).resolve()
    if path!=base and base not in path.parents:
        raise ValueError("Caminho fora da pasta do bot.")
    if private_file_name(path.name):
        raise ValueError("Esse arquivo contém dados privados e não pode ser aberto pelo painel.")
    if path.is_file() or (not path.exists() and not allow_directory):
        if path.suffix.lower() not in EDITABLE_EXTS:
            raise ValueError("Tipo de arquivo não permitido.")
    return base,path

def file_command(cmd):
    op=cmd.get("operation");bid=str(cmd.get("botId",""));relative=str(cmd.get("path",""))
    if op=="logs":
        base=bot_folder(bid)
        log_path=base/"bot.log"
        if not log_path.exists(): return {"botId":bid,"logs":"Ainda não existe log para este bot."}
        with log_path.open("rb") as handle:
            handle.seek(0,os.SEEK_END);size=handle.tell()
            handle.seek(max(0,size-24000),os.SEEK_SET)
            data=handle.read(24000)
        text=data.decode("utf-8",errors="replace")
        return {"botId":bid,"logs":text[-18000:],"truncated":size>24000,"size":size}
    base,path=safe_file_path(bid,relative,allow_directory=(op=="list"))
    if not base.exists():
        raise FileNotFoundError("A pasta deste bot ainda não existe neste worker.")
    if op=="list":
        if not path.exists(): path.mkdir(parents=True,exist_ok=True)
        if not path.is_dir(): raise ValueError("O caminho não é uma pasta.")
        items=[]
        for p in sorted(path.iterdir(),key=lambda x:(not x.is_dir(),x.name.lower())):
            if p.name.startswith(".") or private_file_name(p.name) or p.name in BLOCKED_DIRS: continue
            if p.is_file() and p.suffix.lower() not in EDITABLE_EXTS: continue
            try:
                items.append({"name":p.name,"path":p.relative_to(base).as_posix(),"directory":p.is_dir(),
                              "size":p.stat().st_size if p.is_file() else 0})
            except OSError: pass
        return {"path":relative,"items":items[:300]}
    if op=="read":
        if not path.is_file(): raise FileNotFoundError("Arquivo não encontrado.")
        if path.stat().st_size>256*1024: raise ValueError("Arquivo maior que 256 KiB; edição pelo painel bloqueada.")
        data=path.read_bytes()
        try: content=data.decode("utf-8")
        except UnicodeDecodeError: raise ValueError("O arquivo não é texto UTF-8.")
        return {"path":relative,"content":content,"size":len(data)}
    if op=="write":
        content=cmd.get("content","")
        if not isinstance(content,str) or len(content.encode("utf-8"))>256*1024:
            raise ValueError("O conteúdo deve ter no máximo 256 KiB.")
        if path.exists() and not path.is_file(): raise ValueError("O destino não é um arquivo.")
        path.parent.mkdir(parents=True,exist_ok=True)
        tmp=path.with_suffix(path.suffix+".tmp")
        tmp.write_text(content,encoding="utf-8")
        tmp.replace(path)
        return {"path":relative,"size":path.stat().st_size,"saved":True}
    if op=="delete":
        if not path.is_file(): raise FileNotFoundError("Arquivo não encontrado.")
        path.unlink()
        return {"path":relative,"deleted":True}
    if op=="restart":
        stop(sid(bid))
        return {"botId":bid,"restarted":True}
    raise ValueError("Operação não reconhecida.")

def discord_api(token_value, method, endpoint, payload):
    response=S.request(method,"https://discord.com/api/v10"+endpoint,
        headers={"Authorization":"Bot "+token_value,"Content-Type":"application/json"},
        json=payload,timeout=30)
    try: body=response.json()
    except Exception: body={"message":response.text[:250]}
    if response.status_code>=300:
        raise RuntimeError("Discord HTTP "+str(response.status_code)+": "+str(body.get("message","falha"))[:180])
    return body

def process_worker_commands(cfg,tok,did,queue):
    commands=fb("GET","workerCommands/"+did,tok) or {}
    if not isinstance(commands,dict): return
    for request_id,cmd in list(commands.items())[:5]:
        if not isinstance(cmd,dict): continue
        result={"id":request_id,"updatedAt":int(time.time()*1000)}
        try:
            op=cmd.get("operation")
            if op=="profile":
                bid=str(cmd.get("botId",""))
                bot_cfg=queue.get(bid) if isinstance(queue,dict) else None
                secret=bot_cfg.get("token") if isinstance(bot_cfg,dict) else None
                if not secret: raise ValueError("O bot não está atribuído a este worker ou não tem token.")
                changes={};name=cmd.get("name");avatar=cmd.get("avatarDataUrl");description=cmd.get("description")
                if name:
                    changes["username"]=str(name)[:32]
                if avatar:
                    if not isinstance(avatar,str) or not avatar.startswith(("data:image/png;base64,","data:image/jpeg;base64,")):
                        raise ValueError("Avatar inválido: use PNG ou JPEG.")
                    if len(avatar)>6*1024*1024: raise ValueError("A imagem é muito grande (limite 4,5 MB).")
                    changes["avatar"]=avatar
                if changes:
                    discord_api(secret,"PATCH","/users/@me",changes)
                if description is not None:
                    if len(str(description))>400: raise ValueError("A descrição deve ter até 400 caracteres.")
                    discord_api(secret,"PATCH","/applications/@me",{"description":str(description)})
                result.update(status="ok",message="Perfil atualizado.",nameChanged=bool(name),avatarChanged=bool(avatar),descriptionChanged=description is not None)
            else:
                result.update(status="ok",result=file_command(cmd))
        except Exception as e:
            result.update(status="error",message=str(e)[:350])
        try:
            fb("PUT","workerResults/"+did+"/"+urllib.parse.quote(str(request_id),safe=""),tok,result)
            fb("DELETE","workerCommands/"+did+"/"+urllib.parse.quote(str(request_id),safe=""),tok)
        except Exception as e:
            print("[BotHub] Não foi possível publicar o resultado do comando:",str(e)[:180],flush=True)

def acquire_single_worker():
    global WORKER_LOCK_HANDLE
    LOCKFILE.parent.mkdir(parents=True,exist_ok=True)
    WORKER_LOCK_HANDLE=LOCKFILE.open("a+")
    if fcntl is not None:
        try:
            fcntl.flock(WORKER_LOCK_HANDLE.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print("[BotHub] Já existe um worker nesta pasta; encerrando para evitar processos duplicados.",flush=True)
            raise SystemExit(73)

def main():
    acquire_single_worker()
    cfg=setup()
    v=ROOT/"venv";vp=v/("Scripts/python.exe" if os.name=="nt" else "bin/python")
    if not vp.exists():
        subprocess.check_call([sys.executable,"-m","venv",str(v)])
        subprocess.check_call([str(vp),"-m","pip","install","--upgrade","pip"])
        subprocess.check_call([str(vp),"-m","pip","install","requests","discord.py","aiohttp"])
        os.execv(str(vp),[str(vp),str(Path(__file__).resolve())])
    print("[BotHub] Worker iniciado sem pedir ID, e-mail ou senha.",flush=True)
    while True:
        try:
            t=token(cfg);did=urllib.parse.quote(cfg["device_id"],safe="")
            fb("PUT","workers/"+did,t,stats(cfg))
            queue=fb("GET","workerTasks/"+did,t) or {}
            process_worker_commands(cfg,t,did,queue)
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
