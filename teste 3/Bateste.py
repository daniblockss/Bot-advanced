
import subprocess
import json

def verificar_bateria():
    try:
        resultado = subprocess.run(
            ["termux-battery-status"],
            capture_output=True,
            text=True,
            timeout=10
        )

        if resultado.returncode != 0:
            print("Erro:", resultado.stderr)
            return

        bateria = json.loads(resultado.stdout)

        status = {
            "CHARGING": "Carregando ⚡",
            "DISCHARGING": "Descarregando 🔋",
            "FULL": "Carga completa ✅",
            "NOT_CHARGING": "Não carregando",
            "UNKNOWN": "Desconhecido"
        }

        fontes = {
            "PLUGGED_USB": "USB",
            "PLUGGED_AC": "Tomada",
            "PLUGGED_WIRELESS": "Sem fio",
            "UNPLUGGED": "Desconectado"
        }

        print("\n========== BATERIA ==========")
        print(f"Porcentagem: {bateria.get('percentage')}%")
        print(f"Estado: {status.get(bateria.get('status'), 'Desconhecido')}")
        print(f"Conexão: {fontes.get(bateria.get('plugged'), 'Desconhecida')}")
        print(f"Temperatura: {bateria.get('temperature')} °C")
        print(f"Saúde: {bateria.get('health')}")
        print(f"Voltagem: {bateria.get('voltage')} mV")
        print(f"Corrente: {bateria.get('current')} µA")
        print("=============================\n")

    except Exception as erro:
        print("Erro ao consultar bateria:", erro)


verificar_bateria()
