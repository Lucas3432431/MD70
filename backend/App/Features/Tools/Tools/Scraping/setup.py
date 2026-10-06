import logging
import os
import sys
from typing import Optional, Callable

# Variáveis globais para armazenar as funções de carregamento
load_config = None


def setup_scraping_config():
    """Configura as funções de carregamento de configuração."""
    global load_config

    try:
        from App.Core.Settings.Settings import load_config as _load_config

        load_config = _load_config
        logging.info("[SCRAPING] [OK] Configurações vinculadas com sucesso")
    except Exception as e:
        logging.warning(f"[SCRAPING] ✗ Erro ao vincular configurações: {e}")


def get_load_config():
    """Retorna a função load_config."""
    return load_config
