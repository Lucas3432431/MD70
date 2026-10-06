"""
Gerenciador de banco de dados híbrido (local + cloud).

ARQUITETURA:
- Produção: Todas operações usam DB local (SQLite com WAL)
- Leituras (GET): Apenas local (sem sync com cloud)
- Backups via Litestream (WAL file watching)
"""

from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session

from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Logs import debug, error


class HybridDBManager:
    """Gerenciador híbrido que delega para DatabaseManager (SQLite local)"""

    def __init__(self):
        self.db = DatabaseManager

    # ==================== READ OPERATIONS (LOCAL ONLY) ====================

    @staticmethod
    def get_session() -> Session:
        """Obter sessão (local apenas)"""
        return DatabaseManager.get_session()

    @staticmethod
    def get_client(session: Session, client_id: int):
        """Buscar cliente (local apenas)"""
        return DatabaseManager.get_client(session, client_id)

    @staticmethod
    def get_user_by_email(session: Session, email: str):
        """Buscar usuário por email (local apenas)"""
        return DatabaseManager.get_user_by_email(session, email)

    @staticmethod
    def get_access_token(session: Session, token_id: str):
        """Buscar access token (local apenas)"""
        return DatabaseManager.get_access_token(session, token_id)

    @staticmethod
    def get_refresh_token(session: Session, token_id: str):
        """Buscar refresh token (local apenas)"""
        return DatabaseManager.get_refresh_token(session, token_id)

    @staticmethod
    def get_chat_sql(session: Session, chat_id: str):
        """Buscar chat (local apenas)"""
        return DatabaseManager.get_chat_sql(session, chat_id)

    @staticmethod
    def get_client_chats(session: Session, client_id: int) -> List:
        """Listar chats do cliente (local apenas)"""
        return DatabaseManager.get_client_chats(session, client_id)

    @staticmethod
    def get_chat_messages_sql(session: Session, chat_id: str) -> List:
        """Listar mensagens do chat (local apenas)"""
        return DatabaseManager.get_chat_messages_sql(session, chat_id)

    @staticmethod
    def get_file_by_hash(session: Session, file_hash: str):
        """Buscar arquivo por hash (local apenas)"""
        return DatabaseManager.get_file_by_hash(session, file_hash)

    @staticmethod
    def get_file_by_id(session: Session, file_id: str):
        """Buscar arquivo por ID (local apenas)"""
        return DatabaseManager.get_file_by_id(session, file_id)

    @staticmethod
    def get_chat_files(
        session: Session, chat_id: str, file_category: str = None
    ) -> List:
        """Listar arquivos do chat (local apenas)"""
        return DatabaseManager.get_chat_files(session, chat_id, file_category)

    @staticmethod
    def get_client_files(
        session: Session, client_id: int, file_category: str = None, chat_id: str = None
    ) -> List:
        """Listar arquivos do cliente (local apenas)"""
        return DatabaseManager.get_client_files(
            session, client_id, file_category, chat_id
        )

    @staticmethod
    def get_chat_tasks(session: Session, chat_id: str, status: str = None) -> List:
        """Listar tasks (local apenas)"""
        return DatabaseManager.get_chat_tasks(session, chat_id, status)

    @staticmethod
    def get_task_by_name_step(
        session: Session, chat_id: str, task_name: str, step_name: str
    ):
        """Buscar task por nome e step (local apenas)"""
        return DatabaseManager.get_task_by_name_step(
            session, chat_id, task_name, step_name
        )

    # ==================== WRITE OPERATIONS ====================

    def create_client(self, session: Session, client_data: dict):
        """Criar cliente"""
        return DatabaseManager.create_client(session, client_data)

    def create_user(self, session: Session, user_data: dict):
        """Criar usuário"""
        return DatabaseManager.create_user(session, user_data)

    def save_access_token(
        self,
        session: Session,
        token_id: str,
        user_id: int,
        client_id: int,
        token_hash: str,
        expires_at,
    ) -> bool:
        """Salvar access token"""
        return DatabaseManager.save_access_token(
            session, token_id, user_id, client_id, token_hash, expires_at
        )

    def revoke_access_token(self, session: Session, token_id: str) -> bool:
        """Revogar access token"""
        return DatabaseManager.revoke_access_token(session, token_id)

    def save_refresh_token(
        self,
        session: Session,
        token_id: str,
        user_id: int,
        client_id: int,
        token_hash: str,
        expires_at,
    ) -> bool:
        """Salvar refresh token"""
        return DatabaseManager.save_refresh_token(
            session, token_id, user_id, client_id, token_hash, expires_at
        )

    def revoke_refresh_token(self, session: Session, token_id: str) -> bool:
        """Revogar refresh token"""
        return DatabaseManager.revoke_refresh_token(session, token_id)

    def create_chat(self, session: Session, chat_data: dict):
        """Criar chat"""
        return DatabaseManager.create_chat(session, chat_data)

    def create_message(self, session: Session, message_data: dict):
        """Criar mensagem"""
        return DatabaseManager.create_message(session, message_data)

    def save_ai_message(
        self, session: Session, chat_id: str, content: str, model: str = "gpt-4o-mini"
    ):
        """Salvar mensagem IA"""
        return DatabaseManager.save_ai_message(session, chat_id, content, model)

    def save_file_record(self, session: Session, file_data: dict) -> bool:
        """Registrar arquivo"""
        return DatabaseManager.save_file_record(session, file_data)

    def mark_file_deleted(self, session: Session, file_id: str) -> bool:
        """Marcar arquivo como deletado"""
        return DatabaseManager.mark_file_deleted(session, file_id)

    def save_task(
        self,
        session: Session,
        task_id: str,
        chat_id: str,
        client_id: int,
        task_name: str,
        step_name: str,
        status: str,
    ) -> bool:
        """Salvar task"""
        return DatabaseManager.save_task(
            session, task_id, chat_id, client_id, task_name, step_name, status
        )

    # ==================== PASSTHROUGH METHODS ====================

    @staticmethod
    def get_or_create_isolated_chat(
        session: Session, chat_id: str, user_id: str, agent_id: str
    ):
        """Criar chat isolado"""
        return DatabaseManager.get_or_create_isolated_chat(
            session, chat_id, user_id, agent_id
        )

    @staticmethod
    def save_isolated_message(
        session: Session,
        isolated_chat_id: int,
        agent_id: str,
        agent: str,
        role: str,
        content: str,
        message_type: str = "message",
        message_uuid: Optional[str] = None,
    ):
        """Salvar mensagem isolada"""
        return DatabaseManager.save_isolated_message(
            session,
            isolated_chat_id,
            agent_id,
            agent,
            role,
            content,
            message_type,
            message_uuid,
        )

    @staticmethod
    def get_isolated_messages(session: Session, isolated_chat_id: str) -> List:
        """Listar mensagens isoladas (local apenas)"""
        return DatabaseManager.get_isolated_messages(session, isolated_chat_id)

    @staticmethod
    def sync_isolated_to_main(session: Session, chat_id: str, agent_id: str):
        """Sincronizar chat isolado para main"""
        return DatabaseManager.sync_isolated_to_main(session, chat_id, agent_id)

    @staticmethod
    def sync_mediaai_tool_to_main(
        session: Session,
        chat_id: str,
        client_id: int,
        media_type: str,
        model: str,
        filename: str,
    ) -> bool:
        """Sincronizar mediaai tool"""
        return DatabaseManager.sync_mediaai_tool_to_main(
            session, chat_id, client_id, media_type, model, filename
        )

    @staticmethod
    def update_external_tool_result(
        session: Session,
        chat_id: str,
        client_id: int,
        tool_call_id: str,
        result_content: str,
    ) -> bool:
        """Atualizar resultado de external tool"""
        return DatabaseManager.update_external_tool_result(
            session, chat_id, client_id, tool_call_id, result_content
        )
