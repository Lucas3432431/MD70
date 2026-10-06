"""
Html.py - Tool logic for HTML dashboard/report generation
"""

import json
from typing import Dict, Any
from App.Core.Logs import error

_MAX_HTML_BYTES = 512 * 1024  # 512 KB


def execute_html(args: Dict[str, Any]) -> str:
    try:
        title = args.get("title", "").strip()
        html = args.get("html", "").strip()

        if not title or not html:
            return json.dumps(
                {"success": False, "error": "title e html são campos obrigatórios."},
                ensure_ascii=False,
            )

        if len(html.encode("utf-8")) > _MAX_HTML_BYTES:
            return json.dumps(
                {"success": False, "error": "HTML excede o limite de 512 KB."},
                ensure_ascii=False,
            )

        return json.dumps(
            {"success": True, "tool": "html", "title": title, "html": html},
            ensure_ascii=False,
        )

    except Exception as e:
        error(f"[HTML] Erro ao processar html tool: {e}")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
