"""
Cliente HTTP para a API do 99Food.
Estrutura espelhada no IFoodClient para manter consistência.

Docs: https://developer.99app.com (pendente de acesso)
"""

import httpx
from dataclasses import dataclass
from typing import Literal

BASE_URL = "https://api.99app.com/food"  # placeholder — confirmar endpoint oficial


@dataclass
class NovenoveFoodCredentials:
    api_key: str
    store_id: str
    access_token: str | None = None


class NovenoveFoodClient:
    def __init__(self, credentials: NovenoveFoodCredentials):
        self.creds = credentials

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.creds.access_token or self.creds.api_key}",
            "Content-Type": "application/json",
        }

    # ── Catalog: Disponibilidade ──────────────────────────────────────────

    async def set_item_status(
        self,
        item_id: str,
        status: Literal["AVAILABLE", "UNAVAILABLE"],
    ) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.patch(
                f"{BASE_URL}/v1/stores/{self.creds.store_id}/items/{item_id}/status",
                headers=self._headers(),
                json={"status": status},
            )
            r.raise_for_status()
            return r.json() if r.content else {}

    # ── Catalog: Quantidade ───────────────────────────────────────────────

    async def set_item_inventory(self, item_id: str, amount: int) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.patch(
                f"{BASE_URL}/v1/stores/{self.creds.store_id}/items/{item_id}/inventory",
                headers=self._headers(),
                json={"quantity": amount},
            )
            r.raise_for_status()
            return r.json() if r.content else {}

    # ── Catalog: Preço ────────────────────────────────────────────────────

    async def set_item_price(self, item_id: str, price: float) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.patch(
                f"{BASE_URL}/v1/stores/{self.creds.store_id}/items/{item_id}/price",
                headers=self._headers(),
                json={"price": price},
            )
            r.raise_for_status()
            return r.json() if r.content else {}

    # ── Pedidos ───────────────────────────────────────────────────────────

    async def list_orders(self, status: str | None = None) -> list[dict]:
        params = {"status": status} if status else {}
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{BASE_URL}/v1/stores/{self.creds.store_id}/orders",
                headers=self._headers(),
                params=params,
            )
            r.raise_for_status()
            return r.json()

    async def get_order(self, order_id: str) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{BASE_URL}/v1/stores/{self.creds.store_id}/orders/{order_id}",
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()

    async def update_order_status(
        self,
        order_id: str,
        status: Literal["CONFIRMED", "DISPATCHED", "CANCELLED"],
        reason: str | None = None,
    ) -> dict:
        body: dict = {"status": status}
        if reason:
            body["reason"] = reason
        async with httpx.AsyncClient() as client:
            r = await client.patch(
                f"{BASE_URL}/v1/stores/{self.creds.store_id}/orders/{order_id}/status",
                headers=self._headers(),
                json=body,
            )
            r.raise_for_status()
            return r.json() if r.content else {}
