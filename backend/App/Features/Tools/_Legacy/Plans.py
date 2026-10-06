"""
Rotas para gerenciamento de planos de execução salvos.
Permite visualizar, listar e baixar planos aprovados.
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import json
from datetime import datetime
from loguru import logger

# Dependencies
from fastapi import Request


async def get_current_user(request: Request):
    """Obtém o usuário autenticado da sessão."""
    from .Auth import get_current_user as auth_get_current_user

    return await auth_get_current_user(request)


# Models
class PlanApproval(BaseModel):
    approved: bool
    notes: Optional[str] = None


router = APIRouter(prefix="/api/plans", tags=["plans"])

# Diretório onde os planos são salvos
PLANS_DIR = Path(__file__).parent.parent.parent / "data" / "plans"


@router.get("/")
async def list_plans() -> List[Dict[str, Any]]:
    """
    Lista todos os planos salvos.

    Returns:
        Lista de planos com metadados
    """
    if not PLANS_DIR.exists():
        return []

    plans = []
    for plan_file in PLANS_DIR.glob("*_plan.json"):
        try:
            with open(plan_file, "r", encoding="utf-8") as f:
                plan_data = json.load(f)

            plans.append(
                {
                    "task_id": plan_data.get("task_id"),
                    "approved_at": plan_data.get("approved_at"),
                    "status": plan_data.get("status"),
                    "file_name": plan_file.name,
                    "file_path": str(plan_file),
                    "subtasks_count": len(
                        plan_data.get("plan", {}).get("subtasks", [])
                    ),
                    "plan_summary": plan_data.get("plan", {}).get(
                        "plan_summary", "N/A"
                    ),
                }
            )
        except Exception as e:
            logger.error(f"Erro ao ler plano {plan_file}: {e}")
            continue

    # Ordena por data de aprovação (mais recente primeiro)
    plans.sort(key=lambda x: x["approved_at"], reverse=True)

    return plans


@router.get("/{task_id}/status")
async def get_plan_status(task_id: str) -> Dict[str, Any]:
    """
    Retorna apenas o status de aprovação de um plano.

    Args:
        task_id: ID da task

    Returns:
        Status de aprovação do plano
    """
    plan_file = PLANS_DIR / f"{task_id}_plan.json"

    if not plan_file.exists():
        raise HTTPException(status_code=404, detail=f"Plano não encontrado: {task_id}")

    try:
        with open(plan_file, "r", encoding="utf-8") as f:
            plan_data = json.load(f)

        return {
            "task_id": task_id,
            "approval_status": plan_data.get("approval_status", "pending"),
            "approval_user": plan_data.get("approval_user"),
            "approval_timestamp": plan_data.get("approval_timestamp"),
            "approval_notes": plan_data.get("approval_notes"),
        }
    except Exception as e:
        logger.error(f"Erro ao ler status do plano {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao ler status: {str(e)}")


@router.get("/{task_id}")
async def get_plan(task_id: str) -> Dict[str, Any]:
    """
    Retorna um plano específico pelo task_id.

    Args:
        task_id: ID da task

    Returns:
        Dados completos do plano
    """
    plan_file = PLANS_DIR / f"{task_id}_plan.json"

    if not plan_file.exists():
        raise HTTPException(status_code=404, detail=f"Plano não encontrado: {task_id}")

    try:
        with open(plan_file, "r", encoding="utf-8") as f:
            plan_data = json.load(f)

        return plan_data
    except Exception as e:
        logger.error(f"Erro ao ler plano {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao ler plano: {str(e)}")


@router.get("/{task_id}/download")
async def download_plan(task_id: str):
    """
    Baixa um plano específico como arquivo JSON.

    Args:
        task_id: ID da task

    Returns:
        Arquivo JSON do plano
    """
    plan_file = PLANS_DIR / f"{task_id}_plan.json"

    if not plan_file.exists():
        raise HTTPException(status_code=404, detail=f"Plano não encontrado: {task_id}")

    return FileResponse(
        path=str(plan_file),
        media_type="application/json",
        filename=f"{task_id}_plan.json",
    )


@router.delete("/{task_id}")
async def delete_plan(task_id: str) -> Dict[str, str]:
    """
    Deleta um plano específico.

    Args:
        task_id: ID da task

    Returns:
        Mensagem de confirmação
    """
    plan_file = PLANS_DIR / f"{task_id}_plan.json"

    if not plan_file.exists():
        raise HTTPException(status_code=404, detail=f"Plano não encontrado: {task_id}")

    try:
        plan_file.unlink()
        logger.info(f"Plano deletado: {task_id}")
        return {"message": f"Plano {task_id} deletado com sucesso"}
    except Exception as e:
        logger.error(f"Erro ao deletar plano {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao deletar plano: {str(e)}")


@router.get("/{task_id}/subtasks")
async def get_plan_subtasks(task_id: str) -> List[Dict[str, Any]]:
    """
    Retorna apenas as subtarefas de um plano.

    Args:
        task_id: ID da task

    Returns:
        Lista de subtarefas do plano
    """
    plan_file = PLANS_DIR / f"{task_id}_plan.json"

    if not plan_file.exists():
        raise HTTPException(status_code=404, detail=f"Plano não encontrado: {task_id}")

    try:
        with open(plan_file, "r", encoding="utf-8") as f:
            plan_data = json.load(f)

        return plan_data.get("plan", {}).get("subtasks", [])
    except Exception as e:
        logger.error(f"Erro ao ler subtarefas do plano {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao ler subtarefas: {str(e)}")


@router.post("/{task_id}/approve")
async def approve_plan(
    task_id: str, approval: PlanApproval, user: str = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Aprova ou rejeita um plano.

    Args:
        task_id: ID da task
        approval: Dados de aprovação (approved=True/False, notes)

    Returns:
        Status da aprovação e próximos passos
    """
    plan_file = PLANS_DIR / f"{task_id}_plan.json"

    if not plan_file.exists():
        raise HTTPException(status_code=404, detail=f"Plano não encontrado: {task_id}")

    try:
        with open(plan_file, "r", encoding="utf-8") as f:
            plan_data = json.load(f)

        # Verificar se já foi aprovado/rejeitado
        if plan_data.get("approval_status") in ["approved", "rejected"]:
            raise HTTPException(
                status_code=400,
                detail=f"Plano já foi {plan_data.get('approval_status')}. Não pode ser alterado.",
            )

        # Atualizar status
        plan_data["approval_status"] = "pending" if approval.approved else "rejected"
        plan_data["approval_user"] = user
        plan_data["approval_timestamp"] = datetime.utcnow().isoformat()
        plan_data["approval_notes"] = approval.notes

        # Salvar atualização
        with open(plan_file, "w", encoding="utf-8") as f:
            json.dump(plan_data, f, indent=2, ensure_ascii=False)

        logger.info(
            f"📋 Plano {task_id} {'aprovado' if approval.approved else 'rejeitado'} por {user}"
        )

        # Se aprovado, adicionar subtarefas à fila
        if approval.approved:
            from ..orchestrator import CustomOrchestrator
            from ..server import orchestrator

            # Adicionar subtarefas à fila
            orchestrator.queue_subtasks(task_id, plan_data["plan"])

            return {
                "status": "approved",
                "message": "Plano aprovado! Subtarefas adicionadas à fila de execução.",
                "task_id": task_id,
                "subtasks_count": len(plan_data["plan"].get("subtasks", [])),
                "queue_info": {
                    "pending_tasks": orchestrator.task_queue.get_pending_count()
                },
            }
        else:
            return {
                "status": "rejected",
                "message": "Plano rejeitado.",
                "task_id": task_id,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao processar aprovação do plano {task_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Erro ao processar aprovação: {str(e)}"
        )
