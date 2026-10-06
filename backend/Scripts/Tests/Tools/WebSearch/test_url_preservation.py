import asyncio
import logging
import json
import re
import sys
import os
from pathlib import Path

# Configurar o PYTHONPATH para o root do backend
backend_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.append(str(backend_root))

# Mock básico para evitar carregamento de todo o framework e circular imports
import unittest.mock as mock

sys.modules["App.Core.Services.Common.Dependencies"] = mock.MagicMock()
sys.modules["App.Core.Services.Common.AppSetup"] = mock.MagicMock()
sys.modules["App.Core.Settings.Settings"] = mock.MagicMock()

# Agora podemos importar a ferramenta real
from App.Features.Tools.Tools.Scraping.crawler import ScrapingScrawlingTool

# Configuração de Logs
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


async def diagnose_tool_extraction(url):
    print(f"\n{'='*70}")
    print(f"DIAGNÓSTICO DA FERRAMENTA SCRAPING: {url}")
    print(f"{'='*70}\n")

    crawler = ScrapingScrawlingTool()

    # 1. Teste de FETCH via Ferramenta (que agora usa Trafilatura + Fallback)
    print(f"--- [EXECUTANDO] crawler.execute(url) ---")
    start_time = asyncio.get_event_loop().time()
    result = await crawler.execute(url=url)
    duration = asyncio.get_event_loop().time() - start_time

    if result.get("status") == "success":
        content = result.get("content", "")

        # Analisar preservação de URLs e Imagens
        links = re.findall(r"https?://[^\s\)]+", content)
        # Padrao markdown para imagens: ![alt](url)
        markdown_images = re.findall(r"!\[.*?\]\((.*?)\)", content)
        # Padrao html para imagens: <img src="url">
        html_images = re.findall(r'<img[^>]+src=["\'](.*?)["\']', content)

        total_images = len(markdown_images) + len(html_images)

        print(f"Tempo de execução: {duration:.2f}s")
        print(f"Tamanho do conteúdo: {len(content)} caracteres")
        print(f"Total de Links (URLs) preservados: {len(links)}")
        print(f"Total de Imagens preservadas: {total_images}")

        print(f"\n--- AMOSTRA DE LINKS ENCONTRADOS (Top 10) ---")
        for i, link in enumerate(links[:10], 1):
            print(f"{i}. {link}")

        print(f"\n--- AMOSTRA DE IMAGENS ENCONTRADAS (Top 5) ---")
        all_imgs = markdown_images + html_images
        for i, img in enumerate(all_imgs[:5], 1):
            print(f"{i}. {img}")

        print(f"\n--- PREVIEW DO CONTEÚDO (Primeiros 500 chars) ---")
        print(content[:500] + "...")
    else:
        print(f"❌ Erro na ferramenta: {result.get('message')}")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    url = "https://vuranutra.com/products/bye-belly-suplemento-quema-grasa-x30"
    asyncio.run(diagnose_tool_extraction(url))
