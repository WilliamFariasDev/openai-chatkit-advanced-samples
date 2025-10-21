# File Upload Implementation - ChatKit Python Backend

## Visão Geral

Este sistema implementa upload de arquivos usando o **OpenAI Files API** integrado com o ChatKit Python. Os arquivos são enviados diretamente para a OpenAI e referenciados por ID, seguindo o mesmo padrão do seu `backend-service-nodejs`.

## Arquitetura

### Componentes Principais

1. **AttachmentStore** (`attachment_store.py`)
   - Gerencia metadados de attachments no Supabase
   - Faz upload de arquivos para OpenAI Files API
   - Implementa interface do ChatKit para attachments

2. **ThreadItemConverter** (`thread_item_converter.py`)
   - Converte attachments em inputs do Agents SDK
   - Usa OpenAI file IDs ao invés de base64
   - Suporta imagens e PDFs

3. **Endpoints de Upload** (`main.py`)
   - `/api/attachments/{attachment_id}/upload` - Two-phase upload (fase 2)
   - `/api/uploads/direct` - Direct upload (uma etapa)

### Fluxo de Upload

#### Two-Phase Upload (Recomendado)

**Fase 1: Registro**
1. Cliente chama ChatKit API para criar attachment
2. ChatKit persiste metadata no banco
3. Retorna `upload_url` para o cliente

**Fase 2: Upload**
1. Cliente envia arquivo para `POST /api/attachments/{attachment_id}/upload`
2. Backend faz upload para OpenAI Files API
3. Salva `openai_file_id` no banco
4. Retorna confirmação

#### Direct Upload (Alternativa)

1. Cliente envia arquivo para `POST /api/uploads/direct`
2. Backend cria attachment e faz upload em uma só operação
3. Retorna attachment completo com `openai_file_id`

## Banco de Dados

### Tabela `uploads`

```sql
CREATE TABLE public.uploads (
    id VARCHAR PRIMARY KEY,                  -- Attachment ID
    user_id BIGINT NOT NULL,                 -- Usuário dono do arquivo
    openai_file_id VARCHAR UNIQUE,           -- ID na OpenAI Files API
    filename VARCHAR NOT NULL,               -- Nome do arquivo
    byte_size INTEGER NOT NULL,              -- Tamanho em bytes
    mime VARCHAR NOT NULL,                   -- MIME type
    status VARCHAR NOT NULL DEFAULT 'pending', -- pending|uploaded|failed
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
```

### Tabela `thread_files`

```sql
CREATE TABLE public.thread_files (
    id VARCHAR PRIMARY KEY,
    thread_id VARCHAR NOT NULL,              -- ID da thread (conversation)
    openai_file_id VARCHAR NOT NULL,         -- ID do arquivo na OpenAI
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
```

## Uso no Agents SDK

Quando um usuário envia uma mensagem com attachment, o sistema:

1. Obtém o `openai_file_id` do banco de dados
2. Usa `OpenAIFileThreadItemConverter` para converter:
   - **Imagens**: `ResponseInputImageParam` com `image_url=f"file://{openai_file_id}"`
   - **PDFs**: `ResponseInputFileParam` com `file_id=openai_file_id`

```python
# Exemplo no chat.py
converter = OpenAIFileThreadItemConverter(user_id)
agent_input = await converter.to_agent_input(target_item)

result = Runner.run_streamed(
    self.assistant,
    agent_input,
    context=agent_context,
)
```

## Configuração

### Variáveis de Ambiente

Certifique-se de ter no `.env`:

```env
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1  # Opcional
DATABASE_URL=postgresql://...
SUPABASE_URL=https://....supabase.co
SUPABASE_ANON_KEY=...
```

### Migração do Banco

Execute a migração para criar as tabelas:

```bash
# Se estiver usando psql
psql $DATABASE_URL -f backend/migrations/005_add_uploads_table.sql
```

## Exemplos de API

### Two-Phase Upload

```bash
# Fase 1: Cliente usa ChatKit para criar attachment
# (feito automaticamente pelo ChatKit client)

# Fase 2: Upload do arquivo
curl -X POST http://localhost:8000/api/attachments/att_abc123/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@documento.pdf"

# Response:
{
  "id": "att_abc123",
  "openai_file_id": "file-xyz789",
  "status": "uploaded"
}
```

### Direct Upload

```bash
curl -X POST http://localhost:8000/api/uploads/direct \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@imagem.jpg" \
  -F "thread_id=thread_123"

# Response:
{
  "id": "att_abc123",
  "thread_id": "thread_123",
  "mime_type": "image/jpeg",
  "name": "imagem.jpg",
  "size_bytes": 102400,
  "openai_file_id": "file-xyz789",
  "created_at": "2025-10-20T12:00:00"
}
```

## Tipos de Arquivos Suportados

### Imagens
- JPG, PNG, GIF, WebP
- Enviadas como `ResponseInputImageParam`
- Renderizadas inline no chat

### Documentos
- **PDF** (totalmente suportado)
- Outros formatos de texto podem exigir conversão para PDF

## Segurança

### Row Level Security (RLS)

Todas as tabelas têm RLS habilitado:
- Usuários só podem ver/modificar seus próprios uploads
- Uploads vinculados a threads são protegidos pela propriedade da thread

### Expiração de Arquivos

Arquivos na OpenAI expiram automaticamente após 7 dias:

```python
# Em attachment_store.py
expires_after={'anchor': 'created_at', 'seconds': 60 * 60 * 24 * 7}
```

### Validação

- Tamanho máximo de arquivo (configurável no FastAPI)
- Validação de MIME type
- Verificação de propriedade antes de qualquer operação

## Próximos Passos

1. **Associar files com threads**: Use `thread_files` para rastrear quais arquivos estão em cada conversa
2. **Enviar files para o Assistant**: Ao criar uma run na OpenAI, inclua os `file_ids` relevantes
3. **Preview de imagens**: Implemente geração de preview URLs para thumbnails
4. **Storage local alternativo**: Se preferir S3/GCS ao invés de OpenAI Files API

## Diferenças do Node.js Backend

O backend Python segue a mesma lógica do `backend-service-nodejs`:

| Aspecto | Node.js | Python |
|---------|---------|--------|
| Upload para OpenAI | ✓ | ✓ |
| Tabela `uploads` | ✓ | ✓ |
| Tabela `thread_files` | ✓ | ✓ |
| Direct upload | Via Multer | Via FastAPI UploadFile |
| Row Level Security | ✓ | ✓ |

## Troubleshooting

### Erro: "openai_file_id is null"

O arquivo ainda não foi enviado. Certifique-se de completar a fase 2 do upload.

### Erro: "File attachments are not supported"

O conversor padrão não suporta attachments. Verifique se `OpenAIFileThreadItemConverter` está sendo usado.

### Erro de permissão no banco

Verifique se as políticas RLS foram criadas corretamente e se o usuário está autenticado.

