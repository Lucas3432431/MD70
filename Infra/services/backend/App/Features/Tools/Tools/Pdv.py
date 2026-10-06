"""
Tools: pdv_menu, pdv_stock, pdv_orders, pdv_settings
Gerenciamento do PDV (cardápio, estoque, pedidos, configurações da loja).
"""

import json
import uuid
from datetime import datetime
from typing import Any, Dict

from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager

# ─────────────────────────────────────────────
# pdv_menu
# ─────────────────────────────────────────────

def execute_pdv_menu(args: Dict[str, Any], client_id: str) -> str:
    if not client_id:
        return json.dumps({"success": False, "error": "client_id não encontrado para o usuário."})

    action = (args.get("action") or "").strip()

    try:
        if action == "list_products":
            category = args.get("category")
            available = args.get("available")
            query = "SELECT * FROM pdv_products WHERE client_id = :cid"
            params: Dict[str, Any] = {"cid": client_id}
            if category:
                query += " AND category = :cat"
                params["cat"] = category
            if available is not None:
                query += " AND available = :av"
                params["av"] = 1 if available else 0
            query += " ORDER BY category, name"
            rows = DatabaseManager.fetch_all(query, params) or []
            return json.dumps({"success": True, "products": [dict(r) for r in rows], "total": len(rows)}, ensure_ascii=False, default=str)

        elif action == "get_product":
            product_id = args.get("product_id")
            sku_id = args.get("sku_id")
            if product_id:
                row = DatabaseManager.fetch_one(
                    "SELECT * FROM pdv_products WHERE client_id = :cid AND id = :pid",
                    {"cid": client_id, "pid": product_id},
                )
            elif sku_id:
                row = DatabaseManager.fetch_one(
                    "SELECT * FROM pdv_products WHERE client_id = :cid AND sku_id = :sid",
                    {"cid": client_id, "sid": sku_id},
                )
            else:
                return json.dumps({"success": False, "error": "Informe product_id ou sku_id."})
            if not row:
                return json.dumps({"success": False, "error": "Produto não encontrado."})
            return json.dumps({"success": True, "product": dict(row)}, ensure_ascii=False, default=str)

        elif action == "create_product":
            name = args.get("name")
            price = args.get("price")
            category = args.get("category", "Geral")
            if not name or price is None:
                return json.dumps({"success": False, "error": "name e price são obrigatórios."})
            sku_id = args.get("sku_id") or str(uuid.uuid4())[:8].upper()
            DatabaseManager.execute_query(
                """INSERT INTO pdv_products
                   (client_id, sku_id, name, price, category, available, emoji, description,
                    price_delivery, price_ifood, price_99, created_at, updated_at)
                   VALUES (:cid, :sku, :name, :price, :cat, :av, :emoji, :desc,
                           :pd, :pif, :p99, :now, :now)""",
                {
                    "cid": client_id,
                    "sku": sku_id,
                    "name": name,
                    "price": float(price),
                    "cat": category,
                    "av": 1 if args.get("available", True) else 0,
                    "emoji": args.get("emoji"),
                    "desc": args.get("description"),
                    "pd": args.get("price_delivery"),
                    "pif": args.get("price_ifood"),
                    "p99": args.get("price_99"),
                    "now": datetime.utcnow(),
                },
            )
            row = DatabaseManager.fetch_one(
                "SELECT * FROM pdv_products WHERE client_id = :cid AND sku_id = :sku ORDER BY id DESC LIMIT 1",
                {"cid": client_id, "sku": sku_id},
            )
            return json.dumps({"success": True, "product": dict(row) if row else None}, ensure_ascii=False, default=str)

        elif action == "update_product":
            product_id = args.get("product_id")
            sku_id = args.get("sku_id")
            if not product_id and not sku_id:
                return json.dumps({"success": False, "error": "Informe product_id ou sku_id."})

            if product_id:
                existing = DatabaseManager.fetch_one(
                    "SELECT * FROM pdv_products WHERE client_id = :cid AND id = :pid",
                    {"cid": client_id, "pid": product_id},
                )
            else:
                existing = DatabaseManager.fetch_one(
                    "SELECT * FROM pdv_products WHERE client_id = :cid AND sku_id = :sid",
                    {"cid": client_id, "sid": sku_id},
                )
            if not existing:
                return json.dumps({"success": False, "error": "Produto não encontrado."})

            updatable = ["name", "price", "category", "available", "emoji", "description",
                         "price_delivery", "price_ifood", "price_99"]
            sets = []
            params2: Dict[str, Any] = {"cid": client_id, "pid": existing["id"], "now": datetime.utcnow()}
            for field in updatable:
                if field in args:
                    sets.append(f"{field} = :{field}")
                    val = args[field]
                    if field == "available":
                        val = 1 if val else 0
                    params2[field] = val
            if not sets:
                return json.dumps({"success": False, "error": "Nenhum campo para atualizar."})
            sets.append("updated_at = :now")
            DatabaseManager.execute_query(
                f"UPDATE pdv_products SET {', '.join(sets)} WHERE client_id = :cid AND id = :pid",
                params2,
            )
            row = DatabaseManager.fetch_one(
                "SELECT * FROM pdv_products WHERE client_id = :cid AND id = :pid",
                {"cid": client_id, "pid": existing["id"]},
            )
            return json.dumps({"success": True, "product": dict(row) if row else None}, ensure_ascii=False, default=str)

        elif action == "list_categories":
            rows = DatabaseManager.fetch_all(
                "SELECT * FROM pdv_categories WHERE client_id = :cid ORDER BY sort_order, name",
                {"cid": client_id},
            ) or []
            return json.dumps({"success": True, "categories": [dict(r) for r in rows]}, ensure_ascii=False, default=str)

        elif action == "create_category":
            name = args.get("name")
            if not name:
                return json.dumps({"success": False, "error": "name é obrigatório."})
            sort_order = args.get("sort_order", 0)
            cat_type = args.get("type", "product")
            DatabaseManager.execute_query(
                "INSERT INTO pdv_categories (client_id, name, sort_order, type, created_at) VALUES (:cid, :name, :so, :type, :now)",
                {"cid": client_id, "name": name, "so": sort_order, "type": cat_type, "now": datetime.utcnow()},
            )
            row = DatabaseManager.fetch_one(
                "SELECT * FROM pdv_categories WHERE client_id = :cid AND name = :name ORDER BY id DESC LIMIT 1",
                {"cid": client_id, "name": name},
            )
            return json.dumps({"success": True, "category": dict(row) if row else None}, ensure_ascii=False, default=str)

        else:
            return json.dumps({
                "success": False,
                "error": f"Ação desconhecida: '{action}'",
                "available_actions": ["list_products", "get_product", "create_product", "update_product", "list_categories", "create_category"],
            })

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


# ─────────────────────────────────────────────
# pdv_stock
# ─────────────────────────────────────────────

def execute_pdv_stock(args: Dict[str, Any], client_id: str) -> str:
    if not client_id:
        return json.dumps({"success": False, "error": "client_id não encontrado para o usuário."})

    action = (args.get("action") or "").strip()

    try:
        if action == "list_items":
            category = args.get("category")
            below_min = args.get("below_min")
            query = "SELECT * FROM pdv_stock_items WHERE client_id = :cid"
            params: Dict[str, Any] = {"cid": client_id}
            if category:
                query += " AND category = :cat"
                params["cat"] = category
            if below_min:
                query += " AND quantity < min_stock"
            query += " ORDER BY category, name"
            rows = DatabaseManager.fetch_all(query, params) or []
            return json.dumps({"success": True, "items": [dict(r) for r in rows], "total": len(rows)}, ensure_ascii=False, default=str)

        elif action == "get_item":
            item_id = args.get("item_id")
            if not item_id:
                return json.dumps({"success": False, "error": "item_id é obrigatório."})
            row = DatabaseManager.fetch_one(
                "SELECT * FROM pdv_stock_items WHERE client_id = :cid AND id = :id",
                {"cid": client_id, "id": item_id},
            )
            if not row:
                return json.dumps({"success": False, "error": "Item não encontrado."})
            return json.dumps({"success": True, "item": dict(row)}, ensure_ascii=False, default=str)

        elif action == "create_item":
            name = args.get("name")
            unit = args.get("unit", "un")
            if not name:
                return json.dumps({"success": False, "error": "name é obrigatório."})
            DatabaseManager.execute_query(
                """INSERT INTO pdv_stock_items
                   (client_id, name, emoji, unit, category, item_type, quantity, min_stock, cost_per_unit, expiry_date, phase, created_at, updated_at)
                   VALUES (:cid, :name, :emoji, :unit, :cat, :itype, :qty, :min, :cost, :exp, :phase, :now, :now)""",
                {
                    "cid": client_id,
                    "name": name,
                    "emoji": args.get("emoji"),
                    "unit": unit,
                    "cat": args.get("category"),
                    "itype": args.get("item_type", "supply"),
                    "qty": float(args.get("quantity", 0)),
                    "min": float(args.get("min_stock", 0)),
                    "cost": float(args.get("cost_per_unit", 0)),
                    "exp": args.get("expiry_date"),
                    "phase": args.get("phase", "ok"),
                    "now": datetime.utcnow(),
                },
            )
            row = DatabaseManager.fetch_one(
                "SELECT * FROM pdv_stock_items WHERE client_id = :cid AND name = :name ORDER BY id DESC LIMIT 1",
                {"cid": client_id, "name": name},
            )
            return json.dumps({"success": True, "item": dict(row) if row else None}, ensure_ascii=False, default=str)

        elif action == "update_item":
            item_id = args.get("item_id")
            if not item_id:
                return json.dumps({"success": False, "error": "item_id é obrigatório."})
            existing = DatabaseManager.fetch_one(
                "SELECT * FROM pdv_stock_items WHERE client_id = :cid AND id = :id",
                {"cid": client_id, "id": item_id},
            )
            if not existing:
                return json.dumps({"success": False, "error": "Item não encontrado."})
            updatable = ["name", "emoji", "unit", "category", "item_type", "min_stock", "cost_per_unit", "expiry_date", "phase"]
            sets = []
            params2: Dict[str, Any] = {"cid": client_id, "id": item_id, "now": datetime.utcnow()}
            for field in updatable:
                if field in args:
                    sets.append(f"{field} = :{field}")
                    params2[field] = args[field]
            if not sets:
                return json.dumps({"success": False, "error": "Nenhum campo para atualizar."})
            sets.append("updated_at = :now")
            DatabaseManager.execute_query(
                f"UPDATE pdv_stock_items SET {', '.join(sets)} WHERE client_id = :cid AND id = :id",
                params2,
            )
            row = DatabaseManager.fetch_one(
                "SELECT * FROM pdv_stock_items WHERE client_id = :cid AND id = :id",
                {"cid": client_id, "id": item_id},
            )
            return json.dumps({"success": True, "item": dict(row) if row else None}, ensure_ascii=False, default=str)

        elif action == "add_purchase":
            item_id = args.get("item_id")
            quantity = args.get("quantity")
            if not item_id or quantity is None:
                return json.dumps({"success": False, "error": "item_id e quantity são obrigatórios."})
            qty = float(quantity)
            total_cost = args.get("total_cost")
            DatabaseManager.execute_query(
                "UPDATE pdv_stock_items SET quantity = quantity + :qty, updated_at = :now WHERE client_id = :cid AND id = :id",
                {"cid": client_id, "id": item_id, "qty": qty, "now": datetime.utcnow()},
            )
            DatabaseManager.execute_query(
                """INSERT INTO pdv_stock_transactions (client_id, stock_item_id, type, quantity, total_cost, expiry_date, note, created_at)
                   VALUES (:cid, :iid, 'purchase', :qty, :cost, :exp, :note, :now)""",
                {
                    "cid": client_id, "iid": item_id, "qty": qty,
                    "cost": float(total_cost) if total_cost is not None else None,
                    "exp": args.get("expiry_date"),
                    "note": args.get("note"),
                    "now": datetime.utcnow(),
                },
            )
            row = DatabaseManager.fetch_one(
                "SELECT * FROM pdv_stock_items WHERE client_id = :cid AND id = :id",
                {"cid": client_id, "id": item_id},
            )
            return json.dumps({"success": True, "item": dict(row) if row else None}, ensure_ascii=False, default=str)

        elif action == "register_loss":
            item_id = args.get("item_id")
            quantity = args.get("quantity")
            if not item_id or quantity is None:
                return json.dumps({"success": False, "error": "item_id e quantity são obrigatórios."})
            qty = float(quantity)
            DatabaseManager.execute_query(
                "UPDATE pdv_stock_items SET quantity = MAX(0, quantity - :qty), updated_at = :now WHERE client_id = :cid AND id = :id",
                {"cid": client_id, "id": item_id, "qty": qty, "now": datetime.utcnow()},
            )
            DatabaseManager.execute_query(
                """INSERT INTO pdv_stock_transactions (client_id, stock_item_id, type, quantity, note, created_at)
                   VALUES (:cid, :iid, 'loss', :qty, :note, :now)""",
                {"cid": client_id, "iid": item_id, "qty": qty, "note": args.get("note"), "now": datetime.utcnow()},
            )
            row = DatabaseManager.fetch_one(
                "SELECT * FROM pdv_stock_items WHERE client_id = :cid AND id = :id",
                {"cid": client_id, "id": item_id},
            )
            return json.dumps({"success": True, "item": dict(row) if row else None}, ensure_ascii=False, default=str)

        elif action == "list_transactions":
            item_id = args.get("item_id")
            limit = min(int(args.get("limit", 50)), 200)
            query = "SELECT * FROM pdv_stock_transactions WHERE client_id = :cid"
            params2: Dict[str, Any] = {"cid": client_id}
            if item_id:
                query += " AND stock_item_id = :iid"
                params2["iid"] = item_id
            query += f" ORDER BY created_at DESC LIMIT {limit}"
            rows = DatabaseManager.fetch_all(query, params2) or []
            return json.dumps({"success": True, "transactions": [dict(r) for r in rows]}, ensure_ascii=False, default=str)

        else:
            return json.dumps({
                "success": False,
                "error": f"Ação desconhecida: '{action}'",
                "available_actions": ["list_items", "get_item", "create_item", "update_item", "add_purchase", "register_loss", "list_transactions"],
            })

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


# ─────────────────────────────────────────────
# pdv_orders
# ─────────────────────────────────────────────

def execute_pdv_orders(args: Dict[str, Any], client_id: str) -> str:
    if not client_id:
        return json.dumps({"success": False, "error": "client_id não encontrado para o usuário."})

    action = (args.get("action") or "").strip()

    try:
        if action == "list_orders":
            limit = min(int(args.get("limit", 50)), 200)
            date_from = args.get("date_from")
            date_to = args.get("date_to")
            payment_method = args.get("payment_method")
            status = args.get("status")
            query = "SELECT * FROM pdv_orders WHERE client_id = :cid"
            params: Dict[str, Any] = {"cid": client_id}
            if date_from:
                query += " AND created_at >= :df"
                params["df"] = date_from
            if date_to:
                query += " AND created_at <= :dt"
                params["dt"] = date_to
            if payment_method:
                query += " AND payment_method = :pm"
                params["pm"] = payment_method
            if status:
                query += " AND status = :st"
                params["st"] = status
            query += f" ORDER BY created_at DESC LIMIT {limit}"
            rows = DatabaseManager.fetch_all(query, params) or []
            return json.dumps({"success": True, "orders": [dict(r) for r in rows], "total": len(rows)}, ensure_ascii=False, default=str)

        elif action == "get_order":
            order_id = args.get("order_id")
            if not order_id:
                return json.dumps({"success": False, "error": "order_id é obrigatório."})
            row = DatabaseManager.fetch_one(
                "SELECT * FROM pdv_orders WHERE client_id = :cid AND id = :id",
                {"cid": client_id, "id": order_id},
            )
            if not row:
                return json.dumps({"success": False, "error": "Pedido não encontrado."})
            return json.dumps({"success": True, "order": dict(row)}, ensure_ascii=False, default=str)

        elif action == "create":
            comanda_label = args.get("comanda_label")
            payment_method = args.get("payment_method")
            if not comanda_label and not payment_method:
                return json.dumps({"success": False, "error": "Informe comanda_label ou payment_method (ao menos um é obrigatório)."})
            items_json = args.get("items_json")
            if isinstance(items_json, list):
                items_json = json.dumps(items_json, ensure_ascii=False)
            coupons_json = args.get("coupons_json")
            if isinstance(coupons_json, list):
                coupons_json = json.dumps(coupons_json, ensure_ascii=False)
            subtotal = float(args.get("subtotal", 0))
            garcom_fee = float(args.get("garcom_fee", 0))
            coupon_discount = float(args.get("coupon_discount", 0))
            total = float(args.get("total", subtotal + garcom_fee - coupon_discount))
            DatabaseManager.execute_query(
                """INSERT INTO pdv_orders
                   (client_id, comanda_label, payment_method, payment_gateway, cpf, customer_name,
                    subtotal, garcom_fee, coupon_discount, total, items_json, coupons_json, nfe_emitted,
                    status, effective_rate, effective_flat_fee, effective_receive_days, created_at)
                   VALUES (:cid, :cl, :pm, :pg, :cpf, :cn,
                           :sub, :gf, :cd, :total, :ij, :cj, :nfe,
                           :status, 0, 0, 0, :now)""",
                {
                    "cid": client_id,
                    "cl": comanda_label,
                    "pm": payment_method,
                    "pg": args.get("payment_gateway", "none"),
                    "cpf": args.get("cpf"),
                    "cn": args.get("customer_name"),
                    "sub": subtotal,
                    "gf": garcom_fee,
                    "cd": coupon_discount,
                    "total": total,
                    "ij": items_json or "[]",
                    "cj": coupons_json or "[]",
                    "nfe": int(args.get("nfe_emitted", 0)),
                    "status": args.get("status", "operacao_confirmada"),
                    "now": datetime.utcnow(),
                },
            )
            row = DatabaseManager.fetch_one(
                "SELECT * FROM pdv_orders WHERE client_id = :cid ORDER BY id DESC LIMIT 1",
                {"cid": client_id},
            )
            return json.dumps({"success": True, "order": dict(row) if row else None}, ensure_ascii=False, default=str)

        elif action == "update":
            order_id = args.get("order_id")
            status = args.get("status")
            if not order_id:
                return json.dumps({"success": False, "error": "order_id é obrigatório."})
            if not status:
                return json.dumps({"success": False, "error": "status é obrigatório. Valores válidos: operacao_confirmada, cancelado."})
            existing = DatabaseManager.fetch_one(
                "SELECT id FROM pdv_orders WHERE client_id = :cid AND id = :id",
                {"cid": client_id, "id": order_id},
            )
            if not existing:
                return json.dumps({"success": False, "error": "Pedido não encontrado."})
            DatabaseManager.execute_query(
                "UPDATE pdv_orders SET status = :status WHERE client_id = :cid AND id = :id",
                {"cid": client_id, "id": order_id, "status": status},
            )
            row = DatabaseManager.fetch_one(
                "SELECT * FROM pdv_orders WHERE client_id = :cid AND id = :id",
                {"cid": client_id, "id": order_id},
            )
            return json.dumps({"success": True, "order": dict(row) if row else None}, ensure_ascii=False, default=str)

        elif action == "get_summary":
            date_from = args.get("date_from")
            date_to = args.get("date_to")
            query = "SELECT COUNT(*) as count, SUM(total) as revenue, AVG(total) as avg_ticket FROM pdv_orders WHERE client_id = :cid AND status != 'cancelado'"
            params3: Dict[str, Any] = {"cid": client_id}
            if date_from:
                query += " AND created_at >= :df"
                params3["df"] = date_from
            if date_to:
                query += " AND created_at <= :dt"
                params3["dt"] = date_to
            row = DatabaseManager.fetch_one(query, params3)
            by_payment = DatabaseManager.fetch_all(
                "SELECT payment_method, COUNT(*) as count, SUM(total) as revenue FROM pdv_orders WHERE client_id = :cid AND status != 'cancelado' GROUP BY payment_method ORDER BY revenue DESC",
                {"cid": client_id},
            ) or []
            return json.dumps({
                "success": True,
                "summary": dict(row) if row else {},
                "by_payment": [dict(r) for r in by_payment],
            }, ensure_ascii=False, default=str)

        else:
            return json.dumps({
                "success": False,
                "error": f"Ação desconhecida: '{action}'",
                "available_actions": ["list_orders", "get_order", "create", "update", "get_summary"],
            })

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


# ─────────────────────────────────────────────
# pdv_settings
# ─────────────────────────────────────────────

def execute_pdv_settings(args: Dict[str, Any], client_id: str) -> str:
    if not client_id:
        return json.dumps({"success": False, "error": "client_id não encontrado para o usuário."})

    action = (args.get("action") or "").strip()

    try:
        if action == "get_profile":
            row = DatabaseManager.fetch_one(
                "SELECT * FROM pdv_store_profiles WHERE client_id = :cid",
                {"cid": client_id},
            )
            return json.dumps({"success": True, "profile": dict(row) if row else None}, ensure_ascii=False, default=str)

        elif action == "update_profile":
            updatable = ["name", "description", "google_review_link", "garcom_enabled", "garcom_pct", "nfe_enabled"]
            sets = []
            params: Dict[str, Any] = {"cid": client_id, "now": datetime.utcnow()}
            for field in updatable:
                if field in args:
                    sets.append(f"{field} = :{field}")
                    params[field] = args[field]
            if not sets:
                return json.dumps({"success": False, "error": "Nenhum campo para atualizar."})
            sets.append("updated_at = :now")
            existing = DatabaseManager.fetch_one(
                "SELECT id FROM pdv_store_profiles WHERE client_id = :cid", {"cid": client_id}
            )
            if existing:
                DatabaseManager.execute_query(
                    f"UPDATE pdv_store_profiles SET {', '.join(sets)} WHERE client_id = :cid",
                    params,
                )
            else:
                params["name"] = args.get("name", "Minha Loja")
                DatabaseManager.execute_query(
                    "INSERT INTO pdv_store_profiles (client_id, name, created_at, updated_at) VALUES (:cid, :name, :now, :now)",
                    {"cid": client_id, "name": params["name"], "now": params["now"]},
                )
                if sets:
                    DatabaseManager.execute_query(
                        f"UPDATE pdv_store_profiles SET {', '.join(sets)} WHERE client_id = :cid",
                        params,
                    )
            row = DatabaseManager.fetch_one(
                "SELECT * FROM pdv_store_profiles WHERE client_id = :cid", {"cid": client_id}
            )
            return json.dumps({"success": True, "profile": dict(row) if row else None}, ensure_ascii=False, default=str)

        elif action == "get_hours":
            row = DatabaseManager.fetch_one(
                "SELECT opening_hours FROM clients WHERE client_id = :cid",
                {"cid": client_id},
            )
            if not row:
                return json.dumps({"success": False, "error": "Cliente não encontrado."})
            raw = row.get("opening_hours")
            hours = json.loads(raw) if raw else {}
            return json.dumps({"success": True, "opening_hours": hours}, ensure_ascii=False)

        elif action == "update_hours":
            hours = args.get("opening_hours")
            if hours is None:
                return json.dumps({"success": False, "error": "opening_hours é obrigatório (objeto com chaves mon..sun)."})
            if isinstance(hours, str):
                hours = json.loads(hours)
            DatabaseManager.execute_query(
                "UPDATE clients SET opening_hours = :oh, updated_at = CURRENT_TIMESTAMP WHERE client_id = :cid",
                {"cid": client_id, "oh": json.dumps(hours, ensure_ascii=False)},
            )
            return json.dumps({"success": True, "opening_hours": hours}, ensure_ascii=False)

        else:
            return json.dumps({
                "success": False,
                "error": f"Ação desconhecida: '{action}'",
                "available_actions": ["get_profile", "update_profile", "get_hours", "update_hours"],
            })

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


# ─────────────────────────────────────────────
# pdv_promotions  (cupons + benefícios)
# ─────────────────────────────────────────────

def execute_pdv_promotions(args: Dict[str, Any], client_id: str) -> str:
    if not client_id:
        return json.dumps({"success": False, "error": "client_id não encontrado para o usuário."})

    action = (args.get("action") or "").strip()

    try:
        # ── Coupons ──
        if action == "list_coupons":
            rows = DatabaseManager.fetch_all(
                "SELECT * FROM pdv_coupons WHERE client_id = :cid ORDER BY created_at DESC",
                {"cid": client_id},
            ) or []
            return json.dumps({"success": True, "coupons": [dict(r) for r in rows]}, ensure_ascii=False, default=str)

        elif action == "get_coupon":
            coupon_id = args.get("coupon_id")
            code = args.get("code")
            if coupon_id:
                row = DatabaseManager.fetch_one(
                    "SELECT * FROM pdv_coupons WHERE client_id = :cid AND id = :id",
                    {"cid": client_id, "id": coupon_id},
                )
            elif code:
                row = DatabaseManager.fetch_one(
                    "SELECT * FROM pdv_coupons WHERE client_id = :cid AND code = :code",
                    {"cid": client_id, "code": code},
                )
            else:
                return json.dumps({"success": False, "error": "Informe coupon_id ou code."})
            if not row:
                return json.dumps({"success": False, "error": "Cupom não encontrado."})
            return json.dumps({"success": True, "coupon": dict(row)}, ensure_ascii=False, default=str)

        elif action == "create_coupon":
            name = args.get("name")
            if not name:
                return json.dumps({"success": False, "error": "name é obrigatório."})
            code = args.get("code", "")
            coupon_type = args.get("type", "percent")
            value = float(args.get("value", 0))
            DatabaseManager.execute_query(
                """INSERT INTO pdv_coupons
                   (client_id, code, name, type, value, bonus_value, min_order_value, active, expires_at, created_at)
                   VALUES (:cid, :code, :name, :type, :value, :bv, :mov, :active, :exp, :now)""",
                {
                    "cid": client_id,
                    "code": code,
                    "name": name,
                    "type": coupon_type,
                    "value": value,
                    "bv": args.get("bonus_value"),
                    "mov": float(args.get("min_order_value")) if args.get("min_order_value") is not None else None,
                    "active": 1 if args.get("active", True) else 0,
                    "exp": args.get("expires_at"),
                    "now": datetime.utcnow(),
                },
            )
            row = DatabaseManager.fetch_one(
                "SELECT * FROM pdv_coupons WHERE client_id = :cid AND name = :name ORDER BY id DESC LIMIT 1",
                {"cid": client_id, "name": name},
            )
            return json.dumps({"success": True, "coupon": dict(row) if row else None}, ensure_ascii=False, default=str)

        elif action == "update_coupon":
            coupon_id = args.get("coupon_id")
            if not coupon_id:
                return json.dumps({"success": False, "error": "coupon_id é obrigatório."})
            existing = DatabaseManager.fetch_one(
                "SELECT id FROM pdv_coupons WHERE client_id = :cid AND id = :id",
                {"cid": client_id, "id": coupon_id},
            )
            if not existing:
                return json.dumps({"success": False, "error": "Cupom não encontrado."})
            updatable = ["code", "name", "type", "value", "bonus_value", "min_order_value", "active", "expires_at"]
            sets = []
            params: Dict[str, Any] = {"cid": client_id, "id": coupon_id}
            for field in updatable:
                if field in args:
                    sets.append(f"{field} = :{field}")
                    val = args[field]
                    if field == "active":
                        val = 1 if val else 0
                    params[field] = val
            if not sets:
                return json.dumps({"success": False, "error": "Nenhum campo para atualizar."})
            DatabaseManager.execute_query(
                f"UPDATE pdv_coupons SET {', '.join(sets)} WHERE client_id = :cid AND id = :id",
                params,
            )
            row = DatabaseManager.fetch_one(
                "SELECT * FROM pdv_coupons WHERE client_id = :cid AND id = :id",
                {"cid": client_id, "id": coupon_id},
            )
            return json.dumps({"success": True, "coupon": dict(row) if row else None}, ensure_ascii=False, default=str)

        elif action == "delete_coupon":
            coupon_id = args.get("coupon_id")
            if not coupon_id:
                return json.dumps({"success": False, "error": "coupon_id é obrigatório."})
            DatabaseManager.execute_query(
                "DELETE FROM pdv_coupons WHERE client_id = :cid AND id = :id",
                {"cid": client_id, "id": coupon_id},
            )
            return json.dumps({"success": True}, ensure_ascii=False)

        # ── Benefits ──
        elif action == "list_benefits":
            rows = DatabaseManager.fetch_all(
                "SELECT * FROM pdv_benefits WHERE client_id = :cid ORDER BY created_at DESC",
                {"cid": client_id},
            ) or []
            return json.dumps({"success": True, "benefits": [dict(r) for r in rows]}, ensure_ascii=False, default=str)

        elif action == "get_benefit":
            benefit_id = args.get("benefit_id")
            if not benefit_id:
                return json.dumps({"success": False, "error": "benefit_id é obrigatório."})
            row = DatabaseManager.fetch_one(
                "SELECT * FROM pdv_benefits WHERE client_id = :cid AND id = :id",
                {"cid": client_id, "id": benefit_id},
            )
            if not row:
                return json.dumps({"success": False, "error": "Benefício não encontrado."})
            return json.dumps({"success": True, "benefit": dict(row)}, ensure_ascii=False, default=str)

        elif action == "create_benefit":
            name = args.get("name")
            if not name:
                return json.dumps({"success": False, "error": "name é obrigatório."})
            DatabaseManager.execute_query(
                "INSERT INTO pdv_benefits (client_id, name, description, active, created_at) VALUES (:cid, :name, :desc, :active, :now)",
                {
                    "cid": client_id,
                    "name": name,
                    "desc": args.get("description", ""),
                    "active": 1 if args.get("active", True) else 0,
                    "now": datetime.utcnow(),
                },
            )
            row = DatabaseManager.fetch_one(
                "SELECT * FROM pdv_benefits WHERE client_id = :cid AND name = :name ORDER BY id DESC LIMIT 1",
                {"cid": client_id, "name": name},
            )
            return json.dumps({"success": True, "benefit": dict(row) if row else None}, ensure_ascii=False, default=str)

        elif action == "update_benefit":
            benefit_id = args.get("benefit_id")
            if not benefit_id:
                return json.dumps({"success": False, "error": "benefit_id é obrigatório."})
            existing = DatabaseManager.fetch_one(
                "SELECT id FROM pdv_benefits WHERE client_id = :cid AND id = :id",
                {"cid": client_id, "id": benefit_id},
            )
            if not existing:
                return json.dumps({"success": False, "error": "Benefício não encontrado."})
            sets = []
            params2: Dict[str, Any] = {"cid": client_id, "id": benefit_id}
            for field in ("name", "description", "active"):
                if field in args:
                    sets.append(f"{field} = :{field}")
                    val = args[field]
                    if field == "active":
                        val = 1 if val else 0
                    params2[field] = val
            if not sets:
                return json.dumps({"success": False, "error": "Nenhum campo para atualizar."})
            DatabaseManager.execute_query(
                f"UPDATE pdv_benefits SET {', '.join(sets)} WHERE client_id = :cid AND id = :id",
                params2,
            )
            row = DatabaseManager.fetch_one(
                "SELECT * FROM pdv_benefits WHERE client_id = :cid AND id = :id",
                {"cid": client_id, "id": benefit_id},
            )
            return json.dumps({"success": True, "benefit": dict(row) if row else None}, ensure_ascii=False, default=str)

        elif action == "delete_benefit":
            benefit_id = args.get("benefit_id")
            if not benefit_id:
                return json.dumps({"success": False, "error": "benefit_id é obrigatório."})
            DatabaseManager.execute_query(
                "DELETE FROM pdv_benefits WHERE client_id = :cid AND id = :id",
                {"cid": client_id, "id": benefit_id},
            )
            return json.dumps({"success": True}, ensure_ascii=False)

        else:
            return json.dumps({
                "success": False,
                "error": f"Ação desconhecida: '{action}'",
                "available_actions": [
                    "list_coupons", "get_coupon", "create_coupon", "update_coupon", "delete_coupon",
                    "list_benefits", "get_benefit", "create_benefit", "update_benefit", "delete_benefit",
                ],
            })

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


# ─────────────────────────────────────────────
# pdv_payments  (taxas por método + recebimentos)
# ─────────────────────────────────────────────

def execute_pdv_payments(args: Dict[str, Any], client_id: str) -> str:
    if not client_id:
        return json.dumps({"success": False, "error": "client_id não encontrado para o usuário."})

    action = (args.get("action") or "").strip()

    try:
        if action == "list_methods":
            rows = DatabaseManager.fetch_all(
                "SELECT * FROM pdv_payment_configs WHERE client_id = :cid ORDER BY sort_order",
                {"cid": client_id},
            ) or []
            return json.dumps({"success": True, "methods": [dict(r) for r in rows]}, ensure_ascii=False, default=str)

        elif action == "get_method":
            method_key = args.get("method_key")
            if not method_key:
                return json.dumps({"success": False, "error": "method_key é obrigatório."})
            row = DatabaseManager.fetch_one(
                "SELECT * FROM pdv_payment_configs WHERE client_id = :cid AND method_key = :mk",
                {"cid": client_id, "mk": method_key},
            )
            if not row:
                return json.dumps({"success": False, "error": "Método de pagamento não encontrado."})
            return json.dumps({"success": True, "method": dict(row)}, ensure_ascii=False, default=str)

        elif action == "update_method":
            method_key = args.get("method_key")
            if not method_key:
                return json.dumps({"success": False, "error": "method_key é obrigatório."})
            existing = DatabaseManager.fetch_one(
                "SELECT id FROM pdv_payment_configs WHERE client_id = :cid AND method_key = :mk",
                {"cid": client_id, "mk": method_key},
            )
            if not existing:
                return json.dumps({"success": False, "error": "Método de pagamento não encontrado."})
            updatable = ["name", "rate", "flat_fee", "receive_days", "enabled", "sort_order"]
            sets = []
            params: Dict[str, Any] = {"cid": client_id, "mk": method_key, "now": datetime.utcnow()}
            for field in updatable:
                if field in args:
                    sets.append(f"{field} = :{field}")
                    params[field] = args[field]
            if not sets:
                return json.dumps({"success": False, "error": "Nenhum campo para atualizar."})
            sets.append("updated_at = :now")
            DatabaseManager.execute_query(
                f"UPDATE pdv_payment_configs SET {', '.join(sets)} WHERE client_id = :cid AND method_key = :mk",
                params,
            )
            row = DatabaseManager.fetch_one(
                "SELECT * FROM pdv_payment_configs WHERE client_id = :cid AND method_key = :mk",
                {"cid": client_id, "mk": method_key},
            )
            return json.dumps({"success": True, "method": dict(row) if row else None}, ensure_ascii=False, default=str)

        elif action == "list_gateway_rates":
            rows = DatabaseManager.fetch_all(
                "SELECT * FROM pdv_gateway_rates WHERE client_id = :cid ORDER BY gateway_type, method",
                {"cid": client_id},
            ) or []
            return json.dumps({"success": True, "gateway_rates": [dict(r) for r in rows]}, ensure_ascii=False, default=str)

        elif action == "list_receipts":
            # Recebimentos = pedidos confirmados com valor líquido estimado após taxas
            limit = min(int(args.get("limit", 100)), 500)
            date_from = args.get("date_from")
            date_to = args.get("date_to")
            payment_method = args.get("payment_method")
            query = (
                "SELECT id, comanda_label, payment_method, payment_gateway, total,"
                " effective_rate, effective_flat_fee, effective_receive_days,"
                " (total - (total * effective_rate / 100.0) - effective_flat_fee) AS net_amount,"
                " created_at, status"
                " FROM pdv_orders WHERE client_id = :cid AND status != 'cancelado'"
            )
            params2: Dict[str, Any] = {"cid": client_id}
            if date_from:
                query += " AND created_at >= :df"
                params2["df"] = date_from
            if date_to:
                query += " AND created_at <= :dt"
                params2["dt"] = date_to
            if payment_method:
                query += " AND payment_method = :pm"
                params2["pm"] = payment_method
            query += f" ORDER BY created_at DESC LIMIT {limit}"
            rows = DatabaseManager.fetch_all(query, params2) or []
            total_gross = sum(float(r.get("total") or 0) for r in rows)
            total_net = sum(float(r.get("net_amount") or 0) for r in rows)
            return json.dumps({
                "success": True,
                "receipts": [dict(r) for r in rows],
                "count": len(rows),
                "total_gross": round(total_gross, 2),
                "total_net": round(total_net, 2),
            }, ensure_ascii=False, default=str)

        else:
            return json.dumps({
                "success": False,
                "error": f"Ação desconhecida: '{action}'",
                "available_actions": ["list_methods", "get_method", "update_method", "list_gateway_rates", "list_receipts"],
            })

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})
