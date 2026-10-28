#!/data/data/com.termux/files/usr/bin/bash
# BotHub Firebase worker installer for Termux/Linux; downloads files and installs missing Python packages.
set -Eeuo pipefail
REPO="https://raw.githubusercontent.com/daniblockss/Bot-advanced/main"
ROOT="${BOTHUB_INSTALL_DIR:-$HOME/.bothub}"
say(){ printf '\n[BotHub] %s\n' "$*"; }
if ! command -v python3 >/dev/null 2>&1; then
  if command -v pkg >/dev/null 2>&1; then pkg update -y; pkg install -y python curl
  elif command -v apt-get >/dev/null 2>&1; then
    if [ "$(id -u)" -eq 0 ]; then apt-get update; apt-get install -y python3 python3-venv python3-pip curl
    elif command -v sudo >/dev/null 2>&1; then sudo apt-get update; sudo apt-get install -y python3 python3-venv python3-pip curl
    else echo "Instale Python 3 e execute novamente."; exit 1; fi
  else echo "Python 3 não encontrado. Instale Python pelo gerenciador do sistema e execute novamente."; exit 1; fi
fi
if ! command -v curl >/dev/null 2>&1; then
  if command -v pkg >/dev/null 2>&1; then pkg install -y curl
  elif command -v apt-get >/dev/null 2>&1; then
    if [ "$(id -u)" -eq 0 ]; then apt-get install -y curl
    elif command -v sudo >/dev/null 2>&1; then sudo apt-get install -y curl
    else echo "curl não instalado."; exit 1; fi
  fi
fi
mkdir -p "$ROOT"; cd "$ROOT"
say "Baixando worker Firebase..."
curl -fLsS "$REPO/bothub_firebase_worker.py" -o bothub_firebase_worker.py
python3 - <<'PY'
from pathlib import Path
p=Path("bothub_firebase_worker.py")
if not p.exists() or p.stat().st_size<3000:raise SystemExit("Download incompleto; cancelado.")
print("Worker conferido.")
PY
if [ ! -x "$ROOT/venv/bin/python" ]; then
  say "Criando ambiente Python isolado..."
  python3 -m venv "$ROOT/venv" || {
    if command -v pkg >/dev/null 2>&1; then pkg install -y python; python3 -m venv "$ROOT/venv"; 
    else echo "Não foi possível criar venv. Instale python3-venv e tente novamente."; exit 1; fi
  }
fi
PY="$ROOT/venv/bin/python"
say "Instalando/verificando dependências..."
"$PY" -m pip install --disable-pip-version-check --upgrade pip
"$PY" -m pip install requests psutil discord.py aiohttp Pillow
say "Instalação pronta. O worker vai pedir o ID do dispositivo e as credenciais Firebase próprias deste worker."
exec "$PY" "$ROOT/bothub_firebase_worker.py"
