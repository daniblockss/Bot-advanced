# CERTO — BotHub funcional

Esta pasta reúne apenas os arquivos necessários para a versão atual do painel e do worker.

## Arquivos
- `index.html`: painel web BotHub, com gerenciamento de perfil e editor de arquivos.
- `bothub_firebase_worker.py`: worker, distribuição dos bots, comandos de arquivo e atualização de perfil via API do Discord.
- `add_cluster_server.py`: instalador do worker.
- `firebase_database.rules.json`: regras privadas do Firebase, incluindo permissões para comandos e resultados do worker.
- `main.py`: entrada do bot Discord, com o comando `!perfil` restrito aos criadores.

## Antes de usar
1. Publique o conteúdo de `firebase_database.rules.json` no Realtime Database do projeto Firebase. Faça backup das regras atuais e confirme que os caminhos `admins` e `workerUids` continuam corretos para os seus dispositivos.
2. Publique `index.html` em um host HTTPS que você controla e permita acesso somente a administradores autorizados.
3. Atualize o worker em cada dispositivo usando `add_cluster_server.py` ou substituindo o arquivo e reiniciando o worker. O worker antigo não conhece os comandos novos.
4. O worker executa o bot em uma pasta separada `bots/<id>/`. O gerenciador de arquivos limita operações a arquivos de texto permitidos nessa pasta; não permite terminal arbitrário nem acesso a tokens/configurações privadas.
5. No painel, escolha um bot atribuído a um worker online para alterar perfil ou gerenciar arquivos.

## Comando `!perfil`
- Anexe uma imagem PNG/JPEG e envie `!perfil` para mudar o avatar.
- `!perfil NovoNome` para mudar o nome.
- `!perfil NovoNome descrição do bot` para mudar nome e descrição.
- Para nomes com espaços, use aspas: `!perfil "Meu Bot" descrição aqui`.

O Discord pode aplicar limites de frequência e validação aos campos do perfil. A descrição é a descrição da aplicação, não o tópico de um servidor.

## Segurança
Nunca publique tokens em HTML, no GitHub ou em mensagens. O painel envia operações autenticadas ao worker e não mostra o token. Não conceda permissões administrativas do Firebase a contas não confiáveis.
