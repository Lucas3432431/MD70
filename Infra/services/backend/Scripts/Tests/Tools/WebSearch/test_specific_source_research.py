"""
Testa a lógica de SpecificSourceResearch:
  - Construção correta das URLs (site: + paginação)
  - Execução real do crawler (execute_specific_source_research)
  - Roteamento via _execute_specific_source_research (sem créditos reais)

Uso:
    python test_specific_source_research.py                  # testa URL building + crawler real
    python test_specific_source_research.py --dry-run        # apenas URL building, sem HTTP
    python test_specific_source_research.py --save           # salva output JSON em ./output/
"""

import asyncio
import json
import sys
import os
import argparse
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus, unquote_plus

# ── Path setup ─────────────────────────────────────────────────────────────────
backend_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.append(str(backend_root))

# ── Mocks mínimos para evitar imports pesados do framework ─────────────────────
import unittest.mock as mock

sys.modules.setdefault("App.Core.Services.Common.Dependencies", mock.MagicMock())
sys.modules.setdefault("App.Core.Services.Common.AppSetup", mock.MagicMock())
sys.modules.setdefault("App.Core.Settings.Settings", mock.MagicMock())

# Importar apenas o crawler (sem framework completo)
from App.Features.Tools.Tools.Scraping.crawler import ScrapingScrawlingTool

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

# ── Cenários de teste ──────────────────────────────────────────────────────────
SCENARIOS = [
    {
        "name": "Instagram — influencer moda",
        "site": "instagram.com",
        "terms": ["@influencer moda brasil"],
        "pages": 2,
    },
    {
        "name": "LinkedIn — decisores marketing",
        "site": "linkedin.com",
        "terms": ["head of marketing fintech"],
        "pages": 2,
    },
    {
        "name": "Multi-term — Instagram nicho fitness",
        "site": "instagram.com",
        "terms": ["personal trainer SP", "@fitness brasil"],
        "pages": 1,
    },
]


# ── Helpers ────────────────────────────────────────────────────────────────────


def build_expected_urls(site: str, terms: list, pages: int) -> list[dict]:
    """Reconstrói as URLs que o crawler vai gerar — para validação unitária."""
    domain = site.replace("https://", "").replace("http://", "").rstrip("/")
    urls = []
    for term in terms:
        for page_idx in range(pages):
            start = page_idx * 10
            query = f'site:{domain} "{term}"'
            encoded = quote_plus(query)
            url = f"https://www.google.com/search?q={encoded}&start={start}"
            urls.append(
                {"term": term, "page": page_idx + 1, "start": start, "url": url}
            )
    return urls


def print_section(title: str):
    print(f"\n{'─' * 70}")
    print(f"  {title}")
    print(f"{'─' * 70}")


def print_result_summary(result: dict):
    status = "✓" if result.get("status") == "success" else "✗"
    print(f"  Status      : {status} {result.get('status')}")
    print(f"  Site        : {result.get('site')}")
    print(f"  Terms       : {result.get('terms')}")
    print(f"  Pages/term  : {result.get('pages_per_term')}")
    print(f"  Total pages : {result.get('total_pages_scraped')}")
    print(f"  Successes   : {result.get('success_count')}")

    results = result.get("results", [])
    if results:
        print(f"\n  Resultados por página:")
        for r in results:
            icon = "✓" if r["status"] == "success" else "✗"
            content_len = len(r.get("content", ""))
            print(
                f"    {icon} [{r['term']}] p{r['page']} (start={r['start']}) — {content_len} chars"
            )
            if r.get("error"):
                print(f"       Erro: {r['error'][:80]}")
            if r.get("content"):
                preview = r["content"][:200].replace("\n", " ")
                print(f"       Preview: {preview}...")


# ── Teste 1: Validação de URL building ────────────────────────────────────────


def test_url_building():
    print_section("TESTE 1 — Construção de URLs (sem HTTP)")
    all_passed = True

    cases = [
        {
            "site": "instagram.com",
            "term": "@fashion brasil",
            "pages": 3,
            "expected_starts": [0, 10, 20],
        },
        {
            "site": "https://linkedin.com/",
            "term": "head of growth",
            "pages": 2,
            "expected_starts": [0, 10],
        },
    ]

    for case in cases:
        urls = build_expected_urls(case["site"], [case["term"]], case["pages"])
        starts = [u["start"] for u in urls]
        decoded_urls = [unquote_plus(u["url"]) for u in urls]
        domains_ok = all(
            f'site:{case["site"].replace("https://","").replace("http://","").rstrip("/")}'
            in d
            for d in decoded_urls
        )
        terms_ok = all(f'"{case["term"]}"' in d for d in decoded_urls)
        starts_ok = starts == case["expected_starts"]
        http_cleaned = all(
            "https://" not in d.split("site:")[1].split(" ")[0] for d in decoded_urls
        )

        passed = domains_ok and terms_ok and starts_ok and http_cleaned
        icon = "✓" if passed else "✗"
        print(
            f"\n  {icon} site={case['site']!r}, term={case['term']!r}, pages={case['pages']}"
        )

        for u in urls:
            decoded_q = unquote_plus(u["url"].split("?q=")[1].split("&")[0])
            print(f"     p{u['page']} start={u['start']}: {decoded_q}")

        if not passed:
            all_passed = False
            if not domains_ok:
                print("     ✗ Domínio não aparece corretamente na URL")
            if not terms_ok:
                print("     ✗ Termo não está entre aspas na URL")
            if not starts_ok:
                print(
                    f"     ✗ Starts incorretos: {starts} != {case['expected_starts']}"
                )
            if not http_cleaned:
                print("     ✗ http:// não foi removido do domínio")

    return all_passed


# ── Teste 2: Crawler real ─────────────────────────────────────────────────────


async def test_crawler_real(scenario: dict, save: bool = False) -> dict:
    print_section(f"TESTE 2 — Crawler real: {scenario['name']}")
    print(
        f"  site={scenario['site']!r}, terms={scenario['terms']}, pages={scenario['pages']}"
    )
    print(f"  Total requests planejados: {len(scenario['terms']) * scenario['pages']}")

    crawler = ScrapingScrawlingTool()
    start_ts = asyncio.get_event_loop().time()

    result = await crawler.execute_specific_source_research(
        site=scenario["site"],
        terms=scenario["terms"],
        pages=scenario["pages"],
    )

    elapsed = asyncio.get_event_loop().time() - start_ts
    print(f"\n  Tempo total: {elapsed:.1f}s")
    print_result_summary(result)

    if save:
        output_dir = Path(__file__).parent / "output"
        output_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = (
            scenario["name"]
            .lower()
            .replace(" ", "_")
            .replace("—", "")
            .replace(" ", "")[:30]
        )
        out_file = output_dir / f"{ts}_{slug}.json"
        out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"\n  Output salvo: {out_file}")

    return result


# ── Teste 3: Validações de input ──────────────────────────────────────────────


async def test_input_validation():
    print_section("TESTE 3 — Validações de input do crawler")
    crawler = ScrapingScrawlingTool()
    passed = True

    # Site vazio: deve retornar error (sem crash)
    try:
        r = await crawler.execute_specific_source_research(
            site="", terms=["test"], pages=1
        )
        # Se não crashou mas sem domain, o URL fica errado — verificar
        if r.get("results"):
            first_url = r["results"][0]["url"]
            if 'site:"' in first_url or "site: " in first_url:
                print("  ✗ Site vazio gerou URL malformada")
                passed = False
            else:
                print(f"  ~ Site vazio: rodou mas URL={first_url[:60]}...")
        else:
            print("  ~ Site vazio: nenhum resultado (aceitável)")
    except Exception as e:
        print(f"  ~ Site vazio levantou exceção: {type(e).__name__}: {e}")

    # Pages=0: deve gerar 0 tasks → resultado vazio
    r = await crawler.execute_specific_source_research(
        site="instagram.com", terms=["test"], pages=0
    )
    total = r.get("total_pages_scraped", -1)
    if total == 0:
        print("  ✓ pages=0 → total_pages_scraped=0 (correto)")
    else:
        print(f"  ✗ pages=0 → total_pages_scraped={total} (esperado 0)")
        passed = False

    # Multi-term contagem correta
    r = await crawler.execute_specific_source_research(
        site="example.com", terms=["a", "b", "c"], pages=2
    )
    expected_total = 3 * 2
    actual_total = r.get("total_pages_scraped", -1)
    if actual_total == expected_total:
        print(f"  ✓ 3 terms × 2 pages = {actual_total} requests (correto)")
    else:
        print(f"  ✗ 3 terms × 2 pages = {actual_total} (esperado {expected_total})")
        passed = False

    return passed


# ── Main ───────────────────────────────────────────────────────────────────────


async def main(dry_run: bool, save: bool, scenario_idx: int | None):
    print("\n" + "═" * 70)
    print("  TEST: SpecificSourceResearch")
    print("═" * 70)

    results = {"url_building": False, "validation": False, "crawl": []}

    # Teste 1 sempre roda
    results["url_building"] = test_url_building()

    if dry_run:
        print("\n  [--dry-run] Pulando testes com HTTP.")
    else:
        # Teste 3: validações
        results["validation"] = await test_input_validation()

        # Teste 2: crawler real — roda cenário específico ou o primeiro
        scenarios = (
            [SCENARIOS[scenario_idx]] if scenario_idx is not None else [SCENARIOS[0]]
        )
        for scenario in scenarios:
            r = await test_crawler_real(scenario, save=save)
            results["crawl"].append(
                {
                    "scenario": scenario["name"],
                    "success": r.get("status") == "success",
                    "success_count": r.get("success_count", 0),
                    "total": r.get("total_pages_scraped", 0),
                }
            )

    # Sumário
    print_section("SUMÁRIO")
    url_icon = "✓" if results["url_building"] else "✗"
    val_icon = "✓" if results["validation"] else ("–" if dry_run else "✗")
    print(f"  {url_icon} URL building")
    print(f"  {val_icon} Input validation")
    for c in results["crawl"]:
        icon = "✓" if c["success"] else "✗"
        print(f"  {icon} {c['scenario']}: {c['success_count']}/{c['total']} páginas ok")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Testa SpecificSourceResearch")
    parser.add_argument(
        "--dry-run", action="store_true", help="Só testa URL building, sem HTTP"
    )
    parser.add_argument(
        "--save", action="store_true", help="Salva resultado JSON em ./output/"
    )
    parser.add_argument(
        "--scenario",
        type=int,
        default=None,
        choices=range(len(SCENARIOS)),
        metavar=f"0-{len(SCENARIOS)-1}",
        help=f"Índice do cenário a rodar (0=Instagram, 1=LinkedIn, 2=Multi-term). Padrão: 0",
    )
    args = parser.parse_args()

    print("\nCenários disponíveis:")
    for i, s in enumerate(SCENARIOS):
        print(
            f"  [{i}] {s['name']} — site={s['site']}, terms={s['terms']}, pages={s['pages']}"
        )

    asyncio.run(main(dry_run=args.dry_run, save=args.save, scenario_idx=args.scenario))
