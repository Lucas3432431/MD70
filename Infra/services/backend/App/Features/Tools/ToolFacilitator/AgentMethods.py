"""
Métodos para manipulação e listagem de agentes.
"""

import json
from pathlib import Path
from typing import List, Dict, Optional, Set, Any
from App.Core.Logs import debug, info, warning, error


def load_agents_from_json(base_dir) -> list:
    """Carrega agents direto do AGENTS.json com estrutura aninhada preservada."""
    try:
        agents_file = base_dir / "Data" / "Agents" / "AGENTS.json"
        with open(agents_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("agents", [])
    except Exception as e:
        error(f"[load_agents_from_json] {str(e)}")
        return []


def flatten_agents(agents_list: list, parent_id: str = None) -> list:
    """Achata recursivamente a lista de agents preservando o parent_id."""
    flattened = []
    for agent in agents_list:
        agent_copy = dict(agent)
        agent_copy["parent_id"] = parent_id
        flattened.append(agent_copy)
        if "sub_agents" in agent and agent["sub_agents"]:
            flattened.extend(flatten_agents(agent["sub_agents"], agent.get("id")))
    return flattened


def get_accessible_agent_ids(
    caller_agent_id: Optional[str],
    base_dir: Path,
    agent_manager: Any = None,
    debug_mode: bool = False,
) -> Set[str]:
    """
    Retorna IDs de agents acessíveis baseado na hierarquia.
    - "user" é mapeado para ASSISTANT (manager-001) para determinar acessibilidade
    - Cada agent acessa: sub_agents + brothers + parent primário
    """
    try:
        # Carregar agents JSON diretamente
        all_agents_raw = load_agents_from_json(base_dir)
        debug(
            f"[get_accessible_agent_ids] Carregado {len(all_agents_raw)} agents raw para caller: {caller_agent_id}"
        )
        if not all_agents_raw:
            debug(f"[get_accessible_agent_ids] all_agents_raw está vazio")
            return set()

        # Achata todos os agents
        all_agents_flat = flatten_agents(all_agents_raw)
        debug(f"[get_accessible_agent_ids] Achata {len(all_agents_flat)} agents")

        # Se caller é None, retorna set vazio (sem contexto)
        if caller_agent_id is None:
            debug(
                f"[get_accessible_agent_ids] caller_agent_id is None, retornando set vazio"
            )
            return set()

        # Mapeia "user" para ASSISTANT (manager-001) - chamadas do usuário via API
        if caller_agent_id == "user":
            caller_agent_id = "manager-001"
            debug(
                f"[get_accessible_agent_ids] 'user' mapeado para ASSISTANT (manager-001)"
            )

        # Achar o agent chamador na estrutura achatada
        caller = next(
            (a for a in all_agents_flat if a.get("id") == caller_agent_id), None
        )

        if not caller:
            return set()

        accessible = set()

        # 1. Sub_agents diretos
        accessible.update({a["id"] for a in caller.get("sub_agents", [])})

        # 2. Parent primário
        if caller.get("parent_id"):
            accessible.add(caller["parent_id"])

        # 3. Brothers (mesmo parent)
        if caller.get("parent_id"):
            parent = next(
                (a for a in all_agents_flat if a.get("id") == caller["parent_id"]), None
            )
            if parent:
                accessible.update({a["id"] for a in parent.get("sub_agents", [])})

        # ⚠️ SEGURANÇA: Remove SECURITY_OFFICER da lista acessível
        # SECURITY_OFFICER é um supervisor/validador, não deve receber mensagens diretas
        accessible.discard("security-officer-001")

        return accessible

    except Exception as e:
        error(f"[get_accessible_agent_ids] {str(e)}")
        debug(f"[get_accessible_agent_ids] Traceback:\n{str(e)}")
        return set()
