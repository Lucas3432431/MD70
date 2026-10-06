#!/usr/bin/env python3
"""
CheckDeadEnvVars.py
Verifica variáveis de ambiente declaradas no .env que não são usadas
em nenhum arquivo Python ou TypeScript do projeto.

Uso:
    python Scripts/Tools/CheckDeadEnvVars.py
    python Scripts/Tools/CheckDeadEnvVars.py --env ../../.env.development
    python Scripts/Tools/CheckDeadEnvVars.py --show-used
"""

import argparse
import os
import re
import sys
from pathlib import Path
from collections import defaultdict

# Raiz do projeto (services/backend)
BACKEND_ROOT = Path(__file__).parent.parent.parent
MVP_ROOT = BACKEND_ROOT.parent.parent  # App/mvp

# Arquivos/pastas ignorados na busca
IGNORE_DIRS = {
    "__pycache__",
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
}
IGNORE_FILES = {".env", ".env.development", ".env.production", ".env.example"}

ENV_FILE_DEFAULT = MVP_ROOT / ".env.development"


def parse_env_file(env_path: Path) -> dict[str, str]:
    """Lê todas as variáveis do arquivo .env e retorna {VAR: valor}."""
    vars_ = {}
    if not env_path.exists():
        print(f"[ERRO] Arquivo não encontrado: {env_path}")
        sys.exit(1)
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key = line.split("=", 1)[0].strip()
            val = line.split("=", 1)[1].strip()
            vars_[key] = val
    return vars_


def collect_source_files(roots: list[Path]) -> list[Path]:
    """Coleta todos os arquivos .py e .ts/.tsx a partir das raízes."""
    files = []
    for root in roots:
        for path in root.rglob("*"):
            if any(part in IGNORE_DIRS for part in path.parts):
                continue
            if path.name in IGNORE_FILES:
                continue
            if path.suffix in (".py", ".ts", ".tsx", ".js", ".jsx"):
                files.append(path)
    return files


def find_usages(var_name: str, source_files: list[Path]) -> list[str]:
    """Retorna lista de caminhos relativos onde a variável é referenciada."""
    usages = []
    patterns = [
        re.compile(rf"\b{re.escape(var_name)}\b"),
        re.compile(rf'["\']' + re.escape(var_name) + r'["\']'),
        re.compile(rf"process\.env\.{re.escape(var_name)}"),
        re.compile(
            rf'import\.meta\.env\.VITE_{re.escape(var_name.replace("VITE_", ""))}'
            if var_name.startswith("VITE_")
            else r"(?!x)x"
        ),
    ]
    for path in source_files:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            if any(p.search(content) for p in patterns):
                usages.append(str(path))
        except Exception:
            pass
    return usages


def main():
    parser = argparse.ArgumentParser(
        description="Detecta env vars declaradas mas não usadas no código"
    )
    parser.add_argument(
        "--env", default=str(ENV_FILE_DEFAULT), help="Caminho do arquivo .env"
    )
    parser.add_argument(
        "--show-used",
        action="store_true",
        help="Também mostra vars usadas com seus arquivos",
    )
    parser.add_argument(
        "--min-refs",
        type=int,
        default=0,
        help="Reportar vars com menos de N referências (default: 0 = só as sem nenhuma)",
    )
    args = parser.parse_args()

    env_path = Path(args.env)
    print(f"Lendo env vars de: {env_path}")

    env_vars = parse_env_file(env_path)
    print(f"Total de vars declaradas: {len(env_vars)}\n")

    # Raízes de busca: backend Python + frontend TS
    search_roots = [
        BACKEND_ROOT / "App",
        MVP_ROOT / "services" / "frontend" / "src",
    ]
    source_files = collect_source_files(search_roots)
    print(f"Arquivos fonte indexados: {len(source_files)}\n")

    dead: list[tuple[str, str]] = []  # (var, valor)
    low_refs: list[tuple[str, list[str]]] = []  # (var, [files])
    used: list[tuple[str, list[str]]] = []

    for var, val in sorted(env_vars.items()):
        refs = find_usages(var, source_files)
        if not refs:
            dead.append((var, val[:40] + "..." if len(val) > 40 else val))
        elif args.min_refs and len(refs) <= args.min_refs:
            low_refs.append((var, refs))
        else:
            used.append((var, refs))

    # --- Resultados ---
    print("=" * 60)
    print(f"  VARS SEM NENHUMA REFERÊNCIA NO CÓDIGO ({len(dead)})")
    print("=" * 60)
    if dead:
        for var, val in dead:
            print(f"  ❌  {var:<45} = {val}")
    else:
        print("  Nenhuma — todas as vars têm pelo menos uma referência.")

    if args.min_refs and low_refs:
        print(f"\n{'=' * 60}")
        print(f"  VARS COM ≤ {args.min_refs} REFERÊNCIAS ({len(low_refs)})")
        print("=" * 60)
        for var, refs in low_refs:
            print(f"  ⚠️  {var}")
            for f in refs:
                rel = os.path.relpath(f, MVP_ROOT)
                print(f"       → {rel}")

    if args.show_used and used:
        print(f"\n{'=' * 60}")
        print(f"  VARS EM USO ({len(used)})")
        print("=" * 60)
        for var, refs in used:
            print(f"  ✅  {var:<45} ({len(refs)} arquivo(s))")

    print(
        f"\nResumo: {len(dead)} mortas | {len(low_refs)} pouco usadas | {len(used)} ativas"
    )


if __name__ == "__main__":
    main()
