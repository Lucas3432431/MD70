"""
Centralized health check for MD70 scripts.

Reads BACKEND_HOST, BACKEND_PORT, FRONTEND_HOST, FRONTEND_PORT (or VITE_DEV_PORT)
from the environment. The caller is responsible for loading the .env before calling
run_health_check(). URLs can also be passed explicitly to override env resolution.

Usage (standalone):
    cd App/mvp/services/backend
    python3 Scripts/HealthCheck/health_check.py
    python3 Scripts/HealthCheck/health_check.py --env-file .env.wsl

Usage (imported):
    from Scripts.HealthCheck.health_check import run_health_check

    # Reads BACKEND_HOST / BACKEND_PORT / FRONTEND_HOST / FRONTEND_PORT from env:
    run_health_check()
    run_health_check(check_frontend=False)   # backend only

    # Explicit override (env vars still validated for non-overridden side):
    run_health_check(backend_url="http://localhost:4001", check_frontend=False)
"""

import sys
import os
import requests
from pathlib import Path

SEP = "=" * 70


# ── HTTP probe ────────────────────────────────────────────────────────────────


def _probe(url: str, timeout: int = 5) -> tuple[bool, str]:
    """Returns (ok, description_message)."""
    try:
        response = requests.get(url, timeout=timeout)
        status = response.status_code
        body = response.text
        if status == 200:
            return True, f"HTTP 200  {body[:80]}"
        return False, f"HTTP {status}"
    except requests.exceptions.RequestException as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)


# ── ENV resolution ────────────────────────────────────────────────────────────


def _resolve_urls() -> tuple[str, str]:
    """
    Reads env vars (NO fallbacks) and returns (backend_url, frontend_url).
    Exits with a clear error listing every missing variable.
    """
    backend_host = os.environ.get("BACKEND_HOST")
    backend_port = os.environ.get("BACKEND_PORT")
    frontend_host = os.environ.get("FRONTEND_HOST")
    frontend_port = os.environ.get("VITE_DEV_PORT") or os.environ.get("FRONTEND_PORT")
    protocol = os.environ.get("VITE_HTTP_PROTOCOL", "http")

    missing = []
    if not backend_host:
        missing.append("BACKEND_HOST")
    if not backend_port:
        missing.append("BACKEND_PORT")
    if not frontend_host:
        missing.append("FRONTEND_HOST")
    if not frontend_port:
        missing.append("FRONTEND_PORT (or VITE_DEV_PORT)")

    if missing:
        print(f"\n{'!' * 70}")
        print(f"  CRITICAL ERROR: Missing required environment variables:")
        for var in missing:
            print(f"    - {var}")
        print(f"\n  Define these in your .env.development (or pass via --env-file).")
        print(f"{'!' * 70}\n")
        sys.exit(1)

    def _fix(url: str) -> str:
        # Resolve '0.0.0.0' to '127.0.0.1' to satisfy security audits and ensure local reachability
        return url.replace("0.0.0.0", "127.0.0.1")

    return (
        _fix(f"{protocol}://{backend_host}:{backend_port}"),
        _fix(f"{protocol}://{frontend_host}:{frontend_port}"),
    )


# ── Public API ────────────────────────────────────────────────────────────────


def run_health_check(
    backend_url: str | None = None,
    frontend_url: str | None = None,
    check_backend: bool = True,
    check_frontend: bool = True,
    exit_on_fail: bool = True,
) -> bool:
    """
    Checks backend (/api/health) and/or frontend (/health).

    If backend_url / frontend_url are not provided the function resolves them
    from environment variables (BACKEND_HOST, BACKEND_PORT, FRONTEND_HOST,
    FRONTEND_PORT / VITE_DEV_PORT). Missing vars cause an immediate exit.

    Returns True when all requested checks pass.
    Calls sys.exit(1) on failure when exit_on_fail=True.
    """
    print(f"\n{SEP}")
    print("  HEALTH CHECK")
    print(SEP)

    # Resolve missing URLs from env
    needs_env = (check_backend and not backend_url) or (
        check_frontend and not frontend_url
    )
    if needs_env:
        env_backend, env_frontend = _resolve_urls()
        if check_backend and not backend_url:
            backend_url = env_backend
        if check_frontend and not frontend_url:
            frontend_url = env_frontend

    results: list[bool] = []

    if check_backend and backend_url:
        url = f"{backend_url.rstrip('/')}/api/health"
        print(f"  Backend   →  {url}")
        ok, msg = _probe(url)
        if ok:
            print(f"  [OK]   {msg}")
        else:
            print(f"  [FAIL] {msg}")
            print(
                f"         Backend não está disponível. Inicie o serviço antes de continuar."
            )
        results.append(ok)

    if check_frontend and frontend_url:
        url = f"{frontend_url.rstrip('/')}/health"
        print(f"  Frontend  →  {url}")
        ok, msg = _probe(url)
        if ok:
            print(f"  [OK]   {msg}")
        else:
            print(f"  [FAIL] {msg}")
            print(
                f"         Frontend não está disponível. Inicie o serviço antes de continuar."
            )
        results.append(ok)

    all_ok = all(results) if results else False

    if not all_ok:
        print(f"\n{'!' * 70}")
        print("  Os serviços acima precisam estar rodando para este script funcionar.")
        print(f"{'!' * 70}\n")
        if exit_on_fail:
            sys.exit(1)

    print(f"{SEP}\n")
    return all_ok


# ── Standalone ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv

    BACKEND_DIR = Path(__file__).parent.parent.parent.absolute()

    _parser = argparse.ArgumentParser(description="MD70 health check")
    _parser.add_argument(
        "--env-file",
        default=None,
        help="Path to .env file (default: mvp/.env.development)",
    )
    _parser.add_argument("--backend-only", action="store_true")
    _parser.add_argument("--frontend-only", action="store_true")
    _args = _parser.parse_args()

    # Load base env
    _mvp_env = BACKEND_DIR.parent.parent / ".env.development"
    if _mvp_env.exists():
        load_dotenv(dotenv_path=str(_mvp_env), override=True)
        print(f"  Loaded env: {_mvp_env}")
    else:
        print(f"  ⚠️  .env.development not found at {_mvp_env}")

    # Apply override if provided
    if _args.env_file:
        _override = Path(_args.env_file)
        if _override.exists():
            load_dotenv(dotenv_path=str(_override), override=True)
            print(f"  Override env: {_override}")
        else:
            print(f"  ⚠️  --env-file not found: {_override}")

    run_health_check(
        check_backend=not _args.frontend_only,
        check_frontend=not _args.backend_only,
    )
