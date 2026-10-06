"""Provider Google Ads para MCP nativo."""
from typing import Dict, Any, List
import httpx

from ._shared import _TokenExpiredError, _refresh_access_token

TOOL_DEFINITIONS: List[Dict] = [
    {
        "name": "mcp__google-ads__list_campaigns",
        "description": "[GOOGLE-ADS] Lista campanhas do Google Ads.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filtrar por status: ENABLED, PAUSED, REMOVED (opcional)",
                },
            },
        },
    },
    {
        "name": "mcp__google-ads__get_campaign_stats",
        "description": "[GOOGLE-ADS] Obtém métricas de desempenho das campanhas (impressões, cliques, custo, conversões).",
        "parameters": {
            "type": "object",
            "properties": {
                "campaign_id": {
                    "type": "string",
                    "description": "ID da campanha (opcional, omitir para todas)",
                },
                "days": {
                    "type": "integer",
                    "description": "Período em dias (padrão 30)",
                },
            },
        },
    },
    {
        "name": "mcp__google-ads__update_campaign",
        "description": "[GOOGLE-ADS] Atualiza nome ou status de uma campanha.",
        "parameters": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string", "description": "ID da campanha"},
                "name": {"type": "string", "description": "Novo nome (opcional)"},
                "status": {
                    "type": "string",
                    "description": "Novo status: ENABLED ou PAUSED (opcional)",
                },
            },
            "required": ["campaign_id"],
        },
    },
    {
        "name": "mcp__google-ads__pause_campaign",
        "description": "[GOOGLE-ADS] Pausa uma campanha ativa do Google Ads.",
        "parameters": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string", "description": "ID da campanha"},
            },
            "required": ["campaign_id"],
        },
    },
    {
        "name": "mcp__google-ads__enable_campaign",
        "description": "[GOOGLE-ADS] Ativa uma campanha pausada do Google Ads.",
        "parameters": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string", "description": "ID da campanha"},
            },
            "required": ["campaign_id"],
        },
    },
    {
        "name": "mcp__google-ads__delete_campaign",
        "description": "[GOOGLE-ADS] Remove permanentemente uma campanha do Google Ads.",
        "parameters": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string", "description": "ID da campanha"},
            },
            "required": ["campaign_id"],
        },
    },
    {
        "name": "mcp__google-ads__update_ad_group",
        "description": "[GOOGLE-ADS] Atualiza nome ou status de um ad group.",
        "parameters": {
            "type": "object",
            "properties": {
                "ad_group_id": {"type": "string", "description": "ID do ad group"},
                "name": {"type": "string", "description": "Novo nome (opcional)"},
                "status": {
                    "type": "string",
                    "description": "Novo status: ENABLED ou PAUSED (opcional)",
                },
            },
            "required": ["ad_group_id"],
        },
    },
    {
        "name": "mcp__google-ads__pause_ad_group",
        "description": "[GOOGLE-ADS] Pausa um ad group ativo.",
        "parameters": {
            "type": "object",
            "properties": {
                "ad_group_id": {"type": "string", "description": "ID do ad group"},
            },
            "required": ["ad_group_id"],
        },
    },
    {
        "name": "mcp__google-ads__enable_ad_group",
        "description": "[GOOGLE-ADS] Ativa um ad group pausado.",
        "parameters": {
            "type": "object",
            "properties": {
                "ad_group_id": {"type": "string", "description": "ID do ad group"},
            },
            "required": ["ad_group_id"],
        },
    },
    {
        "name": "mcp__google-ads__pause_ad",
        "description": "[GOOGLE-ADS] Pausa um anúncio (criativo) ativo.",
        "parameters": {
            "type": "object",
            "properties": {
                "ad_group_id": {"type": "string", "description": "ID do ad group"},
                "ad_id": {"type": "string", "description": "ID do anúncio"},
            },
            "required": ["ad_group_id", "ad_id"],
        },
    },
    {
        "name": "mcp__google-ads__enable_ad",
        "description": "[GOOGLE-ADS] Ativa um anúncio (criativo) pausado.",
        "parameters": {
            "type": "object",
            "properties": {
                "ad_group_id": {"type": "string", "description": "ID do ad group"},
                "ad_id": {"type": "string", "description": "ID do anúncio"},
            },
            "required": ["ad_group_id", "ad_id"],
        },
    },
    {
        "name": "mcp__google-ads__list_ad_groups",
        "description": "[GOOGLE-ADS] Lista os ad groups de uma campanha do Google Ads.",
        "parameters": {
            "type": "object",
            "properties": {
                "campaign_id": {
                    "type": "string",
                    "description": "ID da campanha (opcional, omitir para todos os ad groups da conta)",
                },
                "status": {
                    "type": "string",
                    "description": "Filtrar por status: ENABLED, PAUSED, REMOVED (opcional)",
                },
            },
        },
    },
    {
        "name": "mcp__google-ads__list_keywords",
        "description": "[GOOGLE-ADS] Lista as keywords (palavras-chave) de um ad group ou campanha.",
        "parameters": {
            "type": "object",
            "properties": {
                "ad_group_id": {
                    "type": "string",
                    "description": "ID do ad group (opcional)",
                },
                "campaign_id": {
                    "type": "string",
                    "description": "ID da campanha (opcional)",
                },
                "status": {
                    "type": "string",
                    "description": "Filtrar por status: ENABLED, PAUSED, REMOVED (opcional)",
                },
            },
        },
    },
    {
        "name": "mcp__google-ads__list_ads",
        "description": "[GOOGLE-ADS] Lista os anúncios (criativos) de um ad group ou campanha.",
        "parameters": {
            "type": "object",
            "properties": {
                "ad_group_id": {
                    "type": "string",
                    "description": "ID do ad group (opcional)",
                },
                "campaign_id": {
                    "type": "string",
                    "description": "ID da campanha (opcional)",
                },
                "status": {
                    "type": "string",
                    "description": "Filtrar por status: ENABLED, PAUSED, REMOVED (opcional)",
                },
            },
        },
    },
]

# Google Ads API version — update when newer stable version is available
_GADS_API_VERSION = "v24"

# GAQL só aceita literais fixos para DURING — valores aceitos pela API
_GAQL_DAYS_MAP = {7: "LAST_7_DAYS", 14: "LAST_14_DAYS", 30: "LAST_30_DAYS"}


def _gads_error_message(data: dict, fallback: str) -> str:
    """Extrai mensagem legível da resposta de erro REST do Google Ads."""
    for detail in data.get("error", {}).get("details", []):
        for err in detail.get("errors", []):
            msg = err.get("message")
            if msg:
                return msg
    return data.get("error", {}).get("message") or fallback


async def call(tool_name: str, args: Dict, env: Dict) -> Dict:
    from App.Core.Settings.Settings import (
        GADS_DEVELOPER_TOKEN as _SERVER_DEV_TOKEN,
        GADS_MANAGER_CUSTOMER_ID as _SERVER_MANAGER_ID,
    )

    refresh_token = env.get("GADS_REFRESH_TOKEN", "")
    client_id_oauth = env.get("GADS_CLIENT_ID", "")
    client_secret = env.get("GADS_CLIENT_SECRET", "")
    developer_token = env.get("GADS_DEVELOPER_TOKEN", "") or _SERVER_DEV_TOKEN
    login_customer_id = (
        env.get("GADS_LOGIN_CUSTOMER_ID", "") or _SERVER_MANAGER_ID
    ).replace("-", "")
    # If no per-user customer_id, default to the manager's own account (covers
    # existing integrations created before the OAuth callback auto-save was added)
    customer_id = env.get("GADS_CUSTOMER_ID", "").replace("-", "") or login_customer_id
    api_version = env.get("GADS_API_VERSION", _GADS_API_VERSION)

    missing = [
        k
        for k, v in {
            "GADS_DEVELOPER_TOKEN": developer_token,
            "GADS_CUSTOMER_ID": customer_id,
        }.items()
        if not v
    ]
    access_token = env.get("GADS_ACCESS_TOKEN", "")
    if not access_token and not refresh_token:
        missing.append("GADS_ACCESS_TOKEN ou GADS_REFRESH_TOKEN")
    if missing:
        return {
            "success": False,
            "error": f"Credenciais do Google Ads não configuradas: {', '.join(missing)}. "
            "Configure a integração em Configurações → Conexões.",
        }

    # Obtém token antes de qualquer chamada quando só há refresh_token disponível
    if not access_token and refresh_token:
        access_token = (
            await _refresh_access_token(client_id_oauth, client_secret, refresh_token)
            or ""
        )

    base_url = f"https://googleads.googleapis.com/{api_version}/customers/{customer_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": developer_token,
        "Content-Type": "application/json",
    }
    if login_customer_id:
        headers["login-customer-id"] = login_customer_id

    async with httpx.AsyncClient(timeout=30.0) as http:

        async def _refresh_and_retry(req_fn):
            resp = await req_fn(headers)
            if resp.status_code == 401 and refresh_token:
                new_token = await _refresh_access_token(
                    client_id_oauth, client_secret, refresh_token
                )
                if new_token:
                    headers["Authorization"] = f"Bearer {new_token}"
                    resp = await req_fn(headers)
            if resp.status_code == 401:
                # 401 = token OAuth do usuário expirado/inválido
                raise _TokenExpiredError("401", who="user")
            if resp.status_code == 403:
                # 403 no Google Ads REST = developer token do servidor sem permissão
                # (token OAuth do usuário gera 401, nunca 403)
                raise _TokenExpiredError("403", who="system")
            return resp

        async def _gaql_search(query: str):
            resp = await _refresh_and_retry(
                lambda h: http.post(
                    f"{base_url}/googleAds:search", headers=h, json={"query": query}
                )
            )
            if resp.status_code != 200:
                try:
                    data = resp.json()
                    msg = _gads_error_message(data, str(resp.status_code))
                except Exception:
                    msg = f"HTTP {resp.status_code}: {resp.text[:200] or 'resposta vazia'}"
                return None, msg
            return resp.json().get("results", []), None

        if tool_name == "list_campaigns":
            status_filter = args.get("status")
            where = (
                f"WHERE campaign.status = '{status_filter}'" if status_filter else ""
            )
            rows, err = await _gaql_search(
                f"SELECT campaign.id, campaign.name, campaign.status FROM campaign {where} ORDER BY campaign.id"
            )
            if err:
                return {"success": False, "error": err}
            lines = [
                f"ID: {r['campaign']['id']} | {r['campaign']['name']} | {r['campaign']['status']}"
                for r in rows
            ]
            return {
                "success": True,
                "content": f"{len(rows)} campanha(s):\n" + "\n".join(lines),
            }

        elif tool_name == "get_campaign_stats":
            days = args.get("days", 30)
            gaql_period = _GAQL_DAYS_MAP.get(days) or (
                "LAST_7_DAYS"
                if days <= 7
                else "LAST_14_DAYS"
                if days <= 14
                else "LAST_30_DAYS"
            )
            campaign_id = args.get("campaign_id")
            where = f"WHERE segments.date DURING {gaql_period}"
            if campaign_id:
                where += f" AND campaign.id = {campaign_id}"
            rows, err = await _gaql_search(
                f"SELECT campaign.id, campaign.name, metrics.impressions, metrics.clicks, "
                f"metrics.cost_micros, metrics.conversions, metrics.ctr FROM campaign {where}"
            )
            if err:
                return {"success": False, "error": err}
            lines = []
            for r in rows:
                c = r.get("campaign", {})
                m = r.get("metrics", {})
                cost = int(m.get("costMicros", 0)) / 1_000_000
                lines.append(
                    f"{c.get('name')} — impressões: {m.get('impressions', 0)}, "
                    f"cliques: {m.get('clicks', 0)}, custo: R${cost:.2f}, "
                    f"conversões: {m.get('conversions', 0)}, CTR: {float(m.get('ctr', 0)):.2%}"
                )
            return {
                "success": True,
                "content": f"Métricas ({gaql_period}):\n" + "\n".join(lines),
            }

        elif tool_name in ("update_campaign", "pause_campaign", "enable_campaign"):
            campaign_id = args.get("campaign_id")
            resource_name = f"customers/{customer_id}/campaigns/{campaign_id}"
            update_obj = {"resourceName": resource_name}
            mask_fields = []
            if tool_name == "pause_campaign":
                update_obj["status"] = "PAUSED"
                mask_fields = ["status"]
            elif tool_name == "enable_campaign":
                update_obj["status"] = "ENABLED"
                mask_fields = ["status"]
            else:
                if args.get("name"):
                    update_obj["name"] = args["name"]
                    mask_fields.append("name")
                if args.get("status"):
                    update_obj["status"] = args["status"]
                    mask_fields.append("status")
            body = {
                "operations": [
                    {"update": update_obj, "updateMask": ",".join(mask_fields)}
                ]
            }
            resp = await _refresh_and_retry(
                lambda h: http.post(
                    f"{base_url}/campaigns:mutate", headers=h, json=body
                )
            )
            data = resp.json()
            if resp.status_code == 200:
                return {
                    "success": True,
                    "content": f"Campanha {campaign_id} atualizada",
                }
            return {
                "success": False,
                "error": _gads_error_message(data, str(resp.status_code)),
            }

        elif tool_name == "delete_campaign":
            campaign_id = args.get("campaign_id")
            resource_name = f"customers/{customer_id}/campaigns/{campaign_id}"
            body = {"operations": [{"remove": resource_name}]}
            resp = await _refresh_and_retry(
                lambda h: http.post(
                    f"{base_url}/campaigns:mutate", headers=h, json=body
                )
            )
            data = resp.json()
            if resp.status_code == 200:
                return {"success": True, "content": f"Campanha {campaign_id} removida"}
            return {
                "success": False,
                "error": _gads_error_message(data, str(resp.status_code)),
            }

        elif tool_name == "list_ad_groups":
            campaign_id = args.get("campaign_id")
            status_filter = args.get("status")
            where_parts = []
            if campaign_id:
                where_parts.append(f"campaign.id = {campaign_id}")
            if status_filter:
                where_parts.append(f"ad_group.status = '{status_filter}'")
            where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
            rows, err = await _gaql_search(
                f"SELECT ad_group.id, ad_group.name, ad_group.status, campaign.id, campaign.name "
                f"FROM ad_group {where} ORDER BY ad_group.id"
            )
            if err:
                return {"success": False, "error": err}
            lines = [
                f"ID: {r['adGroup']['id']} | {r['adGroup']['name']} | {r['adGroup']['status']} "
                f"| Campanha: {r['campaign']['name']}"
                for r in rows
            ]
            return {
                "success": True,
                "content": f"{len(rows)} ad group(s):\n" + "\n".join(lines),
            }

        elif tool_name == "list_keywords":
            ad_group_id = args.get("ad_group_id")
            campaign_id = args.get("campaign_id")
            status_filter = args.get("status")
            where_parts = []
            if ad_group_id:
                where_parts.append(f"ad_group.id = {ad_group_id}")
            if campaign_id:
                where_parts.append(f"campaign.id = {campaign_id}")
            if status_filter:
                where_parts.append(f"ad_group_criterion.status = '{status_filter}'")
            where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
            rows, err = await _gaql_search(
                f"SELECT ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type, "
                f"ad_group_criterion.status, ad_group_criterion.criterion_id, "
                f"ad_group.name, campaign.name "
                f"FROM ad_group_criterion "
                f"WHERE ad_group_criterion.type = 'KEYWORD' "
                + (("AND " + " AND ".join(where_parts)) if where_parts else "")
                + " ORDER BY ad_group_criterion.criterion_id"
            )
            if err:
                return {"success": False, "error": err}
            lines = [
                f"{r['adGroupCriterion']['keyword']['text']} "
                f"[{r['adGroupCriterion']['keyword']['matchType']}] "
                f"| {r['adGroupCriterion']['status']} "
                f"| Ad Group: {r['adGroup']['name']} | Campanha: {r['campaign']['name']}"
                for r in rows
            ]
            return {
                "success": True,
                "content": f"{len(rows)} keyword(s):\n" + "\n".join(lines),
            }

        elif tool_name == "list_ads":
            ad_group_id = args.get("ad_group_id")
            campaign_id = args.get("campaign_id")
            status_filter = args.get("status")
            where_parts = []
            if ad_group_id:
                where_parts.append(f"ad_group.id = {ad_group_id}")
            if campaign_id:
                where_parts.append(f"campaign.id = {campaign_id}")
            if status_filter:
                where_parts.append(f"ad_group_ad.status = '{status_filter}'")
            where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
            rows, err = await _gaql_search(
                f"SELECT ad_group_ad.ad.id, ad_group_ad.ad.type, ad_group_ad.ad.name, "
                f"ad_group_ad.ad.final_urls, ad_group_ad.status, "
                f"ad_group_ad.ad.responsive_search_ad.headlines, "
                f"ad_group_ad.ad.responsive_search_ad.descriptions, "
                f"ad_group.name, campaign.name "
                f"FROM ad_group_ad {where} ORDER BY ad_group_ad.ad.id"
            )
            if err:
                return {"success": False, "error": err}
            lines = []
            for r in rows:
                ad = r.get("adGroupAd", {}).get("ad", {})
                rsa = ad.get("responsiveSearchAd", {})
                headlines = ", ".join(
                    h.get("text", "") for h in rsa.get("headlines", [])[:3]
                )
                descriptions = ", ".join(
                    d.get("text", "") for d in rsa.get("descriptions", [])[:2]
                )
                urls = ", ".join(ad.get("finalUrls", [])[:1])
                lines.append(
                    f"ID: {ad.get('id')} | Tipo: {ad.get('type')} | {r['adGroupAd']['status']}"
                    + (f"\n  Títulos: {headlines}" if headlines else "")
                    + (f"\n  Descrições: {descriptions}" if descriptions else "")
                    + (f"\n  URL: {urls}" if urls else "")
                    + f"\n  Ad Group: {r['adGroup']['name']} | Campanha: {r['campaign']['name']}"
                )
            return {
                "success": True,
                "content": f"{len(rows)} anúncio(s):\n" + "\n".join(lines),
            }

        elif tool_name in ("update_ad_group", "pause_ad_group", "enable_ad_group"):
            ad_group_id = args.get("ad_group_id")
            resource_name = f"customers/{customer_id}/adGroups/{ad_group_id}"
            update_obj = {"resourceName": resource_name}
            mask_fields = []
            if tool_name == "pause_ad_group":
                update_obj["status"] = "PAUSED"
                mask_fields = ["status"]
            elif tool_name == "enable_ad_group":
                update_obj["status"] = "ENABLED"
                mask_fields = ["status"]
            else:
                if args.get("name"):
                    update_obj["name"] = args["name"]
                    mask_fields.append("name")
                if args.get("status"):
                    update_obj["status"] = args["status"]
                    mask_fields.append("status")
            body = {
                "operations": [
                    {"update": update_obj, "updateMask": ",".join(mask_fields)}
                ]
            }
            resp = await _refresh_and_retry(
                lambda h: http.post(f"{base_url}/adGroups:mutate", headers=h, json=body)
            )
            data = resp.json()
            if resp.status_code == 200:
                return {
                    "success": True,
                    "content": f"Ad group {ad_group_id} atualizado",
                }
            return {
                "success": False,
                "error": _gads_error_message(data, str(resp.status_code)),
            }

        elif tool_name in ("pause_ad", "enable_ad"):
            ad_group_id = args.get("ad_group_id")
            ad_id = args.get("ad_id")
            resource_name = f"customers/{customer_id}/adGroupAds/{ad_group_id}~{ad_id}"
            new_status = "PAUSED" if tool_name == "pause_ad" else "ENABLED"
            body = {
                "operations": [
                    {
                        "update": {
                            "resourceName": resource_name,
                            "status": new_status,
                        },
                        "updateMask": "status",
                    }
                ]
            }
            resp = await _refresh_and_retry(
                lambda h: http.post(
                    f"{base_url}/adGroupAds:mutate", headers=h, json=body
                )
            )
            data = resp.json()
            if resp.status_code == 200:
                return {
                    "success": True,
                    "content": f"Anúncio {ad_id} (ad group {ad_group_id}) → {new_status}",
                }
            return {
                "success": False,
                "error": _gads_error_message(data, str(resp.status_code)),
            }

    return {"success": False, "error": "Ferramenta não reconhecida"}
