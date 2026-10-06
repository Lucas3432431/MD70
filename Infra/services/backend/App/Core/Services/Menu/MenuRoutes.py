# -*- coding: utf-8 -*-
import json
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

import asyncio

from App.Core.Cache.RedisCache import cache_delete, cache_get, cache_set
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Logs import error as log_error
from App.Core.Services.Auth.RequestAuth import get_client_id_from_request
from App.Core.Services.WS.WSOrdersRoutes import orders_watcher

menu_router = APIRouter(tags=["Menu"], prefix="/api/menu")

_TTL = 300  # 5 min


def _key(client_id: str, kind: str) -> str:
    return f"menu:{client_id}:{kind}"


def _pub_key(client_id: str, kind: str) -> str:
    return f"pub_menu:{client_id}:{kind}"


def _bust(client_id: str, *kinds: str) -> None:
    for k in kinds:
        cache_delete(_key(client_id, k))
        cache_delete(_pub_key(client_id, k))


# ─── Schemas ──────────────────────────────────────────────────────────────────


class CategoryCreate(BaseModel):
    name: str
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None


class ProductCreate(BaseModel):
    sku_id: str
    name: str
    price: float
    category: str
    available: bool = True
    emoji: Optional[str] = None
    description: Optional[str] = None
    is_combo: bool = False
    variations_json: Optional[str] = None
    addons_json: Optional[str] = None
    recipe_json: Optional[str] = None
    accompaniments_json: Optional[str] = None
    price_delivery: Optional[float] = None
    price_ifood: Optional[float] = None
    price_99: Optional[float] = None
    production_type: str = "on_demand"
    stock_quantity: int = 0
    status: str = "active"


class ProductUpdate(BaseModel):
    sku_id: Optional[str] = None
    name: Optional[str] = None
    price: Optional[float] = None
    category: Optional[str] = None
    available: Optional[bool] = None
    emoji: Optional[str] = None
    description: Optional[str] = None
    is_combo: Optional[bool] = None
    variations_json: Optional[str] = None
    addons_json: Optional[str] = None
    recipe_json: Optional[str] = None
    accompaniments_json: Optional[str] = None
    price_delivery: Optional[float] = None
    price_ifood: Optional[float] = None
    price_99: Optional[float] = None
    photo_path: Optional[str] = None
    production_type: Optional[str] = None
    stock_quantity: Optional[int] = None
    preparation_time: Optional[int] = None
    status: Optional[str] = None


class StoreUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    cover_photo: Optional[str] = None
    profile_photo: Optional[str] = None
    social_links_json: Optional[str] = None
    google_review_link: Optional[str] = None
    store_slug: Optional[str] = None
    delivery_enabled: Optional[int] = None
    delivery_cost_per_km: Optional[float] = None
    delivery_time_per_km: Optional[int] = None
    store_addr_cep: Optional[str] = None
    store_addr_rua: Optional[str] = None
    store_addr_numero: Optional[str] = None
    store_addr_bairro: Optional[str] = None
    store_addr_cidade: Optional[str] = None
    store_addr_estado: Optional[str] = None
    wifi_ssid: Optional[str] = None
    wifi_password: Optional[str] = None


# ─── Categories ───────────────────────────────────────────────────────────────


@menu_router.get("/categories")
async def list_categories(request: Request):
    client_id = get_client_id_from_request(request)
    key = _key(client_id, "categories")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _query(session):
        from sqlalchemy import text
        rows = session.execute(
            text(
                "SELECT id, name, sort_order, created_at FROM pdv_categories"
                " WHERE client_id = :cid AND (type = 'product' OR type IS NULL)"
                " ORDER BY sort_order ASC, id ASC"
            ),
            {"cid": client_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    result = DatabaseManager.execute_transaction(_query)
    cache_set(key, result, _TTL)
    return result


@menu_router.post("/categories")
async def create_category(payload: CategoryCreate, request: Request):
    client_id = get_client_id_from_request(request)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome vazio")

    def _insert(session):
        from sqlalchemy import text
        session.execute(
            text(
                "INSERT INTO pdv_categories (client_id, name, sort_order)"
                " VALUES (:cid, :name, :sort)"
            ),
            {"cid": client_id, "name": name, "sort": payload.sort_order},
        )
        row = session.execute(
            text(
                "SELECT id, name, sort_order, created_at FROM pdv_categories"
                " WHERE client_id = :cid AND name = :name ORDER BY id DESC LIMIT 1"
            ),
            {"cid": client_id, "name": name},
        ).first()
        return dict(row._mapping) if row else {"name": name}

    try:
        result = DatabaseManager.execute_transaction(_insert)
        _bust(client_id, "categories")
        return result
    except Exception as e:
        log_error(f"[MENU] create_category: {e}")
        raise HTTPException(status_code=500, detail="Erro ao criar categoria")


@menu_router.patch("/categories/{category_id}")
async def update_category(category_id: int, payload: CategoryUpdate, request: Request):
    client_id = get_client_id_from_request(request)
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)

    def _update(session):
        from sqlalchemy import text
        result = session.execute(
            text(f"UPDATE pdv_categories SET {set_clause} WHERE id = :id AND client_id = :cid"),
            {**updates, "id": category_id, "cid": client_id},
        )
        if result.rowcount == 0:
            return None
        row = session.execute(
            text("SELECT id, name, sort_order, created_at FROM pdv_categories WHERE id = :id"),
            {"id": category_id},
        ).first()
        return dict(row._mapping) if row else None

    result = DatabaseManager.execute_transaction(_update)
    if result is None:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")
    _bust(client_id, "categories")
    return result


@menu_router.delete("/categories/{category_id}")
async def delete_category(category_id: int, request: Request):
    client_id = get_client_id_from_request(request)

    def _delete(session):
        from sqlalchemy import text
        r = session.execute(
            text("DELETE FROM pdv_categories WHERE id = :id AND client_id = :cid"),
            {"id": category_id, "cid": client_id},
        )
        return r.rowcount

    if DatabaseManager.execute_transaction(_delete) == 0:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")
    _bust(client_id, "categories")
    return {"ok": True}


# ─── Products ─────────────────────────────────────────────────────────────────

_PRODUCT_COLS = (
    "id, sku_id, name, price, category, available, emoji,"
    " description, is_combo, variations_json, addons_json, recipe_json, accompaniments_json,"
    " price_delivery, price_ifood, price_99, photo_path,"
    " production_type, stock_quantity, preparation_time, status, created_at"
)


@menu_router.get("/products")
async def list_products(request: Request):
    client_id = get_client_id_from_request(request)
    key = _key(client_id, "products")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _query(session):
        from sqlalchemy import text
        rows = session.execute(
            text(f"SELECT {_PRODUCT_COLS} FROM pdv_products WHERE client_id = :cid ORDER BY id ASC"),
            {"cid": client_id},
        ).fetchall()
        stock_rows = session.execute(
            text("SELECT id, quantity FROM pdv_stock_items WHERE client_id = :cid"),
            {"cid": client_id},
        ).fetchall()
        stock_qty = {r[0]: (r[1] or 0) for r in stock_rows}
        result = []
        for r in rows:
            d = dict(r._mapping)
            prod_type = d.get("production_type") or "on_demand"
            if prod_type in ("independent", "resale"):
                d["available"] = 1 if (d.get("stock_quantity") or 0) > 0 else 0
            elif prod_type == "on_demand":
                try:
                    recipe = json.loads(d.get("recipe_json") or "[]")
                except Exception:
                    recipe = []
                if recipe:
                    can_produce = all(
                        stock_qty.get(ing.get("stockItemId"), 0) >= (ing.get("quantity") or 0)
                        for ing in recipe
                        if ing.get("stockItemId") and ing.get("quantity")
                    )
                    d["available"] = 1 if can_produce else 0
            result.append(d)
        return result

    result = DatabaseManager.execute_transaction(_query)
    cache_set(key, result, _TTL)
    return result


@menu_router.post("/products")
async def create_product(payload: ProductCreate, request: Request):
    client_id = get_client_id_from_request(request)

    def _insert(session):
        from sqlalchemy import text
        session.execute(
            text(
                "INSERT INTO pdv_products"
                " (client_id, sku_id, name, price, category, available, emoji,"
                "  description, is_combo, variations_json, addons_json, recipe_json, accompaniments_json,"
                "  price_delivery, price_ifood, price_99, production_type, stock_quantity, status)"
                " VALUES (:cid, :sku, :name, :price, :cat, :avail, :emoji,"
                "  :desc, :combo, :var, :add, :rec, :acc,"
                "  :p_del, :p_ifood, :p_99, :prod_type, :stock_qty, :status)"
            ),
            {
                "cid": client_id, "sku": payload.sku_id, "name": payload.name,
                "price": payload.price, "cat": payload.category,
                "avail": payload.available, "emoji": payload.emoji,
                "desc": payload.description, "combo": payload.is_combo,
                "var": payload.variations_json or "[]",
                "add": payload.addons_json or "[]",
                "rec": payload.recipe_json or "[]",
                "acc": payload.accompaniments_json or "[]",
                "p_del": payload.price_delivery,
                "p_ifood": payload.price_ifood,
                "p_99": payload.price_99,
                "prod_type": payload.production_type,
                "stock_qty": payload.stock_quantity,
                "status": payload.status,
            },
        )
        row = session.execute(
            text(
                f"SELECT {_PRODUCT_COLS} FROM pdv_products"
                " WHERE client_id = :cid AND sku_id = :sku ORDER BY id DESC LIMIT 1"
            ),
            {"cid": client_id, "sku": payload.sku_id},
        ).first()
        return dict(row._mapping) if row else {}

    try:
        result = DatabaseManager.execute_transaction(_insert)
        _bust(client_id, "products")
        return result
    except Exception as e:
        log_error(f"[MENU] create_product: {e}")
        raise HTTPException(status_code=500, detail="Erro ao criar produto")


@menu_router.patch("/products/{product_id}")
@menu_router.put("/products/{product_id}")
async def update_product(product_id: int, payload: ProductUpdate, request: Request):
    client_id = get_client_id_from_request(request)
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)

    def _update(session):
        from sqlalchemy import text
        result = session.execute(
            text(
                f"UPDATE pdv_products SET {set_clause}, updated_at = CURRENT_TIMESTAMP"
                " WHERE id = :pid AND client_id = :cid"
            ),
            {**updates, "pid": product_id, "cid": client_id},
        )
        if result.rowcount == 0:
            return None
        row = session.execute(
            text(f"SELECT {_PRODUCT_COLS} FROM pdv_products WHERE id = :pid"),
            {"pid": product_id},
        ).first()
        return dict(row._mapping) if row else None

    result = DatabaseManager.execute_transaction(_update)
    if result is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    _bust(client_id, "products", "stock_products")
    return result


@menu_router.delete("/products/{product_id}")
async def delete_product(product_id: int, request: Request):
    client_id = get_client_id_from_request(request)

    def _delete(session):
        from sqlalchemy import text
        r = session.execute(
            text("DELETE FROM pdv_products WHERE id = :pid AND client_id = :cid"),
            {"pid": product_id, "cid": client_id},
        )
        return r.rowcount

    if DatabaseManager.execute_transaction(_delete) == 0:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    _bust(client_id, "products")
    return {"ok": True}


@menu_router.post("/products/{product_id}/photo")
async def upload_product_photo(
    product_id: int,
    file: UploadFile = File(...),
    request: Request = None,
):
    import asyncio
    from pathlib import Path
    client_id = get_client_id_from_request(request)
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Imagem muito grande (máx 10MB)")

    backend_path = Path(__file__).parent.parent.parent.parent.parent
    media_dir = backend_path / "Data" / "Media" / f"client_{client_id}" / "products" / str(product_id)
    media_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "photo.jpg").suffix or ".jpg"
    raw_path = media_dir / f"photo{suffix}"
    raw_path.write_bytes(content)

    try:
        from App.Core.Crunch.Storage.MediaCompressor import MediaCompressor
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, MediaCompressor.process_upload, raw_path, client_id, False)
        final_path = result.get("storage") or raw_path
    except Exception:
        final_path = raw_path

    photo_path = f"client_{client_id}/products/{product_id}/{final_path.name}"

    def _update(session):
        from sqlalchemy import text
        session.execute(
            text("UPDATE pdv_products SET photo_path = :path, updated_at = CURRENT_TIMESTAMP WHERE id = :pid AND client_id = :cid"),
            {"path": photo_path, "pid": product_id, "cid": client_id},
        )
    DatabaseManager.execute_transaction(_update)
    _bust(client_id, "products")
    return {"photo_path": photo_path}


@menu_router.post("/products/{product_id}/variations/{variation_id}/photo")
async def upload_variation_photo(
    product_id: int,
    variation_id: int,
    file: UploadFile = File(...),
    request: Request = None,
):
    import asyncio
    from pathlib import Path
    client_id = get_client_id_from_request(request)
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Imagem muito grande (máx 10MB)")

    backend_path = Path(__file__).parent.parent.parent.parent.parent
    media_dir = backend_path / "Data" / "Media" / f"client_{client_id}" / "products" / str(product_id) / "variations" / str(variation_id)
    media_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "photo.jpg").suffix or ".jpg"
    raw_path = media_dir / f"photo{suffix}"
    raw_path.write_bytes(content)

    try:
        from App.Core.Crunch.Storage.MediaCompressor import MediaCompressor
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, MediaCompressor.process_upload, raw_path, client_id, False)
        final_path = result.get("storage") or raw_path
    except Exception:
        final_path = raw_path

    photo_path = f"client_{client_id}/products/{product_id}/variations/{variation_id}/{final_path.name}"
    return {"photo_path": photo_path}


# ─── Store profile ────────────────────────────────────────────────────────────

_STORE_COLS = (
    "name, description, cover_photo, profile_photo,"
    " social_links_json, google_review_link, store_slug, updated_at,"
    " delivery_enabled, delivery_cost_per_km, delivery_time_per_km,"
    " store_addr_cep, store_addr_rua, store_addr_numero, store_addr_bairro, store_addr_cidade, store_addr_estado,"
    " wifi_ssid_enc, wifi_password_enc"
)


@menu_router.get("/store")
async def get_store(request: Request):
    from App.Core.Services.Subscription.EncryptionUtil import decrypt_field
    client_id = get_client_id_from_request(request)
    key = _key(client_id, "store")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _query(session):
        from sqlalchemy import text
        row = session.execute(
            text(f"SELECT {_STORE_COLS} FROM pdv_store_profiles WHERE client_id = :cid LIMIT 1"),
            {"cid": client_id},
        ).first()
        if not row:
            return {}
        result = dict(row._mapping)
        result["wifi_ssid"]     = decrypt_field(result.pop("wifi_ssid_enc", None))
        result["wifi_password"] = decrypt_field(result.pop("wifi_password_enc", None))
        return result

    result = DatabaseManager.execute_transaction(_query)
    cache_set(key, result, _TTL)
    return result


@menu_router.get("/stock-items")
async def list_stock_items(request: Request):
    client_id = get_client_id_from_request(request)
    key = _key(client_id, "stock_items")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _query(session):
        from sqlalchemy import text
        rows = session.execute(
            text(
                "SELECT id, name, emoji, unit, category, quantity, min_stock, cost_per_unit, expiry_date"
                " FROM pdv_stock_items WHERE client_id = :cid ORDER BY category ASC, name ASC"
            ),
            {"cid": client_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    result = DatabaseManager.execute_transaction(_query)
    cache_set(key, result, _TTL)
    return result


@menu_router.get("/active-integrations")
async def get_active_integrations(request: Request):
    """Returns which delivery marketplace integrations are active for this client."""
    client_id = get_client_id_from_request(request)
    key = _key(client_id, "active_integrations")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _query(session):
        from sqlalchemy import text
        rows = session.execute(
            text("SELECT platform FROM delivery_integrations WHERE store_id = :cid"),
            {"cid": client_id},
        ).fetchall()
        return {"platforms": [r[0] for r in rows]}

    try:
        result = DatabaseManager.execute_transaction(_query)
    except Exception:
        result = {"platforms": []}
    cache_set(key, result, 60)
    return result


# ─── Garçom settings ──────────────────────────────────────────────────────────


class GarcomSettingsUpdate(BaseModel):
    enabled: bool
    pct: float


@menu_router.get("/settings/garcom")
async def get_garcom_settings(request: Request):
    client_id = get_client_id_from_request(request)
    key = _key(client_id, "garcom_settings")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _query(session):
        from sqlalchemy import text
        row = session.execute(
            text("SELECT garcom_enabled, garcom_pct FROM pdv_store_profiles WHERE client_id = :cid LIMIT 1"),
            {"cid": client_id},
        ).first()
        if row:
            return {"enabled": bool(row[0]), "pct": float(row[1] or 10.0)}
        return {"enabled": False, "pct": 10.0}

    result = DatabaseManager.execute_transaction(_query)
    cache_set(key, result, _TTL)
    return result


@menu_router.put("/settings/garcom")
@menu_router.patch("/settings/garcom")
async def update_garcom_settings(payload: GarcomSettingsUpdate, request: Request):
    client_id = get_client_id_from_request(request)

    def _upsert(session):
        from sqlalchemy import text
        exists = session.execute(
            text("SELECT 1 FROM pdv_store_profiles WHERE client_id = :cid LIMIT 1"),
            {"cid": client_id},
        ).first()
        if exists:
            session.execute(
                text(
                    "UPDATE pdv_store_profiles SET garcom_enabled = :enabled, garcom_pct = :pct,"
                    " updated_at = CURRENT_TIMESTAMP WHERE client_id = :cid"
                ),
                {"enabled": int(payload.enabled), "pct": payload.pct, "cid": client_id},
            )
        else:
            session.execute(
                text(
                    "INSERT INTO pdv_store_profiles (client_id, garcom_enabled, garcom_pct)"
                    " VALUES (:cid, :enabled, :pct)"
                ),
                {"cid": client_id, "enabled": int(payload.enabled), "pct": payload.pct},
            )

    try:
        DatabaseManager.execute_transaction(_upsert)
        _bust(client_id, "garcom_settings", "store")
        return {"enabled": payload.enabled, "pct": payload.pct}
    except Exception as e:
        log_error(f"[MENU] update_garcom_settings: {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar configuração de garçom")


class DeliverySettingsUpdate(BaseModel):
    enabled: bool
    cost_per_km: float
    time_per_km: int
    addr_cep: Optional[str] = None
    addr_rua: Optional[str] = None
    addr_numero: Optional[str] = None
    addr_bairro: Optional[str] = None
    addr_cidade: Optional[str] = None
    addr_estado: Optional[str] = None


@menu_router.get("/settings/delivery")
async def get_delivery_settings(request: Request):
    client_id = get_client_id_from_request(request)
    key = _key(client_id, "delivery_settings")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _query(session):
        from sqlalchemy import text
        row = session.execute(
            text(
                "SELECT delivery_enabled, delivery_cost_per_km, delivery_time_per_km,"
                " store_addr_cep, store_addr_rua, store_addr_numero, store_addr_bairro, store_addr_cidade, store_addr_estado"
                " FROM pdv_store_profiles WHERE client_id = :cid LIMIT 1"
            ),
            {"cid": client_id},
        ).first()
        if row:
            return {
                "enabled": bool(row[0]),
                "cost_per_km": float(row[1] or 0),
                "time_per_km": int(row[2] or 3),
                "addr_cep": row[3], "addr_rua": row[4], "addr_numero": row[5],
                "addr_bairro": row[6], "addr_cidade": row[7], "addr_estado": row[8],
            }
        return {"enabled": False, "cost_per_km": 0, "time_per_km": 3,
                "addr_cep": None, "addr_rua": None, "addr_numero": None,
                "addr_bairro": None, "addr_cidade": None, "addr_estado": None}

    result = DatabaseManager.execute_transaction(_query)
    cache_set(key, result, _TTL)
    return result


@menu_router.put("/settings/delivery")
@menu_router.patch("/settings/delivery")
async def update_delivery_settings(payload: DeliverySettingsUpdate, request: Request):
    client_id = get_client_id_from_request(request)

    def _upsert(session):
        from sqlalchemy import text
        exists = session.execute(
            text("SELECT 1 FROM pdv_store_profiles WHERE client_id = :cid LIMIT 1"),
            {"cid": client_id},
        ).first()
        params = {
            "enabled": int(payload.enabled), "cost": payload.cost_per_km,
            "time": payload.time_per_km, "cep": payload.addr_cep, "rua": payload.addr_rua,
            "numero": payload.addr_numero, "bairro": payload.addr_bairro,
            "cidade": payload.addr_cidade, "estado": payload.addr_estado, "cid": client_id,
        }
        if exists:
            session.execute(
                text(
                    "UPDATE pdv_store_profiles SET"
                    " delivery_enabled=:enabled, delivery_cost_per_km=:cost, delivery_time_per_km=:time,"
                    " store_addr_cep=COALESCE(:cep, store_addr_cep),"
                    " store_addr_rua=COALESCE(:rua, store_addr_rua),"
                    " store_addr_numero=COALESCE(:numero, store_addr_numero),"
                    " store_addr_bairro=COALESCE(:bairro, store_addr_bairro),"
                    " store_addr_cidade=COALESCE(:cidade, store_addr_cidade),"
                    " store_addr_estado=COALESCE(:estado, store_addr_estado),"
                    " updated_at=CURRENT_TIMESTAMP WHERE client_id=:cid"
                ),
                params,
            )
        else:
            session.execute(
                text(
                    "INSERT INTO pdv_store_profiles"
                    " (client_id, delivery_enabled, delivery_cost_per_km, delivery_time_per_km,"
                    "  store_addr_cep, store_addr_rua, store_addr_numero, store_addr_bairro, store_addr_cidade, store_addr_estado)"
                    " VALUES (:cid, :enabled, :cost, :time, :cep, :rua, :numero, :bairro, :cidade, :estado)"
                ),
                params,
            )

    try:
        DatabaseManager.execute_transaction(_upsert)
        _bust(client_id, "delivery_settings", "store")
        return {
            "enabled": payload.enabled, "cost_per_km": payload.cost_per_km,
            "time_per_km": payload.time_per_km, "addr_cep": payload.addr_cep,
            "addr_rua": payload.addr_rua, "addr_numero": payload.addr_numero,
            "addr_bairro": payload.addr_bairro, "addr_cidade": payload.addr_cidade,
            "addr_estado": payload.addr_estado,
        }
    except Exception as e:
        log_error(f"[MENU] update_delivery_settings: {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar configurações de delivery")


class CaloteSettingsUpdate(BaseModel):
    mode: Optional[str] = None  # "balance" | "cpf" | null


@menu_router.get("/settings/calote")
async def get_calote_settings(request: Request):
    client_id = get_client_id_from_request(request)

    def _query(session):
        from sqlalchemy import text
        row = session.execute(
            text("SELECT calote_mode FROM pdv_store_profiles WHERE client_id = :cid LIMIT 1"),
            {"cid": client_id},
        ).first()
        return {"mode": row[0] if row else None}

    return DatabaseManager.execute_transaction(_query)


@menu_router.put("/settings/calote")
@menu_router.patch("/settings/calote")
async def update_calote_settings(payload: CaloteSettingsUpdate, request: Request):
    client_id = get_client_id_from_request(request)

    def _upsert(session):
        from sqlalchemy import text
        exists = session.execute(
            text("SELECT 1 FROM pdv_store_profiles WHERE client_id = :cid LIMIT 1"),
            {"cid": client_id},
        ).first()
        if exists:
            session.execute(
                text("UPDATE pdv_store_profiles SET calote_mode = :mode, updated_at = CURRENT_TIMESTAMP WHERE client_id = :cid"),
                {"mode": payload.mode, "cid": client_id},
            )
        else:
            session.execute(
                text("INSERT INTO pdv_store_profiles (client_id, calote_mode) VALUES (:cid, :mode)"),
                {"cid": client_id, "mode": payload.mode},
            )

    try:
        DatabaseManager.execute_transaction(_upsert)
        _bust(client_id, "store")
        return {"mode": payload.mode}
    except Exception as e:
        log_error(f"[MENU] update_calote_settings: {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar configuração de calote")


@menu_router.post("/store/cover")
async def upload_store_cover(file: UploadFile = File(...), request: Request = None):
    import asyncio
    from pathlib import Path
    client_id = get_client_id_from_request(request)
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Imagem muito grande (máx 10MB)")

    backend_path = Path(__file__).parent.parent.parent.parent.parent
    media_dir = backend_path / "Data" / "Media" / f"client_{client_id}" / "store"
    media_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "cover.jpg").suffix or ".jpg"
    raw_path = media_dir / f"cover{suffix}"
    raw_path.write_bytes(content)

    try:
        from App.Core.Crunch.Storage.MediaCompressor import MediaCompressor
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, MediaCompressor.process_upload, raw_path, client_id, False)
        final_path = result.get("storage") or raw_path
    except Exception:
        final_path = raw_path

    photo_path = f"client_{client_id}/store/{final_path.name}"

    def _update(session):
        from sqlalchemy import text
        exists = session.execute(
            text("SELECT 1 FROM pdv_store_profiles WHERE client_id = :cid LIMIT 1"),
            {"cid": client_id},
        ).first()
        if exists:
            session.execute(
                text("UPDATE pdv_store_profiles SET cover_photo = :path, updated_at = CURRENT_TIMESTAMP WHERE client_id = :cid"),
                {"path": photo_path, "cid": client_id},
            )
        else:
            session.execute(
                text("INSERT INTO pdv_store_profiles (client_id, cover_photo) VALUES (:cid, :path)"),
                {"cid": client_id, "path": photo_path},
            )

    DatabaseManager.execute_transaction(_update)
    _bust(client_id, "store")
    return {"photo_path": photo_path}


@menu_router.post("/store/profile")
async def upload_store_profile(file: UploadFile = File(...), request: Request = None):
    import asyncio
    from pathlib import Path
    client_id = get_client_id_from_request(request)
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Imagem muito grande (máx 10MB)")

    backend_path = Path(__file__).parent.parent.parent.parent.parent
    media_dir = backend_path / "Data" / "Media" / f"client_{client_id}" / "store"
    media_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "profile.jpg").suffix or ".jpg"
    raw_path = media_dir / f"profile{suffix}"
    raw_path.write_bytes(content)

    try:
        from App.Core.Crunch.Storage.MediaCompressor import MediaCompressor
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, MediaCompressor.process_upload, raw_path, client_id, False)
        final_path = result.get("storage") or raw_path
    except Exception:
        final_path = raw_path

    photo_path = f"client_{client_id}/store/{final_path.name}"

    def _update(session):
        from sqlalchemy import text
        exists = session.execute(
            text("SELECT 1 FROM pdv_store_profiles WHERE client_id = :cid LIMIT 1"),
            {"cid": client_id},
        ).first()
        if exists:
            session.execute(
                text("UPDATE pdv_store_profiles SET profile_photo = :path, updated_at = CURRENT_TIMESTAMP WHERE client_id = :cid"),
                {"path": photo_path, "cid": client_id},
            )
        else:
            session.execute(
                text("INSERT INTO pdv_store_profiles (client_id, profile_photo) VALUES (:cid, :path)"),
                {"cid": client_id, "path": photo_path},
            )

    DatabaseManager.execute_transaction(_update)
    _bust(client_id, "store")
    return {"photo_path": photo_path}


@menu_router.put("/store")
@menu_router.patch("/store")
async def upsert_store(payload: StoreUpdate, request: Request):
    import re
    from App.Core.Services.Subscription.EncryptionUtil import encrypt_field, decrypt_field
    client_id = get_client_id_from_request(request)
    if payload.store_slug is not None:
        slug = payload.store_slug.strip().lower()
        if not re.match(r'^[a-z0-9][a-z0-9\-\_]{1,48}[a-z0-9]$', slug):
            raise HTTPException(status_code=400, detail="Slug inválido: use apenas letras minúsculas, números, hífens e underscores (3–50 caracteres)")
        payload = payload.model_copy(update={"store_slug": slug})

    raw = {k: v for k, v in payload.model_dump().items() if v is not None}
    # Encrypt wifi fields before storing; map plaintext keys to _enc column names
    updates: dict = {}
    for k, v in raw.items():
        if k == "wifi_ssid":
            updates["wifi_ssid_enc"] = encrypt_field(v) if v else None
        elif k == "wifi_password":
            updates["wifi_password_enc"] = encrypt_field(v) if v else None
        else:
            updates[k] = v
    updates = {k: v for k, v in updates.items() if v is not None}

    def _upsert(session):
        from sqlalchemy import text
        exists = session.execute(
            text("SELECT 1 FROM pdv_store_profiles WHERE client_id = :cid LIMIT 1"),
            {"cid": client_id},
        ).first()

        if exists:
            if updates:
                set_clause = ", ".join(f"{k} = :{k}" for k in updates)
                session.execute(
                    text(
                        f"UPDATE pdv_store_profiles SET {set_clause},"
                        " updated_at = CURRENT_TIMESTAMP WHERE client_id = :cid"
                    ),
                    {**updates, "cid": client_id},
                )
        else:
            cols = ["client_id"] + list(updates.keys())
            vals = [":cid"] + [f":{k}" for k in updates]
            session.execute(
                text(
                    f"INSERT INTO pdv_store_profiles ({', '.join(cols)})"
                    f" VALUES ({', '.join(vals)})"
                ),
                {"cid": client_id, **updates},
            )

        row = session.execute(
            text(f"SELECT {_STORE_COLS} FROM pdv_store_profiles WHERE client_id = :cid LIMIT 1"),
            {"cid": client_id},
        ).first()
        if not row:
            return {}
        result = dict(row._mapping)
        result["wifi_ssid"]     = decrypt_field(result.pop("wifi_ssid_enc", None))
        result["wifi_password"] = decrypt_field(result.pop("wifi_password_enc", None))
        return result

    try:
        result = DatabaseManager.execute_transaction(_upsert)
        _bust(client_id, "store")
        return result
    except Exception as e:
        log_error(f"[MENU] upsert_store: {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar perfil da loja")


# ─── NFe settings ──────────────────────────────────────────────────────────────


@menu_router.get("/settings/nfe")
async def get_nfe_settings(request: Request):
    client_id = get_client_id_from_request(request)
    key = _key(client_id, "nfe_settings")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _query(session):
        from sqlalchemy import text
        row = session.execute(
            text("SELECT nfe_enabled FROM pdv_store_profiles WHERE client_id = :cid LIMIT 1"),
            {"cid": client_id},
        ).first()
        return {"enabled": bool(row[0]) if row else False}

    result = DatabaseManager.execute_transaction(_query)
    cache_set(key, result, _TTL)
    return result


class NfeSettingsUpdate(BaseModel):
    enabled: bool


@menu_router.put("/settings/nfe")
@menu_router.patch("/settings/nfe")
async def update_nfe_settings(payload: NfeSettingsUpdate, request: Request):
    client_id = get_client_id_from_request(request)
    enabled = payload.enabled

    def _upsert(session):
        from sqlalchemy import text
        exists = session.execute(
            text("SELECT 1 FROM pdv_store_profiles WHERE client_id = :cid LIMIT 1"),
            {"cid": client_id},
        ).first()
        if exists:
            session.execute(
                text("UPDATE pdv_store_profiles SET nfe_enabled = :v, updated_at = CURRENT_TIMESTAMP WHERE client_id = :cid"),
                {"v": int(enabled), "cid": client_id},
            )
        else:
            session.execute(
                text("INSERT INTO pdv_store_profiles (client_id, nfe_enabled) VALUES (:cid, :v)"),
                {"cid": client_id, "v": int(enabled)},
            )

    try:
        DatabaseManager.execute_transaction(_upsert)
        _bust(client_id, "nfe_settings", "store")
        return {"enabled": enabled}
    except Exception as e:
        log_error(f"[MENU] update_nfe_settings: {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar configuração NFe")


# ─── Tables (Mesas) settings ──────────────────────────────────────────────────


class TableEntry(BaseModel):
    id: int
    number: str


class TablesSettings(BaseModel):
    tables: List[TableEntry]


@menu_router.get("/settings/tables")
async def get_tables_settings(request: Request):
    client_id = get_client_id_from_request(request)
    key = _key(client_id, "tables_settings")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _query(session):
        from sqlalchemy import text
        row = session.execute(
            text("SELECT tables_json FROM pdv_store_profiles WHERE client_id = :cid LIMIT 1"),
            {"cid": client_id},
        ).first()
        raw = row[0] if row else None
        try:
            tables = json.loads(raw) if raw else []
        except Exception:
            tables = []
        return {"tables": tables}

    result = DatabaseManager.execute_transaction(_query)
    cache_set(key, result, _TTL)
    return result


@menu_router.put("/settings/tables")
@menu_router.patch("/settings/tables")
async def update_tables_settings(payload: TablesSettings, request: Request):
    client_id = get_client_id_from_request(request)
    tables_json = json.dumps([t.model_dump() for t in payload.tables], ensure_ascii=False)

    def _upsert(session):
        from sqlalchemy import text
        exists = session.execute(
            text("SELECT 1 FROM pdv_store_profiles WHERE client_id = :cid LIMIT 1"),
            {"cid": client_id},
        ).first()
        if exists:
            session.execute(
                text("UPDATE pdv_store_profiles SET tables_json = :tj, updated_at = CURRENT_TIMESTAMP WHERE client_id = :cid"),
                {"tj": tables_json, "cid": client_id},
            )
        else:
            session.execute(
                text("INSERT INTO pdv_store_profiles (client_id, tables_json) VALUES (:cid, :tj)"),
                {"cid": client_id, "tj": tables_json},
            )

    try:
        DatabaseManager.execute_transaction(_upsert)
        _bust(client_id, "tables_settings", "store")
        return {"tables": [t.model_dump() for t in payload.tables]}
    except Exception as e:
        log_error(f"[MENU] update_tables_settings: {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar mesas")


# ─── Customers ─────────────────────────────────────────────────────────────────

_CUSTOMER_TTL = 86400  # 24 h — invalidado apenas em novos cadastros


def _customer_key(client_id: str) -> str:
    return f"customers:{client_id}:all"


@menu_router.get("/customers/search")
async def search_customers(q: str = "", request: Request = None):
    client_id = get_client_id_from_request(request)
    if not q:
        return []

    cache_key = _customer_key(client_id)
    all_customers = cache_get(cache_key)
    if all_customers is None:
        def _fetch_all(session):
            from sqlalchemy import text
            rows = session.execute(
                text(
                    "SELECT cpf, name, phone, total_orders FROM pdv_customers"
                    " WHERE client_id = :cid ORDER BY total_orders DESC"
                ),
                {"cid": client_id},
            ).fetchall()
            return [dict(r._mapping) for r in rows]
        all_customers = DatabaseManager.execute_transaction(_fetch_all)
        cache_set(cache_key, all_customers, _CUSTOMER_TTL)

    q_lower = q.lower()
    matches = [
        c for c in all_customers
        if c["cpf"].startswith(q) or c["name"].lower().startswith(q_lower)
    ]
    return matches[:10]


class CustomerCreate(BaseModel):
    cpf: str
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    gender: Optional[str] = None
    birth_date: Optional[str] = None
    source: Optional[str] = None


@menu_router.post("/customers")
async def create_customer(payload: CustomerCreate, request: Request):
    client_id = get_client_id_from_request(request)

    def _upsert(session):
        from sqlalchemy import text
        session.execute(
            text(
                "INSERT INTO pdv_customers (client_id, cpf, name, phone, email, gender, birth_date, source)"
                " VALUES (:cid, :cpf, :name, :phone, :email, :gender, :birth_date, :source)"
                " ON CONFLICT(client_id, cpf) DO UPDATE SET name = excluded.name,"
                " phone = excluded.phone, email = excluded.email,"
                " gender = excluded.gender, birth_date = excluded.birth_date,"
                " source = COALESCE(excluded.source, pdv_customers.source)"
            ),
            {"cid": client_id, "cpf": payload.cpf, "name": payload.name,
             "phone": payload.phone, "email": payload.email,
             "gender": payload.gender, "birth_date": payload.birth_date,
             "source": payload.source},
        )

    try:
        DatabaseManager.execute_transaction(_upsert)
        cache_delete(_customer_key(client_id))
        return {"ok": True}
    except Exception as e:
        log_error(f"[MENU] create_customer: {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar cliente")


# ─── Orders (history) ──────────────────────────────────────────────────────────


class OrderCreate(BaseModel):
    comanda_label: Optional[str] = None
    payment_method: Optional[str] = None
    payment_gateway: Optional[str] = "none"
    machine_id: Optional[int] = None
    cpf: Optional[str] = None
    customer_name: Optional[str] = None
    subtotal: float = 0
    garcom_fee: float = 0
    coupon_discount: float = 0
    total: float = 0
    items_json: Optional[str] = None
    coupons_json: Optional[str] = None
    nfe_emitted: bool = False


@menu_router.post("/orders")
async def create_order(payload: OrderCreate, request: Request):
    client_id = get_client_id_from_request(request)

    def _insert(session):
        from sqlalchemy import text

        # Rate lookup for machine/prox gateways
        effective_rate = 0.0
        effective_flat_fee = 0.0
        effective_receive_days = 0

        gateway = payload.payment_gateway or "none"
        machine_id_val = payload.machine_id
        method_val = (payload.payment_method or "").lower()

        if gateway in ("machine", "prox") and method_val in ("credito", "debito", "pix"):
            rate_row = session.execute(
                text(
                    "SELECT rate, flat_fee, receive_days FROM pdv_gateway_rates"
                    " WHERE client_id=:cid AND gateway_type=:gt"
                    " AND COALESCE(machine_id,0)=COALESCE(:mid,0) AND method=:method"
                ),
                {"cid": client_id, "gt": gateway, "mid": machine_id_val, "method": method_val},
            ).fetchone()
            if rate_row:
                effective_rate = rate_row[0]
                effective_flat_fee = rate_row[1]
                effective_receive_days = rate_row[2]

        r = session.execute(
            text(
                "INSERT INTO pdv_orders"
                " (client_id, comanda_label, payment_method, payment_gateway, machine_id, cpf, customer_name,"
                "  subtotal, garcom_fee, coupon_discount, total, items_json, coupons_json, nfe_emitted,"
                "  status, effective_rate, effective_flat_fee, effective_receive_days)"
                " VALUES (:cid, :comanda_label, :payment_method, :payment_gateway, :machine_id, :cpf, :customer_name,"
                "  :subtotal, :garcom_fee, :coupon_discount, :total, :items_json, :coupons_json, :nfe_emitted,"
                "  'operacao_confirmada', :effective_rate, :effective_flat_fee, :effective_receive_days)"
            ),
            {
                "cid": client_id,
                "comanda_label": payload.comanda_label,
                "payment_method": payload.payment_method,
                "payment_gateway": gateway,
                "machine_id": payload.machine_id,
                "cpf": payload.cpf or None,
                "customer_name": payload.customer_name or None,
                "subtotal": payload.subtotal,
                "garcom_fee": payload.garcom_fee,
                "coupon_discount": payload.coupon_discount,
                "total": payload.total,
                "items_json": payload.items_json,
                "coupons_json": payload.coupons_json,
                "nfe_emitted": int(payload.nfe_emitted),
                "effective_rate": effective_rate,
                "effective_flat_fee": effective_flat_fee,
                "effective_receive_days": effective_receive_days,
            },
        )
        if payload.cpf:
            session.execute(
                text(
                    "UPDATE pdv_customers"
                    " SET total_orders = COALESCE(total_orders, 0) + 1,"
                    "     total_spent  = COALESCE(total_spent, 0) + :total,"
                    "     last_visit   = datetime('now')"
                    " WHERE client_id = :cid AND cpf = :cpf"
                ),
                {"cid": client_id, "cpf": payload.cpf, "total": payload.total},
            )
        return r.lastrowid

    try:
        new_order_id = DatabaseManager.execute_transaction(_insert)
    except Exception as e:
        log_error(f"[MENU] create_order: {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar pedido")

    # Auto-deduct stock for items that carry product_id
    try:
        import json as _json
        items_raw = _json.loads(payload.items_json or "[]")
        deduct_items = [
            StockDeductItem(product_id=it["product_id"], quantity=it.get("quantity", 1))
            for it in items_raw if it.get("product_id")
        ]
        if deduct_items:
            deduct_payload = StockDeductPayload(items=deduct_items)

            def _deduct_inline(session):
                import json as _json2
                from sqlalchemy import text as _text
                for item in deduct_payload.items:
                    row = session.execute(
                        _text(
                            "SELECT production_type, stock_quantity, recipe_json, price FROM pdv_products"
                            " WHERE id = :pid AND client_id = :cid"
                        ),
                        {"pid": item.product_id, "cid": client_id},
                    ).first()
                    if not row:
                        continue
                    prod_type = row[0] or "on_demand"
                    if prod_type in ("independent", "resale"):
                        new_qty = max(0, (row[1] or 0) - item.quantity)
                        session.execute(
                            _text(
                                "UPDATE pdv_products SET stock_quantity = :qty,"
                                " available = :avail, updated_at = CURRENT_TIMESTAMP"
                                " WHERE id = :pid AND client_id = :cid"
                            ),
                            {"qty": new_qty, "avail": 1 if new_qty > 0 else 0,
                             "pid": item.product_id, "cid": client_id},
                        )
                        # Sync products_stock and log sale transaction
                        ps = session.execute(
                            _text("SELECT id, cost_per_unit FROM products_stock WHERE product_id = :pid AND client_id = :cid"),
                            {"pid": item.product_id, "cid": client_id},
                        ).first()
                        if ps:
                            session.execute(
                                _text(
                                    "UPDATE products_stock SET quantity = :qty,"
                                    " updated_at = CURRENT_TIMESTAMP"
                                    " WHERE product_id = :pid AND client_id = :cid"
                                ),
                                {"qty": new_qty, "pid": item.product_id, "cid": client_id},
                            )
                            unit_price = float(row[3] or 0)
                            unit_cost = float(ps[1] or 0)
                            session.execute(
                                _text(
                                    "INSERT INTO products_stock_transactions"
                                    " (client_id, product_id, type, quantity, total_cost, unit_cost)"
                                    " VALUES (:cid, :pid, 'venda', :qty, :cost, :ucost)"
                                ),
                                {"cid": client_id, "pid": item.product_id, "qty": item.quantity,
                                 "cost": unit_price * item.quantity if unit_price > 0 else None,
                                 "ucost": unit_cost if unit_cost > 0 else None},
                            )
                    else:
                        try:
                            recipe = _json2.loads(row[2] or "[]")
                        except Exception:
                            recipe = []
                        for ingredient in recipe:
                            sid = ingredient.get("stockItemId")
                            qty_per_unit = ingredient.get("quantity", 0)
                            if not sid or not qty_per_unit:
                                continue
                            session.execute(
                                _text(
                                    "UPDATE pdv_stock_items SET quantity = MAX(0, quantity - :deduct),"
                                    " updated_at = CURRENT_TIMESTAMP WHERE id = :sid AND client_id = :cid"
                                ),
                                {"deduct": qty_per_unit * item.quantity, "sid": sid, "cid": client_id},
                            )
                        can_produce = True
                        for ingredient in recipe:
                            sid = ingredient.get("stockItemId")
                            qty_per_unit = ingredient.get("quantity", 0)
                            if not sid or not qty_per_unit:
                                continue
                            stock_row = session.execute(
                                _text("SELECT quantity FROM pdv_stock_items WHERE id = :sid AND client_id = :cid"),
                                {"sid": sid, "cid": client_id},
                            ).first()
                            if not stock_row or (stock_row[0] or 0) < qty_per_unit:
                                can_produce = False
                                break
                        if not can_produce:
                            session.execute(
                                _text(
                                    "UPDATE pdv_products SET available = 0, updated_at = CURRENT_TIMESTAMP"
                                    " WHERE id = :pid AND client_id = :cid"
                                ),
                                {"pid": item.product_id, "cid": client_id},
                            )

            busted_pids = [i.product_id for i in deduct_items]
            DatabaseManager.execute_transaction(_deduct_inline)
            _bust(client_id, "products", "stock_items", "stock_products")
            for pid in busted_pids:
                cache_delete(f"pstock:{client_id}:txns:{pid}")
    except Exception as e:
        log_error(f"[MENU] create_order auto-deduct: {e}")

    _bust(client_id, "orders:last_24h")
    cache_delete(_key(client_id, "product_perf"))
    cache_delete(_key(client_id, "product_seasonality"))

    asyncio.ensure_future(orders_watcher.broadcast(client_id, {
        "type": "new_order",
        "order": {
            "id": new_order_id,
            "comanda_label": payload.comanda_label,
            "customer_name": payload.customer_name,
            "payment_method": payload.payment_method,
            "subtotal": payload.subtotal,
            "total": payload.total,
            "items_json": payload.items_json,
            "status": "operacao_confirmada",
        },
    }))

    return {"ok": True}


_ORDERED_STATUSES_EXCL = "('preparado','preparando','pronto','saiu','saiu_entrega','entregue','cancelado')"

@menu_router.get("/orders")
async def list_orders(
    request: Request,
    period: str = "last_24h",
    filter_by: Optional[str] = None,
    gateway: Optional[str] = None,
    stage: Optional[str] = None,
):
    client_id = get_client_id_from_request(request)
    cache_suffix = f"{period}:{filter_by or ''}:{gateway or ''}:{stage or ''}"
    key = _key(client_id, f"orders:{cache_suffix}")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _query(session):
        from sqlalchemy import text
        _base = (
            "SELECT id, comanda_label, payment_method, payment_gateway, machine_id, cpf, customer_name,"
            " subtotal, garcom_fee, coupon_discount, total, items_json, coupons_json,"
            " nfe_emitted, status, effective_rate, effective_flat_fee, effective_receive_days, created_at"
            " FROM pdv_orders WHERE client_id = :cid"
        )
        params: dict = {"cid": client_id}

        # Optional gateway filter
        gw_clause = ""
        if filter_by == "gateway" and gateway:
            gw_clause = " AND payment_gateway = :gateway"
            params["gateway"] = gateway

        # Optional stage filter — "ordered" = not yet processed by kitchen
        stage_clause = ""
        if stage == "ordered":
            stage_clause = f" AND (status IS NULL OR status NOT IN {_ORDERED_STATUSES_EXCL})"

        extra = gw_clause + stage_clause

        if period == "last_24h":
            rows = session.execute(
                text(_base + extra + " AND created_at >= datetime('now', '-24 hours') ORDER BY created_at DESC"),
                params,
            ).fetchall()
        elif period == "yesterday":
            rows = session.execute(
                text(_base + extra + " AND DATE(datetime(created_at, '-3 hours')) = DATE(datetime('now', '-3 hours', '-1 day')) ORDER BY created_at DESC"),
                params,
            ).fetchall()
        elif period == "this_week":
            rows = session.execute(
                text(_base + extra + " AND DATE(datetime(created_at, '-3 hours')) >= DATE(datetime('now', '-3 hours'), 'weekday 0', '-6 days') ORDER BY created_at DESC"),
                params,
            ).fetchall()
        else:
            rows = session.execute(
                text(_base + extra + " ORDER BY created_at DESC LIMIT 200"),
                params,
            ).fetchall()
        return [dict(r._mapping) for r in rows]

    result = DatabaseManager.execute_transaction(_query)
    cache_set(key, result, 15)  # shorter TTL for stage-filtered nav badge
    return result


@menu_router.get("/purchases")
async def list_purchases(request: Request, period: str = "today"):
    client_id = get_client_id_from_request(request)
    key = _key(client_id, f"purchases:{period}")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _query(session):
        from sqlalchemy import text
        date_filter = "AND DATE(pst.created_at) = DATE('now', 'localtime')" if period == "today" else ""
        rows = session.execute(
            text(
                "SELECT pst.id, pst.product_id, pst.quantity, pst.total_cost,"
                " pst.unit_cost, pst.type,"
                " pst.payment_method, pst.created_at,"
                " p.name, p.emoji, p.category"
                f" FROM products_stock_transactions pst"
                " JOIN pdv_products p ON p.id = pst.product_id"
                " WHERE pst.client_id = :cid AND pst.type IN ('compra', 'perda')"
                " AND (pst.type = 'perda' OR pst.total_cost > 0)"
                f" {date_filter}"
                " ORDER BY pst.created_at DESC LIMIT 500"
            ),
            {"cid": client_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    result = DatabaseManager.execute_transaction(_query)
    cache_set(key, result, 60)
    return result


@menu_router.get("/analytics/product-performance")
async def product_performance(request: Request):
    client_id = get_client_id_from_request(request)
    key = _key(client_id, "product_perf")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _query(session):
        from sqlalchemy import text
        # Aggregate from orders items_json — parse JSON in Python
        orders = session.execute(
            text(
                "SELECT items_json, total, effective_rate, effective_flat_fee"
                " FROM pdv_orders WHERE client_id = :cid AND status != 'cancelado'"
            ),
            {"cid": client_id},
        ).fetchall()

        import json as _json
        perf: dict = {}
        for row in orders:
            try:
                items = _json.loads(row[0] or "[]")
            except Exception:
                continue
            for item in items:
                pid = item.get("product_id") or item.get("productId")
                if not pid:
                    continue
                name = str(item.get("name") or item.get("product_name") or "")
                qty = float(item.get("quantity") or item.get("qty") or 1)
                price = float(item.get("price") or 0)
                revenue = price * qty
                if pid not in perf:
                    perf[pid] = {"name": name, "category": "", "unitsSold": 0, "revenue": 0.0, "cost": 0.0}
                perf[pid]["unitsSold"] += qty
                perf[pid]["revenue"] += revenue

        if not perf:
            return []

        # Enrich with product metadata + persisted WAC cost_per_unit
        pid_list = list(perf.keys())
        placeholders = ",".join(f":p{i}" for i in range(len(pid_list)))
        params = {f"p{i}": v for i, v in enumerate(pid_list)}
        params["cid"] = client_id
        prods = session.execute(
            text(
                f"SELECT id, name, category, price, production_type, preparation_time"
                f" FROM pdv_products WHERE client_id = :cid AND id IN ({placeholders})"
            ),
            params,
        ).fetchall()
        for p in prods:
            pid = p[0]
            if pid in perf:
                perf[pid]["category"] = p[2] or ""
                perf[pid]["production_type"] = p[4] or ""
                perf[pid]["preparation_time"] = p[5]

        if pid_list:
            # WAC cost_per_unit from products_stock (persisted, updated on each purchase)
            stocks = session.execute(
                text(
                    f"SELECT product_id, cost_per_unit FROM products_stock"
                    f" WHERE client_id = :cid AND product_id IN ({placeholders})"
                ),
                params,
            ).fetchall()
            for srow in stocks:
                pid = srow[0]
                if pid in perf:
                    perf[pid]["cpu"] = float(srow[1] or 0)

            # Loss quantities
            losses = session.execute(
                text(
                    f"SELECT product_id, SUM(quantity)"
                    f" FROM products_stock_transactions"
                    f" WHERE client_id = :cid AND type = 'perda' AND product_id IN ({placeholders})"
                    f" GROUP BY product_id"
                ),
                params,
            ).fetchall()
            for lrow in losses:
                pid = lrow[0]
                if pid in perf:
                    perf[pid]["loss"] = float(lrow[1] or 0)

            # Soonest expiry date per product (future dates only)
            expiries = session.execute(
                text(
                    f"SELECT product_id, MIN(expiry_date)"
                    f" FROM products_stock_transactions"
                    f" WHERE client_id = :cid AND type = 'compra'"
                    f" AND expiry_date IS NOT NULL"
                    f" AND expiry_date >= DATE('now', 'localtime')"
                    f" AND product_id IN ({placeholders})"
                    f" GROUP BY product_id"
                ),
                params,
            ).fetchall()
            for erow in expiries:
                pid = erow[0]
                if pid in perf:
                    perf[pid]["expiry_date"] = erow[1]

        # Compute giro: ratio = product_units / avg_units_across_all_products
        total_units = sum(d["unitsSold"] for d in perf.values())
        num_products = len(perf)
        avg_units = (total_units / num_products) if num_products > 0 else 1

        import datetime as _dt

        def _giro_score(units: float) -> int:
            ratio = units / avg_units if avg_units > 0 else 0
            if ratio > 1.6:   return 5
            if ratio > 1.2:   return 4
            if ratio > 0.8:   return 3
            if ratio > 0.4:   return 2
            return 1

        def _prazo_score(expiry_str) -> int:
            if not expiry_str:
                return 3
            try:
                exp = _dt.date.fromisoformat(str(expiry_str))
                days = (exp - _dt.date.today()).days
            except Exception:
                return 3
            if days > 60:   return 5
            if days > 30:   return 4
            if days > 14:   return 3
            if days >= 7:   return 2
            return 1

        def _mo_score(production_type, prep_time) -> int:
            if production_type == "resale":
                return 5
            if not prep_time:
                return 3
            mins = int(prep_time)
            if mins <= 5:    return 5
            if mins <= 10:   return 4
            if mins <= 20:   return 3
            if mins <= 40:   return 2
            return 1

        # COGS and lossCost use the persisted WAC (cpu)
        # profit = revenue - COGS - lossCost
        profits = {}
        for pid, d in perf.items():
            cpu = d.get("cpu", 0.0)
            cogs = d["unitsSold"] * cpu
            loss_qty = d.get("loss", 0.0)
            loss_cost = loss_qty * cpu
            d["cogs"] = cogs
            d["lossCost"] = loss_cost
            profits[pid] = d["revenue"] - cogs - loss_cost

        total_profit = sum(v for v in profits.values())
        num_perf = len(perf)
        avg_profit = (total_profit / num_perf) if num_perf > 0 else 1

        def _margin_score(profit: float) -> int:
            ratio = profit / avg_profit if avg_profit > 0 else 0
            if ratio > 1.6:   return 5
            if ratio > 1.2:   return 4
            if ratio > 0.8:   return 3
            if ratio > 0.4:   return 2
            return 1

        result = []
        for pid, d in perf.items():
            cpu = d.get("cpu", 0.0)
            revenue = d["revenue"]
            profit = profits[pid]
            result.append({
                "id": pid,
                "name": d["name"],
                "category": d["category"],
                "unitsSold": round(d["unitsSold"]),
                "revenue": round(revenue, 2),
                "cost": round(d["cogs"], 2),
                "loss": round(d.get("loss", 0), 2),
                "lossCost": round(d["lossCost"], 2),
                "profit": round(profit, 2),
                "unitCost": round(cpu, 4),
                "marginScore": _margin_score(profit),
                "giro": _giro_score(d["unitsSold"]),
                "prazoValidade": _prazo_score(d.get("expiry_date")),
                "tempoMO": _mo_score(d.get("production_type"), d.get("preparation_time")),
            })
        return sorted(result, key=lambda x: x["revenue"], reverse=True)

    result = DatabaseManager.execute_transaction(_query)
    cache_set(key, result, 120)
    return result


@menu_router.get("/analytics/product-seasonality")
async def product_seasonality(request: Request):
    client_id = get_client_id_from_request(request)
    key = _key(client_id, "product_seasonality")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _query(session):
        from sqlalchemy import text
        import json as _json
        import datetime as _dt

        BRT = _dt.timezone(_dt.timedelta(hours=-3))
        WEEK_LABELS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
        MONTH_LABELS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

        orders = session.execute(
            text("SELECT created_at, items_json FROM pdv_orders WHERE client_id = :cid AND status != 'cancelado'"),
            {"cid": client_id},
        ).fetchall()

        # season[pid][view][slot] = units
        season: dict = {}
        for row in orders:
            try:
                raw_dt = str(row[0]).strip()
                if "+" not in raw_dt and not raw_dt.endswith("Z"):
                    raw_dt += "+00:00"
                dt = _dt.datetime.fromisoformat(raw_dt).astimezone(BRT)
            except Exception:
                continue

            hora_label = f"{dt.hour}h"
            semana_label = WEEK_LABELS[dt.weekday()]  # Mon=0
            mes_label = str(dt.day)
            ano_label = MONTH_LABELS[dt.month - 1]

            try:
                items = _json.loads(row[1] or "[]")
            except Exception:
                continue

            for item in items:
                pid = item.get("product_id") or item.get("productId")
                if not pid:
                    continue
                pid = int(pid)
                qty = float(item.get("quantity") or item.get("qty") or 1)
                if pid not in season:
                    season[pid] = {"hora": {}, "semana": {}, "mes": {}, "ano": {}}
                for view, label in [("hora", hora_label), ("semana", semana_label), ("mes", mes_label), ("ano", ano_label)]:
                    season[pid][view][label] = season[pid][view].get(label, 0) + qty

        result = {}
        for pid, views in season.items():
            result[str(pid)] = {
                "hora":   [{"label": f"{h}h",         "pedidos": round(views["hora"].get(f"{h}h", 0))}    for h in range(0, 24)],
                "semana": [{"label": lb,               "pedidos": round(views["semana"].get(lb, 0))}       for lb in WEEK_LABELS],
                "mes":    [{"label": str(d),           "pedidos": round(views["mes"].get(str(d), 0))}      for d in range(1, 32)],
                "ano":    [{"label": lb,               "pedidos": round(views["ano"].get(lb, 0))}          for lb in MONTH_LABELS],
            }
        return result

    result = DatabaseManager.execute_transaction(_query)
    cache_set(key, result, 300)
    return result


@menu_router.delete("/orders/{order_id}")
async def delete_order(order_id: int, request: Request):
    client_id = get_client_id_from_request(request)

    def _delete(session):
        from sqlalchemy import text
        result = session.execute(
            text("DELETE FROM pdv_orders WHERE id = :id AND client_id = :cid"),
            {"id": order_id, "cid": client_id},
        )
        return result.rowcount

    deleted = DatabaseManager.execute_transaction(_delete)
    if not deleted:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Order not found")
    _bust(client_id, "orders:last_24h")
    return {"ok": True}


class OrderStatusUpdate(BaseModel):
    status: str


@menu_router.patch("/orders/{order_id}/status")
async def update_order_status(order_id: int, payload: OrderStatusUpdate, request: Request):
    client_id = get_client_id_from_request(request)
    valid = {"pedido", "preparado", "saiu", "entregue", "cancelado"}
    if payload.status not in valid:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Status inválido")

    def _update(session):
        from sqlalchemy import text
        r = session.execute(
            text("UPDATE pdv_orders SET status = :status WHERE id = :id AND client_id = :cid"),
            {"status": payload.status, "id": order_id, "cid": client_id},
        )
        return r.rowcount

    count = DatabaseManager.execute_transaction(_update)
    if not count:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    _bust(client_id, "orders:last_24h")
    return {"ok": True, "status": payload.status}


@menu_router.get("/customers")
async def list_customers(request: Request, limit: int = 200, offset: int = 0):
    client_id = get_client_id_from_request(request)

    def _query(session):
        from sqlalchemy import text
        rows = session.execute(
            text(
                "SELECT id, cpf, name, phone, email, gender, birth_date, total_orders, total_spent, last_visit, created_at, source"
                " FROM pdv_customers WHERE client_id = :cid"
                " ORDER BY total_spent DESC LIMIT :limit OFFSET :offset"
            ),
            {"cid": client_id, "limit": limit, "offset": offset},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    return DatabaseManager.execute_transaction(_query)


@menu_router.delete("/customers/{customer_id}")
async def delete_customer(customer_id: int, request: Request):
    client_id = get_client_id_from_request(request)

    def _delete(session):
        from sqlalchemy import text
        result = session.execute(
            text("DELETE FROM pdv_customers WHERE id = :id AND client_id = :cid"),
            {"id": customer_id, "cid": client_id},
        )
        session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Customer not found")

    DatabaseManager.execute_transaction(_delete)
    cache_delete(_customer_key(client_id))
    return {"ok": True}


@menu_router.get("/customers/{cpf}/orders")
async def get_customer_orders(cpf: str, request: Request):
    client_id = get_client_id_from_request(request)

    def _query(session):
        from sqlalchemy import text
        rows = session.execute(
            text(
                "SELECT id, comanda_label, payment_method, subtotal, garcom_fee, coupon_discount, total, items_json, created_at"
                " FROM pdv_orders WHERE client_id = :cid AND cpf = :cpf"
                " ORDER BY created_at DESC LIMIT 30"
            ),
            {"cid": client_id, "cpf": cpf},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    return DatabaseManager.execute_transaction(_query)


# ─── Comandas ──────────────────────────────────────────────────────────────────


class ComandaCreate(BaseModel):
    label: str
    cpf: Optional[str] = None
    customer_name: Optional[str] = None


class ComandaItemsUpdate(BaseModel):
    items_json: str


@menu_router.get("/comandas")
async def list_comandas(request: Request):
    client_id = get_client_id_from_request(request)

    def _query(session):
        from sqlalchemy import text
        rows = session.execute(
            text(
                "SELECT id, label, cpf, customer_name, items_json, status, opened_at"
                " FROM pdv_comandas WHERE client_id = :cid AND status = 'open'"
                " ORDER BY opened_at ASC"
            ),
            {"cid": client_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    return DatabaseManager.execute_transaction(_query)


@menu_router.get("/comandas/paid")
async def list_paid_comandas(request: Request, period: str = "last_hour"):
    client_id = get_client_id_from_request(request)

    period_filters = {
        "last_hour":  "AND closed_at >= datetime('now', '-1 hour')",
        "last_24h":   "AND closed_at >= datetime('now', '-24 hours')",
        "yesterday":  "AND DATE(datetime(closed_at, '-3 hours')) = DATE(datetime('now', '-3 hours', '-1 day'))",
        "this_week":  "AND DATE(datetime(closed_at, '-3 hours')) >= DATE(datetime('now', '-3 hours'), 'weekday 0', '-6 days')",
        "all":        "",
    }
    where = period_filters.get(period, period_filters["last_hour"])

    def _query(session):
        from sqlalchemy import text
        rows = session.execute(
            text(
                "SELECT id, label, cpf, customer_name, items_json, status, opened_at, closed_at"
                f" FROM pdv_comandas WHERE client_id = :cid AND status = 'closed'"
                f" {where}"
                " ORDER BY closed_at DESC"
            ),
            {"cid": client_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    return DatabaseManager.execute_transaction(_query)


@menu_router.post("/comandas")
async def create_comanda(payload: ComandaCreate, request: Request):
    client_id = get_client_id_from_request(request)

    def _insert(session):
        from sqlalchemy import text
        result = session.execute(
            text(
                "INSERT INTO pdv_comandas (client_id, label, cpf, customer_name)"
                " VALUES (:cid, :label, :cpf, :name)"
            ),
            {"cid": client_id, "label": payload.label, "cpf": payload.cpf or None, "name": payload.customer_name or None},
        )
        session.commit()
        return result.lastrowid

    try:
        new_id = DatabaseManager.execute_transaction(_insert)
        return {"id": new_id, "label": payload.label}
    except Exception as e:
        log_error(f"[MENU] create_comanda: {e}")
        raise HTTPException(status_code=500, detail="Erro ao criar comanda")


@menu_router.patch("/comandas/{comanda_id}/items")
async def update_comanda_items(comanda_id: int, payload: ComandaItemsUpdate, request: Request):
    client_id = get_client_id_from_request(request)

    def _update(session):
        from sqlalchemy import text
        session.execute(
            text("UPDATE pdv_comandas SET items_json = :items WHERE id = :id AND client_id = :cid"),
            {"items": payload.items_json, "id": comanda_id, "cid": client_id},
        )

    DatabaseManager.execute_transaction(_update)
    return {"ok": True}


@menu_router.patch("/comandas/{comanda_id}/close")
async def close_comanda(comanda_id: int, request: Request):
    client_id = get_client_id_from_request(request)

    def _close(session):
        from sqlalchemy import text
        session.execute(
            text(
                "UPDATE pdv_comandas SET status = 'closed', closed_at = datetime('now')"
                " WHERE id = :id AND client_id = :cid"
            ),
            {"id": comanda_id, "cid": client_id},
        )

    DatabaseManager.execute_transaction(_close)
    return {"ok": True}


@menu_router.delete("/comandas/{comanda_id}")
async def delete_comanda(comanda_id: int, request: Request):
    client_id = get_client_id_from_request(request)

    def _delete(session):
        from sqlalchemy import text
        session.execute(
            text("DELETE FROM pdv_comandas WHERE id = :id AND client_id = :cid"),
            {"id": comanda_id, "cid": client_id},
        )

    DatabaseManager.execute_transaction(_delete)
    return {"ok": True}


# ─── Machines ──────────────────────────────────────────────────────────────────

_MACHINES_TTL = 300


class MachineCreate(BaseModel):
    name: str
    sort_order: int = 0


class MachineUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    sort_order: Optional[int] = None


@menu_router.get("/machines")
async def list_machines(request: Request):
    client_id = get_client_id_from_request(request)
    key = _key(client_id, "machines")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _fetch(session):
        from sqlalchemy import text
        rows = session.execute(
            text("SELECT id, name, enabled, sort_order FROM pdv_machines WHERE client_id = :cid ORDER BY sort_order, id"),
            {"cid": client_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    result = DatabaseManager.execute_transaction(_fetch)
    cache_set(key, result, _MACHINES_TTL)
    return result


@menu_router.post("/machines")
async def create_machine(payload: MachineCreate, request: Request):
    client_id = get_client_id_from_request(request)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome vazio")

    def _insert(session):
        from sqlalchemy import text
        session.execute(
            text("INSERT INTO pdv_machines (client_id, name, sort_order) VALUES (:cid, :name, :so)"),
            {"cid": client_id, "name": name, "so": payload.sort_order},
        )
        row = session.execute(
            text("SELECT id, name, enabled, sort_order FROM pdv_machines WHERE client_id = :cid AND name = :name ORDER BY id DESC LIMIT 1"),
            {"cid": client_id, "name": name},
        ).first()
        return dict(row._mapping) if row else {}

    try:
        result = DatabaseManager.execute_transaction(_insert)
        cache_delete(_key(client_id, "machines"))
        return result
    except Exception as e:
        log_error(f"[MENU] create_machine: {e}")
        raise HTTPException(status_code=500, detail="Erro ao criar maquininha")


@menu_router.patch("/machines/{machine_id}")
async def update_machine(machine_id: int, payload: MachineUpdate, request: Request):
    client_id = get_client_id_from_request(request)
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nada para atualizar")
    if "enabled" in updates:
        updates["enabled"] = int(updates["enabled"])
    set_clause = ", ".join(f"{k} = :{k}" for k in updates)

    def _update(session):
        from sqlalchemy import text
        result = session.execute(
            text(f"UPDATE pdv_machines SET {set_clause} WHERE id = :id AND client_id = :cid"),
            {**updates, "id": machine_id, "cid": client_id},
        )
        if result.rowcount == 0:
            return None
        row = session.execute(
            text("SELECT id, name, enabled, sort_order FROM pdv_machines WHERE id = :id"),
            {"id": machine_id},
        ).first()
        return dict(row._mapping) if row else None

    result = DatabaseManager.execute_transaction(_update)
    if result is None:
        raise HTTPException(status_code=404, detail="Maquininha não encontrada")
    cache_delete(_key(client_id, "machines"))
    cache_delete(_key(client_id, "gateway_rates"))
    return result


@menu_router.delete("/machines/{machine_id}")
async def delete_machine(machine_id: int, request: Request):
    client_id = get_client_id_from_request(request)

    def _delete(session):
        from sqlalchemy import text
        r = session.execute(
            text("DELETE FROM pdv_machines WHERE id = :id AND client_id = :cid"),
            {"id": machine_id, "cid": client_id},
        )
        return r.rowcount

    count = DatabaseManager.execute_transaction(_delete)
    if count == 0:
        raise HTTPException(status_code=404, detail="Maquininha não encontrada")
    cache_delete(_key(client_id, "machines"))
    cache_delete(_key(client_id, "gateway_rates"))
    return {"ok": True}


# ─── Gateway rates ─────────────────────────────────────────────────────────────

_DEFAULT_PROX_RATES = [
    {"method": "credito", "rate": 4.49, "flat_fee": 0.49, "receive_days": 1},
    {"method": "debito",  "rate": 3.39, "flat_fee": 0.39, "receive_days": 1},
    {"method": "pix",     "rate": 0.0,  "flat_fee": 2.49, "receive_days": 0},
]
_DEFAULT_MACHINE_RATES = [
    {"method": "credito", "rate": 3.99, "flat_fee": 0.0, "receive_days": 30},
    {"method": "debito",  "rate": 1.49, "flat_fee": 0.0, "receive_days": 1},
    {"method": "pix",     "rate": 0.0,  "flat_fee": 0.0, "receive_days": 0},
]


class GatewayRateItem(BaseModel):
    gateway_type: str
    machine_id: Optional[int] = None
    method: str
    rate: float = 0
    flat_fee: float = 0
    receive_days: int = 0


@menu_router.get("/gateway-rates")
async def get_gateway_rates(request: Request):
    client_id = get_client_id_from_request(request)
    key = _key(client_id, "gateway_rates")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _fetch(session):
        from sqlalchemy import text
        rows = session.execute(
            text(
                "SELECT id, gateway_type, machine_id, method, rate, flat_fee, receive_days"
                " FROM pdv_gateway_rates WHERE client_id = :cid"
            ),
            {"cid": client_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    result = DatabaseManager.execute_transaction(_fetch)
    # Always upsert prox rates to keep them in sync with _DEFAULT_PROX_RATES
    def _seed(session):
        from sqlalchemy import text
        for cfg in _DEFAULT_PROX_RATES:
            session.execute(
                text(
                    "INSERT INTO pdv_gateway_rates"
                    " (client_id, gateway_type, machine_id, method, rate, flat_fee, receive_days)"
                    " VALUES (:cid, 'prox', NULL, :method, :rate, :ff, :rd)"
                    " ON CONFLICT(client_id, gateway_type, COALESCE(machine_id, 0), method)"
                    " DO UPDATE SET rate = excluded.rate, flat_fee = excluded.flat_fee,"
                    " receive_days = excluded.receive_days"
                ),
                {"cid": client_id, "method": cfg["method"], "rate": cfg["rate"],
                 "ff": cfg["flat_fee"], "rd": cfg["receive_days"]},
            )
    DatabaseManager.execute_transaction(_seed)
    if not result:
        result = [
            {"id": None, "gateway_type": "prox", "machine_id": None,
             "method": c["method"], "rate": c["rate"], "flat_fee": c["flat_fee"],
             "receive_days": c["receive_days"]}
            for c in _DEFAULT_PROX_RATES
        ]

    cache_set(key, result, _TTL)
    return result


@menu_router.put("/gateway-rates")
async def upsert_gateway_rates(payload: List[GatewayRateItem], request: Request):
    client_id = get_client_id_from_request(request)

    def _upsert(session):
        from sqlalchemy import text
        for item in payload:
            session.execute(
                text(
                    "INSERT INTO pdv_gateway_rates"
                    " (client_id, gateway_type, machine_id, method, rate, flat_fee, receive_days)"
                    " VALUES (:cid, :gt, :mid, :method, :rate, :ff, :rd)"
                    " ON CONFLICT(client_id, gateway_type, COALESCE(machine_id, 0), method)"
                    " DO UPDATE SET rate = excluded.rate, flat_fee = excluded.flat_fee,"
                    " receive_days = excluded.receive_days"
                ),
                {"cid": client_id, "gt": item.gateway_type, "mid": item.machine_id,
                 "method": item.method, "rate": item.rate, "ff": item.flat_fee, "rd": item.receive_days},
            )

    try:
        DatabaseManager.execute_transaction(_upsert)
        cache_delete(_key(client_id, "gateway_rates"))
        return {"ok": True}
    except Exception as e:
        log_error(f"[MENU] upsert_gateway_rates: {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar taxas")


@menu_router.post("/machines/{machine_id}/rates/seed")
async def seed_machine_rates(machine_id: int, request: Request):
    """Seeds default rates for a newly created machine."""
    client_id = get_client_id_from_request(request)

    def _seed(session):
        from sqlalchemy import text
        row = session.execute(
            text("SELECT id FROM pdv_machines WHERE id = :id AND client_id = :cid"),
            {"id": machine_id, "cid": client_id},
        ).first()
        if not row:
            return False
        for cfg in _DEFAULT_MACHINE_RATES:
            session.execute(
                text(
                    "INSERT OR IGNORE INTO pdv_gateway_rates"
                    " (client_id, gateway_type, machine_id, method, rate, flat_fee, receive_days)"
                    " VALUES (:cid, 'machine', :mid, :method, :rate, :ff, :rd)"
                ),
                {"cid": client_id, "mid": machine_id, "method": cfg["method"],
                 "rate": cfg["rate"], "ff": cfg["flat_fee"], "rd": cfg["receive_days"]},
            )
        return True

    ok = DatabaseManager.execute_transaction(_seed)
    if not ok:
        raise HTTPException(status_code=404, detail="Maquininha não encontrada")
    cache_delete(_key(client_id, "gateway_rates"))
    return {"ok": True}


# ─── Payment configs ───────────────────────────────────────────────────────────

_DEFAULT_PAYMENT_CONFIGS = [
    {"method_key": "dinheiro", "name": "Dinheiro",         "rate": 0.0,  "flat_fee": 0.0, "receive_days": 0,  "enabled": 1, "sort_order": 0},
    {"method_key": "pix",      "name": "Pix",              "rate": 0.0,  "flat_fee": 0.0, "receive_days": 0,  "enabled": 1, "sort_order": 1},
    {"method_key": "debito",   "name": "Cartão de Débito", "rate": 1.49, "flat_fee": 0.0, "receive_days": 1,  "enabled": 1, "sort_order": 2},
    {"method_key": "credito",  "name": "Cartão de Crédito","rate": 3.99, "flat_fee": 0.0, "receive_days": 30, "enabled": 1, "sort_order": 3},
    {"method_key": "vr",       "name": "Vale Refeição",    "rate": 1.2,  "flat_fee": 0.0, "receive_days": 30, "enabled": 1, "sort_order": 4},
]


@menu_router.get("/payment-configs")
async def get_payment_configs(request: Request):
    client_id = get_client_id_from_request(request)
    key = _key(client_id, "payment_configs")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _fetch(session):
        from sqlalchemy import text
        rows = session.execute(
            text(
                "SELECT method_key, name, rate, flat_fee, receive_days, enabled, sort_order"
                " FROM pdv_payment_configs WHERE client_id = :cid ORDER BY sort_order"
            ),
            {"cid": client_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    result = DatabaseManager.execute_transaction(_fetch)
    if not result:
        def _seed(session):
            from sqlalchemy import text
            for cfg in _DEFAULT_PAYMENT_CONFIGS:
                session.execute(
                    text(
                        "INSERT OR IGNORE INTO pdv_payment_configs"
                        " (client_id, method_key, name, rate, flat_fee, receive_days, enabled, sort_order)"
                        " VALUES (:cid, :mk, :name, :rate, :ff, :rd, :en, :so)"
                    ),
                    {"cid": client_id, "mk": cfg["method_key"], "name": cfg["name"],
                     "rate": cfg["rate"], "ff": cfg["flat_fee"], "rd": cfg["receive_days"],
                     "en": cfg["enabled"], "so": cfg["sort_order"]},
                )
        DatabaseManager.execute_transaction(_seed)
        result = _DEFAULT_PAYMENT_CONFIGS

    cache_set(key, result, _TTL)
    return result


# ─── Stock deduction ───────────────────────────────────────────────────────────


class StockDeductItem(BaseModel):
    product_id: int
    quantity: int


class StockDeductPayload(BaseModel):
    items: list[StockDeductItem]


@menu_router.post("/stock/deduct")
async def deduct_stock(payload: StockDeductPayload, request: Request):
    client_id = get_client_id_from_request(request)

    def _deduct(session):
        import json as _json
        from sqlalchemy import text

        for item in payload.items:
            row = session.execute(
                text(
                    "SELECT production_type, stock_quantity, recipe_json FROM pdv_products"
                    " WHERE id = :pid AND client_id = :cid"
                ),
                {"pid": item.product_id, "cid": client_id},
            ).first()
            if not row:
                continue

            prod_type = row[0] or "on_demand"
            if prod_type in ("independent", "resale"):
                new_qty = max(0, (row[1] or 0) - item.quantity)
                session.execute(
                    text(
                        "UPDATE pdv_products SET stock_quantity = :qty,"
                        " available = :avail, updated_at = CURRENT_TIMESTAMP"
                        " WHERE id = :pid AND client_id = :cid"
                    ),
                    {"qty": new_qty, "avail": 1 if new_qty > 0 else 0,
                     "pid": item.product_id, "cid": client_id},
                )
            else:
                try:
                    recipe = _json.loads(row[2] or "[]")
                except Exception:
                    recipe = []
                for ingredient in recipe:
                    sid = ingredient.get("stockItemId")
                    qty_per_unit = ingredient.get("quantity", 0)
                    if not sid or not qty_per_unit:
                        continue
                    session.execute(
                        text(
                            "UPDATE pdv_stock_items SET quantity = MAX(0, quantity - :deduct),"
                            " updated_at = CURRENT_TIMESTAMP WHERE id = :sid AND client_id = :cid"
                        ),
                        {"deduct": qty_per_unit * item.quantity, "sid": sid, "cid": client_id},
                    )
                can_produce = True
                for ingredient in recipe:
                    sid = ingredient.get("stockItemId")
                    qty_per_unit = ingredient.get("quantity", 0)
                    if not sid or not qty_per_unit:
                        continue
                    stock_row = session.execute(
                        text("SELECT quantity FROM pdv_stock_items WHERE id = :sid AND client_id = :cid"),
                        {"sid": sid, "cid": client_id},
                    ).first()
                    if not stock_row or (stock_row[0] or 0) < qty_per_unit:
                        can_produce = False
                        break
                if not can_produce:
                    session.execute(
                        text(
                            "UPDATE pdv_products SET available = 0, updated_at = CURRENT_TIMESTAMP"
                            " WHERE id = :pid AND client_id = :cid"
                        ),
                        {"pid": item.product_id, "cid": client_id},
                    )

    try:
        DatabaseManager.execute_transaction(_deduct)
        _bust(client_id, "products", "stock_items", "stock_products")
        return {"ok": True}
    except Exception as e:
        log_error(f"[MENU] deduct_stock: {e}")
        raise HTTPException(status_code=500, detail="Erro ao dar baixa no estoque")


@menu_router.get("/stock-products")
async def get_stock_products(request: Request):
    """Lightweight endpoint: returns only product IDs + availability/stock info."""
    client_id = get_client_id_from_request(request)

    def _query(session):
        import json as _json
        import math
        from sqlalchemy import text

        rows = session.execute(
            text(
                "SELECT id, production_type, stock_quantity, recipe_json, available"
                " FROM pdv_products WHERE client_id = :cid"
            ),
            {"cid": client_id},
        ).fetchall()

        result = []
        for r in rows:
            pid, prod_type, stock_qty, recipe_json, available = (
                r[0], r[1] or "on_demand", r[2] or 0, r[3], r[4]
            )
            entry = {"id": pid}
            if prod_type in ("independent", "resale"):
                entry["stock_quantity"] = stock_qty
                entry["available_quantity"] = stock_qty
                entry["available"] = 1 if stock_qty > 0 else 0
            else:
                # on_demand: compute max producible from recipe + supply levels
                try:
                    recipe = _json.loads(recipe_json or "[]")
                except Exception:
                    recipe = []
                max_producible = None  # None means unlimited (no recipe)
                can_produce = True
                for ingredient in recipe:
                    sid = ingredient.get("stockItemId")
                    qty_per_unit = ingredient.get("quantity", 0)
                    if not sid or not qty_per_unit:
                        continue
                    stock_row = session.execute(
                        text(
                            "SELECT quantity FROM pdv_stock_items"
                            " WHERE id = :sid AND client_id = :cid"
                        ),
                        {"sid": sid, "cid": client_id},
                    ).first()
                    supply_qty = (stock_row[0] or 0) if stock_row else 0
                    producible = math.floor(supply_qty / qty_per_unit)
                    if max_producible is None or producible < max_producible:
                        max_producible = producible
                    if supply_qty < qty_per_unit:
                        can_produce = False
                entry["can_produce"] = can_produce
                if max_producible is not None:
                    entry["available_quantity"] = max_producible
                entry["available"] = 1 if can_produce else 0
            result.append(entry)
        return result

    return DatabaseManager.execute_transaction(_query)


# ── Billing ────────────────────────────────────────────────────────────────────

PROX_PCT = 0.015
PROX_PER_TXN = 0.50
BILLING_MINIMUM = 200.0


@menu_router.get("/billing/invoice-summary")
async def get_billing_invoice_summary(request: Request):
    """Returns current month's MD70 fee summary."""
    client_id = get_client_id_from_request(request)

    def _query(session):
        from sqlalchemy import text
        row = session.execute(
            text(
                "SELECT COALESCE(SUM(total), 0), COUNT(*)"
                " FROM pdv_orders"
                " WHERE client_id = :cid"
                "   AND payment_gateway = 'prox'"
                "   AND strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')"
            ),
            {"cid": client_id},
        ).first()
        total_revenue = float(row[0] or 0)
        num_txns = int(row[1] or 0)
        fee_from_pct = total_revenue * PROX_PCT
        fee_from_txns = num_txns * PROX_PER_TXN
        fee_collected = fee_from_pct + fee_from_txns
        return {
            "total_revenue": total_revenue,
            "num_transactions": num_txns,
            "fee_from_pct": fee_from_pct,
            "fee_from_txns": fee_from_txns,
            "fee_collected": fee_collected,
            "minimum_fee": BILLING_MINIMUM,
            "balance_due": max(0.0, BILLING_MINIMUM - fee_collected),
        }

    return DatabaseManager.execute_transaction(_query)


class BillingCardCreate(BaseModel):
    stripe_payment_method_id: str
    last4: str
    brand: str = "card"
    holder: Optional[str] = None


@menu_router.get("/billing/cards")
async def get_billing_cards(request: Request):
    client_id = get_client_id_from_request(request)

    def _query(session):
        from sqlalchemy import text
        rows = session.execute(
            text(
                "SELECT id, stripe_payment_method_id, last4, brand, holder, is_active, created_at"
                " FROM pdv_billing_cards WHERE client_id = :cid ORDER BY is_active DESC, id ASC"
            ),
            {"cid": client_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    return DatabaseManager.execute_transaction(_query)


@menu_router.post("/billing/cards")
async def add_billing_card(payload: BillingCardCreate, request: Request):
    client_id = get_client_id_from_request(request)

    def _query(session):
        from sqlalchemy import text
        existing = session.execute(
            text("SELECT COUNT(*) FROM pdv_billing_cards WHERE client_id = :cid"),
            {"cid": client_id},
        ).scalar()
        is_active = 1 if (existing or 0) == 0 else 0
        session.execute(
            text(
                "INSERT INTO pdv_billing_cards"
                " (client_id, stripe_payment_method_id, last4, brand, holder, is_active)"
                " VALUES (:cid, :pm, :last4, :brand, :holder, :active)"
            ),
            {
                "cid": client_id,
                "pm": payload.stripe_payment_method_id,
                "last4": payload.last4,
                "brand": payload.brand,
                "holder": payload.holder,
                "active": is_active,
            },
        )
        row = session.execute(
            text("SELECT id, stripe_payment_method_id, last4, brand, holder, is_active, created_at FROM pdv_billing_cards WHERE stripe_payment_method_id = :pm"),
            {"pm": payload.stripe_payment_method_id},
        ).first()
        return dict(row._mapping) if row else {}

    return DatabaseManager.execute_transaction(_query)


@menu_router.delete("/billing/cards/{card_id}")
async def delete_billing_card(card_id: int, request: Request):
    client_id = get_client_id_from_request(request)

    def _query(session):
        from sqlalchemy import text
        row = session.execute(
            text("SELECT is_active FROM pdv_billing_cards WHERE id = :id AND client_id = :cid"),
            {"id": card_id, "cid": client_id},
        ).first()
        if not row:
            raise HTTPException(status_code=404, detail="Card not found")
        session.execute(
            text("DELETE FROM pdv_billing_cards WHERE id = :id AND client_id = :cid"),
            {"id": card_id, "cid": client_id},
        )
        if row[0]:  # was active — promote the next card
            session.execute(
                text(
                    "UPDATE pdv_billing_cards SET is_active = 1"
                    " WHERE client_id = :cid AND id = (SELECT id FROM pdv_billing_cards WHERE client_id = :cid ORDER BY id ASC LIMIT 1)"
                ),
                {"cid": client_id},
            )
        return {"ok": True}

    return DatabaseManager.execute_transaction(_query)


@menu_router.patch("/billing/cards/{card_id}/activate")
async def activate_billing_card(card_id: int, request: Request):
    client_id = get_client_id_from_request(request)

    def _query(session):
        from sqlalchemy import text
        session.execute(
            text("UPDATE pdv_billing_cards SET is_active = 0 WHERE client_id = :cid"),
            {"cid": client_id},
        )
        session.execute(
            text("UPDATE pdv_billing_cards SET is_active = 1 WHERE id = :id AND client_id = :cid"),
            {"id": card_id, "cid": client_id},
        )
        return {"ok": True}

    return DatabaseManager.execute_transaction(_query)


@menu_router.post("/billing/setup-intent")
async def create_billing_setup_intent(request: Request):
    """Creates a Stripe SetupIntent for saving a payment method."""
    client_id = get_client_id_from_request(request)
    try:
        import stripe as _stripe
        from App.Core.Services.Subscription.StripePaymentService import StripePaymentService
        svc = StripePaymentService()
        intent = _stripe.SetupIntent.create(
            usage="off_session",
            metadata={"client_id": client_id},
        )
        return {"client_secret": intent.client_secret}
    except Exception as e:
        log_error(f"[BILLING] setup-intent error: {e}")
        raise HTTPException(status_code=500, detail="Stripe unavailable")


# ─── Coupons ──────────────────────────────────────────────────────────────────


class CouponCreate(BaseModel):
    code: str = ""
    name: str
    type: str = "percent"
    value: float = 0
    bonus_value: Optional[str] = None
    min_order_value: Optional[float] = None
    active: bool = True
    expires_at: Optional[str] = None


class CouponUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    value: Optional[float] = None
    bonus_value: Optional[str] = None
    min_order_value: Optional[float] = None
    active: Optional[bool] = None
    expires_at: Optional[str] = None


@menu_router.get("/prox-coupons")
async def list_prox_coupons(request: Request):
    def _q(session):
        from sqlalchemy import text
        rows = session.execute(
            text(
                "SELECT id, code, name, type, value, bonus_value, min_order_value, active, expires_at, created_at"
                " FROM pdv_coupons WHERE source = 'prox' AND active = 1"
                " ORDER BY id ASC"
            ),
        ).fetchall()
        return [dict(r._mapping) for r in rows]
    return DatabaseManager.execute_transaction(_q)


@menu_router.get("/coupons")
async def list_coupons(request: Request):
    client_id = get_client_id_from_request(request)

    def _q(session):
        from sqlalchemy import text
        rows = session.execute(
            text("SELECT id, code, name, type, value, bonus_value, min_order_value, active, expires_at, created_at FROM pdv_coupons WHERE client_id = :cid ORDER BY created_at DESC"),
            {"cid": client_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    return DatabaseManager.execute_transaction(_q)


@menu_router.post("/coupons")
async def create_coupon(payload: CouponCreate, request: Request):
    client_id = get_client_id_from_request(request)

    def _q(session):
        from sqlalchemy import text
        result = session.execute(
            text("INSERT INTO pdv_coupons (client_id, code, name, type, value, bonus_value, min_order_value, active, expires_at) VALUES (:cid, :code, :name, :type, :value, :bv, :mov, :active, :exp)"),
            {"cid": client_id, "code": payload.code, "name": payload.name, "type": payload.type, "value": payload.value, "bv": payload.bonus_value, "mov": payload.min_order_value, "active": 1 if payload.active else 0, "exp": payload.expires_at},
        )
        new_id = result.lastrowid
        row = session.execute(
            text("SELECT id, code, name, type, value, bonus_value, min_order_value, active, expires_at, created_at FROM pdv_coupons WHERE id = :id"),
            {"id": new_id},
        ).fetchone()
        return dict(row._mapping)

    return DatabaseManager.execute_transaction(_q)


@menu_router.put("/coupons/{coupon_id}")
async def update_coupon(coupon_id: int, payload: CouponUpdate, request: Request):
    client_id = get_client_id_from_request(request)

    def _q(session):
        from sqlalchemy import text
        row = session.execute(
            text("SELECT id FROM pdv_coupons WHERE id = :id AND client_id = :cid"),
            {"id": coupon_id, "cid": client_id},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Coupon not found")
        updates = {k: v for k, v in payload.model_dump().items() if v is not None}
        if "active" in updates:
            updates["active"] = 1 if updates["active"] else 0
        if updates:
            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            session.execute(
                text(f"UPDATE pdv_coupons SET {set_clause} WHERE id = :id AND client_id = :cid"),
                {**updates, "id": coupon_id, "cid": client_id},
            )
        updated = session.execute(
            text("SELECT id, code, name, type, value, bonus_value, min_order_value, active, expires_at, created_at FROM pdv_coupons WHERE id = :id"),
            {"id": coupon_id},
        ).fetchone()
        return dict(updated._mapping)

    return DatabaseManager.execute_transaction(_q)


@menu_router.delete("/coupons/{coupon_id}")
async def delete_coupon(coupon_id: int, request: Request):
    client_id = get_client_id_from_request(request)

    def _q(session):
        from sqlalchemy import text
        session.execute(
            text("DELETE FROM pdv_coupons WHERE id = :id AND client_id = :cid"),
            {"id": coupon_id, "cid": client_id},
        )
        return {"ok": True}

    return DatabaseManager.execute_transaction(_q)


# ─── Benefits ─────────────────────────────────────────────────────────────────


class BenefitCreate(BaseModel):
    name: str
    description: str = ""
    active: bool = True


class BenefitUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    active: Optional[bool] = None


@menu_router.get("/benefits")
async def list_benefits(request: Request):
    client_id = get_client_id_from_request(request)

    def _q(session):
        from sqlalchemy import text
        rows = session.execute(
            text("SELECT id, name, description, is_active AS active, created_at FROM pdv_benefits WHERE client_id = :cid ORDER BY created_at DESC"),
            {"cid": client_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    return DatabaseManager.execute_transaction(_q)


@menu_router.post("/benefits")
async def create_benefit(payload: BenefitCreate, request: Request):
    client_id = get_client_id_from_request(request)

    def _q(session):
        from sqlalchemy import text
        result = session.execute(
            text("INSERT INTO pdv_benefits (client_id, name, description, type, is_active, created_at, updated_at) VALUES (:cid, :name, :desc, 'general', :active, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
            {"cid": client_id, "name": payload.name, "desc": payload.description, "active": 1 if payload.active else 0},
        )
        new_id = result.lastrowid
        row = session.execute(
            text("SELECT id, name, description, is_active AS active, created_at FROM pdv_benefits WHERE id = :id"),
            {"id": new_id},
        ).fetchone()
        return dict(row._mapping)

    return DatabaseManager.execute_transaction(_q)


@menu_router.put("/benefits/{benefit_id}")
async def update_benefit(benefit_id: int, payload: BenefitUpdate, request: Request):
    client_id = get_client_id_from_request(request)

    def _q(session):
        from sqlalchemy import text
        row = session.execute(
            text("SELECT id FROM pdv_benefits WHERE id = :id AND client_id = :cid"),
            {"id": benefit_id, "cid": client_id},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Benefit not found")
        updates = {k: v for k, v in payload.model_dump().items() if v is not None}
        col_map = {"active": "is_active"}
        if updates:
            set_clause = ", ".join(f"{col_map.get(k, k)} = :{k}" for k in updates)
            if "active" in updates:
                updates["active"] = 1 if updates["active"] else 0
            session.execute(
                text(f"UPDATE pdv_benefits SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id = :id AND client_id = :cid"),
                {**updates, "id": benefit_id, "cid": client_id},
            )
        updated = session.execute(
            text("SELECT id, name, description, is_active AS active, created_at FROM pdv_benefits WHERE id = :id"),
            {"id": benefit_id},
        ).fetchone()
        return dict(updated._mapping)

    return DatabaseManager.execute_transaction(_q)


@menu_router.delete("/benefits/{benefit_id}")
async def delete_benefit(benefit_id: int, request: Request):
    client_id = get_client_id_from_request(request)

    def _q(session):
        from sqlalchemy import text
        session.execute(
            text("DELETE FROM pdv_benefits WHERE id = :id AND client_id = :cid"),
            {"id": benefit_id, "cid": client_id},
        )
        return {"ok": True}

    return DatabaseManager.execute_transaction(_q)
