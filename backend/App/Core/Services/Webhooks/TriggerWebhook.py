"""
Trigger Webhooks — recebe mensagens de canais externos e cria chats na plataforma.

URL: /webhook/trigger/{webhook_secret}/{provider}

Fluxo:
  1. Resolve webhook_secret → client_id + config do agente
  2. Verifica assinatura HMAC por provider
  3. Extrai sender_id, sender_name e texto do evento
  4. Cria ou reutiliza chat na tabela chats (source='trigger')
  5. Cria trigger_executions e enfileira no queue_manager
  6. Notifica sidebar via WebSocket (unseen_update)
"""

import hashlib
import hmac as _hmac
import json
import os
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import text

from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Logs import debug, error as log_error, info, warning
from App.Core.Settings.Settings import WEBHOOK_PREFIX

trigger_webhook_router = APIRouter(
    tags=["TriggerWebhooks"], prefix=f"{WEBHOOK_PREFIX}/trigger"
)

# ── Rate limiting (memória — per web_secret_id, 60 req/min) ──────────────────

_rate_windows: dict[str, deque] = defaultdict(deque)
_RATE_MAX = 60
_RATE_WINDOW = 60


def _check_rate_limit(key: str) -> bool:
    now = time.time()
    win = _rate_windows[key]
    while win and win[0] < now - _RATE_WINDOW:
        win.popleft()
    if len(win) >= _RATE_MAX:
        return False
    win.append(now)
    return True


# ── Tabelas on-demand ─────────────────────────────────────────────────────────

_TABLES_CREATED = False


def _ensure_tables():
    global _TABLES_CREATED
    if _TABLES_CREATED:
        return

    # Create trigger_executions table
    try:
        DatabaseManager.execute_query(
            """
            CREATE TABLE IF NOT EXISTS trigger_executions (
                id TEXT PRIMARY KEY NOT NULL,
                web_secret_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                chat_id TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                result_summary TEXT,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                finished_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """,
            {},
        )
    except Exception as e:
        debug(f"[TriggerWebhook] CREATE trigger_executions: {e}")
    try:
        DatabaseManager.execute_query(
            "CREATE INDEX IF NOT EXISTS idx_trigger_exec_secret ON trigger_executions (web_secret_id)",
            {},
        )
    except Exception as e:
        debug(f"[TriggerWebhook] CREATE INDEX secret: {e}")
    try:
        DatabaseManager.execute_query(
            "CREATE INDEX IF NOT EXISTS idx_trigger_exec_user ON trigger_executions (user_id)",
            {},
        )
    except Exception as e:
        debug(f"[TriggerWebhook] CREATE INDEX user: {e}")

    # Migrate webhook_secrets: add columns if missing — each in its own session
    existing = {
        row["name"]
        for row in (
            DatabaseManager.fetch_all("PRAGMA table_info(webhook_secrets)", {}) or []
        )
    }
    migrations = [
        (
            "status",
            "ALTER TABLE webhook_secrets ADD COLUMN status TEXT DEFAULT 'pending'",
        ),
        ("prompt", "ALTER TABLE webhook_secrets ADD COLUMN prompt TEXT"),
        (
            "autonomy_level",
            "ALTER TABLE webhook_secrets ADD COLUMN autonomy_level INTEGER DEFAULT 4",
        ),
        ("tools", "ALTER TABLE webhook_secrets ADD COLUMN tools TEXT DEFAULT '[]'"),
        (
            "last_received_at",
            "ALTER TABLE webhook_secrets ADD COLUMN last_received_at DATETIME",
        ),
        ("updated_at", "ALTER TABLE webhook_secrets ADD COLUMN updated_at DATETIME"),
    ]
    for col_name, col_sql in migrations:
        if col_name not in existing:
            try:
                DatabaseManager.execute_query(col_sql, {})
            except Exception as e:
                debug(f"[TriggerWebhook] Migration {col_name}: {e}")

    _TABLES_CREATED = True


# ── Lookup + status ───────────────────────────────────────────────────────────


def _resolve_secret(webhook_secret: str, provider: str) -> Optional[Dict]:
    row = DatabaseManager.fetch_one(
        "SELECT web_secret_id, client_id, prompt, autonomy_level, tools "
        "FROM webhook_secrets WHERE webhook_secret = :s AND provider = :p LIMIT 1",
        {"s": webhook_secret, "p": provider},
    )
    if not row:
        return None
    tools = row.get("tools") or "[]"
    return {
        "web_secret_id": str(row["web_secret_id"]),
        "client_id": str(row["client_id"]),
        "prompt": row.get("prompt") or "",
        "autonomy_level": row.get("autonomy_level") or 4,
        "tools": json.loads(tools) if isinstance(tools, str) else tools,
    }


def _mark_connected(webhook_secret: str, provider: str):
    with DatabaseManager.get_session() as s:
        s.execute(
            text(
                "UPDATE webhook_secrets SET status = 'connected', last_received_at = :now "
                "WHERE webhook_secret = :s AND provider = :p"
            ),
            {"now": datetime.utcnow(), "s": webhook_secret, "p": provider},
        )
        s.commit()


def _mark_lost(webhook_secret: str, provider: str):
    with DatabaseManager.get_session() as s:
        s.execute(
            text(
                "UPDATE webhook_secrets SET status = 'lost' WHERE webhook_secret = :s AND provider = :p"
            ),
            {"s": webhook_secret, "p": provider},
        )
        s.commit()


# ── Usuário do cliente ────────────────────────────────────────────────────────


def _get_client_user_id(client_id: str) -> Optional[str]:
    row = DatabaseManager.fetch_one(
        "SELECT user_id FROM users WHERE client_id = :cid LIMIT 1",
        {"cid": str(client_id)},
    )
    return str(row["user_id"]) if row else None


# ── Verificação de assinatura ─────────────────────────────────────────────────


def _verify_signature(
    provider: str, secret: str, body: bytes, request: Request
) -> bool:
    try:
        if provider in ("whatsapp", "instagram"):
            sig = request.headers.get("X-Hub-Signature-256", "")
            expected = (
                "sha256=" + _hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            )
            return _hmac.compare_digest(expected, sig)
        elif provider == "telegram":
            token_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            return _hmac.compare_digest(secret, token_header)
        elif provider == "slack":
            ts = request.headers.get("X-Slack-Request-Timestamp", "")
            sig = request.headers.get("X-Slack-Signature", "")
            base = f"v0:{ts}:{body.decode('utf-8', errors='replace')}"
            expected = (
                "v0="
                + _hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()
            )
            return _hmac.compare_digest(expected, sig)
        elif provider == "stripe":
            sig_header = request.headers.get("Stripe-Signature", "")
            parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
            ts_val = parts.get("t", "")
            v1 = parts.get("v1", "")
            payload_str = f"{ts_val}.{body.decode('utf-8', errors='replace')}"
            expected = _hmac.new(
                secret.encode(), payload_str.encode(), hashlib.sha256
            ).hexdigest()
            return _hmac.compare_digest(expected, v1)
        elif provider == "typeform":
            import base64

            sig_header = request.headers.get("Typeform-Signature", "")
            digest = _hmac.new(secret.encode(), body, hashlib.sha256).digest()
            expected = "sha256=" + base64.b64encode(digest).decode()
            return _hmac.compare_digest(expected, sig_header)
        elif provider == "resend":
            # Resend entrega via Svix — autenticação já garantida pelo token na URL
            return True
        else:
            token_header = request.headers.get("X-Webhook-Token", "")
            return _hmac.compare_digest(secret, token_header)
    except Exception as e:
        warning(f"[TRIGGER] Erro na verificação de assinatura ({provider}): {e}")
        return False


# ── Extração de payload por provider ─────────────────────────────────────────


def _extract_sender_id(provider: str, payload: dict) -> Optional[str]:
    try:
        if provider == "telegram":
            msg = payload.get("message") or payload.get("edited_message") or {}
            chat = msg.get("chat") or {}
            return str(chat.get("id") or (msg.get("from") or {}).get("id") or "")
        elif provider == "whatsapp":
            entry = (payload.get("entry") or [{}])[0]
            changes = (entry.get("changes") or [{}])[0]
            messages = changes.get("value", {}).get("messages") or []
            if messages:
                return str(messages[0].get("from", ""))
        elif provider == "instagram":
            entry = (payload.get("entry") or [{}])[0]
            sender = (entry.get("messaging") or [{}])[0].get("sender", {})
            return str(sender.get("id", ""))
        elif provider == "slack":
            event = payload.get("event") or {}
            user = event.get("user") or event.get("bot_id", "")
            channel = event.get("channel", "")
            return f"{user}_{channel}" if user else None
        elif provider == "resend":
            data = payload.get("data") or payload
            return str(data.get("from") or "")
    except Exception:
        pass
    return None


def _extract_sender_name(provider: str, payload: dict) -> Optional[str]:
    try:
        if provider == "resend":
            data = payload.get("data") or payload
            sender = str(data.get("from") or "")
            # "Nome <email@x.com>" → "Nome", ou só o email
            if "<" in sender:
                return sender.split("<")[0].strip()
            return sender
        elif provider == "telegram":
            msg = payload.get("message") or payload.get("edited_message") or {}
            frm = msg.get("from") or {}
            chat = msg.get("chat") or {}
            first = frm.get("first_name") or chat.get("first_name") or ""
            last = frm.get("last_name") or chat.get("last_name") or ""
            title = (
                frm.get("username") or chat.get("title") or chat.get("username") or ""
            )
            return f"{first} {last}".strip() or title or None
        elif provider == "whatsapp":
            entry = (payload.get("entry") or [{}])[0]
            changes = (entry.get("changes") or [{}])[0]
            contacts = changes.get("value", {}).get("contacts") or []
            if contacts:
                return (contacts[0].get("profile") or {}).get("name") or None
        elif provider == "slack":
            event = payload.get("event") or {}
            return event.get("user_name") or event.get("username") or None
    except Exception:
        pass
    return None


def _extract_event_summary(provider: str, payload: dict) -> str:
    try:
        if provider == "whatsapp":
            entry = (payload.get("entry") or [{}])[0]
            changes = (entry.get("changes") or [{}])[0]
            messages = changes.get("value", {}).get("messages") or []
            if messages:
                msg = messages[0]
                text_body = (msg.get("text") or {}).get("body", "[sem texto]")
                return f"Mensagem WhatsApp de {msg.get('from', '?')}: {text_body}"
        elif provider == "instagram":
            entry = (payload.get("entry") or [{}])[0]
            # DMs chegam em entry.messaging[]; outros eventos (comments, mentions) em entry.changes[]
            messaging = (entry.get("messaging") or [{}])[0]
            if messaging:
                sender_id = (messaging.get("sender") or {}).get("id", "?")
                text = (messaging.get("message") or {}).get("text", "[sem texto]")
                return f"Mensagem Instagram de {sender_id}: {text}"
            # Fallback para eventos de feed/story via changes[]
            changes = (entry.get("changes") or [{}])[0]
            value = changes.get("value", {})
            return f"Instagram {value.get('item', 'evento')}: {json.dumps(value)[:300]}"
        elif provider == "telegram":
            msg = payload.get("message") or payload.get("edited_message") or {}
            sender = (msg.get("from") or {}).get("first_name", "?")
            return f"Mensagem Telegram de {sender}: {msg.get('text', '[sem texto]')}"
        elif provider == "slack":
            if payload.get("type") == "url_verification":
                return "__slack_challenge__"
            event = payload.get("event") or {}
            return f"Slack {event.get('type', 'mensagem')} de {event.get('user', '?')}: {event.get('text', '[sem texto]')}"
        elif provider == "stripe":
            event_type = payload.get("type", "?")
            obj = (payload.get("data") or {}).get("object") or {}
            customer = obj.get("customer") or obj.get("email") or obj.get("id", "?")
            return f"Stripe {event_type} — cliente: {customer}"
        elif provider == "typeform":
            response = payload.get("form_response") or {}
            answers = response.get("answers") or []
            summary = "; ".join(
                f"{(a.get('field') or {}).get('ref', '?')}: "
                f"{a.get('text') or (a.get('choice') or {}).get('label', '')}"
                for a in answers[:5]
            )
            return f"Typeform {response.get('form_id', '?')} — {summary}"
        elif provider == "resend":
            # Svix envelope: { "type": "email.received", "data": { "from": ..., "subject": ..., "text": ... } }
            data = payload.get("data") or payload
            sender = str(data.get("from") or "?")
            subject = data.get("subject") or "(sem assunto)"
            body = data.get("text") or data.get("html") or ""
            # Strip HTML tags simply
            if data.get("html") and not data.get("text"):
                import re as _re

                body = _re.sub(r"<[^>]+>", "", body).strip()
            body_preview = body[:500] if body else ""
            return f"E-mail de {sender} — Assunto: {subject}\n\n{body_preview}"
    except Exception as exc:
        warning(f"[TRIGGER] Erro ao extrair summary ({provider}): {exc}")
    return f"Evento de {provider}: {json.dumps(payload)[:300]}"


# ── Prompt para o agente ──────────────────────────────────────────────────────

_AUTONOMY_LABELS = {
    1: "Nível 1 — Sem autonomia: apenas analise o evento e responda em texto.",
    2: "Nível 2 — Acesso a dados: pode consultar dados (leitura). Ações de escrita aguardam aprovação.",
    3: "Nível 3 — Autônomo: execute a ação completa, incluindo envios e escritas.",
    4: "Nível 4 — Total: autonomia máxima, execute tudo sem restrições.",
}

_CONCLUSION_BLOCK = """\
FERRAMENTAS DE CONCLUSÃO (chame exatamente uma delas para encerrar):
1. send — RESPONDER ao remetente externo: send(message="...")
2. cancel — FINALIZAR sem resposta: cancel(cancel=true, reason="...")
3. cancel com escalada — ESCALAR para revisão humana: cancel(cancel=true, escalate_to_human=true, reason="...")
⛔ NÃO escreva texto simples como resposta — ele NÃO chega ao remetente externo."""


def _build_agent_prompt(
    provider: str, autonomy_level: int, webhook_prompt: str, event_summary: str
) -> str:
    return (
        f"[TRIGGER: {provider.upper()}]\n"
        f"Evento recebido: {event_summary}\n\n"
        f"⚠️ Canal webhook externo — respostas em texto simples NÃO chegam ao remetente.\n\n"
        f"{_CONCLUSION_BLOCK}\n\n"
        f"{_AUTONOMY_LABELS.get(autonomy_level, _AUTONOMY_LABELS[4])}\n\n"
        f"Instrução base: {webhook_prompt}"
    )


def _build_display_json(
    provider: str, event_summary: str, raw_payload: dict = None
) -> str:
    sender = None
    message_text = event_summary
    extra = {}

    if provider == "resend" and raw_payload:
        data = raw_payload.get("data") or raw_payload
        sender = str(data.get("from") or "")
        subject = data.get("subject") or ""
        html_body = data.get("html") or ""
        body = data.get("text") or ""
        if not body and html_body:
            import re as _re

            body = _re.sub(r"<[^>]+>", "", html_body).strip()
        message_text = body or subject or event_summary
        extra = {"subject": subject, "to": data.get("to") or [], "html": html_body}
    else:
        try:
            if ": " in event_summary and " de " in event_summary.split(": ")[0]:
                parts = event_summary.split(": ", 1)
                message_text = parts[1]
                sender = parts[0].rsplit(" de ", 1)[1]
        except Exception:
            pass

    return json.dumps(
        {
            "type": "trigger_event",
            "provider": provider,
            "sender": sender,
            "message": message_text,
            **extra,
        },
        ensure_ascii=False,
    )


# ── Dispatch para fila ────────────────────────────────────────────────────────


def _dispatch(config: dict, provider: str, event_summary: str, raw_payload: dict):
    _ensure_tables()
    try:
        from App.Core.Services.Common.Dependencies import COMPONENTS
        from App.Core.Queues.MultiQueueManager import Message

        web_secret_id = config["web_secret_id"]
        client_id = config["client_id"]
        autonomy_level = config.get("autonomy_level", 4)
        webhook_prompt = config.get("prompt", "")
        now = datetime.utcnow()

        user_id = _get_client_user_id(client_id)
        if not user_id:
            warning(f"[TRIGGER] client_id={client_id} sem usuário associado")
            return

        execution_id = str(uuid.uuid4())
        DatabaseManager.execute_query(
            "INSERT INTO trigger_executions (id, web_secret_id, user_id, status, started_at, created_at) "
            "VALUES (:id, :wsid, :uid, 'running', :now, :now)",
            {
                "id": execution_id,
                "wsid": web_secret_id,
                "uid": user_id,
                "now": now.isoformat(),
            },
        )

        # Reutiliza ou cria chat para o mesmo remetente
        sender_id = _extract_sender_id(provider, raw_payload)
        sender_name = _extract_sender_name(provider, raw_payload)
        existing = None
        if sender_id:
            existing = DatabaseManager.fetch_one(
                "SELECT chat_id FROM chats WHERE trigger_id = :tid AND external_sender_id = :sid AND status = 'active' LIMIT 1",
                {"tid": web_secret_id, "sid": sender_id},
            )

        if existing:
            chat_id = existing["chat_id"]
            DatabaseManager.execute_query(
                "UPDATE chats SET seen=0, updated_at=:now, external_sender_name=COALESCE(:name, external_sender_name) WHERE chat_id=:id",
                {"now": now.isoformat(), "id": chat_id, "name": sender_name},
            )
            debug(f"[TRIGGER] Reutilizando chat={chat_id} para sender={sender_id}")
        else:
            chat_id = str(uuid.uuid4())
            DatabaseManager.execute_query(
                "INSERT INTO chats (chat_id, user_id, chat_name, connections, status, source, seen, "
                "trigger_id, external_sender_id, external_sender_name, created_at, updated_at) "
                "VALUES (:chat_id, :user_id, :chat_name, :connections, 'active', 'trigger', 0, "
                ":trigger_id, :ext_sid, :ext_sname, :now, :now)",
                {
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "chat_name": f"Webhook: {provider}",
                    "connections": "[]",
                    "trigger_id": web_secret_id,
                    "ext_sid": sender_id,
                    "ext_sname": sender_name,
                    "now": now.isoformat(),
                },
            )

        DatabaseManager.execute_query(
            "UPDATE trigger_executions SET chat_id = :chat_id WHERE id = :id",
            {"chat_id": chat_id, "id": execution_id},
        )

        # Notifica sidebar via WebSocket
        try:
            from App.Core.Services.Chat.ChatRoutes import notify_user_ws as _notify_ws

            counts = (
                DatabaseManager.fetch_one(
                    "SELECT COALESCE(SUM(CASE WHEN source='trigger' THEN 1 ELSE 0 END),0) AS triggers, "
                    "COALESCE(SUM(CASE WHEN source='scheduled' THEN 1 ELSE 0 END),0) AS scheduled "
                    "FROM chats WHERE user_id = :uid AND seen = 0",
                    {"uid": user_id},
                )
                or {}
            )
            _notify_ws(
                user_id,
                {
                    "type": "unseen_update",
                    "triggers": int(counts.get("triggers") or 0),
                    "scheduled": int(counts.get("scheduled") or 0),
                },
            )
        except Exception as ws_err:
            debug(f"[TRIGGER] Erro ao notificar WS: {ws_err}")

        content = _build_agent_prompt(
            provider, autonomy_level, webhook_prompt, event_summary
        )
        display_json = _build_display_json(provider, event_summary, raw_payload)

        queue_manager = COMPONENTS.get("queue_manager")
        if queue_manager:
            msg = Message(
                message_id=str(uuid.uuid4()),
                chat_id=chat_id,
                job_id=execution_id,
                user_id=user_id,
                role="user",
                content=content,
                agent_id="orchestrator-global",
                context={"trigger_display": display_json},
            )
            queue_manager.enqueue_message(msg)
            info(f"[TRIGGER] Enfileirado — provider={provider}, chat={chat_id}")
        else:
            warning(
                f"[TRIGGER] queue_manager indisponível para web_secret_id={web_secret_id}"
            )
            DatabaseManager.execute_query(
                "UPDATE trigger_executions SET status='failed', finished_at=:now WHERE id=:id",
                {"now": now.isoformat(), "id": execution_id},
            )

    except Exception as exc:
        log_error(f"[TRIGGER] Erro no dispatch: {exc}")


# ── Endpoints ─────────────────────────────────────────────────────────────────


@trigger_webhook_router.post("/{webhook_secret}/{provider}")
async def handle_trigger(webhook_secret: str, provider: str, request: Request):
    _ensure_tables()
    config = _resolve_secret(webhook_secret, provider)
    if not config:
        warning(f"[TRIGGER] webhook_secret inválido para provider={provider}")
        return {"status": "ignored"}

    if not _check_rate_limit(config["web_secret_id"]):
        return {"status": "ignored", "reason": "rate_limit"}

    body = await request.body()

    # Busca o webhook_secret original para verificação de assinatura
    row = DatabaseManager.fetch_one(
        "SELECT webhook_secret FROM webhook_secrets WHERE web_secret_id = :wsid LIMIT 1",
        {"wsid": config["web_secret_id"]},
    )
    signing_secret = row["webhook_secret"] if row else webhook_secret

    if not _verify_signature(provider, signing_secret, body, request):
        warning(f"[TRIGGER] Assinatura inválida — provider={provider}")
        return {"status": "ignored", "reason": "invalid_signature"}

    try:
        payload: dict[str, Any] = json.loads(body) if body else {}
    except Exception:
        payload = {}

    # Slack challenge
    if provider == "slack" and payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    event_summary = _extract_event_summary(provider, payload)
    try:
        _mark_connected(webhook_secret, provider)
    except Exception as _e:
        debug(f"[TRIGGER] _mark_connected falhou: {_e}")

    import threading

    threading.Thread(
        target=_dispatch,
        args=(config, provider, event_summary, payload),
        daemon=True,
    ).start()

    return {"received": True}


@trigger_webhook_router.get("/{webhook_secret}/{provider}")
async def verify_trigger_webhook(webhook_secret: str, provider: str, request: Request):
    """Verificação GET do Meta (WhatsApp/Instagram hub.challenge)."""
    _ensure_tables()
    if not _resolve_secret(webhook_secret, provider):
        return {"status": "error"}

    params = request.query_params
    verify_token = os.environ.get("OMNI_VERIFY_TOKEN", "prox_default_token")
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == verify_token
    ):
        _mark_connected(webhook_secret, provider)
        return PlainTextResponse(params.get("hub.challenge", ""))
    return {"status": "error"}


__all__ = ["trigger_webhook_router"]
