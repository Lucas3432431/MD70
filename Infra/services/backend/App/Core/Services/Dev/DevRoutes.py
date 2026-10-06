"""
Rotas de desenvolvimento/teste — acessíveis apenas diretamente na porta do backend.
O Nginx não expõe /dev/, então estas rotas nunca chegam em produção via gateway.
Registradas apenas quando ENVIRONMENT != "production".
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

dev_router = APIRouter(prefix="/dev", tags=["Dev"])


class BrowserToolRequest(BaseModel):
    user_id: str
    action: str
    url: Optional[str] = None
    x: Optional[int] = None
    y: Optional[int] = None
    text: Optional[str] = None
    selector: Optional[str] = None
    key: Optional[str] = None
    amount: Optional[int] = None
    domain: Optional[str] = None
    pages: int = 1


@dev_router.get("/browser-connections")
async def list_browser_connections():
    """Lista os user_ids com WebSocket ativo no ConnectionManager."""
    from App.Core.Services.WS.UserBrowserRouter import manager

    return {"connected_users": list(manager.active_connections.keys())}


@dev_router.post("/browser-tool")
async def run_browser_tool(req: BrowserToolRequest):
    """Dispara uma ação via UserBrowserTool para o browser do usuário conectado."""
    from App.Core.Services.WS.UserBrowserRouter import manager

    kwargs = {
        k: v
        for k, v in req.model_dump().items()
        if k not in ("user_id", "action") and v is not None
    }
    if req.pages != 1:
        kwargs["pages"] = req.pages

    result = await manager.send_and_wait(req.user_id, {"action": req.action, **kwargs})
    return result
