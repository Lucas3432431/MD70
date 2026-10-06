"""
Rotas de Sharing - FastAPI Routes
Geração de tokens de compartilhamento e estatísticas de referral.
"""

import random
import string
import uuid

from fastapi import APIRouter, Request, HTTPException

from App.Core.Logs import debug, info, error
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager

sharing_router = APIRouter(tags=["Sharing"], prefix="/api/sharing")


def _get_user_id(request: Request) -> str:
    from App.Core.Services.Auth.RequestAuth import get_payload_from_request

    return get_payload_from_request(request).get("user_id")


def _generate_short_code(length: int = 8) -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=length))


@sharing_router.post("/token")
async def get_or_create_sharing_token(request: Request):
    """
    Retorna ou cria o token de compartilhamento do usuário autenticado.
    Cada usuário tem exatamente 1 campanha shared_link permanente.
    """
    try:
        user_id = _get_user_id(request)
        db = DatabaseManager()

        existing = db.fetch_one(
            "SELECT short_code FROM campaigns WHERE owner_user_id = :uid AND channel = 'shared_link' AND is_active = 1",
            {"uid": user_id},
        )

        if existing:
            short_code = existing["short_code"]
        else:
            short_code = None
            for _ in range(10):
                candidate = _generate_short_code()
                collision = db.fetch_one(
                    "SELECT id FROM campaigns WHERE short_code = :code",
                    {"code": candidate},
                )
                if not collision:
                    short_code = candidate
                    break

            if not short_code:
                raise HTTPException(
                    status_code=500, detail="Não foi possível gerar código único"
                )

            campaign_id = str(uuid.uuid4())
            db.execute_query(
                """
                INSERT INTO campaigns (campaign_id, short_code, channel, name, owner_user_id, is_active)
                VALUES (:campaign_id, :short_code, 'shared_link', :name, :user_id, 1)
                """,
                {
                    "campaign_id": campaign_id,
                    "short_code": short_code,
                    "name": f"Convite de {user_id}",
                    "user_id": user_id,
                },
            )

            db.execute_query(
                "INSERT INTO sharing_logs (sharing_log_id, user_id) VALUES (:id, :uid)",
                {"id": str(uuid.uuid4()), "uid": user_id},
            )

            info(f"[SHARING] Novo token criado para user={user_id}: {short_code}")

        return {"short_code": short_code}

    except HTTPException:
        raise
    except Exception as e:
        error(f"[SHARING] Erro ao obter token: {e}")
        raise HTTPException(
            status_code=500, detail="Erro ao obter token de compartilhamento"
        )


@sharing_router.get("/stats")
async def get_sharing_stats(request: Request):
    """
    Retorna estatísticas de referral do usuário autenticado.
    """
    try:
        user_id = _get_user_id(request)
        db = DatabaseManager()

        # Buscar short_code do usuário
        campaign = db.fetch_one(
            "SELECT short_code FROM campaigns WHERE owner_user_id = :uid AND channel = 'shared_link' AND is_active = 1",
            {"uid": user_id},
        )
        short_code = campaign["short_code"] if campaign else None

        clicks = 0
        if short_code:
            clicks_result = db.fetch_one(
                """
                SELECT COUNT(*) as total FROM visitor_logs
                WHERE conversion_method_id = :code OR channel_id = :code
                """,
                {"code": short_code},
            )
            clicks = clicks_result.get("total", 0) if clicks_result else 0

        attributions = (
            db.fetch_all(
                """
            SELECT ra.status, ra.trial_credits_awarded_referrer,
                   ra.subscription_credits_awarded_referrer,
                   ra.registered_at, ra.trialed_at, ra.subscribed_at,
                   u.full_name
            FROM referral_attributions ra
            LEFT JOIN users u ON ra.referred_user_id = u.user_id
            WHERE ra.referrer_user_id = :uid
            ORDER BY ra.created_at DESC
            """,
                {"uid": user_id},
            )
            or []
        )

        total_referred = len(attributions)
        total_trialed = sum(
            1 for a in attributions if a.get("status") in ["trialed", "subscribed"]
        )
        total_subscribed = sum(
            1 for a in attributions if a.get("status") == "subscribed"
        )
        credits_earned = sum(
            (10 if a.get("trial_credits_awarded_referrer") else 0)
            + (100 if a.get("subscription_credits_awarded_referrer") else 0)
            for a in attributions
        )

        friends = [
            {
                "name": a.get("full_name") or "Amigo",
                "status": a.get("status", "registered"),
                "joined_at": str(a.get("registered_at") or ""),
            }
            for a in attributions
        ]

        return {
            "short_code": short_code,
            "clicks": clicks,
            "total_referred": total_referred,
            "total_trialed": total_trialed,
            "total_subscribed": total_subscribed,
            "credits_earned": credits_earned,
            "friends": friends,
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[SHARING] Erro ao obter stats: {e}")
        raise HTTPException(status_code=500, detail="Erro ao obter estatísticas")


@sharing_router.post("/invite")
async def create_invite_token(request: Request):
    """
    Cria um novo token de convite com UUID único.
    Cada token gera um link personalizado (?i=<short_code>) para rastreamento individual.
    """
    try:
        user_id = _get_user_id(request)
        body = (
            await request.json()
            if request.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        label = body.get("label") or None

        db = DatabaseManager()
        invite_id = str(uuid.uuid4())
        short_code = None
        for _ in range(10):
            candidate = _generate_short_code(8)
            collision = db.fetch_one(
                "SELECT id FROM invite_tokens WHERE short_code = :code",
                {"code": candidate},
            )
            if not collision:
                short_code = candidate
                break

        if not short_code:
            raise HTTPException(
                status_code=500, detail="Não foi possível gerar código único"
            )

        db.execute_query(
            """
            INSERT INTO invite_tokens (invite_id, short_code, referrer_user_id, label)
            VALUES (:invite_id, :short_code, :user_id, :label)
            """,
            {
                "invite_id": invite_id,
                "short_code": short_code,
                "user_id": user_id,
                "label": label,
            },
        )

        info(f"[INVITE] Novo token criado para user={user_id}: {short_code}")
        return {
            "invite_id": invite_id,
            "short_code": short_code,
            "label": label,
            "status": "pending",
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[INVITE] Erro ao criar token: {e}")
        raise HTTPException(status_code=500, detail="Erro ao criar token de convite")


@sharing_router.get("/invites")
async def list_invite_tokens(request: Request):
    """
    Lista todos os tokens de convite do usuário com seus status.
    """
    try:
        user_id = _get_user_id(request)
        db = DatabaseManager()

        invites = (
            db.fetch_all(
                """
            SELECT it.invite_id, it.short_code, it.label, it.status,
                   it.created_at, it.used_at,
                   u.full_name as referred_name
            FROM invite_tokens it
            LEFT JOIN referral_attributions ra ON it.attribution_id = ra.attribution_id
            LEFT JOIN users u ON ra.referred_user_id = u.user_id
            WHERE it.referrer_user_id = :uid
            ORDER BY it.created_at DESC
            """,
                {"uid": user_id},
            )
            or []
        )

        return {
            "invites": [
                {
                    "invite_id": inv["invite_id"],
                    "short_code": inv["short_code"],
                    "label": inv.get("label"),
                    "status": inv.get("status", "pending"),
                    "referred_name": inv.get("referred_name"),
                    "created_at": str(inv.get("created_at") or ""),
                    "used_at": str(inv.get("used_at") or "")
                    if inv.get("used_at")
                    else None,
                }
                for inv in invites
            ]
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[INVITE] Erro ao listar tokens: {e}")
        raise HTTPException(status_code=500, detail="Erro ao listar convites")


__all__ = ["sharing_router"]
