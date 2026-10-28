# BotHub Cluster — execução distribuída pela LAN

Este agente é uma implementação inicial de cluster sem líder fixo. Cada nó tem banco local, replica o catálogo entre pares e tenta obter uma lease com maioria antes de executar um bot. A administração escuta apenas em loopback e exige token administrativo.

## Aviso honesto

É uma versão inicial para teste, não um consenso industrialmente auditado. Cada nó confiável recebe cópias dos tokens Discord dos bots. Use somente dispositivos sob seu controle, mantenha relógios sincronizados e não exponha a porta 47800 à internet. Em partições, a maioria estática deve ficar disponível; caso contrário, novas leases falham fechadas. Teste com bots descartáveis antes de qualquer uso real.

## Instalação em cada nó

1. Instale Python 3.9+ e as dependências do bot que seu projeto exige. Para medir RAM, instale `psutil` (`python -m pip install psutil`).
2. Baixe `bothub_cluster.py` do repositório em cada tablet/servidor.
3. Gere um segredo forte e um token administrativo, guarde-os fora do GitHub. Use os mesmos valores em todos os nós autorizados; dê a cada nó um `BOTHUB_NODE_ID` único.
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
