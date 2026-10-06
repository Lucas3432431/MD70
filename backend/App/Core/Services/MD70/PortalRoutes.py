"""
MD70 Portal Routes — /api/portal/data, /api/portal/developments

TODO: Read investor_id from authenticated session instead of the hardcoded dev value.
      Replace DEV_INVESTOR_ID with a proper session/token lookup before production.
"""

import json as _json

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from App.Core.Crunch.TablesSQL.Database import database
from App.Core.Logs import info, error

router = APIRouter(prefix="/api/portal", tags=["portal-md70"])

# TODO: Replace with session-based lookup (e.g. request.scope["_auth_payload"]["investor_id"])
DEV_INVESTOR_ID = "inv-ricardo"


# ---------------------------------------------------------------------------
# GET /api/portal/data
# ---------------------------------------------------------------------------

@router.get("/data")
async def get_portal_data():
    """
    Returns everything the investor portal needs in a single round-trip:
      - investor profile
      - investments with monthly snapshots series
      - announcements
    """
    engine = database.engine
    try:
        with engine.connect() as conn:
            # -- investor --
            row = conn.execute(text(
                "SELECT id, name, email FROM md70_investors WHERE id = :inv_id"
            ), {"inv_id": DEV_INVESTOR_ID}).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Investidor não encontrado.")
            investor = {"id": row[0], "name": row[1], "email": row[2]}

            # -- investments for this investor --
            inv_rows = conn.execute(text(
                "SELECT id, development_id, invested "
                "FROM md70_investments WHERE investor_id = :inv_id ORDER BY created_at"
            ), {"inv_id": DEV_INVESTOR_ID}).fetchall()

            investments = []
            for inv_id, dev_id, invested in inv_rows:
                # snapshots ordered by month
                snap_rows = conn.execute(text(
                    "SELECT month, invested, value, cdi_value "
                    "FROM md70_investment_snapshots "
                    "WHERE investment_id = :inv_id ORDER BY month ASC"
                ), {"inv_id": inv_id}).fetchall()

                series = []
                last_value = invested
                last_cdi_value = invested
                for month, s_invested, s_value, s_cdi_value in snap_rows:
                    # Fetch CDI rate for this month to include in series point
                    cdi_row = conn.execute(text(
                        "SELECT rate FROM md70_cdi_rates WHERE month = :month"
                    ), {"month": month}).fetchone()
                    cdi_rate = cdi_row[0] if cdi_row else 0.0
                    return_rate = (
                        (s_value / last_value - 1) * 100 if last_value > 0 else 0.0
                    )
                    series.append({
                        "month": month,
                        "invested": s_invested,
                        "value": s_value,
                        "cdiValue": s_cdi_value,
                        "cdiRate": cdi_rate,
                        "returnRate": round(return_rate, 4),
                    })
                    last_value = s_value
                    last_cdi_value = s_cdi_value

                # Summarize from latest snapshot
                if series:
                    latest = series[-1]
                    lat_value = latest["value"]
                    lat_cdi = latest["cdiValue"]
                    rent = round((lat_value - invested) / invested * 100, 4) if invested else 0.0
                    cdi_rent = round((lat_cdi - invested) / invested * 100, 4) if invested else 0.0
                else:
                    lat_value = invested
                    lat_cdi = invested
                    rent = 0.0
                    cdi_rent = 0.0

                investments.append({
                    "id": inv_id,
                    "developmentId": dev_id,
                    "invested": invested,
                    "value": lat_value,
                    "cdiValue": lat_cdi,
                    "rent": rent,
                    "cdiRent": cdi_rent,
                    "series": series,
                })

            # -- announcements --
            ann_rows = conn.execute(text(
                "SELECT id, created_at, title, body, development_id "
                "FROM md70_announcements ORDER BY created_at DESC"
            )).fetchall()
            announcements = [
                {
                    "id": r[0], "date": r[1], "title": r[2],
                    "summary": r[3], "developmentId": r[4],
                }
                for r in ann_rows
            ]

        return {
            "investor": investor,
            "investments": investments,
            "announcements": announcements,
        }

    except HTTPException:
        raise
    except Exception as exc:
        error(f"[PortalRoutes] GET /portal/data error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao carregar dados do portal.")


# ---------------------------------------------------------------------------
# GET /api/portal/developments
# ---------------------------------------------------------------------------

@router.get("/developments")
async def get_portal_developments():
    """
    Returns the developments in which this investor has active investments,
    enriched with the project fields used by the admin portal (same AdminProject shape).
    """
    engine = database.engine
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT d.id, d.name, d.status, d.progress, d.capital, "
                "       d.budget, d.remaining, d.forecast, d.image_url, "
                "       d.city, d.category, d.summary, d.planned_progress, "
                "       d.current_stage, d.next_stage "
                "FROM md70_developments d "
                "INNER JOIN md70_investments i ON i.development_id = d.id "
                "WHERE i.investor_id = :inv_id "
                "ORDER BY d.created_at"
            ), {"inv_id": DEV_INVESTOR_ID}).fetchall()

            developments = [
                {
                    "id": r[0], "name": r[1], "status": r[2],
                    "progress": r[3], "capital": r[4],
                    "budget": r[5], "remaining": r[6],
                    "forecast": r[7], "imageUrl": r[8],
                    "city": r[9], "category": r[10], "summary": r[11],
                    "plannedProgress": r[12] or 0,
                    "currentStage": r[13], "nextStage": r[14],
                }
                for r in rows
            ]

        return developments

    except Exception as exc:
        error(f"[PortalRoutes] GET /portal/developments error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao carregar empreendimentos.")


# ---------------------------------------------------------------------------
# GET /api/portal/documents
# ---------------------------------------------------------------------------

@router.get("/documents")
async def get_portal_documents():
    """Returns investor-facing documents."""
    engine = database.engine
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT d.id, d.name, d.category, d.date, d.size, d.file_url, d.development_id, "
                "       dev.name as dev_name "
                "FROM md70_investor_documents d "
                "LEFT JOIN md70_developments dev ON dev.id = d.development_id "
                "ORDER BY d.date DESC"
            )).fetchall()
            documents = [
                {
                    "id": r[0], "name": r[1], "category": r[2],
                    "date": r[3], "size": r[4], "fileUrl": r[5],
                    "developmentId": r[6], "developmentName": r[7],
                }
                for r in rows
            ]
        return documents
    except Exception as exc:
        error(f"[PortalRoutes] GET /portal/documents error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao carregar documentos.")


# ---------------------------------------------------------------------------
# GET /api/portal/developments/{dev_id}
# ---------------------------------------------------------------------------

@router.get("/developments/{dev_id}")
async def get_portal_development_detail(dev_id: str):
    """Returns full detail for a single development including construction diary, milestones, budget, etc."""
    engine = database.engine
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT id, name, city, status, progress, planned_progress, capital, budget, remaining, "
                "       forecast, image_url, category, summary, current_stage, next_stage, "
                "       gallery_json, plan_json, scenarios_json, milestones_json, gantt_months_json, "
                "       diary_json, budget_series_json, budget_items_json, result_json, "
                "       month_changes_json, month_impact "
                "FROM md70_developments WHERE id = :id"
            ), {"id": dev_id}).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Empreendimento não encontrado.")

            def _json_or(val, default):
                if val:
                    try:
                        return _json.loads(val)
                    except Exception:
                        pass
                return default

            return {
                "id": row[0], "name": row[1], "city": row[2],
                "status": row[3], "progress": row[4], "plannedProgress": row[5] or 0,
                "capital": row[6], "budget": row[7], "remaining": row[8],
                "forecast": row[9], "imageUrl": row[10], "category": row[11],
                "summary": row[12], "currentStage": row[13], "nextStage": row[14],
                "gallery": _json_or(row[15], []),
                "plan": _json_or(row[16], {}),
                "scenarios": _json_or(row[17], []),
                "milestones": _json_or(row[18], []),
                "ganttMonths": _json_or(row[19], []),
                "diary": _json_or(row[20], []),
                "budgetSeries": _json_or(row[21], []),
                "budgetItems": _json_or(row[22], []),
                "result": _json_or(row[23], []),
                "monthChanges": _json_or(row[24], []),
                "monthImpact": row[25] or "",
            }
    except HTTPException:
        raise
    except Exception as exc:
        error(f"[PortalRoutes] GET /portal/developments/{dev_id} error: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao carregar empreendimento.")
