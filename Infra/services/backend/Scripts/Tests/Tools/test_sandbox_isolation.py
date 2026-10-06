import os
import sys
import json

# Adiciona a raiz do backend ao path para que os imports de App.* funcionem
# O script está em Scripts/Tests/Tools/, então a raiz está 3 níveis acima
backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
sys.path.append(backend_root)

from App.Features.Tools._sandbox import SandboxMixin


class MockTool(SandboxMixin):
    def __init__(self, user_id):
        # Simulamos o atributo que a classe real teria
        self.current_user_id = user_id


def test_isolation():
    print("--- INICIANDO TESTE DE ISOLAMENTO DO SANDBOX ---")

    # URL do sandbox deve estar acessível (via localhost:8001 devido ao mapeamento que fizemos)
    sandbox_url = os.environ.get("SANDBOX_URL", "http://localhost:8001")
    print(f"Testando contra: {sandbox_url}")

    user_a = MockTool("cliente_alfa")
    user_b = MockTool("cliente_beta")

    # 1. Usuário A cria um arquivo secreto
    print("\n[User A] Criando arquivo secreto...")
    res_a = user_a._execute_terminal(
        {"shell": "echo 'SENHA_SECRETA_123' > segredo.txt && ls"}
    )
    print(f"Resposta A: {res_a}")

    # 2. Usuário B tenta listar arquivos (não deve ver o arquivo do A)
    print("\n[User B] Tentando listar arquivos...")
    res_b1 = user_b._execute_terminal({"shell": "ls"})
    print(f"Resposta B (ls): {res_b1}")

    # 3. Usuário B tenta ler o arquivo do A explicitamente
    print("\n[User B] Tentando ler segredo do User A...")
    res_b2 = user_b._execute_terminal({"shell": "cat segredo.txt"})
    print(f"Resposta B (cat): {res_b2}")

    # Validação lógica
    data_a = json.loads(res_a)
    data_b1 = json.loads(res_b1)
    data_b2 = json.loads(res_b2)

    success = True

    if not data_a.get("success"):
        print(
            "❌ ERRO: User A não conseguiu executar o comando. O Sandbox está rodando?"
        )
        success = False

    if "segredo.txt" in data_b1.get("stdout", ""):
        print("❌ FALHA: User B conseguiu listar o arquivo do User A!")
        success = False

    if data_b2.get("exit_code") == 0:
        print("❌ FALHA: User B conseguiu ler o arquivo do User A!")
        success = False

    if success:
        print(
            "\n✅ SUCESSO: O ambiente está isolado. User B não tem acesso aos dados do User A."
        )
    else:
        print("\n❌ CONCLUSÃO: O isolamento FALHOU.")


if __name__ == "__main__":
    test_isolation()
