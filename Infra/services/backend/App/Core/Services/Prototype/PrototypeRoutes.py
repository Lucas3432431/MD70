"""
PrototypeRoutes — sessão anônima para /prototype
Cria um Client + User vinculado ao device_id (cookie) se ainda não existir,
e retorna os cookies de autenticação normais para que o frontend possa
usar todas as APIs protegidas sem login explícito.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from datetime import datetime

from App.Core.Logs import debug, info, warning, error
from App.Core.Settings.Settings import (
    COOKIE_SECURE,
    COOKIE_HTTPONLY,
    COOKIE_SAMESITE,
    ACCESS_TOKEN_EXPIRY,
    REFRESH_TOKEN_EXPIRY,
)
from App.Features.Auth import get_auth_service

prototype_router = APIRouter(prefix="/api/prototype", tags=["prototype"])

_PROTO_EMAIL_SUFFIX = "@proto.prox.internal"
_PROTO_PASSWORD = "prototype-session-no-login"
_PROTO_PLAN_TYPE = "free"
_PROTO_CREDITS = 5


class PrototypeSessionRequest(BaseModel):
    device_id: str


@prototype_router.post("/session")
async def prototype_session(body: PrototypeSessionRequest, request: Request):
    """
    Inicia ou retoma uma sessão de protótipo anônima.
    - Recebe o device_id gerado pelo frontend (cookie prototype_uid)
    - Cria Client + User se ainda não existir para esse device_id
    - Retorna cookies access_token / refresh_token idênticos ao fluxo normal
    """
    device_id = body.device_id.strip()
    if not device_id or len(device_id) > 64:
        return JSONResponse(status_code=400, content={"detail": "device_id inválido"})

    proto_email = f"proto_{device_id}{_PROTO_EMAIL_SUFFIX}"

    auth_service = get_auth_service()
    if not auth_service or not auth_service.db:
        return JSONResponse(status_code=503, content={"detail": "Serviço indisponível"})

    try:
        session = auth_service.db.get_session()

        # ── Buscar usuário existente ──────────────────────────────────────
        existing = session.execute(
            text(
                "SELECT user_id, client_id, email, full_name FROM users WHERE email = :email LIMIT 1"
            ),
            {"email": proto_email},
        ).fetchone()

        if existing:
            user_data = {
                "user_id": existing[0],
                "client_id": existing[1],
                "email": existing[2],
                "full_name": existing[3],
                "role": "member",
            }
            created = False
            debug(f"[Prototype] Sessão retomada: user_id={user_data['user_id']}")
        else:
            # ── Criar novo Client ─────────────────────────────────────────
            from App.Features.Credits.PlanManager import get_plan_manager

            plan_manager = get_plan_manager()
            plans_by_type = plan_manager.get_active_plans()
            free_plan = plans_by_type.get(_PROTO_PLAN_TYPE)
            if not free_plan:
                return JSONResponse(
                    status_code=503, content={"detail": "Plano free não disponível"}
                )

            result = session.execute(
                text("SELECT MAX(CAST(client_id AS INTEGER)) FROM clients")
            ).fetchone()
            next_client_id = str((result[0] or 0) + 1)

            auth_service.db.create_client(
                session,
                {
                    "client_id": next_client_id,
                    "plan_id": free_plan.get("plan_id"),
                    "started_at": datetime.utcnow(),
                    "finishes_at": None,
                    "users_available": 1,
                },
            )

            # ── Criar novo User ───────────────────────────────────────────
            import bcrypt

            result = session.execute(
                text("SELECT MAX(CAST(user_id AS INTEGER)) FROM users")
            ).fetchone()
            next_user_id = str((result[0] or 0) + 1)

            hashed_pw = bcrypt.hashpw(
                _PROTO_PASSWORD.encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8")

            user = auth_service.db.create_user(
                session,
                {
                    "user_id": next_user_id,
                    "client_id": next_client_id,
                    "email": proto_email,
                    "password": hashed_pw,
                    "full_name": "Visitante",
                    "ip_address": request.client.host if request.client else None,
                    "fingerprint_id": device_id,
                },
            )

            # ── Distribuir créditos iniciais ──────────────────────────────
            try:
                from App.Features.Credits.CreditsManager import CreditsManager

                ok = CreditsManager.distribute_plan_credits(
                    next_user_id, free_plan.get("plan_id")
                )
                if not ok:
                    raise RuntimeError("distribute_plan_credits retornou False")
            except Exception as ce:
                warning(f"[Prototype] Créditos via plan falhou, aplicando direto: {ce}")
                try:
                    session.execute(
                        text(
                            "UPDATE users SET credits = :c, last_reset = 'cumulative' WHERE user_id = :uid"
                        ),
                        {"c": _PROTO_CREDITS, "uid": next_user_id},
                    )
                    session.commit()
                except Exception as fe:
                    error(f"[Prototype] Falha total ao atribuir créditos: {fe}")

            user_data = {
                "user_id": user.user_id,
                "client_id": user.client_id,
                "email": user.email,
                "full_name": user.full_name,
                "role": "member",
            }
            created = True
            info(
                f"[Prototype] Novo usuário criado: user_id={next_user_id} device={device_id}"
            )

        # ── Gerar tokens ──────────────────────────────────────────────────
        access_token = auth_service.generate_access_token(user_data)
        refresh_token_data = auth_service.generate_refresh_token(user_data)

        response = JSONResponse(
            content={
                "user_id": user_data["user_id"],
                "created": created,
            }
        )

        cookie_params = {
            "httponly": COOKIE_HTTPONLY,
            "secure": COOKIE_SECURE,
            "samesite": COOKIE_SAMESITE,
        }
        response.set_cookie(
            key="access_token",
            value=access_token,
            max_age=ACCESS_TOKEN_EXPIRY,
            **cookie_params,
        )
        response.set_cookie(
            key="refresh_token",
            value=refresh_token_data["token"],
            max_age=REFRESH_TOKEN_EXPIRY,
            **cookie_params,
        )

        return response

    except Exception as e:
        error(f"[Prototype] Erro ao criar sessão: {e}")
        return JSONResponse(status_code=500, content={"detail": "Erro interno"})
