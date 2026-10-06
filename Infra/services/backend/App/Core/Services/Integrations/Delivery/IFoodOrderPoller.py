"""
Polling assíncrono de pedidos iFood — executa a cada 30s por loja autenticada.

Responsabilidades:
  1. Detecta transição de horário → abre/fecha loja no iFood via set_merchant_status
  2. Dentro do horário + WS online → poll de eventos e broadcast via orders_watcher
  3. Fora do horário → skip (loja já foi fechada na transição)

Fontes de horário (por prioridade):
  delivery_integrations.opening_hours  (horário específico iFood, configurado no card iFood)
  → se NULL, usa clients.opening_hours (horário geral do estabelecimento)
  → se ambos NULL, opera 24h

Condições para polling:
  - WS do PDV conectada (orders_watcher.clients[store_id] não vazio)
  - Dentro do horário de funcionamento iFood
"""

import asyncio
import json
import time
from datetime import datetime

from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Crunch.TablesSQL.DBCryptographyManager import DBCryptographyManager as Crypto
from App.Core.Logs import info, error, debug

POLL_INTERVAL = 30  # segundos

_NEW_ORDER_CODES = {"PLC"}
_STATUS_CODES    = {"CFM", "DSP", "CAN", "RTP", "CON"}


def _parse_auto_manage(ifood_hours_json: str | None, db_auto_manage) -> bool:
    """Lê auto_manage do JSON de horários ou da coluna dedicada. Default: True."""
    # Se o campo auto_manage foi salvo na própria coluna da tabela
    if db_auto_manage is not None:
        return bool(db_auto_manage)
    # Legado: auto_manage embutido no JSON de horários
    if ifood_hours_json:
        try:
            data = json.loads(ifood_hours_json)
            if "auto_manage" in data:
                return bool(data["auto_manage"])
        except Exception:
            pass
    return True


class IFoodOrderPoller:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self._running = False
        # Rastreia o último estado aberto/fechado por store_id
        # para detectar transições e chamar set_merchant_status
        self._store_open: dict[str, bool] = {}

    def start(self):
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._loop())
            info("[IFoodPoller] Iniciado — intervalo 30s")

    def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        info("[IFoodPoller] Parado")

    # ── Loop ─────────────────────────────────────────────────────────────

    async def _loop(self):
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                error(f"[IFoodPoller] Erro no loop: {e}")
            await asyncio.sleep(POLL_INTERVAL)

    async def _tick(self):
        rows = DatabaseManager.fetch_all(
            """SELECT di.store_id, di.access_token, di.refresh_token,
                      di.expires_at, di.opening_hours AS ifood_hours,
                      di.auto_manage,
                      c.opening_hours AS store_hours
               FROM delivery_integrations di
               LEFT JOIN clients c ON c.client_id = di.store_id
               WHERE di.platform = 'ifood'""",
            {},
        )
        for row in rows:
            store_id = str(row["store_id"])
            try:
                await self._process_store(store_id, row)
            except Exception as e:
                error(f"[IFoodPoller] Erro store={store_id}: {e}")

    # ── Por loja ──────────────────────────────────────────────────────────

    async def _process_store(self, store_id: str, row: dict):
        # auto_manage: se False, poller faz polling mas NÃO abre/fecha a loja
        auto_manage = _parse_auto_manage(row.get("ifood_hours"), row.get("auto_manage"))

        # Horário efetivo: iFood-specific > geral do estabelecimento > sempre aberto
        hours_json = row.get("ifood_hours") or row.get("store_hours")
        now_open   = self._is_within_hours(hours_json)
        was_open   = self._store_open.get(store_id)  # None = primeiro tick

        client = self._build_client(store_id, row)
        if client is None:
            return

        # ── Detecta transição de estado ───────────────────────────────
        if was_open is None:
            # Primeiro tick: só sincroniza estado, sem chamar API
            self._store_open[store_id] = now_open
        elif now_open and not was_open:
            self._store_open[store_id] = True
            if auto_manage:
                try:
                    await client.set_merchant_status(open=True)
                    info(f"[IFoodPoller] store={store_id} ABERTO no iFood")
                except Exception as e:
                    error(f"[IFoodPoller] Erro ao abrir store={store_id}: {e}")
        elif not now_open and was_open:
            self._store_open[store_id] = False
            if auto_manage:
                try:
                    await client.set_merchant_status(open=False)
                    info(f"[IFoodPoller] store={store_id} FECHADO no iFood")
                except Exception as e:
                    error(f"[IFoodPoller] Erro ao fechar store={store_id}: {e}")

        # ── Polling só se aberto + WS online ─────────────────────────
        if not now_open:
            debug(f"[IFoodPoller] store={store_id} fora do horário — skip poll")
            return

        if not self._is_ws_online(store_id):
            debug(f"[IFoodPoller] store={store_id} WS offline — skip poll")
            return

        await self._poll_events(store_id, client)

    # ── Poll de eventos ───────────────────────────────────────────────────

    async def _poll_events(self, store_id: str, client):
        events = await client.poll_events()
        if not events:
            return

        from App.Core.Services.WS.WSOrdersRoutes import orders_watcher

        event_ids: list[str] = []
        for event in events:
            eid = event.get("id")
            if eid:
                event_ids.append(eid)
            code     = event.get("code", "")
            order_id = event.get("orderId")

            if code in _NEW_ORDER_CODES and order_id:
                try:
                    order = await client.get_order(order_id)
                    await orders_watcher.broadcast(store_id, {
                        "type":     "new_order",
                        "platform": "ifood",
                        "order":    order,
                    })
                    info(f"[IFoodPoller] Novo pedido store={store_id} order={order_id}")
                except Exception as e:
                    error(f"[IFoodPoller] Erro ao buscar pedido {order_id}: {e}")

            elif code in _STATUS_CODES and order_id:
                await orders_watcher.broadcast(store_id, {
                    "type":     "order_status",
                    "platform": "ifood",
                    "orderId":  order_id,
                    "code":     code,
                })

        if event_ids:
            try:
                await client.acknowledge_events(event_ids)
                debug(f"[IFoodPoller] ACK {len(event_ids)} evento(s) store={store_id}")
            except Exception as e:
                error(f"[IFoodPoller] Erro ACK store={store_id}: {e}")

    # ── Helpers ───────────────────────────────────────────────────────────

    def _is_ws_online(self, store_id: str) -> bool:
        try:
            from App.Core.Services.WS.WSOrdersRoutes import orders_watcher
            return bool(orders_watcher.clients.get(store_id))
        except Exception:
            return False

    def _is_within_hours(self, hours_json: str | None) -> bool:
        """True se hora atual está dentro do horário configurado. None = sempre aberto."""
        if not hours_json:
            return True
        try:
            hours = json.loads(hours_json)
        except Exception:
            return True

        now = datetime.now()
        keys = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        day_cfg = hours.get(keys[now.weekday()], {})

        if not day_cfg.get("enabled", True):
            return False

        now_m = now.hour * 60 + now.minute

        def _in_range(open_str: str, close_str: str) -> bool:
            oh, om = map(int, open_str.split(":"))
            ch, cm = map(int, close_str.split(":"))
            return (oh * 60 + om) <= now_m <= (ch * 60 + cm)

        # Primeiro turno
        if _in_range(day_cfg.get("open", "00:00"), day_cfg.get("close", "23:59")):
            return True

        # Segundo turno (split)
        if day_cfg.get("split") and day_cfg.get("open2") and day_cfg.get("close2"):
            if _in_range(day_cfg["open2"], day_cfg["close2"]):
                return True

        return False

    def _build_client(self, store_id: str, row: dict):
        try:
            from App.Core.Services.Integrations.Delivery.DeliveryRoutes import _ifood_app_credentials
            from App.Core.Services.Integrations.Delivery.IFoodClient import IFoodClient, IFoodCredentials

            cid, csec = _ifood_app_credentials()
            expires_at = row.get("expires_at")
            if hasattr(expires_at, "timestamp"):
                expires_at = expires_at.timestamp()
            else:
                expires_at = float(expires_at or 0)

            return IFoodClient(IFoodCredentials(
                client_id=cid,
                client_secret=csec,
                merchant_id=store_id,
                access_token=Crypto.decrypt_field(row["access_token"]),
                refresh_token=Crypto.decrypt_field(row["refresh_token"]) if row.get("refresh_token") else None,
                expires_at=expires_at,
            ))
        except Exception as e:
            error(f"[IFoodPoller] Erro ao construir cliente store={store_id}: {e}")
            return None


ifood_order_poller = IFoodOrderPoller()
