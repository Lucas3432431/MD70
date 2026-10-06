"""
Tool send — envia mensagem de resposta para o remetente externo do trigger.
Detecta o canal automaticamente pelo contexto do chat (trigger_id + provider).
O bot_token/credentials são resolvidos internamente a partir do provider_config
criptografado do trigger — o agente nunca tem acesso ao token.
"""
import json
import re
import httpx
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Crunch.TablesSQL.DBCryptographyManager import DBCryptographyManager
from App.Core.Logs import debug, warning


def _decrypt_provider_config(raw) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        decrypted = DBCryptographyManager.decrypt_field(raw)
        return json.loads(decrypted if decrypted else raw)
    except Exception:
        try:
            return json.loads(raw)
        except Exception:
            return {}


def _extract_message_text(raw) -> tuple[str, str]:
    """
    Extrai texto puro e parse_mode de qualquer formato que o agente passe em 'message'.
    Retorna (text, parse_mode).
    """
    parse_mode = "HTML"

    if isinstance(raw, dict):
        # send(message={"message": "..."}) ou send(message={"text": "..."})
        text = (raw.get("message") or raw.get("text") or "").strip()
        parse_mode = raw.get("parse_mode") or "HTML"
        return text, parse_mode

    if isinstance(raw, str):
        raw = raw.strip()
        # Tenta desserializar caso o agente tenha passado JSON como string
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                text = (parsed.get("message") or parsed.get("text") or raw).strip()
                parse_mode = parsed.get("parse_mode") or "HTML"
                return text, parse_mode
            # JSON mas não dict (ex: string entre aspas duplas)
            return str(parsed).strip(), parse_mode
        except Exception:
            pass
        # String pura — retorna diretamente
        return raw, parse_mode

    return str(raw).strip(), parse_mode


def _send_telegram(
    bot_token: str, recipient_id: str, message: str, parse_mode: str
) -> dict:
    with httpx.Client(timeout=10) as client:
        resp = client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": int(recipient_id),
                "text": message,
                "parse_mode": parse_mode,
            },
        )
    data = resp.json()
    if data.get("ok"):
        debug(f"[SEND] Telegram → {recipient_id}")
        return {
            "success": True,
            "provider": "telegram",
            "message": message,
            "message_id": data.get("result", {}).get("message_id"),
        }
    return {
        "success": False,
        "provider": "telegram",
        "error": data.get("description", "Erro do Telegram"),
    }


def _send_whatsapp(
    access_token: str, phone_number_id: str, recipient_phone: str, message: str
) -> dict:
    with httpx.Client(timeout=15) as client:
        resp = client.post(
            f"https://graph.facebook.com/v22.0/{phone_number_id}/messages",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": recipient_phone,
                "type": "text",
                "text": {"body": message},
            },
        )
    data = resp.json()
    if resp.status_code == 200 and data.get("messages"):
        msg_id = data["messages"][0].get("id", "")
        debug(f"[SEND] WhatsApp → {recipient_phone} msg_id={msg_id}")
        return {
            "success": True,
            "provider": "whatsapp",
            "message": message,
            "message_id": msg_id,
        }
    error_info = data.get("error") or {}
    error_msg = error_info.get("message") or f"HTTP {resp.status_code}"
    warning(f"[SEND] WhatsApp erro: {error_msg} | body={str(data)[:300]}")
    return {"success": False, "provider": "whatsapp", "error": error_msg}


def _send_instagram(
    access_token: str, ig_user_id: str, recipient_igsid: str, message: str
) -> dict:
    # Instagram Messaging API: POST /{ig-user-id}/messages
    with httpx.Client(timeout=15) as client:
        resp = client.post(
            f"https://graph.facebook.com/v22.0/{ig_user_id}/messages",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "recipient": {"id": recipient_igsid},
                "message": {"text": message},
            },
        )
    data = resp.json()
    if resp.status_code == 200 and data.get("message_id"):
        debug(f"[SEND] Instagram → {recipient_igsid}")
        return {
            "success": True,
            "provider": "instagram",
            "message": message,
            "message_id": data.get("message_id", ""),
        }
    error_info = data.get("error") or {}
    error_msg = error_info.get("message") or f"HTTP {resp.status_code}"
    warning(f"[SEND] Instagram erro: {error_msg} | body={str(data)[:300]}")
    return {"success": False, "provider": "instagram", "error": error_msg}


def execute(args: dict, chat_id: str = None, **kwargs) -> str:
    # ── Extrair parâmetros ───────────────────────────────────────────────────
    message, parse_mode = _extract_message_text(args.get("message", ""))

    if not message:
        return json.dumps({"success": False, "error": "Campo 'message' obrigatório."})
    if not chat_id:
        return json.dumps(
            {"success": False, "error": "Contexto de chat não disponível."}
        )

    db = DatabaseManager()

    # ── Resolver contexto do chat ────────────────────────────────────────────
    chat_row = db.fetch_one(
        "SELECT trigger_id, external_sender_id FROM chats WHERE chat_id = :id",
        {"id": chat_id},
    )
    if (
        not chat_row
        or not chat_row.get("trigger_id")
        or not chat_row.get("external_sender_id")
    ):
        return json.dumps(
            {"success": False, "error": "Chat não está associado a um trigger externo."}
        )

    trigger_id = chat_row["trigger_id"]
    recipient_id = chat_row["external_sender_id"]

    # ── Buscar webhook_secret (substitui tabela `triggers` que foi dropada) ──
    ws_row = db.fetch_one(
        "SELECT provider, client_id, provider_config FROM webhook_secrets WHERE web_secret_id = :id",
        {"id": trigger_id},
    )
    if not ws_row:
        return json.dumps({"success": False, "error": "Webhook não encontrado."})

    provider = ws_row.get("provider", "")
    client_id = ws_row.get("client_id", "")
    provider_config = _decrypt_provider_config(ws_row.get("provider_config"))

    # ── Verificar provider override do agente ───────────────────────────────
    channel_arg = args.get("channel") or {}
    if isinstance(channel_arg, str):
        try:
            channel_arg = json.loads(channel_arg)
        except Exception:
            channel_arg = {}
    requested_provider = channel_arg.get("provider") or provider

    if requested_provider != provider:
        return json.dumps(
            {
                "success": False,
                "error": f"Provider solicitado '{requested_provider}' não corresponde ao provider do trigger '{provider}'.",
            }
        )

    # ── Rotear para o canal correto ──────────────────────────────────────────
    try:
        if provider == "telegram":
            bot_token = provider_config.get("bot_token", "")
            if not bot_token:
                return json.dumps(
                    {
                        "success": False,
                        "error": "bot_token não configurado no trigger Telegram.",
                    }
                )
            result = _send_telegram(bot_token, recipient_id, message, parse_mode)
            return json.dumps(result)

        if provider == "whatsapp":
            access_token = provider_config.get("access_token", "")
            phone_number_id = provider_config.get("phone_number_id", "")
            if not access_token or not phone_number_id:
                return json.dumps(
                    {
                        "success": False,
                        "error": "access_token ou phone_number_id não configurados no trigger WhatsApp.",
                    }
                )
            result = _send_whatsapp(
                access_token, phone_number_id, recipient_id, message
            )
            return json.dumps(result)

        if provider == "instagram":
            # Credenciais vêm da integração MCP (mcp_integrations), não do webhook_secret
            session = db.get_session()
            try:
                env_vars = DatabaseManager.get_mcp_integration_env_vars(
                    session, client_id, "instagram"
                )
            finally:
                session.close()

            access_token = env_vars.get("INSTAGRAM_ACCESS_TOKEN", "")
            ig_user_id = env_vars.get("INSTAGRAM_BUSINESS_ACCOUNT_ID") or env_vars.get(
                "INSTAGRAM_USER_ID", ""
            )
            if not access_token or not ig_user_id:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Integração Instagram não configurada — conecte em Configurações → Integrações.",
                    }
                )
            result = _send_instagram(access_token, ig_user_id, recipient_id, message)
            return json.dumps(result)

        return json.dumps(
            {
                "success": False,
                "error": f"Provider '{provider}' ainda não suportado pela tool send.",
            }
        )

    except Exception as e:
        warning(f"[SEND] Erro ao enviar via {provider}: {e}")
        return json.dumps({"success": False, "error": str(e)})
