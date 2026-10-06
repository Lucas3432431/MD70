"""
Rotas de Chat - FastAPI Routes
Apenas rotas e validacoes HTTP, logica de negocio delegada para ChatService
"""

import os
import threading
import asyncio
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from fastapi import (
    APIRouter,
    Request,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    Form,
    File,
    UploadFile,
    Query,
)
from pydantic import BaseModel, Field
import base64
import tempfile

import uuid
from datetime import datetime

from App.Core.Logs import debug, info, warning, error
from App.Features.Auth import get_auth_service
from App.Features.Chat.ChatService import ChatService
from App.Core.Services.Common.Dependencies import COMPONENTS
from App.Features.AgentOrchestrator import AgentOrchestrator
from App.Core.Crunch.Storage.StorageManager import StorageManager
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Features.Credits.CreditsManager import CreditsManager

from App.Features.Job import get_job_manager
from fastapi.responses import FileResponse, JSONResponse
from App.Core.Services.Inspirations.InspirationRoutes import get_inspiration_by_id

# ========================================================================
# WEBSOCKET MANAGER
# ========================================================================


class ChatWatcher:
    """Gerencia conexoes WebSocket por chat_id (multiplas conexoes OK)"""

    def __init__(self):
        self.clients: Dict[str, list[WebSocket]] = {}  # chat_id -> lista de WebSockets

    async def connect(self, websocket: WebSocket, chat_id: str):
        # Inicializar lista se nao existir
        if chat_id not in self.clients:
            self.clients[chat_id] = []

        # Adicionar nova conexao
        self.clients[chat_id].append(websocket)
        debug(
            f"[WS] [OK] Conexao ativa para chat {chat_id} ({len(self.clients[chat_id])} cliente(s))"
        )

    async def disconnect(self, websocket: WebSocket, chat_id: str):
        if chat_id in self.clients:
            try:
                self.clients[chat_id].remove(websocket)
                debug(
                    f"[WS] [DISCONN] Desconectado: chat {chat_id} ({len(self.clients[chat_id])} cliente(s) restante(s))"
                )

                # Limpar entrada se lista vazia
                if not self.clients[chat_id]:
                    del self.clients[chat_id]
            except ValueError:
                pass

    async def broadcast(self, chat_id: str, data: Dict[str, Any]):
        """Envia mensagem para TODOS os clientes conectados a um chat_id"""
        if chat_id not in self.clients or not self.clients[chat_id]:
            debug(f"[WS] [WARN] Nenhum cliente conectado para chat {chat_id}")
            return

        disconnected = []
        for ws in self.clients[chat_id]:
            try:
                await ws.send_json(data)
            except Exception as e:
                debug(f"[WS] [ERR] Erro ao enviar: {e}")
                disconnected.append(ws)

        # Remover conexoes quebradas
        for ws in disconnected:
            try:
                self.clients[chat_id].remove(ws)
            except ValueError:
                pass

        debug(
            f"[WS] [SEND] Mensagem enviada para chat {chat_id} ({len(self.clients[chat_id])} cliente(s))"
        )

    async def shutdown_all(self):
        """Fecha TODAS as conexoes WebSocket (para hot reload/shutdown)"""
        total = 0
        for chat_id, clients in list(self.clients.items()):
            for ws in clients:
                try:
                    await ws.close(code=1001, reason="Server shutdown")
                    total += 1
                except Exception as e:
                    debug(f"[WS] [WARN] Erro ao fechar conexao: {e}")

        self.clients.clear()
        debug(f"[WS] [STOP] Shutdown: {total} conexao(oes) fechada(s)")


# Instancia global (exportada para uso em Services.py)
chat_watcher = ChatWatcher()

# ── Loop reference para notificações WS a partir de threads síncronas ─────────
_main_loop: asyncio.AbstractEventLoop | None = None


def capture_main_loop() -> None:
    """Captura o event loop rodando. Chamar no startup do FastAPI."""
    global _main_loop
    try:
        _main_loop = asyncio.get_running_loop()
    except RuntimeError:
        pass


def notify_user_ws(user_id: str, data: dict) -> None:
    """Agenda um broadcast para user_watcher a partir de qualquer thread."""
    if _main_loop and not _main_loop.is_closed():
        asyncio.run_coroutine_threadsafe(
            user_watcher.broadcast(user_id, data), _main_loop
        )


class UserWatcher:
    """Gerencia conexoes WebSocket por user_id para notificacoes globais"""

    def __init__(self):
        self.clients: Dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        if user_id not in self.clients:
            self.clients[user_id] = []
        self.clients[user_id].append(websocket)
        debug(
            f"[UWS] Conectado user {user_id} ({len(self.clients[user_id])} cliente(s))"
        )

    async def disconnect(self, websocket: WebSocket, user_id: str):
        if user_id in self.clients:
            try:
                self.clients[user_id].remove(websocket)
                if not self.clients[user_id]:
                    del self.clients[user_id]
            except ValueError:
                pass

    async def broadcast(self, user_id: str, data: Dict[str, Any]):
        if user_id not in self.clients or not self.clients[user_id]:
            return
        disconnected = []
        for ws in self.clients[user_id]:
            try:
                await ws.send_json(data)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            try:
                self.clients[user_id].remove(ws)
            except ValueError:
                pass


user_watcher = UserWatcher()

__all__ = [
    "chat_router",
    "chat_operations_router",
    "chat_watcher",
    "user_watcher",
    "capture_main_loop",
    "notify_user_ws",
    "broadcast_db_updated",
    "broadcast_context_limit_reached",
]


# ========================================================================
# HELPERS
# ========================================================================


async def _broadcast_job_status_async(
    chat_id: str,
    job_id: str,
    status: str,
    response: Optional[str] = None,
    user_id: Optional[str] = None,
):
    """Coroutine de broadcast — deve rodar no main event loop."""
    try:
        await chat_watcher.broadcast(
            chat_id,
            {
                "type": "job_status",
                "job_id": job_id,
                "status": status,
            },
        )
        debug(
            f"[WS BROADCAST] job_status enviado — chat={chat_id} job={job_id} status={status}"
        )
    except Exception as e:
        debug(f"[WS BROADCAST] Erro ao enviar job_status: {e}")


def _broadcast_job_status(
    chat_id: str,
    job_id: str,
    status: str,
    response: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """Agenda o broadcast no main event loop a partir de qualquer thread."""
    if _main_loop and not _main_loop.is_closed():
        asyncio.run_coroutine_threadsafe(
            _broadcast_job_status_async(chat_id, job_id, status),
            _main_loop,
        )
    else:
        debug(
            f"[WS BROADCAST] main_loop indisponível — job_status não enviado para job {job_id}"
        )


def broadcast_db_updated(chat_id: str) -> None:
    """Notifica clientes WS do chat que o DB foi atualizado. Seguro para threads."""
    if _main_loop and not _main_loop.is_closed():
        asyncio.run_coroutine_threadsafe(
            chat_watcher.broadcast(chat_id, {"type": "db_updated", "chat_id": chat_id}),
            _main_loop,
        )


def broadcast_context_limit_reached(chat_id: str) -> None:
    """Notifica clientes WS que o chat atingiu o limite de contexto. Seguro para threads."""
    if _main_loop and not _main_loop.is_closed():
        asyncio.run_coroutine_threadsafe(
            chat_watcher.broadcast(
                chat_id,
                {"type": "context_limit_reached", "chat_id": chat_id},
            ),
            _main_loop,
        )


async def _mark_chat_unseen_and_notify(chat_id: str):
    """Marca chat de trigger/scheduled como unseen e notifica o user via WS"""
    try:
        from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager as _DBM

        _db = _DBM()
        row = _db.fetch_one(
            "SELECT user_id, source FROM chats WHERE chat_id = :c",
            {"c": chat_id},
        )
        if not row or not row.get("source"):
            return
        _db.execute_query(
            "UPDATE chats SET seen = 0 WHERE chat_id = :c",
            {"c": chat_id},
        )
        user_id = row["user_id"]
        counts = (
            _db.fetch_one(
                """SELECT
                COALESCE(SUM(CASE WHEN source='trigger' THEN 1 ELSE 0 END), 0) AS triggers,
                COALESCE(SUM(CASE WHEN source='scheduled' THEN 1 ELSE 0 END), 0) AS scheduled
               FROM chats WHERE user_id = :uid AND seen = 0""",
                {"uid": user_id},
            )
            or {}
        )
        await user_watcher.broadcast(
            user_id,
            {
                "type": "unseen_update",
                "triggers": int(counts.get("triggers") or 0),
                "scheduled": int(counts.get("scheduled") or 0),
            },
        )
        debug(f"[UWS] Chat {chat_id} marcado unseen; notificado user {user_id}")
    except Exception as e:
        debug(f"[UWS] Erro ao marcar unseen: {e}")


# ========================================================================
# MODELS
# ========================================================================


class CreateChatRequest(BaseModel):
    """Requisicao para criar um novo chat"""

    chat_name: str = Field(..., description="Nome do novo chat", min_length=1)
    message: Optional[str] = Field(None, description="Mensagem inicial (opcional)")
    model: str = Field("gpt-4o-mini", description="Modelo de IA a usar")
    agent_id: Optional[str] = Field(
        "orchestrator-global", description="ID do agente vinculado ao chat"
    )


class AttachmentInfo(BaseModel):
    """Informacao de um attachment"""

    attachment_type: str = Field(
        ..., description="Tipo de attachment: 'file' ou 'template'"
    )
    attachment_id: str = Field(..., description="ID do arquivo ou template")


class SendMessageRequest(BaseModel):
    """Requisicao para enviar uma mensagem"""

    message: str = Field(..., description="Conteudo da mensagem", min_length=1)
    context: Optional[Dict[str, Any]] = Field(
        None, description="Contexto adicional (chave-valor)"
    )
    model: str = Field("gpt-4o-mini", description="Modelo de IA a usar")
    agent_id: Optional[str] = Field(
        "orchestrator-global", description="ID do agente para processar a mensagem"
    )
    attachment: Optional[AttachmentInfo] = Field(
        None, description="Attachment unico (arquivo ou template)"
    )


class RenameChatRequest(BaseModel):
    """Requisicao para renomear um chat"""

    chat_name: str = Field(..., description="Novo nome do chat", min_length=1)


class UpdateCalendarPostRequest(BaseModel):
    """Requisicao para atualizar um post do calendario"""

    post_date: Optional[str] = Field(None, description="Nova data do post (DD.MM.YYYY)")
    short_description: Optional[str] = Field(None, description="Nova descricao do post")


class FeedbackRequest(BaseModel):
    """Requisicao para enviar feedback sobre uma mensagem"""

    feedback: Optional[str] = Field(
        None, description="Feedback do usuario (positivo, negativo, etc)"
    )


class QuizAnswerRequest(BaseModel):
    """Requisicao para enviar respostas de um quiz"""

    quiz_call_id: str = Field(..., description="ID do quiz/tool_call")
    answers: List[Dict[str, Any]] = Field(
        ..., description="Lista de respostas {question, answer}"
    )
    attachment_id: Optional[str] = Field(
        None, description="ID do attachment único (questão com attachment: true)"
    )
    attachment_ids: Optional[List[str]] = Field(
        None,
        description="IDs de múltiplos attachments (questão com multiple_attach: true)",
    )


class UpdateCreativeRequest(BaseModel):
    """Requisicao para atualizar uma composicao criativa (Canva-like)"""

    title: Optional[str] = None
    state: Dict[str, Any] = Field(
        ..., description="Estado completo da composicao (arvore JSON)"
    )
    version: Optional[int] = None
    preview_url: Optional[str] = None


# ========================================================================
# ROUTER
# ========================================================================

chat_router = APIRouter(tags=["Chat"], prefix="/api/chats")
chat_operations_router = APIRouter(tags=["Chat"], prefix="/api")


# ========================================================================
# DEPENDENCY - Extrair user_id / client_id do token (helpers globais)
# ========================================================================

from App.Core.Services.Auth.RequestAuth import (
    get_user_id_from_request as get_user_id_from_token,
    get_client_id_from_request as get_client_id_from_token,
)


# ========================================================================
# HELPER FUNCTIONS - Verificacao de plano Trial
# ========================================================================


def check_trial_plan_restrictions(identifier: str, operation: str) -> None:
    """
    Verifica se o usuario pertence a um cliente no plano trial ou free e aplica restricoes.

    Args:
        identifier: ID do usuario ou ID do cliente
        operation: Operacao sendo realizada ('create_chat', 'rename_chat', 'delete_chat', 'download_chat', etc.)

    Raises:
        HTTPException: Se operacao nao permitida para plano trial/free
    """
    try:
        # Buscar informacoes do plano atraves do usuario ou cliente
        # Se for um ID numerico curto, provavelmente e client_id
        is_numeric_id = str(identifier).isdigit() or (
            isinstance(identifier, str) and len(identifier) < 5
        )

        if is_numeric_id:
            query = """
            SELECT COALESCE(p.plan_type, 'trial') as plan_type, c.client_id
            FROM clients c
            LEFT JOIN plans p ON c.plan_id = p.plan_id
            WHERE c.client_id = :id
            LIMIT 1
            """
        else:
            query = """
            SELECT COALESCE(p.plan_type, 'trial') as plan_type, u.client_id
            FROM users u
            LEFT JOIN clients c ON u.client_id = c.client_id
            LEFT JOIN plans p ON c.plan_id = p.plan_id
            WHERE u.user_id = :id
            LIMIT 1
            """

        result = DatabaseManager.fetch_one(query, {"id": identifier})

        if not result:
            debug(
                f"[PLAN_CHECK] Identificador {identifier} nao encontrado - permitindo operacao {operation}"
            )
            return

        plan_type = result.get("plan_type", "").lower()
        client_id = result.get("client_id")

        debug(
            f"[PLAN_CHECK] ID {identifier} (Client {client_id}) - Plan Type: {plan_type}"
        )

        # Verificar se e plano restrito (trial ou free)
        is_restricted = plan_type in ["trial", "free"]

        if is_restricted:
            if operation == "create_chat":
                # Para create_chat, precisamos do user_id real para contar os chats
                user_id = identifier
                if is_numeric_id:
                    user_query = (
                        "SELECT user_id FROM users WHERE client_id = :client_id LIMIT 1"
                    )
                    user_res = DatabaseManager.fetch_one(
                        user_query, {"client_id": identifier}
                    )
                    if user_res:
                        user_id = user_res.get("user_id")

                # Limite de 1 chat por usuário no plano free/trial — comentado
                # chat_count_query = (
                #     "SELECT COUNT(*) as chat_count FROM chats WHERE user_id = :user_id"
                # )
                # chat_count_result = DatabaseManager.fetch_one(
                #     chat_count_query, {"user_id": user_id}
                # )
                # chat_count = (
                #     chat_count_result.get("chat_count", 0) if chat_count_result else 0
                # )
                # if chat_count > 0:
                #     raise HTTPException(status_code=402, detail="signup for more")

            elif operation in [
                "rename_chat",
                "delete_chat",
                "download_chat",
                "download_asset",
                "download_document",
            ]:
                raise HTTPException(status_code=402, detail="signup for more")

    except HTTPException:
        raise
    except Exception as e:
        debug(f"[PLAN_CHECK] Erro ao verificar plano (continuando): {e}")
        # Nao bloquear a operacao se houver erro na verificacao


def validate_and_renew_token_for_new_chat(
    request: Request,
) -> tuple[str, Optional[dict]]:
    """
    Valida o token para a rota /new-chat e renova se expirado (apenas para trial).

    Returns:
        (user_id, response_headers) - user_id ou None se sem autenticacao
        response_headers: dict com cookies a setar se token foi renovado

    Raises:
        HTTPException: Se erro ao verificar/renovar token
    """
    try:
        auth_service = get_auth_service()

        # Verificar se tem access_token
        access_token = request.cookies.get("access_token")

        if not access_token:
            # Sem token - retornar None (frontend deve mostrar AgreementPopup)
            debug("[NEW-CHAT] Sem access_token no cookie")
            return None, None

        # Verificar se token e valido
        payload = auth_service.verify_token(access_token)

        if payload:
            # Token valido
            user_id = payload.get("user_id")
            debug(f"[NEW-CHAT] Token valido para user {user_id}")
            return user_id, None

        # Token expirado - tentar renovar com refresh_token
        debug("[NEW-CHAT] Token expirado, tentando renovar...")
        refresh_token = request.cookies.get("refresh_token")

        if not refresh_token:
            # Sem refresh token tambem - pedir nova autenticacao
            debug("[NEW-CHAT] Sem refresh_token, retornando None")
            return None, None

        # Validar refresh_token
        refresh_payload = auth_service.verify_token(refresh_token)

        if not refresh_payload:
            # Refresh token tambem expirou
            debug("[NEW-CHAT] Refresh token expirado")
            return None, None

        user_id = refresh_payload.get("user_id")

        # Verificar se user e trial ANTES de renovar
        query = """
        SELECT COALESCE(p.plan_type, 'trial') as plan_type
        FROM users u
        LEFT JOIN clients c ON u.client_id = c.client_id
        LEFT JOIN plans p ON c.plan_id = p.plan_id
        WHERE u.user_id = :user_id
        """
        result = DatabaseManager.fetch_one(query, {"user_id": user_id})
        plan_type = result.get("plan_type", "").lower() if result else "trial"

        # Apenas renovar token se for trial
        if plan_type != "trial":
            debug(
                f"[NEW-CHAT] User {user_id} nao e trial (plan_type={plan_type}), negando renovacao"
            )
            return None, None

        # Renovar token para usuario trial
        debug(f"[NEW-CHAT] Renovando token para usuario trial {user_id}")

        user_data = {
            "user_id": refresh_payload.get("user_id"),
            "email": refresh_payload.get("email"),
            "full_name": refresh_payload.get("full_name"),
            "role": refresh_payload.get("role", "member"),
            "client_id": refresh_payload.get("client_id"),
        }

        new_access_token = auth_service.generate_access_token(user_data)

        # Retornar user_id e headers com novo cookie
        response_headers = {
            "set-cookie": f"access_token={new_access_token}; HttpOnly; Secure; SameSite=Lax; Max-Age={86400}"
        }

        info(f"[NEW-CHAT] Token renovado para usuario trial {user_id}")
        return user_id, response_headers

    except Exception as e:
        error(f"[NEW-CHAT] Erro ao validar/renovar token: {e}")
        raise HTTPException(status_code=500, detail="Erro ao validar autenticacao")


# ========================================================================
# HELPER FUNCTIONS
# ========================================================================


async def move_attachments_from_temp(
    client_id: int, chat_id: str, message_id: str, attachment_ids: List[str]
) -> List[Dict[str, Any]]:
    """
    Move attachments from TempFolder to Chat/Message folder e atualiza DB.

    Args:
        client_id: ID do cliente
        chat_id: ID do chat
        message_id: ID da mensagem
        attachment_ids: Lista de attachment_ids a mover

    Returns:
        Lista de attachments movidos com informacoes atualizadas
    """
    moved_attachments = []

    if not attachment_ids:
        return moved_attachments

    try:
        from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager

        # Query user_id from first attachment
        query_user = """
        SELECT user_id FROM attachments WHERE attachment_id = :attachment_id
        """
        attachment_record = DatabaseManager.fetch_one(
            query_user, {"attachment_id": attachment_ids[0]}
        )

        if not attachment_record:
            error(
                f"[MOVE_ATTACHMENTS] Primeiro attachment nao encontrado: {attachment_ids[0]}"
            )
            return moved_attachments

        user_id = attachment_record.get("user_id")

        base_path = StorageManager.LOCAL_STORAGE_BASE
        temp_folder = base_path / f"client_{client_id}" / "TempFolder"
        dest_folder = (
            base_path
            / f"client_{client_id}"
            / f"user_{user_id}"
            / f"chat_{chat_id}"
            / f"message_{message_id}"
        )

        # Garantir que a pasta de destino existe
        StorageManager.ensure_path_exists(dest_folder)

        # Mover cada arquivo
        for attachment_id in attachment_ids:
            try:
                # Procurar arquivo em TempFolder
                temp_files = list(temp_folder.glob(f"{attachment_id}*"))

                if not temp_files:
                    warning(
                        f"[MOVE_ATTACHMENTS] Arquivo nao encontrado no TempFolder: {attachment_id}"
                    )
                    continue

                temp_file = temp_files[0]
                dest_file = dest_folder / temp_file.name

                # Mover arquivo
                temp_file.rename(dest_file)
                rel_src = StorageManager.get_relative_path(temp_file)
                rel_dst = StorageManager.get_relative_path(dest_file)
                debug(f"[MOVE_ATTACHMENTS] Arquivo movido: {rel_src} -> {rel_dst}")

                # Atualizar DB com caminho relativo e extensao
                # Caminho relativo a partir de Data/Database/
                relative_path = f"client_{client_id}/user_{user_id}/chat_{chat_id}/message_{message_id}/{temp_file.name}"

                # Extrair extensao do arquivo
                file_ext = temp_file.suffix.lower().lstrip(
                    "."
                )  # Remove o ponto da extensao
                if not file_ext:
                    # Se nao tiver extensao, usar o nome completo do arquivo
                    file_ext = (
                        temp_file.name.split(".")[-1].lower()
                        if "." in temp_file.name
                        else "unknown"
                    )

                update_query = """
                UPDATE attachments
                SET chat_id = :chat_id, message_id = :message_id, is_temp = 0, storage_path = :storage_path, storage_env = 'local', extension = :extension, file_type = :file_type
                WHERE attachment_id = :attachment_id
                """

                DatabaseManager.execute_query(
                    update_query,
                    {
                        "attachment_id": attachment_id,
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "storage_path": relative_path,
                        "extension": file_ext,
                        "file_type": file_ext,
                    },
                )

                info(
                    f"[MOVE_ATTACHMENTS] Attachment movido e DB atualizado: {attachment_id}"
                )
                moved_attachments.append(
                    {
                        "attachment_id": attachment_id,
                        "storage_path": str(dest_file),
                        "status": "moved",
                    }
                )

            except Exception as e:
                error(f"[MOVE_ATTACHMENTS] Erro ao mover {attachment_id}: {e}")
                moved_attachments.append(
                    {"attachment_id": attachment_id, "status": "error", "error": str(e)}
                )

        return moved_attachments

    except Exception as e:
        error(f"[MOVE_ATTACHMENTS] Erro geral: {e}")
        raise


async def register_template_attachment(
    user_id: str, chat_id: str, message_id: str, template_id: str
) -> Dict[str, Any]:
    """
    Registra um attachment de template no banco de dados.

    Args:
        user_id: ID do usuario
        chat_id: ID do chat
        message_id: ID da mensagem
        template_id: ID do template

    Returns:
        Dict com informacoes do attachment registrado
    """
    try:
        attachment_id = str(uuid.uuid4())

        # Resolve file_name from inspiration data
        file_name = None
        try:
            inspiration = get_inspiration_by_id(template_id)
            if inspiration:
                raw_image = inspiration.get("image", "")
                file_name = (
                    raw_image.split("/")[-1] if "/" in raw_image else raw_image or None
                )
        except Exception:
            pass

        query = """
        INSERT INTO attachments
        (attachment_id, user_id, chat_id, message_id, template_id, file_name, attachment_type, is_temp)
        VALUES (:attachment_id, :user_id, :chat_id, :message_id, :template_id, :file_name, 'template', 0)
        """

        DatabaseManager.execute_query(
            query,
            {
                "attachment_id": attachment_id,
                "user_id": user_id,
                "chat_id": chat_id,
                "message_id": message_id,
                "template_id": template_id,
                "file_name": file_name,
            },
        )

        debug(
            f"[REGISTER_TEMPLATE] Template attachment registrado: {attachment_id} (template_id: {template_id}, file_name: {file_name})"
        )

        return {
            "attachment_id": attachment_id,
            "template_id": template_id,
            "file_name": file_name,
            "status": "registered",
        }

    except Exception as e:
        error(f"[REGISTER_TEMPLATE] Erro ao registrar template attachment: {e}")
        raise


async def register_drive_attachment(
    user_id: str,
    chat_id: str,
    message_id: str,
    file_id: str,
    file_name: str,
    mime_type: str,
) -> Dict[str, Any]:
    """Registra um attachment de Google Drive no banco de dados."""
    try:
        attachment_id = str(uuid.uuid4())

        query = """
        INSERT INTO attachments
        (attachment_id, user_id, chat_id, message_id, file_name, file_type, attachment_type, is_temp)
        VALUES (:attachment_id, :user_id, :chat_id, :message_id, :file_name, :file_type, 'drive_file', 0)
        """

        DatabaseManager.execute_query(
            query,
            {
                "attachment_id": attachment_id,
                "user_id": user_id,
                "chat_id": chat_id,
                "message_id": message_id,
                "file_name": file_name,
                "file_type": file_id,  # store drive file_id in file_type column for retrieval
            },
        )

        debug(
            f"[REGISTER_DRIVE] Drive attachment registrado: {attachment_id} (file_id: {file_id}, name: {file_name})"
        )

        return {
            "attachment_id": attachment_id,
            "file_id": file_id,
            "file_name": file_name,
            "status": "registered",
        }

    except Exception as e:
        error(f"[REGISTER_DRIVE] Erro ao registrar drive attachment: {e}")
        raise


# ========================================================================
# HELPER FUNCTIONS FOR IMAGE CONTEXTUALIZATION
# ========================================================================


def contextualize_image_with_agent(
    client_id: int,
    chat_id: str,
    message_id: str,
    attachment_ids: List[str],
    user_message: str,
    job_id: str,
) -> Optional[str]:
    """
    Processa imagens e chama o vision model (OpenAI GPT-4o) para gerar contexto.

    Args:
        client_id: ID do cliente
        chat_id: ID do chat
        message_id: ID da mensagem
        attachment_ids: Lista de IDs dos attachments
        user_message: Mensagem original do usuario
        job_id: ID do job para logging

    Returns:
        String com o contexto gerado pela IA, ou None se falhar
    """
    try:
        if not attachment_ids:
            return None

        # Localizar arquivo de imagem
        base_path = StorageManager.LOCAL_STORAGE_BASE
        message_folder = (
            base_path
            / f"client_{client_id}"
            / f"chat_{chat_id}"
            / f"message_{message_id}"
        )

        rel_folder = StorageManager.get_relative_path(message_folder)
        debug(f"[IMAGE-CONTEXT {job_id}] Procurando imagens em: {rel_folder}")

        # Encontrar primeira imagem (geralmente webp)
        image_files = (
            list(message_folder.glob("*.webp"))
            + list(message_folder.glob("*.jpg"))
            + list(message_folder.glob("*.jpeg"))
        )

        if not image_files:
            warning(
                f"[IMAGE-CONTEXT {job_id}] Nenhuma imagem encontrada em {rel_folder}"
            )
            return None

        image_file = image_files[0]
        rel_image = StorageManager.get_relative_path(image_file)
        debug(f"[IMAGE-CONTEXT {job_id}] Imagem encontrada: {rel_image}")

        # Ler imagem como base64
        import base64

        with open(image_file, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        # Criar prompt para analise de imagem
        system_prompt = """Voce e um especialista em analise de imagens para campanhas de marketing.
Analise a imagem fornecida junto com a mensagem do usuario e forneca um contexto conciso.

Forneca uma analise em maximo 3-4 paragrafos que:
1. Descreva o conteudo visual principal da imagem
2. Identifique elementos que podem ser uteis para marketing
3. Sugira como a imagem pode ser usada em diferentes formatos (feed, stories, reels)
4. Complemente o contexto da mensagem do usuario

Nao use markdown, emojis ou analises muito longas. Apenas texto puro."""

        analysis_prompt = f"Mensagem do usuario: {user_message}\n\nAnalize esta imagem e forneca contexto."

        # Tentar usar OpenAI GPT-4o REST API (Multimodal)
        try:
            from App.Core.Settings.Settings import get_openai_api_key

            openai_api_key = get_openai_api_key()

            if not openai_api_key:
                warning(f"[IMAGE-CONTEXT {job_id}] OpenAI API Key nao configurada")
                raise ValueError("OpenAI API Key missing")

            debug(
                f"[IMAGE-CONTEXT {job_id}] Tentando usar OpenAI GPT-4o para analise de imagem (REST)"
            )

            image_media_type = "image/webp"
            if str(image_file).endswith(".jpg") or str(image_file).endswith(".jpeg"):
                image_media_type = "image/jpeg"

            import requests

            headers = {
                "Authorization": f"Bearer {openai_api_key}",
                "Content-Type": "application/json",
            }

            payload = {
                "model": "gpt-4o",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": analysis_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{image_media_type};base64,{image_data}"
                                },
                            },
                        ],
                    },
                ],
                "temperature": 0.7,
            }

            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60,
            )

            if response.status_code == 200:
                data = response.json()
                context_response = data["choices"][0]["message"]["content"].strip()
                if context_response:
                    info(
                        f"[IMAGE-CONTEXT {job_id}] Analise de imagem gerada com sucesso via OpenAI GPT-4o"
                    )
                    return context_response
            else:
                warning(
                    f"[IMAGE-CONTEXT {job_id}] OpenAI API falhou ({response.status_code}): {response.text}"
                )

        except Exception as openai_error:
            warning(f"[IMAGE-CONTEXT {job_id}] Erro ao usar OpenAI: {openai_error}")

        # Fallback: Usar Claude vision API
        try:
            import anthropic

            debug(f"[IMAGE-CONTEXT {job_id}] Usando fallback - Claude vision API")

            # Verificar se API key esta configurada
            from App.Core.Settings.Settings import load_config as _load_config

            claude_api_key = _load_config().get("anthropic_api_key", "").strip()
            if not claude_api_key:
                warning(
                    f"[IMAGE-CONTEXT {job_id}] ANTHROPIC_API_KEY nao configurada, nao e possivel usar Claude fallback"
                )
                return None

            # Converter base64 para URL com media type
            image_media_type = "image/webp"
            if str(image_file).endswith(".jpg") or str(image_file).endswith(".jpeg"):
                image_media_type = "image/jpeg"

            client = anthropic.Anthropic(api_key=claude_api_key)
            message = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=8192,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": image_media_type,
                                    "data": image_data,
                                },
                            },
                            {"type": "text", "text": analysis_prompt},
                        ],
                    }
                ],
            )

            context_response = message.content[0].text if message.content else ""
            info(
                f"[IMAGE-CONTEXT {job_id}] Analise de imagem gerada com sucesso via Claude"
            )
            return context_response

        except Exception as claude_error:
            error(
                f"[IMAGE-CONTEXT {job_id}] Erro ao usar Claude fallback: {claude_error}"
            )
            warning(
                f"[IMAGE-CONTEXT {job_id}] Ambos OpenAI e Claude falharam, retornando None"
            )
            return None

    except Exception as e:
        error(f"[IMAGE-CONTEXT {job_id}] Erro geral ao processar imagem: {e}")
        import traceback

        debug(f"[IMAGE-CONTEXT {job_id}] Traceback: {traceback.format_exc()}")
        return None


# ========================================================================
# ROUTES
# ========================================================================


@chat_router.get("/health")
async def chat_health():
    """Health check da rota de chats"""
    debug("[GET /api/chat/health] Health check request")

    try:
        chat_service = ChatService()

        # Verificar se cliente padrao existe
        client_data = chat_service.db.fetch_one(
            "SELECT client_id, legal_company_name FROM clients WHERE client_id = 1", {}
        )

        if client_data:
            info(
                f"[GET /api/chat/health] Cliente padrao existe: {client_data.get('legal_company_name')}"
            )
        else:
            warning(
                "[GET /api/chat/health] Cliente padrao nao encontrado - banco pode estar vazio"
            )

        # Verificar se tabelas existem
        tables_check = chat_service.db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('chats', 'messages', 'clients')",
            {},
        )

        if tables_check:
            info("[GET /api/chat/health] Tabelas do banco de dados existem")
        else:
            warning("[GET /api/chat/health] Tabelas do banco podem estar faltando")

        return {
            "status": "ok",
            "message": "Chat router funcionando",
            "client_default_exists": bool(client_data),
            "database_initialized": bool(tables_check),
        }
    except Exception as e:
        error(f"[GET /api/chat/health] Erro no health check: {e}")
        return {
            "status": "error",
            "message": f"Erro ao verificar saude: {str(e)}",
            "error": str(e),
        }


@chat_router.post("/debug/chat-creation", status_code=200)
async def debug_chat_creation(request_data: CreateChatRequest, request: Request):
    """
    Endpoint de DEBUG para rastrear o fluxo de criacao e envio de mensagem.
    Cria um chat e envia uma mensagem de teste, retornando detalhes de cada passo.
    """
    try:
        client_id = get_client_id_from_token(request)

        steps = []

        # Passo 1: Criar chat
        try:
            chat_service = ChatService()
            create_result = chat_service.create_chat(
                client_id=client_id,
                chat_name=f"[DEBUG] {request_data.chat_name or 'Test Chat'}",
                message=request_data.message,
            )
            test_chat_id = create_result.get("chat_id")
            steps.append(
                {
                    "step": "create_chat",
                    "status": "success",
                    "chat_id": test_chat_id,
                    "chat_name": create_result.get("chat_name"),
                }
            )
        except Exception as e:
            return {
                "status": "failed",
                "step": "create_chat",
                "error": str(e),
                "steps": steps,
            }

        # Passo 2: Verificar que chat foi criado
        try:
            chat_check = chat_service.get_chat(test_chat_id, client_id)
            steps.append(
                {
                    "step": "verify_chat_exists",
                    "status": "success",
                    "chat_name": chat_check.get("chat_name"),
                    "messages_count": len(chat_check.get("messages", [])),
                }
            )
        except Exception as e:
            return {
                "status": "failed",
                "step": "verify_chat_exists",
                "error": str(e),
                "steps": steps,
            }

        # Passo 3: Preparar envio de mensagem
        test_message = "Test message para DEBUG"
        info(f"[DEBUG] Preparando para enviar mensagem ao chat {test_chat_id}")

        steps.append(
            {
                "step": "prepare_message_send",
                "status": "success",
                "test_chat_id": test_chat_id,
                "test_message": test_message,
            }
        )

        return {
            "status": "success",
            "message": "Chat criado com sucesso. Proximo passo: enviar mensagem para /api/chat/{}/message".format(
                test_chat_id
            ),
            "test_chat_id": test_chat_id,
            "test_message": test_message,
            "steps": steps,
            "next_request": {
                "method": "POST",
                "url": f"/api/chat/{test_chat_id}/message",
                "body": {"message": test_message, "model": "gpt-4o-mini"},
            },
        }

    except Exception as e:
        error(f"[DEBUG] Erro no endpoint de debug: {e}")
        return {"status": "error", "error": str(e)}


@chat_router.get("/health/test-db")
async def test_database():
    """Test endpoint para verificar se o banco de dados esta funcionando e salvando dados"""
    try:
        chat_service = ChatService()

        # Teste 1: Verificar cliente
        test_client_id = 1
        client_check = chat_service.db.fetch_one(
            "SELECT client_id FROM clients WHERE client_id = :id",
            {"id": test_client_id},
        )

        if not client_check:
            return {
                "status": "failed",
                "step": "client_check",
                "error": f"Cliente {test_client_id} nao existe no banco",
            }

        # Teste 2: Criar chat de teste
        test_chat_name = f"Test Chat {uuid.uuid4().hex[:8]}"
        try:
            create_result = chat_service.create_chat(
                client_id=test_client_id, chat_name=test_chat_name
            )
            test_chat_id = create_result.get("chat_id")
        except Exception as e:
            return {
                "status": "failed",
                "step": "create_chat",
                "error": f"Erro ao criar chat: {str(e)}",
            }

        # Teste 3: Verificar se chat foi salvo
        chat_check = chat_service.get_chat(
            chat_id=test_chat_id, client_id=test_client_id
        )

        if not chat_check:
            return {
                "status": "failed",
                "step": "verify_chat",
                "error": f"Chat {test_chat_id} foi criado mas nao pode ser recuperado",
            }

        # Teste 4: Salvar uma troca de mensagens
        try:
            chat_service.save_message_exchange(
                chat_id=test_chat_id,
                client_id=test_client_id,
                user_message="Teste de mensagem do usuario",
                ai_response="Teste de resposta da IA",
                model="test-model",
                agent_id="test-agent",
            )
        except Exception as e:
            return {
                "status": "failed",
                "step": "save_message_exchange",
                "error": f"Erro ao salvar mensagens: {str(e)}",
            }

        # Teste 5: Verificar se mensagens foram salvas
        updated_chat = chat_service.get_chat(
            chat_id=test_chat_id, client_id=test_client_id
        )

        messages_count = len(updated_chat.get("messages", []))

        return {
            "status": "success",
            "message": "Todos os testes passaram com sucesso",
            "test_chat_id": test_chat_id,
            "test_chat_name": test_chat_name,
            "messages_saved": messages_count,
        }

    except Exception as e:
        error(f"[GET /api/chat/health/test-db] Erro no teste: {e}")
        import traceback

        return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}


@chat_operations_router.post("/new-chat", status_code=201)
async def create_chat(request_data: CreateChatRequest, request: Request):
    """
    Cria um novo chat com suporte a mensagem inicial
    """
    try:
        # Autenticar com suporte a renovacao de token para trial
        user_id, token_headers = validate_and_renew_token_for_new_chat(request)

        # Se sem token, retornar 401 com Message: ShowAgreementPopup
        if user_id is None:
            debug(
                "[POST /api/new-chat] Sem autenticacao, retornando ShowAgreementPopup"
            )
            return JSONResponse(
                status_code=401, content={"message": "ShowAgreementPopup"}
            )

        # Obter plan_type (via user_id) - usar LEFT JOINs para suportar usuarios sem plano
        query = """
        SELECT COALESCE(p.plan_type, 'trial') as plan_type
        FROM users u
        LEFT JOIN clients c ON u.client_id = c.client_id
        LEFT JOIN plans p ON c.plan_id = p.plan_id
        WHERE u.user_id = :user_id
        """
        result = DatabaseManager.fetch_one(query, {"user_id": user_id})
        if not result:
            # Se usuario nao encontrado, usar trial como padrao
            plan_type = "trial"
            debug(
                f"[POST /api/new-chat] Usuario {user_id} sem plano associado, usando 'trial'"
            )
        else:
            plan_type = result.get("plan_type", "trial").lower()

        # Se for plan_type restrito (trial ou free), usar verificacao
        if plan_type in ["trial", "free"]:
            check_trial_plan_restrictions(user_id, "create_chat")
        else:
            # Para outros planos, verificar creditos disponiveis
            has_credits, available_credits = CreditsManager.check_credits(
                user_id, required_credits=1.0
            )
            if not has_credits:
                raise HTTPException(status_code=402, detail="no fundings")

        # Validar entrada
        chat_name = (request_data.chat_name or "").strip()
        message = (request_data.message or "").strip() if request_data.message else None

        # Criar servico
        chat_service = ChatService()

        result = chat_service.create_chat(
            user_id=user_id,
            chat_name=chat_name,
            message=message,
            model=request_data.model,
        )

        chat_id = result.get("chat_id")

        # [STAR] Criar isolated_chat com o mesmo chat_id para sincronizacao
        try:
            session = DatabaseManager.get_session()
            try:
                DatabaseManager.get_or_create_isolated_chat(
                    session=session,
                    chat_id=chat_id,
                    user_id=user_id,
                    agent_id=request_data.agent_id or "orchestrator-global",
                )
                debug(f"[POST /api/new-chat] Isolated chat criado para: {chat_id}")
            finally:
                session.close()
        except Exception as isolated_error:
            warning(
                f"[POST /api/new-chat] Erro ao criar isolated chat: {isolated_error}"
            )

        debug(f"[POST /api/new-chat] Chat criado: {chat_id}")

        # [STAR] Registrar evento de lifecycle
        try:
            from App.Features.Tracking.LifecycleTracker import LifecycleTracker

            LifecycleTracker.track(
                user_id=user_id, event_type="chat_initiated", chat_id=chat_id
            )
        except Exception as lifecycle_error:
            warning(f"[LIFECYCLE] Erro ao registrar chat_initiated: {lifecycle_error}")

        # Conceder créditos ao referrer se for 1° chat do referred
        try:
            from App.Core.Services.Sharing.ReferralManager import ReferralManager

            ReferralManager.award_trial_credits_to_referrer(user_id)
        except Exception as referral_error:
            warning(f"[REFERRAL] Erro ao verificar trial credits: {referral_error}")

        info(f"[POST /api/new-chat] [201] Chat criado por user {user_id}")

        # Se token foi renovado, incluir na resposta
        if token_headers:
            response = JSONResponse(status_code=201, content=result)
            for header_name, header_value in token_headers.items():
                response.headers[header_name] = header_value
            return response

        return result

    except ValueError as ve:
        warning(f"[POST /api/new-chat] Validacao: {str(ve)}")
        raise HTTPException(status_code=400, detail=str(ve))
    except HTTPException:
        raise
    except Exception as e:
        error(f"[POST /api/new-chat] Erro ao criar chat: {e}")
        import traceback

        error(f"[POST /api/new-chat] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Erro ao criar conversa")


@chat_router.get("")
async def get_chats(limit: int = 20, offset: int = 0, request: Request = None):
    """
    Lista todos os chats do usuario com paginacao
    """
    try:
        # Autenticar
        user_id = get_user_id_from_token(request)
        debug(f"[GET /api/chats] User ID: {user_id}")

        chat_service = ChatService()

        result = chat_service.get_chats(user_id=user_id, limit=limit, offset=offset)

        info(f"[GET /api/chats] [200] {len(result.get('chats', []))} chats retornados")
        return result

    except HTTPException:
        raise
    except Exception as e:
        error(f"[GET /api/chats] Erro ao listar chats: {e}")
        raise HTTPException(status_code=500, detail="Erro ao listar conversas")


@chat_router.patch("/{chat_id}/seen")
async def mark_chat_seen(chat_id: str, request: Request):
    """Marca um chat como visto (seen=1)"""
    try:
        from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager as _DBM

        user_id = get_user_id_from_token(request)
        _db = _DBM()
        _db.execute_query(
            "UPDATE chats SET seen = 1 WHERE chat_id = :cid AND user_id = :uid",
            {"cid": chat_id, "uid": user_id},
        )

        # Para agendamentos, o visto já resolve o status de pending_review
        from datetime import datetime

        _db.execute_query(
            """UPDATE task_executions
               SET status = 'completed', finished_at = :now
               WHERE chat_id = :cid AND status = 'pending_review'""",
            {"cid": chat_id, "now": datetime.utcnow().isoformat()},
        )

        # Recalcular e notificar WS
        counts = (
            _db.fetch_one(
                """SELECT
                COALESCE(SUM(CASE WHEN source='trigger' THEN 1 ELSE 0 END), 0) AS triggers,
                COALESCE(SUM(CASE WHEN source='scheduled' THEN 1 ELSE 0 END), 0) AS scheduled
               FROM chats WHERE user_id = :uid AND seen = 0""",
                {"uid": user_id},
            )
            or {}
        )
        await user_watcher.broadcast(
            user_id,
            {
                "type": "unseen_update",
                "triggers": int(counts.get("triggers") or 0),
                "scheduled": int(counts.get("scheduled") or 0),
            },
        )
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        error(f"[PATCH /api/chats/{chat_id}/seen] Erro: {e}")
        raise HTTPException(status_code=500, detail="Erro ao marcar como visto")


@chat_router.get("/{chat_id}/content/{content_id}/proxy")
async def get_generated_content_proxy(chat_id: str, content_id: str, request: Request):
    """
    Retorna informacoes sobre conteudo gerado (imagens/videos) com link para acesso

    Args:
        chat_id: ID do chat
        content_id: ID do conteudo gerado (generated_content_id)
        request: Requisicao HTTP

    Returns:
        {
            "content_id": str,
            "content_name": str,
            "type": "img" | "film",
            "storage_path": str,
            "storage_env": str,
            "created_at": str,
            "link": str
        }
    """
    try:
        # Autenticar
        user_id = get_user_id_from_token(request)

        from App.Core.Crunch.TablesSQL.Models import GeneratedContent

        db_session = DatabaseManager.get_session()

        try:
            # Buscar conteudo gerado
            content = (
                db_session.query(GeneratedContent)
                .filter(
                    GeneratedContent.asset_id == content_id,
                    GeneratedContent.chat_id == chat_id,
                )
                .first()
            )

            if not content:
                raise HTTPException(status_code=404, detail="Conteudo nao encontrado")

            # Verificar autorizacao (usuario deve pertencer ao chat)
            chat_row = db_session.execute(
                text("SELECT user_id FROM chats WHERE chat_id = :chat_id"),
                {"chat_id": chat_id},
            ).first()

            if not chat_row or chat_row[0] != user_id:
                raise HTTPException(status_code=403, detail="Acesso negado")

            response_data = {
                "content_id": str(content.asset_id),
                "content_name": content.content_name,
                "type": content.type,
                "storage_path": content.storage_path or "",
                "storage_env": content.storage_env or "local",
                "created_at": (
                    content.created_at.isoformat() if content.created_at else None
                ),
                "link": f"/api/chat/{chat_id}/content/{content.asset_id}/file",
            }

            debug(
                f"[GET /api/chat/{chat_id}/content/{content_id}/proxy] Conteudo encontrado: {content.content_name}"
            )
            return response_data

        finally:
            db_session.close()

    except HTTPException:
        raise
    except Exception as e:
        error(f"[GET /api/chat/{chat_id}/content/{content_id}/proxy] Erro: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar conteudo gerado")


@chat_router.patch("/{chat_id}")
async def rename_chat_old(
    chat_id: str, request_data: RenameChatRequest, request: Request
):
    """
    Renomeia um chat (rota antiga - compatibilidade)
    DEPRECATED: Use PATCH /api/chat/{chat_id}/name

    Args:
        chat_id: ID do chat
        request_data: Novo nome do chat
        request: Requisicao HTTP (para extrair token)

    Returns:
        Confirmacao da renomeacao
    """
    try:
        # Autenticar
        client_id = get_client_id_from_token(request)

        # Verificar restricoes de plano trial
        check_trial_plan_restrictions(client_id, "rename_chat")

        # Validar entrada
        new_name = (request_data.chat_name or "").strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="Nome e obrigatorio")

        chat_service = ChatService()
        result = chat_service.rename_chat(
            chat_id=chat_id, client_id=client_id, new_name=new_name
        )

        info(f"[PATCH /api/chats/{chat_id}] Chat renomeado para: {new_name}")
        return result

    except ValueError as ve:
        warning(f"[PATCH /api/chats/{chat_id}] {str(ve)}")
        raise HTTPException(status_code=404, detail=str(ve))
    except HTTPException:
        raise
    except Exception as e:
        error(f"[PATCH /api/chats/{chat_id}] Erro: {e}")
        raise HTTPException(status_code=500, detail="Erro ao renomear conversa")


def _process_chat_background(
    job,
    chat_id: str,
    client_id: int,
    message: str,
    context: Optional[Dict[str, Any]],
    model: str,
    agent_id: str,
    chat_manager,
    message_processor,
    attachment_ids: Optional[List[str]] = None,
    message_id: Optional[str] = None,
):
    """
    Processa a mensagem em background atraves do orquestrador.
    FLUXO: Mensagem -> Orchestrator -> MessageProcessor -> IA (com tools para encaminhar a sub-agents)
    """
    try:
        # Valida componentes essenciais
        if not (message_processor and chat_manager):
            job.mark_error("MessageProcessor ou ChatManager nao inicializado")
            return

        # Tentar carregar a sessao anterior do chat, se existir
        # Se nao existir, criar uma nova
        chat_service = ChatService()

        # Buscar todas as mensagens anteriores do chat para manter contexto
        try:
            existing_chat = chat_service.get_chat(chat_id, client_id)
            existing_messages = existing_chat.get("messages", [])
            debug(
                f"[BACKGROUND JOB {job.job_id}] Chat tem {len(existing_messages)} mensagens anteriores"
            )
        except Exception:
            existing_messages = []
            debug(f"[BACKGROUND JOB {job.job_id}] Nenhuma mensagem anterior encontrada")

        # Criar nova sessao (mas vamos sincronizar o historico anterior)
        session_id = chat_manager.create_session()
        debug(f"[BACKGROUND JOB {job.job_id}] Sessao criada: {session_id}")

        # Associar sessao ao chat
        session = chat_manager.get_session(session_id)
        if session:
            session.chat_id = chat_id
            # Sincronizar mensagens anteriores para a sessao atual
            for prev_msg in existing_messages:
                role = "user" if prev_msg.get("role") == "user" else "assistant"
                session.conversation_history.append(
                    {"role": role, "content": prev_msg.get("content", "")}
                )
            debug(
                f"[BACKGROUND JOB {job.job_id}] Historico sincronizado: {len(session.conversation_history)} mensagens"
            )

        # Processar a mensagem APENAS com o orchestrador
        try:
            # Inicializa o orquestrador
            orchestrator = AgentOrchestrator(
                message_processor=message_processor,
                chat_service=chat_service,
                agents_config=None,
            )

            debug(
                f"[BACKGROUND JOB {job.job_id}] Enviando mensagem para o orchestrador"
            )

            # Orquestra o processamento (envia APENAS para o orchestrador)
            # O orchestrador coordena as tarefas atraves de tools
            orchestration_result = orchestrator.orchestrate(
                user_message=message,
                chat_id=chat_id,
                client_id=client_id,
                session_id=session_id,
                job=job,
            )

            # Processa resultado do orquestrador
            if orchestration_result.get("success", False):
                debug(f"[BACKGROUND JOB {job.job_id}] Orquestracao concluida")

                # A resposta do orchestrador ja e processada pelo MessageProcessor
                ai_response = orchestration_result.get("response", "")
                debug(
                    f"[BACKGROUND JOB {job.job_id}] ai_response length: {len(ai_response) if ai_response else 0}, empty: {not ai_response}"
                )

                # Salva a resposta do orchestrador no main chat
                if ai_response:
                    try:
                        chat_service.save_message_exchange(
                            chat_id=chat_id,
                            client_id=client_id,
                            user_message=message,
                            ai_response=ai_response,
                            model=model,
                            agent_id="orchestrator-global",
                            save_user_message=False,  # Mensagem ja foi salva na rota
                        )
                        debug(
                            f"[BACKGROUND JOB {job.job_id}] Resposta do orchestrador salva"
                        )
                        from App.Core.Cache.RedisCache import cache_delete

                        cache_delete(f"chat:{chat_id}")

                    except Exception as save_error:
                        error(
                            f"[BACKGROUND JOB {job.job_id}] Erro ao salvar resposta: {save_error}"
                        )
                        import traceback

                        error(f"[BACKGROUND JOB {job.job_id}] {traceback.format_exc()}")
                else:
                    warning(
                        f"[BACKGROUND JOB {job.job_id}] ai_response esta vazio! Resposta nao sera salva."
                    )

                # NAO marcar como completed se ha tools enfileiradas (wait=true)
                # Job deve permanecer "running" ate as tools terminarem.
                # O SyncWorker marca completed (com WS) DEPOIS de sincronizar o main chat.
                if job.status == "running":
                    debug(
                        f"[BACKGROUND JOB {job.job_id}] Job continua em 'running' para processar tools enfileirados — SyncWorker enviará 'completed' após sync"
                    )
                    # NÃO disparar WS "completed" aqui — as mensagens ainda não estão no main chat.
                    # O ExternalToolWorker → SyncWorker enfileiram o sync e marcam o job
                    # como completed DEPOIS de sincronizar todas as mensagens (MultiWorkerPool.py ~l370).
                elif job.status == "waiting":
                    # Job pausado aguardando interação do usuário (quiz ou tool approval)
                    # Frontend deve parar o polling mas continuar fazendo getChat até o card aparecer
                    info(
                        f"[BACKGROUND JOB {job.job_id}] Job em 'waiting' — broadcast waiting para frontend"
                    )
                    _broadcast_job_status(chat_id, job.job_id, "waiting")
                else:
                    job.mark_completed(
                        ai_response if ai_response else "Processing completed"
                    )
                    info(
                        f"[BACKGROUND JOB {job.job_id}] [DONE] Job marcado como COMPLETED | response_length: {len(ai_response) if ai_response else 0}"
                    )
                    _broadcast_job_status(chat_id, job.job_id, "completed", ai_response)

                # Marcar unseen para chats de trigger/scheduled
                try:
                    _uloop = asyncio.new_event_loop()
                    asyncio.set_event_loop(_uloop)
                    _uloop.run_until_complete(_mark_chat_unseen_and_notify(chat_id))
                    _uloop.close()
                except Exception as _ue:
                    debug(f"[BACKGROUND JOB {job.job_id}] Erro ao marcar unseen: {_ue}")
            else:
                error_msg = orchestration_result.get(
                    "error", "Erro ao processar orquestracao"
                )
                job.mark_error(error_msg)
                debug(f"[BACKGROUND JOB {job.job_id}] Orquestracao falhou: {error_msg}")

                # Notificar clientes via WebSocket de erro
                _broadcast_job_status(chat_id, job.job_id, "error", error_msg)

        except Exception as e:
            error(f"[BACKGROUND JOB {job.job_id}] Erro ao processar: {e}")
            import traceback

            error(traceback.format_exc())
            job.mark_error(str(e))

    except Exception as e:
        error(f"[BACKGROUND JOB {job.job_id}] Erro geral: {e}")
        job.mark_error(str(e))
    finally:
        if not job.is_finished():
            job.mark_error("Background processing failed")


@chat_operations_router.post("/chat/{chat_id}/message", status_code=202)
async def send_message(
    chat_id: str, request_data: SendMessageRequest, request: Request
):
    """
    Inicia o processamento de uma mensagem em background e retorna um job_id.
    IMEDIATAMENTE salva a mensagem do user para sincronizacao em tempo real.
    """
    try:
        # [STAR] IMPORTAR AQUI no inicio para evitar "local variable not associated with a value"
        from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager

        # Log detalhado do request
        debug(
            f"[POST /api/chat/{{chat_id}}/message] Raw chat_id from path: '{chat_id}' (type: {type(chat_id).__name__})"
        )

        # Validar que chat_id nao e um template literal
        if chat_id.startswith("{{") or chat_id.endswith("}}") or "{" in chat_id:
            error(
                f"[POST /api/chat/INVALID/message] ERRO CRITICO: chat_id e um template literal: '{chat_id}'"
            )
            error(
                "[POST /api/chat/INVALID/message] Isso significa que o frontend esta enviando a URL errada"
            )
            error(
                "[POST /api/chat/INVALID/message] O frontend deve enviar: /api/chat/<UUID>/message"
            )
            error(
                f"[POST /api/chat/INVALID/message] Mas esta enviando: /api/chat/{chat_id}/message"
            )
            raise HTTPException(
                status_code=400,
                detail=f"chat_id invalido: '{chat_id}' - Parece que o frontend esta enviando um template nao renderizado. Verifique se o chatId esta sendo passado corretamente.",
            )

        client_id = get_client_id_from_token(request)
        message = (request_data.message or "").strip()

        if not message:
            raise HTTPException(status_code=400, detail="Mensagem e obrigatoria")

        # Validar que ha no maximo um attachment
        if request_data.attachment:
            if not isinstance(request_data.attachment, AttachmentInfo):
                raise HTTPException(
                    status_code=400, detail="Formato de attachment invalido"
                )
            if (
                not request_data.attachment.attachment_type
                or not request_data.attachment.attachment_id
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Attachment deve ter attachment_type e attachment_id",
                )
            debug(
                f"[POST /api/chat/{chat_id}/message] Attachment validado: {request_data.attachment.attachment_type}/{request_data.attachment.attachment_id}"
            )

        # Obter user_id e plan_type para verificar creditos
        user_query = """
        SELECT u.user_id, COALESCE(p.plan_type, 'trial') as plan_type
        FROM users u
        LEFT JOIN clients c ON u.client_id = c.client_id
        LEFT JOIN plans p ON c.plan_id = p.plan_id
        WHERE u.client_id = :client_id
        LIMIT 1
        """
        user_result = DatabaseManager.fetch_one(user_query, {"client_id": client_id})
        if not user_result:
            raise HTTPException(status_code=500, detail="Usuario nao encontrado")

        user_id = user_result.get("user_id")
        debug(
            f"[POST /api/chat/{chat_id}/message] Database query result - client_id: {client_id}, retrieved user_id: {user_id}, full result: {user_result}"
        )
        plan_type = user_result.get("plan_type", "trial").lower()

        # Verificar creditos disponiveis (via user_id)
        has_credits, available_credits = CreditsManager.check_credits(
            user_id, required_credits=1.0
        )
        if not has_credits:
            # Se nao tem creditos, verificar se e trial/free ou nao
            if plan_type in ["trial", "free"]:
                raise HTTPException(status_code=402, detail="signup for more")
            else:
                raise HTTPException(status_code=402, detail="no fundings")

        agent_id = request_data.agent_id or "orchestrator-global"

        # Log detalhado da requisicao (incluindo attachment)
        debug(
            f"[POST /api/chat/{chat_id}/message] Dados recebidos: message_length={len(message)}, attachment={request_data.attachment}"
        )

        # 1. SALVAR MENSAGEM DO USER IMEDIATAMENTE EM MAIN_CHAT (messages)
        # Isso garante que o user veja a mensagem aparecer imediatamente
        # A sincronizacao isolada acontecera durante o processamento em background
        user_msg_id = str(uuid.uuid4())
        try:
            from datetime import datetime

            now = datetime.utcnow()

            # Salvar em messages com estrutura existente
            user_save_query = """
            INSERT INTO messages (message_id, chat_id, message_type, content, created_at)
            VALUES (:message_id, :chat_id, :message_type, :content, :created_at)
            """

            DatabaseManager.execute_query(
                user_save_query,
                {
                    "message_id": user_msg_id,
                    "chat_id": chat_id,
                    "message_type": "user",
                    "content": message,
                    "created_at": now,
                },
            )
            debug(
                f"[POST /api/chat/{chat_id}/message] [OK] Mensagem do user salva IMEDIATAMENTE em messages (main_chat): {user_msg_id}"
            )

            # Invalidar cache do chat para o polling ver dados frescos
            from App.Core.Cache.RedisCache import cache_delete

            cache_delete(f"chat:{chat_id}")

            # Notificar clientes via WebSocket (só carrega o chat completo se houver clientes)
            try:
                if chat_id in chat_watcher.clients and chat_watcher.clients[chat_id]:
                    chat_service_temp = ChatService()
                    chat_data = chat_service_temp.get_chat(
                        chat_id=chat_id, user_id=user_id
                    )
                    await chat_watcher.broadcast(
                        chat_id, {"type": "message_saved", "chat": chat_data}
                    )
                else:
                    debug(
                        f"[POST /api/chat/{chat_id}/message] Sem clientes WS, pulando get_chat"
                    )
                debug(
                    f"[POST /api/chat/{chat_id}/message] [OK] Notificacao WS enviada para chat_id: {chat_id}"
                )
            except Exception as ws_error:
                debug(
                    f"[POST /api/chat/{chat_id}/message] ? Erro ao notificar WS: {ws_error}"
                )
        except Exception as e:
            error(
                f"[POST /api/chat/{chat_id}/message] [ERR] Erro ao salvar mensagem em messages: {e}"
            )
            raise HTTPException(
                status_code=500, detail=f"Erro ao salvar mensagem: {str(e)}"
            )

        # 1.5. PROCESSAR ATTACHMENT (file ou template)
        if request_data.attachment:
            if request_data.attachment.attachment_type == "file":
                try:
                    debug(
                        f"[POST /api/chat/{chat_id}/message] Iniciando movimento de file attachment: {request_data.attachment.attachment_id}"
                    )
                    moved = await move_attachments_from_temp(
                        client_id,
                        chat_id,
                        user_msg_id,
                        [request_data.attachment.attachment_id],
                    )
                    info(
                        f"[POST /api/chat/{chat_id}/message] File attachment movido: {request_data.attachment.attachment_id}"
                    )

                except Exception as e:
                    error(
                        f"[POST /api/chat/{chat_id}/message] Erro ao mover attachment: {e}"
                    )
                    warning(
                        f"[POST /api/chat/{chat_id}/message] Continuando mesmo com erro de attachment"
                    )

            elif request_data.attachment.attachment_type == "template":
                try:
                    debug(
                        f"[POST /api/chat/{chat_id}/message] Registrando template attachment: {request_data.attachment.attachment_id}"
                    )
                    registered = await register_template_attachment(
                        user_id,
                        chat_id,
                        user_msg_id,
                        request_data.attachment.attachment_id,
                    )
                    info(
                        f"[POST /api/chat/{chat_id}/message] Template attachment registrado: {request_data.attachment.attachment_id}"
                    )

                except Exception as e:
                    error(
                        f"[POST /api/chat/{chat_id}/message] Erro ao registrar template attachment: {e}"
                    )
                    warning(
                        f"[POST /api/chat/{chat_id}/message] Continuando mesmo com erro de attachment"
                    )

        # 1.6. PROCESSAR drive_files do context
        if request_data.context and isinstance(request_data.context, dict):
            drive_files = request_data.context.get("drive_files")
            if drive_files and isinstance(drive_files, list):
                for df in drive_files:
                    file_id = df.get("file_id", "")
                    file_name = df.get("name", "")
                    mime_type = df.get("mime_type", "")
                    if not file_id:
                        continue
                    try:
                        await register_drive_attachment(
                            user_id,
                            chat_id,
                            user_msg_id,
                            file_id,
                            file_name,
                            mime_type,
                        )
                        info(
                            f"[POST /api/chat/{chat_id}/message] Drive attachment registrado: {file_name} ({file_id})"
                        )
                    except Exception as e:
                        error(
                            f"[POST /api/chat/{chat_id}/message] Erro ao registrar drive attachment: {e}"
                        )

        # 2. Obter componentes
        chat_manager = COMPONENTS.get("chat_manager")
        message_processor = COMPONENTS.get("message_processor")

        if not (chat_manager and message_processor):
            raise HTTPException(
                status_code=500, detail="Componentes de processamento nao inicializados"
            )

        job_manager = get_job_manager()
        job = job_manager.create_job(
            chat_id=chat_id, user_id=str(user_id) if user_id else None
        )

        # Extrair job_id do ProcessingJob object
        actual_job_id = (
            job.job_id
            if hasattr(job, "job_id")
            else (job.get("job_id") if isinstance(job, dict) else None)
        )
        debug(f"[POST /api/chat/{chat_id}/message] Job criado: {actual_job_id}")

        # 3. Enfileirar mensagem em MESSAGE_QUEUE para processamento async
        # Em vez de criar thread individual, enfileira em fila global
        try:
            from App.Core.Queues import Message  # Import Message class

            # Enfileirar mensagem
            queue_manager = COMPONENTS.get("queue_manager")
            if queue_manager:
                debug(
                    f"[POST /api/chat/{chat_id}/message] Creating Message object - user_id value: {user_id}, client_id value: {client_id}"
                )
                msg = Message(
                    message_id=user_msg_id,
                    chat_id=chat_id,
                    job_id=actual_job_id,
                    user_id=user_id,  # Use actual user_id from database query
                    role="user",
                    content=message,
                    context=request_data.context,
                    model=request_data.model,
                    agent_id=agent_id,
                    attachment=(
                        request_data.attachment.dict()
                        if request_data.attachment
                        else None
                    ),
                )
                await asyncio.get_event_loop().run_in_executor(
                    None, queue_manager.enqueue_message, msg
                )
                info(
                    f"[POST /api/chat/{chat_id}/message] Mensagem enfileirada com job_id: {actual_job_id}"
                )
            else:
                warning(
                    f"[POST /api/chat/{chat_id}/message] queue_manager nao disponivel"
                )

        except Exception as e:
            error(f"[POST /api/chat/{chat_id}/message] Erro ao enfileirar: {e}")

        # Return job_id immediately (message processing happens in background)
        # Frontend will use this job_id to poll /api/chat/{chat_id}/job/{job_id}
        return {
            "job_id": actual_job_id,
            "message_id": user_msg_id,
            "status": "queued",
            "message": "Mensagem enfileirada para processamento",
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[POST /api/chat/{chat_id}/message] Erro: {e}")
        raise HTTPException(status_code=500, detail="Erro ao iniciar processamento")


@chat_router.get("/{chat_id}/active-job")
async def get_active_job_for_chat(chat_id: str):
    """Verifica se ha um job em execucao para um determinado chat."""
    try:
        job_manager = get_job_manager()
        active_job = job_manager.find_active_job_by_chat_id(chat_id)
        if active_job:
            info(
                f"[GET /api/chat/{chat_id}/active-job] [200] Active job found: {active_job.job_id}"
            )
            return {"job_id": active_job.job_id}

        info(f"[GET /api/chat/{chat_id}/active-job] [200] No active job found.")
        return {"job_id": None}
    except Exception as e:
        error(f"[GET /api/chat/{chat_id}/active-job] [500] Erro: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@chat_operations_router.get("/chat/{chat_id}/active-job")
async def get_active_job_for_chat_ops(chat_id: str):
    """Verifica se ha um job em execucao para um determinado chat."""
    try:
        job_manager = get_job_manager()
        active_job = job_manager.find_active_job_by_chat_id(chat_id)
        if active_job:
            info(
                f"[GET /api/chat/{chat_id}/active-job] [200] Active job found: {active_job.job_id}"
            )
            return {"job_id": active_job.job_id}

        info(f"[GET /api/chat/{chat_id}/active-job] [200] No active job found.")
        return {"job_id": None}
    except Exception as e:
        error(f"[GET /api/chat/{chat_id}/active-job] [500] Erro: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@chat_operations_router.post("/chat/{chat_id}/upload-audio")
async def upload_audio_legacy(
    chat_id: str, file: UploadFile = File(...), request: Request = None
):
    """Legacy — redireciona para o endpoint sem chat_id."""
    return await upload_audio(file=file, request=request)


@chat_operations_router.post("/audio/transcribe")
async def upload_audio(file: UploadFile = File(...), request: Request = None):
    """
    Recebe um arquivo de áudio, transcreve via Whisper e retorna o texto.
    Não exige chat_id — funciona em chats novos (antes da primeira mensagem).
    Debita créditos do usuário baseado na duração.
    """
    import tempfile as _tempfile

    auth_service = get_auth_service()
    token = request.cookies.get("access_token") if request else None
    if not token:
        raise HTTPException(status_code=401, detail="Não autenticado")
    payload = auth_service.verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido")
    user_id = str(payload.get("user_id"))

    suffix = ".webm"
    if file.filename:
        ext = (
            "." + file.filename.rsplit(".", 1)[-1] if "." in file.filename else ".webm"
        )
        suffix = ext

    try:
        with _tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
    except Exception as e:
        error(f"[upload-audio] Erro ao salvar arquivo temp: {e}")
        raise HTTPException(status_code=500, detail="Erro ao processar áudio")

    try:
        from App.Features.Llm.LLMClient import OpenAIClient
        from App.Core.Settings.Settings import GLOBAL_CONFIG

        openai_key = GLOBAL_CONFIG.get("openai_api_key") or GLOBAL_CONFIG.get(
            "OPENAI_API_KEY"
        )
        if not openai_key:
            raise HTTPException(status_code=503, detail="OpenAI não configurada")

        client = OpenAIClient(api_key=openai_key)
        result = client.transcribe_audio(tmp_path, language="pt")

        if result["error"]:
            raise HTTPException(
                status_code=502, detail=f"Erro na transcrição: {result['error']}"
            )

        duration = result["duration_seconds"]
        cost_centavos = CreditsManager.calculate_audio_cost(duration)
        cost_credits = CreditsManager.centavos_to_credits(cost_centavos)

        if cost_credits > 0:
            success = CreditsManager.consume_credits(
                user_id,
                cost_credits,
                reason=f"Whisper transcription ({duration:.1f}s)",
            )
            if not success:
                raise HTTPException(status_code=402, detail="Créditos insuficientes")

        info(
            f"[upload-audio] user={user_id} duration={duration:.1f}s cost={cost_credits:.6f}"
        )
        return {"transcription": result["text"], "duration_seconds": duration}

    finally:
        import os as _os

        try:
            _os.unlink(tmp_path)
        except Exception:
            pass


@chat_operations_router.post("/audio/synthesize")
async def synthesize_audio(request: Request):
    """Converte texto em áudio MP3 via OpenAI TTS (tts-1, voz nova)."""
    from fastapi.responses import Response as _Response

    auth_service = get_auth_service()
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Não autenticado")
    payload = auth_service.verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido")
    user_id = str(payload.get("user_id"))

    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Texto vazio")
    if len(text) > 4096:
        text = text[:4096]

    voice = body.get("voice") or "nova"

    try:
        from App.Features.Llm.LLMClient import OpenAIClient
        from App.Core.Settings.Settings import GLOBAL_CONFIG

        openai_key = GLOBAL_CONFIG.get("openai_api_key") or GLOBAL_CONFIG.get(
            "OPENAI_API_KEY"
        )
        if not openai_key:
            raise HTTPException(status_code=503, detail="OpenAI não configurada")

        client = OpenAIClient(api_key=openai_key)
        audio_bytes = client.synthesize_speech(text, voice=voice)

        # Custo: tts-1 cobra ~$0.015/1k chars (≈ R$0.09/1k chars)
        chars = len(text)
        cost_centavos = (chars / 1000) * 9.0
        cost_credits = CreditsManager.centavos_to_credits(cost_centavos)
        if cost_credits > 0:
            CreditsManager.consume_credits(
                user_id, cost_credits, reason=f"TTS ({chars} chars)"
            )

        info(f"[audio/synthesize] user={user_id} chars={chars}")
        return _Response(content=audio_bytes, media_type="audio/mpeg")

    except HTTPException:
        raise
    except Exception as e:
        error(f"[audio/synthesize] {e}")
        raise HTTPException(status_code=500, detail="Erro ao sintetizar áudio")


@chat_operations_router.post("/chat/{chat_id}/pin")
async def pin_chat(chat_id: str, request: Request = None):
    """Toggle is_pinned para um chat."""
    user_id = get_user_id_from_token(request)
    try:
        result = DatabaseManager.fetch_one(
            "SELECT is_pinned FROM chats WHERE chat_id = :chat_id AND user_id = :user_id",
            {"chat_id": chat_id, "user_id": user_id},
        )
        if not result:
            raise HTTPException(status_code=404, detail="Chat não encontrado")
        new_value = 0 if result.get("is_pinned") else 1
        DatabaseManager.execute_query(
            "UPDATE chats SET is_pinned = :v WHERE chat_id = :chat_id AND user_id = :user_id",
            {"v": new_value, "chat_id": chat_id, "user_id": user_id},
        )
        return {"pinned": bool(new_value)}
    except HTTPException:
        raise
    except Exception as e:
        error(f"[pin-chat] {e}")
        raise HTTPException(status_code=500, detail="Erro ao pinar chat")


@chat_operations_router.delete("/chat/{chat_id}", status_code=200)
async def delete_chat_op(chat_id: str, request: Request):
    """
    Deleta um chat e todas as suas mensagens

    Args:
        chat_id: ID do chat
        request: Requisicao HTTP (para extrair token)

    Returns:
        Confirmacao da delecao
    """
    try:
        # Autenticar
        client_id = get_client_id_from_token(request)
        user_id = get_user_id_from_token(request)

        # Verificar restricoes de plano trial
        check_trial_plan_restrictions(client_id, "delete_chat")

        chat_service = ChatService()
        result = chat_service.delete_chat(chat_id=chat_id, user_id=user_id)

        info(f"[DELETE /api/chat/{chat_id}] Chat deletado com sucesso")
        return result

    except HTTPException:
        raise
    except ValueError as ve:
        warning(f"[DELETE /api/chat/{chat_id}] {str(ve)}")
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        error(f"[DELETE /api/chat/{chat_id}] Erro: {e}")
        raise HTTPException(status_code=500, detail="Erro ao deletar conversa")


@chat_operations_router.patch("/chat/{chat_id}/name", status_code=200)
async def rename_chat_new(
    chat_id: str, request_data: RenameChatRequest, request: Request
):
    """
    Renomeia um chat (nova rota: /api/chat/{chat_id}/name)

    Args:
        chat_id: ID do chat
        request_data: Novo nome do chat
        request: Requisicao HTTP (para extrair token)

    Returns:
        Confirmacao da renomeacao
    """
    try:
        # Autenticar
        client_id = get_client_id_from_token(request)

        # Verificar restricoes de plano trial
        check_trial_plan_restrictions(client_id, "rename_chat")

        # Validar entrada
        new_name = (request_data.chat_name or "").strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="Nome e obrigatorio")

        chat_service = ChatService()
        result = chat_service.rename_chat(
            chat_id=chat_id, client_id=client_id, new_name=new_name
        )

        info(f"[PATCH /api/chat/{chat_id}/name] Chat renomeado para: {new_name}")
        return result

    except ValueError as ve:
        warning(f"[PATCH /api/chat/{chat_id}/name] {str(ve)}")
        raise HTTPException(status_code=404, detail=str(ve))
    except HTTPException:
        raise
    except Exception as e:
        error(f"[PATCH /api/chat/{chat_id}/name] Erro: {e}")
        raise HTTPException(status_code=500, detail="Erro ao renomear conversa")


@chat_operations_router.post("/chat/{chat_id}/job/{job_id}/cancel", status_code=200)
async def cancel_job_endpoint(chat_id: str, job_id: str):
    """Endpoint para cancelar um job em execucao."""
    debug(
        f"[POST /api/chat/{chat_id}/job/{job_id}/cancel] Recebida requisicao para cancelar job"
    )
    try:
        job_manager = get_job_manager()
        success = job_manager.cancel_job(job_id)
        if not success:
            warning(
                f"[POST /api/chat/{chat_id}/job/{job_id}/cancel] [404] Job nao encontrado ou ja finalizado"
            )
            raise HTTPException(status_code=404, detail="Job not found or not running.")

        # IMPORTANTE: Notificar o MessageProcessor para parar o loop de iteracoes
        message_processor = COMPONENTS.get("message_processor")
        if message_processor:
            message_processor.mark_job_cancelled(chat_id, job_id)
            debug(
                f"[POST /api/chat/{chat_id}/job/{job_id}/cancel] MessageProcessor notificado para parar iteracoes"
            )
        else:
            warning(
                f"[POST /api/chat/{chat_id}/job/{job_id}/cancel] MessageProcessor nao disponivel em COMPONENTS"
            )

        info(f"[POST /api/chat/{chat_id}/job/{job_id}/cancel] [200] Job cancelado")
        return {"message": "Job cancellation request accepted."}
    except HTTPException:
        raise
    except Exception as e:
        error(
            f"[POST /api/chat/{chat_id}/job/{job_id}/cancel] [500] Erro ao cancelar job: {e}"
        )
        raise HTTPException(status_code=500, detail=str(e))


@chat_operations_router.post("/trigger/post", status_code=200)
async def track_post_created(request: Request):
    """
    Rastreia quando usuario clica em 'Postar'.
    Registra evento 'post_created' em customer_lifecycle_tracking.
    """
    try:
        user_id = get_user_id_from_token(request)
        if not user_id:
            raise HTTPException(status_code=401, detail="Nao autenticado")

        body = await request.json()
        chat_id = body.get("chat_id")
        asset_id = body.get("asset_id")

        from App.Features.Tracking.LifecycleTracker import LifecycleTracker

        LifecycleTracker.track(
            user_id=user_id,
            event_type="post_created",
            chat_id=chat_id,
            metadata={"asset_id": asset_id} if asset_id else None,
        )

        debug(f"[POST /api/trigger/post] Post criado para chat {chat_id}")
        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        error(f"[POST /api/trigger/post] {e}")
        raise HTTPException(status_code=500, detail=str(e))


@chat_operations_router.post("/trigger/i-already-posted", status_code=200)
async def track_post_confirmed(request: Request):
    """
    Rastreia quando usuario clica em 'Ja postei'.
    Registra evento 'post_confirmed' em customer_lifecycle_tracking.
    """
    try:
        user_id = get_user_id_from_token(request)
        if not user_id:
            raise HTTPException(status_code=401, detail="Nao autenticado")

        body = await request.json()
        chat_id = body.get("chat_id")

        from App.Features.Tracking.LifecycleTracker import LifecycleTracker

        LifecycleTracker.track(
            user_id=user_id, event_type="post_confirmed", chat_id=chat_id
        )

        debug(
            f"[POST /api/trigger/i-already-posted] Post confirmado para chat {chat_id}"
        )
        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        error(f"[POST /api/trigger/i-already-posted] {e}")
        raise HTTPException(status_code=500, detail=str(e))


@chat_operations_router.get("/chat/{chat_id}/job/{job_id}")
async def get_job_status(chat_id: str, job_id: str):
    """Retorna status do job para polling."""
    try:
        job_manager = get_job_manager()
        status = job_manager.get_job_status(job_id)

        if status.get("not_found"):
            error(f"[GET /api/chat/{chat_id}/job/{job_id}] [404] Job nao encontrado")
            raise HTTPException(status_code=404, detail="Job nao encontrado")

        return status
    except HTTPException:
        raise
    except Exception as e:
        error(f"[GET /api/chat/{chat_id}/job/{job_id}] [500] Erro: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@chat_operations_router.get("/chat/assets_n_attachs_lib")
async def assets_n_attachs_lib(request: Request):
    """
    Retorna a biblioteca de midias do usuario:
    - Todos os assets gerados (tabela `assets`)
    - Todos os attachments de imagem (tabela `attachments`, file_type starts with 'image/')
    """
    try:
        client_id = get_client_id_from_token(request)
        user_id = get_user_id_from_token(request)

        db_session = None
        try:
            from sqlalchemy import text as sa_text

            db_session = DatabaseManager.get_session()

            assets_rows = db_session.execute(
                sa_text(
                    """
                SELECT a.asset_id, a.content_name AS title, a.type AS file_type,
                       a.chat_id, a.created_at, a.ratio, a.approval_status, a.variation_id
                FROM assets a
                WHERE a.client_id = :client_id
                ORDER BY a.created_at DESC
                LIMIT 200
                """
                ),
                {"client_id": client_id},
            ).fetchall()

            assets_list = []
            for row in assets_rows:
                r = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
                asset_id = r.get("asset_id", "")
                chat_id_val = r.get("chat_id") or ""
                assets_list.append(
                    {
                        "kind": "asset",
                        "id": asset_id,
                        "asset_id": asset_id,
                        "title": r.get("title") or asset_id,
                        "file_type": r.get("file_type") or "image/jpeg",
                        "chat_id": chat_id_val,
                        "created_at": str(r.get("created_at") or ""),
                        "ratio": r.get("ratio"),
                        "variation_id": r.get("variation_id"),
                        "approval_status": r.get("approval_status"),
                        "proxy_url": f"/api/chat/{chat_id_val}/asset/{asset_id}/proxy"
                        if chat_id_val
                        else None,
                    }
                )

            attach_rows = db_session.execute(
                sa_text(
                    """
                SELECT attachment_id, file_name, file_type, file_size,
                       chat_id, message_id, created_at
                FROM attachments
                WHERE user_id = :user_id
                  AND (
                    file_type LIKE 'image/%'
                    OR LOWER(file_type) IN ('jpg','jpeg','png','gif','webp','bmp','tif','tiff','svg','avif')
                    OR file_type IN ('.jpg','.jpeg','.png','.gif','.webp','.bmp','.tif','.tiff','.svg','.avif')
                    OR LOWER(extension) IN ('jpg','jpeg','png','gif','webp','bmp','tif','tiff','svg','avif')
                    OR extension IN ('.jpg','.jpeg','.png','.gif','.webp','.bmp','.tif','.tiff','.svg','.avif')
                    OR LOWER(file_name) LIKE '%.jpg' OR LOWER(file_name) LIKE '%.jpeg'
                    OR LOWER(file_name) LIKE '%.png' OR LOWER(file_name) LIKE '%.gif'
                    OR LOWER(file_name) LIKE '%.webp' OR LOWER(file_name) LIKE '%.bmp'
                    OR LOWER(file_name) LIKE '%.svg' OR LOWER(file_name) LIKE '%.avif'
                  )
                  AND (deleted_at IS NULL OR deleted_at = '')
                ORDER BY created_at DESC
                LIMIT 200
                """
                ),
                {"user_id": user_id},
            ).fetchall()

            attachments_list = []
            for row in attach_rows:
                r = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
                att_id = r.get("attachment_id", "")
                chat_id_val = r.get("chat_id") or ""
                attachments_list.append(
                    {
                        "kind": "attachment",
                        "id": att_id,
                        "asset_id": att_id,
                        "title": r.get("file_name") or att_id,
                        "file_type": r.get("file_type") or "image/jpeg",
                        "file_size": r.get("file_size"),
                        "chat_id": chat_id_val,
                        "message_id": r.get("message_id"),
                        "created_at": str(r.get("created_at") or ""),
                        "proxy_url": f"/api/chat/{chat_id_val}/attachment/{att_id}"
                        if chat_id_val
                        else None,
                    }
                )

            return {
                "assets": assets_list,
                "attachments": attachments_list,
                "total": len(assets_list) + len(attachments_list),
            }

        finally:
            if db_session:
                db_session.close()

    except HTTPException:
        raise
    except Exception as e:
        error(f"[GET /api/chat/assets_n_attachs_lib] {e}")
        raise HTTPException(
            status_code=500, detail="Erro ao buscar biblioteca de midias"
        )


@chat_operations_router.get("/chat/{chat_id}")
async def get_chat_detail(chat_id: str, request: Request):
    """
    Obtem um chat especifico com mensagens, tasks e documents
    Rota alternativa em /api/chat/{chat_id} para compatibilidade
    """
    try:
        # info(f"[GET /api/chat/{chat_id}] ROTA CHAMADA - isso e a rota chat_operations_router (/api/chat/...) COM FEEDBACK LOADING")

        # Autenticar
        user_id = get_user_id_from_token(request)

        # Cache rápido — evita todas as queries abaixo
        from App.Core.Cache.RedisCache import cache_get, cache_set

        _chat_cache_key = f"chat:{chat_id}"
        _cached = cache_get(_chat_cache_key)
        if _cached is not None:
            debug(f"[GET /api/chat/{chat_id}] cache hit")
            return _cached

        chat_service = ChatService()
        result = chat_service.get_chat(chat_id=chat_id, user_id=user_id)

        # Adicionar feedback information as mensagens
        # IMPORTANTE: Converter Row objects para dict para permitir adicionar campos
        messages = result.get("messages", [])
        debug(
            f"[GET /api/chat/{chat_id}] Carregando feedback para {len(messages)} mensagens"
        )

        if messages:
            messages_list = []
            # Filter out non-last chain-of-thought messages (they cause extra spacing)
            total_messages = len(messages)

            for idx, msg in enumerate(messages):
                # Converter Row para dict se necessario
                msg_dict = dict(msg) if not isinstance(msg, dict) else msg.copy()

                message_id = msg_dict.get("id")
                chat_id_msg = msg_dict.get("chat_id")

                # Sempre tentar carregar feedback, mesmo que falhe
                try:
                    feedback_query = """
                    SELECT feedback_type, content
                    FROM message_feedbacks
                    WHERE message_id = :message_id AND chat_id = :chat_id
                    """
                    feedback = DatabaseManager.fetch_one(
                        feedback_query,
                        {"message_id": message_id, "chat_id": chat_id_msg},
                    )

                    if feedback:
                        msg_dict["feedback"] = {
                            "type": feedback.get("feedback_type"),
                            "content": feedback.get("content"),
                        }
                        debug(
                            f"[GET /api/chat/{chat_id}] Feedback encontrado para msg {message_id}: {feedback.get('feedback_type')}"
                        )
                    else:
                        msg_dict["feedback"] = None
                except Exception as msg_error:
                    error(
                        f"[GET /api/chat/{chat_id}] Erro ao carregar feedback para msg {message_id}: {msg_error}"
                    )
                    msg_dict["feedback"] = None

                # Extrair e adicionar campo tool para mensagens de tool
                from App.Core.Crunch.SyncManager import SyncManager

                try:
                    role = msg_dict.get("role", "user")
                    if role == "tool":
                        content = msg_dict.get("content", "")
                        # Tentar extrair tool do banco de dados primeiro
                        tool_name = msg_dict.get("tool")
                        # Se nao estiver no DB, tentar extrair do conteudo
                        if not tool_name:
                            tool_name = SyncManager.extract_tool_name(content)
                        if tool_name:
                            msg_dict["tool"] = tool_name
                            debug(
                                f"[GET /api/chat/{chat_id}] Tool extraida para msg {message_id}: {tool_name}"
                            )
                except Exception as tool_error:
                    debug(
                        f"[GET /api/chat/{chat_id}] Erro ao extrair tool para msg {message_id}: {tool_error}"
                    )

                # Skip chain-of-thought messages that are not the last message
                tool_name = msg_dict.get("tool")
                is_last_message = idx == total_messages - 1
                if tool_name == "chain-of-thought" and not is_last_message:
                    debug(
                        f"[GET /api/chat/{chat_id}] Filtrando chain-of-thought nao-ultima (idx={idx})"
                    )
                    continue

                # Remover campos que nao devem ser retornados
                msg_dict.pop("message_type", None)

                messages_list.append(msg_dict)

            # Atualizar result com a nova lista de dicionarios
            result["messages"] = messages_list
        else:
            # Se nao ha mensagens, garantir que o campo "messages" esta sempre presente
            result["messages"] = []

        # Obter tasks do banco de dados
        tasks_data = {"tasks": [], "total_tasks": 0}
        db_session_tasks = None
        try:
            db_session_tasks = DatabaseManager.get_session()
            db_tasks = DatabaseManager.get_chat_tasks(db_session_tasks, chat_id)

            if db_tasks:
                tasks_list = []
                for task in db_tasks:
                    tasks_list.append(
                        {
                            "task_id": task.get("task_id"),
                            "step_id": task.get("step_id"),
                            "task_name": task.get("task_name"),
                            "step_name": task.get("step_name"),
                            "status": task.get("status"),
                            "completed_at": task.get("completed_at"),
                        }
                    )
                tasks_data = {"tasks": tasks_list, "total_tasks": len(tasks_list)}
                debug(
                    f"[GET /api/chat/{chat_id}] Tasks carregadas do DB: {tasks_data.get('total_tasks', 0)} tasks"
                )
            else:
                debug(f"[GET /api/chat/{chat_id}] Nenhuma task encontrada no DB")
        except Exception as e:
            debug(f"[GET /api/chat/{chat_id}] Erro ao buscar tasks do DB: {e}")
            tasks_data = {"tasks": [], "total_tasks": 0}
        finally:
            if db_session_tasks:
                db_session_tasks.close()

        # Obter documents do banco de dados
        documents_list = []
        db_session_files = None
        try:
            db_session_files = DatabaseManager.get_session()

            # Fetch documents from documents table (now stored with content in DB)
            from sqlalchemy import text

            db_documents = db_session_files.execute(
                text(
                    "SELECT document_id, title, content, extension, tool_type, created_at FROM documents WHERE chat_id = :chat_id AND user_id = :user_id ORDER BY created_at DESC"
                ),
                {"chat_id": chat_id, "user_id": user_id},
            ).fetchall()

            # Process documents from documents table
            if db_documents:
                for doc_record in db_documents:
                    try:
                        (
                            document_id,
                            title,
                            content,
                            extension,
                            tool_type,
                            created_at,
                        ) = doc_record

                        # Handle created_at: pode vir como string ou datetime
                        if isinstance(created_at, str):
                            created_at_str = created_at
                        elif created_at:
                            created_at_str = created_at.isoformat()
                        else:
                            created_at_str = datetime.now().isoformat()

                        doc_content = content or ""

                        doc_entry = {
                            "file_id": document_id,
                            "document_id": document_id,
                            "filename": title,
                            "content": doc_content,
                            "size": len(doc_content) if doc_content else 0,
                            "created_at": created_at_str,
                            "type": tool_type or "document",
                        }
                        documents_list.append(doc_entry)
                    except Exception as e:
                        debug(
                            f"[GET /api/chat/{chat_id}] Erro ao processar documento do DB: {e}"
                        )
                        import traceback

                        debug(
                            f"[GET /api/chat/{chat_id}] Traceback: {traceback.format_exc()}"
                        )

            # Ordenar por created_at descendente
            documents_list.sort(key=lambda x: x["created_at"], reverse=True)

            if documents_list:
                debug(
                    f"[GET /api/chat/{chat_id}] Documents carregados do DB: {len(documents_list)} documentos"
                )
            else:
                debug(f"[GET /api/chat/{chat_id}] Nenhum documento encontrado no DB")
        except Exception as e:
            debug(f"[GET /api/chat/{chat_id}] Erro ao buscar documents do DB: {e}")
        finally:
            if db_session_files:
                db_session_files.close()

        # Obter calendar posts do banco de dados (GLOBAL para o cliente, nao apenas chat-especifico)
        calendar_data = {"calendar": [], "total_calendar": 0}
        db_session_calendar = None
        try:
            from App.Core.Crunch.TablesSQL.Models import Calendar

            db_session_calendar = DatabaseManager.get_session()
            db_calendar_posts = (
                db_session_calendar.query(Calendar)
                .filter(Calendar.user_id == user_id)
                .all()
            )

            if db_calendar_posts:
                calendar_list = []
                for post in db_calendar_posts:
                    calendar_list.append(
                        {
                            "id": post.post_id,
                            "campaign_name": post.campaign_name,
                            "day": (
                                post.post_date.strftime("%d.%m.%Y")
                                if post.post_date
                                else ""
                            ),
                            "short_description": post.short_description or "",
                            "content_type": post.content_type or "",
                            "status": post.status,
                        }
                    )
                calendar_data = {
                    "calendar": calendar_list,
                    "total_calendar": len(calendar_list),
                }
                debug(
                    f"[GET /api/chat/{chat_id}] Calendar posts carregados do DB (GLOBAL do cliente): {calendar_data.get('total_calendar', 0)} posts"
                )
            else:
                debug(
                    f"[GET /api/chat/{chat_id}] Nenhum calendar post encontrado para o cliente"
                )
        except Exception as e:
            debug(f"[GET /api/chat/{chat_id}] Erro ao buscar calendar posts do DB: {e}")
            calendar_data = {"calendar": [], "total_calendar": 0}
        finally:
            if db_session_calendar:
                db_session_calendar.close()

        # Debug: verificar se feedback foi adicionado
        messages_with_feedback = result.get("messages", [])
        debug(
            f"[GET /api/chat/{chat_id}] Verificando messages antes de retornar: {len(messages_with_feedback)} mensagens"
        )
        for i, msg in enumerate(messages_with_feedback[:3]):  # Debug apenas primeiras 3
            debug(f"  [{i}] msg {msg.get('id')}: feedback={msg.get('feedback')}")

        # Obter assets do cliente filtrados por chat
        assets_list = []
        db_session_contents = None
        try:
            client_id = get_client_id_from_token(request)
            db_session_contents = DatabaseManager.get_session()
            raw_assets = DatabaseManager.get_client_files(
                db_session_contents, client_id, file_category="asset", chat_id=chat_id
            )
            debug(
                f"[GET /api/chat/{chat_id}] {len(raw_assets)} assets do chat {chat_id}"
            )

            for content in raw_assets:
                try:
                    asset_id = content.get("file_id") or content.get("asset_id")
                    asset_chat_id = content.get("chat_id", chat_id)
                    asset_entry = {
                        "asset_id": str(asset_id),
                        "chat_id": asset_chat_id,
                        "variation_id": content.get("variation_id"),
                        "ratio": content.get("ratio"),
                        "approval_status": content.get("approval_status"),
                        "approval_feedback": content.get("approval_feedback"),
                        "approving_id": content.get("approving_id"),
                        "content_name": content.get("file_name"),
                        "type": content.get("file_type", "img"),
                        "created_at": (
                            str(content.get("created_at"))
                            if content.get("created_at")
                            else None
                        ),
                        "title": content.get("file_name"),
                        "link": f"/api/chat/{asset_chat_id}/asset/{asset_id}/proxy",
                    }
                    assets_list.append(asset_entry)
                except Exception as e:
                    error(f"[GET /api/chat/{chat_id}] Erro ao processar asset: {e}")
        except Exception as e:
            error(f"[GET /api/chat/{chat_id}] Erro ao buscar assets: {e}")
            import traceback

            error(traceback.format_exc())
        finally:
            if db_session_contents:
                db_session_contents.close()

        # Verificar limite de contexto e % de uso (context_usage_pct é mantido pelo SyncManager)
        _context_limit_reached = False
        _context_usage_pct = 0.0
        try:
            _last_error_job = DatabaseManager.fetch_one(
                "SELECT error_message FROM jobs WHERE chat_id = :cid AND status = 'error' ORDER BY created_at DESC LIMIT 1",
                {"cid": chat_id},
            )
            if _last_error_job:
                _err_msg = _last_error_job.get("error_message") or ""
                _context_limit_reached = (
                    "maximum context length" in _err_msg
                    or "context_length_exceeded" in _err_msg
                )
        except Exception:
            pass

        try:
            _chat_row = DatabaseManager.fetch_one(
                "SELECT context_usage_pct FROM chats WHERE chat_id = :cid",
                {"cid": chat_id},
            )
            if _chat_row:
                _context_usage_pct = float(_chat_row.get("context_usage_pct") or 0.0)
        except Exception:
            pass

        response = {
            "chat_id": result.get("chat_id"),
            "chat_name": result.get("chat_name"),
            "created_at": result.get("created_at"),
            "messages": messages_with_feedback,
            "context_limit_reached": _context_limit_reached,
            "context_usage_pct": round(_context_usage_pct, 4),
        }

        messages_count = len(messages_with_feedback)
        info(
            f"[GET /api/chat/{chat_id}] [200] Chat com {messages_count} msg"
        )

        # Debug: verificar JSON final
        try:
            json_test = json.dumps(response, default=str)

            # Verificar se feedback esta no JSON
            has_feedback_field = '"feedback"' in json_test
            has_messages = len(messages_with_feedback) > 0

            if has_messages and has_feedback_field:
                debug(
                    f"[GET /api/chat/{chat_id}] [DONE] Feedback PRESENTE no JSON final ({len(messages_with_feedback)} mensagens)"
                )
            elif has_messages and not has_feedback_field:
                error(
                    f"[GET /api/chat/{chat_id}] [FAIL] Feedback AUSENTE no JSON final! ({len(messages_with_feedback)} mensagens)"
                )
            elif not has_messages:
                debug(f"[GET /api/chat/{chat_id}] [INFO] Chat vazio (0 mensagens)")
        except Exception as e:
            debug(f"[GET /api/chat/{chat_id}] Erro ao testar JSON: {e}")

        cache_set(_chat_cache_key, response, 300)  # 5 min TTL
        return response

    except ValueError as ve:
        warning(f"[GET /api/chat/{chat_id}] Validacao: {str(ve)}")
        raise HTTPException(status_code=404, detail=str(ve))
    except HTTPException:
        raise
    except Exception as e:
        error(f"[GET /api/chat/{chat_id}] Erro: {e}")
        raise HTTPException(status_code=500, detail="Erro ao obter conversa")


@chat_operations_router.get("/debug/chat/{chat_id}/chain-of-thought-filter")
async def debug_chain_of_thought_filter(chat_id: str, request: Request):
    """
    [TEMPORARY DIAGNOSTIC ROUTE]

    Valida se a filtragem de chain-of-thought esta funcionando
    ou se ha caching impedindo o filtro de trabalhar.

    Compara:
    1. Mensagens RAW do banco (sem filtro)
    2. Mensagens FILTRADAS (com logica de CoT)

    Se o filtro esta funcionando:
    - raw_cot_count > filtered_cot_count (alguns CoT removidos)
    - filtered_cot_messages tera apenas 0 ou 1 item (a ultima)

    Se ha caching impedindo:
    - raw_cot_count == filtered_cot_count (filtro nao afeta a saida)
    """
    try:
        user_id = get_user_id_from_token(request)
        chat_service = ChatService()

        # Obter resultado bruto (sem filtro)
        result = chat_service.get_chat(chat_id=chat_id, user_id=user_id)
        raw_messages = result.get("messages", [])

        # Contar CoT messages no raw
        raw_cot_messages = []
        for idx, msg in enumerate(raw_messages):
            msg_dict = dict(msg) if not isinstance(msg, dict) else msg.copy()

            # Extrair tool name
            role = msg_dict.get("role", "user")
            if role == "tool":
                from App.Core.Crunch.SyncManager import SyncManager

                content = msg_dict.get("content", "")
                tool_name = msg_dict.get("tool") or SyncManager.extract_tool_name(
                    content
                )

                if tool_name == "chain-of-thought":
                    raw_cot_messages.append(
                        {
                            "index": idx,
                            "id": msg_dict.get("id"),
                            "created_at": msg_dict.get("created_at"),
                            "is_last_message": (idx == len(raw_messages) - 1),
                        }
                    )

        # Contar CoT messages apos filtro (simular logica do get_chat_detail)
        filtered_cot_messages = []
        for idx, msg in enumerate(raw_messages):
            msg_dict = dict(msg) if not isinstance(msg, dict) else msg.copy()

            # Extrair tool name
            role = msg_dict.get("role", "user")
            if role == "tool":
                from App.Core.Crunch.SyncManager import SyncManager

                content = msg_dict.get("content", "")
                tool_name = msg_dict.get("tool") or SyncManager.extract_tool_name(
                    content
                )

                is_last_message = idx == len(raw_messages) - 1

                # APLICAR FILTRO: Remove CoT nao-ultima
                if tool_name == "chain-of-thought" and not is_last_message:
                    continue  # Pula, nao adiciona a lista filtrada

                if tool_name == "chain-of-thought":
                    filtered_cot_messages.append(
                        {
                            "index": idx,
                            "id": msg_dict.get("id"),
                            "created_at": msg_dict.get("created_at"),
                            "is_last_message": is_last_message,
                        }
                    )

        # Montar resposta de diagnostico
        diagnostic_result = {
            "chat_id": chat_id,
            "timestamp": datetime.now().isoformat(),
            "raw_message_count": len(raw_messages),
            "raw_cot_count": len(raw_cot_messages),
            "filtered_cot_count": len(filtered_cot_messages),
            "filter_working": len(raw_cot_messages) > len(filtered_cot_messages),
            "raw_cot_messages": raw_cot_messages,
            "filtered_cot_messages": filtered_cot_messages,
            "diagnosis": _diagnose_cot_filtering(
                raw_cot_messages, filtered_cot_messages
            ),
        }

        debug(
            f"[DEBUG /api/debug/chat/{chat_id}/chain-of-thought-filter] {diagnostic_result}"
        )
        return diagnostic_result

    except ValueError as ve:
        warning(
            f"[DEBUG /api/debug/chat/{chat_id}/chain-of-thought-filter] Validacao: {str(ve)}"
        )
        raise HTTPException(status_code=404, detail=str(ve))
    except HTTPException:
        raise
    except Exception as e:
        error(f"[DEBUG /api/debug/chat/{chat_id}/chain-of-thought-filter] Erro: {e}")
        import traceback

        error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Erro ao diagnosticar filtro")


def _diagnose_cot_filtering(raw_cot: list, filtered_cot: list) -> str:
    """Diagnostico automatico do estado do filtro"""
    if not raw_cot:
        return "[DONE] SEM CoT: Nenhuma mensagem chain-of-thought no chat"

    if len(raw_cot) == len(filtered_cot):
        if len(filtered_cot) == 1:
            return "[DONE] FUNCIONANDO: Uma CoT e ela e a ultima"
        else:
            return "[FAIL] CACHING DETECTADO: Filtro nao removeu as CoTs nao-ultima"

    if len(filtered_cot) == 1:
        return f"[DONE] FUNCIONANDO: Manteve apenas a ultima CoT ({len(raw_cot)} -> 1)"

    return f"? ESTADO DESCONHECIDO: {len(raw_cot)} raw -> {len(filtered_cot)} filtered"


@chat_router.get("/{chat_id}/agent-messages")
async def get_agent_messages(
    chat_id: str, agent_id: Optional[str] = None, request: Request = None
):
    """
    Obtem mensagens de agentes para exibir no painel 'Tarefas'.

    Args:
        chat_id: ID do chat
        agent_id: ID do agente (opcional)
        request: Requisicao HTTP (para extrair token)

    Returns:
        Lista de mensagens dos agentes
    """
    try:
        # Autenticar
        client_id = get_client_id_from_token(request)

        chat_service = ChatService()
        result = chat_service.get_agent_messages(
            chat_id=chat_id, client_id=client_id, agent_id=agent_id
        )

        info(
            f"[GET /api/chat/{chat_id}/agent-messages] [200] {len(result.get('agent_messages', []))} mensagens retornadas"
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        error(f"[GET /api/chat/{chat_id}/agent-messages] Erro: {e}")
        raise HTTPException(
            status_code=500, detail="Erro ao buscar mensagens de agentes"
        )


# ============================================================================
# [DOC] CHECK DOCUMENTS ROUTES
# ============================================================================

_NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _cache_headers(content_type: str, etag: str) -> dict:
    """Cache longo para imagens imutáveis; no-cache para tudo mais."""
    if content_type.startswith("image/"):
        return {
            "Cache-Control": "private, max-age=86400, immutable",
            "ETag": f'"{etag}"',
        }
    return _NO_CACHE_HEADERS


async def get_attachment_metadata(
    chat_id: str, message_id: str, attachment_id: str, request: Request
):
    """
    Retorna metadados do attachment (file_name, file_size, file_type, etc).
    Usado pelo frontend para exibir informacoes do arquivo.

    Args:
        chat_id: ID do chat
        message_id: ID da mensagem
        attachment_id: ID do attachment
        request: Requisicao HTTP (para extrair token)

    Returns:
        JSON com metadados do attachment
    """
    try:
        client_id = get_client_id_from_token(request)

        debug(
            f"[GET /api/chat/{chat_id}/message/{message_id}/attachment/{attachment_id}] Buscando metadados"
        )
        debug(f"  - client_id: {client_id}")
        debug(f"  - chat_id: {chat_id}")
        debug(f"  - message_id: {message_id}")
        debug(f"  - attachment_id: {attachment_id}")

        # Buscar attachment no DB
        query = """
        SELECT attachment_id, file_name, file_size, file_type, storage_path, uploaded_at
        FROM attachments
        WHERE attachment_id = :attachment_id AND chat_id = :chat_id AND message_id = :message_id
        AND user_id = :user_id AND deleted_at IS NULL
        """

        attachment = DatabaseManager.fetch_one(
            query,
            {
                "attachment_id": attachment_id,
                "chat_id": chat_id,
                "message_id": message_id,
                "user_id": client_id,
            },
        )

        if not attachment:
            debug(
                f"[GET /api/chat/{chat_id}/message/{message_id}/attachment/{attachment_id}] Attachment nao encontrado"
            )
            debug("  - Tentando buscar SEM user_id para debug...")

            # Debug: Buscar sem user_id para ver se existe
            debug_query = """
            SELECT attachment_id, chat_id, message_id, user_id, file_name, deleted_at
            FROM attachments
            WHERE attachment_id = :attachment_id
            """
            debug_result = DatabaseManager.fetch_one(
                debug_query, {"attachment_id": attachment_id}
            )
            if debug_result:
                debug(f"  - Encontrado no DB: {debug_result}")
            else:
                debug("  - NAO encontrado em NENHUMA query")

            raise HTTPException(status_code=404, detail="Arquivo nao encontrado")

        debug(
            f"[GET /api/chat/{chat_id}/message/{message_id}/attachment/{attachment_id}] Attachment encontrado: {attachment.get('file_name')}"
        )

        return {
            "attachment_id": attachment.get("attachment_id"),
            "file_name": attachment.get("file_name"),
            "file_size": attachment.get("file_size"),
            "file_type": attachment.get("file_type"),
            "uploaded_at": attachment.get("uploaded_at"),
        }

    except HTTPException:
        raise
    except Exception as e:
        error(
            f"[GET /api/chat/{chat_id}/message/{message_id}/attachment/{attachment_id}] Erro: {e}"
        )
        import traceback

        error(
            f"[GET /api/chat/{chat_id}/message/{message_id}/attachment/{attachment_id}] Traceback: {traceback.format_exc()}"
        )
        raise HTTPException(
            status_code=500, detail="Erro ao buscar metadados do arquivo"
        )


@chat_operations_router.get(
    "/chat/{chat_id}/message/{message_id}/attachment/{attachment_id}"
)
async def proxy_attachment(
    chat_id: str, message_id: str, attachment_id: str, request: Request
):
    """
    Proxy para download/visualizacao de arquivo anexado a mensagem.
    Valida acesso e retorna o arquivo com headers apropriados.

    Args:
        chat_id: ID do chat
        message_id: ID da mensagem
        attachment_id: ID do attachment
        request: Requisicao HTTP (para extrair token)

    Returns:
        Arquivo com content-type apropriado
    """
    try:
        from fastapi.responses import FileResponse, JSONResponse
        from pathlib import Path

        debug(
            f"[PROXY] [START] INICIANDO - attachment_id={attachment_id}, chat_id={chat_id}, message_id={message_id}"
        )

        debug(f"[PROXY] 1 Extraindo client_id do token...")
        client_id = get_client_id_from_token(request)
        debug(f"[PROXY] [OK] client_id={client_id}")

        debug(f"[PROXY] 2 Buscando attachment no DB...")
        # Buscar attachment no DB
        # [WARN] Nota: SQLAlchemy retorna tipos especiais, nao strings puras
        # Por isso comparamos convertendo tudo para string
        query = """
        SELECT attachment_id, file_name, storage_path, storage_env, user_id, chat_id, message_id
        FROM attachments
        WHERE attachment_id = :attachment_id AND chat_id = :chat_id AND message_id = :message_id
        AND deleted_at IS NULL
        """

        # Buscar SEM filtrar por user_id primeiro, depois comparar em Python
        attachment = DatabaseManager.fetch_one(
            query,
            {
                "attachment_id": attachment_id,
                "chat_id": chat_id,
                "message_id": message_id,
            },
        )

        # [INFO] Nota: Nao validamos user_id aqui pois:
        # 1. attachment_id e unico globalmente
        # 2. chat_id + message_id + attachment_id e suficiente para ID unica
        # 3. Caso raro: attachment criado por API/sistema pode ter user_id diferente
        # O JWT ja validou o token, entao e seguro servir o arquivo

        if not attachment:
            debug(f"[PROXY] [ERR] NAO encontrado com query completa")
            debug(f"[PROXY] Tentando debug sem user_id...")

            # Debug: tentar sem user_id
            debug_query = """
            SELECT * FROM attachments
            WHERE attachment_id = :attachment_id AND chat_id = :chat_id AND message_id = :message_id
            """
            debug_result = DatabaseManager.fetch_one(
                debug_query,
                {
                    "attachment_id": attachment_id,
                    "chat_id": chat_id,
                    "message_id": message_id,
                },
            )

            if debug_result:
                debug(f"[PROXY] [OK] Encontrado SEM user_id!")
                db_uid = debug_result.get("user_id")
                debug(
                    f"[PROXY]   DB user_id: {db_uid!r} (type: {type(db_uid).__name__}, len: {len(str(db_uid))})"
                )
                debug(
                    f"[PROXY]   Token user_id: {client_id!r} (type: {type(client_id).__name__}, len: {len(str(client_id))})"
                )
                debug(f"[PROXY]   Match: {db_uid == client_id}")
                debug(f"[PROXY]   Match (str): {str(db_uid) == str(client_id)}")
                if db_uid != client_id:
                    debug(
                        f"[PROXY]   [ERR] MISMATCH! Bytes DB: {db_uid.encode() if isinstance(db_uid, str) else 'N/A'}"
                    )
                    debug(
                        f"[PROXY]   [ERR] MISMATCH! Bytes Token: {client_id.encode() if isinstance(client_id, str) else 'N/A'}"
                    )
            else:
                debug(f"[PROXY] [ERR] NAO encontrado nem sem user_id")
                # Tentar so por attachment_id
                debug(f"[PROXY] Tentando so por attachment_id...")
                id_query = (
                    "SELECT * FROM attachments WHERE attachment_id = :attachment_id"
                )
                id_result = DatabaseManager.fetch_one(
                    id_query, {"attachment_id": attachment_id}
                )
                if id_result:
                    debug(f"[PROXY] Encontrado por ID: {id_result}")

            raise HTTPException(status_code=404, detail="Arquivo nao encontrado")

        debug(f"[PROXY] [OK] Encontrado no DB")

        debug(f"[PROXY] 3 Construindo caminho do arquivo...")
        # Construir caminho do arquivo
        storage_path = attachment.get("storage_path")
        storage_env = attachment.get("storage_env")
        debug(f"[PROXY]   storage_path: {storage_path}")
        debug(f"[PROXY]   storage_env: {storage_env}")

        # Se storage_env e 'local', construir caminho relativo
        if storage_env == "local":
            from App.Core.Crunch.Storage.StorageManager import StorageManager

            base_path = StorageManager.LOCAL_STORAGE_BASE
            file_path = base_path / storage_path
            debug(f"[PROXY]   base_path: {base_path}")
            debug(f"[PROXY]   file_path: {file_path}")
            debug(f"[PROXY]   exists: {file_path.exists()}")
        else:
            file_path = Path(storage_path)
            debug(f"[PROXY]   file_path (external): {file_path}")

        debug(f"[PROXY] 4 Validando arquivo no disco...")
        # Validar que arquivo existe
        if not file_path.exists():
            error(f"[PROXY] [ERR] Arquivo NAO existe: {file_path}")
            raise HTTPException(status_code=404, detail="Arquivo nao existe no storage")

        debug(f"[PROXY] [OK] Arquivo existe")

        # Determinar content-type por extensao
        file_ext = Path(file_path).suffix.lower()
        content_type_map = {
            ".webp": "image/webp",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".pdf": "application/pdf",
            ".txt": "text/plain",
            ".csv": "text/csv",
        }
        content_type = content_type_map.get(file_ext, "application/octet-stream")

        debug(
            f"[GET /api/chat/{chat_id}/message/{message_id}/proxy/{attachment_id}] Retornando arquivo: {file_path.name}"
        )
        rel_path = StorageManager.get_relative_path(file_path)
        debug(f"  - Caminho: {rel_path}")
        debug(f"  - Tamanho: {file_path.stat().st_size} bytes")
        debug(f"  - Content-Type: {content_type}")

        return FileResponse(
            path=file_path,
            filename=attachment.get("file_name"),
            media_type=content_type,
            headers=_cache_headers(content_type, attachment_id),
        )

    except HTTPException:
        raise
    except Exception as e:
        error(
            f"[GET /api/chat/{chat_id}/message/{message_id}/proxy/{attachment_id}] Erro: {e}"
        )
        import traceback

        error(
            f"[GET /api/chat/{chat_id}/message/{message_id}/proxy/{attachment_id}] Traceback: {traceback.format_exc()}"
        )
        raise HTTPException(status_code=500, detail="Erro ao buscar arquivo")


@chat_operations_router.get("/chat/{chat_id}/attachment/{attachment_id}")
async def proxy_attachment_direct(chat_id: str, attachment_id: str, request: Request):
    """
    Proxy para attachment sem message_id.
    Usado para arquivos gerados pelo terminal (que nao tem message_id).
    """
    try:
        from fastapi.responses import FileResponse
        from pathlib import Path

        client_id = get_client_id_from_token(request)

        query = """
        SELECT attachment_id, file_name, storage_path, storage_env
        FROM attachments
        WHERE attachment_id = :attachment_id AND chat_id = :chat_id
        AND deleted_at IS NULL
        """
        attachment = DatabaseManager.fetch_one(
            query, {"attachment_id": attachment_id, "chat_id": chat_id}
        )

        if not attachment:
            raise HTTPException(status_code=404, detail="Arquivo nao encontrado")

        storage_path = attachment.get("storage_path")
        storage_env = attachment.get("storage_env")

        if storage_env == "local":
            from App.Core.Crunch.Storage.StorageManager import StorageManager

            file_path = StorageManager.LOCAL_STORAGE_BASE / storage_path
        else:
            file_path = Path(storage_path)

        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Arquivo nao existe no storage")

        file_ext = Path(file_path).suffix.lower()
        content_type_map = {
            ".webp": "image/webp",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".svg": "image/svg+xml",
            ".pdf": "application/pdf",
            ".txt": "text/plain",
            ".log": "text/plain",
            ".csv": "text/csv",
            ".tsv": "text/tab-separated-values",
            ".html": "text/html",
            ".htm": "text/html",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xls": "application/vnd.ms-excel",
            ".json": "application/json",
            ".db": "application/octet-stream",
            ".sqlite": "application/octet-stream",
            ".sqlite3": "application/octet-stream",
            ".parquet": "application/octet-stream",
        }
        content_type = content_type_map.get(file_ext, "application/octet-stream")

        # inline: browser renderiza direto (imagem, html, texto, json, csv)
        # attachment: browser força download (binários, planilhas, db)
        _INLINE_TYPES = {
            "image/",
            "text/",
            "application/json",
            "application/pdf",
        }
        is_inline = any(content_type.startswith(t) for t in _INLINE_TYPES)
        fname = attachment.get("file_name") or file_path.name
        disposition = (
            f'inline; filename="{fname}"'
            if is_inline
            else f'attachment; filename="{fname}"'
        )

        return FileResponse(
            path=file_path,
            media_type=content_type,
            headers={
                "Content-Disposition": disposition,
                **_cache_headers(content_type, attachment_id),
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        error(f"[PROXY_DIRECT] Erro ao buscar attachment {attachment_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar arquivo")


@chat_operations_router.get("/screenshot/{screenshot_id}/view")
async def view_screenshot_by_temp_token(screenshot_id: str, token: str = Query(...)):
    """
    Retorna screenshot validado por token temporario (sem autenticacao JWT).
    Usado pelo Replicate API para analisar screenshots com vision.
    Token gerado em TemporaryScreenshotStore.generate() com TTL de 30 min.

    Uso: GET /api/screenshot/{screenshot_id}/view?token={token}
    """
    try:
        from App.Core.Utils.TemporaryScreenshotStore import get_filepath
        from fastapi.responses import FileResponse

        debug(
            f"[SCREENSHOT_TOKEN] Validando screenshot_id={screenshot_id}, token={token[:20]}..."
        )

        filepath = get_filepath(token)
        if not filepath:
            debug(f"[SCREENSHOT_TOKEN] Token invalido ou expirado para {screenshot_id}")
            raise HTTPException(status_code=403, detail="Token invalido ou expirado")

        from pathlib import Path

        filepath = Path(filepath)

        if not filepath.exists():
            error(f"[SCREENSHOT_TOKEN] Screenshot nao existe: {filepath}")
            raise HTTPException(status_code=404, detail="Screenshot nao encontrado")

        debug(f"[SCREENSHOT_TOKEN] Retornando screenshot: {filepath.name}")

        return FileResponse(
            path=filepath,
            media_type="image/png",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    except HTTPException:
        raise
    except Exception as e:
        error(f"[SCREENSHOT_TOKEN] Erro ao buscar screenshot {token}: {e}")
        import traceback

        error(f"[SCREENSHOT_TOKEN] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Erro ao buscar screenshot")


@chat_operations_router.get("/chat/{chat_id}/attachment/{attachment_id}/db-tables")
async def get_db_tables(
    chat_id: str,
    attachment_id: str,
    request: Request,
    table: Optional[str] = None,
):
    """Retorna lista de tabelas + dados de uma tabela específica (tail=100 linhas)."""
    import sqlite3 as _sqlite3

    try:
        get_client_id_from_token(request)

        query = """
        SELECT storage_path, storage_env FROM attachments
        WHERE attachment_id = :attachment_id AND chat_id = :chat_id AND deleted_at IS NULL
        """
        attachment = DatabaseManager.fetch_one(
            query, {"attachment_id": attachment_id, "chat_id": chat_id}
        )
        if not attachment:
            raise HTTPException(status_code=404, detail="Arquivo não encontrado")

        storage_path = attachment.get("storage_path")
        storage_env = attachment.get("storage_env")

        from App.Core.Crunch.Storage.StorageManager import StorageManager
        from pathlib import Path as _Path

        file_path = (
            StorageManager.LOCAL_STORAGE_BASE / storage_path
            if storage_env == "local"
            else _Path(storage_path)
        )
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Arquivo não existe no storage")

        conn = _sqlite3.connect(str(file_path))
        conn.row_factory = _sqlite3.Row
        try:
            table_names = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
            ]

            target = (
                table
                if table and table in table_names
                else (table_names[0] if table_names else None)
            )

            data = None
            if target:
                # `target` is validated against the SQLite master table list above;
                # double-quotes escape the identifier per SQL standard — safe against injection.
                assert target in table_names, "table not in whitelist"
                try:
                    count_q = f'SELECT COUNT(*) FROM "{target}"'  # nosec B608 — whitelist-validated
                    rows_q = f'SELECT * FROM "{target}" ORDER BY rowid DESC LIMIT 100'  # nosec B608
                    row_count = conn.execute(count_q).fetchone()[0]
                    cursor = conn.execute(rows_q)
                    columns = [d[0] for d in cursor.description or []]
                    rows = list(reversed([list(r) for r in cursor.fetchall()]))
                    data = {
                        "name": target,
                        "columns": columns,
                        "rows": rows,
                        "row_count": row_count,
                    }
                except Exception:
                    data = {"name": target, "columns": [], "rows": [], "row_count": 0}
        finally:
            conn.close()

        return {"tables": table_names, "data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@chat_operations_router.get("/chat/{chat_id}/attachment/{attachment_id}/view")
async def view_attachment_by_temp_token(
    chat_id: str,
    attachment_id: str,
    token: str,
):
    """
    Retorna arquivo de attachment validado por token temporario (sem cookie JWT).
    Usado pelo LLM para analisar imagens enviadas como media attachment.
    Token gerado em MessageProcessor._generate_temp_media_url() com TTL de 10 min.
    """
    try:
        from App.Core.Utils.TempTokenStore import validate
        from fastapi.responses import FileResponse
        from App.Core.Crunch.Storage.StorageManager import StorageManager

        debug(f"[TEMP_TOKEN] Validando token para attachment {attachment_id}")

        entry = validate(token)
        if not entry or entry["attachment_id"] != attachment_id:
            debug(
                f"[TEMP_TOKEN] Token invalido ou expirado para attachment {attachment_id}"
            )
            raise HTTPException(status_code=403, detail="Token invalido ou expirado")

        query = """
        SELECT file_name, storage_path, storage_env
        FROM attachments
        WHERE attachment_id = :attachment_id AND user_id = :user_id AND deleted_at IS NULL
        """
        attachment = DatabaseManager.fetch_one(
            query, {"attachment_id": attachment_id, "user_id": entry["user_id"]}
        )

        if not attachment:
            debug(f"[TEMP_TOKEN] Attachment nao encontrado: {attachment_id}")
            raise HTTPException(status_code=404, detail="Arquivo nao encontrado")

        if attachment.get("storage_env") == "local":
            base_path = StorageManager.LOCAL_STORAGE_BASE
            file_path = base_path / Path(attachment["storage_path"])
        else:
            file_path = Path(attachment["storage_path"])

        if not file_path.exists():
            error(f"[TEMP_TOKEN] Arquivo nao existe: {file_path}")
            raise HTTPException(status_code=404, detail="Arquivo nao existe no storage")

        file_ext = file_path.suffix.lower()
        content_type_map = {
            ".webp": "image/webp",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
        }
        content_type = content_type_map.get(file_ext, "application/octet-stream")

        debug(
            f"[TEMP_TOKEN] Retornando imagem: {file_path.name} (content-type: {content_type})"
        )

        return FileResponse(
            path=file_path,
            media_type=content_type,
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    except HTTPException:
        raise
    except Exception as e:
        error(f"[TEMP_TOKEN] Erro ao buscar attachment {attachment_id}: {e}")
        import traceback

        error(f"[TEMP_TOKEN] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Erro ao buscar arquivo")


@chat_operations_router.get("/files/temp/{token}")
async def serve_temp_file(token: str):
    """
    Serve arquivo por token temporário gerado via generate_temporary_public_url.
    Multi-use — não consome o token. Expira conforme TTL (padrão 1h).
    """
    import mimetypes
    from pathlib import Path as _Path
    from fastapi.responses import FileResponse
    from App.Core.Utils.TempTokenStore import validate_file_token

    filepath = validate_file_token(token)
    if not filepath:
        raise HTTPException(status_code=403, detail="Token inválido ou expirado")

    file_path = _Path(filepath)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")

    mime = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    return FileResponse(
        path=file_path,
        media_type=mime,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@chat_operations_router.post("/debug/tool/{tool_name}", status_code=200)
async def debug_execute_tool(tool_name: str, request: Request):
    """
    [DEBUG] ROTA DE DEBUG - Executa tools diretamente para validacao rapida

    Headers obrigatorios:
    - X-Dev-Bypass-Key: dev_bypass_key configurado

    Body: JSON com argumentos especificos da tool

    Query parameter (opcional):
    - sync=true: Executar sincronamente e retornar resultado imediato (apenas para scraping rapido)

    Exemplos:
    POST /api/debug/tool/scraping
    {"search": "Nike"}

    POST /api/debug/tool/scraping?sync=true
    {"search": "Nike"}  -> Retorna resultado direto, sem polling

    POST /api/debug/tool/asset
    {"type": "image", "prompt": "...", "reference_image": "..."}

    Retorna (async mode):
    {
        "success": true,
        "tool_call_id": "550e8400-e29b-41d4-a716-446655440000",
        "tool_name": "scraping",
        "message": "Tool enfileirada para execucao",
        "next_step": "GET /api/debug/tool/scraping/tool_call/550e8400-e29b-41d4-a716-446655440000/result"
    }

    Retorna (sync mode):
    {
        "success": true,
        "tool_name": "scraping",
        "result": "[resultado da execucao]",
        "execution_time": 1.23
    }
    """
    try:
        # Verificar dev_bypass_key no header
        dev_bypass_key = request.headers.get("X-Dev-Bypass-Key", "").strip()
        if not dev_bypass_key:
            raise HTTPException(
                status_code=401, detail="X-Dev-Bypass-Key header e obrigatorio"
            )

        # Validar tool_name
        valid_tools = ["scraping", "asset", "vision", "document"]
        if tool_name not in valid_tools:
            raise HTTPException(
                status_code=400, detail=f"Tool invalida. Validas: {valid_tools}"
            )

        # Parse body
        body = await request.json()
        if not body:
            raise HTTPException(
                status_code=400, detail="Body com argumentos e obrigatorio"
            )

        # Check if sync mode requested (only for scraping, which is fast)
        sync_mode = request.query_params.get("sync", "false").lower() == "true"

        # Only allow sync for scraping (fast), not for media generation (slow)
        if sync_mode and tool_name not in ["scraping", "vision"]:
            raise HTTPException(
                status_code=400,
                detail="Sync mode only available for scraping and vision",
            )

        # Criar IDs para teste
        tool_call_id = str(uuid.uuid4())  # UUID que sera salvo em isolated_messages
        message_id = str(uuid.uuid4())
        test_chat_id = "debug-chat-" + str(uuid.uuid4())[:8]
        test_job_id = str(uuid.uuid4())
        test_client_id = 1  # Cliente padrao para debug
        debug_agent_id = "debug-agent"

        debug(f"[DEBUG TOOL] Executando {tool_name} com args: {body}")
        debug(f"[DEBUG TOOL] tool_call_id: {tool_call_id}")

        # Criar ou recuperar isolated_chat ANTES de enfileirar
        isolated_chat_id = None
        try:
            db_session = DatabaseManager.get_session()
            try:
                # Recuperar ou criar isolated_chat
                isolated_chat = DatabaseManager.get_or_create_isolated_chat(
                    session=db_session,
                    chat_id=test_chat_id,
                    agent_id=debug_agent_id,
                    user_id=test_client_id,
                )
                isolated_chat_id = isolated_chat.id
                debug(
                    f"[DEBUG TOOL] Isolated chat recovered/created: {isolated_chat_id}"
                )
            finally:
                db_session.close()
        except Exception as e:
            warning(f"[DEBUG TOOL] Error creating isolated_chat: {e}")

        # Enfileirar como external tool call
        try:
            from App.Core.Queues import ToolCall

            queue_manager = COMPONENTS.get("queue_manager")
            if not queue_manager:
                raise HTTPException(
                    status_code=500, detail="queue_manager nao disponivel"
                )

            # IMPORTANTE: Para DEBUG, enfileiramos a tool DIRETAMENTE, bypassando MessageProcessor
            # Isso permite testar tools sem conversa real ou validacoes de UX (como print obrigatorio)
            tool_call = ToolCall(
                tool_call_id=tool_call_id,  # Este e o UUID que sera salvo em isolated_messages
                message_id=message_id,
                chat_id=test_chat_id,
                client_id=test_client_id,
                job_id=test_job_id,
                tool_name=tool_name,
                arguments=body,
                agent_id=debug_agent_id,
            )

            queue_manager.enqueue_tool_call(tool_call)

            info(
                f"[DEBUG TOOL] Tool {tool_name} enfileirada (BYPASS MODE - sem MessageProcessor) com tool_call_id: {tool_call_id}"
            )

            return {
                "success": True,
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "message": f"Tool '{tool_name}' enfileirada para execucao (bypass mode - sem validacoes de MessageProcessor)",
                "next_step": f"GET /api/debug/tool/{tool_name}/tool_call/{tool_call_id}/result",
            }

        except Exception as e:
            error(f"[DEBUG TOOL] Erro ao enfileirar: {e}")
            raise HTTPException(
                status_code=500, detail=f"Erro ao enfileirar tool: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        error(f"[DEBUG TOOL] Erro: {e}")
        import traceback

        error(f"[DEBUG TOOL] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@chat_operations_router.get("/chat/{chat_id}/asset/{asset_id}/proxy")
async def proxy_asset(chat_id: str, asset_id: str, request: Request):
    """Proxy para retornar arquivo de asset gerado por mediaai."""
    try:
        client_id = get_client_id_from_token(request)
        user_id = get_user_id_from_token(request)

        db_session = None
        try:
            db_session = DatabaseManager.get_session()
            asset_file = DatabaseManager.get_generated_content_by_id(
                db_session, asset_id
            )

            if not asset_file:
                raise HTTPException(status_code=404, detail="Asset nao encontrado")

            # Validar que o asset pertence ao chat e cliente corretos (str comparison to avoid int/str mismatch)
            if asset_file.get("chat_id") != chat_id or str(
                asset_file.get("client_id", "")
            ) != str(client_id):
                raise HTTPException(status_code=403, detail="Acesso negado")

            # Validar que e um asset
            if asset_file.get("file_category") != "asset":
                raise HTTPException(status_code=400, detail="Arquivo nao e um asset")

            storage_path = asset_file.get("storage_path")
            if not storage_path:
                raise HTTPException(
                    status_code=404, detail="Storage path nao disponivel"
                )

            # Construir caminho do arquivo
            if asset_file.get("storage_env") == "local":
                from App.Core.Crunch.Storage.StorageManager import StorageManager

                base_path = StorageManager.LOCAL_STORAGE_BASE
                file_path = base_path / storage_path
            else:
                file_path = Path(storage_path)

            # Validar que arquivo existe
            if not file_path.exists():
                raise HTTPException(status_code=404, detail="Arquivo nao existe")

            # Determinar content-type por extensao
            file_ext = Path(file_path).suffix.lower()
            content_type_map = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".gif": "image/gif",
                ".webp": "image/webp",
                ".mp4": "video/mp4",
                ".webm": "video/webm",
                ".mov": "video/quicktime",
                ".avi": "video/x-msvideo",
            }
            content_type = content_type_map.get(file_ext, "application/octet-stream")

            # # Verificar se usuario e free - aplicar watermark obrigatoriamente
            # file_to_serve = file_path
            # from App.Core.Crunch.Storage.WatermarkManager import WatermarkManager

            # if WatermarkManager.should_apply_watermark(user_id):
            #     # Gerar nome do arquivo com watermark
            #     watermarked_filename = WatermarkManager.get_watermarked_filename(file_path.name)
            #     watermarked_path = file_path.parent / watermarked_filename

            #     # Se ainda nao tem watermark, gerar
            #     if not watermarked_path.exists():
            #         if not WatermarkManager.add_image_watermark(file_path, watermarked_path):
            #             raise HTTPException(status_code=500, detail="Erro ao gerar marca d'agua do arquivo")
            #         debug(f"[WATERMARK] Arquivo com watermark gerado: {watermarked_filename}")

            #     file_to_serve = watermarked_path
            #     debug(f"[WATERMARK] Servindo arquivo com watermark: {watermarked_filename}")

            file_to_serve = file_path

            # Ler e retornar arquivo
            with open(file_to_serve, "rb") as f:
                file_content = f.read()

            from fastapi.responses import Response

            return Response(content=file_content, media_type=content_type)

        finally:
            if db_session:
                db_session.close()

    except HTTPException:
        raise
    except Exception as e:
        error(f"[GET /api/chat/{chat_id}/asset/{asset_id}/proxy] Erro: {e}")
        import traceback

        error(
            f"[GET /api/chat/{chat_id}/asset/{asset_id}/proxy] Traceback: {traceback.format_exc()}"
        )
        raise HTTPException(status_code=500, detail="Erro ao buscar asset")


class AssetJudgeBody(BaseModel):
    feedback: Optional[str] = None
    status: Optional[str] = None  # 'approved', 'discarded', 'improve'


async def _judge_asset(
    chat_id: str, asset_id: str, action: str, feedback: Optional[str], request: Request
):
    """Helper compartilhado para approve / discard / improve."""
    from sqlalchemy import text as _text_j

    client_id = get_client_id_from_token(request)

    db_session = None
    try:
        db_session = DatabaseManager.get_session()

        # Validar que o asset pertence ao chat e cliente
        asset_row = db_session.execute(
            _text_j(
                "SELECT asset_id, client_id FROM assets WHERE asset_id = :aid AND chat_id = :cid"
            ),
            {"aid": asset_id, "cid": chat_id},
        ).first()

        if not asset_row:
            raise HTTPException(
                status_code=404, detail="Asset nao encontrado neste chat"
            )
        if str(asset_row[1]) != str(client_id):
            raise HTTPException(status_code=403, detail="Acesso negado")

        db_session.execute(
            _text_j(
                "UPDATE assets SET approval_status = :status, feedback = :feedback, updated_at = CURRENT_TIMESTAMP WHERE asset_id = :aid"
            ),
            {"status": action, "feedback": feedback, "aid": asset_id},
        )
        db_session.commit()
        return {
            "success": True,
            "asset_id": asset_id,
            "status": action,
            "feedback": feedback,
        }

    finally:
        if db_session:
            db_session.close()


@chat_operations_router.post("/chat/{chat_id}/asset/{asset_id}/status")
async def set_asset_status(
    chat_id: str, asset_id: str, body: AssetJudgeBody = None, request: Request = None
):
    action = (body.status if body and body.status else None) or "approved"
    return await _judge_asset(
        chat_id, asset_id, action, body.feedback if body else None, request
    )


class AssetRefineBody(BaseModel):
    prompt: str
    aspect_ratio: Optional[str] = None


@chat_operations_router.post("/chat/{chat_id}/asset/{asset_id}/refine")
async def refine_asset(
    chat_id: str, asset_id: str, body: AssetRefineBody, request: Request
):
    """
    Gera uma nova variação do asset usando o asset existente como imagem de referência.
    Chama generate_from_reference_image com o prompt do usuário e retorna o novo asset_id.
    """
    import asyncio
    from sqlalchemy import text
    from App.Core.Crunch.Storage.StorageManager import StorageManager
    from App.Features.Tools.Tools.Assets import generate_from_reference_image

    client_id = get_client_id_from_token(request)
    user_id = get_user_id_from_token(request)

    debug(
        f"[REFINE] chat_id={chat_id} asset_id={asset_id} client_id={client_id} user_id={user_id}"
    )

    db_session = None
    try:
        db_session = DatabaseManager.get_session()

        # Buscar asset original
        asset_row = db_session.execute(
            text(
                "SELECT asset_id, client_id, storage_path, storage_env, ratio FROM assets "
                "WHERE asset_id = :aid AND chat_id = :cid"
            ),
            {"aid": asset_id, "cid": chat_id},
        ).first()

        debug(f"[REFINE] asset_row={asset_row}")

        if not asset_row:
            raise HTTPException(
                status_code=404, detail="Asset não encontrado neste chat"
            )
        if str(asset_row[1]) != str(client_id):
            debug(f"[REFINE] client_id mismatch: db={asset_row[1]} token={client_id}")
            raise HTTPException(status_code=403, detail="Acesso negado")

        storage_path = asset_row[2]
        storage_env = asset_row[3]
        original_ratio = asset_row[4] or "1:1"

        # Resolver caminho completo do arquivo
        if storage_env == "local" or not storage_env:
            full_path = str(StorageManager.LOCAL_STORAGE_BASE / storage_path)
        else:
            full_path = storage_path

        if not Path(full_path).exists():
            raise HTTPException(
                status_code=404, detail="Arquivo do asset não encontrado"
            )

        # Calcular próximo ID versionado: <root>-v{N}.<ext>
        import re as _re

        _stem, _ext = asset_id.rsplit(".", 1) if "." in asset_id else (asset_id, "jpg")
        _root = _re.sub(r"-v\d+$", "", _stem)
        _like_pattern = f"{_root}-v%"
        _count_row = db_session.execute(
            text("SELECT COUNT(*) FROM assets WHERE asset_id LIKE :pat"),
            {"pat": _like_pattern},
        ).first()
        _next_version = (_count_row[0] if _count_row else 0) + 1
        _new_asset_id = f"{_root}-v{_next_version}.{_ext}"

    finally:
        if db_session:
            db_session.close()

    aspect_ratio = body.aspect_ratio or original_ratio

    await chat_watcher.broadcast(
        chat_id,
        {
            "type": "refine_job_start",
            "asset_id": asset_id,
            "new_asset_id": _new_asset_id,
        },
    )

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: generate_from_reference_image(
            reference_image=full_path,
            num_variations=1,
            prompt_extra=body.prompt,
            chat_id=chat_id,
            user_id=user_id,
            db_manager=DatabaseManager,
            aspect_ratio=aspect_ratio,
            asset_id_override=_new_asset_id,
        ),
    )

    debug(
        f"[REFINE] generate result: success={result.get('success')} error={result.get('error')} assets={result.get('generated_assets')}"
    )

    if not result.get("success"):
        await chat_watcher.broadcast(
            chat_id,
            {
                "type": "refine_job_error",
                "asset_id": asset_id,
                "error": result.get("error", "Erro ao gerar variação"),
            },
        )
        raise HTTPException(
            status_code=500, detail=result.get("error", "Erro ao gerar variação")
        )

    generated = result.get("generated_assets", [])
    if not generated or not generated[0].get("asset_id"):
        raise HTTPException(status_code=500, detail="Nenhum asset gerado")

    new_asset = generated[0]
    new_asset_id = new_asset["asset_id"]

    await chat_watcher.broadcast(
        chat_id,
        {
            "type": "refine_job_done",
            "asset_id": asset_id,
            "new_asset_id": new_asset_id,
            "ratio": new_asset.get("ratio", aspect_ratio),
        },
    )

    return {
        "success": True,
        "asset_id": new_asset_id,
        "link": f"/api/chat/{chat_id}/asset/{new_asset_id}/proxy",
        "ratio": new_asset.get("ratio", aspect_ratio),
        "credits_consumed": result.get("credits_consumed", 0),
        "credits_remaining": result.get("credits_remaining", 0),
    }


@chat_operations_router.get(
    "/brand-communication/assets/{client_part}/{assets_part}/{filename}"
)
async def get_brand_communication_asset(
    client_part: str, assets_part: str, filename: str, request: Request
):
    """
    Serve arquivos de assets brand_communication armazenados em client_{client_id}/assets/

    Args:
        client_part: Parte do caminho contendo client_id com prefixo (client_xxxxx)
        assets_part: Literal 'assets'
        filename: Nome do arquivo
        request: Requisicao HTTP

    Returns:
        Arquivo com content-type apropriado
    """
    try:
        from App.Core.Crunch.Storage.StorageManager import StorageManager

        # Extrair client_id do client_part
        if not client_part.startswith("client_"):
            raise HTTPException(status_code=400, detail="Formato de URL invalido")

        client_id = client_part.replace("client_", "")

        # Validar que assets_part e 'assets'
        if assets_part != "assets":
            raise HTTPException(status_code=400, detail="Formato de URL invalido")

        # Construir caminho do arquivo
        assets_folder = StorageManager.get_client_assets_folder(client_id)
        file_path = assets_folder / filename

        # Validar que arquivo existe
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Arquivo nao encontrado")

        # Seguranca: garantir que o arquivo esta dentro da pasta permitida
        try:
            file_path.relative_to(assets_folder)
        except ValueError:
            raise HTTPException(status_code=403, detail="Acesso negado")

        # Determinar content-type
        file_ext = Path(file_path).suffix.lower()
        content_type_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".mov": "video/quicktime",
            ".avi": "video/x-msvideo",
        }
        content_type = content_type_map.get(file_ext, "application/octet-stream")

        # Ler e retornar arquivo
        with open(file_path, "rb") as f:
            file_content = f.read()

        from fastapi.responses import Response

        return Response(
            content=file_content,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    except HTTPException:
        raise
    except Exception as e:
        error(
            f"[GET /api/brand-communication/assets/{client_part}/{assets_part}/{filename}] Erro: {e}"
        )
        import traceback

        error(
            f"[GET /api/brand-communication/assets/{client_part}/{assets_part}/{filename}] Traceback: {traceback.format_exc()}"
        )
        raise HTTPException(status_code=500, detail="Erro ao buscar asset")


# ============================================================================
# [LIKE] MESSAGE FEEDBACK ROUTES (Like, Dislike, Feedback)
# ============================================================================


@chat_operations_router.post(
    "/chat/{chat_id}/message/{message_id}/like", status_code=200
)
async def like_message(chat_id: str, message_id: str, request: Request):
    """
    Enviar like em uma mensagem.

    Args:
        chat_id: ID do chat
        message_id: ID da mensagem
        request: Requisicao HTTP (para extrair token)

    Returns:
        JSON com status da operacao
    """
    try:
        user_id = get_user_id_from_token(request)

        debug(f"[POST /api/chat/{chat_id}/message/{message_id}/like] Marcando like")
        debug(f"  - user_id: {user_id}")
        debug(f"  - chat_id: {chat_id}")
        debug(f"  - message_id: {message_id}")

        # Inserir ou atualizar feedback
        insert_query = """
        INSERT INTO message_feedbacks (feedback_id, chat_id, message_id, user_id, feedback_type, created_at, updated_at)
        VALUES (:feedback_id, :chat_id, :message_id, :user_id, 'like', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(message_id, feedback_type) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
        """

        DatabaseManager.execute_query(
            insert_query,
            {
                "feedback_id": str(uuid.uuid4()),
                "chat_id": chat_id,
                "message_id": message_id,
                "user_id": user_id,
            },
        )

        info(
            f"[POST /api/chat/{chat_id}/message/{message_id}/like] Like registrado com sucesso"
        )

        return {
            "status": "success",
            "feedback_type": "like",
            "message_id": message_id,
            "timestamp": datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[POST /api/chat/{chat_id}/message/{message_id}/like] Erro: {e}")
        import traceback

        error(
            f"[POST /api/chat/{chat_id}/message/{message_id}/like] Traceback: {traceback.format_exc()}"
        )
        raise HTTPException(status_code=500, detail="Erro ao registrar like")


@chat_operations_router.post(
    "/chat/{chat_id}/message/{message_id}/dislike", status_code=200
)
async def dislike_message(chat_id: str, message_id: str, request: Request):
    """
    Enviar dislike em uma mensagem (sem feedback).

    Args:
        chat_id: ID do chat
        message_id: ID da mensagem
        request: Requisicao HTTP (para extrair token)

    Returns:
        JSON com status da operacao
    """
    try:
        user_id = get_user_id_from_token(request)

        debug(
            f"[POST /api/chat/{chat_id}/message/{message_id}/dislike] Marcando dislike"
        )
        debug(f"  - user_id: {user_id}")
        debug(f"  - chat_id: {chat_id}")
        debug(f"  - message_id: {message_id}")

        # Inserir ou atualizar feedback
        feedback_id = str(uuid.uuid4())
        insert_query = """
        INSERT INTO message_feedbacks (feedback_id, chat_id, message_id, user_id, feedback_type, created_at, updated_at)
        VALUES (:feedback_id, :chat_id, :message_id, :user_id, 'dislike', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(message_id, feedback_type) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
        """

        DatabaseManager.execute_query(
            insert_query,
            {
                "feedback_id": feedback_id,
                "chat_id": chat_id,
                "message_id": message_id,
                "user_id": user_id,
            },
        )

        info(
            f"[POST /api/chat/{chat_id}/message/{message_id}/dislike] Dislike registrado com sucesso"
        )

        return {
            "status": "success",
            "feedback_type": "dislike",
            "message_id": message_id,
            "timestamp": datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[POST /api/chat/{chat_id}/message/{message_id}/dislike] Erro: {e}")
        import traceback

        error(
            f"[POST /api/chat/{chat_id}/message/{message_id}/dislike] Traceback: {traceback.format_exc()}"
        )
        raise HTTPException(status_code=500, detail="Erro ao registrar dislike")


@chat_operations_router.post(
    "/chat/{chat_id}/message/{message_id}/feedback", status_code=200
)
async def send_message_feedback(
    chat_id: str, message_id: str, body: FeedbackRequest, request: Request
):
    """
    Enviar feedback detalhado sobre uma mensagem.
    Rota independente para coletar feedback adicional.

    Args:
        chat_id: ID do chat
        message_id: ID da mensagem
        body: Feedback Request com conteudo do feedback
        request: Requisicao HTTP (para extrair token)

    Returns:
        JSON com status da operacao
    """
    try:
        user_id = get_user_id_from_token(request)

        debug(
            f"[POST /api/chat/{chat_id}/message/{message_id}/feedback] Enviando feedback"
        )
        debug(f"  - user_id: {user_id}")
        debug(f"  - chat_id: {chat_id}")
        debug(f"  - message_id: {message_id}")
        debug(f"  - feedback length: {len(body.feedback) if body.feedback else 0}")

        # Atualizar feedback com conteudo
        update_query = """
        UPDATE message_feedbacks
        SET content = :content, updated_at = CURRENT_TIMESTAMP
        WHERE message_id = :message_id AND feedback_type = 'dislike' AND user_id = :user_id
        """

        DatabaseManager.execute_query(
            update_query,
            {"content": body.feedback, "message_id": message_id, "user_id": user_id},
        )

        info(
            f"[POST /api/chat/{chat_id}/message/{message_id}/feedback] Feedback registrado com sucesso"
        )

        try:
            from App.Core.Services.TelegramAlert import telegram_alert_service
            from App.Core.Services.AdminEmail import admin_email_service

            subject = "💬 Feedback de chat recebido"
            alert_body = (
                f"Feedback de mensagem no chat:\n\n"
                f"User: {user_id}\n"
                f"Chat: {chat_id}\n"
                f"Mensagem: {message_id}\n\n"
                f"---\n{body.feedback or '(sem texto)'}\n---"
            )
            telegram_alert_service.send_critical_alert(subject, alert_body)
            admin_email_service.send_critical_alert(subject, alert_body)
        except Exception as alert_err:
            error(f"[FEEDBACK CHAT] Erro ao enviar alerta: {alert_err}")

        return {
            "status": "success",
            "message_id": message_id,
            "feedback_received": True,
            "timestamp": datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[POST /api/chat/{chat_id}/message/{message_id}/feedback] Erro: {e}")
        import traceback

        error(
            f"[POST /api/chat/{chat_id}/message/{message_id}/feedback] Traceback: {traceback.format_exc()}"
        )
        raise HTTPException(status_code=500, detail="Erro ao registrar feedback")


@chat_operations_router.post(
    "/chat/{chat_id}/message/{message_id}/cancel-like", status_code=200
)
async def cancel_like(chat_id: str, message_id: str, request: Request):
    """
    Cancelar like de uma mensagem.

    Args:
        chat_id: ID do chat
        message_id: ID da mensagem
        request: Requisicao HTTP (para extrair token)

    Returns:
        JSON com status da operacao
    """
    try:
        user_id = get_user_id_from_token(request)

        debug(
            f"[POST /api/chat/{chat_id}/message/{message_id}/cancel-like] Cancelando like"
        )
        debug(f"  - user_id: {user_id}")
        debug(f"  - chat_id: {chat_id}")
        debug(f"  - message_id: {message_id}")

        # Deletar feedback de like
        delete_query = """
        DELETE FROM message_feedbacks
        WHERE message_id = :message_id AND feedback_type = 'like' AND user_id = :user_id
        """

        DatabaseManager.execute_query(
            delete_query, {"message_id": message_id, "user_id": user_id}
        )

        info(
            f"[POST /api/chat/{chat_id}/message/{message_id}/cancel-like] Like cancelado com sucesso"
        )

        return {
            "status": "success",
            "action": "cancel",
            "feedback_type": "like",
            "message_id": message_id,
            "timestamp": datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[POST /api/chat/{chat_id}/message/{message_id}/cancel-like] Erro: {e}")
        import traceback

        error(
            f"[POST /api/chat/{chat_id}/message/{message_id}/cancel-like] Traceback: {traceback.format_exc()}"
        )
        raise HTTPException(status_code=500, detail="Erro ao cancelar like")


@chat_operations_router.post(
    "/chat/{chat_id}/message/{message_id}/cancel-dislike", status_code=200
)
async def cancel_dislike(chat_id: str, message_id: str, request: Request):
    """
    Cancelar dislike de uma mensagem.

    Args:
        chat_id: ID do chat
        message_id: ID da mensagem
        request: Requisicao HTTP (para extrair token)

    Returns:
        JSON com status da operacao
    """
    try:
        user_id = get_user_id_from_token(request)

        debug(
            f"[POST /api/chat/{chat_id}/message/{message_id}/cancel-dislike] Cancelando dislike"
        )
        debug(f"  - user_id: {user_id}")
        debug(f"  - chat_id: {chat_id}")
        debug(f"  - message_id: {message_id}")

        # Deletar feedback de dislike
        delete_query = """
        DELETE FROM message_feedbacks
        WHERE message_id = :message_id AND feedback_type = 'dislike' AND user_id = :user_id
        """

        DatabaseManager.execute_query(
            delete_query, {"message_id": message_id, "user_id": user_id}
        )

        info(
            f"[POST /api/chat/{chat_id}/message/{message_id}/cancel-dislike] Dislike cancelado com sucesso"
        )

        return {
            "status": "success",
            "action": "cancel",
            "feedback_type": "dislike",
            "message_id": message_id,
            "timestamp": datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        error(
            f"[POST /api/chat/{chat_id}/message/{message_id}/cancel-dislike] Erro: {e}"
        )
        import traceback

        error(
            f"[POST /api/chat/{chat_id}/message/{message_id}/cancel-dislike] Traceback: {traceback.format_exc()}"
        )
        raise HTTPException(status_code=500, detail="Erro ao cancelar dislike")


# ============================================================================
# [QUIZ] QUIZ ROUTES
# ============================================================================

from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import uuid

# ... (outros imports se houver, mas manterei o foco no quiz_answer)


@chat_operations_router.patch("/chat/{chat_id}/calendar/{post_id}", status_code=200)
async def update_calendar_post(
    chat_id: str,
    post_id: str,
    request_data: UpdateCalendarPostRequest,
    request: Request,
):
    """
    Atualiza dados de um post do calendario (data e/ou descricao).
    """
    try:
        # Autenticar
        user_id = get_user_id_from_token(request)

        chat_service = ChatService()
        result = chat_service.update_calendar_post(
            post_id=post_id,
            user_id=user_id,
            post_date=request_data.post_date,
            short_description=request_data.short_description,
        )

        info(
            f"[PATCH /api/chat/{chat_id}/calendar/{post_id}] Atualizacao realizada: {request_data.dict(exclude_none=True)}"
        )
        return result

    except ValueError as ve:
        warning(f"[PATCH /api/chat/{chat_id}/calendar/{post_id}] {str(ve)}")
        raise HTTPException(status_code=400, detail=str(ve))
    except HTTPException:
        raise
    except Exception as e:
        error(f"[PATCH /api/chat/{chat_id}/calendar/{post_id}] Erro: {e}")
        raise HTTPException(status_code=500, detail="Erro ao atualizar agendamento")


@chat_operations_router.post(
    "/chat/{chat_id}/message/{message_id}/quiz_answer", status_code=202
)
async def submit_quiz_answer(
    chat_id: str,
    message_id: str,
    request_data: QuizAnswerRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Recebe as respostas do usuario para um quiz e retoma o looping da IA.
    Retorna imediatamente 202 Accepted para permitir polling do front.
    """
    try:
        from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
        from App.Features.Job import get_job_manager

        client_id = get_client_id_from_token(request)
        quiz_call_id = request_data.quiz_call_id
        answers = request_data.answers

        debug(
            f"[POST /api/chat/{chat_id}/message/{message_id}/quiz_answer] Recebendo respostas para quiz_call_id: {quiz_call_id}"
        )

        session = DatabaseManager.get_session()
        try:
            # 1. Se quiz_call_id nao veio no body, extrair do message_id (INPUT do quiz)
            if not quiz_call_id:
                input_msg_query = "SELECT tool_call_id FROM isolated_messages WHERE isolated_message_id = :message_id AND tool_called = 'quiz' AND tool_call_type = 'input' LIMIT 1"
                input_msg = DatabaseManager.fetch_one(
                    input_msg_query, {"message_id": message_id}
                )
                if not input_msg:
                    raise HTTPException(
                        status_code=404, detail="Quiz INPUT nao encontrado"
                    )

                quiz_call_id = input_msg.get("tool_call_id")
                if not quiz_call_id:
                    raise HTTPException(
                        status_code=400, detail="tool_call_id nao preenchido no INPUT"
                    )

                debug(
                    f"[POST /api/chat/{chat_id}/message/{message_id}/quiz_answer] tool_call_id extraido do INPUT: {quiz_call_id}"
                )
            else:
                debug(
                    f"[POST /api/chat/{chat_id}/message/{message_id}/quiz_answer] tool_call_id recebido no body: {quiz_call_id}"
                )

            # 2. Obter user_id
            user_query = (
                "SELECT user_id FROM users WHERE client_id = :client_id LIMIT 1"
            )
            user_result = DatabaseManager.fetch_one(
                user_query, {"client_id": client_id}
            )
            if not user_result:
                raise HTTPException(status_code=500, detail="Usuario nao encontrado")
            user_id = user_result.get("user_id")

            agent_id = "orchestrator-global"

            # 3. Buscar INPUT do quiz para dados originais
            input_query = "SELECT content FROM isolated_messages WHERE tool_call_id = :tool_call_id AND tool_called = 'quiz' AND tool_call_type = 'input' LIMIT 1"
            input_msg = DatabaseManager.fetch_one(
                input_query, {"tool_call_id": quiz_call_id}
            )

            quiz_data = {}
            first_question = None
            first_options = None
            first_type = None
            first_answer = None
            raw_call = ""

            if input_msg and input_msg.get("content"):
                try:
                    raw_input_content = input_msg.get("content", "")
                    raw_call = raw_input_content  # Guardar raw completo

                    # Parse: conteudo pode ser "Tool: quiz\nArgs: {...}" ou JSON direto
                    input_content = None
                    if raw_input_content.startswith("Tool:"):
                        # Formato raw_input: "Tool: quiz\nArgs: {...}"
                        if "Args: " in raw_input_content:
                            args_part = raw_input_content.split("Args: ", 1)[1]
                            input_content = json.loads(args_part)
                    else:
                        # Formato JSON direto
                        input_content = json.loads(raw_input_content)

                    # Extrair quiz data original (pode ser array de questoes)
                    if input_content:
                        quiz_list = input_content.get("quiz", [])
                        if quiz_list:
                            first_q = quiz_list[0]
                            first_question = first_q.get("question", "")
                            first_options = first_q.get("options", [])
                            first_type = first_q.get("type", "")

                            # Buscar a resposta para a primeira pergunta
                            if answers:
                                first_answer = answers[0].get("answer", "")
                except Exception as e:
                    debug(f"[POST /quiz_answer] Erro ao parsear INPUT: {e}")
                    pass

            # Construir final_answers (todas as respostas em formato estruturado)
            # Para perguntas com attachment: true, substituir o answer (filename) pelo attachment_id
            quiz_questions_map = {}
            if input_msg and input_msg.get("content"):
                try:
                    _rc = input_msg.get("content", "")
                    _ic = None
                    if "Args: " in _rc:
                        _ic = json.loads(_rc.split("Args: ", 1)[1])
                    else:
                        _ic = json.loads(_rc)
                    for _q in (_ic or {}).get("quiz", []):
                        quiz_questions_map[_q.get("question", "")] = _q
                except Exception:
                    pass

            final_answers = []
            for answer_item in answers:
                _q_text = answer_item.get("question", "")
                _ans = answer_item.get("answer", "")
                _q_def = quiz_questions_map.get(_q_text, {})

                # Per-answer attachment_ids (embedded by frontend per-step) take priority.
                # Never use global attachment_id/attachment_ids as fallback — they belong
                # to a specific question and would overwrite URL answers in other questions.
                _per_ids = answer_item.get("attachment_ids")
                if _per_ids and isinstance(_per_ids, list) and len(_per_ids) > 0:
                    if _q_def.get("attachment") is True and len(_per_ids) == 1:
                        _ans = _per_ids[0]  # single attachment: plain UUID string
                    else:
                        _ans = json.dumps(
                            _per_ids, ensure_ascii=False
                        )  # multiple: JSON array

                final_answers.append({"question": _q_text, "answer": _ans})

            # Salvar OUTPUT com novo formato (apenas success, raw, final_answers)
            output_data: Dict[str, Any] = {
                "success": True,
                "raw": raw_call,
                "final_answers": final_answers,
            }
            if request_data.attachment_id:
                output_data["attachment_id"] = request_data.attachment_id
            result_content = json.dumps(output_data, ensure_ascii=False)

            DatabaseManager.save_isolated_message(
                session=session,
                isolated_chat_id=chat_id,
                agent_id=agent_id,
                agent="ORCHESTRATOR_GLOBAL",
                role="assistant",
                content=result_content,
                message_type="tool_call",
                tool_call_id=quiz_call_id,
                tool_called="quiz",
                tool_call_type="output",
                # isolated_message_id auto-gerado como novo UUID
                # tool_call_id identifica a pair INPUT/OUTPUT para consolidacao
            )
            session.commit()
            debug(
                f"[POST /api/chat/{chat_id}/quiz_answer] Respostas salvas em isolated_messages"
            )
        except Exception as e:
            session.rollback()
            error(
                f"[POST /api/chat/{chat_id}/quiz_answer] Erro ao salvar respostas: {e}"
            )
            raise HTTPException(
                status_code=500, detail="Erro ao salvar respostas do quiz"
            )
        finally:
            session.close()

        # 2b. Mover todos os attachments da TempFolder para pasta permanente do chat/message
        _all_attachment_ids: list = []
        if request_data.attachment_id:
            _all_attachment_ids.append(request_data.attachment_id)
        if request_data.attachment_ids:
            _all_attachment_ids.extend(request_data.attachment_ids)
        # Deduplicate preserving order
        _seen_ids: set = set()
        _deduped: list = []
        for _aid in _all_attachment_ids:
            if _aid not in _seen_ids:
                _seen_ids.add(_aid)
                _deduped.append(_aid)
        _all_attachment_ids = _deduped
        if _all_attachment_ids:
            try:
                await move_attachments_from_temp(
                    client_id=client_id,
                    chat_id=chat_id,
                    message_id=message_id,
                    attachment_ids=_all_attachment_ids,
                )
                debug(
                    f"[POST /api/chat/{chat_id}/quiz_answer] Attachments movidos: {_all_attachment_ids}"
                )
            except Exception as e:
                error(
                    f"[POST /api/chat/{chat_id}/quiz_answer] Erro ao mover attachments: {e}"
                )
                # Não bloqueia o fluxo — a resposta já foi salva

        # 3. PREPARAR RETOMADA (Tentar encontrar job em waiting ou criar um novo)
        job_manager = get_job_manager()
        existing_job = job_manager.find_active_job_by_chat_id(chat_id)

        if existing_job and existing_job.status == "waiting":
            debug(
                f"[POST /api/chat/{chat_id}/quiz_answer] Retomando job existente: {existing_job.job_id}"
            )
            existing_job.set_status("running")
            new_job = existing_job
            job_id = existing_job.job_id
        else:
            new_job = job_manager.create_job(
                chat_id=chat_id, user_id=str(user_id) if user_id else None
            )
            job_id = new_job.job_id
            debug(f"[POST /api/chat/{chat_id}/quiz_answer] Criado novo job: {job_id}")

        # 4. Agendar a retomada no BackgroundTasks
        message_processor = COMPONENTS.get("message_processor")
        if not message_processor:
            raise HTTPException(
                status_code=500, detail="MessageProcessor nao inicializado"
            )

        # Funcao auxiliar para rodar em background (evita bloqueio do request)
        def run_resume():
            try:
                # Nota: Aqui passamos o job_id para o MessageProcessor se ele suportar,
                # ou deixamos ele criar o dele. Como queremos que o polling funcione,
                # o job_id retornado deve ser o que o worker vai atualizar.
                debug(
                    f"[Background] Iniciando retomada do quiz para chat {chat_id}, job {job_id}"
                )

                # Vamos injetar o job_id no resume_after_tool_call para ele saber qual job usar
                # (Precisaremos ajustar o MessageProcessor para aceitar um job_id opcional)
                message_processor.resume_after_tool_call(
                    chat_id=chat_id,
                    message_id=message_id,
                    content=result_content,
                    user_id=user_id,
                    agent_id=agent_id,
                    job_id=job_id,  # Passaremos o ID que ja criamos
                )
            except Exception as e:
                error(f"[Background] Erro na retomada do quiz: {e}")

        background_tasks.add_task(run_resume)

        info(
            f"[POST /api/chat/{chat_id}/quiz_answer] Resposta aceita. Polling deve usar job_id: {job_id}"
        )

        return {
            "success": True,
            "job_id": job_id,
            "status": "processing",
            "message": "Respostas recebidas. O processamento continuara em segundo plano.",
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[POST /api/chat/{chat_id}/quiz_answer] Erro geral: {e}")
        import traceback

        error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


# ========================================================================
# TOOL APPROVAL — Aprovar ou rejeitar tool interceptada (autonomy_level = 3)
# ========================================================================


class ToolApprovalRequest(BaseModel):
    tool_approval_id: str = Field(
        ..., description="ID do registro em trigger_tool_approvals"
    )
    approved: bool = Field(..., description="True para aprovar, False para rejeitar")
    message_id: Optional[str] = Field(
        None,
        description="ID da mensagem no frontend (messages table) para update direto",
    )
    adjusted_args: Optional[str] = Field(
        None, description="JSON com args ajustados (opcional, apenas quando aprovado)"
    )


@chat_operations_router.post(
    "/chat/{chat_id}/message/{message_id}/tool_approval", status_code=202
)
async def submit_tool_approval(
    chat_id: str,
    message_id: str,
    request_data: ToolApprovalRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Recebe a decisão do usuário (aprovar/rejeitar) para uma tool interceptada
    pelo autonomy gate (nível 3) e retoma o processamento.
    """
    try:
        from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
        from App.Features.Job import get_job_manager
        from datetime import datetime as _dt

        client_id = get_client_id_from_token(request)
        tool_approval_id = request_data.tool_approval_id
        approved = request_data.approved

        debug(
            f"[POST /api/chat/{chat_id}/message/{message_id}/tool_approval] "
            f"tool_approval_id={tool_approval_id}, approved={approved}"
        )

        session = DatabaseManager.get_session()
        try:
            # 1. Buscar o registro de aprovação
            approval_row = DatabaseManager.fetch_one(
                "SELECT * FROM trigger_tool_approvals WHERE id = :id LIMIT 1",
                {"id": tool_approval_id},
            )
            if not approval_row:
                raise HTTPException(
                    status_code=404, detail="tool_approval não encontrado"
                )

            if approval_row["status"] != "pending":
                # Atualizar o content da mensagem em messages caso ainda mostre "waiting"
                # (pode ocorrer se o update anterior falhou ou é uma approval antiga)
                try:
                    _existing_status = approval_row["status"]
                    _existing_approved = _existing_status == "approved"
                    _pending_msg = DatabaseManager.fetch_one(
                        """SELECT message_id, content FROM messages
                           WHERE chat_id = :chat_id
                           AND json_extract(content, '$.tool_approval_id') = :approval_id
                           AND json_extract(content, '$.status') = 'waiting'
                           LIMIT 1""",
                        {"chat_id": chat_id, "approval_id": tool_approval_id},
                    )
                    if _pending_msg:
                        _pc = json.loads(_pending_msg["content"])
                        _pc["approved"] = _existing_approved
                        _pc["status"] = _existing_status
                        DatabaseManager.execute_query(
                            "UPDATE messages SET content = :content WHERE message_id = :mid",
                            {
                                "content": json.dumps(_pc, ensure_ascii=False),
                                "mid": _pending_msg["message_id"],
                            },
                        )
                        debug(
                            f"[tool_approval/409] messages atualizado para status={_existing_status}"
                        )
                except Exception as _fix_err:
                    debug(f"[tool_approval/409] Falha ao corrigir message: {_fix_err}")
                raise HTTPException(
                    status_code=409,
                    detail=f"tool_approval já processado: {approval_row['status']}",
                )

            # 2. Obter user_id
            user_result = DatabaseManager.fetch_one(
                "SELECT user_id FROM users WHERE client_id = :client_id LIMIT 1",
                {"client_id": client_id},
            )
            if not user_result:
                raise HTTPException(status_code=500, detail="Usuario nao encontrado")
            user_id = user_result.get("user_id")

            agent_id = "orchestrator-global"
            tool_name = approval_row["tool_name"]
            args_json = approval_row["args_json"] or "{}"

            # 3. Determinar args efetivos (originais ou ajustados)
            if approved and request_data.adjusted_args:
                try:
                    effective_args = json.loads(request_data.adjusted_args)
                    effective_args_str = request_data.adjusted_args
                except Exception:
                    effective_args = json.loads(args_json)
                    effective_args_str = args_json
            else:
                effective_args = json.loads(args_json)
                effective_args_str = args_json

            # 4. Para rejeição, montar result_content agora (sem execução)
            if not approved:
                rejection_error = "Execução rejeitada pelo usuário."
                rejection_payload: dict = {
                    "success": False,
                    "approved": False,
                    "tool": tool_name,
                    "tool_approval_id": tool_approval_id,
                    "error": rejection_error,
                }
                if request_data.adjusted_args:
                    rejection_payload[
                        "user_adjustment_request"
                    ] = request_data.adjusted_args
                    rejection_payload["error"] = (
                        f"Execução rejeitada pelo usuário com solicitação de ajuste: "
                        f"{request_data.adjusted_args}. "
                        f"Refaça a ação incorporando este ajuste."
                    )
                result_content_immediate = json.dumps(
                    rejection_payload, ensure_ascii=False
                )
            else:
                # Para aprovação: content provisório; o real chega no background
                result_content_immediate = json.dumps(
                    {
                        "success": True,
                        "approved": True,
                        "tool": tool_name,
                        "tool_approval_id": tool_approval_id,
                        "status": "processing",
                    },
                    ensure_ascii=False,
                )

            # 5. Marcar status imediatamente no DB (protege contra retentativas)
            new_status = "approved" if approved else "rejected"
            DatabaseManager.execute_query(
                """
                UPDATE trigger_tool_approvals
                SET status = :status, result_json = :result, updated_at = :now
                WHERE id = :id
                """,
                {
                    "status": new_status,
                    "result": result_content_immediate,
                    "now": _dt.utcnow().isoformat(),
                    "id": tool_approval_id,
                },
            )

            # 6b. Atualizar o content da mensagem em messages para refletir a decisão
            try:
                _body_message_id = request_data.message_id or message_id
                if _body_message_id:
                    pending_msg = DatabaseManager.fetch_one(
                        """SELECT message_id, content FROM messages
                           WHERE message_id = :mid AND chat_id = :chat_id LIMIT 1""",
                        {"mid": _body_message_id, "chat_id": chat_id},
                    )
                else:
                    pending_msg = DatabaseManager.fetch_one(
                        """SELECT message_id, content FROM messages
                           WHERE chat_id = :chat_id
                           AND json_extract(content, '$.tool_approval_id') = :approval_id
                           LIMIT 1""",
                        {"chat_id": chat_id, "approval_id": tool_approval_id},
                    )
                if pending_msg:
                    try:
                        _pending = json.loads(pending_msg["content"])
                        _pending["approved"] = approved
                        _pending["status"] = new_status
                        DatabaseManager.execute_query(
                            "UPDATE messages SET content = :content WHERE message_id = :mid",
                            {
                                "content": json.dumps(_pending, ensure_ascii=False),
                                "mid": pending_msg["message_id"],
                            },
                        )
                        debug(
                            f"[tool_approval] messages content atualizado: message_id={_body_message_id}"
                        )
                    except Exception as _upd_err:
                        debug(
                            f"[tool_approval] Falha ao atualizar content em messages: {_upd_err}"
                        )
            except Exception as _find_err:
                debug(
                    f"[tool_approval] Não encontrou mensagem para atualizar: {_find_err}"
                )

            session.commit()

        except HTTPException:
            session.rollback()
            raise
        except Exception as e:
            session.rollback()
            error(f"[tool_approval] Erro ao processar: {e}")
            raise HTTPException(status_code=500, detail="Erro ao processar aprovação")
        finally:
            session.close()

        # 7. Retomar o job
        job_manager = get_job_manager()
        existing_job = job_manager.find_active_job_by_chat_id(chat_id)

        if existing_job and existing_job.status == "waiting":
            existing_job.set_status("running")
            new_job = existing_job
            job_id = existing_job.job_id
            debug(f"[tool_approval] Retomando job existente: {job_id}")
        else:
            new_job = job_manager.create_job(
                chat_id=chat_id, user_id=str(user_id) if user_id else None
            )
            job_id = new_job.job_id
            debug(f"[tool_approval] Criado novo job: {job_id}")

        message_processor = COMPONENTS.get("message_processor")
        if not message_processor:
            raise HTTPException(
                status_code=500, detail="MessageProcessor nao inicializado"
            )

        # Capturar variáveis para o background (closure)
        _bg_chat_id = chat_id
        _bg_message_id = message_id
        _bg_user_id = user_id
        _bg_agent_id = agent_id
        _bg_job_id = job_id
        _bg_tool_name = tool_name
        _bg_tool_approval_id = tool_approval_id
        _bg_approved = approved
        _bg_effective_args_str = effective_args_str
        _bg_job_id_approval = approval_row.get("job_id")
        _bg_result_immediate = result_content_immediate

        def run_resume():
            try:
                debug(
                    f"[Background/tool_approval] Retomando chat {_bg_chat_id}, job {_bg_job_id}"
                )
                _broadcast_job_status(_bg_chat_id, _bg_job_id, "running")

                if _bg_approved:
                    # Executar a tool no background (pode ser demorado: Vertex AI, etc.)
                    try:
                        from App.Features.Tools.Core import Core as ToolCore

                        _db_manager = COMPONENTS.get("db_manager")
                        _chat_manager = COMPONENTS.get("chat_manager")
                        _msg_proc = COMPONENTS.get("message_processor")

                        executor = ToolCore(
                            db_manager=_db_manager,
                            chat_manager=_chat_manager,
                            message_processor=_msg_proc,
                        )
                        executor.current_chat_id = _bg_chat_id
                        executor.current_user_id = _bg_user_id
                        executor.current_job_id = _bg_job_id_approval
                        executor.current_isolated_message_id = _bg_message_id
                        executor._autonomy_cache = {_bg_chat_id: 5}

                        tool_result_raw = executor.execute_tool(
                            tool_name=_bg_tool_name,
                            arguments=_bg_effective_args_str,
                            agent_id=_bg_agent_id,
                            chat_id=_bg_chat_id,
                            user_id=_bg_user_id,
                            job_id=_bg_job_id_approval,
                            isolated_message_id=_bg_message_id,
                        )
                    except Exception as exec_err:
                        error(
                            f"[Background/tool_approval] Erro ao executar tool: {exec_err}"
                        )
                        tool_result_raw = json.dumps(
                            {
                                "success": False,
                                "error": str(exec_err),
                                "tool": _bg_tool_name,
                            },
                            ensure_ascii=False,
                        )

                    result_content = json.dumps(
                        {
                            "success": True,
                            "approved": True,
                            "tool": _bg_tool_name,
                            "tool_approval_id": _bg_tool_approval_id,
                            "tool_result": tool_result_raw,
                        },
                        ensure_ascii=False,
                    )

                    # Atualizar trigger_tool_approvals com resultado real
                    try:
                        from datetime import datetime as _dt2

                        DatabaseManager.execute_query(
                            "UPDATE trigger_tool_approvals SET result_json = :result, updated_at = :now WHERE id = :id",
                            {
                                "result": result_content,
                                "now": _dt2.utcnow().isoformat(),
                                "id": _bg_tool_approval_id,
                            },
                        )
                    except Exception as _ue:
                        debug(
                            f"[Background/tool_approval] Falha ao atualizar result_json: {_ue}"
                        )

                    # Atualizar OUTPUT em isolated_messages
                    try:
                        from App.Core.Crunch.TablesSQL.DBManager import (
                            DatabaseManager as _DBM2,
                        )
                        from App.Core.Crunch.TablesSQL.Models import (
                            IsolatedMessage as _IsoMsg,
                        )

                        _bg_session = _DBM2.get_session()
                        try:
                            _iso_output = (
                                _bg_session.query(_IsoMsg)
                                .filter(
                                    _IsoMsg.isolated_chat_id == _bg_chat_id,
                                    _IsoMsg.tool_call_type == "output",
                                    _IsoMsg.content.contains(_bg_tool_approval_id),
                                )
                                .first()
                            )
                            if _iso_output:
                                _iso_output.content = result_content
                                _iso_output.tool_called = _bg_tool_name
                                _bg_session.commit()
                            else:
                                _DBM2.save_isolated_message(
                                    session=_bg_session,
                                    isolated_chat_id=_bg_chat_id,
                                    agent_id=_bg_agent_id,
                                    agent="ORCHESTRATOR_GLOBAL",
                                    role="assistant",
                                    content=result_content,
                                    message_type="tool_call",
                                    tool_call_id=_bg_tool_approval_id,
                                    tool_called=_bg_tool_name,
                                    tool_call_type="output",
                                )
                        finally:
                            _bg_session.close()
                    except Exception as _step6_err:
                        debug(
                            f"[Background/tool_approval] Falha ao atualizar isolated_messages: {_step6_err}"
                        )

                    # Atualizar messages table com tool_result para render do card
                    try:
                        _msg_row = DatabaseManager.fetch_one(
                            """SELECT message_id, content FROM messages
                               WHERE chat_id = :chat_id
                               AND json_extract(content, '$.tool_approval_id') = :approval_id
                               LIMIT 1""",
                            {
                                "chat_id": _bg_chat_id,
                                "approval_id": _bg_tool_approval_id,
                            },
                        )
                        if _msg_row:
                            _mc = json.loads(_msg_row["content"])
                            _mc["tool_result"] = tool_result_raw
                            DatabaseManager.execute_query(
                                "UPDATE messages SET content = :content WHERE message_id = :mid",
                                {
                                    "content": json.dumps(_mc, ensure_ascii=False),
                                    "mid": _msg_row["message_id"],
                                },
                            )
                    except Exception as _mre:
                        debug(
                            f"[Background/tool_approval] Falha ao atualizar tool_result em messages: {_mre}"
                        )
                else:
                    result_content = _bg_result_immediate

                message_processor.resume_after_tool_call(
                    chat_id=_bg_chat_id,
                    message_id=_bg_message_id,
                    content=result_content,
                    user_id=_bg_user_id,
                    agent_id=_bg_agent_id,
                    job_id=_bg_job_id,
                )
            except Exception as e:
                error(f"[Background/tool_approval] Erro na retomada: {e}")

        background_tasks.add_task(run_resume)

        info(
            f"[tool_approval] Aprovação processada: tool={tool_name}, approved={approved}, job_id={job_id}"
        )

        return {
            "success": True,
            "job_id": job_id,
            "status": "processing",
            "approved": approved,
            "message": "Decisão registrada. Processamento retomado em segundo plano.",
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[POST /tool_approval] Erro geral: {e}")
        import traceback

        error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


# ========================================================================
# WEBSOCKET ENDPOINT - Via Middleware (em /api/)
# ========================================================================


@chat_operations_router.websocket("/ws/notifications")
async def user_notifications_ws(websocket: WebSocket):
    """WebSocket para notificações de unseen chats (triggers/scheduled)"""
    await websocket.accept()

    from App.Core.Services.WS.WSService import ws_authenticate as _ws_auth

    user_id = await _ws_auth(websocket, label="WS-NOTIFICATIONS")
    if not user_id:
        try:
            await websocket.close(code=1008, reason="Unauthorized")
        except Exception:
            pass
        return

    await user_watcher.connect(websocket, user_id)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if msg == "pong":
                    debug(f"[UWS] Pong recebido de user {user_id}")
            except asyncio.TimeoutError:
                await websocket.send_text("ping")
    except WebSocketDisconnect:
        await user_watcher.disconnect(websocket, user_id)
    except Exception as e:
        error(f"[UWS] Erro na conexao user {user_id}: {e}")
        await user_watcher.disconnect(websocket, user_id)


# ========================================================================
# [DESIGN] CREATIVE DESIGN ROUTES (CANVA-LIKE)
# ========================================================================


def _assert_chat_owner(db_session, chat_id: str, user_id: str) -> None:
    """Levanta 403 se o chat_id não pertence ao user_id autenticado."""
    from sqlalchemy import text as _t

    row = db_session.execute(
        _t("SELECT 1 FROM chats WHERE chat_id = :c AND user_id = :u"),
        {"c": chat_id, "u": user_id},
    ).first()
    if not row:
        raise HTTPException(status_code=403, detail="Acesso negado")


@chat_operations_router.get("/chat/{chat_id}/creative/{composition_id}")
async def get_creative_composition(chat_id: str, composition_id: str, request: Request):
    """
    Retorna uma composicao criativa especifica (arvore JSON do Canva).
    """
    try:
        user_id = get_user_id_from_token(request)

        db_session = DatabaseManager.get_session()
        try:
            from App.Core.Crunch.TablesSQL.Models import CreativeComposition

            _assert_chat_owner(db_session, chat_id, user_id)

            # Buscar composicao
            creative = (
                db_session.query(CreativeComposition)
                .filter(
                    CreativeComposition.composition_id == composition_id,
                    CreativeComposition.chat_id == chat_id,
                )
                .first()
            )

            if not creative:
                raise HTTPException(status_code=404, detail="Composicao nao encontrada")

            return {
                "success": True,
                "composition_id": creative.composition_id,
                "chat_id": creative.chat_id,
                "title": creative.title,
                "state": creative.state,
                "version": creative.version,
                "preview_url": creative.preview_url,
                "updated_at": creative.updated_at.isoformat(),
            }
        finally:
            db_session.close()

    except HTTPException:
        raise
    except Exception as e:
        error(f"[GET /api/chat/{chat_id}/creative/{composition_id}] Erro: {e}")
        raise HTTPException(status_code=500, detail="Erro ao carregar composicao")


@chat_operations_router.post("/chat/{chat_id}/creative/{composition_id}/update")
async def update_creative_composition(
    chat_id: str,
    composition_id: str,
    request_data: UpdateCreativeRequest,
    request: Request,
):
    """
    Atualiza o estado (arvore JSON) de uma composicao criativa.
    """
    try:
        user_id = get_user_id_from_token(request)

        db_session = DatabaseManager.get_session()
        try:
            from App.Core.Crunch.TablesSQL.Models import CreativeComposition
            from sqlalchemy import text as _text

            _assert_chat_owner(db_session, chat_id, user_id)

            # Buscar composicao existente
            creative = (
                db_session.query(CreativeComposition)
                .filter(
                    CreativeComposition.composition_id == composition_id,
                    CreativeComposition.chat_id == chat_id,
                )
                .first()
            )

            if not creative:
                # Se nao existe, podemos criar (comportamento upsert amigavel para frontend)
                new_creative = CreativeComposition(
                    composition_id=composition_id,
                    chat_id=chat_id,
                    title=request_data.title or "Sem titulo",
                    state=request_data.state,
                    version=1,
                    preview_url=request_data.preview_url,
                )
                db_session.add(new_creative)
                db_session.commit()
                info(
                    f"[POST /api/chat/{chat_id}/creative/{composition_id}/update] Criada nova composicao"
                )
                return {"success": True, "message": "Design criado", "version": 1}

            # Atualizar campos
            if request_data.title:
                creative.title = request_data.title
            creative.state = request_data.state
            creative.version = (creative.version or 0) + 1
            if request_data.preview_url:
                creative.preview_url = request_data.preview_url
            creative.updated_at = datetime.utcnow()

            db_session.commit()
            info(
                f"[POST /api/chat/{chat_id}/creative/{composition_id}/update] Design atualizado para v{creative.version}"
            )

            return {
                "success": True,
                "message": "Design atualizado",
                "version": creative.version,
            }

        finally:
            db_session.close()

    except HTTPException:
        raise
    except Exception as e:
        error(f"[POST /api/chat/{chat_id}/creative/{composition_id}/update] Erro: {e}")
        import traceback

        debug(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Erro ao salvar composicao")


@chat_operations_router.get("/chat/{chat_id}/creative/{composition_id}/snapshot/status")
async def get_snapshot_status(chat_id: str, composition_id: str, request: Request):
    """
    Verifica se o snapshot está atualizado em relação à versão atual do design.
    Frontend usa para decidir se precisa enviar um novo snapshot.
    Retorna needs_snapshot=True se versões divergem ou snapshot ainda não existe.
    """
    try:
        user_id = get_user_id_from_token(request)
        db_session = DatabaseManager.get_session()
        try:
            from App.Core.Crunch.TablesSQL.Models import CreativeComposition

            _assert_chat_owner(db_session, chat_id, user_id)

            creative = (
                db_session.query(CreativeComposition)
                .filter(
                    CreativeComposition.composition_id == composition_id,
                    CreativeComposition.chat_id == chat_id,
                )
                .first()
            )
            if not creative:
                raise HTTPException(status_code=404, detail="Composicao nao encontrada")

            current_version = creative.version or 1
            snapshot_version = creative.snapshot_version
            needs_snapshot = (
                snapshot_version is None or snapshot_version != current_version
            )

            return {
                "needs_snapshot": needs_snapshot,
                "current_version": current_version,
                "snapshot_version": snapshot_version,
            }
        finally:
            db_session.close()
    except HTTPException:
        raise
    except Exception as e:
        error(f"[GET snapshot/status] {e}")
        raise HTTPException(status_code=500, detail="Erro ao verificar snapshot")


class UploadSnapshotRequest(BaseModel):
    snapshot_b64: str  # base64 PNG sem prefixo data URI


@chat_operations_router.post("/chat/{chat_id}/creative/{composition_id}/snapshot")
async def upload_snapshot(
    chat_id: str,
    composition_id: str,
    request_data: UploadSnapshotRequest,
    request: Request,
):
    """
    Salva o snapshot base64 do design renderizado e marca snapshot_version = version atual.
    Só deve ser chamado quando /snapshot/status retornar needs_snapshot=True.
    """
    try:
        user_id = get_user_id_from_token(request)
        db_session = DatabaseManager.get_session()
        try:
            from App.Core.Crunch.TablesSQL.Models import CreativeComposition

            _assert_chat_owner(db_session, chat_id, user_id)

            creative = (
                db_session.query(CreativeComposition)
                .filter(
                    CreativeComposition.composition_id == composition_id,
                    CreativeComposition.chat_id == chat_id,
                )
                .first()
            )
            if not creative:
                raise HTTPException(status_code=404, detail="Composicao nao encontrada")

            creative.snapshot_b64 = request_data.snapshot_b64
            creative.snapshot_version = creative.version or 1
            db_session.commit()
            debug(
                f"[POST snapshot] snapshot salvo para {composition_id} v{creative.snapshot_version}"
            )
            return {"success": True, "snapshot_version": creative.snapshot_version}
        finally:
            db_session.close()
    except HTTPException:
        raise
    except Exception as e:
        error(f"[POST snapshot] {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar snapshot")


@chat_operations_router.get("/chat/{chat_id}/creative/{composition_id}/snapshot")
async def serve_snapshot(chat_id: str, composition_id: str, request: Request):
    """
    Serve o snapshot do design como imagem PNG (para vision do agente).
    Fallback: tenta servir o asset bruto se snapshot nao existe.
    """
    import base64
    from fastapi.responses import Response

    try:
        user_id = get_user_id_from_token(request)
        db_session = DatabaseManager.get_session()
        try:
            from App.Core.Crunch.TablesSQL.Models import CreativeComposition, Asset

            _assert_chat_owner(db_session, chat_id, user_id)

            creative = (
                db_session.query(CreativeComposition)
                .filter(
                    CreativeComposition.composition_id == composition_id,
                    CreativeComposition.chat_id == chat_id,
                )
                .first()
            )
            if not creative:
                raise HTTPException(status_code=404, detail="Composicao nao encontrada")

            # Snapshot disponível — detecta WebP vs PNG pelo magic bytes
            if creative.snapshot_b64:
                try:
                    img_bytes = base64.b64decode(creative.snapshot_b64)
                    # WebP magic: "RIFF....WEBP"; PNG magic: b'\x89PNG'
                    if img_bytes[:4] == b"RIFF" and img_bytes[8:12] == b"WEBP":
                        media_type = "image/webp"
                    elif img_bytes[:4] == b"\x89PNG":
                        media_type = "image/png"
                    else:
                        media_type = "image/jpeg"
                    return Response(content=img_bytes, media_type=media_type)
                except Exception:
                    pass  # fallback para asset bruto se b64 corrompido

            # Fallback: asset bruto (composition_id == asset_id sem extensão)
            asset_id = composition_id + ".jpg"
            asset = db_session.query(Asset).filter(Asset.asset_id == asset_id).first()
            if asset and asset.file_path:
                import os

                if os.path.exists(asset.file_path):
                    with open(asset.file_path, "rb") as f:
                        return Response(content=f.read(), media_type="image/jpeg")

            raise HTTPException(status_code=404, detail="Snapshot nao disponivel")
        finally:
            db_session.close()
    except HTTPException:
        raise
    except Exception as e:
        error(f"[GET snapshot] {e}")
        raise HTTPException(status_code=500, detail="Erro ao servir snapshot")
