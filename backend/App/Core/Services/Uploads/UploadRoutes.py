"""
Rotas de Upload - FastAPI Routes para gerenciar uploads de arquivos
Apenas rotas e validações HTTP, lógica delegada para UploadService
"""

import os
import json
import asyncio
import hashlib
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field

import uuid
from datetime import datetime, timedelta

from App.Core.Logs import debug, info, warning, error
from App.Features.Auth import get_auth_service
from App.Core.Crunch.Storage.StorageManager import StorageManager
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Crunch.Storage.MediaCompressor import MediaCompressor

# ========================================================================
# MODELS
# ========================================================================


class UploadResponse(BaseModel):
    """Resposta de upload"""

    attachment_id: str
    file_name: str
    extension: str
    file_size: int
    storage_path: str
    is_temp: bool
    uploaded_at: str


class AttachmentDeleteRequest(BaseModel):
    """Requisição para deletar attachment"""

    attachment_id: str = Field(..., description="ID do attachment a deletar")


# ========================================================================
# ROUTER
# ========================================================================

upload_router = APIRouter(tags=["Uploads"], prefix="/api/upload")


# ========================================================================
# DEPENDENCY - Extrair client_id do token
# ========================================================================


def get_user_and_client_id_from_token(request: Request) -> tuple:
    """
    Extrai user_id e client_id do token JWT verificando o cookie.
    Suporta renovação automática de token para trial users com token expirado.
    Retorna também headers para setar novo cookie se token foi renovado.

    Returns:
        tuple: (user_id, client_id, response_headers_dict)

    Raises:
        HTTPException: Se sem token, expirado e sem refresh token, ou outro erro
    """
    try:
        # DEV MODE: Verificar se o dev_bypass foi ativado pelo middleware
        if request.scope.get("dev_bypass_enabled"):
            dev_user_id = request.scope.get("dev_user_id", "1")
            dev_client_id = request.scope.get("dev_client_id", "1")
            debug(
                f"[UPLOAD] DEV BYPASS: Usando user_id={dev_user_id}, client_id={dev_client_id}"
            )
            return (dev_user_id, dev_client_id, None)

        auth_service = get_auth_service()

        # Verificar se tem access_token
        access_token = request.cookies.get("access_token")

        if not access_token:
            # Sem token - retornar erro específico
            debug("[UPLOAD] Sem access_token no cookie")
            raise HTTPException(status_code=401, detail="no auth cookie")

        # Verificar se token é válido
        payload = auth_service.verify_token(access_token)

        if payload:
            # Token válido
            user_id = payload.get("user_id")
            client_id = payload.get("client_id")
            if not user_id or not client_id:
                raise HTTPException(status_code=401, detail="invalid token payload")
            debug(f"[UPLOAD] Token válido para user {user_id}")
            return (user_id, client_id, None)

        # Token expirado - tentar renovar com refresh_token
        debug("[UPLOAD] Token expirado, tentando renovar...")
        refresh_token = request.cookies.get("refresh_token")

        if not refresh_token:
            # Sem refresh token também - pedir nova autenticação
            debug("[UPLOAD] Sem refresh_token")
            raise HTTPException(status_code=401, detail="token expired")

        # Validar refresh_token
        refresh_payload = auth_service.verify_token(refresh_token)

        if not refresh_payload:
            # Refresh token também expirou
            debug("[UPLOAD] Refresh token expirado")
            raise HTTPException(status_code=401, detail="token expired")

        user_id = refresh_payload.get("user_id")
        client_id = refresh_payload.get("client_id")

        if not user_id or not client_id:
            raise HTTPException(status_code=401, detail="invalid refresh token payload")

        # Verificar se user é trial ANTES de renovar
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
                f"[UPLOAD] User {user_id} não é trial (plan_type={plan_type}), negando renovação"
            )
            raise HTTPException(status_code=401, detail="token expired")

        # Renovar token para usuário trial
        debug(f"[UPLOAD] Renovando token para usuário trial {user_id}")

        user_data = {
            "user_id": user_id,
            "email": refresh_payload.get("email"),
            "full_name": refresh_payload.get("full_name"),
            "role": refresh_payload.get("role", "member"),
            "client_id": client_id,
        }

        new_access_token = auth_service.generate_access_token(user_data)

        # Retornar user_id, client_id e headers com novo cookie
        response_headers = {
            "set-cookie": f"access_token={new_access_token}; HttpOnly; Secure; SameSite=Lax; Max-Age={86400}"
        }

        info(f"[UPLOAD] Token renovado para usuário trial {user_id}")
        return (user_id, client_id, response_headers)

    except HTTPException:
        raise
    except Exception as e:
        error(f"[UPLOAD] Erro ao extrair/renovar token: {e}")
        raise HTTPException(status_code=401, detail="auth error")


# ========================================================================
# HELPER FUNCTIONS
# ========================================================================


def _create_session(client_id: int, user_id: Optional[int] = None) -> str:
    """
    Cria uma nova session no DB para isolamento de uploads temporários.

    Args:
        client_id: ID do cliente
        user_id: ID do usuário (opcional)

    Returns:
        session_id criado
    """
    session_id = f"session_{uuid.uuid4().hex[:16]}"
    expires_at = (datetime.utcnow() + timedelta(hours=24)).isoformat()

    query = """
    INSERT INTO sessions (session_id, client_id, user_id, expires_at)
    VALUES (:session_id, :client_id, :user_id, :expires_at)
    """

    try:
        DatabaseManager.execute_query(
            query,
            {
                "session_id": session_id,
                "client_id": client_id,
                "user_id": user_id,
                "expires_at": expires_at,
            },
        )
        debug(f"[UPLOAD] Session criada: {session_id}")
        return session_id
    except Exception as e:
        error(f"[UPLOAD] Erro ao criar session: {e}")
        raise


def _compute_file_hash(content: bytes) -> str:
    """Calcula hash SHA256 do arquivo"""
    return hashlib.sha256(content).hexdigest()


def _ensure_upload_path(
    client_id: int,
    path_type: str,
    chat_id: Optional[str] = None,
    message_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Path:
    """
    Cria e retorna caminho de upload conforme tipo.

    Args:
        client_id: ID do cliente
        path_type: 'temp' (TempFolder) ou 'chat' (ChatId/MessageId)
        chat_id: ID do chat (obrigatório se path_type='chat')
        message_id: ID da mensagem (obrigatório se path_type='chat')
        session_id: ID da session (obrigatório se path_type='temp')

    Returns:
        Path completo
    """
    base_path = StorageManager.LOCAL_STORAGE_BASE

    if path_type == "temp":
        if not session_id:
            raise ValueError("session_id obrigatório para uploads temporários")
        upload_path = base_path / f"client_{client_id}" / "TempFolder" / session_id
    elif path_type == "chat":
        if not (chat_id and message_id):
            raise ValueError("chat_id e message_id obrigatórios para uploads de chat")
        upload_path = base_path / f"client_{client_id}" / chat_id / message_id
    else:
        raise ValueError(f"path_type desconhecido: {path_type}")

    StorageManager.ensure_path_exists(upload_path)
    return upload_path


# ========================================================================
# ROUTES
# ========================================================================


@upload_router.post("/", status_code=201)
async def upload_file_index(
    file: UploadFile = File(...),
    metadata: Optional[str] = Form(None),
    request: Request = None,
) -> UploadResponse:
    """
    Upload temporário (Index page) - salva em Storage/ClientId/TempFolder/
    Frontend gerencia quais attachments foram uploadados e quando confirmar a mensagem,
    backend move os arquivos para a pasta correta do chat/mensagem.

    Args:
        file: Arquivo a fazer upload
        request: Requisição HTTP (para extrair token)

    Returns:
        Dados do attachment criado
    """
    try:
        user_id, client_id, token_headers = get_user_and_client_id_from_token(request)

        # Validar arquivo
        if not file.filename:
            raise HTTPException(status_code=400, detail="Nome do arquivo obrigatório")

        allowed_types = {
            "image": ["image/jpeg", "image/png", "image/gif", "image/webp"],
            "document": [
                "application/pdf",
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.ms-excel",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/vnd.ms-powerpoint",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "text/plain",
                "text/csv",
                "text/markdown",
                "text/x-markdown",
                "text/html",
            ],
            "audio": ["audio/mp4", "audio/ogg"],
            "video": ["video/mp4", "video/quicktime"],
        }

        flat_types = [t for types in allowed_types.values() for t in types]
        if file.content_type not in flat_types:
            raise HTTPException(
                status_code=400,
                detail=f"Tipo de arquivo não permitido: {file.content_type}",
            )

        # Ler conteúdo
        content = await file.read()
        if len(content) > 100 * 1024 * 1024:  # 100MB
            raise HTTPException(
                status_code=413, detail="Arquivo muito grande (máx 100MB)"
            )

        # Debug: Printar campos recebidos
        debug(f"[POST /api/upload/] Campos recebidos:")
        debug(f"  - file.filename: {file.filename}")
        debug(f"  - file.content_type: {file.content_type}")
        debug(f"  - file.size: {file.size}")
        debug(f"  - metadata: {metadata}")

        # Parsear metadata se fornecido
        metadata_dict = {}
        if metadata:
            try:
                metadata_dict = json.loads(metadata)
                debug(f"  - metadata parsed: {metadata_dict}")
            except json.JSONDecodeError as e:
                warning(f"[POST /api/upload/] Erro ao parsear metadata JSON: {e}")

        # Preparar arquivo
        attachment_id = f"attach_{uuid.uuid4().hex[:12]}"
        file_ext = Path(file.filename).suffix or ""
        original_filename = file.filename or "arquivo"
        safe_filename = f"{attachment_id}{file_ext}"

        # Salvar arquivo temporário (sem session, direto em TempFolder)
        base_path = StorageManager.LOCAL_STORAGE_BASE
        upload_path = base_path / f"client_{client_id}" / "TempFolder"
        StorageManager.ensure_path_exists(upload_path)
        temp_file_path = upload_path / safe_filename

        try:
            with open(temp_file_path, "wb") as f:
                f.write(content)
            rel_path = StorageManager.get_relative_path(temp_file_path)
            debug(f"[POST /api/upload/] Arquivo temporário salvo: {rel_path}")
        except Exception as e:
            error(f"[POST /api/upload/] Erro ao salvar arquivo: {e}")
            raise HTTPException(status_code=500, detail="Erro ao salvar arquivo")

        # Processar com MediaCompressor se for imagem
        file_type = file.content_type.split("/")[0]  # 'image', 'video', 'document'
        final_file_path = temp_file_path
        file_size = len(content)

        if file_type == "image":
            try:
                loop = asyncio.get_event_loop()
                compress_result = await loop.run_in_executor(
                    None,
                    MediaCompressor.process_upload,
                    temp_file_path,
                    client_id,
                    True,
                )
                if compress_result["storage"]:
                    final_file_path = compress_result["storage"]
                    file_size = final_file_path.stat().st_size
                    debug(
                        f"[POST /api/upload/] Imagem comprimida e convertida para WebP"
                    )
                else:
                    warning(
                        f"[POST /api/upload/] Falha ao comprimir imagem, usando original"
                    )
            except Exception as e:
                warning(
                    f"[POST /api/upload/] Erro ao processar mídia: {e}, usando original"
                )

        # Calcular hash
        file_hash = _compute_file_hash(final_file_path.read_bytes())

        # Inserir no DB (arquivo salvo em TempFolder)
        # Usar caminho relativo (a partir de Data/Database/)
        relative_path = f"client_{client_id}/TempFolder/{final_file_path.name}"
        file_extension = file_ext.lstrip(".") if file_ext else ""

        query = """
        INSERT INTO attachments
        (attachment_id, user_id, file_name, extension, is_temp)
        VALUES (:attachment_id, :user_id, :file_name, :extension, 1)
        """

        try:
            DatabaseManager.execute_query(
                query,
                {
                    "attachment_id": attachment_id,
                    "user_id": user_id,
                    "file_name": original_filename,
                    "extension": file_extension,
                },
            )
        except Exception as e:
            error(f"[POST /api/upload/] Erro ao registrar no DB: {e}")
            raise HTTPException(status_code=500, detail="Erro ao registrar arquivo")

        info(f"[POST /api/upload/] Upload temporário salvo: {attachment_id}")

        response_data = UploadResponse(
            attachment_id=attachment_id,
            file_name=original_filename,
            extension=file_extension,
            file_size=file_size,
            storage_path=relative_path,
            is_temp=True,
            uploaded_at=datetime.utcnow().isoformat(),
        )

        # Se token foi renovado, incluir na resposta
        if token_headers:
            from fastapi.responses import JSONResponse

            response = JSONResponse(status_code=201, content=response_data.model_dump())
            for header_name, header_value in token_headers.items():
                response.headers[header_name] = header_value
            return response

        return response_data

    except HTTPException:
        raise
    except Exception as e:
        error(f"[POST /api/upload/] Erro: {e}")
        import traceback

        error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Erro ao fazer upload")


@upload_router.post("/{chat_id}", status_code=201)
async def upload_file_chat(
    chat_id: str,
    file: UploadFile = File(...),
    metadata: Optional[str] = Form(None),
    request: Request = None,
) -> UploadResponse:
    """
    Upload em chat - salva em Storage/ClientId/TempFolder/
    Frontend gerencia quais attachments pertencem a qual mensagem.
    Quando a mensagem é enviada, o backend move os arquivos para a pasta correta.

    Args:
        chat_id: ID do chat (para contexto, mas arquivo salvo em TempFolder)
        file: Arquivo a fazer upload
        request: Requisição HTTP (para extrair token)

    Returns:
        Dados do attachment criado
    """
    try:
        user_id, client_id, token_headers = get_user_and_client_id_from_token(request)

        # Validar arquivo
        if not file.filename:
            raise HTTPException(status_code=400, detail="Nome do arquivo obrigatório")

        allowed_types = {
            "image": ["image/jpeg", "image/png", "image/gif", "image/webp"],
            "document": [
                "application/pdf",
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.ms-excel",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/vnd.ms-powerpoint",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "text/plain",
                "text/csv",
                "text/markdown",
                "text/x-markdown",
                "text/html",
            ],
            "audio": ["audio/mp4", "audio/ogg"],
            "video": ["video/mp4", "video/quicktime"],
        }

        flat_types = [t for types in allowed_types.values() for t in types]
        if file.content_type not in flat_types:
            raise HTTPException(
                status_code=400,
                detail=f"Tipo de arquivo não permitido: {file.content_type}",
            )

        # Ler conteúdo
        content = await file.read()
        if len(content) > 100 * 1024 * 1024:  # 100MB
            raise HTTPException(
                status_code=413, detail="Arquivo muito grande (máx 100MB)"
            )

        # Debug: Printar campos recebidos
        debug(f"[POST /api/upload/{{chat_id}}] Campos recebidos:")
        debug(f"  - file.filename: {file.filename}")
        debug(f"  - file.content_type: {file.content_type}")
        debug(f"  - file.size: {file.size}")
        debug(f"  - metadata: {metadata}")

        # Parsear metadata se fornecido
        metadata_dict = {}
        if metadata:
            try:
                metadata_dict = json.loads(metadata)
                debug(f"  - metadata parsed: {metadata_dict}")
            except json.JSONDecodeError as e:
                warning(
                    f"[POST /api/upload/{{chat_id}}] Erro ao parsear metadata JSON: {e}"
                )

        # Preparar arquivo
        attachment_id = f"attach_{uuid.uuid4().hex[:12]}"
        file_ext = Path(file.filename).suffix or ""
        original_filename = file.filename or "arquivo"
        safe_filename = f"{attachment_id}{file_ext}"

        # Salvar arquivo temporário (sem criar estrutura de chat, direto em TempFolder)
        base_path = StorageManager.LOCAL_STORAGE_BASE
        upload_path = base_path / f"client_{client_id}" / "TempFolder"
        StorageManager.ensure_path_exists(upload_path)
        temp_file_path = upload_path / safe_filename

        try:
            with open(temp_file_path, "wb") as f:
                f.write(content)
            rel_path = StorageManager.get_relative_path(temp_file_path)
            debug(
                f"[POST /api/upload/{{chat_id}}] Arquivo temporário salvo: {rel_path}"
            )
        except Exception as e:
            error(f"[POST /api/upload/{{chat_id}}] Erro ao salvar arquivo: {e}")
            raise HTTPException(status_code=500, detail="Erro ao salvar arquivo")

        # Processar com MediaCompressor se for imagem
        file_type = file.content_type.split("/")[0]  # 'image', 'video', 'document'
        final_file_path = temp_file_path
        file_size = len(content)

        if file_type == "image":
            try:
                loop = asyncio.get_event_loop()
                compress_result = await loop.run_in_executor(
                    None,
                    MediaCompressor.process_upload,
                    temp_file_path,
                    client_id,
                    True,
                )
                if compress_result["storage"]:
                    final_file_path = compress_result["storage"]
                    file_size = final_file_path.stat().st_size
                    debug(
                        f"[POST /api/upload/{{chat_id}}] Imagem comprimida e convertida para WebP"
                    )
                else:
                    warning(
                        f"[POST /api/upload/{{chat_id}}] Falha ao comprimir imagem, usando original"
                    )
            except Exception as e:
                warning(
                    f"[POST /api/upload/{{chat_id}}] Erro ao processar mídia: {e}, usando original"
                )

        # Calcular hash
        file_hash = _compute_file_hash(final_file_path.read_bytes())

        # Inserir no DB (arquivo salvo em TempFolder, será vinculado à mensagem depois)
        # Usar caminho relativo (a partir de Data/Database/)
        relative_path = f"client_{client_id}/TempFolder/{final_file_path.name}"
        file_extension = file_ext.lstrip(".") if file_ext else ""

        query = """
        INSERT INTO attachments
        (attachment_id, user_id, file_name, extension, is_temp)
        VALUES (:attachment_id, :user_id, :file_name, :extension, 1)
        """

        try:
            DatabaseManager.execute_query(
                query,
                {
                    "attachment_id": attachment_id,
                    "user_id": user_id,
                    "file_name": original_filename,
                    "extension": file_extension,
                },
            )
        except Exception as e:
            error(f"[POST /api/upload/{{chat_id}}] Erro ao registrar no DB: {e}")
            raise HTTPException(status_code=500, detail="Erro ao registrar arquivo")

        info(f"[POST /api/upload/{{chat_id}}] Upload em chat salvo: {attachment_id}")

        response_data = UploadResponse(
            attachment_id=attachment_id,
            file_name=original_filename,
            extension=file_extension,
            file_size=file_size,
            storage_path=relative_path,
            is_temp=True,
            uploaded_at=datetime.utcnow().isoformat(),
        )

        # Se token foi renovado, incluir na resposta
        if token_headers:
            from fastapi.responses import JSONResponse

            response = JSONResponse(status_code=201, content=response_data.model_dump())
            for header_name, header_value in token_headers.items():
                response.headers[header_name] = header_value
            return response

        return response_data

    except HTTPException:
        raise
    except Exception as e:
        error(f"[POST /api/upload/{{chat_id}}] Erro: {e}")
        import traceback

        error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Erro ao fazer upload")


@upload_router.delete("/{attachment_id}", status_code=200)
async def delete_attachment(attachment_id: str, request: Request = None):
    """
    Deleta um attachment (temporário ou persistente).
    Apenas o user que fez upload pode deletar.

    Args:
        attachment_id: ID do attachment
        request: Requisição HTTP (para extrair token)

    Returns:
        Confirmação da deleção
    """
    try:
        user_id, client_id, _ = get_user_and_client_id_from_token(request)

        # Buscar attachment (verificar se pertence ao user)
        query = """
        SELECT * FROM attachments WHERE attachment_id = :attachment_id AND user_id = :user_id
        """

        attachment = DatabaseManager.fetch_one(
            query, {"attachment_id": attachment_id, "user_id": user_id}
        )

        if not attachment:
            raise HTTPException(
                status_code=404,
                detail="Arquivo não encontrado ou você não tem permissão",
            )

        # Tentar deletar arquivo físico do caminho esperado (TempFolder)
        base_path = StorageManager.LOCAL_STORAGE_BASE
        extension = attachment.get("extension", "")
        safe_filename = f"{attachment_id}{f'.{extension}' if extension else ''}"
        temp_file_path = (
            base_path / f"client_{client_id}" / "TempFolder" / safe_filename
        )

        if temp_file_path.exists():
            try:
                temp_file_path.unlink()
                debug(
                    f"[DELETE /api/upload/{{attachment_id}}] Arquivo deletado: {temp_file_path}"
                )
            except Exception as e:
                warning(
                    f"[DELETE /api/upload/{{attachment_id}}] Erro ao deletar arquivo: {e}"
                )

        # Deletar registro do DB
        delete_query = """
        DELETE FROM attachments WHERE attachment_id = :attachment_id AND user_id = :user_id
        """

        try:
            DatabaseManager.execute_query(
                delete_query, {"attachment_id": attachment_id, "user_id": user_id}
            )
        except Exception as e:
            error(f"[DELETE /api/upload/{{attachment_id}}] Erro ao deletar do DB: {e}")
            raise HTTPException(status_code=500, detail="Erro ao deletar arquivo")

        info(
            f"[DELETE /api/upload/{{attachment_id}}] Arquivo deletado: {attachment_id}"
        )

        return {
            "status": "deleted",
            "attachment_id": attachment_id,
            "message": "Arquivo deletado com sucesso",
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[DELETE /api/upload/{{attachment_id}}] Erro: {e}")
        raise HTTPException(status_code=500, detail="Erro ao deletar arquivo")
