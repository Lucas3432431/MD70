"""
Rotas de administração — /api/admin

Autenticação via TOTP (RFC 6238, 6 dígitos, janela 30s).
Não usa sessão/cookie — o token TOTP é a única credencial.
"""

import pyotp
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from App.Core.Logs import info, warning
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Features.Credits.CreditsManager import CreditsManager

admin_router = APIRouter(tags=["Admin"], prefix="/api/admin")

_TOTP_SECRET: str = ""


def _get_totp_secret() -> str:
    global _TOTP_SECRET
    if not _TOTP_SECRET:
        from App.Core.Settings.Settings import GLOBAL_CONFIG

        _TOTP_SECRET = GLOBAL_CONFIG.get("admin_totp_secret", "")
    return _TOTP_SECRET


def _verify_totp(token: str) -> bool:
    secret = _get_totp_secret()
    if not secret:
        return False
    try:
        totp = pyotp.TOTP(secret)
        # valid_window=1 aceita ±30s de drift de relógio
        return totp.verify(token, valid_window=1)
    except Exception:
        return False


class AddCreditsRequest(BaseModel):
    user_id: str = Field(..., description="ID do usuário que receberá os créditos")
    amount: float = Field(..., gt=0, description="Quantidade de créditos a adicionar")


@admin_router.post("/add_credits")
async def admin_add_credits(request: Request, body: AddCreditsRequest):
    totp = request.headers.get("x-admin-token", "")
    if not _verify_totp(totp):
        warning(
            f"[ADMIN] Tentativa de add_credits com TOTP inválido — user_id={body.user_id}"
        )
        raise HTTPException(status_code=401, detail="Token inválido ou expirado.")

    user = DatabaseManager.fetch_one(
        "SELECT user_id, credits FROM users WHERE user_id = :uid LIMIT 1",
        {"uid": body.user_id},
    )
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    balance_before = float(user.get("credits") or 0)

    ok = CreditsManager.add_credits(
        user_id=body.user_id,
        amount=body.amount,
        reason="[ADMIN] add_credits manual",
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Erro ao adicionar créditos.")

    new_row = DatabaseManager.fetch_one(
        "SELECT credits FROM users WHERE user_id = :uid LIMIT 1",
        {"uid": body.user_id},
    )
    balance_after = float((new_row or {}).get("credits") or 0)

    info(
        f"[ADMIN] add_credits — user_id={body.user_id} "
        f"amount={body.amount:.6f} balance={balance_before:.6f}→{balance_after:.6f}"
    )

    return {
        "success": True,
        "user_id": body.user_id,
        "amount_added": body.amount,
        "balance_before": balance_before,
        "balance_after": balance_after,
    }
