"""
Agent Orchestrator - Coordena a comunicação com o orchestrator/assistente principal.
Envia a mensagem do usuário APENAS para o orchestrator que coordena tarefas via tools.
"""

from typing import Dict, Any, Optional
from datetime import datetime

from App.Core.Logs import debug, info, error


class AgentOrchestrator:
    """
    Orquestrador que processa mensagens do usuário através do orchestrator/assistente principal.
    O orchestrator tem acesso a tools para encaminhar mensagens para sub-agents com task names.
    """

    def __init__(
        self, message_processor, chat_service, agents_config: Dict[str, Any] = None
    ):
        """
        Inicializa o orquestrador.

        Args:
            message_processor: Instância de MessageProcessor para processar mensagens
            chat_service: Instância de ChatService para salvar resultados
            agents_config: Configuração dos agentes (não utilizado no fluxo atual)
        """
        self.message_processor = message_processor
        self.chat_service = chat_service
        self.agents_config = agents_config

    def orchestrate(
        self,
        user_message: str,
        chat_id: str,
        client_id: int,
        session_id: str,
        job=None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Orquestra o processamento da mensagem do usuário.
        Envia a mensagem APENAS para o orchestrador/assistente principal.

        Args:
            user_message: Mensagem do usuário
            chat_id: ID do chat
            client_id: ID do cliente
            session_id: ID da sessão
            job: Job para rastreamento de progresso
            **kwargs: Argumentos adicionais

        Returns:
            Dict com resultado do processamento do orchestrador
        """
        try:
            debug(f"[ORCHESTRATOR] Iniciando orquestração para chat {chat_id}")

            # Processa a mensagem com o orchestrator/assistente principal
            # O orchestrator é uma IA que tem acesso a tools para encaminhar para sub-agents
            result = self.message_processor.process_message(
                job_id=(
                    job.job_id if job else session_id
                ),  # Use job_id from job object if available
                user_message=user_message,
                agent_id="orchestrator-global",
                chat_id=chat_id,
                client_id=client_id,
                job=job,  # Passa o job para marcar como completo quando resposta final é salva
            )

            # Extrai a resposta do orchestrator
            response = (
                result.response
                if hasattr(result, "response")
                else result.get("response", "")
            )
            model = (
                result.model
                if hasattr(result, "model")
                else result.get("model", "gpt-4o")
            )

            # Nota: Resposta do orchestrator já é salva via isolated_messages no MessageProcessor
            debug(f"[ORCHESTRATOR] Resposta do orchestrator processada")

            info(f"[ORCHESTRATOR] Processamento concluído para chat {chat_id}")

            success = (
                result.success
                if hasattr(result, "success")
                else result.get("success", True)
            )
            tool_calls = (
                len(result.tool_calls)
                if hasattr(result, "tool_calls") and result.tool_calls
                else 0
            )

            return {
                "success": success,
                "response": response,
                "chat_id": chat_id,
                "tool_calls": tool_calls,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            error(f"[ORCHESTRATOR] Erro ao orquestrar: {e}")
            import traceback

            error(traceback.format_exc())

            return {
                "success": False,
                "error": str(e),
                "chat_id": chat_id,
                "timestamp": datetime.now().isoformat(),
            }
