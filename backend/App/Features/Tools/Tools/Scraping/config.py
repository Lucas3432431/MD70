"""Configuration and logging setup"""

import logging
import os
from typing import Optional
from .setup import get_load_config


def setup_logging(human_mode: bool = False):
    """Configura logging baseado em human_mode"""
    if human_mode:
        # Modo humano: mostra logs
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    else:
        # Modo normal: silencia logs
        logging.basicConfig(level=logging.ERROR)

    logging.getLogger("crawl4ai").setLevel(logging.ERROR)


def get_scraping_proxy() -> Optional[str]:
    """Retorna um proxy aleatório da lista ou a URL de proxy rotativo configurada (Global)."""
    try:
        load_config = get_load_config()
        if load_config:
            config = load_config()

            # 1. Prioridade: Proxy Rotativo
            rotating_url = config.get("rotating_proxy_url", "")
            if rotating_url:
                return rotating_url

            # 2. Alternativa: Lista de Proxies
            proxy_list_str = config.get("proxy_list", "")
            if proxy_list_str:
                import random

                proxies = [p.strip() for p in proxy_list_str.split(",") if p.strip()]
                if proxies:
                    return random.choice(proxies)

        # 3. Fallback: Variável de ambiente direta
        return os.getenv("PROXY_URL") or os.getenv("HTTP_PROXY")
    except Exception:
        return None


def get_browserbase_config() -> Optional[dict]:
    """Retorna as credenciais do Browserbase se configuradas."""
    try:
        load_config = get_load_config()
        api_key = ""
        project_id = ""
        if load_config:
            config = load_config()
            api_key = config.get("browserbase_api_key", "")
            project_id = config.get("browserbase_project_id", "")

        api_key = api_key or os.getenv("BROWSERBASE_API_KEY", "")
        project_id = project_id or os.getenv("BROWSERBASE_PROJECT_ID", "")

        if api_key and project_id:
            return {"api_key": api_key, "project_id": project_id}
        return None
    except Exception:
        return None
