"""
Rotas de Tool Calls - FastAPI Routes
Endpoint para responder tool calls (quiz, wait, etc)
"""

import json
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from App.Core.Logs import debug, info, warning, error
from App.Core.Services.Common.Dependencies import COMPONENTS
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Features.Job import get_job_manager
from App.Features.Llm.ToolResponseRegistry import register_tool_call_response
from App.Features.Chat.MessageProcessor import MessageProcessor

# ========================================================================
# MODELS
# ========================================================================


class ToolResponseRequest(BaseModel):
    """Requisição para responder um tool call"""

    content: str = Field(
        ...,
        description="Resposta do usuário ao tool call (JSON ou texto)",
        min_length=1,
    )


# ========================================================================
# ROUTER
# ========================================================================

tools_router = APIRouter(tags=["Tools"], prefix="/api")


# ========================================================================
# DEPENDENCY - Extrair client_id do token
# ========================================================================


def get_client_id_from_token(request: Request) -> int:
    from App.Core.Services.Auth.RequestAuth import get_payload_from_request

    return get_payload_from_request(request).get("client_id", "")


# ========================================================================
# ENDPOINTS
# ========================================================================


@tools_router.post("/chat/{chat_id}/message/{message_id}/tool_call", status_code=200)
async def tool_call_response(
    chat_id: str, message_id: str, request_data: ToolResponseRequest, request: Request
):
    """
    Responde um tool call (quiz, wait, etc).
    Valida a existência e salva content como OUTPUT.

    Args:
        chat_id: ID do chat
        message_id: ID da tool_call original
        content: Resposta (JSON ou texto)
    """
    try:
        debug(f"[ToolCall] POST /api/chat/{chat_id}/message/{message_id}/tool_call")

        # Validar content
        content = (request_data.content or "").strip()
        if not content:
            raise HTTPException(status_code=400, detail="Content é obrigatório")

        debug(f"[ToolCall] Content recebido: {len(content)} chars")

        # Obter database manager
        db_manager = COMPONENTS.get("db_manager")
        if not db_manager:
            raise HTTPException(status_code=500, detail="DB manager não configurado")

        session = db_manager.get_session()
        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedChat, IsolatedMessage

            # 1. Validar que o chat existe
            isolated_chat = (
                session.query(IsolatedChat)
                .filter(IsolatedChat.chat_id == chat_id)
                .first()
            )

            if not isolated_chat:
                raise HTTPException(status_code=404, detail=f"Chat não encontrado")

            # 2. Validar que a tool_call existe
            tool_call = (
                session.query(IsolatedMessage)
                .filter(
                    IsolatedMessage.uuid == message_id,
                    IsolatedMessage.isolated_chat_id == isolated_chat.chat_id,
                    IsolatedMessage.type == "tool_call",
                )
                .first()
            )

            if not tool_call:
                raise HTTPException(status_code=404, detail=f"Tool call não encontrada")

            debug(f"[ToolCall] Tool call validada: {message_id}")

            # 3. Obter client_id a partir do chat
            client_id_result = session.execute(
                text("SELECT client_id FROM chats WHERE chat_id = :chat_id"),
                {"chat_id": chat_id},
            ).fetchone()

            if not client_id_result:
                raise HTTPException(
                    status_code=404, detail=f"Chat não encontrado em chats"
                )

            client_id = client_id_result[0]

            # 4. Salvar content como OUTPUT com mesmo UUID
            db_manager.save_isolated_message(
                session=session,
                isolated_chat_id=isolated_chat.chat_id,
                agent_id="user",
                agent="USER",
                role="user",
                content=content,
                message_type="tool_call",
                isolated_message_id=message_id,
                tool_call_id=tool_call.tool_call_id,
                tool_called=tool_call.tool_called,
                tool_call_type="output",
            )

            session.commit()
            debug(f"[ToolCall] OUTPUT salvo: {message_id}")

            # 5. Registrar resposta no LLMClient (cache em memória)
            register_tool_call_response(chat_id, message_id, content)
            debug(f"[ToolCall] Resposta registrada no LLMClient")

            # 6. Retomar processamento via MessageProcessor (novo job)
            message_processor = MessageProcessor()
            resume_result = message_processor.resume_after_tool_call(
                chat_id=chat_id,
                message_id=message_id,
                content=content,
                client_id=client_id,
            )

            if resume_result.success:
                debug(f"[ToolCall] Processamento retomado via MessageProcessor")
                info(f"[ToolCall] Nova resposta gerada pela IA")
            else:
                warning(
                    f"[ToolCall] Erro ao retomar via MessageProcessor: {resume_result.error}"
                )

            info(f"[ToolCall] Sucesso: {message_id}")

            return {"success": True, "message_id": message_id, "chat_id": chat_id}

        finally:
            session.close()

    except HTTPException:
        raise
    except Exception as e:
        error(f"[ToolCall] Erro: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
