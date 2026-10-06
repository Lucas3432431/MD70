#!/usr/bin/env python3
"""
Modulariza Core.py em mixin files.
Core.py permanece o entry point e importa todos os mixins.
Cada mixin usa 'self' normalmente — Python MRO resolve tudo.

Uso: python Scripts/modularize_core.py
     (rodar a partir de services/backend/)
"""

import re
from pathlib import Path

CORE_PATH = Path("App/Features/Tools/Core.py")
TOOLS_DIR = Path("App/Features/Tools")

# ---------------------------------------------------------------------------
# Mapeamento: nome do método → arquivo mixin (sem extensão)
# Métodos NÃO listados aqui ficam em Core.py
# ---------------------------------------------------------------------------
METHOD_TO_MIXIN = {
    # --- Document execute (create) ---
    "_execute_document": "_document",
    "_check_required_documents_exist": "_document",
    "_update_brand_communication_document": "_document",
    "_convert_brand_communication_to_relative_url": "_document",
    "_convert_relative_to_complete_url": "_document",
    "_set_nested_field": "_document",
    "_get_documents_list": "_document",
    "_get_document_by_id": "_document",
    # --- Document update / delete ---
    "_execute_update": "_document_update",
    "_execute_delete": "_document_update",
    # --- Document validators ---
    "_validate_business_canvas_json": "_document_validators",
    "_validate_brand_communication_json": "_document_validators",
    "_validate_product_json": "_document_validators",
    "_validate_copy_json": "_document_validators",
    "_validate_copywriting_document_id": "_document_validators",
    "_validate_range_or_value": "_document_validators",
    "_validate_tools_config": "_document_validators",
    # --- Asset (geração de imagem / vídeo / variação) ---
    "_execute_asset": "_asset",
    "_execute_asset_variation_mode": "_asset",
    "_generate_all_copy_assets": "_asset",
    "_resolve_uuid_to_media_url": "_asset",
    "_resolve_image_input_to_url": "_asset",
    "_compress_base64_image_for_vision": "_asset",
    "_gen_img_fallback_dalle3": "_asset",
    "_gen_film_fallback_google_veo": "_asset",
    "_vision_openai_gpt4o": "_asset",
    "_execute_vision": "_asset",
    "_validate_and_clean_url": "_asset",
    "_build_extra_params": "_asset",
    "_select_model": "_asset",
    "_vision_fallback_to_claude": "_asset",
    # --- Quiz ---
    "_execute_quiz": "_quiz",
    "_check_quiz_in_chat_history": "_quiz",
    "_check_quiz_in_chat_history_10": "_quiz",
    "_check_product_url_quiz_answered": "_quiz",
    "_check_copywriting_quiz_in_chat": "_quiz",
    "_check_strings_in_quiz": "_quiz",
    "_check_required_topics_in_quiz": "_quiz",
    "_get_quiz_user_answers_blob": "_quiz",
    "_get_last_quiz_answers": "_quiz",
    "_parse_quiz_answers_by_type": "_quiz",
    "_get_quiz_post_category": "_quiz",
    "_get_quiz_selected_product_id": "_quiz",
    # --- Web Search ---
    "_execute_web_search": "_web_search",
    "_check_web_search_visual_analysis": "_web_search",
    "_check_web_search_with_specific_strings": "_web_search",
    "_check_web_search_with_concepts": "_web_search",
    # --- Schedule / Calendar ---
    "_execute_schedule": "_schedule",
    "_save_calendar_to_db": "_schedule",
    "_find_conflicting_schedule_dates": "_schedule",
    "_schedule_calendar_posts": "_schedule",
    "_infer_type": "_schedule",
    "_generate_calendar_data": "_schedule",
    "_summarize_calendar_posts": "_schedule",
    "_save_calendar_json": "_schedule",
    "_get_calendar_context": "_schedule",
    "_execute_context_calendar": "_schedule",
    # --- Context ---
    "_execute_context": "_context",
    "_execute_context_steps": "_context",
    "_execute_context_rag": "_context",
    "_execute_client": "_context",
    "_get_client_documents_list": "_context",
    "_get_client_id_from_user": "_context",
    "_get_last_visual_analysis": "_context",
    "_check_context_calendar_in_chat_history": "_context",
    "_get_assets_list": "_context",
    # --- Task ---
    "_execute_task": "_task",
    "_build_tasks_json": "_task",
    "_save_tasks_to_db": "_task",
    "_save_tasks_json": "_task",
    "_get_next_step_context": "_task",
    "_load_task_context_for_step": "_task",
    "_check_tasks_after_quiz": "_task",
    "_check_copywriting_tasks_in_chat": "_task",
    # --- Validators (checks de chat / lookup / state) ---
    "_check_copywriting_lookup_in_chat": "_validators",
    "_check_variation_quiz_answered_in_chat": "_validators",
    "_check_caption_lookup_in_chat": "_validators",
    "_check_competitor_analysis_lookup_in_chat": "_validators",
    "_check_lookup_in_chat": "_validators",
    "_check_brand_lookup_in_chat": "_validators",
    "_check_canvas_lookup_in_chat": "_validators",
    "_check_product_lookup_in_chat": "_validators",
    "_check_prompt_engineering_in_chat": "_validators",
    "_get_tool_messages_blob": "_validators",
    "_user_has_business_canvas": "_validators",
    "_user_has_brand_communication": "_validators",
    "_user_has_product": "_validators",
    "_get_product_docs_list": "_validators",
    "_get_product_doc_by_id": "_validators",
}

# Mixin name → class name
MIXIN_CLASS_NAMES = {
    "_document": "DocumentMixin",
    "_document_update": "DocumentUpdateMixin",
    "_document_validators": "DocumentValidatorsMixin",
    "_asset": "AssetMixin",
    "_quiz": "QuizMixin",
    "_web_search": "WebSearchMixin",
    "_schedule": "ScheduleMixin",
    "_context": "ContextMixin",
    "_task": "TaskMixin",
    "_validators": "ValidatorsMixin",
}

# Ordem das bases no Core (controla MRO)
MIXIN_ORDER = [
    "_document",
    "_document_update",
    "_document_validators",
    "_asset",
    "_quiz",
    "_web_search",
    "_schedule",
    "_context",
    "_task",
    "_validators",
]


# ---------------------------------------------------------------------------
# Parsing: extrai métodos da classe
# ---------------------------------------------------------------------------


def parse_methods(lines: list[str]) -> dict[str, tuple[int, int]]:
    """
    Retorna {method_name: (start_line_idx, end_line_idx)} (índices 0-based, end exclusive).
    Considera apenas métodos de classe (4 espaços de indentação).
    """
    METHOD_RE = re.compile(r"^    def (\w+)\s*\(")
    starts: list[tuple[str, int]] = []

    for i, line in enumerate(lines):
        m = METHOD_RE.match(line)
        if m:
            starts.append((m.group(1), i))

    methods: dict[str, tuple[int, int]] = {}
    for idx, (name, start) in enumerate(starts):
        end = starts[idx + 1][1] if idx + 1 < len(starts) else len(lines)
        # Se o mesmo nome aparece duas vezes (override), fica com o último
        methods[name] = (start, end)

    return methods


def extract_header(lines: list[str]) -> tuple[list[str], int]:
    """Retorna (linhas do módulo antes da classe, idx da linha 'class Core:')."""
    CLASS_RE = re.compile(r"^class \w+")
    for i, line in enumerate(lines):
        if CLASS_RE.match(line):
            return lines[:i], i
    raise ValueError("Não encontrei 'class Core' em Core.py")


# ---------------------------------------------------------------------------
# Geração dos arquivos
# ---------------------------------------------------------------------------

MIXIN_FILE_HEADER = '''\
"""
{module_name} — Mixin extraído de Core.py.
Core.py importa este módulo e herda {class_name}.
NÃO edite a assinatura da classe — use Core.py como entry point.
"""
# ruff: noqa
# type: ignore
from __future__ import annotations
from typing import TYPE_CHECKING, Dict, Any, Optional

if TYPE_CHECKING:
    pass  # evita imports circulares em type checking

'''


def build_mixin_file(
    mixin_key: str, method_blocks: list[str], module_header: list[str]
) -> str:
    """Monta o conteúdo de um arquivo mixin."""
    class_name = MIXIN_CLASS_NAMES[mixin_key]
    module_name = f"{mixin_key}.py"

    # Imports e constantes do módulo original (tudo antes da class)
    header_str = "".join(module_header)

    body = "\n".join(method_blocks)

    return (
        MIXIN_FILE_HEADER.format(module_name=module_name, class_name=class_name)
        + header_str
        + "\n\n"
        + f"class {class_name}:\n"
        + body
        + "\n"
    )


def build_new_core(
    module_header: list[str],
    class_docstring: str,
    core_methods: list[str],  # blocos dos métodos que ficam em Core
) -> str:
    """Monta o Core.py novo com imports dos mixins e herança."""
    imports_block = "".join(module_header)

    mixin_imports = "\n".join(
        f"from .{key} import {MIXIN_CLASS_NAMES[key]}" for key in MIXIN_ORDER
    )
    bases = ", ".join(MIXIN_CLASS_NAMES[k] for k in MIXIN_ORDER)

    methods_str = "\n".join(core_methods)

    return (
        imports_block
        + "\n"
        + "# Mixins — cada arquivo contém um domínio de tools\n"
        + mixin_imports
        + "\n\n\n"
        + f"class Core({bases}):\n"
        + f'    """{class_docstring}"""\n'
        + "\n"
        + methods_str
        + "\n"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print(f"Lendo {CORE_PATH} ...")
    raw = CORE_PATH.read_text(encoding="utf-8")
    lines = raw.splitlines(keepends=True)

    # 1. Separar cabeçalho do módulo e início da classe
    module_header, class_start_idx = extract_header(lines)

    # 2. Linha da class e docstring (a linha de class + próximas até o __init__)
    class_line = lines[class_start_idx]  # "class Core:\n"
    # Pegar docstring da classe (se houver, está na linha seguinte)
    class_docstring = "Facilita execução de tools para agents."
    for line in lines[class_start_idx + 1 : class_start_idx + 5]:
        stripped = line.strip().strip('"').strip("'")
        if stripped and not stripped.startswith("def "):
            class_docstring = stripped
            break

    # 3. Extrair todos os métodos
    # Trabalhar apenas nas linhas dentro da classe
    class_lines = lines[class_start_idx:]
    methods = parse_methods(class_lines)
    print(f"  {len(methods)} métodos encontrados")

    # 4. Separar métodos: Core vs mixins
    mixin_methods: dict[str, list[str]] = {k: [] for k in MIXIN_ORDER}
    core_method_blocks: list[str] = []

    seen = set()
    for name, (start, end) in sorted(methods.items(), key=lambda x: x[1][0]):
        if name in seen:
            continue
        seen.add(name)

        block = "".join(class_lines[start:end])

        target = METHOD_TO_MIXIN.get(name)
        if target:
            mixin_methods[target].append(block)
        else:
            core_method_blocks.append(block)

    # 5. Escrever arquivos de mixin
    for key in MIXIN_ORDER:
        if not mixin_methods[key]:
            print(f"  [WARN] {key}: nenhum método — pulando")
            continue

        dest = TOOLS_DIR / f"{key}.py"
        content = build_mixin_file(key, mixin_methods[key], module_header)
        dest.write_text(content, encoding="utf-8")

        n_methods = len(mixin_methods[key])
        n_lines = content.count("\n")
        print(f"  Escrito: {dest.name}  ({n_methods} métodos, ~{n_lines} linhas)")

    # 6. Reescrever Core.py
    new_core = build_new_core(module_header, class_docstring, core_method_blocks)
    CORE_PATH.write_text(new_core, encoding="utf-8")

    n_core_methods = len(core_method_blocks)
    n_core_lines = new_core.count("\n")
    print(f"  Reescrito: Core.py ({n_core_methods} métodos, ~{n_core_lines} linhas)")

    # 7. Criar __init__.py vazio se não existir (garante que o pacote reconhece os novos arquivos)
    init_path = TOOLS_DIR / "__init__.py"
    if not init_path.exists():
        init_path.write_text("", encoding="utf-8")
        print(f"  Criado: {init_path}")

    print("\nPronto! Verifique a sintaxe:")
    print("  python -m py_compile App/Features/Tools/Core.py")
    for key in MIXIN_ORDER:
        print(f"  python -m py_compile App/Features/Tools/{key}.py")


if __name__ == "__main__":
    main()
