"""
ChatManager - Gerenciamento de chat baseado em sessão para isolamento de contexto
Adaptado do AgentX para MD70 com suporte a múltiplos agents em paralelo
"""

import json
import threading
import copy
import uuid
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional  # Added this import

from App.Core.Logs import debug, info, error, warning


@dataclass
class Session:
    """Encapsula o estado de uma única sessão de chat."""

    session_id: str
    conversation_history: list = field(default_factory=list)
    chat_id: str = None
    chat_file: Path = None
    created_at: datetime = field(default_factory=datetime.now)


class ChatManager:
    """Gerencia múltiplos chats de forma isolada usando um modelo de sessão."""

    def __init__(self, base_dir: Path, config: dict = None):
        """
        Inicializa o gerenciador de chats.

        Args:
            base_dir: Diretório base do projeto
            config: Configuração (se None, usa valores padrão)
        """
        self.base_dir = base_dir
        self.config = config or {}

        # Gerenciamento de sessões e locks (sem armazenamento JSON)
        self.sessions = {}
        self.chat_to_session_map = {}
        self.sessions_lock = threading.Lock()
        self.chat_id_lock = threading.Lock()

        # Rastreia a sessão e chat atual para compatibilidade
        self.current_session_id = None
        self.current_chat_id = None

        debug(f"ChatManager inicializado (dados armazenados em banco de dados)")

    def create_session(self) -> str:
        """
        Cria uma nova sessão de chat e retorna seu ID.

        Returns:
            ID da sessão (UUID)
        """
        session_id = str(uuid.uuid4())
        with self.sessions_lock:
            self.sessions[session_id] = Session(session_id=session_id)
        debug(f"Nova sessão criada: {session_id}")
        return session_id

    def get_session(self, session_id: str) -> Session:
        """
        Recupera uma sessão pelo ID.

        Args:
            session_id: ID da sessão

        Returns:
            Objeto Session

        Raises:
            ValueError: Se sessão não encontrada
        """
        with self.sessions_lock:
            if session_id not in self.sessions:
                raise ValueError(f"Sessão '{session_id}' não encontrada.")
            return self.sessions[session_id]

    def close_session(self, session_id: str):
        """
        Encerra uma sessão e a remove do gerenciador.

        Args:
            session_id: ID da sessão
        """
        with self.sessions_lock:
            if session_id in self.sessions:
                session = self.sessions[session_id]
                if session.chat_id and session.chat_id in self.chat_to_session_map:
                    del self.chat_to_session_map[session.chat_id]
                del self.sessions[session_id]
                debug(f"Sessão encerrada: {session_id}")

    def get_session_by_chat_id(self, chat_id: str) -> Optional[Session]:
        """
        Recupera uma sessão pelo chat_id associado.

        Args:
            chat_id: ID do chat (UUID)

        Returns:
            Objeto Session ou None se não encontrada
        """
        with self.sessions_lock:
            session_id = self.chat_to_session_map.get(chat_id)
            if session_id and session_id in self.sessions:
                return self.sessions[session_id]
            return None

    def bind_session_to_chat(self, session_id: str, chat_id: str):
        """
        Associa uma sessão a um chat ID.
        Usado para mapear sessões UUID para chat IDs persistentes.

        Args:
            session_id: ID da sessão (UUID)
            chat_id: ID do chat (UUID)
        """
        try:
            session = self.get_session(session_id)
            session.chat_id = chat_id
            self.chat_to_session_map[chat_id] = session_id  # Store the mapping
            # Dados armazenados em banco de dados, não em arquivos JSON
            debug(f"[ChatManager] Sessão {session_id} associada ao chat {chat_id}")
        except Exception as e:
            error(f"[ChatManager] Erro ao associar sessão ao chat: {e}")

    def list_chats(self) -> list:
        """
        Lista todos os chats existentes com data, ID e nome.
        Nota: Chats são recuperados do banco de dados, não de arquivos JSON.

        Returns:
            Lista vazia (chats são gerenciados pelo banco de dados)
        """
        # Todos os chats são armazenados em banco de dados
        return []

    def load_chat(self, session_id: str, chat_id: str) -> bool:
        """
        Carrega um chat anterior para uma sessão específica.
        Nota: Chats são carregados do banco de dados, não de arquivos JSON.

        Args:
            session_id: ID da sessão
            chat_id: ID do chat a carregar

        Returns:
            True se carregado com sucesso, False caso contrário
        """
        # Chats são gerenciados pelo banco de dados
        # Esta função agora apenas mapeia a sessão ao chat_id
        try:
            session = self.get_session(session_id)
            session.chat_id = chat_id
            debug(f"Chat {chat_id} mapeado para a sessão {session_id}")
            return True
        except Exception as e:
            debug(f"Erro ao mapear chat para a sessão {session_id}: {e}")
            return False

    def get_conversation_history(self, session_id: str) -> list:
        """
        Retorna uma cópia do histórico de conversas para uma sessão.

        Args:
            session_id: ID da sessão

        Returns:
            Cópia profunda do histórico de conversas
        """
        session = self.get_session(session_id)
        return copy.deepcopy(session.conversation_history)

    def save_message(self, job_id: str, role: str, content: str, **kwargs):
        """
        Salva uma mensagem no arquivo individual do agent para uma sessão.

        Args:
            job_id: ID do job de processamento
            role: Role da mensagem (user, assistant, tool, system)
            content: Conteúdo da mensagem
            **kwargs: Metadados adicionais (agent_name, agent_id, etc)
        """
        # job_id is tracked but session retrieval uses chat_id if available
        chat_id = kwargs.get("chat_id")
        session = self.get_session(chat_id) if chat_id else None

        # Se a sessão não tem chat_id associado, não consegue salvar
        # (chat deve ser criado na rota antes de processar mensagens)
        if not session or not session.chat_id:
            from App.Core.Logs import warning as log_warning

            log_warning(
                f"[ChatManager.save_message] Sessão {session_id} sem chat_id associado"
            )
            return

        # Normalizar conteúdo
        if isinstance(content, dict):
            content = content.get("content", str(content))
        elif not isinstance(content, str):
            content = str(content)

        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs,
        }

        agent_name = kwargs.get("agent_name")

        # Validação de segurança
        if agent_name and str(agent_name).strip().lower() == "all":
            warning(
                f"[SECURITY] Tentativa de salvar mensagem com agent_name='all'. Ignorando."
            )
            return

        if not agent_name:
            agent_name = "ASSISTANT"
            message["agent_name"] = agent_name
            message["agent_id"] = "orchestrator-global"

        session.conversation_history.append(message)
        self._save_message_to_agent_file(session_id, agent_name, message)

    def _save_message_to_agent_file(
        self, session_id: str, agent_name: str, message: dict
    ):
        """
        Salva mensagem no arquivo individual do agent para uma sessão.

        Args:
            session_id: ID da sessão
            agent_name: Nome do agent
            message: Mensagem a salvar
        """
        # Mensagens são salvas no banco de dados via DatabaseManager
        # Esta função é mantida para compatibilidade mas não faz nada
        debug(f"[ChatManager] Mensagem do agent {agent_name} armazenada em DB")

    def _extract_chat_name_from_messages(self, messages: list) -> str:
        """
        Extrai o nome do chat da primeira mensagem do usuário (máx 50 caracteres).

        Args:
            messages: Lista de mensagens

        Returns:
            Nome do chat ou None
        """
        for msg in messages:
            # Procura pela primeira mensagem do usuário
            is_user_message = (
                msg.get("role") == "user" or msg.get("agent_name") == "USER"
            )
            if is_user_message:
                content = msg.get("content", "").strip()
                if content:
                    # Remove quebras de linha e limita a 50 caracteres
                    name = content.replace("\n", " ").replace("\r", "")[:50]
                    return name
        return None

    def rename_chat(self, session_id: str, new_name: str) -> bool:
        """
        Renomeia um chat manualmente (máx 50 caracteres).

        Args:
            session_id: ID da sessão
            new_name: Novo nome do chat

        Returns:
            True se renomeado com sucesso, False caso contrário
        """
        session = self.get_session(session_id)
        if not session.chat_id:
            return False
        return self.rename_chat_by_id(session.chat_id, new_name)

    def rename_chat_by_id(self, chat_id: str, new_name: str) -> bool:
        """
        Renomeia um chat manualmente usando chat_id.
        Nota: Renomeação é gerenciada pelo banco de dados.

        Args:
            chat_id: ID do chat
            new_name: Novo nome

        Returns:
            True se renomeado com sucesso, False caso contrário
        """
        # Renomeação é gerenciada pelo banco de dados
        debug(f"Chat {chat_id} renomeação gerenciada pelo banco de dados")
        return True

    def sync_to_main_chat(self, job_id: str):
        """
        Sincroniza mensagens de todos os agents para o chat principal.
        Nota: Sincronização agora é gerenciada pelo banco de dados.

        Args:
            job_id: ID do job de processamento
        """
        # Sincronização é feita pelo DatabaseManager.sync_isolated_to_main
        debug(
            f"[ChatManager] Sincronização gerenciada pelo banco de dados para job {job_id}"
        )

    def _filter_and_reorganize_messages(self, all_messages: list) -> list:
        """
        Filtra e reorganiza mensagens para o arquivo principal.
        Remove mensagens de agentes internos e tool calls que não agregam valor.

        Args:
            all_messages: Lista de todas as mensagens

        Returns:
            Lista de mensagens filtradas
        """
        filtered = []
        skip_indices = set()

        # Identifica respostas de agents via tool
        agent_responses_via_tool = {}
        for i, msg in enumerate(all_messages):
            if msg.get("role") == "tool" and msg.get("_agent_execution"):
                agent_name = msg.get("_agent_execution", {}).get("agent_name")
                if agent_name:
                    agent_responses_via_tool[agent_name] = msg.get("timestamp")

        # Filtra mensagens
        for i, msg in enumerate(all_messages):
            if i in skip_indices:
                continue

            msg_clean = {k: v for k, v in msg.items() if k != "_source_agent_file"}

            # Skip: Tool calls de agentes
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                tool_calls = msg.get("tool_calls", [])
                tool_names = [tc.get("function", {}).get("name") for tc in tool_calls]
                if all(name in ["agent", "print"] for name in tool_names):
                    skip_indices.add(i)
                    continue
                filtered.append(msg_clean)
                continue

            # Skip: Respostas de agents que já foram sincronizadas
            if (
                msg.get("role") == "assistant"
                and msg.get("agent_name") in agent_responses_via_tool
            ):
                skip_indices.add(i)
                continue

            # Skip: Tool messages de agent calls
            if msg.get("role") == "tool" and msg.get("name") == "agent":
                skip_indices.add(i)
                continue

            # Skip: "Chamando..." messages sem tool_calls reais
            if (
                msg.get("role") == "assistant"
                and "Chamando" in msg.get("content", "")
                and not msg.get("tool_calls")
            ):
                skip_indices.add(i)
                continue

            # Remove campos internos
            msg_clean = {k: v for k, v in msg_clean.items() if not k.startswith("_")}
            filtered.append(msg_clean)

        return filtered

    def _get_chat_created_at(self, session_id: str) -> str:
        """
        Obtém data de criação do chat para uma sessão.

        Args:
            session_id: ID da sessão

        Returns:
            Data de criação em ISO format
        """
        session = self.get_session(session_id)
        try:
            # main_chat_file = None  # chats_dir removido / f"{}{session.chat_id}" / f"{}{session.chat_id}{}"
            if False:  # Arquivo removido
                with open(main_chat_file, "r", encoding="utf-8") as f:
                    chat_data = json.load(f)
                    return chat_data.get("created_at", session.created_at.isoformat())
        except:
            pass
        return session.created_at.isoformat()
