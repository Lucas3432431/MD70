"""
MD70 Admin Routes — /api/admin/data, /api/admin/leads/{id}, /api/admin/purchases/{id}

TODO: Add proper authentication (TOTP or session-based) before production deployment.
      Currently all endpoints are open (dev mode).
"""

from datetime import date, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from App.Core.Crunch.TablesSQL.Database import database
from App.Core.Logs import info, error

router = APIRouter(prefix="/api/portal-admin", tags=["admin-md70"])
public_router = APIRouter(prefix="/api/public", tags=["public-md70"])

# ---------------------------------------------------------------------------
# Shared lookup lists (single source of truth — edit here to add categories)
# ---------------------------------------------------------------------------

OBRA_TYPES: list[str] = ["MO", "Material"]

OBRA_CATEGORIES: list[str] = [
    "Alvenaria",
    "Aprovação",
    "Aquisição do imóvel",
    "Capital",
    "Custo recorrente",
    "Elétrica",
    "Fundação",
    "Hidráulica",
    "Mão de obra",
    "Máquinas e equipamentos",
    "Projetos",
    "Segurança",
    "Outros",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row) -> dict:
    """Convert a SQLAlchemy Row / RowMapping to a plain dict."""
    try:
        return dict(row._mapping)
    except AttributeError:
        return dict(row)


# ---------------------------------------------------------------------------
# GET /api/admin/data
# ---------------------------------------------------------------------------

@router.get("/data")
async def get_admin_data():
    """
    Returns the full AdminData payload consumed by the admin portal frontend.
    Shape mirrors admin-types.ts: { minQuotes, projects, budgets, suppliers,
                                     purchases, movements, leads }
    """
    engine = database.engine
    # Ensure CDI rates table exists (own connection so it never conflicts with ALTER TABLE migrations)
    try:
        with engine.connect() as _mig:
            _mig.execute(text(
                "CREATE TABLE IF NOT EXISTS md70_cdi_rates "
                "(id TEXT PRIMARY KEY NOT NULL, month TEXT NOT NULL UNIQUE, "
                "rate REAL NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
            ))
            _mig.commit()
    except Exception:
        pass
    try:
        with engine.connect() as conn:
            # -- projects --
            rows = conn.execute(text(
                "SELECT id, name, status, progress, capital, budget, remaining, forecast, image_url, "
                "       city, category, summary, vgv "
                "FROM md70_developments ORDER BY created_at"
            )).fetchall()
            projects = [
                {
                    "id": r[0], "name": r[1], "status": r[2],
                    "progress": r[3], "capital": r[4], "budget": r[5],
                    "remaining": r[6], "forecast": r[7], "imageUrl": r[8],
                    "city": r[9], "category": r[10], "summary": r[11],
                    "vgv": r[12],
                }
                for r in rows
            ]

            # -- budgets --
            rows = conn.execute(text(
                "SELECT id, development_id, category, item, planned, committed, remaining, "
                "       quantity, unit, note "
                "FROM md70_budget_lines ORDER BY development_id, id"
            )).fetchall()
            budgets = [
                {
                    "id": r[0], "projectId": r[1], "category": r[2], "item": r[3],
                    "planned": r[4], "committed": r[5], "remaining": r[6],
                    "quantity": r[7], "unit": r[8], "note": r[9],
                }
                for r in rows
            ]

            # -- suppliers --
            rows = conn.execute(text(
                "SELECT id, name, cnpj, contact, phone, email, notes "
                "FROM md70_suppliers ORDER BY name"
            )).fetchall()
            suppliers = [
                {
                    "id": r[0], "name": r[1], "cnpj": r[2], "contact": r[3],
                    "phone": r[4], "email": r[5], "notes": r[6],
                }
                for r in rows
            ]

            # -- purchases (without quotes first) --
            rows = conn.execute(text(
                "SELECT id, development_id, budget_line_id, description, quantity, unit, "
                "       estimate, requester, date, status, selected_quote_id, "
                "       approved_by, approved_at, justification, paid_at, note, "
                "       cnpj, recipient_name, is_operational, obra_type, obra_category, attachment "
                "FROM md70_purchases ORDER BY date DESC"
            )).fetchall()
            purchases_map: dict = {}
            purchases_list = []
            for r in rows:
                p = {
                    "id": r[0], "projectId": r[1], "budgetId": r[2],
                    "description": r[3], "quantity": r[4], "unit": r[5],
                    "estimate": r[6], "requester": r[7], "date": r[8],
                    "status": r[9], "selectedQuoteId": r[10],
                    "approvedBy": r[11], "approvedAt": r[12],
                    "justification": r[13], "paidAt": r[14], "note": r[15],
                    "cnpj": r[16], "recipientName": r[17],
                    "isOperational": bool(r[18]) if r[18] is not None else False,
                    "obraType": r[19], "obraCategory": r[20],
                    "attachment": r[21],
                    "quotes": [],
                }
                purchases_map[r[0]] = p
                purchases_list.append(p)

            # -- quotes (nested into purchases) --
            rows = conn.execute(text(
                "SELECT id, purchase_id, supplier_id, value, shipping, discount, "
                "       payment, delivery, validity, notes, attachment_url "
                "FROM md70_quotes ORDER BY purchase_id, id"
            )).fetchall()
            for r in rows:
                pur = purchases_map.get(r[1])
                if pur is not None:
                    pur["quotes"].append({
                        "id": r[0], "supplierId": r[2],
                        "value": r[3], "shipping": r[4], "discount": r[5],
                        "payment": r[6], "delivery": r[7], "validity": r[8],
                        "notes": r[9], "attachment": r[10],
                    })

            # -- idempotent migrations --
            for _sql in [
                "ALTER TABLE md70_movements ADD COLUMN supplier_id TEXT REFERENCES md70_suppliers(id)",
                "ALTER TABLE md70_leads ADD COLUMN cpf TEXT",
            ]:
                try:
                    conn.execute(text(_sql))
                    conn.commit()
                except Exception:
                    conn.rollback()

            # -- movements (without attachments first) --
            rows = conn.execute(text(
                "SELECT id, development_id, purchase_id, date, description, category, "
                "       direction, value, status, date_competencia, "
                "       is_operational, obra_type, obra_category, cnpj, recipient_name, supplier_id "
                "FROM md70_movements ORDER BY date DESC"
            )).fetchall()
            movements_map: dict = {}
            movements_list = []
            for r in rows:
                m = {
                    "id": r[0], "projectId": r[1], "purchaseId": r[2],
                    "date": r[3], "description": r[4], "category": r[5],
                    "direction": r[6], "value": r[7], "status": r[8],
                    "dateCompetencia": r[9],
                    "isOperational": bool(r[10]),
                    "obraType": r[11],
                    "obraCategory": r[12],
                    "cnpj": r[13],
                    "recipientName": r[14],
                    "supplierId": r[15],
                    "attachments": [],
                }
                movements_map[r[0]] = m
                movements_list.append(m)

            # -- documents → attachments[] --
            rows = conn.execute(text(
                "SELECT movement_id, url FROM md70_documents ORDER BY created_at"
            )).fetchall()
            for r in rows:
                mov = movements_map.get(r[0])
                if mov is not None:
                    mov["attachments"].append(r[1])

            # -- leads --
            rows = conn.execute(text(
                "SELECT id, name, email, phone, project_interest, status, "
                "       source, value, notes, created_at, project_interests_json, cpf "
                "FROM md70_leads ORDER BY created_at DESC"
            )).fetchall()
            import json as _json2
            leads = []
            for r in rows:
                pi_raw = r[10]
                project_interests = []
                if pi_raw:
                    try:
                        project_interests = _json2.loads(pi_raw)
                    except Exception:
                        pass
                leads.append({
                    "id": r[0], "name": r[1], "email": r[2], "phone": r[3],
                    "projectInterest": r[4], "status": r[5], "source": r[6],
                    "value": r[7], "notes": r[8], "createdAt": r[9],
                    "projectInterests": project_interests,
                    "cpf": r[11],
                })

            # -- CDI rates --
            try:
                cdi_rows = conn.execute(text(
                    "SELECT month, rate FROM md70_cdi_rates ORDER BY month DESC"
                )).fetchall()
                cdi_rates = [{"yearMonth": r[0], "rate": r[1]} for r in cdi_rows]
            except Exception:
                cdi_rates = []

        with engine.connect() as aum_conn:
            aum_data = _calc_aum(aum_conn)
        return {
            "minQuotes": 2,
            "projects": projects,
            "budgets": budgets,
            "suppliers": suppliers,
            "purchases": purchases_list,
            "movements": movements_list,
            "leads": leads,
            "aumCurrent": aum_data["aum_current"],
            "aumRatePerSecond": aum_data["rate_per_second"],
            "cdiRates": cdi_rates,
            "obraCategories": OBRA_CATEGORIES,
            "obraTypes": OBRA_TYPES,
        }

    except Exception as exc:
        error(f"[AdminRoutes] GET /data error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao carregar dados do admin.")


# ---------------------------------------------------------------------------
# PATCH /api/admin/leads/{lead_id}
# ---------------------------------------------------------------------------

class LeadPatch(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    project_interests: Optional[list] = None  # [{projectId, value}]
    value: Optional[float] = None
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    project_interest: Optional[str] = None
    cpf: Optional[str] = None


@router.patch("/leads/{lead_id}")
async def patch_lead(lead_id: str, body: LeadPatch):
    """Update a lead's status and/or notes."""
    engine = database.engine

    valid_statuses = {"Interesse", "Qualificado", "Em negociação", "Investidor ativo", "Descartado", "Descartado/Adiado"}
    if body.status is not None and body.status not in valid_statuses:
        raise HTTPException(
            status_code=422,
            detail=f"Status inválido. Valores aceitos: {', '.join(sorted(valid_statuses))}",
        )

    import json as _json3
    set_parts = ["updated_at = CURRENT_TIMESTAMP"]
    params: dict = {"id": lead_id}
    scalar_lead = {"status": "status", "notes": "notes", "value": "value", "name": "name", "email": "email", "phone": "phone", "source": "source", "project_interest": "project_interest", "cpf": "cpf"}
    for attr, col in scalar_lead.items():
        val = getattr(body, attr)
        if val is not None:
            set_parts.append(f"{col} = :{attr}")
            params[attr] = val
    if body.project_interests is not None:
        set_parts.append("project_interests_json = :pi_json")
        params["pi_json"] = _json3.dumps(body.project_interests)

    if len(set_parts) == 1:
        raise HTTPException(status_code=400, detail="Nenhum campo fornecido.")

    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                f"UPDATE md70_leads SET {', '.join(set_parts)} WHERE id = :id"
            ), params)
            conn.commit()
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail=f"Lead '{lead_id}' não encontrado.")
        info(f"[AdminRoutes] Lead {lead_id} updated: {body.model_dump(exclude_none=True)}")
        return {"ok": True, "id": lead_id}
    except HTTPException:
        raise
    except Exception as exc:
        error(f"[AdminRoutes] PATCH /leads/{lead_id} error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao atualizar lead.")


# ---------------------------------------------------------------------------
# PATCH /api/admin/purchases/{purchase_id}
# ---------------------------------------------------------------------------

class PurchasePatch(BaseModel):
    status: Optional[str] = None
    selectedQuoteId: Optional[str] = None
    approvedBy: Optional[str] = None
    approvedAt: Optional[str] = None
    paidAt: Optional[str] = None
    quantity: Optional[float] = None
    description: Optional[str] = None
    note: Optional[str] = None
    development_id: Optional[str] = None
    cnpj: Optional[str] = None
    recipient_name: Optional[str] = None
    is_operational: Optional[bool] = None
    obra_type: Optional[str] = None
    obra_category: Optional[str] = None
    attachment: Optional[str] = None


@router.patch("/purchases/{purchase_id}")
async def patch_purchase(purchase_id: str, body: PurchasePatch):
    """Update purchase status and approval/payment fields."""
    engine = database.engine

    valid_statuses = {
        "Solicitado", "Fornecedores Contatados",
        "Orçamento 1", "Orçamento 2", "Orçamento 3",
        "Aguardando entrega", "Entregue", "Cancelado",
    }
    if body.status is not None and body.status not in valid_statuses:
        raise HTTPException(
            status_code=422,
            detail=f"Status inválido. Valores aceitos: {', '.join(sorted(valid_statuses))}",
        )

    # Build dynamic SET clause from provided fields only
    set_parts = ["updated_at = CURRENT_TIMESTAMP"]
    params: dict = {"id": purchase_id}

    if body.status is not None:
        set_parts.append("status = :status")
        params["status"] = body.status
    if body.selectedQuoteId is not None:
        set_parts.append("selected_quote_id = :sel_q")
        params["sel_q"] = body.selectedQuoteId
    if body.approvedBy is not None:
        set_parts.append("approved_by = :appr_by")
        params["appr_by"] = body.approvedBy
    if body.approvedAt is not None:
        set_parts.append("approved_at = :appr_at")
        params["appr_at"] = body.approvedAt
    if body.paidAt is not None:
        set_parts.append("paid_at = :paid_at")
        params["paid_at"] = body.paidAt
    if body.quantity is not None:
        set_parts.append("quantity = :quantity")
        params["quantity"] = body.quantity
    if body.description is not None:
        set_parts.append("description = :description")
        params["description"] = body.description
    if body.note is not None:
        set_parts.append("note = :note")
        params["note"] = body.note
    if body.development_id is not None:
        set_parts.append("development_id = :dev_id")
        params["dev_id"] = body.development_id
    if body.cnpj is not None:
        set_parts.append("cnpj = :cnpj")
        params["cnpj"] = body.cnpj
    if body.recipient_name is not None:
        set_parts.append("recipient_name = :recipient_name")
        params["recipient_name"] = body.recipient_name
    if body.is_operational is not None:
        set_parts.append("is_operational = :is_op")
        params["is_op"] = 1 if body.is_operational else 0
    if body.obra_type is not None:
        set_parts.append("obra_type = :obra_type")
        params["obra_type"] = body.obra_type
    if body.obra_category is not None:
        set_parts.append("obra_category = :obra_cat")
        params["obra_cat"] = body.obra_category
    if body.attachment is not None:
        set_parts.append("attachment = :attachment")
        params["attachment"] = body.attachment

    if len(set_parts) == 1:
        raise HTTPException(status_code=400, detail="Nenhum campo fornecido para atualização.")

    sql = f"UPDATE md70_purchases SET {', '.join(set_parts)} WHERE id = :id"

    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql), params)
            conn.commit()
            if result.rowcount == 0:
                raise HTTPException(
                    status_code=404,
                    detail=f"Compra '{purchase_id}' não encontrada.",
                )
        info(f"[AdminRoutes] Purchase {purchase_id} updated: {body.model_dump(exclude_none=True)}")
        return {"ok": True, "id": purchase_id}
    except HTTPException:
        raise
    except Exception as exc:
        error(f"[AdminRoutes] PATCH /purchases/{purchase_id} error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao atualizar compra.")


# ---------------------------------------------------------------------------
# POST /api/portal-admin/projects — create a new development
# ---------------------------------------------------------------------------

class ProjectCreate(BaseModel):
    name: str
    city: Optional[str] = ""
    status: Optional[str] = "Projeto"
    progress: Optional[int] = 0
    capital: Optional[float] = 0
    budget: Optional[float] = 0
    remaining: Optional[float] = 0
    forecast: Optional[str] = None
    image_url: Optional[str] = None
    category: Optional[str] = None
    summary: Optional[str] = None


@router.post("/projects", status_code=201)
async def create_project(body: ProjectCreate):
    """Create a new development project."""
    engine = database.engine
    import uuid as _uuid
    project_id = body.name.lower().replace(" ", "-").replace("/", "-")[:40] + "-" + _uuid.uuid4().hex[:6]
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO md70_developments (id, name, city, status, progress, capital, budget, remaining, forecast, image_url, category, summary) "
                "VALUES (:id, :name, :city, :status, :progress, :capital, :budget, :remaining, :forecast, :image_url, :category, :summary)"
            ), {"id": project_id, "name": body.name, "city": body.city or "", "status": body.status, "progress": body.progress, "capital": body.capital, "budget": body.budget, "remaining": body.remaining, "forecast": body.forecast, "image_url": body.image_url, "category": body.category, "summary": body.summary})
            conn.commit()
        info(f"[AdminRoutes] Project created: {project_id}")
        return {"ok": True, "id": project_id}
    except Exception as exc:
        error(f"[AdminRoutes] POST /projects error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao criar projeto.")


# ---------------------------------------------------------------------------
# PATCH /api/portal-admin/projects/{project_id}
# ---------------------------------------------------------------------------

class ProjectPatch(BaseModel):
    name: Optional[str] = None
    city: Optional[str] = None
    status: Optional[str] = None
    progress: Optional[int] = None
    capital: Optional[float] = None
    budget: Optional[float] = None
    remaining: Optional[float] = None
    forecast: Optional[str] = None
    image_url: Optional[str] = None
    category: Optional[str] = None
    summary: Optional[str] = None
    planned_progress: Optional[int] = None
    current_stage: Optional[str] = None
    next_stage: Optional[str] = None
    vgv: Optional[float] = None


@router.patch("/projects/{project_id}")
async def patch_project(project_id: str, body: ProjectPatch):
    """Update a development project's fields."""
    engine = database.engine
    set_parts = ["updated_at = CURRENT_TIMESTAMP"]
    params: dict = {"id": project_id}
    field_map = {"name": "name", "city": "city", "status": "status", "progress": "progress", "capital": "capital", "budget": "budget", "remaining": "remaining", "forecast": "forecast", "image_url": "image_url", "category": "category", "summary": "summary", "planned_progress": "planned_progress", "current_stage": "current_stage", "next_stage": "next_stage", "vgv": "vgv"}
    for field, col in field_map.items():
        val = getattr(body, field)
        if val is not None:
            set_parts.append(f"{col} = :{field}")
            params[field] = val
    if len(set_parts) == 1:
        raise HTTPException(status_code=400, detail="Nenhum campo fornecido.")
    sql = f"UPDATE md70_developments SET {', '.join(set_parts)} WHERE id = :id"
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql), params)
            conn.commit()
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail=f"Projeto '{project_id}' não encontrado.")
        return {"ok": True, "id": project_id}
    except HTTPException:
        raise
    except Exception as exc:
        error(f"[AdminRoutes] PATCH /projects/{project_id} error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao atualizar projeto.")


# ---------------------------------------------------------------------------
# POST /api/portal-admin/leads — create a new lead
# ---------------------------------------------------------------------------

class LeadCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    cpf: Optional[str] = None
    project_interest: Optional[str] = None
    status: Optional[str] = "Interesse"
    source: Optional[str] = None
    value: Optional[float] = 0
    notes: Optional[str] = None


@router.post("/leads", status_code=201)
async def create_lead(body: LeadCreate):
    """Create a new CRM lead."""
    engine = database.engine
    import uuid as _uuid
    lead_id = "l-" + _uuid.uuid4().hex[:10]
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO md70_leads (id, name, email, phone, cpf, project_interest, status, source, value, notes) "
                "VALUES (:id, :name, :email, :phone, :cpf, :project_interest, :status, :source, :value, :notes)"
            ), {"id": lead_id, "name": body.name, "email": body.email, "phone": body.phone, "cpf": body.cpf, "project_interest": body.project_interest, "status": body.status, "source": body.source, "value": body.value or 0, "notes": body.notes})
            conn.commit()
        info(f"[AdminRoutes] Lead created: {lead_id}")
        return {"ok": True, "id": lead_id}
    except Exception as exc:
        error(f"[AdminRoutes] POST /leads error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao criar lead.")


# ---------------------------------------------------------------------------
# POST /api/portal-admin/purchases — create a new purchase request
# ---------------------------------------------------------------------------

class PurchaseCreate(BaseModel):
    development_id: str
    budget_line_id: Optional[str] = None
    description: str
    quantity: Optional[float] = 1
    unit: Optional[str] = "serviço"
    estimate: Optional[float] = 0
    requester: Optional[str] = None
    date: Optional[str] = None
    note: Optional[str] = None


@router.post("/purchases", status_code=201)
async def create_purchase(body: PurchaseCreate):
    """Create a new purchase request."""
    engine = database.engine
    import uuid as _uuid
    from datetime import date as _date
    purchase_id = "c-" + _uuid.uuid4().hex[:10]
    purchase_date = body.date or _date.today().isoformat()
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO md70_purchases (id, development_id, budget_line_id, description, quantity, unit, estimate, requester, date, status, note) "
                "VALUES (:id, :dev_id, :budget_id, :desc, :qty, :unit, :estimate, :requester, :date, 'Solicitado', :note)"
            ), {"id": purchase_id, "dev_id": body.development_id, "budget_id": body.budget_line_id, "desc": body.description, "qty": body.quantity, "unit": body.unit, "estimate": body.estimate, "requester": body.requester, "date": purchase_date, "note": body.note})
            conn.commit()
        info(f"[AdminRoutes] Purchase created: {purchase_id}")
        return {"ok": True, "id": purchase_id}
    except Exception as exc:
        error(f"[AdminRoutes] POST /purchases error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao criar compra.")


# ---------------------------------------------------------------------------
# POST /api/portal-admin/movements — create a financial movement
# ---------------------------------------------------------------------------

class MovementCreate(BaseModel):
    development_id: Optional[str] = None
    date: Optional[str] = None
    date_competencia: Optional[str] = None
    description: str
    category: str
    direction: str  # "Entrada" or "Saída"
    value: float
    status: Optional[str] = "Realizado"
    purchase_id: Optional[str] = None
    is_operational: Optional[bool] = False
    obra_type: Optional[str] = None
    obra_category: Optional[str] = None
    supplier_id: Optional[str] = None


@router.post("/movements", status_code=201)
async def create_movement(body: MovementCreate):
    """Create a new financial movement."""
    engine = database.engine
    import uuid as _uuid
    from datetime import date as _date
    movement_id = "m-" + _uuid.uuid4().hex[:10]
    movement_date = body.date or _date.today().isoformat()
    if body.direction not in ("Entrada", "Saída"):
        raise HTTPException(status_code=422, detail="direction deve ser 'Entrada' ou 'Saída'.")
    dev_id = body.development_id or ("fundo-md70" if body.is_operational else None)
    if not dev_id:
        raise HTTPException(status_code=422, detail="development_id é obrigatório para movimentos de empreendimento.")

    cnpj = None
    recipient = None
    # If supplier_id provided, pull cnpj/name from suppliers table
    if body.supplier_id:
        try:
            with engine.connect() as _sc:
                sup = _sc.execute(text("SELECT name, cnpj FROM md70_suppliers WHERE id = :id"), {"id": body.supplier_id}).fetchone()
                if sup:
                    recipient = sup[0]
                    cnpj = sup[1] or cnpj
        except Exception:
            pass

    try:
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO md70_movements "
                "(id, development_id, purchase_id, date, date_competencia, description, category, direction, value, status, is_operational, obra_type, obra_category, cnpj, recipient_name, supplier_id) "
                "VALUES (:id, :dev_id, :purchase_id, :date, :date_competencia, :desc, :category, :direction, :value, :status, :is_op, :obra_type, :obra_cat, :cnpj, :recipient, :sup_id)"
            ), {
                "id": movement_id, "dev_id": dev_id, "purchase_id": body.purchase_id,
                "date": movement_date, "date_competencia": body.date_competencia,
                "desc": body.description, "category": body.category,
                "direction": body.direction, "value": body.value, "status": body.status,
                "is_op": 1 if body.is_operational else 0,
                "obra_type": body.obra_type, "obra_cat": body.obra_category,
                "cnpj": cnpj, "recipient": recipient,
                "sup_id": body.supplier_id,
            })
            conn.commit()
        info(f"[AdminRoutes] Movement created: {movement_id}")
        return {"ok": True, "id": movement_id}
    except Exception as exc:
        error(f"[AdminRoutes] POST /movements error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao criar movimento.")


# ---------------------------------------------------------------------------
# PATCH /api/portal-admin/movements/{movement_id}
# ---------------------------------------------------------------------------

class MovementPatch(BaseModel):
    date: Optional[str] = None
    date_competencia: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    direction: Optional[str] = None
    value: Optional[float] = None
    status: Optional[str] = None
    development_id: Optional[str] = None
    is_operational: Optional[bool] = None
    obra_type: Optional[str] = None
    obra_category: Optional[str] = None
    supplier_id: Optional[str] = None
    recipient_name: Optional[str] = None
    attachment_url: Optional[str] = None


@router.patch("/movements/{movement_id}")
async def patch_movement(movement_id: str, body: MovementPatch):
    """Update a financial movement."""
    engine = database.engine
    set_parts = ["updated_at = CURRENT_TIMESTAMP"]
    params: dict = {"id": movement_id}
    scalar_fields = ["date", "date_competencia", "description", "category", "direction", "value", "status", "development_id", "obra_type", "obra_category", "supplier_id", "recipient_name"]
    for field in scalar_fields:
        val = getattr(body, field)
        if val is not None:
            set_parts.append(f"{field} = :{field}")
            params[field] = val
    if body.is_operational is not None:
        set_parts.append("is_operational = :is_op")
        params["is_op"] = 1 if body.is_operational else 0
    if body.attachment_url is not None:
        set_parts.append("attachment = :attachment")
        params["attachment"] = body.attachment_url
    if len(set_parts) == 1:
        raise HTTPException(status_code=400, detail="Nenhum campo fornecido.")
    sql = f"UPDATE md70_movements SET {', '.join(set_parts)} WHERE id = :id"
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql), params)
            conn.commit()
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail=f"Movimento '{movement_id}' não encontrado.")
        return {"ok": True, "id": movement_id}
    except HTTPException:
        raise
    except Exception as exc:
        error(f"[AdminRoutes] PATCH /movements/{movement_id} error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao atualizar movimento.")


# ---------------------------------------------------------------------------
# DELETE /api/portal-admin/movements/{movement_id}
# ---------------------------------------------------------------------------

@router.delete("/movements/{movement_id}", status_code=200)
async def delete_movement(movement_id: str):
    """Delete a financial movement."""
    engine = database.engine
    try:
        with engine.connect() as conn:
            result = conn.execute(text("DELETE FROM md70_movements WHERE id = :id"), {"id": movement_id})
            conn.commit()
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail=f"Movimento '{movement_id}' não encontrado.")
        info(f"[AdminRoutes] Movement deleted: {movement_id}")
        return {"ok": True, "id": movement_id}
    except HTTPException:
        raise
    except Exception as exc:
        error(f"[AdminRoutes] DELETE /movements/{movement_id} error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao deletar movimento.")


# ---------------------------------------------------------------------------
# DELETE /api/portal-admin/leads/{lead_id}
# ---------------------------------------------------------------------------

@router.delete("/leads/{lead_id}", status_code=200)
async def delete_lead(lead_id: str):
    """Delete a CRM lead."""
    engine = database.engine
    try:
        with engine.connect() as conn:
            result = conn.execute(text("DELETE FROM md70_leads WHERE id = :id"), {"id": lead_id})
            conn.commit()
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail=f"Lead '{lead_id}' não encontrado.")
        info(f"[AdminRoutes] Lead deleted: {lead_id}")
        return {"ok": True, "id": lead_id}
    except HTTPException:
        raise
    except Exception as exc:
        error(f"[AdminRoutes] DELETE /leads/{lead_id} error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao deletar lead.")


# ---------------------------------------------------------------------------
# DELETE /api/portal-admin/purchases/{purchase_id}
# ---------------------------------------------------------------------------

@router.delete("/purchases/{purchase_id}", status_code=200)
async def delete_purchase(purchase_id: str):
    """Delete a purchase request."""
    engine = database.engine
    try:
        with engine.connect() as conn:
            result = conn.execute(text("DELETE FROM md70_purchases WHERE id = :id"), {"id": purchase_id})
            conn.commit()
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail=f"Compra '{purchase_id}' não encontrada.")
        info(f"[AdminRoutes] Purchase deleted: {purchase_id}")
        return {"ok": True, "id": purchase_id}
    except HTTPException:
        raise
    except Exception as exc:
        error(f"[AdminRoutes] DELETE /purchases/{purchase_id} error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao deletar compra.")


# ---------------------------------------------------------------------------
# POST /api/portal-admin/quotes — add a quote to a purchase
# ---------------------------------------------------------------------------

class QuoteCreate(BaseModel):
    purchase_id: str
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None  # free-text if no supplier record
    value: float = 0
    shipping: Optional[float] = 0
    discount: Optional[float] = 0
    payment: Optional[str] = ""
    delivery: Optional[str] = ""
    validity: Optional[str] = None
    notes: Optional[str] = None
    attachment_url: Optional[str] = None


@router.post("/quotes", status_code=201)
async def create_quote(body: QuoteCreate):
    """Add a new quote to a purchase."""
    engine = database.engine
    import uuid as _uuid
    from datetime import date as _date
    quote_id = "q-" + _uuid.uuid4().hex[:10]
    # supplier_id required by FK — use a free-text supplier record if none given
    if not body.supplier_id:
        # auto-create a supplier for the free-text name
        sup_id = "s-" + _uuid.uuid4().hex[:8]
        sup_name = body.supplier_name or "Fornecedor"
        try:
            with engine.connect() as conn:
                conn.execute(text(
                    "INSERT OR IGNORE INTO md70_suppliers (id, name) VALUES (:id, :name)"
                ), {"id": sup_id, "name": sup_name})
                conn.commit()
        except Exception:
            sup_id = "s-default"
        supplier_id = sup_id
    else:
        supplier_id = body.supplier_id
    validity = body.validity or _date.today().isoformat()
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO md70_quotes (id, purchase_id, supplier_id, value, shipping, discount, payment, delivery, validity, notes, attachment_url) "
                "VALUES (:id, :pur_id, :sup_id, :value, :shipping, :discount, :payment, :delivery, :validity, :notes, :att)"
            ), {"id": quote_id, "pur_id": body.purchase_id, "sup_id": supplier_id, "value": body.value, "shipping": body.shipping or 0, "discount": body.discount or 0, "payment": body.payment or "", "delivery": body.delivery or "", "validity": validity, "notes": body.notes, "att": body.attachment_url})
            conn.commit()
        info(f"[AdminRoutes] Quote created: {quote_id}")
        return {"ok": True, "id": quote_id, "supplierId": supplier_id}
    except Exception as exc:
        error(f"[AdminRoutes] POST /quotes error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao criar cotação.")


# ---------------------------------------------------------------------------
# PATCH /api/portal-admin/quotes/{quote_id}
# ---------------------------------------------------------------------------

class QuotePatch(BaseModel):
    supplier_name: Optional[str] = None
    value: Optional[float] = None
    shipping: Optional[float] = None
    discount: Optional[float] = None
    payment: Optional[str] = None
    delivery: Optional[str] = None
    validity: Optional[str] = None
    notes: Optional[str] = None
    attachment_url: Optional[str] = None


@router.patch("/quotes/{quote_id}")
async def patch_quote(quote_id: str, body: QuotePatch):
    """Update an existing quote."""
    engine = database.engine
    set_parts: list[str] = []
    params: dict = {"id": quote_id}
    field_map = {"value": "value", "shipping": "shipping", "discount": "discount", "payment": "payment", "delivery": "delivery", "validity": "validity", "notes": "notes", "attachment_url": "attachment_url"}
    for attr, col in field_map.items():
        val = getattr(body, attr)
        if val is not None:
            set_parts.append(f"{col} = :{attr}")
            params[attr] = val
    if body.supplier_name is not None:
        # Update the supplier name linked to this quote
        try:
            with engine.connect() as conn:
                conn.execute(text(
                    "UPDATE md70_suppliers SET name = :name "
                    "WHERE id = (SELECT supplier_id FROM md70_quotes WHERE id = :qid)"
                ), {"name": body.supplier_name, "qid": quote_id})
                conn.commit()
        except Exception:
            pass
    if not set_parts:
        return {"ok": True, "id": quote_id}
    sql = f"UPDATE md70_quotes SET {', '.join(set_parts)} WHERE id = :id"
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql), params)
            conn.commit()
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail=f"Cotação '{quote_id}' não encontrada.")
        return {"ok": True, "id": quote_id}
    except HTTPException:
        raise
    except Exception as exc:
        error(f"[AdminRoutes] PATCH /quotes/{quote_id} error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao atualizar cotação.")


# ---------------------------------------------------------------------------
# DELETE /api/portal-admin/quotes/{quote_id}
# ---------------------------------------------------------------------------

class BudgetLinePatch(BaseModel):
    planned: Optional[float] = None
    remaining: Optional[float] = None
    note: Optional[str] = None


@router.patch("/budget-lines/{line_id}")
async def patch_budget_line(line_id: str, body: BudgetLinePatch):
    """Update planned and/or remaining on a budget line."""
    engine = database.engine
    set_parts: list[str] = []
    params: dict = {"id": line_id}
    if body.planned is not None:
        set_parts.append("planned = :planned")
        params["planned"] = body.planned
    if body.remaining is not None:
        set_parts.append("remaining = :remaining")
        params["remaining"] = body.remaining
    if body.note is not None:
        set_parts.append("note = :note")
        params["note"] = body.note
    if not set_parts:
        return {"ok": True, "id": line_id}
    sql = f"UPDATE md70_budget_lines SET {', '.join(set_parts)} WHERE id = :id"
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql), params)
            conn.commit()
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail=f"Linha '{line_id}' não encontrada.")
        return {"ok": True, "id": line_id}
    except HTTPException:
        raise
    except Exception as exc:
        error(f"[AdminRoutes] PATCH /budget-lines/{line_id} error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao atualizar linha orçamentária.")


@router.delete("/quotes/{quote_id}", status_code=200)
async def delete_quote(quote_id: str):
    """Delete a quote."""
    engine = database.engine
    try:
        with engine.connect() as conn:
            result = conn.execute(text("DELETE FROM md70_quotes WHERE id = :id"), {"id": quote_id})
            conn.commit()
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail=f"Cotação '{quote_id}' não encontrada.")
        return {"ok": True, "id": quote_id}
    except HTTPException:
        raise
    except Exception as exc:
        error(f"[AdminRoutes] DELETE /quotes/{quote_id} error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao deletar cotação.")


# ---------------------------------------------------------------------------
# CRUD /api/portal-admin/suppliers
# ---------------------------------------------------------------------------

class SupplierCreate(BaseModel):
    name: str
    cnpj: Optional[str] = None
    contact: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None


class SupplierPatch(BaseModel):
    name: Optional[str] = None
    cnpj: Optional[str] = None
    contact: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None


@router.post("/suppliers", status_code=201)
async def create_supplier(body: SupplierCreate):
    import uuid as _uuid
    sup_id = "sup-" + _uuid.uuid4().hex[:10]
    engine = database.engine
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO md70_suppliers (id, name, cnpj, contact, phone, email, notes) "
                "VALUES (:id, :name, :cnpj, :contact, :phone, :email, :notes)"
            ), {"id": sup_id, "name": body.name.strip(), "cnpj": body.cnpj, "contact": body.contact, "phone": body.phone, "email": body.email, "notes": body.notes})
            conn.commit()
        return {"ok": True, "id": sup_id}
    except Exception as exc:
        error(f"[AdminRoutes] POST /suppliers error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao criar fornecedor.")


@router.patch("/suppliers/{supplier_id}")
async def patch_supplier(supplier_id: str, body: SupplierPatch):
    engine = database.engine
    set_parts: list[str] = []
    params: dict = {"id": supplier_id}
    for field in ["name", "cnpj", "contact", "phone", "email", "notes"]:
        val = getattr(body, field)
        if val is not None:
            set_parts.append(f"{field} = :{field}")
            params[field] = val
    if not set_parts:
        return {"ok": True, "id": supplier_id}
    sql = f"UPDATE md70_suppliers SET {', '.join(set_parts)} WHERE id = :id"
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql), params)
            conn.commit()
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="Fornecedor não encontrado.")
        return {"ok": True, "id": supplier_id}
    except HTTPException:
        raise
    except Exception as exc:
        error(f"[AdminRoutes] PATCH /suppliers/{supplier_id} error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao atualizar fornecedor.")


@router.delete("/suppliers/{supplier_id}", status_code=200)
async def delete_supplier(supplier_id: str):
    engine = database.engine
    try:
        with engine.connect() as conn:
            result = conn.execute(text("DELETE FROM md70_suppliers WHERE id = :id"), {"id": supplier_id})
            conn.commit()
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="Fornecedor não encontrado.")
        return {"ok": True, "id": supplier_id}
    except HTTPException:
        raise
    except Exception as exc:
        error(f"[AdminRoutes] DELETE /suppliers/{supplier_id} error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao deletar fornecedor.")


# ---------------------------------------------------------------------------
# PUT /api/portal-admin/cdi/{year_month} — upsert CDI rate for a month
# ---------------------------------------------------------------------------

class CdiRatePatch(BaseModel):
    rate: float


@router.put("/cdi/{year_month}", status_code=200)
async def upsert_cdi_rate(year_month: str, body: CdiRatePatch):
    """Create or update the CDI effective rate for a given year-month (YYYY-MM)."""
    engine = database.engine
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO md70_cdi_rates (id, month, rate) VALUES (:id, :ym, :r) "
                "ON CONFLICT(month) DO UPDATE SET rate = excluded.rate"
            ), {"id": year_month, "ym": year_month, "r": body.rate})
            conn.commit()
        info(f"[AdminRoutes] CDI rate upserted: {year_month} = {body.rate}%")
        return {"ok": True, "yearMonth": year_month, "rate": body.rate}
    except Exception as exc:
        error(f"[AdminRoutes] PUT /cdi/{year_month} error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao salvar CDI.")


# ---------------------------------------------------------------------------
# AUM helpers — shared between admin and public endpoints
# ---------------------------------------------------------------------------

_CDI_MONTHLY_RATE = 0.01          # 1 % a.m.  (kept for reference, no longer used by _calc_aum)
_SECONDS_PER_MONTH = 30.44 * 24 * 3600  # ≈ 2,630,016  (kept for reference)


# ---------------------------------------------------------------------------
# Brazilian banking calendar helpers
# ---------------------------------------------------------------------------

def _easter(year: int) -> date:
    """Computus algorithm — returns Easter Sunday for the given year."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


_holidays_cache: dict = {}


def _br_holidays(year: int) -> frozenset:
    if year in _holidays_cache:
        return _holidays_cache[year]
    e = _easter(year)
    h = {
        date(year, 1, 1),
        e - timedelta(days=2),       # Sexta-feira Santa
        e + timedelta(days=60),      # Corpus Christi
        date(year, 4, 21),
        date(year, 5, 1),
        date(year, 9, 7),
        date(year, 10, 12),
        date(year, 11, 2),
        date(year, 11, 15),
        date(year, 12, 25),
        e - timedelta(days=47),      # Carnival Tuesday
    }
    if year >= 2024:
        h.add(date(year, 11, 20))    # Consciência Negra
    result = frozenset(h)
    _holidays_cache[year] = result
    return result


def _is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in _br_holidays(d.year)


def _count_bdays(start: date, end_exclusive: date) -> int:
    """Count Brazilian banking business days in [start, end_exclusive)."""
    count = 0
    cur = start
    while cur < end_exclusive:
        if _is_business_day(cur):
            count += 1
        cur += timedelta(days=1)
    return count


def _cdi_factor(start: date, end: date, rate_map: dict) -> float:
    """
    Accumulate CDI factor from start (inclusive) to end (exclusive).
    rate_map: {year_month_str: float} where float is monthly rate as decimal (e.g. 0.0107).
    Uses business-day-proportional compounding per month.
    """
    factor = 1.0
    cur = start
    while cur < end:
        ym = f"{cur.year}-{cur.month:02d}"
        monthly_rate = rate_map.get(ym, 0.0)
        # month boundaries
        if cur.month == 12:
            next_month = date(cur.year + 1, 1, 1)
        else:
            next_month = date(cur.year, cur.month + 1, 1)
        month_start = date(cur.year, cur.month, 1)
        total_bdays = _count_bdays(month_start, next_month)
        period_end = min(end, next_month)
        bdays = _count_bdays(cur, period_end)
        if total_bdays > 0 and bdays > 0 and monthly_rate > 0:
            daily = (1 + monthly_rate) ** (1.0 / total_bdays) - 1
            factor *= (1 + daily) ** bdays
        cur = next_month
    return factor


def _calc_aum(conn) -> dict:
    """
    Returns base AUM (Capital Realizado movements) plus CDI accrued per-investment
    using actual monthly CDI rates from the md70_cdi_rates table and a Brazilian
    banking calendar for business-day-proportional compounding.
    """
    from datetime import datetime, timezone

    # Load CDI rates
    try:
        rows = conn.execute(text("SELECT month, rate FROM md70_cdi_rates")).fetchall()
        rate_map = {r[0]: r[1] / 100.0 for r in rows}
    except Exception:
        rate_map = {}

    # Fetch all Capital/Realizado movements with their dates
    rows = conn.execute(text(
        "SELECT date, direction, value FROM md70_movements "
        "WHERE status = 'Realizado' AND category = 'Capital'"
    )).fetchall()

    today = datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc)

    base_aum = 0.0
    cdi_aum = 0.0
    for r in rows:
        mv_date_str, direction, value = r[0], r[1], float(r[2])
        signed = value if direction == "Entrada" else -value
        base_aum += signed
        try:
            mv_date = date.fromisoformat(mv_date_str[:10])
            if mv_date < today and signed > 0:
                factor = _cdi_factor(mv_date, today, rate_map)
                cdi_aum += signed * factor
            else:
                cdi_aum += signed
        except Exception:
            cdi_aum += signed

    month_start_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elapsed_seconds = (now - month_start_dt).total_seconds()

    # Current month's CDI ticker: cdi_aum grows at daily rate within current month
    today_ym = f"{today.year}-{today.month:02d}"
    cur_monthly = rate_map.get(today_ym, 0.01)
    if today.month == 12:
        next_mo = date(today.year + 1, 1, 1)
    else:
        next_mo = date(today.year, today.month + 1, 1)
    month_start_date = date(today.year, today.month, 1)
    total_bdays_cur = _count_bdays(month_start_date, next_mo)
    daily_rate = (1 + cur_monthly) ** (1.0 / max(total_bdays_cur, 21)) - 1
    seconds_per_day = 86400
    rate_per_second = cdi_aum * daily_rate / seconds_per_day

    aum_current = cdi_aum + rate_per_second * elapsed_seconds

    return {
        "aum": base_aum,
        "aum_current": aum_current,
        "rate_per_second": rate_per_second,
    }


# ---------------------------------------------------------------------------
# GET /api/public/aum — patrimônio sob gestão (public, no auth required)
# ---------------------------------------------------------------------------

@public_router.get("/aum")
async def get_public_aum():
    engine = database.engine
    try:
        with engine.connect() as conn:
            return _calc_aum(conn)
    except Exception as exc:
        error(f"[PublicRoutes] GET /aum error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno.")
