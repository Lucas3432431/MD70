"""Core AgentSessionManager - Coordena todas as sessões de agentes."""

from typing import Dict, Any, List, Optional
from .SessionExecutor import SessionExecutor
from .SessionSync import SessionSync
from .SessionQueries import SessionQueries
from .ConfigLoader import ConfigLoader


class AgentSessionManager:
    """Gerenciador central de sessões de agentes isoladas."""

    def __init__(self, llm_client, chat_manager, tool_facilitator, agent_manager):
        """
        Inicializa o gerenciador de sessões.

        Args:
            llm_client: Cliente LLM
            chat_manager: Gerenciador de chats
            tool_facilitator: Facilitador de ferramentas
            agent_manager: Gerenciador de agentes
        """
        self.llm_client = llm_client
        self.chat_manager = chat_manager
        self.tool_facilitator = tool_facilitator
        self.agent_manager = agent_manager

        # Armazenar sessões ativas
        self.active_sessions: Dict[str, Any] = {}

        # Inicializar componentes
        self.executor = SessionExecutor(
            llm_client, chat_manager, tool_facilitator, agent_manager
        )
        self.sync = SessionSync(chat_manager)
        self.queries = SessionQueries(self.active_sessions)

    def create_session(
        self,
        agent_id: str,
        agent_name: str,
        task: str,
        conversation_history: List[Dict],
        caller_agent_id: Optional[str] = None,
    ) -> Any:
        """
        Cria uma nova sessão isolada para execução de agent.

        Args:
            agent_id: ID do agent a executar
            agent_name: Nome do agent
            task: Tarefa/prompt a executar
            conversation_history: Histórico da conversa principal
            caller_agent_id: ID do agent que chamou

        Returns:
            AgentSession com contexto isolado criado
        """
        session = self.executor.create_session(
            agent_id=agent_id,
            agent_name=agent_name,
            task=task,
            conversation_history=conversation_history,
            caller_agent_id=caller_agent_id,
        )

        # Armazenar sessão
        self.active_sessions[session.session_id] = session
        return session

    def execute_session(
        self, session: Any, agent_llm_client=None, max_iterations: int = 25
    ) -> Dict[str, Any]:
        """
        Executa um agent em sua sessão isolada.

        Args:
            session: AgentSession a executar
            agent_llm_client: LLMClient específico do agent (se None, usa o global)
            max_iterations: Limite de iterações do loop

        Returns:
            Dict com resultado da execução
        """
        return self.executor.execute_session(session, agent_llm_client, max_iterations)

    def sync_session_to_history(
        self,
        session: Any,
        main_history: List[Dict],
        tool_call_id: str,
        tool_name: str = "agent",
    ) -> List[Dict]:
        """
        Sincroniza resultado da sessão de volta ao histórico principal.

        Args:
            session: AgentSession completada
            main_history: Histórico principal do chat
            tool_call_id: ID da tool call original que disparou o agent
            tool_name: Nome da ferramenta que foi chamada

        Returns:
            Histórico atualizado
        """
        updated_history = self.sync.sync_session_to_history(
            session=session,
            main_history=main_history,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
        )

        # Remover sessão do cache após sincronizar
        if session.session_id in self.active_sessions:
            del self.active_sessions[session.session_id]

        return updated_history

    def get_session_status(self, session_id: str) -> Dict[str, Any]:
        """
        Obtém status de uma sessão.

        Args:
            session_id: ID da sessão

        Returns:
            Status da sessão
        """
        return self.queries.get_session_status(session_id)

    def list_active_sessions(self) -> List[Dict[str, Any]]:
        """
        Lista todas as sessões ativas.

        Returns:
            Lista de sessões ativas
        """
        return self.queries.list_sessions()

    def _find_agent_system_prompt(self, agent_id: str) -> Optional[str]:
        """
        [BACKWARD COMPATIBILITY] Wrapper para ConfigLoader.find_agent_system_prompt

        Permite que código antigo que chama este método continue funcionando.

        Args:
            agent_id: ID do agent

        Returns:
            System prompt do agent ou None
        """
        agents_config = self.executor.agents_config
        return ConfigLoader.find_agent_system_prompt(agent_id, agents_config)
