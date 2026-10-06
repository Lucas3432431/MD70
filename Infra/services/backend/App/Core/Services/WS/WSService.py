"""
Utilitários compartilhados para endpoints WebSocket.

Fornece autenticação padronizada: aceitar a conexão, tentar cookie
HTTPOnly primeiro e, se ausente, aguardar {"type": "auth", "token": "..."}
como primeira mensagem do front-end.
"""

import asyncio
import json
from typing import Optional

from fastapi import WebSocket

from App.Features.Auth import get_auth_service
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Logs import debug, warning

AUTH_TIMEOUT = 10.0


def resolve_user_id_from_token(token: str) -> Optional[str]:
    """Valida um JWT e retorna o user_id, ou None se inválido."""
    payload = get_auth_service().verify_token(token)
    if not payload:
        return None
    return payload.get("user_id") if isinstance(payload, dict) else str(payload)


def dev_user_id(websocket: WebSocket) -> Optional[str]:
    """Retorna user_id de dev bypass quando habilitado, ou None."""
    if not websocket.scope.get("dev_bypass_enabled"):
        return None
    uid = websocket.scope.get("dev_user_id")
    if not uid:
        res = DatabaseManager.fetch_one(
            "SELECT user_id FROM users WHERE client_id = '1' LIMIT 1", {}
        )
        uid = res.get("user_id") if res else "dev-user-1"
    return uid


async def ws_authenticate(websocket: WebSocket, label: str = "WS") -> Optional[str]:
    """
    Autentica uma conexão WebSocket já aceita.

    Ordem de tentativa:
      1. Cookie HTTPOnly `access_token`
      2. Mensagem JSON `{"type": "auth", "token": "..."}` (até AUTH_TIMEOUT s)
      3. Dev bypass (scope `dev_bypass_enabled`)

    Retorna user_id (str) se autenticado, None caso contrário.
    Não fecha a conexão — responsabilidade do chamador.
    """
    # 1. Dev bypass
    uid = dev_user_id(websocket)
    if uid:
        debug(f"[{label}] Dev bypass — user_id={uid}")
        return uid

    # 2. Cookie HTTPOnly
    try:
        token = websocket.cookies.get("access_token")
        if token:
            uid = resolve_user_id_from_token(token)
            if uid:
                debug(f"[{label}] Auth via cookie — user_id={uid}")
                return uid
    except Exception as e:
        debug(f"[{label}] Erro ao ler cookie: {e}")

    # 3. Primeira mensagem com token
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT)
        message = json.loads(raw)
        if message.get("type") == "auth":
            token = message.get("token", "")
            uid = resolve_user_id_from_token(token)
            if uid:
                debug(f"[{label}] Auth via mensagem — user_id={uid}")
                return uid
            else:
                warning(f"[{label}] Token inválido na mensagem auth")
        else:
            warning(f"[{label}] Primeira mensagem não é auth: {message.get('type')}")
    except asyncio.TimeoutError:
        warning(f"[{label}] Timeout aguardando auth ({AUTH_TIMEOUT}s)")
    except Exception as e:
        warning(f"[{label}] Erro ao processar mensagem auth: {e}")

    return None
