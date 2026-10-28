#!/usr/bin/env python3
# BotHub Firebase worker: auto-registers this device using Firebase Anonymous Auth.
import os,sys,json,time,socket,platform,shutil,subprocess,urllib.parse,uuid,signal,atexit
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parent
ROOT.mkdir(parents=True,exist_ok=True)
CFGFILE=ROOT/"worker.json"
TOKFILE=ROOT/"firebase-token.json"
API_KEY="AIzaSyDS_KvyPWGgzYqIVgkagw5DAwzlenNZtiE"
DB="https://bothub-bca02-default-rtdb.firebaseio.com"
PROCS={};LOGS={};S=requests.Session();WORKER_STARTED=time.time();CURRENT_CFG=None

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

def fb(method,path,tok,data=None,_retried=False):
    r=S.request(method,DB+"/"+path.strip("/")+".json",params={"auth":tok},json=data,timeout=20)
    if r.status_code==401 and not _retried:
        detail=r.text[:300]
        low=detail.lower()
        # Reautentica apenas quando o Firebase indica token inválido/expirado.
        if any(term in low for term in ("expired","invalid token","invalid_token","auth token","id token")) and CURRENT_CFG is not None:
            try:
                if TOKFILE.exists(): TOKFILE.unlink()
                fresh=token(CURRENT_CFG)
                print("[BotHub] Token rejeitado pelo Firebase; sessão renovada, repetindo a solicitação uma vez.",flush=True)
                return fb(method,path,fresh,data,_retried=True)
            except Exception as e:
                raise RuntimeError("Firebase recusou a sessão (401) e a renovação falhou: "+str(e)[:180])
        raise RuntimeError("Firebase HTTP 401: "+detail+" | Confira Authentication > Anonymous e as regras de leitura/gravação do Realtime Database para usuários autenticados.")
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
        try:p.terminate();p.wait(timeout=5)
        except Exception:
            try:p.kill()
            except Exception:pass
    if l:
        try:l.close()
        except Exception:pass

def child_parent_death_signal():
    """Linux: encerra o bot se o controlador morrer abruptamente."""
    if not sys.platform.startswith("linux"):
        return
    try:
        import ctypes
        libc = ctypes.CDLL(None)
        PR_SET_PDEATHSIG = 1
        libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
        # Fecha a pequena janela em que o pai pode morrer antes de prctl.
        if os.getppid() == 1:
            os.kill(os.getpid(), signal.SIGTERM)
    except Exception:
        pass

def cleanup_children():
    for key in list(PROCS):
        stop(key)

def handle_shutdown_signal(signum, frame):
    print("[BotHub] Controlador sendo desligado; encerrando todos os main.py...", flush=True)
    cleanup_children()
    raise SystemExit(0)

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
    popen_kwargs = {}
    if sys.platform.startswith("linux"):
        popen_kwargs["preexec_fn"] = child_parent_death_signal
    p=subprocess.Popen([sys.executable,"-u",str(script)],cwd=str(folder),stdin=subprocess.DEVNULL,
        stdout=log,stderr=subprocess.STDOUT,start_new_session=(os.name!="nt"),**popen_kwargs)
    PROCS[k]=p;LOGS[k]=log
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

def download_latest_main(folder):
    url=os.getenv("BOTHUB_BOT_SOURCE_URL","https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/main.py")
    response=S.get(url,timeout=45);response.raise_for_status()
    data=response.content
    if len(data)<10000: raise RuntimeError("main.py baixado está incompleto.")
    compile(data.decode("utf-8"),"main.py","exec")
    target=folder/"main.py";tmp=folder/"main.py.update.tmp"
    tmp.write_bytes(data);tmp.replace(target)
    return len(data)

def notify_update(bot_id, bot_cfg, update):
    token_value=bot_cfg.get("token")
    if not token_value:return
    try:
        app_info=discord_api(token_value,"GET","/applications/@me",None)
        owner=(app_info.get("owner") or {}).get("id")
        if not owner:return
        channel=discord_api(token_value,"POST","/users/@me/channels",{"recipient_id":str(owner)})
        mode="OBRIGATÓRIA" if update.get("type")=="mandatory" else "OPCIONAL"
        description=str(update.get("description") or "Melhorias e correções.")[:1500]
        content=("📦 **Atualização BotHub disponível — "+mode+"**\n"+description+
                 ("\n\nEsta atualização será instalada automaticamente." if mode=="OBRIGATÓRIA"
                  else "\n\nPara instalar, digite !update neste chat com o bot."))
        discord_api(token_value,"POST","/channels/"+str(channel["id"])+"/messages",
                    {"content":content,"allowed_mentions":{"parse":[]}})
    except Exception as e:
        print("[BotHub] Não foi possível avisar o criador de",bot_id,":",str(e)[:180],flush=True)

def process_release_updates(tok, queue):
    release=fb("GET","botHubUpdates/current",tok)
    if not isinstance(release,dict) or not release.get("updateId"):return
    for raw_id,bot_cfg in list(queue.items()):
        if not isinstance(bot_cfg,dict) or not bot_cfg.get("enabled",True):continue
        bid=sid(raw_id);folder=ROOT/"bots"/bid
        if not folder.exists():continue
        state_file=folder/".bothub_update_state.json"
        try:state=json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
        except Exception:state={}
        update_id=str(release.get("updateId"))
        if state.get("updateId")!=update_id:
            notify_update(raw_id,bot_cfg,release)
            state={"updateId":update_id,"announced":True,"updated":False}
            save_json(state_file,state)
        request_file=folder/".bothub_update_request"
        mandatory=release.get("type")=="mandatory"
        accepted=request_file.exists()
        if state.get("updateId")==update_id and state.get("updated"):continue
        if not mandatory and not accepted:continue
        try:
            stop(bid)
            size=download_latest_main(folder)
            start(bid,bot_cfg)
            state.update(updateId=update_id,announced=True,updated=True,updatedAt=int(time.time()*1000),bytes=size)
            save_json(state_file,state)
            if request_file.exists():request_file.unlink()
            print("[BotHub] bot atualizado:",raw_id,"bytes:",size,flush=True)
        except Exception as e:
            print("[BotHub] falha ao atualizar",raw_id,":",str(e)[:220],flush=True)
            try:
                if bid not in PROCS or PROCS[bid].poll() is not None:start(bid,bot_cfg)
            except Exception:pass


CLUSTER_UPDATE_URLS={
    "add_cluster_server.py":"https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/add_cluster_server.py",
    "bothub_firebase_worker.py":"https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/bothub_firebase_worker.py",
}

def process_cluster_update(tok):
    """Em atualização obrigatória, baixa o instalador e o worker diretamente do GitHub."""
    release=fb("GET","botHubUpdates/current",tok)
    if not isinstance(release,dict) or not release.get("updateId") or release.get("type")!="mandatory":
        return False
    update_id=str(release.get("updateId"))
    state_path=ROOT/".bothub_cluster_update_state.json"
    try: state=json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    except Exception: state={}
    if state.get("updateId")==update_id and state.get("status") in ("applied","installing"):
        return False

    clean={}
    for name,url in CLUSTER_UPDATE_URLS.items():
        response=S.get(url,timeout=45)
        response.raise_for_status()
        data=response.content
        if len(data)<1000:
            raise RuntimeError("Download incompleto de "+name)
        source=data.decode("utf-8")
        compile(source,name,"exec")
        clean[name]=source

    pending=ROOT/".bothub_cluster_update_pending.json"
    save_json(pending,{"updateId":update_id,"files":clean})
    helper="""import json,os,sys,time,subprocess
from pathlib import Path
parent=int(sys.argv[1]);root=Path(sys.argv[2]).resolve();py=sys.argv[3]
pending=root/".bothub_cluster_update_pending.json"
state=root/".bothub_cluster_update_state.json"
allowed={"add_cluster_server.py","bothub_firebase_worker.py"}
def alive(pid):
    try: os.kill(pid,0); return True
    except OSError: return False
deadline=time.time()+90
while alive(parent) and time.time()<deadline: time.sleep(.5)
if alive(parent):
    try: os.kill(parent,15)
    except OSError: pass
    time.sleep(2)
data=json.loads(pending.read_text(encoding="utf-8"))
for name,source in data.get("files",{}).items():
    if name not in allowed or not isinstance(source,str): raise RuntimeError("Arquivo não permitido")
    compile(source,name,"exec")
    target=root/name;tmp=root/(name+".cluster-update.tmp")
    tmp.write_text(source,encoding="utf-8");tmp.replace(target)
venvpy=root/"venv"/("Scripts/python.exe" if os.name=="nt" else "bin/python")
if not venvpy.exists(): venvpy=Path(py)
state.write_text(json.dumps({"updateId":data.get("updateId"),"status":"applied","appliedAt":int(time.time()*1000)}),encoding="utf-8")
pending.unlink(missing_ok=True)
installer=root/"add_cluster_server.py"
if not installer.exists():
    raise RuntimeError("Instalador atualizado não foi encontrado; não é possível reiniciar a instalação.")
os.execv(str(venvpy),[str(venvpy),str(installer)])
"""
    helper_path=ROOT/".bothub_cluster_updater.py"
    helper_path.write_text(helper,encoding="utf-8")
    save_json(state_path,{"updateId":update_id,"status":"installing","requestedAt":int(time.time()*1000)})
    print("[BotHub] Atualização obrigatória: baixando add_cluster_server.py e bothub_firebase_worker.py do GitHub; reiniciando controlador.",flush=True)
    subprocess.Popen([sys.executable,str(helper_path),str(os.getpid()),str(ROOT),sys.executable],
        cwd=str(ROOT),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        start_new_session=(os.name!="nt"))
    return True

def acquire_worker_lock():
    """Impede dois controladores de iniciarem os mesmos bots nesta instalação."""
    lock_path = ROOT / ".bothub_worker.lock"
    handle = open(lock_path, "a+", encoding="utf-8")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            if lock_path.stat().st_size == 0:
                handle.write("0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError):
        handle.close()
        return None
    return handle

def main():
    global CURRENT_CFG
    cfg=setup()
    CURRENT_CFG=cfg
    v=ROOT/"venv";vp=v/("Scripts/python.exe" if os.name=="nt" else "bin/python")
    if not vp.exists():
        subprocess.check_call([sys.executable,"-m","venv",str(v)])
        subprocess.check_call([str(vp),"-m","pip","install","--upgrade","pip"])
        subprocess.check_call([str(vp),"-m","pip","install","requests","discord.py","aiohttp"])
        os.execv(str(vp),[str(vp),str(Path(__file__).resolve())])
    lock_handle = acquire_worker_lock()
    if lock_handle is None:
        print("[BotHub] Já existe um controlador rodando nesta pasta. Este processo será encerrado para evitar bots duplicados.", flush=True)
        return
    signal.signal(signal.SIGTERM, handle_shutdown_signal)
    signal.signal(signal.SIGINT, handle_shutdown_signal)
    atexit.register(cleanup_children)
    print("[BotHub] Worker iniciado sem pedir ID, e-mail ou senha.",flush=True)
    while True:
        try:
            t=token(cfg);did=urllib.parse.quote(cfg["device_id"],safe="")
            fb("PUT","workers/"+did,t,stats(cfg))
            queue=fb("GET","workerTasks/"+did,t) or {}
            process_worker_commands(cfg,t,did,queue)
            # Uma conta Discord (token) só pode ter uma instância ativa neste worker.
            # Se o painel atribuir o mesmo token a IDs/pastas diferentes, manter apenas a primeira.
            desired={}
            token_owner={}
            duplicate_ids=set()
            for raw_id,b in queue.items():
                if not isinstance(b,dict) or not b.get("enabled",True):
                    continue
                k=sid(raw_id)
                secret=str(b.get("token") or "").strip()
                if not secret:
                    print("[BotHub] bot sem token ignorado:",k,flush=True)
                    continue
                if secret in token_owner:
                    duplicate_ids.add(k)
                    print("[BotHub] token duplicado detectado; não inicia a segunda pasta:",k,
                          "(a conta já está atribuída a",token_owner[secret]+")",flush=True)
                    continue
                token_owner[secret]=k
                desired[k]=b
            for k in list(PROCS):
                if k not in desired or k in duplicate_ids:
                    stop(k)
                    print("[BotHub] parado para evitar instância duplicada:",k,flush=True)
            for k,b in desired.items():
                if k not in PROCS or PROCS[k].poll() is not None:
                    try:start(k,b)
                    except Exception as e:print("[BotHub] falha no bot",k,str(e)[:220],flush=True)
            try:
                if process_cluster_update(t):
                    break
            except Exception as e: print("[BotHub] falha ao atualizar arquivos de cluster:",str(e)[:220],flush=True)
            try: process_release_updates(t,queue)
            except Exception as e: print("[BotHub] falha ao verificar atualização:",str(e)[:220],flush=True)
        except KeyboardInterrupt:break
        except Exception as e:print("[BotHub] erro Firebase/worker:",str(e)[:300],flush=True)
        time.sleep(max(10,int(os.getenv("BOTHUB_POLL_SECONDS","15"))))
    cleanup_children()

if __name__=="__main__":
    try:main()
    except Exception as e:print("Erro fatal:",e,file=sys.stderr);raise
