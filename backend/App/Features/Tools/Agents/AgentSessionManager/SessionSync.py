"""Session synchronization to main history."""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
from App.Core.Logs import debug, error
from App.Core.Crunch.TablesSQL.Models import AgentSession
from .FileManager import FileManager


class SessionSync:
    """Gerencia sincronização de sessões de volta ao histórico principal."""

    def __init__(self, chat_manager):
        """
        Inicializa o sincronizador.

        Args:
            chat_manager: Gerenciador de chats
        """
        self.chat_manager = chat_manager

    def sync_session_to_history(
        self,
        session: AgentSession,
        main_history: List[Dict],
        tool_call_id: str,
        tool_name: str = "agent",
    ) -> List[Dict]:
        """
        Sincroniza resultado da sessão de volta ao histórico principal.

        Este método:
        1. Extrai todas as tool results da sessão do agent
        2. Adiciona essas tool results ao histórico principal
        3. Inclui a resposta final do agent com sua metadata

        Args:
            session: AgentSession completada
            main_history: Histórico principal do chat
            tool_call_id: ID da tool call original
            tool_name: Nome da ferramenta

        Returns:
            Histórico atualizado
        """
        try:
            debug(f"===== INICIANDO SYNC_SESSION_TO_HISTORY =====")
            debug(f"Session ID: {session.session_id} | Agent: {session.agent_name}")
            debug(f"tool_call_id={tool_call_id}, tool_name={tool_name}")

            # Carrega histórico ATUALIZADO do arquivo do agent
            updated_agent_history = self._load_updated_agent_history(session)

            # Sincroniza PAIRS (assistant + tool) da sessão do agent
            if updated_agent_history:
                self._sync_agent_messages(session, updated_agent_history, main_history)

            # Extrai resultado final do agent
            result_content = self._extract_final_result(session, updated_agent_history)

            # Salva resposta final no arquivo do caller
            self._save_final_response(session, tool_call_id, tool_name, result_content)

            debug(f"Sessão sincronizada: {session.agent_name}")
            debug(f"Histórico agora tem {len(main_history)} mensagens")

            return main_history

        except Exception as e:
            error(f"Erro ao sincronizar sessão: {str(e)}")
            return main_history

    def _load_updated_agent_history(self, session: AgentSession) -> List[Dict]:
        """Carrega o histórico atualizado do arquivo do agent."""
        updated_agent_history = session.agent_history

        if not self.chat_manager.current_chat_id:
            return updated_agent_history

        try:
            chat_folder = (
                Path(self.chat_manager.chats_dir)
                / f"chat_{self.chat_manager.current_chat_id}"
            )
            agent_file = chat_folder / f"{session.agent_name}.json"

            if agent_file.exists():
                with open(agent_file, "r", encoding="utf-8") as f:
                    agent_data = json.load(f)
                    updated_agent_history = agent_data.get(
                        "messages", session.agent_history
                    )
                    debug(
                        f"Carregado histórico atualizado do {session.agent_name}.json: {len(updated_agent_history)} mensagens"
                    )
        except Exception as e:
            debug(f"Erro ao carregar histórico do agent: {e}")

        return updated_agent_history

    def _sync_agent_messages(
        self,
        session: AgentSession,
        updated_agent_history: List[Dict],
        main_history: List[Dict],
    ) -> None:
        """Sincroniza mensagens de assistant e tool da sessão."""
        # [CRÍTICO] NUNCA sincroniza mensagens de agent de volta ao histórico principal
        # Isso previne loops onde agent calls internas contaminem o histórico do caller
        # Exemplo: Se ELON faz agent call para CHAIRMEN dentro de sua sessão,
        # essa agent call NÃO deve voltar ao histórico de CHAIRMEN (causaria loop)
        #
        # A ÚNICA coisa sincronizada é o resultado final via tool message na linha 224
        debug(
            f"[SessionSync] {session.agent_name}: pulando sincronização de mensagens (mantém isolamento total)"
        )
        return

    def _extract_final_result(
        self, session: AgentSession, updated_agent_history: List[Dict]
    ) -> str:
        """Extrai a resposta final do agent."""
        result_content = None

        if updated_agent_history:
            debug(
                f"Procurando resposta final em {len(updated_agent_history)} mensagens"
            )
            for msg in reversed(updated_agent_history):
                if msg.get("role") == "assistant" and not msg.get("tool_calls"):
                    result_content = msg.get("content", "")
                    debug(
                        f"Encontrada resposta final: {len(result_content)} caracteres"
                    )
                    break

        # Se não encontrou, usa session.result
        if not result_content:
            if session.status == "completed":
                result_content = session.result
            else:
                result_content = f"[ERRO] {session.error}"

        return result_content

    def _save_final_response(
        self,
        session: AgentSession,
        tool_call_id: str,
        tool_name: str,
        result_content: str,
    ) -> None:
        """Salva a resposta final do agent no arquivo do caller."""
        if not self.chat_manager.current_chat_id:
            debug(f"current_chat_id é None, não salvando resposta final")
            return

        try:
            assistant_chat_folder = (
                Path(self.chat_manager.chats_dir)
                / f"chat_{self.chat_manager.current_chat_id}"
            )
            assistant_file = assistant_chat_folder / "ASSISTANT.json"

            debug(f"Tentando salvar em: {assistant_file}")

            if assistant_file.exists():
                with open(assistant_file, "r", encoding="utf-8") as f:
                    assistant_data = json.load(f)

                debug(
                    f"ASSISTANT.json carregado, {len(assistant_data.get('messages', []))} mensagens"
                )

                # Adiciona resposta do agent como tool message
                tool_response_msg = {
                    "role": "tool",
                    "content": result_content,
                    "tool_call_id": tool_call_id,
                    "name": tool_name,
                    "agent_name": "ASSISTANT",
                    "agent_id": "manager-001",
                    "timestamp": datetime.now().isoformat(),
                }

                assistant_data["messages"].append(tool_response_msg)

                with open(assistant_file, "w", encoding="utf-8") as f:
                    json.dump(assistant_data, f, indent=2, ensure_ascii=False)

                debug(
                    f"✓ Resposta do agent {session.agent_name} salva em ASSISTANT.json"
                )

                # Notifica o job
                if (
                    hasattr(self.chat_manager, "current_job")
                    and self.chat_manager.current_job
                ):
                    self.chat_manager.current_job.mark_agent_save_complete()
            else:
                debug(f"ASSISTANT.json NÃO ENCONTRADO em {assistant_file}")

        except Exception as e:
            error(f"Erro ao salvar resposta final: {str(e)}")
