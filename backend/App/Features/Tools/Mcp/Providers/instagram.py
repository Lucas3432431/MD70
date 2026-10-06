"""Provider Instagram para MCP nativo."""
import asyncio
from typing import Dict, Any, List
import httpx

TOOL_DEFINITIONS: List[Dict] = [
    {
        "name": "mcp__instagram__get_profile",
        "description": "[INSTAGRAM] Retorna o perfil do Instagram Business: username, bio, seguidores, seguindo, nº de posts.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "mcp__instagram__list_media",
        "description": "[INSTAGRAM] Lista publicações/mídias do perfil Instagram Business.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Número máximo de publicações (padrão 10)",
                },
            },
        },
    },
    {
        "name": "mcp__instagram__get_media",
        "description": "[INSTAGRAM] Obtém detalhes (legenda, likes, comentários, link) de uma publicação pelo ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "media_id": {"type": "string", "description": "ID da publicação"},
            },
            "required": ["media_id"],
        },
    },
    {
        "name": "mcp__instagram__get_media_insights",
        "description": "[INSTAGRAM] Retorna métricas de uma publicação: alcance, impressões, curtidas, comentários, salvamentos, compartilhamentos.",
        "parameters": {
            "type": "object",
            "properties": {
                "media_id": {"type": "string", "description": "ID da publicação"},
            },
            "required": ["media_id"],
        },
    },
    {
        "name": "mcp__instagram__get_account_insights",
        "description": "[INSTAGRAM] Retorna métricas da conta: impressões, alcance, visitas ao perfil, novos seguidores.",
        "parameters": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": "Período: day, week, days_28, month (padrão: days_28)",
                },
            },
        },
    },
    {
        "name": "mcp__instagram__list_comments",
        "description": "[INSTAGRAM] Lista comentários de uma publicação com contagem de likes e respostas.",
        "parameters": {
            "type": "object",
            "properties": {
                "media_id": {"type": "string", "description": "ID da publicação"},
                "limit": {
                    "type": "integer",
                    "description": "Número máximo de comentários (padrão 20)",
                },
            },
            "required": ["media_id"],
        },
    },
    {
        "name": "mcp__instagram__reply_comment",
        "description": "[INSTAGRAM] Responde a um comentário em uma publicação.",
        "parameters": {
            "type": "object",
            "properties": {
                "comment_id": {
                    "type": "string",
                    "description": "ID do comentário a responder",
                },
                "message": {"type": "string", "description": "Texto da resposta"},
            },
            "required": ["comment_id", "message"],
        },
    },
    {
        "name": "mcp__instagram__create_post",
        "description": "[INSTAGRAM] Publica uma imagem no Instagram Business (requer URL pública da imagem).",
        "parameters": {
            "type": "object",
            "properties": {
                "image_url": {
                    "type": "string",
                    "description": "URL pública da imagem a publicar",
                },
                "caption": {
                    "type": "string",
                    "description": "Legenda da publicação (opcional)",
                },
            },
            "required": ["image_url"],
        },
    },
    {
        "name": "mcp__instagram__create_carousel",
        "description": "[INSTAGRAM] Publica um carrossel de imagens (2–10 imagens) com legenda.",
        "parameters": {
            "type": "object",
            "properties": {
                "image_urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de URLs públicas das imagens (mín 2, máx 10)",
                },
                "caption": {
                    "type": "string",
                    "description": "Legenda do carrossel (opcional)",
                },
            },
            "required": ["image_urls"],
        },
    },
    {
        "name": "mcp__instagram__create_reel",
        "description": "[INSTAGRAM] Publica um Reel (vídeo) no Instagram Business. O vídeo deve ser acessível via URL pública.",
        "parameters": {
            "type": "object",
            "properties": {
                "video_url": {
                    "type": "string",
                    "description": "URL pública do vídeo (.mp4)",
                },
                "caption": {
                    "type": "string",
                    "description": "Legenda do Reel (opcional)",
                },
                "cover_url": {
                    "type": "string",
                    "description": "URL da imagem de capa (opcional)",
                },
            },
            "required": ["video_url"],
        },
    },
    {
        "name": "mcp__instagram__get_account_info",
        "description": "[INSTAGRAM] Alias de get_profile. Retorna nome, username, bio, followers_count, media_count da conta Business.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "mcp__instagram__get_comments",
        "description": "[INSTAGRAM] Alias de list_comments. Lista comentários de uma publicação.",
        "parameters": {
            "type": "object",
            "properties": {
                "media_id": {"type": "string", "description": "ID da publicação"},
                "limit": {
                    "type": "integer",
                    "description": "Número máximo de comentários (padrão 20)",
                },
            },
            "required": ["media_id"],
        },
    },
    {
        "name": "mcp__instagram__get_mentions",
        "description": "[INSTAGRAM] Lista posts de outros usuários que marcaram (@mencionaram) a conta Business.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Número máximo de menções (padrão 20)",
                },
            },
        },
    },
    {
        "name": "mcp__instagram__get_hashtag_search",
        "description": "[INSTAGRAM] Pesquisa posts públicos por hashtag. Retorna top ou recent posts com likes e comentários.",
        "parameters": {
            "type": "object",
            "properties": {
                "hashtag": {
                    "type": "string",
                    "description": "Hashtag a pesquisar (com ou sem #)",
                },
                "type": {"type": "string", "description": "top (padrão) ou recent"},
                "limit": {
                    "type": "integer",
                    "description": "Número máximo de resultados (padrão 10)",
                },
            },
            "required": ["hashtag"],
        },
    },
    {
        "name": "mcp__instagram__get_stories",
        "description": "[INSTAGRAM] Lista os stories ativos da conta Business (expiram em 24h).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "mcp__instagram__get_conversations",
        "description": "[INSTAGRAM] Lista conversas de DM da conta Instagram Business. Retorna ID da conversa, participantes e prévia das últimas mensagens. Requer permissão instagram_manage_messages.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Número máximo de conversas (padrão 10, máx 50)",
                },
            },
        },
    },
    {
        "name": "mcp__instagram__get_messages",
        "description": "[INSTAGRAM] Busca mensagens de uma conversa de DM específica. Use o conversation_id retornado por get_conversations. Requer permissão instagram_manage_messages.",
        "parameters": {
            "type": "object",
            "properties": {
                "conversation_id": {
                    "type": "string",
                    "description": "ID da conversa (retornado por get_conversations)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Número máximo de mensagens (padrão 20)",
                },
            },
            "required": ["conversation_id"],
        },
    },
    {
        "name": "mcp__instagram__send_message",
        "description": "[INSTAGRAM] Envia uma mensagem direta (DM) para um usuário via Instagram Messaging API. O destinatário precisa ter iniciado contato antes (janela de 7 dias). Requer permissão instagram_manage_messages.",
        "parameters": {
            "type": "object",
            "properties": {
                "recipient_id": {
                    "type": "string",
                    "description": "Instagram-Scoped User ID (IGSID) do destinatário",
                },
                "message": {
                    "type": "string",
                    "description": "Texto da mensagem a enviar",
                },
            },
            "required": ["recipient_id", "message"],
        },
    },
]


async def _get_page_token(user_token: str, ig_user_id: str) -> tuple[str, str]:
    """Retorna (page_id, page_access_token) da Página do Facebook conectada à conta Instagram."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.get(
                "https://graph.facebook.com/v22.0/me/accounts",
                params={
                    "access_token": user_token,
                    "fields": "id,access_token,instagram_business_account{id}",
                },
            )
            for page in r.json().get("data", []):
                if page.get("instagram_business_account", {}).get("id") == ig_user_id:
                    return page["id"], page["access_token"]
    except Exception:
        pass
    return "", ""


async def call(tool_name: str, args: Dict, env: Dict) -> Dict:
    access_token = env.get("INSTAGRAM_ACCESS_TOKEN", "")
    # INSTAGRAM_BUSINESS_ACCOUNT_ID é a chave usada pelo OAuth callback
    user_id = env.get("INSTAGRAM_BUSINESS_ACCOUNT_ID") or env.get(
        "INSTAGRAM_USER_ID", ""
    )
    base_url = "https://graph.facebook.com/v22.0"

    if not access_token:
        return {
            "success": False,
            "error": "Token Instagram não configurado — reconecte em Configurações → Integrações.",
        }

    def _ig_err(data: dict) -> Dict | None:
        if isinstance(data, dict) and "error" in data:
            err = data["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            code = err.get("code", 0) if isinstance(err, dict) else 0
            if code in (190, 102):
                return {
                    "success": False,
                    "error": "Token Instagram expirado — reconecte em Configurações → Integrações.",
                }
            return {"success": False, "error": f"Instagram API: {msg}"}
        return None

    async def _publish_container(http: httpx.AsyncClient, creation_id: str) -> Dict:
        resp = await http.post(
            f"{base_url}/{user_id}/media_publish",
            data={"access_token": access_token, "creation_id": creation_id},
        )
        data = resp.json()
        if err := _ig_err(data):
            return err
        return {
            "success": True,
            "media_id": data.get("id"),
            "content": f"Publicação criada com sucesso! ID: {data.get('id')}",
        }

    async with httpx.AsyncClient(timeout=30.0) as http:
        if tool_name == "get_profile":
            if not user_id:
                return {
                    "success": False,
                    "error": "ID da conta Instagram não configurado.",
                }
            params = {
                "access_token": access_token,
                "fields": "id,username,name,biography,followers_count,follows_count,media_count,profile_picture_url,website",
            }
            resp = await http.get(f"{base_url}/{user_id}", params=params)
            data = resp.json()
            if err := _ig_err(data):
                return err
            lines = [
                f"Username: @{data.get('username','?')}",
                f"Nome: {data.get('name','?')}",
                f"Bio: {data.get('biography','')[:120]}",
                f"Seguidores: {data.get('followers_count','?')} | Seguindo: {data.get('follows_count','?')} | Posts: {data.get('media_count','?')}",
            ]
            if data.get("website"):
                lines.append(f"Site: {data['website']}")
            return {"success": True, "content": "\n".join(lines)}

        elif tool_name == "list_media":
            if not user_id:
                return {
                    "success": False,
                    "error": "ID da conta Instagram não configurado.",
                }
            params = {
                "access_token": access_token,
                "fields": "id,caption,media_type,timestamp,permalink,thumbnail_url,media_url",
                "limit": min(args.get("limit", 10), 50),
            }
            resp = await http.get(f"{base_url}/{user_id}/media", params=params)
            data = resp.json()
            if err := _ig_err(data):
                return err
            items = data.get("data", [])
            lines = [
                f"ID: {item['id']} | {item.get('media_type','?')} | "
                f"{item.get('timestamp','')[:10]} | {(item.get('caption') or '')[:60]}"
                for item in items
            ]
            return {
                "success": True,
                "content": f"{len(items)} publicação(ões):\n" + "\n".join(lines),
            }

        elif tool_name == "get_media":
            media_id = args.get("media_id")
            params = {
                "access_token": access_token,
                "fields": "id,caption,media_type,timestamp,permalink,media_url,thumbnail_url,like_count,comments_count",
            }
            resp = await http.get(f"{base_url}/{media_id}", params=params)
            data = resp.json()
            if err := _ig_err(data):
                return err
            return {
                "success": True,
                "content": (
                    f"ID: {data.get('id')} | {data.get('media_type','?')} | {data.get('timestamp','')[:10]}\n"
                    f"Permalink: {data.get('permalink','')}\n"
                    f"Legenda: {(data.get('caption') or '')[:200]}\n"
                    f"Likes: {data.get('like_count','N/A')} | Comentários: {data.get('comments_count','N/A')}"
                ),
            }

        elif tool_name == "get_media_insights":
            media_id = args.get("media_id")
            params = {
                "access_token": access_token,
                "metric": "impressions,reach,likes,comments,saved,shares,total_interactions",
                "period": "lifetime",
            }
            resp = await http.get(f"{base_url}/{media_id}/insights", params=params)
            data = resp.json()
            if err := _ig_err(data):
                return err
            metrics = {
                m["name"]: m.get("values", [{}])[0].get("value", m.get("value", 0))
                for m in data.get("data", [])
            }
            lines = [f"Insights da publicação {media_id}:"]
            for name, val in metrics.items():
                lines.append(
                    f"  {name}: {val:,}" if isinstance(val, int) else f"  {name}: {val}"
                )
            return {"success": True, "content": "\n".join(lines)}

        elif tool_name == "get_account_insights":
            if not user_id:
                return {
                    "success": False,
                    "error": "ID da conta Instagram não configurado.",
                }
            period = args.get("period", "days_28")
            params = {
                "access_token": access_token,
                "metric": "impressions,reach,profile_views,follower_count",
                "period": period,
            }
            resp = await http.get(f"{base_url}/{user_id}/insights", params=params)
            data = resp.json()
            if err := _ig_err(data):
                return err
            lines = [f"Insights da conta (período: {period}):"]
            for m in data.get("data", []):
                vals = m.get("values", [])
                total = sum(v.get("value", 0) for v in vals)
                lines.append(f"  {m['name']}: {total:,}")
            return {"success": True, "content": "\n".join(lines)}

        elif tool_name == "list_comments":
            media_id = args.get("media_id")
            limit = min(args.get("limit", 20), 100)
            params = {
                "access_token": access_token,
                "fields": "id,text,username,timestamp,like_count,replies_count",
                "limit": limit,
            }
            resp = await http.get(f"{base_url}/{media_id}/comments", params=params)
            data = resp.json()
            if err := _ig_err(data):
                return err
            items = data.get("data", [])
            lines = [
                f"@{c.get('username','?')} | {c.get('timestamp','')[:10]} | ❤️{c.get('like_count',0)} | {c.get('text','')[:100]} [ID: {c.get('id')}]"
                for c in items
            ]
            return {
                "success": True,
                "content": f"{len(items)} comentário(s):\n" + "\n".join(lines),
            }

        elif tool_name == "reply_comment":
            comment_id = args.get("comment_id")
            message = args.get("message", "")
            if not comment_id or not message:
                return {
                    "success": False,
                    "error": "Campos 'comment_id' e 'message' são obrigatórios.",
                }
            resp = await http.post(
                f"{base_url}/{comment_id}/replies",
                data={"access_token": access_token, "message": message},
            )
            data = resp.json()
            if err := _ig_err(data):
                return err
            return {
                "success": True,
                "content": f"Resposta enviada! ID: {data.get('id')}",
            }

        elif tool_name == "create_post":
            if not user_id:
                return {
                    "success": False,
                    "error": "ID da conta Instagram não configurado.",
                }
            image_url = args.get("image_url")
            caption = args.get("caption", "")
            resp = await http.post(
                f"{base_url}/{user_id}/media",
                data={
                    "access_token": access_token,
                    "image_url": image_url,
                    "caption": caption,
                },
            )
            data = resp.json()
            if err := _ig_err(data):
                return err
            creation_id = data.get("id")
            if not creation_id:
                return {"success": False, "error": "Falha ao criar container de mídia."}
            return await _publish_container(http, creation_id)

        elif tool_name == "create_carousel":
            if not user_id:
                return {
                    "success": False,
                    "error": "ID da conta Instagram não configurado.",
                }
            image_urls = args.get("image_urls", [])
            if len(image_urls) < 2:
                return {
                    "success": False,
                    "error": "Carrossel requer pelo menos 2 imagens.",
                }
            caption = args.get("caption", "")
            # Step 1: create item containers
            children = []
            for url in image_urls[:10]:
                r = await http.post(
                    f"{base_url}/{user_id}/media",
                    data={
                        "access_token": access_token,
                        "image_url": url,
                        "is_carousel_item": "true",
                    },
                )
                item = r.json()
                if err := _ig_err(item):
                    return err
                item_id = item.get("id")
                if not item_id:
                    return {
                        "success": False,
                        "error": f"Falha ao criar item do carrossel para: {url}",
                    }
                children.append(item_id)
            # Step 2: create carousel container
            r2 = await http.post(
                f"{base_url}/{user_id}/media",
                data={
                    "access_token": access_token,
                    "media_type": "CAROUSEL",
                    "caption": caption,
                    "children": ",".join(children),
                },
            )
            carousel = r2.json()
            if err := _ig_err(carousel):
                return err
            creation_id = carousel.get("id")
            if not creation_id:
                return {
                    "success": False,
                    "error": "Falha ao criar container do carrossel.",
                }
            return await _publish_container(http, creation_id)

        elif tool_name == "create_reel":
            if not user_id:
                return {
                    "success": False,
                    "error": "ID da conta Instagram não configurado.",
                }
            video_url = args.get("video_url")
            caption = args.get("caption", "")
            cover_url = args.get("cover_url", "")
            payload: Dict[str, Any] = {
                "access_token": access_token,
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
                "share_to_feed": "true",
            }
            if cover_url:
                payload["cover_url"] = cover_url
            resp = await http.post(f"{base_url}/{user_id}/media", data=payload)
            data = resp.json()
            if err := _ig_err(data):
                return err
            creation_id = data.get("id")
            if not creation_id:
                return {"success": False, "error": "Falha ao criar container do Reel."}
            # Poll until video is processed (max 30s)
            for _ in range(6):
                await asyncio.sleep(5)
                status_resp = await http.get(
                    f"{base_url}/{creation_id}",
                    params={"access_token": access_token, "fields": "status_code"},
                )
                status = status_resp.json().get("status_code", "")
                if status == "FINISHED":
                    break
                if status == "ERROR":
                    return {
                        "success": False,
                        "error": "Falha no processamento do vídeo pelo Instagram.",
                    }
            return await _publish_container(http, creation_id)

        elif tool_name == "get_conversations":
            if not user_id:
                return {
                    "success": False,
                    "error": "ID da conta Instagram não configurado.",
                }
            page_id, page_token = await _get_page_token(access_token, user_id)
            if not page_id:
                return {
                    "success": False,
                    "error": "Página do Facebook conectada não encontrada — reconecte em Configurações → Integrações.",
                }
            limit = min(args.get("limit", 10), 50)
            params = {
                "access_token": page_token,
                "platform": "instagram",
                "fields": "id,participants,messages.limit(3){id,from,message,created_time}",
                "limit": limit,
            }
            resp = await http.get(f"{base_url}/{page_id}/conversations", params=params)
            data = resp.json()
            if err := _ig_err(data):
                return err
            conversations = data.get("data", [])
            lines = []
            for conv in conversations:
                participants = [
                    p.get("username") or p.get("name") or p.get("id", "?")
                    for p in (conv.get("participants") or {}).get("data", [])
                ]
                last_msg = ""
                msgs = (conv.get("messages") or {}).get("data", [])
                if msgs:
                    m = msgs[0]
                    sender = (m.get("from") or {}).get("name") or (
                        m.get("from") or {}
                    ).get("id", "?")
                    last_msg = (
                        f' | última: "{(m.get("message") or "")[:60]}" ({sender})'
                    )
                lines.append(f"ID: {conv['id']} | {', '.join(participants)}{last_msg}")
            return {
                "success": True,
                "content": f"{len(conversations)} conversa(s):\n" + "\n".join(lines),
            }

        elif tool_name == "get_messages":
            conversation_id = args.get("conversation_id")
            if not conversation_id:
                return {
                    "success": False,
                    "error": "Campo 'conversation_id' obrigatório.",
                }
            limit = min(args.get("limit", 20), 100)
            _page_id, page_token = (
                await _get_page_token(access_token, user_id) if user_id else ("", "")
            )
            _tok = page_token or access_token
            params = {
                "access_token": _tok,
                "platform": "instagram",
                "fields": "id,from,to,message,created_time,attachments",
                "limit": limit,
            }
            resp = await http.get(
                f"{base_url}/{conversation_id}/messages", params=params
            )
            data = resp.json()
            if err := _ig_err(data):
                return err
            messages = data.get("data", [])
            lines = []
            for m in reversed(messages):
                sender = (m.get("from") or {}).get("name") or (m.get("from") or {}).get(
                    "id", "?"
                )
                ts = (m.get("created_time") or "")[:19].replace("T", " ")
                text = m.get("message") or "[mídia/anexo]"
                lines.append(f"[{ts}] {sender}: {text[:200]}")
            return {
                "success": True,
                "content": f"{len(messages)} mensagem(ns):\n" + "\n".join(lines),
            }

        elif tool_name == "send_message":
            if not user_id:
                return {
                    "success": False,
                    "error": "ID da conta Instagram não configurado.",
                }
            recipient_id = args.get("recipient_id", "")
            message = args.get("message", "")
            if not recipient_id or not message:
                return {
                    "success": False,
                    "error": "Campos 'recipient_id' e 'message' são obrigatórios.",
                }
            resp = await http.post(
                f"{base_url}/{user_id}/messages",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"recipient": {"id": recipient_id}, "message": {"text": message}},
            )
            data = resp.json()
            if err := _ig_err(data):
                return err
            return {
                "success": True,
                "content": f"Mensagem enviada! ID: {data.get('message_id', data.get('id', '?'))}",
                "message_id": data.get("message_id") or data.get("id"),
            }

        # ── Aliases de nomes antigos ──────────────────────────────────────────
        elif tool_name == "get_account_info":
            # Alias → get_profile
            if not user_id:
                return {
                    "success": False,
                    "error": "ID da conta Instagram não configurado.",
                }
            params = {
                "access_token": access_token,
                "fields": "id,username,name,biography,followers_count,follows_count,media_count,profile_picture_url,website",
            }
            resp = await http.get(f"{base_url}/{user_id}", params=params)
            data = resp.json()
            if err := _ig_err(data):
                return err
            return {
                "success": True,
                "content": (
                    f"Username: @{data.get('username','?')}\n"
                    f"Nome: {data.get('name','?')}\n"
                    f"Bio: {data.get('biography','')[:120]}\n"
                    f"Seguidores: {data.get('followers_count','?')} | Seguindo: {data.get('follows_count','?')} | Posts: {data.get('media_count','?')}\n"
                    + (f"Site: {data['website']}" if data.get("website") else "")
                ),
            }

        elif tool_name == "get_comments":
            # Alias → list_comments
            media_id = args.get("media_id")
            limit = min(args.get("limit", 20), 100)
            params = {
                "access_token": access_token,
                "fields": "id,text,username,timestamp,like_count,replies_count",
                "limit": limit,
            }
            resp = await http.get(f"{base_url}/{media_id}/comments", params=params)
            data = resp.json()
            if err := _ig_err(data):
                return err
            items = data.get("data", [])
            lines = [
                f"@{c.get('username','?')} | {c.get('timestamp','')[:10]} | ❤️{c.get('like_count',0)} | {c.get('text','')[:100]} [ID: {c.get('id')}]"
                for c in items
            ]
            return {
                "success": True,
                "content": f"{len(items)} comentário(s):\n" + "\n".join(lines),
            }

        # ── Tools novas ───────────────────────────────────────────────────────
        elif tool_name == "get_mentions":
            if not user_id:
                return {
                    "success": False,
                    "error": "ID da conta Instagram não configurado.",
                }
            params = {
                "access_token": access_token,
                "fields": "id,caption,media_type,timestamp,permalink,media_url",
                "limit": min(args.get("limit", 20), 50),
            }
            resp = await http.get(f"{base_url}/{user_id}/tags", params=params)
            data = resp.json()
            if err := _ig_err(data):
                return err
            items = data.get("data", [])
            lines = [
                f"ID: {i['id']} | {i.get('media_type','?')} | {i.get('timestamp','')[:10]} | {(i.get('caption') or '')[:80]}"
                for i in items
            ]
            return {
                "success": True,
                "content": f"{len(items)} menção(ões):\n" + "\n".join(lines)
                if lines
                else "Nenhuma menção encontrada.",
            }

        elif tool_name == "get_hashtag_search":
            hashtag = args.get("hashtag", "").lstrip("#")
            search_type = args.get("type", "top")  # top | recent
            if not hashtag:
                return {"success": False, "error": "Campo 'hashtag' obrigatório."}
            if not user_id:
                return {
                    "success": False,
                    "error": "ID da conta Instagram não configurado.",
                }
            # Step 1: resolver hashtag → ID
            r1 = await http.get(
                f"{base_url}/ig_hashtag_search",
                params={"access_token": access_token, "user_id": user_id, "q": hashtag},
            )
            d1 = r1.json()
            if err := _ig_err(d1):
                return err
            hashtag_id = (d1.get("data") or [{}])[0].get("id")
            if not hashtag_id:
                return {
                    "success": False,
                    "error": f"Hashtag #{hashtag} não encontrada.",
                }
            # Step 2: buscar posts
            edge = "top_media" if search_type == "top" else "recent_media"
            r2 = await http.get(
                f"{base_url}/{hashtag_id}/{edge}",
                params={
                    "access_token": access_token,
                    "user_id": user_id,
                    "fields": "id,caption,media_type,timestamp,permalink,like_count,comments_count",
                    "limit": min(args.get("limit", 10), 50),
                },
            )
            d2 = r2.json()
            if err := _ig_err(d2):
                return err
            items = d2.get("data", [])
            lines = [
                f"ID: {i['id']} | {i.get('media_type','?')} | {i.get('timestamp','')[:10]} | ❤️{i.get('like_count','?')} 💬{i.get('comments_count','?')} | {(i.get('caption') or '')[:80]}"
                for i in items
            ]
            return {
                "success": True,
                "content": f"#{hashtag} — {len(items)} resultado(s) ({search_type}):\n"
                + "\n".join(lines),
            }

        elif tool_name == "get_stories":
            if not user_id:
                return {
                    "success": False,
                    "error": "ID da conta Instagram não configurado.",
                }
            params = {
                "access_token": access_token,
                "fields": "id,media_type,timestamp,media_url,permalink",
            }
            resp = await http.get(f"{base_url}/{user_id}/stories", params=params)
            data = resp.json()
            if err := _ig_err(data):
                return err
            items = data.get("data", [])
            if not items:
                return {"success": True, "content": "Nenhum story ativo no momento."}
            lines = [
                f"ID: {i['id']} | {i.get('media_type','?')} | publicado: {i.get('timestamp','')[:19].replace('T',' ')}"
                for i in items
            ]
            return {
                "success": True,
                "content": f"{len(items)} story(ies) ativo(s):\n" + "\n".join(lines),
            }

    return {"success": False, "error": "Ferramenta não reconhecida"}
