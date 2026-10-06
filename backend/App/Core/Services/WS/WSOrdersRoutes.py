# -*- coding: utf-8 -*-
"""
WebSocket endpoint para pedidos em tempo real.
Cada cliente (client_id) pode ter múltiplas conexões (ex: vários tablets).
Quando um pedido chega, o orders_watcher.broadcast() notifica todos.
"""

import asyncio
import json
from typing import Any, Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Logs import debug, error
from App.Core.Services.WS.WSService import ws_authenticate

router = APIRouter()


class OrdersWatcher:
    """Pool de conexões WS por client_id (suporta múltiplos tablets)."""

    def __init__(self):
        self.clients: Dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        self.clients.setdefault(client_id, []).append(websocket)
        debug(f"[WS-ORDERS] Conectado: client={client_id} ({len(self.clients[client_id])} conn)")

    async def disconnect(self, websocket: WebSocket, client_id: str):
        conns = self.clients.get(client_id, [])
        try:
            conns.remove(websocket)
        except ValueError:
            pass
        if not conns:
            self.clients.pop(client_id, None)
        debug(f"[WS-ORDERS] Desconectado: client={client_id} ({len(conns)} restante(s))")

    async def broadcast(self, client_id: str, data: Dict[str, Any]):
        conns = self.clients.get(client_id, [])
        if not conns:
            return
        dead = []
        for ws in conns:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            try:
                conns.remove(ws)
            except ValueError:
                pass
        debug(f"[WS-ORDERS] Broadcast client={client_id}: {data.get('type')} → {len(conns)} conn(s)")


orders_watcher = OrdersWatcher()


def _client_id_from_user(user_id: str) -> str | None:
    row = DatabaseManager.fetch_one(
        "SELECT client_id FROM users WHERE user_id = :uid LIMIT 1",
        {"uid": user_id},
    )
    return row.get("client_id") if row else None


@router.websocket("/api/ws/pdv-orders")
async def orders_ws_endpoint(websocket: WebSocket):
    """
    Conexão WS para receber pedidos em tempo real.
    Auth: cookie HTTPOnly primeiro, depois {"type":"auth","token":"..."}.
    Envia ping a cada 30s para manter vivo.
    """
    await websocket.accept()

    user_id = await ws_authenticate(websocket, label="WS-ORDERS")
    if not user_id:
        try:
            await websocket.close(code=1008, reason="Unauthorized")
        except Exception:
            pass
        return

    client_id = _client_id_from_user(user_id)
    if not client_id:
        try:
            await websocket.close(code=1008, reason="Client not found")
        except Exception:
            pass
        return

    await websocket.send_json({"type": "auth_ok", "client_id": client_id})
    await orders_watcher.connect(websocket, client_id)

    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if raw == "pong":
                    continue
                try:
                    msg = json.loads(raw)
                    if msg.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except Exception:
                    pass
            except asyncio.TimeoutError:
                await websocket.send_text("ping")
    except WebSocketDisconnect:
        await orders_watcher.disconnect(websocket, client_id)
    except Exception as e:
        error(f"[WS-ORDERS] Erro: {e}")
        await orders_watcher.disconnect(websocket, client_id)
