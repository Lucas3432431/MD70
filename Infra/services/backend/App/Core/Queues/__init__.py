"""
Queue Management Module

Handles multi-operation job isolation and processing through Redis queues.
Supports 5 operation types: agent, scraping, image_gen, video_gen, vision.
"""

from .MultiQueueManager import (
    MultiQueueManager,
    OperationType,
    JobStatus,
    Message,
    ToolCall,
    Job,
    CompactorJob,
    get_queue_manager,
    reset_queue_manager,
)
from .MultiWorkerPool import (
    MultiWorkerPool,
    MessageWorker,
    SyncMessageWorker,
    ExternalToolCallWorker,
    DocumentToolCallWorker,
)
from .QueueSetup import QueueSystem, initialize_queue_system, get_queue_system

__all__ = [
    "MultiQueueManager",
    "OperationType",
    "JobStatus",
    "Message",
    "ToolCall",
    "Job",
    "CompactorJob",
    "get_queue_manager",
    "reset_queue_manager",
    "MultiWorkerPool",
    "MessageWorker",
    "SyncMessageWorker",
    "ExternalToolCallWorker",
    "DocumentToolCallWorker",
    "QueueSystem",
    "initialize_queue_system",
    "get_queue_system",
]
