from fastapi import APIRouter, Request, FastAPI
from fastapi.responses import JSONResponse, FileResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
import uuid
import json
import os
import logging
import hmac
import hashlib
import secrets
import time
import traceback

# Importar constantes de Cookies e Configurações
from App.Core.Settings.Settings import (
    GLOBAL_CONFIG,
    MAX_USERS,
    SECRET_KEY,
    ENVIRONMENT,
    VITE_HTTP_PROTOCOL,
    FRONTEND_HOST,
    FRONTEND_PORT,
    NGINX_PORT,
    COOKIE_SECURE,
    COOKIE_HTTPONLY,
    COOKIE_SAMESITE,
)

# Importar o app e componentes do setup centralizado
from .Common.AppSetup import app, setup_app, startup_event, COMPONENTS

logger = logging.getLogger("uvicorn.error")

# ========================================================================
# CSRF — CONSTANTES E HELPERS
# ========================================================================

_CSRF_COOKIE = "csrf_token"
_CSRF_HEADER = "X-CSRF-Token"
_CSRF_MAX_AGE = 86400  # 24h

# Rotas isentas de validação CSRF
_CSRF_EXEMPT_PREFIXES = [
    "/api/auth/",
    "/webhook/",
    "/api/health",
    "/api/share/",
    "/api/external/",
    "/api/lp/",  # Landing page — endpoint público, sem sessão autenticada
    "/api/prototype/",  # Protótipo — sessão anônima por cookie device_id
    "/api/admin/",  # Admin — autenticado via TOTP, sem sessão/cookie
    "/api/validate-postal-code",  # CEP — endpoint público chamado do cardápio
    "/api/validate-email",       # Validação de e-mail — endpoint público, sem sessão
    "/api/validate-cellphone",   # Validação de telefone — endpoint público, sem sessão
]


def _csrf_generate() -> str:
    """Gera token CSRF assinado: {timestamp}.{nonce}.{hmac_sha256}"""
    ts = str(int(time.time()))
    nonce = secrets.token_hex(16)
    payload = f"{ts}.{nonce}"
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _csrf_verify(token: str) -> bool:
    """Verifica assinatura HMAC e validade temporal do token CSRF."""
    try:
        ts, nonce, sig = token.split(".", 2)
        payload = f"{ts}.{nonce}"
        expected = hmac.new(
            SECRET_KEY.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        age = int(time.time()) - int(ts)
        return 0 <= age <= _CSRF_MAX_AGE
    except Exception:
        return False


# ========================================================================
# CORS MIDDLEWARE - VALIDAÇÃO DE ORIGEM
# ========================================================================


# Importar os routers
from .Auth.AuthRoutes import auth_router, validation_auth_router
from .Auth.UserRoutes import user_router
from .Auth.ConsumerAuthRoutes import consumer_auth_router
from .Chat.ChatRoutes import chat_router, chat_operations_router, chat_watcher
from .Tools.ToolRoutes import tools_router
from .Subscription.SubscriptionRoutes import (
    subscription_router,
    subscription_cancel_router,
    credits_router,
    webhook_router,
    stripe_router,
    stripe_webhook_router,
)
from .Subscription.external_validation import validation_router
from .Agreement.AgreementRoutes import agreement_router
from .Sharing.SharingRoutes import sharing_router
from .Feedback.FeedbackRoutes import feedback_router
from .Uploads import upload_router
from .Webhooks import webhooks_router
from .Webhooks.OmniChannelWebhook import omni_webhook_router, omni_settings_router
from .Webhooks.TriggerWebhook import trigger_webhook_router
from .Webhooks.TriggerRoutes import trigger_router
from .Integrations.IntegrationsRoutes import webhook_secrets_router
from .Inspirations.InspirationRoutes import inspiration_router
from .WS.UserBrowserRouter import router as ws_agent_router
from .WS.WSChatRoutes import router as ws_chat_router
from .Integrations.IntegrationsRoutes import integrations_router
from .Agents.AgentsRoutes import agents_router
from .Scheduled.ScheduledRoutes import scheduled_router
from .Skills.SkillsRoutes import skills_router
from .Notes.NotesRoutes import notes_router
from .Google.GoogleActionsRoutes import google_actions_router
from .Admin.AdminRoutes import admin_router
from .MD70.AdminRoutes import router as md70_admin_router
from .MD70.PortalRoutes import router as md70_portal_router

try:
    from .Proxy.ProxyRoutes import proxy_router
except ImportError:
    proxy_router = None

if ENVIRONMENT != "production":
    try:
        from .Dev.DevRoutes import dev_router
    except ImportError:
        dev_router = None
else:
    dev_router = None

# Importar funções de logging
from App.Core.Logs import (
    log_by_level,
    set_request_id,
    set_session_id,
    debug,
    warning,
    error,
    info,
)

# ========================================================================
# VALIDATION ERROR HANDLER
# ========================================================================


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Captura erros de validação do Pydantic e loga detalhes"""
    error(f"[VALIDATION ERROR] Path: {request.url.path}, Errors: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )


# ========================================================================
# 5XX GLOBAL EXCEPTION HANDLER
# ========================================================================

_last_500_alert: float = 0.0
_ALERT_500_COOLDOWN = 5 * 60  # 5 minutos entre alertas


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Captura erros 500 não tratados e envia alerta ao Telegram (com cooldown)."""
    global _last_500_alert
    tb = traceback.format_exc()
    error(f"[500] {request.method} {request.url.path} — {exc}\n{tb}")

    now = time.time()
    if now - _last_500_alert > _ALERT_500_COOLDOWN:
        _last_500_alert = now
        try:
            from App.Core.Services.TelegramAlert.TelegramAlertService import (
                telegram_alert_service,
            )

            telegram_alert_service.send_critical_alert(
                subject="Erro 500 no backend",
                message=(
                    f"<b>Rota:</b> {request.method} {request.url.path}\n"
                    f"<b>Erro:</b> {type(exc).__name__}: {str(exc)[:200]}"
                ),
            )
        except Exception:
            pass

    return JSONResponse(
        status_code=500,
        content={"detail": "Erro interno do servidor"},
    )


# ========================================================================
# RATE LIMITING BYPASS MIDDLEWARE (EXCLUDED ROUTES)
# ========================================================================


@app.middleware("http")
async def rate_limiting_bypass_middleware(request: Request, call_next):
    """
    Skippa rate limiting para rotas específicas.
    """
    path = request.url.path
    if path.startswith("/api/chat/"):
        parts = path.split("/")
        if len(parts) >= 4:
            request.scope["skip_rate_limit"] = True

    response = await call_next(request)
    return response


# ========================================================================
# DEV BYPASS MIDDLEWARE
# ========================================================================


@app.middleware("http")
async def dev_bypass_middleware(request: Request, call_next):
    """
    Verifica se há dev_bypass_key no header X-Dev-Bypass-Key.
    """
    dev_bypass_key = request.headers.get("X-Dev-Bypass-Key")
    expected_dev_key = GLOBAL_CONFIG.get("dev_bypass_key", "")
    dev_user_id = GLOBAL_CONFIG.get("dev_user_id", "")
    dev_client_id = GLOBAL_CONFIG.get("dev_client_id", "1")

    if expected_dev_key and dev_bypass_key and dev_bypass_key == expected_dev_key:
        request.scope["dev_bypass_enabled"] = True
        request.scope["dev_user_id"] = dev_user_id
        request.scope["dev_client_id"] = dev_client_id

    response = await call_next(request)
    return response


# ========================================================================
# CSRF PROTECTION MIDDLEWARE
# ========================================================================


@app.middleware("http")
async def csrf_protection_middleware(request: Request, call_next):
    """
    Proteção CSRF via Double-Submit Cookie com assinatura HMAC-SHA256.

    Fluxo:
    - GETs emitem/renovam o csrf_token cookie (não-HttpOnly, lido pelo JS).
    - POSTs/PUTs/PATCHs/DELETEs exigem X-CSRF-Token header igual ao cookie.
    - O token é assinado com SECRET_KEY para prevenir forjamento.
    """
    path = request.url.path
    method = request.method.upper()

    # Dev bypass: pula validação CSRF em ambiente de desenvolvimento
    dev_bypass_key = request.headers.get("X-Dev-Bypass-Key", "")
    expected_dev_key = GLOBAL_CONFIG.get("dev_bypass_key", "")
    if expected_dev_key and dev_bypass_key == expected_dev_key:
        return await call_next(request)

    existing_token = request.cookies.get(_CSRF_COOKIE)
    is_mutating = method not in {"GET", "HEAD", "OPTIONS"}
    is_exempt = any(path.startswith(prefix) for prefix in _CSRF_EXEMPT_PREFIXES)

    # Validar em requisições mutantes não isentas
    if is_mutating and not is_exempt:
        if not existing_token or not _csrf_verify(existing_token):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "CSRF token ausente ou expirado. Recarregue a página."
                },
            )
        client_token = request.headers.get(_CSRF_HEADER, "")
        if not client_token or not hmac.compare_digest(client_token, existing_token):
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token inválido."},
            )

    response = await call_next(request)

    # Emitir/renovar token se ausente ou inválido
    if not existing_token or not _csrf_verify(existing_token):
        new_token = _csrf_generate()
        # httponly=False is intentional: csrf_token implements the "Double Submit Cookie"
        # pattern (RFC 6749 §10.12 / OWASP CSRF Prevention). The JS frontend reads this
        # cookie and echoes it in the X-CSRF-Token request header; the server then
        # compares both values. Setting HttpOnly would break this mechanism by making the
        # cookie unreadable to JavaScript. The session/auth token (access_token) is
        # separate and IS HttpOnly.
        response.set_cookie(
            _CSRF_COOKIE,
            new_token,
            max_age=_CSRF_MAX_AGE,
            httponly=False,  # nosec — by design, see comment above
            samesite="Strict",
            secure=COOKIE_SECURE,
            path="/",
        )

    return response


# ========================================================================
# REQUEST LOGGING MIDDLEWARE
# ========================================================================


@app.middleware("http")
async def log_all_requests(request: Request, call_next):
    """
    Loga todas as requisições HTTP.
    """
    sensitive_filter_enabled = GLOBAL_CONFIG.get("sensitive_filter", True)

    request_data = ""
    if request.method in ["POST", "PUT", "PATCH"]:
        try:
            content_type = request.headers.get("content-type", "")
            if "multipart/form-data" in content_type:
                request_data = " - [FormData upload]"
            else:
                body = await request.body()
                if body:
                    try:
                        data = json.loads(body)
                        # Filtro básico de campos sensíveis
                        security_filters_config = GLOBAL_CONFIG.get(
                            "security_filters_config", {}
                        )
                        sensitive_fields = {
                            f.lower()
                            for f in security_filters_config.get("sensitive_fields", [])
                        }

                        safe_fields = {
                            k: (
                                "***"
                                if k.lower() in sensitive_fields
                                and sensitive_filter_enabled
                                else v
                            )
                            for k, v in data.items()
                        }
                        fields = " ".join(
                            [f"[{k}: {v}]" for k, v in safe_fields.items()]
                        )
                        request_data = f" - {fields}" if fields else ""
                    except:
                        request_data = f" - [Content-Type: {content_type}]"

                async def receive():
                    return {"type": "http.request", "body": body, "more_body": False}

                request._receive = receive
        except Exception as e:
            warning(f"[LOG_MIDDLEWARE] Erro ao capturar body: {e}")

    response = await call_next(request)

    responsible_file = ""
    try:
        endpoint = request.scope.get("endpoint")
        if endpoint and endpoint.__module__ != "App.Core.Services.Services":
            responsible_file = f"[{endpoint.__module__}]"
    except:
        pass

    separator = " " if responsible_file else ""
    log_by_level(
        f"[{request.method}] {request.url.path}{request_data}{separator}{responsible_file} [{response.status_code}]"
    )

    return response


# ========================================================================
# AUTH TOKEN CACHE MIDDLEWARE
# ========================================================================


import asyncio as _asyncio
import hashlib as _hashlib


def _resolve_auth_token(token: str):
    """Resolve token JWT: Redis → JWT+DB. Roda em thread pool para não bloquear o event loop."""
    try:
        from App.Core.Cache.RedisCache import cache_get, cache_set

        _key = "auth:" + _hashlib.sha256(token.encode()).hexdigest()[:32]
        cached = cache_get(_key)
        if cached is not None:
            return cached, _key
        from App.Features.Auth import get_auth_service

        payload = get_auth_service().verify_token(token, check_db=True)
        if payload:
            # Cache até a expiração real do token (max 30 min), com 30s de margem
            import time as _time
            exp = payload.get("exp", 0)
            ttl = max(60, min(int(exp - _time.time()) - 30, 1800)) if exp else 300
            cache_set(_key, payload, ttl)
            return payload, _key
        return None, _key
    except Exception:
        return None, None


@app.middleware("http")
async def auth_token_cache_middleware(request: Request, call_next):
    """
    Resolve o token JWT UMA vez por request e armazena em scope["_auth_payload"].
    Corre em thread pool para não bloquear o event loop durante I/O de Redis/SQLite.
    Fluxo: Redis hit → scope (zero DB). Redis miss → verify_token (JWT+DB) → scope + Redis(60s).
    """
    token = request.cookies.get("access_token")
    if token and not request.scope.get("dev_bypass_enabled"):
        try:
            payload, _ = await _asyncio.to_thread(_resolve_auth_token, token)
            if payload:
                request.scope["_auth_payload"] = payload
        except Exception:
            pass
    response = await call_next(request)
    return response


# ========================================================================
# REQUEST ID AND SESSION ID MIDDLEWARE
# ========================================================================


@app.middleware("http")
async def id_headers_middleware(request: Request, call_next):
    """
    Injeta X-Request-ID e X-Session-ID headers.
    """
    request_id = set_request_id()
    session_id = request.headers.get("X-Session-ID") or str(uuid.uuid4())
    set_session_id(session_id)

    response = await call_next(request)

    # Prevenção de Session Fixation: Regenerar ID em caso de login/registro bem-sucedido (200)
    if response.status_code == 200 and any(
        path in request.url.path
        for path in [
            "/api/auth/login",
            "/api/auth/signup",
            "/api/auth/callback",
            "/api/auth/refresh",
        ]
    ):
        session_id = str(uuid.uuid4())
        set_session_id(session_id)

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Session-ID"] = session_id

    return response


# ========================================================================
# ROUTERS
# ========================================================================

if auth_router:
    app.include_router(auth_router)
if validation_auth_router:
    app.include_router(validation_auth_router)
if user_router:
    app.include_router(user_router)
app.include_router(consumer_auth_router)
if chat_router:
    app.include_router(chat_router)
if chat_operations_router:
    app.include_router(chat_operations_router)
if tools_router:
    app.include_router(tools_router)
if subscription_router:
    app.include_router(subscription_router)
if subscription_cancel_router:
    app.include_router(subscription_cancel_router)
if credits_router:
    app.include_router(credits_router)
if webhook_router:
    app.include_router(webhook_router)
if stripe_router:
    app.include_router(stripe_router)
if stripe_webhook_router:
    app.include_router(stripe_webhook_router)
if omni_webhook_router:
    app.include_router(omni_webhook_router)
if omni_settings_router:
    app.include_router(omni_settings_router)
if trigger_webhook_router:
    app.include_router(trigger_webhook_router)
if trigger_router:
    app.include_router(trigger_router)
if webhook_secrets_router:
    app.include_router(webhook_secrets_router)
if validation_router:
    app.include_router(validation_router)
if agreement_router:
    app.include_router(agreement_router)
if sharing_router:
    app.include_router(sharing_router)
if feedback_router:
    app.include_router(feedback_router)
if upload_router:
    app.include_router(upload_router)
if webhooks_router:
    app.include_router(webhooks_router)
if inspiration_router:
    app.include_router(inspiration_router)
if ws_agent_router:
    app.include_router(ws_agent_router)
app.include_router(ws_chat_router)
if integrations_router:
    app.include_router(integrations_router)
app.include_router(agents_router)
app.include_router(scheduled_router)
app.include_router(skills_router)
app.include_router(notes_router)
app.include_router(google_actions_router)
app.include_router(admin_router)
app.include_router(md70_admin_router)
app.include_router(md70_portal_router)
if dev_router:
    app.include_router(dev_router)
if proxy_router:
    try:
        app.include_router(proxy_router)
    except:
        pass


# ========================================================================
# DOWNLOAD EXTENSION
# ========================================================================


@app.get("/api/download-extension")
async def download_extension():
    """Download the MD70 Browser Extension (zipped)."""
    file_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "..",
        "Media",
        "Static",
        "prox_extension.zip",
    )
    if not os.path.exists(file_path):
        return JSONResponse(
            status_code=404, content={"detail": "Arquivo de extensão não encontrado."}
        )
    return FileResponse(
        path=file_path,
        filename="prox_extension.zip",
        media_type="application/zip",
    )


# ========================================================================
# HEALTH CHECK
# ========================================================================


@app.api_route("/api/health", methods=["GET", "HEAD"])
async def health_check():
    return {"status": "ok", "message": "Backend saudável (Services.py)"}


# ========================================================================
# CATCH-ALL HANDLER PARA ROTAS NÃO MAPEADAS (404)
# ========================================================================


@app.api_route(
    "/{full_path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def catch_all(full_path: str, request: Request):
    return JSONResponse(
        status_code=404, content={"detail": "Not Found", "path": f"/{full_path}"}
    )


# ========================================================================
# ZERA SECURITY MIDDLEWARE (LOW-LEVEL ASGI)
# ========================================================================


class ZeraSecurityMiddleware:
    """
    Middleware de Segurança de baixo nível (ASGI) para garantir a remoção
    definitiva de headers de fingerprinting do servidor.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = []
                # Padrões para remover (em bytes, como o ASGI exige)
                to_remove = [b"server", b"x-powered-by"]

                # Filtrar headers originais e injetar flags em cookies
                for k, v in message.get("headers", []):
                    if k.lower() not in to_remove:
                        if k.lower() == b"set-cookie":
                            cookie_val = v.decode()
                            # csrf_token deve ser lido pelo JS — nunca recebe HttpOnly
                            is_csrf = cookie_val.lstrip().startswith(f"{_CSRF_COOKIE}=")
                            if not is_csrf and "httponly" not in cookie_val.lower():
                                cookie_val += "; HttpOnly"
                            if COOKIE_SECURE and "secure" not in cookie_val.lower():
                                cookie_val += "; Secure"
                            if "samesite" not in cookie_val.lower():
                                cookie_val += f"; SameSite={COOKIE_SAMESITE}"
                            headers.append((k, cookie_val.encode()))
                        else:
                            headers.append((k, v))

                # Injetar headers de segurança
                headers.append((b"x-system-engine", b"MD70 Security Server"))
                # Security headers are now handled by the Nginx Gateway
                headers.append((b"x-content-type-options", b"nosniff"))
                headers.append((b"x-xss-protection", b"1; mode=block"))
                headers.append((b"referrer-policy", b"strict-origin-when-cross-origin"))
                headers.append(
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()")
                )

                message["headers"] = headers

            await send(message)

        await self.app(scope, receive, send_wrapper)


# Aplicar middleware de segurança de baixo nível ao final (será o primeiro a processar a resposta)
app.add_middleware(ZeraSecurityMiddleware)

# ========================================================================
# EXPORTS
# ========================================================================

__all__ = ["app", "setup_app", "startup_event", "COMPONENTS"]
