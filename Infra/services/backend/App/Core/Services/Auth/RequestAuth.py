"""
RequestAuth — helpers globais para extrair user_id / client_id de qualquer Request.

Toda rota deve usar estas funções em vez de chamar verify_token diretamente.
O middleware auth_token_cache_middleware (Services.py) pré-popula
request.scope["_auth_payload"] antes de cada rota, então na maioria dos casos
não há nem chamada JWT nem DB.
"""

from fastapi import HTTPException, Request
from App.Core.Logs import debug, error


def get_user_id_from_request(request: Request) -> str:
    """
    Retorna user_id autenticado. Lê do scope (preenchido pelo middleware)
    e só chama verify_token se scope estiver vazio.
    """
    try:
        if request.scope.get("dev_bypass_enabled"):
            from App.Core.Settings.Settings import GLOBAL_CONFIG

            dev_user_id = request.scope.get("dev_user_id")
            if not dev_user_id:
                from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager

                res = DatabaseManager.fetch_one(
                    "SELECT user_id FROM users WHERE client_id = '1' LIMIT 1"
                )
                dev_user_id = res.get("user_id") if res else "dev-user-1"
            debug(f"[RequestAuth] DEV BYPASS: user_id={dev_user_id}")
            return str(dev_user_id)

        # Caminho rápido: middleware já resolveu
        cached = request.scope.get("_auth_payload")
        if cached:
            user_id = cached.get("user_id")
            if user_id:
                return str(user_id)

        # Fallback: middleware falhou ou Redis não disponível
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(status_code=401, detail="Token nao fornecido")

        from App.Features.Auth import get_auth_service

        auth_service = get_auth_service()
        payload = auth_service.verify_token(token)

        # Anon admin bypass
        if not payload:
            anon = auth_service.verify_token(token, check_db=False)
            if anon and anon.get("user_id") == "anon-admin-md70":
                from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
                admin = DatabaseManager.fetch_one(
                    "SELECT user_id FROM users WHERE role = :role LIMIT 1",
                    {"role": "admin"},
                )
                if admin:
                    return str(admin.get("user_id"))

        if not payload:
            raise HTTPException(status_code=401, detail="AUTH_FAILED")

        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=401, detail="User ID nao encontrado no token"
            )

        return str(user_id)

    except HTTPException:
        raise
    except Exception as e:
        error(f"[RequestAuth] Erro ao extrair user_id: {e}")
        raise HTTPException(status_code=401, detail="Autenticacao invalida")


def get_client_id_from_request(request: Request):
    """
    Retorna client_id autenticado. Lê do scope (preenchido pelo middleware)
    e só chama verify_token se scope estiver vazio.
    """
    try:
        if request.scope.get("dev_bypass_enabled"):
            return request.scope.get("dev_client_id", 1)

        # Caminho rápido: middleware já resolveu
        cached = request.scope.get("_auth_payload")
        if cached:
            client_id = cached.get("client_id")
            if client_id:
                return client_id

        # Fallback: middleware falhou ou Redis não disponível
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(status_code=401, detail="Token nao fornecido")

        from App.Features.Auth import get_auth_service

        auth_service = get_auth_service()
        payload = auth_service.verify_token(token)

        # Anon admin bypass
        if not payload:
            anon = auth_service.verify_token(token, check_db=False)
            if anon and anon.get("user_id") == "anon-admin-md70":
                from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
                admin = DatabaseManager.fetch_one(
                    "SELECT user_id, client_id FROM users WHERE role = :role LIMIT 1",
                    {"role": "admin"},
                )
                if admin:
                    return admin.get("client_id")

        if not payload:
            raise HTTPException(status_code=401, detail="AUTH_FAILED")

        client_id = payload.get("client_id")
        if not client_id:
            raise HTTPException(
                status_code=401, detail="Client ID nao encontrado no token"
            )

        return client_id

    except HTTPException:
        raise
    except Exception as e:
        error(f"[RequestAuth] Erro ao extrair client_id: {e}")
        raise HTTPException(status_code=401, detail="Autenticacao invalida")


def get_payload_from_request(request: Request) -> dict:
    """
    Retorna o payload JWT completo. Lê do scope (middleware) primeiro,
    cai em verify_token só se necessário.
    """
    try:
        if request.scope.get("dev_bypass_enabled"):
            return {
                "user_id": str(request.scope.get("dev_user_id", "1")),
                "client_id": str(request.scope.get("dev_client_id", "1")),
            }

        cached = request.scope.get("_auth_payload")
        if cached:
            return cached

        token = request.cookies.get("access_token") or (
            request.headers.get("Authorization", "").replace("Bearer ", "") or None
        )
        if not token:
            raise HTTPException(status_code=401, detail="Token nao fornecido")

        from App.Features.Auth import get_auth_service

        payload = get_auth_service().verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="AUTH_FAILED")
        return payload

    except HTTPException:
        raise
    except Exception as e:
        error(f"[RequestAuth] Erro ao extrair payload: {e}")
        raise HTTPException(status_code=401, detail="Autenticacao invalida")


# Aliases para compatibilidade com código existente em ChatRoutes.py
get_user_id_from_token = get_user_id_from_request
get_client_id_from_token = get_client_id_from_request
