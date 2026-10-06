"""
DataTables.py - Tool logic for structured data tables generation
"""

import json
from typing import Dict, Any, List
from App.Core.Logs import debug, error


def execute_data_table(args: Dict[str, Any]) -> str:
    """
    Processa e valida dados para tabelas estruturadas.
    """
    try:
        title = args.get("title")
        columns = args.get("columns")
        rows = args.get("rows")

        if not title or not columns or not rows:
            return json.dumps(
                {
                    "success": False,
                    "error": "title, columns e rows são campos obrigatórios.",
                },
                ensure_ascii=False,
            )

        if not isinstance(columns, list) or not isinstance(rows, list):
            return json.dumps(
                {
                    "success": False,
                    "error": "Os campos 'columns' e 'rows' devem ser arrays.",
                },
                ensure_ascii=False,
            )

        # Retorna os dados estruturados para o frontend
        return json.dumps(
            {
                "success": True,
                "tool": "generate_data_table",
                "title": title,
                "columns": columns,
                "rows": rows,
            },
            ensure_ascii=False,
        )

    except Exception as e:
        error(f"[DATATABLES] Erro ao processar tabela: {e}")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
