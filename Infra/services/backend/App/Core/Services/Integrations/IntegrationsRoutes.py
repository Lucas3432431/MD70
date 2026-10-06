"""
Rotas de Integrações MCP - /api/integrations
Gerencia conexões com provedores externos (Meta Ads, Shopify, Stripe, Google, Notion, etc.)
"""

import asyncio
import json
import re
import secrets
import urllib.parse
from typing import Optional
from fastapi import APIRouter, Query, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from pydantic import BaseModel, Field
import httpx

from sqlalchemy import text
from App.Core.Logs import debug, error as log_error
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Services.Common.Dependencies import COMPONENTS
from App.Features.Tools.Mcp.MCPClientManager import mcp_manager
from App.Features.Auth import get_auth_service
from App.Core.Settings.Settings import (
    GOOGLE_AUTH_CLIENT_ID,
    GOOGLE_AUTH_CLIENT_SECRET,
    GADS_DEVELOPER_TOKEN,
    GADS_MANAGER_CUSTOMER_ID,
    GITHUB_CLIENT_ID,
    GITHUB_CLIENT_SECRET,
    META_CLIENT_ID,
    META_CLIENT_SECRET,
    NOTION_CLIENT_ID,
    NOTION_CLIENT_SECRET,
    LINKEDIN_CLIENT_ID,
    LINKEDIN_CLIENT_SECRET,
    VITE_HTTP_PROTOCOL,
    PUBLIC_URL,
    FRONTEND_HOST,
    NGINX_PORT,
    FRONTEND_PORT,
    ENVIRONMENT,
    WEBHOOK_PREFIX,
)

integrations_router = APIRouter(tags=["Integrations"], prefix="/api/integrations")

# ========================================================================
# CONFIGURAÇÃO DE PROVEDORES
# provider → command/args que o MCPClientManager vai usar
# ========================================================================

PROVIDER_CONFIGS = {
    "meta-ads": {"command": "npx", "args": ["-y", "meta-ads-mcp"]},
    "instagram": {"command": "npx", "args": ["-y", "instagram-mcp"]},
    "linkedin": {"command": "npx", "args": ["-y", "linkedin-mcp"]},
    "tiktok-ads": {"command": "npx", "args": ["-y", "tiktok-ads-mcp"]},
    "shopify": {"command": "npx", "args": ["-y", "shopify-mcp"]},
    "stripe": {"command": "npx", "args": ["-y", "stripe-mcp"]},
    "notion": {"command": "npx", "args": ["-y", "@notionhq/notion-mcp-server"]},
    "google-drive": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-gdrive"],
    },
    "google-calendar": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-gcalendar"],
    },
    "google-tasks": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-gtasks"],
    },
    "google-keep": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-google-keep"],
    },
    "gmail": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-gmail"],
    },
    "google-analytics": {
        "command": "npx",
        "args": ["-y", "google-analytics-mcp"],
    },
    "google-ads": {
        "command": "npx",
        "args": ["-y", "google-ads-mcp"],
    },
    "hubspot": {"command": "npx", "args": ["-y", "@hubspot/mcp-server"]},
    "klaviyo": {"command": "npx", "args": ["-y", "klaviyo-mcp"]},
    "airtable": {"command": "npx", "args": ["-y", "airtable-mcp"]},
    "slack": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-slack"]},
    "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]},
    "supabase": {"command": "npx", "args": ["-y", "@supabase/mcp-server-supabase"]},
    "resend": {"command": "native", "args": [], "native": True},
}


# Providers com transformação especial de env_vars
def _transform_env_vars(provider: str, env_vars: dict) -> dict:
    """Transforma env_vars amigáveis para o formato que o MCP server espera."""
    if provider == "notion" and "NOTION_TOKEN" in env_vars:
        token = env_vars["NOTION_TOKEN"]
        return {
            "OPENAPI_MCP_HEADERS": json.dumps(
                {
                    "Authorization": f"Bearer {token}",
                    "Notion-Version": "2022-06-28",
                }
            )
        }
    return env_vars


def _extract_cross_provider(provider: str, env_vars: dict) -> tuple[dict, str | None]:
    """Extrai env_vars do provider secundário se campos cruzados estiverem presentes."""
    if provider == "meta-ads":
        ig_id = env_vars.get("INSTAGRAM_BUSINESS_ACCOUNT_ID", "").strip()
        token = env_vars.get("META_ACCESS_TOKEN", "")
        if ig_id and token:
            return {
                "INSTAGRAM_ACCESS_TOKEN": token,
                "INSTAGRAM_BUSINESS_ACCOUNT_ID": ig_id,
            }, "instagram"

    if provider == "instagram":
        ad_id = env_vars.get("META_AD_ACCOUNT_ID", "").strip()
        token = env_vars.get("INSTAGRAM_ACCESS_TOKEN", "")
        if ad_id and token:
            normalized = ad_id if ad_id.startswith("act_") else f"act_{ad_id}"
            return {
                "META_ACCESS_TOKEN": token,
                "META_AD_ACCOUNT_ID": normalized,
            }, "meta-ads"

    return {}, None


# ========================================================================
# HELPERS DE AUTH
# ========================================================================


def _get_auth_payload(request: Request) -> dict:
    if request.scope.get("dev_bypass_enabled"):
        return {
            "client_id": str(request.scope.get("dev_client_id", "1")),
            "user_id": str(request.scope.get("dev_user_id", "1")),
        }

    # Caminho rápido: middleware já resolveu o token no scope
    cached = request.scope.get("_auth_payload")
    if cached:
        return cached

    # Fallback: verificação completa (Redis miss no middleware)
    token = request.cookies.get("access_token") or (
        request.headers.get("Authorization", "").replace("Bearer ", "")
        if request.headers.get("Authorization")
        else None
    )
    if not token:
        raise HTTPException(status_code=401, detail="Token não fornecido")

    auth_service = get_auth_service()
    payload = auth_service.verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido")

    return payload


def _get_base_url() -> str:
    if ENVIRONMENT == "production":
        return PUBLIC_URL.rstrip("/")
    port = NGINX_PORT or FRONTEND_PORT
    host = FRONTEND_HOST if FRONTEND_HOST not in ("0.0.0.0", "") else "localhost"
    return f"{VITE_HTTP_PROTOCOL}://{host}:{port}"


def _clear_mcp_sessions(client_id: str):
    try:
        from App.Features.Tools.Mcp.MCPClientManager import mcp_manager

        if client_id in mcp_manager.client_sessions:
            del mcp_manager.client_sessions[client_id]
    except Exception:
        pass


# ========================================================================
# MODELS
# ========================================================================


class TokenConnectRequest(BaseModel):
    provider: str = Field(..., min_length=1, max_length=100)
    env_vars: dict = Field(default_factory=dict)


class ChatConnectionBody(BaseModel):
    chat_id: str = Field(..., min_length=1)


class CustomMCPRequest(BaseModel):
    provider: str = Field(..., min_length=1, max_length=100)
    command: str = Field(..., min_length=1, max_length=200)
    args: list = Field(default_factory=list)
    env_vars: dict = Field(default_factory=dict)


class McpCallRequest(BaseModel):
    tool_name: str = Field(..., description="Nome completo: mcp__provider__action")
    args: dict = Field(default_factory=dict)


# ========================================================================
# MCP DIRECT CALL (file picker, etc.)
# ========================================================================


@integrations_router.post("/mcp/call")
async def call_mcp_tool(body: McpCallRequest, request: Request):
    """Chama uma ferramenta MCP diretamente (ex: listar arquivos do Drive para file picker)."""
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    if not body.tool_name.startswith("mcp__"):
        raise HTTPException(status_code=400, detail="tool_name deve começar com mcp__")

    try:
        from App.Features.Tools.Mcp.MCPClientManager import mcp_manager

        result = await mcp_manager.call_tool(client_id, body.tool_name, body.args)
        return result
    except Exception as e:
        log_error(f"[Integrations] Erro ao chamar MCP tool {body.tool_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========================================================================
# GOOGLE DRIVE FILE PICKER
# ========================================================================

_DRIVE_LINE_RE = re.compile(r"^(.+?)\s+\(([^)]+)\)\s+—\s+id:\s+(.+)$")


@integrations_router.get("/google-drive/files")
async def list_drive_files(
    request: Request,
    q: Optional[str] = Query(None, description="Filtro de busca (client-side)"),
    max_results: int = Query(50, ge=1, le=200),
):
    """Lista arquivos do Google Drive do usuário autenticado como JSON estruturado."""
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    try:
        from App.Features.Tools.Mcp.MCPClientManager import mcp_manager

        result = await mcp_manager.call_tool(
            client_id,
            "mcp__google-drive__list",
            {"max_results": max_results},
        )

        if not result.get("success"):
            return {
                "success": False,
                "files": [],
                "error": result.get("error", "Drive não conectado"),
            }

        files = []
        for line in (result.get("content") or "").splitlines():
            line = line.strip()
            if not line:
                continue
            m = _DRIVE_LINE_RE.match(line)
            if m:
                files.append(
                    {
                        "name": m.group(1).strip(),
                        "mimeType": m.group(2).strip(),
                        "fileId": m.group(3).strip(),
                    }
                )

        return {"success": True, "files": files}

    except Exception as e:
        log_error(f"[Drive] Erro ao listar arquivos: {e}")
        return {"success": False, "files": [], "error": str(e)}


# ========================================================================
# CRUD
# ========================================================================


_TRIGGER_MESSAGING_PROVIDERS = {"whatsapp", "telegram", "instagram"}


def _invalidate_integrations_cache(client_id: str) -> None:
    try:
        from App.Core.Cache.RedisCache import cache_delete

        cache_delete(f"integrations:{client_id}")
    except Exception:
        pass


@integrations_router.get("")
async def list_integrations(request: Request):
    """Lista integrações ativas do usuário, incluindo providers de triggers de mensageria."""
    from App.Core.Cache.RedisCache import cache_get, cache_set

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    _int_cache_key = f"integrations:{client_id}"
    _cached_int = cache_get(_int_cache_key)
    if _cached_int is not None:
        debug(f"[Integrations] list cache hit para client {client_id}")
        return _cached_int

    from App.Core.Services.Webhooks.TriggerWebhook import _ensure_tables

    _ensure_tables()

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=500, detail="DB manager não configurado")

    try:
        records = db_manager.execute_transaction(
            lambda session: db_manager.list_mcp_integrations(session, client_id)
        )

        existing_providers = {r["provider"] for r in records}

        def _get_trigger_providers(session):
            rows = session.execute(
                text(
                    "SELECT DISTINCT provider, MIN(created_at) AS created_at"
                    " FROM webhook_secrets"
                    " WHERE client_id = :cid"
                    " AND provider IN ('whatsapp', 'telegram', 'instagram')"
                    " GROUP BY provider"
                ),
                {"cid": client_id},
            ).fetchall()
            return rows

        trigger_rows = db_manager.execute_transaction(_get_trigger_providers)
        for row in trigger_rows:
            provider = row[0]
            created_at = row[1]
            if provider not in existing_providers:
                records.append(
                    {
                        "integration_id": f"trigger__{provider}__{client_id}",
                        "provider": provider,
                        "is_active": True,
                        "token_valid": True,
                        "created_at": (
                            created_at.isoformat()
                            if hasattr(created_at, "isoformat")
                            else str(created_at)
                        ),
                    }
                )

        # Health check para providers sem auto-refresh (ex: meta-ads)
        try:
            health = await mcp_manager.check_native_token_health(client_id)
            for provider, is_valid in health.items():
                record = next((r for r in records if r["provider"] == provider), None)
                if record and record.get("token_valid") != is_valid:
                    if is_valid:
                        db_manager.execute_transaction(
                            lambda session, p=provider: DatabaseManager.mark_integration_token_valid(
                                session, client_id, p
                            )
                        )
                    else:
                        db_manager.execute_transaction(
                            lambda session, p=provider: DatabaseManager.mark_integration_token_invalid(
                                session, client_id, p
                            )
                        )
                    record["token_valid"] = is_valid
                    debug(
                        f"[Integrations] Health check atualizou {provider} token_valid={is_valid}"
                    )
        except Exception as health_err:
            debug(f"[Integrations] Erro no health check: {health_err}")

        result_payload = {"integrations": records}
        cache_set(
            _int_cache_key, result_payload, 86400
        )  # 24h TTL (invalidação precisa)
        return result_payload
    except Exception as e:
        log_error(f"[Integrations] Erro ao listar: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar integrações")


_SENSITIVE_KEYS = {"TOKEN", "SECRET", "KEY", "PASSWORD", "ACCESS", "REFRESH"}


def _mask_env_vars(env: dict) -> dict:
    """Retorna env_vars com campos sensíveis mascarados (últimos 4 chars visíveis)."""
    result = {}
    for k, v in env.items():
        if not v:
            result[k] = v
            continue
        upper = k.upper()
        if any(s in upper for s in _SENSITIVE_KEYS) and len(str(v)) > 8:
            masked = "••••••••" + str(v)[-4:]
            result[k] = masked
        else:
            result[k] = v
    return result


@integrations_router.get("/{provider}/fields")
async def get_integration_fields(provider: str, request: Request):
    """Retorna os campos atuais de uma integração (tokens mascarados)."""
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=500, detail="DB manager não configurado")

    env = db_manager.execute_transaction(
        lambda session: db_manager.get_mcp_integration_env_vars(
            session, client_id=client_id, provider=provider
        )
    )
    return {"fields": _mask_env_vars(env)}


class FieldsPatchBody(BaseModel):
    patch: dict


@integrations_router.patch("/{provider}/fields")
async def patch_integration_fields(
    provider: str, body: FieldsPatchBody, request: Request
):
    """Atualiza campos específicos de uma integração sem substituir tudo."""
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=500, detail="DB manager não configurado")

    if not body.patch:
        raise HTTPException(status_code=400, detail="Nenhum campo enviado")

    ok = db_manager.execute_transaction(
        lambda session: db_manager.patch_mcp_integration_env_vars(
            session, client_id=client_id, provider=provider, patch=body.patch
        )
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Integração não encontrada")

    _clear_mcp_sessions(client_id)
    return {"success": True}


@integrations_router.delete("/{integration_id}")
async def delete_integration(integration_id: str, request: Request):
    """Desativa uma integração MCP."""
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=500, detail="DB manager não configurado")

    try:
        ok = db_manager.execute_transaction(
            lambda session: db_manager.delete_mcp_integration(
                session, integration_id, client_id
            )
        )
        if not ok:
            raise HTTPException(status_code=404, detail="Integração não encontrada")

        _clear_mcp_sessions(client_id)
        _invalidate_integrations_cache(client_id)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"[Integrations] Erro ao deletar {integration_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro ao remover integração")


# ========================================================================
# CONEXÃO VIA TOKEN (Meta, Shopify, Stripe, Notion, TikTok, etc.)
# ========================================================================


@integrations_router.post("/token")
async def connect_via_token(body: TokenConnectRequest, request: Request):
    """
    Conecta qualquer provider via token.
    O backend conhece o command/args de cada provider pelo ID.
    """
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    config = PROVIDER_CONFIGS.get(body.provider)
    if not config:
        raise HTTPException(
            status_code=400, detail=f"Provider '{body.provider}' não suportado"
        )

    if not body.env_vars:
        raise HTTPException(
            status_code=400, detail="Informe pelo menos um token/credencial"
        )

    # Extrai e remove campos cruzados do env_vars antes de salvar o provider principal
    cross_env_vars, cross_provider = _extract_cross_provider(
        body.provider, body.env_vars
    )
    env_vars = _transform_env_vars(
        body.provider,
        {
            k: v
            for k, v in body.env_vars.items()
            if k not in {"INSTAGRAM_BUSINESS_ACCOUNT_ID", "META_AD_ACCOUNT_ID"}
            or body.provider in ("meta-ads", "instagram")
        },
    )
    # Limpa campos cruzados do env_vars primário
    if body.provider == "meta-ads":
        env_vars.pop("INSTAGRAM_BUSINESS_ACCOUNT_ID", None)
    elif body.provider == "instagram":
        env_vars.pop("META_AD_ACCOUNT_ID", None)

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=500, detail="DB manager não configurado")

    try:
        integration_id = db_manager.execute_transaction(
            lambda session: db_manager.create_mcp_integration(
                session,
                client_id=client_id,
                provider=body.provider,
                command=config["command"],
                args=config["args"],
                env_vars=env_vars,
            )
        )

        # Cross-save: salva provider secundário se campos cruzados foram fornecidos
        cross_integration_id = None
        if cross_provider and cross_env_vars:
            cross_config = PROVIDER_CONFIGS.get(cross_provider)
            if cross_config:
                try:
                    cross_integration_id = db_manager.execute_transaction(
                        lambda session: db_manager.create_mcp_integration(
                            session,
                            client_id=client_id,
                            provider=cross_provider,
                            command=cross_config["command"],
                            args=cross_config["args"],
                            env_vars=cross_env_vars,
                        )
                    )
                    debug(
                        f"[Integrations] Cross-save: {cross_provider} conectado para client {client_id}"
                    )
                except Exception as ce:
                    log_error(
                        f"[Integrations] Cross-save falhou para {cross_provider}: {ce}"
                    )

        _clear_mcp_sessions(client_id)
        _invalidate_integrations_cache(client_id)
        debug(f"[Integrations] {body.provider} conectado para client {client_id}")
        return {
            "success": True,
            "integration_id": integration_id,
            "cross_integration_id": cross_integration_id,
            "cross_provider": cross_provider,
        }
    except Exception as e:
        log_error(f"[Integrations] Erro ao conectar {body.provider}: {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar integração")


# ========================================================================
# VALIDAÇÃO DE CREDENCIAIS
# ========================================================================


class ValidateRequest(BaseModel):
    provider: str
    env_vars: dict


async def _fetch_meta_permissions(client: httpx.AsyncClient, token: str) -> set:
    """Retorna o conjunto de permissões concedidas ao token."""
    r = await client.get(
        "https://graph.facebook.com/v21.0/me/permissions",
        params={"access_token": token},
        timeout=10,
    )
    if r.status_code != 200:
        return set()
    data = r.json().get("data", [])
    return {p["permission"] for p in data if p.get("status") == "granted"}


async def _validate_meta_ad_account(
    client: httpx.AsyncClient, token: str, account_id: str
) -> dict:
    """Valida conta de anúncios. Retorna {"ok": bool, "error": str|None}."""
    if not account_id.startswith("act_"):
        account_id = f"act_{account_id}"
    r = await client.get(
        f"https://graph.facebook.com/v21.0/{account_id}",
        params={"fields": "id,name,account_status", "access_token": token},
        timeout=10,
    )
    data = r.json()
    if r.status_code != 200:
        return {
            "ok": False,
            "error": data.get("error", {}).get("message", "Account ID inválido"),
        }
    STATUS_LABELS = {
        2: "desativada",
        3: "sem pagamento cadastrado",
        7: "pendente de revisão",
    }
    status = data.get("account_status")
    if status in STATUS_LABELS:
        return {"ok": False, "error": f"Conta de anúncios {STATUS_LABELS[status]}"}
    return {"ok": True, "error": None}


async def _validate_instagram_account(
    client: httpx.AsyncClient, token: str, ig_account_id: str
) -> dict:
    """Valida conta Instagram Business. Retorna {"ok": bool, "error": str|None}."""
    r = await client.get(
        f"https://graph.facebook.com/v21.0/{ig_account_id}",
        params={"fields": "id,name,username,followers_count", "access_token": token},
        timeout=10,
    )
    data = r.json()
    if r.status_code != 200:
        return {
            "ok": False,
            "error": data.get("error", {}).get("message", "ID do Instagram inválido"),
        }
    return {"ok": True, "error": None}


@integrations_router.post("/validate")
async def validate_integration(body: ValidateRequest, request: Request):
    """Valida credenciais e verifica escopos cruzados (Meta Ads ↔ Instagram)."""
    _get_auth_payload(request)

    if body.provider == "meta-ads":
        token = body.env_vars.get("META_ACCESS_TOKEN", "")
        account_id = body.env_vars.get("META_AD_ACCOUNT_ID", "").strip()
        ig_account_id = body.env_vars.get("INSTAGRAM_BUSINESS_ACCOUNT_ID", "").strip()

        if not token or not account_id:
            return {"valid": False, "error": "Token e Account ID são obrigatórios"}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Valida conta de anúncios + busca permissões em paralelo
                ad_result, scopes = await asyncio.gather(
                    _validate_meta_ad_account(client, token, account_id),
                    _fetch_meta_permissions(client, token),
                )

            if not ad_result["ok"]:
                return {"valid": False, "error": ad_result["error"]}

            has_instagram = (
                "instagram_manage_insights" in scopes or "pages_show_list" in scopes
            )

            # Valida conta Instagram se fornecida
            cross_valid = False
            ig_error = None
            if ig_account_id:
                async with httpx.AsyncClient(timeout=10) as client:
                    ig_result = await _validate_instagram_account(
                        client, token, ig_account_id
                    )
                cross_valid = ig_result["ok"] and has_instagram
                ig_error = ig_result["error"] if not ig_result["ok"] else None

            return {
                "valid": True,
                "scopes": {
                    "instagram_basic": has_instagram,
                    "ads_read": "ads_read" in scopes,
                    "ads_management": "ads_management" in scopes,
                },
                "cross_valid": cross_valid,
                "cross_provider": "instagram" if cross_valid else None,
                "cross_error": ig_error,
            }

        except httpx.TimeoutException:
            return {"valid": False, "error": "Timeout ao conectar com a API do Meta"}
        except Exception as e:
            log_error(f"[Integrations] Erro ao validar meta-ads: {e}")
            return {"valid": False, "error": "Erro ao validar credenciais"}

    if body.provider == "instagram":
        token = body.env_vars.get("INSTAGRAM_ACCESS_TOKEN", "")
        ig_account_id = body.env_vars.get("INSTAGRAM_BUSINESS_ACCOUNT_ID", "").strip()
        ad_account_id = body.env_vars.get("META_AD_ACCOUNT_ID", "").strip()

        if not token or not ig_account_id:
            return {
                "valid": False,
                "error": "Token e ID da conta Instagram são obrigatórios",
            }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                ig_result, scopes = await asyncio.gather(
                    _validate_instagram_account(client, token, ig_account_id),
                    _fetch_meta_permissions(client, token),
                )

            if not ig_result["ok"]:
                return {"valid": False, "error": ig_result["error"]}

            has_ads_read = "ads_read" in scopes or "ads_management" in scopes

            cross_valid = False
            ad_error = None
            if ad_account_id:
                async with httpx.AsyncClient(timeout=10) as client:
                    ad_result = await _validate_meta_ad_account(
                        client, token, ad_account_id
                    )
                cross_valid = ad_result["ok"] and has_ads_read
                ad_error = ad_result["error"] if not ad_result["ok"] else None

            return {
                "valid": True,
                "scopes": {
                    "instagram_manage_insights": "instagram_manage_insights" in scopes,
                    "pages_show_list": "pages_show_list" in scopes,
                    "ads_read": has_ads_read,
                },
                "cross_valid": cross_valid,
                "cross_provider": "meta-ads" if cross_valid else None,
                "cross_error": ad_error,
            }

        except httpx.TimeoutException:
            return {"valid": False, "error": "Timeout ao conectar com a API do Meta"}
        except Exception as e:
            log_error(f"[Integrations] Erro ao validar instagram: {e}")
            return {"valid": False, "error": "Erro ao validar credenciais"}

    if body.provider == "supabase":
        url = body.env_vars.get("SUPABASE_URL", "").rstrip("/")
        key = body.env_vars.get("SUPABASE_SERVICE_KEY", "")
        if not url or not key:
            return {
                "valid": False,
                "error": "SUPABASE_URL e SUPABASE_SERVICE_KEY são obrigatórios",
            }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{url}/rest/v1/",
                    headers={"apikey": key, "Authorization": f"Bearer {key}"},
                )
            if resp.status_code in (200, 201):
                return {"valid": True}
            return {
                "valid": False,
                "error": f"Supabase retornou HTTP {resp.status_code}",
            }
        except httpx.TimeoutException:
            return {"valid": False, "error": "Timeout ao conectar com o Supabase"}
        except Exception as e:
            log_error(f"[Integrations] Erro ao validar supabase: {e}")
            return {"valid": False, "error": "Erro ao validar credenciais"}

    if body.provider == "resend":
        api_key = body.env_vars.get("RESEND_API_KEY", "").strip()
        if not api_key:
            return {"valid": False, "error": "RESEND_API_KEY é obrigatório"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.resend.com/domains",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            if resp.status_code == 200:
                return {"valid": True}
            if resp.status_code == 401:
                return {"valid": False, "error": "API key inválida"}
            return {"valid": False, "error": f"Resend retornou HTTP {resp.status_code}"}
        except httpx.TimeoutException:
            return {"valid": False, "error": "Timeout ao conectar com a API do Resend"}
        except Exception as e:
            log_error(f"[Integrations] Erro ao validar resend: {e}")
            return {"valid": False, "error": "Erro ao validar credenciais"}

    return {"valid": True}


# ========================================================================
# MCP PERSONALIZADO
# ========================================================================


@integrations_router.post("/custom")
async def create_custom_integration(body: CustomMCPRequest, request: Request):
    """Cria uma integração MCP totalmente personalizada."""
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=500, detail="DB manager não configurado")

    try:
        integration_id = db_manager.execute_transaction(
            lambda session: db_manager.create_mcp_integration(
                session,
                client_id=client_id,
                provider=body.provider,
                command=body.command,
                args=body.args,
                env_vars=body.env_vars,
            )
        )
        _clear_mcp_sessions(client_id)
        _invalidate_integrations_cache(client_id)
        return {"success": True, "integration_id": integration_id}
    except Exception as e:
        log_error(f"[Integrations] Erro ao criar MCP personalizado: {e}")
        raise HTTPException(status_code=500, detail="Erro ao criar integração")


# ========================================================================
# GOOGLE OAUTH (Drive + Sheets — reutiliza infra existente)
# ========================================================================

_google_states: dict = {}  # state → (client_id, provider)

_GOOGLE_PROVIDER_SCOPES = {
    "google-drive": [
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/spreadsheets",
    ],
    "google-calendar": [
        "https://www.googleapis.com/auth/calendar",
    ],
    "google-tasks": [
        "https://www.googleapis.com/auth/tasks",
    ],
    "google-keep": [
        "https://www.googleapis.com/auth/keep",
    ],
    "gmail": [
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.modify",
    ],
    "google-analytics": [
        "https://www.googleapis.com/auth/analytics.readonly",
    ],
    "google-ads": [
        "https://www.googleapis.com/auth/adwords",
    ],
    "youtube": [
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ],
}


class GoogleOAuthInitBody(BaseModel):
    provider: str = "google-drive"


@integrations_router.post("/oauth/google/init")
async def google_oauth_init(request: Request, body: GoogleOAuthInitBody):
    """Gera a URL de autorização do Google e armazena o state.
    Chamado via POST com auth headers — retorna a URL para o frontend abrir no popup."""
    if not GOOGLE_AUTH_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google OAuth não configurado")
    if body.provider not in _GOOGLE_PROVIDER_SCOPES:
        raise HTTPException(
            status_code=400, detail=f"Provider '{body.provider}' não suportado"
        )

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    state = secrets.token_urlsafe(32)
    _google_states[state] = (client_id, body.provider)

    callback_url = f"{_get_base_url()}/api/integrations/oauth/google/callback"
    scopes = " ".join(_GOOGLE_PROVIDER_SCOPES[body.provider])

    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={GOOGLE_AUTH_CLIENT_ID}"
        f"&redirect_uri={urllib.parse.quote(callback_url, safe='')}"
        f"&response_type=code"
        f"&scope={urllib.parse.quote(scopes, safe='')}"
        f"&access_type=offline"
        f"&prompt=consent"
        f"&state={state}"
    )

    return JSONResponse({"auth_url": auth_url})


async def _fetch_gads_account_ids(access_token: str, developer_token: str) -> list[str]:
    """Returns list of accessible Google Ads customer IDs."""
    if not developer_token:
        return []
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get(
                "https://googleads.googleapis.com/v21/customers:listAccessibleCustomers",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "developer-token": developer_token,
                },
            )
            if resp.status_code != 200:
                debug(
                    f"[Integrations] listAccessibleCustomers HTTP {resp.status_code}: {resp.text[:200]}"
                )
                return []
            data = resp.json()
            resource_names = data.get("resourceNames", [])
            return [rn.split("/")[-1] for rn in resource_names]
    except Exception as exc:
        debug(f"[Integrations] Erro ao buscar GADS account IDs: {exc}")
        return []


def _popup_html(
    msg_type: str, provider: str = "", error_key: str = "", extra: dict | None = None
) -> str:
    payload: dict = {"type": msg_type, "provider": provider, "error": error_key}
    if extra:
        payload.update(extra)
    payload_json = json.dumps(payload)
    return f"""<!DOCTYPE html><html><body><script>
var p={payload_json};
try{{if(window.opener){{window.opener.postMessage(p,'*');}}}}catch(e){{}}
try{{var bc=new BroadcastChannel('prox_oauth');bc.postMessage(p);setTimeout(function(){{bc.close();}},200);}}catch(e){{}}
setTimeout(function(){{window.close();}},400);
</script></body></html>"""


@integrations_router.get("/oauth/google/callback")
async def google_oauth_callback(
    request: Request,
    code: str = None,
    state: str = None,
    error: str = None,
):
    """Processa callback OAuth do Google e salva a integração."""
    if error or not code or not state:
        return HTMLResponse(
            _popup_html("google_oauth_error", error_key="google_denied")
        )

    state_data = _google_states.pop(state, None)
    if not state_data:
        return HTMLResponse(
            _popup_html("google_oauth_error", error_key="invalid_state")
        )

    client_id, provider = state_data

    try:
        callback_url = f"{_get_base_url()}/api/integrations/oauth/google/callback"

        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": GOOGLE_AUTH_CLIENT_ID,
                    "client_secret": GOOGLE_AUTH_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": callback_url,
                    "grant_type": "authorization_code",
                },
            )
            token_data = resp.json()

        refresh_token = token_data.get("refresh_token", "")
        access_token = token_data.get("access_token", "")

        if not refresh_token and not access_token:
            return HTMLResponse(
                _popup_html("google_oauth_error", error_key="token_exchange_failed")
            )

        db_manager = COMPONENTS.get("db_manager")
        if not db_manager:
            return HTMLResponse(_popup_html("google_oauth_error", error_key="db_error"))

        key_cid, key_secret, key_refresh, key_access = _GOOGLE_PROVIDER_ENV_KEYS[
            provider
        ]
        env_vars = {
            key_cid: GOOGLE_AUTH_CLIENT_ID,
            key_secret: GOOGLE_AUTH_CLIENT_SECRET,
            key_refresh: refresh_token,
            key_access: access_token,
        }

        gads_accounts: list[str] = []
        if provider == "google-ads":
            if GADS_DEVELOPER_TOKEN:
                env_vars["GADS_DEVELOPER_TOKEN"] = GADS_DEVELOPER_TOKEN
                if GADS_MANAGER_CUSTOMER_ID:
                    env_vars["GADS_LOGIN_CUSTOMER_ID"] = GADS_MANAGER_CUSTOMER_ID
                gads_accounts = await _fetch_gads_account_ids(
                    access_token, GADS_DEVELOPER_TOKEN
                )
                debug(f"[Integrations] Google Ads contas acessíveis: {gads_accounts}")
            else:
                debug(
                    "[Integrations] Aviso: GADS_DEVELOPER_TOKEN não configurado no servidor"
                )

        config = PROVIDER_CONFIGS.get(provider, PROVIDER_CONFIGS["google-drive"])
        db_manager.execute_transaction(
            lambda session: db_manager.create_mcp_integration(
                session,
                client_id=client_id,
                provider=provider,
                command=config["command"],
                args=config["args"],
                env_vars=env_vars,
            )
        )
        _clear_mcp_sessions(client_id)
        _invalidate_integrations_cache(client_id)
        extra = {"accounts": gads_accounts} if provider == "google-ads" else None
        return HTMLResponse(
            _popup_html("google_oauth_success", provider=provider, extra=extra)
        )

    except Exception as exc:
        log_error(f"[Integrations] Erro no callback Google: {exc}")
        return HTMLResponse(_popup_html("google_oauth_error", error_key="google_error"))


class GoogleConnectBody(BaseModel):
    code: str
    provider: str = "google-drive"


_GOOGLE_PROVIDER_ENV_KEYS = {
    "google-drive": (
        "GDRIVE_CLIENT_ID",
        "GDRIVE_CLIENT_SECRET",
        "GDRIVE_REFRESH_TOKEN",
        "GDRIVE_ACCESS_TOKEN",
    ),
    "google-calendar": (
        "GCALENDAR_CLIENT_ID",
        "GCALENDAR_CLIENT_SECRET",
        "GCALENDAR_REFRESH_TOKEN",
        "GCALENDAR_ACCESS_TOKEN",
    ),
    "google-tasks": (
        "GTASKS_CLIENT_ID",
        "GTASKS_CLIENT_SECRET",
        "GTASKS_REFRESH_TOKEN",
        "GTASKS_ACCESS_TOKEN",
    ),
    "google-keep": (
        "GKEEP_CLIENT_ID",
        "GKEEP_CLIENT_SECRET",
        "GKEEP_REFRESH_TOKEN",
        "GKEEP_ACCESS_TOKEN",
    ),
    "gmail": (
        "GMAIL_CLIENT_ID",
        "GMAIL_CLIENT_SECRET",
        "GMAIL_REFRESH_TOKEN",
        "GMAIL_ACCESS_TOKEN",
    ),
    "google-analytics": (
        "GA_CLIENT_ID",
        "GA_CLIENT_SECRET",
        "GA_REFRESH_TOKEN",
        "GA_ACCESS_TOKEN",
    ),
    "google-ads": (
        "GADS_CLIENT_ID",
        "GADS_CLIENT_SECRET",
        "GADS_REFRESH_TOKEN",
        "GADS_ACCESS_TOKEN",
    ),
    "youtube": (
        "YOUTUBE_CLIENT_ID",
        "YOUTUBE_CLIENT_SECRET",
        "YOUTUBE_REFRESH_TOKEN",
        "YOUTUBE_ACCESS_TOKEN",
    ),
}


@integrations_router.post("/oauth/google/connect")
async def google_oauth_connect(request: Request, body: GoogleConnectBody):
    """Troca auth code do popup Google por tokens e salva a integração."""
    if not GOOGLE_AUTH_CLIENT_ID or not GOOGLE_AUTH_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="Google OAuth não configurado")

    provider = body.provider
    if provider not in _GOOGLE_PROVIDER_ENV_KEYS:
        raise HTTPException(
            status_code=400, detail=f"Provider '{provider}' não suportado"
        )

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": GOOGLE_AUTH_CLIENT_ID,
                    "client_secret": GOOGLE_AUTH_CLIENT_SECRET,
                    "code": body.code,
                    "redirect_uri": "postmessage",
                    "grant_type": "authorization_code",
                },
            )
            token_data = resp.json()

        refresh_token = token_data.get("refresh_token", "")
        access_token = token_data.get("access_token", "")

        if not refresh_token and not access_token:
            raise HTTPException(
                status_code=400, detail="Falha ao obter tokens do Google"
            )

        key_cid, key_secret, key_refresh, key_access = _GOOGLE_PROVIDER_ENV_KEYS[
            provider
        ]
        env_vars = {
            key_cid: GOOGLE_AUTH_CLIENT_ID,
            key_secret: GOOGLE_AUTH_CLIENT_SECRET,
            key_refresh: refresh_token,
            key_access: access_token,
        }

        gads_accounts: list[str] = []
        if provider == "google-ads":
            if GADS_DEVELOPER_TOKEN:
                env_vars["GADS_DEVELOPER_TOKEN"] = GADS_DEVELOPER_TOKEN
                if GADS_MANAGER_CUSTOMER_ID:
                    env_vars["GADS_LOGIN_CUSTOMER_ID"] = GADS_MANAGER_CUSTOMER_ID
                gads_accounts = await _fetch_gads_account_ids(
                    access_token, GADS_DEVELOPER_TOKEN
                )
                debug(f"[Integrations] Google Ads contas acessíveis: {gads_accounts}")
            else:
                debug(
                    "[Integrations] Aviso: GADS_DEVELOPER_TOKEN não configurado no servidor"
                )

        config = PROVIDER_CONFIGS.get(provider, PROVIDER_CONFIGS["google-drive"])
        db_manager = COMPONENTS.get("db_manager")
        if not db_manager:
            raise HTTPException(status_code=503, detail="DB não disponível")

        db_manager.execute_transaction(
            lambda session: db_manager.create_mcp_integration(
                session,
                client_id=client_id,
                provider=provider,
                command=config["command"],
                args=config["args"],
                env_vars=env_vars,
            )
        )
        _clear_mcp_sessions(client_id)
        _invalidate_integrations_cache(client_id)
        return JSONResponse(
            {"success": True, "provider": provider, "accounts": gads_accounts}
        )

    except HTTPException:
        raise
    except Exception as exc:
        log_error(f"[Integrations] Erro no connect Google popup: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno ao conectar Google")


# ========================================================================
# OAUTH GENÉRICO — Meta, Instagram, GitHub, Notion, LinkedIn
# ========================================================================

_oauth_states: dict = {}  # state → (client_id, provider)


@integrations_router.post("/oauth/meta-ads/init")
async def meta_oauth_init(request: Request):
    if not META_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="Meta OAuth não configurado (META_CLIENT_ID ausente)",
        )
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = (client_id, "meta-ads")
    callback_url = f"{_get_base_url()}/api/integrations/oauth/meta-ads/callback"
    scopes = "ads_read,ads_management,business_management"
    auth_url = (
        f"https://www.facebook.com/v21.0/dialog/oauth"
        f"?client_id={META_CLIENT_ID}"
        f"&redirect_uri={urllib.parse.quote(callback_url, safe='')}"
        f"&response_type=code"
        f"&scope={urllib.parse.quote(scopes, safe='')}"
        f"&state={state}"
    )
    return JSONResponse({"auth_url": auth_url})


@integrations_router.get("/oauth/meta-ads/callback")
async def meta_oauth_callback(
    request: Request,
    code: str = None,
    state: str = None,
    error: str = None,
):
    if error or not code or not state:
        return HTMLResponse(_popup_html("oauth_error", "meta-ads", "meta_denied"))
    state_data = _oauth_states.pop(state, None)
    if not state_data:
        return HTMLResponse(_popup_html("oauth_error", "meta-ads", "invalid_state"))
    client_id, _ = state_data
    try:
        callback_url = f"{_get_base_url()}/api/integrations/oauth/meta-ads/callback"
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                "https://graph.facebook.com/v21.0/oauth/access_token",
                params={
                    "client_id": META_CLIENT_ID,
                    "client_secret": META_CLIENT_SECRET,
                    "redirect_uri": callback_url,
                    "code": code,
                },
            )
            short_token = r.json().get("access_token", "")
        if not short_token:
            return HTMLResponse(
                _popup_html("oauth_error", "meta-ads", "token_exchange_failed")
            )
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                "https://graph.facebook.com/v21.0/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": META_CLIENT_ID,
                    "client_secret": META_CLIENT_SECRET,
                    "fb_exchange_token": short_token,
                },
            )
            access_token = r.json().get("access_token", short_token)
        db_manager = COMPONENTS.get("db_manager")
        if not db_manager:
            return HTMLResponse(_popup_html("oauth_error", "meta-ads", "db_error"))
        cfg = PROVIDER_CONFIGS["meta-ads"]
        db_manager.execute_transaction(
            lambda session: db_manager.create_mcp_integration(
                session,
                client_id=client_id,
                provider="meta-ads",
                command=cfg["command"],
                args=cfg["args"],
                env_vars={
                    "META_ACCESS_TOKEN": access_token,
                    "META_APP_ID": META_CLIENT_ID,
                },
            )
        )
        _clear_mcp_sessions(client_id)
        _invalidate_integrations_cache(client_id)
        return HTMLResponse(_popup_html("oauth_success", "meta-ads"))
    except Exception as exc:
        log_error(f"[Integrations] Erro no callback Meta: {exc}")
        return HTMLResponse(_popup_html("oauth_error", "meta-ads", "meta_error"))


@integrations_router.post("/oauth/instagram/init")
async def instagram_oauth_init(request: Request):
    if not META_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="Meta OAuth não configurado (META_CLIENT_ID ausente)",
        )
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = (client_id, "instagram")
    callback_url = f"{_get_base_url()}/api/integrations/oauth/instagram/callback"
    scopes = "pages_show_list,pages_read_engagement,business_management,instagram_basic,instagram_manage_insights,instagram_manage_messages"
    auth_url = (
        f"https://www.facebook.com/v21.0/dialog/oauth"
        f"?client_id={META_CLIENT_ID}"
        f"&redirect_uri={urllib.parse.quote(callback_url, safe='')}"
        f"&response_type=code"
        f"&scope={urllib.parse.quote(scopes, safe='')}"
        f"&state={state}"
    )
    return JSONResponse({"auth_url": auth_url})


@integrations_router.get("/oauth/instagram/callback")
async def instagram_oauth_callback(
    request: Request,
    code: str = None,
    state: str = None,
    error: str = None,
):
    if error or not code or not state:
        return HTMLResponse(_popup_html("oauth_error", "instagram", "meta_denied"))
    state_data = _oauth_states.pop(state, None)
    if not state_data:
        return HTMLResponse(_popup_html("oauth_error", "instagram", "invalid_state"))
    client_id, _ = state_data
    try:
        callback_url = f"{_get_base_url()}/api/integrations/oauth/instagram/callback"
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                "https://graph.facebook.com/v21.0/oauth/access_token",
                params={
                    "client_id": META_CLIENT_ID,
                    "client_secret": META_CLIENT_SECRET,
                    "redirect_uri": callback_url,
                    "code": code,
                },
            )
            short_token = r.json().get("access_token", "")
        if not short_token:
            return HTMLResponse(
                _popup_html("oauth_error", "instagram", "token_exchange_failed")
            )
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                "https://graph.facebook.com/v21.0/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": META_CLIENT_ID,
                    "client_secret": META_CLIENT_SECRET,
                    "fb_exchange_token": short_token,
                },
            )
            access_token = r.json().get("access_token", short_token)
        ig_account_id = ""
        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                r = await http.get(
                    "https://graph.facebook.com/v22.0/me/accounts",
                    params={
                        "fields": "instagram_business_account",
                        "access_token": access_token,
                    },
                )
                for page in r.json().get("data", []):
                    ig_id = page.get("instagram_business_account", {}).get("id", "")
                    if ig_id:
                        ig_account_id = ig_id
                        break
        except Exception:
            pass
        db_manager = COMPONENTS.get("db_manager")
        if not db_manager:
            return HTMLResponse(_popup_html("oauth_error", "instagram", "db_error"))
        cfg = PROVIDER_CONFIGS.get("instagram", PROVIDER_CONFIGS["meta-ads"])
        db_manager.execute_transaction(
            lambda session: db_manager.create_mcp_integration(
                session,
                client_id=client_id,
                provider="instagram",
                command=cfg["command"],
                args=cfg["args"],
                env_vars={
                    "INSTAGRAM_ACCESS_TOKEN": access_token,
                    "INSTAGRAM_BUSINESS_ACCOUNT_ID": ig_account_id,
                },
            )
        )
        _clear_mcp_sessions(client_id)
        _invalidate_integrations_cache(client_id)
        return HTMLResponse(_popup_html("oauth_success", "instagram"))
    except Exception as exc:
        log_error(f"[Integrations] Erro no callback Instagram: {exc}")
        return HTMLResponse(_popup_html("oauth_error", "instagram", "meta_error"))


@integrations_router.post("/oauth/github/init")
async def github_oauth_init(request: Request):
    if not GITHUB_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="GitHub OAuth não configurado (GITHUB_CLIENT_ID ausente)",
        )
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = (client_id, "github")
    callback_url = f"{_get_base_url()}/api/integrations/oauth/github/callback"
    auth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&redirect_uri={urllib.parse.quote(callback_url, safe='')}"
        f"&scope={urllib.parse.quote('repo read:org read:user user:email', safe='')}"
        f"&state={state}"
        f"&allow_signup=true"
    )
    return JSONResponse({"auth_url": auth_url})


@integrations_router.get("/oauth/github/callback")
async def github_oauth_callback(
    request: Request,
    code: str = None,
    state: str = None,
    error: str = None,
):
    if error or not code or not state:
        return HTMLResponse(_popup_html("oauth_error", "github", "github_denied"))
    state_data = _oauth_states.pop(state, None)
    if not state_data:
        return HTMLResponse(_popup_html("oauth_error", "github", "invalid_state"))
    client_id, _ = state_data
    try:
        callback_url = f"{_get_base_url()}/api/integrations/oauth/github/callback"
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": GITHUB_CLIENT_ID,
                    "client_secret": GITHUB_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": callback_url,
                },
            )
            access_token = r.json().get("access_token", "")
        if not access_token:
            return HTMLResponse(
                _popup_html("oauth_error", "github", "token_exchange_failed")
            )
        db_manager = COMPONENTS.get("db_manager")
        if not db_manager:
            return HTMLResponse(_popup_html("oauth_error", "github", "db_error"))
        cfg = PROVIDER_CONFIGS["github"]
        db_manager.execute_transaction(
            lambda session: db_manager.create_mcp_integration(
                session,
                client_id=client_id,
                provider="github",
                command=cfg["command"],
                args=cfg["args"],
                env_vars={"GITHUB_PERSONAL_ACCESS_TOKEN": access_token},
            )
        )
        _clear_mcp_sessions(client_id)
        _invalidate_integrations_cache(client_id)
        return HTMLResponse(_popup_html("oauth_success", "github"))
    except Exception as exc:
        log_error(f"[Integrations] Erro no callback GitHub: {exc}")
        return HTMLResponse(_popup_html("oauth_error", "github", "github_error"))


@integrations_router.post("/oauth/notion/init")
async def notion_oauth_init(request: Request):
    if not NOTION_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="Notion OAuth não configurado (NOTION_CLIENT_ID ausente)",
        )
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = (client_id, "notion")
    callback_url = f"{_get_base_url()}/api/integrations/oauth/notion/callback"
    auth_url = (
        f"https://api.notion.com/v1/oauth/authorize"
        f"?client_id={NOTION_CLIENT_ID}"
        f"&redirect_uri={urllib.parse.quote(callback_url, safe='')}"
        f"&response_type=code"
        f"&owner=user"
        f"&state={state}"
    )
    return JSONResponse({"auth_url": auth_url})


@integrations_router.get("/oauth/notion/callback")
async def notion_oauth_callback(
    request: Request,
    code: str = None,
    state: str = None,
    error: str = None,
):
    if error or not code or not state:
        return HTMLResponse(_popup_html("oauth_error", "notion", "notion_denied"))
    state_data = _oauth_states.pop(state, None)
    if not state_data:
        return HTMLResponse(_popup_html("oauth_error", "notion", "invalid_state"))
    client_id, _ = state_data
    try:
        import base64

        callback_url = f"{_get_base_url()}/api/integrations/oauth/notion/callback"
        credentials = base64.b64encode(
            f"{NOTION_CLIENT_ID}:{NOTION_CLIENT_SECRET}".encode()
        ).decode()
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                "https://api.notion.com/v1/oauth/token",
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/json",
                },
                json={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": callback_url,
                },
            )
            access_token = r.json().get("access_token", "")
        if not access_token:
            return HTMLResponse(
                _popup_html("oauth_error", "notion", "token_exchange_failed")
            )
        db_manager = COMPONENTS.get("db_manager")
        if not db_manager:
            return HTMLResponse(_popup_html("oauth_error", "notion", "db_error"))
        cfg = PROVIDER_CONFIGS["notion"]
        env_vars = {
            "OPENAPI_MCP_HEADERS": json.dumps(
                {
                    "Authorization": f"Bearer {access_token}",
                    "Notion-Version": "2022-06-28",
                }
            )
        }
        db_manager.execute_transaction(
            lambda session: db_manager.create_mcp_integration(
                session,
                client_id=client_id,
                provider="notion",
                command=cfg["command"],
                args=cfg["args"],
                env_vars=env_vars,
            )
        )
        _clear_mcp_sessions(client_id)
        _invalidate_integrations_cache(client_id)
        return HTMLResponse(_popup_html("oauth_success", "notion"))
    except Exception as exc:
        log_error(f"[Integrations] Erro no callback Notion: {exc}")
        return HTMLResponse(_popup_html("oauth_error", "notion", "notion_error"))


@integrations_router.post("/oauth/linkedin/init")
async def linkedin_oauth_init(request: Request):
    if not LINKEDIN_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="LinkedIn OAuth não configurado (LINKEDIN_CLIENT_ID ausente)",
        )
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = (client_id, "linkedin")
    callback_url = f"{_get_base_url()}/api/integrations/oauth/linkedin/callback"
    scopes = "openid profile email w_member_social r_organization_social rw_organization_admin r_ads r_ads_reporting"
    auth_url = (
        f"https://www.linkedin.com/oauth/v2/authorization"
        f"?response_type=code"
        f"&client_id={LINKEDIN_CLIENT_ID}"
        f"&redirect_uri={urllib.parse.quote(callback_url, safe='')}"
        f"&scope={urllib.parse.quote(scopes, safe='')}"
        f"&state={state}"
    )
    return JSONResponse({"auth_url": auth_url})


@integrations_router.get("/oauth/linkedin/callback")
async def linkedin_oauth_callback(
    request: Request,
    code: str = None,
    state: str = None,
    error: str = None,
):
    if error or not code or not state:
        return HTMLResponse(_popup_html("oauth_error", "linkedin", "linkedin_denied"))
    state_data = _oauth_states.pop(state, None)
    if not state_data:
        return HTMLResponse(_popup_html("oauth_error", "linkedin", "invalid_state"))
    client_id, _ = state_data
    try:
        callback_url = f"{_get_base_url()}/api/integrations/oauth/linkedin/callback"
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                "https://www.linkedin.com/oauth/v2/accessToken",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": LINKEDIN_CLIENT_ID,
                    "client_secret": LINKEDIN_CLIENT_SECRET,
                    "redirect_uri": callback_url,
                },
            )
            token_data = r.json()
            access_token = token_data.get("access_token", "")
        if not access_token:
            return HTMLResponse(
                _popup_html("oauth_error", "linkedin", "token_exchange_failed")
            )
        # Fetch person URN to enable post creation without extra API calls
        person_urn = ""
        try:
            async with httpx.AsyncClient(timeout=10.0) as http2:
                ui = await http2.get(
                    "https://api.linkedin.com/v2/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                person_urn = ui.json().get("sub", "")
        except Exception:
            pass
        db_manager = COMPONENTS.get("db_manager")
        if not db_manager:
            return HTMLResponse(_popup_html("oauth_error", "linkedin", "db_error"))
        cfg = PROVIDER_CONFIGS["linkedin"]
        env_vars: dict = {"LINKEDIN_ACCESS_TOKEN": access_token}
        if person_urn:
            env_vars["LINKEDIN_PERSON_URN"] = person_urn
        db_manager.execute_transaction(
            lambda session: db_manager.create_mcp_integration(
                session,
                client_id=client_id,
                provider="linkedin",
                command=cfg["command"],
                args=cfg["args"],
                env_vars=env_vars,
            )
        )
        _clear_mcp_sessions(client_id)
        _invalidate_integrations_cache(client_id)
        return HTMLResponse(_popup_html("oauth_success", "linkedin"))
    except Exception as exc:
        log_error(f"[Integrations] Erro no callback LinkedIn: {exc}")
        return HTMLResponse(_popup_html("oauth_error", "linkedin", "linkedin_error"))


class GoogleAdsSetupBody(BaseModel):
    customer_id: str


@integrations_router.patch("/google-ads/setup")
async def setup_google_ads(body: GoogleAdsSetupBody, request: Request):
    """Saves the user-selected GADS_CUSTOMER_ID after OAuth."""
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))
    customer_id = body.customer_id.replace("-", "").strip()
    if not customer_id:
        raise HTTPException(status_code=400, detail="customer_id inválido")

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=503, detail="DB indisponível")

    ok = db_manager.execute_transaction(
        lambda session: db_manager.patch_mcp_integration_env_vars(
            session,
            client_id=client_id,
            provider="google-ads",
            patch={"GADS_CUSTOMER_ID": customer_id},
        )
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="Integração Google Ads não encontrada. Conecte primeiro.",
        )
    _clear_mcp_sessions(client_id)
    _invalidate_integrations_cache(client_id)
    return {"success": True}


@integrations_router.get("/google-ads/accounts")
async def list_google_ads_accounts(request: Request):
    """Lists all Google Ads customer accounts accessible with the stored token, including names."""
    from App.Core.Cache.RedisCache import cache_get, cache_set

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    _key = f"gads_accounts:{client_id}"
    _cached = cache_get(_key)
    if _cached is not None:
        return _cached

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=503, detail="DB indisponível")

    configs = db_manager.execute_transaction(
        lambda session: db_manager.get_mcp_configs(session, client_id)
    )
    config = next((c for c in configs if c["provider"] == "google-ads"), None)
    if not config:
        raise HTTPException(
            status_code=404, detail="Integração Google Ads não encontrada."
        )

    env = config.get("env", {})
    access_token = env.get("GADS_ACCESS_TOKEN", "")
    developer_token = env.get("GADS_DEVELOPER_TOKEN", "") or GADS_DEVELOPER_TOKEN
    login_customer_id = (
        env.get("GADS_LOGIN_CUSTOMER_ID", "") or GADS_MANAGER_CUSTOMER_ID
    )
    if not access_token or not developer_token:
        raise HTTPException(status_code=400, detail="Token Google Ads não configurado.")

    base_headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": developer_token,
    }
    if login_customer_id:
        base_headers["login-customer-id"] = login_customer_id.replace("-", "")

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            # Step 1: list all accessible customer IDs
            list_resp = await http.get(
                "https://googleads.googleapis.com/v21/customers:listAccessibleCustomers",
                headers=base_headers,
            )
            if list_resp.status_code != 200:
                log_error(
                    f"[Google Ads] listAccessibleCustomers {list_resp.status_code}: {list_resp.text[:400]}"
                )
                raise HTTPException(
                    status_code=list_resp.status_code,
                    detail=f"Erro ao listar contas Google Ads: {list_resp.text[:200]}",
                )
            resource_names = list_resp.json().get("resourceNames", [])
            customer_ids = [rn.split("/")[-1] for rn in resource_names]

            # Step 2: fetch descriptive name for each customer in parallel
            async def _fetch_name(cid: str) -> dict:
                try:
                    h = {**base_headers, "login-customer-id": cid}
                    r = await http.post(
                        f"https://googleads.googleapis.com/v21/customers/{cid}/googleAds:search",
                        headers=h,
                        json={
                            "query": "SELECT customer.id, customer.descriptive_name, customer.status, customer.manager FROM customer LIMIT 1"
                        },
                    )
                    if r.status_code == 200:
                        rows = r.json().get("results", [])
                        if rows:
                            c = rows[0].get("customer", {})
                            return {
                                "id": cid,
                                "customer_id": cid,
                                "name": c.get("descriptiveName", ""),
                                "status": c.get("status", ""),
                                "is_manager": c.get("manager", False),
                            }
                except Exception:
                    pass
                return {
                    "id": cid,
                    "customer_id": cid,
                    "name": "",
                    "status": "",
                    "is_manager": False,
                }

            accounts = await asyncio.gather(*[_fetch_name(cid) for cid in customer_ids])
            result = {"accounts": list(accounts)}
            cache_set(_key, result, 300)
            return result
    except HTTPException:
        raise
    except Exception as exc:
        log_error(f"[Google Ads] list_accounts erro: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@integrations_router.get("/meta-ads/accounts")
async def list_meta_ads_accounts(request: Request):
    """Lists all Meta Ads accounts accessible with the stored token."""
    from App.Core.Cache.RedisCache import cache_get, cache_set

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    _key = f"meta_accounts:{client_id}"
    _cached = cache_get(_key)
    if _cached is not None:
        return _cached

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=503, detail="DB indisponível")

    configs = db_manager.execute_transaction(
        lambda session: db_manager.get_mcp_configs(session, client_id)
    )
    config = next((c for c in configs if c["provider"] == "meta-ads"), None)
    if not config:
        raise HTTPException(
            status_code=404, detail="Integração Meta Ads não encontrada."
        )

    env = config.get("env", {})
    access_token = env.get("META_ACCESS_TOKEN", "")
    if not access_token:
        raise HTTPException(status_code=400, detail="Token Meta Ads não configurado.")

    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get(
                "https://graph.facebook.com/v21.0/me/adaccounts",
                params={
                    "access_token": access_token,
                    "fields": "id,name,account_id,account_status,currency",
                    "limit": 50,
                },
            )
            data = resp.json()
            if "error" in data:
                err = data["error"]
                raise HTTPException(
                    status_code=400, detail=err.get("message", str(err))
                )
            accounts = [
                {
                    "id": a["id"],
                    "account_id": a.get("account_id", ""),
                    "name": a.get("name", ""),
                    "status": a.get("account_status", 1),
                    "currency": a.get("currency", ""),
                }
                for a in data.get("data", [])
            ]
            result = {"accounts": accounts}
            cache_set(_key, result, 300)
            return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@integrations_router.get("/meta-ads/insights")
async def get_meta_ads_insights(request: Request, days: int = 30):
    """Retorna métricas agregadas de Meta Ads: impressões, alcance, engajamento, cliques."""
    from App.Core.Cache.RedisCache import cache_get, cache_set

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    _key = f"meta_insights2:{client_id}:{days}"
    _cached = cache_get(_key)
    if _cached is not None:
        return _cached

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=503, detail="DB indisponível")

    configs = db_manager.execute_transaction(
        lambda session: db_manager.get_mcp_configs(session, client_id)
    )
    config = next((c for c in configs if c["provider"] == "meta-ads"), None)
    if not config:
        raise HTTPException(
            status_code=404, detail="Integração Meta Ads não encontrada."
        )

    env = config.get("env", {})
    access_token = env.get("META_ACCESS_TOKEN", "")
    account_id = env.get("META_AD_ACCOUNT_ID", "")
    if not access_token or not account_id:
        return {
            "impressions": 0,
            "reach": 0,
            "engagement": 0,
            "clicks": 0,
            "days": days,
            "configured": False,
        }

    if not account_id.startswith("act_"):
        account_id = f"act_{account_id}"

    from datetime import date, timedelta

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.get(
                f"https://graph.facebook.com/v21.0/{account_id}/insights",
                params={
                    "access_token": access_token,
                    "fields": "impressions,reach,clicks,spend,actions",
                    "time_range": json.dumps(
                        {"since": str(start_date), "until": str(end_date)}
                    ),
                },
            )
            data = resp.json()
            if "error" in data:
                raise HTTPException(
                    status_code=400,
                    detail=data["error"].get("message", str(data["error"])),
                )

            row = (data.get("data") or [{}])[0]
            engagement = 0
            for action in row.get("actions") or []:
                if action.get("action_type") in (
                    "post_engagement",
                    "page_engagement",
                    "video_view",
                ):
                    engagement += int(action.get("value", 0))

            result = {
                "impressions": int(row.get("impressions", 0)),
                "reach": int(row.get("reach", 0)),
                "engagement": engagement,
                "clicks": int(row.get("clicks", 0)),
                "spend": float(row.get("spend", 0)),
                "days": days,
            }
            cache_set(_key, result, 300)
            return result
    except HTTPException:
        raise
    except Exception as exc:
        log_error(f"[Meta Insights] Erro: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


class MetaAdsSetupBody(BaseModel):
    account_id: str  # numeric or "act_XXX" format


@integrations_router.patch("/meta-ads/setup")
async def setup_meta_ads(body: MetaAdsSetupBody, request: Request):
    """Saves the user-selected META_AD_ACCOUNT_ID after connecting Meta Ads."""
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))
    account_id = body.account_id.strip()
    if not account_id:
        raise HTTPException(status_code=400, detail="account_id inválido")

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=503, detail="DB indisponível")

    ok = db_manager.execute_transaction(
        lambda session: db_manager.patch_mcp_integration_env_vars(
            session,
            client_id=client_id,
            provider="meta-ads",
            patch={"META_AD_ACCOUNT_ID": account_id},
        )
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="Integração Meta Ads não encontrada. Conecte primeiro.",
        )
    return {"success": True}


@integrations_router.get("/meta-ads/campaigns")
async def list_meta_ads_campaigns(request: Request):
    """Returns Meta Ads campaigns with their ad sets for the configured account."""
    from App.Core.Cache.RedisCache import cache_get, cache_set

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    _key = f"meta_campaigns:{client_id}"
    _cached = cache_get(_key)
    if _cached is not None:
        return _cached

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=503, detail="DB indisponível")

    configs = db_manager.execute_transaction(
        lambda session: db_manager.get_mcp_configs(session, client_id)
    )
    config = next((c for c in configs if c["provider"] == "meta-ads"), None)
    if not config:
        raise HTTPException(
            status_code=404, detail="Integração Meta Ads não encontrada."
        )

    env = config.get("env", {})
    access_token = env.get("META_ACCESS_TOKEN", "")
    account_id = env.get("META_AD_ACCOUNT_ID", "")
    if not access_token or not account_id:
        raise HTTPException(
            status_code=400,
            detail="Meta Ads não configurado. Selecione uma conta primeiro.",
        )

    if not account_id.startswith("act_"):
        account_id = f"act_{account_id}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.get(
                f"https://graph.facebook.com/v21.0/{account_id}/campaigns",
                params={
                    "access_token": access_token,
                    "fields": "id,name,status,effective_status,objective",
                    "filtering": json.dumps(
                        [
                            {
                                "field": "effective_status",
                                "operator": "IN",
                                "value": ["ACTIVE", "PAUSED"],
                            }
                        ]
                    ),
                    "limit": 100,
                },
            )
            data = resp.json()
            if "error" in data:
                raise HTTPException(
                    status_code=400,
                    detail=data["error"].get("message", str(data["error"])),
                )

            campaigns_raw = data.get("data", [])

            async def _fetch_adsets(campaign_id: str) -> list:
                try:
                    r = await http.get(
                        f"https://graph.facebook.com/v21.0/{campaign_id}/adsets",
                        params={
                            "access_token": access_token,
                            "fields": "id,name,status,effective_status",
                            "filtering": json.dumps(
                                [
                                    {
                                        "field": "effective_status",
                                        "operator": "IN",
                                        "value": ["ACTIVE", "PAUSED"],
                                    }
                                ]
                            ),
                            "limit": 50,
                        },
                    )
                    d = r.json()
                    return [
                        {
                            "id": s["id"],
                            "name": s.get("name", ""),
                            "status": s.get("effective_status", s.get("status", "")),
                        }
                        for s in d.get("data", [])
                    ]
                except Exception:
                    return []

            adsets_lists = await asyncio.gather(
                *[_fetch_adsets(c["id"]) for c in campaigns_raw]
            )

            campaigns = [
                {
                    "id": c["id"],
                    "name": c.get("name", ""),
                    "status": c.get("effective_status", c.get("status", "")),
                    "objective": c.get("objective", ""),
                    "adsets": adsets_lists[i],
                }
                for i, c in enumerate(campaigns_raw)
            ]

            result = {"campaigns": campaigns, "channel": "meta-ads"}
            cache_set(_key, result, 120)
            return result
    except HTTPException:
        raise
    except Exception as exc:
        log_error(f"[Meta Ads] list_campaigns erro: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@integrations_router.get("/google-ads/campaigns")
async def list_google_ads_campaigns(request: Request):
    """Returns Google Ads campaigns for the configured customer account."""
    from App.Core.Cache.RedisCache import cache_get, cache_set

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    _key = f"gads_campaigns:{client_id}"
    _cached = cache_get(_key)
    if _cached is not None:
        return _cached

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=503, detail="DB indisponível")

    configs = db_manager.execute_transaction(
        lambda session: db_manager.get_mcp_configs(session, client_id)
    )
    config = next((c for c in configs if c["provider"] == "google-ads"), None)
    if not config:
        raise HTTPException(
            status_code=404, detail="Integração Google Ads não encontrada."
        )

    env = config.get("env", {})
    access_token = env.get("GADS_ACCESS_TOKEN", "")
    developer_token = env.get("GADS_DEVELOPER_TOKEN", "") or GADS_DEVELOPER_TOKEN
    customer_id = env.get("GADS_CUSTOMER_ID", "").replace("-", "")
    login_customer_id = (
        env.get("GADS_LOGIN_CUSTOMER_ID", "") or GADS_MANAGER_CUSTOMER_ID
    )

    if not access_token or not developer_token:
        raise HTTPException(status_code=400, detail="Google Ads não configurado.")
    if not customer_id:
        raise HTTPException(
            status_code=400, detail="Selecione uma conta Google Ads primeiro."
        )

    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": developer_token,
    }
    if login_customer_id:
        headers["login-customer-id"] = login_customer_id.replace("-", "")

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.post(
                f"https://googleads.googleapis.com/v21/customers/{customer_id}/googleAds:search",
                headers=headers,
                json={
                    "query": (
                        "SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type "
                        "FROM campaign "
                        "WHERE campaign.status IN ('ENABLED', 'PAUSED') "
                        "ORDER BY campaign.name LIMIT 100"
                    )
                },
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=resp.status_code, detail=resp.text[:300]
                )

            rows = resp.json().get("results", [])
            campaigns = [
                {
                    "id": str(r["campaign"]["id"]),
                    "name": r["campaign"].get("name", ""),
                    "status": r["campaign"].get("status", ""),
                    "channel_type": r["campaign"].get("advertisingChannelType", ""),
                }
                for r in rows
            ]

            result = {"campaigns": campaigns, "channel": "google-ads"}
            cache_set(_key, result, 120)
            return result
    except HTTPException:
        raise
    except Exception as exc:
        log_error(f"[Google Ads] list_campaigns erro: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@integrations_router.get("/instagram/accounts")
async def list_instagram_accounts(request: Request):
    """Lists Instagram Business Accounts connected to the user's Facebook Pages."""
    from App.Core.Cache.RedisCache import cache_get, cache_set

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    _key = f"ig_accounts:{client_id}"
    _cached = cache_get(_key)
    if _cached is not None:
        return _cached

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=503, detail="DB indisponível")

    configs = db_manager.execute_transaction(
        lambda session: db_manager.get_mcp_configs(session, client_id)
    )
    config = next((c for c in configs if c["provider"] == "instagram"), None)
    if not config:
        raise HTTPException(
            status_code=404, detail="Integração Instagram não encontrada."
        )

    access_token = config.get("env", {}).get("INSTAGRAM_ACCESS_TOKEN", "")
    if not access_token:
        raise HTTPException(status_code=400, detail="Token Instagram não configurado.")

    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get(
                "https://graph.facebook.com/v22.0/me/accounts",
                params={
                    "access_token": access_token,
                    "fields": "id,name,instagram_business_account{id,name,username,followers_count,profile_picture_url}",
                    "limit": 50,
                },
            )
            data = resp.json()
            if "error" in data:
                raise HTTPException(
                    status_code=400,
                    detail=data["error"].get("message", str(data["error"])),
                )

            accounts = []
            for page in data.get("data", []):
                ig = page.get("instagram_business_account")
                if ig:
                    accounts.append(
                        {
                            "id": ig["id"],
                            "username": ig.get("username", ""),
                            "name": ig.get("name", page.get("name", "")),
                            "followers_count": ig.get("followers_count", 0),
                            "profile_picture_url": ig.get("profile_picture_url", ""),
                            "page_name": page.get("name", ""),
                        }
                    )

            result = {"accounts": accounts}
            cache_set(_key, result, 300)
            return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@integrations_router.get("/google-ads/insights")
async def get_google_ads_insights(request: Request, days: int = 30):
    """Retorna métricas agregadas de Google Ads: impressões, cliques, interações."""
    from App.Core.Cache.RedisCache import cache_get, cache_set

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    _key = f"gads_insights2:{client_id}:{days}"
    _cached = cache_get(_key)
    if _cached is not None:
        return _cached

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=503, detail="DB indisponível")

    configs = db_manager.execute_transaction(
        lambda session: db_manager.get_mcp_configs(session, client_id)
    )
    config = next((c for c in configs if c["provider"] == "google-ads"), None)
    if not config:
        raise HTTPException(
            status_code=404, detail="Integração Google Ads não encontrada."
        )

    env = config.get("env", {})
    access_token = env.get("GADS_ACCESS_TOKEN", "")
    customer_id = env.get("GADS_CUSTOMER_ID", "").replace("-", "")
    developer_token = env.get("GADS_DEVELOPER_TOKEN", "") or GADS_DEVELOPER_TOKEN
    login_customer_id = (
        env.get("GADS_LOGIN_CUSTOMER_ID", "") or GADS_MANAGER_CUSTOMER_ID
    )

    if not access_token or not customer_id or not developer_token:
        return {
            "impressions": 0,
            "clicks": 0,
            "interactions": 0,
            "days": days,
            "configured": False,
        }

    from datetime import date, timedelta

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    gaql = (
        f"SELECT metrics.impressions, metrics.clicks, metrics.interactions, metrics.cost_micros "
        f"FROM customer "
        f"WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'"
    )

    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": developer_token,
        "Content-Type": "application/json",
    }
    if login_customer_id:
        headers["login-customer-id"] = login_customer_id.replace("-", "")

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.post(
                f"https://googleads.googleapis.com/v21/customers/{customer_id}/googleAds:search",
                headers=headers,
                json={"query": gaql},
            )
            if resp.status_code == 403:
                log_error(
                    f"[Google Ads Insights] 403 PERMISSION_DENIED — developer token sem acesso Standard: {resp.text[:200]}"
                )
                return {
                    "impressions": 0,
                    "clicks": 0,
                    "interactions": 0,
                    "days": days,
                    "configured": True,
                    "permission_denied": True,
                }
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=resp.status_code, detail=resp.text[:300]
                )
            data = resp.json()

        impressions = 0
        clicks = 0
        interactions = 0
        spend = 0.0
        for row in data.get("results") or []:
            m = row.get("metrics", {})
            impressions += int(m.get("impressions", 0))
            clicks += int(m.get("clicks", 0))
            interactions += int(m.get("interactions", 0))
            spend += int(m.get("costMicros", 0)) / 1_000_000

        result = {
            "impressions": impressions,
            "clicks": clicks,
            "interactions": interactions,
            "spend": round(spend, 2),
            "days": days,
        }
        cache_set(_key, result, 300)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        log_error(f"[Google Ads Insights] Erro: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@integrations_router.get("/instagram/insights")
async def get_instagram_insights(request: Request, days: int = 30):
    """Retorna métricas orgânicas do Instagram: impressões, alcance, engajamento."""
    from App.Core.Cache.RedisCache import cache_get, cache_set

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    _key = f"ig_insights:{client_id}:{days}"
    _cached = cache_get(_key)
    if _cached is not None:
        return _cached

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=503, detail="DB indisponível")

    configs = db_manager.execute_transaction(
        lambda session: db_manager.get_mcp_configs(session, client_id)
    )
    config = next((c for c in configs if c["provider"] == "instagram"), None)
    if not config:
        raise HTTPException(
            status_code=404, detail="Integração Instagram não encontrada."
        )

    env = config.get("env", {})
    access_token = env.get("INSTAGRAM_ACCESS_TOKEN", "")
    ig_account_id = env.get("INSTAGRAM_BUSINESS_ACCOUNT_ID", "")
    if not access_token or not ig_account_id:
        return {
            "impressions": 0,
            "reach": 0,
            "engagement": 0,
            "days": days,
            "configured": False,
        }

    from datetime import date, timedelta

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.get(
                f"https://graph.facebook.com/v21.0/{ig_account_id}/insights",
                params={
                    "access_token": access_token,
                    "metric": "impressions,reach,total_interactions",
                    "period": "day",
                    "since": str(start_date),
                    "until": str(end_date),
                },
            )
            data = resp.json()
            if "error" in data:
                log_error(f"[Instagram Insights] API error: {data['error']}")
                return {
                    "impressions": 0,
                    "reach": 0,
                    "engagement": 0,
                    "days": days,
                    "configured": True,
                    "error": True,
                }

            metric_totals: dict = {}
            for metric_data in data.get("data", []):
                name = metric_data.get("name", "")
                total = sum(v.get("value", 0) for v in metric_data.get("values", []))
                metric_totals[name] = total

            result = {
                "impressions": metric_totals.get("impressions", 0),
                "reach": metric_totals.get("reach", 0),
                "engagement": metric_totals.get("total_interactions", 0),
                "days": days,
            }
            cache_set(_key, result, 300)
            return result
    except HTTPException:
        raise
    except Exception as exc:
        log_error(f"[Instagram Insights] Erro: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@integrations_router.get("/linkedin/insights")
async def get_linkedin_insights(request: Request, days: int = 30):
    """Retorna métricas orgânicas do LinkedIn: impressões, cliques, engajamento."""
    from App.Core.Cache.RedisCache import cache_get, cache_set

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    _key = f"li_insights:{client_id}:{days}"
    _cached = cache_get(_key)
    if _cached is not None:
        return _cached

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=503, detail="DB indisponível")

    configs = db_manager.execute_transaction(
        lambda session: db_manager.get_mcp_configs(session, client_id)
    )
    config = next((c for c in configs if c["provider"] == "linkedin"), None)
    if not config:
        raise HTTPException(
            status_code=404, detail="Integração LinkedIn não encontrada."
        )

    env = config.get("env", {})
    access_token = env.get("LINKEDIN_ACCESS_TOKEN", "")
    org_urn = env.get("LINKEDIN_ORGANIZATION_URN", "")

    if not access_token:
        return {
            "impressions": 0,
            "clicks": 0,
            "engagement": 0,
            "days": days,
            "configured": False,
        }

    from datetime import date, timedelta, datetime as dt

    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    start_ms = int(dt.combine(start_date, dt.min.time()).timestamp() * 1000)
    end_ms = int(dt.combine(end_date, dt.min.time()).timestamp() * 1000)

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "LinkedIn-Version": "202411",
                "X-Restli-Protocol-Version": "2.0.0",
            }

            if not org_urn:
                # Try to get organization from person's administered orgs
                me_resp = await http.get(
                    "https://api.linkedin.com/v2/organizationAcls?q=roleAssignee&role=ADMINISTRATOR&state=APPROVED&count=5",
                    headers=headers,
                )
                if me_resp.status_code == 200:
                    orgs = me_resp.json().get("elements", [])
                    if orgs:
                        org_urn = orgs[0].get("organization", "")

            if not org_urn:
                return {
                    "impressions": 0,
                    "clicks": 0,
                    "engagement": 0,
                    "days": days,
                    "configured": True,
                    "no_org": True,
                }

            # Encode org URN for URL
            encoded_org = urllib.parse.quote(org_urn, safe="")
            stats_resp = await http.get(
                f"https://api.linkedin.com/v2/organizationalEntityShareStatistics"
                f"?q=organizationalEntity&organizationalEntity={encoded_org}"
                f"&timeIntervals.timeGranularityType=DAY"
                f"&timeIntervals.timeRange.start={start_ms}"
                f"&timeIntervals.timeRange.end={end_ms}",
                headers=headers,
            )

            impressions = 0
            clicks = 0
            engagement = 0

            if stats_resp.status_code == 200:
                for elem in stats_resp.json().get("elements", []):
                    s = elem.get("totalShareStatistics", {})
                    impressions += s.get("impressionCount", 0)
                    clicks += s.get("clickCount", 0)
                    engagement += (
                        s.get("likeCount", 0)
                        + s.get("commentCount", 0)
                        + s.get("shareCount", 0)
                    )

            result = {
                "impressions": impressions,
                "clicks": clicks,
                "engagement": engagement,
                "days": days,
            }
            cache_set(_key, result, 300)
            return result
    except HTTPException:
        raise
    except Exception as exc:
        log_error(f"[LinkedIn Insights] Erro: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@integrations_router.get("/linkedin/campaigns")
async def list_linkedin_campaigns(request: Request):
    """Returns LinkedIn Campaign Manager campaigns."""
    from App.Core.Cache.RedisCache import cache_get, cache_set

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    _key = f"li_campaigns:{client_id}"
    _cached = cache_get(_key)
    if _cached is not None:
        return _cached

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=503, detail="DB indisponível")

    configs = db_manager.execute_transaction(
        lambda session: db_manager.get_mcp_configs(session, client_id)
    )
    config = next((c for c in configs if c["provider"] == "linkedin"), None)
    if not config:
        raise HTTPException(
            status_code=404, detail="Integração LinkedIn não encontrada."
        )

    env = config.get("env", {})
    access_token = env.get("LINKEDIN_ACCESS_TOKEN", "")
    if not access_token:
        raise HTTPException(status_code=400, detail="LinkedIn não configurado.")

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "LinkedIn-Version": "202411",
                "X-Restli-Protocol-Version": "2.0.0",
            }
            resp = await http.get(
                "https://api.linkedin.com/v2/adCampaigns?q=search&search.status.values[0]=ACTIVE&search.status.values[1]=PAUSED&count=100",
                headers=headers,
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=resp.status_code, detail=resp.text[:300]
                )

            campaigns = [
                {
                    "id": str(c.get("id", "")),
                    "name": c.get("name", ""),
                    "status": c.get("status", ""),
                    "type": c.get("type", ""),
                }
                for c in resp.json().get("elements", [])
            ]
            result = {"campaigns": campaigns, "channel": "linkedin"}
            cache_set(_key, result, 120)
            return result
    except HTTPException:
        raise
    except Exception as exc:
        log_error(f"[LinkedIn Campaigns] Erro: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Helpers para insights granulares ──────────────────────────────────────────


def _load_meta_config(client_id: str) -> tuple:
    """Returns (access_token, account_id) for Meta Ads or raises HTTPException."""
    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=503, detail="DB indisponível")
    configs = db_manager.execute_transaction(
        lambda session: db_manager.get_mcp_configs(session, client_id)
    )
    config = next((c for c in configs if c["provider"] == "meta-ads"), None)
    if not config:
        raise HTTPException(
            status_code=404, detail="Integração Meta Ads não encontrada."
        )
    env = config.get("env", {})
    token = env.get("META_ACCESS_TOKEN", "")
    if not token:
        raise HTTPException(status_code=400, detail="Token Meta Ads não configurado.")
    return token, env.get("META_AD_ACCOUNT_ID", "")


async def _meta_entity_insights(entity_id: str, access_token: str, days: int) -> dict:
    """Fetch Meta Graph API insights for any entity (campaign/adset/ad)."""
    from datetime import date, timedelta

    end = date.today()
    start = end - timedelta(days=days)
    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.get(
            f"https://graph.facebook.com/v21.0/{entity_id}/insights",
            params={
                "access_token": access_token,
                "fields": "impressions,reach,clicks,spend,actions",
                "time_range": json.dumps({"since": str(start), "until": str(end)}),
            },
        )
    data = resp.json()
    if "error" in data:
        raise HTTPException(
            status_code=400, detail=data["error"].get("message", str(data["error"]))
        )
    row = (data.get("data") or [{}])[0]
    engagement = sum(
        int(a.get("value", 0))
        for a in (row.get("actions") or [])
        if a.get("action_type") in ("post_engagement", "page_engagement", "video_view")
    )
    return {
        "impressions": int(row.get("impressions", 0)),
        "reach": int(row.get("reach", 0)),
        "engagement": engagement,
        "clicks": int(row.get("clicks", 0)),
        "spend": float(row.get("spend", 0)),
        "days": days,
    }


# ── Meta Ads: insights granulares ──────────────────────────────────────────────


@integrations_router.get("/meta-ads/campaigns/{campaign_id}/insights")
async def get_meta_campaign_insights(
    campaign_id: str, request: Request, days: int = 30
):
    from App.Core.Cache.RedisCache import cache_get, cache_set

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))
    _key = f"meta_camp_ins:{client_id}:{campaign_id}:{days}"
    cached = cache_get(_key)
    if cached is not None:
        return cached
    token, _ = _load_meta_config(client_id)
    try:
        result = await _meta_entity_insights(campaign_id, token, days)
        cache_set(_key, result, 300)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@integrations_router.get("/meta-ads/adsets/{adset_id}/insights")
async def get_meta_adset_insights(adset_id: str, request: Request, days: int = 30):
    from App.Core.Cache.RedisCache import cache_get, cache_set

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))
    _key = f"meta_adset_ins:{client_id}:{adset_id}:{days}"
    cached = cache_get(_key)
    if cached is not None:
        return cached
    token, _ = _load_meta_config(client_id)
    try:
        result = await _meta_entity_insights(adset_id, token, days)
        cache_set(_key, result, 300)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@integrations_router.get("/meta-ads/adsets/{adset_id}/ads")
async def list_meta_adset_ads(adset_id: str, request: Request):
    """List ads inside a Meta Ads ad set."""
    from App.Core.Cache.RedisCache import cache_get, cache_set

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))
    _key = f"meta_adset_ads:{client_id}:{adset_id}"
    cached = cache_get(_key)
    if cached is not None:
        return cached
    token, _ = _load_meta_config(client_id)
    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.get(
                f"https://graph.facebook.com/v21.0/{adset_id}/ads",
                params={
                    "access_token": token,
                    "fields": "id,name,status,effective_status",
                    "filtering": json.dumps(
                        [
                            {
                                "field": "effective_status",
                                "operator": "IN",
                                "value": ["ACTIVE", "PAUSED"],
                            }
                        ]
                    ),
                    "limit": 50,
                },
            )
        data = resp.json()
        if "error" in data:
            raise HTTPException(
                status_code=400, detail=data["error"].get("message", str(data["error"]))
            )
        ads = [
            {
                "id": a["id"],
                "name": a.get("name", ""),
                "status": a.get("effective_status", a.get("status", "")),
            }
            for a in data.get("data", [])
        ]
        result = {"ads": ads}
        cache_set(_key, result, 120)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class MetaStatusToggleBody(BaseModel):
    entity_type: str  # "campaign" | "adset" | "ad"
    entity_id: str
    status: str  # "ACTIVE" | "PAUSED"


@integrations_router.patch("/meta-ads/status")
async def toggle_meta_ads_status(body: MetaStatusToggleBody, request: Request):
    """Alterna o status (ACTIVE/PAUSED) de campanha, conjunto de anúncios ou anúncio no Meta Ads e invalida o cache Redis."""
    from App.Core.Cache.RedisCache import cache_delete

    if body.status not in ("ACTIVE", "PAUSED"):
        raise HTTPException(status_code=400, detail="status deve ser ACTIVE ou PAUSED")
    if body.entity_type not in ("campaign", "adset", "ad"):
        raise HTTPException(
            status_code=400, detail="entity_type inválido: use campaign, adset ou ad"
        )

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))
    token, _ = _load_meta_config(client_id)

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.post(
                f"https://graph.facebook.com/v21.0/{body.entity_id}",
                data={"access_token": token, "status": body.status},
            )
        data = resp.json()
        if "error" in data:
            raise HTTPException(
                status_code=400,
                detail=data["error"].get("message", str(data["error"])),
            )

        cache_delete(f"meta_campaigns:{client_id}")
        if body.entity_type == "adset":
            cache_delete(f"meta_adset_ads:{client_id}:{body.entity_id}")

        return {"entity_id": body.entity_id, "status": body.status, "success": True}
    except HTTPException:
        raise
    except Exception as exc:
        log_error(f"[Meta Ads] toggle_status erro: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@integrations_router.get("/meta-ads/ads/{ad_id}/insights")
async def get_meta_ad_insights(ad_id: str, request: Request, days: int = 30):
    from App.Core.Cache.RedisCache import cache_get, cache_set

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))
    _key = f"meta_ad_ins:{client_id}:{ad_id}:{days}"
    cached = cache_get(_key)
    if cached is not None:
        return cached
    token, _ = _load_meta_config(client_id)
    try:
        result = await _meta_entity_insights(ad_id, token, days)
        cache_set(_key, result, 300)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Instagram: posts e insights por postagem ────────────────────────────────────


@integrations_router.get("/instagram/posts")
async def list_instagram_posts(request: Request, limit: int = 20):
    """List recent Instagram media posts."""
    from App.Core.Cache.RedisCache import cache_get, cache_set

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))
    _key = f"ig_posts:{client_id}:{limit}"
    cached = cache_get(_key)
    if cached is not None:
        return cached
    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=503, detail="DB indisponível")
    configs = db_manager.execute_transaction(
        lambda session: db_manager.get_mcp_configs(session, client_id)
    )
    config = next((c for c in configs if c["provider"] == "instagram"), None)
    if not config:
        raise HTTPException(
            status_code=404, detail="Integração Instagram não encontrada."
        )
    env = config.get("env", {})
    token = env.get("INSTAGRAM_ACCESS_TOKEN", "")
    ig_id = env.get("INSTAGRAM_BUSINESS_ACCOUNT_ID", "")
    if not token or not ig_id:
        raise HTTPException(status_code=400, detail="Instagram não configurado.")
    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.get(
                f"https://graph.facebook.com/v21.0/{ig_id}/media",
                params={
                    "access_token": token,
                    "fields": "id,caption,media_type,timestamp,like_count,comments_count,permalink",
                    "limit": limit,
                },
            )
        data = resp.json()
        if "error" in data:
            raise HTTPException(
                status_code=400, detail=data["error"].get("message", str(data["error"]))
            )
        posts = [
            {
                "id": p["id"],
                "caption": (p.get("caption") or "")[:80],
                "media_type": p.get("media_type", ""),
                "timestamp": p.get("timestamp", ""),
                "like_count": p.get("like_count", 0),
                "comments_count": p.get("comments_count", 0),
                "permalink": p.get("permalink", ""),
            }
            for p in data.get("data", [])
        ]
        result = {"posts": posts}
        cache_set(_key, result, 300)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@integrations_router.get("/instagram/posts/{media_id}/insights")
async def get_instagram_post_insights(media_id: str, request: Request):
    """Insights for a specific Instagram post."""
    from App.Core.Cache.RedisCache import cache_get, cache_set

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))
    _key = f"ig_post_ins:{client_id}:{media_id}"
    cached = cache_get(_key)
    if cached is not None:
        return cached
    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=503, detail="DB indisponível")
    configs = db_manager.execute_transaction(
        lambda session: db_manager.get_mcp_configs(session, client_id)
    )
    config = next((c for c in configs if c["provider"] == "instagram"), None)
    if not config:
        raise HTTPException(
            status_code=404, detail="Integração Instagram não encontrada."
        )
    token = config.get("env", {}).get("INSTAGRAM_ACCESS_TOKEN", "")
    if not token:
        raise HTTPException(status_code=400, detail="Instagram não configurado.")
    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.get(
                f"https://graph.facebook.com/v21.0/{media_id}/insights",
                params={
                    "access_token": token,
                    "metric": "impressions,reach,saved,total_interactions",
                },
            )
        data = resp.json()
        if "error" in data:
            # Some media types don't support all metrics — return zeros
            return {
                "impressions": 0,
                "reach": 0,
                "engagement": 0,
                "clicks": 0,
                "spend": 0,
            }
        totals = {
            m["name"]: m.get("values", [{}])[0].get("value", 0)
            for m in data.get("data", [])
        }
        result = {
            "impressions": totals.get("impressions", 0),
            "reach": totals.get("reach", 0),
            "engagement": totals.get("total_interactions", 0),
            "clicks": totals.get("saved", 0),
            "spend": 0,
        }
        cache_set(_key, result, 300)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Google Ads: insights por campanha e ad groups ───────────────────────────────


@integrations_router.get("/google-ads/campaigns/{campaign_id}/insights")
async def get_google_campaign_insights(
    campaign_id: str, request: Request, days: int = 30
):
    """Metrics for a specific Google Ads campaign."""
    from App.Core.Cache.RedisCache import cache_get, cache_set

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))
    _key = f"gads_camp_ins:{client_id}:{campaign_id}:{days}"
    cached = cache_get(_key)
    if cached is not None:
        return cached
    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=503, detail="DB indisponível")
    configs = db_manager.execute_transaction(
        lambda session: db_manager.get_mcp_configs(session, client_id)
    )
    config = next((c for c in configs if c["provider"] == "google-ads"), None)
    if not config:
        raise HTTPException(
            status_code=404, detail="Integração Google Ads não encontrada."
        )
    env = config.get("env", {})
    access_token = env.get("GADS_ACCESS_TOKEN", "")
    developer_token = env.get("GADS_DEVELOPER_TOKEN", "") or GADS_DEVELOPER_TOKEN
    customer_id = env.get("GADS_CUSTOMER_ID", "").replace("-", "")
    if not access_token or not customer_id:
        raise HTTPException(status_code=400, detail="Google Ads não configurado.")
    from datetime import date, timedelta

    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    gaql = (
        f"SELECT metrics.impressions, metrics.clicks, metrics.interactions, metrics.cost_micros "
        f"FROM campaign "
        f"WHERE campaign.id = {campaign_id} "
        f"AND segments.date BETWEEN '{start_date}' AND '{end_date}'"
    )
    try:
        async with httpx.AsyncClient(timeout=20.0) as http:
            resp = await http.post(
                f"https://googleads.googleapis.com/v21/customers/{customer_id}/googleAds:search",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "developer-token": developer_token,
                    "Content-Type": "application/json",
                },
                json={"query": gaql},
            )
        data = resp.json()
        if "error" in data:
            raise HTTPException(status_code=400, detail=str(data["error"]))
        impressions = clicks = spend = 0
        for row in data.get("results", []):
            m = row.get("metrics", {})
            impressions += int(m.get("impressions", 0))
            clicks += int(m.get("clicks", 0))
            spend += int(m.get("costMicros", 0)) / 1_000_000
        result = {
            "impressions": impressions,
            "reach": 0,
            "engagement": 0,
            "clicks": clicks,
            "spend": round(spend, 2),
            "days": days,
        }
        cache_set(_key, result, 300)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@integrations_router.get("/google-ads/adgroups")
async def list_google_adgroups(request: Request, campaign_id: str = ""):
    """List Google Ads ad groups (conjuntos de anúncios), optionally filtered by campaign."""
    from App.Core.Cache.RedisCache import cache_get, cache_set

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))
    _key = f"gads_adgroups:{client_id}:{campaign_id}"
    cached = cache_get(_key)
    if cached is not None:
        return cached
    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=503, detail="DB indisponível")
    configs = db_manager.execute_transaction(
        lambda session: db_manager.get_mcp_configs(session, client_id)
    )
    config = next((c for c in configs if c["provider"] == "google-ads"), None)
    if not config:
        raise HTTPException(
            status_code=404, detail="Integração Google Ads não encontrada."
        )
    env = config.get("env", {})
    access_token = env.get("GADS_ACCESS_TOKEN", "")
    developer_token = env.get("GADS_DEVELOPER_TOKEN", "") or GADS_DEVELOPER_TOKEN
    customer_id = env.get("GADS_CUSTOMER_ID", "").replace("-", "")
    if not access_token or not customer_id:
        raise HTTPException(status_code=400, detail="Google Ads não configurado.")
    where = f"WHERE ad_group.status IN ('ENABLED','PAUSED')"
    if campaign_id:
        where += f" AND campaign.id = {campaign_id}"
    gaql = f"SELECT ad_group.id, ad_group.name, ad_group.status, campaign.id FROM ad_group {where} LIMIT 200"
    try:
        async with httpx.AsyncClient(timeout=20.0) as http:
            resp = await http.post(
                f"https://googleads.googleapis.com/v21/customers/{customer_id}/googleAds:search",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "developer-token": developer_token,
                    "Content-Type": "application/json",
                },
                json={"query": gaql},
            )
        data = resp.json()
        if "error" in data:
            raise HTTPException(status_code=400, detail=str(data["error"]))
        adgroups = [
            {
                "id": str(r["adGroup"]["id"]),
                "name": r["adGroup"].get("name", ""),
                "status": r["adGroup"].get("status", ""),
                "campaign_id": str(r["campaign"]["id"]),
            }
            for r in data.get("results", [])
            if "adGroup" in r
        ]
        result = {"adgroups": adgroups}
        cache_set(_key, result, 120)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@integrations_router.get("/google-ads/adgroups/{adgroup_id}/insights")
async def get_google_adgroup_insights(
    adgroup_id: str, request: Request, days: int = 30
):
    """Metrics for a specific Google Ads ad group."""
    from App.Core.Cache.RedisCache import cache_get, cache_set

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))
    _key = f"gads_ag_ins:{client_id}:{adgroup_id}:{days}"
    cached = cache_get(_key)
    if cached is not None:
        return cached
    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=503, detail="DB indisponível")
    configs = db_manager.execute_transaction(
        lambda session: db_manager.get_mcp_configs(session, client_id)
    )
    config = next((c for c in configs if c["provider"] == "google-ads"), None)
    if not config:
        raise HTTPException(
            status_code=404, detail="Integração Google Ads não encontrada."
        )
    env = config.get("env", {})
    access_token = env.get("GADS_ACCESS_TOKEN", "")
    developer_token = env.get("GADS_DEVELOPER_TOKEN", "") or GADS_DEVELOPER_TOKEN
    customer_id = env.get("GADS_CUSTOMER_ID", "").replace("-", "")
    if not access_token or not customer_id:
        raise HTTPException(status_code=400, detail="Google Ads não configurado.")
    from datetime import date, timedelta

    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    gaql = (
        f"SELECT metrics.impressions, metrics.clicks, metrics.cost_micros "
        f"FROM ad_group "
        f"WHERE ad_group.id = {adgroup_id} "
        f"AND segments.date BETWEEN '{start_date}' AND '{end_date}'"
    )
    try:
        async with httpx.AsyncClient(timeout=20.0) as http:
            resp = await http.post(
                f"https://googleads.googleapis.com/v21/customers/{customer_id}/googleAds:search",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "developer-token": developer_token,
                    "Content-Type": "application/json",
                },
                json={"query": gaql},
            )
        data = resp.json()
        if "error" in data:
            raise HTTPException(status_code=400, detail=str(data["error"]))
        impressions = clicks = spend = 0
        for row in data.get("results", []):
            m = row.get("metrics", {})
            impressions += int(m.get("impressions", 0))
            clicks += int(m.get("clicks", 0))
            spend += int(m.get("costMicros", 0)) / 1_000_000
        result = {
            "impressions": impressions,
            "reach": 0,
            "engagement": 0,
            "clicks": clicks,
            "spend": round(spend, 2),
            "days": days,
        }
        cache_set(_key, result, 300)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class InstagramSetupBody(BaseModel):
    account_id: str


@integrations_router.patch("/instagram/setup")
async def setup_instagram(body: InstagramSetupBody, request: Request):
    """Saves the user-selected INSTAGRAM_BUSINESS_ACCOUNT_ID."""
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))
    account_id = body.account_id.strip()
    if not account_id:
        raise HTTPException(status_code=400, detail="account_id inválido")

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=503, detail="DB indisponível")

    ok = db_manager.execute_transaction(
        lambda session: db_manager.patch_mcp_integration_env_vars(
            session,
            client_id=client_id,
            provider="instagram",
            patch={"INSTAGRAM_BUSINESS_ACCOUNT_ID": account_id},
        )
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="Integração Instagram não encontrada. Conecte primeiro.",
        )
    return {"success": True}


# ========================================================================
# CONEXÕES POR CHAT (ativa/inativa provider MCP para um chat específico)
# ========================================================================


@integrations_router.get("/chat/{chat_id}/connections")
async def get_chat_connections(chat_id: str, request: Request):
    """Retorna a lista de providers ativos no chat (None = sem restrições)."""
    _get_auth_payload(request)
    db = DatabaseManager()
    row = db.fetch_one(
        "SELECT connections FROM chats WHERE chat_id = :cid", {"cid": chat_id}
    )
    if not row:
        raise HTTPException(status_code=404, detail="Chat não encontrado")
    raw = row.get("connections")
    return {"connections": json.loads(raw) if raw else None}


@integrations_router.post("/{integration_id}/inactivate")
async def inactivate_integration_for_chat(
    integration_id: str, body: ChatConnectionBody, request: Request
):
    """Inativa um provider MCP apenas para um chat (não desconecta globalmente)."""
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    db = DatabaseManager()

    integration = db.fetch_one(
        "SELECT provider FROM mcp_integrations WHERE integration_id = :iid AND client_id = :cid",
        {"iid": integration_id, "cid": client_id},
    )
    if not integration:
        raise HTTPException(status_code=404, detail="Integração não encontrada")
    provider = integration["provider"]

    chat = db.fetch_one(
        "SELECT connections FROM chats WHERE chat_id = :cid", {"cid": body.chat_id}
    )
    if not chat:
        raise HTTPException(status_code=404, detail="Chat não encontrado")

    raw = chat.get("connections")
    if raw:
        allowed: list = json.loads(raw)
    else:
        all_rows = db.fetch_all(
            "SELECT provider FROM mcp_integrations WHERE client_id = :cid AND is_active = 1",
            {"cid": client_id},
        )
        allowed = [r["provider"] for r in all_rows]

    if provider in allowed:
        allowed.remove(provider)

    db.execute_query(
        "UPDATE chats SET connections = :conn WHERE chat_id = :cid",
        {"conn": json.dumps(allowed), "cid": body.chat_id},
    )
    debug(f"[Integrations] Inativado '{provider}' no chat {body.chat_id}")
    return {"success": True, "connections": allowed}


@integrations_router.post("/{integration_id}/activate")
async def activate_integration_for_chat(
    integration_id: str, body: ChatConnectionBody, request: Request
):
    """Reativa um provider MCP para um chat específico."""
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    db = DatabaseManager()

    integration = db.fetch_one(
        "SELECT provider FROM mcp_integrations WHERE integration_id = :iid AND client_id = :cid",
        {"iid": integration_id, "cid": client_id},
    )
    if not integration:
        raise HTTPException(status_code=404, detail="Integração não encontrada")
    provider = integration["provider"]

    chat = db.fetch_one(
        "SELECT connections FROM chats WHERE chat_id = :cid", {"cid": body.chat_id}
    )
    if not chat:
        raise HTTPException(status_code=404, detail="Chat não encontrado")

    raw = chat.get("connections")
    if not raw:
        return {"success": True, "connections": None}

    allowed: list = json.loads(raw)
    if provider not in allowed:
        allowed.append(provider)

    all_rows = db.fetch_all(
        "SELECT provider FROM mcp_integrations WHERE client_id = :cid AND is_active = 1",
        {"cid": client_id},
    )
    all_providers = {r["provider"] for r in all_rows}

    if set(allowed) >= all_providers:
        db.execute_query(
            "UPDATE chats SET connections = NULL WHERE chat_id = :cid",
            {"cid": body.chat_id},
        )
        debug(
            f"[Integrations] Todas conexões ativas — resetando para NULL no chat {body.chat_id}"
        )
        return {"success": True, "connections": None}

    db.execute_query(
        "UPDATE chats SET connections = :conn WHERE chat_id = :cid",
        {"conn": json.dumps(allowed), "cid": body.chat_id},
    )
    debug(f"[Integrations] Ativado '{provider}' no chat {body.chat_id}")
    return {"success": True, "connections": allowed}


@integrations_router.post("/{provider}/sync")
async def sync_knowledge_provider(provider: str, request: Request):
    """
    Indexa os documentos de um provider knowledge (google-drive, notion) no banco vetorial.
    """
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))
    user_id = str(payload.get("user_id", ""))

    from App.Core.Services.VectorSearch.KnowledgeSyncService import (
        sync_provider,
        _SUPPORTED_PROVIDERS,
    )

    if provider not in _SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider}' não suporta indexação. Suportados: {list(_SUPPORTED_PROVIDERS.keys())}",
        )

    result = await sync_provider(
        client_id=client_id, user_id=user_id, provider=provider
    )
    if not result.get("success"):
        raise HTTPException(
            status_code=500, detail=result.get("error", "Erro ao sincronizar")
        )
    return result


__all__ = ["integrations_router", "webhook_secrets_router"]


# ========================================================================
# WEBHOOK SECRETS ROUTER
# ========================================================================

import secrets as _secrets
import uuid as _uuid

webhook_secrets_router = APIRouter(
    tags=["WebhookSecrets"], prefix="/api/webhook-secrets"
)


def _get_or_create_webhook_secret(client_id: str, provider: str) -> dict:
    from App.Core.Settings.Settings import get_public_url
    from sqlalchemy import text as _text
    from App.Core.Services.Webhooks.TriggerWebhook import _ensure_tables

    _ensure_tables()

    pub_url = get_public_url().rstrip("/")
    db = DatabaseManager.get_session()
    try:
        row = db.execute(
            _text(
                "SELECT web_secret_id, webhook_secret, status, prompt, autonomy_level, tools, last_received_at "
                "FROM webhook_secrets WHERE client_id = :cid AND provider = :p LIMIT 1"
            ),
            {"cid": client_id, "p": provider},
        ).fetchone()
        if row:
            data = dict(row._mapping)
        else:
            secret = _secrets.token_urlsafe(32)
            wsid = str(_uuid.uuid4())
            db.execute(
                _text(
                    "INSERT INTO webhook_secrets (web_secret_id, client_id, provider, webhook_secret) "
                    "VALUES (:wsid, :cid, :p, :s)"
                ),
                {"wsid": wsid, "cid": client_id, "p": provider, "s": secret},
            )
            db.commit()
            data = {
                "web_secret_id": wsid,
                "webhook_secret": secret,
                "status": "pending",
                "prompt": None,
                "autonomy_level": 4,
                "tools": "[]",
                "last_received_at": None,
            }
    finally:
        db.close()

    webhook_url = (
        f"{pub_url}{WEBHOOK_PREFIX}/trigger/{data['webhook_secret']}/{provider}"
    )
    return {
        "web_secret_id": data["web_secret_id"],
        "provider": provider,
        "webhook_url": webhook_url,
        "status": data["status"],
        "prompt": data.get("prompt"),
        "autonomy_level": data.get("autonomy_level", 4),
        "tools": data.get("tools", "[]"),
        "last_received_at": data.get("last_received_at"),
    }


@webhook_secrets_router.get("/{provider}")
async def get_webhook_secret(provider: str, request: Request):
    """Retorna (ou cria) o webhook_secret do cliente para o provider informado,
    com a URL completa já montada pelo backend."""
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))
    return _get_or_create_webhook_secret(client_id, provider)


@webhook_secrets_router.patch("/{provider}")
async def update_webhook_config(provider: str, request: Request):
    """Atualiza prompt, autonomy_level e/ou tools do webhook."""
    from sqlalchemy import text as _text

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))
    body = await request.json()

    allowed = {"prompt", "autonomy_level", "tools"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(400, "Nenhum campo válido para atualizar")

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["cid"] = client_id
    updates["p"] = provider

    db = DatabaseManager.get_session()
    try:
        db.execute(
            _text(
                f"UPDATE webhook_secrets SET {set_clause}, updated_at = CURRENT_TIMESTAMP "
                "WHERE client_id = :cid AND provider = :p"
            ),
            updates,
        )
        db.commit()
    finally:
        db.close()

    return _get_or_create_webhook_secret(client_id, provider)


def _ping_webhook_url(webhook_url: str) -> bool:
    """Faz um GET no webhook_url via sandbox (curl) e retorna True se acessível."""
    import os as _os
    import requests as _req

    sandbox_url = _os.environ.get("SANDBOX_URL", "").rstrip("/")
    if not sandbox_url:
        return False
    try:
        # curl -s -o /dev/null -w "%{http_code}" retorna só o status HTTP na stdout
        cmd = f'curl -s -o /dev/null -w "%{{http_code}}" --max-time 8 "{webhook_url}"'
        resp = _req.post(
            f"{sandbox_url}/execute",
            json={"command": cmd, "user_id": "health_check"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success") and data.get("exit_code", 1) != 0:
            return False
        http_code = (data.get("stdout") or "").strip()
        return http_code.isdigit() and int(http_code) < 500
    except Exception as e:
        debug(f"[WebhookHealth] ping via sandbox falhou: {e}")
        return False


@webhook_secrets_router.get("/{provider}/health")
async def get_webhook_health(provider: str, request: Request):
    """Verifica saúde do webhook: lê DB + faz ping real via sandbox."""
    from sqlalchemy import text as _text
    from datetime import timezone
    from App.Core.Settings.Settings import get_public_url

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    db = DatabaseManager.get_session()
    try:
        row = db.execute(
            _text(
                "SELECT webhook_secret, status, last_received_at FROM webhook_secrets "
                "WHERE client_id = :cid AND provider = :p LIMIT 1"
            ),
            {"cid": client_id, "p": provider},
        ).fetchone()
    finally:
        db.close()

    if not row:
        return {
            "status": "pending",
            "last_received_at": None,
            "health": "pending",
            "reachable": False,
        }

    data = dict(row._mapping)
    status = data.get("status") or "pending"
    last_received_at = data.get("last_received_at")
    webhook_secret = data.get("webhook_secret", "")

    # Ping real via sandbox (bloqueante → thread para não travar o event loop)
    import asyncio as _asyncio

    pub_url = get_public_url().rstrip("/")
    ping_url = f"{pub_url}{WEBHOOK_PREFIX}/trigger/{webhook_secret}/{provider}"
    reachable = await _asyncio.to_thread(_ping_webhook_url, ping_url)

    if status == "connected" and last_received_at:
        try:
            from datetime import datetime as _dt

            if isinstance(last_received_at, str):
                ts = _dt.fromisoformat(last_received_at.replace("Z", "+00:00"))
            else:
                ts = last_received_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_hours = (_dt.now(timezone.utc) - ts).total_seconds() / 3600
            health = "healthy" if age_hours < 24 else "degraded"
        except Exception:
            health = "healthy"
    elif status == "lost":
        health = "degraded"
    elif reachable:
        health = "reachable"
    else:
        health = "pending"

    return {
        "status": status,
        "last_received_at": last_received_at,
        "health": health,
        "reachable": reachable,
    }


@webhook_secrets_router.post("/{provider}/rotate")
async def rotate_webhook_secret(provider: str, request: Request):
    """Gera um novo webhook_secret, invalidando o anterior."""
    from sqlalchemy import text as _text
    from App.Core.Settings.Settings import get_public_url

    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    new_secret = _secrets.token_urlsafe(32)
    pub_url = get_public_url().rstrip("/")

    db = DatabaseManager.get_session()
    try:
        db.execute(
            _text(
                "UPDATE webhook_secrets SET webhook_secret = :s, status = 'pending', "
                "updated_at = CURRENT_TIMESTAMP WHERE client_id = :cid AND provider = :p"
            ),
            {"s": new_secret, "cid": client_id, "p": provider},
        )
        db.commit()
    finally:
        db.close()

    return {
        "webhook_url": f"{pub_url}{WEBHOOK_PREFIX}/trigger/{new_secret}/{provider}",
        "status": "pending",
    }
