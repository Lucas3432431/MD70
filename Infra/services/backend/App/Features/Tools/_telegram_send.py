"""
Tool telegram_send — envia mensagem de resposta via Telegram Bot API.
Funciona apenas em chats originados de trigger Telegram (source='trigger', provider='telegram').
"""
import json
import httpx
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Logs import debug, warning


def execute(args: dict, chat_id: str = None, **kwargs) -> str:
    message = args.get("message", "").strip()
    if not message:
        return json.dumps({"success": False, "error": "Campo 'message' obrigatório."})
    if not chat_id:
        return json.dumps(
            {"success": False, "error": "Contexto de chat não disponível."}
        )

    db = DatabaseManager()

    # Buscar trigger_id e external_sender_id do chat
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
            {"success": False, "error": "Chat não associado a um trigger Telegram."}
        )

    trigger_id = chat_row["trigger_id"]
    recipient_id = chat_row["external_sender_id"]

    # Buscar bot_token do trigger
    trigger_row = db.fetch_one(
        "SELECT provider, provider_config FROM triggers WHERE id = :id",
        {"id": trigger_id},
    )
    if not trigger_row or trigger_row.get("provider") != "telegram":
        return json.dumps({"success": False, "error": "Trigger não é Telegram."})

    provider_config = trigger_row.get("provider_config")
    if isinstance(provider_config, str):
        try:
            import json as _json

            provider_config = _json.loads(provider_config)
        except Exception:
            provider_config = None

    bot_token = (provider_config or {}).get("bot_token", "")
    if not bot_token:
        return json.dumps(
            {"success": False, "error": "bot_token não configurado no trigger."}
        )

    # Enviar mensagem
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": int(recipient_id),
                    "text": message,
                    "parse_mode": "HTML",
                },
            )
        data = resp.json()
        if data.get("ok"):
            debug(f"[TELEGRAM_SEND] Mensagem enviada para {recipient_id}")
            return json.dumps(
                {
                    "success": True,
                    "message_id": data.get("result", {}).get("message_id"),
                }
            )
        return json.dumps(
            {"success": False, "error": data.get("description", "Erro do Telegram")}
        )
    except Exception as e:
        warning(f"[TELEGRAM_SEND] Erro: {e}")
        return json.dumps({"success": False, "error": str(e)})
