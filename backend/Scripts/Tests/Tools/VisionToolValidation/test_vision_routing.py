import os
import sys
import json
from pathlib import Path

# Configurar PYTHONPATH para encontrar App
backend_dir = Path(__file__).parent.parent.parent.parent
sys.path.append(str(backend_dir))

from App.Features.Tools.Core import Core
from App.Core.Settings.Settings import load_config
from App.Core.Logs import debug


def test_vision_real_url():
    print("🚀 Iniciando Teste REAL de Roteamento Vision -> OpenAI GPT-4o")

    # Carregar PUBLIC_URL do ambiente
    config = load_config()
    public_url = config.get("public_url", "").rstrip("/")

    if not public_url or "ngrok" not in public_url:
        print("❌ ERRO: PUBLIC_URL (ngrok) não configurada corretamente no .env")
        return

    # Instanciar Core
    core = Core()
    core.current_user_id = "test_user"
    core.current_chat_id = "test_chat"

    # URL REAL de um template via Proxy (como o agente recebe no contexto)
    test_image_url = f"{public_url}/api/proxy/references/BurburyAds_Template.jpg"
    test_prompt = "Descreva os elementos visuais desta imagem, cores e se há pessoas."

    args = {"prompt": test_prompt, "image_input": test_image_url, "wait": True}

    print(f"--- Chamando vision() com URL REAL (ngrok) ---")
    print(f"Prompt: {test_prompt}")
    print(f"Image URL: {test_image_url}")
    print(f"Nota: Este teste falhará com erro 400 se o ngrok estiver sem banda.")

    try:
        result_json = core._execute_vision(args)
        result = json.loads(result_json)

        print("\n--- Resultado ---")
        print(json.dumps(result, indent=2, ensure_ascii=False))

        if result.get("success"):
            print("\n✅ SUCESSO: OpenAI conseguiu baixar e analisar a imagem via ngrok!")
            if result.get("model") == "gpt-4o":
                print("🎯 Confirmado: Modelo GPT-4o utilizado.")
        else:
            print(f"\n❌ FALHA NA API: {result.get('error')}")
            if "400" in str(result) or "invalid_image_url" in str(result):
                print(
                    "🚨 DIAGNÓSTICO: OpenAI não conseguiu acessar a URL. Verifique o limite do ngrok."
                )

    except Exception as e:
        print(f"\n💥 EXCEÇÃO NO CÓDIGO: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_vision_real_url()
