"""
ProxyRoutes.py - Rotas para servir arquivos estáticos (referências, assets, etc)
Permite que a API Imagen acesse imagens locais via URLs públicas
"""

import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from App.Core.Logs import debug, error
import mimetypes

_BROWSER_SERVICE_URL = os.getenv("BROWSER_SERVICE_URL", "")

# Router
proxy_router = APIRouter(tags=["Proxy"], prefix="/api/proxy")

# Base path para referências — usa MEDIA_PATH env var ou Data/Media como fallback
# Data/ já está montado como :rw em todos os ambientes, sem precisar de volume extra
backend_path = Path(__file__).parent.parent.parent.parent.parent
_env_media = os.getenv("MEDIA_PATH", "")
BASE_REFERENCES_PATH = Path(_env_media) if _env_media else backend_path / "Data" / "Media"
BASE_REFERENCES_PATH.mkdir(parents=True, exist_ok=True)

debug(f"[PROXY] BASE_REFERENCES_PATH: {BASE_REFERENCES_PATH}")


_OG_CACHE_TTL = 86400  # 24 horas


@proxy_router.get("/link-preview")
async def get_link_preview(url: str):
    """Delega para o browser container extrair OG/meta tags e retornar preview estruturado."""
    from App.Core.Cache.RedisCache import cache_get, cache_set, url_hash

    domain = ""
    try:
        domain = urlparse(url).netloc
    except Exception:
        pass

    cache_key = f"og:{url_hash(url)}"
    cached = cache_get(cache_key)
    if cached is not None:
        debug(f"[PROXY] link-preview cache hit: {url}")
        return cached

    if not _BROWSER_SERVICE_URL:
        return {
            "success": False,
            "url": url,
            "title": None,
            "description": None,
            "image": None,
            "domain": domain,
        }

    try:
        import requests as _req

        data = await asyncio.to_thread(
            lambda: _req.post(
                f"{_BROWSER_SERVICE_URL}/link-preview",
                json={"url": url},
                timeout=20,
            ).json()
        )
        if data.get("success"):
            cache_set(cache_key, data, _OG_CACHE_TTL)
        return data
    except Exception as exc:
        error(f"[PROXY] link-preview falhou para {url}: {exc}")
        return {
            "success": False,
            "url": url,
            "title": None,
            "description": None,
            "image": None,
            "domain": domain,
        }


_EXTRACT_IMAGES_CACHE_TTL = 1800  # 30 min


@proxy_router.get("/extract-images")
async def extract_page_images(url: str):
    """Extrai imagens do conteúdo principal da página via browser service (exclui header/footer/nav)."""
    from App.Core.Cache.RedisCache import cache_get, cache_set, url_hash

    cache_key = f"extract-images:{url_hash(url)}"
    cached = cache_get(cache_key)
    if cached is not None:
        debug(f"[PROXY] extract-images cache hit: {url}")
        return cached

    if not _BROWSER_SERVICE_URL:
        return {"success": False, "images": [], "url": url}

    try:
        import requests as _req

        data = await asyncio.to_thread(
            lambda: _req.post(
                f"{_BROWSER_SERVICE_URL}/extract-images",
                json={"url": url},
                timeout=45,
            ).json()
        )
        if data.get("success") and data.get("images"):
            cache_set(cache_key, data, _EXTRACT_IMAGES_CACHE_TTL)
        return data
    except Exception as exc:
        error(f"[PROXY] extract-images falhou para {url}: {exc}")
        return {"success": False, "images": [], "url": url}


@proxy_router.get("/references/{path_param:path}")
async def serve_reference(path_param: str):
    r"""
    Serve arquivos de Data/References via URL pública

    Exemplo:
        GET /api/proxy/references/Test/IP
        Retorna: C:\...\Data\References\Test\IP

    Args:
        path_param: Caminho relativo dentro de Data/References (ex: "Test/IP")

    Returns:
        Arquivo servido com content-type correto
    """
    try:
        # Resolver o caminho completo
        file_path = (BASE_REFERENCES_PATH / path_param).resolve()

        # Validação de segurança: garantir que o arquivo está dentro de BASE_REFERENCES_PATH
        if not str(file_path).startswith(str(BASE_REFERENCES_PATH.resolve())):
            error(
                f"[PROXY] Tentativa de acesso fora do diretório permitido: {file_path}"
            )
            raise HTTPException(status_code=403, detail="Acesso negado")

        # Verificar se o arquivo existe
        if not file_path.exists():
            error(f"[PROXY] Arquivo não encontrado: {file_path}")
            raise HTTPException(
                status_code=404, detail=f"Arquivo não encontrado: {path_param}"
            )

        # Se for diretório, tentar servir arquivos dentro dele
        if file_path.is_dir():
            # Procurar por arquivo com extensão de imagem
            for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
                candidate = file_path / f"image{ext}"
                if candidate.exists():
                    file_path = candidate
                    break
                # Ou procurar qualquer imagem no diretório
                for img in file_path.glob(f"*{ext}"):
                    file_path = img
                    break

            if file_path.is_dir():
                error(f"[PROXY] Diretório sem imagem: {file_path}")
                raise HTTPException(
                    status_code=404,
                    detail=f"Nenhuma imagem encontrada em: {path_param}",
                )

        debug(f"[PROXY] Servindo arquivo: {file_path}")

        # Detectar media type baseado na extensão
        ext = file_path.suffix.lower()
        media_type_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".mov": "video/quicktime",
        }
        media_type = media_type_map.get(ext, "application/octet-stream")

        response = FileResponse(path=str(file_path), media_type=media_type)

        # Cache header
        response.headers["Cache-Control"] = "public, max-age=3600"

        return response

    except HTTPException:
        raise
    except Exception as e:
        error(f"[PROXY] Erro ao servir {path_param}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
