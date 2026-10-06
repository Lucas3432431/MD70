"""
LandingPage Routes — captura de e-mails da LP e disparo de notificações.
"""

import asyncio
from pathlib import Path

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from App.Core.Logs import error, info
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Services.AdminEmail import admin_email_service
from App.Core.Services.AdminEmail.AdminEmailService import LUCAS_FROM, NOREPLY_FROM
from App.Core.Services.TelegramAlert import telegram_alert_service
from sqlalchemy import text

# ============================================================
lp_router = APIRouter(tags=["LandingPage"], prefix="/api/lp")
# ============================================================

_HTML_DIR = Path(__file__).resolve().parents[4] / "HTMLs"


def _load_html(filename: str) -> str:
    path = _HTML_DIR / filename
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        error(f"[LP] Erro ao carregar template {filename}: {e}")
        return ""


class LPSignupRequest(BaseModel):
    email: str


class LPPreferencesRequest(BaseModel):
    email: str
    wants_book_list: bool = False
    wants_video_list: bool = False
    wants_article_list: bool = False


# ── helpers ─────────────────────────────────────────────────


def _save_email(email: str) -> bool:
    try:
        DatabaseManager.execute_transaction(
            lambda session: session.execute(
                text(
                    "INSERT INTO waitlist (email, status) "
                    "VALUES (:email, 'pending') "
                    "ON CONFLICT(email) DO NOTHING"
                ),
                {"email": email},
            )
        )
        return True
    except Exception as e:
        error(f"[LP] Erro ao salvar e-mail {email}: {e}")
        return False


def _notify_admin(email: str) -> None:
    subject = "🎯 Novo cadastro na LP"
    body = f"Novo e-mail capturado na landing page:\n\n{email}"
    telegram_alert_service.send_critical_alert(subject, body)
    admin_email_service.send_critical_alert(subject, body)


def _welcome_email_immediate(email: str) -> None:
    html = _load_html("email_confirmacao.html")
    if not html:
        return
    admin_email_service.send_email(
        to=email,
        subject="Cadastro confirmado — o próximo passo é nosso · MD70",
        html_body=html,
        from_email=NOREPLY_FROM,
    )


def _welcome_email_followup(email: str) -> None:
    html = _load_html("email_lucas_sdr.html")
    if not html:
        return
    admin_email_service.send_email(
        to=email,
        subject="15 minutos esta semana? (Lucas · MD70)",
        html_body=html,
        from_email=LUCAS_FROM,
    )


async def _process_signup(email: str) -> None:
    saved = _save_email(email)
    if saved:
        info(f"[LP] Novo cadastro: {email}")
    _notify_admin(email)
    _welcome_email_immediate(email)
    await asyncio.sleep(120)
    _welcome_email_followup(email)


# ── routes ──────────────────────────────────────────────────


@lp_router.post("/signup")
async def lp_signup(body: LPSignupRequest, background_tasks: BackgroundTasks):
    """Captura e-mail da landing page, salva no waitlist e dispara notificações."""
    background_tasks.add_task(_process_signup, body.email.strip().lower())
    return {"success": True}


@lp_router.post("/preferences")
async def lp_preferences(body: LPPreferencesRequest):
    """Salva preferências de conteúdo do inscrito (lista de livros, vídeos)."""
    try:
        DatabaseManager.execute_transaction(
            lambda session: session.execute(
                text(
                    "UPDATE waitlist SET wants_book_list = :book, wants_video_list = :video, "
                    "wants_article_list = :article WHERE email = :email"
                ),
                {
                    "email": body.email.strip().lower(),
                    "book": int(body.wants_book_list),
                    "video": int(body.wants_video_list),
                    "article": int(body.wants_article_list),
                },
            )
        )
        info(f"[LP] Preferências salvas para {body.email}")
        return {"success": True}
    except Exception as e:
        error(f"[LP] Erro ao salvar preferências: {e}")
        return {"success": False}


@lp_router.get("/ebook/diagnostico-funil")
async def ebook_diagnostico_funil(
    background_tasks: BackgroundTasks,
    email: str = Query(default=""),
):
    """Serve o e-book 'Diagnóstico de Funil: O Guia Prático' para download."""
    if email:
        background_tasks.add_task(_track_ebook_download, email.strip().lower())
    path = _HTML_DIR / "ebook_diagnostico_funil.pdf"
    return FileResponse(
        path=path,
        media_type="application/pdf",
        filename="Diagnostico-de-Funil-MD70.pdf",
        headers={
            "Content-Disposition": "attachment; filename=Diagnostico-de-Funil-MD70.pdf"
        },
    )


def _track_ebook_download(email: str) -> None:
    try:
        DatabaseManager.execute_transaction(
            lambda session: session.execute(
                text(
                    "UPDATE waitlist SET ebook_downloaded = 1, ebook_downloaded_at = :ts "
                    "WHERE email = :email"
                ),
                {"email": email, "ts": datetime.now(timezone.utc).isoformat()},
            )
        )
        info(f"[LP] Ebook baixado por {email}")
    except Exception as e:
        error(f"[LP] Erro ao registrar download do ebook para {email}: {e}")
