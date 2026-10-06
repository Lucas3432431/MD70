"""Job Manager Singleton - Instância global compartilhada do JobManager."""

from .JobManager import JobManager

# Singleton global instance
_job_manager_instance = None


def get_job_manager() -> JobManager:
    """Retorna a instância global singleton do JobManager."""
    global _job_manager_instance
    if _job_manager_instance is None:
        _job_manager_instance = JobManager()
    return _job_manager_instance
