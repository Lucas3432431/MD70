"""
ToolResponseRegistry - Armazenamento temporário de respostas de ferramentas (tool calls).
Módulo isolado para evitar importações circulares.
"""

from typing import Dict, Any, Optional
from App.Core.Logs import debug, error

_tool_call_responses = {}
LOG_PREFIX = "[ToolRegistry]"


def register_tool_call_response(chat_id: str, message_id: str, content: str) -> bool:
    try:
        key = f"{chat_id}:{message_id}"
        _tool_call_responses[key] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "content": content,
        }
        debug(f"{LOG_PREFIX} Tool call response registrada: {key}")
        return True
    except Exception as e:
        error(f"{LOG_PREFIX} Erro ao registrar tool call response: {e}")
        return False


def get_tool_call_response(chat_id: str, message_id: str) -> Optional[Dict[str, Any]]:
    key = f"{chat_id}:{message_id}"
    response = _tool_call_responses.get(key)
    if response:
        del _tool_call_responses[key]
        debug(f"{LOG_PREFIX} Tool call response recuperada: {key}")
    return response
