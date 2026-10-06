"""Auth Feature - Autenticação e Autorização"""

from .AuthService import AuthService, get_auth_service, init_auth_service, AuthConfig

# Alias para compatibilidade com código antigo
AuthManager = AuthService

__all__ = [
    "AuthService",
    "AuthManager",  # Alias para compatibilidade
    "get_auth_service",
    "init_auth_service",
    "AuthConfig",
]
