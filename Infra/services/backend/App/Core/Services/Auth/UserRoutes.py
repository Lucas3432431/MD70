from typing import Optional, List
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
import json
from App.Core.Logs import info, error, debug
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Features.Auth import get_auth_service

user_router = APIRouter(tags=["User"], prefix="/api/user")

# ========================================================================
# MODELS
# ========================================================================


class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = None
    whatsapp: Optional[str] = None
    telegram: Optional[str] = None
    instagram: Optional[str] = None
    job_title: Optional[str] = None
    language: Optional[str] = None
    timezone: Optional[str] = None


# ========================================================================
# HELPERS
# ========================================================================


def _get_user_id_from_request(request: Request) -> Optional[str]:
    try:
        from App.Core.Services.Auth.RequestAuth import get_user_id_from_request

        return get_user_id_from_request(request)
    except Exception:
        return None


# ========================================================================
# ROUTES
# ========================================================================


@user_router.get("/profile-interface")
async def get_profile_interface(request: Request):
    user_id = _get_user_id_from_request(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Não autenticado")

    session = DatabaseManager.get_session()
    try:
        # Busca dados do usuário
        user_row = session.execute(
            text("SELECT * FROM users WHERE user_id = :uid LIMIT 1"), {"uid": user_id}
        ).fetchone()

        if not user_row:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")

        user_data = dict(user_row._mapping)
        # Remove senha do retorno
        user_data.pop("password", None)

        # Busca dados do cliente (workspace)
        client_row = session.execute(
            text("SELECT * FROM clients WHERE client_id = :cid LIMIT 1"),
            {"cid": user_data["client_id"]},
        ).fetchone()
        client_data = dict(client_row._mapping) if client_row else {}

        # Constrói resposta no formato esperado pelo frontend
        return {
            "user": {
                "id": user_data["id"],
                "user_id": user_data["user_id"],
                "client_id": user_data["client_id"],
                "email": user_data["email"],
                "full_name": user_data["full_name"],
                "whatsapp": user_data.get("whatsapp"),
                "telegram": user_data.get("telegram"),
                "instagram": user_data.get("instagram"),
                "role": user_data.get("type", "member"),
                "created_at": user_data["created_at"],
                "updated_at": user_data["updated_at"],
            },
            "client": {
                "id": client_data.get("client_id"),
                "legal_company_name": client_data.get("name") or "Minha Workspace",
                "subscription_status": "active",  # Placeholder
            },
            "permissions": {
                "is_founder": True,
                "role": user_data.get("type", "member"),
                "can_manage_users": True,
            },
            "preferences": {
                "language": "pt",
                "timezone": "America/Sao_Paulo",
                "screen_mode": "dark",
            },
            "authentication": {
                "type": "email_password",
                "is_oauth": False,
                "has_password": True,
            },
            "notifications": {"preferences": [], "quiet_hours_enabled": False},
            "session": {"subscription_active": True},
        }
    finally:
        session.close()


@user_router.patch("/profile")
async def update_profile(body: UpdateProfileRequest, request: Request):
    user_id = _get_user_id_from_request(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Não autenticado")

    session = DatabaseManager.get_session()
    try:
        update_data = body.dict(exclude_unset=True)
        if not update_data:
            return {"message": "Nenhum campo para atualizar", "updated_fields": []}

        # Constrói a query de update dinamicamente
        set_clause = ", ".join([f"{k} = :{k}" for k in update_data.keys()])
        update_data["uid"] = user_id

        session.execute(
            text(
                f"UPDATE users SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE user_id = :uid"
            ),
            update_data,
        )
        session.commit()

        info(
            f"[USER] Perfil atualizado para user {user_id}: {list(update_data.keys())}"
        )
        return {
            "message": "Perfil atualizado com sucesso",
            "updated_fields": list(update_data.keys()),
        }
    except Exception as e:
        session.rollback()
        error(f"[USER] Erro ao atualizar perfil do user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao atualizar perfil")
    finally:
        session.close()


# ── Horário de funcionamento do estabelecimento ───────────────────────────────

_DEFAULT_HOURS = {
    "mon": {"enabled": False, "open": "08:00", "close": "22:00"},
    "tue": {"enabled": True,  "open": "08:00", "close": "22:00"},
    "wed": {"enabled": True,  "open": "08:00", "close": "22:00"},
    "thu": {"enabled": True,  "open": "08:00", "close": "22:00"},
    "fri": {"enabled": True,  "open": "08:00", "close": "22:00"},
    "sat": {"enabled": True,  "open": "08:00", "close": "22:00"},
    "sun": {"enabled": True,  "open": "08:00", "close": "22:00"},
}


class DayHours(BaseModel):
    enabled: bool = True
    open: str = "08:00"
    close: str = "22:00"
    split: bool = False
    open2: str | None = None
    close2: str | None = None


class OpeningHoursBody(BaseModel):
    mon: DayHours = DayHours(enabled=False)
    tue: DayHours = DayHours()
    wed: DayHours = DayHours()
    thu: DayHours = DayHours()
    fri: DayHours = DayHours()
    sat: DayHours = DayHours()
    sun: DayHours = DayHours()


@user_router.get("/business/opening-hours")
async def get_business_opening_hours(request: Request):
    user_id = _get_user_id_from_request(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Não autenticado")

    row = DatabaseManager.fetch_one(
        "SELECT c.opening_hours FROM users u JOIN clients c ON c.client_id = u.client_id WHERE u.user_id = :uid LIMIT 1",
        {"uid": user_id},
    )
    raw = row.get("opening_hours") if row else None
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    return _DEFAULT_HOURS


@user_router.put("/business/opening-hours")
async def set_business_opening_hours(body: OpeningHoursBody, request: Request):
    user_id = _get_user_id_from_request(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Não autenticado")

    session = DatabaseManager.get_session()
    try:
        user_row = session.execute(
            text("SELECT client_id FROM users WHERE user_id = :uid LIMIT 1"), {"uid": user_id}
        ).fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")

        client_id = dict(user_row._mapping)["client_id"]
        hours_json = json.dumps(body.dict())

        session.execute(
            text("UPDATE clients SET opening_hours = :oh, updated_at = CURRENT_TIMESTAMP WHERE client_id = :cid"),
            {"oh": hours_json, "cid": client_id},
        )
        session.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        error(f"[USER] Erro ao salvar horário client_id: {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar horário")
    finally:
        session.close()
