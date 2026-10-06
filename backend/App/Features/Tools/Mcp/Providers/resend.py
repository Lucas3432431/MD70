"""Provider Resend para MCP nativo."""
import json
from typing import Dict, Any, List

TOOL_DEFINITIONS: List[Dict] = [
    {
        "name": "mcp__resend__send_email",
        "description": "[RESEND] Envia um e-mail via Resend. Suporta HTML com CSS inline ou texto puro, múltiplos destinatários e attachments do chat.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": ["string", "array"],
                    "description": "Destinatário(s): 'email@x.com' ou ['a@x.com','b@x.com']",
                },
                "subject": {
                    "type": "string",
                    "description": "Assunto do e-mail",
                },
                "html": {
                    "type": "string",
                    "description": "Conteúdo HTML com CSS inline (use para layouts complexos)",
                },
                "text": {
                    "type": "string",
                    "description": "Conteúdo em texto puro (alternativa ao html)",
                },
                "from_name": {
                    "type": "string",
                    "description": "Nome do remetente (padrão: MD70). O domínio é fixo.",
                },
                "attachments": {
                    "type": "array",
                    "description": "Lista de attachment_ids do chat para anexar ao e-mail",
                },
            },
            "required": ["to", "subject"],
        },
    },
]


async def call(tool_name: str, args: Dict, env: Dict) -> Dict:
    from App.Features.Tools._resend_tool import execute_resend

    chat_id = env.get("_chat_id", "")
    user_id = env.get("_user_id", "")
    client_id = env.get("_client_id", "")

    result_json = execute_resend(
        args, chat_id or None, user_id or None, client_id or None
    )
    try:
        result = json.loads(result_json)
    except Exception:
        result = {"success": False, "error": result_json}

    if result.get("success"):
        return {"success": True, "content": result_json}
    return {"success": False, "error": result.get("error", "Erro ao enviar e-mail")}
