# TESTE 2 — instalação isolada

Esta pasta é uma cópia de teste. Os arquivos desta instalação usam o diretório de teste 2 como raiz local e não devem atualizar arquivos da raiz do repositório nem arquivos de outra instalação.

## Arquivos
- main.py: bot; configurações, banco SQLite e arquivos de memória ficam ao lado deste arquivo.
- add_cluster_server.py: instalador/atualizador, usando somente os arquivos desta pasta no GitHub.
- bothub_firebase_worker.py: controlador do cluster; os bots que ele executa ficam em teste 2/bots/.
- docs/bothub.html: painel com namespace Firebase separado teste2/.
- docs/cluster-cooperativo.md: documentação desta cópia.
- .github/workflows/validate-cluster.yml: cópia de configuração de validação; o GitHub só executa workflows localizados na pasta .github/workflows da raiz, então este arquivo dentro de teste 2 não roda automaticamente.

## Isolamento
- Os downloads de atualização usam a branch teste-2 e o caminho teste 2/.
- O worker salva o ambiente virtual, logs, configuração, estado e bots dentro da pasta onde está instalado.
- O painel e o worker usam o prefixo teste2/ no Firebase para não misturar a fila de bots desta cópia com a raiz do painel antigo.
- A detecção de processos duplicados só considera bots dentro da pasta bots/ desta instalação. Ela não encerra bots de outras pastas.
- A branch main e os arquivos na raiz do repositório não são modificados por estes arquivos.

## Iniciar
Baixe/copie a pasta inteira para o servidor e execute o instalador a partir dela:
```bash
cd "teste 2"
python3 add_cluster_server.py
```
O instalador usa a própria pasta do script como diretório de trabalho, mesmo se for iniciado por outro caminho.

Atenção: o namespace Firebase teste2/ é separado. Se as regras do Realtime Database exigirem cadastro de administrador, configure a autorização para esse namespace de teste antes de usar o painel.
