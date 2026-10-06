"""
QueueSetup.py - Queue System Initialization and Management

Provides a singleton-like pattern for initializing and managing the queue system
across the application. Handles MultiQueueManager and MultiWorkerPool setup.

Example Usage:
    # At application startup
    from Core.Queues.QueueSetup import initialize_queue_system, get_queue_system

    queue_system = initialize_queue_system(core_instance)
    queue_system.start()

    # From MessageProcessor or other components
    qs = get_queue_system()
    qs.submit_task(queue_name="audio_processing", task_func, *args, **kwargs)

    # Check status
    status = qs.get_status()
    print(f"Active workers: {status['active_workers']}")

    # At application shutdown
    queue_system.stop(timeout=10)
"""

from typing import Dict, Any, Optional, Callable
import logging
from datetime import datetime
from App.Core.Logs import debug, info, warning, error


class QueueSystem:
    """
    Central queue system manager that coordinates MultiQueueManager and MultiWorkerPool.

    Provides a unified interface for queue operations, worker management, and system monitoring.
    """

    def __init__(
        self, queue_manager, worker_pool, config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the QueueSystem.

        Args:
            queue_manager: MultiQueueManager instance
            worker_pool: MultiWorkerPool instance
            config: Optional configuration dictionary with 'max_queue_size', 'worker_timeout', etc.
        """
        self.queue_manager = queue_manager
        self.worker_pool = worker_pool
        self.config = config or {}
        self.is_running = False
        self.started_at = None

    def start(self) -> bool:
        """
        Start all workers and initialize the queue system.

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if self.is_running:
                return True

            # Start all workers
            self.worker_pool.start()
            self.is_running = True
            self.started_at = datetime.now()

            return True

        except Exception as e:
            error(f"Failed to start QueueSystem: {str(e)}", exc_info=True)
            self.is_running = False
            raise

    def stop(self, timeout: int = 30) -> bool:
        """
        Stop all workers and shutdown the queue system gracefully.

        Args:
            timeout: Maximum seconds to wait for workers to finish (default: 30)

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not self.is_running:
                warning("QueueSystem is not running")
                return True

            info("Stopping QueueSystem with %d second timeout...", timeout)

            # Stop all workers gracefully
            self.worker_pool.stop()
            self.is_running = False

            info("QueueSystem stopped successfully")
            return True

        except Exception as e:
            error(f"Error stopping QueueSystem: {str(e)}", exc_info=True)
            return False

    def submit_task(
        self, queue_name: str, task_func: Callable, *args, **kwargs
    ) -> Optional[str]:
        """
        Submit a task to a specific queue.

        Args:
            queue_name: Name of the queue (e.g., 'audio_processing', 'image_processing')
            task_func: The function to execute
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function

        Returns:
            str: Task ID if successful, None otherwise
        """
        if not self.is_running:
            error("Cannot submit task: QueueSystem is not running")
            return None

        try:
            task_id = self.queue_manager.enqueue(queue_name, task_func, *args, **kwargs)
            debug(f"Task {task_id} submitted to queue '{queue_name}'")
            return task_id
        except Exception as e:
            error(
                f"Failed to submit task to queue '{queue_name}': {str(e)}",
                exc_info=True,
            )
            return None

    def get_status(self) -> Dict[str, Any]:
        """
        Get comprehensive status of the queue system.

        Returns:
            dict: Contains:
                - is_running: bool
                - started_at: datetime or None
                - uptime_seconds: int (0 if not running)
                - num_workers: int
                - active_workers: int
                - queue_stats: dict with queue names and sizes
                - total_queued_tasks: int
        """
        status = {
            "is_running": self.is_running,
            "started_at": self.started_at,
            "uptime_seconds": 0,
            "num_workers": self.worker_pool.num_workers,
            "active_workers": (
                self.worker_pool.get_active_workers_count()
                if hasattr(self.worker_pool, "get_active_workers_count")
                else 0
            ),
            "queue_stats": {},
            "total_queued_tasks": 0,
        }

        if self.is_running and self.started_at:
            status["uptime_seconds"] = int(
                (datetime.now() - self.started_at).total_seconds()
            )

        try:
            # Get queue statistics
            queue_names = (
                self.queue_manager.get_queue_names()
                if hasattr(self.queue_manager, "get_queue_names")
                else []
            )
            for queue_name in queue_names:
                queue = self.queue_manager.get_queue(queue_name)
                if queue:
                    queue_size = queue.qsize() if hasattr(queue, "qsize") else 0
                    status["queue_stats"][queue_name] = {
                        "size": queue_size,
                        "workers_assigned": (
                            self.worker_pool.get_workers_for_queue(queue_name)
                            if hasattr(self.worker_pool, "get_workers_for_queue")
                            else 0
                        ),
                    }
                    status["total_queued_tasks"] += queue_size
        except Exception as e:
            warning(f"Error retrieving queue status: {str(e)}")

        return status

    def get_queue_stats(self, queue_name: str) -> Optional[Dict[str, Any]]:
        """
        Get statistics for a specific queue.

        Args:
            queue_name: Name of the queue

        Returns:
            dict: Queue statistics or None if queue doesn't exist
        """
        try:
            queue = self.queue_manager.get_queue(queue_name)
            if not queue:
                return None

            return {
                "name": queue_name,
                "size": queue.qsize() if hasattr(queue, "qsize") else 0,
                "workers_assigned": (
                    self.worker_pool.get_workers_for_queue(queue_name)
                    if hasattr(self.worker_pool, "get_workers_for_queue")
                    else 0
                ),
            }
        except Exception as e:
            error(f"Error retrieving stats for queue '{queue_name}': {str(e)}")
            return None


# Global singleton instance
_queue_system: Optional[QueueSystem] = None


def initialize_queue_system(
    core_instance, config: Optional[Dict[str, Any]] = None
) -> QueueSystem:
    """
    Initialize the global queue system instance.

    This should be called once at application startup.

    Args:
        core_instance: The core application instance with queue_manager and worker_pool
        config: Optional configuration dictionary

    Returns:
        QueueSystem: The initialized queue system instance

    Raises:
        ValueError: If core_instance doesn't have required attributes
        RuntimeError: If queue system is already initialized
    """
    global _queue_system

    if _queue_system is not None:
        warning("Queue system is already initialized")
        return _queue_system

    try:
        # Validate core instance has required components
        if not hasattr(core_instance, "queue_manager"):
            raise ValueError("core_instance must have 'queue_manager' attribute")
        if not hasattr(core_instance, "worker_pool"):
            raise ValueError("core_instance must have 'worker_pool' attribute")

        _queue_system = QueueSystem(
            queue_manager=core_instance.queue_manager,
            worker_pool=core_instance.worker_pool,
            config=config,
        )

        return _queue_system

    except Exception as e:
        error(f"Failed to initialize QueueSystem: {str(e)}", exc_info=True)
        raise


def get_queue_system() -> Optional[QueueSystem]:
    """
    Get the global queue system instance.

    Returns:
        QueueSystem: The queue system instance or None if not initialized
    """
    global _queue_system

    if _queue_system is None:
        warning("Queue system not initialized. Call initialize_queue_system() first.")
        return None

    return _queue_system


def reset_queue_system() -> None:
    """
    Reset the global queue system instance.

    This should only be used in testing or during shutdown/restart scenarios.
    """
    global _queue_system

    if _queue_system is not None:
        try:
            if _queue_system.is_running:
                _queue_system.stop(timeout=5)
        except Exception as e:
            error(f"Error stopping queue system during reset: {str(e)}")

    _queue_system = None
    info("Queue system reset")
