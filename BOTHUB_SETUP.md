# BotHub — configuração inicial

## Arquivos
- `bothub_node.py`: arquivo único que você baixa e executa em cada tablet/servidor. Cria o venv, instala dependências, salva configuração e inicia o agente.
- `bothub_api.py`: API central que recebe heartbeats, mede capacidade e envia DM no Discord em mudanças de estado.
- `requirements-bothub.txt`: dependências da API central.

## 1. Publique a API central
A API precisa rodar em um servidor sempre ligado e ser publicada por HTTPS. Em um servidor Linux com Python 3.11+:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-bothub.txt
```

Configure variáveis de ambiente antes de iniciar. Exemplo de nomes (use valores seus e não publique tokens):

- `BOTHUB_ADMIN_TOKEN`: token aleatório longo para proteger endpoints administrativos.
- `BOTHUB_WORKERS_JSON`: JSON com IDs e tokens individuais dos workers, por exemplo `{"tablet-01":"TOKEN_ALEATORIO_LONGO" }`.
- `BOTHUB_DISCORD_BOT_TOKEN`: token do bot Discord criado no Developer Portal.
- `BOTHUB_DISCORD_USER_ID`: seu ID numérico de usuário Discord.
- `BOTHUB_MIN_DISK_GB`: espaço mínimo livre (padrão 1 GB).
- `BOTHUB_MIN_RAM_MB`: RAM mínima livre (padrão 200 MB).

Inicie a API:
```bash
uvicorn bothub_api:app --host 127.0.0.1 --port 8000
```

Coloque um proxy HTTPS (por exemplo, Caddy ou Nginx) na frente dela. Não exponha a porta 8000 diretamente à internet sem HTTPS. A DM só funciona se o usuário permitir mensagens do bot/servidor; o bot precisa conseguir abrir uma DM.

## 2. Configure cada tablet/servidor
Baixe o arquivo único do GitHub e execute:

```bash
python3 bothub_node.py
```

URL raw do instalador:
https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/bothub_node.py

O instalador pergunta a URL HTTPS da API, o ID do dispositivo e o token individual correspondente ao ID configurado em `BOTHUB_WORKERS_JSON`. Ele cria `~/.bothub/venv`, instala os requisitos e inicia o heartbeat. Em Termux, para iniciar após reinicialização, instale Termux:Boot; o instalador configura o script automaticamente apenas se `~/.termux/boot` já existir.

## 3. Estado e alertas
- O worker envia heartbeat a cada 30 segundos.
- Um tablet é considerado offline depois de 100 segundos sem heartbeat.
- A capacidade depende do espaço em disco e da RAM livre.
- O endpoint administrativo `POST /api/admin/queue` atualiza a quantidade de bots aguardando. Envie `{"waiting_bots": 3}` com cabeçalho `Authorization: Bearer SEU_BOTHUB_ADMIN_TOKEN`.
- `GET /api/admin/status` mostra os tablets e a capacidade, protegido pelo mesmo token.
- Alertas de capacidade esgotada/restaurada são enviados por DM quando há bots na fila e a disponibilidade muda.

## Limitações importantes desta primeira versão
Esta versão configura e monitora os workers e implementa a lógica de alertas. Ela **ainda não distribui nem inicia automaticamente os processos dos bots Discord** e não integra a fila ao painel/site existente. A quantidade da fila precisa ser atualizada pelo backend/painel usando o endpoint administrativo. Não cole tokens no código nem em commits públicos.