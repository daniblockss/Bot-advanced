# BotHub — arquitetura de cluster distribuído (fase experimental)

## Objetivo

Todos os tablets/servidores participam da descoberta e da proposta de distribuição de tarefas. Não há um líder fixo. A administração e o cofre de tokens continuam privados: somente o administrador cria, altera, desativa e remove bots.

## Arquivos

- `bothub_api.py`: API privada legada de administração/catálogo e distribuição atual. Ela ainda é centralizada e NÃO deve ser confundida com o protótipo mesh.
- `bothub_node.py`: instalador/supervisor atual de bots.
- `bothub_admin.py`: painel CLI privado.
- `bothub_mesh.py`: protótipo novo de descoberta de pares na rede local e cálculo determinístico de um proprietário proposto por rendezvous hashing.
- `BOTHUB_DISTRIBUTED_ARCHITECTURE.md`: este plano.

## Como a arquitetura final deve ficar

1. **Plano de administração privado:** o CLI autenticado é o único caminho para cadastrar e modificar bots. Credenciais nunca entram no site público nem no repositório.
2. **Estado compartilhado:** cada nó mantém um diário local replicado de eventos identificados por UUID (bot criado/alterado, tarefa atribuída, lease renovada, execução reportada). Eventos precisam de versão, origem, idempotência e validação de assinatura.
3. **Descoberta LAN:** multicast UDP autenticado detecta nós na mesma rede local sem precisar da internet. Para redes diferentes, será necessário um transporte alcançável (por exemplo, WireGuard/Tailscale ou um relay público); multicast não atravessa roteadores por padrão.
4. **Agendamento:** os nós anunciam RAM/disco/carga e calculam propostas determinísticas usando rendezvous hashing. A proposta, sozinha, não autoriza executar.
5. **Leases e split-brain:** antes de iniciar um bot, o nó precisa obter uma concessão válida confirmada por quórum de nós elegíveis, com época/termo monotônico, expiração e renovação. Sem quórum, tarefas novas param; bots existentes seguem a política de segurança configurada. Essa camada ainda precisa ser implementada antes de produção.
6. **Recuperação:** um nó só pode reassumir a tarefa após expiração da lease anterior e confirmação de que o processo antigo não pode continuar servindo. Bots Discord não oferecem fencing token nativo, então partições de rede exigem política conservadora.
7. **Fila:** tarefas não alocadas ficam em estado pendente replicado; reatribuições são eventos idempotentes. Alertas ao administrador devem disparar em transições, não a cada heartbeat.
8. **Segurança:** HMAC de mensagens de descoberta protege contra pacotes forjados de quem não conhece o segredo do cluster, mas não substitui TLS, rotação de chaves, autenticação por nó e armazenamento protegido de tokens.

## Protótipo de descoberta LAN

O arquivo `bothub_mesh.py` usa apenas a biblioteca padrão para descoberta multicast na rede local. Cada nó precisa ter Python 3.9+ e a mesma variável de ambiente `BOTHUB_MESH_SECRET`, com um segredo aleatório de pelo menos 32 caracteres. Nunca commite o segredo.

Linux/Termux (shell):

```bash
export BOTHUB_MESH_SECRET='COLOQUE_AQUI_UM_SEGREDO_ALEATORIO_LONGO'
python3 bothub_mesh.py --node-id tablet-01
```

Em cada dispositivo use um ID diferente e o mesmo segredo. Permita UDP multicast na porta 47777 dentro da LAN. Para ver uma proposta determinística de proprietário para uma tarefa:

```bash
python3 bothub_mesh.py --node-id tablet-01 --task-id bot-exemplo
```

A saída lista os pares vistos e a proposta de colocação. O programa é somente diagnóstico/protótipo: **não inicia, para nem move bots**. A descoberta multicast depende do roteador e não funciona automaticamente pela internet, entre VLANs ou em redes de convidados isoladas.

## Migração segura por fases

- Fase 1: validar descoberta LAN e identidade única de cada nó.
- Fase 2: implementar diário replicado e protocolo de consenso/leases com quórum; testar partições e reinícios.
- Fase 3: integrar o agendador com o supervisor e fazer o processo do bot exigir lease válida.
- Fase 4: tornar a administração privada a origem autenticada dos eventos de configuração, sem transformar a API em coordenador obrigatório.
- Fase 5: testes com bots de teste, quedas de energia, reinícios, perda de internet, nós isolados e recuperação de capacidade.

## Estado atual e limitações

Esta mudança inicia a base P2P e documenta a arquitetura; **não transforma ainda o sistema legado em cluster autônomo de produção**. A API e o supervisor existentes ainda usam atribuições centralizadas. O protótipo não garante consenso, persistência replicada, prevenção absoluta de execução duplicada ou comunicação entre LANs. Não coloque tokens reais no repositório e não use o protótipo sozinho para hospedar bots de clientes.
