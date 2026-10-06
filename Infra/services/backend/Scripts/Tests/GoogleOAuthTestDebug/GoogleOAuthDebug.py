import os
import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime

# Adicionar o diretório root do backend ao sys.path para importar as Features
BACKEND_DIR = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from App.Core.Settings.Settings import load_config
from App.Features.Auth.AuthService import AuthConfig, AuthService
from App.Core.Logs import info, error, debug


async def run_debug():
    output_dir = Path(__file__).parent / "outputs"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = output_dir / f"debug_results_{timestamp}.json"

    results = {
        "timestamp": timestamp,
        "env_check": {},
        "config_check": {},
        "backend_logic_test": {},
    }

    print("\n\n" + "=" * 60)
    print("🔍 INICIANDO DEBUG DO GOOGLE OAUTH")
    print("=" * 60 + "\n")

    # 1. Verificar Variáveis de Ambiente Brutas
    print("Step 1: Verificando variáveis de ambiente no OS...")
    results["env_check"] = {
        "GOOGLE_AUTH_CLIENT_ID": os.environ.get("GOOGLE_AUTH_CLIENT_ID", "MISSING")[:20]
        + "...",
        "GOOGLE_AUTH_CLIENT_SECRET": (
            "PRESENT" if os.environ.get("GOOGLE_AUTH_CLIENT_SECRET") else "MISSING"
        ),
        "ENV_FILE": os.environ.get("ENV_FILE", "Not Set"),
    }

    # 2. Verificar o que o Settings.py está carregando
    print("Step 2: Verificando carregamento via Settings.py...")
    config = load_config()
    client_id = AuthConfig.get_google_client_id()
    secret = AuthConfig.get_google_client_secret()

    masked_secret = (
        f"{secret[:10]}...{secret[-10:]}"
        if secret and len(secret) > 20
        else "TOO SHORT OR EMPTY"
    )

    results["config_check"] = {
        "loaded_client_id": client_id,
        "has_secret": bool(secret),
        "secret_length": len(secret) if secret else 0,
        "masked_secret": masked_secret,
        "callback_urls": config.get("google_callback_urls", []),
        "auth_callback_url": config.get("google_auth_callback_url", "Not Set"),
    }

    print(f"\n--- CREDENCIAIS CARREGADAS ---")
    print(f"ID: {client_id}")
    print(f"Secret (Mascarado): {masked_secret}")
    print(f"Comprimento do Secret: {len(secret) if secret else 0} caracteres")
    print(f"------------------------------\n")

    # 3. Teste de Lógica de Callback (Simulado)
    print("Step 3: Testando lógica de tentativa de URLs...")
    # Aqui simulamos o que acontece quando um código chega
    test_code = "4/simulated_code_for_debug_purposes"

    # Vamos interceptar os requests para ver o que seria enviado
    print("\n--- Verificação de Segurança ---")
    secret = AuthConfig.get_google_client_secret()
    if secret:
        if secret.startswith("'") or secret.startswith('"'):
            print("✅ Secret está protegido por aspas.")
        if "#" in secret:
            print(
                "⚠️ ATENÇÃO: Caractere '#' detectado no Secret. Isso pode causar problemas se não houver aspas."
            )
    else:
        print("❌ CRÍTICO: GOOGLE_AUTH_CLIENT_SECRET está vazio!")

    # 4. Instruções para o Usuário
    print("\n" + "=" * 60)
    print("💡 PRÓXIMOS PASSOS:")
    print("1. Se 'has_secret' for False, seu .env não está sendo lido.")
    print("2. Verifique se o REDIRECT_URI no console do Google é:")
    print(f"   http://localhost:5082/auth/callback")
    print(f"   OU o valor especial: postmessage")
    print("=" * 60 + "\n")

    # Salvar resultados
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4)

    print(f"✅ Resultados salvos em: {log_file}")


if __name__ == "__main__":
    asyncio.run(run_debug())
