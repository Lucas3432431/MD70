"""
Rotas de Autenticação - FastAPI Routes
"""

import asyncio
from typing import Optional, Dict, Any
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import re
import time
import redis as _redis

from App.Core.Logs import debug, info, warning, error
from App.Core.Services.TelegramAlert.TelegramAlertService import telegram_alert_service
from App.Core.Settings.Settings import (
    GLOBAL_CONFIG,
    ENVIRONMENT,
    COOKIE_SECURE,
    COOKIE_HTTPONLY,
    COOKIE_SAMESITE,
    ACCESS_TOKEN_EXPIRY,
    REFRESH_TOKEN_EXPIRY,
)
from App.Features.Auth import get_auth_service, AuthConfig

_LOCKOUT_MAX_FAILURES = 5
_LOCKOUT_TTL = 15 * 60  # 15 minutos

_redis_client: "_redis.Redis | None" = None


def _get_redis() -> "_redis.Redis | None":
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        url = GLOBAL_CONFIG.get("redis_url", "")
        if url:
            _redis_client = _redis.Redis.from_url(
                url, decode_responses=True, socket_connect_timeout=2
            )
        else:
            host = GLOBAL_CONFIG.get("redis_host", "localhost")
            port = int(GLOBAL_CONFIG.get("redis_port", 6379))
            password = GLOBAL_CONFIG.get("redis_password") or None
            _redis_client = _redis.Redis(
                host=host,
                port=port,
                password=password,
                decode_responses=True,
                socket_connect_timeout=2,
            )
        _redis_client.ping()
    except Exception as e:
        warning(f"[LOCKOUT] Redis indisponível, lockout desativado: {e}")
        _redis_client = None
    return _redis_client


def _lockout_check(email: str) -> int:
    """Retorna 0 se OK, ou os segundos restantes de bloqueio."""
    r = _get_redis()
    if not r:
        return 0
    try:
        ttl = r.ttl(f"auth:lock:{email}")
        return ttl if ttl > 0 else 0
    except Exception:
        return 0


def _lockout_failure(email: str) -> int:
    """Registra falha. Retorna número de tentativas acumuladas."""
    r = _get_redis()
    if not r:
        return 0
    try:
        pipe = r.pipeline()
        pipe.incr(f"auth:fail:{email}")
        pipe.expire(f"auth:fail:{email}", _LOCKOUT_TTL)
        results = pipe.execute()
        attempts = results[0]
        if attempts >= _LOCKOUT_MAX_FAILURES:
            r.set(f"auth:lock:{email}", 1, ex=_LOCKOUT_TTL)
            warning(
                f"[LOCKOUT] Conta bloqueada por {_LOCKOUT_TTL}s: {email} ({attempts} falhas)"
            )
            try:
                telegram_alert_service.send_critical_alert(
                    subject="Conta bloqueada por brute force",
                    message=(
                        f"<b>Email:</b> {email}\n"
                        f"<b>Tentativas:</b> {attempts}\n"
                        f"<b>Bloqueio:</b> {_LOCKOUT_TTL // 60} minutos"
                    ),
                )
            except Exception:
                pass
        return attempts
    except Exception:
        return 0


def _lockout_clear(email: str) -> None:
    r = _get_redis()
    if not r:
        return
    try:
        r.delete(f"auth:fail:{email}", f"auth:lock:{email}")
    except Exception:
        pass


# --- Models ---
class LoginRequest(BaseModel):
    email: str
    password: str
    fingerprint_id: str
    fingerprint_components: Dict[str, Any]
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class SignUpRequest(BaseModel):
    email: str
    password: str
    fingerprint_id: str
    fingerprint_components: Dict[str, Any]
    ip_address: Optional[str] = None


class ValidateEmailRequest(BaseModel):
    value: str


class TwoFactorLoginRequest(BaseModel):
    pending_token: str
    code: str


class TwoFactorEnableRequest(BaseModel):
    secret: str
    code: str


class TwoFactorDisableRequest(BaseModel):
    code: str


# --- Routers ---
auth_router = APIRouter(tags=["Authentication"], prefix="/api/auth")
validation_auth_router = APIRouter(tags=["Validation"], prefix="/api")


@auth_router.get("/health")
async def auth_health():
    return {"status": "ok", "message": "Auth router funcionando"}


@auth_router.post("/check")
async def auth_check(request: Request):
    # Middleware já resolveu e cacheou o token em scope — usar diretamente (zero DB)
    payload = request.scope.get("_auth_payload")
    if not payload:
        # Fallback: sem cookie ou token inválido
        if not request.cookies.get("access_token"):
            return {"authenticated": False, "user": None, "needs_agreement": True}
        return {"authenticated": False, "user": None, "needs_agreement": True}

    return {
        "authenticated": True,
        "user": {
            "user_id": payload.get("user_id"),
            "email": payload.get("email"),
            "full_name": payload.get("full_name"),
        },
    }


@auth_router.post("/login")
async def login(login_data: LoginRequest, request: Request):
    # Verifica lockout antes de qualquer operação
    remaining = _lockout_check(login_data.email)
    if remaining > 0:
        raise HTTPException(
            status_code=429,
            detail="Conta temporariamente bloqueada por excesso de tentativas",
            headers={"Retry-After": str(remaining)},
        )

    auth_service = get_auth_service()
    success, user_data, error_msg = auth_service.authenticate_user(
        email=login_data.email,
        password=login_data.password,
        fingerprint_id=login_data.fingerprint_id,
        fingerprint_components=login_data.fingerprint_components,
    )

    if not success:
        time.sleep(0.3)  # Anti-brute force delay
        attempts = _lockout_failure(login_data.email)
        warning(
            f"[AUDIT] Falha de login para o email: {login_data.email} | IP: {request.client.host} | tentativas: {attempts}"
        )
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    _lockout_clear(login_data.email)

    # Verificar se 2FA está habilitado
    from App.Core.Services.Auth.TwoFactorService import get_2fa_service

    tfa = get_2fa_service()
    if tfa.get_status(user_data["user_id"]):
        pending_token = auth_service.generate_pending_2fa_token(user_data["user_id"])
        info(
            f"[AUDIT] Login com 2FA requerido: {user_data['email']} | IP: {request.client.host}"
        )
        return JSONResponse(
            content={"requires_2fa": True, "pending_token": pending_token},
            status_code=200,
        )

    info(
        f"[AUDIT] Login realizado com sucesso: {user_data['email']} (ID: {user_data['user_id']}) | IP: {request.client.host}"
    )
    access_token = auth_service.generate_access_token(user_data)
    refresh_token_data = auth_service.generate_refresh_token(user_data)

    response = JSONResponse(
        content={"message": "Login ok", "user": user_data, "requires_2fa": False}
    )

    # Flags serão injetados globalmente pelo ZeraSecurityMiddleware,
    # mas definimos aqui por redundância
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


async def _signup_welcome_flow(email: str) -> None:
    import os
    from App.Core.Services.AdminEmail import admin_email_service
    from App.Core.Services.AdminEmail.AdminEmailService import LUCAS_FROM, NOREPLY_FROM

    _html_dir = os.path.join(os.path.dirname(__file__), "../../../../HTMLs")
    with open(os.path.join(_html_dir, "email_boas_vindas_user.html"), encoding="utf-8") as _f:
        immediate_html = _f.read()

    admin_email_service.send_email(
        to=email,
        subject="Bem-vindo ao MD70! Sua conta está pronta",
        html_body=immediate_html,
        from_email=NOREPLY_FROM,
    )

    await asyncio.sleep(120)

    followup_html = f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="UTF-8" /></head>
<body style="margin:0;padding:0;background:#ffffff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;">
    <tr>
      <td align="center" style="padding:40px 16px;">
        <table width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;">
          <tr>
            <td style="padding-bottom:32px;">
              <span style="font-size:17px;font-weight:700;color:#0f0f0f;letter-spacing:-0.02em;">◐ MD70</span>
            </td>
          </tr>
          <tr>
            <td style="font-size:15px;line-height:1.65;color:#333333;">
              <p style="margin:0 0 16px;">Tudo bem?</p>
              <p style="margin:0 0 16px;">
                Aqui é o Lucas, do time de Sucesso do Cliente do MD70.
                Vi que você acabou de criar a sua conta e queria entender melhor o que está buscando.
              </p>
              <p style="margin:0 0 16px;">
                Dependendo do momento em que o seu negócio está — seja na organização do atendimento,
                na gestão de leads ou na integração dos canais de comunicação — existem caminhos
                bem diferentes que podem fazer sentido. Antes de qualquer coisa, gostaria de entender
                melhor o seu cenário para, aí sim, ajudar você a tirar o máximo da plataforma.
              </p>
              <p style="margin:0 0 16px;">
                Se quiser, pode responder esse e-mail me contando um pouco mais sobre o que está
                avaliando. Não tem compromisso — estou aqui para ajudar a pensar, não para vender.
              </p>
              <p style="margin:0 0 32px;">
                Fico à disposição.
              </p>
              <p style="margin:0;">
                Abraço,<br/>
                <strong>Lucas</strong><br/>
                <span style="color:#666666;">Head de Sucesso do Cliente · MD70</span>
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:40px 0 24px;">
              <hr style="border:none;border-top:1px solid #e8e8e8;margin:0;" />
            </td>
          </tr>
          <tr>
            <td style="font-size:11px;color:#999999;line-height:1.6;">
              Você recebeu esse e-mail porque criou uma conta em prox.app.<br/>
              MD70 Technologies · São Paulo, SP
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
    admin_email_service.send_email(
        to=email,
        subject="Sou o Lucas, do time de Sucesso do Cliente · MD70",
        html_body=followup_html,
        from_email=LUCAS_FROM,
    )


@auth_router.post("/signup")
async def signup(
    signup_data: SignUpRequest, request: Request, background_tasks: BackgroundTasks
):
    auth_service = get_auth_service()
    success, user_data, error_msg = auth_service.register_user(
        email=signup_data.email,
        password=signup_data.password,
        fingerprint_id=signup_data.fingerprint_id,
        fingerprint_components=signup_data.fingerprint_components,
        ip_address=request.client.host,
    )

    if not success:
        if error_msg == "email_exists":
            raise HTTPException(status_code=409, detail="Email já cadastrado")
        if error_msg == "max_users_reached":
            raise HTTPException(status_code=429, detail="max_users_reached")
        raise HTTPException(status_code=400, detail=error_msg or "Erro ao criar conta")

    info(
        f"[AUDIT] Signup realizado com sucesso: {user_data['email']} (ID: {user_data['user_id']}) | IP: {request.client.host}"
    )

    background_tasks.add_task(_signup_welcome_flow, user_data["email"])

    access_token = auth_service.generate_access_token(user_data)
    refresh_token_data = auth_service.generate_refresh_token(user_data)

    response = JSONResponse(
        content={"message": "Conta criada com sucesso", "user": user_data}
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


@auth_router.get("/callback")
async def google_callback(
    request: Request,
    code: str,
    state: Optional[str] = None,
    redirect_uri: Optional[str] = None,
    action: Optional[str] = "login",
):
    auth_service = get_auth_service()
    preferred_redirect_uri = (
        redirect_uri if redirect_uri and redirect_uri != "" else "postmessage"
    )
    success, user_data, error_msg = auth_service.handle_google_auth(
        auth_code=code, preferred_redirect_uri=preferred_redirect_uri
    )

    if not success:
        if error_msg and "limite" in error_msg.lower():
            raise HTTPException(status_code=429, detail="max_users_reached")
        raise HTTPException(
            status_code=401, detail=error_msg or "Falha na autenticação Google"
        )

    info(
        f"[AUDIT] Google OAuth bem-sucedido: {user_data['email']} (ID: {user_data['user_id']}) | IP: {request.client.host}"
    )
    access_token = auth_service.generate_access_token(user_data)
    refresh_token_data = auth_service.generate_refresh_token(user_data)

    response = JSONResponse(content={"message": "Login Google ok", "user": user_data})
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


@auth_router.post("/refresh")
async def refresh_token_endpoint(request: Request):
    """
    Rotaciona tokens: invalida access+refresh antigos e emite novos.
    Requer cookie refresh_token válido.
    """
    from sqlalchemy import text as _text
    from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager

    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="Refresh token ausente")

    auth_service = get_auth_service()
    payload = auth_service.verify_token(token, token_type="refresh")
    if not payload:
        raise HTTPException(
            status_code=401, detail="Refresh token inválido ou expirado"
        )

    user_id = str(payload.get("user_id"))
    old_refresh_token_id = payload.get("token_id")

    session = DatabaseManager.get_session()
    try:
        row = session.execute(
            _text(
                "SELECT user_id, email, full_name, client_id, type "
                "FROM users WHERE user_id = :uid LIMIT 1"
            ),
            {"uid": user_id},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Usuário não encontrado")
        user_data = dict(row._mapping)
        user_data["role"] = user_data.pop("type", "member") or "member"

        # Invalida refresh token antigo
        DatabaseManager.revoke_refresh_token(session, old_refresh_token_id)

        # Invalida todos os access tokens ativos do usuário
        session.execute(
            _text(
                "UPDATE access_tokens SET revoked_at = CURRENT_TIMESTAMP "
                "WHERE user_id = :uid AND revoked_at IS NULL"
            ),
            {"uid": user_id},
        )
        session.commit()
    finally:
        session.close()

    new_access_token = auth_service.generate_access_token(user_data)
    new_refresh_data = auth_service.generate_refresh_token(user_data)

    info(f"[AUDIT] Tokens rotacionados para user {user_id}")

    response = JSONResponse(content={"message": "Tokens renovados"})
    cookie_params = {
        "httponly": COOKIE_HTTPONLY,
        "secure": COOKIE_SECURE,
        "samesite": COOKIE_SAMESITE,
    }
    response.set_cookie(
        key="access_token",
        value=new_access_token,
        max_age=ACCESS_TOKEN_EXPIRY,
        **cookie_params,
    )
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_data["token"],
        max_age=REFRESH_TOKEN_EXPIRY,
        **cookie_params,
    )
    return response


@auth_router.post("/logout")
async def logout():
    response = JSONResponse(content={"message": "Logout ok"})
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return response


def _get_user_id_from_request(request: Request) -> Optional[str]:
    """Extrai user_id — usa o helper global que lê do scope do middleware."""
    try:
        from App.Core.Services.Auth.RequestAuth import get_user_id_from_request

        return get_user_id_from_request(request)
    except Exception:
        return None


@auth_router.post("/2fa/login")
async def two_factor_login(body: TwoFactorLoginRequest, request: Request):
    """Segunda etapa do login quando 2FA está ativo."""
    auth_service = get_auth_service()
    user_id = auth_service.verify_pending_2fa_token(body.pending_token)
    if not user_id:
        time.sleep(0.3)
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")

    from App.Core.Services.Auth.TwoFactorService import get_2fa_service

    tfa = get_2fa_service()
    plain_secret = tfa.get_secret_for_login(user_id)
    if not plain_secret or not tfa.verify_code(body.code, plain_secret):
        time.sleep(0.3)
        raise HTTPException(status_code=400, detail="Código 2FA inválido")

    from sqlalchemy import text as _text
    from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager

    session = DatabaseManager.get_session()
    try:
        row = session.execute(
            _text(
                "SELECT user_id, email, full_name, client_id, type FROM users WHERE user_id = :uid LIMIT 1"
            ),
            {"uid": user_id},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Usuário não encontrado")
        user_data = dict(row._mapping)
        user_data["role"] = user_data.pop("type", "member") or "member"
    finally:
        session.close()

    access_token = auth_service.generate_access_token(user_data)
    refresh_token_data = auth_service.generate_refresh_token(user_data)

    info(
        f"[AUDIT] Login 2FA concluído: {user_data['email']} | IP: {request.client.host}"
    )
    response = JSONResponse(content={"message": "Login ok", "user": user_data})
    cookie_params = {
        "httponly": COOKIE_HTTPONLY,
        "secure": COOKIE_SECURE,
        "samesite": COOKIE_SAMESITE,
    }
    response.set_cookie(
        "access_token", access_token, max_age=ACCESS_TOKEN_EXPIRY, **cookie_params
    )
    response.set_cookie(
        "refresh_token",
        refresh_token_data["token"],
        max_age=REFRESH_TOKEN_EXPIRY,
        **cookie_params,
    )
    return response


@auth_router.get("/2fa/status")
async def two_factor_status(request: Request):
    """Retorna se 2FA está habilitado para o usuário autenticado."""
    user_id = _get_user_id_from_request(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Não autenticado")
    from App.Core.Services.Auth.TwoFactorService import get_2fa_service

    return {"enabled": get_2fa_service().get_status(user_id)}


@auth_router.post("/2fa/setup")
async def two_factor_setup(request: Request):
    """Gera QR code e secret para configuração do 2FA. Não habilita ainda."""
    user_id = _get_user_id_from_request(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Não autenticado")

    from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
    from sqlalchemy import text as _text

    session = DatabaseManager.get_session()
    try:
        row = session.execute(
            _text("SELECT email FROM users WHERE user_id = :uid LIMIT 1"),
            {"uid": user_id},
        ).fetchone()
        email = row[0] if row else user_id
    finally:
        session.close()

    from App.Core.Services.Auth.TwoFactorService import get_2fa_service

    return get_2fa_service().generate_setup(user_id, email)


@auth_router.post("/2fa/enable")
async def two_factor_enable(body: TwoFactorEnableRequest, request: Request):
    """Habilita 2FA após verificar o código gerado pelo autenticador."""
    user_id = _get_user_id_from_request(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Não autenticado")

    from App.Core.Services.Auth.TwoFactorService import get_2fa_service

    ok, msg = get_2fa_service().enable(user_id, body.secret, body.code)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


@auth_router.post("/2fa/disable")
async def two_factor_disable(body: TwoFactorDisableRequest, request: Request):
    """Desabilita 2FA após confirmar com o código atual."""
    user_id = _get_user_id_from_request(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Não autenticado")

    from App.Core.Services.Auth.TwoFactorService import get_2fa_service

    ok, msg = get_2fa_service().disable(user_id, body.code)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[\d\s\-().]{7,20}$")


@validation_auth_router.post("/validate-email")
async def validate_email(body: ValidateEmailRequest):
    email = body.value.strip()
    is_valid = bool(_EMAIL_RE.match(email))
    user_exists = 0
    if is_valid:
        try:
            from App.Core.Crunch import get_db_manager
            from sqlalchemy import text as _text

            db = get_db_manager()
            session = db.get_session()
            try:
                row = session.execute(
                    _text("SELECT 1 FROM users WHERE email = :email LIMIT 1"),
                    {"email": email},
                ).fetchone()
                user_exists = 1 if row else 0
            finally:
                session.close()
        except Exception as _e:
            from App.Core.Logs.Logs import error as _log_error

            _log_error(f"[VALIDATE_EMAIL] Erro ao verificar user_exists: {_e}")
    return {"is_valid": is_valid, "user_exists": user_exists}


@validation_auth_router.post("/validate-cellphone")
async def validate_cellphone(body: ValidateEmailRequest):
    is_valid = bool(_PHONE_RE.match(body.value.strip()))
    return {"is_valid": is_valid}


# ============================================================================
# RECUPERAÇÃO DE SENHA
# ============================================================================

_RECOVERY_CODE_TTL = 15 * 60  # 15 min
_RECOVERY_SESSION_TTL = 10 * 60  # 10 min após código confirmado


class ConfirmEmailRequest(BaseModel):
    email: str


class SendRecoveryCodeRequest(BaseModel):
    email: str


class ConfirmRecoveryCodeRequest(BaseModel):
    email: str
    code: str


class RedefinePasswordRequest(BaseModel):
    session_token: str
    new_password: str


def _recovery_code_html(code: str, full_name: str) -> str:
    import pathlib

    template_path = (
        pathlib.Path(__file__).parent.parent.parent.parent.parent
        / "HTMLs"
        / "email_recuperacao_senha.html"
    )
    html = template_path.read_text(encoding="utf-8")
    return html.replace("{{code}}", code).replace("{{full_name}}", full_name)


@auth_router.post("/confirm_email")
async def confirm_email(body: ConfirmEmailRequest):
    """Verifica se o email está cadastrado."""
    email = body.email.strip().lower()
    try:
        from App.Core.Crunch import get_db_manager
        from sqlalchemy import text as _text

        db = get_db_manager()
        session = db.get_session()
        try:
            row = session.execute(
                _text(
                    "SELECT user_id, full_name FROM users WHERE email = :email LIMIT 1"
                ),
                {"email": email},
            ).fetchone()
        finally:
            session.close()
    except Exception as e:
        error(f"[RECOVERY] confirm_email erro: {e}")
        raise HTTPException(status_code=500, detail="Erro interno.")

    if not row:
        raise HTTPException(status_code=404, detail="Email não encontrado.")

    return {"ok": True, "email": email}


@auth_router.post("/send_recovery_code")
async def send_recovery_code(body: SendRecoveryCodeRequest):
    """Gera e envia código de 6 dígitos por email."""
    import random

    email = body.email.strip().lower()

    try:
        from App.Core.Crunch import get_db_manager
        from sqlalchemy import text as _text

        db = get_db_manager()
        session = db.get_session()
        try:
            row = session.execute(
                _text(
                    "SELECT user_id, full_name FROM users WHERE email = :email LIMIT 1"
                ),
                {"email": email},
            ).fetchone()
        finally:
            session.close()
    except Exception as e:
        error(f"[RECOVERY] send_recovery_code erro db: {e}")
        raise HTTPException(status_code=500, detail="Erro interno.")

    if not row:
        raise HTTPException(status_code=404, detail="Email não encontrado.")

    full_name = row[1] or "usuário"

    r = _get_redis()
    if not r:
        raise HTTPException(status_code=503, detail="Serviço indisponível.")

    # Reutiliza código existente se ainda válido — evita spam e inconsistência
    try:
        existing = r.get(f"auth:recovery_code:{email}")
        code = (
            (existing if isinstance(existing, str) else existing.decode())
            if existing
            else f"{random.randint(0, 999999):06d}"
        )
        if not existing:
            r.set(f"auth:recovery_code:{email}", code, ex=_RECOVERY_CODE_TTL)
    except Exception as e:
        error(f"[RECOVERY] Redis erro: {e}")
        raise HTTPException(status_code=500, detail="Erro ao gerar código.")

    try:
        from App.Core.Services.AdminEmail import admin_email_service
        from App.Core.Services.AdminEmail.AdminEmailService import NOREPLY_FROM

        admin_email_service.send_email(
            to=email,
            subject="Seu código de recuperação de senha — MD70",
            html_body=_recovery_code_html(code, full_name),
            from_email=NOREPLY_FROM,
        )
    except Exception as e:
        error(f"[RECOVERY] Erro ao enviar email: {e}")
        raise HTTPException(status_code=500, detail="Erro ao enviar email.")

    info(f"[RECOVERY] Código enviado para {email}")
    return {"ok": True}


@auth_router.post("/confirm_recovery_code")
async def confirm_recovery_code(body: ConfirmRecoveryCodeRequest):
    """Valida o código e retorna session_token temporário."""
    import secrets as _secrets

    email = body.email.strip().lower()
    code = body.code.strip()

    r = _get_redis()
    if not r:
        raise HTTPException(status_code=503, detail="Serviço indisponível.")

    try:
        stored = r.get(f"auth:recovery_code:{email}")
    except Exception as e:
        error(f"[RECOVERY] Redis get erro: {e}")
        raise HTTPException(status_code=500, detail="Erro interno.")

    stored_str = stored if isinstance(stored, str) else stored.decode()
    if not stored or stored_str != code:
        warning(f"[RECOVERY] Código inválido para {email}")
        raise HTTPException(status_code=401, detail="Código inválido ou expirado.")

    try:
        from App.Core.Crunch import get_db_manager
        from sqlalchemy import text as _text

        db = get_db_manager()
        session = db.get_session()
        try:
            row = session.execute(
                _text("SELECT user_id FROM users WHERE email = :email LIMIT 1"),
                {"email": email},
            ).fetchone()
        finally:
            session.close()
    except Exception as e:
        error(f"[RECOVERY] Erro ao buscar user: {e}")
        raise HTTPException(status_code=500, detail="Erro interno.")

    if not row:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    session_token = _secrets.token_urlsafe(32)
    try:
        r.set(
            f"auth:recovery_session:{session_token}", row[0], ex=_RECOVERY_SESSION_TTL
        )
        r.delete(f"auth:recovery_code:{email}")
    except Exception as e:
        error(f"[RECOVERY] Redis session erro: {e}")
        raise HTTPException(status_code=500, detail="Erro interno.")

    info(f"[RECOVERY] Código confirmado para {email}")
    return {"ok": True, "session_token": session_token}


_PASSWORD_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[\W_]).{8,}$")


@auth_router.post("/redefine_password")
async def redefine_password(body: RedefinePasswordRequest):
    """Redefine a senha usando o session_token do código confirmado."""
    if not _PASSWORD_RE.match(body.new_password):
        raise HTTPException(
            status_code=400,
            detail="A senha deve ter no mínimo 8 caracteres, letra maiúscula, minúscula, número e símbolo.",
        )

    r = _get_redis()
    if not r:
        raise HTTPException(status_code=503, detail="Serviço indisponível.")

    try:
        user_id_bytes = r.get(f"auth:recovery_session:{body.session_token}")
    except Exception as e:
        error(f"[RECOVERY] Redis get session erro: {e}")
        raise HTTPException(status_code=500, detail="Erro interno.")

    if not user_id_bytes:
        raise HTTPException(
            status_code=401, detail="Sessão expirada. Solicite um novo código."
        )

    user_id = (
        user_id_bytes if isinstance(user_id_bytes, str) else user_id_bytes.decode()
    )

    auth_service = get_auth_service()
    new_hash = auth_service.hash_password(body.new_password)

    try:
        from App.Core.Crunch import get_db_manager
        from sqlalchemy import text as _text

        db = get_db_manager()
        session = db.get_session()
        try:
            session.execute(
                _text(
                    "UPDATE users SET password = :pw, updated_at = CURRENT_TIMESTAMP WHERE user_id = :uid"
                ),
                {"pw": new_hash, "uid": user_id},
            )
            session.commit()
        finally:
            session.close()
    except Exception as e:
        error(f"[RECOVERY] Erro ao atualizar senha: {e}")
        raise HTTPException(status_code=500, detail="Erro ao atualizar senha.")

    try:
        r.delete(f"auth:recovery_session:{body.session_token}")
    except Exception:
        pass

    info(f"[RECOVERY] Senha redefinida para user_id={user_id}")
    return {"ok": True}


__all__ = ["auth_router", "validation_auth_router"]
