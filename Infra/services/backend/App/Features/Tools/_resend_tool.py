"""
_resend_tool.py — Tool `resend`
Envia e-mails via Resend API. Lê credenciais da integração do usuário (provider=resend).
Fallback para RESEND_API_KEY global se não houver integração configurada.
"""

import base64
import json
import logging
from pathlib import Path
from typing import Optional

import httpx

_RESEND_URL = "https://api.resend.com/emails"


def execute_resend(args: dict, chat_id: Optional[str], user_id, client_id=None) -> str:
    api_key, email_domain = _get_credentials(client_id)

    if not api_key:
        return json.dumps(
            {
                "success": False,
                "error": (
                    "Integração Resend não configurada. "
                    "Adicione a integração em Configurações → Integrações → Resend."
                ),
            },
            ensure_ascii=False,
        )

    from_name = (args.get("from_name") or "MD70").strip()
    from_email = f"{from_name} <noreply@{email_domain}>"

    to_raw = args.get("to") or args.get("recipient") or ""
    to: list[str] = [to_raw] if isinstance(to_raw, str) else list(to_raw)
    to = [t.strip() for t in to if t.strip()]
    if not to:
        return json.dumps(
            {"success": False, "error": "Campo 'to' é obrigatório"}, ensure_ascii=False
        )

    subject = (args.get("subject") or "").strip()
    if not subject:
        return json.dumps(
            {"success": False, "error": "Campo 'subject' é obrigatório"},
            ensure_ascii=False,
        )

    html_body = args.get("html") or ""
    text_body = args.get("text") or ""
    if not html_body and not text_body:
        return json.dumps(
            {
                "success": False,
                "error": "Forneça 'html' ou 'text' com o conteúdo do e-mail",
            },
            ensure_ascii=False,
        )

    payload: dict = {"from": from_email, "to": to, "subject": subject}
    if html_body:
        payload["html"] = html_body
    if text_body:
        payload["text"] = text_body

    attachment_ids = args.get("attachments") or args.get("attachment_ids") or []
    if isinstance(attachment_ids, str):
        attachment_ids = [attachment_ids]
    if attachment_ids and chat_id:
        resend_attachments = _load_attachments(attachment_ids, chat_id)
        if resend_attachments:
            payload["attachments"] = resend_attachments

    try:
        resp = httpx.post(
            _RESEND_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            return json.dumps(
                {
                    "success": True,
                    "email_id": data.get("id"),
                    "to": to,
                    "subject": subject,
                    "from": from_email,
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "success": False,
                "error": f"Resend retornou {resp.status_code}: {resp.text[:500]}",
            },
            ensure_ascii=False,
        )
    except Exception as e:
        logging.error(f"[resend_tool] Erro ao enviar: {e}")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def _get_credentials(client_id) -> tuple[str, str]:
    """Lê API key e domínio da integração do usuário. Fallback para settings globais."""
    from App.Core.Settings.Settings import RESEND_API_KEY, RESEND_EMAIL_DOMAIN

    if not client_id:
        return RESEND_API_KEY or "", RESEND_EMAIL_DOMAIN or "prox.app.br"

    try:
        from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
        from App.Core.Crunch.TablesSQL.DBCryptographyManager import (
            DBCryptographyManager,
        )

        row = DatabaseManager.fetch_one(
            "SELECT env_vars FROM integrations_mcp WHERE client_id = :cid AND provider = 'resend' "
            "AND is_active = 1 ORDER BY created_at DESC LIMIT 1",
            {"cid": str(client_id)},
        )
        if row and row.get("env_vars"):
            raw = (
                json.loads(row["env_vars"])
                if isinstance(row["env_vars"], str)
                else row["env_vars"]
            )
            if isinstance(raw, dict) and "_enc" in raw:
                decrypted = DBCryptographyManager.decrypt_field(raw["_enc"])
                env = json.loads(decrypted) if decrypted else {}
            else:
                env = raw if isinstance(raw, dict) else {}
            api_key = env.get("RESEND_API_KEY", "").strip()
            domain = (
                env.get("RESEND_EMAIL_DOMAIN", "").strip()
                or RESEND_EMAIL_DOMAIN
                or "prox.app.br"
            )
            if api_key:
                return api_key, domain
    except Exception as e:
        logging.warning(f"[resend_tool] Erro ao ler integração: {e}")

    return RESEND_API_KEY or "", RESEND_EMAIL_DOMAIN or "prox.app.br"


def _load_attachments(attachment_ids: list, chat_id: str) -> list:
    from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
    from App.Core.Crunch.Storage.StorageManager import StorageManager

    result = []
    for aid in attachment_ids:
        try:
            row = DatabaseManager.fetch_one(
                "SELECT file_name, storage_path, storage_env FROM attachments "
                "WHERE attachment_id = :aid AND chat_id = :cid AND deleted_at IS NULL",
                {"aid": aid, "cid": chat_id},
            )
            if not row:
                continue
            storage_path = row.get("storage_path")
            storage_env = row.get("storage_env", "local")
            file_path = (
                StorageManager.PROJECT_ROOT / storage_path
                if storage_env == "local" and not str(storage_path).startswith("/")
                else Path(storage_path)
            )
            if not file_path.exists():
                logging.warning(f"[resend_tool] attachment não encontrado: {file_path}")
                continue
            content = base64.b64encode(file_path.read_bytes()).decode()
            result.append({"filename": row.get("file_name") or aid, "content": content})
        except Exception as e:
            logging.warning(f"[resend_tool] erro ao carregar attachment {aid}: {e}")
    return result
