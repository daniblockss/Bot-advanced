#!/usr/bin/env python3
# BotHub Firebase worker: auto-registers this device using Firebase Anonymous Auth.
import os,sys,json,time,socket,platform,shutil,subprocess,urllib.parse,uuid,signal,atexit,base64,hashlib,sqlite3
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parent
ROOT.mkdir(parents=True,exist_ok=True)
CFGFILE=ROOT/"worker.json"
TOKFILE=ROOT/"firebase-token.json"
API_KEY="AIzaSyDS_KvyPWGgzYqIVgkagw5DAwzlenNZtiE"
DB="https://bothub-bca02-default-rtdb.firebaseio.com"
PROCS={};LOGS={};CLEAN_EXITED={};S=requests.Session();WORKER_STARTED=time.time();CURRENT_CFG=None
LAST_TOKEN=None;LAST_DID=None;LAST_QUEUE={};SHUTDOWN_IN_PROGRESS=False

WORKER_VERSION="2026.11.13.4"

def runtime_environment():
    """Identifica o ambiente real sem confundir Android/Termux com Linux comum."""
    prefix=os.environ.get("PREFIX","")
    home=str(Path.home()).lower()
    android=("ANDROID_ROOT" in os.environ or "ANDROID_DATA" in os.environ
             or "/data/data/" in prefix.lower() or "/data/data/com.termux" in home)
    if android and ("com.termux" in prefix.lower() or "com.termux" in home):
        runtime="Termux"
    elif android:
        runtime="Android"
    elif os.name=="nt":
        runtime="Windows"
    elif sys.platform=="darwin":
        runtime="macOS"
    elif sys.platform.startswith("linux"):
        runtime="Linux"
    else:
        runtime=platform.system() or "Desconhecido"
    command=shutil.which("termux-battery-status")
    if not command and prefix:
        candidate=Path(prefix)/"bin"/"termux-battery-status"
        if candidate.is_file():command=str(candidate)
    return runtime,command

def battery_stats(command):
    """Lê a bateria pelo Termux:API; em outros sistemas informa ausência real."""
    result={"batteryPresent":False,"batteryPercent":None,"batteryStatus":"unknown",
            "batteryPlugged":False,"batteryPluggedType":None,"batteryTemperatureC":None,
            "batteryHealth":None,"batteryVoltageMv":None,"batteryCurrentUa":None}
    if not command:
        try:
            import psutil
            battery=psutil.sensors_battery()
            if battery is not None and battery.percent is not None:
                plugged=bool(battery.power_plugged)
                result.update(batteryPresent=True,batteryPercent=round(float(battery.percent),1),
                              batteryStatus=("charging" if plugged else "discharging"),
                              batteryPlugged=plugged,
                              batteryPluggedType=("PLUGGED_AC" if plugged else "UNPLUGGED"))
            return result
        except Exception:return result
    try:
        proc=subprocess.run([command],capture_output=True,text=True,timeout=3,
                            stdin=subprocess.DEVNULL)
        if proc.returncode!=0:return result
        raw=json.loads(proc.stdout or "{}")
        if not isinstance(raw,dict) or "percentage" not in raw:return result
        pct=float(raw.get("percentage"))
        if not 0<=pct<=100:return result
        status=str(raw.get("status") or "unknown").strip().lower().replace(" ","_")
        status_map={"charging":"charging","discharging":"discharging","full":"full",
                    "not_charging":"not_charging","unknown":"unknown"}
        plugged_raw=raw.get("plugged")
        plugged_type=(str(plugged_raw).strip().upper() if plugged_raw is not None and not isinstance(plugged_raw,bool) else None)
        plugged=(plugged_type not in (None,"UNPLUGGED","NONE","UNKNOWN"))
        if isinstance(plugged_raw,bool):plugged=plugged_raw
        elif isinstance(plugged_raw,str) and plugged_raw.upper() in ("TRUE","FALSE"):
            plugged=plugged_raw.upper()=="TRUE";plugged_type=None
        result.update(batteryPresent=True,batteryPercent=round(pct,1),
                      batteryStatus=status_map.get(status,"unknown"),
                      batteryPlugged=plugged,batteryPluggedType=plugged_type,
                      batteryHealth=str(raw.get("health") or "") or None)
        for source,target,divisor in (("temperature","batteryTemperatureC",1),
                                      ("voltage","batteryVoltageMv",1),
                                      ("current","batteryCurrentUa",1)):
            value=raw.get(source)
            if isinstance(value,(int,float)) and not isinstance(value,bool):
                result[target]=value/divisor
        return result
    except (OSError,subprocess.SubprocessError,ValueError,TypeError,json.JSONDecodeError):
        return result

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
            if cfg.get("device_id"):
                original=str(cfg["device_id"])
                safe_id="".join(c for c in original if c.isalnum() or c in "-_")[:80]
                if not safe_id:
                    safe_id="device-"+uuid.uuid4().hex[:16]
                if safe_id != original:
                    print("[BotHub] ID antigo do worker continha caracteres inválidos para o Firebase; ID normalizado.",flush=True)
                    cfg["device_id"]=safe_id
                    save_json(CFGFILE,cfg)
                return cfg
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
    if r.status_code>=300:
        raise RuntimeError("Firebase "+str(r.status_code)+" em "+method+" "+path+": "+r.text[:220])
    return r.json() if r.text else None

def stats(cfg):
    d=shutil.disk_usage(str(ROOT))
    running=[k for k,p in PROCS.items() if p.poll() is None]
    ready=[k for k in running if (ROOT/"bots"/sid(k)/".bothub_discord_ready").is_file()]
    runtime, battery_command=runtime_environment()
    x={"deviceId":cfg["device_id"],"uid":cfg.get("uid",""),"hostname":socket.gethostname(),
       "label":socket.gethostname(),"platform":platform.platform(),"runtimeType":runtime,
       "termuxApiInstalled":bool(battery_command) if runtime=="Termux" else None,
       "workerVersion":WORKER_VERSION,"architecture":platform.machine(),
       "pythonVersion":platform.python_version(),"diskFreeBytes":d.free,
       "diskTotalBytes":d.total,"cpuCount":os.cpu_count() or 1,"runningBots":len(running),
       "runningBotIds":running,"readyBotIds":ready,"lastSeen":int(time.time()*1000),
       "uptimeSeconds":int(time.time()-WORKER_STARTED),
       "workerUptimeSeconds":int(time.time()-WORKER_STARTED),
       "workerStartedAt":int(WORKER_STARTED*1000)}
    x.update(battery_stats(battery_command))
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

def clean_exit_state(k, requested_at=None):
    """Aplica uma pausa temporária após saída limpa; nunca deixa o bot parado para sempre."""
    path=ROOT/"bots"/sid(k)/".bothub_clean_exit.json"
    try:
        data=json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        saved=float(data.get("startRequestedAt") or 0)
        current=float(requested_at or 0)
        if requested_at is not None and current > saved:
            path.unlink(missing_ok=True)
            return None
        retry_after=float(data.get("retryAfter") or 0)
        if retry_after > time.time():
            return saved
        path.unlink(missing_ok=True)
    except Exception:
        pass
    return None

def mark_clean_exit(k, requested_at, code=0):
    folder=ROOT/"bots"/sid(k)
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/".bothub_clean_exit.json"
    try:
        previous=json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        previous={}
    same_request=float(previous.get("startRequestedAt") or 0)==float(requested_at or 0)
    attempts=int(previous.get("attempts") or 0)+1 if same_request else 1
    delay=min(300,30*(2**min(attempts-1,4)))
    retry_after=time.time()+delay
    save_json(path,{
        "startRequestedAt":float(requested_at or 0),
        "exitCode":int(code),
        "exitedAt":int(time.time()*1000),
        "attempts":attempts,
        "retryAfter":retry_after,
        "retryDelaySeconds":delay
    })
    CLEAN_EXITED[k]=float(requested_at or 0)
    print("[BotHub] bot encerrou com código 0; nova tentativa em",delay,"segundos (tentativa",attempts,"):",k,flush=True)

def stop(k):
    p=PROCS.pop(k,None);l=LOGS.pop(k,None)
    try:(ROOT/"bots"/sid(k)/".bothub_discord_ready").unlink(missing_ok=True)
    except OSError:pass
    if p and p.poll() is None:
        try:
            if os.name != "nt" and p.pid:
                os.killpg(p.pid, signal.SIGTERM)
            else:
                p.terminate()
            p.wait(timeout=5)
        except Exception:
            try:
                if os.name != "nt" and p.pid:
                    os.killpg(p.pid, getattr(signal,"SIGKILL",signal.SIGTERM))
                else:
                    p.kill()
            except Exception:
                try:p.kill()
                except Exception:pass
            try:p.wait(timeout=2)
            except Exception:pass
    if l:
        try:l.close()
        except Exception:pass

def stop_bot_processes(bot_id):
    """Encerra o script exato deste bot (IA, Standard ou Admin), mesmo se estiver órfão."""
    folder = (ROOT / "bots" / sid(bot_id)).resolve()
    targets = {(folder / name).resolve() for name in ("main.py", "standard_main.py", "bot_admin.py")}
    current_pid = os.getpid()
    found = []
    if os.name != "nt" and Path("/proc").is_dir():
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit() or int(entry.name) == current_pid:
                continue
            try:
                raw = (entry / "cmdline").read_bytes()
                args = [part.decode("utf-8", errors="ignore") for part in raw.split(b"\0") if part]
                if any(arg.endswith(".py") and Path(arg).resolve() in targets for arg in args[1:]):
                    found.append(int(entry.name))
            except (OSError, ValueError, RuntimeError):
                continue
    else:
        try:
            import psutil
            for proc in psutil.process_iter(["pid", "cmdline"]):
                pid = proc.info.get("pid")
                if not pid or pid == current_pid:
                    continue
                for arg in (proc.info.get("cmdline") or [])[1:]:
                    try:
                        if arg.endswith(".py") and Path(arg).resolve() in targets:
                            found.append(pid)
                            break
                    except (OSError, ValueError, RuntimeError):
                        continue
        except Exception as e:
            print("[BotHub] Não foi possível localizar o processo do bot", bot_id, str(e)[:140], flush=True)
    for pid in sorted(set(found)):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.time() + 4
    remaining = set(found)
    while remaining and time.time() < deadline:
        remaining = {pid for pid in remaining if Path("/proc").exists() and Path("/proc", str(pid)).exists()}
        if remaining:
            time.sleep(0.2)
    for pid in remaining:
        try:
            os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        except OSError:
            pass
    if found:
        print("[BotHub] processo do bot", bot_id, "encerrado; PID(s):", ", ".join(map(str, sorted(set(found)))), flush=True)
    return bool(found)

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

def kill_bot_processes_under_root():
    """Encerra todos os main.py pertencentes às pastas de bots desta instalação, inclusive órfãos."""
    bots_root = (ROOT / "bots").resolve()
    current_pid = os.getpid()
    candidates = []
    if os.name != "nt" and Path("/proc").is_dir():
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            if pid == current_pid:
                continue
            try:
                raw = (entry / "cmdline").read_bytes()
                args = [part.decode("utf-8", errors="ignore") for part in raw.split(b"\0") if part]
                for arg in args[1:]:
                    if not arg.endswith(".py"):
                        continue
                    script = Path(arg).resolve()
                    if script.name in {"main.py","standard_main.py","bot_admin.py"} and bots_root in script.parents:
                        candidates.append(pid)
                        break
            except (OSError, ValueError, RuntimeError):
                continue
    else:
        try:
            import psutil
            for proc in psutil.process_iter(["pid", "cmdline"]):
                pid = proc.info.get("pid")
                if not pid or pid == current_pid:
                    continue
                for arg in (proc.info.get("cmdline") or [])[1:]:
                    try:
                        script = Path(arg).resolve()
                        if script.name in {"main.py","standard_main.py","bot_admin.py"} and bots_root in script.parents:
                            candidates.append(pid)
                            break
                    except (OSError, ValueError, RuntimeError):
                        continue
        except Exception as e:
            print("[BotHub] Não foi possível localizar todos os main.py órfãos:", str(e)[:160], flush=True)
    stopped = []
    for pid in sorted(set(candidates)):
        try:
            os.kill(pid, signal.SIGTERM)
            stopped.append(pid)
        except OSError:
            pass
    deadline = time.time() + 5
    while stopped and time.time() < deadline:
        alive = []
        for pid in stopped:
            try:
                os.kill(pid, 0)
                alive.append(pid)
            except OSError:
                pass
        stopped = alive
        if stopped:
            time.sleep(0.2)
    for pid in stopped:
        try:
            os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        except OSError:
            pass
    if candidates:
        print("[BotHub] Processos main.py encerrados:", ", ".join(map(str, sorted(set(candidates)))), flush=True)

def cleanup_children():
    # Encerra primeiro os processos para que o snapshot SQLite final seja consistente.
    for key in list(PROCS):
        stop(key)
        try:
            sync_bot_state(key, 'push', CURRENT_FIREBASE_TOKEN, CURRENT_DEVICE_ID)
        except Exception:
            pass
        try:
            release_bot_lease(key, CURRENT_DEVICE_ID, CURRENT_FIREBASE_TOKEN)
        except Exception:
            pass
    # Depois encontra e encerra processos órfãos que sobreviveram a uma execução anterior.
    kill_bot_processes_under_root()

def publish_shutdown_status(reason="Servidor desligado"):
    """Publica o desligamento no Firebase sem enviar mensagens privadas aos donos dos bots."""
    global LAST_TOKEN, LAST_DID, LAST_QUEUE
    now = int(time.time() * 1000)
    stopped_ids = list(LAST_QUEUE.keys()) if isinstance(LAST_QUEUE, dict) else []
    if LAST_TOKEN and LAST_DID:
        try:
            fb("PATCH", "workers/" + LAST_DID, LAST_TOKEN, {
                "status": "offline", "online": False, "runningBots": 0,
                "runningBotIds": [], "shutdownAt": now, "shutdownReason": reason,
                "lastSeen": now - 120000, "workerUptimeSeconds": int(time.time() - WORKER_STARTED)
            })
            fb("PUT", "workerEvents/" + LAST_DID + "/lastShutdown", LAST_TOKEN, {
                "status": "offline", "online": False, "reason": reason,
                "stoppedBotIds": stopped_ids, "timestamp": now
            })
            print("[BotHub] Desligamento publicado no Firebase.", flush=True)
        except Exception as e:
            print("[BotHub] Não foi possível publicar o desligamento no Firebase:", str(e)[:180], flush=True)

def handle_shutdown_signal(signum, frame):
    global SHUTDOWN_IN_PROGRESS
    if SHUTDOWN_IN_PROGRESS:
        return
    SHUTDOWN_IN_PROGRESS = True
    reason = "SIGINT (interrupção manual)" if signum == signal.SIGINT else "SIGTERM (servidor encerrado)"
    print("[BotHub] Controlador sendo desligado; publicando status e encerrando processos...", flush=True)
    publish_shutdown_status(reason)
    cleanup_children()
    raise SystemExit(0)

def script_already_running(script, token_value=None):
    """Detecta main.py duplicado por caminho OU pelo mesmo token em outra pasta."""
    target = str(script.resolve())
    current_pid = os.getpid()
    if sys.platform.startswith("linux") and Path("/proc").is_dir():
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit() or int(entry.name) in (current_pid, os.getppid()):
                continue
            try:
                raw = (entry / "cmdline").read_bytes()
                args = [part.decode("utf-8", errors="ignore") for part in raw.split(b"\\0") if part]
                script_args = [arg for arg in args[1:] if arg.endswith(".py")]
                for arg in script_args:
                    try:
                        running_script = Path(arg).resolve()
                    except Exception:
                        continue
                    if running_script.name != "main.py":
                        continue
                    if str(running_script) == target:
                        return int(entry.name)
                    if token_value:
                        try:
                            cfg_path = running_script.parent / "config.json"
                            running_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                            running_token = str(running_cfg.get("discord_token") or running_cfg.get("token") or "")
                            if running_token and running_token == str(token_value):
                                return int(entry.name)
                        except Exception:
                            pass
            except (OSError, ValueError, RuntimeError):
                continue
    else:
        try:
            import psutil
            for proc in psutil.process_iter(["pid", "cmdline"]):
                if proc.info["pid"] == current_pid:
                    continue
                args = proc.info.get("cmdline") or []
                for arg in (proc.info.get("cmdline") or [])[1:]:
                    try:
                        running_script = Path(arg).resolve()
                    except Exception:
                        continue
                    if not str(arg).endswith(".py") or running_script.name != "main.py":
                        continue
                    if str(running_script) == target:
                        return proc.info["pid"]
                    if token_value:
                        try:
                            cfg_path = running_script.parent / "config.json"
                            running_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                            running_token = str(running_cfg.get("discord_token") or running_cfg.get("token") or "")
                            if running_token and running_token == str(token_value):
                                return proc.info["pid"]
                        except Exception:
                            pass
        except Exception:
            pass
    return None

def kill_existing_bothub_bots():
    """Encerra processos antigos de bots do BotHub antes de o controlador atual iniciá-los."""
    current_pid = os.getpid()
    killed = []
    if sys.platform.startswith("linux") and Path("/proc").is_dir():
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            if pid in (current_pid, os.getppid()):
                continue
            try:
                raw = (entry / "cmdline").read_bytes()
                args = [part.decode("utf-8", errors="ignore") for part in raw.split(b"\\0") if part]
                if len(args) < 2:
                    continue
                script_args = [arg for arg in args[1:] if arg.endswith(".py")]
                if not script_args:
                    continue
                is_bot_script = False
                for arg in script_args:
                    path = Path(arg).resolve()
                    if path.name == "main.py" and "bots" in path.parts:
                        is_bot_script = True
                        break
                if is_bot_script:
                    os.kill(pid, signal.SIGTERM)
                    killed.append(pid)
            except (OSError, ValueError, RuntimeError):
                continue
    elif os.name == "nt":
        try:
            import psutil
            for proc in psutil.process_iter(["pid", "cmdline"]):
                pid = proc.info.get("pid")
                if not pid or pid in (current_pid, os.getppid()):
                    continue
                args = proc.info.get("cmdline") or []
                for arg in args[1:]:
                    try:
                        path = Path(arg).resolve()
                        if path.name == "main.py" and "bots" in path.parts:
                            proc.terminate()
                            killed.append(pid)
                            break
                    except (OSError, ValueError, RuntimeError):
                        continue
        except Exception as e:
            print("[BotHub] Não foi possível verificar todos os processos antigos:", str(e)[:160], flush=True)
    if killed:
        print("[BotHub] Encerrando bots antigos antes de iniciar esta instância:", ", ".join(map(str, killed)), flush=True)
        deadline = time.time() + 5
        while time.time() < deadline:
            alive = []
            for pid in killed:
                try:
                    os.kill(pid, 0)
                    alive.append(pid)
                except OSError:
                    pass
            if not alive:
                break
            time.sleep(0.2)
        for pid in alive if 'alive' in locals() else []:
            try:
                os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
            except OSError:
                pass

# --- Cooperative leases and Firebase-backed memory state ---
LEASE_SECONDS = max(45, int(os.getenv('BOTHUB_LEASE_SECONDS', '75')))
STATE_FIXED_FILES = {'bot_personality.json','foto de perfil.txt','image_history.json','memory.sqlite3','reminders.sqlite3','memoria_geral','importantes','geral_avisos','identidade','regras','identidade-padrao.txt','regras-padrao.txt','comunidades_autorizadas.txt'}
ACTIVE_LEASES = {}
CURRENT_DEVICE_ID = ''
CURRENT_FIREBASE_TOKEN = ''
LEASE_MISSES = 0

def _lease_url(bot_id):
    return DB + '/botLeases/' + urllib.parse.quote(sid(bot_id), safe='') + '.json'

def _state_url(bot_id):
    return DB + '/botState/' + urllib.parse.quote(sid(bot_id), safe='') + '/files'

def _req_json(method, url, tok, data=None, headers=None):
    h = {'User-Agent':'BotHub-Cluster/4.0'}
    if headers: h.update(headers)
    r = S.request(method, url, params={'auth':tok}, json=data, headers=h, timeout=20)
    if r.status_code >= 300: raise RuntimeError('Firebase HTTP '+str(r.status_code)+': '+r.text[:160])
    return r

def claim_bot_lease(bot_id, device_id, tok):
    bid=sid(bot_id); url=_lease_url(bid); now=int(time.time()*1000)
    for _ in range(5):
        r=_req_json('GET',url,tok,headers={'X-Firebase-ETag':'true'})
        etag=r.headers.get('ETag','null_etag'); cur=r.json() if r.text else {}
        if not isinstance(cur,dict): cur={}
        owner=str(cur.get('owner') or ''); until=int(cur.get('leaseUntil') or 0)
        if owner and owner != device_id and until > now: return None
        same=(owner == device_id); fence=int(cur.get('fence') or 0)+(0 if same else 1)
        lease={'owner':device_id,'leaseUntil':now+LEASE_SECONDS*1000,'heartbeatAt':now,'fence':max(1,fence)}
        put=S.put(url,params={'auth':tok},json=lease,headers={'If-Match':etag,'User-Agent':'BotHub-Cluster/4.0'},timeout=20)
        if put.status_code in (200,204):
            ACTIVE_LEASES[bid]={'fence':lease['fence'],'leaseUntil':lease['leaseUntil']}; return lease
        if put.status_code in (409,412): continue
        raise RuntimeError('Falha ao gravar lease: HTTP '+str(put.status_code))
    return None

def release_bot_lease(bot_id, device_id, tok):
    bid=sid(bot_id); url=_lease_url(bid)
    try:
        r=_req_json('GET',url,tok,headers={'X-Firebase-ETag':'true'}); cur=r.json() if r.text else {}
        if isinstance(cur,dict) and cur.get('owner') == device_id:
            S.put(url,params={'auth':tok},json={'owner':'','leaseUntil':0,'heartbeatAt':int(time.time()*1000),'fence':int(cur.get('fence') or 0)},headers={'If-Match':r.headers.get('ETag','null_etag'),'User-Agent':'BotHub-Cluster/4.0'},timeout=15)
    except Exception as e: print('[BotHub] falha ao liberar lease:',str(e)[:120],flush=True)
    ACTIVE_LEASES.pop(bid,None)

def _state_key(name):
    return base64.urlsafe_b64encode(name.encode('utf-8')).decode('ascii').rstrip('=')

def _state_files(folder):
    out={}
    for p in folder.iterdir():
        if not p.is_file() or p.name.startswith('.') or p.name in {'config.json','bot.log','worker.json','firebase-token.json'}: continue
        if p.name in STATE_FIXED_FILES or (p.suffix.lower()=='.txt' and any(x in p.name for x in ('memoria','importante','avisos','identidade','regras'))):
            try:
                if p.stat().st_size <= 8*1024*1024: out[p.name]=p
            except OSError: pass
    return out

def _snapshot_bytes(path):
    if path.name.endswith('.sqlite3') and path.exists():
        tmp=path.with_name(path.name+'.sync.tmp')
        try:
            src=sqlite3.connect(str(path),timeout=10); dst=sqlite3.connect(str(tmp),timeout=10)
            try: src.backup(dst)
            finally: dst.close(); src.close()
            return tmp.read_bytes()
        finally:
            try: tmp.unlink()
            except OSError: pass
    return path.read_bytes()

def sync_bot_state(bot_id, mode='push', tok=None, device_id=None):
    bid=sid(bot_id); tok=tok or CURRENT_FIREBASE_TOKEN; device_id=device_id or CURRENT_DEVICE_ID
    lease=ACTIVE_LEASES.get(bid)
    if not tok or not device_id or not lease: return
    owner=_req_json('GET',_lease_url(bid),tok).json()
    if not isinstance(owner,dict) or owner.get('owner') != device_id or int(owner.get('fence') or 0) != int(lease['fence']):
        ACTIVE_LEASES.pop(bid,None); raise RuntimeError('Lease perdido; estado compartilhado protegido.')
    folder=ROOT/'bots'/bid; folder.mkdir(parents=True,exist_ok=True); url=_state_url(bid)
    r=_req_json('GET',url+'.json',tok); remote=r.json() if r.text else {}
    if not isinstance(remote,dict): remote={}
    if mode == 'pull' and remote:
        for rec in remote.values():
            if not isinstance(rec,dict): continue
            name=str(rec.get('name') or '')
            if not name or Path(name).name != name or name.startswith('.') or '..' in name or '/' in name or chr(92) in name: continue
            if name not in STATE_FIXED_FILES and not (name.endswith('.txt') and any(x in name for x in ('memoria','importante','avisos','identidade','regras'))): continue
            try:
                raw=base64.b64decode(rec.get('data',''),validate=True)
                if len(raw)>8*1024*1024: continue
                dest=folder/name; tmp=dest.with_name(dest.name+'.sync.tmp'); tmp.write_bytes(raw); tmp.replace(dest)
            except Exception as e: print('[BotHub] estado remoto ignorado:',name,str(e)[:100],flush=True)
    changed=False
    for name,path in _state_files(folder).items():
        try:
            raw=_snapshot_bytes(path); digest=hashlib.sha256(raw).hexdigest(); key=_state_key(name)
            if isinstance(remote.get(key),dict) and remote[key].get('sha256') == digest: continue
            if len(raw)>8*1024*1024: continue
            rec={'name':name,'sha256':digest,'data':base64.b64encode(raw).decode('ascii'),'updatedAt':int(time.time()*1000),'writer':device_id,'fence':int(lease['fence'])}
            _req_json('PUT',url+'/'+key+'.json',tok,rec); changed=True
        except Exception as e: print('[BotHub] sync de memória falhou:',name,str(e)[:120],flush=True)
    if changed: print('[BotHub] memórias/estado sincronizados:',bid,flush=True)


def start(k,b):
    folder=ROOT/"bots"/sid(k);folder.mkdir(parents=True,exist_ok=True)
    requested_at=float(b.get("startRequestedAt") or 0)
    if clean_exit_state(k,requested_at) is not None:
        CLEAN_EXITED[k]=requested_at
        print("[BotHub] início pausado: última execução terminou com código 0; aguardando novo pedido do painel:",k,flush=True)
        return
    bot_type=str(b.get("botType") or (b.get("config") or {}).get("botType") or "ia_chat").lower()
    if bot_type not in {"ia_chat","standard","bot_admin"}: bot_type="ia_chat"
    script_name={"ia_chat":"main.py","standard":"standard_main.py","bot_admin":"bot_admin.py"}[bot_type]
    script=folder/script_name
    if k in PROCS and PROCS[k].poll() is None:
        return
    sync_bot_state(k, 'pull')
    if not script.exists():
        default_urls={
            "ia_chat":os.getenv("BOTHUB_BOT_SOURCE_URL","https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/teste%202/main.py"),
            "standard":"https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/standard_main.py",
            "bot_admin":"https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/teste%202/bot_admin.py",
        }
        url=default_urls[bot_type]
        r=S.get(url,timeout=45);r.raise_for_status()
        if len(r.content)<1000:raise RuntimeError("Download incompleto de "+script_name)
        source=r.content.decode("utf-8");compile(source,str(script),"exec")
        tmp=script.with_suffix(".py.download.tmp");tmp.write_bytes(r.content);tmp.replace(script)
    try:
        compile(script.read_text(encoding="utf-8"),str(script),"exec")
    except Exception as exc:
        raise RuntimeError(script_name+" não passou na validação de sintaxe: "+str(exc)[:180])
    duplicate_pid = script_already_running(script, b.get("token"))
    if duplicate_pid is not None:
        print("[BotHub] Duplicata de main.py/token detectada (PID",duplicate_pid,"). Encerrando a cópia antiga antes de iniciar a instância correta para",k,flush=True)
        try:
            os.kill(duplicate_pid, signal.SIGTERM)
            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    os.kill(duplicate_pid, 0)
                except OSError:
                    break
                time.sleep(0.2)
            else:
                os.kill(duplicate_pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        except OSError:
            pass
    cfg=dict(b.get("config") or {});cfg["discord_token"]=b["token"]
    # Configuração de autorização individual, recebida do painel BotHub.
    auth=dict(cfg.get("bot_authorization") or {})
    auth.update({
        "password_salt": str(b.get("allowPasswordSalt") or auth.get("password_salt") or ""),
        "password_hash": str(b.get("allowPasswordHash") or auth.get("password_hash") or ""),
        "allow_user_ids": [str(x) for x in (b.get("allowUserIds") if b.get("allowUserIds") is not None else auth.get("allow_user_ids", [])) if str(x).isdigit()],
        "authorized_guild_ids": [str(x) for x in (b.get("authorizedGuildIds") if b.get("authorizedGuildIds") is not None else auth.get("authorized_guild_ids", [])) if str(x).isdigit()],
    })
    cfg["bot_authorization"]=auth
    cp=folder/"config.json";save_json(cp,cfg)

    # Tenta iniciar mais de uma vez se o processo cair imediatamente (ex.: falha transitória).
    last_error=""
    for attempt in range(1,4):
        if k in PROCS:
            stop(k)
        log=open(folder/"bot.log","ab",buffering=0)
        popen_kwargs = {}
        if sys.platform.startswith("linux"):
            popen_kwargs["preexec_fn"] = child_parent_death_signal
        try:
            # Remove o sinal antigo antes de cada inicialização; só on_ready do Discord recria.
            try:(folder/".bothub_discord_ready").unlink(missing_ok=True)
            except OSError:pass
            child_env=os.environ.copy()
            child_env["BOTHUB_SHARED_STATE_DIR"]=str(ROOT/".bothub_shared")
            child_env["BOTHUB_BOT_ID"]=str(k)
            p=subprocess.Popen([sys.executable,"-u",str(script)],cwd=str(folder),stdin=subprocess.DEVNULL,
                stdout=log,stderr=subprocess.STDOUT,start_new_session=(os.name!="nt"),env=child_env,**popen_kwargs)
        except Exception:
            log.close()
            raise
        PROCS[k]=p;LOGS[k]=log
        print("[BotHub] iniciando",b.get("name",k),"PID",p.pid,"tentativa",attempt,"/3",flush=True)
        # Pequena janela de saúde: processos que morrem logo após o Popen não são marcados como iniciados.
        deadline=time.time()+3
        while time.time()<deadline and p.poll() is None:
            time.sleep(0.25)
        if p.poll() is None:
            print("[BotHub] processo permaneceu ativo após a verificação inicial:",b.get("name",k),flush=True)
            return
        try:
            log.flush()
            with open(folder/"bot.log","r",encoding="utf-8",errors="replace") as handle:
                last_error="\\n".join(handle.readlines()[-18:])[-1800:]
        except Exception:
            last_error="sem detalhes adicionais no log"
        print("[BotHub] o processo encerrou durante a inicialização (código",p.returncode,"):",last_error[-700:],flush=True)
        if p.returncode == 0:
            # Saída limpa não deve provocar um ciclo infinito de reinicializações.
            mark_clean_exit(k, b.get("startRequestedAt"), p.returncode)
            PROCS.pop(k,None)
            LOGS.pop(k,None)
            try: log.close()
            except Exception: pass
            raise RuntimeError("o processo encerrou com código 0; reinício automático pausado até um novo pedido de inicialização")
        PROCS.pop(k,None)
        LOGS.pop(k,None)
        try: log.close()
        except Exception: pass
        if attempt<3:
            time.sleep(attempt)
    raise RuntimeError("main.py encerrou nas 3 tentativas. Últimas linhas do log: "+last_error[-900:])


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
            if op=="stop":
                bid=sid(cmd.get("botId",""))
                tracked = bid in PROCS
                stop(bid)
                orphan_stopped = stop_bot_processes(bid)
                # Impede que a cópia da fila lida antes do comando reinicie o bot neste ciclo.
                if isinstance(queue, dict):
                    queue.pop(bid, None)
                try:
                    fb("DELETE","workerTasks/"+did+"/"+urllib.parse.quote(bid,safe=""),tok)
                except Exception as queue_error:
                    print("[BotHub] não foi possível remover a tarefa do bot parado:",bid,str(queue_error)[:140],flush=True)
                try: sync_bot_state(bid,"push",tok,cfg.get("device_id"))
                except Exception as state_error:
                    print("[BotHub] estado final não sincronizado ao parar",bid,str(state_error)[:140],flush=True)
                try: release_bot_lease(bid,cfg.get("device_id"),tok)
                except Exception as lease_error:
                    print("[BotHub] lease não liberado ao parar",bid,str(lease_error)[:140],flush=True)
                stopped = tracked or orphan_stopped
                print("[BotHub] parada explícita confirmada:",bid,"processo encerrado:",stopped,flush=True)
                result.update(status="ok",message="main.py do bot encerrado neste worker.",stopped=stopped)
            elif op=="create_invite":
                bid=sid(cmd.get("botId",""))
                bot_cfg=queue.get(bid) if isinstance(queue,dict) else None
                secret=bot_cfg.get("token") if isinstance(bot_cfg,dict) else None
                if not secret: raise ValueError("O bot não está atribuído a este worker ou não tem token.")
                profile=discord_api(secret,"GET","/users/@me",None)
                application_id=str(profile.get("id") or "")
                if not application_id: raise RuntimeError("Discord não retornou o ID da aplicação.")
                permissions=117840 if str(bot_cfg.get("botType") or "ia_chat").lower()=="bot_admin" else 0
                invite_url=f"https://discord.com/oauth2/authorize?client_id={application_id}&scope=bot%20applications.commands&permissions={permissions}"
                result.update(status="ok",inviteUrl=invite_url,applicationId=application_id,cached=False)
            elif op=="profile":
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

def bot_script_info(bot_type):
    kind=str(bot_type or "ia_chat").lower()
    if kind=="ia_chat":
        return "main.py",os.getenv("BOTHUB_BOT_SOURCE_URL","https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/teste%202/main.py"),10000
    if kind=="bot_admin":
        return "bot_admin.py",os.getenv("BOTHUB_ADMIN_SOURCE_URL","https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/teste%202/bot_admin.py"),5000
    if kind=="standard":
        return "standard_main.py",os.getenv("BOTHUB_STANDARD_SOURCE_URL","https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/standard_main.py"),1000
    raise RuntimeError("Tipo de bot não suportado para atualização: "+kind)

def latest_bot_script_bytes(bot_type):
    name,url,minimum=bot_script_info(bot_type)
    response=S.get(url,timeout=45);response.raise_for_status()
    data=response.content
    if len(data)<minimum:raise RuntimeError(name+" baixado está incompleto.")
    compile(data.decode("utf-8"),name+" (versão publicada)","exec")
    return data

def download_latest_bot_script(folder,bot_type):
    name,_,_=bot_script_info(bot_type)
    data=latest_bot_script_bytes(bot_type)
    target=folder/name;tmp=folder/(name+".update.tmp")
    backup=folder/("."+name+".last-good")
    if target.exists():
        old=target.read_bytes()
        if len(old)>=1000:
            compile(old.decode("utf-8"),name+" (versão anterior)","exec")
            backup_tmp=backup.with_suffix(".tmp")
            backup_tmp.write_bytes(old);backup_tmp.replace(backup)
    tmp.write_bytes(data);tmp.replace(target)
    return len(data)

def latest_main_bytes():
    return latest_bot_script_bytes("ia_chat")

def download_latest_main(folder):
    return download_latest_bot_script(folder,"ia_chat")

def notify_update(bot_id, bot_cfg, update, notification_state):
    token_value=bot_cfg.get("token")
    if not token_value:return False
    try:
        app_info=discord_api(token_value,"GET","/applications/@me",None)
        owner=(app_info.get("owner") or {}).get("id")
        if not owner:return False
        owner=str(owner)
        update_id=str(update.get("updateId") or "")
        # A mesma pessoa pode ser dona de vários bots: avisar somente uma vez por versão.
        if update_id and notification_state.get(owner)==update_id:
            return True
        channel=discord_api(token_value,"POST","/users/@me/channels",{"recipient_id":owner})
        mode="OBRIGATÓRIA" if update.get("type")=="mandatory" else "OPCIONAL"
        description=str(update.get("description") or "Melhorias e correções.")[:1500]
        content=("📦 **Atualização BotHub disponível — "+mode+"**\n"+description+
                 ("\n\nEsta atualização será instalada automaticamente." if mode=="mandatory"
                  else "\n\nPara instalar, digite !update neste chat com o bot."))
        discord_api(token_value,"POST","/channels/"+str(channel["id"])+"/messages",
                    {"content":content,"allowed_mentions":{"parse":[]}})
        if update_id:
            notification_state[owner]=update_id
            save_json(ROOT/".bothub_update_notifications.json",notification_state)
        return True
    except Exception as e:
        print("[BotHub] Não foi possível avisar o criador de",bot_id,":",str(e)[:180],flush=True)
        return False

def process_release_updates(tok, queue):
    release=fb("GET","botHubUpdates/current",tok)
    if not isinstance(release,dict) or not release.get("updateId") or release.get("clusterOnly"):
        return
    notification_file=ROOT/".bothub_update_notifications.json"
    try:
        notification_state=json.loads(notification_file.read_text(encoding="utf-8")) if notification_file.exists() else {}
    except Exception:
        notification_state={}
    if not isinstance(notification_state,dict):
        notification_state={}
    update_id=str(release.get("updateId"))
    for raw_id,bot_cfg in list(queue.items()):
        if not isinstance(bot_cfg,dict) or not bot_cfg.get("enabled",True):
            continue
        bid=sid(raw_id)
        folder=ROOT/"bots"/bid
        if not folder.exists():
            continue
        state_file=folder/".bothub_update_state.json"
        try:
            state=json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
        except Exception:
            state={}
        if not isinstance(state,dict):
            state={}
        if state.get("updateId")!=update_id:
            state={"updateId":update_id,"announced":False,"updated":False,"attempts":0}
        mandatory=release.get("type")=="mandatory"
        bot_type=str(bot_cfg.get("botType") or (bot_cfg.get("config") or {}).get("botType") or "ia_chat").lower()
        if bot_type not in {"ia_chat","standard","bot_admin"}:continue
        script_name,_,_=bot_script_info(bot_type)
        # Se o arquivo já corresponde à publicação, marca como atualizado sem reiniciar.
        if not state.get("updated"):
            try:
                installed=folder/script_name
                published=latest_bot_script_bytes(bot_type)
                if installed.is_file() and installed.read_bytes()==published:
                    state.update(updateId=update_id,announced=bool(mandatory or state.get("announced")),updated=True,
                                 updatedAt=int(time.time()*1000),bytes=len(published),
                                 retryAfter=0,lastError="",alreadyCurrent=True)
                    save_json(state_file,state)
                    print("[BotHub] bot já está na versão publicada; atualização ignorada sem reiniciar:",raw_id,script_name,flush=True)
                    continue
            except Exception as compare_error:
                print("[BotHub] não foi possível comparar a versão instalada de",raw_id,":",str(compare_error)[:160],flush=True)
        if state.get("updated"):
            continue
        # Atualizações obrigatórias são silenciosas: não enviam DM e não pedem !update.
        if not mandatory and not state.get("announced"):
            announced=notify_update(raw_id,bot_cfg,release,notification_state)
            state["announced"]=bool(announced)
            save_json(state_file,state)

        request_file=folder/".bothub_update_request"
        accepted=request_file.exists()
        # Não repete download/restart a cada ciclo quando a atualização falhou.
        # A tentativa seguinte só ocorre depois do backoff persistido em disco.
        try:
            retry_after=float(state.get("retryAfter") or 0)
        except (TypeError,ValueError):
            retry_after=0
        if retry_after>time.time():
            continue
        if not mandatory and not accepted:
            continue
        try:
            stop(bid)
            size=download_latest_bot_script(folder,bot_type)
            start(bid,bot_cfg)
            state.update(updateId=update_id,announced=bool(mandatory or state.get("announced")),updated=True,
                         updatedAt=int(time.time()*1000),bytes=size,
                         retryAfter=0,lastError="")
            save_json(state_file,state)
            if request_file.exists():
                request_file.unlink()
            print("[BotHub] bot atualizado:",raw_id,"bytes:",size,flush=True)
        except Exception as e:
            attempts=int(state.get("attempts") or 0)+1
            delay=min(900,30*(2**min(attempts-1,5)))
            state.update(updateId=update_id,announced=True,updated=False,
                         attempts=attempts,retryAfter=time.time()+delay,
                         retryDelaySeconds=delay,lastAttemptAt=int(time.time()*1000),
                         lastError=str(e)[:500])
            save_json(state_file,state)
            print("[BotHub] atualização falhou para",raw_id,
                  "- código/erro:",str(e)[:180],
                  "- próxima tentativa em",delay,"segundos.",flush=True)
            # Restaura a versão anterior, mas não reinicia em ciclo apertado.
            try:
                backup=folder/("."+script_name+".last-good")
                if backup.is_file():
                    restored=folder/(script_name+".restore.tmp")
                    restored.write_bytes(backup.read_bytes())
                    restored.replace(folder/script_name)
                    print("[BotHub] versão anterior restaurada para",raw_id,flush=True)
                    if bid not in PROCS or PROCS[bid].poll() is not None:
                        start(bid,bot_cfg)
            except Exception as recovery_error:
                print("[BotHub] recuperação da versão anterior falhou para",raw_id,
                      ":",str(recovery_error)[:180],flush=True)


CLUSTER_UPDATE_URLS={
    "add_cluster_server.py":"https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/teste%202/add_cluster_server.py",
    "bothub_firebase_worker.py":"https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/teste%202/bothub_firebase_worker.py",
}

def process_cluster_update(tok):
    """Aplica a atualização no próprio processo, sem iniciar outro instalador/supervisor."""
    release=fb("GET","botHubClusterUpdates/current",tok)
    if not isinstance(release,dict) or not release.get("updateId"):
        return False
    update_id=str(release.get("updateId"))
    state_path=ROOT/".bothub_cluster_update_state.json"
    try:
        state=json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    except Exception:
        state={}
    if state.get("updateId")==update_id and state.get("status")=="applied":
        return False
    # Se uma execução anterior foi interrompida durante o download, permite
    # tentar novamente depois de 3 minutos, sem iniciar um segundo controlador.
    if state.get("updateId")==update_id and state.get("status")=="installing":
        started=float(state.get("requestedAt") or 0)/1000
        if started and time.time()-started < 180:
            return False

    requested=release.get("files",[])
    if isinstance(requested,dict):
        requested=list(requested.keys())
    if not isinstance(requested,list) or not requested:
        return False
    allowed={"add_cluster_server.py","bothub_firebase_worker.py"}
    clean={}
    for name in requested:
        if name not in allowed:
            raise RuntimeError("Arquivo de cluster não permitido: "+str(name))
        url=CLUSTER_UPDATE_URLS[name]
        response=S.get(url,timeout=45)
        response.raise_for_status()
        data=response.content
        if len(data)<1000:
            raise RuntimeError("Download incompleto de "+name)
        source=data.decode("utf-8")
        compile(source,name,"exec")
        clean[name]=source

    save_json(state_path,{"updateId":update_id,"status":"installing","requestedAt":int(time.time()*1000)})
    # Substituição atômica: o processo atual continua vivo enquanto os arquivos
    # são preparados. Não chama add_cluster_server.py, pois ele criaria outro
    # supervisor no Termux e provocaria reinicializações com código 0.
    for name,source in clean.items():
        target=ROOT/name
        tmp=ROOT/(name+".cluster-update.tmp")
        tmp.write_text(source,encoding="utf-8")
        tmp.replace(target)
    save_json(state_path,{"updateId":update_id,"status":"applied","appliedAt":int(time.time()*1000)})
    print("[BotHub] Atualização aplicada:",", ".join(clean.keys()),"- reiniciando o mesmo processo, sem encerrar o supervisor.",flush=True)
    worker=ROOT/"bothub_firebase_worker.py"
    os.execv(sys.executable,[sys.executable,str(worker)])
    return True

def _pid_is_this_worker(pid):
    """Confere se o PID pertence ao worker desta instalação, não a outro servidor."""
    if pid == os.getpid():
        return True
    expected = str((ROOT / "bothub_firebase_worker.py").resolve())
    if os.name != "nt":
        try:
            raw = (Path("/proc") / str(pid) / "cmdline").read_bytes()
            args = [part.decode("utf-8", errors="ignore") for part in raw.split(b"\\0") if part]
            return any(arg.endswith(".py") and str(Path(arg).resolve()) == expected for arg in args[1:])
        except Exception:
            return False
    try:
        import psutil
        process = psutil.Process(pid)
        return any(str(Path(arg).resolve()) == expected for arg in process.cmdline()
                   if str(arg).lower().endswith(".py"))
    except Exception:
        return False

def main():
    global CURRENT_CFG, CURRENT_DEVICE_ID, CURRENT_FIREBASE_TOKEN, LEASE_MISSES
    cfg=setup()
    CURRENT_CFG=cfg
    CURRENT_DEVICE_ID=cfg['device_id']
    v=ROOT/"venv";vp=v/("Scripts/python.exe" if os.name=="nt" else "bin/python")
    if not vp.exists():
        subprocess.check_call([sys.executable,"-m","venv",str(v)])
        subprocess.check_call([str(vp),"-m","pip","install","--upgrade","pip"])
        subprocess.check_call([str(vp),"-m","pip","install","requests","discord.py","aiohttp"])
        os.execv(str(vp),[str(vp),str(Path(__file__).resolve())])
    # Execução direta: não bloquear o Worker por arquivo de lock.
    signal.signal(signal.SIGTERM, handle_shutdown_signal)
    signal.signal(signal.SIGINT, handle_shutdown_signal)
    atexit.register(cleanup_children)
    kill_existing_bothub_bots()
    kill_bot_processes_under_root()
    print("[BotHub] Todos os main.py antigos desta instalação foram encerrados; iniciando os bots atribuídos.", flush=True)
    print("[BotHub] Worker iniciado sem pedir ID, e-mail ou senha.",flush=True)
    while True:
        try:
            t=token(cfg);did=urllib.parse.quote(cfg["device_id"],safe="")
            shared_auth_dir=ROOT/".bothub_shared";shared_auth_dir.mkdir(parents=True,exist_ok=True)
            save_json(shared_auth_dir/"firebase-worker-token.json",{"idToken":t,"uid":str(cfg.get("uid") or ""),"updatedAt":int(time.time()*1000)})
            LAST_TOKEN=t;LAST_DID=did;CURRENT_FIREBASE_TOKEN=t
            # Verifica atualização antes do heartbeat: um erro no PUT de status
            # não pode impedir que este worker receba a própria correção.
            try:
                if process_cluster_update(t):
                    break
            except Exception as update_error:
                print("[BotHub] falha ao verificar atualização do cluster:",str(update_error)[:220],flush=True)
            fb("PUT","workers/"+did,t,stats(cfg))
            queue=fb("GET","workerTasks/"+did,t) or {}
            LAST_QUEUE=queue if isinstance(queue,dict) else {}
            process_worker_commands(cfg,t,did,queue)
            # Uma conta Discord (token) só pode ter uma instância ativa neste worker.
            # Se o painel atribuir o mesmo token a IDs/pastas diferentes, manter apenas a primeira.
            desired={}
            token_owner={}
            duplicate_ids=set()
            for raw_id,b in list(queue.items()):
                if not isinstance(b,dict) or not b.get("enabled",True):
                    continue
                k=sid(raw_id)
                # O cadastro principal é a fonte de verdade; uma fila antiga nunca pode
                # ressuscitar um bot que o painel já marcou como OFF.
                try:
                    remote_bot = fb("GET","bots/"+urllib.parse.quote(k,safe=""),t) or {}
                    if (not isinstance(remote_bot,dict) or remote_bot.get("enabled") is False
                            or str(remote_bot.get("desiredState","on")).lower()=="off"):
                        queue.pop(raw_id, None)
                        queue.pop(k, None)
                        stop(k)
                        stop_bot_processes(k)
                        try: release_bot_lease(k,cfg["device_id"],t)
                        except Exception: pass
                        try: fb("DELETE","workerTasks/"+did+"/"+urllib.parse.quote(k,safe=""),t)
                        except Exception: pass
                        print("[BotHub] bot OFF no cadastro; main.py encerrado e tarefa removida:",k,flush=True)
                        continue
                except Exception as status_error:
                    print("[BotHub] não foi possível confirmar o estado do bot",k,str(status_error)[:120],flush=True)
                    continue
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
            leased={}
            for k,bot_cfg in desired.items():
                try:
                    if claim_bot_lease(k,cfg['device_id'],t):
                        leased[k]=bot_cfg
                    else:
                        print("[BotHub] bot pertence a outro worker; aguardando:",k,flush=True)
                except Exception as lease_error:
                    print("[BotHub] lease indisponível para",k,str(lease_error)[:140],flush=True)
            for k in list(PROCS):
                if k not in leased or k in duplicate_ids:
                    stop(k)
                    try: sync_bot_state(k,'push',t,cfg['device_id'])
                    except Exception: pass
                    release_bot_lease(k,cfg['device_id'],t)
                    if k not in leased:
                        shutil.rmtree(ROOT/'bots'/sid(k),ignore_errors=True)
                    print("[BotHub] bot parado/transferido:",k,flush=True)
            # Propaga para o painel as comunidades liberadas pelo comando privado !allow.
            for active_id in list(leased):
                try:
                    local_cfg_path=ROOT/"bots"/sid(active_id)/"config.json"
                    if local_cfg_path.exists():
                        local_cfg=json.loads(local_cfg_path.read_text(encoding="utf-8"))
                        auth_cfg=local_cfg.get("bot_authorization") if isinstance(local_cfg,dict) else {}
                        ids=auth_cfg.get("authorized_guild_ids",[]) if isinstance(auth_cfg,dict) else []
                        ids=sorted({str(x) for x in ids if str(x).isdigit()})
                        remote_ids=fb("GET","bots/"+sid(active_id)+"/authorizedGuildIds",t) or []
                        remote_ids=sorted({str(x) for x in remote_ids if str(x).isdigit()}) if isinstance(remote_ids,list) else []
                        if ids != remote_ids:
                            fb("PUT","bots/"+sid(active_id)+"/authorizedGuildIds",t,ids)
                except Exception as auth_sync_error:
                    print("[BotHub] sincronização das comunidades autorizadas falhou:",active_id,str(auth_sync_error)[:140],flush=True)
            # Reinicia apenas o bot cuja configuração de autorização mudou no painel.
            for active_id,active_cfg in leased.items():
                try:
                    if active_id in PROCS and PROCS[active_id].poll() is None:
                        local_path=ROOT/"bots"/sid(active_id)/"config.json"
                        local=json.loads(local_path.read_text(encoding="utf-8")) if local_path.exists() else {}
                        current=local.get("bot_authorization") if isinstance(local,dict) else {}
                        current=current if isinstance(current,dict) else {}
                        desired={
                            "password_salt":str(active_cfg.get("allowPasswordSalt") or ""),
                            "password_hash":str(active_cfg.get("allowPasswordHash") or ""),
                            "allow_user_ids":sorted({str(x) for x in (active_cfg.get("allowUserIds") or []) if str(x).isdigit()}),
                            "authorized_guild_ids":sorted({str(x) for x in (active_cfg.get("authorizedGuildIds") or []) if str(x).isdigit()}),
                        }
                        normalized={
                            "password_salt":str(current.get("password_salt") or ""),
                            "password_hash":str(current.get("password_hash") or ""),
                            "allow_user_ids":sorted({str(x) for x in (current.get("allow_user_ids") or []) if str(x).isdigit()}),
                            "authorized_guild_ids":sorted({str(x) for x in (current.get("authorized_guild_ids") or []) if str(x).isdigit()}),
                        }
                        if normalized != desired:
                            stop(active_id)
                            print("[BotHub] autorização alterada no painel; reiniciando bot:",active_id,flush=True)
                except Exception as auth_restart_error:
                    print("[BotHub] não foi possível conferir autorização:",active_id,str(auth_restart_error)[:120],flush=True)
            for k,bot_cfg in leased.items():
                try:
                    requested_at=float(bot_cfg.get("startRequestedAt") or 0)
                    saved_exit=clean_exit_state(k,requested_at)
                    if saved_exit is not None:
                        CLEAN_EXITED[k]=saved_exit
                        continue
                    CLEAN_EXITED.pop(k,None)
                    if k not in PROCS or PROCS[k].poll() is not None:
                        # Se terminou normalmente depois de iniciar, pausa novas tentativas
                        # até o painel registrar um novo pedido explícito de inicialização.
                        previous=PROCS.get(k)
                        if previous is not None and previous.poll() is not None and previous.returncode == 0:
                            mark_clean_exit(k,requested_at,previous.returncode)
                            print("[BotHub] bot encerrou com código 0; pausa persistida até novo pedido:",k,flush=True)
                            stop(k)
                            continue
                        sync_bot_state(k,'pull',t,cfg['device_id'])
                        sync_bot_state(k,'push',t,cfg['device_id'])
                        auto_start=bot_cfg.get("autoStart",True) is not False
                        start_requested=float(bot_cfg.get("startRequestedAt") or 0)
                        if not auto_start and start_requested <= WORKER_STARTED*1000: continue
                        start(k,bot_cfg)
                except Exception as e: print("[BotHub] falha no bot",k,str(e)[:220],flush=True)
            try: process_release_updates(t,queue)
            except Exception as e: print("[BotHub] falha ao verificar atualização:",str(e)[:220],flush=True)
        except KeyboardInterrupt: break
        except Exception as e:
            LEASE_MISSES += 1
            print('[BotHub] erro Firebase/worker:',str(e)[:300],flush=True)
            if LEASE_MISSES >= 3:
                for active_id in list(PROCS): stop(active_id)
                ACTIVE_LEASES.clear()
        else:
            LEASE_MISSES = 0
        time.sleep(max(10,int(os.getenv('BOTHUB_POLL_SECONDS','15'))))
    cleanup_children()

if __name__=="__main__":
    try:main()
    except Exception as e:print("Erro fatal:",e,file=sys.stderr);raise
