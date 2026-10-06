# -*- coding: utf-8 -*-
"""
Public menu endpoints — no authentication required.
Resolve store slug → client_id and serve read-only menu data.
"""
import asyncio
import json as _json
import re
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import uuid
from datetime import datetime

from App.Core.Cache.RedisCache import cache_delete, cache_get, cache_set
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Logs import error as log_error, info as log_info

public_menu_router = APIRouter(tags=["Public Menu"], prefix="/api/public")

_TTL = 60  # shorter TTL for public data


def _pub_key(client_id: str, kind: str) -> str:
    return f"pub_menu:{client_id}:{kind}"


_PRODUCT_COLS = (
    "id, sku_id, name, price, category, available, emoji,"
    " description, is_combo, variations_json, addons_json, accompaniments_json,"
    " price_delivery, photo_path, production_type, stock_quantity, preparation_time, status"
)


@public_menu_router.get("/resolve/{slug}")
async def resolve_slug(slug: str):
    """Return client_id and store info for a given slug."""
    if not re.match(r'^[a-z0-9][a-z0-9\-\_]{1,48}[a-z0-9]$', slug.lower()):
        raise HTTPException(status_code=404, detail="Slug não encontrado")

    cached = cache_get(f"pub_slug:{slug}")
    if cached:
        return cached

    def _query(session):
        from sqlalchemy import text
        from App.Core.Services.Subscription.EncryptionUtil import decrypt_field
        row = session.execute(
            text(
                "SELECT client_id, name, description, cover_photo, profile_photo,"
                " google_review_link, social_links_json,"
                " delivery_enabled, delivery_cost_per_km, delivery_time_per_km,"
                " wifi_ssid_enc"
                " FROM pdv_store_profiles WHERE store_slug = :slug LIMIT 1"
            ),
            {"slug": slug.lower()},
        ).first()
        if not row:
            return None
        data = dict(row._mapping)
        data["wifi_ssid"] = decrypt_field(data.pop("wifi_ssid_enc", None))
        return data

    result = DatabaseManager.execute_transaction(_query)
    if not result:
        raise HTTPException(status_code=404, detail="Slug não encontrado")

    cache_set(f"pub_slug:{slug}", result, _TTL)
    return result


@public_menu_router.get("/og/{slug}", response_class=HTMLResponse)
async def og_html(slug: str, request: Request):
    """Server-rendered HTML with Open Graph tags for bots/crawlers on links.domain."""
    if not re.match(r'^[a-z0-9][a-z0-9\-\_]{1,48}[a-z0-9]$', slug.lower()):
        raise HTTPException(status_code=404, detail="Not found")

    cache_key = f"pub_og:{slug}"
    cached = cache_get(cache_key)
    if cached:
        return HTMLResponse(content=cached, media_type="text/html; charset=utf-8")

    def _query(session):
        from sqlalchemy import text
        row = session.execute(
            text(
                "SELECT name, description, cover_photo, profile_photo"
                " FROM pdv_store_profiles WHERE store_slug = :slug LIMIT 1"
            ),
            {"slug": slug.lower()},
        ).first()
        return dict(row._mapping) if row else None

    store = DatabaseManager.execute_transaction(_query)
    if not store:
        raise HTTPException(status_code=404, detail="Not found")

    from App.Core.Settings.Settings import PUBLIC_URL

    # Build absolute image URLs via the app's public proxy endpoint
    base = PUBLIC_URL.rstrip("/")
    def _img(path):
        if not path or not str(path).strip():
            return ""
        return f"{base}/api/proxy/references/{path}"

    name        = store.get("name") or "Cardápio"
    description = store.get("description") or "Acesse o cardápio digital"
    og_image    = _img(store.get("cover_photo"))   # foto de capa do estabelecimento
    favicon     = f"{base}/favicon.ico"            # favicon do MD70

    # Derive the canonical links URL from the incoming request host
    scheme   = request.headers.get("x-forwarded-proto", "https")
    host     = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
    page_url = f"{scheme}://{host}/{slug}"

    import html as _html
    def e(s): return _html.escape(str(s)) if s else ""

    favicon_tag  = f'<link rel="icon" href="{e(favicon)}">'
    og_image_tag = f'<meta property="og:image" content="{e(og_image)}">' if og_image else ""

    html_content = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <title>{e(name)}</title>
  <meta name="description" content="{e(description)}">
  <meta property="og:type"        content="website">
  <meta property="og:url"         content="{e(page_url)}">
  <meta property="og:title"       content="{e(name)}">
  <meta property="og:description" content="{e(description)}">
  <meta property="og:site_name"   content="MD70">
  {og_image_tag}
  <meta name="twitter:card"        content="summary_large_image">
  <meta name="twitter:title"       content="{e(name)}">
  <meta name="twitter:description" content="{e(description)}">
  {og_image_tag.replace("og:image", "twitter:image")}
  {favicon_tag}
</head>
<body>
  <h1>{e(name)}</h1>
  <p>{e(description)}</p>
</body>
</html>"""

    cache_set(cache_key, html_content, 300)  # 5 min TTL
    return HTMLResponse(content=html_content, media_type="text/html; charset=utf-8")


@public_menu_router.get("/wifi/{slug}")
async def get_wifi_credentials(slug: str):
    """Return decrypted WiFi credentials for a store — only if configured."""
    if not re.match(r'^[a-z0-9][a-z0-9\-\_]{1,48}[a-z0-9]$', slug.lower()):
        raise HTTPException(status_code=404, detail="Slug não encontrado")

    def _query(session):
        from sqlalchemy import text
        row = session.execute(
            text(
                "SELECT wifi_ssid_enc, wifi_password_enc"
                " FROM pdv_store_profiles WHERE store_slug = :slug LIMIT 1"
            ),
            {"slug": slug.lower()},
        ).first()
        if not row:
            return None
        return dict(row._mapping)

    result = DatabaseManager.execute_transaction(_query)
    if not result or not result.get("wifi_ssid_enc"):
        raise HTTPException(status_code=404, detail="WiFi não configurado")

    from App.Core.Services.Subscription.EncryptionUtil import decrypt_field
    return {
        "ssid":     decrypt_field(result["wifi_ssid_enc"]),
        "password": decrypt_field(result.get("wifi_password_enc")),
    }


@public_menu_router.get("/menu/{client_id}/store")
async def public_get_store(client_id: str):
    key = _pub_key(client_id, "store")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _query(session):
        from sqlalchemy import text
        row = session.execute(
            text(
                "SELECT p.name, p.description, p.cover_photo, p.profile_photo,"
                " p.social_links_json, p.google_review_link, p.store_slug, p.calote_mode, p.updated_at,"
                " p.delivery_enabled, p.delivery_cost_per_km, p.delivery_time_per_km,"
                " c.opening_hours"
                " FROM pdv_store_profiles p"
                " LEFT JOIN clients c ON c.client_id = p.client_id"
                " WHERE p.client_id = :cid LIMIT 1"
            ),
            {"cid": client_id},
        ).first()
        return dict(row._mapping) if row else {}

    result = DatabaseManager.execute_transaction(_query)
    cache_set(key, result, _TTL)
    return result


@public_menu_router.get("/menu/{client_id}/categories")
async def public_list_categories(client_id: str):
    key = _pub_key(client_id, "categories")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _query(session):
        from sqlalchemy import text
        rows = session.execute(
            text(
                "SELECT id, name, sort_order FROM pdv_categories"
                " WHERE client_id = :cid AND (type = 'product' OR type IS NULL)"
                " ORDER BY sort_order ASC, id ASC"
            ),
            {"cid": client_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    result = DatabaseManager.execute_transaction(_query)
    cache_set(key, result, _TTL)
    return result


@public_menu_router.get("/menu/{client_id}/products")
async def public_list_products(client_id: str):
    key = _pub_key(client_id, "products")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _query(session):
        import json as _json
        from sqlalchemy import text
        rows = session.execute(
            text(
                f"SELECT {_PRODUCT_COLS}, recipe_json FROM pdv_products"
                " WHERE client_id = :cid AND (status = 'active' OR status IS NULL)"
                " ORDER BY id ASC"
            ),
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
                    recipe = _json.loads(d.get("recipe_json") or "[]")
                except Exception:
                    recipe = []
                if recipe:
                    can_produce = all(
                        stock_qty.get(ing.get("stockItemId"), 0) >= (ing.get("quantity") or 0)
                        for ing in recipe
                        if ing.get("stockItemId") and ing.get("quantity")
                    )
                    d["available"] = 1 if can_produce else 0
            d.pop("recipe_json", None)
            result.append(d)
        return result

    result = DatabaseManager.execute_transaction(_query)
    cache_set(key, result, _TTL)
    return result


@public_menu_router.get("/menu/{client_id}/stock-products")
async def public_get_stock_products(client_id: str):
    """Lightweight availability check: IDs + stock quantities / producibility."""
    key = _pub_key(client_id, "stock_products")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _query(session):
        import json as _json
        from sqlalchemy import text

        rows = session.execute(
            text(
                "SELECT id, production_type, stock_quantity, recipe_json"
                " FROM pdv_products WHERE client_id = :cid"
                " AND (status = 'active' OR status IS NULL)"
            ),
            {"cid": client_id},
        ).fetchall()

        result = []
        for r in rows:
            pid, prod_type, stock_qty, recipe_json = (
                r[0], r[1] or "on_demand", r[2] or 0, r[3]
            )
            entry = {"id": pid}
            if prod_type in ("independent", "resale"):
                entry["stock_quantity"] = stock_qty
                entry["available_quantity"] = stock_qty
                entry["available"] = 1 if stock_qty > 0 else 0
            else:
                import math as _math
                try:
                    recipe = _json.loads(recipe_json or "[]")
                except Exception:
                    recipe = []
                max_producible = None
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
                    producible = _math.floor(supply_qty / qty_per_unit)
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

    result = DatabaseManager.execute_transaction(_query)
    cache_set(key, result, _TTL)
    return result


@public_menu_router.get("/check-slug/{slug}")
async def check_slug_available(slug: str, current_client_id: Optional[str] = None):
    """Check if a slug is available (not taken by another store)."""
    slug = slug.strip().lower()
    if not re.match(r'^[a-z0-9][a-z0-9\-\_]{1,48}[a-z0-9]$', slug):
        return {"available": False, "reason": "format"}

    def _query(session):
        from sqlalchemy import text
        row = session.execute(
            text("SELECT client_id FROM pdv_store_profiles WHERE store_slug = :slug LIMIT 1"),
            {"slug": slug},
        ).first()
        if not row:
            return {"available": True}
        if current_client_id and str(row[0]) == str(current_client_id):
            return {"available": True}
        return {"available": False, "reason": "taken"}

    try:
        return DatabaseManager.execute_transaction(_query)
    except Exception as e:
        log_error(f"[PUBLIC] check_slug: {e}")
        return {"available": False, "reason": "error"}


# ─── Public order submission ──────────────────────────────────────────────────

class PublicOrderItem(BaseModel):
    product_id: int
    name: str
    quantity: int
    unit_price: float = 0.0


class PublicOrderCreate(BaseModel):
    items: List[PublicOrderItem]
    subtotal: float = 0.0
    garcom_fee: float = 0.0
    delivery_fee: float = 0.0
    total: float = 0.0
    payment_method: Optional[str] = None  # "card" | "pix" | None
    consumer_id: Optional[str] = None
    consumer_name: Optional[str] = None
    source: str = "cardapio"  # "cardapio" | "delivery"


@public_menu_router.post("/menu/{client_id}/orders")
async def public_create_order(client_id: str, payload: PublicOrderCreate):
    """Submit an order from the consumer-facing cardápio (no store auth required)."""

    items_json_str = _json.dumps(
        [{"product_id": it.product_id, "name": it.name, "quantity": it.quantity, "unit_price": it.unit_price}
         for it in payload.items]
    )

    comanda_label = (payload.consumer_name or "ONLINE").upper()[:40]

    def _insert(session):
        from sqlalchemy import text
        r = session.execute(
            text(
                "INSERT INTO pdv_orders"
                " (client_id, comanda_label, payment_method, payment_gateway, cpf, customer_name,"
                "  subtotal, garcom_fee, delivery_fee, coupon_discount, total, items_json, nfe_emitted,"
                "  status, source, effective_rate, effective_flat_fee, effective_receive_days)"
                " VALUES (:cid, :comanda_label, :payment_method, 'consumer', NULL, :customer_name,"
                "  :subtotal, :garcom_fee, :delivery_fee, 0, :total, :items_json, 0,"
                "  'operacao_confirmada', :source, 0, 0, 0)"
            ),
            {
                "cid": client_id,
                "comanda_label": comanda_label,
                "payment_method": payload.payment_method or "card",
                "customer_name": payload.consumer_name or None,
                "subtotal": payload.subtotal,
                "garcom_fee": payload.garcom_fee,
                "delivery_fee": payload.delivery_fee,
                "total": payload.total,
                "items_json": items_json_str,
                "source": payload.source,
            },
        )
        return r.lastrowid

    try:
        new_order_id = DatabaseManager.execute_transaction(_insert)
    except Exception as e:
        log_error(f"[PUBLIC] create_order: {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar pedido")

    # Auto-deduct stock (mirrors authenticated endpoint)
    deducted_pids: list = []
    try:
        def _deduct(session):
            from sqlalchemy import text as _text
            for item in payload.items:
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
                    deducted_pids.append(item.product_id)
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
        DatabaseManager.execute_transaction(_deduct)
        cache_delete(_pub_key(client_id, "products"))
        cache_delete(_pub_key(client_id, "stock_products"))
        for pid in deducted_pids:
            cache_delete(f"pstock:{client_id}:txns:{pid}")
        # Bust authenticated orders cache
        cache_delete(f"menu:{client_id}:orders:last_24h::")
    except Exception as e:
        log_error(f"[PUBLIC] create_order deduct: {e}")

    # Update store CRM if consumer has a CPF on file
    if payload.consumer_id:
        try:
            def _crm_update(session):
                from sqlalchemy import text as _text
                from App.Core.Services.Subscription.EncryptionUtil import decrypt_field
                cons_row = session.execute(
                    _text("SELECT cpf_encrypted FROM consumers WHERE consumer_id = :cid LIMIT 1"),
                    {"cid": payload.consumer_id},
                ).first()
                if not cons_row or not cons_row[0]:
                    return
                cpf = decrypt_field(cons_row[0])
                if not cpf:
                    return
                session.execute(
                    _text(
                        "INSERT INTO pdv_customers (client_id, cpf, name, source, total_orders, total_spent, last_visit)"
                        " VALUES (:cid, :cpf, :name, 'cardapio', 1, :total, datetime('now'))"
                        " ON CONFLICT(client_id, cpf) DO UPDATE SET"
                        "  total_orders = COALESCE(total_orders, 0) + 1,"
                        "  total_spent = COALESCE(total_spent, 0) + :total,"
                        "  last_visit = datetime('now')"
                    ),
                    {"cid": client_id, "cpf": cpf, "name": payload.consumer_name or None, "total": payload.total},
                )
            DatabaseManager.execute_transaction(_crm_update)
            cache_delete(f"menu:{client_id}:customers")
        except Exception as e:
            log_error(f"[PUBLIC] create_order crm_update: {e}")

    # Broadcast to PDV orders watcher
    try:
        from App.Core.Services.WS.WSOrdersRoutes import orders_watcher
        asyncio.ensure_future(orders_watcher.broadcast(client_id, {
            "type": "new_order",
            "order": {
                "id": new_order_id,
                "comanda_label": comanda_label,
                "customer_name": payload.consumer_name,
                "payment_method": payload.payment_method or "card",
                "subtotal": payload.subtotal,
                "total": payload.total,
                "items_json": items_json_str,
                "status": "operacao_confirmada",
                "source": payload.source,
            },
        }))
    except Exception as e:
        log_error(f"[PUBLIC] create_order broadcast: {e}")

    return {"id": new_order_id}


@public_menu_router.get("/menu/{client_id}/coupons")
async def public_list_coupons(client_id: str):
    """Return active coupons for a store (public, no auth)."""
    from sqlalchemy import text as _text

    with DatabaseManager.get_session() as session:
        rows = session.execute(
            _text(
                "SELECT id, code, name, type, value, bonus_value, min_order_value, expires_at"
                " FROM pdv_coupons"
                " WHERE client_id = :cid AND active = 1"
                " AND (expires_at IS NULL OR expires_at >= DATE('now'))"
                " ORDER BY created_at DESC"
            ),
            {"cid": client_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]


@public_menu_router.get("/menu/{client_id}/benefits")
async def public_list_benefits(client_id: str):
    """Return active benefits for a store (public, no auth)."""
    from sqlalchemy import text as _text

    with DatabaseManager.get_session() as session:
        rows = session.execute(
            _text(
                "SELECT id, name, description, type, value, applies_to FROM pdv_benefits"
                " WHERE client_id = :cid AND is_active = 1"
                " ORDER BY created_at DESC"
            ),
            {"cid": client_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]


class PublicFeedbackCreate(BaseModel):
    client_id: str
    rating: int  # 1-5
    comment: Optional[str] = None
    consumer_id: Optional[str] = None
    source: str = "links"  # "links" | "cardapio" | "delivery"


@public_menu_router.post("/feedback")
async def public_submit_feedback(payload: PublicFeedbackCreate):
    """Save a consumer star-rating + optional comment for a store. No auth required."""
    if not 1 <= payload.rating <= 5:
        raise HTTPException(status_code=400, detail="Rating deve ser entre 1 e 5")

    feedback_id = str(uuid.uuid4())

    def _insert(session):
        from sqlalchemy import text as _text
        session.execute(
            _text(
                "INSERT INTO consumer_feedbacks"
                " (feedback_id, client_id, consumer_id, rating, comment, source, created_at)"
                " VALUES (:fid, :cid, :cons, :rating, :comment, :source, :now)"
            ),
            {
                "fid": feedback_id,
                "cid": payload.client_id,
                "cons": payload.consumer_id,
                "rating": payload.rating,
                "comment": (payload.comment or "").strip() or None,
                "source": payload.source,
                "now": datetime.utcnow(),
            },
        )

    try:
        DatabaseManager.execute_transaction(_insert)
    except Exception as e:
        log_error(f"[PUBLIC] feedback: {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar feedback")

    log_info(f"[PUBLIC] feedback salvo: client={payload.client_id} rating={payload.rating}")
    return {"feedback_id": feedback_id, "ok": True}


# ─── Delivery freight ──────────────────────────────────────────────────────────

class FreightOrderItem(BaseModel):
    product_id: int
    qty: int

class FreightRequest(BaseModel):
    client_id: str
    destination_cep: str
    order_items: List[FreightOrderItem] = []


@public_menu_router.post("/delivery/freight")
async def calculate_freight(payload: FreightRequest):
    """Calculate delivery freight for a given destination CEP.
    Caches Google Maps results by (origin_cep, destination_cep) pair.
    """
    import os
    import httpx
    from sqlalchemy import text as _text

    dest_cep = payload.destination_cep.replace("-", "").replace(".", "").strip()
    if len(dest_cep) != 8:
        raise HTTPException(status_code=400, detail="CEP inválido")

    def _get_store(session):
        row = session.execute(
            _text(
                "SELECT delivery_enabled, delivery_cost_per_km, delivery_time_per_km,"
                " store_addr_cep, store_addr_cidade, store_addr_estado"
                " FROM pdv_store_profiles WHERE client_id = :cid LIMIT 1"
            ),
            {"cid": payload.client_id},
        ).first()
        return dict(row._mapping) if row else None

    store = DatabaseManager.execute_transaction(_get_store)
    if not store or not store.get("delivery_enabled") or not store.get("store_addr_cep"):
        raise HTTPException(status_code=400, detail="Delivery não disponível para este estabelecimento")

    origin_cep = (store["store_addr_cep"] or "").replace("-", "").strip()
    cost_per_km = float(store.get("delivery_cost_per_km") or 0)
    time_per_km = int(store.get("delivery_time_per_km") or 3)

    # 1 — Check distance cache
    def _check_cache(session):
        row = session.execute(
            _text(
                "SELECT distance_meters, duration_seconds FROM delivery_distance_cache"
                " WHERE origin_cep = :orig AND destination_cep = :dest LIMIT 1"
            ),
            {"orig": origin_cep, "dest": dest_cep},
        ).first()
        return dict(row._mapping) if row else None

    cached = DatabaseManager.execute_transaction(_check_cache)

    if cached:
        distance_meters = cached["distance_meters"]
        duration_seconds = cached["duration_seconds"]
    else:
        # 2 — Call Google Maps Distance Matrix
        api_key = os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
        if not api_key:
            # No Maps key — flat 5 km estimate so checkout doesn't break in dev
            distance_meters = 5000
            duration_seconds = 900
        else:
            try:
                def _fmt(c): return f"{c[:5]}-{c[5:]}" if len(c) == 8 else c
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(
                        "https://routes.googleapis.com/directions/v2:computeRoutes",
                        headers={
                            "Content-Type": "application/json",
                            "X-Goog-Api-Key": api_key,
                            "X-Goog-FieldMask": "routes.distanceMeters,routes.staticDuration",
                        },
                        json={
                            "origin": {"address": f"{_fmt(origin_cep)}, Brasil"},
                            "destination": {"address": f"{_fmt(dest_cep)}, Brasil"},
                            "travelMode": "DRIVE",
                            "routingPreference": "TRAFFIC_UNAWARE",
                        },
                    )
                data = resp.json()
                routes = data.get("routes", [])
                if not routes:
                    raise HTTPException(status_code=400, detail="Endereço fora da área de entrega")
                distance_meters = routes[0]["distanceMeters"]
                dur_str = routes[0].get("staticDuration") or routes[0].get("duration", "900s")
                duration_seconds = int(dur_str.rstrip("s"))
            except HTTPException:
                raise
            except Exception as e:
                log_error(f"[PUBLIC] freight routes error ({type(e).__name__}): {e}")
                distance_meters = 5000
                duration_seconds = 900

        # 3 — Save to cache (only for real Maps results, not the flat-estimate fallback)
        if api_key:
            def _save_cache(session):
                session.execute(
                    _text(
                        "INSERT OR REPLACE INTO delivery_distance_cache"
                        " (origin_cep, destination_cep, distance_meters, duration_seconds, created_at)"
                        " VALUES (:orig, :dest, :dist, :dur, CURRENT_TIMESTAMP)"
                    ),
                    {"orig": origin_cep, "dest": dest_cep,
                     "dist": distance_meters, "dur": duration_seconds},
                )
            DatabaseManager.execute_transaction(_save_cache)

    distance_km = distance_meters / 1000
    freight_value = round(distance_km * cost_per_km, 2)
    travel_minutes = max(10, round(distance_km * time_per_km))

    # 4 — Sum preparation times for order items
    prep_minutes = 0
    if payload.order_items:
        pid_list = [item.product_id for item in payload.order_items]
        qty_map = {item.product_id: item.qty for item in payload.order_items}

        def _get_prep(session):
            placeholders = ", ".join(f":p{i}" for i in range(len(pid_list)))
            params = {f"p{i}": pid_list[i] for i in range(len(pid_list))}
            rows = session.execute(
                _text(f"SELECT id, preparation_time FROM pdv_products WHERE id IN ({placeholders})"),
                params,
            ).fetchall()
            return [(row[0], row[1]) for row in rows]

        prods = DatabaseManager.execute_transaction(_get_prep)
        for pid, pt in prods:
            prep_minutes += (pt or 0) * qty_map.get(pid, 1)

    # 5 — Queue time: count active delivery orders
    def _queue(session):
        row = session.execute(
            _text(
                "SELECT COUNT(*) FROM pdv_orders"
                " WHERE client_id = :cid AND source = 'delivery'"
                " AND status = 'operacao_confirmada'"
                " AND created_at >= datetime('now', '-2 hours')"
            ),
            {"cid": payload.client_id},
        ).first()
        return int(row[0]) if row else 0

    queue_count = DatabaseManager.execute_transaction(_queue)
    queue_minutes = queue_count * 5  # 5 min overhead per queued delivery order

    eta_minutes = prep_minutes + travel_minutes + queue_minutes

    log_info(f"[PUBLIC] freight: client={payload.client_id} dist={distance_km:.1f}km fee={freight_value} eta={eta_minutes}min")
    return {
        "distance_km": round(distance_km, 2),
        "freight_value": freight_value,
        "travel_minutes": travel_minutes,
        "prep_minutes": prep_minutes,
        "queue_minutes": queue_minutes,
        "eta_minutes": eta_minutes,
    }


# ─── CEP lookup proxy ──────────────────────────────────────────────────────────

@public_menu_router.get("/cep/{cep}")
async def lookup_cep(cep: str):
    """Proxy ViaCEP to avoid browser CSP blocks."""
    import httpx
    digits = cep.replace("-", "").replace(".", "").strip()
    if len(digits) != 8 or not digits.isdigit():
        raise HTTPException(status_code=400, detail="CEP inválido")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"https://viacep.com.br/ws/{digits}/json/")
        data = resp.json()
        if data.get("erro"):
            raise HTTPException(status_code=404, detail="CEP não encontrado")
        return data
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"[PUBLIC] cep lookup error: {e}")
        raise HTTPException(status_code=503, detail="Serviço de CEP indisponível")
