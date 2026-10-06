"""
Rotas de Skills Personalizadas — /api/skills
GET/POST/PATCH/DELETE de custom_skills.
"""

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

from App.Core.Logs import error as log_error
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Services.Skills.SkillsService import SkillsService
from App.Core.Services.Auth.RequestAuth import get_payload_from_request

skills_router = APIRouter(tags=["Skills"], prefix="/api/skills")

_service = SkillsService()


def _get_user(request: Request) -> dict:
    return get_payload_from_request(request)


class SkillCreate(BaseModel):
    name: str
    description: Optional[str] = None
    content: str


class SkillUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    is_active: Optional[bool] = None


@skills_router.get("")
async def list_skills(request: Request):
    user = _get_user(request)
    try:
        skills = DatabaseManager.execute_transaction(
            lambda session: _service.list_skills(session, user["user_id"])
        )
        return {"skills": skills}
    except Exception as e:
        log_error(f"[SKILLS] list_skills: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@skills_router.post("")
async def create_skill(request: Request, body: SkillCreate):
    user = _get_user(request)
    try:
        skill = DatabaseManager.execute_transaction(
            lambda session: _service.create_skill(session, user["user_id"], body.dict())
        )
        return {"skill": skill}
    except Exception as e:
        log_error(f"[SKILLS] create_skill: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@skills_router.patch("/{skill_id}")
async def update_skill(skill_id: str, request: Request, body: SkillUpdate):
    user = _get_user(request)
    try:
        data = body.dict(exclude_none=True)
        if "is_active" in data:
            data["is_active"] = 1 if data["is_active"] else 0
        skill = DatabaseManager.execute_transaction(
            lambda session: _service.update_skill(
                session, skill_id, user["user_id"], data
            )
        )
        if not skill:
            raise HTTPException(status_code=404, detail="Skill não encontrada")
        return {"skill": skill}
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"[SKILLS] update_skill: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@skills_router.delete("/{skill_id}")
async def delete_skill(skill_id: str, request: Request):
    user = _get_user(request)
    try:
        ok = DatabaseManager.execute_transaction(
            lambda session: _service.delete_skill(session, skill_id, user["user_id"])
        )
        if not ok:
            raise HTTPException(status_code=404, detail="Skill não encontrada")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"[SKILLS] delete_skill: {e}")
        raise HTTPException(status_code=500, detail=str(e))
