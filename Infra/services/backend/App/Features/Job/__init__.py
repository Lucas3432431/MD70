"""Job package."""

from .JobManager import ProcessingJob, JobManager
from .Singleton import get_job_manager

__all__ = [
    # JobManager
    "ProcessingJob",
    "JobManager",
    # Singleton
    "get_job_manager",
]
