# BotHub Firebase — painel central e workers

Arquitetura correta: o painel HTML central controla os dispositivos pela Firebase Realtime Database. Cada tablet/servidor executa `bothub_firebase_worker.py`, envia heartbeat e busca apenas a fila atribuída a ele. Não é um painel local por dispositivo.

## Arquivos
- `bothub_firebase_panel.html`: painel central com login Firebase Auth, status dos workers, cadastro de bots, distribuição priorizando maior espaço livre, fila e pausa/ativação.
- `bothub_firebase_worker.py`: worker de cada dispositivo; cria ambiente Python e instala dependências ausentes automaticamente, autentica no Firebase e inicia/paralisa bots.
- `firebase_database.rules.json`: regras de segurança para importar no Realtime Database.
- `install_bothub_firebase.sh`: instalador automático para este fluxo Firebase.\n- Painel publicado em `docs/bothub.html` quando GitHub Pages estiver configurado para a pasta `/docs`.

## Configuração inicial Firebase (uma vez)
1. No Firebase Console do projeto `bothub-bca02`, ative Authentication > Sign-in method > Email/Password.
2. Crie um usuário admin e um usuário Firebase separado para cada dispositivo (worker). Não use a conta pessoal principal para os workers.
3. Copie o UID do admin e de cada worker na página Authentication.
4. Em Realtime Database, importe `firebase_database.rules.json` como regras. As rotas do painel continuam privadas; `clusterServers` permite que usuários autenticados descubram nós e cada conta só pode atualizar os campos do próprio nó.
5. Em Realtime Database > Data, crie manualmente:
   - `admins/UID_DO_ADMIN` = `true`
   - `workerUids/ID_DO_DISPOSITIVO` = `UID_DO_USUARIO_WORKER`
   Repita `workerUids` para cada dispositivo. Esses mapeamentos devem ser criados no Console, porque as regras bloqueiam alterações neles via cliente.
6. Publique o painel em HTTPS (por exemplo, GitHub Pages) e entre com a conta admin. O Firebase web config identifica o projeto; a segurança real depende de Authentication e das regras, não de esconder a apiKey.
7. Em cada dispositivo, baixe o worker e execute-o. Na primeira execução, informe o ID do dispositivo, e-mail e senha do usuário Firebase daquele worker. O worker guarda a configuração em `~/.bothub/worker.json` com permissão restrita.

## Instalar/rodar worker automaticamente (Termux ou Linux)

No dispositivo, rode o instalador, que baixa o worker, prepara o ambiente virtual e instala as dependências ausentes:

```sh
mkdir -p ~/bothub-setup && cd ~/bothub-setup
curl -fLsS https://raw.githubusercontent.com/daniblockss/Bot-advanced/main/install_bothub_firebase.sh -o install_bothub_firebase.sh
bash install_bothub_firebase.sh
```

Na primeira execução, informe o ID único do dispositivo e as credenciais do usuário Firebase próprio daquele worker. O worker fica em `~/.bothub`; dependências Python são instaladas automaticamente. O script tenta instalar Python/curl pelo gerenciador quando possível, mas não consegue conceder permissões de sistema que o usuário não tenha.

## Segurança e limitações desta primeira versão
- Tokens Discord ficam em `bots/{id}/token` e são copiados para `workerTasks/{deviceId}` do worker escolhido. As regras permitem ler tarefas somente ao admin e ao UID associado ao próprio worker.
- O painel é um cliente web; a redistribuição automática enquanto o painel está aberto depende da sessão administrativa conectada. Para reatribuição garantida mesmo quando o painel está fechado, implemente Cloud Functions/Cloud Run com privilégios de servidor.
- O diretório P2P usa Firebase para descobrir membros, mas a comunicação entre nós ainda exige conectividade direta na porta configurada (47800 por padrão). Para acesso pela internet, configure encaminhamento de porta/firewall ou use uma hospedagem com porta pública. Registros antigos permanecem na lista de membros e devem ser removidos do nó `clusterServers` pelo Console quando um servidor for definitivamente desativado; manter membros antigos faz o cluster falhar fechado em vez de reduzir o quórum.
- Configure os dispositivos apenas com contas de worker próprias. Não exponha senhas/tokens, e teste primeiro com bots de teste.
