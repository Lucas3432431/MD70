"""Configuration loading for agent session management."""

import json
from pathlib import Path
from typing import Dict, Any
from App.Core.Logs import debug, warning, error

BASE_DIR = Path(__file__).parent.parent.parent.parent.parent.parent


class ConfigLoader:
    """Gerencia carregamento de configurações de agents."""

    @staticmethod
    def load_agents_config() -> Dict[str, Any]:
        """
        Carrega configurações dos agents do arquivo AGENTS.json

        Returns:
            Dict com configurações dos agents
        """
        try:
            agents_file = BASE_DIR / "Data" / "Agents" / "AGENTS.json"

            if agents_file.exists():
                with open(agents_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    debug(
                        f"Configurações de agents carregadas: ./Data/Agents/AGENTS.json"
                    )
                    return config
            else:
                warning(
                    f"Arquivo AGENTS.json não encontrado em: ./Data/Agents/AGENTS.json"
                )
                return {"agents": []}
        except Exception as e:
            error(f"Erro ao carregar AGENTS.json: {str(e)}")
            return {"agents": []}

    @staticmethod
    def find_agent_system_prompt(
        agent_id: str, agents_config: Dict[str, Any]
    ) -> str | None:
        """
        Busca o system_prompt de um agent pelo ID (busca recursiva em agents e sub_agents)

        Args:
            agent_id: ID do agent
            agents_config: Configuração de agents carregada

        Returns:
            System prompt do agent ou None
        """
        if not agents_config or "agents" not in agents_config:
            return None

        def search_in_agents(agents_list):
            """Busca recursiva em agents e sub_agents"""
            for agent in agents_list:
                if agent.get("id") == agent_id:
                    return agent.get("system_prompt")
                # Busca em sub_agents se existir
                if "sub_agents" in agent:
                    result = search_in_agents(agent["sub_agents"])
                    if result:
                        return result
            return None

        return search_in_agents(agents_config.get("agents", []))
