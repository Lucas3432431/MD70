"""Meta Ads Library search functions"""

import asyncio
import base64
import json
import logging
import os
from io import BytesIO
from typing import Optional, Dict, Any
from urllib.parse import quote_plus

try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import undetected_chromedriver as uc
    from webdriver_manager.chrome import ChromeDriverManager

    HAS_UNDETECTED = True
except ImportError:
    HAS_UNDETECTED = False

from .setup import get_load_config


async def load_or_create_meta_ads_library_map(page, debug=False):
    """
    Retorna seletores robusos para Meta Ads Library usando Playwright

    Args:
        page: Página Playwright
        debug: Se True, mostra logs de debug

    Returns:
        Dict com seletores dos elementos
    """
    element_map = {
        "country_button": {
            "selector": "button[aria-label*='Country'], button[aria-label*='Pais'], button[aria-label*='país']",
            "label": "Botao de Pais",
        },
        "ad_category_button": {
            "selector": "button[aria-label*='Category'], button[aria-label*='Categoria']",
            "label": "Botao de Categoria de Anuncio",
        },
        "search_input": {
            "selector": "input[type='search'], input[placeholder*='Pesquisar'], input[placeholder*='Search']:not([disabled]), input[aria-label*='search']:not([disabled])",
            "label": "Campo de Pesquisa",
        },
    }

    if debug:
        print("[DEBUG] [OK] Usando seletores robustos padrao")

    return element_map
