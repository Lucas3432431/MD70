"""
Rotas para gerenciamento de tarefas e eventos.
"""

import uuid
from typing import Optional
from loguru import logger
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime

from App.Features.Database import DatabaseManager
from App.Features.Models import (
    Task,
    SubTask,
    TaskStatus,
    TaskEvent,
    TaskEventType,
    EventSource,
)


# ============= Models =============
class TaskRequest(BaseModel):
    description: str


class TaskResponseRequest(BaseModel):
    message: str


# ============= Router =============
router = APIRouter(prefix="/tasks", tags=["tasks"])

# ============= Dependencies =============
from fastapi import Request


def get_db_manager() -> DatabaseManager:
    """Retorna o DatabaseManager."""
    # Será injetado pelo server.py
    from ..server import db_manager

    return db_manager


async def get_current_user(request: Request):
    """Obtém o usuário autenticado da sessão."""
    from .Auth import get_current_user as auth_get_current_user

    return await auth_get_current_user(request)


# ============= Endpoints =============
@router.post("", status_code=201)
async def create_task(req: TaskRequest, user: str = Depends(get_current_user)):
    """Cria uma nova tarefa."""
    db_manager = get_db_manager()
    session = db_manager.get_session()

    task = Task(
        id=str(uuid.uuid4()),
        type="generic",
        description=req.description,
        status=TaskStatus.PENDING,
        created_by=user,
    )
    db_manager.save_task(session, task)

    db_manager.save_task_event(
        session,
        TaskEvent(
            task_id=task.id,
            type=TaskEventType.STATUS_CHANGE,
            source=EventSource.SYSTEM,
            message=f"Task created with status: PENDING",
        ),
    )

    logger.info(f"Task criada por '{user}': {task.id}")
    return {"id": task.id, "description": task.description, "status": task.status.value}


@router.get("")
async def list_tasks(user: str = Depends(get_current_user)):
    """Lista todas as tarefas."""
    db_manager = get_db_manager()
    session = db_manager.get_session()
    tasks = session.query(Task).order_by(Task.created_at.desc()).all()
    return {
        "tasks": [
            {"id": t.id, "description": t.description, "status": t.status.value}
            for t in tasks
        ]
    }


@router.get("/{task_id}/events")
async def get_task_events(task_id: str, user: str = Depends(get_current_user)):
    """Retorna todos os eventos (mensagens, aprovações) para o chat de uma tarefa."""
    db_manager = get_db_manager()
    session = db_manager.get_session()
    events = db_manager.get_task_events(session, task_id)

    event_list = []
    for event in events:
        e = {
            "id": event.id,
            "timestamp": event.timestamp.isoformat(),
            "type": event.type.value,
            "source": event.source.value,
            "message": event.message,
        }
        if event.type == TaskEventType.APPROVAL_REQUEST and event.payload:
            from ..models import Approval

            e["approval_id"] = event.payload.get("approval_id")
            e["status"] = (
                db_manager.get_session()
                .query(Approval)
                .get(e["approval_id"])
                .status.value
            )
        event_list.append(e)

    return {"events": event_list}


@router.post("/{task_id}/respond")
async def post_task_message(
    task_id: str, req: TaskResponseRequest, user: str = Depends(get_current_user)
):
    """Permite que um usuário envie uma mensagem para o chat da tarefa."""
    db_manager = get_db_manager()
    session = db_manager.get_session()
    event = TaskEvent(
        task_id=task_id,
        type=TaskEventType.MESSAGE,
        source=EventSource.USER,
        message=req.message,
    )
    db_manager.save_task_event(session, event)
    return {"status": "message received"}
