"""
Graphs.py - Tool logic for structured graph data generation
"""

import json
from typing import Dict, Any, List
from App.Core.Logs import debug, error


def execute_graph_visualization(args: Dict[str, Any]) -> str:
    """
    Processa e valida dados para visualização gráfica.
    Como é uma inline tool voltada para o frontend, o objetivo principal aqui
    é validação e estruturação uniforme.
    """
    try:
        chart_type = args.get("chart_type")
        title = args.get("title")
        data = args.get("data")

        if not chart_type or not title or not data:
            return json.dumps(
                {
                    "success": False,
                    "error": "chart_type, title e data são campos obrigatórios.",
                },
                ensure_ascii=False,
            )

        if not isinstance(data, list):
            return json.dumps(
                {
                    "success": False,
                    "error": "O campo 'data' deve ser um array de objetos.",
                },
                ensure_ascii=False,
            )

        # Retorna os dados estruturados para o frontend
        return json.dumps(
            {
                "success": True,
                "tool": "create_graph_visualization",
                "chart_type": chart_type,
                "title": title,
                "xAxisLabel": args.get("xAxisLabel", ""),
                "yAxisLabel": args.get("yAxisLabel", ""),
                "data": data,
            },
            ensure_ascii=False,
        )

    except Exception as e:
        error(f"[GRAPHS] Erro ao processar visualização: {e}")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
