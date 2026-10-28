#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Painel para gerenciar vários bots Discord independentes."""
import datetime, hashlib, json, os, shutil, signal, subprocess, sys, threading, time
import urllib.request, urllib.error
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent
BOTS = ROOT / "bots"
VENV = ROOT / ".venv"
STATE = ROOT / "painel_bots.json"
URL = "https://raw.githubusercontent.com/daniblockss/Bot-advanced/refs/heads/main/main8.py"
URL_PAINEL = "https://raw.githubusercontent.com/daniblockss/Bot-advanced/refs/heads/main/painel.py"
INTERVALO_ATUALIZACAO = 300
PACOTES = ["discord.py", "aiohttp", "requests"]


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
    resposta = requests.get(URL, headers={"User-Agent": "BotAdvancedPanel/1.0", "Cache-Control": "no-cache"}, timeout=30)
    resposta.raise_for_status()
    dados = resposta.content
    if len(dados) < 10000:
        raise RuntimeError("O arquivo baixado parece incompleto; atualização cancelada.")
    return dados


def obter_info_publicacao():
    """Consulta a data do commit publicado para main8.py no GitHub."""
    try:
        resposta = requests.get(
            "https://api.github.com/repos/daniblockss/Bot-advanced/commits",
            params={"path": "main8.py", "per_page": 1},
            headers={"Accept": "application/vnd.github+json", "User-Agent": "BotAdvancedPanel/1.0"},
            timeout=15,
        )
        resposta.raise_for_status()
        itens = resposta.json()
        commit = itens[0] if isinstance(itens, list) and itens else {}
        info = commit.get("commit", {})
        autor = info.get("author") or info.get("committer") or {}
        return {"commit_sha": commit.get("sha", ""), "published_at": autor.get("date", "")}
    except (requests.RequestException, ValueError, IndexError, TypeError):
        return {"commit_sha": "", "published_at": ""}


def idade_publicacao(data_iso):
    if not data_iso:
        return "data de publicação indisponível"
    try:
        instante = datetime.datetime.fromisoformat(data_iso.replace("Z", "+00:00"))
        segundos = max(0, int((datetime.datetime.now(datetime.timezone.utc) - instante.astimezone(datetime.timezone.utc)).total_seconds()))
        if segundos < 3600:
            return f"há {max(1, segundos // 60)} minuto(s)"
        if segundos < 86400:
            return f"há {segundos // 3600} hora(s)"
        return f"há {segundos // 86400} dia(s)"
    except (ValueError, TypeError):
        return "data de publicação indisponível"


def salvar_versao_bot(pasta, hash_script, info):
    registro = {
        "sha256": hash_script,
        "commit_sha": info.get("commit_sha", ""),
        "published_at": info.get("published_at", ""),
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    destino = pasta / "main8.version.json"
    temporario = destino.with_suffix(".tmp")
    temporario.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(destino)


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
        self._log_offsets = {}
        self._erros_vistos = set()
        self._afk_index = 0
        self._cpu_sample = None
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
            cfg = {"discord_token": token, "apis": [], "criadores_ids": [1252679441629315144],
                   "criador_supremo": 1252679441629315144, "raiz_permissoes": {}, "canais_configurados": {},
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
            self._log_offsets[nome] = log.tell()
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
            info_publicacao = obter_info_publicacao()
            if info_publicacao.get("published_at"):
                print(f"[Atualização] Código do GitHub publicado {idade_publicacao(info_publicacao['published_at'])}.")
        except Exception as e:
            print(f"[Atualização] Verificação falhou: {type(e).__name__}.")
            return
        novo_hash = hashlib.sha256(novo).hexdigest()
        self.script = novo
        alvos = []
        for nome in list(self.estado["bots"]):
            script_local = self.pasta(nome) / "main8.py"
            try:
                hash_local = hashlib.sha256(script_local.read_bytes()).hexdigest()
            except OSError:
                hash_local = ""
            if hash_local != novo_hash:
                alvos.append(nome)
        self.hash_script = novo_hash
        if not alvos:
            for nome in list(self.estado["bots"]):
                try:
                    salvar_versao_bot(self.pasta(nome), novo_hash, info_publicacao)
                except OSError:
                    pass
            print("[Atualização] Todos os bots já estão na versão atual.")
            return
        print(f"[Atualização] Atualizando {len(alvos)} bot(s)...")
        for nome in alvos:
            pasta = self.pasta(nome)
            script = pasta / "main8.py"
            backup = pasta / "main8.py.previous"
            proc = self.processos.get(nome)
            estava_rodando = bool(proc and proc.poll() is None)
            try:
                if estava_rodando:
                    self.notificar(pasta, "atualizando")
                    self.parar(nome)
                if script.exists():
                    shutil.copy2(script, backup)
                temp = pasta / "main8.py.tmp"
                temp.write_bytes(novo)
                temp.replace(script)
                teste = subprocess.run([str(pyvenv()), str(script), "--self-test"], cwd=pasta,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
                if teste.returncode != 0:
                    print(f"{nome}: autoteste falhou; restaurando versão anterior.")
                    if backup.exists():
                        shutil.copy2(backup, script)
                    if estava_rodando:
                        self.iniciar(nome)
                    continue
                salvar_versao_bot(pasta, novo_hash, info_publicacao)
                if estava_rodando:
                    self.iniciar(nome)
                    self.notificar(pasta, "atualizado")
                print(f"{nome}: atualizado" + (" e reiniciado." if estava_rodando else "."))
            except Exception as e:
                print(f"{nome}: atualização falhou ({type(e).__name__}).")
                if backup.exists():
                    shutil.copy2(backup, script)
                if estava_rodando:
                    try:
                        self.iniciar(nome)
                    except Exception:
                        pass

    def metricas_sistema(self):
        memoria_total = memoria_disponivel = None
        cpu = None
        try:
            if os.path.exists("/proc/meminfo"):
                dados = {}
                with open("/proc/meminfo", encoding="utf-8") as f:
                    for linha in f:
                        partes = linha.split()
                        if len(partes) >= 2:
                            dados[partes[0].rstrip(":")] = int(partes[1])
                memoria_total = dados.get("MemTotal", 0) // 1024
                memoria_disponivel = dados.get("MemAvailable", dados.get("MemFree", 0)) // 1024
            if os.path.exists("/proc/stat"):
                with open("/proc/stat", encoding="utf-8") as f:
                    campos = list(map(int, f.readline().split()[1:]))
                total = sum(campos[:8])
                ocioso = campos[3] + (campos[4] if len(campos) > 4 else 0)
                anterior = self._cpu_sample
                self._cpu_sample = (total, ocioso)
                if anterior and total > anterior[0]:
                    cpu = max(0.0, min(100.0, (1 - (ocioso-anterior[1])/(total-anterior[0])) * 100))
            else:
                try:
                    import psutil
                    memoria = psutil.virtual_memory()
                    memoria_total = int(memoria.total / 1048576)
                    memoria_disponivel = int(memoria.available / 1048576)
                    cpu = float(psutil.cpu_percent(interval=0.1))
                except ImportError:
                    pass
        except (OSError, ValueError, IndexError):
            pass
        rodando = [(nome, proc.pid) for nome, proc in list(self.processos.items()) if proc and proc.poll() is None]
        usos = []
        for _, pid in rodando:
            try:
                with open(f"/proc/{pid}/status", encoding="utf-8") as f:
                    for linha in f:
                        if linha.startswith("VmRSS:"):
                            usos.append(int(linha.split()[1]) // 1024)
                            break
            except (OSError, ValueError, IndexError):
                pass
        media_bot = max(250, int(sum(usos) / len(usos))) if usos else 250
        restantes = max(0, memoria_disponivel // media_bot) if memoria_disponivel is not None else None
        return memoria_total, memoria_disponivel, cpu, len(rodando), restantes, media_bot

    def mostrar_status(self):
        total, livre, cpu, rodando, restantes, media = self.metricas_sistema()
        ram = f"RAM: {livre} MB livres / {total} MB" if livre is not None else "RAM: indisponível"
        cpu_txt = f"CPU: {cpu:.1f}%" if cpu is not None else "CPU: calculando/indisponível"
        capacidade = f"Estimativa: +{restantes} bot(s) por RAM (base ~{media} MB/bot)" if restantes is not None else "Estimativa de bots: indisponível"
        print(f"\n📊 {ram} | {cpu_txt} | Bots rodando: {rodando} | {capacidade}")

    def mostrar_log_afk(self):
        nomes = list(self.estado["bots"])
        if not nomes:
            print("\n[AFK] Nenhum bot cadastrado.")
            return
        nome = nomes[self._afk_index % len(nomes)]
        self._afk_index += 1
        caminho = self.pasta(nome) / "bot.log"
        try:
            linhas = caminho.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            linhas = []
        print(f"\n--- LOG AFK: {nome} (últimas 8 linhas) ---")
        print("\n".join(linhas[-8:]) if linhas else "(log vazio)")
        print("Pressione qualquer tecla para voltar ao painel.")

    def ler_comando_afk(self, prompt):
        if not sys.stdin.isatty():
            return input(prompt)
        print(prompt, end="", flush=True)
        buffer = ""
        ultima_tecla = time.monotonic()
        ultima_troca = 0.0
        em_afk = False
        if os.name == "nt":
            import msvcrt
            while True:
                if msvcrt.kbhit():
                    tecla = msvcrt.getwch()
                    if em_afk:
                        print("\nVoltando ao painel...\n")
                        return ""
                    ultima_tecla = time.monotonic()
                    if tecla in ("\r", "\n"):
                        print()
                        return buffer
                    if tecla == "\x03":
                        raise KeyboardInterrupt
                    if tecla == "\x08":
                        if buffer:
                            buffer = buffer[:-1]
                            print("\b \b", end="", flush=True)
                    elif tecla not in ("\x00", "\xe0"):
                        buffer += tecla
                        print(tecla, end="", flush=True)
                elif time.monotonic() - ultima_tecla >= 30:
                    em_afk = True
                    if time.monotonic() - ultima_troca >= 8:
                        self.mostrar_log_afk()
                        ultima_troca = time.monotonic()
                    time.sleep(0.08)
                else:
                    time.sleep(0.05)
        else:
            import select, termios, tty
            fd = sys.stdin.fileno()
            antigo = termios.tcgetattr(fd)
            try:
                tty.setcbreak(fd)
                while True:
                    pronto, _, _ = select.select([sys.stdin], [], [], 0.2)
                    if pronto:
                        tecla = sys.stdin.read(1)
                        if em_afk:
                            print("\nVoltando ao painel...\n")
                            return ""
                        ultima_tecla = time.monotonic()
                        if tecla in ("\r", "\n"):
                            print()
                            return buffer
                        if tecla == "\x03":
                            raise KeyboardInterrupt
                        if tecla in ("\x7f", "\b"):
                            if buffer:
                                buffer = buffer[:-1]
                                print("\b \b", end="", flush=True)
                        else:
                            buffer += tecla
                            print(tecla, end="", flush=True)
                    elif time.monotonic() - ultima_tecla >= 30:
                        em_afk = True
                        if time.monotonic() - ultima_troca >= 8:
                            self.mostrar_log_afk()
                            ultima_troca = time.monotonic()
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, antigo)

    def monitorar_erros(self):
        padrao = ("traceback", "exception", "error", "critical", "falha ao", "erro:")
        while not self.parar_atualizador.wait(2):
            for nome in list(self.estado["bots"]):
                caminho = self.pasta(nome) / "bot.log"
                try:
                    tamanho = caminho.stat().st_size
                    offset = self._log_offsets.get(nome, tamanho)
                    if tamanho < offset:
                        offset = 0
                    with caminho.open("rb") as f:
                        f.seek(offset)
                        novos = f.read()
                        self._log_offsets[nome] = f.tell()
                    texto = novos.decode("utf-8", errors="replace")
                except OSError:
                    continue
                for linha in texto.splitlines():
                    baixa = linha.lower()
                    if not any(p in baixa for p in padrao):
                        continue
                    assinatura = (nome, linha.strip()[:240])
                    if assinatura in self._erros_vistos:
                        continue
                    self._erros_vistos.add(assinatura)
                    if len(self._erros_vistos) > 500:
                        self._erros_vistos.clear()
                        self._erros_vistos.add(assinatura)
                    for _ in range(3):
                        print(f"\n⚠️ ERRO DETECTADO — {nome}. Verificar agora.\n⚠️ Erro detectado no painel: bots/{nome}/bot.log")
                        time.sleep(0.35)

    def verificar_atualizacao_painel(self):
        """Atualiza o próprio painel a partir do GitHub e reinicia o processo."""
        caminho = Path(__file__).resolve()
        temporario = caminho.with_suffix(".py.update.tmp")
        backup = caminho.with_suffix(".py.previous")
        try:
            resposta = requests.get(
                URL_PAINEL,
                headers={"User-Agent": "BotAdvancedPanel/1.0", "Cache-Control": "no-cache"},
                timeout=30,
            )
            resposta.raise_for_status()
            novo = resposta.content
            if len(novo) < 3000:
                raise RuntimeError("O arquivo remoto parece incompleto.")
            codigo = novo.decode("utf-8")
            compile(codigo, str(caminho), "exec")
            atual = caminho.read_bytes()
            if hashlib.sha256(atual).hexdigest() == hashlib.sha256(novo).hexdigest():
                print("[Painel] O painel já está atualizado.")
                return False
            temporario.write_bytes(novo)
            # Confirma que o arquivo temporário contém Python sintaticamente válido.
            compile(temporario.read_text(encoding="utf-8"), str(temporario), "exec")
            shutil.copy2(caminho, backup)
            temporario.replace(caminho)
            print("[Painel] Nova versão instalada. Reiniciando o painel...")
            sys.stdout.flush()
            sys.stderr.flush()
            os.execv(sys.executable, [sys.executable, str(caminho), *sys.argv[1:]])
            return True
        except Exception as e:
            try:
                if temporario.exists():
                    temporario.unlink()
            except OSError:
                pass
            print(f"[Painel] Atualização automática do próprio painel falhou: {type(e).__name__}: {e}")
            return False

    def atualizador(self):
        while not self.parar_atualizador.wait(INTERVALO_ATUALIZACAO):
            if self.verificar_atualizacao_painel():
                return
            self.verificar_atualizacao()

    def encerrar(self):
        print("\nEncerrando todos os bots...")
        self.parar_atualizador.set()
        for nome in list(self.processos):
            self.parar(nome)
        print("Todos os bots iniciados por este painel foram encerrados.")

    def executar(self):
        self.verificar_atualizacao_painel()
        self.verificar_atualizacao()
        threading.Thread(target=self.atualizador, daemon=True).start()
        for nome, info in self.estado["bots"].items():
            if info.get("enabled", True):
                try: self.iniciar(nome)
                except Exception as e: print(f"{nome}: falha ao iniciar ({type(e).__name__}).")
        threading.Thread(target=self.monitorar_erros, daemon=True).start()
        while True:
            print("\n" + "=" * 48 + "\nPAINEL DE BOTS DISCORD\n" + "=" * 48)
            self.mostrar_status()
            print("1. Adicionar novo bot\n2. Apagar bot\n3. Ver log de um bot\n4. Listar bots")
            print("5. Iniciar bot parado\n6. Parar um bot\n7. Verificar atualização agora\n0. Sair e desligar todos")
            try: escolha = self.ler_comando_afk("Comando: ").strip()
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