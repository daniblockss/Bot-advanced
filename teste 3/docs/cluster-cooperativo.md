# Arquitetura de cluster cooperativo BotHub

## Objetivo
Executar bots Discord em vários workers, transferir a execução automaticamente quando um worker falha e preservar memórias no Firebase Realtime Database.

## Dados no Realtime Database
- `workers/{deviceId}`: heartbeat e métricas.
- `bots/{botId}`: cadastro e configuração do bot.
- `workerTasks/{deviceId}/{botId}`: fila de bots atribuídos pelo painel.
- `botLeases/{botId}`: proprietário, expiração, heartbeat e fencing token. A aquisição usa ETag + If-Match para comparação e troca atômica.
- `botState/{botId}/files/{filenameKey}`: conteúdo base64, SHA-256, timestamp, writer e fencing token.
- `workerCommands/{deviceId}` e `workerResults/{deviceId}`: comandos e respostas do painel.
- `botHubClusterUpdates/current`: pedido de atualização do controlador.

## Ciclo de trabalho
1. O worker publica seu heartbeat e consulta a fila.
2. Antes de iniciar um bot, adquire ou renova o lease com compare-and-swap no Firebase.
3. Apenas o proprietário do lease com o fencing token atual pode iniciar o bot e gravar memórias.
4. Antes do primeiro start, restaura o estado do Firebase; depois envia alterações locais com hash para evitar gravações desnecessárias.
5. Quando perde a atribuição, encerra o bot, libera o lease se ainda for proprietário e remove a pasta local daquela cópia.
6. Após reiniciar, consulta a fila e o lease; nunca presume que ainda é proprietário só porque a pasta existe.
7. Se o Firebase ficar indisponível por vários ciclos, o worker encerra os bots para evitar que continue executando indefinidamente sem conseguir renovar o lease.

## Dados de memória sincronizados
Personalidade do bot, histórico/estado de imagens, bancos SQLite de memória e lembretes, além de arquivos de memória e regras em texto. Bases SQLite são copiadas por meio da API de backup para gerar snapshots consistentes. `config.json`, tokens, arquivos de ambiente, credenciais e logs não são enviados como arquivos de memória.

## Atualização do controlador
O worker já possui um fluxo de atualização separado: baixa os arquivos permitidos do GitHub, valida a sintaxe, grava um pacote pendente e chama um processo auxiliar separado para parar o controlador antigo, substituir os arquivos atomicamente e iniciar a nova versão. O processo que está sendo substituído não tenta apagar a si próprio.

## Limites operacionais
- O painel continua sendo a camada de atribuição; leases são a camada de exclusão mútua.
- Heartbeat atrasado não prova que uma máquina morreu. A expiração do lease e o fencing evitam que uma instância antiga reivindique a propriedade indefinidamente.
- O Realtime Database não é armazenamento de blobs otimizado. O worker limita cada arquivo sincronizado a 8 MiB; arquivos maiores devem ir para Firebase Storage.
- Regras do RTDB devem exigir autenticação e limitar leitura/gravação por worker. Não coloque credenciais administrativas no HTML público.