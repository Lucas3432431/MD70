"""
Validação do Terminal Sandbox — API atual.

A API mudou de language/code para shell (Fase 1) e command (Fase 2 HTTP).

Cenários:
  Python:
    P1. Saída simples via heredoc            → stdout correto
    P2. Cálculo com stdlib                   → resultado correto
    P3. JSON parse + transformação           → resultado correto
    P4. Timeout (loop infinito)              → erro de timeout, não trava
    P5. Sem acesso a env do backend          → variáveis sensíveis ausentes
    P6. Sem acesso a /app (código backend)   → negado

  curl:
    C1. Endpoint HTTPS público               → exit_code 0
    C2. IP interno 127.0.0.1 bloqueado       → bloqueado
    C3. localhost bloqueado                  → bloqueado
    C4. file:// bloqueado                    → bloqueado

  Isolamento:
    I1. User A cria arquivo secreto          → OK
    I2. User B não vê arquivo do User A      → isolado
    I3. User B não lê arquivo do User A      → acesso negado

  Fase 2 (HTTP service):
    H1. /health                              → {"status": "ok"}
    H2. /execute Python via HTTP             → sucesso
    H3. /execute curl externo via HTTP       → sucesso (ou skip se sem rede)
    H4. Blacklist via HTTP                   → bloqueado

Uso:
    # Fase 1 apenas (sem container)
    python Scripts/Tests/Sandbox/test_sandbox.py

    # Fase 1 + Fase 2
    python Scripts/Tests/Sandbox/test_sandbox.py --sandbox-url http://localhost:8001

    # SANDBOX_URL do .env é usada automaticamente se definida
"""

import sys
import os
import json
import argparse

_BACKEND_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../..")
)
os.chdir(_BACKEND_ROOT)

import importlib.util as _ilu

_spec = _ilu.spec_from_file_location(
    "_sandbox",
    os.path.join(_BACKEND_ROOT, "App/Features/Tools/_sandbox.py"),
)
_sandbox_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_sandbox_mod)
SandboxMixin = _sandbox_mod.SandboxMixin
_ENV_SANDBOX_URL = _sandbox_mod.SANDBOX_URL

PASS = "    OK"
FAIL = "    *** FALHA ***"
SKIP = "    --"

_results: list[bool] = []


def _ok(label: str) -> bool:
    print(f"{PASS}: {label}")
    _results.append(True)
    return True


def _fail(label: str, detail: str = "") -> bool:
    suffix = f" | {detail}" if detail else ""
    print(f"{FAIL}: {label}{suffix}")
    _results.append(False)
    return False


def _skip(label: str, reason: str = "") -> None:
    suffix = f" ({reason})" if reason else ""
    print(f"{SKIP}: {label}{suffix}")


def _parse(raw: str) -> dict:
    try:
        return json.loads(raw)
    except Exception:
        return {"_raw": raw}


class _FakeSandbox(SandboxMixin):
    current_user_id = "test-sandbox-user"


class _FakeSandboxB(SandboxMixin):
    current_user_id = "test-sandbox-user-B"


_sb = _FakeSandbox()
_sb2 = _FakeSandboxB()


# ─── Python ───────────────────────────────────────────────────────────────────


def test_p1_saida_simples():
    print("\n── P1: Python — saída simples (heredoc) ─────────────────────")
    res = _parse(_sb._execute_terminal({"shell": "python3 -c \"print('sandbox_ok')\""}))
    if res.get("success") and "sandbox_ok" in (res.get("stdout") or ""):
        return _ok("stdout contém 'sandbox_ok'")
    return _fail("saída inesperada", json.dumps(res)[:300])


def test_p2_calculo_stdlib():
    print("\n── P2: Python — cálculo com stdlib ──────────────────────────")
    res = _parse(
        _sb._execute_terminal(
            {"shell": 'python3 -c "import math; print(round(math.sqrt(144), 2))"'}
        )
    )
    if res.get("success") and "12.0" in (res.get("stdout") or ""):
        return _ok("resultado correto: 12.0")
    return _fail("cálculo incorreto", json.dumps(res)[:300])


def test_p3_json_transform():
    print("\n── P3: Python — JSON parse + transformação (heredoc) ────────")
    shell = (
        "cat > /tmp/_test_p3.py << 'EOF'\n"
        "import json\n"
        'data = [{"v": 10}, {"v": 20}, {"v": 30}]\n'
        "print(sum(d['v'] for d in data))\n"
        "EOF\n"
        "python3 /tmp/_test_p3.py"
    )
    res = _parse(_sb._execute_terminal({"shell": shell}))
    if res.get("success") and "60" in (res.get("stdout") or ""):
        return _ok("soma correta: 60")
    return _fail("transformação incorreta", json.dumps(res)[:300])


def test_p4_timeout():
    print("\n── P4: Python — timeout (loop infinito) ─────────────────────")
    orig = _sandbox_mod.SANDBOX_TIMEOUT
    _sandbox_mod.SANDBOX_TIMEOUT = 2
    try:
        res = _parse(_sb._execute_terminal({"shell": 'python3 -c "while True: pass"'}))
    finally:
        _sandbox_mod.SANDBOX_TIMEOUT = orig
    if not res.get("success") and "Timeout" in (res.get("error") or ""):
        return _ok("timeout detectado corretamente")
    return _fail("timeout não foi detectado", json.dumps(res)[:300])


def test_p5_env_isolado():
    print("\n── P5: Python — sem acesso a env do backend ─────────────────")
    shell = (
        'python3 -c "'
        "import os, json; "
        "keys = list(os.environ.keys()); "
        "leaked = [k for k in keys if any(s in k.upper() for s in "
        "['SECRET', 'TOKEN', 'API_KEY', 'PASSWORD', 'DATABASE'])]; "
        "print(json.dumps({'leaked': leaked, 'total': len(keys)}))\""
    )
    res = _parse(_sb._execute_terminal({"shell": shell}))
    if not res.get("success"):
        return _fail("execução falhou", json.dumps(res)[:300])
    try:
        out = json.loads(res.get("stdout", "{}"))
        leaked = out.get("leaked", [])
        if leaked:
            return _fail(f"variáveis sensíveis vazaram: {leaked}")
        return _ok(f"nenhum env sensível exposto ({out.get('total')} vars)")
    except Exception as e:
        return _fail(f"parse do stdout falhou: {e}", res.get("stdout", "")[:200])


def test_p6_sem_acesso_backend():
    print("\n── P6: Python — sem acesso ao código do backend ─────────────")
    shell = (
        'python3 -c "'
        "try:\\n"
        "    f = open('/app/App/Core/Settings/Settings.py')\\n"
        "    print('LEAK:' + f.read(20))\\n"
        "except Exception as e:\\n"
        "    print(f'bloqueado: {e}')\""
    )
    res = _parse(_sb._execute_terminal({"shell": shell}))
    stdout = res.get("stdout") or ""
    stderr = res.get("stderr") or ""
    if "LEAK:" in stdout:
        return _fail(
            "arquivo do backend lido — sandbox NÃO está isolado!", stdout[:200]
        )
    return _ok("acesso ao /app negado corretamente")


# ─── curl ─────────────────────────────────────────────────────────────────────


def test_c1_https_publico():
    print("\n── C1: curl — endpoint HTTPS público ───────────────────────")
    res = _parse(
        _sb._execute_terminal(
            {"shell": "curl -s --max-time 10 https://httpbin.org/get"}
        )
    )
    _NO_NET = {6, 7, 28, 35, 52, 56}
    if res.get("success") and res.get("exit_code") == 0:
        return _ok("curl público executou com exit_code=0")
    if res.get("success") and res.get("exit_code") in _NO_NET:
        _skip(
            "C1",
            f"sem acesso à internet (exit_code={res.get('exit_code')}) — sandbox OK",
        )
        return True
    if not res.get("success") and "Timeout" in (res.get("error") or ""):
        _skip("C1", "timeout de rede — ignorado em ambiente sem internet")
        return True
    return _fail("curl público falhou inesperadamente", json.dumps(res)[:300])


def test_c2_ip_interno_bloqueado():
    print("\n── C2: curl — IP interno 127.0.0.1 bloqueado ───────────────")
    res = _parse(_sb._execute_terminal({"shell": "curl http://127.0.0.1:8000/health"}))
    if not res.get("success") and "bloqueado" in (res.get("error") or "").lower():
        return _ok("127.0.0.1 bloqueado")
    return _fail("IP interno não foi bloqueado", json.dumps(res)[:300])


def test_c3_localhost_bloqueado():
    print("\n── C3: curl — localhost bloqueado ───────────────────────────")
    res = _parse(_sb._execute_terminal({"shell": "curl http://localhost/api/health"}))
    if not res.get("success") and "bloqueado" in (res.get("error") or "").lower():
        return _ok("localhost bloqueado")
    return _fail("localhost não foi bloqueado", json.dumps(res)[:300])


def test_c4_file_bloqueado():
    print("\n── C4: curl — file:// bloqueado ─────────────────────────────")
    res = _parse(_sb._execute_terminal({"shell": "curl file:///etc/passwd"}))
    if not res.get("success") and "bloqueado" in (res.get("error") or "").lower():
        return _ok("file:// bloqueado")
    return _fail("file:// não foi bloqueado", json.dumps(res)[:300])


# ─── Isolamento ───────────────────────────────────────────────────────────────


def test_i1_user_a_cria_arquivo():
    print("\n── I1: Isolamento — User A cria arquivo secreto ─────────────")
    res = _parse(
        _sb._execute_terminal(
            {"shell": "echo 'SENHA_SECRETA_123' > segredo.txt && ls segredo.txt"}
        )
    )
    if res.get("success") and "segredo.txt" in (res.get("stdout") or ""):
        return _ok("User A criou segredo.txt com sucesso")
    return _fail("User A falhou ao criar arquivo", json.dumps(res)[:300])


def test_i2_user_b_nao_ve_arquivo():
    print("\n── I2: Isolamento — User B não lista arquivo do User A ──────")
    res = _parse(_sb2._execute_terminal({"shell": "ls"}))
    stdout = res.get("stdout") or ""
    if "segredo.txt" in stdout:
        return _fail(
            "FALHA DE ISOLAMENTO: User B conseguiu listar segredo.txt do User A!",
            stdout,
        )
    return _ok("User B não vê arquivos do User A")


def test_i3_user_b_nao_le_arquivo():
    print("\n── I3: Isolamento — User B não lê arquivo do User A ─────────")
    res = _parse(_sb2._execute_terminal({"shell": "cat segredo.txt"}))
    if res.get("exit_code") == 0 and "SENHA_SECRETA" in (res.get("stdout") or ""):
        return _fail("FALHA DE ISOLAMENTO: User B leu segredo.txt do User A!")
    return _ok("User B não conseguiu ler segredo.txt do User A")


# ─── Fase 2 — HTTP ────────────────────────────────────────────────────────────


def test_h1_health(sandbox_url: str):
    print("\n── H1: Fase 2 — /health ─────────────────────────────────────")
    import urllib.request as _r

    try:
        with _r.urlopen(f"{sandbox_url}/health", timeout=5) as resp:
            data = json.loads(resp.read())
            if data.get("status") == "ok":
                return _ok(f"serviço respondeu {data}")
            return _fail("status inesperado", str(data))
    except Exception as e:
        return _fail(f"não foi possível conectar ({sandbox_url})", str(e))


def test_h2_execute_python(sandbox_url: str):
    print("\n── H2: Fase 2 — /execute Python via HTTP ────────────────────")
    import urllib.request as _r

    payload = json.dumps(
        {"command": 'python3 -c "print(2 ** 10)"', "user_id": "test-h2"}
    ).encode()
    try:
        req = _r.Request(
            f"{sandbox_url}/execute",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _r.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            if data.get("success") and "1024" in (data.get("stdout") or ""):
                return _ok("Python via HTTP retornou 1024")
            return _fail("resultado inesperado", json.dumps(data)[:300])
    except Exception as e:
        return _fail("requisição HTTP falhou", str(e))


def test_h3_execute_curl(sandbox_url: str):
    print("\n── H3: Fase 2 — /execute curl externo via HTTP ──────────────")
    import urllib.request as _r

    payload = json.dumps(
        {
            "command": "curl -s --max-time 10 https://httpbin.org/get",
            "user_id": "test-h3",
        }
    ).encode()
    try:
        req = _r.Request(
            f"{sandbox_url}/execute",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _r.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read())
        _NO_NET = {6, 7, 28, 35, 52, 56}
        if data.get("success") and data.get("exit_code") == 0:
            return _ok("curl via HTTP executou com exit_code=0")
        if data.get("success") and data.get("exit_code") in _NO_NET:
            _skip("H3", f"sem acesso à internet (exit_code={data.get('exit_code')})")
            return True
        if not data.get("success") and "Timeout" in (data.get("error") or ""):
            _skip("H3", "timeout de rede — ignorado")
            return True
        return _fail("resultado inesperado", json.dumps(data)[:300])
    except Exception as e:
        return _fail("requisição HTTP falhou", str(e))


def test_h4_blacklist_via_http(sandbox_url: str):
    print("\n── H4: Fase 2 — blacklist 127.0.0.1 via HTTP ───────────────")
    import urllib.request as _r

    payload = json.dumps(
        {
            "command": "curl http://127.0.0.1:8000/health",
            "user_id": "test-h4",
        }
    ).encode()
    try:
        req = _r.Request(
            f"{sandbox_url}/execute",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _r.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if not data.get("success") and "bloqueado" in (data.get("error") or "").lower():
            return _ok("blacklist funcionou via HTTP")
        return _fail("blacklist não bloqueou via HTTP", json.dumps(data)[:300])
    except Exception as e:
        return _fail("requisição HTTP falhou", str(e))


# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Validação do Terminal Sandbox")
    parser.add_argument(
        "--sandbox-url",
        default=_ENV_SANDBOX_URL or "",
        help="URL do serviço sandbox Fase 2 (ex: http://localhost:8001). "
        "Se omitido e SANDBOX_URL não estiver definida, testes H* são pulados.",
    )
    args = parser.parse_args()
    sandbox_url = args.sandbox_url.rstrip("/")

    print("=" * 60)
    print("  Validação do Terminal Sandbox")
    print("  Fase 1 (subprocess local) + Fase 2 (HTTP)")
    print("=" * 60)

    print("\n=== FASE 1: PYTHON ===")
    test_p1_saida_simples()
    test_p2_calculo_stdlib()
    test_p3_json_transform()
    test_p4_timeout()
    test_p5_env_isolado()
    test_p6_sem_acesso_backend()

    print("\n=== FASE 1: CURL ===")
    test_c1_https_publico()
    test_c2_ip_interno_bloqueado()
    test_c3_localhost_bloqueado()
    test_c4_file_bloqueado()

    print("\n=== FASE 1: ISOLAMENTO ENTRE USUÁRIOS ===")
    test_i1_user_a_cria_arquivo()
    test_i2_user_b_nao_ve_arquivo()
    test_i3_user_b_nao_le_arquivo()

    print("\n=== FASE 2: HTTP ===")
    if sandbox_url:
        test_h1_health(sandbox_url)
        test_h2_execute_python(sandbox_url)
        test_h3_execute_curl(sandbox_url)
        test_h4_blacklist_via_http(sandbox_url)
    else:
        print(f"{SKIP}: testes H* pulados — use --sandbox-url http://localhost:8001")

    print()
    total = len(_results)
    passed = sum(_results)
    failed = total - passed
    print("=" * 60)
    if failed == 0:
        print(f"  TODOS OS TESTES PASSARAM ✓  ({passed}/{total})")
    else:
        print(f"  {failed} FALHA(S) de {total} testes ✗  ({passed} OK)")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
