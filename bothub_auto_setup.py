#!/usr/bin/env python3
# BotHub — diagnóstico automático do Firebase
# Não grava a senha e não altera permissões de administrador.
# A Web API Key do Firebase e o e-mail padrão ficam configurados abaixo.

import getpass
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

API_KEY = "AIzaSyDS_KvyPWGgzYqIVgkagw5DAwzlenNZtiE"
DB_URL = "https://bothub-bca02-default-rtdb.firebaseio.com"
EMAIL_PADRAO = "daniblocks100@gmail.com"
AUTH_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"


def requisicao(url, metodo="GET", dados=None, token=None):
    headers = {"Content-Type": "application/json"}
    # O Realtime Database REST aceita o ID token no parâmetro auth.
    # Usamos esse formato para evitar incompatibilidades com o cabeçalho Bearer.
    if token:
        partes = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(partes.query, keep_blank_values=True)
        query.append(("auth", token))
        url = urllib.parse.urlunsplit((
            partes.scheme,
            partes.netloc,
            partes.path,
            urllib.parse.urlencode(query),
            partes.fragment,
        ))
    corpo = None if dados is None else json.dumps(dados).encode()
    req = urllib.request.Request(url, data=corpo, headers=headers, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=15) as resposta:
            texto = resposta.read().decode()
            return resposta.status, json.loads(texto) if texto else None
    except urllib.error.HTTPError as erro:
        texto = erro.read().decode(errors="replace")
        try:
            return erro.code, json.loads(texto)
        except json.JSONDecodeError:
            return erro.code, {"error": {"message": texto}}
    except Exception as erro:
        return 0, {"error": {"message": str(erro)}}


def mensagem(resultado):
    """Converte respostas de erro do Firebase em texto sem quebrar."""
    if isinstance(resultado, dict):
        erro = resultado.get("error")
        if isinstance(erro, dict):
            return str(erro.get("message", resultado))
        if isinstance(erro, str):
            return erro
        return str(resultado)
    return str(resultado)


def main():
    print("=" * 48)
    print(" BotHub — configuração e diagnóstico")
    print("=" * 48)

    api_key = API_KEY.strip()
    if not api_key:
        print("Configure API_KEY no início do arquivo.")
        return

    email = EMAIL_PADRAO
    print(f"E-mail configurado automaticamente: {email}")
    senha = getpass.getpass("Senha Firebase (entrada oculta): ")
    senha_original = senha
    if not senha:
        print("Senha vazia.")
        return

    print("\n[1/4] Autenticando no Firebase...")
    status, dados = requisicao(
        AUTH_URL + "?key=" + urllib.parse.quote(api_key),
        metodo="POST",
        dados={"email": email, "password": senha, "returnSecureToken": True},
    )
    senha = None

    if status != 200 or not isinstance(dados, dict) or not dados.get("idToken"):
        print("Falha no login:", mensagem(dados))
        print("Confira a conta, a senha, a API Key e o método E-mail/senha.")
        return

    token = dados["idToken"]
    uid = dados.get("localId")
    # Salva as credenciais localmente para o start.py, somente após login confirmado.
    # Não envia o arquivo para o GitHub e restringe permissões no Linux/Termux.
    config_path = Path(__file__).resolve().parent / "cluster_config.json"
    try:
        config = {}
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                config = {}
        config["firebase_email"] = email
        config["firebase_password"] = senha_original
        config["firebase_uid"] = uid
        tmp_path = config_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            tmp_path.chmod(0o600)
        except OSError:
            pass
        tmp_path.replace(config_path)
        try:
            config_path.chmod(0o600)
        except OSError:
            pass
        print("Credenciais salvas localmente em cluster_config.json (não compartilhe esse arquivo).")
    except Exception as exc:
        print("AVISO: login correto, mas não consegui salvar as credenciais:", str(exc))
    print("Login realizado.")
    print("UID da conta:", uid)

    print("\n[2/4] Conferindo administrador...")
    url_admin = f"{DB_URL}/admins/{urllib.parse.quote(uid, safe='')}.json"
    status, admin = requisicao(url_admin, token=token)
    admin_ok = status == 200 and admin is True
    if admin_ok:
        print("OK: conta administradora confirmada.")
    elif status == 200:
        print("ATENÇÃO: admins/UID não está definido como true.")
        print("Valor atual:", repr(admin))
    else:
        print("Não foi possível ler admins/UID:", mensagem(admin))

    print("\n[3/4] Testando caminhos do banco...")
    caminhos = ["workers", "bots", "queue", "clusterServers"]
    banco_ok = True
    for caminho in caminhos:
        codigo, resultado = requisicao(f"{DB_URL}/{caminho}.json", token=token)
        if codigo == 200:
            estado = "vazio" if resultado is None else "acessível"
            print(f"OK — {caminho}: {estado}")
        else:
            banco_ok = False
            print(f"ERRO — {caminho}: HTTP {codigo} — {mensagem(resultado)}")

    print("\n[4/4] Verificação concluída.")
    if admin_ok and banco_ok:
        print("Autenticação, permissão de administrador e leituras testadas funcionaram.")
    else:
        print("Há permissões ou regras a revisar no Firebase Console.")
        print("Não altere regras para liberar acesso público.")
    print("Console: https://console.firebase.google.com/project/bothub-bca02")
    print("O script não salva senha nem token e não altera regras do banco.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nOperação cancelada.")
