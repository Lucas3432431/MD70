"""
Serviço unificado de chat - Substitui ChatCoordinator, ChatSessionManager, ChatDatabase
Single source of truth para todas as operações de chat
"""

import json
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import text

from App.Core.Logs import debug, info, error, warning
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager


class ChatService:
    """
    Serviço unificado de chat.
    Gerencia criação, leitura, atualização e deleção de chats e mensagens.
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        """
        Inicializa o serviço de chat.

        Args:
            db_manager: Instância de DatabaseManager (ou None para usar singleton)
        """
        self.db = db_manager or DatabaseManager()
        debug("[CHAT-SERVICE] ChatService inicializado")

    def get_sync_callback(self):
        """
        Retorna callback para sincronizar isolated→main para MessageProcessor.

        Returns:
            Função(chat_id, agent_id) que sincroniza
        """

        def sync_callback(chat_id: str, agent_id: str):
            """Sincroniza isolated_chat para main_chat via DatabaseManager."""
            try:
                with self.db.get_session() as sync_session:
                    DatabaseManager.sync_isolated_to_main(
                        session=sync_session, chat_id=chat_id, agent_id=agent_id
                    )
                debug(
                    f"[CHAT-SERVICE] Sync callback: isolated→main concluído para {chat_id}"
                )
            except Exception as e:
                error(f"[CHAT-SERVICE] Erro no sync callback: {e}")

        return sync_callback

    # ==================== CHAT OPERATIONS ====================

    def create_chat(
        self,
        user_id: str,
        chat_name: str,
        message: Optional[str] = None,
        model: str = "gpt-4o-mini",
    ) -> Dict[str, Any]:
        """
        Cria um novo chat vinculado a um usuário específico.

        Args:
            user_id: ID do usuário (UUID)
            chat_name: Nome do chat
            message: Mensagem inicial (usada só para nome, não salva)
            model: Modelo de IA a usar

        Returns:
            Dict com dados do chat criado

        Raises:
            ValueError: Se falhar ao criar o chat
        """
        try:
            # Validações
            chat_name = (chat_name or "").strip()
            message = (message or "").strip()

            if not chat_name and not message:
                raise ValueError(
                    "Nome do chat é obrigatório (ou forneça uma mensagem inicial)"
                )

            # Se só tem mensagem, usar como nome do chat
            if not chat_name and message:
                chat_name = message[:50]

            # Gerar ID único
            chat_id = str(uuid.uuid4())
            now = datetime.now().isoformat()

            debug(
                f"[CHAT-SERVICE] Criando chat: id={chat_id}, name={chat_name}, user={user_id}"
            )

            # Criar apenas o chat (sem salvar mensagem)
            def create_chat_transaction(session):
                session.execute(
                    text(
                        """
                        INSERT INTO chats
                        (chat_id, user_id, chat_name, created_at, updated_at, status, chat_cover)
                        VALUES (:chat_id, :user_id, :chat_name, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'active', NULL)
                    """
                    ),
                    {
                        "chat_id": chat_id,
                        "user_id": user_id,
                        "chat_name": chat_name,
                    },
                )

            self.db.execute_transaction(create_chat_transaction)

            response = {
                "chat_id": chat_id,
                "chat_name": chat_name,
                "created_at": now,
                "message": "Chat criado com sucesso",
            }

            info(f"[CHAT-SERVICE] Chat criado: {chat_id} para usuário {user_id}")
            return response

        except Exception as e:
            error(f"[CHAT-SERVICE] Erro ao criar chat: {e}")
            raise

    def get_chat(self, chat_id: str, user_id: str) -> Dict[str, Any]:
        """
        Obtém um chat específico garantindo que pertence ao usuário.

        Args:
            chat_id: ID do chat
            user_id: ID do usuário (para validação de acesso)

        Returns:
            Dict com dados do chat e mensagens

        Raises:
            ValueError: Se chat não encontrado ou sem permissão
        """
        try:
            debug(f"[CHAT-SERVICE] Buscando chat {chat_id} para usuário {user_id}")

            # Buscar chat verificando se pertence ao user
            chat_data = self.db.fetch_one(
                """
                SELECT chat_id, chat_name, created_at, updated_at, status, chat_cover
                FROM chats
                WHERE chat_id = :chat_id AND user_id = :user_id
            """,
                {"chat_id": chat_id, "user_id": user_id},
            )

            # VALIDAR SE CHAT EXISTE
            if not chat_data:
                warning(
                    f"[CHAT-SERVICE] Chat não encontrado: {chat_id} (user: {user_id})"
                )
                raise ValueError(f"Chat {chat_id} não encontrado ou acesso negado")

            debug(
                f"[CHAT-SERVICE] Chat encontrado: {chat_data.get('chat_name', 'N/A')}"
            )

            # Buscar client_id do usuário para filtros de attachments e files
            user_data = self.db.fetch_one(
                "SELECT client_id FROM users WHERE user_id = :user_id",
                {"user_id": user_id},
            )
            client_id = user_data.get("client_id") if user_data else None

            # Buscar mensagens
            messages = self.db.fetch_all(
                """
                SELECT message_id as id, message_type as role, content, tool, created_at
                FROM messages
                WHERE chat_id = :chat_id
                ORDER BY created_at ASC
            """,
                {"chat_id": chat_id},
            )
            # Adicionar attachments a cada mensagem
            if messages and user_id:
                for msg in messages:
                    try:
                        attachments = self.db.fetch_all(
                            """
                            SELECT attachment_id, message_id, attachment_type, file_type, file_name, extension, template_id
                            FROM attachments
                            WHERE message_id = :message_id AND user_id = :user_id AND is_temp = 0
                            ORDER BY uploaded_at ASC
                            """,
                            {"message_id": msg.get("id"), "user_id": user_id},
                        )
                        msg["attachments"] = attachments or []
                    except Exception as e:
                        debug(
                            f"[CHAT-SERVICE] Erro ao buscar attachments para msg {msg.get('id')}: {e}"
                        )
                        msg["attachments"] = []

            debug(
                f"[CHAT-SERVICE] Mensagens encontradas: {len(messages) if messages else 0}"
            )

            # Buscar arquivos gerados (conteúdo gerado como imagens/vídeos)
            files = []
            if client_id:
                try:
                    files = self.db.fetch_all(
                        """
                        SELECT DISTINCT gc.id, gc.asset_id, gc.content_name, gc.type, gc.storage_path, gc.created_at, gc.chat_id
                        FROM assets gc
                        WHERE gc.chat_id = :chat_id AND gc.client_id = :client_id
                        ORDER BY gc.created_at ASC
                    """,
                        {"chat_id": chat_id, "client_id": client_id},
                    )
                    file_count = len(files) if files else 0
                    debug(f"[CHAT-SERVICE] Arquivos gerados encontrados: {file_count}")
                except Exception as e:
                    debug(f"[CHAT-SERVICE] Arquivos gerados não encontrados: {e}")
                    files = []

            # Buscar todos os attachments do chat
            attachments = []
            if user_id:
                try:
                    debug(
                        f"[CHAT-SERVICE] Buscando attachments para chat_id={chat_id}, user_id={user_id}"
                    )
                    attachments = self.db.fetch_all(
                        """
                        SELECT attachment_id, message_id, attachment_type, file_type, file_name, extension, template_id
                        FROM attachments
                        WHERE chat_id = :chat_id AND user_id = :user_id AND is_temp = 0
                        ORDER BY uploaded_at ASC
                        """,
                        {"chat_id": chat_id, "user_id": user_id},
                    )
                    attachment_count = len(attachments) if attachments else 0
                    debug(f"[CHAT-SERVICE] Attachments encontrados: {attachment_count}")
                    if attachments:
                        debug(f"[CHAT-SERVICE] Attachments details: {attachments}")
                except Exception as e:
                    error(f"[CHAT-SERVICE] Erro ao buscar attachments: {e}")
                    import traceback

                    error(f"[CHAT-SERVICE] Traceback: {traceback.format_exc()}")
                    attachments = []

            response = {
                **chat_data,
                "messages": messages or [],
                "files": files or [],
                "attachments": attachments or [],
            }

            info(
                f"[CHAT-SERVICE] Chat carregado: {chat_id} com {len(messages) if messages else 0} mensagens"
            )
            return response

        except ValueError:
            raise
        except Exception as e:
            error(f"[CHAT-SERVICE] Erro ao buscar chat: {e}")
            import traceback

            error(f"[CHAT-SERVICE] Traceback: {traceback.format_exc()}")
            raise ValueError(f"Erro ao buscar chat: {str(e)}")

    def get_chats(
        self, user_id: str, limit: int = 20, offset: int = 0
    ) -> Dict[str, Any]:
        """
        Lista todos os chats de um usuário específico.

        Args:
            user_id: ID do usuário
            limit: Quantidade máxima de resultados
            offset: Deslocamento para paginação

        Returns:
            Dict com lista de chats e informações de paginação
        """
        try:
            debug(f"[CHAT-SERVICE] Listando chats do usuário {user_id}")

            # Buscar chats (pelo user_id)
            chats = self.db.fetch_all(
                """
                SELECT chat_id, chat_name, created_at, updated_at, status, chat_cover,
                       COALESCE(is_pinned, 0) AS is_pinned
                FROM chats
                WHERE user_id = :user_id AND (source IS NULL OR source = '')
                ORDER BY COALESCE(is_pinned, 0) DESC, updated_at DESC
                LIMIT :limit OFFSET :offset
            """,
                {"user_id": user_id, "limit": limit, "offset": offset},
            )

            # Contar total
            total_result = self.db.fetch_one(
                """
                SELECT COUNT(*) as total FROM chats
                WHERE user_id = :user_id AND (source IS NULL OR source = '')
""",
                {"user_id": user_id},
            )
            total_count = (total_result or {}).get("total", 0)

            response = {
                "chats": chats or [],
                "total": total_count,
                "pagination": {
                    "limit": limit,
                    "offset": offset,
                    "hasMore": (offset + len(chats or [])) < total_count,
                },
            }

            info(
                f"[CHAT-SERVICE] {len(chats or [])} chats listados para usuário {user_id}"
            )
            return response

        except Exception as e:
            error(f"[CHAT-SERVICE] Erro ao listar chats para {user_id}: {e}")
            return {
                "chats": [],
                "total": 0,
                "pagination": {"limit": limit, "offset": offset, "hasMore": False},
            }

    def rename_chat(self, chat_id: str, user_id: str, new_name: str) -> Dict[str, Any]:
        """
        Renomeia um chat garantindo que pertence ao usuário.

        Args:
            chat_id: ID do chat
            user_id: ID do usuário
            new_name: Novo nome

        Returns:
            Dict com confirmação

        Raises:
            ValueError: Se chat não encontrado
        """
        try:
            new_name = (new_name or "").strip()
            if not new_name:
                raise ValueError("Nome é obrigatório")

            debug(f"[CHAT-SERVICE] Renomeando chat {chat_id} para usuário {user_id}")

            # Executar update com filtro de user_id para segurança
            self.db.execute_query(
                """
                UPDATE chats
                SET chat_name = :chat_name, updated_at = CURRENT_TIMESTAMP
                WHERE chat_id = :chat_id AND user_id = :user_id
            """,
                {
                    "chat_name": new_name,
                    "chat_id": chat_id,
                    "user_id": user_id,
                },
            )

            info(f"[CHAT-SERVICE] Chat renomeado: {chat_id} -> {new_name}")
            return {
                "message": "Chat renomeado com sucesso",
                "chat_id": chat_id,
                "new_name": new_name,
                "updated_at": datetime.now().isoformat(),
            }

        except Exception as e:
            error(f"[CHAT-SERVICE] Erro ao renomear chat: {e}")
            raise

    def delete_chat(self, chat_id: str, user_id: str) -> Dict[str, Any]:
        """
        Deleta um chat e suas mensagens garantindo que pertence ao usuário.

        Args:
            chat_id: ID do chat
            user_id: ID do usuário

        Returns:
            Dict com confirmação

        Raises:
            ValueError: Se chat não encontrado
        """
        try:
            debug(f"[CHAT-SERVICE] Deletando chat {chat_id} para usuário {user_id}")

            # Verificar se chat pertence ao usuário antes de deletar
            chat_check = self.db.fetch_one(
                "SELECT chat_id FROM chats WHERE chat_id = :chat_id AND user_id = :user_id",
                {"chat_id": chat_id, "user_id": user_id},
            )

            if not chat_check:
                warning(
                    f"[CHAT-SERVICE] Tentativa de deletar chat inexistente ou sem permissão: {chat_id} (user: {user_id})"
                )
                raise ValueError("Chat não encontrado ou acesso negado")

            def delete_chat_transaction(session):
                # Deletar mensagens primeiro
                session.execute(
                    text(
                        """
                        DELETE FROM messages
                        WHERE chat_id = :chat_id
                    """
                    ),
                    {"chat_id": chat_id},
                )

                # Deletar chat
                session.execute(
                    text(
                        """
                        DELETE FROM chats
                        WHERE chat_id = :chat_id AND user_id = :user_id
                    """
                    ),
                    {"chat_id": chat_id, "user_id": user_id},
                )

                # Deletar isolated_chats relacionados
                session.execute(
                    text("DELETE FROM isolated_chat WHERE chat_id = :chat_id"),
                    {"chat_id": chat_id},
                )

            self.db.execute_transaction(delete_chat_transaction)

            info(f"[CHAT-SERVICE] Chat deletado: {chat_id}")
            return {
                "message": "Chat deletado com sucesso",
                "chat_id": chat_id,
                "deleted": True,
                "deleted_at": datetime.now().isoformat(),
            }

        except Exception as e:
            error(f"[CHAT-SERVICE] Erro ao deletar chat: {e}")
            raise

    # ==================== MESSAGE OPERATIONS ====================

    def save_message_exchange(
        self,
        chat_id: str,
        user_id: str,
        user_message: str,
        ai_response: str,
        model: str = "gpt-4o-mini",
        agent_id: str = "orchestrator-global",
        save_user_message: bool = True,
    ) -> Dict[str, Any]:
        """
        Salva uma troca de mensagens (usuário + IA) atomicamente.

        Args:
            chat_id: ID do chat
            user_id: ID do usuário
            user_message: Mensagem do usuário
            ai_response: Resposta da IA
            model: Modelo usado
            agent_id: ID do agente que processou
            save_user_message: Se False, não salva a mensagem do user (porque já foi salva anteriormente)

        Returns:
            Dict com IDs das mensagens salvas

        Raises:
            ValueError: Se falhar ao salvar
        """
        try:
            # Buscar client_id do usuário
            user_data = self.db.fetch_one(
                "SELECT client_id FROM users WHERE user_id = :user_id",
                {"user_id": user_id},
            )
            if not user_data:
                raise ValueError(f"Usuário {user_id} não encontrado")

            client_id = user_data.get("client_id")

            user_msg_id = str(uuid.uuid4())
            ai_msg_id = str(uuid.uuid4())

            debug(
                f"[CHAT-SERVICE] Salvando troca de mensagens no chat {chat_id} (user={user_id})"
            )

            def save_exchange_transaction(session):
                # 1. Criar ou obter isolated_chat (agora vinculamos ao user_id/client_id corretos)
                session.execute(
                    text(
                        """
                        INSERT OR IGNORE INTO isolated_chat
                        (chat_id, client_id, agent_id, created_at, updated_at)
                        VALUES (:chat_id, :client_id, :agent_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                    ),
                    {
                        "chat_id": chat_id,
                        "client_id": client_id,
                        "agent_id": agent_id,
                    },
                )

                # Obter isolated_chat_id
                result = session.execute(
                    text(
                        """
                        SELECT id FROM isolated_chat
                        WHERE chat_id = :chat_id AND agent_id = :agent_id
                    """
                    ),
                    {"chat_id": chat_id, "agent_id": agent_id},
                )
                isolated_chat_id = result.scalar()

                # 2. Salvar mensagem do usuário (APENAS se não foi salva antes)
                if save_user_message:
                    session.execute(
                        text(
                            """
                            INSERT INTO messages
                            (message_id, chat_id, message_type, content, model, created_at)
                            VALUES (:message_id, :chat_id, 'user', :content, 'user-input', CURRENT_TIMESTAMP)
                        """
                        ),
                        {
                            "message_id": user_msg_id,
                            "chat_id": chat_id,
                            "content": user_message,
                        },
                    )

                    # 3. Salvar em isolated_messages (para sincronização posterior)
                    if isolated_chat_id:
                        session.execute(
                            text(
                                """
                                INSERT INTO isolated_messages
                                (isolated_chat_id, uuid, agent_id, agent, role, content, type, created_at)
                                VALUES (:isolated_chat_id, :uuid, :agent_id, :agent, 'user', :content, 'message', CURRENT_TIMESTAMP)
                            """
                            ),
                            {
                                "isolated_chat_id": isolated_chat_id,
                                "uuid": user_msg_id,
                                "agent_id": "user",
                                "agent": "USER",
                                "content": user_message,
                            },
                        )

                # 4. Sincronização é feita via fila ou MessageProcessor
                debug(
                    f"[CHAT-SERVICE] AI response será sincronizado via sync_isolated_to_main"
                )

                # 5. Atualizar timestamp do chat
                session.execute(
                    text(
                        "UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE chat_id = :chat_id"
                    ),
                    {"chat_id": chat_id},
                )

            try:
                self.db.execute_transaction(save_exchange_transaction)
                info(f"[CHAT-SERVICE] Mensagens salvas para chat {chat_id}")
            except Exception as tx_error:
                # Verificar se o chat existe e pertence ao user
                chat_exists = self.db.fetch_one(
                    "SELECT chat_id FROM chats WHERE chat_id = :chat_id AND user_id = :user_id",
                    {"chat_id": chat_id, "user_id": user_id},
                )
                if not chat_exists:
                    error(
                        f"[CHAT-SERVICE] Chat não encontrado ou acesso negado: {chat_id} (user: {user_id})"
                    )
                    raise ValueError(f"Chat {chat_id} não encontrado")
                else:
                    error(f"[CHAT-SERVICE] Erro ao salvar mensagens: {tx_error}")
                    raise

            return {
                "user_message_id": user_msg_id,
                "ai_message_id": ai_msg_id,
                "saved": True,
            }

        except Exception as e:
            error(f"[CHAT-SERVICE] Erro ao salvar troca de mensagens: {e}")
            raise

    def save_agent_message(
        self,
        chat_id: str,
        user_id: str,
        agent_id: str,
        content: str,
        model: str = "gpt-4o-mini",
        task_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Salva uma mensagem de agente garantindo vínculo com o cliente correto através do usuário.

        Args:
            chat_id: ID do chat
            user_id: ID do usuário
            agent_id: ID do agente que gerou a mensagem
            content: Conteúdo da mensagem do agente
            model: Modelo usado pelo agente
            task_name: Nome da tarefa/agente para exibição no frontend

        Returns:
            Dict com ID da mensagem salva
        """
        try:
            # Buscar client_id do usuário
            user_data = self.db.fetch_one(
                "SELECT client_id FROM users WHERE user_id = :user_id",
                {"user_id": user_id},
            )
            if not user_data:
                raise ValueError(f"Usuário {user_id} não encontrado")

            client_id = user_data.get("client_id")
            message_id = str(uuid.uuid4())

            debug(
                f"[CHAT-SERVICE] Salvando mensagem de agente {agent_id} no chat {chat_id}"
            )

            self.db.execute_query(
                """
                INSERT INTO sub_agents_messages
                (message_id, chat_id, client_id, agent_id, task_name, message_type, content, model, created_at)
                VALUES (:message_id, :chat_id, :client_id, :agent_id, :task_name, 'ai', :content, :model, CURRENT_TIMESTAMP)
            """,
                {
                    "message_id": message_id,
                    "chat_id": chat_id,
                    "client_id": client_id,
                    "agent_id": agent_id,
                    "task_name": task_name,
                    "content": content,
                    "model": model,
                },
            )

            info(f"[CHAT-SERVICE] Mensagem de agente salva para chat {chat_id}")
            return {
                "message_id": message_id,
                "agent_id": agent_id,
                "saved": True,
            }

        except Exception as e:
            error(f"[CHAT-SERVICE] Erro ao salvar mensagem de agente: {e}")
            raise

    def get_agent_messages(
        self,
        chat_id: str,
        user_id: str,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Obtém mensagens de agentes e isolated_chats vinculados ao usuário.

        Args:
            chat_id: ID do chat
            user_id: ID do usuário
            agent_id: ID do agente (opcional)

        Returns:
            Dict com lista de isolated_chats e suas mensagens
        """
        try:
            # Buscar client_id do usuário para filtro em isolated_chat
            user_data = self.db.fetch_one(
                "SELECT client_id FROM users WHERE user_id = :user_id",
                {"user_id": user_id},
            )
            if not user_data:
                raise ValueError(f"Usuário {user_id} não encontrado")

            client_id = user_data.get("client_id")

            debug(
                f"[CHAT-SERVICE] Buscando isolated_chats para chat {chat_id} (user={user_id})"
            )

            # Buscar isolated_chats do chat e cliente correto
            isolated_chats = self.db.fetch_all(
                """
                SELECT id, agent_id, name, created_at, updated_at
                FROM isolated_chat
                WHERE chat_id = :chat_id AND client_id = :client_id
                ORDER BY created_at ASC
                """,
                {"chat_id": chat_id, "client_id": client_id},
            )

            # Para cada isolated_chat, buscar suas mensagens
            agent_tasks = []
            if isolated_chats:
                for chat in isolated_chats:
                    messages = self.db.fetch_all(
                        """
                        SELECT id, uuid, agent_id, agent, role, content, type as message_type, created_at
                        FROM isolated_messages
                        WHERE isolated_chat_id = :isolated_chat_id
                        ORDER BY created_at ASC
                        """,
                        {"isolated_chat_id": chat["id"]},
                    )
                    agent_tasks.append(
                        {
                            "isolated_chat_id": chat["id"],
                            "agent_id": chat["agent_id"],
                            "name": chat["name"],
                            "created_at": chat["created_at"],
                            "updated_at": chat["updated_at"],
                            "messages": messages or [],
                        }
                    )

            info(
                f"[CHAT-SERVICE] {len(agent_tasks)} isolated_chats recuperados para chat {chat_id}"
            )
            return {
                "agent_tasks": agent_tasks,
                "chat_id": chat_id,
                "agent_id": agent_id,
            }

        except Exception as e:
            error(f"[CHAT-SERVICE] Erro ao buscar isolated_chats: {e}")
            return {
                "agent_tasks": [],
                "chat_id": chat_id,
                "agent_id": agent_id,
                "error": str(e),
            }

    def get_chat_documents(self, chat_id: str, user_id: str) -> Dict[str, Any]:
        """
        Obtém lista de documentos do chat garantindo acesso do usuário.

        Args:
            chat_id: ID do chat
            user_id: ID do usuário

        Returns:
            Dict com lista de documentos
        """
        try:
            from pathlib import Path
            from App.Core.Crunch.Storage.StorageManager import StorageManager

            # Verificar permissão e obter client_id
            user_data = self.db.fetch_one(
                """
                SELECT u.client_id
                FROM users u
                JOIN chats c ON u.user_id = c.user_id
                WHERE u.user_id = :user_id AND c.chat_id = :chat_id
                """,
                {"user_id": user_id, "chat_id": chat_id},
            )

            if not user_data:
                raise ValueError("Chat não encontrado ou acesso negado")

            client_id = user_data.get("client_id")

            debug(
                f"[CHAT-SERVICE] Obtendo documentos do chat {chat_id} (client={client_id})"
            )

            # Obter caminho dos documentos
            docs_folder = StorageManager.get_documents_folder(
                client_id=client_id, chat_uuid=chat_id
            )

            documents_list = []

            if Path(docs_folder).exists():
                # Ler metadata se existir
                documents_metadata = {}
                try:
                    metadata_file = Path(docs_folder) / "documents.json"
                    if metadata_file.exists():
                        with open(metadata_file, "r", encoding="utf-8") as f:
                            documents_metadata = json.load(f)
                except Exception as e:
                    debug(f"[CHAT-SERVICE] Erro metadata documentos: {e}")

                # Listar arquivos
                for filename in Path(docs_folder).iterdir():
                    if filename.is_file() and filename.name != "documents.json":
                        try:
                            file_stat = filename.stat()
                            doc_meta = documents_metadata.get("documents", {}).get(
                                filename.name, {}
                            )

                            documents_list.append(
                                {
                                    "filename": filename.name,
                                    "size": file_stat.st_size,
                                    "created_at": doc_meta.get(
                                        "created_at", filename.stat().st_ctime
                                    ),
                                    "hash": doc_meta.get("hash", ""),
                                    "path": str(filename),
                                }
                            )
                        except Exception as e:
                            warning(
                                f"[CHAT-SERVICE] Erro ao processar documento {filename.name}: {e}"
                            )

            info(
                f"[CHAT-SERVICE] {len(documents_list)} documentos recuperados do chat {chat_id}"
            )
            return {
                "chat_id": chat_id,
                "documents": documents_list,
                "total_count": len(documents_list),
            }

        except Exception as e:
            error(f"[CHAT-SERVICE] Erro ao buscar documentos: {e}")
            return {
                "chat_id": chat_id,
                "documents": [],
                "total_count": 0,
                "error": str(e),
            }

    # ==================== TOOL CALL RESPONSE ====================

    def resume_tool_call(
        self, chat_id: str, message_id: str, content: str, user_id: str
    ) -> Dict[str, Any]:
        """
        Retoma o processamento de um chat garantindo acesso do usuário.

        Args:
            chat_id: ID do chat
            message_id: UUID da tool_call original
            content: Conteúdo da resposta
            user_id: ID do usuário

        Returns:
            Dict com status da retomada
        """
        try:
            debug(f"[CHAT-SERVICE] Retomando chat {chat_id} para usuário {user_id}")

            # Verificar permissão
            chat_check = self.db.fetch_one(
                "SELECT chat_id FROM chats WHERE chat_id = :chat_id AND user_id = :user_id",
                {"chat_id": chat_id, "user_id": user_id},
            )

            if not chat_check:
                raise ValueError("Chat não encontrado ou acesso negado")

            internal_msg_id = str(uuid.uuid4())
            now = datetime.now().isoformat()

            # Salvar como mensagem de sistema indicando que há resposta
            insert_query = """
            INSERT INTO messages
            (message_id, chat_id, message_type, content, model, created_at)
            VALUES (:msg_id, :chat_id, 'system', :content, 'tool-response', :created_at)
            """

            self.db.execute_query(
                insert_query,
                {
                    "msg_id": internal_msg_id,
                    "chat_id": chat_id,
                    "content": content,
                    "created_at": now,
                },
            )

            info(f"[CHAT-SERVICE] Tool call retomada para chat {chat_id}")

            return {
                "success": True,
                "chat_id": chat_id,
                "message_id": message_id,
                "internal_message_id": internal_msg_id,
                "message": "Tool call response enfileirada para retomada",
            }

        except Exception as e:
            error(f"[CHAT-SERVICE] Erro ao retomar tool_call: {e}")
            return {"success": False, "error": str(e), "chat_id": chat_id}

    # ==================== CALENDAR OPERATIONS ====================

    def update_calendar_post(
        self,
        post_id: str,
        user_id: str,
        post_date: str = None,
        short_description: str = None,
    ) -> Dict[str, Any]:
        """
        Atualiza dados de um post do calendário.
        """
        try:
            updates = []
            params = {"post_id": post_id, "user_id": user_id}

            if post_date:
                from datetime import datetime

                date_str = post_date.replace(".", "/")
                try:
                    new_date = datetime.strptime(date_str, "%d/%m/%Y").date()
                except ValueError:
                    try:
                        new_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    except ValueError:
                        raise ValueError(
                            "Formato de data inválido. Use DD.MM.YYYY ou DD/MM/YYYY"
                        )

                updates.append("post_date = :post_date")
                params["post_date"] = new_date

            if short_description is not None:
                updates.append("short_description = :short_description")
                params["short_description"] = short_description

            if not updates:
                return {"success": True, "message": "Nenhuma alteração fornecida"}

            updates.append("updated_at = CURRENT_TIMESTAMP")

            query = f"""
                UPDATE calendar
                SET {", ".join(updates)}
                WHERE post_id = :post_id AND user_id = :user_id
            """

            self.db.execute_query(query, params)

            return {
                "success": True,
                "post_id": post_id,
                "message": "Agendamento atualizado com sucesso",
            }
        except Exception as e:
            error(f"[CHAT-SERVICE] Erro ao atualizar post do calendário: {e}")
            raise
