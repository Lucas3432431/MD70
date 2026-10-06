"""
Valida a biblioteca global de assets e documentos.

GET /api/chat/{chat_id} deve retornar:
  - assets: TODOS os assets do cliente, de todos os chats (não só do chat atual)
  - documents: todos os documentos do chat atual

Testes:
  01. Cria chat_A com 2 assets e chat_B com 2 assets para o mesmo cliente
  02. GET /api/chat/{chat_A} retorna 4 assets (chat_A + chat_B)
  03. GET /api/chat/{chat_B} retorna 4 assets (chat_A + chat_B)
  04. Cada asset retornado tem chat_id correto (não apenas o chat da requisição)
  05. Assets do chat_A têm link apontando para chat_A, e vice-versa
  06. GET /api/chat/{chat_A} inclui documents do chat_A
  07. GET /api/chat/{chat_B} inclui documents do chat_B
  08. Documents não vazam entre chats (chat_A não vê docs de chat_B e vice-versa)

Uso:
    cd App/mvp/services/backend
    python3 Scripts/Tests/GlobalLib/test_global_lib.py --start
    python3 Scripts/Tests/GlobalLib/test_global_lib.py --start --cleanup
"""

import sys
import os
import uuid
import json
import argparse
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--start", action="store_true")
_parser.add_argument("--base-url", default="http://localhost:4001")
_parser.add_argument("--cleanup", action="store_true")
_args, _ = _parser.parse_known_args()

if not _args.start:
    print("Informe --start para executar.")
    print("  python3 Scripts/Tests/GlobalLib/test_global_lib.py --start")
    sys.exit(1)

from dotenv import load_dotenv

_env = BACKEND_DIR.parent.parent / ".env.development"
if _env.exists():
    load_dotenv(dotenv_path=str(_env), override=True)

BASE_URL = _args.base_url.rstrip("/")
CLEANUP = _args.cleanup

from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Features.Auth.AuthService import get_auth_service
from Scripts.HealthCheck.health_check import run_health_check

SEP = "=" * 70
SEP2 = "-" * 70
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
DB_PATH = BACKEND_DIR / "Data" / "Database" / "MD70.db"

results: list[dict] = []
STATE = {
    "user_id": None,
    "client_id": None,
    "token": None,
    "chat_a": None,
    "chat_b": None,
    "assets_a": [],
    "assets_b": [],
    "doc_a": None,
    "doc_b": None,
}


def get_db():
    engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"timeout": 10})
    return sessionmaker(bind=engine)()


def step(label: str, *, passed: bool, detail: str = "") -> bool:
    icon = "[OK]  " if passed else "[FAIL]"
    print(f"\n{SEP2}\n  {icon} {label}")
    if detail:
        print(f"       {detail}")
    results.append({"label": label, "passed": passed})
    return passed


def save(name: str, data):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    p = OUTPUT_DIR / f"{ts}_{name}.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def _minimal_jpeg() -> bytes:
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
        b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
        b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e\x00"
        b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00"
        b"\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00"
        b"\x08\x01\x01\x00\x00?\x00\xfb\xd6\xff\xd9"
    )


def _http(method: str, path: str, **kwargs):
    import requests as _req

    cookies = {"access_token": STATE["token"]} if STATE["token"] else {}
    headers = kwargs.pop("headers", {"Content-Type": "application/json"})
    return getattr(_req, method)(
        f"{BASE_URL}{path}", cookies=cookies, headers=headers, timeout=15, **kwargs
    )


def _copy_doc(chat_id: str, label: str) -> dict:
    return {
        "document_id": str(uuid.uuid4()),
        "is_paid_ad": False,
        "channels": ["instagram"],
        "aspect_ratio": ["9:16", "4:5"],
        "framework": "PAS",
        "problem": f"Problema {label}",
        "agitate": "Agitação",
        "solution": "Solução",
        "hypothesy": "Hipótese",
        "hook_pain_awareness": "Hook",
        "empathy": "Empatia",
        "autority": "Autoridade",
        "solution_contious": "Solução",
        "product_contious": "Produto",
        "offer_concious": "Oferta",
        "archetype": "lider_visionario",
        "moodboard": "Tech",
        "minicopy": {
            "post_type": "topo_de_funil",
            "hook": "H",
            "trigger": "T",
            "cta": "C",
        },
        "caption": f"Caption {label}",
        "assets": [
            {
                "prompt": {
                    "description": f"{label} asset 0",
                    "has_realistic_people": False,
                },
                "angle": "",
                "background": "",
                "variation_label": "variation_1",
                "source_idx": 0,
                "format": "9:16",
                "asset_type": "img",
                "status": "toDo",
            },
            {
                "prompt": {
                    "description": f"{label} asset 1",
                    "has_realistic_people": False,
                },
                "angle": "",
                "background": "",
                "variation_label": "variation_1",
                "source_idx": 0,
                "format": "4:5",
                "asset_type": "img",
                "status": "toDo",
            },
        ],
        "variation": {"category": "Criativo", "count": 1},
        "variation_1": {
            "hook_variation": "H1",
            "cta_variation": "C1",
            "visual_focus": "V1",
        },
    }


# ── Setup ─────────────────────────────────────────────────────────────────────


def setup():
    print(f"\n{SEP}\n  SETUP\n{SEP}")
    auth = get_auth_service()
    tid = str(uuid.uuid4())[:8]
    ok, ud, err = auth.register_user(
        email=f"gl.{tid}@prox.test",
        password=f"Test@{tid}!",
        fingerprint_id=f"fp_gl_{tid}",
        fingerprint_components={},
        ip_address="127.0.0.1",
    )
    if not ok:
        print(f"  [ERRO] {err}")
        sys.exit(1)

    user_id = ud["user_id"]
    client_id = str(ud["client_id"])
    token = auth.generate_access_token(
        {
            "user_id": user_id,
            "client_id": client_id,
            "email": f"gl.{tid}@prox.test",
            "role": "member",
            "full_name": "GL Test",
        },
        save_to_db=True,
    )

    STATE.update({"user_id": user_id, "client_id": client_id, "token": token})
    print(f"  [OK] user={user_id} | client={client_id}")

    session = get_db()
    try:
        for label in ("A", "B"):
            chat_id = str(uuid.uuid4())
            session.execute(
                text(
                    """
                INSERT INTO chats (chat_id, user_id, chat_name, status, created_at, updated_at)
                VALUES (:cid, :uid, :name, 'active', datetime('now'), datetime('now'))
            """
                ),
                {"cid": chat_id, "uid": user_id, "name": f"GL Chat {label}"},
            )

            doc_id = str(uuid.uuid4())
            content = _copy_doc(chat_id, label)
            session.execute(
                text(
                    """
                INSERT INTO documents (document_id, tool_type, title, content, chat_id, user_id, client_id, created_at, updated_at)
                VALUES (:did, 'copywriting', :title, :content, :cid, :uid, :cl, datetime('now'), datetime('now'))
            """
                ),
                {
                    "did": doc_id,
                    "title": f"Doc {label}",
                    "content": json.dumps(content),
                    "cid": chat_id,
                    "uid": user_id,
                    "cl": client_id,
                },
            )

            STATE[f"chat_{label.lower()}"] = chat_id
            STATE[f"doc_{label.lower()}"] = doc_id
        session.commit()
    finally:
        session.close()

    print(f"  [OK] chat_A={STATE['chat_a']} | chat_B={STATE['chat_b']}")


# ── Fase 1: Geração de assets nos dois chats ──────────────────────────────────


def generate_assets():
    print(f"\n{SEP}\n  FASE 1: GERAÇÃO DE ASSETS (2 chats × 2 assets)\n{SEP}")

    from App.Features.Tools.Tools.Assets import generate_from_document

    fake_bytes = _minimal_jpeg()

    for label in ("a", "b"):
        chat_id = STATE[f"chat_{label}"]
        doc_id = STATE[f"doc_{label}"]
        prefix = chat_id[:8]
        idx = [0]

        def _mock(*args, _p=prefix, _i=idx, **kwargs):
            i = _i[0]
            _i[0] += 1
            return {
                "success": True,
                "filename": f"gl_{_p}_{i}.jpg",
                "content": fake_bytes,
            }

        with patch(
            "App.Features.Tools.Tools.Assets.run_model_logic", side_effect=_mock
        ):
            result = generate_from_document(
                document_id=doc_id,
                chat_id=chat_id,
                user_id=STATE["user_id"],
                db_manager=DatabaseManager,
            )

        session = get_db()
        try:
            rows = session.execute(
                text("SELECT asset_id FROM assets WHERE chat_id = :cid ORDER BY id"),
                {"cid": chat_id},
            ).fetchall()
        finally:
            session.close()

        STATE[f"assets_{label}"] = [r[0] for r in rows]
        ok = result.get("success") and len(rows) == 2
        step(
            f"0{'12'['ab'.index(label)]}. Geração chat_{label.upper()}: 2 assets criados",
            passed=ok,
            detail=f"success={result.get('success')} | assets_no_db={len(rows)}",
        )

    step(
        "03. Total: 4 assets únicos no DB (2 por chat)",
        passed=len(STATE["assets_a"]) + len(STATE["assets_b"]) == 4,
        detail=f"A={STATE['assets_a']} | B={STATE['assets_b']}",
    )


# ── Fase 2: Validação HTTP ────────────────────────────────────────────────────


def run_http_tests():
    import requests as _req

    print(f"\n{SEP}\n  FASE 2: VALIDAÇÃO HTTP — BIBLIOTECA GLOBAL\n{SEP}")

    all_asset_ids = set(STATE["assets_a"] + STATE["assets_b"])

    for num, (label, other) in enumerate([("a", "b"), ("b", "a")], start=4):
        chat_id = STATE[f"chat_{label}"]
        other_chat_id = STATE[f"chat_{other}"]

        r = _http("get", f"/api/chat/{chat_id}")
        save(
            f"0{num}_get_chat_{label.upper()}",
            r.json() if r.ok else {"status_code": r.status_code},
        )

        if not r.ok:
            step(
                f"0{num}. GET /chat/{label.upper()} → HTTP 200",
                passed=False,
                detail=f"HTTP {r.status_code}",
            )
            continue

        data = r.json()
        returned_ids = {a["asset_id"] for a in data.get("assets", [])}
        missing = all_asset_ids - returned_ids
        extra = returned_ids - all_asset_ids

        step(
            f"0{num}. GET /chat/{label.upper()} retorna os 4 assets globais do cliente",
            passed=len(missing) == 0,
            detail=f"total={len(returned_ids)} | missing={missing} | extra={extra}",
        )

    # 06: cada asset tem chat_id correto no response
    r = _http("get", f"/api/chat/{STATE['chat_a']}")
    assets = r.json().get("assets", []) if r.ok else []
    save(
        "06_assets_chat_ids",
        [{"asset_id": a["asset_id"], "chat_id": a.get("chat_id")} for a in assets],
    )

    assets_a_ids = set(STATE["assets_a"])
    assets_b_ids = set(STATE["assets_b"])
    chat_id_ok = all(
        (a["asset_id"] in assets_a_ids and a.get("chat_id") == STATE["chat_a"])
        or (a["asset_id"] in assets_b_ids and a.get("chat_id") == STATE["chat_b"])
        for a in assets
    )
    step(
        "06. Cada asset retornado tem chat_id correto (não o chat da requisição)",
        passed=chat_id_ok,
        detail=f"assets verificados={len(assets)}",
    )

    # 07: link aponta para o chat_id correto do asset
    link_ok = all(
        a.get("link", "").startswith(f"/api/chat/{a.get('chat_id')}/")
        for a in assets
        if a.get("chat_id")
    )
    step(
        "07. Link de cada asset aponta para o chat_id do asset (não da requisição)",
        passed=link_ok,
        detail=f"assets verificados={len(assets)}",
    )

    # 08: documents do chat_A aparecem no GET chat_A
    r_a = _http("get", f"/api/chat/{STATE['chat_a']}")
    docs_a = r_a.json().get("documents", []) if r_a.ok else []
    docs_a_ids = {d.get("document_id") for d in docs_a}
    step(
        "08. GET /chat/A inclui o documento criado no chat_A",
        passed=STATE["doc_a"] in docs_a_ids,
        detail=f"doc_a={STATE['doc_a']} | docs_retornados={docs_a_ids}",
    )

    # 09: documents do chat_A não aparecem no GET chat_B (docs são por chat)
    r_b = _http("get", f"/api/chat/{STATE['chat_b']}")
    docs_b = r_b.json().get("documents", []) if r_b.ok else []
    docs_b_ids = {d.get("document_id") for d in docs_b}
    step(
        "09. Documents são por chat: doc_A não aparece no GET /chat/B",
        passed=STATE["doc_a"] not in docs_b_ids,
        detail=f"doc_a={STATE['doc_a']} | docs_chat_B={docs_b_ids}",
    )


# ── Cleanup ───────────────────────────────────────────────────────────────────


def cleanup():
    session = get_db()
    try:
        for chat_id in (STATE["chat_a"], STATE["chat_b"]):
            if chat_id:
                session.execute(
                    text("DELETE FROM assets WHERE chat_id = :cid"), {"cid": chat_id}
                )
                session.execute(
                    text("DELETE FROM documents WHERE chat_id = :cid"), {"cid": chat_id}
                )
                session.execute(
                    text("DELETE FROM chats WHERE chat_id = :cid"), {"cid": chat_id}
                )
        if STATE["user_id"]:
            session.execute(
                text("DELETE FROM access_tokens WHERE user_id = :uid"),
                {"uid": STATE["user_id"]},
            )
            session.execute(
                text("DELETE FROM users WHERE user_id = :uid"),
                {"uid": STATE["user_id"]},
            )
        session.commit()
        print(f"\n  [CLEAN] Dados de teste removidos.")
    finally:
        session.close()


# ── Main ──────────────────────────────────────────────────────────────────────


def run():
    print(f"\n{SEP}\n  GLOBAL LIB TEST\n{SEP}")
    run_health_check(backend_url=BASE_URL, check_frontend=False)
    setup()
    generate_assets()
    run_http_tests()
    if CLEANUP:
        cleanup()


if __name__ == "__main__":
    run()

    print(f"\n{SEP}\nRESULTADO FINAL\n{SEP}")
    all_pass = True
    for r in results:
        icon = "[OK]  " if r["passed"] else "[FAIL]"
        print(f"  {icon} {r['label']}")
        if not r["passed"]:
            all_pass = False

    passed = sum(1 for r in results if r["passed"])
    print(f"\n  {passed}/{len(results)} testes passaram")
    print(f"  Outputs: {OUTPUT_DIR}\n")
    sys.exit(0 if all_pass else 1)
