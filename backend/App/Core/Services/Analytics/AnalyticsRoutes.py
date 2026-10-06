"""
Rotas de Analytics — /api/analytics

Dependências de autorização centralizadas:
  require_client      → resolve client_id do user autenticado.
  require_analytics_site → resolve (client_id, config), levanta 404 se não configurado.

Rotas que apenas precisam saber quem é o user usam require_client.
Rotas que operam sobre dados do site usam require_analytics_site.
Setup é a exceção: precisa de user_id para a transação de upsert.
"""

from typing import Annotated, Optional
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
import uuid
import httpx
import os

from sqlalchemy import text

from App.Core.Logs import error as log_error
from App.Features.Auth import get_auth_service
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager

analytics_router = APIRouter(tags=["Analytics"], prefix="/api/analytics")

ANALYTICS_INTERNAL_URL = os.environ.get(
    "ANALYTICS_INTERNAL_URL", "http://analytics:3001"
)
INTERNAL_KEY = os.environ.get("ANALYTICS_INTERNAL_KEY", "")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8081")
BROWSER_SERVICE_URL = os.environ.get("BROWSER_SERVICE_URL", "").rstrip("/")
_IS_DEV = os.environ.get("ENV", "production").lower() == "development"


# ── Auth helpers ──────────────────────────────────────────────────────────────


def _resolve_user_and_client(request: Request) -> tuple[str, str]:
    """Resolve (user_id, client_id) a partir do token de sessão. Levanta 401/404."""
    from App.Core.Services.Auth.RequestAuth import get_payload_from_request

    payload = get_payload_from_request(request)
    user_id = str(payload.get("user_id") or payload.get("sub", ""))
    client_id = DatabaseManager.execute_transaction(
        lambda s: DatabaseManager.get_client_id_by_user_id(s, user_id)
    )
    if not client_id:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    return user_id, client_id


def _load_analytics_config(session, client_id: str) -> Optional[dict]:
    row = session.execute(
        text("SELECT sdk_key, site_id, site_url FROM clients WHERE client_id = :cid"),
        {"cid": client_id},
    ).first()
    return dict(row._mapping) if row else None


def _internal_headers(client_id: str) -> dict:
    """Headers para chamadas ao analytics internal API.

    x-internal-key: autenticidade de serviço (o chamador é o backend).
    x-client-id:    autorização por recurso (o client_id é dono do site_id).
    O analytics valida ambos independentemente — defesa em profundidade contra IDOR.
    """
    return {"x-internal-key": INTERNAL_KEY, "x-client-id": client_id}


# ── FastAPI dependencies ──────────────────────────────────────────────────────


async def require_client(request: Request) -> str:
    """Dependency: resolve client_id do user autenticado."""
    _, client_id = _resolve_user_and_client(request)
    return client_id


async def require_analytics_site(
    client_id: Annotated[str, Depends(require_client)],
) -> tuple[str, dict]:
    """Dependency: resolve (client_id, config). Levanta 404 se analytics não configurado."""
    config = DatabaseManager.execute_transaction(
        lambda s: _load_analytics_config(s, client_id)
    )
    if not config or not config.get("site_id"):
        raise HTTPException(status_code=404, detail="Analytics não configurado.")
    return client_id, config


# ── Payloads ──────────────────────────────────────────────────────────────────


class SetupPayload(BaseModel):
    site_url: Optional[str] = None


class VerifyPayload(BaseModel):
    url: str


class FunnelTypePayload(BaseModel):
    funnel_type: str


class FunnelStepPayload(BaseModel):
    match_type: str
    match_value: str


# ── Routes ────────────────────────────────────────────────────────────────────


@analytics_router.post("/setup")
async def setup(payload: SetupPayload, request: Request):
    # Exceção justificada: setup precisa de user_id para a transação de upsert.
    user_id, client_id = _resolve_user_and_client(request)

    def _upsert(session):
        row = session.execute(
            text("SELECT sdk_key, site_id FROM clients WHERE client_id = :cid"),
            {"cid": client_id},
        ).first()
        existing = dict(row._mapping) if row else {}
        sdk_key = existing.get("sdk_key") or str(uuid.uuid4())
        site_id = existing.get("site_id") or str(uuid.uuid4())
        session.execute(
            text(
                "UPDATE clients SET sdk_key = :sdk_key, site_id = :site_id, site_url = :site_url"
                " WHERE client_id = :cid"
            ),
            {
                "sdk_key": sdk_key,
                "site_id": site_id,
                "site_url": payload.site_url,
                "cid": client_id,
            },
        )
        return {"sdk_key": sdk_key, "site_id": site_id}

    result = DatabaseManager.execute_transaction(_upsert)

    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            await http.post(
                f"{ANALYTICS_INTERNAL_URL}/internal/sites",
                json={
                    "site_id": result["site_id"],
                    "client_id": client_id,
                    "sdk_key": result["sdk_key"],
                    "site_url": payload.site_url,
                },
                headers=_internal_headers(client_id),
            )
    except Exception as e:
        log_error(f"[ANALYTICS] Falha ao registrar site no analytics service: {e}")

    return {
        "sdk_key": result["sdk_key"],
        "site_id": result["site_id"],
        "site_url": payload.site_url,
    }


@analytics_router.get("/snippet")
async def get_snippet(client_id: Annotated[str, Depends(require_client)]):
    config = DatabaseManager.execute_transaction(
        lambda s: _load_analytics_config(s, client_id)
    )
    if not config or not config.get("sdk_key"):
        return {"configured": False, "snippet": None, "sdk_key": None, "site_id": None}
    snippet = (
        f"<script\n"
        f'  src="{PUBLIC_URL}/sdk.js"\n'
        f'  data-site-id="{config["site_id"]}"\n'
        f'  data-sdk-key="{config["sdk_key"]}"\n'
        f"  async>\n"
        f"</script>"
    )
    return {
        "configured": True,
        "snippet": snippet,
        "sdk_key": config["sdk_key"],
        "site_id": config["site_id"],
        "site_url": config.get("site_url"),
    }


@analytics_router.post("/verify")
async def verify_installation(
    payload: VerifyPayload,
    auth: Annotated[tuple, Depends(require_analytics_site)],
):
    _, config = auth
    url = payload.url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    html = await _fetch_html_for_verify(url)
    if html is None:
        return {"installed": False, "error": "Não foi possível acessar a URL informada"}
    installed = config["sdk_key"] in html and config["site_id"] in html
    return {"installed": installed, "url": url}


@analytics_router.get("/summary")
async def get_summary(auth: Annotated[tuple, Depends(require_analytics_site)]):
    client_id, config = auth
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            resp = await http.get(
                f"{ANALYTICS_INTERNAL_URL}/internal/summary/{config['site_id']}",
                headers=_internal_headers(client_id),
            )
            return resp.json()
    except Exception as e:
        log_error(f"[ANALYTICS] Falha ao buscar summary: {e}")
        return {"total_events": 0, "unique_visitors": 0, "top_pages": []}


@analytics_router.get("/funnel")
async def get_funnel(auth: Annotated[tuple, Depends(require_analytics_site)]):
    client_id, config = auth
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            resp = await http.get(
                f"{ANALYTICS_INTERNAL_URL}/internal/funnel/{config['site_id']}",
                headers=_internal_headers(client_id),
            )
            return resp.json()
    except Exception as e:
        log_error(f"[ANALYTICS] Falha ao buscar funil: {e}")
        return {"funnel_type": "consultivo", "steps": []}


@analytics_router.put("/funnel")
async def set_funnel_type(
    payload: FunnelTypePayload,
    auth: Annotated[tuple, Depends(require_analytics_site)],
):
    client_id, config = auth
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            resp = await http.put(
                f"{ANALYTICS_INTERNAL_URL}/internal/funnel/{config['site_id']}",
                json={"funnel_type": payload.funnel_type},
                headers=_internal_headers(client_id),
            )
            return resp.json()
    except Exception as e:
        log_error(f"[ANALYTICS] Falha ao salvar tipo de funil: {e}")
        raise HTTPException(status_code=502, detail="Serviço analytics indisponível.")


@analytics_router.put("/funnel/steps/{stage_id}")
async def upsert_funnel_step(
    stage_id: str,
    payload: FunnelStepPayload,
    auth: Annotated[tuple, Depends(require_analytics_site)],
):
    client_id, config = auth
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            resp = await http.put(
                f"{ANALYTICS_INTERNAL_URL}/internal/funnel/{config['site_id']}/steps/{stage_id}",
                json={
                    "match_type": payload.match_type,
                    "match_value": payload.match_value,
                },
                headers=_internal_headers(client_id),
            )
            return resp.json()
    except Exception as e:
        log_error(f"[ANALYTICS] Falha ao salvar etapa de funil: {e}")
        raise HTTPException(status_code=502, detail="Serviço analytics indisponível.")


@analytics_router.delete("/funnel/steps/{stage_id}")
async def delete_funnel_step(
    stage_id: str,
    auth: Annotated[tuple, Depends(require_analytics_site)],
):
    client_id, config = auth
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            resp = await http.delete(
                f"{ANALYTICS_INTERNAL_URL}/internal/funnel/{config['site_id']}/steps/{stage_id}",
                headers=_internal_headers(client_id),
            )
            return resp.json()
    except Exception as e:
        log_error(f"[ANALYTICS] Falha ao deletar etapa de funil: {e}")
        raise HTTPException(status_code=502, detail="Serviço analytics indisponível.")


@analytics_router.get("/funnel/report")
async def get_funnel_report(auth: Annotated[tuple, Depends(require_analytics_site)]):
    client_id, config = auth
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            resp = await http.get(
                f"{ANALYTICS_INTERNAL_URL}/internal/funnel/{config['site_id']}/report",
                headers=_internal_headers(client_id),
            )
            return resp.json()
    except Exception as e:
        log_error(f"[ANALYTICS] Falha ao buscar report de funil: {e}")
        return {"data": []}


@analytics_router.get("/funnel/cohort")
async def get_funnel_cohort(
    auth: Annotated[tuple, Depends(require_analytics_site)],
    utm_campaign: str = "",
    utm_content: Optional[str] = None,
    days: int = 30,
):
    if not utm_campaign:
        raise HTTPException(status_code=400, detail="utm_campaign required")
    client_id, config = auth
    params: dict = {"utm_campaign": utm_campaign, "days": days}
    if utm_content:
        params["utm_content"] = utm_content
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            resp = await http.get(
                f"{ANALYTICS_INTERNAL_URL}/internal/funnel/{config['site_id']}/cohort",
                params=params,
                headers=_internal_headers(client_id),
            )
            return resp.json()
    except Exception as e:
        log_error(f"[ANALYTICS] Falha ao buscar cohort de funil: {e}")
        return {"data": []}


@analytics_router.get("/top-urls")
async def get_top_urls(
    auth: Annotated[tuple, Depends(require_analytics_site)],
    limit: int = 50,
    days: int = 30,
):
    from App.Core.Cache.RedisCache import cache_get, cache_set

    client_id, config = auth
    cache_key = f"analytics:top-urls:{config['site_id']}:{days}:{limit}"

    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            resp = await http.get(
                f"{ANALYTICS_INTERNAL_URL}/internal/top-urls/{config['site_id']}?limit={limit}&days={days}",
                headers=_internal_headers(client_id),
            )
            data = resp.json()
            cache_set(cache_key, data, ttl=300)
            return data
    except Exception as e:
        log_error(f"[ANALYTICS] Falha ao buscar top URLs: {e}")
        return {"data": []}


# ── Verify helpers ────────────────────────────────────────────────────────────


def _translate_localhost(url: str) -> str:
    import re

    return re.sub(
        r"(https?://)localhost(:\d+)?",
        lambda m: f"{m.group(1)}gateway{m.group(2) or ''}",
        url,
    )


async def _fetch_html_for_verify(url: str) -> Optional[str]:
    browser_url = _translate_localhost(url)
    was_translated = browser_url != url
    if BROWSER_SERVICE_URL and not was_translated:
        try:
            async with httpx.AsyncClient(timeout=30.0) as http:
                resp = await http.post(
                    f"{BROWSER_SERVICE_URL}/scrape",
                    json={"url": browser_url, "wait_until": "load"},
                )
                data = resp.json()
                if data.get("success") and data.get("html"):
                    return data["html"]
                log_error(
                    f"[ANALYTICS] Browser service recusou {url}: {data.get('error')}"
                )
        except Exception as e:
            log_error(f"[ANALYTICS] Erro ao chamar browser service: {e}")

    if not _IS_DEV:
        return None

    from urllib.parse import urlparse as _urlparse

    _orig_host = _urlparse(url).netloc or _urlparse(url).hostname or ""
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as http:
            resp = await http.get(
                browser_url,
                headers={"User-Agent": "MD70-Verify/1.0", "Host": _orig_host},
            )
            return resp.text
    except Exception as e:
        log_error(f"[ANALYTICS] Fallback httpx falhou para {browser_url}: {e}")
        return None
