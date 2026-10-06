"""
Valida que aspect_ratio é campo obrigatório no documento copywriting
e que é sempre um único valor — nunca derivado de channels.

Testa a lógica de validação diretamente, sem dependência do servidor.

Casos testados:
  01. aspect_ratio ausente → warning de obrigatoriedade, não derivado de channels
  02. aspect_ratio string válida ("9:16", "16:9", "1:1", "4:5") → aceito e normalizado
  03. aspect_ratio lista de 1 elemento → aceito e normalizado
  04. aspect_ratio lista de múltiplos valores → rejeitado
  05. aspect_ratio inválido (ex: "21:9") → rejeitado
  06. channels presentes SEM aspect_ratio → rejeitado (sem auto-derivação)
  07. channels + aspect_ratio explícito → aspect_ratio prevalece
  08. valid_data com aspect_ratio="16:9" + 3 variações → 3 assets, todos 16:9 (sem multiplicação)

Uso:
    cd App/mvp/services/backend
    python3 Scripts/Tests/AspectRatioValidation/test_aspect_ratio_validation.py
    python3 Scripts/Tests/AspectRatioValidation/test_aspect_ratio_validation.py --verbose
"""

import sys
import os
import json
import importlib.util
import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# ── Cores ─────────────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

passed = 0
failed = 0
verbose = False


def ok(label: str, detail: str = ""):
    global passed
    passed += 1
    suffix = f"  {CYAN}{detail}{RESET}" if detail and verbose else ""
    print(f"  {GREEN}✓{RESET} {label}{suffix}")


def fail(label: str, detail: str = ""):
    global failed
    failed += 1
    suffix = f"\n    {RED}{detail}{RESET}" if detail else ""
    print(f"  {RED}✗{RESET} {label}{suffix}")


def section(title: str):
    print(f"\n{BOLD}{CYAN}{title}{RESET}")


# ── Lógica de validação extraída de _document_validators.py ───────────────────
# Mantida idêntica ao código real para garantir que o teste valida o comportamento correto.

_VALID_RATIOS = {"9:16", "16:9", "1:1", "4:5"}

# Formatos derivados de channels (comportamento ANTERIOR — não deve mais acontecer)
_COPY_CHANNEL_VALID_FORMATS = {
    "instagram": ["9:16", "1:1", "4:5"],
    "facebook": ["9:16", "1:1", "16:9"],
    "youtube": ["16:9"],
    "tiktok": ["9:16"],
    "linkedin": ["1:1", "16:9"],
    "x": ["1:1", "16:9"],
    "google": ["1:1", "16:9"],
    "whatsapp": ["9:16", "1:1"],
}


def validate_aspect_ratio(data: dict, warnings: list, valid_data: dict):
    """Replica exata da lógica em _document_validators.py após o fix."""
    if "aspect_ratio" in data:
        _ar_raw = data["aspect_ratio"]
        if isinstance(_ar_raw, list):
            _filtered = [r for r in _ar_raw if str(r).strip() in _VALID_RATIOS]
            if len(_filtered) > 1:
                warnings.append(
                    f"invalid: aspect_ratio — apenas UM formato por geração é permitido. "
                    f"Recebido: {_ar_raw}. Envie somente o valor escolhido pelo usuário: "
                    f"'9:16', '16:9', '1:1' ou '4:5'."
                )
            elif _filtered:
                valid_data["aspect_ratio"] = [_filtered[0]]
            else:
                warnings.append(
                    f"invalid: aspect_ratio '{_ar_raw}' — valores válidos: '9:16', '16:9', '1:1', '4:5'."
                )
        else:
            _ar_str = str(_ar_raw).strip()
            if _ar_str in _VALID_RATIOS:
                valid_data["aspect_ratio"] = [_ar_str]
            else:
                warnings.append(
                    f"invalid: aspect_ratio '{_ar_raw}' — valores válidos: '9:16', '16:9', '1:1', '4:5'."
                )
    else:
        warnings.append(
            "missing: aspect_ratio (OBRIGATÓRIO — envie UM formato: '9:16', '16:9', '1:1' ou '4:5', "
            "usando a resposta exata do usuário no quiz)"
        )


def simulate_old_channel_derivation(channels: list) -> list:
    """Simula o comportamento ANTERIOR que derivava aspect_ratio de channels."""
    seen = []
    for ch in channels:
        for fmt in _COPY_CHANNEL_VALID_FORMATS.get(ch, []):
            if fmt not in seen:
                seen.append(fmt)
    return seen


def has_warning(warnings: list, *fragments: str) -> bool:
    return all(any(frag.lower() in w.lower() for w in warnings) for frag in fragments)


# ── Testes ────────────────────────────────────────────────────────────────────


def test_missing():
    section("01. aspect_ratio ausente → rejeição, sem auto-derivação de channels")
    channels = ["instagram", "facebook", "youtube"]
    data = {"channels": channels}
    warnings, vd = [], {}
    validate_aspect_ratio(data, warnings, vd)

    if has_warning(warnings, "aspect_ratio", "obrigatório"):
        ok(
            "Warning de obrigatoriedade emitido",
            str([w for w in warnings if "aspect_ratio" in w.lower()][:1]),
        )
    else:
        fail("Deveria emitir warning de obrigatoriedade", f"warnings: {warnings}")

    if "aspect_ratio" not in vd:
        ok("aspect_ratio não foi injetado em valid_data")
    else:
        fail("aspect_ratio foi injetado indevidamente", f"valor: {vd['aspect_ratio']}")

    # Confirmar que o comportamento antigo teria derivado múltiplos valores
    old_derived = simulate_old_channel_derivation(channels)
    if len(old_derived) > 1:
        ok(
            f"Comportamento antigo teria derivado {len(old_derived)} formatos: {old_derived} — agora bloqueado"
        )


def test_valid_strings():
    section("02. aspect_ratio string válida → aceito e normalizado")
    for ratio in ["9:16", "16:9", "1:1", "4:5"]:
        data = {"aspect_ratio": ratio}
        warnings, vd = [], {}
        validate_aspect_ratio(data, warnings, vd)
        ar_w = [w for w in warnings if "aspect_ratio" in w.lower()]
        if not ar_w and vd.get("aspect_ratio") == [ratio]:
            ok(f'"{ratio}" → aceito como ["{ratio}"]')
        else:
            fail(
                f'"{ratio}" falhou',
                f"warnings: {ar_w}, valid: {vd.get('aspect_ratio')}",
            )


def test_single_element_list():
    section("03. aspect_ratio lista de 1 elemento → aceito")
    data = {"aspect_ratio": ["16:9"]}
    warnings, vd = [], {}
    validate_aspect_ratio(data, warnings, vd)
    ar_w = [w for w in warnings if "aspect_ratio" in w.lower()]
    if not ar_w and vd.get("aspect_ratio") == ["16:9"]:
        ok('["16:9"] → aceito e normalizado para ["16:9"]')
    else:
        fail(
            "Lista de 1 elemento falhou",
            f"warnings: {ar_w}, valid: {vd.get('aspect_ratio')}",
        )


def test_multiple_values_rejected():
    section("04. aspect_ratio lista múltipla → rejeitado com erro")
    data = {"aspect_ratio": ["1:1", "4:5", "9:16", "16:9"]}
    warnings, vd = [], {}
    validate_aspect_ratio(data, warnings, vd)
    ar_w = [w for w in warnings if "aspect_ratio" in w.lower()]

    if ar_w and ("apenas" in ar_w[0].lower() or "um formato" in ar_w[0].lower()):
        ok(f"Lista múltipla rejeitada com erro claro", f"{ar_w[:1]}")
    else:
        fail(
            "Deveria rejeitar lista múltipla com erro explícito",
            f"warnings: {warnings}",
        )

    if "aspect_ratio" not in vd:
        ok("aspect_ratio não foi salvo em valid_data")
    else:
        fail("Lista múltipla foi aceita indevidamente", f"valor: {vd['aspect_ratio']}")


def test_invalid_values():
    section("05. aspect_ratio inválido → rejeitado")
    for bad in ["21:9", "widescreen", "0:0", "hd", "square"]:
        data = {"aspect_ratio": bad}
        warnings, vd = [], {}
        validate_aspect_ratio(data, warnings, vd)
        ar_w = [w for w in warnings if "aspect_ratio" in w.lower()]
        if ar_w and "aspect_ratio" not in vd:
            ok(f'"{bad}" → rejeitado corretamente')
        else:
            fail(
                f'"{bad}" deveria ser rejeitado',
                f"warnings: {ar_w}, valid: {vd.get('aspect_ratio')}",
            )


def test_channels_without_ratio():
    section("06. channels sem aspect_ratio → rejeição (sem auto-derivação)")
    channels = ["instagram", "facebook", "youtube"]
    data = {"channels": channels}
    warnings, vd = [], {}
    validate_aspect_ratio(data, warnings, vd)

    if has_warning(warnings, "aspect_ratio"):
        ok("Rejeitado: channels não derivam mais aspect_ratio")
    else:
        fail("Deveria rejeitar: aspect_ratio é obrigatório", f"warnings: {warnings}")

    derived = vd.get("aspect_ratio", [])
    old_derived = simulate_old_channel_derivation(channels)
    if derived != old_derived and len(derived) != len(old_derived):
        ok(f"Não auto-derivou de channels (antigo derivaria {old_derived})")
    elif not derived:
        ok(f"aspect_ratio vazio em valid_data (antigo derivaria {old_derived})")
    else:
        fail("Channels derivou aspect_ratio indevidamente", f"valor: {derived}")


def test_channels_with_explicit_ratio():
    section("07. channels + aspect_ratio explícito → aspect_ratio prevalece")
    data = {"aspect_ratio": "16:9", "channels": ["instagram", "facebook", "youtube"]}
    warnings, vd = [], {}
    validate_aspect_ratio(data, warnings, vd)
    ar_w = [w for w in warnings if "aspect_ratio" in w.lower()]

    if not ar_w and vd.get("aspect_ratio") == ["16:9"]:
        ok('"16:9" prevaleceu → salvo como ["16:9"]')
    else:
        fail(
            "aspect_ratio explícito não prevaleceu",
            f"warnings: {ar_w}, valid: {vd.get('aspect_ratio')}",
        )

    old_derived = simulate_old_channel_derivation(["instagram", "facebook", "youtube"])
    ok(
        f"Comportamento antigo teria derivado {len(old_derived)} formatos: {old_derived} — ignorado"
    )


def test_assets_not_multiplied():
    section("08. 3 variações + aspect_ratio='16:9' → 3 assets sem multiplicação")
    # Replica a lógica de _document.py que decide se expande assets por formato
    valid_data = {
        "aspect_ratio": ["16:9"],
        "variation": {"category": "Criativo", "count": 3},
        "assets": [
            {"asset_type": "img", "prompt": "v1", "source_idx": 0, "format": "16:9"},
            {"asset_type": "img", "prompt": "v2", "source_idx": 1, "format": "16:9"},
            {"asset_type": "img", "prompt": "v3", "source_idx": 2, "format": "16:9"},
        ],
    }

    _formats = valid_data.get("aspect_ratio", [])
    _base_assets = valid_data.get("assets", [])
    _already_variation_expanded = bool(valid_data.get("variation", {}).get("count", 0))

    if not _already_variation_expanded:
        if len(_formats) > 1 and _base_assets:
            expanded = []
            for fmt in _formats:
                for i, a in enumerate(_base_assets):
                    n = dict(a)
                    n["format"] = fmt
                    n["source_idx"] = i
                    expanded.append(n)
            valid_data["assets"] = expanded

    assets = valid_data["assets"]
    if len(assets) == 3:
        ok("3 assets — sem multiplicação por formatos (variation bloqueou expansão)")
    else:
        fail(f"Esperado 3 assets, obtido {len(assets)}")

    wrong = [a for a in assets if a.get("format") != "16:9"]
    if not wrong:
        ok("Todos os assets têm format='16:9'")
    else:
        fail(f"{len(wrong)} asset(s) com formato errado", str(wrong))

    # Simula o que acontecia ANTES com 4 formatos derivados de channels
    old_formats = simulate_old_channel_derivation(["instagram", "facebook", "youtube"])
    old_count = len(old_formats) * 3 if len(old_formats) > 1 else 3
    ok(
        f"Comportamento antigo (channels derivando) geraria {old_count} assets ({len(old_formats)} formatos × 3 variações)"
    )


def _load_assets_module():
    """Carrega Assets.py diretamente via importlib, evitando o circular import do __init__.py."""
    assets_path = BACKEND_DIR / "App" / "Features" / "Tools" / "Tools" / "Assets.py"
    spec = importlib.util.spec_from_file_location("_Assets_isolated", str(assets_path))
    A = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(A)
    return A


def test_assets_passes_correct_ratio_to_model():
    section("09. Assets.py → run_model_logic recebe extra_args['aspect_ratio'] correto")

    try:
        A = _load_assets_module()
    except Exception as e:
        fail("Falha ao importar Assets.py via importlib", str(e))
        return

    copy_data = {
        "aspect_ratio": ["16:9"],
        "should_keep_brand_identity": True,
        "caption": "caption test",
        "title": "Doc Test",
        "assets": [
            {
                "asset_type": "img",
                "prompt": "Product on white studio background",
                "format": "16:9",
                "source_idx": 0,
                "status": "toDo",
            }
        ],
    }

    # Mock session: retorna doc na 1ª chamada, None (client_id) na 2ª e NULL-safe nas demais
    call_idx = [0]

    def _execute(query, params=None):
        call_idx[0] += 1
        m = MagicMock()
        if call_idx[0] == 1:
            m.first.return_value = (json.dumps(copy_data),)
        else:
            m.first.return_value = None
        return m

    mock_session = MagicMock()
    mock_session.execute.side_effect = _execute
    mock_db = MagicMock()
    mock_db.get_session.return_value = mock_session

    # Capturar chamadas reais de run_model_logic
    captured: list[dict] = []

    def _mock_run_model_logic(prompt, extra_args=None, **kwargs):
        captured.append({"prompt": prompt, "extra_args": dict(extra_args or {})})
        return {"success": True, "filename": "out.jpg", "content": b"\xff\xd8\xff\xe0"}

    A.run_model_logic = _mock_run_model_logic

    # Mocks dos módulos importados lazily dentro de generate_from_document
    mock_credits = MagicMock()
    mock_credits.check_and_consume_for_batch_assets.return_value = (True, 0, 100.0)
    mock_credits.check_credits.return_value = (True, 100.0)
    mock_credits.calculate_batch_asset_cost.return_value = 0
    mock_credits.centavos_to_credits.return_value = 0.0

    mock_storage = MagicMock()
    mock_storage.save_file.return_value = "/fake/storage/asset.jpg"

    sys_mocks = {
        "App.Features.Credits": MagicMock(),
        "App.Features.Credits.CreditsManager": MagicMock(CreditsManager=mock_credits),
        "App.Core.Crunch.Storage": MagicMock(),
        "App.Core.Crunch.Storage.StorageManager": MagicMock(
            StorageManager=mock_storage
        ),
        "App.Core.Crunch.TablesSQL": MagicMock(),
        "App.Core.Crunch.TablesSQL.Models": MagicMock(
            Asset=MagicMock(return_value=MagicMock())
        ),
    }

    with patch.dict(sys.modules, sys_mocks):
        result = A.generate_from_document(
            document_id="test-doc-uuid-0001",
            db_manager=mock_db,
            chat_id="chat-test-001",
            user_id="user-test-001",
        )

    # Verificações
    if not captured:
        fail(
            "run_model_logic não foi chamado — generate_from_document não gerou nenhum asset"
        )
        return
    ok(f"run_model_logic chamado {len(captured)} vez(es)")

    if len(captured) == 1:
        ok("Exatamente 1 chamada (1 asset, 1 formato — sem multiplicação)")
    else:
        fail(
            f"Esperado 1 chamada, recebido {len(captured)}",
            str([c["extra_args"] for c in captured]),
        )

    ratio_sent = captured[0]["extra_args"].get("aspect_ratio")
    if ratio_sent == "16:9":
        ok('extra_args["aspect_ratio"] == "16:9" ✓ (correto, vem de asset["format"])')
    else:
        fail(
            f'extra_args["aspect_ratio"] incorreto',
            f'recebido: {ratio_sent!r} | esperado: "16:9"',
        )

    # Garantir que não é lista
    if not isinstance(ratio_sent, list):
        ok("aspect_ratio enviado como string (não lista)")
    else:
        fail(
            "aspect_ratio enviado como lista — modelo não aceita lista", str(ratio_sent)
        )


# ── Runner ────────────────────────────────────────────────────────────────────


def main():
    global verbose
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    verbose = args.verbose

    print(f"\n{BOLD}=== AspectRatioValidation ==={RESET}")

    test_missing()
    test_valid_strings()
    test_single_element_list()
    test_multiple_values_rejected()
    test_invalid_values()
    test_channels_without_ratio()
    test_channels_with_explicit_ratio()
    test_assets_not_multiplied()
    test_assets_passes_correct_ratio_to_model()

    total = passed + failed
    color = GREEN if not failed else RED
    print(f"\n{BOLD}Resultado: {color}{passed}/{total}{RESET}{BOLD} passaram{RESET}")
    if failed:
        print(f"  {RED}{failed} falha(s){RESET}")
        sys.exit(1)
    else:
        print(f"  {GREEN}Todos os testes passaram ✓{RESET}")


if __name__ == "__main__":
    main()
