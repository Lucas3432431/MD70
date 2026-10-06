# generate_temporary_public_url — Gerar URL Pública de Arquivo

**Objetivo:** Converter `attachment_id` ou arquivo local em URL pública temporária para usar em `vision()`, `asset()`, Meta Ads, Replicate e qualquer API externa.

> **USE SEMPRE** que precisar passar imagem/arquivo para outra tool. Essas ferramentas **não convertem attachment_id automaticamente**.

## Exemplos

### Usuário enviou um arquivo
```
generate_temporary_public_url(attachment_id="attach_a1b2c3d4")
// → { "url": "https://api.prox.app.br/api/files/temp/TOKEN" }
```

### Arquivo gerado no servidor
```
generate_temporary_public_url(file_path="/tmp/sandbox/{user_id}/imagem.png")
```

### Buscar por nome no sandbox
```
generate_temporary_public_url(filename="logo.png")
```

## Parâmetros

| Parâmetro | Tipo | Descrição |
|-----------|------|-----------|
| `attachment_id` | string | ID do upload do usuário (`attach_XXXX`) |
| `file_path` | string | Caminho absoluto no servidor |
| `filename` | string | Nome do arquivo — busca no sandbox e attachments do chat |
| `ttl_minutes` | integer | Validade da URL em minutos (padrão: 60) |

Pelo menos um dos três primeiros parâmetros é obrigatório.

## Fluxo típico

```
// 1. Gerar URL
url_result = generate_temporary_public_url(attachment_id="attach_a1b2c3")

// 2. Usar a URL em outra tool
vision(prompt="Descreva esta imagem", image_input=url_result["url"])
asset(type="image", id="POST_ID", image_input=url_result["url"], ...)
```

**Retorna:** `{ "success": true, "url": "https://...", "mime_type": "...", "ttl_minutes": 60 }`
