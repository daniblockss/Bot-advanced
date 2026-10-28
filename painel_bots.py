#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Painel para gerenciar vários bots Discord independentes."""
import hashlib, json, os, shutil, signal, subprocess, sys, threading, time
import urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BOTS = ROOT / "bots"
VENV = ROOT / ".venv"
STATE = ROOT / "painel_bots.json"
URL = "https://raw.githubusercontent.com/daniblockss/Bot-advanced/refs/heads/main/main8.py"
INTERVALO_ATUALIZACAO = 300
PACOTES = ["discord.py", "aiohttp", "Pillow"]


def pyvenv():
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def instalar_dependencias():
    if not VENV.exists():
        print("[Painel] Criando venv...")
        import venv
        venv.EnvBuilder(with_pip=True).create(VENV)
    else:
        print("[Painel] venv existente; reutilizando.")
    if not pyvenv().exists():
        raise RuntimeError("venv inválido. Apague a pasta .venv e execute novamente.")
    subprocess.run([str(pyvenv()), "-m", "pip", "install", "--disable-pip-version-check",
                    "--upgrade", *PACOTES], check=True)


def baixar_script():
    req = urllib.request.Request(URL, headers={"User-Agent": "BotAdvancedPanel/1.0", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        dados = resp.read()
    if len(dados) < 10000:
        raise RuntimeError("O arquivo baixado parece incompleto; atualização cancelada.")
    return dados


def carregar_estado():
    try:
        dados = json.loads(STATE.read_text(encoding="utf-8"))
        if isinstance(dados, dict) and isinstance(dados.get("bots"), dict):
            return dados
    except (OSError, json.JSONDecodeError):
        pass
    return {"bots": {}}


def salvar_estado():
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(self.estado, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE)


def nome_seguro(nome):
    nome = "".join(c for c in nome.strip() if c.isalnum() or c in " _-.")
    nome = "_".join(nome.split()).strip("._-")
    return nome[:60] or "bot_nome_invalido"


def validar_token(token):
    req = urllib.request.Request("https://discord.com/api/v10/users/@me",
        headers={"Authorization": "Bot " + token, "User-Agent": "BotAdvancedPanel/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            info = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise ValueError("Token inválido ou sem autorização.") from e
        raise ValueError(f"Discord respondeu HTTP {e.code}.") from e
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise ValueError(f"Falha ao validar token: {type(e).__name__}.") from e
    if not info.get("id") or not info.get("username"):
        raise ValueError("O Discord não retornou os dados do bot.")
    return info


def mandar_mensagem(token, destino, texto):
    if not str(destino).isdigit():
        return False
    body = json.dumps({"content": texto, "allowed_mentions": {"parse": []}}).encode()
    req = urllib.request.Request(f"https://discord.com/api/v10/channels/{destino}/messages", data=body,
        headers={"Authorization": "Bot " + token, "Content-Type": "application/json",
                 "User-Agent": "BotAdvancedPanel/1.0"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return False


class Painel:
    def __init__(self):
        self.estado = carregar_estado()
        self.processos = {}
        self.lock = threading.RLock()
        self.parar_atualizador = threading.Event()
        self.script = baixar_script()
        self.hash_script = hashlib.sha256(self.script).hexdigest()
        BOTS.mkdir(exist_ok=True)
        for pasta in BOTS.iterdir():
            if pasta.is_dir() and (pasta / "main8.py").exists() and pasta.name not in self.estado["bots"]:
                self.estado["bots"][pasta.name] = {"folder": str(pasta), "enabled": True}
        self.salvar_estado()

    def salvar_estado(self):
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.estado, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(STATE)

    def pasta(self, nome):
        info = self.estado["bots"].get(nome, {})
        return Path(info.get("folder", BOTS / nome))

    def listar(self):
        if not self.estado["bots"]:
            print("Nenhum bot cadastrado.")
        for nome in self.estado["bots"]:
            proc = self.processos.get(nome)
            status = f"RODANDO PID={proc.pid}" if proc and proc.poll() is None else "PARADO"
            print(f" - {nome}: {status} | {self.pasta(nome)}")

    def adicionar(self):
        print("\n--- Adicionar novo bot ---")
        nome_digitado = input("Nome do bot (pode deixar vazio): ").strip()
        provisoria = nome_seguro(nome_digitado) if nome_digitado else "bot_nome_invalido"
        # Reserva uma pasta temporária; o nome final virá do perfil retornado pelo Discord.
        tmp = BOTS / (provisoria + "_temporario")
        n = 2
        while tmp.exists():
            tmp = BOTS / f"{provisoria}_temporario_{n}"; n += 1
        token = input("Token do bot: ").strip()
        if not token:
            print("Token vazio; cancelado."); return
        try:
            perfil = validar_token(token)
        except ValueError as e:
            print("Não foi possível adicionar:", e); return
        final = nome_seguro(perfil["username"])
        destino = BOTS / final
        n = 2
        while destino.exists():
            existente = self.ler_config(destino).get("discord_token", "")
            if existente == token:
                print("Esse bot já está cadastrado."); return
            destino = BOTS / f"{final}_{n}"; n += 1
        try:
            destino.mkdir(parents=True)
            (destino / "main8.py").write_bytes(self.script)
            cfg = {"discord_token": token, "apis": [], "criadores_ids": [],
                   "criador_supremo": 0, "raiz_permissoes": {}, "canais_configurados": {},
                   "tell_presets": {}, "format_security": {"salt": "", "hash": "", "attempts": 0, "blocked_until": 0},
                   "ai": {}}
            (destino / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            (destino / "bot_info.json").write_text(json.dumps({"bot_name": perfil["username"],
                "bot_id": str(perfil["id"])}, ensure_ascii=False, indent=2), encoding="utf-8")
            self.estado["bots"][destino.name] = {"folder": str(destino), "enabled": True,
                "bot_id": str(perfil["id"]), "bot_name": perfil["username"]}
            self.salvar_estado()
        except Exception as e:
            shutil.rmtree(destino, ignore_errors=True)
            print(f"Erro preparando bot: {type(e).__name__}: {e}"); return
        print(f"Bot {perfil['username']} salvo em bots/{destino.name}.")
        print("Opcional: no config.json desse bot, adicione update_notify_channel_id e/ou update_notify_admin_ids.")
        self.iniciar(destino.name)

    @staticmethod
    def ler_config(pasta):
        try:
            return json.loads((pasta / "config.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def iniciar(self, nome):
        with self.lock:
            proc = self.processos.get(nome)
            if proc and proc.poll() is None:
                print(f"{nome}: já está rodando."); return
            pasta = self.pasta(nome)
            script = pasta / "main8.py"
            if not script.exists():
                print(f"{nome}: main8.py não encontrado."); return
            log = open(pasta / "bot.log", "ab", buffering=0)
            try:
                proc = subprocess.Popen([str(pyvenv()), "-u", str(script)], cwd=pasta,
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                    creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0),
                    start_new_session=(os.name != "nt"))
            except Exception:
                log.close(); raise
            proc._painel_log = log
            self.processos[nome] = proc
            print(f"{nome}: iniciado PID {proc.pid}. Log: bots/{nome}/bot.log")

    def parar(self, nome):
        with self.lock:
            proc = self.processos.get(nome)
            if not proc or proc.poll() is not None:
                self.processos.pop(nome, None); print(f"{nome}: já estava parado."); return
            try:
                if os.name == "nt": proc.send_signal(signal.CTRL_BREAK_EVENT)
                else: os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
                try: proc.wait(timeout=5)
                except Exception: pass
            log = getattr(proc, "_painel_log", None)
            if log: log.close()
            self.processos.pop(nome, None)
            print(f"{nome}: parado.")

    def apagar(self):
        self.listar()
        nome = input("Nome exato da pasta do bot: ").strip()
        if nome not in self.estado["bots"]:
            print("Bot não encontrado."); return
        if input(f"Apagar bots/{nome} permanentemente? (s/N): ").strip().lower() != "s":
            print("Cancelado."); return
        self.parar(nome)
        shutil.rmtree(self.pasta(nome))
        del self.estado["bots"][nome]
        self.salvar_estado()
        print("Bot apagado.")

    def ver_log(self):
        self.listar()
        nome = input("Nome da pasta do bot: ").strip()
        log = self.pasta(nome) / "bot.log"
        if not log.exists():
            print("Ainda não há log."); return
        linhas = log.read_text(encoding="utf-8", errors="replace").splitlines()
        print("\n".join(linhas[-100:]) or "(log vazio)")

    def notificar(self, pasta, etapa):
        cfg = self.ler_config(pasta)
        token = str(cfg.get("discord_token", "")).strip()
        texto = ("🔄 Estou atualizando para a versão mais recente. Reiniciarei em instantes."
                 if etapa == "atualizando" else "✅ Atualização concluída. Estou pronto para uso.")
        canal = cfg.get("update_notify_channel_id", "")
        if canal:
            mandar_mensagem(token, str(canal), texto)
        admins = cfg.get("update_notify_admin_ids", [])
        if isinstance(admins, list):
            for uid in admins[:20]:
                if str(uid).isdigit():
                    # DM channel is created via Discord API first.
                    try:
                        body = json.dumps({"recipient_id": str(uid)}).encode()
                        req = urllib.request.Request("https://discord.com/api/v10/users/@me/channels", data=body,
                            headers={"Authorization": "Bot " + token, "Content-Type": "application/json"}, method="POST")
                        with urllib.request.urlopen(req, timeout=10) as r:
                            dm = json.loads(r.read().decode()).get("id")
                        if dm: mandar_mensagem(token, dm, texto)
                    except Exception:
                        pass

    def verificar_atualizacao(self):
        try:
            novo = baixar_script()
        except Exception as e:
            print(f"[Atualização] Verificação falhou: {type(e).__name__}."); return
        novo_hash = hashlib.sha256(novo).hexdigest()
        if novo_hash == self.hash_script:
            print("[Atualização] Todos os bots já estão na versão atual."); return
        print("[Atualização] Nova versão encontrada.")
        self.script, self.hash_script = novo, novo_hash
        for nome in list(self.estado["bots"]):
            pasta = self.pasta(nome)
            script = pasta / "main8.py"
            backup = pasta / "main8.py.previous"
            try:
                self.notificar(pasta, "atualizando")
                self.parar(nome)
                if script.exists(): shutil.copy2(script, backup)
                temp = pasta / "main8.py.tmp"
                temp.write_bytes(novo); temp.replace(script)
                teste = subprocess.run([str(pyvenv()), str(script), "--self-test"], cwd=pasta,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
                if teste.returncode != 0:
                    print(f"{nome}: autoteste falhou; restaurando versão anterior.")
                    if backup.exists(): shutil.copy2(backup, script)
                    self.iniciar(nome); continue
                self.iniciar(nome)
                self.notificar(pasta, "atualizado")
                print(f"{nome}: atualizado e reiniciado.")
            except Exception as e:
                print(f"{nome}: atualização falhou ({type(e).__name__}).")
                if backup.exists():
                    shutil.copy2(backup, script)
                    try: self.iniciar(nome)
                    except Exception: pass

    def atualizador(self):
        while not self.parar_atualizador.wait(INTERVALO_ATUALIZACAO):
            self.verificar_atualizacao()

    def encerrar(self):
        print("\nEncerrando todos os bots...")
        self.parar_atualizador.set()
        for nome in list(self.processos):
            self.parar(nome)
        print("Todos os bots iniciados por este painel foram encerrados.")

    def executar(self):
        threading.Thread(target=self.atualizador, daemon=True).start()
        for nome, info in self.estado["bots"].items():
            if info.get("enabled", True):
                try: self.iniciar(nome)
                except Exception as e: print(f"{nome}: falha ao iniciar ({type(e).__name__}).")
        while True:
            print("\n" + "=" * 48 + "\nPAINEL DE BOTS DISCORD\n" + "=" * 48)
            print("1. Adicionar novo bot\n2. Apagar bot\n3. Ver log de um bot\n4. Listar bots")
            print("5. Iniciar bot parado\n6. Parar um bot\n7. Verificar atualização agora\n0. Sair e desligar todos")
            try: escolha = input("Comando: ").strip()
            except (EOFError, KeyboardInterrupt): break
            try:
                if escolha == "1": self.adicionar()
                elif escolha == "2": self.apagar()
                elif escolha == "3": self.ver_log()
                elif escolha == "4": self.listar()
                elif escolha == "5":
                    self.listar(); self.iniciar(input("Nome da pasta: ").strip())
                elif escolha == "6":
                    self.listar(); self.parar(input("Nome da pasta: ").strip())
                elif escolha == "7": self.verificar_atualizacao()
                elif escolha == "0": break
                else: print("Comando inválido.")
            except KeyboardInterrupt:
                print("\nOperação cancelada.")
            except Exception as e:
                print(f"Erro: {type(e).__name__}: {e}")
        self.encerrar()


def main():
    print("Painel de Bots Discord — cada bot terá sua própria pasta/configuração.")
    try:
        instalar_dependencias()
        Painel().executar()
    except KeyboardInterrupt:
        print("\nPainel interrompido.")
    except Exception as e:
        print(f"ERRO: {type(e).__name__}: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
