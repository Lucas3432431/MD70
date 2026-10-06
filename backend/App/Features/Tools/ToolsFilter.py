# APPs/Voicebot/modules/tools_filter.py
"""
Sistema de filtro de tools baseado no status de plans aprovados.
Libera task_tools somente quando um agent tem um plan aprovado.
"""

from typing import List, Optional, Dict, Any


class ToolsFilter:
    """Gerencia o acesso a task_tools baseado em plans aprovados."""

    def __init__(self, plan_manager=None):
        """
        Inicializa o filtro de tools.
        plan_manager: (Deprecated) Not used in MD70
        """
        pass

    def get_available_tools(self, agent_config: Any, agent_id: str) -> List[str]:
        """
        Retorna a lista de tools disponíveis para um agent.

        Usa AGENTS.json como fonte de verdade:
        - default_tools (sempre disponíveis)
        - task_tools (apenas se tiver plan aprovado)

        Args:
            agent_config: Configuração do agent (do AGENTS.json)
            agent_id: ID do agent

        Returns:
            Lista de tools disponíveis
        """
        tools = set()

        # Default tools do agent (FONTE DE VERDADE: AGENTS.json)
        if hasattr(agent_config, "tools") and agent_config.tools:
            default_tools = agent_config.tools.get("default_tools", [])
            tools.update(default_tools)

            # Task tools (sempre disponíveis agora que não há verificação de plano)
            task_tools = agent_config.tools.get("task_tools", [])
            tools.update(task_tools)

        return sorted(list(tools))

    def can_use_tool(
        self, agent_id: str, tool_name: str, agent_config: Any
    ) -> tuple[bool, Optional[str]]:
        """
        Verifica se um agent pode usar uma ferramenta específica.

        Usa AGENTS.json como fonte de verdade para decidir quais tools estão disponíveis.

        Args:
            agent_id: ID do agent
            tool_name: Nome da ferramenta
            agent_config: Configuração do agent

        Returns:
            Tuple (pode_usar, motivo_se_não)
        """
        available_tools = self.get_available_tools(agent_config, agent_id)

        if tool_name in available_tools:
            return True, None

        return False, f"Tool '{tool_name}' não está disponível para este agent"

    def format_available_tools_message(
        self, agent_id: str, agent_name: str, agent_config: Any
    ) -> str:
        """
        Formata uma mensagem com as tools disponíveis para um agent.

        Args:
            agent_id: ID do agent
            agent_name: Nome do agent
            agent_config: Configuração do agent

        Returns:
            String formatada com as tools
        """
        available_tools = self.get_available_tools(agent_config, agent_id)

        message = f"\n[{agent_name}] Tools Disponíveis:\n"
        message += f"  [OK] {', '.join(available_tools)}\n"

        return message
