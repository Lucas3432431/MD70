# 📦 Storage Logic - Watermark & ZipManager

## 🎯 Fluxo Completo

```
Frontend (JavaScript/React)
    ↓
1. GET /api/chat/:id/check-documents
    ↓ [retorna: business_canvas, brand_communication, goals content]
2. Renderiza em hidden container
    ↓
3. documentConverterService.convertDocuments()
    ↓ [gera 3 formatos: raw, feed_4-5, story_9-16]
4. POST /api/chat/:id/download-zip [FormData com 9 base64]
    ↓
Backend (Python/FastAPI)
    ↓
ChatRoutes.download_chat_zip()
    ↓
├─ MODO 1: has_converted_docs = True (tem base64 do frontend)
│   ├─ Processa 3 documentos (business_canvas, brand_communication, goals)
│   ├─ Para cada documento:
│   │   ├─ RAW → salva em documents table
│   │   └─ RAW + FEED + STORY → salva em files table (assets)
│   └─ Se aplicável: watermark via WatermarkManager
│
└─ MODO 2: has_converted_docs = False (sem base64 do frontend)
    └─ ZipManager.create_chat_zip() → busca assets já existentes
```

---

## 🔐 WatermarkManager

### Responsabilidade
Adicionar watermark (logomarca) em imagens JPG **apenas para usuários FREE**.

### Fluxo de Decisão
```
1. Recebe user_id
2. Faz SQL 3-table JOIN:
   User → Client → Plan → plan_type
3. Retorna:
   - True: if plan_type == 'free'
   - False: if plan_type == 'paid'
```

### Implementação

**Arquivo:** `WatermarkManager.py`

```python
@staticmethod
def should_apply_watermark(user_id: str) -> bool:
    """
    Verifica se usuário é FREE via SQL JOIN.

    SQL:
    SELECT p.plan_type
    FROM users u
    JOIN clients c ON u.client_id = c.client_id
    JOIN plans p ON c.plan_id = p.plan_id
    WHERE u.user_id = :user_id

    Retorna: True se plan_type = 'free', False caso contrário
    """
    # SEM FALLBACK - se não encontrar, lança exceção
```

**Uso:**
```python
should_watermark = WatermarkManager.should_apply_watermark(user_id)
# True = aplicar watermark
# False = não aplicar
```

### Aplicação

**Arquivo:** `WatermarkManager.py`

```python
@staticmethod
def add_image_watermark(input_path: Path, output_path: Path) -> bool:
    """
    Aplica watermark em imagem JPG.

    Specs:
    - Logo: 5 níveis acima (../../../../../../logo.png)
    - Posição: 75% da altura (vertical)
    - Opacidade: 0.75 (75%)
    - Tamanho: proporcional à imagem

    Retorna: True se sucesso, False se erro
    """
```

---

## 📦 ZipManager

### Responsabilidade
Criar arquivo ZIP para download com:
- Documents (markdown originais) - **DESATIVADO**
- Uploads (arquivos enviados pelo usuário)
- Assets (imagens geradas/convertidas)

### Fluxo Principal

**Arquivo:** `ZipManager.py`

```python
@staticmethod
def create_chat_zip(
    client_id: int,
    chat_id: str,
    chat_name: str,
    user_id: Optional[str] = None,
    include_documents: bool = True,  # IGNORADO - não processa markdown
    include_uploads: bool = False,
    include_assets: bool = False,
    convert_md_to_pdf: bool = False  # DESATIVADO
) -> Optional[Dict[str, Any]]:
    """
    Cria ZIP para download do chat.

    Processo:
    1. [DESATIVADO] Markdown → PDF
    2. [ATIVO] Uploads → copia com watermark se user é free
    3. [ATIVO] Assets → copia com watermark se user é free
    """
```

### Passos Internos

#### 1️⃣ Estrutura de Pastas
```
{client_id}/chat_{chat_id}/
├── extract/          [pasta temporária de montagem do ZIP]
│   ├── documents/    [vazio - markdown desativado]
│   ├── uploads/      [arquivos do usuário]
│   └── assets/       [imagens geradas/convertidas]
├── temp_md/          [markdown temporário - desativado]
└── {chat_name}.zip   [arquivo final]
```

#### 2️⃣ Processamento de Uploads
```python
if include_uploads:
    uploads_folder = StorageManager.get_uploads_folder(client_id, chat_id)
    for upload_file in uploads_folder:
        if is_image_file(upload_file) and should_watermark:
            WatermarkManager.add_image_watermark(upload_file, dest_file)
        else:
            copy(upload_file, dest_file)
```

#### 3️⃣ Processamento de Assets
```python
if include_assets:
    db_assets = DatabaseManager.get_chat_files(
        db_session,
        chat_id,
        file_category="asset"
    )
    for asset in db_assets:
        asset_path = StorageManager.LOCAL_STORAGE_BASE / asset.storage_path
        if asset_path.exists():
            if is_image_file(asset_path) and should_watermark:
                WatermarkManager.add_image_watermark(asset_path, dest_file)
            else:
                copy(asset_path, dest_file)
```

#### 4️⃣ Criação do ZIP
```python
with zipfile.ZipFile(zip_path, 'w') as zipf:
    for file_path in extract_folder.rglob('*'):
        if file_path.is_file():
            arcname = f"{relative_path}/{file_path.name}"
            zipf.write(file_path, arcname=arcname)
```

#### 5️⃣ Limpeza
```python
# Após download (em background)
shutil.rmtree(extract_folder)
os.remove(zip_path)
```

---

## 💾 Storage no Banco de Dados

### Tabela: `files`

Campo | Tipo | Uso
--- | --- | ---
`file_id` | UUID | Identificador único
`chat_id` | UUID | Link ao chat
`file_name` | string | Nome do arquivo (ex: `Business_Canvas.jpg`, `Business_Canvas_feed_4-5.jpg`)
`file_size` | int | Tamanho em bytes
`file_hash` | string | MD5 do arquivo
`file_category` | enum | `"upload"` ou `"asset"`
`extension` | string | `"jpg"`, `"png"`, etc
`storage_path` | string | Caminho relativo no filesystem
`storage_env` | enum | `"local"` ou `"cloud"`
`created_at` | datetime | Timestamp

### Busca de Assets

```python
# Em ChatRoutes ou ZipManager
db_assets = DatabaseManager.get_chat_files(
    db_session,
    chat_id,
    file_category="asset"
)

# Retorna lista de File objects com:
# - file_name: Business_Canvas.jpg (document raw)
# - file_name: Business_Canvas_feed_4-5.jpg (asset gerado)
# - file_name: Business_Canvas_story_9-16.jpg (asset gerado)
# - storage_path: (mesmo nome do arquivo)
# - storage_env: local
```

### Recuperação do Arquivo

```python
for asset in db_assets:
    asset_path = StorageManager.LOCAL_STORAGE_BASE / asset.storage_path
    # Exemplo: Data/Database/client_xxx/chat_yyy/Business_Canvas_raw.jpg

    if asset_path.exists():
        # Aplicar watermark se necessário
        # Copiar para extract folder
```

---

## 🔄 Fluxo de Salvamento de Assets (Backend - POST /download-zip)

### MODO 1: Com Documentos Convertidos (has_converted_docs = True)

**Entrada:** FormData com 9 base64 (3 tipos × 3 formatos)

```
business_canvas_jpg_raw_base64     [123KB]
business_canvas_jpg_feed_base64    [456KB]
business_canvas_jpg_story_base64   [789KB]
brand_communication_jpg_raw_base64 [111KB]
brand_communication_jpg_feed_base64[222KB]
brand_communication_jpg_story_base64[333KB]
goals_jpg_raw_base64               [444KB]
goals_jpg_feed_base64              [555KB]
goals_jpg_story_base64             [666KB]
```

**Processamento:**

```python
for doc_type in ["business_canvas", "brand_communication", "goals"]:
    jpg_raw = request.form.get(f"{doc_type}_jpg_raw_base64")
    jpg_feed = request.form.get(f"{doc_type}_jpg_feed_base64")
    jpg_story = request.form.get(f"{doc_type}_jpg_story_base64")

    # 1. Salvar RAW em documents
    if jpg_raw:
        insert_documents(
            title=doc_type,
            content=jpg_raw,  # base64
            extension="jpg",
            tool_type=doc_type
        )

    # 2. Salvar 3 formatos em assets
    for format_name, jpg_base64 in [
        ("raw", jpg_raw),
        ("feed_4-5", jpg_feed),
        ("story_9-16", jpg_story)
    ]:
        if jpg_base64:
            jpg_data = base64.b64decode(jpg_base64)
            # Documents: sem sufixo (raw apenas). Assets: com sufixo (feed_4-5, story_9-16)
            filename = f"{title}.jpg" if format_name == "raw" else f"{title}_{format_name}.jpg"

            # 2a. Salvar arquivo em filesystem
            file_path = {client_id}/chat_{chat_id}/{filename}
            file_path.write_bytes(jpg_data)

            # 2b. Registrar em BD (files table)
            insert_files(
                file_name=filename,
                file_category="asset",
                storage_path=filename,
                storage_env="local",
                file_hash=md5(jpg_data)
            )

            # 2c. Aplicar watermark se user é free
            if should_watermark:
                WatermarkManager.add_image_watermark(file_path, file_path)
```

---

## 📥 Fluxo de Download

### Request
```
POST /api/chat/{chat_id}/download-zip
Content-Type: multipart/form-data

[FormData com base64s]
```

### Response
```
Content-Type: application/zip
Content-Disposition: attachment; filename="chat_name.zip"

[ZIP file binary]
```

### Conteúdo do ZIP
```
documents/
  Business_Canvas.jpg (documento raw, sem sufixo)
  Brand_Communication.jpg (documento raw, sem sufixo)
  Goals.jpg (documento raw, sem sufixo)

uploads/
  user_file.pdf
  user_image.jpg

assets/
  Business_Canvas.jpg (raw document)
  Business_Canvas_feed_4-5.jpg (gerado do raw)
  Business_Canvas_story_9-16.jpg (gerado do raw)
  Brand_Communication.jpg (raw document)
  Brand_Communication_feed_4-5.jpg (gerado do raw)
  Brand_Communication_story_9-16.jpg (gerado do raw)
  Goals.jpg (raw document)
  Goals_feed_4-5.jpg (gerado do raw)
  Goals_story_9-16.jpg (gerado do raw)
```

---

## ⚠️ Casos Especiais

### Usuário FREE
- ✅ Watermark aplicado em TODOS os JPGs (assets + uploads)
- ✅ Processamento normal

### Usuário PAID
- ❌ Sem watermark
- ✅ Processamento normal

### Documentos Não Encontrados
- ✅ ZIP vazio criado mesmo assim
- ✅ Assets ainda podem ser inclusos

### Imagem com Erro de Conversão
- ⚠️ Log de warning
- ❌ Arquivo não incluído no ZIP
- ✅ Processamento continua com outros

---

## 🔧 Configuração

**Arquivo:** `ZipManager.py`

```python
WATERMARK_OPACITY = 0.75          # 75% opacidade
WATERMARK_VERTICAL_POS = 0.75     # 75% da altura
LOGO_RELATIVE_PATH = "../../../../logo.png"  # 5 níveis acima
MAX_ZIP_SIZE = 500 * 1024 * 1024  # 500MB
```

---

## 📝 Notas Importantes

1. **PDF → DESATIVADO**: `convert_md_to_pdf = False` por padrão
2. **Markdown → DESATIVADO**: Não cria `temp_md` ou `.md` temporários
3. **Watermark → OBRIGATÓRIO**: Sempre aplicado a imagens de users FREE
4. **Assets → INDEPENDENTE**: Buscados do BD, não do frontend
5. **Documentos Convertidos**: Salvos pelo backend, não vêm prontos do frontend

---

## 🚀 Próximos Passos

1. ✅ Documentar Watermark e ZipManager (ESTE ARQUIVO)
2. ⏳ Corrigir chamadas do frontend para enviar base64
3. ⏳ Validar fluxo completo ponta-a-ponta
4. ⏳ Testes de edge cases (user FREE, múltiplos uploads, etc)
