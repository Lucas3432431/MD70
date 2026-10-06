"""Coordenador de operações de mensagens com suporte a isolamento por agente"""

import uuid
from datetime import datetime
from typing import Dict, Any, List
from sqlalchemy import text
from App.Core.Logs import debug, error


class MessageCoordinator:
    """Coordena operações de mensagens com isolamento por agente"""

    def __init__(self, database):
        """Inicializa o coordenador de mensagens"""
        self.db = database
        debug("[MSG-COORD] MessageCoordinator inicializado com isolamento por agente")

    def save_user_message(
        self, chat_id: str, user_id: str, message: str, agent_id: str = "default_agent"
    ) -> Dict[str, Any]:
        """Salva uma mensagem do usuário com isolamento por agente"""
        try:
            message_id = str(uuid.uuid4())

            # 1. Primeiro salvar no sistema isolado (isolated_messages)
            isolated_result = self._save_to_isolated_messages(
                chat_id=chat_id,
                user_id=user_id,
                agent_id=agent_id,
                role="user",
                content=message,
                message_type="message",
            )

            # 2. Depois salvar no sistema principal (messages) para compatibilidade
            def save_message_transaction(conn):
                conn.execute(
                    text(
                        """
                    INSERT INTO messages
                    (message_id, chat_id, client_id, message_type, content, model, created_at)
                    VALUES (:message_id, :chat_id, :client_id, 'user', :content, 'user-input', CURRENT_TIMESTAMP)
                """
                    ),
                    {
                        "message_id": message_id,
                        "chat_id": chat_id,
                        "client_id": client_id,
                        "content": message,
                    },
                )

            self.db.execute_with_connection(save_message_transaction)

            debug(
                f"[MSG-COORD] Mensagem do usuário salva: {message_id} (agente: {agent_id})"
            )
            debug(f"[MSG-COORD] Isolado: {isolated_result.get('success', False)}")

            return {
                "message_id": message_id,
                "content": message,
                "message_type": "user",
                "model": "user-input",
                "agent_id": agent_id,
                "isolated_success": isolated_result.get("success", False),
                "isolated_uuid": isolated_result.get("message_uuid"),
                "created_at": datetime.now().isoformat(),
            }

        except Exception as e:
            error(f"[MSG-COORD] Erro ao salvar mensagem: {e}")
            # Retornar dados básicos mesmo se falhar
            return {
                "message_id": str(uuid.uuid4()),
                "content": message,
                "message_type": "user",
                "model": "user-input",
                "agent_id": agent_id,
                "isolated_success": False,
                "created_at": datetime.now().isoformat(),
            }

    def save_ai_message(
        self,
        chat_id: str,
        user_id: str,
        ai_response: Dict[str, Any],
        processing_time: int = 0,
        agent_id: str = "default_agent",
    ) -> Dict[str, Any]:
        """Salva uma resposta da IA com isolamento por agente"""
        try:
            model_used = ai_response.get("model", "zera-micro-1")
            message_id = str(uuid.uuid4())
            content = ai_response.get("content", "")

            # 1. Primeiro salvar no sistema isolado (isolated_messages)
            isolated_result = self._save_to_isolated_messages(
                chat_id=chat_id,
                user_id=user_id,
                agent_id=agent_id,
                role="assistant",
                content=content,
                message_type="message",
            )

            # 2. Depois salvar no sistema principal (messages) para compatibilidade
            def save_ai_message_transaction(conn):
                conn.execute(
                    text(
                        """
                    INSERT INTO messages
                    (message_id, chat_id, client_id, message_type, content,
                     tokens_used, processing_time, model, created_at)
                    VALUES (:message_id, :chat_id, :client_id, 'ai', :content,
                            :tokens, :time, :model, CURRENT_TIMESTAMP)
                """
                    ),
                    {
                        "message_id": message_id,
                        "chat_id": chat_id,
                        "client_id": client_id,
                        "content": content,
                        "tokens": ai_response.get("tokens_used", 0),
                        "time": processing_time,
                        "model": model_used,
                    },
                )

            self.db.execute_with_connection(save_ai_message_transaction)

            debug(
                f"[MSG-COORD] Resposta da IA salva: {message_id} (agente: {agent_id})"
            )
            debug(f"[MSG-COORD] Isolado: {isolated_result.get('success', False)}")

            return {
                "message_id": message_id,
                "content": content,
                "message_type": "ai",
                "tokens_used": ai_response.get("tokens_used", 0),
                "model": model_used,
                "provider": ai_response.get("provider", "zera"),
                "agent_id": agent_id,
                "isolated_success": isolated_result.get("success", False),
                "isolated_uuid": isolated_result.get("message_uuid"),
                "processing_time": processing_time,
                "created_at": datetime.now().isoformat(),
            }

        except Exception as e:
            error(f"[MSG-COORD] Erro ao salvar resposta da IA: {e}")
            # Retornar dados básicos
            return {
                "message_id": str(uuid.uuid4()),
                "content": ai_response.get("content", ""),
                "message_type": "ai",
                "tokens_used": ai_response.get("tokens_used", 0),
                "model": model_used,
                "provider": ai_response.get("provider", "zera"),
                "agent_id": agent_id,
                "isolated_success": False,
                "processing_time": processing_time,
                "created_at": datetime.now().isoformat(),
            }

    def get_chat_history(
        self, chat_id: str, client_id: int, limit: int = 10, agent_id: str = None
    ) -> List[Dict]:
        """Obtém histórico de mensagens do chat, com suporte a isolamento por agente"""
        try:
            # Se agent_id for especificado, buscar do sistema isolado
            if agent_id and self.db.table_exists("isolated_messages"):
                return self._get_isolated_chat_history(
                    chat_id, client_id, agent_id, limit
                )

            # Caso contrário, usar sistema principal (compatibilidade)
            if not self.db.table_exists("messages"):
                return []

            query = """
                SELECT message_type, content
                FROM messages
                WHERE chat_id = :chat_id AND client_id = :client_id
                ORDER BY created_at DESC
                LIMIT :limit
            """

            messages = self.db.fetch_all(
                query, {"chat_id": chat_id, "client_id": client_id, "limit": limit}
            )

            # Converter para formato de histórico
            history = []
            for msg in reversed(messages):  # Ordem cronológica
                role = "user" if msg["message_type"] == "user" else "assistant"
                history.append({"role": role, "content": msg["content"]})

            debug(
                f"[MSG-COORD] {len(history)} mensagens no histórico (agente: {'todos' if not agent_id else agent_id})"
            )
            return history

        except Exception as e:
            error(f"[MSG-COORD] Erro ao obter histórico: {e}")
            return []

    def get_chat_messages(
        self, chat_id: str, user_id: str, agent_id: str = None
    ) -> List[Dict]:
        """Obtem todas as mensagens do chat (para get_chat), com suporte a isolamento por agente"""
        try:
            # Se agent_id for especificado, buscar do sistema isolado
            if agent_id and self.db.table_exists("isolated_messages"):
                return self._get_isolated_chat_messages(chat_id, user_id, agent_id)

            # Caso contrario, usar sistema principal (compatibilidade)
            if not self.db.table_exists("messages"):
                return []

            query = """
                SELECT
                    message_id,
                    message_type,
                    content,
                    created_at,
                    COALESCE(tokens_used, 0) as tokens_used,
                    COALESCE(model, 'unknown') as model
                FROM messages
                WHERE chat_id = :chat_id AND client_id = :client_id
                ORDER BY created_at ASC
            """

            messages = self.db.fetch_all(
                query, {"chat_id": chat_id, "client_id": client_id}
            )

            # Mapear message_id para id para compatibilidade
            formatted_messages = []
            for msg in messages:
                formatted_msg = {"id": msg["message_id"], **msg}
                formatted_messages.append(formatted_msg)

            return formatted_messages

        except Exception as e:
            error(f"[MSG-COORD] Erro ao buscar mensagens: {e}")
            return []

    # ============================================================================
    # MÉTODOS DE ISOLAMENTO POR AGENTE
    # ============================================================================

    def _get_or_create_isolated_chat(
        self, chat_id: str, user_id: str, agent_id: str
    ) -> int:
        """Obtém ou cria um chat isolado para um agente"""
        try:
            # Verificar se já existe
            query = """
                SELECT id FROM isolated_chat
                WHERE chat_id = :chat_id AND agent_id = :agent_id
            """

            existing = self.db.fetch_one(
                query, {"chat_id": chat_id, "agent_id": agent_id}
            )

            if existing:
                return existing["id"]

            # Criar novo chat isolado
            def create_isolated_chat_transaction(conn):
                result = conn.execute(
                    text(
                        """
                    INSERT INTO isolated_chat (chat_id, agent_id, created_at, updated_at)
                    VALUES (:chat_id, :agent_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    RETURNING id
                """
                    ),
                    {"chat_id": chat_id, "agent_id": agent_id},
                )
                return result.scalar()

            isolated_chat_id = self.db.execute_with_connection(
                create_isolated_chat_transaction
            )
            debug(
                f"[MSG-COORD] Chat isolado criado: id={isolated_chat_id}, agente={agent_id}"
            )
            return isolated_chat_id

        except Exception as e:
            error(f"[MSG-COORD] Erro ao criar chat isolado: {e}")
            # Retornar -1 para indicar erro
            return -1

    def _save_to_isolated_messages(
        self,
        chat_id: str,
        user_id: str,
        agent_id: str,
        role: str,
        content: str,
        message_type: str = "message",
    ) -> Dict[str, Any]:
        """Salva uma mensagem no sistema isolado"""
        try:
            # 1. Obter ou criar chat isolado
            isolated_chat_id = self._get_or_create_isolated_chat(
                chat_id, user_id, agent_id
            )

            if isolated_chat_id == -1:
                return {"success": False, "error": "Failed to get/create isolated chat"}

            # 2. Salvar mensagem isolada
            message_uuid = str(uuid.uuid4())

            def save_isolated_message_transaction(conn):
                conn.execute(
                    text(
                        """
                    INSERT INTO isolated_messages
                    (isolated_chat_id, uuid, role, content, type, created_at, updated_at)
                    VALUES (:isolated_chat_id, :uuid, :role, :content, :type,
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
                    ),
                    {
                        "isolated_chat_id": isolated_chat_id,
                        "uuid": message_uuid,
                        "role": role,
                        "content": content,
                        "type": message_type,
                    },
                )

                # Atualizar timestamp do chat isolado
                conn.execute(
                    text(
                        """
                    UPDATE isolated_chat
                    SET updated_at = CURRENT_TIMESTAMP
                    WHERE id = :isolated_chat_id
                """
                    ),
                    {"isolated_chat_id": isolated_chat_id},
                )

            self.db.execute_with_connection(save_isolated_message_transaction)

            debug(
                f"[MSG-COORD] Mensagem isolada salva: uuid={message_uuid}, agente={agent_id}, role={role}"
            )
            return {
                "success": True,
                "message_uuid": message_uuid,
                "isolated_chat_id": isolated_chat_id,
                "agent_id": agent_id,
            }

        except Exception as e:
            error(f"[MSG-COORD] Erro ao salvar mensagem isolada: {e}")
            return {"success": False, "error": str(e)}

    def _get_isolated_chat_history(
        self, chat_id: str, client_id: int, agent_id: str, limit: int = 10
    ) -> List[Dict]:
        """Obtém histórico do chat isolado"""
        try:
            # Primeiro obter o chat isolado
            query = """
                SELECT id FROM isolated_chat
                WHERE chat_id = :chat_id AND client_id = :client_id AND agent_id = :agent_id
            """

            isolated_chat = self.db.fetch_one(
                query,
                {"chat_id": chat_id, "client_id": client_id, "agent_id": agent_id},
            )

            if not isolated_chat:
                debug(f"[MSG-COORD] Chat isolado não encontrado para agente {agent_id}")
                return []

            isolated_chat_id = isolated_chat["id"]

            # Buscar mensagens isoladas
            query = """
                SELECT role, content, type, created_at
                FROM isolated_messages
                WHERE isolated_chat_id = :isolated_chat_id AND type = 'message'
                ORDER BY created_at DESC
                LIMIT :limit
            """

            messages = self.db.fetch_all(
                query, {"isolated_chat_id": isolated_chat_id, "limit": limit}
            )

            # Converter para formato de histórico
            history = []
            for msg in reversed(messages):  # Ordem cronológica
                history.append({"role": msg["role"], "content": msg["content"]})

            debug(
                f"[MSG-COORD] {len(history)} mensagens isoladas no histórico (agente: {agent_id})"
            )
            return history

        except Exception as e:
            error(f"[MSG-COORD] Erro ao obter histórico isolado: {e}")
            return []

    def _get_isolated_chat_messages(
        self, chat_id: str, user_id: str, agent_id: str
    ) -> List[Dict]:
        """Obtém todas as mensagens do chat isolado"""
        try:
            # Primeiro obter o chat isolado
            query = """
                SELECT id FROM isolated_chat
                WHERE chat_id = :chat_id AND client_id = :client_id AND agent_id = :agent_id
            """

            isolated_chat = self.db.fetch_one(
                query,
                {"chat_id": chat_id, "client_id": client_id, "agent_id": agent_id},
            )

            if not isolated_chat:
                debug(f"[MSG-COORD] Chat isolado não encontrado para agente {agent_id}")
                return []

            isolated_chat_id = isolated_chat["id"]

            # Buscar mensagens isoladas
            query = """
                SELECT
                    uuid as message_id,
                    role,
                    content,
                    type as message_type,
                    created_at
                FROM isolated_messages
                WHERE isolated_chat_id = :isolated_chat_id
                ORDER BY created_at ASC
            """

            messages = self.db.fetch_all(query, {"isolated_chat_id": isolated_chat_id})

            # Formatar para compatibilidade
            formatted_messages = []
            for msg in messages:
                # Mapear role para message_type do sistema principal
                if msg["role"] == "user":
                    message_type = "user"
                elif msg["role"] == "assistant":
                    message_type = "ai"
                else:
                    message_type = "system"

                formatted_msg = {
                    "id": msg["message_id"],
                    "message_id": msg["message_id"],
                    "message_type": message_type,
                    "content": msg["content"],
                    "created_at": msg["created_at"],
                    "tokens_used": 0,
                    "model": "isolated",
                    "agent_id": agent_id,
                    "source": "isolated",
                }
                formatted_messages.append(formatted_msg)

            return formatted_messages

        except Exception as e:
            error(f"[MSG-COORD] Erro ao buscar mensagens isoladas: {e}")
            return []

    def migrate_existing_messages_to_isolated(
        self, chat_id: str, user_id: str, agent_id: str = "default_agent"
    ) -> Dict[str, Any]:
        """Migra mensagens existentes para sistema isolado"""
        try:
            # Buscar mensagens existentes
            existing_messages = self.get_chat_messages(chat_id, user_id)

            if not existing_messages:
                return {
                    "success": True,
                    "message": "No messages to migrate",
                    "migrated": 0,
                }

            migrated_count = 0

            for msg in existing_messages:
                # Mapear message_type para role
                if msg["message_type"] == "user":
                    role = "user"
                elif msg["message_type"] == "ai":
                    role = "assistant"
                else:
                    role = "system"

                # Salvar no sistema isolado
                result = self._save_to_isolated_messages(
                    chat_id=chat_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    role=role,
                    content=msg["content"],
                    message_type="message",
                )

                if result.get("success"):
                    migrated_count += 1

            debug(
                f"[MSG-COORD] {migrated_count}/{len(existing_messages)} mensagens migradas para isolado"
            )

            return {
                "success": True,
                "migrated": migrated_count,
                "total": len(existing_messages),
                "agent_id": agent_id,
                "chat_id": chat_id,
            }

        except Exception as e:
            error(f"[MSG-COORD] Erro na migração: {e}")
            return {"success": False, "error": str(e), "migrated": 0}
