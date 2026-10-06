"""Provider Google Analytics para MCP nativo."""
from typing import Dict, Any, List
import httpx

from ._shared import _TokenExpiredError, _refresh_access_token

TOOL_DEFINITIONS: List[Dict] = [
    {
        "name": "mcp__google-analytics__get_report",
        "description": "[GOOGLE-ANALYTICS] Obtém relatório GA4 com métricas e dimensões customizadas.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Data de início: '7daysAgo', '30daysAgo', 'YYYY-MM-DD'",
                },
                "end_date": {
                    "type": "string",
                    "description": "Data de fim: 'today', 'yesterday', 'YYYY-MM-DD'",
                },
                "metrics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Métricas: sessions, activeUsers, screenPageViews, bounceRate, averageSessionDuration, newUsers",
                },
                "dimensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Dimensões (opcional): country, city, pagePath, deviceCategory, sessionSource",
                },
                "property_id": {
                    "type": "string",
                    "description": "ID da propriedade GA4 (ex: 123456789), se não configurado na integração",
                },
            },
            "required": ["start_date", "end_date", "metrics"],
        },
    },
]


async def call(tool_name: str, args: Dict, env: Dict) -> Dict:
    access_token = env.get("GANALYTICS_ACCESS_TOKEN", "")
    refresh_token = env.get("GANALYTICS_REFRESH_TOKEN", "")
    client_id_oauth = env.get("GANALYTICS_CLIENT_ID", "")
    client_secret = env.get("GANALYTICS_CLIENT_SECRET", "")
    property_id = args.get("property_id") or env.get("GANALYTICS_PROPERTY_ID", "")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

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
            if resp.status_code in (401, 403):
                raise _TokenExpiredError(str(resp.status_code))
            return resp

        if tool_name == "get_report":
            if not property_id:
                return {
                    "success": False,
                    "error": "property_id é obrigatório (configure na integração ou passe como argumento)",
                }

            start_date = args.get("start_date", "7daysAgo")
            end_date = args.get("end_date", "today")
            metrics_list = args.get("metrics", ["sessions", "activeUsers"])
            dimensions_list = args.get("dimensions", [])

            body = {
                "dateRanges": [{"startDate": start_date, "endDate": end_date}],
                "metrics": [{"name": m} for m in metrics_list],
            }
            if dimensions_list:
                body["dimensions"] = [{"name": d} for d in dimensions_list]

            resp = await _refresh_and_retry(
                lambda h: http.post(
                    f"https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport",
                    headers=h,
                    json=body,
                )
            )
            data = resp.json()
            if resp.status_code != 200:
                return {
                    "success": False,
                    "error": data.get("error", {}).get(
                        "message", str(resp.status_code)
                    ),
                }

            rows = data.get("rows", [])
            metric_headers = [h["name"] for h in data.get("metricHeaders", [])]
            dim_headers = [h["name"] for h in data.get("dimensionHeaders", [])]

            lines = []
            for row in rows[:50]:
                dims = " | ".join(v["value"] for v in row.get("dimensionValues", []))
                metrics_vals = " | ".join(
                    f"{metric_headers[i]}: {v['value']}"
                    for i, v in enumerate(row.get("metricValues", []))
                )
                lines.append(f"{dims} → {metrics_vals}" if dims else metrics_vals)

            return {
                "success": True,
                "content": f"Relatório GA4 ({start_date} → {end_date}):\n"
                + "\n".join(lines),
                "row_count": len(rows),
            }

    return {"success": False, "error": "Ferramenta não reconhecida"}
