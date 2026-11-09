
import os

BASE = "/sys/class/power_supply"

def ler(arquivo):
    try:
        with open(arquivo, "r") as f:
            return f.read().strip()
    except:
        return None

print("\n======= BATERIA DO DISPOSITIVO =======")

for dispositivo in os.listdir(BASE):
    caminho = os.path.join(BASE, dispositivo)

    tipo = ler(os.path.join(caminho, "type"))

    if tipo != "Battery":
        continue

    capacidade = ler(os.path.join(caminho, "capacity"))
    status = ler(os.path.join(caminho, "status"))
    temperatura = ler(os.path.join(caminho, "temp"))

    print(f"Bateria: {capacidade}%" if capacidade else "Bateria: indisponível")
    print(f"Estado: {status or 'Indisponível'}")

    if temperatura:
        try:
            valor = int(temperatura)
            if valor > 100:
                valor /= 10
            print(f"Temperatura: {valor} °C")
        except:
            print(f"Temperatura: {temperatura}")

print("======================================")
