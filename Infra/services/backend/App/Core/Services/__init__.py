"""Services package."""

from . import Auth
from . import Common

# Importar rotas para fácil acesso
try:
    from .Auth import auth_router
except ImportError:
    auth_router = None
