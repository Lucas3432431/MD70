# gen_free_image

Gera uma imagem com prompt livre via Gemini 3 Pro Image (Vertex AI). Cobra créditos por geração bem-sucedida. **Requer aprovação do usuário** antes de executar.

## Uso básico

```
gen_free_image(
  prompt="Mulher 30 anos segurando produto X em ambiente externo, luz natural, AspectRatio 9:16",
  aspect_ratio="9:16"
)
```

## Com imagem de referência

```
gen_free_image(
  prompt="Reproduza essa imagem exatamente no formato 1:1, centralizando o sujeito principal",
  reference_image="https://...",
  aspect_ratio="1:1"
)
```

## Parâmetros

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `prompt` | string | Sim | Prompt livre para geração. Inclua no próprio prompt instruções sobre composição, sujeito, enquadramento, ambiente, etc. |
| `aspect_ratio` | string | Não | Proporção da imagem. Padrão: `"9:16"`. Valores: `"9:16"`, `"16:9"`, `"1:1"`, `"4:5"`, `"3:4"` |
| `reference_image` | string (URL) | Não | URL pública da imagem de referência. Gere via `generate_temporary_public_url(attachment_id="...")` antes de passar aqui. |

## Fluxo para usar reference_image de um attachment

```
1. generate_temporary_public_url(attachment_id="attach_XXXX")
   → retorna { url: "https://..." }

2. gen_free_image(
     prompt="Converta essa imagem para o formato 1:1 ...",
     reference_image="<url do passo 1>",
     aspect_ratio="1:1"
   )
```

## Retorno

```json
{
  "success": true,
  "tool": "gen_free_image",
  "asset_id": "uuid-do-asset",
  "filename": "uuid.jpg",
  "ratio": "9:16",
  "credits_remaining": 12.5,
  "message": "Imagem gerada com sucesso (9:16). Use file(filename='uuid.jpg') para exibir..."
}
```

## Aspect ratios suportados

| Valor | Uso |
|-------|-----|
| `9:16` | Stories, Reels (vertical) |
| `16:9` | YouTube, banners horizontais |
| `1:1` | Feed quadrado |
| `4:5` | Feed retrato (recomendado Meta Ads) |
| `3:4` | Retrato editorial |

## Notas

- O prompt é enviado **diretamente** ao modelo sem formatação estruturada. Inclua todos os detalhes que desejar.
- Para variações de aspect ratio de uma imagem existente, use `reference_image` com URL temporária e descreva no `prompt` a adaptação desejada.
- Cobra créditos de geração de imagem igual ao `asset` tool.
