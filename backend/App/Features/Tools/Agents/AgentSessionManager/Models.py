"""Data models for agent sessions."""

from dataclasses import dataclass, field
from typing import Dict, Optional, List


@dataclass
class AgentSession:
    """Representa uma execução isolada de um agent"""

    session_id: str
    agent_id: str
    agent_name: str
    caller_agent_id: Optional[str]  # Quem chamou (None = user/manager)
    task: str
    started_at: str
    completed_at: Optional[str] = None
    status: str = "pending"  # pending, in_progress, completed, failed
    agent_history: List[Dict] = field(default_factory=list)  # Cópia isolada
    result: Optional[str] = None
    error: Optional[str] = None
    iterations: int = 0
    tools_executed: int = 0
