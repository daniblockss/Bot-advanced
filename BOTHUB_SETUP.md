# BotHub privado — API central + workers

Este sistema é destinado ao administrador do serviço. Não existe painel público para clientes. O administrador cadastra os bots e seus tokens pela API protegida; os workers recebem apenas os bots que lhes foram atribuídos.

## Arquivos
- `bothub_api.py`: API central privada, banco SQLite, autenticação, cadastro/ativação/exclusão de bots, alocação por capacidade e fila.
- `bothub_node.py`: instalador de arquivo único para cada tablet/servidor; instala dependências, envia heartbeat, consulta tarefas e inicia/reinicia bots.
- `bothub_admin.py`: painel CLI privado do administrador; lista servidores/bots, cadastra bots após validar token no Discord, desativa, reativa e exclui bots.
- `requirements-bothub.txt`: dependências da API.

## Segurança obrigatória
- Nunca salve tokens reais no repositório GitHub.
- Use HTTPS público e tokens longos e diferentes para administrador e cada worker.
- O banco SQLite contém tokens dos bots em texto claro; mantenha o arquivo e o volume do servidor protegidos e com backup seguro.
- A API deve ser acessível apenas por HTTPS na internet. O exemplo de servidor abaixo escuta em localhost para ficar atrás de um proxy TLS.
- Defina `BOTHUB_WORKERS_JSON` com todos os IDs de worker e tokens correspondentes antes de iniciar. O ID precisa ser idêntico ao digitado no instalador.
- Defina `BOTHUB_ADMIN_TOKEN` com um segredo longo aleatório. Não o coloque no navegador nem no código do repositório.
- Para DM, configure `BOTHUB_DISCORD_BOT_TOKEN` e `BOTHUB_DISCORD_USER_ID`. O bot de alerta precisa ter permissão para abrir DM com sua conta.

## Instalar API central (Linux)
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-bothub.txt
export BOTHUB_ADMIN_TOKEN='COLOQUE_UM_SEGREDO_LONGO'
export BOTHUB_WORKERS_JSON='{"tablet-01":"TOKEN_WORKER_LONGO_ALEATORIO"}'
export BOTHUB_DISCORD_BOT_TOKEN='TOKEN_DO_BOT_DE_ALERTA'
export BOTHUB_DISCORD_USER_ID='SEU_ID_DISCORD'
uvicorn bothub_api:app --host 127.0.0.1 --port 8000
```
Configure Caddy/Nginx ou o proxy da hospedagem para fornecer HTTPS e encaminhar para localhost:8000. Use armazenamento persistente para `bothub.sqlite3`.

## Painel privado do administrador (recomendado)
Baixe e execute no seu computador ou celular de administrador:

```bash
python3 -c "import urllib.request; urllib.request.urlretrieve('https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/bothub_admin.py','bothub_admin.py')"
python3 bothub_admin.py
```

Na primeira execução, informe a URL da API e o token administrativo. Ele fica salvo localmente em `~/.bothub-admin/config.json` com permissão restrita quando o sistema operacional permite. Não compartilhe essa pasta nem o token. O painel permite cadastrar bots, consultar capacidade/fila e ativar/desativar/excluir bots.

## Cadastrar bots (somente administrador)
Envie `POST /api/admin/bots` com cabeçalho `Authorization: Bearer SEU_BOTHUB_ADMIN_TOKEN` e JSON:
```json
{"bot_name":"Bot do cliente","discord_token":"TOKEN_DO_BOT","config":{}}
```
A resposta inclui `bot_id`. O token não é devolvido nas rotas administrativas de listagem. A API não valida automaticamente se o token do bot é válido; valide-o antes do cadastro. Nunca passe tokens de bots para clientes.

Listar bots: `GET /api/admin/bots`
Status da capacidade/fila: `GET /api/admin/status`
Desativar bot: `PATCH /api/admin/bots/ID` com `{"enabled":false}`
Reativar: `PATCH /api/admin/bots/ID` com `{"enabled":true}`
Excluir: `DELETE /api/admin/bots/ID`

Todos esses endpoints exigem o token administrativo. A documentação interativa da API em `/docs` não ignora autenticação.

## Configurar cada tablet/servidor
Baixe o instalador:
```bash
python3 -c "import urllib.request; urllib.request.urlretrieve('https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/bothub_node.py','bothub_node.py')"
python3 bothub_node.py
```
Informe a URL HTTPS da API, o ID de worker cadastrado em `BOTHUB_WORKERS_JSON` e seu token. O worker instala `requests` e `psutil`, reporta recursos e consulta a API. Bots atribuídos são baixados de `BOTHUB_BOT_SOURCE_URL` (padrão: main8.py), recebem configuração local e são iniciados usando o ambiente Python compartilhado. Logs ficam em `~/.bothub/bots/ID/bot.log`.

Para Android/Termux, instale Termux:Boot e Termux:API, abra o Termux:Boot pelo menos uma vez e execute o instalador de novo depois que `~/.termux/boot` existir. Android pode encerrar processos em segundo plano; configure a bateria sem restrições. O wake lock ajuda a manter o dispositivo acordado, mas não garante uptime se o sistema encerrar o app.

## Fila e capacidade
A API atribui até `BOTHUB_MAX_BOTS_PER_WORKER` bots por worker elegível (padrão 3). Um worker é elegível se estiver online e tiver pelo menos `BOTHUB_MIN_DISK_GB` GB livres e `BOTHUB_MIN_RAM_MB` MB livres. Bots sem slot ficam aguardando e são atribuídos automaticamente quando houver espaço. Valores padrão: 1 GB e 200 MB. Ajuste de acordo com o peso real de seus bots.

Alertas por DM ocorrem em transições de capacidade/fila, não a cada heartbeat. Antes de uso real, teste com um bot de teste e confirme logs, início/parada, reassociação de worker, persistência do banco e envio de DM. O supervisor reinicia bots que saem inesperadamente ao sincronizar tarefas.

## Limitações conhecidas
- Esta é uma primeira integração funcional, ainda precisa ser testada no seu ambiente antes de produção.
- A atribuição considera limite de bots, RAM e disco, mas não prevê consumo futuro exato por bot.
- Se um worker morrer abruptamente, o bot pode demorar até a próxima sincronização para ser reatribuído.
- A configuração de inicialização automática é best-effort; Android/Termux não garante execução contínua.
- Proteja o endpoint e o banco: a API entrega o token de cada bot apenas ao worker autorizado que o executa.


## Cluster distribuído experimental (novo)

O arquivo `bothub_mesh.py` adiciona descoberta de pares pela rede local sem líder fixo. Leia primeiro `BOTHUB_DISTRIBUTED_ARCHITECTURE.md`.

Teste a descoberta em cada dispositivo (Python 3.9+; não exige dependências extras):

```bash
export BOTHUB_MESH_SECRET='USE_UM_SEGREDO_ALEATORIO_LONGO_COM_32_CARACTERES_OU_MAIS'
python3 bothub_mesh.py --node-id tablet-01
```

Use um ID diferente por dispositivo e o mesmo segredo somente nos nós confiáveis. A porta UDP multicast 47777 precisa ser permitida na rede local. Para consultar uma proposta de colocação determinística, acrescente `--task-id bot-exemplo`.

**Importante:** esta é a primeira camada experimental de descoberta e proposta de distribuição. Ela não inicia nem move bots, não é consenso e não impede sozinha duplicação de processos durante partições de rede. A API e o supervisor antigos ainda fazem atribuição centralizada. Não use `bothub_mesh.py` sozinho em produção; o protocolo de diário replicado e leases confirmadas por quórum ainda precisa ser implementado e testado.