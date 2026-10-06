"""Query methods for agent sessions."""

from typing import Dict, Any, List, Optional
from App.Core.Logs import debug
from App.Core.Crunch.TablesSQL.Models import AgentSession


class SessionQueries:
    """Gerencia consultas de status e informações de sessões."""

    def __init__(self, sessions: Dict[str, AgentSession]):
        """
        Inicializa o gerenciador de consultas.

        Args:
            sessions: Dicionário de sessões (referência)
        """
        self.sessions = sessions

    def get_session(self, session_id: str) -> Optional[AgentSession]:
        """Retorna sessão pelo ID"""
        return self.sessions.get(session_id)

    def get_session_status(self, session_id: str) -> Dict[str, Any]:
        """
        Retorna status de uma sessão.

        Args:
            session_id: ID da sessão

        Returns:
            Dict com informações de status
        """
        session = self.get_session(session_id)
        if not session:
            return {"error": f"Sessão {session_id} não encontrada"}

        return {
            "session_id": session.session_id,
            "agent_id": session.agent_id,
            "agent_name": session.agent_name,
            "status": session.status,
            "iterations": session.iterations,
            "tools_executed": session.tools_executed,
            "started_at": session.started_at,
            "completed_at": session.completed_at,
            "result": session.result[:100] + "..." if session.result else None,
        }

    def list_sessions(self) -> List[Dict[str, Any]]:
        """
        Lista todas as sessões conhecidas.

        Returns:
            Lista de status de sessões
        """
        return [self.get_session_status(sid) for sid in self.sessions.keys()]

    def cleanup_session(self, session_id: str) -> None:
        """
        Remove sessão (para limpeza após sincronização).

        Args:
            session_id: ID da sessão a remover
        """
        if session_id in self.sessions:
            del self.sessions[session_id]
            debug(f"Sessão {session_id} removida")
