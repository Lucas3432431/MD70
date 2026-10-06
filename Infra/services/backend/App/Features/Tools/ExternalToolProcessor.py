"""
ExternalToolProcessor - Processa resultados de external tools de forma isolada
Responsável por salvar apenas o OUTPUT (resultado) sem conflitos de constraint
"""

import json
import uuid
from typing import Optional, Any, Dict
from App.Core.Logs import debug, error, info
from App.Core.Crunch import DatabaseManager


class ExternalToolProcessor:
    """Processa e salva resultados de external tools"""

    def __init__(self, db_manager=None):
        self.db_manager = db_manager or DatabaseManager

    def save_tool_output(
        self,
        tool_call_id: str,
        isolated_chat_id: str,
        agent_id: str,
        result: str,
        tool_name: str,
        session=None,
    ) -> Optional[Dict[str, Any]]:
        """
        Salva APENAS o OUTPUT (resultado) de uma external tool

        O INPUT já foi salvo pelo MessageProcessor com o tool_call_id original
        Aqui criamos um novo isolated_message_id para o OUTPUT

        Args:
            tool_call_id: ID original da chamada (INPUT)
            isolated_chat_id: ID do chat isolado
            agent_id: ID do agente
            result: Resultado da tool (JSON string ou dict)
            tool_name: Nome da tool
            session: Sessão SQLAlchemy (opcional)

        Returns:
            Dict com dados do OUTPUT salvo ou None em caso de erro
        """
        try:
            # Gerar novo UUID para o OUTPUT (diferente do INPUT)
            output_message_id = str(uuid.uuid4())

            debug(f"[ExternalToolProcessor] Salvando OUTPUT de {tool_name}")
            debug(f"  - tool_call_id (INPUT): {tool_call_id}")
            debug(f"  - output_message_id (OUTPUT): {output_message_id}")

            # Salvar OUTPUT com novo UUID
            self.db_manager.save_isolated_message(
                session=session,
                isolated_chat_id=isolated_chat_id,
                agent_id=agent_id,
                agent=agent_id,
                role="user",
                content=result,
                message_type="tool_call",
                isolated_message_id=output_message_id,  # NOVO UUID para OUTPUT
                tool_call_id=tool_call_id,  # Referencia o INPUT original
                tool_called=tool_name,
                tool_call_type="output",
            )

            info(f"[ExternalToolProcessor] ✅ OUTPUT salvo: {output_message_id}")
            return {
                "success": True,
                "input_message_id": tool_call_id,
                "output_message_id": output_message_id,
                "tool_name": tool_name,
            }

        except Exception as e:
            error(f"[ExternalToolProcessor] ❌ Erro ao salvar OUTPUT: {e}")
            return None
