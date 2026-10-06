"""
Scraping Tool - Main Entry Point

The actual implementation is modularized in:
- Scraping/setup.py - Path and imports configuration
- Scraping/config.py - Logging and proxy configuration
- Scraping/meta_ads.py - Meta Ads Library functions
- Scraping/crawler.py - Main ScrapingScrawlingTool class
- Scraping/__init__.py - Package exports
"""

import asyncio
import argparse
import sys
import logging
import os
import io
import json
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import quote_plus

# Import all modules from the Scraping package
from Scraping import (
    # Setup
    _setup_path_and_imports,
    get_backend_dir,
    get_meta_ads_library_map_file,
    get_load_config,
    _backend_dir,
    _debug_mode,
    # Config
    setup_logging,
    get_scraping_proxy,
    # Crawler
    ScrapingScrawlingTool,
)


async def main():
    """Main entry point for the scraping tool"""
    parser = argparse.ArgumentParser(description="Tool de Scraping com Vision AI")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--fetch", type=str, help="Conteúdo HTML ou path para arquivo HTML fetchado."
    )
    group.add_argument(
        "--query", type=str, help="Termo para pesquisar. Ex: 'Imóveis Rio Claro - SP'"
    )
    group.add_argument(
        "--meta-ads-library",
        type=str,
        help="Buscar conta na Meta Ads Library. Ex: --meta-ads-library nike",
    )
    group.add_argument(
        "--pain-mapping",
        type=str,
        help="Mapear dores de concorrentes. Ex: --pain-mapping 'make.com' ou --pain-mapping 'Xavier Camargo Imobiliária, Rio Claro'",
    )
    group.add_argument(
        "--specific-source-research",
        type=str,
        help="Pesquisar termos em fonte específica. Ex: --specific-source-research 'instagram.com|@fashion,influencer|5' (site|terms_comma_sep|pages)",
    )

    parser.add_argument(
        "--human",
        type=str,
        default="false",
        help="Exibe resultados formatados para leitura humana. Use: --human true ou --human false",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Modo debug: mostra informações detalhadas e pausa antes de chamar IA",
    )
    parser.add_argument(
        "--vision",
        type=str,
        default="on",
        help="Ativar/desativar análise com IA. Use: --vision on ou --vision off (padrão: on)",
    )
    parser.add_argument(
        "--screenshot",
        type=str,
        default="false",
        help="Capturar apenas screenshot sem scraping. Use: --screenshot true ou --screenshot false",
    )
    args = parser.parse_args()

    tool = ScrapingScrawlingTool()

    # Converter flags string para boolean
    debug_mode = args.debug  # Já é boolean com action='store_true'
    human_mode = (
        args.human.lower() == "true" or debug_mode
    )  # Debug mode força stealth/human mode
    vision_enabled = args.vision.lower() != "off"
    screenshot_only = args.screenshot.lower() == "true"

    if debug_mode:
        human_mode = True  # Força stealth em modo debug

    # Configurar logging baseado em human_mode
    setup_logging(human_mode)

    target_url = None
    fetched_content = None
    is_google_search_flag = False
    is_meta_ads_library_flag = False
    is_pain_mapping_flag = False
    is_specific_source_flag = False
    meta_ads_account = None
    pain_mapping_input = None
    specific_source_site = None
    specific_source_terms = []
    specific_source_pages = 1

    if getattr(args, "specific_source_research", None):
        is_specific_source_flag = True
        raw = args.specific_source_research.strip()
        parts = raw.split("|")
        if len(parts) >= 3:
            specific_source_site = parts[0].strip()
            specific_source_terms = [
                t.strip() for t in parts[1].split(",") if t.strip()
            ]
            specific_source_pages = int(parts[2].strip())
        else:
            print("[ERRO] Formato: --specific-source-research 'site|term1,term2|pages'")
            sys.exit(1)
        logging.info(
            f"[SPECIFIC_SOURCE] site={specific_source_site}, terms={specific_source_terms}, pages={specific_source_pages}"
        )

    if args.pain_mapping:
        is_pain_mapping_flag = True
        pain_mapping_input = args.pain_mapping.strip()
        logging.info(
            f"[PAIN_MAPPING] Iniciando mapeamento de dores para: {pain_mapping_input}"
        )
    elif args.query:
        encoded_search_term = quote_plus(args.query)
        target_url = f"https://www.google.com/search?q={encoded_search_term}"
        is_google_search_flag = True
    elif args.meta_ads_library:
        is_meta_ads_library_flag = True
        # Processa a conta fornecida
        account_input = args.meta_ads_library.strip()

        # Remove @ se tiver
        if account_input.startswith("@"):
            meta_ads_account = account_input[1:]
        else:
            meta_ads_account = account_input

        # Valida
        if len(meta_ads_account) > 0:
            logging.info(f"[META_ADS] Buscando: {meta_ads_account}")
        else:
            print("[ERRO] Erro: Conta inválida!")
            print("Use: --meta-ads-library nike")
            sys.exit(1)
    elif args.fetch:
        fetch_input = args.fetch.strip()
        fetch_path = Path(fetch_input)

        if fetch_path.exists() and fetch_path.is_file():
            # Permite leitura apenas de /tmp para evitar acesso a arquivos do backend
            try:
                resolved = fetch_path.resolve()
                resolved.relative_to(Path("/tmp"))
            except ValueError:
                print(f"[ERRO] --fetch só pode ler arquivos de /tmp por segurança.")
                sys.exit(1)
            try:
                fetched_content = fetch_path.read_text(encoding="utf-8")
                target_url = f"fetched://{fetch_path.absolute()}"
                logging.info(f"[FETCH] Conteúdo carregado de /tmp: {fetch_path}")
            except Exception as e:
                print(f"[ERRO] Erro ao ler arquivo: {e}")
                sys.exit(1)
        else:
            fetched_content = fetch_input
            target_url = "fetched://inline"
            logging.info(f"[FETCH] Conteúdo HTML fornecido diretamente")

    if not human_mode and target_url:
        sys.stdout.write(f"URL: {target_url}\n")
        sys.stdout.flush()

    # Create a StringIO object to capture stdout
    old_stdout = sys.stdout
    redirected_output = io.StringIO()
    if not human_mode:
        sys.stdout = redirected_output

    if is_specific_source_flag:
        sys.stdout = old_stdout if not human_mode else sys.stdout
        print(
            f"\n[SPECIFIC_SOURCE] Pesquisando '{specific_source_terms}' em {specific_source_site} ({specific_source_pages} páginas/termo)..."
        )

        try:
            result = await tool.execute_specific_source_research(
                site=specific_source_site,
                terms=specific_source_terms,
                pages=specific_source_pages,
            )
        except Exception as e:
            print(f"[ERROR] Erro ao executar specific source research: {e}")
            import traceback

            print(traceback.format_exc())
            sys.exit(1)

        if not human_mode:
            sys.stdout = redirected_output
    elif is_pain_mapping_flag:
        sys.stdout = old_stdout if not human_mode else sys.stdout

        # Debug mode: aviso sobre navegador visível
        if debug_mode:
            print(f"\n[PAIN_MAPPING] Mapeando dores de: {pain_mapping_input}...")
            print("[DEBUG] Janela do navegador vai abrir com headless=False...")
            print("[DEBUG] Pressione ENTER quando terminar de observar...")
        else:
            print(f"\n[PAIN_MAPPING] Mapeando dores de: {pain_mapping_input}...")

        # Executar pain mapping (função async)
        try:
            result = await tool.execute_pain_mapping(
                pain_mapping_input, debug=debug_mode
            )
        except Exception as e:
            print(f"[ERROR] Erro ao executar pain mapping: {e}")
            import traceback

            print(traceback.format_exc())
            sys.exit(1)

        if not human_mode:
            sys.stdout = redirected_output
    elif is_meta_ads_library_flag:
        sys.stdout = old_stdout if not human_mode else sys.stdout
        print(f"\n[META_ADS] Buscando na Meta Ads Library...")

        # Para Meta Ads, precisamos da classe implementada no crawler
        # Implementar execute_facebook_ads_search_interactive
        result = {
            "status": "error",
            "message": "Meta Ads Library search ainda não implementado nesta versão",
        }
        if not human_mode:
            sys.stdout = redirected_output
    else:
        sys.stdout = old_stdout if not human_mode else sys.stdout
        if screenshot_only:
            print(f"\n[SCREENSHOT] Capturando screenshot...")
        else:
            print(f"\n[CRAWLER] Carregando página...")

        # Debug mode: pausa antes de chamar IA (APENAS se não for screenshot_only)
        if debug_mode and vision_enabled and not screenshot_only:
            print("[DEBUG] ⏸️ Página carregada. Pressione ENTER para chamar IA...")
            input()

        result = await tool.execute(
            target_url,
            css_selector=None,
            is_google_search=is_google_search_flag,
            debug=debug_mode,
            vision_only=screenshot_only,
            fetched_content=fetched_content,
        )
        if not human_mode:
            sys.stdout = redirected_output

    if not human_mode:
        # Restore stdout
        sys.stdout = old_stdout
        # Get captured output, discard it
        _ = redirected_output.getvalue()

    if result["status"] == "success" or result["status"] == "success_with_warning":
        if human_mode:
            # Exibição formatada para humanos
            print("=" * 80)
            if is_specific_source_flag:
                print(
                    f"[SPECIFIC_SOURCE] RESULTADOS: {result.get('site')} — {result.get('success_count')}/{result.get('total_pages_scraped')} páginas"
                )
                print("=" * 80)
                for r in result.get("results", []):
                    print(
                        f"\n[TERMO: {r['term']} | Página {r['page']} | start={r['start']}]"
                    )
                    print(f"URL: {r['url']}")
                    print(f"Status: {r['status']}")
                    if r.get("content"):
                        print(
                            r["content"][:500] + "..."
                            if len(r.get("content", "")) > 500
                            else r.get("content", "")
                        )
                    if r.get("error"):
                        print(f"Erro: {r['error']}")
            elif result.get("type") == "pain_mapping":
                print(f"[PAIN_MAPPING] ANÁLISE DE DORES DO CONCORRENTE")
                print("=" * 80)

                # Exibir reviews do Google Maps
                if result.get("google_maps_reviews"):
                    print("\nGOOGLE MAPS - PIORES AVALIACOES")
                    print("-" * 80)
                    reviews = result["google_maps_reviews"]
                    print(f"Total de reviews extraídos: {len(reviews)}")

                    # Contar por rating
                    rating_counts = {}
                    for review in reviews:
                        rating = review.get("rating", 5)
                        rating_counts[rating] = rating_counts.get(rating, 0) + 1

                    print("\nBreakdown por Rating:")
                    for star in range(1, 6):
                        count = rating_counts.get(star, 0)
                        if count > 0:
                            print(f"  {star} stars: {count} reviews")

                    for i, review in enumerate(reviews[:10], 1):  # Top 10
                        print(
                            f"\n[{i}] Rating: {review.get('rating', 'N/A')} - {review.get('author', 'Anonimo')}"
                        )
                        print(f"Data: {review.get('date', 'N/A')}")
                        print(f"Texto: {review.get('text', '')[:300]}...")

                # Exibir reviews do Trustpilot
                if result.get("trustpilot_reviews"):
                    print("\n\nTRUESTIPLOT - PIORES AVALIAÇÕES")
                    print("-" * 80)
                    reviews = result["trustpilot_reviews"]
                    print(f"Total de reviews extraídos: {len(reviews)}")

                    # Contar por rating
                    rating_counts = {}
                    for review in reviews:
                        rating = review.get("rating", 5)
                        rating_counts[rating] = rating_counts.get(rating, 0) + 1

                    print("\nBreakdown por Rating:")
                    for star in range(1, 6):
                        count = rating_counts.get(star, 0)
                        if count > 0:
                            print(f"  {star} stars: {count} reviews")

                    for i, review in enumerate(reviews[:10], 1):  # Top 10
                        print(
                            f"\n[{i}] Rating: {review.get('rating', 'N/A')} - {review.get('author', 'Anonimo')}"
                        )
                        print(f"Data: {review.get('date', 'N/A')}")
                        print(f"Texto: {review.get('text', '')[:300]}...")

                # Exibir análise consolidada de dores
                if result.get("pain_analysis"):
                    print("\n\nANALISE CONSOLIDADA DE DORES")
                    print("-" * 80)
                    analysis = result["pain_analysis"]

                    if isinstance(analysis, dict):
                        # Exibir em formato legível
                        print(
                            f"Total de Reviews Analisados: {analysis.get('total_reviews', 0)}"
                        )
                        print()

                        # Mostrar principais dores
                        pain_types = analysis.get("pain_types", [])
                        if pain_types:
                            print("### PRINCIPAIS DORES IDENTIFICADAS\n")
                            for pain in pain_types:
                                print(
                                    f"{pain.get('rank')}. **{pain.get('type')}** - Mencionado em {pain.get('count')} reviews ({pain.get('percentage')}%)"
                                )
                    else:
                        # Fallback para string (compatibilidade)
                        print(analysis)

            elif result.get("type") == "screenshot":
                print(f"[SCREENSHOT] CAPTURA DA PÁGINA")
                # Salvar screenshot localmente se em debug mode
                if debug_mode and screenshot_only:
                    try:
                        import base64
                        from pathlib import Path
                        from datetime import datetime

                        # Extrair base64 do data URI
                        content = result["content"]
                        if content.startswith("data:image/png;base64,"):
                            base64_data = content.replace("data:image/png;base64,", "")

                            # Criar diretório de screenshots se não existir
                            screenshots_dir = Path("./screenshots")
                            screenshots_dir.mkdir(exist_ok=True)

                            # Gerar nome do arquivo com timestamp
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            filename = screenshots_dir / f"screenshot_{timestamp}.png"

                            # Decodificar e salvar
                            image_data = base64.b64decode(base64_data)
                            filename.write_bytes(image_data)
                            print(f"\n✅ Screenshot salvo: {filename.absolute()}\n")
                    except Exception as e:
                        print(f"\n⚠️ Erro ao salvar screenshot: {e}\n")

                # Exibir análise de design se disponível
                if result.get("design_analysis"):
                    print("\n" + "=" * 80)
                    print("📊 ANÁLISE DE DESIGN")
                    print("=" * 80)
                    import json

                    design_data = result["design_analysis"]
                    if isinstance(design_data, dict):
                        print(json.dumps(design_data, indent=2, ensure_ascii=False))
                    else:
                        print(design_data)
                    print("=" * 80)
            elif is_google_search_flag:
                print(f"[BUSCA] RESULTADOS DE BUSCA")
            elif is_meta_ads_library_flag:
                print(f"📱 META ADS LIBRARY - BUSCA POR CONTA")
            else:
                print("📄 CONTEÚDO DA PÁGINA")
            print("=" * 80)

            # Para screenshots e pain_mapping, não exibir content
            if result.get("type") not in ["screenshot", "pain_mapping"]:
                sys.stdout.write(result.get("content", ""))
                sys.stdout.write("\n\n")

            # Exibir debug data se disponível
            if result.get("debug_data"):
                print("=" * 50)
                print("[BUSCA] DEBUG - DADOS EXTRAÍDOS")
                print("=" * 50)
                print(result["debug_data"])
                print()

            # Exibir análise de vision
            if result.get("profile_pic_analysis"):
                print("=" * 50)
                print("📊 ANÁLISE DA FOTO DE PERFIL (VISION IA)")
                print("=" * 50)
                pic_data = result["profile_pic_analysis"]
                print(f"\n{pic_data.get('analysis')}")
            elif result.get("favicon_for_branding"):
                print("=" * 50)
                print("📊 ANÁLISE DE FAVICON (VISION IA)")
                print("=" * 50)
                favicon_data = result["favicon_for_branding"]
                print(f"URL: {favicon_data.get('url')}\n")
                print(f"{favicon_data.get('analysis')}")
            elif result.get("favicon_vision_analysis"):
                print("=" * 50)
                print("📊 ANÁLISE DE FAVICON (VISION IA)")
                print("=" * 50)
                print(f"\n{result['favicon_vision_analysis']}")
        else:
            # Saída padrão (JSON)
            if is_specific_source_flag:
                sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False))
            # Para pain_mapping, exibir resultado consolidado
            elif result.get("type") == "pain_mapping":
                import json

                pain_data = {
                    "type": "pain_mapping",
                    "google_maps_reviews": result.get("google_maps_reviews", []),
                    "trustpilot_reviews": result.get("trustpilot_reviews", []),
                    "pain_analysis": result.get("pain_analysis", ""),
                }
                sys.stdout.write(json.dumps(pain_data, indent=2, ensure_ascii=False))
            elif result.get("type") != "screenshot":
                sys.stdout.write(result["content"])

            if result.get("design_analysis"):
                import json

                sys.stdout.write("\n")
                design_data = result["design_analysis"]
                if isinstance(design_data, dict):
                    sys.stdout.write(
                        json.dumps(design_data, indent=2, ensure_ascii=False)
                    )
                else:
                    sys.stdout.write(str(design_data))
                sys.stdout.write("\n")
            elif result.get("profile_pic_analysis"):
                sys.stdout.write("\n\n---\n\n")
                sys.stdout.write("## 📊 Análise da Foto de Perfil (Vision IA)\n\n")
                pic_data = result["profile_pic_analysis"]
                sys.stdout.write(f"{pic_data.get('analysis')}\n")
            elif result.get("favicon_for_branding"):
                sys.stdout.write("\n\n---\n\n")
                sys.stdout.write("## 📊 Análise de Favicon (Vision IA)\n\n")
                favicon_data = result["favicon_for_branding"]
                sys.stdout.write(f"URL: {favicon_data.get('url')}\n\n")
                sys.stdout.write(f"{favicon_data.get('analysis')}\n")
            elif result.get("favicon_vision_analysis"):
                sys.stdout.write("\n\n---\n\n")
                sys.stdout.write("## 📊 Análise de Favicon (Vision IA)\n\n")
                sys.stdout.write(f"{result['favicon_vision_analysis']}\n")
            sys.stdout.flush()
    else:
        sys.stderr.write(f"Error: {result['message']}\n")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
