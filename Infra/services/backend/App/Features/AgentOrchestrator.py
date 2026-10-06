"""
Orquestrador de Agentes - Coordena a comunicação com múltiplos agents
Envia a mensagem do usuário APENAS para o orchestrator (coordenador)
O orchestrator coordena as tarefas dos sub-agents através de tools
"""

from typing import Optional, Dict, Any
from App.Core.Logs import debug, info, error


class AgentOrchestrator:
    """
    Orquestrador que processa mensagens do usuário.
    Não dispara múltiplos agentes diretamente.
    Ao invés disso, envia a mensagem para o orchestrator/coordenador
    que tem acesso a uma tool para encaminhar para sub-agents.
    """

    def __init__(self, message_processor, chat_service, agents_config=None):
        """
        Inicializa o orquestrador.

        Args:
            message_processor: Processador de mensagens (IA)
            chat_service: Serviço de chat para salvar mensagens
            agents_config: Configuração de agentes (não usado no fluxo atual)
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
        job,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Orquestra o processamento da mensagem do usuário.
        Envia a mensagem APENAS para o orchestrador/coordenador.

        Args:
            user_message: Mensagem do usuário
            chat_id: ID do chat
            client_id: ID do cliente
            session_id: ID da sessão
            job: Objeto do job para tracking
            **kwargs: Argumentos adicionais

        Returns:
            Dict com resultado do processamento
        """
        try:
            debug(
                f"[ORCHESTRATOR] Iniciando orquestração",
                undefined=None,
                data={
                    "chat_id": chat_id,
                    "user_message": user_message[:100],
                },
            )

            # Processa a mensagem com o orchestrator
            # O orchestrator é uma IA que tem acesso a tools para encaminhar para sub-agents
            response = self.message_processor.process_message(
                user_message=user_message,
                chat_id=chat_id,
                client_id=client_id,
                session_id=session_id,
                job=job,
            )

            info(
                f"[ORCHESTRATOR] Processamento concluído",
                undefined=None,
                data={"chat_id": chat_id},
            )

            return {
                "success": True,
                "response": response,
                "chat_id": chat_id,
            }

        except Exception as e:
            error(f"[ORCHESTRATOR] Erro ao orquestrar: {e}")
            import traceback

            error(traceback.format_exc())

            return {
                "success": False,
                "error": str(e),
                "chat_id": chat_id,
            }
