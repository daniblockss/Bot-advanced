#!/usr/bin/env bash
# BotHub automatic installer/launcher for Termux and common Linux systems.
set -Eeuo pipefail

REPO="https://raw.githubusercontent.com/daniblockss/Bot-advanced/main"
APP_DIR="${BOTHUB_INSTALL_DIR:-$HOME/BotHub}"
cd "$HOME"

say(){ printf '\n[BotHub] %s\n' "$*"; }
fail(){ say "ERRO: $*"; exit 1; }

if ! command -v python3 >/dev/null 2>&1; then
  if command -v pkg >/dev/null 2>&1; then
    say "Python não encontrado. Instalando pelo gerenciador do Termux..."
    pkg update -y
    pkg install -y python curl
  elif command -v apt-get >/dev/null 2>&1; then
    say "Python não encontrado. Instalando pelo APT..."
    if [ "$(id -u)" -eq 0 ]; then apt-get update && apt-get install -y python3 python3-venv python3-pip curl
    elif command -v sudo >/dev/null 2>&1; then sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip curl
    else fail "Python ausente e sem permissão de instalar pacotes. Instale Python 3 e execute novamente."; fi
  else
    fail "Não encontrei Python 3 nem um gerenciador de pacotes compatível. Em Android, use Termux."
  fi
fi
command -v curl >/dev/null 2>&1 || {
  if command -v pkg >/dev/null 2>&1; then pkg install -y curl
  elif command -v apt-get >/dev/null 2>&1; then
    if [ "$(id -u)" -eq 0 ]; then apt-get install -y curl
    elif command -v sudo >/dev/null 2>&1; then sudo apt-get install -y curl
    else fail "curl não está instalado e não tenho permissão para instalá-lo."; fi
  else fail "curl é necessário para baixar os arquivos."; fi
}

mkdir -p "$APP_DIR"
cd "$APP_DIR"
say "Baixando o agente e o painel HTML..."
curl -fLsS "$REPO/bothub_cluster.py" -o bothub_cluster.py
curl -fLsS "$REPO/bothub_panel.html" -o bothub_panel.html
python3 - <<'PY'
from pathlib import Path
p=Path("bothub_cluster.py")
if not p.exists() or p.stat().st_size < 10000:
    raise SystemExit("Download de bothub_cluster.py incompleto; instalação cancelada.")
if not Path("bothub_panel.html").exists() or Path("bothub_panel.html").stat().st_size < 1000:
    raise SystemExit("Download do painel incompleto; instalação cancelada.")
print("[BotHub] Arquivos conferidos.")
PY

if ! python3 -m venv .venv >/dev/null 2>&1; then
  if command -v pkg >/dev/null 2>&1; then
    say "Preparando ambiente Python do Termux..."
    pkg install -y python
    python3 -m venv .venv || fail "Não consegui criar o ambiente Python."
  else
    say "O módulo venv parece ausente; tentando instalar o pacote de suporte..."
    if command -v apt-get >/dev/null 2>&1; then
      if [ "$(id -u)" -eq 0 ]; then apt-get install -y python3-venv
      elif command -v sudo >/dev/null 2>&1; then sudo apt-get install -y python3-venv
      fi
    fi
    python3 -m venv .venv || fail "Não consegui criar .venv. Verifique se o pacote python3-venv está instalado."
  fi
fi
PY="$APP_DIR/.venv/bin/python"
say "Verificando e instalando automaticamente as dependências ausentes..."
"$PY" -m pip install --upgrade pip
"$PY" -m pip install psutil discord.py aiohttp Pillow

read_value(){
  local label="$1" default="${2:-}" value
  if [ -n "$default" ]; then read -r -p "$label [$default]: " value || true; value="${value:-$default}"
  else read -r -p "$label: " value || true; fi
  printf '%s' "$value"
}
NODE_ID="${BOTHUB_NODE_ID:-}"
if [ -z "$NODE_ID" ]; then NODE_ID="$(read_value 'ID único deste dispositivo (ex.: tablet-a)' "node-$(hostname 2>/dev/null | tr -cd '[:alnum:]-' | cut -c1-20)")"; fi
[ -n "$NODE_ID" ] || fail "O ID do nó não pode ficar vazio."

SECRET="${BOTHUB_CLUSTER_SECRET:-}"
if [ -z "$SECRET" ]; then
  SECRET="$( "$PY" -c 'import secrets; print(secrets.token_hex(32))' )"
  say "Gerei um segredo de cluster. Guarde-o; todos os nós autorizados precisam usar exatamente o mesmo segredo."
  printf 'Segredo do cluster: %s\n' "$SECRET"
  printf 'Copie-o diretamente para os outros dispositivos autorizados; não o envie no chat nem publique no GitHub.\n'
fi
ADMIN="${BOTHUB_ADMIN_TOKEN:-}"
if [ -z "$ADMIN" ]; then
  ADMIN="$( "$PY" -c 'import secrets; print(secrets.token_hex(24))' )"
  say "Token administrativo gerado (guarde-o; ele não será mostrado novamente ao iniciar)."
  printf 'Token administrativo: %s\n' "$ADMIN"
fi
PEERS="${BOTHUB_CLUSTER_PEERS_JSON:-}"
if [ -z "$PEERS" ]; then
  printf '\nPares no formato JSON, sem incluir o ID deste nó. Exemplo: {"tablet-b":"http://192.168.1.22:47800"}\n'
  PEERS="$(read_value 'Pares (Enter se este for o primeiro nó)' '{}')"
fi
"$PY" - "$NODE_ID" "$SECRET" "$ADMIN" "$PEERS" <<'PY'
import json,sys
node,secret,admin,peers=sys.argv[1:]
try: peers_obj=json.loads(peers)
except Exception as e: raise SystemExit("JSON de pares inválido: "+str(e))
if not isinstance(peers_obj,dict): raise SystemExit("Os pares precisam ser um objeto JSON.")
if node in peers_obj: raise SystemExit("O ID deste nó não pode aparecer na lista de pares.")
if len(secret)<32 or len(admin)<24: raise SystemExit("Segredo/token curtos demais.")
from pathlib import Path
import os
vals={"BOTHUB_NODE_ID":node,"BOTHUB_CLUSTER_SECRET":secret,"BOTHUB_ADMIN_TOKEN":admin,"BOTHUB_CLUSTER_PEERS_JSON":json.dumps(peers_obj,separators=(",",":"))}
p=Path("bothub.env")
with p.open("w",encoding="utf-8") as f:
    for k,v in vals.items():
        if any(c in v for c in "\n\r\0"): raise SystemExit("Valor inválido.")
        f.write(k+"="+json.dumps(v,ensure_ascii=False)+"\n")
try: p.chmod(0o600)
except OSError: pass
print("Configuração privada gravada em",p)
PY

cat > run_bothub.sh <<'RUN'
#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"
set -a
. ./bothub.env
set +a
exec ./.venv/bin/python bothub_cluster.py
RUN
cat > admin_bothub.sh <<'ADMIN'
#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"
set -a
. ./bothub.env
set +a
exec ./.venv/bin/python bothub_cluster.py admin
ADMIN
chmod 700 run_bothub.sh admin_bothub.sh
chmod 600 bothub.env

say "Instalação concluída. Iniciando o nó BotHub..."
say "Para abrir o painel, no navegador DESTE dispositivo acesse: http://127.0.0.1:47800/admin/ui"
say "Token administrativo fica guardado em bothub.env; não publique nem compartilhe esse arquivo."
say "Para iniciar depois: $APP_DIR/run_bothub.sh"
say "Para usar o CLI administrativo: $APP_DIR/admin_bothub.sh"
exec "$APP_DIR/run_bothub.sh"
