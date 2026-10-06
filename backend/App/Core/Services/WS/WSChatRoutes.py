"""
WebSocket endpoints para o chat (job status + active_job).
"""

import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from App.Core.Logs import debug, error
from App.Core.Services.WS.WSService import ws_authenticate

router = APIRouter()


@router.websocket("/api/ws/{chat_id}")
async def chat_ws_endpoint(websocket: WebSocket, chat_id: str):
    """
    Conexão WS por chat_id.
    Auth: cookie HTTPOnly primeiro, depois {"type":"auth","token":"..."}.
    Após auth envia auth_ok e, se houver job ativo, active_job.
    Mantém vivo com ping/pong a cada 30s.
    """
    await websocket.accept()

    user_id = await ws_authenticate(websocket, label=f"WS-CHAT/{chat_id}")
    if not user_id:
        debug(f"[WS-CHAT] Auth falhou para chat {chat_id} — encerrando")
        try:
            await websocket.close(code=1008, reason="Unauthorized")
        except Exception:
            pass
        return

    debug(f"[WS-CHAT] User {user_id} autenticado para chat {chat_id}")
    await websocket.send_json({"type": "auth_ok"})

    # Registrar no ChatWatcher (importado aqui para evitar circular)
    from App.Core.Services.Chat.ChatRoutes import chat_watcher

    await chat_watcher.connect(websocket, chat_id)

    # Enviar active_job se houver job em andamento
    try:
        from App.Features.Job import get_job_manager

        jm = get_job_manager()
        active = jm.find_active_job_by_chat_id(chat_id)
        if active and not active.is_finished():
            await websocket.send_json(
                {
                    "type": "active_job",
                    "job_id": active.job_id,
                    "status": active.status,
                }
            )
            debug(
                f"[WS-CHAT] active_job enviado: job={active.job_id} status={active.status}"
            )
    except Exception as e:
        debug(f"[WS-CHAT] Erro ao verificar active_job: {e}")

    # Loop principal — ping a cada 30s + handle mensagens do cliente
    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)

                if raw == "pong":
                    debug(f"[WS-CHAT] Pong de chat {chat_id}")
                    continue

                try:
                    msg = json.loads(raw)
                except Exception:
                    continue

                if msg.get("type") == "check_active_job":
                    try:
                        from App.Features.Job import get_job_manager as _gjm

                        _active = _gjm().find_active_job_by_chat_id(chat_id)
                        if _active and not _active.is_finished():
                            await websocket.send_json(
                                {
                                    "type": "active_job",
                                    "job_id": _active.job_id,
                                    "status": _active.status,
                                }
                            )
                            debug(
                                f"[WS-CHAT] check_active_job → job={_active.job_id} status={_active.status}"
                            )
                        else:
                            await websocket.send_json({"type": "no_active_job"})
                            debug(f"[WS-CHAT] check_active_job → no active job")
                    except Exception as _e:
                        debug(f"[WS-CHAT] Erro ao checar active_job: {_e}")

            except asyncio.TimeoutError:
                await websocket.send_text("ping")
    except WebSocketDisconnect:
        await chat_watcher.disconnect(websocket, chat_id)
    except Exception as e:
        error(f"[WS-CHAT] Erro na conexão {chat_id}: {e}")
        await chat_watcher.disconnect(websocket, chat_id)
