"""Utilitários compartilhados entre providers MCP."""
from typing import Optional
import httpx
from App.Core.Logs import error


class _TokenExpiredError(Exception):
    """Lançada quando o access_token expirou e o refresh também falhou.

    who="user"   → token OAuth do usuário expirado (reconectar em Integrações)
    who="system" → developer token do servidor inválido (problema de configuração)
    """

    def __init__(self, status: str = "", who: str = "user"):
        super().__init__(status)
        self.who = who


async def _refresh_access_token(
    client_id_oauth: str, client_secret: str, refresh_token: str
) -> Optional[str]:
    """Renova o access_token usando o refresh_token."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client_id_oauth,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            data = resp.json()
            return data.get("access_token")
    except Exception as e:
        error(f"[MCP-NATIVE] Erro ao renovar token: {e}")
        return None
