"""
Gerenciamento de senioridade e fluxos de aprovação condicionais.
"""

from typing import Dict, Optional, Tuple
from enum import Enum
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from App.Features.Tools.Tasks.Plan import RiskLevel


class SeniorityLevel(str, Enum):
    """Níveis de senioridade de agentes."""

    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"


class SeniorityManager:
    """Gerencia fluxos de aprovação baseados em senioridade."""

    @staticmethod
    def requires_approval(
        agent_seniority: str, task_risk: RiskLevel, task_story_points: int
    ) -> Tuple[bool, str]:
        """
        Determina se uma tarefa requer aprovação.

        Returns:
            (requires_approval, approver_type)
            approver_type: "orchestrator", "security_officer", "both", "none"
        """
        try:
            seniority = SeniorityLevel(agent_seniority)
        except ValueError:
            seniority = SeniorityLevel.MID

        # SENIOR: Só requer aprovação para HIGH/CRITICAL
        if seniority == SeniorityLevel.SENIOR:
            if task_risk in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
                return True, "security_officer"
            return False, "none"

        # MID: Só ao final de lote (batch de 1-3 SP)
        elif seniority == SeniorityLevel.MID:
            if task_risk in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
                return True, "security_officer"
            # Aprovação apenas ao final do lote (implementado no executor)
            return False, "orchestrator_batch"

        # JUNIOR: Aprovação a cada passo
        elif seniority == SeniorityLevel.JUNIOR:
            if task_risk in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
                return True, "both"  # Orchestrator + SECURITY_OFFICER
            return True, "orchestrator"

        return False, "none"

    @staticmethod
    def get_approver_agent_id(
        approver_type: str, task_creator_id: str, agent_manager=None
    ) -> Optional[str]:
        """
        Obtém ID do agente aprovador.

        Args:
            approver_type: "orchestrator", "security_officer", "both"
            task_creator_id: ID do agente que criou a task
            agent_manager: Instância do AgentManager

        Returns:
            ID do agente aprovador ou None
        """
        if approver_type == "security_officer":
            return "security-officer-001"

        elif approver_type == "orchestrator":
            # Busca o parent_id do agente criador
            if agent_manager:
                agent = agent_manager.get_agent(task_creator_id)
                if agent and hasattr(agent, "parent_id") and agent.parent_id:
                    return agent.parent_id
            return None

        elif approver_type == "both":
            # Dupla aprovação: primeiro orchestrator, depois security_officer
            return "both"  # Sinaliza fluxo de dupla aprovação

        return None
