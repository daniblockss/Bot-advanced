#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Private interactive CLI for the BotHub administrator. Keep its config private."""
import json, os, sys, getpass, urllib.request, urllib.error
from pathlib import Path

ROOT = Path.home() / ".bothub-admin"
CONFIG = ROOT / "config.json"

def request(api, token, method, path, payload=None):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(api.rstrip("/") + path, data=body, method=method,
        headers={"Authorization":"Bearer " + token, "Content-Type":"application/json",
                 "User-Agent":"BotHub-Admin/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw=resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        try: detail=e.read().decode("utf-8")[:500]
        except Exception: detail=str(e)
        raise RuntimeError(f"API HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Não foi possível conectar à API: {e.reason}") from e

def load_config():
    ROOT.mkdir(parents=True,exist_ok=True)
    if CONFIG.exists():
        try: return json.loads(CONFIG.read_text(encoding="utf-8"))
        except Exception: pass
    api=input("URL HTTPS da API BotHub: ").strip().rstrip("/")
    if not api.startswith("https://") and not api.startswith("http://127.0.0.1") and not api.startswith("http://localhost"):
        raise SystemExit("Use HTTPS fora do próprio dispositivo.")
    token=getpass.getpass("Token administrativo (não será exibido): ").strip()
    if len(token)<24: raise SystemExit("Token administrativo muito curto.")
    data={"api_url":api,"admin_token":token}
    CONFIG.write_text(json.dumps(data,indent=2),encoding="utf-8")
    try: CONFIG.chmod(0o600)
    except OSError: pass
    return data

def discord_validate(bot_token):
    req=urllib.request.Request("https://discord.com/api/v10/users/@me",
        headers={"Authorization":"Bot "+bot_token,"User-Agent":"BotHub-Admin/1.0"})
    try:
        with urllib.request.urlopen(req,timeout=15) as resp:
            info=json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401,403): raise RuntimeError("Token Discord inválido ou sem autorização.") from e
        raise RuntimeError(f"Discord respondeu HTTP {e.code}.") from e
    except Exception as e: raise RuntimeError(f"Falha ao validar token Discord: {type(e).__name__}") from e
    if not info.get("id") or not info.get("username"): raise RuntimeError("Perfil do bot não retornado.")
    return info

def show_status(data):
    s=request(data["api_url"],data["admin_token"],"GET","/api/admin/status")
    print("\n=== STATUS BOT HUB ===")
    print("Workers com slots livres:",s.get("available_nodes",0))
    print("Workers online com recursos:",s.get("online_capacity_nodes",0))
    print("Bots ativos:",s.get("active_bots",0))
    print("Bots na fila:",s.get("queued_bots",0))
    for n in s.get("nodes",[]):
        print(f" - {n['device_id']}: {'ONLINE' if n.get('online') else 'OFFLINE'} | "
              f"RAM livre {int(n.get('ram_free_bytes') or 0)//(1024*1024)} MB | "
              f"disco livre {int(n.get('disk_free_bytes') or 0)//(1024**3)} GB")
    print()

def show_bots(data):
    result=request(data["api_url"],data["admin_token"],"GET","/api/admin/bots")
    bots=result.get("bots",[])
    if not bots: print("Nenhum bot cadastrado."); return
    for b in bots:
        status="ATIVO" if b.get("enabled") else "DESATIVADO"
        worker=b.get("worker_id") or "NA FILA"
        print(f"{b['bot_id']} | {b['bot_name']} | {status} | worker: {worker}")

def add_bot(data):
    name=input("Nome para identificar o bot: ").strip()
    if not name: print("Cancelado: nome vazio."); return
    token=getpass.getpass("Token do bot Discord (não será exibido): ").strip()
    if not token: print("Cancelado: token vazio."); return
    profile=discord_validate(token)
    print(f"Token validado: {profile['username']} (ID {profile['id']}).")
    confirm=input("Cadastrar esse bot no BotHub? (s/N): ").strip().lower()
    if confirm!="s": print("Cancelado."); return
    result=request(data["api_url"],data["admin_token"],"POST","/api/admin/bots",
                   {"bot_name":name,"discord_token":token,"config":{}})
    print("Bot cadastrado:",result.get("bot_id"),"|",result.get("message",""))

def change_bot(data, enabled):
    bot_id=input("ID do bot: ").strip()
    result=request(data["api_url"],data["admin_token"],"PATCH","/api/admin/bots/"+bot_id,
                   {"enabled":enabled})
    print("Operação concluída:",result)

def delete_bot(data):
    bot_id=input("ID exato do bot para excluir: ").strip()
    if input("Isso remove o cadastro central. Continuar? (s/N): ").strip().lower()!="s":
        print("Cancelado."); return
    print(request(data["api_url"],data["admin_token"],"DELETE","/api/admin/bots/"+bot_id))

def main():
    print("BotHub — painel privado do administrador")
    data=load_config()
    while True:
        print("\n1. Status dos servidores e fila\n2. Listar bots\n3. Cadastrar bot\n"
              "4. Desativar bot\n5. Reativar bot\n6. Excluir bot\n7. Verificar conexão\n0. Sair")
        choice=input("Opção: ").strip()
        try:
            if choice=="1": show_status(data)
            elif choice=="2": show_bots(data)
            elif choice=="3": add_bot(data)
            elif choice=="4": change_bot(data,False)
            elif choice=="5": change_bot(data,True)
            elif choice=="6": delete_bot(data)
            elif choice=="7": print(request(data["api_url"],data["admin_token"],"GET","/health"))
            elif choice=="0": break
            else: print("Opção inválida.")
        except KeyboardInterrupt: print("\nOperação cancelada.")
        except Exception as e: print("ERRO:",e)
if __name__=="__main__":
    try: main()
    except KeyboardInterrupt: print("\nEncerrado.")
