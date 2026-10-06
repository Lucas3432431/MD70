import requests
import argparse
import sys


def check_balance(api_key):
    url = "https://api.deepseek.com/user/balance"
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}

    try:
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            data = response.json()
            if not data.get("is_available"):
                print("⚠️  Aviso: Sua conta consta como indisponível para uso.")

            print("\n=== Saldo DeepSeek ===")
            for info in data.get("balance_infos", []):
                currency = info.get("currency")
                total = info.get("total_balance")
                granted = info.get("granted_balance")
                topped_up = info.get("topped_up_balance")

                print(f"Moeda: {currency}")
                print(f"  Saldo Total: {total}")
                print(f"  Créditos Gratuitos: {granted}")
                print(f"  Saldo Recarregado: {topped_up}")
                print("-" * 20)
        else:
            print(f"❌ Erro na requisição: {response.status_code}")
            print(f"Detalhes: {response.text}")

    except Exception as e:
        print(f"❌ Ocorreu um erro inesperado: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verifica o saldo da API DeepSeek.")
    parser.add_argument("--api-key", required=True, help="Sua DeepSeek API Key")

    args = parser.parse_args()
    check_balance(args.api_key)
