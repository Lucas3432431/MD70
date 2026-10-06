from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
import asyncio
from typing import Dict, Optional

from App.Core.Settings.Settings import GLOBAL_CONFIG
from App.Core.Logs import debug, info, warning, error
from App.Core.Services.WS.WSService import ws_authenticate

router = APIRouter()

PING_INTERVAL = 25.0  # segundos sem mensagem antes de enviar ping de verificação

# Loop principal do FastAPI — capturado quando o primeiro WS conecta.
_main_loop: Optional[asyncio.AbstractEventLoop] = None


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.pending_responses: Dict[str, asyncio.Future] = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        global _main_loop
        _main_loop = asyncio.get_running_loop()
        # Fecha conexão anterior do mesmo usuário se existir
        old = self.active_connections.get(user_id)
        if old is not None and old is not websocket:
            try:
                await old.close()
            except Exception:
                pass
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: str):
        self.active_connections.pop(user_id, None)

    async def send_and_wait(self, user_id: str, payload: dict, timeout: float = 45.0):
        if user_id not in self.active_connections:
            return {"error": f"User {user_id} browser not connected"}

        loop = asyncio.get_running_loop()
        cmd_id = f"sf_{loop.time()}"
        payload["cmd_id"] = cmd_id

        future = loop.create_future()
        self.pending_responses[cmd_id] = future

        try:
            await self.active_connections[user_id].send_text(json.dumps(payload))
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return {"error": "Timeout waiting for browser response"}
        except Exception as e:
            self.disconnect(user_id)
            return {"error": str(e)}
        finally:
            self.pending_responses.pop(cmd_id, None)

    async def send_signal(self, user_id: str, payload: dict):
        """Envia mensagem fire-and-forget para o browser do usuário."""
        if user_id not in self.active_connections:
            return
        try:
            await self.active_connections[user_id].send_text(json.dumps(payload))
        except Exception:
            self.disconnect(user_id)

    def send_signal_sync(self, user_id: str, payload: dict):
        """Versão síncrona de send_signal para threads sem event loop."""
        if _main_loop is None or not _main_loop.is_running():
            return
        if user_id not in self.active_connections:
            return
        asyncio.run_coroutine_threadsafe(self.send_signal(user_id, payload), _main_loop)

    def send_and_wait_sync(
        self, user_id: str, payload: dict, timeout: float = 50.0
    ) -> dict:
        """Versão síncrona para chamar de threads sem event loop (AnyIO worker)."""
        if _main_loop is None or not _main_loop.is_running():
            return {
                "success": False,
                "error": "Browser do usuário não está conectado. Peça ao usuário que instale/ative a extensão MD70 e acesse o app.",
            }
        if user_id not in self.active_connections:
            return {
                "success": False,
                "error": "Browser do usuário não está conectado. Peça ao usuário que instale/ative a extensão MD70 e acesse o app.",
            }
        future = asyncio.run_coroutine_threadsafe(
            self.send_and_wait(user_id, payload, timeout), _main_loop
        )
        try:
            return future.result(
                timeout=timeout + 5.0
            )  # margem acima do asyncio timeout interno
        except TimeoutError:
            return {"success": False, "error": "Timeout waiting for browser response"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def resolve_command(self, cmd_id: str, response: dict):
        if cmd_id in self.pending_responses:
            self.pending_responses[cmd_id].set_result(response)

    async def ping_all(self):
        """Envia ping JSON para todas as conexões e remove as mortas."""
        dead = []
        for uid, ws in list(self.active_connections.items()):
            try:
                await ws.send_text(json.dumps({"type": "ping"}))
            except Exception:
                dead.append(uid)
        for uid in dead:
            self.disconnect(uid)
            warning(f"[BROWSER-AGENT] Conexão morta removida no ping: {uid}")


manager = ConnectionManager()


@router.websocket("/ws/agent")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    user_id = await ws_authenticate(websocket, label="BROWSER-AGENT")
    if not user_id:
        try:
            await websocket.close(code=1008, reason="Unauthorized")
        except Exception:
            pass
        warning("[BROWSER-AGENT] Conexão recusada: auth falhou.")
        return

    await manager.connect(user_id, websocket)
    await websocket.send_text(json.dumps({"type": "auth_ok"}))
    info(f"[BROWSER-AGENT] User {user_id} autenticado e conectado.")

    try:
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(), timeout=PING_INTERVAL
                )
            except asyncio.TimeoutError:
                # Nenhuma mensagem em PING_INTERVAL segundos — verifica se está vivo
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    # Conexão morta — sai do loop
                    break
                continue

            message = json.loads(data)

            if message.get("type") == "pong":
                continue  # Resposta ao ping — conexão confirmada viva

            if "cmd_id" in message:
                manager.resolve_command(message["cmd_id"], message)
            elif message.get("type") == "cancel":
                info(f"[BROWSER-AGENT] User {user_id} cancelou a execução.")
                try:
                    from App.Features.Job.Singleton import get_job_manager
                    from App.Core.Services.Common.Dependencies import COMPONENTS

                    _job_manager = get_job_manager()
                    _job = _job_manager.find_active_job_by_user_id(user_id)
                    if _job:
                        _job_manager.cancel_job(_job.job_id)
                        _mp = COMPONENTS.get("message_processor")
                        if _mp:
                            _mp.mark_job_cancelled(_job.chat_id, _job.job_id)
                        info(
                            f"[BROWSER-AGENT] Job {_job.job_id} cancelado via WS para user {user_id}."
                        )
                except Exception as _ce:
                    error(f"[BROWSER-AGENT] Erro ao cancelar job via WS: {_ce}")
            else:
                debug(
                    f"[BROWSER-AGENT] Msg de {user_id}: {message.get('type') or message.get('action')}"
                )

    except WebSocketDisconnect:
        info(f"[BROWSER-AGENT] User {user_id} desconectado.")
    finally:
        manager.disconnect(user_id)
