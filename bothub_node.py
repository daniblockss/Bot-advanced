#!/usr/bin/env python3
"""BotHub Node: instalador de arquivo único para Linux/Termux. Execute: python bothub_node.py"""
from __future__ import annotations
import os, sys, json, time, shutil, subprocess, platform, secrets
from pathlib import Path

ROOT = Path.home() / ".bothub"
CONFIG = ROOT / "config.json"
WORKER = ROOT / "worker.py"
REQ = ROOT / "requirements.txt"
PY = ROOT / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

WORKER_SOURCE = r'''import os, json, time, socket, platform, shutil
from pathlib import Path
import requests
try:
 import psutil
except ImportError:
 psutil = None
ROOT = Path.home() / ".bothub"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
API = CONFIG["api_url"].rstrip("/")
DEVICE = CONFIG["device_id"]
TOKEN = CONFIG["worker_token"]
INTERVAL = max(15, int(CONFIG.get("heartbeat_seconds", 30)))
SESSION = requests.Session()
SESSION.headers.update({"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json", "User-Agent": "BotHub-Node/1.0"})
def resources():
 usage = shutil.disk_usage(str(Path.home()))
 data = {"device_id": DEVICE, "hostname": socket.gethostname(), "platform": platform.platform(),
         "disk_free_bytes": usage.free, "disk_total_bytes": usage.total, "cpu_count": os.cpu_count() or 1,
         "python": platform.python_version(), "status": "online", "timestamp": int(time.time())}
 if psutil:
  data["ram_total_bytes"] = psutil.virtual_memory().total
  data["ram_free_bytes"] = psutil.virtual_memory().available
  data["cpu_percent"] = psutil.cpu_percent(interval=0.2)
 return data
def main():
 print("BotHub Node iniciado. Ctrl+C para sair.")
 while True:
  try:
   r = SESSION.post(API + "/api/worker/heartbeat", json=resources(), timeout=15)
   if r.status_code == 401:
    print("Token do worker recusado. Confira a configuração; aguardando 60s.")
    time.sleep(60); continue
   r.raise_for_status()
   result = r.json() if r.content else {}
   if result.get("message"): print(result["message"])
  except KeyboardInterrupt: break
  except Exception as e: print("API indisponível:", str(e)[:300])
  time.sleep(INTERVAL)
if __name__ == "__main__": main()
'''

def ask(label, default=""):
    value = input(label + (f" [{default}]" if default else "") + ": ").strip()
    return value or default
def run(cmd):
    print("+", " ".join(map(str, cmd)))
    subprocess.check_call(list(map(str, cmd)))
def main():
    print("\n=== BotHub Node - configuração automática ===")
    print("Este agente registra os recursos do dispositivo no servidor BotHub.")
    if sys.version_info < (3, 9):
        raise SystemExit("Python 3.9+ é necessário. Instale Python 3 e tente novamente.")
    ROOT.mkdir(parents=True, exist_ok=True)
    if not PY.exists():
        print("Criando ambiente virtual...")
        run([sys.executable, "-m", "venv", ROOT / "venv"])
    REQ.write_text("requests>=2.31,<3\npsutil>=5.9,<8\n", encoding="utf-8")
    print("Instalando/atualizando dependências no venv...")
    run([PY, "-m", "pip", "install", "--upgrade", "pip"])
    run([PY, "-m", "pip", "install", "-r", REQ])
    existing = {}
    if CONFIG.exists():
        try: existing = json.loads(CONFIG.read_text(encoding="utf-8"))
        except Exception: pass
    api = ask("URL HTTPS da API BotHub", existing.get("api_url", "")).rstrip("/")
    if not api.startswith("https://") and not api.startswith("http://127.0.0.1") and not api.startswith("http://localhost"):
        raise SystemExit("Por segurança, use HTTPS para a API fora do próprio dispositivo.")
    device = ask("ID deste tablet/servidor", existing.get("device_id", platform.node() or secrets.token_hex(4)))
    token = ask("Token individual do worker", existing.get("worker_token", ""))
    if len(token) < 24:
        raise SystemExit("Token muito curto. Gere um token aleatório de pelo menos 24 caracteres no painel/API.")
    config = {"api_url": api, "device_id": device, "worker_token": token, "heartbeat_seconds": 30}
    CONFIG.write_text(json.dumps(config, indent=2), encoding="utf-8")
    try: CONFIG.chmod(0o600)
    except OSError: pass
    WORKER.write_text(WORKER_SOURCE, encoding="utf-8")
    try: WORKER.chmod(0o700)
    except OSError: pass
    boot = Path.home() / ".termux" / "boot"
    boot_script = boot / "bothub-start.sh"
    if "com.termux" in os.environ.get("PREFIX", "") and boot.exists():
        boot_script.write_text("#!/data/data/com.termux/files/usr/bin/sh\ntermux-wake-lock\n" +
            f'"{PY}" "{WORKER}" >> "$HOME/.bothub/worker.log" 2>&1\n', encoding="utf-8")
        boot_script.chmod(0o700)
        print("Inicialização automática configurada em Termux:Boot.")
    else:
        starter = ROOT / "iniciar.sh"
        starter.write_text("#!/bin/sh\n" + f'exec "{PY}" "{WORKER}"\n', encoding="utf-8")
        starter.chmod(0o700)
        print("Para iniciar o agente: sh ~/.bothub/iniciar.sh")
        print("No Termux, instale Termux:Boot e crie ~/.termux/boot para iniciar após reinicialização.")
    print("\nInstalação local concluída. Configuração:", CONFIG)
    print("A API central precisa estar publicada e aceitar /api/worker/heartbeat.")
    print("Iniciando agente agora...")
    os.execv(str(PY), [str(PY), str(WORKER)])
if __name__ == "__main__":
    try: main()
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"Falha ao instalar dependências (código {e.returncode}). Confira a internet e tente novamente.")
