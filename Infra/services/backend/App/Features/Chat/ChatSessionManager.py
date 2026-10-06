"""Gerenciador de sessões de chat no banco de dados"""

import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List
from sqlalchemy import text
from App.Core.Logs import info, debug, error, warning


class ChatSessionManager:
    """Gerencia operações de criação, listagem e manipulação de chats no banco"""

    def __init__(self, database):
        """Inicializa o gerenciador de sessões de chat"""
        self.db = database
        self._message_coordinator = None  # Cache para MessageCoordinator
        debug(f"[CHAT-SESSION] ChatSessionManager inicializado")

    def _get_message_coordinator(self):
        """Obtém MessageCoordinator (lazy loading para evitar import circular)"""
        if self._message_coordinator is None:
            from .MessageCoordinator import MessageCoordinator

            self._message_coordinator = MessageCoordinator(self.db)
        return self._message_coordinator

    def create_chat(
        self,
        client_id: int,
        chat_name: str,
        message: Optional[str] = None,
        model: str = "gpt-4o-mini",
    ) -> Dict[str, Any]:
        """Cria um novo chat"""
        try:
            chat_id = str(uuid.uuid4())
            debug(
                f"[CHAT-SESSION] Criando chat: id={chat_id}, name={chat_name}, client={client_id}"
            )

            def create_chat_transaction(conn):
                # Criar chat
                debug(f"[CHAT-SESSION] Executando INSERT na tabela chats")
                result = conn.execute(
                    text(
                        """
                    INSERT INTO chats (chat_id, client_id, chat_name, created_at, updated_at, status)
                    VALUES (:chat_id, :client_id, :chat_name, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'active')
                """
                    ),
                    {
                        "chat_id": chat_id,
                        "client_id": client_id,
                        "chat_name": chat_name,
                    },
                )
                debug(
                    f"[CHAT-SESSION] INSERT executado, rows affected: {result.rowcount}"
                )
                return chat_id

            chat_id = self.db.execute_with_connection(create_chat_transaction)

            # Verificar se realmente foi inserido
            check_query = "SELECT chat_id FROM chats WHERE chat_id = :chat_id"
            check_result = self.db.fetch_one(check_query, {"chat_id": chat_id})

            if check_result:
                debug(f"[CHAT-SESSION] Chat criado e verificado: {chat_id}")
            else:
                error(
                    f"[CHAT-SESSION] ERRO: Chat criado mas não encontrado após inserção: {chat_id}"
                )

            response = {
                "chat_id": chat_id,
                "chat_name": chat_name,
                "created_at": datetime.now().isoformat(),
                "message": "Conversa criada com sucesso",
            }

            return response

        except Exception as e:
            error(f"[CHAT-SESSION] Erro ao criar chat: {e}")
            raise

    def get_chats(
        self, client_id: int, limit: int = 20, offset: int = 0
    ) -> Dict[str, Any]:
        """Lista todos os chats do usuário"""
        try:
            debug(f"[CHAT-SESSION] Buscando chats para cliente {client_id}")

            # Verificar estrutura da tabela
            columns = self.db.get_table_columns("chats")
            if not columns:
                return self._empty_chats_response(limit, offset)

            # Construir query dinâmica
            select_cols = self._get_chat_select_columns(columns)

            query = f"""
                SELECT {', '.join([f'c.{col}' if col != '*' else 'c.*' for col in select_cols])}
                FROM chats c
                JOIN users u ON c.user_id = u.user_id
                WHERE u.client_id = :client_id
                ORDER BY COALESCE(c.updated_at, c.created_at, datetime('1970-01-01')) DESC
                LIMIT :limit OFFSET :offset
            """

            chats = self.db.fetch_all(
                query, {"client_id": client_id, "limit": limit, "offset": offset}
            )

            # Normalizar dados dos chats
            normalized_chats = [self._normalize_chat_data(chat) for chat in chats]

            # Contar total
            count_query = """
                SELECT COUNT(*) as total FROM chats c
                JOIN users u ON c.user_id = u.user_id
                WHERE u.client_id = :client_id
            """
            total_result = self.db.fetch_one(count_query, {"client_id": client_id})
            total_count = total_result.get("total", 0) if total_result else 0

            debug(f"[CHAT-SESSION] {len(normalized_chats)} chats encontrados")

            return {
                "chats": normalized_chats,
                "total": total_count,
                "pagination": {
                    "limit": limit,
                    "offset": offset,
                    "hasMore": (offset + len(normalized_chats)) < total_count,
                },
            }

        except Exception as e:
            error(f"[CHAT-SESSION] Erro ao listar chats: {e}")
            return self._empty_chats_response(limit, offset)

    def get_chat(self, chat_id: str, client_id: int) -> Dict[str, Any]:
        """Obtém um chat específico"""
        try:
            debug(f"[CHAT-SESSION] Buscando chat {chat_id} para cliente {client_id}")

            # Obter dados do chat
            columns = self.db.get_table_columns("chats")
            if not columns:
                raise ValueError("Tabela chats não encontrada")

            select_cols = self._get_chat_select_columns(columns)
            query = f"""
                SELECT {', '.join(select_cols)}
                FROM chats
                WHERE chat_id = :chat_id AND client_id = :client_id
            """

            chat_data = self.db.fetch_one(
                query, {"chat_id": chat_id, "client_id": client_id}
            )

            if not chat_data:
                debug(
                    f"[CHAT-SESSION] Chat não encontrado: chat_id={chat_id}, client_id={client_id}"
                )
                raise ValueError("Conversa não encontrada ou sem permissão")

            # Normalizar dados
            chat_data = self._normalize_chat_data(chat_data)

            # Obter mensagens usando MessageCoordinator
            message_coordinator = self._get_message_coordinator()
            messages = message_coordinator.get_chat_messages(chat_id, client_id)
            chat_data["messages"] = messages

            # Obter documentos se a tabela existir
            documents = []
            if self.db.table_exists("documents"):
                doc_query = """
                    SELECT
                        document_id as id,
                        title,
                        extension,
                        link,
                        COALESCE(type, 'unknown') as type,
                        description
                    FROM documents
                    WHERE chat_id = :chat_id AND client_id = :client_id
                    ORDER BY created_at ASC
                """
                try:
                    documents = self.db.fetch_all(
                        doc_query, {"chat_id": chat_id, "client_id": client_id}
                    )
                except Exception as e:
                    debug(f"[CHAT-SESSION] Erro ao buscar documentos: {e}")

            chat_data["documents"] = documents

            info(
                f"[CHAT-SESSION] Chat carregado: {chat_id} com {len(messages)} mensagens e {len(documents)} documentos"
            )

            return chat_data

        except ValueError as ve:
            # Re-raise para ser tratado pelo coordinator
            raise
        except Exception as e:
            error(f"[CHAT-SESSION] Erro ao buscar chat: {e}")
            import traceback

            error(f"[CHAT-SESSION] Traceback completo: {traceback.format_exc()}")
            raise ValueError(f"Erro interno ao buscar chat: {str(e)}")

    def debug_check_chat(self, chat_id: str, client_id: int):
        """Método de debug para verificar se chat existe"""
        try:
            debug(
                f"[CHAT-SESSION-DEBUG] Verificando chat: {chat_id}, client: {client_id}"
            )

            # Verificar se tabela existe
            if not self.db.table_exists("chats"):
                debug(f"[CHAT-SESSION-DEBUG] Tabela 'chats' não existe!")
                return False

            # Verificar todas as colunas
            columns = self.db.get_table_columns("chats")
            debug(f"[CHAT-SESSION-DEBUG] Colunas da tabela chats: {columns}")

            # Verificar todos os chats deste cliente
            all_chats_query = """
                SELECT c.chat_id, c.chat_name
                FROM chats c
                JOIN users u ON c.user_id = u.user_id
                WHERE u.client_id = :client_id
            """
            all_chats = self.db.fetch_all(all_chats_query, {"client_id": client_id})
            debug(
                f"[CHAT-SESSION-DEBUG] Todos os chats do cliente {client_id}: {all_chats}"
            )

            # Verificar chat específico
            specific_query = """
                SELECT * FROM chats
                WHERE chat_id = :chat_id
            """
            chat_result = self.db.fetch_all(specific_query, {"chat_id": chat_id})
            debug(
                f"[CHAT-SESSION-DEBUG] Chat com ID {chat_id} encontrado: {chat_result}"
            )

            return len(chat_result) > 0

        except Exception as e:
            error(f"[CHAT-SESSION-DEBUG] Erro ao verificar chat: {e}")
            return False

    def validate_chat_exists(self, chat_id: str, client_id: int) -> Dict[str, Any]:
        """Valida se um chat existe e retorna seus dados básicos"""
        query = """
            SELECT chat_id, chat_name
            FROM chats
            WHERE chat_id = :chat_id AND client_id = :client_id
        """

        chat = self.db.fetch_one(query, {"chat_id": chat_id, "client_id": client_id})

        if not chat:
            raise ValueError("Conversa não encontrada")

        return chat

    def rename_chat(
        self, chat_id: str, client_id: int, new_name: str
    ) -> Dict[str, Any]:
        """Renomeia um chat"""
        try:
            query = """
                UPDATE chats
                SET chat_name = :chat_name, updated_at = CURRENT_TIMESTAMP
                WHERE chat_id = :chat_id AND client_id = :client_id
            """

            self.db.execute_query(
                query,
                {"chat_name": new_name, "chat_id": chat_id, "client_id": client_id},
            )

            debug(f"[CHAT-SESSION] Chat renomeado: {chat_id} -> {new_name}")

            return {
                "message": "Conversa renomeada com sucesso",
                "chat_id": chat_id,
                "new_name": new_name,
                "updated_at": datetime.now().isoformat(),
            }

        except Exception as e:
            error(f"[CHAT-SESSION] Erro ao renomear chat: {e}")
            raise

    def delete_chat(self, chat_id: str, client_id: int) -> Dict[str, Any]:
        """Deleta um chat"""
        try:
            # Deletar mensagens primeiro
            messages_deleted = 0
            if self.db.table_exists("messages"):
                query = """
                    DELETE FROM messages
                    WHERE chat_id = :chat_id AND client_id = :client_id
                """
                result = self.db.execute_query(
                    query, {"chat_id": chat_id, "client_id": client_id}
                )
                messages_deleted = result.rowcount

            # Deletar chat
            query = """
                DELETE FROM chats
                WHERE chat_id = :chat_id AND client_id = :client_id
            """
            result = self.db.execute_query(
                query, {"chat_id": chat_id, "client_id": client_id}
            )
            chat_deleted = result.rowcount

            debug(f"[CHAT-SESSION] Chat deletado: {chat_id}")

            return {
                "message": "Conversa deletada com sucesso",
                "chat_id": chat_id,
                "deleted": True,
                "records_deleted": {"messages": messages_deleted, "chat": chat_deleted},
                "deleted_at": datetime.now().isoformat(),
            }

        except Exception as e:
            error(f"[CHAT-SESSION] Erro ao deletar chat: {e}")
            raise

    def update_chat_timestamp(self, chat_id: str) -> None:
        """Atualiza o timestamp de um chat"""
        query = """
            UPDATE chats SET updated_at = CURRENT_TIMESTAMP
            WHERE chat_id = :chat_id
        """
        self.db.execute_query(query, {"chat_id": chat_id})

    # Métodos auxiliares
    def _get_chat_select_columns(self, available_columns: List[str]) -> List[str]:
        """Retorna colunas para SELECT baseado nas colunas disponíveis"""
        select_cols = []

        # Colunas obrigatórias
        required = ["chat_id", "client_id", "chat_name"]
        for col in required:
            if col in available_columns:
                select_cols.append(col)

        # Colunas opcionais
        optional = [
            "created_at",
            "updated_at",
            "status",
            "letters_counting",
            "messenges_counting",
        ]
        for col in optional:
            if col in available_columns:
                select_cols.append(col)

        return select_cols

    def _normalize_chat_data(self, chat_data: Dict[str, Any]) -> Dict[str, Any]:
        """Normaliza dados do chat com valores padrão"""
        if "created_at" not in chat_data:
            chat_data["created_at"] = datetime.now().isoformat()
        if "updated_at" not in chat_data:
            chat_data["updated_at"] = datetime.now().isoformat()
        if "status" not in chat_data:
            chat_data["status"] = "active"
        if "letters_counting" not in chat_data:
            chat_data["letters_counting"] = 0
        if "messenges_counting" not in chat_data:
            chat_data["messenges_counting"] = 0

        return chat_data

    def _empty_chats_response(self, limit: int, offset: int) -> Dict[str, Any]:
        """Retorna resposta vazia para chats"""
        return {
            "chats": [],
            "total": 0,
            "pagination": {"limit": limit, "offset": offset, "hasMore": False},
        }
