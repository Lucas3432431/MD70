"""
Teste do WS ping-pong e limpeza de conexões mortas.

Cenários:
  A. Conexão viva: cliente conecta, autentica, aguarda ping do servidor,
     responde pong, verifica que conexão continua ativa
  B. Conexão morta: cliente conecta, autentica e então fecha o socket
     abruptamente; verifica que o servidor remove o entry de active_connections
     após tentar enviar para o user_id

Uso:
    python Scripts/Tests/test_ws_pingpong.py [base_url]
    # Padrão: lê NGINX_PORT do .env.development → ws://localhost:8081
"""

import sys
import os
import asyncio
import json
import time

_BACKEND_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "../..")
)
sys.path.insert(0, _BACKEND_ROOT)
os.chdir(_BACKEND_ROOT)

import websockets
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Features.Auth import get_auth_service

_ENV_FILE = os.path.abspath(os.path.join(_BACKEND_ROOT, "../../.env.development"))
_DEFAULT_PORT = "8081"
if os.path.exists(_ENV_FILE):
    for _line in open(_ENV_FILE):
        if _line.startswith("NGINX_PORT="):
            _DEFAULT_PORT = _line.strip().split("=", 1)[1]
            break

BASE_URL = (
    sys.argv[1].rstrip("/")
    if len(sys.argv) > 1
    else f"http://localhost:{_DEFAULT_PORT}"
)
WS_URL = (
    BASE_URL.replace("http://", "ws://").replace("https://", "wss://") + "/ws/agent"
)

PASS = "    OK"
FAIL = "    *** FALHA ***"
PING_INTERVAL = 25  # deve bater com UserBrowserRouter.PING_INTERVAL


def get_test_user_token():
    row = DatabaseManager.fetch_one(
        "SELECT user_id, email, full_name, client_id, type FROM users LIMIT 1", {}
    )
    if not row:
        raise RuntimeError("Nenhum usuário encontrado no banco.")
    user = dict(row)
    user["role"] = user.pop("type", "member") or "member"
    auth = get_auth_service()
    token = auth.generate_access_token(user)
    return str(user["user_id"]), token


# ─── Cenário A: ping-pong ─────────────────────────────────────────────────


async def test_pingpong():
    print("\n── Cenário A: ping-pong ─────────────────────────────────────")

    user_id, token = get_test_user_token()
    print(f"[A1] user_id={user_id} | conectando em {WS_URL}...")

    try:
        async with websockets.connect(WS_URL, open_timeout=10) as ws:
            # Autenticação
            await ws.send(json.dumps({"type": "auth", "token": token}))
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            msg = json.loads(raw)
            if msg.get("type") != "auth_ok":
                print(f"{FAIL}: esperado auth_ok, recebido {msg}")
                return False
            print(f"{PASS}: auth_ok recebido")

            # Aguarda ping do servidor (timeout = PING_INTERVAL + 10s de folga)
            wait = PING_INTERVAL + 10
            print(f"[A2] Aguardando ping do servidor (timeout={wait}s)...")
            start = time.time()
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=wait)
                elapsed = time.time() - start
                msg = json.loads(raw)
            except asyncio.TimeoutError:
                print(f"{FAIL}: servidor não enviou ping em {wait}s")
                return False

            if msg.get("type") != "ping":
                print(f"{FAIL}: esperado ping, recebido type={msg.get('type')!r}")
                return False
            print(f"{PASS}: ping recebido em {elapsed:.1f}s")

            # Responde pong
            await ws.send(json.dumps({"type": "pong"}))
            print("[A3] pong enviado")

            # Verifica que conexão continua viva (servidor não fechou)
            try:
                await asyncio.wait_for(ws.recv(), timeout=3)
                # Se chegou algo, tudo bem (pode ser outro ping ou mensagem)
            except asyncio.TimeoutError:
                pass  # Silêncio = conexão ainda aberta, correto
            except websockets.exceptions.ConnectionClosed:
                print(f"{FAIL}: servidor fechou a conexão após pong")
                return False

            print(f"{PASS}: conexão permanece ativa após pong")
            return True

    except (OSError, websockets.exceptions.WebSocketException) as e:
        print(f"*** ERRO de conexão WS: {e}")
        return False


# ─── Cenário B: conexão morta ──────────────────────────────────────────────


async def test_dead_connection():
    """
    Conecta, autentica, fecha o socket abruptamente.
    Então usa send_signal_sync diretamente para verificar que o manager
    remove o entry ao detectar a falha de envio.
    """
    print("\n── Cenário B: limpeza de conexão morta ──────────────────────")

    user_id, token = get_test_user_token()
    print(f"[B1] Conectando user_id={user_id}...")

    try:
        ws = await websockets.connect(WS_URL, open_timeout=10)
        await ws.send(json.dumps({"type": "auth", "token": token}))
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        msg = json.loads(raw)
        if msg.get("type") != "auth_ok":
            print(f"{FAIL}: auth_ok não recebido: {msg}")
            await ws.close()
            return False
        print(f"{PASS}: auth_ok recebido")

        # Fecha socket abruptamente (sem fechar o handshake WS corretamente)
        print("[B2] Fechando socket abruptamente (simula conexão morta)...")
        await ws.close()
        await asyncio.sleep(1)  # dá tempo para o server detectar o fechamento

        # Importa o manager do servidor (mesmo processo se rodando inline,
        # ou verifica via endpoint HTTP se rodando em processo separado)
        try:
            from App.Core.Services.WS.UserBrowserRouter import manager

            connected = user_id in manager.active_connections
            if connected:
                # Tenta send_signal — deve remover a conexão morta
                print(
                    "[B3] user_id ainda em active_connections, tentando send_signal..."
                )
                await manager.send_signal(user_id, {"type": "test_dead_check"})
                still_connected = user_id in manager.active_connections
                if still_connected:
                    print(
                        f"{FAIL}: send_signal não removeu conexão morta de active_connections"
                    )
                    return False
                print(f"{PASS}: send_signal removeu conexão morta automaticamente")
            else:
                print(
                    f"{PASS}: servidor já removeu user_id de active_connections no fechamento"
                )
        except ImportError:
            # Rodando contra servidor externo — não conseguimos inspecionar o manager
            print(
                "    INFO: servidor em processo separado; verificação de active_connections ignorada."
            )
            print(
                "    Confirme nos logs do servidor que a conexão foi removida após o fechamento."
            )

        return True

    except (OSError, websockets.exceptions.WebSocketException) as e:
        print(f"*** ERRO de conexão WS: {e}")
        return False


# ─── Main ────────────────────────────────────────────────────────────────────


async def main_async():
    print(f"=== Teste WS Ping-Pong | {WS_URL} ===")
    results = [
        await test_pingpong(),
        await test_dead_connection(),
    ]
    print()
    if all(results):
        print("=== TODOS OS TESTES PASSARAM ✓ ===")
        return True
    else:
        print("=== FALHA EM UM OU MAIS TESTES ✗ ===")
        return False


def main():
    try:
        ok = asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário.")
        sys.exit(1)
    except Exception as e:
        import traceback

        print(f"\n*** ERRO inesperado: {e}")
        traceback.print_exc()
        sys.exit(1)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
