"""
Service layer for user custom skills CRUD.
"""

import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session

from App.Core.Crunch.TablesSQL.Models import CustomSkill


class SkillsService:
    def list_skills(self, session: Session, user_id: str) -> List[Dict[str, Any]]:
        skills = (
            session.query(CustomSkill)
            .filter(CustomSkill.user_id == user_id)
            .order_by(CustomSkill.created_at.desc())
            .all()
        )
        return [self._to_dict(s) for s in skills]

    def create_skill(
        self, session: Session, user_id: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        skill = CustomSkill(
            id=str(uuid.uuid4()),
            user_id=user_id,
            name=data["name"],
            description=data.get("description"),
            content=data["content"],
            is_active=1,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(skill)
        session.flush()
        return self._to_dict(skill)

    def update_skill(
        self, session: Session, skill_id: str, user_id: str, data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        skill = (
            session.query(CustomSkill)
            .filter(CustomSkill.id == skill_id, CustomSkill.user_id == user_id)
            .first()
        )
        if not skill:
            return None
        for field in ("name", "description", "content", "is_active"):
            if field in data:
                setattr(skill, field, data[field])
        skill.updated_at = datetime.utcnow()
        session.flush()
        return self._to_dict(skill)

    def delete_skill(self, session: Session, skill_id: str, user_id: str) -> bool:
        skill = (
            session.query(CustomSkill)
            .filter(CustomSkill.id == skill_id, CustomSkill.user_id == user_id)
            .first()
        )
        if not skill:
            return False
        session.delete(skill)
        return True

    def list_active_skills(
        self, session: Session, user_id: str
    ) -> List[Dict[str, Any]]:
        skills = (
            session.query(CustomSkill)
            .filter(CustomSkill.user_id == user_id, CustomSkill.is_active == 1)
            .order_by(CustomSkill.created_at.asc())
            .all()
        )
        return [self._to_dict(s) for s in skills]

    def _to_dict(self, skill: CustomSkill) -> Dict[str, Any]:
        return {
            "id": skill.id,
            "user_id": skill.user_id,
            "name": skill.name,
            "description": skill.description,
            "content": skill.content,
            "is_active": bool(skill.is_active),
            "created_at": skill.created_at.isoformat() if skill.created_at else None,
            "updated_at": skill.updated_at.isoformat() if skill.updated_at else None,
        }
