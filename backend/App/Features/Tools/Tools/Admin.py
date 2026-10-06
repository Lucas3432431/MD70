"""
MD70 Admin Tools: md70_projetos, md70_compras, md70_crm, md70_financeiro
Reads (list_*, get_*) are always authorized.
Writes (create, patch, delete) require bypass_approval (handled in Core.py).
"""

import json
import uuid
from datetime import date as _date
from typing import Any, Dict

from sqlalchemy import text
from App.Core.Crunch.TablesSQL.Database import database


def _engine():
    return database.engine


# ─────────────────────────────────────────────────────────────
# md70_projetos
# ─────────────────────────────────────────────────────────────

def execute_md70_projetos(args: Dict[str, Any]) -> str:
    action = (args.get("action") or "").strip()
    try:
        engine = _engine()
        with engine.connect() as conn:

            if action == "list_projects":
                rows = conn.execute(text(
                    "SELECT id, name, status, progress, capital, budget, remaining, "
                    "forecast, image_url, city, category, summary "
                    "FROM md70_developments ORDER BY created_at"
                )).fetchall()
                projects = [
                    {"id": r[0], "name": r[1], "status": r[2], "progress": r[3],
                     "capital": r[4], "budget": r[5], "remaining": r[6],
                     "forecast": r[7], "imageUrl": r[8], "city": r[9],
                     "category": r[10], "summary": r[11]}
                    for r in rows
                ]
                return json.dumps({"success": True, "projects": projects, "total": len(projects)}, ensure_ascii=False)

            elif action == "get_project":
                project_id = args.get("project_id")
                if not project_id:
                    return json.dumps({"success": False, "error": "project_id é obrigatório."})
                row = conn.execute(text(
                    "SELECT id, name, status, progress, capital, budget, remaining, "
                    "forecast, image_url, city, category, summary "
                    "FROM md70_developments WHERE id = :id"
                ), {"id": project_id}).fetchone()
                if not row:
                    return json.dumps({"success": False, "error": f"Projeto '{project_id}' não encontrado."})
                return json.dumps({"success": True, "project": {
                    "id": row[0], "name": row[1], "status": row[2], "progress": row[3],
                    "capital": row[4], "budget": row[5], "remaining": row[6],
                    "forecast": row[7], "imageUrl": row[8], "city": row[9],
                    "category": row[10], "summary": row[11],
                }}, ensure_ascii=False)

            elif action == "create_project":
                name = args.get("name")
                if not name:
                    return json.dumps({"success": False, "error": "name é obrigatório."})
                project_id = name.lower().replace(" ", "-").replace("/", "-")[:40] + "-" + uuid.uuid4().hex[:6]
                conn.execute(text(
                    "INSERT INTO md70_developments (id, name, city, status, progress, capital, budget, remaining, forecast, image_url, category, summary) "
                    "VALUES (:id, :name, :city, :status, :progress, :capital, :budget, :remaining, :forecast, :image_url, :category, :summary)"
                ), {
                    "id": project_id, "name": name,
                    "city": args.get("city", ""),
                    "status": args.get("status", "Projeto"),
                    "progress": args.get("progress", 0),
                    "capital": args.get("capital", 0),
                    "budget": args.get("budget", 0),
                    "remaining": args.get("remaining", 0),
                    "forecast": args.get("forecast"),
                    "image_url": args.get("image_url"),
                    "category": args.get("category"),
                    "summary": args.get("summary"),
                })
                conn.commit()
                return json.dumps({"success": True, "id": project_id, "_reload_page": "Projeto criado. Recarregue a página para ver."}, ensure_ascii=False)

            elif action == "patch_project":
                project_id = args.get("project_id")
                if not project_id:
                    return json.dumps({"success": False, "error": "project_id é obrigatório."})
                field_map = {"name": "name", "city": "city", "status": "status", "progress": "progress",
                             "capital": "capital", "budget": "budget", "remaining": "remaining",
                             "forecast": "forecast", "image_url": "image_url", "category": "category", "summary": "summary"}
                set_parts = ["updated_at = CURRENT_TIMESTAMP"]
                params: Dict[str, Any] = {"id": project_id}
                for field, col in field_map.items():
                    if field in args and args[field] is not None:
                        set_parts.append(f"{col} = :{field}")
                        params[field] = args[field]
                if len(set_parts) == 1:
                    return json.dumps({"success": False, "error": "Nenhum campo fornecido."})
                result = conn.execute(text(f"UPDATE md70_developments SET {', '.join(set_parts)} WHERE id = :id"), params)
                conn.commit()
                if result.rowcount == 0:
                    return json.dumps({"success": False, "error": f"Projeto '{project_id}' não encontrado."})
                return json.dumps({"success": True, "id": project_id, "_reload_page": "Projeto atualizado. Recarregue a página."}, ensure_ascii=False)

            else:
                return json.dumps({"success": False, "error": f"Ação '{action}' desconhecida.", "actions": ["list_projects", "get_project", "create_project", "patch_project"]})

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


# ─────────────────────────────────────────────────────────────
# md70_compras
# ─────────────────────────────────────────────────────────────

def execute_md70_compras(args: Dict[str, Any]) -> str:
    action = (args.get("action") or "").strip()
    try:
        engine = _engine()
        with engine.connect() as conn:

            if action == "list_purchases":
                project_id = args.get("project_id")
                status_filter = args.get("status")
                query = (
                    "SELECT id, development_id, budget_line_id, description, quantity, unit, "
                    "estimate, requester, date, status, selected_quote_id, approved_by, approved_at, "
                    "justification, paid_at, note, cnpj, recipient_name, is_operational, obra_type, obra_category, attachment "
                    "FROM md70_purchases WHERE 1=1"
                )
                params: Dict[str, Any] = {}
                if project_id:
                    query += " AND development_id = :pid"
                    params["pid"] = project_id
                if status_filter:
                    query += " AND status = :status"
                    params["status"] = status_filter
                query += " ORDER BY date DESC"
                rows = conn.execute(text(query), params).fetchall()
                purchases = [_purchase_row(r) for r in rows]
                return json.dumps({"success": True, "purchases": purchases, "total": len(purchases)}, ensure_ascii=False)

            elif action == "get_purchase":
                purchase_id = args.get("purchase_id")
                if not purchase_id:
                    return json.dumps({"success": False, "error": "purchase_id é obrigatório."})
                row = conn.execute(text(
                    "SELECT id, development_id, budget_line_id, description, quantity, unit, "
                    "estimate, requester, date, status, selected_quote_id, approved_by, approved_at, "
                    "justification, paid_at, note, cnpj, recipient_name, is_operational, obra_type, obra_category, attachment "
                    "FROM md70_purchases WHERE id = :id"
                ), {"id": purchase_id}).fetchone()
                if not row:
                    return json.dumps({"success": False, "error": f"Compra '{purchase_id}' não encontrada."})
                return json.dumps({"success": True, "purchase": _purchase_row(row)}, ensure_ascii=False)

            elif action == "create_purchase":
                dev_id = args.get("development_id") or args.get("project_id")
                description = args.get("description")
                if not dev_id or not description:
                    return json.dumps({"success": False, "error": "development_id e description são obrigatórios."})
                purchase_id = "c-" + uuid.uuid4().hex[:10]
                purchase_date = args.get("date") or _date.today().isoformat()
                conn.execute(text(
                    "INSERT INTO md70_purchases (id, development_id, budget_line_id, description, quantity, unit, "
                    "estimate, requester, date, status, note, cnpj, recipient_name, is_operational, obra_type, obra_category, attachment) "
                    "VALUES (:id, :dev_id, :budget_id, :desc, :qty, :unit, :estimate, :requester, :date, 'Solicitado', "
                    ":note, :cnpj, :recipient, :is_op, :obra_type, :obra_cat, :attachment)"
                ), {
                    "id": purchase_id, "dev_id": dev_id,
                    "budget_id": args.get("budget_line_id"),
                    "desc": description, "qty": args.get("quantity", 1),
                    "unit": args.get("unit", "serviço"),
                    "estimate": args.get("estimate", 0),
                    "requester": args.get("requester"),
                    "date": purchase_date, "note": args.get("note"),
                    "cnpj": args.get("cnpj"), "recipient": args.get("recipient_name"),
                    "is_op": 1 if args.get("is_operational") else 0,
                    "obra_type": args.get("obra_type"),
                    "obra_cat": args.get("obra_category"),
                    "attachment": args.get("attachment"),
                })
                conn.commit()
                return json.dumps({"success": True, "id": purchase_id, "_reload_page": "Compra criada. Recarregue a página."}, ensure_ascii=False)

            elif action == "patch_purchase":
                purchase_id = args.get("purchase_id")
                if not purchase_id:
                    return json.dumps({"success": False, "error": "purchase_id é obrigatório."})
                set_parts = ["updated_at = CURRENT_TIMESTAMP"]
                params_p: Dict[str, Any] = {"id": purchase_id}
                scalar = ["status", "description", "quantity", "unit", "estimate", "requester",
                          "date", "note", "cnpj", "recipient_name", "obra_type", "obra_category",
                          "attachment", "approved_by", "approved_at", "paid_at", "selected_quote_id",
                          "development_id", "budget_line_id"]
                for field in scalar:
                    if field in args and args[field] is not None:
                        col = "selected_quote_id" if field == "selected_quote_id" else field
                        set_parts.append(f"{col} = :{field}")
                        params_p[field] = args[field]
                if "is_operational" in args and args["is_operational"] is not None:
                    set_parts.append("is_operational = :is_op")
                    params_p["is_op"] = 1 if args["is_operational"] else 0
                if len(set_parts) == 1:
                    return json.dumps({"success": False, "error": "Nenhum campo fornecido."})
                result = conn.execute(text(f"UPDATE md70_purchases SET {', '.join(set_parts)} WHERE id = :id"), params_p)
                conn.commit()
                if result.rowcount == 0:
                    return json.dumps({"success": False, "error": f"Compra '{purchase_id}' não encontrada."})
                return json.dumps({"success": True, "id": purchase_id, "_reload_page": "Compra atualizada. Recarregue a página."}, ensure_ascii=False)

            elif action == "delete_purchase":
                purchase_id = args.get("purchase_id")
                if not purchase_id:
                    return json.dumps({"success": False, "error": "purchase_id é obrigatório."})
                result = conn.execute(text("DELETE FROM md70_purchases WHERE id = :id"), {"id": purchase_id})
                conn.commit()
                if result.rowcount == 0:
                    return json.dumps({"success": False, "error": f"Compra '{purchase_id}' não encontrada."})
                return json.dumps({"success": True, "id": purchase_id, "_reload_page": "Compra excluída. Recarregue a página."}, ensure_ascii=False)

            else:
                return json.dumps({"success": False, "error": f"Ação '{action}' desconhecida.", "actions": ["list_purchases", "get_purchase", "create_purchase", "patch_purchase", "delete_purchase"]})

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def _purchase_row(r) -> dict:
    return {
        "id": r[0], "projectId": r[1], "budgetId": r[2],
        "description": r[3], "quantity": r[4], "unit": r[5],
        "estimate": r[6], "requester": r[7], "date": r[8],
        "status": r[9], "selectedQuoteId": r[10],
        "approvedBy": r[11], "approvedAt": r[12],
        "justification": r[13], "paidAt": r[14], "note": r[15],
        "cnpj": r[16], "recipientName": r[17],
        "isOperational": bool(r[18]) if r[18] is not None else False,
        "obraType": r[19], "obraCategory": r[20], "attachment": r[21],
    }


# ─────────────────────────────────────────────────────────────
# md70_crm
# ─────────────────────────────────────────────────────────────

def execute_md70_crm(args: Dict[str, Any]) -> str:
    action = (args.get("action") or "").strip()
    try:
        engine = _engine()
        with engine.connect() as conn:

            if action == "list_leads":
                status_filter = args.get("status")
                query = (
                    "SELECT id, name, email, phone, project_interest, status, source, value, notes, "
                    "created_at, project_interests_json FROM md70_leads WHERE 1=1"
                )
                params: Dict[str, Any] = {}
                if status_filter:
                    query += " AND status = :status"
                    params["status"] = status_filter
                query += " ORDER BY created_at DESC"
                rows = conn.execute(text(query), params).fetchall()
                leads = [_lead_row(r) for r in rows]
                return json.dumps({"success": True, "leads": leads, "total": len(leads)}, ensure_ascii=False)

            elif action == "get_lead":
                lead_id = args.get("lead_id")
                if not lead_id:
                    return json.dumps({"success": False, "error": "lead_id é obrigatório."})
                row = conn.execute(text(
                    "SELECT id, name, email, phone, project_interest, status, source, value, notes, "
                    "created_at, project_interests_json FROM md70_leads WHERE id = :id"
                ), {"id": lead_id}).fetchone()
                if not row:
                    return json.dumps({"success": False, "error": f"Lead '{lead_id}' não encontrado."})
                return json.dumps({"success": True, "lead": _lead_row(row)}, ensure_ascii=False)

            elif action == "create_lead":
                name = args.get("name")
                if not name:
                    return json.dumps({"success": False, "error": "name é obrigatório."})
                lead_id = "l-" + uuid.uuid4().hex[:10]
                conn.execute(text(
                    "INSERT INTO md70_leads (id, name, email, phone, project_interest, status, source, value, notes) "
                    "VALUES (:id, :name, :email, :phone, :project_interest, :status, :source, :value, :notes)"
                ), {
                    "id": lead_id, "name": name,
                    "email": args.get("email"), "phone": args.get("phone"),
                    "project_interest": args.get("project_interest"),
                    "status": args.get("status", "Interesse"),
                    "source": args.get("source"),
                    "value": args.get("value", 0),
                    "notes": args.get("notes"),
                })
                conn.commit()
                return json.dumps({"success": True, "id": lead_id, "_reload_page": "Lead criado. Recarregue a página."}, ensure_ascii=False)

            elif action == "patch_lead":
                lead_id = args.get("lead_id")
                if not lead_id:
                    return json.dumps({"success": False, "error": "lead_id é obrigatório."})
                set_parts = ["updated_at = CURRENT_TIMESTAMP"]
                params_l: Dict[str, Any] = {"id": lead_id}
                scalar = ["name", "email", "phone", "project_interest", "status", "source", "value", "notes"]
                for field in scalar:
                    if field in args and args[field] is not None:
                        set_parts.append(f"{field} = :{field}")
                        params_l[field] = args[field]
                if "project_interests" in args and args["project_interests"] is not None:
                    set_parts.append("project_interests_json = :pi_json")
                    params_l["pi_json"] = json.dumps(args["project_interests"])
                if len(set_parts) == 1:
                    return json.dumps({"success": False, "error": "Nenhum campo fornecido."})
                result = conn.execute(text(f"UPDATE md70_leads SET {', '.join(set_parts)} WHERE id = :id"), params_l)
                conn.commit()
                if result.rowcount == 0:
                    return json.dumps({"success": False, "error": f"Lead '{lead_id}' não encontrado."})
                return json.dumps({"success": True, "id": lead_id, "_reload_page": "Lead atualizado. Recarregue a página."}, ensure_ascii=False)

            elif action == "delete_lead":
                lead_id = args.get("lead_id")
                if not lead_id:
                    return json.dumps({"success": False, "error": "lead_id é obrigatório."})
                result = conn.execute(text("DELETE FROM md70_leads WHERE id = :id"), {"id": lead_id})
                conn.commit()
                if result.rowcount == 0:
                    return json.dumps({"success": False, "error": f"Lead '{lead_id}' não encontrado."})
                return json.dumps({"success": True, "id": lead_id, "_reload_page": "Lead excluído. Recarregue a página."}, ensure_ascii=False)

            else:
                return json.dumps({"success": False, "error": f"Ação '{action}' desconhecida.", "actions": ["list_leads", "get_lead", "create_lead", "patch_lead", "delete_lead"]})

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def _lead_row(r) -> dict:
    project_interests = []
    if r[10]:
        try:
            project_interests = json.loads(r[10])
        except Exception:
            pass
    return {
        "id": r[0], "name": r[1], "email": r[2], "phone": r[3],
        "projectInterest": r[4], "status": r[5], "source": r[6],
        "value": r[7], "notes": r[8], "createdAt": r[9],
        "projectInterests": project_interests,
    }


# ─────────────────────────────────────────────────────────────
# md70_financeiro
# ─────────────────────────────────────────────────────────────

def execute_md70_financeiro(args: Dict[str, Any]) -> str:
    action = (args.get("action") or "").strip()
    try:
        engine = _engine()
        with engine.connect() as conn:

            if action == "list_movements":
                project_id = args.get("project_id")
                direction = args.get("direction")
                status_filter = args.get("status")
                query = (
                    "SELECT id, development_id, purchase_id, date, description, category, "
                    "direction, value, status, date_competencia, is_operational, obra_type, obra_category, cnpj, recipient_name "
                    "FROM md70_movements WHERE 1=1"
                )
                params: Dict[str, Any] = {}
                if project_id:
                    query += " AND development_id = :pid"
                    params["pid"] = project_id
                if direction:
                    query += " AND direction = :dir"
                    params["dir"] = direction
                if status_filter:
                    query += " AND status = :status"
                    params["status"] = status_filter
                query += " ORDER BY date DESC"
                rows = conn.execute(text(query), params).fetchall()
                movements = [_movement_row(r) for r in rows]
                return json.dumps({"success": True, "movements": movements, "total": len(movements)}, ensure_ascii=False)

            elif action == "get_movement":
                movement_id = args.get("movement_id")
                if not movement_id:
                    return json.dumps({"success": False, "error": "movement_id é obrigatório."})
                row = conn.execute(text(
                    "SELECT id, development_id, purchase_id, date, description, category, "
                    "direction, value, status, date_competencia, is_operational, obra_type, obra_category, cnpj, recipient_name "
                    "FROM md70_movements WHERE id = :id"
                ), {"id": movement_id}).fetchone()
                if not row:
                    return json.dumps({"success": False, "error": f"Movimento '{movement_id}' não encontrado."})
                return json.dumps({"success": True, "movement": _movement_row(row)}, ensure_ascii=False)

            elif action == "create_movement":
                description = args.get("description")
                category = args.get("category")
                direction = args.get("direction")
                value = args.get("value")
                if not all([description, category, direction, value is not None]):
                    return json.dumps({"success": False, "error": "description, category, direction e value são obrigatórios."})
                if direction not in ("Entrada", "Saída"):
                    return json.dumps({"success": False, "error": "direction deve ser 'Entrada' ou 'Saída'."})
                is_op = bool(args.get("is_operational", False))
                dev_id = args.get("development_id") or args.get("project_id") or ("fundo-md70" if is_op else None)
                if not dev_id:
                    return json.dumps({"success": False, "error": "development_id é obrigatório para movimentos de empreendimento."})
                movement_id = "m-" + uuid.uuid4().hex[:10]
                movement_date = args.get("date") or _date.today().isoformat()
                conn.execute(text(
                    "INSERT INTO md70_movements "
                    "(id, development_id, purchase_id, date, date_competencia, description, category, direction, value, status, "
                    "is_operational, obra_type, obra_category, cnpj, recipient_name) "
                    "VALUES (:id, :dev_id, :purchase_id, :date, :date_competencia, :desc, :category, :direction, :value, :status, "
                    ":is_op, :obra_type, :obra_cat, :cnpj, :recipient)"
                ), {
                    "id": movement_id, "dev_id": dev_id,
                    "purchase_id": args.get("purchase_id"),
                    "date": movement_date,
                    "date_competencia": args.get("date_competencia"),
                    "desc": description, "category": category,
                    "direction": direction, "value": value,
                    "status": args.get("status", "Realizado"),
                    "is_op": 1 if is_op else 0,
                    "obra_type": args.get("obra_type"),
                    "obra_cat": args.get("obra_category"),
                    "cnpj": args.get("cnpj"),
                    "recipient": args.get("recipient_name"),
                })
                conn.commit()
                return json.dumps({"success": True, "id": movement_id, "_reload_page": "Movimento criado. Recarregue a página."}, ensure_ascii=False)

            elif action == "patch_movement":
                movement_id = args.get("movement_id")
                if not movement_id:
                    return json.dumps({"success": False, "error": "movement_id é obrigatório."})
                set_parts = ["updated_at = CURRENT_TIMESTAMP"]
                params_m: Dict[str, Any] = {"id": movement_id}
                scalar = ["date", "date_competencia", "description", "category", "direction",
                          "value", "status", "development_id", "obra_type", "obra_category", "cnpj", "recipient_name"]
                for field in scalar:
                    if field in args and args[field] is not None:
                        set_parts.append(f"{field} = :{field}")
                        params_m[field] = args[field]
                if "is_operational" in args and args["is_operational"] is not None:
                    set_parts.append("is_operational = :is_op")
                    params_m["is_op"] = 1 if args["is_operational"] else 0
                if len(set_parts) == 1:
                    return json.dumps({"success": False, "error": "Nenhum campo fornecido."})
                result = conn.execute(text(f"UPDATE md70_movements SET {', '.join(set_parts)} WHERE id = :id"), params_m)
                conn.commit()
                if result.rowcount == 0:
                    return json.dumps({"success": False, "error": f"Movimento '{movement_id}' não encontrado."})
                return json.dumps({"success": True, "id": movement_id, "_reload_page": "Movimento atualizado. Recarregue a página."}, ensure_ascii=False)

            elif action == "delete_movement":
                movement_id = args.get("movement_id")
                if not movement_id:
                    return json.dumps({"success": False, "error": "movement_id é obrigatório."})
                result = conn.execute(text("DELETE FROM md70_movements WHERE id = :id"), {"id": movement_id})
                conn.commit()
                if result.rowcount == 0:
                    return json.dumps({"success": False, "error": f"Movimento '{movement_id}' não encontrado."})
                return json.dumps({"success": True, "id": movement_id, "_reload_page": "Movimento excluído. Recarregue a página."}, ensure_ascii=False)

            else:
                return json.dumps({"success": False, "error": f"Ação '{action}' desconhecida.", "actions": ["list_movements", "get_movement", "create_movement", "patch_movement", "delete_movement"]})

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def _movement_row(r) -> dict:
    return {
        "id": r[0], "projectId": r[1], "purchaseId": r[2],
        "date": r[3], "description": r[4], "category": r[5],
        "direction": r[6], "value": r[7], "status": r[8],
        "dateCompetencia": r[9],
        "isOperational": bool(r[10]) if r[10] is not None else False,
        "obraType": r[11], "obraCategory": r[12],
        "cnpj": r[13], "recipientName": r[14],
    }
