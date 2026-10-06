"""
Script para obter o GOOGLE_REFRESH_TOKEN do Gmail.
Instruções:
1. Rode o script.
2. Acesse o link gerado no seu navegador.
3. Logue com sua conta lucasc.camargo0701@gmail.com.
4. Autorize o acesso.
5. Copie o 'Authorization Code' e cole aqui no terminal.
6. O script vai imprimir o REFRESH_TOKEN para você colocar no seu .env.
"""

import os
import sys
from pathlib import Path

# Adicionar o diretório backend ao PYTHONPATH
current_dir = Path(__file__).resolve().parent  # Tools
scripts_dir = current_dir.parent  # Scripts
backend_dir = scripts_dir.parent  # backend
sys.path.append(str(backend_dir))

from google_auth_oauthlib.flow import InstalledAppFlow
from App.Core.Settings.Settings import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_AUTH_CLIENT_ID,
    GOOGLE_AUTH_CLIENT_SECRET,
)


def get_refresh_token():
    print("=== Gerador de Google Refresh Token (Gmail) ===")

    # Tentar usar o par de chaves 'AUTH' primeiro, pois ele tem as URLs configuradas
    cid = GOOGLE_AUTH_CLIENT_ID or GOOGLE_CLIENT_ID
    sec = GOOGLE_AUTH_CLIENT_SECRET or GOOGLE_CLIENT_SECRET

    if not cid or not sec:
        print("❌ ERRO: Credenciais do Google não configuradas no .env")
        return

    print(f"Usando Client ID: {cid[:15]}...")

    # Definir o escopo necessário (envio de e-mail)
    SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

    client_config = {
        "web": {
            "client_id": cid,
            "client_secret": sec,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

    try:
        flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)

        # DEFINIR REDIRECT URI AUTORIZADA (deve estar no seu Google Console)
        # Usando a do localhost que você enviou
        flow.redirect_uri = "http://localhost:5082/auth/callback"

        # Gerar URL de autorização
        auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")

        print("\n1. Acesse o link abaixo no seu navegador:")
        print(f"\033[94m{auth_url}\033[0m")

        print(
            "\n2. Após autorizar, o navegador vai te levar para uma página de erro ou branca."
        )
        print(
            "3. COPIE o valor do parâmetro 'code' que aparecerá na BARRA DE ENDEREÇO do navegador."
        )
        print(
            "   Exemplo: http://localhost:5082/auth/callback?code=4/0AfgeX...&scope=..."
        )

        auth_code = input("\n4. Cole o valor do 'code' aqui: ").strip()

        # Trocar código pelo token
        flow.fetch_token(code=auth_code)
        credentials = flow.credentials

        print("\n✅ SUCESSO! Sua 'Chave SSH' foi gerada:")
        print("-" * 50)
        print(f"\033[92mGOOGLE_REFRESH_TOKEN={credentials.refresh_token}\033[0m")
        print("-" * 50)
        print("\nCopie a linha acima e adicione ao seu arquivo .env.development")

    except Exception as e:
        print(f"\n❌ Ocorreu um erro: {e}")


if __name__ == "__main__":
    get_refresh_token()
