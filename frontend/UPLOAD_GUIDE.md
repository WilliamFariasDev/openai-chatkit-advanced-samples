# Upload de Arquivos - Frontend ChatKit

## ✅ Implementação Completa

O sistema de upload de arquivos foi totalmente configurado no frontend usando o ChatKit React.

## Configuração Aplicada

### 1. **ChatKitPanel.tsx**

Adicionada configuração de attachments:

```typescript
composer: {
  placeholder: PLACEHOLDER_INPUT,
  attachments: {
    enabled: true,                    // Habilita upload de arquivos
    uploadStrategy: "direct",         // Upload direto em uma etapa
    accept: [                         // Tipos de arquivo aceitos
      "image/*",
      "application/pdf",
      ".doc",
      ".docx",
      ".txt",
      ".csv",
      ".json",
    ],
    maxFileSizeBytes: 10 * 1024 * 1024, // 10MB máximo
    maxFiles: 5,                        // Máximo 5 arquivos por vez
  },
},
api: {
  url: CHATKIT_API_URL,
  domainKey: CHATKIT_API_DOMAIN_KEY,
  fetch: customFetch,                   // Adiciona token Supabase
  attachments: {
    create: {
      url: UPLOAD_API_URL,              // Endpoint de upload
    },
  },
},
```

### 2. **config.ts**

Adicionada constante para URL de upload:

```typescript
export const UPLOAD_API_URL =
  import.meta.env.VITE_UPLOAD_API_URL ?? "/api/uploads/direct";
```

### 3. **Variáveis de Ambiente**

Atualizado `.env` e `.env.example`:

```env
VITE_CHATKIT_API_URL=http://localhost:8000/chatkit
VITE_UPLOAD_API_URL=http://localhost:8000/api/uploads/direct
VITE_SUPABASE_TOKEN=your-jwt-token-here
```

## Como Funciona

### Fluxo de Upload

1. **Usuário clica no ícone de anexo** (📎) no composer do chat
2. **Seleciona arquivo(s)** do sistema
3. **ChatKit valida** tipo e tamanho
4. **Upload automático** para `POST /api/uploads/direct`
   - Header `Authorization: Bearer {SUPABASE_TOKEN}` é adicionado automaticamente
   - Form-data com `file` e `thread_id`
5. **Backend processa**:
   - Cria registro em `uploads`
   - Faz upload para OpenAI Files API (expira em 7 dias)
   - Associa arquivo à thread em `thread_files`
   - Retorna metadata do attachment
6. **Arquivo aparece na mensagem** como anexo
7. **Ao enviar mensagem**, o Agents SDK recebe o `openai_file_id` automaticamente

### Tipos de Arquivo Suportados

#### Imagens 🖼️
- Qualquer formato (`image/*`)
- JPG, PNG, GIF, WebP, etc.
- Renderizadas inline no chat

#### Documentos 📄
- **PDF** - Totalmente suportado pelo Agents SDK
- **DOC/DOCX** - Word documents
- **TXT** - Arquivos de texto
- **CSV** - Dados tabulares
- **JSON** - Dados estruturados

### Limites

- **Tamanho máximo por arquivo**: 10MB
- **Número máximo de arquivos**: 5 por mensagem
- **Expiração**: Arquivos expiram em 7 dias na OpenAI

## Interface do Usuário

### Botão de Anexo

O ChatKit adiciona automaticamente um botão de clipe de papel (📎) no composer quando `attachments.enabled: true`.

### Preview de Arquivos

Antes de enviar, os usuários veem:
- Nome do arquivo
- Tamanho
- Tipo/ícone
- Botão para remover

### Arquivos Enviados

Após enviar a mensagem:
- Imagens são renderizadas como thumbnails
- Documentos aparecem como cards com ícone e nome
- Click para fazer download (se implementado)

## Personalização

### Mudar Tipos Aceitos

```typescript
accept: [
  "image/*",              // Todas as imagens
  "application/pdf",      // PDFs
  "text/*",              // Qualquer texto
  ".xlsx",               // Excel específico
],
```

### Ajustar Limites

```typescript
maxFileSizeBytes: 20 * 1024 * 1024,  // 20MB
maxFiles: 10,                         // 10 arquivos
```

### Two-Phase Upload

Se preferir two-phase upload ao invés de direct:

```typescript
attachments: {
  enabled: true,
  uploadStrategy: "two-phase",  // Muda para two-phase
  // ...resto da config
}
```

**Diferença:**
- **Direct**: Upload acontece em uma requisição
- **Two-phase**: 
  1. Fase 1: ChatKit cria attachment (GET URL)
  2. Fase 2: Cliente faz upload para a URL retornada

## Autenticação

O `customFetch` adiciona automaticamente o token Supabase:

```typescript
const customFetch = useMemo(() => {
  return async (url: string, options?: RequestInit) => {
    const headers = new Headers(options?.headers);
    if (SUPABASE_TOKEN) {
      headers.set("Authorization", `Bearer ${SUPABASE_TOKEN}`);
    }
    return fetch(url, { ...options, headers });
  };
}, []);
```

Isso garante que todos os uploads sejam autenticados e associados ao usuário correto.

## Testando

### 1. Inicie o Backend

```bash
cd backend
uvicorn app.main:app --reload
```

### 2. Inicie o Frontend

```bash
cd frontend
npm run dev
```

### 3. Teste o Upload

1. Abra http://localhost:5173
2. Clique no ícone de clipe (📎) no composer
3. Selecione uma imagem ou PDF
4. Veja o preview do arquivo
5. Digite uma mensagem (ex: "Analise este documento")
6. Envie
7. O assistente deve processar o arquivo!

## Debugging

### Verificar Upload

Abra DevTools → Network e procure por:
- `POST /api/uploads/direct` - deve retornar 200
- Response deve conter `openai_file_id`

### Verificar Attachment no ChatKit

No console:
```typescript
onError: ({ error }) => {
  console.error("ChatKit error", error);
}
```

### Verificar Backend

Logs do backend devem mostrar:
```
INFO: Created attachment att_xyz123 for user 1
INFO: Uploaded file to OpenAI: file-abc789
INFO: Attached file file-abc789 to thread thread_456
```

## Recursos Adicionais

### Mostrar Arquivos da Thread

Você pode criar um componente para listar arquivos:

```typescript
const [threadFiles, setThreadFiles] = useState([]);

useEffect(() => {
  fetch(`/api/threads/${threadId}/files`, {
    headers: { Authorization: `Bearer ${SUPABASE_TOKEN}` }
  })
    .then(res => res.json())
    .then(data => setThreadFiles(data.files));
}, [threadId]);
```

### Remover Arquivo

```typescript
const removeFile = async (fileId: string) => {
  await fetch(`/api/threads/${threadId}/files/${fileId}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${SUPABASE_TOKEN}` }
  });
};
```

## Segurança

✅ **Row Level Security**: Apenas o dono pode ver/modificar seus arquivos  
✅ **Token de Autenticação**: Todos os uploads exigem token válido  
✅ **Validação de Tipo**: Apenas tipos aceitos são permitidos  
✅ **Limite de Tamanho**: Protege contra uploads muito grandes  
✅ **Expiração Automática**: Arquivos expiram em 7 dias na OpenAI  

## Troubleshooting

### Erro: "Failed to upload"

- Verifique se `VITE_UPLOAD_API_URL` está correto no `.env`
- Confirme que o backend está rodando
- Verifique o token Supabase no console

### Arquivo não aparece

- Confirme que o tipo de arquivo está em `accept`
- Verifique se não excede `maxFileSizeBytes`
- Veja os logs do backend para erros

### "File attachments are not supported"

- Isso não deve mais acontecer! Se aparecer, o conversor não está sendo usado
- Verifique se o backend tem `OpenAIFileThreadItemConverter` configurado

## Próximos Passos

1. **Preview de imagens**: Adicionar thumbnails antes de enviar
2. **Download de arquivos**: Botão para baixar arquivos enviados
3. **Drag & Drop**: Arrastar arquivos para o chat
4. **Área de gestão**: Painel para ver todos os arquivos da thread

---

**🎉 Sistema de upload totalmente funcional!**

Frontend e backend integrados com OpenAI Files API e Agents SDK.

