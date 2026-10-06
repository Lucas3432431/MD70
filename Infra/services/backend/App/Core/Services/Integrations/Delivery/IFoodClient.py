"""
Cliente HTTP para a API do iFood — fluxo distribuído (por merchant).

Fluxo de autorização (fazer uma vez por loja):
  1. MD70 chama get_user_code() → recebe userCode + authorizationCodeVerifier
  2. MD70 exibe userCode e verificationUrl para o dono da loja
  3. Dono entra no Portal do Parceiro, insere o userCode e autoriza
  4. Dono recebe um authorizationCode e informa ao MD70
  5. MD70 chama authenticate_merchant(authorizationCode, authorizationCodeVerifier)
  6. MD70 armazena access_token + refresh_token no banco por store_id

Tempos de expiração (usar sempre o expiresIn da resposta — podem mudar):
  userCode:           600s  (10 min)
  authorizationCode:  300s  (5 min)
  access_token:       21600s (6 horas)
  refresh_token:      604800s (168 horas / 7 dias)

Docs: https://developer.ifood.com.br/en-US/docs/references
"""

import time
import httpx
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

BASE_URL = "https://merchant-api.ifood.com.br"
AUTH_URL = "https://merchant-api.ifood.com.br/authentication/v1.0/oauth/token"
USER_CODE_URL = "https://merchant-api.ifood.com.br/authentication/v1.0/oauth/userCode"


@dataclass
class IFoodCredentials:
    client_id: str
    client_secret: str
    merchant_id: str
    access_token: str | None = None
    refresh_token: str | None = None
    expires_at: float = field(default=0.0)  # unix timestamp


class IFoodClient:
    def __init__(self, credentials: IFoodCredentials):
        self.creds = credentials

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.creds.access_token}",
            "Content-Type": "application/json",
            "accept": "application/json",
        }

    def _is_token_expired(self) -> bool:
        """Considera expirado 5 min antes do prazo real para evitar janelas de erro."""
        return time.time() >= (self.creds.expires_at - 300)

    def _save_token_response(self, data: dict) -> None:
        self.creds.access_token = data["accessToken"]
        if "refreshToken" in data:
            self.creds.refresh_token = data["refreshToken"]
        expires_in = data.get("expiresIn", 21600)  # fallback 6h
        self.creds.expires_at = time.time() + expires_in

    # ── Auth: Fluxo Distribuído ───────────────────────────────────────────

    async def get_user_code(self) -> dict:
        """
        Passo 1 — Gera o userCode que o dono da loja vai inserir no Portal do Parceiro.

        Retorna:
          userCode               → exibir ao dono (ex: "HJLX-LPSQ")
          authorizationCodeVerifier → guardar no banco, necessário no passo 5
          verificationUrl        → URL do Portal do Parceiro (exibir ao dono)
          verificationUrlComplete → URL completa com o código (útil para QR/link)
          expiresIn              → segundos até expirar (600s = 10 min)
        """
        async with httpx.AsyncClient() as client:
            r = await client.post(
                USER_CODE_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={"clientId": self.creds.client_id},
            )
            r.raise_for_status()
            return r.json()

    async def authenticate_merchant(
        self, authorization_code: str, authorization_code_verifier: str
    ) -> str:
        """
        Passo 5 — Troca o authorizationCode (do dono) + authorizationCodeVerifier
        (gerado no passo 1) por access_token + refresh_token.

        authorizationCode expira em 5 min — executar imediatamente após receber do dono.
        """
        async with httpx.AsyncClient() as client:
            r = await client.post(
                AUTH_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grantType": "authorization_code",
                    "clientId": self.creds.client_id,
                    "clientSecret": self.creds.client_secret,
                    "authorizationCode": authorization_code,
                    "authorizationCodeVerifier": authorization_code_verifier,
                },
            )
            r.raise_for_status()
            self._save_token_response(r.json())
            return self.creds.access_token

    async def refresh_access_token(self) -> str:
        """
        Renova o access_token usando o refresh_token (válido por 168h).
        Se o refresh_token também expirou, é necessário novo fluxo de authorization_code.
        Chamar quando receber status 401 ou quando _is_token_expired() for True.
        """
        if not self.creds.refresh_token:
            raise ValueError("refresh_token ausente — iniciar novo fluxo de autenticação")
        async with httpx.AsyncClient() as client:
            r = await client.post(
                AUTH_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grantType": "refresh_token",
                    "clientId": self.creds.client_id,
                    "clientSecret": self.creds.client_secret,
                    "refreshToken": self.creds.refresh_token,
                },
            )
            r.raise_for_status()
            self._save_token_response(r.json())
            return self.creds.access_token

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """
        Wrapper com renovação automática de token.
        Renova preventivamente se próximo da expiração ou após receber 401.
        """
        if self._is_token_expired():
            await self.refresh_access_token()

        async with httpx.AsyncClient() as client:
            r = await client.request(
                method, f"{BASE_URL}{path}", headers=self._headers(), **kwargs
            )
            if r.status_code == 401:
                await self.refresh_access_token()
                r = await client.request(
                    method, f"{BASE_URL}{path}", headers=self._headers(), **kwargs
                )
            r.raise_for_status()
            return r

    # ── Catalog: Catálogos ────────────────────────────────────────────────

    async def list_catalogs(self) -> list[dict]:
        r = await self._request("GET", f"/catalog/v2.0/merchants/{self.creds.merchant_id}/catalogs")
        return r.json() if r.content else []

    # ── Catalog: Categorias ───────────────────────────────────────────────

    async def list_categories(self, include_items: bool = False) -> list[dict]:
        params = {"include_items": "true"} if include_items else None
        r = await self._request(
            "GET",
            f"/catalog/v2.0/merchants/{self.creds.merchant_id}/categories",
            params=params,
        )
        return r.json() if r.content else []

    async def create_category(self, name: str, status: str = "AVAILABLE", template: str = "DEFAULT") -> dict:
        r = await self._request(
            "POST",
            f"/catalog/v2.0/merchants/{self.creds.merchant_id}/categories",
            json={"name": name, "status": status, "template": template},
        )
        return r.json()

    # ── Catalog: Itens ────────────────────────────────────────────────────

    async def upsert_item(self, item: dict, products: list[dict],
                          option_groups: list[dict] | None = None,
                          options: list[dict] | None = None) -> dict:
        """PUT — cria ou atualiza item completo. IDs existentes = update."""
        r = await self._request(
            "PUT",
            f"/catalog/v2.0/merchants/{self.creds.merchant_id}/items",
            json={
                "item": item,
                "products": products,
                "optionGroups": option_groups or [],
                "options": options or [],
            },
        )
        return r.json() if r.content else {}

    async def list_items_in_category(self, category_id: str) -> list[dict]:
        r = await self._request(
            "GET",
            f"/catalog/v2.0/merchants/{self.creds.merchant_id}/categories/{category_id}/items",
        )
        return r.json() if r.content else []

    async def get_item(self, item_id: str) -> dict:
        r = await self._request(
            "GET",
            f"/catalog/v2.0/merchants/{self.creds.merchant_id}/items/{item_id}/flat",
        )
        return r.json()

    async def list_sellable_items(self, catalog_id: str) -> list[dict]:
        r = await self._request(
            "GET",
            f"/catalog/v2.0/merchants/{self.creds.merchant_id}/catalogs/{catalog_id}/sellableItems",
        )
        return r.json() if r.content else []

    async def list_unsellable_items(self, catalog_id: str) -> list[dict]:
        r = await self._request(
            "GET",
            f"/catalog/v2.0/merchants/{self.creds.merchant_id}/catalogs/{catalog_id}/unsellableItems",
        )
        return r.json() if r.content else []

    async def set_item_status(
        self,
        item_id: str,
        status: Literal["AVAILABLE", "UNAVAILABLE"],
        status_by_catalog: list[dict] | None = None,
    ) -> dict:
        payload: dict = {"itemId": item_id, "status": status}
        if status_by_catalog:
            payload["statusByCatalog"] = status_by_catalog
        r = await self._request(
            "PATCH",
            f"/catalog/v2.0/merchants/{self.creds.merchant_id}/items/status",
            json=payload,
        )
        return r.json() if r.content else {}

    async def set_item_price(
        self,
        item_id: str,
        price: float,
        price_by_catalog: list[dict] | None = None,
    ) -> dict:
        payload: dict = {"itemId": item_id, "price": {"value": price}}
        if price_by_catalog:
            payload["priceByCatalog"] = price_by_catalog
        r = await self._request(
            "PATCH",
            f"/catalog/v2.0/merchants/{self.creds.merchant_id}/items/price",
            json=payload,
        )
        return r.json() if r.content else {}

    async def set_item_external_code(
        self,
        item_id: str,
        external_code: str,
        external_code_by_catalog: list[dict] | None = None,
    ) -> dict:
        payload: dict = {"itemId": item_id, "externalCode": external_code}
        if external_code_by_catalog:
            payload["externalCodeByCatalog"] = external_code_by_catalog
        r = await self._request(
            "PATCH",
            f"/catalog/v2.0/merchants/{self.creds.merchant_id}/items/externalCode",
            json=payload,
        )
        return r.json() if r.content else {}

    # ── Catalog: Add-ons (opções) ─────────────────────────────────────────

    async def set_option_price(
        self,
        option_id: str,
        price: float,
        price_by_catalog: list[dict] | None = None,
    ) -> dict:
        payload: dict = {"optionId": option_id, "price": {"value": price}}
        if price_by_catalog:
            payload["priceByCatalog"] = price_by_catalog
        r = await self._request(
            "PATCH",
            f"/catalog/v2.0/merchants/{self.creds.merchant_id}/options/price",
            json=payload,
        )
        return r.json() if r.content else {}

    async def set_option_status(
        self,
        option_id: str,
        status: Literal["AVAILABLE", "UNAVAILABLE"],
        status_by_catalog: list[dict] | None = None,
    ) -> dict:
        payload: dict = {"optionId": option_id, "status": status}
        if status_by_catalog:
            payload["statusByCatalog"] = status_by_catalog
        r = await self._request(
            "PATCH",
            f"/catalog/v2.0/merchants/{self.creds.merchant_id}/options/status",
            json=payload,
        )
        return r.json() if r.content else {}

    async def set_option_external_code(
        self,
        option_id: str,
        external_code: str,
        external_code_by_catalog: list[dict] | None = None,
    ) -> dict:
        payload: dict = {"optionId": option_id, "externalCode": external_code}
        if external_code_by_catalog:
            payload["externalCodeByCatalog"] = external_code_by_catalog
        r = await self._request(
            "PATCH",
            f"/catalog/v2.0/merchants/{self.creds.merchant_id}/options/externalCode",
            json=payload,
        )
        return r.json() if r.content else {}

    # ── Catalog: Batch ────────────────────────────────────────────────────

    async def batch_update_prices(self, updates: list[dict]) -> dict:
        """updates: [{externalCode|productId, price: {value}, resources: [...], catalogContext?}]"""
        r = await self._request(
            "PATCH",
            f"/catalog/v2.0/merchants/{self.creds.merchant_id}/products/price",
            json=updates,
        )
        return r.json() if r.content else {}

    async def batch_update_status(self, updates: list[dict]) -> dict:
        """updates: [{externalCode|productId, status, resources: [...], catalogContext?}]"""
        r = await self._request(
            "PATCH",
            f"/catalog/v2.0/merchants/{self.creds.merchant_id}/products/status",
            json=updates,
        )
        return r.json() if r.content else {}

    async def get_batch_status(self, batch_id: str) -> dict:
        r = await self._request(
            "GET",
            f"/catalog/v2.0/merchants/{self.creds.merchant_id}/batch/{batch_id}",
        )
        return r.json()

    # ── Catalog: Inventário ───────────────────────────────────────────────

    async def set_item_inventory(self, product_id: str, quantity: int) -> dict:
        r = await self._request(
            "POST",
            f"/catalog/v2.0/merchants/{self.creds.merchant_id}/inventory",
            json={"productId": product_id, "quantity": quantity},
        )
        return r.json() if r.content else {}

    async def get_item_inventory(self, product_id: str) -> dict:
        r = await self._request(
            "GET",
            f"/catalog/v2.0/merchants/{self.creds.merchant_id}/inventory/{product_id}",
        )
        return r.json()

    async def delete_inventory(self, product_ids: list[str]) -> None:
        await self._request(
            "POST",
            f"/catalog/v2.0/merchants/{self.creds.merchant_id}/inventory/batchDelete",
            json={"productIds": product_ids},
        )

    # ── Catalog: Imagens ──────────────────────────────────────────────────

    async def upload_image(self, image_base64: str) -> dict:
        """image_base64: data URI completo — 'data:image/png;base64,...'. Máx 5 MB."""
        r = await self._request(
            "POST",
            f"/catalog/v2.0/merchants/{self.creds.merchant_id}/image/upload",
            json={"image": image_base64},
        )
        return r.json()

    # ── Pedidos: Event Feed ───────────────────────────────────────────────

    async def poll_events(self, limit: int | None = None) -> list[dict]:
        """
        Busca eventos pendentes. Chamar a cada ~30s.
        Sempre ACK após processar — sem ACK o evento volta para a fila.
        """
        params = {"limit": limit} if limit else None
        r = await self._request("GET", "/order/v1.0/orders:polling", params=params)
        data = r.json() if r.content else {}
        return data.get("events", data) if isinstance(data, dict) else data

    async def acknowledge_events(self, event_ids: list[str]) -> None:
        """Confirma recebimento dos eventos. Obrigatório após poll_events."""
        await self._request(
            "POST",
            "/order/v1.0/orders:acknowledgment",
            json={"acknowledgedEventIds": event_ids},
        )

    # ── Pedidos: Detalhes ─────────────────────────────────────────────────

    async def get_order(self, order_id: str) -> dict:
        r = await self._request("GET", f"/order/v1.0/orders/{order_id}")
        return r.json()

    # ── Pedidos: Fluxo de status ──────────────────────────────────────────

    async def confirm_order(self, order_id: str) -> dict:
        """Confirmar dentro de 8 minutos após PLACED."""
        r = await self._request("POST", f"/order/v1.0/orders/{order_id}/confirm")
        return r.json() if r.content else {}

    async def start_preparation(self, order_id: str) -> dict:
        r = await self._request("POST", f"/order/v1.0/orders/{order_id}/startPreparation")
        return r.json() if r.content else {}

    async def ready_to_pickup(self, order_id: str) -> dict:
        """Obrigatório para TAKEOUT, DINE_IN e DELIVERY antes do dispatch."""
        r = await self._request("POST", f"/order/v1.0/orders/{order_id}/readyToPickup")
        return r.json() if r.content else {}

    async def dispatch_order(self, order_id: str) -> dict:
        """Apenas para entrega própria (DELIVERY com deliveredBy=MERCHANT)."""
        r = await self._request(
            "POST",
            f"/order/v1.0/orders/{order_id}/dispatch",
            json={"deliveredBy": "MERCHANT"},
        )
        return r.json() if r.content else {}

    # ── Pedidos: Cancelamento ─────────────────────────────────────────────

    async def get_cancellation_reasons(self, order_id: str) -> dict:
        r = await self._request("GET", f"/order/v1.0/orders/{order_id}/cancellationReasons")
        return r.json()

    async def request_cancellation(self, order_id: str, reason_code: str) -> dict:
        """reason_code: '501'–'512'. Resultado chega no próximo polling (CANCELLED ou CANCELLATION_REQUEST_FAILED)."""
        r = await self._request(
            "POST",
            f"/order/v1.0/orders/{order_id}/requestCancellation",
            json={"reason": reason_code},
        )
        return r.json() if r.content else {}

    # ── Pedidos: Rastreamento e validação ─────────────────────────────────

    async def track_driver(self, order_id: str) -> dict:
        """Disponível somente após evento ASSIGN_DRIVER. Max 1 req/30s."""
        r = await self._request("GET", f"/order/v1.0/orders/{order_id}/tracking")
        return r.json()

    async def validate_pickup_code(self, order_id: str, code: str) -> dict:
        """Valida o código de retirada fornecido pelo entregador iFood."""
        r = await self._request(
            "POST",
            f"/order/v1.0/orders/{order_id}/validatePickupCode",
            json={"code": code},
        )
        return r.json()

    async def verify_delivery_code(self, order_id: str, code: str) -> dict:
        """Confirma entrega para entrega própria (localizer do recibo)."""
        r = await self._request(
            "POST",
            f"/order/v1.0/orders/{order_id}/verifyDeliveryCode",
            json={"code": code},
        )
        return r.json()

    async def download_prescription(self, order_id: str, prescription_id: str) -> tuple[bytes, str]:
        """Retorna (bytes, content_type) do arquivo de prescrição."""
        r = await self._request(
            "GET",
            f"/order/v1.0/orders/{order_id}/prescriptions/{prescription_id}",
        )
        content_type = r.headers.get("content-type", "application/octet-stream")
        return r.content, content_type

    # ── Merchant: Lojas ───────────────────────────────────────────────────

    async def list_merchants(self, page: int | None = None, size: int | None = None) -> list[dict]:
        params = {}
        if page is not None:
            params["page"] = page
        if size is not None:
            params["size"] = size
        r = await self._request("GET", "/merchant/v1.0/merchants", params=params or None)
        return r.json() if r.content else []

    async def get_merchant(self) -> dict:
        r = await self._request("GET", f"/merchant/v1.0/merchants/{self.creds.merchant_id}")
        return r.json()

    # ── Merchant: Status ──────────────────────────────────────────────────

    async def get_merchant_status(self, operation: str | None = None) -> list[dict]:
        path = f"/merchant/v1.0/merchants/{self.creds.merchant_id}/status"
        if operation:
            path += f"/{operation}"
        r = await self._request("GET", path)
        return r.json() if r.content else []

    async def set_merchant_status(self, open: bool) -> None:
        await self._request(
            "PUT",
            f"/merchant/v1.0/merchants/{self.creds.merchant_id}/status",
            json={"status": "OPEN" if open else "CLOSED"},
        )

    # ── Merchant: Interrupções ────────────────────────────────────────────

    async def list_interruptions(self) -> list[dict]:
        r = await self._request(
            "GET",
            f"/merchant/v1.0/merchants/{self.creds.merchant_id}/interruptions",
        )
        return r.json() if r.content else []

    async def create_interruption(self, description: str, start: datetime, end: datetime) -> dict:
        """Pausa temporária da loja. start/end em UTC; mínimo 1 min, máximo 7 dias."""
        r = await self._request(
            "POST",
            f"/merchant/v1.0/merchants/{self.creds.merchant_id}/interruptions",
            json={
                "description": description,
                "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
        return r.json()

    async def delete_interruption(self, interruption_id: str) -> None:
        await self._request(
            "DELETE",
            f"/merchant/v1.0/merchants/{self.creds.merchant_id}/interruptions/{interruption_id}",
        )

    # ── Merchant: Horários ────────────────────────────────────────────────

    async def get_opening_hours(self) -> list[dict]:
        r = await self._request(
            "GET",
            f"/merchant/v1.0/merchants/{self.creds.merchant_id}/opening-hours",
        )
        return r.json() if r.content else []

    async def set_opening_hours(self, shifts: list[dict]) -> dict:
        """shifts: [{dayOfWeek, start, duration}, ...]. Substitui completamente os horários."""
        r = await self._request(
            "PUT",
            f"/merchant/v1.0/merchants/{self.creds.merchant_id}/opening-hours",
            json={"storeId": self.creds.merchant_id, "shifts": shifts},
        )
        return r.json()

    # ── Merchant: Check-in QR Code ────────────────────────────────────────

    async def generate_checkin_qrcode(self, merchant_ids: list[str]) -> bytes:
        """Retorna PDF binário com QR codes para check-in de entregadores. Máximo 20 lojas."""
        r = await self._request(
            "POST",
            "/merchant/v1.0/merchants/checkin-qrcode",
            json={"merchantIds": merchant_ids},
        )
        return r.content
