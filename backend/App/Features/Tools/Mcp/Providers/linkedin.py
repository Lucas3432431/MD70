"""Provider LinkedIn para MCP nativo."""
from typing import Dict, Any, List
import httpx

TOOL_DEFINITIONS: List[Dict] = [
    {
        "name": "mcp__linkedin__get_profile",
        "description": "[LINKEDIN] Retorna o perfil do usuário autenticado (nome, email, URN).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "mcp__linkedin__create_post",
        "description": "[LINKEDIN] Publica um post de texto no perfil pessoal do usuário.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Texto do post (máx 3000 caracteres)",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "mcp__linkedin__list_organizations",
        "description": "[LINKEDIN] Lista as páginas de empresa (organizations) que o usuário administra.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "mcp__linkedin__create_organization_post",
        "description": "[LINKEDIN] Publica um post de texto em nome de uma página de empresa.",
        "parameters": {
            "type": "object",
            "properties": {
                "org_id": {
                    "type": "string",
                    "description": "ID numérico da organização (obtido via list_organizations)",
                },
                "text": {
                    "type": "string",
                    "description": "Texto do post (máx 3000 caracteres)",
                },
            },
            "required": ["org_id", "text"],
        },
    },
    {
        "name": "mcp__linkedin__list_ad_accounts",
        "description": "[LINKEDIN] Lista as contas de anúncio do LinkedIn Ads (requer escopo r_ads).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "mcp__linkedin__list_campaigns",
        "description": "[LINKEDIN] Lista campanhas (Campaign Groups) de uma conta de anúncio.",
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "ID numérico da conta de anúncio (obtido via list_ad_accounts)",
                },
            },
            "required": ["account_id"],
        },
    },
    {
        "name": "mcp__linkedin__get_campaign_insights",
        "description": "[LINKEDIN] Retorna métricas de performance de uma conta de anúncio (impressões, cliques, gasto, CTR, CPC).",
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "ID numérico da conta de anúncio",
                },
                "campaign_group_id": {
                    "type": "string",
                    "description": "ID do Campaign Group para filtrar (opcional)",
                },
                "date_range": {
                    "type": "string",
                    "description": "Período: LAST_30_DAYS, LAST_7_DAYS, THIS_MONTH, LAST_MONTH (padrão: LAST_30_DAYS)",
                },
            },
            "required": ["account_id"],
        },
    },
]


async def call(tool_name: str, args: Dict, env: Dict) -> Dict:
    token = env.get("LINKEDIN_ACCESS_TOKEN", "")
    person_urn = env.get("LINKEDIN_PERSON_URN", "")

    if not token:
        return {
            "success": False,
            "error": "Token LinkedIn não configurado — reconecte em Configurações → Integrações.",
        }

    base_v2 = "https://api.linkedin.com/v2"
    base_rest = "https://api.linkedin.com/rest"
    headers_v2 = {
        "Authorization": f"Bearer {token}",
        "X-Restli-Protocol-Version": "2.0.0",
    }
    headers_rest = {
        "Authorization": f"Bearer {token}",
        "LinkedIn-Version": "202401",
        "Content-Type": "application/json",
    }

    def _li_err(data: dict) -> Dict | None:
        if not isinstance(data, dict):
            return None
        status = data.get("status", 200)
        if isinstance(status, int) and status >= 400:
            if status == 401:
                return {
                    "success": False,
                    "error": "Token LinkedIn expirado — reconecte em Configurações → Integrações.",
                }
            msg = data.get("message") or str(data)
            return {"success": False, "error": f"LinkedIn API: {msg}"}
        return None

    async with httpx.AsyncClient(timeout=20.0) as http:
        if tool_name == "get_profile":
            resp = await http.get(f"{base_v2}/userinfo", headers=headers_v2)
            data = resp.json()
            if err := _li_err(data):
                return err
            lines = [
                f"Nome: {data.get('name', '?')}",
                f"Email: {data.get('email', '?')}",
                f"URN: {data.get('sub', '?')}",
            ]
            if data.get("picture"):
                lines.append(f"Foto: {data['picture']}")
            return {"success": True, "content": "\n".join(lines)}

        elif tool_name == "create_post":
            text = args.get("text", "")
            if not text:
                return {"success": False, "error": "Campo 'text' é obrigatório."}
            author = person_urn
            if not author:
                r = await http.get(f"{base_v2}/userinfo", headers=headers_v2)
                author = r.json().get("sub", "")
            if not author:
                return {
                    "success": False,
                    "error": "Não foi possível determinar o autor. Reconfigure a integração.",
                }
            payload = {
                "author": author,
                "lifecycleState": "PUBLISHED",
                "visibility": "PUBLIC",
                "commentary": text[:3000],
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": [],
                },
            }
            resp = await http.post(
                f"{base_rest}/posts", headers=headers_rest, json=payload
            )
            if resp.status_code == 201:
                post_id = resp.headers.get("x-linkedin-id") or resp.headers.get(
                    "x-restli-id", ""
                )
                return {"success": True, "content": f"Post publicado! ID: {post_id}"}
            data = resp.json()
            if err := _li_err(data):
                return err
            return {
                "success": False,
                "error": f"Erro ao criar post: {resp.status_code} — {resp.text[:300]}",
            }

        elif tool_name == "list_organizations":
            resp = await http.get(
                f"{base_v2}/organizationAcls",
                headers=headers_v2,
                params={
                    "q": "roleAssignee",
                    "role": "ADMINISTRATOR",
                    "state": "APPROVED",
                    "count": 10,
                },
            )
            data = resp.json()
            if err := _li_err(data):
                return err
            elements = data.get("elements", [])
            if not elements:
                return {"success": True, "content": "Nenhuma organização encontrada."}
            lines = []
            for el in elements:
                org_urn = el.get("organizationalTarget", "")
                org_id = org_urn.split(":")[-1] if ":" in org_urn else org_urn
                try:
                    r2 = await http.get(
                        f"{base_v2}/organizations/{org_id}",
                        headers=headers_v2,
                        params={"fields": "id,localizedName,vanityName"},
                    )
                    org = r2.json()
                    name = org.get("localizedName") or next(
                        iter((org.get("name") or {}).get("localized", {}).values()),
                        org_urn,
                    )
                    lines.append(f"ID: {org_id} | Nome: {name} | URN: {org_urn}")
                except Exception:
                    lines.append(f"ID: {org_id} | URN: {org_urn}")
            return {
                "success": True,
                "content": f"{len(lines)} organização(ões):\n" + "\n".join(lines),
            }

        elif tool_name == "create_organization_post":
            org_id = args.get("org_id", "")
            text = args.get("text", "")
            if not org_id or not text:
                return {
                    "success": False,
                    "error": "Campos 'org_id' e 'text' são obrigatórios.",
                }
            payload = {
                "author": f"urn:li:organization:{org_id}",
                "lifecycleState": "PUBLISHED",
                "visibility": "PUBLIC",
                "commentary": text[:3000],
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": [],
                },
            }
            resp = await http.post(
                f"{base_rest}/posts", headers=headers_rest, json=payload
            )
            if resp.status_code == 201:
                post_id = resp.headers.get("x-linkedin-id") or resp.headers.get(
                    "x-restli-id", ""
                )
                return {
                    "success": True,
                    "content": f"Post publicado na organização {org_id}! ID: {post_id}",
                }
            data = resp.json()
            if err := _li_err(data):
                return err
            return {
                "success": False,
                "error": f"Erro ao criar post: {resp.status_code} — {resp.text[:300]}",
            }

        elif tool_name == "list_ad_accounts":
            resp = await http.get(
                f"{base_v2}/adAccounts",
                headers=headers_v2,
                params={
                    "q": "search",
                    "search.type.values[0]": "BUSINESS",
                    "count": 20,
                },
            )
            data = resp.json()
            if err := _li_err(data):
                return err
            elements = data.get("elements", [])
            if not elements:
                return {
                    "success": True,
                    "content": "Nenhuma conta de anúncio encontrada. Verifique se o token tem escopo r_ads.",
                }
            lines = [
                f"ID: {el.get('id','?')} | Nome: {el.get('name','?')} | Status: {el.get('status','?')} | Moeda: {el.get('currency','?')}"
                for el in elements
            ]
            return {
                "success": True,
                "content": f"{len(lines)} conta(s) de anúncio:\n" + "\n".join(lines),
            }

        elif tool_name == "list_campaigns":
            account_id = args.get("account_id", "")
            if not account_id:
                return {"success": False, "error": "Campo 'account_id' é obrigatório."}
            resp = await http.get(
                f"{base_v2}/adCampaignGroups",
                headers=headers_v2,
                params={
                    "search.account.values[0]": f"urn:li:sponsoredAccount:{account_id}",
                    "count": 25,
                },
            )
            data = resp.json()
            if err := _li_err(data):
                return err
            elements = data.get("elements", [])
            if not elements:
                return {
                    "success": True,
                    "content": "Nenhuma campanha encontrada para esta conta.",
                }
            lines = []
            for el in elements:
                budget = el.get("totalBudget") or {}
                lines.append(
                    f"ID: {el.get('id','?')} | Nome: {el.get('name','?')} | Status: {el.get('status','?')} | Budget: {budget.get('amount','?')} {budget.get('currencyCode','')}"
                )
            return {
                "success": True,
                "content": f"{len(lines)} campanha(s):\n" + "\n".join(lines),
            }

        elif tool_name == "get_campaign_insights":
            account_id = args.get("account_id", "")
            if not account_id:
                return {"success": False, "error": "Campo 'account_id' é obrigatório."}
            date_range = args.get("date_range", "LAST_30_DAYS")
            params: Dict[str, Any] = {
                "q": "analytics",
                "pivot": "CAMPAIGN_GROUP",
                "dateRange": date_range,
                "accounts[0]": f"urn:li:sponsoredAccount:{account_id}",
                "fields": "impressions,clicks,costInLocalCurrency,totalEngagements",
                "count": 25,
            }
            campaign_group_id = args.get("campaign_group_id", "")
            if campaign_group_id:
                params[
                    "campaignGroups[0]"
                ] = f"urn:li:sponsoredCampaignGroup:{campaign_group_id}"
            resp = await http.get(
                f"{base_v2}/adAnalytics", headers=headers_v2, params=params
            )
            data = resp.json()
            if err := _li_err(data):
                return err
            elements = data.get("elements", [])
            if not elements:
                return {
                    "success": True,
                    "content": "Sem dados para o período selecionado.",
                }
            impressions = sum(el.get("impressions", 0) for el in elements)
            clicks = sum(el.get("clicks", 0) for el in elements)
            spend = sum(float(el.get("costInLocalCurrency", 0) or 0) for el in elements)
            engagements = sum(el.get("totalEngagements", 0) for el in elements)
            ctr = (clicks / impressions * 100) if impressions else 0
            cpc = (spend / clicks) if clicks else 0
            return {
                "success": True,
                "content": (
                    f"LinkedIn Ads — Conta {account_id} | Período: {date_range}\n"
                    f"Impressões: {impressions:,} | Cliques: {clicks:,} | CTR: {ctr:.2f}%\n"
                    f"Engajamentos: {engagements:,} | Gasto: {spend:.2f} | CPC: {cpc:.2f}"
                ),
            }

    return {"success": False, "error": "Ferramenta não reconhecida"}
