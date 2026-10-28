# BotHub Firebase — painel central e workers

Arquitetura correta: o painel HTML central controla os dispositivos pela Firebase Realtime Database. Cada tablet/servidor executa `bothub_firebase_worker.py`, envia heartbeat e busca apenas a fila atribuída a ele. Não é um painel local por dispositivo.

## Arquivos
- `bothub_firebase_panel.html`: painel central com login Firebase Auth, status dos workers, cadastro de bots, distribuição priorizando maior espaço livre, fila e pausa/ativação.
- `bothub_firebase_worker.py`: worker de cada dispositivo; cria ambiente Python e instala dependências ausentes automaticamente, autentica no Firebase e inicia/paralisa bots.
- `firebase_database.rules.json`: regras de segurança para importar no Realtime Database.
- `install_bothub.sh`: instalador anterior do protótipo cluster local; não use para este fluxo Firebase.

## Configuração inicial Firebase (uma vez)
1. No Firebase Console do projeto `bothub-bca02`, ative Authentication > Sign-in method > Email/Password.
2. Crie um usuário admin e um usuário Firebase separado para cada dispositivo (worker). Não use a conta pessoal principal para os workers.
3. Copie o UID do admin e de cada worker na página Authentication.
4. Em Realtime Database, importe `firebase_database.rules.json` como regras. O arquivo deixa todas as rotas privadas por padrão.
5. Em Realtime Database > Data, crie manualmente:
   - `admins/UID_DO_ADMIN` = `true`
   - `workerUids/ID_DO_DISPOSITIVO` = `UID_DO_USUARIO_WORKER`
   Repita `workerUids` para cada dispositivo. Esses mapeamentos devem ser criados no Console, porque as regras bloqueiam alterações neles via cliente.
6. Publique o painel em HTTPS (por exemplo, GitHub Pages) e entre com a conta admin. O Firebase web config identifica o projeto; a segurança real depende de Authentication e das regras, não de esconder a apiKey.
7. Em cada dispositivo, baixe o worker e execute-o. Na primeira execução, informe o ID do dispositivo, e-mail e senha do usuário Firebase daquele worker. O worker guarda a configuração em `~/.bothub/worker.json` com permissão restrita.

## Instalar/rodar worker (Termux ou Linux)
```sh
python3 bothub_firebase_worker.py
```
Na primeira execução ele cria `~/.bothub/venv`, instala `requests`, `psutil`, `discord.py`, `aiohttp` e `Pillow` e reinicia dentro do ambiente. Se o próprio Python/venv não estiver disponível, instale Python pelo gerenciador do sistema/Termux primeiro.

## Segurança e limitações desta primeira versão
- Tokens Discord ficam em `bots/{id}/token` e são copiados para `workerTasks/{deviceId}` do worker escolhido. As regras permitem ler tarefas somente ao admin e ao UID associado ao próprio worker.
- O painel é um cliente web; a redistribuição automática enquanto o painel está aberto depende da sessão administrativa conectada. Para reatribuição garantida mesmo quando o painel está fechado, implemente Cloud Functions/Cloud Run com privilégios de servidor.
- Firebase precisa de internet. Esta versão não implementa coordenação offline pela LAN; o cluster LAN separado não é integrado ao Firebase ainda.
- Configure os dispositivos apenas com contas de worker próprias. Não exponha senhas/tokens, e teste primeiro com bots de teste.
