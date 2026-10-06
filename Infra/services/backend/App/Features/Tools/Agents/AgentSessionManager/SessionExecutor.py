"""Session creation and execution logic."""

import traceback
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
from App.Core.Logs import debug, error, info
from App.Core.Crunch.TablesSQL.Models import AgentSession
from .PromptManager import PromptManager
from .FileManager import FileManager
from .ConfigLoader import ConfigLoader


class SessionExecutor:
    """Gerencia criação e execução de sessões isoladas de agents."""

    def __init__(self, llm_client, chat_manager, tool_facilitator, agent_manager):
        """
        Inicializa o executor de sessões.

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
        self.session_counter = 0
        self.agents_config = ConfigLoader.load_agents_config()

    def create_session(
        self,
        agent_id: str,
        agent_name: str,
        task: str,
        conversation_history: List[Dict],
        caller_agent_id: Optional[str] = None,
    ) -> AgentSession:
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
        self.session_counter += 1
        session_id = f"{agent_id}-{self.session_counter}"

        # Extract main system prompt from conversation_history or config
        main_system_prompt = None

        # Tenta primeiro extrair do histórico da conversa
        if conversation_history and len(conversation_history) > 0:
            first_msg = conversation_history[0]
            if first_msg.get("role") == "system":
                main_system_prompt = first_msg.get("content")

        # Se não encontrou no histórico, carrega do config
        if not main_system_prompt:
            try:
                from App.Core.Settings.Settings import load_config

                config = load_config()
                main_system_prompt = config.get("system_prompt")
                if main_system_prompt:
                    info(
                        f"System prompt geral carregado do config para sessão {session_id}"
                    )
            except Exception as e:
                debug(f"Erro ao carregar system_prompt do config: {e}")

        # Get agent-specific system prompt
        agent_system_prompt = ConfigLoader.find_agent_system_prompt(
            agent_id, self.agents_config
        )

        # Combine system prompts
        combined_system_prompt = PromptManager.combine_system_prompts(
            main_system_prompt, agent_system_prompt, agent_name
        )

        agent_history = [
            {
                "role": "system",
                "content": combined_system_prompt,
                "timestamp": datetime.now().isoformat(),
            }
        ]

        session = AgentSession(
            session_id=session_id,
            agent_id=agent_id,
            agent_name=agent_name,
            caller_agent_id=caller_agent_id,
            task=task,
            started_at=datetime.now().isoformat(),
            agent_history=agent_history,
        )

        debug(f"Sessão criada: {session_id}")
        debug(
            f"Agent: {agent_name} | Histórico: {len(agent_history)} msgs | Tarefa: {task[:50]}..."
        )

        return session

    def execute_session(
        self, session: AgentSession, agent_llm_client=None, max_iterations: int = 25
    ) -> Dict[str, Any]:
        """
        Executa um agent em sua sessão isolada.

        Este método:
        1. Salva o histórico principal do chat_manager
        2. Substitui pelo histórico isolado da sessão
        3. Executa o agent com seu próprio contexto
        4. Restaura o histórico principal

        Args:
            session: AgentSession a executar
            agent_llm_client: LLMClient específico do agent (se None, usa o global)
            max_iterations: Limite de iterações do loop

        Returns:
            Dict com resultado da execução
        """
        try:
            session.status = "in_progress"
            debug(f"Executando sessão: {session.session_id}")

            # Importa aqui para evitar circular imports
            from App.Features.MessageProcessor import MessageProcessor

            # Salva o histórico principal E o arquivo principal (thread-safe)
            with self.chat_manager.history_lock:
                saved_conversation_history = self.chat_manager.conversation_history
                saved_chat_file = self.chat_manager.current_chat_file
                self.chat_manager.conversation_history = session.agent_history

            # Muda o current_chat_file para o arquivo do agent
            if self.chat_manager.current_chat_id:
                chat_folder = (
                    Path(self.chat_manager.chats_dir)
                    / f"chat_{self.chat_manager.current_chat_id}"
                )
                agent_chat_file = chat_folder / f"{session.agent_name}.json"
                self.chat_manager.current_chat_file = agent_chat_file
                debug(f"Current chat file alterado para: {agent_chat_file}")

            debug(
                f"Substituído histórico para sessão isolada: {len(session.agent_history)} msgs"
            )

            # Cria arquivo limpo do agent
            FileManager.create_clean_agent_file(
                session.agent_name,
                session.agent_id,
                (
                    session.agent_history[0].get("content")
                    if session.agent_history
                    and session.agent_history[0].get("role") == "system"
                    else None
                ),
                self.chat_manager,
            )

            # Obtém informações do caller
            caller_agent_name = "ASSISTANT"
            caller_agent_id = session.caller_agent_id or "manager-001"

            if (
                session.caller_agent_id
                and hasattr(self, "agent_manager")
                and self.agent_manager
            ):
                caller_agent = self.agent_manager.get_agent(session.caller_agent_id)
                if caller_agent:
                    caller_agent_name = getattr(caller_agent, "name", "ASSISTANT")

            # Save: Em agent.json como "user"
            self.chat_manager.save_message(
                role="user",
                content=session.task,
                agent_name=session.agent_name,
                agent_id=session.agent_id,
                _from_agent_name=caller_agent_name,
                _from_agent_id=caller_agent_id,
            )

            try:
                # Usa agent_llm_client se fornecido, caso contrário usa o global
                llm_client_to_use = (
                    agent_llm_client
                    if agent_llm_client is not None
                    else self.llm_client
                )

                # Cria MessageProcessor com histórico isolado
                processor = MessageProcessor(
                    llm_client=llm_client_to_use,
                    chat_manager=self.chat_manager,
                    tool_facilitator=self.tool_facilitator,
                )

                # Executa completamente
                result = processor.process_message(
                    user_message=session.task,
                    agent_id=session.agent_id,
                    max_iterations=max_iterations,
                    user_message_already_saved=True,
                )

                # Atualiza sessão com resultado
                session.result = result.get("response", "")
                session.iterations = result.get("iterations", 0)
                session.tools_executed = result.get("tool_calls_executed", 0)
                session.completed_at = datetime.now().isoformat()
                session.status = "completed" if result.get("success") else "failed"

                debug(f"Sessão completa: {session.session_id}")

                return {
                    "success": True,
                    "session_id": session.session_id,
                    "agent_id": session.agent_id,
                    "agent_name": session.agent_name,
                    "result": session.result,
                    "iterations": session.iterations,
                    "tools_executed": session.tools_executed,
                    "timestamp": session.completed_at,
                }

            except Exception as e:
                error_msg = f"Erro ao executar sessão {session.session_id}: {str(e)}"
                error(f"{error_msg}")

                session.error = error_msg
                session.status = "failed"
                session.completed_at = datetime.now().isoformat()

                return {
                    "success": False,
                    "session_id": session.session_id,
                    "agent_id": session.agent_id,
                    "agent_name": session.agent_name,
                    "error": error_msg,
                    "timestamp": session.completed_at,
                }

            finally:
                # Restaura histórico principal (thread-safe)
                with self.chat_manager.history_lock:
                    self.chat_manager.conversation_history = saved_conversation_history
                    self.chat_manager.current_chat_file = saved_chat_file
                debug(
                    f"Histórico e arquivo principais restaurados: {len(saved_conversation_history)} msgs"
                )

        except Exception as e:
            error_msg = f"Erro ao executar sessão {session.session_id}: {str(e)}"
            error(f"{error_msg}\n{traceback.format_exc()}")

            session.error = error_msg
            session.status = "failed"
            session.completed_at = datetime.now().isoformat()

            return {
                "success": False,
                "session_id": session.session_id,
                "agent_id": session.agent_id,
                "agent_name": session.agent_name,
                "error": error_msg,
                "timestamp": session.completed_at,
            }
