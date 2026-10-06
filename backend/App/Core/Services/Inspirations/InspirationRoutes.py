"""
Rotas de Inspirations - FastAPI Routes para servir cards e fazer proxy de imagens
"""

import json
import requests
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from io import BytesIO

from App.Core.Logs import debug, info, warning, error
from App.Core.Settings.Settings import get_public_url

# ========================================================================
# CONFIG
# ========================================================================

SHOULD_USE_PUBLIC_URL = False

INSPIRATIONS_JSON_PATH = (
    Path(__file__).parent.parent.parent.parent.parent / "Media" / "inspirations.json"
)
IMAGE_PROXY_REFERENCES_PATH = "/api/proxy/references"
IMAGE_DEFAULT_EXTENSION = ".jpg"
CACHE_CONTROL = "public, max-age=3600"
PROXY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://unsplash.com/",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


# ========================================================================
# MODELS
# ========================================================================


class InspirationCard(BaseModel):
    """Card de inspiração"""

    id: str
    title: str
    name: str
    description: str
    category: str
    image: str
    source: str
    url: str
    tags: List[str]
    created_at: str
    is_lp: Optional[bool] = False


# ========================================================================
# ROUTER
# ========================================================================

inspiration_router = APIRouter(tags=["Inspirations"], prefix="/api/inspirations")


# ========================================================================
# HELPER FUNCTIONS
# ========================================================================


def resolve_image_url(image_path: str) -> str:
    """
    Retorna caminho relativo para o proxy de references.
    URLs absolutas têm apenas o filename extraído — o frontend usa baseURL para construir a URL final.

    Args:
        image_path: URL completa ou caminho relativo (ex: "ShoesAds7_Template")

    Returns:
        Caminho relativo: /api/proxy/references/{filename}
    """
    if image_path.startswith(("http://", "https://")):
        if SHOULD_USE_PUBLIC_URL:
            return image_path
        filename = image_path.split("/")[-1]
        return f"{IMAGE_PROXY_REFERENCES_PATH}/{filename}"

    image_with_ext = image_path
    if "." not in image_path.split("/")[-1]:
        image_with_ext = f"{image_path}{IMAGE_DEFAULT_EXTENSION}"

    if SHOULD_USE_PUBLIC_URL:
        public_url = get_public_url()
        return f"{public_url}{IMAGE_PROXY_REFERENCES_PATH}/{image_with_ext}"

    return f"{IMAGE_PROXY_REFERENCES_PATH}/{image_with_ext}"


def load_inspirations_data() -> List[dict]:
    """Carrega os dados de inspirações do arquivo JSON e resolve URLs relativas, filtrando apenas is_active"""
    try:
        json_path = INSPIRATIONS_JSON_PATH

        if not json_path.exists():
            error(f"Inspirations JSON file not found: {json_path}")
            raise HTTPException(status_code=500, detail="Inspirations data not found")

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Filtrar apenas is_active: true
        active_inspirations = [insp for insp in data if insp.get("is_active", False)]

        # Processar cada inspiração para resolver caminhos de imagem relativos
        for inspiration in active_inspirations:
            if "image" in inspiration:
                inspiration["image"] = resolve_image_url(inspiration["image"])

        info(f"Loaded {len(active_inspirations)} active inspirations from JSON")
        return active_inspirations
    except Exception as e:
        error(f"Error loading inspirations data: {str(e)}")
        raise HTTPException(status_code=500, detail="Error loading inspirations data")


def get_inspiration_by_id(inspiration_id: str) -> Optional[dict]:
    """Busca uma inspiração pelo ID"""
    try:
        data = load_inspirations_data()
        for inspiration in data:
            if inspiration.get("id") == inspiration_id:
                return inspiration
        return None
    except Exception as e:
        error(f"Error finding inspiration: {str(e)}")
        return None


# ========================================================================
# ROUTES
# ========================================================================


@inspiration_router.get("/cards", response_model=List[InspirationCard])
async def get_inspiration_cards():
    """
    Retorna todos os cards de inspiração
    GET /api/inspirations/cards
    """
    try:
        data = load_inspirations_data()
        return data
    except HTTPException:
        raise
    except Exception as e:
        error(f"Error getting inspiration cards: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Error retrieving inspiration cards"
        )


@inspiration_router.get("/proxy/{inspiration_id}")
async def proxy_inspiration_image(inspiration_id: str):
    """
    Faz proxy de imagens de inspirações
    GET /api/inspirations/proxy/:id

    Busca a URL da imagem no card e retorna a imagem
    """
    try:
        # Buscar inspiração
        inspiration = get_inspiration_by_id(inspiration_id)

        if not inspiration:
            error(f"Inspiration not found: {inspiration_id}")
            raise HTTPException(status_code=404, detail="Inspiration not found")

        image_url = inspiration.get("image")

        if not image_url:
            error(f"No image URL found for inspiration: {inspiration_id}")
            raise HTTPException(status_code=404, detail="Image not found")

        # Fazer proxy da imagem
        debug(f"Proxying image from: {image_url}")
        response = requests.get(
            image_url,
            timeout=10,
            stream=True,
            headers=PROXY_HEADERS,
            allow_redirects=True,
        )

        if response.status_code != 200:
            error(f"Failed to fetch image: {response.status_code}")
            raise HTTPException(
                status_code=502, detail="Failed to fetch image from source"
            )

        # Obter content type da resposta original
        content_type = response.headers.get("content-type", "image/jpeg")

        # Retornar a imagem como StreamingResponse
        return StreamingResponse(
            BytesIO(response.content),
            media_type=content_type,
            headers={"Cache-Control": CACHE_CONTROL, "Content-Type": content_type},
        )

    except HTTPException:
        raise
    except Exception as e:
        error(f"Error proxying inspiration image: {str(e)}")
        raise HTTPException(status_code=500, detail="Error proxying image")
