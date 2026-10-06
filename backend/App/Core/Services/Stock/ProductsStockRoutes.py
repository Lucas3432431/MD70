# -*- coding: utf-8 -*-
from typing import Optional
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from App.Core.Cache.RedisCache import cache_delete, cache_get, cache_set
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Logs import error as log_error
from App.Core.Services.Auth.RequestAuth import get_client_id_from_request

products_stock_router = APIRouter(tags=["ProductsStock"], prefix="/api/products-stock")

_TTL = 300   # 5 min
_TXN_TTL = 120  # 2 min


def _key(client_id: str, kind: str) -> str:
    return f"pstock:{client_id}:{kind}"


def _bust(client_id: str, product_id: Optional[int] = None) -> None:
    cache_delete(_key(client_id, "items"))
    cache_delete(f"menu:{client_id}:stock_products")
    cache_delete(f"menu:{client_id}:products")
    cache_delete(f"menu:{client_id}:purchases:today")
    cache_delete(f"menu:{client_id}:purchases:all")
    if product_id is not None:
        cache_delete(_key(client_id, f"txns:{product_id}"))


# ─── Schemas ──────────────────────────────────────────────────────────────────


class StockUpsert(BaseModel):
    product_id: int
    unit: str = "un"
    min_stock: float = 0
    quantity: float = 0


class PurchaseCreate(BaseModel):
    product_id: int
    quantity: float
    total_cost: float = 0
    expiry_date: Optional[str] = None
    payment_method: Optional[str] = None
    invoice_id: Optional[str] = None
    invoice_path: Optional[str] = None
    note: Optional[str] = None


class LossCreate(BaseModel):
    product_id: int
    quantity: float
    loss_reason: Optional[str] = None
    photo_path: Optional[str] = None
    note: Optional[str] = None


class VerifyTransaction(BaseModel):
    status: str  # verified | rejected
    verification_note: Optional[str] = None
    verified_by: Optional[str] = None


# ─── Stock Items ──────────────────────────────────────────────────────────────


@products_stock_router.get("/items")
async def list_product_stocks(request: Request):
    client_id = get_client_id_from_request(request)
    key = _key(client_id, "items")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _query(session):
        from sqlalchemy import text
        rows = session.execute(
            text(
                "SELECT ps.id, ps.product_id, ps.unit, ps.min_stock, ps.quantity,"
                " ps.cost_per_unit, ps.created_at, ps.updated_at,"
                " p.name, p.emoji, p.category, p.price, p.production_type"
                " FROM products_stock ps"
                " JOIN pdv_products p ON p.id = ps.product_id"
                " WHERE ps.client_id = :cid"
                " ORDER BY p.category, p.name"
            ),
            {"cid": client_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    result = DatabaseManager.execute_transaction(_query)
    cache_set(key, result, _TTL)
    return result


@products_stock_router.get("/items/{product_id}")
async def get_product_stock(product_id: int, request: Request):
    client_id = get_client_id_from_request(request)

    def _query(session):
        from sqlalchemy import text
        row = session.execute(
            text(
                "SELECT ps.id, ps.product_id, ps.unit, ps.min_stock, ps.quantity,"
                " ps.cost_per_unit, ps.created_at, ps.updated_at,"
                " p.name, p.emoji, p.category, p.price, p.production_type"
                " FROM products_stock ps"
                " JOIN pdv_products p ON p.id = ps.product_id"
                " WHERE ps.client_id = :cid AND ps.product_id = :pid"
            ),
            {"cid": client_id, "pid": product_id},
        ).first()
        return dict(row._mapping) if row else None

    result = DatabaseManager.execute_transaction(_query)
    if result is None:
        raise HTTPException(status_code=404, detail="Estoque não encontrado")
    return result


@products_stock_router.put("/items")
async def upsert_product_stock(payload: StockUpsert, request: Request):
    client_id = get_client_id_from_request(request)

    def _upsert(session):
        from sqlalchemy import text
        session.execute(
            text(
                "INSERT INTO products_stock (client_id, product_id, unit, min_stock, quantity)"
                " VALUES (:cid, :pid, :unit, :min_s, :qty)"
                " ON CONFLICT(client_id, product_id) DO UPDATE SET"
                " unit = excluded.unit,"
                " min_stock = excluded.min_stock,"
                " quantity = excluded.quantity,"
                " updated_at = CURRENT_TIMESTAMP"
            ),
            {
                "cid": client_id,
                "pid": payload.product_id,
                "unit": payload.unit,
                "min_s": payload.min_stock,
                "qty": payload.quantity,
            },
        )
        row = session.execute(
            text(
                "SELECT ps.id, ps.product_id, ps.unit, ps.min_stock, ps.quantity,"
                " ps.cost_per_unit, ps.created_at, ps.updated_at,"
                " p.name, p.emoji, p.category, p.price, p.production_type"
                " FROM products_stock ps"
                " JOIN pdv_products p ON p.id = ps.product_id"
                " WHERE ps.client_id = :cid AND ps.product_id = :pid"
            ),
            {"cid": client_id, "pid": payload.product_id},
        ).first()
        return dict(row._mapping) if row else {}

    try:
        result = DatabaseManager.execute_transaction(_upsert)
        _bust(client_id)
        return result
    except Exception as e:
        log_error(f"[PSTOCK] upsert: {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar estoque")


# ─── Transactions ─────────────────────────────────────────────────────────────


@products_stock_router.post("/transactions/purchase")
async def create_purchase(payload: PurchaseCreate, request: Request):
    client_id = get_client_id_from_request(request)
    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantidade inválida")

    invoice_id = payload.invoice_id or str(uuid.uuid4())

    def _purchase(session):
        from sqlalchemy import text

        # Ensure stock row exists; read current qty + cpu for WAC
        existing = session.execute(
            text("SELECT quantity, cost_per_unit FROM products_stock WHERE client_id = :cid AND product_id = :pid"),
            {"cid": client_id, "pid": payload.product_id},
        ).first()
        if existing is None:
            session.execute(
                text(
                    "INSERT INTO products_stock (client_id, product_id, unit, min_stock, quantity, cost_per_unit)"
                    " VALUES (:cid, :pid, 'un', 0, 0, 0)"
                ),
                {"cid": client_id, "pid": payload.product_id},
            )
            current_qty = 0.0
            current_cpu = 0.0
        else:
            current_qty = float(existing[0] or 0)
            current_cpu = float(existing[1] or 0)

        new_qty = current_qty + payload.quantity

        # WAC: (cpu_atual × qty_atual + custo_compra) / qty_total_pós_compra
        if payload.total_cost > 0 and new_qty > 0:
            new_cpu = (current_cpu * current_qty + payload.total_cost) / new_qty
        else:
            new_cpu = current_cpu  # no cost info: keep previous WAC

        # Unit cost for this purchase batch
        purchase_unit_cost = (payload.total_cost / payload.quantity) if payload.quantity > 0 and payload.total_cost > 0 else None

        session.execute(
            text(
                "UPDATE products_stock SET quantity = :qty, cost_per_unit = :cpu,"
                " updated_at = CURRENT_TIMESTAMP"
                " WHERE client_id = :cid AND product_id = :pid"
            ),
            {"qty": new_qty, "cpu": new_cpu, "cid": client_id, "pid": payload.product_id},
        )
        session.execute(
            text("UPDATE pdv_products SET stock_quantity = :qty WHERE id = :pid AND client_id = :cid"),
            {"qty": new_qty, "pid": payload.product_id, "cid": client_id},
        )

        session.execute(
            text(
                "INSERT INTO products_stock_transactions"
                " (client_id, product_id, type, quantity, total_cost, unit_cost,"
                "  expiry_date, payment_method, invoice_id, invoice_path, note)"
                " VALUES (:cid, :pid, 'compra', :qty, :cost, :ucost,"
                "  :exp, :pay, :inv_id, :inv_path, :note)"
            ),
            {
                "cid": client_id,
                "pid": payload.product_id,
                "qty": payload.quantity,
                "cost": payload.total_cost if payload.total_cost > 0 else None,
                "ucost": purchase_unit_cost,
                "exp": payload.expiry_date,
                "pay": payload.payment_method,
                "inv_id": invoice_id,
                "inv_path": payload.invoice_path,
                "note": payload.note,
            },
        )

        # Record as expense outflow
        if payload.total_cost > 0:
            # Fetch product name for description
            prod = session.execute(
                text("SELECT name FROM pdv_products WHERE id = :pid"),
                {"pid": payload.product_id},
            ).first()
            desc = f"Compra: {prod[0]}" if prod else f"Compra produto #{payload.product_id}"
            session.execute(
                text(
                    "INSERT INTO pdv_expense_transactions"
                    " (client_id, source_type, source_id, description, amount, payment_method)"
                    " VALUES (:cid, 'product_purchase', :pid, :desc, :amt, :pay)"
                ),
                {
                    "cid": client_id,
                    "pid": payload.product_id,
                    "desc": desc,
                    "amt": payload.total_cost,
                    "pay": payload.payment_method,
                },
            )

        row = session.execute(
            text(
                "SELECT ps.id, ps.product_id, ps.unit, ps.min_stock, ps.quantity,"
                " p.name, p.emoji, p.production_type"
                " FROM products_stock ps"
                " JOIN pdv_products p ON p.id = ps.product_id"
                " WHERE ps.client_id = :cid AND ps.product_id = :pid"
            ),
            {"cid": client_id, "pid": payload.product_id},
        ).first()
        return dict(row._mapping) if row else {}

    try:
        result = DatabaseManager.execute_transaction(_purchase)
        _bust(client_id, payload.product_id)
        return result
    except Exception as e:
        log_error(f"[PSTOCK] purchase: {e}")
        raise HTTPException(status_code=500, detail="Erro ao registrar compra")


@products_stock_router.post("/transactions/loss")
async def create_loss(payload: LossCreate, request: Request):
    client_id = get_client_id_from_request(request)
    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantidade inválida")

    def _loss(session):
        from sqlalchemy import text

        existing = session.execute(
            text("SELECT quantity, cost_per_unit FROM products_stock WHERE client_id = :cid AND product_id = :pid"),
            {"cid": client_id, "pid": payload.product_id},
        ).first()
        if existing is None:
            return None

        current_qty = float(existing[0] or 0)
        current_cpu = float(existing[1] or 0)
        new_qty = max(0.0, current_qty - payload.quantity)

        session.execute(
            text(
                "UPDATE products_stock SET quantity = :qty, updated_at = CURRENT_TIMESTAMP"
                " WHERE client_id = :cid AND product_id = :pid"
            ),
            {"qty": new_qty, "cid": client_id, "pid": payload.product_id},
        )
        session.execute(
            text("UPDATE pdv_products SET stock_quantity = :qty WHERE id = :pid AND client_id = :cid"),
            {"qty": new_qty, "pid": payload.product_id, "cid": client_id},
        )

        session.execute(
            text(
                "INSERT INTO products_stock_transactions"
                " (client_id, product_id, type, quantity, unit_cost, loss_reason, photo_path, note)"
                " VALUES (:cid, :pid, 'perda', :qty, :ucost, :reason, :photo, :note)"
            ),
            {
                "cid": client_id,
                "pid": payload.product_id,
                "qty": payload.quantity,
                "ucost": current_cpu if current_cpu > 0 else None,
                "reason": payload.loss_reason,
                "photo": payload.photo_path,
                "note": payload.note,
            },
        )

        row = session.execute(
            text(
                "SELECT ps.id, ps.product_id, ps.unit, ps.min_stock, ps.quantity,"
                " p.name, p.emoji, p.production_type"
                " FROM products_stock ps"
                " JOIN pdv_products p ON p.id = ps.product_id"
                " WHERE ps.client_id = :cid AND ps.product_id = :pid"
            ),
            {"cid": client_id, "pid": payload.product_id},
        ).first()
        return dict(row._mapping) if row else {}

    try:
        result = DatabaseManager.execute_transaction(_loss)
        if result is None:
            raise HTTPException(status_code=404, detail="Estoque não encontrado")
        _bust(client_id, payload.product_id)
        return result
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"[PSTOCK] loss: {e}")
        raise HTTPException(status_code=500, detail="Erro ao registrar perda")


@products_stock_router.get("/transactions/{product_id}")
async def list_transactions(product_id: int, request: Request):
    client_id = get_client_id_from_request(request)
    key = _key(client_id, f"txns:{product_id}")
    cached = cache_get(key)
    if cached is not None:
        return cached

    def _query(session):
        from sqlalchemy import text
        rows = session.execute(
            text(
                "SELECT id, product_id, type, quantity, total_cost,"
                " expiry_date, payment_method, invoice_id, invoice_path,"
                " loss_reason, photo_path, status, verified_by, verified_at,"
                " verification_note, note, created_by, created_at"
                " FROM products_stock_transactions"
                " WHERE client_id = :cid AND product_id = :pid"
                " ORDER BY created_at DESC"
            ),
            {"cid": client_id, "pid": product_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    result = DatabaseManager.execute_transaction(_query)
    cache_set(key, result, _TXN_TTL)
    return result


@products_stock_router.patch("/transactions/{txn_id}/verify")
async def verify_transaction(txn_id: int, payload: VerifyTransaction, request: Request):
    client_id = get_client_id_from_request(request)
    if payload.status not in ("verified", "rejected"):
        raise HTTPException(status_code=400, detail="Status inválido")

    def _verify(session):
        from sqlalchemy import text
        r = session.execute(
            text(
                "UPDATE products_stock_transactions"
                " SET status = :status,"
                "     verified_by = :by,"
                "     verified_at = CURRENT_TIMESTAMP,"
                "     verification_note = :note,"
                "     updated_at = CURRENT_TIMESTAMP"
                " WHERE id = :id AND client_id = :cid"
            ),
            {
                "status": payload.status,
                "by": payload.verified_by,
                "note": payload.verification_note,
                "id": txn_id,
                "cid": client_id,
            },
        )
        if r.rowcount == 0:
            return None
        row = session.execute(
            text(
                "SELECT id, product_id, type, quantity, total_cost, status,"
                " verified_by, verified_at, verification_note, created_at"
                " FROM products_stock_transactions WHERE id = :id"
            ),
            {"id": txn_id},
        ).first()
        return dict(row._mapping) if row else None

    result = DatabaseManager.execute_transaction(_verify)
    if result is None:
        raise HTTPException(status_code=404, detail="Lançamento não encontrado")
    # Bust txn cache for the product
    if result.get("product_id"):
        cache_delete(_key(client_id, f"txns:{result['product_id']}"))
    return result


@products_stock_router.delete("/transactions/{txn_id}")
async def delete_transaction(txn_id: int, request: Request):
    client_id = get_client_id_from_request(request)

    def _delete(session):
        from sqlalchemy import text

        row = session.execute(
            text(
                "SELECT product_id, type, quantity FROM products_stock_transactions"
                " WHERE id = :id AND client_id = :cid"
            ),
            {"id": txn_id, "cid": client_id},
        ).first()
        if row is None:
            return None

        product_id = row[0]
        txn_type = row[1]
        quantity = float(row[2] or 0)

        # Reverse quantity impact (venda qty managed by order system — skip)
        if txn_type == "compra":
            qty_delta = -quantity
        elif txn_type == "perda":
            qty_delta = quantity
        else:
            qty_delta = 0

        if qty_delta != 0:
            session.execute(
                text(
                    "UPDATE products_stock"
                    " SET quantity = MAX(0, quantity + :delta), updated_at = CURRENT_TIMESTAMP"
                    " WHERE client_id = :cid AND product_id = :pid"
                ),
                {"delta": qty_delta, "cid": client_id, "pid": product_id},
            )
            session.execute(
                text(
                    "UPDATE pdv_products"
                    " SET stock_quantity = MAX(0, COALESCE(stock_quantity, 0) + :delta)"
                    " WHERE id = :pid AND client_id = :cid"
                ),
                {"delta": qty_delta, "pid": product_id, "cid": client_id},
            )

        session.execute(
            text("DELETE FROM products_stock_transactions WHERE id = :id AND client_id = :cid"),
            {"id": txn_id, "cid": client_id},
        )
        return product_id

    product_id = DatabaseManager.execute_transaction(_delete)
    if product_id is None:
        raise HTTPException(status_code=404, detail="Lançamento não encontrado")
    _bust(client_id, product_id)
    return {"ok": True}
