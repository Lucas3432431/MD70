# -*- coding: utf-8 -*-
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from App.Core.Cache.RedisCache import cache_delete, cache_get, cache_set
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Logs import error as log_error
from App.Core.Services.Auth.RequestAuth import get_client_id_from_request

stock_router = APIRouter(tags=["Stock"], prefix="/api/stock")

_TTL = 300  # 5 min
_TXN_TTL = 120  # 2 min


def _key(client_id: str, kind: str) -> str:
    return f"stock:{client_id}:{kind}"


def _bust_items(client_id: str) -> None:
    cache_delete(_key(client_id, "items"))
    cache_delete(f"menu:{client_id}:stock_items")
    cache_delete(f"menu:{client_id}:stock_products")
    # Stock change may flip product availability in the public menu
    cache_delete(f"pub_menu:{client_id}:products")
    cache_delete(f"pub_menu:{client_id}:stock_products")


# ─── Schemas ──────────────────────────────────────────────────────────────────


class StockItemCreate(BaseModel):
    name: str
    emoji: Optional[str] = None
    unit: str = "un"
    category: Optional[str] = None
    min_stock: float = 0
    phase: str = "ok"


class StockItemUpdate(BaseModel):
    name: Optional[str] = None
    emoji: Optional[str] = None
    unit: Optional[str] = None
    category: Optional[str] = None
    min_stock: Optional[float] = None
    phase: Optional[str] = None
    cost_per_unit: Optional[float] = None
    quantity: Optional[float] = None


class PurchaseCreate(BaseModel):
    stock_item_id: int
    quantity: float
    total_cost: float = 0
    expiry_date: Optional[str] = None
    note: Optional[str] = None


class LossCreate(BaseModel):
    stock_item_id: int
    quantity: float
    note: Optional[str] = None


# ─── Categories ───────────────────────────────────────────────────────────────


@stock_router.get("/categories")
async def list_stock_categories(request: Request):
    client_id = get_client_id_from_request(request)
    key = _key(client_id, "categories")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _query(session):
        from sqlalchemy import text
        rows = session.execute(
            text(
                "SELECT id, name, type, sort_order FROM pdv_categories"
                " WHERE client_id = :cid AND type = 'stock_supply'"
                " ORDER BY type, sort_order"
            ),
            {"cid": client_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    result = DatabaseManager.execute_transaction(_query)
    cache_set(key, result, _TTL)
    return result


# ─── Items ────────────────────────────────────────────────────────────────────


@stock_router.get("/items")
async def list_items(request: Request, filter_by: str = ""):
    client_id = get_client_id_from_request(request)
    key = _key(client_id, f"items:{filter_by}")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _query(session):
        from sqlalchemy import text
        where = "WHERE client_id = :cid"
        if filter_by == "below_min":
            where += " AND (quantity <= 0 OR (min_stock IS NOT NULL AND quantity < min_stock))"
        rows = session.execute(
            text(
                "SELECT id, name, emoji, unit, category,"
                " quantity, min_stock, cost_per_unit, expiry_date, phase, created_at"
                f" FROM pdv_stock_items {where}"
                " ORDER BY category, name"
            ),
            {"cid": client_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    result = DatabaseManager.execute_transaction(_query)
    ttl = 15 if filter_by == "below_min" else _TTL
    cache_set(key, result, ttl)
    return result


@stock_router.get("/items/by-ids")
async def get_items_by_ids(request: Request, ids: str = ""):
    client_id = get_client_id_from_request(request)
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    if not id_list:
        return []

    def _query(session):
        from sqlalchemy import text
        placeholders = ",".join(f":id{i}" for i in range(len(id_list)))
        params: dict = {f"id{i}": v for i, v in enumerate(id_list)}
        params["cid"] = client_id
        rows = session.execute(
            text(
                f"SELECT id, name, emoji, unit, category,"
                f" quantity, min_stock, cost_per_unit, expiry_date, phase"
                f" FROM pdv_stock_items WHERE client_id = :cid AND id IN ({placeholders})"
            ),
            params,
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    return DatabaseManager.execute_transaction(_query)


@stock_router.post("/items")
async def create_item(payload: StockItemCreate, request: Request):
    client_id = get_client_id_from_request(request)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome vazio")

    def _insert(session):
        from sqlalchemy import text
        session.execute(
            text(
                "INSERT INTO pdv_stock_items"
                " (client_id, name, emoji, unit, category, quantity, min_stock, phase)"
                " VALUES (:cid, :name, :emoji, :unit, :cat, 0, :min_s, :phase)"
            ),
            {
                "cid": client_id,
                "name": name,
                "emoji": payload.emoji,
                "unit": payload.unit,
                "cat": payload.category,
                "min_s": payload.min_stock,
                "phase": payload.phase,
            },
        )
        row = session.execute(
            text(
                "SELECT id, name, emoji, unit, category,"
                " quantity, min_stock, cost_per_unit, expiry_date, phase, created_at"
                " FROM pdv_stock_items WHERE client_id = :cid AND name = :name ORDER BY id DESC LIMIT 1"
            ),
            {"cid": client_id, "name": name},
        ).first()
        return dict(row._mapping) if row else {}

    try:
        result = DatabaseManager.execute_transaction(_insert)
        _bust_items(client_id)
        return result
    except Exception as e:
        log_error(f"[STOCK] create_item: {e}")
        raise HTTPException(status_code=500, detail="Erro ao criar item")


@stock_router.patch("/items/{item_id}")
async def update_item(item_id: int, payload: StockItemUpdate, request: Request):
    client_id = get_client_id_from_request(request)
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)

    def _update(session):
        from sqlalchemy import text
        result = session.execute(
            text(f"UPDATE pdv_stock_items SET {set_clause}, updated_at = CURRENT_TIMESTAMP"
                 f" WHERE id = :id AND client_id = :cid"),
            {**updates, "id": item_id, "cid": client_id},
        )
        if result.rowcount == 0:
            return None
        row = session.execute(
            text(
                "SELECT id, name, emoji, unit, category,"
                " quantity, min_stock, cost_per_unit, expiry_date, phase, created_at"
                " FROM pdv_stock_items WHERE id = :id"
            ),
            {"id": item_id},
        ).first()
        return dict(row._mapping) if row else None

    result = DatabaseManager.execute_transaction(_update)
    if result is None:
        raise HTTPException(status_code=404, detail="Item não encontrado")
    _bust_items(client_id)
    return result


@stock_router.delete("/items/{item_id}")
async def delete_item(item_id: int, request: Request):
    client_id = get_client_id_from_request(request)

    def _delete(session):
        from sqlalchemy import text
        r = session.execute(
            text("DELETE FROM pdv_stock_items WHERE id = :id AND client_id = :cid"),
            {"id": item_id, "cid": client_id},
        )
        return r.rowcount

    count = DatabaseManager.execute_transaction(_delete)
    if count == 0:
        raise HTTPException(status_code=404, detail="Item não encontrado")
    _bust_items(client_id)
    return {"ok": True}


# ─── Transactions ─────────────────────────────────────────────────────────────


@stock_router.post("/transactions/purchase")
async def create_purchase(payload: PurchaseCreate, request: Request):
    client_id = get_client_id_from_request(request)
    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantidade inválida")

    def _purchase(session):
        from sqlalchemy import text
        row = session.execute(
            text("SELECT id, quantity, cost_per_unit FROM pdv_stock_items WHERE id = :id AND client_id = :cid"),
            {"id": payload.stock_item_id, "cid": client_id},
        ).first()
        if not row:
            return None

        new_qty = float(row[1]) + payload.quantity
        new_cost = (payload.total_cost / payload.quantity) if payload.quantity > 0 and payload.total_cost > 0 else float(row[2])

        session.execute(
            text(
                "UPDATE pdv_stock_items SET quantity = :qty, cost_per_unit = :cost,"
                " expiry_date = COALESCE(:exp, expiry_date), updated_at = CURRENT_TIMESTAMP"
                " WHERE id = :id AND client_id = :cid"
            ),
            {"qty": new_qty, "cost": new_cost, "exp": payload.expiry_date,
             "id": payload.stock_item_id, "cid": client_id},
        )
        session.execute(
            text(
                "INSERT INTO pdv_stock_transactions"
                " (client_id, stock_item_id, type, quantity, total_cost, expiry_date, note)"
                " VALUES (:cid, :sid, 'purchase', :qty, :cost, :exp, :note)"
            ),
            {"cid": client_id, "sid": payload.stock_item_id,
             "qty": payload.quantity, "cost": payload.total_cost if payload.total_cost > 0 else None,
             "exp": payload.expiry_date, "note": payload.note},
        )
        updated = session.execute(
            text(
                "SELECT id, name, emoji, unit, category,"
                " quantity, min_stock, cost_per_unit, expiry_date, phase"
                " FROM pdv_stock_items WHERE id = :id"
            ),
            {"id": payload.stock_item_id},
        ).first()
        return dict(updated._mapping) if updated else None

    result = DatabaseManager.execute_transaction(_purchase)
    if result is None:
        raise HTTPException(status_code=404, detail="Item não encontrado")
    _bust_items(client_id)
    cache_delete(_key(client_id, f"txns:{payload.stock_item_id}"))
    return result


@stock_router.post("/transactions/loss")
async def create_loss(payload: LossCreate, request: Request):
    client_id = get_client_id_from_request(request)
    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantidade inválida")

    def _loss(session):
        from sqlalchemy import text
        row = session.execute(
            text("SELECT id, quantity, cost_per_unit FROM pdv_stock_items WHERE id = :id AND client_id = :cid"),
            {"id": payload.stock_item_id, "cid": client_id},
        ).first()
        if not row:
            return None

        new_qty = max(0.0, float(row[1]) - payload.quantity)
        session.execute(
            text(
                "UPDATE pdv_stock_items SET quantity = :qty, updated_at = CURRENT_TIMESTAMP"
                " WHERE id = :id AND client_id = :cid"
            ),
            {"qty": new_qty, "id": payload.stock_item_id, "cid": client_id},
        )
        session.execute(
            text(
                "INSERT INTO pdv_stock_transactions"
                " (client_id, stock_item_id, type, quantity, note)"
                " VALUES (:cid, :sid, 'loss', :qty, :note)"
            ),
            {"cid": client_id, "sid": payload.stock_item_id,
             "qty": payload.quantity, "note": payload.note},
        )
        updated = session.execute(
            text(
                "SELECT id, name, emoji, unit, category,"
                " quantity, min_stock, cost_per_unit, expiry_date, phase"
                " FROM pdv_stock_items WHERE id = :id"
            ),
            {"id": payload.stock_item_id},
        ).first()
        return dict(updated._mapping) if updated else None

    result = DatabaseManager.execute_transaction(_loss)
    if result is None:
        raise HTTPException(status_code=404, detail="Item não encontrado")
    _bust_items(client_id)
    cache_delete(_key(client_id, f"txns:{payload.stock_item_id}"))
    return result


@stock_router.get("/transactions/{item_id}")
async def list_transactions(item_id: int, request: Request):
    client_id = get_client_id_from_request(request)
    key = _key(client_id, f"txns:{item_id}")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _query(session):
        from sqlalchemy import text
        row = session.execute(
            text("SELECT 1 FROM pdv_stock_items WHERE id = :id AND client_id = :cid"),
            {"id": item_id, "cid": client_id},
        ).first()
        if not row:
            return None
        rows = session.execute(
            text(
                "SELECT id, stock_item_id, type, quantity, total_cost, expiry_date, note, created_at"
                " FROM pdv_stock_transactions WHERE stock_item_id = :id ORDER BY created_at DESC"
            ),
            {"id": item_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    result = DatabaseManager.execute_transaction(_query)
    if result is None:
        raise HTTPException(status_code=404, detail="Item não encontrado")
    cache_set(key, result, _TXN_TTL)
    return result
