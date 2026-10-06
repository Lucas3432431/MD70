"""
Rotas de Feedback - FastAPI Routes
Apenas rotas e validações HTTP, lógica de negócio delegada para DBManager
"""

import uuid
import json
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

from App.Core.Logs import debug, info, warning, error
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Services.AdminEmail import admin_email_service
from App.Core.Services.AdminEmail.AdminEmailService import NOREPLY_FROM
from App.Core.Services.TelegramAlert import telegram_alert_service

# ========================================================================
# MODELS
# ========================================================================


class SendFeedbackRequest(BaseModel):
    """Requisição para enviar feedback geral"""

    content: str = Field(
        ..., description="Conteúdo do feedback do usuário", min_length=1
    )


class SolutionResearchAnswerRequest(BaseModel):
    """Requisição para enviar resposta de pesquisa de solução"""

    question: str = Field(..., description="A pergunta feita ao usuário")
    options: Optional[List[str]] = Field(
        None, description="Opções disponíveis (opcional)"
    )
    answer: str = Field(..., description="A resposta escolhida ou digitada")
    answer_type: str = Field(
        ..., description="Tipo da resposta (classification, objective, discussion)"
    )


# ========================================================================
# ROUTER
# ========================================================================

feedback_router = APIRouter(tags=["Feedback"], prefix="/api")


# ========================================================================
# HELPERS
# ========================================================================


def _alert_feedback(
    user_id: str, content: str, feedback_id: str, source: str = "app"
) -> None:
    subject = f"💬 Feedback recebido ({source})"
    body = (
        f"Novo feedback de usuário:\n\n"
        f"User: {user_id}\n"
        f"ID: {feedback_id}\n\n"
        f"---\n{content}\n---"
    )
    try:
        telegram_alert_service.send_critical_alert(subject, body)
    except Exception as e:
        error(f"[FEEDBACK] Erro ao enviar alerta Telegram: {e}")
    try:
        admin_email_service.send_critical_alert(subject, body)
    except Exception as e:
        error(f"[FEEDBACK] Erro ao enviar alerta e-mail: {e}")


# ========================================================================
# DEPENDENCY - Extrair user_id do token
# ========================================================================


def get_user_id_from_token(request: Request) -> str:
    try:
        from App.Core.Services.Auth.RequestAuth import get_user_id_from_request

        return get_user_id_from_request(request)
    except HTTPException:
        raise
    except Exception as e:
        error(f"[FEEDBACK] Erro ao extrair user_id: {e}")
        raise HTTPException(status_code=401, detail="Autenticação inválida")


# ========================================================================
# ROUTES
# ========================================================================


@feedback_router.post("/feedback", status_code=201)
async def send_feedback(request_data: SendFeedbackRequest, request: Request):
    """
    Enviar feedback geral do usuário.

    Args:
        request_data: Conteúdo do feedback
        request: Requisição HTTP (para extrair token)

    Returns:
        JSON com status da operação
    """
    try:
        user_id = get_user_id_from_token(request)

        debug(f"[POST /api/feedback] Recebendo feedback")
        debug(f"  - user_id: {user_id}")
        debug(f"  - content_length: {len(request_data.content)}")

        # Validar conteúdo
        if not request_data.content or not request_data.content.strip():
            raise HTTPException(status_code=400, detail="Feedback não pode estar vazio")

        # Gerar IDs
        feedback_id = str(uuid.uuid4())

        # Inserir feedback no banco de dados
        success = DatabaseManager.create_feedback(
            feedback_id=feedback_id,
            user_id=user_id,
            content=request_data.content.strip(),
        )

        if not success:
            raise HTTPException(status_code=500, detail="Erro ao registrar feedback")

        info(
            f"[POST /api/feedback] Feedback registrado com sucesso - feedback_id: {feedback_id}"
        )

        _alert_feedback(
            user_id=user_id,
            content=request_data.content.strip(),
            feedback_id=feedback_id,
        )

        return {
            "status": "success",
            "feedback_id": feedback_id,
            "message": "Feedback registrado com sucesso",
            "timestamp": datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[POST /api/feedback] Erro: {e}")
        raise HTTPException(status_code=500, detail="Erro ao processar feedback")


@feedback_router.post("/solution-research/answer", status_code=201)
async def send_research_answer(
    request_data: SolutionResearchAnswerRequest, request: Request
):
    """
    Registrar resposta de pesquisa de satisfação/solução.
    """
    try:
        user_id = get_user_id_from_token(request)

        answer_id = str(uuid.uuid4())

        options_json = (
            json.dumps(request_data.options) if request_data.options else None
        )

        success = DatabaseManager.create_research_answer(
            answer_id=answer_id,
            user_id=user_id,
            question=request_data.question,
            options=options_json,
            answer=request_data.answer,
            answer_type=request_data.answer_type,
        )

        if not success:
            raise HTTPException(status_code=500, detail="Erro ao registrar resposta")

        info(
            f"[POST /api/solution-research/answer] Resposta registrada com sucesso - answer_id: {answer_id}"
        )

        return {
            "status": "success",
            "answer_id": answer_id,
            "message": "Resposta registrada com sucesso",
            "timestamp": datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[POST /api/solution-research/answer] Erro: {e}")
        raise HTTPException(status_code=500, detail="Erro ao processar resposta")
