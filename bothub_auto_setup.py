#!/usr/bin/env python3
# BotHub — diagnóstico automático do Firebase
# Não grava a senha e não altera permissões de administrador.
# Informe a Web API Key pública do Firebase quando solicitado.

import getpass
import json
import urllib.error
import urllib.parse
import urllib.request

DB_URL = "https://bothub-bca02-default-rtdb.firebaseio.com"
EMAIL_PADRAO = "daniblocks100@gmail.com"
AUTH_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"


def requisicao(url, metodo="GET", dados=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
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
    if isinstance(resultado, dict):
        return resultado.get("error", {}).get("message", str(resultado))
    return str(resultado)


def main():
    print("=" * 48)
    print(" BotHub — configuração e diagnóstico")
    print("=" * 48)

    api_key = getpass.getpass("Firebase Web API Key (entrada oculta): ").strip()
    if not api_key:
        print("API Key vazia.")
        return

    email = input(f"E-mail [{EMAIL_PADRAO}]: ").strip() or EMAIL_PADRAO
    senha = getpass.getpass("Senha Firebase (entrada oculta): ")
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
