"""Provider Gmail para MCP nativo."""
from typing import Dict, Any, List
import httpx

from ._shared import _TokenExpiredError, _refresh_access_token

TOOL_DEFINITIONS: List[Dict] = [
    {
        "name": "mcp__gmail__list_emails",
        "description": "[GMAIL] Lista e-mails recentes da caixa de entrada.",
        "parameters": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Número máximo de e-mails (padrão 10)",
                },
                "query": {
                    "type": "string",
                    "description": "Filtro de busca (ex: 'from:alguem@gmail.com')",
                },
            },
        },
    },
    {
        "name": "mcp__gmail__send_email",
        "description": "[GMAIL] Envia um e-mail pelo Gmail do usuário.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Destinatário"},
                "subject": {"type": "string", "description": "Assunto"},
                "body": {
                    "type": "string",
                    "description": "Corpo do e-mail (texto ou HTML)",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "mcp__gmail__read_email",
        "description": "[GMAIL] Lê o conteúdo completo de um e-mail pelo ID (use list_emails para obter IDs).",
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "ID do e-mail"},
            },
            "required": ["message_id"],
        },
    },
]


async def call(tool_name: str, args: Dict, env: Dict) -> Dict:
    import base64
    from email.mime.text import MIMEText

    access_token = env.get("GMAIL_ACCESS_TOKEN", "")
    refresh_token = env.get("GMAIL_REFRESH_TOKEN", "")
    client_id_oauth = env.get("GMAIL_CLIENT_ID", "")
    client_secret = env.get("GMAIL_CLIENT_SECRET", "")

    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient(timeout=15.0) as http:

        async def _refresh_and_retry(req_fn):
            resp = await req_fn(headers)
            if resp.status_code == 401 and refresh_token:
                new_token = await _refresh_access_token(
                    client_id_oauth, client_secret, refresh_token
                )
                if new_token:
                    headers["Authorization"] = f"Bearer {new_token}"
                    resp = await req_fn(headers)
            if resp.status_code in (401, 403):
                raise _TokenExpiredError(str(resp.status_code))
            return resp

        if tool_name == "list_emails":
            params = {
                "maxResults": args.get("max_results", 10),
                "q": args.get("query", ""),
            }
            resp = await _refresh_and_retry(
                lambda h: http.get(
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                    headers=h,
                    params=params,
                )
            )
            messages = resp.json().get("messages", [])
            lines = []
            for msg in messages[:5]:
                detail = await _refresh_and_retry(
                    lambda h: http.get(
                        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
                        headers=h,
                        params={
                            "format": "metadata",
                            "metadataHeaders": ["Subject", "From", "Date"],
                        },
                    )
                )
                hdrs = {
                    h["name"]: h["value"]
                    for h in detail.json().get("payload", {}).get("headers", [])
                }
                lines.append(
                    f"{hdrs.get('Date','')} | {hdrs.get('From','')} | {hdrs.get('Subject','')}"
                )
            return {
                "success": True,
                "content": f"{len(messages)} e-mail(s):\n" + "\n".join(lines),
            }

        elif tool_name == "send_email":
            msg = MIMEText(args["body"])
            msg["to"] = args["to"]
            msg["subject"] = args["subject"]
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            resp = await _refresh_and_retry(
                lambda h: http.post(
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                    headers={**h, "Content-Type": "application/json"},
                    json={"raw": raw},
                )
            )
            return {"success": True, "content": f"E-mail enviado para {args['to']}"}

        elif tool_name == "read_email":
            message_id = args.get("message_id")
            resp = await _refresh_and_retry(
                lambda h: http.get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
                    headers=h,
                    params={"format": "full"},
                )
            )
            data = resp.json()
            if resp.status_code != 200:
                return {
                    "success": False,
                    "error": data.get("error", {}).get(
                        "message", str(resp.status_code)
                    ),
                }

            payload = data.get("payload", {})
            hdrs = {h["name"]: h["value"] for h in payload.get("headers", [])}

            def _extract_body(part):
                mime = part.get("mimeType", "")
                body_data = part.get("body", {}).get("data", "")
                if mime == "text/plain" and body_data:
                    return base64.urlsafe_b64decode(body_data + "==").decode(
                        "utf-8", errors="replace"
                    )
                for p in part.get("parts", []):
                    result = _extract_body(p)
                    if result:
                        return result
                return ""

            body_text = _extract_body(payload)
            return {
                "success": True,
                "content": (
                    f"De: {hdrs.get('From','')}\n"
                    f"Para: {hdrs.get('To','')}\n"
                    f"Assunto: {hdrs.get('Subject','')}\n"
                    f"Data: {hdrs.get('Date','')}\n"
                    f"---\n{body_text[:4000]}"
                ),
            }

    return {"success": False, "error": "Ferramenta não reconhecida"}
