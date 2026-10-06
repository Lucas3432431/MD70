# asset — Gerar Assets com IA

**Objetivo:** Criar imagens e vídeos com IA vinculados a posts do calendário editorial.

## Gerar imagem
```
asset(
  type="image",
  id="POST_ID",
  prompt="Mulher jovem usando produto em ambiente clean, luz natural, estilo lifestyle",
  image_input="https://exemplo.com/logo.png",
  aspect_ratio="4:5",
  title="Post Instagram - Awareness",
  wait=true
)
```

## Gerar vídeo
```
asset(
  type="video",
  id="POST_ID",
  prompt="Animação suave do produto girando sobre fundo branco",
  reference_image="https://exemplo.com/produto.png",
  duration="15",
  title="Reel - Produto",
  wait=true
)
```

## Parâmetros

| Parâmetro | Tipo | Descrição |
|-----------|------|-----------|
| `type` | string (obrigatório) | `image` \| `video` \| `motion_graphics` |
| `id` | string (obrigatório) | ID do post (obtido via `schedule`) |
| `prompt` | string (obrigatório) | Descrição detalhada do asset |
| `reference_image` | string | URL de imagem de referência |
| `image_input` | string \| array | Imagem(ns) de entrada (URL pública) |
| `aspect_ratio` | string | `1:1` \| `4:5` \| `9:16` \| `16:9` (entre outros) |
| `duration` | string | Duração em segundos (para vídeo) |
| `title` | string | Identificador descritivo (opcional) |
| `wait` | boolean | `true` = aguarda (padrão) \| `false` = background |

## Aspect ratios suportados
`1:1`, `3:2`, `2:3`, `3:4`, `4:3`, `4:5`, `5:4`, `9:16`, `16:9`, `21:9`

> **Para imagens do usuário:** converta `attachment_id` com `generate_temporary_public_url()` antes de passar para `image_input`.
