"""
PlanManager - Gerencia upgrades e transições de planos.
Responsável por identificar tipo de plano e executar transições (ex: trial → free).
"""

from typing import Optional, Dict, Any
from datetime import datetime
from sqlalchemy import text

from App.Core.Logs import debug, info, warning, error
from App.Core.Crunch.PlansSync import PlansSync
from App.Core.Crunch.TablesSQL.Database import database


class PlanManager:
    """Gerencia transições e upgrades de planos."""

    def __init__(self, db_manager=None):
        """
        Inicializa o gerenciador de planos.

        Args:
            db_manager: DatabaseManager com acesso ao banco de dados (não utilizado diretamente)
        """
        self.db = db_manager

    def get_active_plans(self) -> Dict[str, Dict[str, Any]]:
        """
        Obtém todos os planos ativos mapeados por plan_type.

        Returns:
            Dict com estrutura {plan_type: {plan_id, name, ...}}
        """
        try:
            engine = database.engine
            active_plans = PlansSync.get_active_plans(engine)

            # Mapear por plan_type para acesso rápido
            plans_by_type = {}
            for plan in active_plans:
                plan_type = plan.get("plan_type", "").lower()
                if plan_type:
                    plans_by_type[plan_type] = plan

            return plans_by_type

        except Exception as e:
            error(f"[PLAN MANAGER] Erro ao obter planos ativos: {e}")
            return {}

    def get_user_plan_type(self, session, user_id: str) -> Optional[str]:
        """
        Obtém o plan_type atual do usuário.

        Args:
            session: SQLAlchemy session
            user_id: ID do usuário

        Returns:
            plan_type (trial, free, pro, etc) ou None se não encontrado
        """
        try:
            result = session.execute(
                text(
                    """
                    SELECT p.plan_type
                    FROM users u
                    JOIN clients c ON u.client_id = c.client_id
                    JOIN plans p ON c.plan_id = p.plan_id
                    WHERE u.user_id = :user_id
                    LIMIT 1
                """
                ),
                {"user_id": user_id},
            ).fetchone()

            if result:
                return result[0]

            return None

        except Exception as e:
            warning(f"[PLAN MANAGER] Erro ao obter plan_type do usuário {user_id}: {e}")
            return None

    def upgrade_trial_to_free(self, session, client_id: str) -> bool:
        """
        Faz upgrade de Trial para Free.

        Args:
            session: SQLAlchemy session
            client_id: ID do cliente (owner do trial)

        Returns:
            True se bem-sucedido, False caso contrário
        """
        try:
            # Obter plano Free
            plans_by_type = self.get_active_plans()
            free_plan = plans_by_type.get("free")

            if not free_plan:
                warning("[PLAN MANAGER] Plano 'free' não encontrado nos planos ativos")
                return False

            free_plan_id = free_plan.get("plan_id")

            # Atualizar cliente com novo plan_id
            session.execute(
                text(
                    """
                    UPDATE clients
                    SET plan_id = :plan_id, updated_at = :now
                    WHERE client_id = :client_id
                """
                ),
                {
                    "plan_id": free_plan_id,
                    "client_id": client_id,
                    "now": datetime.utcnow(),
                },
            )
            session.commit()

            debug(f"[PLAN MANAGER] ✓ Upgrade Trial→Free para cliente {client_id}")
            return True

        except Exception as e:
            error(f"[PLAN MANAGER] Erro ao fazer upgrade Trial→Free: {e}")
            session.rollback()
            return False

    def check_and_upgrade_trial(self, session, user_id: str) -> bool:
        """
        Verifica se usuário está em plan Trial e faz upgrade para Free se necessário.

        Args:
            session: SQLAlchemy session
            user_id: ID do usuário

        Returns:
            True se upgrade foi executado ou user já não é trial, False se erro
        """
        try:
            # Obter client_id do usuário
            result = session.execute(
                text("SELECT client_id FROM users WHERE user_id = :user_id"),
                {"user_id": user_id},
            ).fetchone()

            if not result:
                warning(f"[PLAN MANAGER] Usuário {user_id} não encontrado")
                return False

            client_id = result[0]

            # Verificar plan_type atual
            plan_type = self.get_user_plan_type(session, user_id)

            if plan_type == "trial":
                info(
                    f"[PLAN MANAGER] Usuário {user_id} em plano Trial, fazendo upgrade para Free"
                )
                return self.upgrade_trial_to_free(session, client_id)
            else:
                debug(
                    f"[PLAN MANAGER] Usuário {user_id} não está em Trial (plano: {plan_type})"
                )
                return True

        except Exception as e:
            error(f"[PLAN MANAGER] Erro ao verificar/fazer upgrade do plano: {e}")
            return False


# Instância global
_plan_manager: Optional[PlanManager] = None


def init_plan_manager(db_manager=None) -> PlanManager:
    """
    Inicializa a instância global do PlanManager.

    Args:
        db_manager: DatabaseManager

    Returns:
        PlanManager inicializado
    """
    global _plan_manager
    _plan_manager = PlanManager(db_manager=db_manager)
    info("[PLAN MANAGER] PlanManager initialized")
    return _plan_manager


def get_plan_manager() -> PlanManager:
    """
    Obtém a instância global do PlanManager.

    Returns:
        PlanManager instance
    """
    global _plan_manager
    if not _plan_manager:
        warning("[PLAN MANAGER] PlanManager not initialized, creating default instance")
        _plan_manager = PlanManager(db_manager=None)
    return _plan_manager
