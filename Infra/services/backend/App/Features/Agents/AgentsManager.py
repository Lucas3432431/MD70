"""
AgentsManager - Gerencia agents disponíveis do arquivo AGENTS.json
Adaptado do AgentX para MD70 com suporte a paralelização de agents
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from App.Core.Logs import debug, error, warning
from App.Core.Crunch.Storage.StorageManager import StorageManager


class AgentsManager:
    """Gerencia o carregamento e acesso de agents disponíveis do arquivo JSON."""

    def __init__(self, agents_json_path: Path):
        """
        Inicializa o gerenciador de agents.

        Args:
            agents_json_path: Caminho para o arquivo AGENTS.json
        """
        self.agents_json_path = Path(agents_json_path)
        self.agents_cache = None
        self.last_load_time = None
        rel_path = StorageManager.get_relative_path(self.agents_json_path)
        debug(f"AgentsManager inicializado com arquivo: {rel_path}")

    def _load_agents_from_file(self) -> List[Dict[str, Any]]:
        """Carrega agents do arquivo JSON. Quebra o servidor se houver erro."""
        try:
            if not self.agents_json_path.exists():
                rel_path = StorageManager.get_relative_path(self.agents_json_path)
                raise FileNotFoundError(f"Arquivo de agents não encontrado: {rel_path}")

            with open(self.agents_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                agents = data.get("agents", []) if isinstance(data, dict) else data
                debug(f"Carregados {len(agents)} agents do arquivo")
                return agents

        except json.JSONDecodeError as e:
            rel_path = StorageManager.get_relative_path(self.agents_json_path)
            error(f"Erro ao parsear JSON do arquivo {rel_path}: {e}")
            raise
        except FileNotFoundError as e:
            error(f"Arquivo de agents não encontrado: {e}")
            raise
        except Exception as e:
            rel_path = StorageManager.get_relative_path(self.agents_json_path)
            error(f"Erro ao carregar agents do arquivo {rel_path}: {e}")
            raise

    def list_agents(self) -> List[Dict[str, Any]]:
        """
        Lista todos os agents disponíveis.

        Returns:
            Lista de agents com suas informações completas
        """
        agents = self._load_agents_from_file()
        return agents

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Obtém um agent específico pelo ID.

        Args:
            agent_id: ID do agent

        Returns:
            Dados do agent ou None se não encontrado
        """

        def find_agent_recursive(
            agents_list: List[Dict], target_id: str
        ) -> Optional[Dict]:
            for agent in agents_list:
                if agent.get("id") == target_id:
                    return agent
                # Procura em sub_agents se existirem
                if "sub_agents" in agent and agent["sub_agents"]:
                    found = find_agent_recursive(agent["sub_agents"], target_id)
                    if found:
                        return found
            return None

        agents = self._load_agents_from_file()
        return find_agent_recursive(agents, agent_id)

    def get_agent_children(self, agent_id: str) -> List[Dict[str, Any]]:
        """
        Obtém os sub-agents de um agent específico.

        Args:
            agent_id: ID do agent pai

        Returns:
            Lista de sub-agents
        """
        agent = self.get_agent(agent_id)
        if agent and "sub_agents" in agent:
            return agent["sub_agents"]
        return []

    def flatten_agents(
        self, agents: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Achata a hierarquia de agents mantendo todas as informações.
        Útil para listar todos os agents sem hierarquia.

        Args:
            agents: Lista de agents (se None, carrega do arquivo)

        Returns:
            Lista de agents achatada (sem sub_agents)
        """
        if agents is None:
            agents = self._load_agents_from_file()

        flattened = []

        def flatten_recursive(agents_list: List[Dict]):
            for agent in agents_list:
                # Cria cópia sem sub_agents
                agent_copy = {k: v for k, v in agent.items() if k != "sub_agents"}
                flattened.append(agent_copy)

                # Processa sub_agents recursivamente
                if "sub_agents" in agent and agent["sub_agents"]:
                    flatten_recursive(agent["sub_agents"])

        flatten_recursive(agents)
        return flattened

    def get_agents_for_parallel_execution(self, agent_id: str) -> List[Dict[str, Any]]:
        """
        Obtém agentes que devem ser executados em paralelo.
        Específico para MD70: alguns agentes podem ter uma lista de sub-agents
        que devem ser executados simultaneamente.

        Args:
            agent_id: ID do agent pai

        Returns:
            Lista de agents a serem executados em paralelo
        """
        agent = self.get_agent(agent_id)
        if not agent:
            return []

        # Se o agent tem "parallel_agents", retorna eles
        parallel_agents = agent.get("parallel_agents", [])
        if parallel_agents:
            # parallel_agents pode conter IDs ou configurações
            result = []
            for parallel_config in parallel_agents:
                if isinstance(parallel_config, str):
                    # É um ID, procura o agent
                    sub_agent = self.get_agent(parallel_config)
                    if sub_agent:
                        result.append(sub_agent)
                else:
                    # É uma configuração, trata como agent
                    result.append(parallel_config)
            return result

        return []
