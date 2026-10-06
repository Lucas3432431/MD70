#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Edit.py - Ferramenta para edição precisa de arquivos com substituição de blocos
Versão: 2.3.0
"""

# StdLib
import argparse
import sys
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
import re
import difflib

# Constantes
SCRIPT_DIR = Path(__file__).parent
TOOLS_DIR = SCRIPT_DIR.parent.parent
ENCODINGS = ["utf-8", "cp1252", "latin1", "iso-8859-1"]


class Colors:
    """Cores para terminal (desativadas por padrão)"""

    HEADER = ""
    OKBLUE = ""
    OKGREEN = ""
    WARNING = ""
    FAIL = ""
    ENDC = ""
    BOLD = ""
    UNDERLINE = ""

    @classmethod
    def init(cls, enabled=False):
        if enabled:
            cls.HEADER = "\033[95m"
            cls.OKBLUE = "\033[94m"
            cls.OKGREEN = "\033[92m"
            cls.WARNING = "\033[93m"
            cls.FAIL = "\033[91m"
            cls.ENDC = "\033[0m"
            cls.BOLD = "\033[1m"
            cls.UNDERLINE = "\033[4m"


# Inicializa cores (desativado por padrão)
Colors.init(False)


def show_help():
    """Exibe ajuda detalhada sobre como usar o Edit.py"""
    help_text = """### **[EDIT.PY - AJUDA DETALHADA]**

### **DESCRIÇÃO:**
Edita um arquivo substituindo blocos COMPLETOS de linhas, com versionamento automático.
A ferramenta cria backups antes de qualquer modificação e pode validar a sintaxe após a edição.

### **USO BÁSICO:**
python Edit.py --file <caminho_absoluto> --old-content "<bloco_antigo>" --new-content "<bloco_novo>"

### **PARÂMETROS:**
| Parâmetro | Descrição | Exemplo |
|-----------|-----------|---------|
| `--file` | [OBRIGATÓRIO] Caminho ABSOLUTO do arquivo | `--file "C:\\projeto\\main.py"` |
| `--old-content` | Bloco COMPLETO a ser substituído | `--old-content "print('old')"` |
| `--new-content` | Novo bloco (opcional, vazio p/ remover) | `--new-content "print('new')"` |
| `--commit` | Ativa backup com mensagem de recuperação | `--commit "Fix bug X"` |
| `--restore` | Recupera arquivo usando mensagem de commit | `--restore "Fix bug X"` |

### **REGRAS IMPORTANTES:**
1. **Exclusividade:** Você deve usar OU `--old-content` (para editar) OU `--restore` (para recuperar). Usar ambos na mesma chamada resultará em erro.
2. **Backups:** Só são criados se `--commit` for fornecido na edição.
3. **Restauração:** O `--restore` busca a versão exata salva com aquela mensagem.

### **SEQUÊNCIAS DE ESCAPE:**
Para incluir caracteres especiais no conteúdo, use:

| Escape | Significado | Exemplo |
|--------|-------------|---------|
| `\\n` | Quebra de linha real | `"linha1\\nlinha2"` |
| `\\r` | Retorno de carro (Windows) | `"linha1\\r\\nlinha2"` |
| `\\t` | Tabulação real | `"\\tidentado"` |
| `\\\\` | Barra invertida literal | `"c:\\\\arquivo"` |
| `/texto/` | Texto LITERAL (não processa escapes) | `"/\\n/"` vira literal "\\n" |

### **CÓDIGOS DE RETORNO:**

| Código | Significado | Formato da saída |
|--------|-------------|------------------|
| 0 | Sucesso (com ou sem alterações) | `### **[OK]**` ou `### **[AVISO]**` |
| 0 | Conteúdo não encontrado | `### **[ERRO - CONTEÚDO NÃO ENCONTRADO]**` |
| 0 | Múltiplas ocorrências (sem --all) | `### **[ERRO - MÚLTIPLAS OCORRÊNCIAS]**` |
| 1 | Erro fatal | `### **[ERRO]**` |

### **BACKUPS AUTOMÁTICOS:**
Os backups são criados em: `{pasta_do_arquivo}/__agentx_legacy/edit_session_AAAAMMDD-HHMMSS/`

### **VALIDAÇÃO PÓS-EDIÇÃO:**
Se `--skip-validation` NÃO for usado, a ferramenta executa o `SyntaxReview.py` automaticamente.
"""
    print(help_text)


def read_file_with_encoding(file_path: Path) -> tuple[str, str]:
    """
    Tenta ler o arquivo com diferentes encodings.
    Retorna (conteúdo, encoding_usado)
    """
    for encoding in ENCODINGS:
        try:
            content = file_path.read_text(encoding=encoding)
            return content, encoding
        except UnicodeDecodeError:
            continue
        except Exception as e:
            raise e

    # Último recurso: lê com ignore
    content = file_path.read_text(encoding="utf-8", errors="ignore")
    return content, "utf-8 (with ignore)"


def normalize_line_endings(text: str) -> str:
    """Normaliza quebras de linha para \n"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def process_escape_sequences(content: str) -> str:
    """
    Processa sequências de escape no conteúdo.

    Regras:
    - /texto/ → texto LITERAL (não processa escapes) APENAS se a string COMEÇA e TERMINA com /
    - \n → quebra de linha real
    - \r → retorno de carro real
    - \t → tabulação real
    - \\ → barra invertida literal
    """
    # Primeiro verifica se a string INTEIRA está entre / /
    # Isso evita confundir / dentro do texto como delimitador
    if content.startswith("/") and content.endswith("/") and len(content) > 1:
        # Remove as barras do início e fim e retorna o conteúdo LITERAL
        return content[1:-1]

    # Se não for literal completo, processa escapes normalmente
    replacements = {
        r"\n": "\n",
        r"\r": "\r",
        r"\t": "\t",
        r"\"": '"',
        r"\'": "'",
        r"\\\\": "\\",  # Dupla barra invertida
        r"\\": "\\",  # Barra invertida simples (fallback)
    }

    # Aplica as substituições na ordem correta
    result = content
    for old, new in replacements.items():
        result = result.replace(old, new)

    return result


def calculate_similarity(a: str, b: str) -> float:
    """
    Calcula similaridade entre duas strings.
    Retorna 100% apenas se forem EXATAMENTE iguais.
    """
    if a == b:
        return 100.0

    # Usa SequenceMatcher para similaridade parcial
    matcher = difflib.SequenceMatcher(None, a, b)
    ratio = matcher.ratio() * 100

    # Garante que não arredonde para 100% se não for exato
    if ratio > 99.9 and a != b:
        return 99.9

    return round(ratio, 1)


def find_similar_blocks(
    original_lines: list, search_lines: list, max_blocks: int = 3
) -> list:
    """
    Encontra blocos similares no arquivo original.
    Retorna lista de dicionários com informações detalhadas do bloco.
    """
    similar_blocks = []
    search_len = len(search_lines)

    for i in range(len(original_lines) - search_len + 1):
        block_lines = original_lines[i : i + search_len]
        block_stripped = [line.rstrip("\n") for line in block_lines]
        search_stripped = [line.rstrip("\n") for line in search_lines]

        # Calcula similaridade média do bloco
        total_similarity = 0
        line_matches = []

        for j in range(search_len):
            similarity = calculate_similarity(block_stripped[j], search_stripped[j])
            total_similarity += similarity
            line_matches.append(
                {
                    "line_number": i + j + 1,
                    "content": block_stripped[j],
                    "searched_for": search_stripped[j],
                    "similarity": similarity,
                    "is_exact": block_stripped[j] == search_stripped[j],
                }
            )

        avg_similarity = total_similarity / search_len

        # Só considera se tiver similaridade significativa
        if avg_similarity > 70:
            # Conta quantas linhas são exatas
            exact_count = sum(1 for m in line_matches if m["is_exact"])

            similar_blocks.append(
                {
                    "start_line": i + 1,
                    "end_line": i + search_len,
                    "avg_similarity": round(avg_similarity, 1),
                    "exact_matches": exact_count,
                    "total_lines": search_len,
                    "lines": line_matches,
                    "block_content": "\n".join(block_stripped),
                }
            )

    # Ordena por similaridade média (maior primeiro) e depois por número de matches exatos
    similar_blocks.sort(
        key=lambda x: (x["avg_similarity"], x["exact_matches"]), reverse=True
    )

    return similar_blocks[:max_blocks]


def find_all_block_matches(original_lines: list, search_lines: list) -> list:
    """
    Encontra TODAS as ocorrências exatas do bloco.
    Retorna lista de posições onde o bloco foi encontrado.
    """
    matches = []
    search_len = len(search_lines)
    search_stripped = [line.rstrip("\n") for line in search_lines]

    for i in range(len(original_lines) - search_len + 1):
        match = True
        for j in range(search_len):
            original_stripped = original_lines[i + j].rstrip("\n")
            if original_stripped != search_stripped[j]:
                match = False
                break

        if match:
            matches.append(
                {
                    "start_line": i,
                    "end_line": i + search_len - 1,
                    "lines": original_lines[i : i + search_len],
                }
            )

    return matches


def find_block_match(original_lines: list, search_lines: list) -> dict:
    """
    Tenta encontrar um bloco de linhas que corresponda exatamente à busca.
    Retorna dicionário com informações da correspondência.
    """
    matches = find_all_block_matches(original_lines, search_lines)

    if len(matches) == 1:
        return {
            "found": True,
            "unique": True,
            "start_line": matches[0]["start_line"],
            "end_line": matches[0]["end_line"],
            "lines": matches[0]["lines"],
        }
    elif len(matches) > 1:
        return {
            "found": True,
            "unique": False,
            "matches": matches,
            "count": len(matches),
        }

    return {"found": False}


def validate_file(file_path: str) -> tuple[bool, str, bool]:
    """
    Valida o arquivo editado usando SyntaxReview.py.
    Retorna (success, output, should_suppress_output)
    """
    try:
        # Usar EnvFinder para encontrar SyntaxReview.py
        env_finder_path = TOOLS_DIR / "EnvFinder.py"

        if not env_finder_path.exists():
            return False, "EnvFinder.py não encontrado.", False

        result = subprocess.run(
            [sys.executable, str(env_finder_path), "--name", "SyntaxReview.py"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return False, "Erro ao encontrar SyntaxReview.py.", False

        file_validator_path = (
            result.stdout.strip().split("\n")[0] if result.stdout else None
        )

        if not file_validator_path or not Path(file_validator_path).exists():
            return False, "SyntaxReview.py não encontrado.", False

        # Executar SyntaxReview
        cmd = [sys.executable, str(file_validator_path), "--file", file_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        output = result.stdout.strip() if result.stdout else ""
        error_output = result.stderr.strip() if result.stderr else ""

        # Verifica se é aviso de tipo não suportado
        combined = (output + " " + error_output).lower()
        if any(
            k in combined for k in ["tipo de arquivo", "not supported", "unsupported"]
        ):
            return True, "", True

        if result.returncode != 0:
            return False, error_output or output, False

        return True, output, False

    except subprocess.TimeoutExpired:
        return False, "TIMEOUT ao executar SyntaxReview.py", False
    except Exception as e:
        return False, f"Erro ao validar: {e}", False


def format_debug_output(debug_info: dict) -> list:
    """Formata a saída de debug de forma legível"""
    lines = []

    lines.append("╔══════════════════════════════════════════════════════════╗")
    lines.append("║                    DEBUG INFORMATION                     ║")
    lines.append("╚══════════════════════════════════════════════════════════╝")
    lines.append("")

    # Informações do arquivo
    if "file_info" in debug_info:
        lines.append("📁 ARQUIVO:")
        for key, value in debug_info["file_info"].items():
            lines.append(f"  • {key}: {value}")
        lines.append("")

    # Conteúdo buscado
    if "search_lines" in debug_info:
        lines.append("🔍 CONTEÚDO BUSCADO (old-content):")
        for i, line in enumerate(debug_info["search_lines"]):
            prefix = "  " + (
                "╭─"
                if i == 0
                else "├─"
                if i < len(debug_info["search_lines"]) - 1
                else "╰─"
            )
            lines.append(f"{prefix} [{i+1}] {repr(line)}")
        lines.append("")

    # Blocos similares encontrados
    if "similar_blocks" in debug_info and debug_info["similar_blocks"]:
        lines.append("🎯 BLOCOS SIMILARES ENCONTRADOS:")

        for block_idx, block in enumerate(debug_info["similar_blocks"]):
            symbol = (
                "🟢"
                if block["avg_similarity"] > 95
                else "🟡"
                if block["avg_similarity"] > 80
                else "🔴"
            )
            lines.append(
                f"  {symbol} BLOCO {block_idx + 1} - {block['avg_similarity']}% similar médio"
            )
            lines.append(f"     Linhas {block['start_line']} a {block['end_line']}")
            lines.append(
                f"     Correspondências exatas: {block['exact_matches']}/{block['total_lines']} linhas"
            )
            lines.append("")

            # Mostra comparação linha a linha
            for line_idx, line_match in enumerate(block["lines"]):
                if line_match["is_exact"]:
                    status = "✅"
                else:
                    status = f"⚠ {line_match['similarity']}%"

                lines.append(f"     {status} Linha {line_match['line_number']}:")
                lines.append(f"        Arquivo: {repr(line_match['content'])}")
                if not line_match["is_exact"]:
                    lines.append(f"        Busca:   {repr(line_match['searched_for'])}")

                    # Mostra a diferença específica
                    diff = get_line_difference(
                        line_match["content"], line_match["searched_for"]
                    )
                    if diff:
                        lines.append(f"        ⚠ {diff}")

            lines.append("")

    # Múltiplas ocorrências
    if "multiple_matches" in debug_info:
        lines.append("🔄 MÚLTIPLAS OCORRÊNCIAS IDÊNTICAS ENCONTRADAS:")
        lines.append(f"  Total: {debug_info['multiple_matches']['count']} ocorrências")
        lines.append("")

        for i, match in enumerate(
            debug_info["multiple_matches"]["matches"][:3]
        ):  # Mostra até 3
            lines.append(
                f"  Ocorrência {i+1} - Linhas {match['start_line']+1} a {match['end_line']+1}"
            )
            lines.append(f"    {repr(match['lines'][0].rstrip())} ...")

        if debug_info["multiple_matches"]["count"] > 3:
            lines.append(
                f"  ... e mais {debug_info['multiple_matches']['count'] - 3} ocorrências"
            )
        lines.append("")

        lines.append("  📝 SUGESTÃO: Use --all para substituir todas as ocorrências")
        lines.append("  OU expanda o bloco para incluir contexto único")
        lines.append("")

    return lines


def get_line_difference(actual: str, expected: str) -> str:
    """Retorna uma descrição detalhada da diferença entre duas linhas"""
    if actual == expected:
        return None

    # Lista de caracteres especiais comuns que podem causar problemas
    special_chars = {
        "/": "barra normal",
        "\\": "barra invertida (ESCAPE)",
        "\n": "quebra de linha",
        "\r": "retorno de carro",
        "\t": "tabulação",
        '"': "aspas duplas",
        "'": "aspas simples",
        "*": "asterisco",
        "{": "chave abrir",
        "}": "chave fechar",
        "[": "colchete abrir",
        "]": "colchete fechar",
        "(": "parêntese abrir",
        ")": "parêntese fechar",
        "<": "menor que",
        ">": "maior que",
        "&": "e comercial",
        "|": "pipe",
        "$": "cifrão",
        "%": "porcentagem",
        "#": "cerquilha",
        "@": "arroba",
        "`": "crase",
        "~": "til",
    }

    # Verifica diferença de tamanho
    if len(actual) != len(expected):
        # Verifica se a diferença pode ser devido a escapes
        actual_escapes = actual.count("\\")
        expected_escapes = expected.count("\\")

        if actual_escapes != expected_escapes:
            return (
                f"tamanho diferente (arquivo: {len(actual)}, busca: {len(expected)}) - "
                f"Possível problema com caracteres de escape: "
                f"arquivo tem {actual_escapes} '\\', busca tem {expected_escapes} '\\'"
            )
        else:
            return f"tamanho diferente (arquivo: {len(actual)}, busca: {len(expected)})"

    # Encontra a primeira posição onde diferem
    for i, (a, e) in enumerate(zip(actual, expected)):
        if a != e:
            # Identifica se são caracteres especiais
            a_desc = special_chars.get(a, f"'{a}' (código {ord(a)})")
            e_desc = special_chars.get(e, f"'{e}' (código {ord(e)})")

            # Pega contexto ao redor
            start = max(0, i - 15)
            end = min(len(actual), i + 15)

            actual_context = actual[start:end]
            expected_context = expected[start:end]

            # Marca a posição da diferença
            marker = " " * (i - start) + "^"

            return (
                f"difere na posição {i}:\n"
                f"        Arquivo: {repr(actual_context)} ({a_desc})\n"
                f"        Busca:   {repr(expected_context)} ({e_desc})\n"
                f"                 {marker}\n"
                f"        {'═'*60}\n"
                f"        DICA: Lembre-se que '\\' é caractere de escape no terminal!\n"
                f"        Para usar '\\' literal no --old-content, use '\\\\' ou /texto/"
            )

    return "diferença desconhecida"


def format_output_success(
    file_path: str,
    backup_path: Path = None,
    validation_output: str = "",
    is_removal: bool = False,
):
    """Formata saída de sucesso"""
    lines = [f"{Colors.OKGREEN}### **[OK]**{Colors.ENDC}"]

    if is_removal:
        lines.append(f"* Bloco removido do arquivo `{file_path}` com sucesso.")
    else:
        lines.append(f"* Arquivo `{file_path}` editado com sucesso.")

    if backup_path:
        lines.append(f"* Backup criado em: `{backup_path}`")

    if validation_output:
        lines.append("---")
        lines.append("### **Validação SyntaxReview:**")
        lines.append(validation_output)

    return "\n".join(lines)


def format_output_multiple_matches(
    file_path: str, matches: list, similar_blocks: list = None
):
    """Formata saída para múltiplas ocorrências"""
    lines = [f"{Colors.WARNING}### **[ERRO - MÚLTIPLAS OCORRÊNCIAS]**{Colors.ENDC}"]
    lines.append(
        f"* O bloco especificado foi encontrado em {len(matches)} locais no arquivo `{file_path}`."
    )
    lines.append("")
    lines.append("### **OCORRÊNCIAS ENCONTRADAS:**")

    for i, match in enumerate(matches[:5]):  # Mostra até 5
        lines.append(f"  {i+1}. Linhas {match['start_line']+1} a {match['end_line']+1}")
        lines.append(f"     {repr(match['lines'][0].rstrip())} ...")

    if len(matches) > 5:
        lines.append(f"  ... e mais {len(matches) - 5} ocorrências")

    lines.append("")
    lines.append("### **SUGESTÕES:**")
    lines.append("1. **Use --all** para substituir todas as ocorrências")
    lines.append(
        "2. **Expanda o bloco** para incluir linhas anteriores/posteriores únicas"
    )
    lines.append("3. **Adicione contexto** ao redor do bloco para torná-lo único")
    lines.append("")

    if similar_blocks and len(similar_blocks) > 1:
        lines.append("### **BLOCOS MAIS SIMILARES (para referência):**")
        for block in similar_blocks[:2]:
            lines.append(
                f"  • Linhas {block['start_line']}-{block['end_line']} - {block['avg_similarity']}% similar"
            )

    lines.append("")
    lines.append("**Use `--debug` para ver análise detalhada**")

    return "\n".join(lines)


def format_output_not_found(file_path: str, similar_blocks: list, search_lines: list):
    """Formata saída para conteúdo não encontrado com ênfase no primeiro bloco similar"""
    lines = [f"{Colors.FAIL}### **[ERRO - CONTEÚDO NÃO ENCONTRADO]**{Colors.ENDC}"]
    lines.append(
        f"* O conteúdo especificado **não foi encontrado** no arquivo `{file_path}`."
    )
    lines.append("")

    if similar_blocks:
        # Pega apenas o primeiro bloco (mais similar)
        block = similar_blocks[0]

        lines.append("### **🔍 BLOCO MAIS SIMILAR ENCONTRADO (BLOCO 1):**")
        lines.append("")

        # Mostra estatísticas do bloco
        lines.append(
            f"**Localização:** Linhas {block['start_line']} a {block['end_line']}"
        )
        lines.append(f"**Similaridade média:** {block['avg_similarity']}%")
        lines.append(
            f"**Linhas exatas:** {block['exact_matches']} de {block['total_lines']}"
        )
        lines.append("")

        # Mostra o bloco COMPLETO com comparação linha a linha
        lines.append(f"**{'═'*60}**")
        lines.append(f"**COMPARAÇÃO DETALHADA LINHA A LINHA:**")
        lines.append(f"**{'═'*60}**")
        lines.append("")

        for line_idx, line_match in enumerate(block["lines"]):
            line_num = line_match["line_number"]

            # Define o símbolo baseado no match
            if line_match["is_exact"]:
                symbol = "✅"
                status = "MATCH EXATO"
            else:
                symbol = "❌"
                status = f"DIFERENTE ({line_match['similarity']}% similar)"

            lines.append(f"**{symbol} LINHA {line_num} - {status}**")
            lines.append(f"   📄 ARQUIVO: {repr(line_match['content'])}")
            lines.append(f"   🔍 BUSCA:   {repr(line_match['searched_for'])}")

            # Se não for exato, mostra a diferença específica
            if not line_match["is_exact"]:
                diff = get_line_difference(
                    line_match["content"], line_match["searched_for"]
                )
                if diff:
                    lines.append(f"   ⚠ DIFERENÇA: {diff}")

            lines.append("")

        lines.append(f"**{'═'*60}**")
        lines.append("")

        # Análise do problema
        lines.append("### **🔍 ANÁLISE DO PROBLEMA:**")
        lines.append("")

        if block["exact_matches"] == 0:
            lines.append("❌ **NENHUMA linha do bloco corresponde exatamente.**")
            lines.append(
                "   Isso indica que o bloco inteiro está diferente do esperado."
            )
        elif block["exact_matches"] < block["total_lines"]:
            lines.append(
                f"⚠️ **APENAS {block['exact_matches']} de {block['total_lines']} linhas correspondem exatamente.**"
            )
            lines.append(
                "   As linhas marcadas com ❌ são as que impedem o match perfeito."
            )
            lines.append("")
            lines.append("   **Problemas mais comuns:**")
            lines.append(
                "   • Indentação diferente (espaços vs tabs, quantidade de espaços)"
            )
            lines.append("   • Espaços extras no início ou fim da linha")
            lines.append("   • Caracteres especiais ou pontuação diferentes")
            lines.append("   • Quebras de linha no meio do texto")

        lines.append("")
        lines.append("### **💡 SUGESTÕES PARA CORREÇÃO:**")
        lines.append("")
        lines.append(
            "1. **Copie o bloco exato do arquivo** e modifique apenas o necessário:"
        )
        lines.append(f"   ```")
        lines.append(f"   {block['block_content']}")
        lines.append(f"   ```")
        lines.append("")
        lines.append("2. **Verifique a indentação** - Compare espaço por espaço")
        lines.append("3. **Use o modo debug** para ver análise ainda mais detalhada:")
        lines.append(
            '   `python Edit.py --file <arquivo> --old-content "<bloco>" --new-content "<novo>" --debug`'
        )
        lines.append("")
        lines.append(
            "4. **Para testes, tente substituições menores** - Blocos muito grandes são mais propensos a erros"
        )
        lines.append("")
        lines.append("5. **ATENÇÃO A CARACTERES ESPECIAIS E ESCAPES:**")
        lines.append("   ┌────────────┬─────────────────────────────────────┐")
        lines.append("   │ CARACTERE  │ COMO USAR NO --old-content         │")
        lines.append("   ├────────────┼─────────────────────────────────────┤")
        lines.append("   │ / (barra)  │ Use /literal/ ou normalmente       │")
        lines.append("   │ \\ (escape) │ Use '\\\\\\\\' (dupla) ou /c:\\\\arquivo/  │")
        lines.append('   │ " (aspas)  │ Use \'\\\\"\' ou /"/                   │')
        lines.append("   │ ' (aspas)  │ Use \"\\\\'\" ou /'/                   │")
        lines.append("   │ Quebra     │ Use '\\\\n'                          │")
        lines.append("   │ Tab        │ Use '\\\\t'                          │")
        lines.append("   └────────────┴─────────────────────────────────────┘")
        lines.append("")
        lines.append(
            "   **EXEMPLO:** Para buscar `{/* Agreement Popup */}` use literalmente,"
        )
        lines.append("   sem escapes, pois `/` não é caractere especial no terminal.")
        lines.append("   Já para `c:\\arquivo` use `c:\\\\arquivo`.")
    else:
        lines.append("### **❌ NENHUM BLOCO SIMILAR ENCONTRADO**")
        lines.append("")
        lines.append(
            "O conteúdo buscado é muito diferente de qualquer parte do arquivo."
        )
        lines.append("")
        lines.append("### **💡 SUGESTÕES:**")
        lines.append("1. **Verifique se o arquivo correto está sendo editado**")
        lines.append("2. **O bloco buscado pode estar em outro arquivo**")
        lines.append("3. **Use o modo debug para ver o conteúdo completo do arquivo**")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Edita um arquivo substituindo blocos COMPLETOS de linhas, com versionamento automático.",
        add_help=False,
    )
    parser.add_argument(
        "--file", type=str, required=False, help="Caminho absoluto do arquivo a editar."
    )
    parser.add_argument(
        "--old-content",
        type=str,
        required=False,
        help="Bloco COMPLETO de linhas a ser substituído.",
    )
    parser.add_argument(
        "--new-content",
        type=str,
        required=False,
        default="",
        help="Novo bloco COMPLETO de linhas (pode ser vazio para remover o bloco).",
    )
    parser.add_argument(
        "--commit",
        type=str,
        required=False,
        help="Mensagem para o commit/backup. Se fornecido, realiza o backup.",
    )
    parser.add_argument(
        "--restore",
        type=str,
        required=False,
        help="Restaura o arquivo usando a mensagem de commit fornecida.",
    )
    parser.add_argument(
        "--all", action="store_true", help="Substituir TODAS as ocorrências do bloco."
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Pula a validação com SyntaxReview.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Mostra informações detalhadas de depuração.",
    )
    parser.add_argument("--color", action="store_true", help="Ativa cores no terminal.")
    parser.add_argument(
        "-h",
        "--help",
        type=str,
        nargs="?",
        const="true",
        default="false",
        help="Exibe ajuda detalhada.",
    )

    args = parser.parse_args()

    # Ativar cores se solicitado
    if args.color:
        Colors.init(True)

    # Verificar parâmetros mínimos
    if not args.file:
        print(f"{Colors.FAIL}### **[ERRO]**{Colors.ENDC}")
        print("* O parâmetro --file é obrigatório.")
        print("  Use --restore para restaurar ou --old-content para editar.")
        sys.exit(1)

    file_path = Path(args.file)

    # Lógica de Restauração
    if args.restore:
        # Se for restore, não pode ter parâmetros de edição
        if args.old_content or args.new_content:
            print(f"{Colors.FAIL}### **[ERRO]**{Colors.ENDC}")
            print(
                "* O parâmetro --restore não pode ser usado junto com --old-content ou --new-content."
            )
            sys.exit(1)

        legacy_dir = file_path.parent / "__agentx_legacy"
        if not legacy_dir.exists():
            print(f"{Colors.FAIL}### **[ERRO]**{Colors.ENDC}")
            print(f"* Diretório de legado não encontrado para `{file_path.name}`.")
            sys.exit(1)

        # Busca a sessão mais recente com a mensagem de restore
        target_msg = f"edit(restore: {args.restore})"
        matching_backups = []

        # Ordena por data (mais recente primeiro)
        sessions = sorted(
            legacy_dir.glob("edit_session_*"), key=lambda x: x.name, reverse=True
        )

        for session_dir in sessions:
            msg_file = session_dir / "commit_message.txt"
            if (
                msg_file.exists()
                and msg_file.read_text(encoding="utf-8").strip() == target_msg
            ):
                # Encontra o arquivo de backup dentro da sessão
                backups = list(session_dir.glob(f"*_{file_path.name}"))
                if backups:
                    matching_backups.append(backups[0])
                    break  # Pega o mais recente

        if not matching_backups:
            print(f"{Colors.FAIL}### **[ERRO]**{Colors.ENDC}")
            print(f"* Nenhum backup encontrado com a mensagem: `{args.restore}`")
            sys.exit(1)

        backup_to_restore = matching_backups[0]
        try:
            shutil.copy2(backup_to_restore, file_path)
            print(f"{Colors.OKGREEN}### **[OK]**{Colors.ENDC}")
            print(f"* Arquivo `{file_path.name}` restaurado com sucesso!")
            print(f"* Origem: `{backup_to_restore}`")
            sys.exit(0)
        except Exception as e:
            print(f"{Colors.FAIL}### **[ERRO]**{Colors.ENDC}")
            print(f"* Falha ao restaurar arquivo: {e}")
            sys.exit(1)

    # Verificar parâmetros obrigatórios para EDIÇÃO (se não for restore)
    if not args.old_content:
        print(f"{Colors.FAIL}### **[ERRO]**{Colors.ENDC}")
        print("* Para editar, o parâmetro --old-content é obrigatório.")
        print('  Para restaurar, use --restore "mensagem".')
        print("")
        print("**Para ajuda detalhada, use:**")
        print("  python Edit.py -h")
        sys.exit(1)

    # Validar caminho absoluto
    if not file_path.is_absolute():
        print(f"{Colors.FAIL}### **[ERRO]**{Colors.ENDC}")
        print(f"* O caminho `{file_path}` não é absoluto. Use um caminho completo.")
        sys.exit(1)

    if not file_path.is_file():
        print(f"{Colors.FAIL}### **[ERRO]**{Colors.ENDC}")
        print(f"* Arquivo `{file_path}` não encontrado ou não é um arquivo válido.")
        sys.exit(1)

    # Processar conteúdos
    old_content_raw = args.old_content
    new_content_raw = args.new_content

    old_content = process_escape_sequences(old_content_raw)
    new_content = process_escape_sequences(new_content_raw)

    # Normalizar quebras de linha
    old_content = normalize_line_endings(old_content)
    new_content = normalize_line_endings(new_content)

    # Debug info
    debug_info = {
        "file_info": {
            "path": str(file_path),
            "exists": file_path.exists(),
            "size": file_path.stat().st_size if file_path.exists() else 0,
        },
        "search_lines": old_content.split("\n"),
        "replace_lines": new_content.split("\n"),
    }

    try:
        # Ler arquivo
        original_content, encoding_used = read_file_with_encoding(file_path)
        original_content = normalize_line_endings(original_content)
        original_lines = original_content.split("\n")

        debug_info["file_info"]["encoding"] = encoding_used
        debug_info["file_info"]["total_lines"] = len(original_lines)

        # Encontrar blocos similares
        search_lines = old_content.split("\n")
        similar_blocks = find_similar_blocks(original_lines, search_lines, max_blocks=3)
        debug_info["similar_blocks"] = similar_blocks

        # Tentar encontrar bloco exato
        block_match = find_block_match(original_lines, search_lines)

        if args.debug:
            # Se houver múltiplas ocorrências, adicionar ao debug
            if block_match["found"] and not block_match.get("unique", True):
                debug_info["multiple_matches"] = {
                    "count": block_match["count"],
                    "matches": block_match["matches"],
                }

            # Mostrar debug formatado
            for line in format_debug_output(debug_info):
                print(line)

        # Caso 1: Bloco não encontrado
        if not block_match["found"]:
            output = format_output_not_found(
                str(file_path), similar_blocks, search_lines
            )
            print(output)
            sys.exit(0)

        # Caso 2: Múltiplas ocorrências sem --all
        if not block_match.get("unique", True) and not args.all:
            output = format_output_multiple_matches(
                str(file_path), block_match["matches"], similar_blocks
            )
            print(output)
            sys.exit(0)

        # Caso 3: Bloco único encontrado (ou --all para múltiplos)

        # Criar backup (apenas se --commit for fornecido)
        backup_path = None
        if args.commit:
            try:
                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                file_timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")

                # Formata a mensagem de commit para o nome da pasta
                commit_msg = args.commit.replace(" ", "_")
                # Limpa caracteres especiais do nome da pasta
                commit_msg = "".join(
                    c for c in commit_msg if c.isalnum() or c in ("_", "-")
                )

                legacy_dir = file_path.parent / "__agentx_legacy"
                session_dir = (
                    legacy_dir / f"edit_session_{timestamp}_edit(restore_{commit_msg})"
                )
                session_dir.mkdir(parents=True, exist_ok=True)

                backup_path = session_dir / f"{file_timestamp}_{file_path.name}"
                shutil.copy2(file_path, backup_path)

                # Salva a mensagem original em um arquivo de texto dentro da sessão
                (session_dir / "commit_message.txt").write_text(
                    f"edit(restore: {args.commit})", encoding="utf-8"
                )

                if args.debug:
                    print(
                        f"{Colors.OKGREEN}✓ Backup criado: {backup_path}{Colors.ENDC}"
                    )

            except Exception as e:
                print(f"{Colors.FAIL}### **[ERRO]**{Colors.ENDC}")
                print(f"* Erro ao criar backup: {e}")
                sys.exit(1)

        # Realizar substituição
        if args.all or block_match.get("unique", True):
            if args.all and not block_match.get("unique", True):
                # Substituir todas as ocorrências
                matches = block_match["matches"]
                new_lines = []
                i = 0
                while i < len(original_lines):
                    replaced = False
                    for match in matches:
                        if i == match["start_line"]:
                            # Se new_content for vazio, não adiciona nada (remove o bloco)
                            if new_content:  # só adiciona se não for vazio
                                new_lines.extend(new_content.split("\n"))
                            i = match["end_line"] + 1
                            replaced = True
                            break
                    if not replaced:
                        new_lines.append(original_lines[i])
                        i += 1
            else:
                # Substituir apenas primeira ocorrência
                start_line = block_match["start_line"]
                end_line = block_match["end_line"]

                # Se new_content for vazio, só não adiciona nada entre as partes
                new_lines = original_lines[:start_line]
                if new_content:  # só adiciona se não for vazio
                    new_lines.extend(new_content.split("\n"))
                new_lines.extend(original_lines[end_line + 1 :])

            new_file_content = "\n".join(new_lines)
            content_changed = new_file_content != original_content

            if not content_changed:
                print(f"{Colors.WARNING}### **[AVISO]**{Colors.ENDC}")
                print(f"* Nenhuma alteração necessária: conteúdo já atualizado.")
                sys.exit(0)

            # Escrever arquivo
            try:
                file_path.write_text(new_file_content, encoding="utf-8")
            except:
                file_path.write_text(
                    new_file_content, encoding="cp1252", errors="replace"
                )

            # Validar (opcional)
            validation_output = ""
            if not args.skip_validation:
                _, validation_output, _ = validate_file(str(file_path))

            # Formatar saída de sucesso
            is_removal = new_content == ""
            print(
                format_output_success(
                    str(file_path), backup_path, validation_output, is_removal
                )
            )
            sys.exit(0)

    except Exception as e:
        print(f"{Colors.FAIL}### **[ERRO]**{Colors.ENDC}")
        print(f"* Erro ao processar arquivo: {e}")
        if args.debug:
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
