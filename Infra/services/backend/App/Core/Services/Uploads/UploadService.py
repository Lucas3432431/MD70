"""
UploadService.py - Serviço de gerenciamento de uploads
Contém lógica de negócio para uploads, limpeza, compressão
"""

from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import shutil

from App.Core.Logs import debug, info, warning, error
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Crunch.Storage.StorageManager import StorageManager


class UploadService:
    """Serviço centralizado de gerenciamento de uploads"""

    @staticmethod
    def cleanup_expired_sessions(hours: int = 24) -> Dict[str, int]:
        """
        Limpa sessions e attachments expirados.

        Args:
            hours: Quantas horas para considerar expirado

        Returns:
            Dict com contagem de deletados
        """
        try:
            cutoff_time = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

            # 1. Buscar sessions expiradas
            query = """
            SELECT id, session_id, client_id FROM sessions WHERE expires_at < :cutoff_time
            """

            expired_sessions = DatabaseManager.fetch_all(
                query, {"cutoff_time": cutoff_time}
            )
            session_count = len(expired_sessions)

            # 2. Para cada session expirada, deletar arquivos e registros
            deleted_files = 0
            for session in expired_sessions:
                session_id = session.get("session_id")
                client_id = session.get("client_id")

                # Buscar attachments
                attach_query = """
                SELECT * FROM attachments WHERE session_id = :session_id AND deleted_at IS NULL
                """

                attachments = DatabaseManager.fetch_all(
                    attach_query, {"session_id": session_id}
                )

                for attach in attachments:
                    storage_path = Path(attach.get("storage_path"))
                    if storage_path.exists():
                        try:
                            storage_path.unlink()
                            deleted_files += 1
                            debug(f"[CLEANUP] Arquivo deletado: {storage_path}")
                        except Exception as e:
                            warning(f"[CLEANUP] Erro ao deletar {storage_path}: {e}")

                    # Soft delete no DB
                    delete_query = """
                    UPDATE attachments SET deleted_at = CURRENT_TIMESTAMP
                    WHERE attachment_id = :attachment_id
                    """
                    try:
                        DatabaseManager.execute_query(
                            delete_query, {"attachment_id": attach.get("attachment_id")}
                        )
                    except Exception as e:
                        error(f"[CLEANUP] Erro ao atualizar DB: {e}")

                # Deletar session
                session_delete_query = (
                    "DELETE FROM sessions WHERE session_id = :session_id"
                )
                try:
                    DatabaseManager.execute_query(
                        session_delete_query, {"session_id": session_id}
                    )
                except Exception as e:
                    error(f"[CLEANUP] Erro ao deletar session: {e}")

            info(
                f"[CLEANUP] Limpeza concluída: {session_count} sessions, {deleted_files} arquivos"
            )

            return {"sessions_cleaned": session_count, "files_deleted": deleted_files}

        except Exception as e:
            error(f"[CLEANUP] Erro ao limpar: {e}")
            return {"error": str(e)}

    @staticmethod
    def cleanup_orphaned_attachments() -> Dict[str, int]:
        """
        Limpa attachments órfãos (sem chat_id ou message_id válidos).

        Returns:
            Dict com contagem de deletados
        """
        try:
            # Buscar attachments órfãos (chat_id não existe em chats)
            query = """
            SELECT a.* FROM attachments a
            LEFT JOIN chats c ON a.chat_id = c.chat_id
            WHERE a.deleted_at IS NULL AND a.chat_id IS NOT NULL AND c.chat_id IS NULL
            """

            orphaned = DatabaseManager.fetch_all(query, {})
            deleted_count = 0

            for attach in orphaned:
                storage_path = Path(attach.get("storage_path"))
                if storage_path.exists():
                    try:
                        storage_path.unlink()
                        deleted_count += 1
                        debug(f"[CLEANUP] Arquivo órfão deletado: {storage_path}")
                    except Exception as e:
                        warning(f"[CLEANUP] Erro ao deletar {storage_path}: {e}")

                # Soft delete
                delete_query = """
                UPDATE attachments SET deleted_at = CURRENT_TIMESTAMP
                WHERE attachment_id = :attachment_id
                """
                try:
                    DatabaseManager.execute_query(
                        delete_query, {"attachment_id": attach.get("attachment_id")}
                    )
                except Exception as e:
                    error(f"[CLEANUP] Erro ao atualizar DB: {e}")

            info(f"[CLEANUP] Attachments órfãos deletados: {deleted_count}")

            return {"orphaned_deleted": deleted_count}

        except Exception as e:
            error(f"[CLEANUP] Erro ao limpar órfãos: {e}")
            return {"error": str(e)}

    @staticmethod
    def cleanup_empty_folders(client_id: int) -> Dict[str, int]:
        """
        Remove pastas vazias de uploads.

        Args:
            client_id: ID do cliente

        Returns:
            Dict com contagem de pastas removidas
        """
        try:
            base_path = StorageManager.LOCAL_STORAGE_BASE / f"client_{client_id}"

            if not base_path.exists():
                return {"folders_removed": 0}

            removed_count = 0

            # Percorrer pastas recursivamente
            for folder in base_path.rglob("*"):
                if folder.is_dir():
                    try:
                        # Verificar se está vazia
                        if not list(folder.iterdir()):
                            folder.rmdir()
                            removed_count += 1
                            debug(f"[CLEANUP] Pasta vazia removida: {folder}")
                    except Exception as e:
                        debug(f"[CLEANUP] Não foi possível remover {folder}: {e}")

            info(f"[CLEANUP] Pastas vazias removidas: {removed_count}")

            return {"folders_removed": removed_count}

        except Exception as e:
            error(f"[CLEANUP] Erro ao limpar pastas: {e}")
            return {"error": str(e)}

    @staticmethod
    def move_attachment_to_chat(
        attachment_id: str, chat_id: str, message_id: str, client_id: int
    ) -> bool:
        """
        Move um attachment de temporário para persistente (em um chat específico).

        Args:
            attachment_id: ID do attachment
            chat_id: ID do chat destino
            message_id: ID da mensagem destino
            client_id: ID do cliente

        Returns:
            True se sucesso, False caso contrário
        """
        try:
            # Buscar attachment atual
            query = """
            SELECT * FROM attachments WHERE attachment_id = :attachment_id AND user_id = :user_id
            """

            attachment = DatabaseManager.fetch_one(
                query, {"attachment_id": attachment_id, "user_id": client_id}
            )

            if not attachment:
                error(f"[MOVE] Attachment não encontrado: {attachment_id}")
                return False

            # Caminho antigo e novo
            old_path = Path(attachment.get("storage_path"))
            base_path = StorageManager.LOCAL_STORAGE_BASE
            new_path = (
                base_path / f"client_{client_id}" / chat_id / message_id / old_path.name
            )

            # Garantir que a pasta de destino existe
            new_path.parent.mkdir(parents=True, exist_ok=True)

            # Mover arquivo
            try:
                shutil.move(str(old_path), str(new_path))
                debug(f"[MOVE] Arquivo movido: {old_path} → {new_path}")
            except Exception as e:
                error(f"[MOVE] Erro ao mover arquivo: {e}")
                return False

            # Atualizar DB
            update_query = """
            UPDATE attachments
            SET chat_id = :chat_id, message_id = :message_id, session_id = NULL, is_temp = 0, storage_path = :storage_path
            WHERE attachment_id = :attachment_id
            """

            try:
                DatabaseManager.execute_query(
                    update_query,
                    {
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "storage_path": str(new_path),
                        "attachment_id": attachment_id,
                    },
                )
                info(f"[MOVE] Attachment movido para chat: {attachment_id}")
                return True
            except Exception as e:
                error(f"[MOVE] Erro ao atualizar DB: {e}")
                return False

        except Exception as e:
            error(f"[MOVE] Erro geral: {e}")
            return False

    @staticmethod
    def get_attachment_info(attachment_id: str, client_id: int) -> Optional[Dict]:
        """
        Obtém informações completas de um attachment.

        Args:
            attachment_id: ID do attachment
            client_id: ID do cliente

        Returns:
            Dict com informações ou None
        """
        try:
            query = """
            SELECT * FROM attachments WHERE attachment_id = :attachment_id AND user_id = :user_id AND deleted_at IS NULL
            """

            return DatabaseManager.fetch_one(
                query, {"attachment_id": attachment_id, "user_id": client_id}
            )

        except Exception as e:
            error(f"[GET-INFO] Erro: {e}")
            return None

    @staticmethod
    def get_chat_attachments(chat_id: str, client_id: int) -> List[Dict]:
        """
        Lista todos os attachments de um chat.

        Args:
            chat_id: ID do chat
            client_id: ID do cliente

        Returns:
            Lista de attachments
        """
        try:
            query = """
            SELECT * FROM attachments
            WHERE chat_id = :chat_id AND client_id = :client_id AND deleted_at IS NULL
            ORDER BY uploaded_at DESC
            """

            return DatabaseManager.fetch_all(
                query, {"chat_id": chat_id, "client_id": client_id}
            )

        except Exception as e:
            error(f"[GET-CHAT] Erro: {e}")
            return []

    @staticmethod
    def get_session_attachments(session_id: str, client_id: int) -> List[Dict]:
        """
        Lista todos os attachments temporários de uma session.

        Args:
            session_id: ID da session
            client_id: ID do cliente

        Returns:
            Lista de attachments
        """
        try:
            query = """
            SELECT * FROM attachments
            WHERE session_id = :session_id AND client_id = :client_id AND deleted_at IS NULL
            ORDER BY uploaded_at DESC
            """

            return DatabaseManager.fetch_all(
                query, {"session_id": session_id, "client_id": client_id}
            )

        except Exception as e:
            error(f"[GET-SESSION] Erro: {e}")
            return []
