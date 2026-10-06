# instagram (MCP)

Acessa e gerencia a conta Instagram Business via Graph API do Meta.

## Permissões necessárias

| Escopo | Operações |
|--------|-----------|
| `instagram_basic`, `instagram_manage_insights` | Perfil, mídia, insights, comentários |
| `instagram_content_publish` | Publicar posts, reels, carrosséis |
| `instagram_manage_messages` | DMs: listar conversas, ler e enviar mensagens |

---

## Perfil e Conta

```
mcp__instagram__get_profile          (alias: get_account_info)
  → username, bio, seguidores, seguindo, nº de posts

mcp__instagram__get_account_insights(period="days_28")
  → impressões, alcance, visitas ao perfil, novos seguidores
  period: day | week | days_28 | month
```

---

## Publicações (READ)

```
mcp__instagram__list_media(limit=10)           (alias: get_media)
  → lista posts/reels/carrosséis: ID, tipo, data, legenda (prévia)

mcp__instagram__get_media_insights(media_id="...")
  → impressões, alcance, likes, comentários, salvamentos, compartilhamentos

mcp__instagram__get_stories()
  → stories ativos da conta (expiram em 24h): ID, tipo, URL, timestamp
```

---

## Publicações (WRITE)

```
mcp__instagram__create_post(image_url="https://...", caption="...")
  → publica imagem (URL pública obrigatória)

mcp__instagram__create_carousel(image_urls=["url1","url2",...], caption="...")
  → carrossel de 2–10 imagens

mcp__instagram__create_reel(video_url="https://...", caption="...", cover_url="...")
  → publica Reel (.mp4 via URL pública); aguarda processamento automático
```

---

## Comentários

```
mcp__instagram__list_comments(media_id="...", limit=20)    (alias: get_comments)
  → @username, timestamp, texto, likes, ID do comentário

mcp__instagram__reply_comment(comment_id="...", message="...")
  → responde a um comentário
```

---

## Menções e Hashtags

```
mcp__instagram__get_mentions(limit=20)
  → posts de outros usuários que marcaram a conta (@menção)
  → retorna: ID, tipo, data, prévia da legenda

mcp__instagram__get_hashtag_search(hashtag="moda", type="top", limit=10)
  → pesquisa posts públicos por hashtag
  type: top (padrão) | recent
  → retorna: ID, tipo, data, likes, comentários, prévia da legenda
```

---

## Mensagens Diretas (DM) — requer instagram_manage_messages

```
mcp__instagram__get_conversations(limit=10)
  → lista conversas de DM: ID da conversa, participantes, prévia da última mensagem

mcp__instagram__get_messages(conversation_id="...", limit=20)
  → mensagens de uma conversa em ordem cronológica: timestamp, remetente, texto

mcp__instagram__send_message(recipient_id="<IGSID>", message="...")
  → envia DM para um usuário
  recipient_id: Instagram-Scoped User ID (aparece em get_conversations como participante)
  IMPORTANTE: o usuário precisa ter enviado mensagem primeiro (janela de 7 dias)
```

---

## Fluxo típico de atendimento via DM

```
1. mcp__instagram__get_conversations()           → lista conversas abertas
2. mcp__instagram__get_messages(conversation_id) → lê histórico
3. mcp__instagram__send_message(recipient_id, message) → responde
```

## Fluxo de publicação

```
1. mcp__instagram__create_post(image_url="https://cdn.exemplo.com/img.jpg", caption="Legenda #hashtag")
   → retorna media_id da publicação criada
```
