# BotHub Cluster — execução distribuída pela LAN

Este agente é uma implementação inicial de cluster sem líder fixo. Cada nó tem banco local, replica o catálogo entre pares e tenta obter uma lease com maioria antes de executar um bot. A administração escuta apenas em loopback e exige token administrativo.

## Aviso honesto

É uma versão inicial para teste, não um consenso industrialmente auditado. Cada nó confiável recebe cópias dos tokens Discord dos bots. Use somente dispositivos sob seu controle, mantenha relógios sincronizados e não exponha a porta 47800 à internet. Em partições, a maioria estática deve ficar disponível; caso contrário, novas leases falham fechadas. Teste com bots descartáveis antes de qualquer uso real.

## Instalação automática e painel HTML

O instalador tenta detectar o ambiente, instalar Python quando possível, criar um ambiente virtual, instalar as dependências que faltarem, baixar o agente e o painel, e pedir os dados de configuração. Não precisa editar o código manualmente.

Baixe e execute o instalador (execute o arquivo baixado, em vez de usar `curl | bash`, para que os prompts interativos funcionem):

```bash
mkdir -p ~/bothub-setup && cd ~/bothub-setup
curl -fLsS https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/install_bothub.sh -o install_bothub.sh
bash install_bothub.sh
```

O instalador inicia o nó depois de configurar. No próprio dispositivo, abra `http://127.0.0.1:47800/admin/ui` no navegador e informe o token administrativo que ele exibiu. O painel permite ver nós/recursos, cadastrar bots e desativá-los. A página HTML fica em `bothub_panel.html`.

O painel administrativo é limitado a loopback por segurança: não o abra diretamente para a rede nem encaminhe a porta 47800 à internet. O segredo e o token ficam no arquivo `bothub.env` com permissões restritas; não faça commit nem compartilhe esse arquivo. Para adicionar outros dispositivos, execute o instalador em cada um e configure o mesmo segredo/token, IDs únicos e listas de pares simétricas. O segredo precisa ser compartilhado apenas com dispositivos sob seu controle.

## Instalação em cada nó

**Não rode este agente junto com o antigo `bothub_node.py` para os mesmos bots**, pois isso pode iniciar processos duplicados. Primeiro teste com bots descartáveis e pare o worker antigo para os bots que migrar.

1. Instale Python 3.9+ e as dependências do bot que seu projeto exige. Para medir RAM, instale `psutil` (`python -m pip install psutil`).
2. Baixe `bothub_cluster.py` do repositório em cada tablet/servidor.
3. Gere um segredo forte e um token administrativo, guarde-os fora do GitHub. Gere valores no terminal com `python3 -c 'import secrets; print(secrets.token_hex(32))'` (segredo do cluster) e `python3 -c 'import secrets; print(secrets.token_hex(24))'` (token admin). Copie-os manualmente para os nós autorizados; não os envie para o chat nem faça commit. Use os mesmos valores em todos os nós autorizados; dê a cada nó um `BOTHUB_NODE_ID` único.
4. Configure a lista estática de pares, com os endereços LAN de todos os outros nós. Exemplo para dois nós:
   - Nó A: `BOTHUB_CLUSTER_PEERS_JSON='{"tablet-b":"http://192.168.1.22:47800}'`
   - Nó B: `BOTHUB_CLUSTER_PEERS_JSON='{"tablet-a":"http://192.168.1.21:47800}'`
5. Execute `python3 bothub_cluster.py` para manter o nó ativo. Para abrir o CLI administrativo local em outro terminal, execute `python3 bothub_cluster.py admin`. Os endpoints administrativos aceitam apenas conexões locais.
6. Na primeira vez, use `status`; depois `add` e informe o token do bot no prompt oculto. Use `disable ID` para desativar um bot. A replicação do catálogo ocorre automaticamente.

Exemplo de variáveis (troque todos os valores):
```bash
export BOTHUB_NODE_ID='tablet-a'
export BOTHUB_CLUSTER_SECRET='PREENCHA_COM_SEGREDO_ALEATORIO_FORTE'
export BOTHUB_ADMIN_TOKEN='PREENCHA_COM_TOKEN_ADMINISTRATIVO_FORTE'
export BOTHUB_CLUSTER_PEERS_JSON='{"tablet-b":"http://192.168.1.22:47800"}'
python3 bothub_cluster.py
```

Para administrar, abra outro terminal com as mesmas variáveis e execute `python3 bothub_cluster.py admin`.

## Limitações operacionais

- Todos os nós devem ter a mesma lista de membros e seus IDs/endpoints devem estar corretos. Use endereços IP fixos/reservas DHCP na LAN.
- Multicast não é necessário nesta versão: os pares são configurados estaticamente para tornar a conexão previsível.
- Para funcionar entre redes, será necessário VPN privada ou endpoints seguros alcançáveis; não exponha HTTP sem TLS diretamente à internet.
- A implementação usa leases simples com quórum estático e relógio do sistema. Ela não substitui Raft/etcd/Consul nem foi auditada para partições adversariais; use somente em laboratório até os testes de falha serem concluídos.
- O código de bots precisa ler `config.json` no diretório de trabalho. Verifique isso no `main8.py` antes de confiar que um bot vai iniciar corretamente.
- Desativar um bot precisa se propagar; confirme a replicação e o encerramento no nó executor nos testes.


## Comandos rápidos de instalação

Em cada Linux/Termux, crie uma pasta, baixe o agente e instale as dependências:

```bash
mkdir -p ~/bothub-cluster && cd ~/bothub-cluster
curl -fsSL https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/bothub_cluster.py -o bothub_cluster.py
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install psutil discord.py aiohttp Pillow
```

No Termux, se `venv` não funcionar, use o Python do Termux e instale os pacotes com `python -m pip install psutil discord.py aiohttp Pillow`.

Antes de iniciar, descubra o IP LAN de cada dispositivo. No Linux/Ubuntu: `hostname -I`. No Termux: `ip -4 addr show wlan0`. Use IPs fixos/reservas DHCP e confirme que ambos conseguem se alcançar na porta TCP 47800.

**Segurança:** o protocolo atual autentica as mensagens, mas não cifra o tráfego. Use somente numa LAN privada confiável para teste; não use Wi-Fi público e não exponha a porta 47800 à internet. Para uso fora da LAN, primeiro configure VPN privada e transporte cifrado.
