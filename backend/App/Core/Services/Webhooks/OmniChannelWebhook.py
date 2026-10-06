import asyncio
import os
import re
import secrets
import string
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional

import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text

from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Logs import info, error as log_error, warning
from App.Features.Auth import get_auth_service
from App.Core.Settings.Settings import (
    OMNI_TELEGRAM_BOT_TOKEN,
    RESEND_API_KEY,
    OMNI_EMAIL_FROM,
    WEBHOOK_PREFIX,
)

omni_webhook_router = APIRouter(
    tags=["OmniChannel"], prefix=f"{WEBHOOK_PREFIX}/omnichannel"
)
omni_settings_router = APIRouter(
    tags=["OmniChannelSettings"], prefix="/api/omnichannel"
)

CONTEXT_LIMIT = 30
_CODE_CHARS = string.ascii_uppercase + string.digits
_CODE_TTL_MINUTES = 15


# ========================================================================
# AUTH HELPER
# ========================================================================


def _get_auth_payload(request: Request) -> dict:
    if request.scope.get("dev_bypass_enabled"):
        return {
            "client_id": str(request.scope.get("dev_client_id", "1")),
            "user_id": str(request.scope.get("dev_user_id", "1")),
        }
    auth_service = get_auth_service()
    if not auth_service:
        raise HTTPException(status_code=500, detail="Auth service não configurado")
    token = request.cookies.get("access_token") or (
        request.headers.get("Authorization", "").replace("Bearer ", "")
        if request.headers.get("Authorization")
        else None
    )
    if not token:
        raise HTTPException(status_code=401, detail="Token não fornecido")
    payload = auth_service.verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido")
    return payload


# ========================================================================
# DB HELPERS
# ========================================================================


def find_user_by_channel(channel: str, identifier: str) -> Optional[Dict]:
    session = DatabaseManager.get_session()
    try:
        col = {
            "whatsapp": "whatsapp",
            "telegram": "telegram",
            "instagram": "instagram",
            "email": "email",
        }.get(channel)
        if not col:
            return None
        row = session.execute(
            text(
                f"SELECT user_id, client_id, email, full_name FROM users WHERE {col} = :val LIMIT 1"
            ),
            {"val": identifier},
        ).fetchone()
        return dict(row._mapping) if row else None
    finally:
        session.close()


def get_or_create_agent_chat(user_id: str, provider: str, external_id: str) -> str:
    chat_id = f"omni_{provider}_{user_id}"
    with DatabaseManager.get_session() as session:
        row = session.execute(
            text("SELECT chat_id FROM agent_chat WHERE chat_id = :cid LIMIT 1"),
            {"cid": chat_id},
        ).fetchone()
        if not row:
            session.execute(
                text(
                    "INSERT INTO agent_chat (chat_id, user_id, provider, external_id) VALUES (:cid, :uid, :p, :eid)"
                ),
                {"cid": chat_id, "uid": user_id, "p": provider, "eid": external_id},
            )
            session.commit()
    return chat_id


def save_agent_message(chat_id: str, sender: str, content: str):
    with DatabaseManager.get_session() as session:
        session.execute(
            text(
                "INSERT INTO agent_messages (message_id, chat_id, sender, content) VALUES (:mid, :cid, :s, :cnt)"
            ),
            {"mid": str(uuid.uuid4()), "cid": chat_id, "s": sender, "cnt": content},
        )
        session.commit()


def load_agent_history(chat_id: str) -> list:
    session = DatabaseManager.get_session()
    try:
        rows = session.execute(
            text(
                "SELECT sender, content FROM agent_messages WHERE chat_id = :cid ORDER BY created_at DESC LIMIT :lim"
            ),
            {"cid": chat_id, "lim": CONTEXT_LIMIT},
        ).fetchall()
        return [
            {"role": "user" if r[0] == "user" else "assistant", "content": r[1]}
            for r in reversed(rows)
        ]
    finally:
        session.close()


# ========================================================================
# TELEGRAM LINK CODES
# ========================================================================


def _generate_link_code(user_id: str) -> str:
    code = "LINK-" + "".join(secrets.choice(_CODE_CHARS) for _ in range(8))
    expires_at = datetime.utcnow() + timedelta(minutes=_CODE_TTL_MINUTES)
    with DatabaseManager.get_session() as session:
        session.execute(
            text("DELETE FROM telegram_link_codes WHERE user_id = :uid"),
            {"uid": user_id},
        )
        session.execute(
            text(
                "INSERT INTO telegram_link_codes (code, user_id, expires_at) VALUES (:c, :uid, :exp)"
            ),
            {"c": code, "uid": user_id, "exp": expires_at},
        )
        session.commit()
    return code


def _consume_link_code(code: str) -> Optional[str]:
    with DatabaseManager.get_session() as session:
        row = session.execute(
            text(
                "SELECT user_id, expires_at FROM telegram_link_codes WHERE code = :c LIMIT 1"
            ),
            {"c": code},
        ).fetchone()
        if not row:
            return None
        expires_at = row.expires_at
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)
        if datetime.utcnow() > expires_at:
            session.execute(
                text("DELETE FROM telegram_link_codes WHERE code = :c"), {"c": code}
            )
            session.commit()
            return None
        user_id = row.user_id
        session.execute(
            text("DELETE FROM telegram_link_codes WHERE code = :c"), {"c": code}
        )
        session.commit()
        return user_id


# ========================================================================
# TELEGRAM REPLY
# ========================================================================


async def _send_telegram_reply(tg_chat_id: int, text_msg: str):
    if not OMNI_TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{OMNI_TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(url, json={"chat_id": tg_chat_id, "text": text_msg})
    except Exception as e:
        log_error(f"[OMNI] Falha ao enviar resposta Telegram: {e}")


# ========================================================================
# EMAIL REPLY (Resend)
# ========================================================================


async def _send_email_reply(to_email: str, subject: str, body_text: str):
    if not RESEND_API_KEY:
        log_error("[OMNI] RESEND_API_KEY não configurada — e-mail não enviado")
        return
    from_email = OMNI_EMAIL_FROM or "MD70 <prox@prox.app.br>"
    html_body = (
        f"<pre style='font-family:sans-serif;white-space:pre-wrap;'>{body_text}</pre>"
    )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": from_email,
                    "to": [to_email],
                    "subject": subject,
                    "html": html_body,
                },
            )
        if resp.status_code not in (200, 201):
            log_error(
                f"[OMNI] Falha ao enviar e-mail via Resend: {resp.status_code} {resp.text}"
            )
        else:
            info(f"[OMNI] E-mail enviado via Resend para {to_email}")
    except Exception as e:
        log_error(f"[OMNI] Erro ao enviar e-mail via Resend: {e}")


# ========================================================================
# AGENT PROCESSING (mesmo pipeline do chat normal)
# ========================================================================


_FORMAT_INSTRUCTIONS = {
    "whatsapp": (
        "\n\n[INSTRUÇÃO DE CANAL: Esta mensagem vem do WhatsApp. "
        "Responda em texto puro sem Markdown. "
        "Use apenas: *negrito*, _itálico_ e listas com hífen (- item). "
        "Sem #headers, sem ``` code blocks, sem tabelas.]"
    ),
    "default": (
        "\n\n[INSTRUÇÃO DE CANAL: Esta mensagem vem de um canal externo. "
        "Responda EXCLUSIVAMENTE em texto puro, sem nenhuma formatação Markdown. "
        "Sem **, sem __, sem #, sem ```, sem tabelas. "
        "Use apenas parágrafos e listas simples com hífen (- item) se necessário.]"
    ),
}


def _run_agent_sync(
    user: Dict, message_text: str, chat_id: str, history: list, provider: str
) -> str:
    """Roda o mesmo pipeline MessageProcessor do chat normal (igual ao queue worker)."""
    from App.Core.Services.Common.Dependencies import COMPONENTS

    message_processor = COMPONENTS.get("message_processor")
    chat_manager = COMPONENTS.get("chat_manager")

    if not message_processor or not chat_manager:
        raise RuntimeError("MessageProcessor ou ChatManager não inicializado")

    # Injeta histórico do agent_messages numa sessão do ChatManager
    session_id = chat_manager.create_session()
    chat_session = chat_manager.get_session(session_id)
    if chat_session:
        chat_session.chat_id = chat_id
        chat_session.conversation_history.extend(history)

    # Instrução de formatação por canal
    fmt = _FORMAT_INSTRUCTIONS.get(provider, _FORMAT_INSTRUCTIONS["default"])
    user_message_with_fmt = message_text + fmt

    result = message_processor.process_message(
        job_id=str(uuid.uuid4()),
        user_message=user_message_with_fmt,
        agent_id="orchestrator-global",
        chat_id=chat_id,
        user_id=user["user_id"],
    )

    if hasattr(result, "response"):
        return result.response or ""
    if isinstance(result, dict):
        return result.get("response", "")
    return ""


# ========================================================================
# SETTINGS ENDPOINTS
# ========================================================================


@omni_settings_router.post("/telegram/link-code")
async def request_telegram_link_code(request: Request):
    try:
        auth = _get_auth_payload(request)
        user_id = auth["user_id"]
    except Exception:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    code = _generate_link_code(user_id)
    return {
        "code": code,
        "bot_username": os.environ.get("OMNI_TELEGRAM_BOT_USERNAME", "prox_bot"),
        "expires_in_minutes": _CODE_TTL_MINUTES,
    }


@omni_settings_router.delete("/telegram/unlink")
async def unlink_telegram(request: Request):
    try:
        auth = _get_auth_payload(request)
        user_id = auth["user_id"]
    except Exception:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    with DatabaseManager.get_session() as session:
        session.execute(
            text("UPDATE users SET telegram = NULL WHERE user_id = :uid"),
            {"uid": user_id},
        )
        session.commit()
    return {"status": "ok"}


@omni_settings_router.get("/telegram/status")
async def telegram_link_status(request: Request):
    try:
        auth = _get_auth_payload(request)
        user_id = auth["user_id"]
    except Exception:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    session = DatabaseManager.get_session()
    try:
        row = session.execute(
            text("SELECT telegram FROM users WHERE user_id = :uid LIMIT 1"),
            {"uid": user_id},
        ).fetchone()
        telegram_id = row.telegram if row else None
        return {"linked": bool(telegram_id), "telegram_id": telegram_id}
    finally:
        session.close()


# ========================================================================
# WEBHOOK RECEIVER
# ========================================================================


@omni_webhook_router.post("/{provider}")
async def handle_omni_message(provider: str, request: Request):
    payload = await request.json()

    sender_id = None
    message_text = None
    tg_chat_id = None

    sender_email = None

    try:
        if provider == "whatsapp":
            val = payload.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})
            messages = val.get("messages", [])
            if messages:
                sender_id = messages[0].get("from")
                message_text = messages[0].get("text", {}).get("body")
        elif provider == "telegram":
            msg = payload.get("message", {})
            sender_id = str(msg.get("from", {}).get("id", ""))
            tg_chat_id = msg.get("chat", {}).get("id")
            message_text = msg.get("text")
        elif provider == "instagram":
            messaging = payload.get("entry", [{}])[0].get("messaging", [{}])[0]
            sender_id = messaging.get("sender", {}).get("id")
            message_text = messaging.get("message", {}).get("text")
        elif provider == "email":
            # Resend inbound webhook payload
            sender_email = payload.get("from") or ""
            sender_id = sender_email
            message_text = payload.get("text") or payload.get("html") or ""
    except Exception:
        pass

    if not sender_id or not message_text:
        return {"status": "ignored"}

    # ── LINKING FLOW (Telegram) ────────────────────────────────────────
    if provider == "telegram" and re.match(r"^LINK-[A-Z0-9]{8}$", message_text.strip()):
        code = message_text.strip()
        user_id = _consume_link_code(code)
        if user_id:
            with DatabaseManager.get_session() as session:
                session.execute(
                    text("UPDATE users SET telegram = :tid WHERE user_id = :uid"),
                    {"tid": sender_id, "uid": user_id},
                )
                session.commit()
            info(
                f"[OMNI] Telegram vinculado: user_id={user_id}, telegram_id={sender_id}"
            )
            if tg_chat_id:
                await _send_telegram_reply(
                    tg_chat_id,
                    "✅ Conta vinculada com sucesso! Agora você pode conversar com seu assistente MD70 aqui.",
                )
            return {"status": "linked"}
        else:
            if tg_chat_id:
                await _send_telegram_reply(
                    tg_chat_id,
                    "❌ Código inválido ou expirado. Gere um novo código no MD70.",
                )
            return {"status": "invalid_code"}

    # ── AUTENTICAÇÃO ──────────────────────────────────────────────────
    user = find_user_by_channel(provider, sender_id)
    if not user:
        warning(f"[OMNI] Bloqueado: remetente {sender_id} não cadastrado no {provider}")
        if provider == "telegram" and tg_chat_id:
            await _send_telegram_reply(
                tg_chat_id,
                "⚠️ Seu Telegram não está vinculado ao MD70.\n\nAcesse Configurações > Omni-channel e gere um código de vinculação.",
            )
        return {
            "status": "unauthorized",
            "message": "Cadastre seu contato no MD70 para usar este canal.",
        }

    # ── PROCESSAMENTO ─────────────────────────────────────────────────
    try:
        chat_id = get_or_create_agent_chat(user["user_id"], provider, sender_id)
        history = load_agent_history(chat_id)

        # Salva mensagem do usuário em agent_messages
        save_agent_message(chat_id, "user", message_text)

        # Roda o mesmo pipeline do chat normal em thread (síncrono sem bloquear o loop)
        loop = asyncio.get_event_loop()
        response_text = await loop.run_in_executor(
            None, _run_agent_sync, user, message_text, chat_id, history, provider
        )

        if not response_text:
            response_text = "Desculpe, não consegui processar sua mensagem agora."

        # Salva resposta do agente em agent_messages
        save_agent_message(chat_id, "agent", response_text)

        # Responde no canal
        if provider == "telegram" and tg_chat_id:
            await _send_telegram_reply(tg_chat_id, response_text)
        elif provider == "email" and sender_email:
            subject = payload.get("subject", "Re: MD70")
            await _send_email_reply(sender_email, f"Re: {subject}", response_text)

        info(f"[OMNI] Resposta enviada para {user['email']} via {provider}")
        return {"status": "ok", "response": response_text}

    except Exception as e:
        log_error(f"[OMNI] Erro no processamento: {e}")
        import traceback

        log_error(traceback.format_exc())
        if provider == "telegram" and tg_chat_id:
            await _send_telegram_reply(
                tg_chat_id, "⚠️ Erro interno. Tente novamente em instantes."
            )
        elif provider == "email" and sender_email:
            await _send_email_reply(
                sender_email,
                "Re: MD70",
                "Ocorreu um erro interno. Por favor, tente novamente em instantes.",
            )
        return {"status": "error", "message": str(e)}


@omni_webhook_router.get("/{provider}")
async def verify_omni_webhook(provider: str, request: Request):
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get(
        "hub.verify_token"
    ) == os.environ.get("OMNI_VERIFY_TOKEN", "prox_default_token"):
        from fastapi.responses import Response

        return Response(content=params.get("hub.challenge"))
    return {"status": "error"}
