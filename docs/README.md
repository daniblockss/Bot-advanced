# BotHub Portal de Solicitações

Portal estático inicial em `portal/index.html`, integrado ao Firebase Authentication (Google e e-mail/senha) e Cloud Firestore para registrar pedidos de criação de bots.

## O que já existe nesta versão
- Landing page responsiva e área do cliente.
- Login/cadastro por Google e e-mail/senha, recuperação de senha.
- Formulário de solicitação com tipo, orçamento, recursos, ID de servidor opcional e descrição.
- Histórico das solicitações do próprio cliente.
- O formulário **não coleta token de bot** e não recebe senha do Discord.
- Login com Discord está explicitamente pendente de um backend OAuth seguro.

## Configuração do Firebase
1. Crie um projeto em https://console.firebase.google.com/.
2. Em Authentication > Sign-in method, habilite Google e Email/Password.
3. Cadastre os domínios autorizados em Authentication > Settings.
4. Crie um banco Cloud Firestore.
5. Copie a configuração do app Web em Firebase project settings e substitua os valores de exemplo de `firebaseConfig` em `index.html`.
6. Publique em HTTPS (Firebase Hosting, GitHub Pages ou outro host estático).
7. Aplique as regras abaixo antes de abrir o portal ao público.

## Regras iniciais sugeridas para Firestore

Estas regras limitam a leitura às próprias solicitações e impedem o cliente de definir campos privilegiados. Ajuste e teste no Emulator Suite antes de produção.

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /botRequests/{requestId} {
      allow create: if request.auth != null
        && request.resource.data.uid == request.auth.uid
        && request.resource.data.keys().hasOnly([
          'uid','email','displayName','botName','botType','budget',
          'features','guildId','description','status','createdAt'
        ])
        && request.resource.data.status == 'recebido'
        && request.resource.data.botName is string
        && request.resource.data.botName.size() > 0
        && request.resource.data.botName.size() <= 60
        && request.resource.data.description is string
        && request.resource.data.description.size() > 0
        && request.resource.data.description.size() <= 3000;
      allow read: if request.auth != null
        && resource.data.uid == request.auth.uid;
      allow update, delete: if false;
    }
  }
}
```

A consulta do histórico usa `uid == current user` e `createdAt desc`; o Firestore poderá solicitar a criação de um índice composto. Siga o link gerado pelo console para criá-lo.

## Pagamentos e operação
- Não implemente pagamento automático nem prometa preço/prazo antes de definir operação, suporte e política de reembolso.
- Nesta fase, a solicitação fica registrada; confirme valor e escopo com o cliente por um canal oficial.
- Para Pix, prefira QR/cobrança gerada por provedor e confirme o pagamento no backend por webhook. Não confie em comprovantes ou em um botão de “paguei”.
- Não peça token de bot por formulário comum, URL, logs, chat público ou Firestore. Para produção, crie um backend autenticado que armazene credenciais em Secret Manager/armazenamento criptografado com acesso restrito, nunca retornando o segredo ao navegador. Ofereça rotação e remoção.
- O login com Discord exige OAuth implementado no backend e emissão de Firebase Custom Token. O client secret nunca deve aparecer neste arquivo.
- Antes de produção: adicionar Termos, Política de Privacidade, política de retenção/exclusão, proteção contra spam/rate limits, logs de auditoria e contato oficial de suporte.

## Limitações conhecidas
- Este portal ainda é uma primeira versão: não cria nem hospeda bots automaticamente, não cobra Pix e não recebe tokens.
- O Firebase web config é uma configuração pública do cliente, mas o acesso aos dados depende das regras de segurança. Nunca coloque service-account JSON, chave privada ou segredo OAuth no frontend.
