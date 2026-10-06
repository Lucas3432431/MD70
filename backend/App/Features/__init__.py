"""Features package."""

from . import Job

# from . import MessageProcessor

from .Auth import AuthManager

# Database, JsonStorage e Models foram movidos para App.Core.Crunch.Crunch
try:
    from .Llm import LLMClient
except ImportError:
    LLMClient = None

__all__ = [
    # Auth
    "AuthManager",
    # Llm
    "LLMClient",
]
