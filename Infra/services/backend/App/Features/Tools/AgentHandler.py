"""
AgentHandler.py - Processa chamadas de agent para agent
Permite um agent chamar outro agent para delegar tarefas
"""

import uuid
import json
from typing import Optional, Dict, Any
from App.Core.Logs import debug, error


class AgentHandler:
    """Handler para execução de chamadas entre agents."""

    def __init__(
        self,
        message_processor=None,
        chat_manager=None,
        agents_manager=None,
        db_manager=None,
    ):
        self.message_processor = message_processor
        self.chat_manager = chat_manager
        self.agents_manager = agents_manager
        self.db_manager = db_manager

    def _find_agent_fuzzy(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Busca um agent usando fuzzy matching (ID exato, nome parcial, etc).

        Args:
            query: String com o ID ou nome do agent

        Returns:
            Agent encontrado ou None
        """
        # 1. Tenta ID exato
        agent = self.agents_manager.get_agent(query)
        if agent:
            return agent

        # 2. Tenta match case-insensitive no ID
        all_agents = self.agents_manager.flatten_agents()
        query_lower = query.lower().strip()

        for agent in all_agents:
            if agent.get("id", "").lower() == query_lower:
                return agent

        # 3. Tenta match no nome (case-insensitive)
        for agent in all_agents:
            agent_name = agent.get("name", "").lower()
            if agent_name == query_lower:
                return agent

        # 4. Tenta match parcial no ID (contém o query)
        for agent in all_agents:
            if query_lower in agent.get("id", "").lower():
                return agent

        # 5. Tenta match parcial no nome
        for agent in all_agents:
            if query_lower in agent.get("name", "").lower():
                return agent

        return None

    def handle_agent_call(
        self,
        target_agent_id: str,
        message: str,
        caller_agent_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Processa uma chamada de um agent para outro agent.

        Args:
            target_agent_id: ID do agent a ser chamado
            message: Mensagem para o agent (deve conter task_name no início)
            caller_agent_id: ID do agent que chamou
            chat_id: ID do chat (opcional)
            user_id: ID do usuário (opcional)

        Returns:
            Dict com resultado da execução
        """
        try:
            debug(
                f"[AGENT_CALL] {caller_agent_id} → {target_agent_id}: {message[:50]}..."
            )

            # Se não houver task_name, chamar task-namer para gerar
            if not message:
                return {
                    "success": False,
                    "tool": "agent",
                    "error": "Mensagem vazia",
                    "agent_id": target_agent_id,
                }

            # Validar dependências
            if not self.message_processor:
                return {
                    "success": False,
                    "tool": "agent",
                    "error": "MessageProcessor não configurado",
                }

            if not self.agents_manager:
                return {
                    "success": False,
                    "tool": "agent",
                    "error": "AgentsManager não configurado",
                }

            if not self.chat_manager:
                return {
                    "success": False,
                    "tool": "agent",
                    "error": "ChatManager não configurado",
                }

            # Verificar se target agent existe (com fuzzy matching)
            target_agent = self._find_agent_fuzzy(target_agent_id)
            if not target_agent:
                # Listar agents disponíveis para sugestão
                all_agents = self.agents_manager.flatten_agents()
                available_ids = [a.get("id") for a in all_agents]
                return {
                    "success": False,
                    "tool": "agent",
                    "error": f"Agent '{target_agent_id}' não encontrado. Agents disponíveis: {', '.join(available_ids)}",
                }

            # Usar o ID real do agent encontrado
            actual_agent_id = target_agent.get("id")

            # Criar nova sessão para o agent chamado
            session_id = self.chat_manager.create_session()
            debug(f"[AGENT_CALL] Sessão criada: {session_id}")

            session = self.chat_manager.get_session(session_id)
            if session:
                session.chat_id = chat_id or f"agent-call-{uuid.uuid4()}"

            # Processar mensagem com o agent alvo (passa chat_id e client_id para sincronização correta)
            result = self.message_processor.process_message(
                session_id=session_id,
                user_message=message,
                agent_id=actual_agent_id,
                chat_id=chat_id,
                client_id=client_id,
            )

            # Extrair resposta e tokens
            response = (
                result.response
                if hasattr(result, "response")
                else result.get("response", "")
            )
            success = (
                result.success
                if hasattr(result, "success")
                else result.get("success", False)
            )
            error_msg = (
                result.error if hasattr(result, "error") else result.get("error", "")
            )
            tokens_used = (
                result.tokens_used
                if hasattr(result, "tokens_used")
                else result.get("tokens_used", {})
            )
            input_tokens = tokens_used.get("input", 0) if tokens_used else 0
            output_tokens = tokens_used.get("output", 0) if tokens_used else 0

            debug(
                f"[AGENT_CALL] Resposta de {actual_agent_id}: success={success}, {response[:50]}..."
            )

            # Se houve erro, retorna sem salvar a conversa
            if not success:
                error(f"[AGENT_CALL] Agent {actual_agent_id} failed: {error_msg}")
                return {
                    "success": False,
                    "tool": "agent",
                    "agent_id": actual_agent_id,
                    "response": response,
                    "error": error_msg or "Agent execution failed",
                    "model": target_agent.get("model", "unknown"),
                }

            # Salvar conversa do sub agent em isolated_messages (se DB está disponível)
            if self.db_manager and chat_id and user_id:
                try:
                    debug(
                        f"[AGENT_CALL] Saving sub-agent conversation: chat={chat_id}, agent={actual_agent_id}"
                    )

                    # Extrair content legível da mensagem (remove task_name e limpa JSON)
                    message_content = message
                    if "task_name:" in message.lower():
                        lines = message.split("\n")
                        message_content = "\n".join(
                            [l for l in lines if "task_name:" not in l.lower()]
                        ).strip()

                    # Tentar extrair conteúdo legível se for JSON
                    try:
                        parsed = json.loads(message_content)
                        if isinstance(parsed, dict) and "message" in parsed:
                            message_content = parsed["message"]
                    except:
                        pass

                    # Extrair task_name da mensagem original OU gerar via task_namer na primeira execução
                    task_name = "Sub-agent Task"
                    if "task_name:" in message.lower():
                        try:
                            lines = message.split("\n")
                            for line in lines:
                                if "task_name:" in line.lower():
                                    task_name = line.split(":", 1)[1].strip()
                                    break
                        except:
                            pass

                    # Agora obter sessão e criar/obter isolated_chat
                    db_session = self.db_manager.get_session()

                    # Criar ou obter isolated_chat para o sub agent
                    isolated_chat = self.db_manager.get_or_create_isolated_chat(
                        session=db_session,
                        chat_id=chat_id,
                        user_id=user_id,
                        agent_id=actual_agent_id,
                    )
                    debug(
                        f"[AGENT_CALL] Isolated chat {isolated_chat.id} created/retrieved for {actual_agent_id}"
                    )

                    # Apenas salvar resposta do agent no chat isolado do agent
                    agent_name = target_agent.get("name", actual_agent_id)

                    # Salvar resposta do agent como mensagem regular
                    self.db_manager.save_isolated_message(
                        session=db_session,
                        isolated_chat_id=isolated_chat.chat_id,
                        agent_id=actual_agent_id,
                        agent=agent_name,
                        role="assistant",
                        content=response,
                        message_type="message",
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
                    debug(f"[AGENT_CALL] Agent response saved for {actual_agent_id}")

                    db_session.commit()
                    db_session.close()

                except Exception as e:
                    error(f"[AGENT_CALL] Error saving sub agent conversation: {e}")
                    import traceback

                    error(traceback.format_exc())

            return {
                "success": success,
                "tool": "agent",
                "agent_id": actual_agent_id,
                "response": response,
                "model": target_agent.get("model", "unknown"),
            }

        except Exception as e:
            error(f"[AGENT_CALL] Erro ao chamar {target_agent_id}: {e}")
            import traceback

            error(traceback.format_exc())
            return {
                "success": False,
                "tool": "agent",
                "error": f"Erro ao chamar agent: {str(e)}",
                "agent_id": target_agent_id,
            }
