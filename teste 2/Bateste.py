
import subprocess
import re

def bateria():
    try:
        resultado = subprocess.run(
            ["dumpsys", "battery"],
            capture_output=True,
            text=True,
            timeout=10
        )

        dados = resultado.stdout

        def pegar(nome):
            match = re.search(
                rf"{nome}:\s*(.+)",
                dados
            )
            return match.group(1).strip() if match else "Indisponível"

        nivel = pegar("level")
        temperatura = pegar("temperature")
        status = pegar("status")
        conectado = pegar("AC powered")

        estados = {
            "1": "Desconhecido",
            "2": "Carregando ⚡",
            "3": "Descarregando 🔋",
            "4": "Não está carregando",
            "5": "Carga completa ✅"
        }

        print("\n======= BATERIA =======")
        print(f"Porcentagem: {nivel}%")
        print(f"Estado: {estados.get(status, status)}")
        print(f"Conectado à tomada: {conectado}")

        if temperatura != "Indisponível":
            print(f"Temperatura: {int(temperatura) / 10} °C")

        print("=======================\n")

    except Exception as erro:
        print("Erro:", erro)

bateria()
