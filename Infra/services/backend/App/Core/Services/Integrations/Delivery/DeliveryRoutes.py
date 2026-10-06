"""
Rotas de integração com plataformas de delivery — /api/integrations/delivery
Todas as rotas são escopadas por {store_id} e {platform} (ifood | 99food).
"""

import uuid
import json
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from typing import Literal
from sqlalchemy import text

from App.Core.Services.Common.Dependencies import COMPONENTS
from App.Core.Logs import error as log_error
from App.Core.Crunch.TablesSQL.DBCryptographyManager import DBCryptographyManager as Crypto
from App.Core.Settings import load_config
from .IFoodClient import IFoodClient, IFoodCredentials
from .NovenoveFoodClient import NovenoveFoodClient, NovenoveFoodCredentials

delivery_router = APIRouter(
    tags=["Delivery Integrations"],
    prefix="/api/integrations/delivery",
)

Platform = Literal["ifood", "99food"]


def _ifood_app_credentials() -> tuple[str, str]:
    """Retorna (client_id, client_secret) do app iFood lidos do ambiente."""
    cfg = load_config()
    client_id = cfg.get("ifood_client_id", "")
    client_secret = cfg.get("ifood_client_secret", "")
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=503,
            detail="Credenciais iFood não configuradas. Defina IFOOD_CLIENT_ID e IFOOD_CLIENT_SECRET no ambiente.",
        )
    return client_id, client_secret


# ── Helpers: banco + cache ────────────────────────────────────────────────────

def _cache_key_pending(store_id: str) -> str:
    return f"ifood:pending_auth:{store_id}"

def _cache_key_token(store_id: str) -> str:
    return f"ifood:token:{store_id}"

def _get_ifood_client(store_id: str) -> IFoodClient:
    """Carrega credenciais do banco + Redis para a loja."""
    try:
        from App.Core.Cache.RedisCache import cache_get
        cached = cache_get(_cache_key_token(store_id))
        if cached:
            data = cached
            cid, csec = _ifood_app_credentials()
            return IFoodClient(IFoodCredentials(
                client_id=cid,
                client_secret=csec,
                merchant_id=store_id,
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token"),
                expires_at=data.get("expires_at", 0.0),
            ))
    except Exception:
        pass

    db = COMPONENTS.get("db_manager")
    if not db:
        raise HTTPException(status_code=503, detail="DB indisponível")

    def _fetch(session):
        row = session.execute(
            text("SELECT access_token, refresh_token, expires_at FROM delivery_integrations WHERE store_id=:s AND platform='ifood'"),
            {"s": store_id},
        ).fetchone()
        return row

    row = db.execute_transaction(_fetch)
    if not row:
        raise HTTPException(status_code=404, detail=f"iFood não conectado para store {store_id}")

    import time
    expires_at = row[2].timestamp() if isinstance(row[2], datetime) else float(row[2] or 0)
    cid, csec = _ifood_app_credentials()
    creds = IFoodCredentials(
        client_id=cid,
        client_secret=csec,
        merchant_id=store_id,
        access_token=Crypto.decrypt_field(row[0]),
        refresh_token=Crypto.decrypt_field(row[1]) if row[1] else None,
        expires_at=expires_at,
    )
    return IFoodClient(creds)


def _get_99food_client(store_id: str) -> NovenoveFoodClient:
    raise NotImplementedError(f"Credenciais 99Food para store {store_id} não configuradas")


def _client(platform: Platform, store_id: str):
    if platform == "ifood":
        return _get_ifood_client(store_id)
    return _get_99food_client(store_id)


# ── Schemas ───────────────────────────────────────────────────────────────────

class IFoodAuthBody(BaseModel):
    authorization_code: str

# ── Catalog schemas ───────────────────────────────────────────────────────────

class PriceByCatalog(BaseModel):
    value: float
    catalogContext: str

class StatusByCatalog(BaseModel):
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    catalogContext: str

class ExternalCodeByCatalog(BaseModel):
    externalCode: str
    catalogContext: str

class ItemStatusBody(BaseModel):
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    statusByCatalog: list[StatusByCatalog] | None = None

class ItemInventoryBody(BaseModel):
    productId: str
    quantity: int

class ItemPriceBody(BaseModel):
    price: float
    priceByCatalog: list[PriceByCatalog] | None = None

class ItemExternalCodeBody(BaseModel):
    externalCode: str
    externalCodeByCatalog: list[ExternalCodeByCatalog] | None = None

class OptionPriceBody(BaseModel):
    price: float
    priceByCatalog: list[PriceByCatalog] | None = None

class OptionStatusBody(BaseModel):
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    statusByCatalog: list[StatusByCatalog] | None = None

class OptionExternalCodeBody(BaseModel):
    externalCode: str
    externalCodeByCatalog: list[ExternalCodeByCatalog] | None = None

class CreateCategoryBody(BaseModel):
    name: str
    status: Literal["AVAILABLE", "UNAVAILABLE"] = "AVAILABLE"
    template: str = "DEFAULT"

class BatchPriceEntry(BaseModel):
    externalCode: str | None = None
    productId: str | None = None
    price: dict          # {"value": float}
    resources: list[str] # ["ITEM", "OPTION"]
    catalogContext: str | None = None

class BatchStatusEntry(BaseModel):
    externalCode: str | None = None
    productId: str | None = None
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    resources: list[str]
    catalogContext: str | None = None

class DeleteInventoryBody(BaseModel):
    productIds: list[str]

class ImageUploadBody(BaseModel):
    image: str  # data URI base64

# ── Order / Merchant schemas ──────────────────────────────────────────────────

class OrderStatusBody(BaseModel):
    status: Literal["CONFIRMED", "PREPARING", "READY", "DISPATCHED", "CANCELLED"]
    reason: str | None = None  # código para CANCELLED, ex: "501"

class OrderCancellationBody(BaseModel):
    reason: str  # código, ex: "501"

class PickupCodeBody(BaseModel):
    code: str

class DeliveryCodeBody(BaseModel):
    code: str

class AcknowledgeEventsBody(BaseModel):
    eventIds: list[str]

class MerchantStatusBody(BaseModel):
    open: bool

class DaySchedule(BaseModel):
    enabled: bool = True
    open: str = "08:00"       # "HH:MM"
    close: str = "22:00"      # "HH:MM"
    split: bool = False        # segundo turno ativo
    open2: str | None = None   # "HH:MM" — início do 2º turno
    close2: str | None = None  # "HH:MM" — fim do 2º turno

class PollerScheduleBody(BaseModel):
    mon: DaySchedule = DaySchedule(enabled=False)
    tue: DaySchedule = DaySchedule()
    wed: DaySchedule = DaySchedule()
    thu: DaySchedule = DaySchedule()
    fri: DaySchedule = DaySchedule()
    sat: DaySchedule = DaySchedule()
    sun: DaySchedule = DaySchedule()
    auto_manage: bool = True   # se False, poller não abre/fecha a loja no iFood

class InterruptionBody(BaseModel):
    description: str
    start: datetime
    end: datetime

class OpeningHoursShift(BaseModel):
    dayOfWeek: Literal["MONDAY","TUESDAY","WEDNESDAY","THURSDAY","FRIDAY","SATURDAY","SUNDAY"]
    start: str        # "HH:MM:SS"
    duration: int     # minutos

class OpeningHoursBody(BaseModel):
    shifts: list[OpeningHoursShift]

class CheckinQRCodeBody(BaseModel):
    merchantIds: list[str]


# ── Auth: iFood (fluxo distribuído) ──────────────────────────────────────────

@delivery_router.post("/{store_id}/ifood/auth/user-code")
async def ifood_get_user_code(store_id: str):
    """
    Passo 1 — Gera o userCode que o dono da loja insere no Portal do Parceiro iFood.
    Persiste userCode + code_verifier no banco e no Redis (TTL 600s).
    Retorna: userCode, verificationUrl, verificationUrlComplete, expiresIn.
    """
    from App.Core.Cache.RedisCache import cache_set

    cid, csec = _ifood_app_credentials()
    tmp_client = IFoodClient(IFoodCredentials(
        client_id=cid,
        client_secret=csec,
        merchant_id=store_id,
    ))
    data = await tmp_client.get_user_code()

    user_code = data["userCode"]
    code_verifier = data["authorizationCodeVerifier"]
    expires_in = data.get("expiresIn", 600)
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    db = COMPONENTS.get("db_manager")
    if db:
        def _upsert(session):
            session.execute(
                text("""
                    INSERT INTO delivery_pending_auth (id, store_id, platform, user_code, code_verifier, expires_at)
                    VALUES (:id, :store_id, 'ifood', :user_code, :cv, :exp)
                    ON CONFLICT DO NOTHING
                """),
                {"id": str(uuid.uuid4()), "store_id": store_id,
                 "user_code": user_code, "cv": Crypto.encrypt_field(code_verifier), "exp": expires_at},
            )
        try:
            db.execute_transaction(_upsert)
        except Exception as e:
            log_error(f"[Delivery] Erro ao salvar pending_auth: {e}")

    cache_set(
        _cache_key_pending(store_id),
        {"user_code": user_code, "code_verifier": Crypto.encrypt_field(code_verifier)},
        expires_in,
    )

    return {
        "userCode": user_code,
        "verificationUrl": data.get("verificationUrl"),
        "verificationUrlComplete": data.get("verificationUrlComplete"),
        "expiresIn": expires_in,
    }


@delivery_router.post("/{store_id}/ifood/auth/token")
async def ifood_authenticate(store_id: str, body: IFoodAuthBody):
    """
    Passo 5 — Troca o authorizationCode pelo access + refresh token.
    Busca o code_verifier do Redis (ou banco). Persiste tokens no banco + Redis.
    """
    import time
    from App.Core.Cache.RedisCache import cache_get, cache_set, cache_delete

    # Busca o code_verifier
    code_verifier: str | None = None
    cached = cache_get(_cache_key_pending(store_id))
    if cached:
        code_verifier = Crypto.decrypt_field(cached.get("code_verifier", ""))

    if not code_verifier:
        db = COMPONENTS.get("db_manager")
        if db:
            def _fetch_verifier(session):
                row = session.execute(
                    text("SELECT code_verifier FROM delivery_pending_auth WHERE store_id=:s AND platform='ifood' ORDER BY created_at DESC LIMIT 1"),
                    {"s": store_id},
                ).fetchone()
                return Crypto.decrypt_field(row[0]) if row else None
            code_verifier = db.execute_transaction(_fetch_verifier)

    if not code_verifier:
        raise HTTPException(status_code=400, detail="userCode expirado ou não iniciado — chame /auth/user-code primeiro")

    cid, csec = _ifood_app_credentials()
    tmp_client = IFoodClient(IFoodCredentials(
        client_id=cid,
        client_secret=csec,
        merchant_id=store_id,
    ))
    await tmp_client.authenticate_merchant(body.authorization_code, code_verifier)

    creds = tmp_client.creds
    expires_at_dt = datetime.utcfromtimestamp(creds.expires_at)
    ttl = int(creds.expires_at - time.time())

    db = COMPONENTS.get("db_manager")
    if db:
        def _save(session):
            session.execute(
                text("""
                    INSERT INTO delivery_integrations (id, store_id, platform, access_token, refresh_token, expires_at)
                    VALUES (:id, :s, 'ifood', :at, :rt, :exp)
                    ON CONFLICT(store_id, platform) DO UPDATE
                    SET access_token=excluded.access_token,
                        refresh_token=excluded.refresh_token,
                        expires_at=excluded.expires_at,
                        updated_at=CURRENT_TIMESTAMP
                """),
                {"id": str(uuid.uuid4()), "s": store_id,
                 "at": Crypto.encrypt_field(creds.access_token),
                 "rt": Crypto.encrypt_field(creds.refresh_token) if creds.refresh_token else None,
                 "exp": expires_at_dt},
            )
            session.execute(
                text("DELETE FROM delivery_pending_auth WHERE store_id=:s AND platform='ifood'"),
                {"s": store_id},
            )
        db.execute_transaction(_save)

    cache_set(
        _cache_key_token(store_id),
        {"access_token": creds.access_token, "refresh_token": creds.refresh_token, "expires_at": creds.expires_at},
        ttl,
    )
    cache_delete(_cache_key_pending(store_id))

    return {"ok": True}


# ── Catalog: Catálogos (iFood only) ──────────────────────────────────────────

@delivery_router.get("/{store_id}/ifood/catalog/catalogs")
async def list_catalogs(store_id: str):
    client = _get_ifood_client(store_id)
    return await client.list_catalogs()


# ── Catalog: Categorias (iFood only) ─────────────────────────────────────────

@delivery_router.get("/{store_id}/ifood/catalog/categories")
async def list_categories(store_id: str, include_items: bool = False):
    client = _get_ifood_client(store_id)
    return await client.list_categories(include_items)

@delivery_router.post("/{store_id}/ifood/catalog/categories")
async def create_category(store_id: str, body: CreateCategoryBody):
    client = _get_ifood_client(store_id)
    return await client.create_category(body.name, body.status, body.template)


# ── Catalog: Itens (iFood only) ───────────────────────────────────────────────

@delivery_router.put("/{store_id}/ifood/catalog/items")
async def upsert_item(store_id: str, request: Request):
    body = await request.json()
    client = _get_ifood_client(store_id)
    return await client.upsert_item(
        body.get("item", {}),
        body.get("products", []),
        body.get("optionGroups"),
        body.get("options"),
    )

@delivery_router.get("/{store_id}/ifood/catalog/categories/{category_id}/items")
async def list_items_in_category(store_id: str, category_id: str):
    client = _get_ifood_client(store_id)
    return await client.list_items_in_category(category_id)

@delivery_router.get("/{store_id}/ifood/catalog/items/{item_id}")
async def get_item(store_id: str, item_id: str):
    client = _get_ifood_client(store_id)
    return await client.get_item(item_id)

@delivery_router.get("/{store_id}/ifood/catalog/catalogs/{catalog_id}/sellable-items")
async def list_sellable_items(store_id: str, catalog_id: str):
    client = _get_ifood_client(store_id)
    return await client.list_sellable_items(catalog_id)

@delivery_router.get("/{store_id}/ifood/catalog/catalogs/{catalog_id}/unsellable-items")
async def list_unsellable_items(store_id: str, catalog_id: str):
    client = _get_ifood_client(store_id)
    return await client.list_unsellable_items(catalog_id)

@delivery_router.patch("/{store_id}/{platform}/catalog/items/{item_id}/status")
async def set_item_status(
    store_id: str,
    platform: Platform,
    item_id: str,
    body: ItemStatusBody,
):
    client = _client(platform, store_id)
    by_catalog = [s.model_dump() for s in body.statusByCatalog] if body.statusByCatalog else None
    return await client.set_item_status(item_id, body.status, by_catalog)

@delivery_router.patch("/{store_id}/{platform}/catalog/items/{item_id}/price")
async def set_item_price(
    store_id: str,
    platform: Platform,
    item_id: str,
    body: ItemPriceBody,
):
    client = _client(platform, store_id)
    by_catalog = [p.model_dump() for p in body.priceByCatalog] if body.priceByCatalog else None
    return await client.set_item_price(item_id, body.price, by_catalog)

@delivery_router.patch("/{store_id}/ifood/catalog/items/{item_id}/external-code")
async def set_item_external_code(store_id: str, item_id: str, body: ItemExternalCodeBody):
    client = _get_ifood_client(store_id)
    by_catalog = [e.model_dump() for e in body.externalCodeByCatalog] if body.externalCodeByCatalog else None
    return await client.set_item_external_code(item_id, body.externalCode, by_catalog)


# ── Catalog: Add-ons (iFood only) ─────────────────────────────────────────────

@delivery_router.patch("/{store_id}/ifood/catalog/options/{option_id}/price")
async def set_option_price(store_id: str, option_id: str, body: OptionPriceBody):
    client = _get_ifood_client(store_id)
    by_catalog = [p.model_dump() for p in body.priceByCatalog] if body.priceByCatalog else None
    return await client.set_option_price(option_id, body.price, by_catalog)

@delivery_router.patch("/{store_id}/ifood/catalog/options/{option_id}/status")
async def set_option_status(store_id: str, option_id: str, body: OptionStatusBody):
    client = _get_ifood_client(store_id)
    by_catalog = [s.model_dump() for s in body.statusByCatalog] if body.statusByCatalog else None
    return await client.set_option_status(option_id, body.status, by_catalog)

@delivery_router.patch("/{store_id}/ifood/catalog/options/{option_id}/external-code")
async def set_option_external_code(store_id: str, option_id: str, body: OptionExternalCodeBody):
    client = _get_ifood_client(store_id)
    by_catalog = [e.model_dump() for e in body.externalCodeByCatalog] if body.externalCodeByCatalog else None
    return await client.set_option_external_code(option_id, body.externalCode, by_catalog)


# ── Catalog: Batch (iFood only) ───────────────────────────────────────────────

@delivery_router.patch("/{store_id}/ifood/catalog/products/price")
async def batch_update_prices(store_id: str, body: list[BatchPriceEntry]):
    client = _get_ifood_client(store_id)
    return await client.batch_update_prices([e.model_dump(exclude_none=True) for e in body])

@delivery_router.patch("/{store_id}/ifood/catalog/products/status")
async def batch_update_status(store_id: str, body: list[BatchStatusEntry]):
    client = _get_ifood_client(store_id)
    return await client.batch_update_status([e.model_dump(exclude_none=True) for e in body])

@delivery_router.get("/{store_id}/ifood/catalog/batch/{batch_id}")
async def get_batch_status(store_id: str, batch_id: str):
    client = _get_ifood_client(store_id)
    return await client.get_batch_status(batch_id)


# ── Catalog: Inventário ───────────────────────────────────────────────────────

@delivery_router.post("/{store_id}/{platform}/catalog/inventory")
async def set_item_inventory(
    store_id: str,
    platform: Platform,
    body: ItemInventoryBody,
):
    client = _client(platform, store_id)
    return await client.set_item_inventory(body.productId, body.quantity)

@delivery_router.get("/{store_id}/ifood/catalog/inventory/{product_id}")
async def get_item_inventory(store_id: str, product_id: str):
    client = _get_ifood_client(store_id)
    return await client.get_item_inventory(product_id)

@delivery_router.post("/{store_id}/ifood/catalog/inventory/delete")
async def delete_inventory(store_id: str, body: DeleteInventoryBody):
    client = _get_ifood_client(store_id)
    await client.delete_inventory(body.productIds)
    return {"ok": True}


# ── Catalog: Imagens (iFood only) ─────────────────────────────────────────────

@delivery_router.post("/{store_id}/ifood/catalog/image/upload")
async def upload_image(store_id: str, body: ImageUploadBody):
    client = _get_ifood_client(store_id)
    return await client.upload_image(body.image)


# ── Pedidos: Event Feed (iFood only) ─────────────────────────────────────────

@delivery_router.get("/{store_id}/ifood/orders/events")
async def poll_events(store_id: str, limit: int | None = None):
    client = _get_ifood_client(store_id)
    return await client.poll_events(limit)

@delivery_router.post("/{store_id}/ifood/orders/acknowledge")
async def acknowledge_events(store_id: str, body: AcknowledgeEventsBody):
    client = _get_ifood_client(store_id)
    await client.acknowledge_events(body.eventIds)
    return {"ok": True}


# ── Pedidos: Detalhes (cross-platform) ───────────────────────────────────────

@delivery_router.get("/{store_id}/{platform}/orders/{order_id}")
async def get_order(store_id: str, platform: Platform, order_id: str):
    client = _client(platform, store_id)
    return await client.get_order(order_id)


# ── Pedidos: 99food ───────────────────────────────────────────────────────────

@delivery_router.get("/{store_id}/99food/orders")
async def list_99food_orders(store_id: str, status: str | None = None):
    client = _get_99food_client(store_id)
    return await client.list_orders(status)

@delivery_router.patch("/{store_id}/99food/orders/{order_id}/status")
async def update_99food_order_status(store_id: str, order_id: str, body: OrderStatusBody):
    client = _get_99food_client(store_id)
    return await client.update_order_status(order_id, body.status, body.reason)


# ── Pedidos: Fluxo de status (iFood only) ─────────────────────────────────────

@delivery_router.post("/{store_id}/ifood/orders/{order_id}/confirm")
async def confirm_order(store_id: str, order_id: str):
    client = _get_ifood_client(store_id)
    return await client.confirm_order(order_id)

@delivery_router.post("/{store_id}/ifood/orders/{order_id}/start-preparation")
async def start_preparation(store_id: str, order_id: str):
    client = _get_ifood_client(store_id)
    return await client.start_preparation(order_id)

@delivery_router.post("/{store_id}/ifood/orders/{order_id}/ready-to-pickup")
async def ready_to_pickup(store_id: str, order_id: str):
    client = _get_ifood_client(store_id)
    return await client.ready_to_pickup(order_id)

@delivery_router.post("/{store_id}/ifood/orders/{order_id}/dispatch")
async def dispatch_order(store_id: str, order_id: str):
    client = _get_ifood_client(store_id)
    return await client.dispatch_order(order_id)


# ── Pedidos: Cancelamento (iFood only) ────────────────────────────────────────

@delivery_router.get("/{store_id}/ifood/orders/{order_id}/cancellation-reasons")
async def get_cancellation_reasons(store_id: str, order_id: str):
    client = _get_ifood_client(store_id)
    return await client.get_cancellation_reasons(order_id)

@delivery_router.post("/{store_id}/ifood/orders/{order_id}/cancel")
async def cancel_order(store_id: str, order_id: str, body: OrderCancellationBody):
    client = _get_ifood_client(store_id)
    return await client.request_cancellation(order_id, body.reason)


# ── Pedidos: Rastreamento e validação (iFood only) ────────────────────────────

@delivery_router.get("/{store_id}/ifood/orders/{order_id}/tracking")
async def track_driver(store_id: str, order_id: str):
    client = _get_ifood_client(store_id)
    return await client.track_driver(order_id)

@delivery_router.post("/{store_id}/ifood/orders/{order_id}/validate-pickup-code")
async def validate_pickup_code(store_id: str, order_id: str, body: PickupCodeBody):
    client = _get_ifood_client(store_id)
    return await client.validate_pickup_code(order_id, body.code)

@delivery_router.post("/{store_id}/ifood/orders/{order_id}/verify-delivery-code")
async def verify_delivery_code(store_id: str, order_id: str, body: DeliveryCodeBody):
    client = _get_ifood_client(store_id)
    return await client.verify_delivery_code(order_id, body.code)

@delivery_router.get("/{store_id}/ifood/orders/{order_id}/prescriptions/{prescription_id}")
async def download_prescription(store_id: str, order_id: str, prescription_id: str):
    client = _get_ifood_client(store_id)
    data, content_type = await client.download_prescription(order_id, prescription_id)
    return Response(content=data, media_type=content_type)


# ── Merchant: Lojas (iFood only) ──────────────────────────────────────────────

@delivery_router.get("/{store_id}/ifood/merchants")
async def list_merchants(store_id: str, page: int | None = None, size: int | None = None):
    client = _get_ifood_client(store_id)
    return await client.list_merchants(page, size)

@delivery_router.get("/{store_id}/ifood/merchant")
async def get_merchant(store_id: str):
    client = _get_ifood_client(store_id)
    return await client.get_merchant()


# ── Merchant: Status (iFood only) ─────────────────────────────────────────────

@delivery_router.get("/{store_id}/ifood/merchant/status")
async def get_merchant_status(store_id: str):
    client = _get_ifood_client(store_id)
    return await client.get_merchant_status()

@delivery_router.get("/{store_id}/ifood/merchant/status/{operation}")
async def get_merchant_status_by_operation(store_id: str, operation: str):
    client = _get_ifood_client(store_id)
    return await client.get_merchant_status(operation)

@delivery_router.put("/{store_id}/ifood/merchant/status")
async def set_merchant_status(store_id: str, body: MerchantStatusBody):
    client = _get_ifood_client(store_id)
    await client.set_merchant_status(body.open)
    return {"ok": True}


# ── Merchant: Interrupções (iFood only) ───────────────────────────────────────

@delivery_router.get("/{store_id}/ifood/merchant/interruptions")
async def list_interruptions(store_id: str):
    client = _get_ifood_client(store_id)
    return await client.list_interruptions()

@delivery_router.post("/{store_id}/ifood/merchant/interruptions")
async def create_interruption(store_id: str, body: InterruptionBody):
    client = _get_ifood_client(store_id)
    return await client.create_interruption(body.description, body.start, body.end)

@delivery_router.delete("/{store_id}/ifood/merchant/interruptions/{interruption_id}")
async def delete_interruption(store_id: str, interruption_id: str):
    client = _get_ifood_client(store_id)
    await client.delete_interruption(interruption_id)
    return {"ok": True}


# ── Merchant: Horários (iFood only) ───────────────────────────────────────────

@delivery_router.get("/{store_id}/ifood/merchant/opening-hours")
async def get_opening_hours(store_id: str):
    client = _get_ifood_client(store_id)
    return await client.get_opening_hours()

@delivery_router.put("/{store_id}/ifood/merchant/opening-hours")
async def set_opening_hours(store_id: str, body: OpeningHoursBody):
    client = _get_ifood_client(store_id)
    return await client.set_opening_hours([s.model_dump() for s in body.shifts])


# ── Merchant: Check-in QR Code (iFood only) ───────────────────────────────────

@delivery_router.post("/{store_id}/ifood/merchant/checkin-qrcode")
async def generate_checkin_qrcode(store_id: str, body: CheckinQRCodeBody):
    client = _get_ifood_client(store_id)
    pdf_bytes = await client.generate_checkin_qrcode(body.merchantIds)
    return Response(content=pdf_bytes, media_type="application/pdf")


# ── Poller: horário de funcionamento (MD70) ───────────────────────────────────

@delivery_router.get("/{store_id}/ifood/poller/schedule")
async def get_poller_schedule(store_id: str):
    """Retorna o horário de funcionamento do poller iFood para a loja."""
    db = COMPONENTS.get("db_manager")
    if not db:
        raise HTTPException(status_code=503, detail="Banco indisponível")

    row = db.fetch_one(
        "SELECT opening_hours, auto_manage FROM delivery_integrations WHERE store_id = :sid AND platform = 'ifood'",
        {"sid": store_id},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Integração iFood não encontrada")

    raw = row.get("opening_hours")
    auto_manage = bool(row.get("auto_manage", 1))
    if raw:
        try:
            data = json.loads(raw)
            data["auto_manage"] = auto_manage
            return data
        except Exception:
            pass

    # Default: seg fechado, ter-dom 08:00-22:00
    return {
        "auto_manage": auto_manage,
        "mon": {"enabled": False, "open": "08:00", "close": "22:00"},
        "tue": {"enabled": True,  "open": "08:00", "close": "22:00"},
        "wed": {"enabled": True,  "open": "08:00", "close": "22:00"},
        "thu": {"enabled": True,  "open": "08:00", "close": "22:00"},
        "fri": {"enabled": True,  "open": "08:00", "close": "22:00"},
        "sat": {"enabled": True,  "open": "08:00", "close": "22:00"},
        "sun": {"enabled": True,  "open": "08:00", "close": "22:00"},
    }


@delivery_router.put("/{store_id}/ifood/poller/schedule")
async def set_poller_schedule(store_id: str, body: PollerScheduleBody):
    """Salva o horário de funcionamento e configurações do poller iFood para a loja."""
    db = COMPONENTS.get("db_manager")
    if not db:
        raise HTTPException(status_code=503, detail="Banco indisponível")

    data = body.dict()
    auto_manage = data.pop("auto_manage", True)
    schedule_json = json.dumps(data)

    def _update(session):
        session.execute(
            text("UPDATE delivery_integrations SET opening_hours = :oh, auto_manage = :am, updated_at = CURRENT_TIMESTAMP WHERE store_id = :sid AND platform = 'ifood'"),
            {"oh": schedule_json, "am": 1 if auto_manage else 0, "sid": store_id},
        )

    try:
        db.execute_transaction(_update)
    except Exception as e:
        log_error(f"[Delivery] Erro ao salvar horário store={store_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar horário")

    return {"ok": True}
