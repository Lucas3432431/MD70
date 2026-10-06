"""
Testa o fluxo de variation_id e aprovação de assets.

Valida:
  01. generate_from_document() cria 4 assets com variation_id preenchido
  02. Assets do mesmo source_idx compartilham o mesmo variation_id (UUID)
  03. Assets de source_idx diferentes têm variation_ids distintos
  04. DB confirma variation_id + status_id=NULL antes de qualquer julgamento
  05. POST /approve → HTTP 200, status='approved' no body
  06. DB confirma approving_logs criado e assets.status_id preenchido após approve
  07. POST /discard → HTTP 200, status='discarded' no body
  08. DB confirma status='discarded' em approving_logs após discard
  09. POST /improve com feedback → HTTP 200, status='improve' no body
  10. DB confirma status='improve' e feedback salvo em approving_logs após improve
  11. POST /improve sem feedback → HTTP 400
  12. GET /api/chat/{chat_id} retorna variation_id e approval_status corretos nos assets

Uso:
    cd App/mvp/services/backend
    python3 Scripts/Tests/AssetVariationJudge/test_asset_variation_judge.py --start
    python3 Scripts/Tests/AssetVariationJudge/test_asset_variation_judge.py --start --cleanup
    python3 Scripts/Tests/AssetVariationJudge/test_asset_variation_judge.py --start --base-url http://localhost:4001

Pré-requisito: servidor rodando no BASE_URL para os testes HTTP (05-12).
Testes 01-04 rodam offline (chamada direta ao Python).
"""

import sys
import os
import uuid
import json
import argparse
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

# ── Path e ENV ────────────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--start", action="store_true", help="Executar testes")
_parser.add_argument("--base-url", default="http://localhost:4001")
_parser.add_argument("--cleanup", action="store_true")
_args, _ = _parser.parse_known_args()

if not _args.start:
    print("Informe --start para executar os testes.")
    print(
        "  python3 Scripts/Tests/AssetVariationJudge/test_asset_variation_judge.py --start"
    )
    sys.exit(1)

from dotenv import load_dotenv

_env_file = BACKEND_DIR.parent.parent / ".env.development"
if _env_file.exists():
    load_dotenv(dotenv_path=str(_env_file), override=True)

BASE_URL = _args.base_url.rstrip("/")
CLEANUP = _args.cleanup

from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker

from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Features.Auth.AuthService import get_auth_service
from Scripts.HealthCheck.health_check import run_health_check

# ── Constantes ────────────────────────────────────────────────────────────────
SEP = "=" * 70
SEP2 = "-" * 70

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

DB_PATH = BACKEND_DIR / "Data" / "Database" / "MD70.db"

results: list[dict] = []

# Estado global do teste — preenchido durante setup
TEST_STATE = {
    "user_id": None,
    "client_id": None,
    "chat_id": None,
    "doc_id": None,
    "asset_ids": [],
    "token": None,
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def get_db_session():
    engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"timeout": 10})
    return sessionmaker(bind=engine)()


def step(label: str, *, passed: bool, detail: str = "") -> bool:
    icon = "[OK]  " if passed else "[FAIL]"
    print(f"\n{SEP2}\n  {icon} {label}")
    if detail:
        print(f"       {detail}")
    results.append({"label": label, "passed": passed})
    return passed


def save_output(name: str, data):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUTPUT_DIR / f"{ts}_{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    return path


def _minimal_jpeg() -> bytes:
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
        b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
        b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e\x00"
        b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00"
        b"\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00"
        b"\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00"
        b'\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07"q\x142\x81'
        b"\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n\x16\x17\x18\x19"
        b"\x1a%&'()*456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz\x83\x84\x85\x86"
        b"\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4"
        b"\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2"
        b"\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9"
        b"\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5"
        b"\xf6\xf7\xf8\xf9\xfa\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xd6"
        b"\xff\xd9"
    )


def _http(method: str, path: str, **kwargs):
    """Faz chamada HTTP autenticada via cookie access_token."""
    import requests as _req

    token = TEST_STATE["token"]
    cookies = {"access_token": token} if token else {}
    headers = kwargs.pop("headers", {})
    headers.setdefault("Content-Type", "application/json")
    url = f"{BASE_URL}{path}"
    return getattr(_req, method)(
        url, cookies=cookies, headers=headers, timeout=15, **kwargs
    )


# ── Setup: usuário real via AuthService ───────────────────────────────────────


def setup():
    print(f"\n{SEP}\n  SETUP: criando usuário de teste\n{SEP}")

    auth_service = get_auth_service()
    test_id = str(uuid.uuid4())[:8]
    email = f"avj.{test_id}@prox.test"
    password = f"Test@{test_id}!"

    ok, user_data, err = auth_service.register_user(
        email=email,
        password=password,
        fingerprint_id=f"fp_avj_{test_id}",
        fingerprint_components={},
        ip_address="127.0.0.1",
    )
    if not ok:
        print(f"  [ERRO] Falha ao criar usuário: {err}")
        sys.exit(1)

    user_id = user_data["user_id"]
    client_id = str(user_data["client_id"])

    user_payload = {
        "user_id": user_id,
        "client_id": client_id,
        "email": email,
        "role": "member",
        "full_name": "AVJ Test",
    }
    token = auth_service.generate_access_token(user_payload, save_to_db=True)

    print(f"  [OK] Usuário: {email} | user_id={user_id} | client_id={client_id}")
    print(f"  [OK] Token:   {token[:40]}...")

    # Criar chat no DB
    chat_id = str(uuid.uuid4())
    session = get_db_session()
    try:
        session.execute(
            text(
                """
            INSERT INTO chats (chat_id, user_id, chat_name, status, created_at, updated_at)
            VALUES (:cid, :uid, 'AVJ Test Chat', 'active', datetime('now'), datetime('now'))
        """
            ),
            {"cid": chat_id, "uid": user_id},
        )

        # Documento copywriting com 4 assets (2 variações × 2 formatos)
        copy_data = {
            "document_id": str(uuid.uuid4()),
            "is_paid_ad": True,
            "channels": ["instagram"],
            "aspect_ratio": ["9:16", "4:5"],
            "framework": "PAS",
            "problem": "Equipes perdem tempo com gestão manual",
            "agitate": "Reuniões improdutivas consomem horas",
            "solution": "MD70 automatiza sprints",
            "hypothesy": "Ferramenta certa muda a dinâmica",
            "hook_pain_awareness": "Sua equipe ainda gerencia projetos no Excel?",
            "empathy": "Sabemos que a pressão é real",
            "autority": "Usado por +200 empresas",
            "solution_contious": "MD70 centraliza tudo",
            "product_contious": "Dashboards em tempo real",
            "offer_concious": "Teste grátis por 14 dias",
            "archetype": "lider_visionario",
            "moodboard": "Tech minimalista",
            "minicopy": {
                "post_type": "topo_de_funil",
                "hook": "Hook",
                "trigger": "Dor",
                "cta": "Teste",
            },
            "caption": "Caption de teste",
            "assets": [
                {
                    "prompt": {
                        "description": "Profissional usando MD70 em laptop moderno",
                        "has_realistic_people": True,
                        "subject_context": "Pessoa usando laptop com dashboard de projetos",
                        "models": [
                            {
                                "sex": "male",
                                "age": "30-35",
                                "skin_color": "white",
                                "style": "business casual",
                                "skin_texture_moisture": "natural_glow",
                            }
                        ],
                        "pose": "Sentado em mesa, olhando para tela",
                        "composition": {"angle": "CloseUpShot", "grid": "RuleOfThirds"},
                        "environment": {
                            "place": "Escritório moderno",
                            "objects": ["laptop", "notebook"],
                        },
                        "colors": {
                            "background": {"hex": ["#F8FAFC"], "bg_type": "office"},
                            "subject": {"hex": ["#0078FF"]},
                            "accent": {"hex": ["#FFFFFF"]},
                            "saturation_contrast": "High",
                            "harmony": "Analogous",
                        },
                        "illumination": "Natural",
                        "emotion_style": "Focado e produtivo",
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
                        "description": "Profissional usando MD70 em laptop moderno",
                        "has_realistic_people": True,
                        "subject_context": "Pessoa usando laptop com dashboard de projetos",
                        "models": [
                            {
                                "sex": "male",
                                "age": "30-35",
                                "skin_color": "white",
                                "style": "business casual",
                                "skin_texture_moisture": "natural_glow",
                            }
                        ],
                        "pose": "Sentado em mesa, olhando para tela",
                        "composition": {"angle": "CloseUpShot", "grid": "RuleOfThirds"},
                        "environment": {
                            "place": "Escritório moderno",
                            "objects": ["laptop", "notebook"],
                        },
                        "colors": {
                            "background": {"hex": ["#F8FAFC"], "bg_type": "office"},
                            "subject": {"hex": ["#0078FF"]},
                            "accent": {"hex": ["#FFFFFF"]},
                            "saturation_contrast": "High",
                            "harmony": "Analogous",
                        },
                        "illumination": "Natural",
                        "emotion_style": "Focado e produtivo",
                    },
                    "angle": "",
                    "background": "",
                    "variation_label": "variation_1",
                    "source_idx": 0,
                    "format": "4:5",
                    "asset_type": "img",
                    "status": "toDo",
                },
                {
                    "prompt": {
                        "description": "Executivo apresentando métricas com tablet em sala de reunião",
                        "has_realistic_people": True,
                        "subject_context": "Executivo segurando tablet com gráficos de sprint",
                        "models": [
                            {
                                "sex": "male",
                                "age": "38-45",
                                "skin_color": "white",
                                "style": "executive",
                                "skin_texture_moisture": "natural_glow",
                            }
                        ],
                        "pose": "Em pé, segurando tablet para câmera",
                        "composition": {"angle": "MidBodyShot", "grid": "Centralized"},
                        "environment": {
                            "place": "Sala de reunião corporativa",
                            "objects": ["tablet", "whiteboard"],
                        },
                        "colors": {
                            "background": {"hex": ["#EFF6FF"], "bg_type": "office"},
                            "subject": {"hex": ["#0056B3"]},
                            "accent": {"hex": ["#0078FF"]},
                            "saturation_contrast": "High",
                            "harmony": "Monochromatic",
                        },
                        "illumination": "Studio",
                        "emotion_style": "Decisivo e confiante",
                    },
                    "angle": "",
                    "background": "",
                    "variation_label": "variation_2",
                    "source_idx": 1,
                    "format": "9:16",
                    "asset_type": "img",
                    "status": "toDo",
                },
                {
                    "prompt": {
                        "description": "Executivo apresentando métricas com tablet em sala de reunião",
                        "has_realistic_people": True,
                        "subject_context": "Executivo segurando tablet com gráficos de sprint",
                        "models": [
                            {
                                "sex": "male",
                                "age": "38-45",
                                "skin_color": "white",
                                "style": "executive",
                                "skin_texture_moisture": "natural_glow",
                            }
                        ],
                        "pose": "Em pé, segurando tablet para câmera",
                        "composition": {"angle": "MidBodyShot", "grid": "Centralized"},
                        "environment": {
                            "place": "Sala de reunião corporativa",
                            "objects": ["tablet", "whiteboard"],
                        },
                        "colors": {
                            "background": {"hex": ["#EFF6FF"], "bg_type": "office"},
                            "subject": {"hex": ["#0056B3"]},
                            "accent": {"hex": ["#0078FF"]},
                            "saturation_contrast": "High",
                            "harmony": "Monochromatic",
                        },
                        "illumination": "Studio",
                        "emotion_style": "Decisivo e confiante",
                    },
                    "angle": "",
                    "background": "",
                    "variation_label": "variation_2",
                    "source_idx": 1,
                    "format": "4:5",
                    "asset_type": "img",
                    "status": "toDo",
                },
            ],
            "variation": {"category": "Criativo", "count": 2},
            "variation_1": {
                "hook_variation": "Hook 1",
                "cta_variation": "CTA 1",
                "visual_focus": "Interface",
            },
            "variation_2": {
                "hook_variation": "Hook 2",
                "cta_variation": "CTA 2",
                "visual_focus": "Resultado",
            },
        }

        doc_id = str(uuid.uuid4())
        session.execute(
            text(
                """
            INSERT INTO documents (document_id, tool_type, title, content, chat_id, user_id, client_id, created_at, updated_at)
            VALUES (:did, 'copywriting', 'Copy - AVJ Test', :content, :chat_id, :uid, :cid, datetime('now'), datetime('now'))
        """
            ),
            {
                "did": doc_id,
                "content": json.dumps(copy_data, ensure_ascii=False),
                "chat_id": chat_id,
                "uid": user_id,
                "cid": client_id,
            },
        )
        session.commit()
    finally:
        session.close()

    TEST_STATE.update(
        {
            "user_id": user_id,
            "client_id": client_id,
            "chat_id": chat_id,
            "doc_id": doc_id,
            "token": token,
        }
    )

    print(f"  [OK] Chat:    {chat_id}")
    print(f"  [OK] Doc:     {doc_id}")


# ── Fase 1: Geração (01-04) ───────────────────────────────────────────────────


def run_generation_tests():
    print(f"\n{SEP}\n  FASE 1: GERAÇÃO — variation_id\n{SEP}")

    from App.Features.Tools.Tools.Assets import generate_from_document

    fake_bytes = _minimal_jpeg()
    doc_id = TEST_STATE["doc_id"]
    chat_id = TEST_STATE["chat_id"]
    user_id = TEST_STATE["user_id"]

    # side_effect com filename único por chamada + por run → evita UNIQUE constraint
    run_prefix = chat_id[:8]
    _call_idx = [0]

    def _mock_model(*args, **kwargs):
        i = _call_idx[0]
        _call_idx[0] += 1
        return {
            "success": True,
            "filename": f"asset_avj_{run_prefix}_{i}.jpg",
            "content": fake_bytes,
        }

    with patch(
        "App.Features.Tools.Tools.Assets.run_model_logic", side_effect=_mock_model
    ):
        result = generate_from_document(
            document_id=doc_id,
            chat_id=chat_id,
            user_id=user_id,
            db_manager=DatabaseManager,
        )

    save_output("01_generate_result", result)

    # 01: geração bem-sucedida
    step(
        "01. generate_from_document() retorna sucesso",
        passed=result.get("success", False),
        detail=f"message={result.get('message')} | assets={len(result.get('generated_assets', []))}",
    )

    # Consultar DB
    session = get_db_session()
    try:
        rows = session.execute(
            text(
                "SELECT asset_id, variation_id FROM assets WHERE chat_id = :cid ORDER BY id"
            ),
            {"cid": chat_id},
        ).fetchall()
    finally:
        session.close()

    save_output("02_assets_db", [dict(r._mapping) for r in rows])

    # 02: 4 assets com variation_id preenchido
    all_have_vid = all(r[1] for r in rows)
    step(
        "02. Todos os 4 assets têm variation_id preenchido",
        passed=all_have_vid and len(rows) == 4,
        detail=f"{len(rows)} assets | variation_ids={[r[1][:8] + '…' for r in rows]}",
    )

    # 03: 2 variation_ids distintos, cada um aparece exatamente 2 vezes (1 por formato)
    from collections import Counter

    vid_counts = Counter(r[1] for r in rows)
    exactly_two_groups = len(vid_counts) == 2
    each_group_has_two = all(c == 2 for c in vid_counts.values())
    step(
        "03. Exatamente 2 variation_ids distintos, cada um em 2 assets (2 formatos por variação)",
        passed=exactly_two_groups and each_group_has_two,
        detail=f"groups={dict(vid_counts)}",
    )

    # 04: status_id=NULL antes de qualquer julgamento
    session = get_db_session()
    try:
        null_rows = session.execute(
            text(
                "SELECT asset_id FROM assets WHERE chat_id = :cid AND status_id IS NULL"
            ),
            {"cid": chat_id},
        ).fetchall()
    finally:
        session.close()

    step(
        "04. status_id=NULL em todos os assets antes de qualquer julgamento",
        passed=len(null_rows) == 4,
        detail=f"{len(null_rows)} assets sem julgamento",
    )

    TEST_STATE["asset_ids"] = [r[0] for r in rows]


# ── Fase 2: Rotas HTTP de julgamento (05-12) ──────────────────────────────────


def run_http_tests():
    import requests as _req

    print(f"\n{SEP}\n  FASE 2: ROTAS HTTP DE JULGAMENTO\n{SEP}")
    print(f"  [INFO] BASE_URL: {BASE_URL}")

    # Verificar servidor
    try:
        r = _req.get(f"{BASE_URL}/api/health", timeout=5)
        server_ok = r.status_code < 500
    except Exception as e:
        print(f"\n  [WARN] Servidor não acessível em {BASE_URL}: {e}")
        _skip_labels = [
            "05. POST /approve → HTTP 200, status='approved'",
            "06. DB confirma approving_logs criado e assets.status_id preenchido",
            "07. POST /discard → HTTP 200, status='discarded'",
            "08. DB confirma status='discarded' em approving_logs",
            "07. POST /discard sem feedback → HTTP 400",
            "08. POST /discard com feedback → HTTP 200, status='discarded'",
            "09. DB confirma status='discarded' em approving_logs",
            "10. POST /improve com feedback → HTTP 200, status='improve'",
            "11. DB confirma status='improve' e feedback salvo",
            "12. POST /improve sem feedback → HTTP 400",
            "13. GET /api/chat/{chat_id} retorna variation_id e approval_status",
        ]
        for lbl in _skip_labels:
            results.append({"label": lbl, "passed": None})
            print(f"  [SKIP] {lbl}")
        return

    asset_ids = TEST_STATE["asset_ids"]
    chat_id = TEST_STATE["chat_id"]

    a_approve = asset_ids[0]
    a_discard = asset_ids[1]
    a_improve = asset_ids[2]

    # ── 05: approve ───────────────────────────────────────────────────────────
    r = _http("post", f"/api/chat/{chat_id}/asset/{a_approve}/approve", json={})
    save_output(
        "05_approve_response",
        r.json() if r.ok else {"status_code": r.status_code, "text": r.text[:300]},
    )
    body = r.json() if r.ok else {}
    step(
        "05. POST /approve → HTTP 200, status='approved'",
        passed=r.status_code == 200 and body.get("status") == "approved",
        detail=f"HTTP {r.status_code} | body={json.dumps(body)[:150]}",
    )

    # ── 06: DB após approve ───────────────────────────────────────────────────
    session = get_db_session()
    try:
        row = session.execute(
            text(
                """
                SELECT al.status, al.approving_id, a.status_id
                FROM assets a
                LEFT JOIN approving_logs al ON a.status_id = al.id
                WHERE a.asset_id = :aid
            """
            ),
            {"aid": a_approve},
        ).first()
    finally:
        session.close()

    save_output("06_db_after_approve", dict(row._mapping) if row else {})
    db_ok = row and row[0] == "approved" and row[1] is not None and row[2] is not None
    step(
        "06. DB confirma approving_logs criado e assets.status_id preenchido",
        passed=bool(db_ok),
        detail=f"status={row[0] if row else None} | approving_id={str(row[1])[:8]+'…' if row and row[1] else None} | status_id={row[2] if row else None}",
    )

    # ── 07: discard sem feedback → 400 ───────────────────────────────────────
    r = _http("post", f"/api/chat/{chat_id}/asset/{a_discard}/discard", json={})
    save_output(
        "07_discard_no_feedback", {"status_code": r.status_code, "text": r.text[:300]}
    )
    step(
        "07. POST /discard sem feedback → HTTP 400",
        passed=r.status_code == 400,
        detail=f"HTTP {r.status_code}",
    )

    # ── 08: discard com feedback ──────────────────────────────────────────────
    discard_feedback = "Composição não alinha com o moodboard definido"
    r = _http(
        "post",
        f"/api/chat/{chat_id}/asset/{a_discard}/discard",
        json={"feedback": discard_feedback},
    )
    save_output(
        "08_discard_response",
        r.json() if r.ok else {"status_code": r.status_code, "text": r.text[:300]},
    )
    body = r.json() if r.ok else {}
    step(
        "08. POST /discard com feedback → HTTP 200, status='discarded'",
        passed=r.status_code == 200 and body.get("status") == "discarded",
        detail=f"HTTP {r.status_code} | body={json.dumps(body)[:150]}",
    )

    # ── 09: DB após discard ───────────────────────────────────────────────────
    session = get_db_session()
    try:
        row = session.execute(
            text(
                """
                SELECT al.status, al.feedback
                FROM assets a
                LEFT JOIN approving_logs al ON a.status_id = al.id
                WHERE a.asset_id = :aid
            """
            ),
            {"aid": a_discard},
        ).first()
    finally:
        session.close()

    save_output("09_db_after_discard", dict(row._mapping) if row else {})
    step(
        "09. DB confirma status='discarded' em approving_logs",
        passed=bool(row and row[0] == "discarded" and row[1] == discard_feedback),
        detail=f"status={row[0] if row else None} | feedback={row[1] if row else None}",
    )

    # ── 10: improve com feedback ──────────────────────────────────────────────
    feedback_txt = "Ajustar enquadramento: mais espaço no topo para texto sobreposto"
    r = _http(
        "post",
        f"/api/chat/{chat_id}/asset/{a_improve}/improve",
        json={"feedback": feedback_txt},
    )
    save_output(
        "10_improve_response",
        r.json() if r.ok else {"status_code": r.status_code, "text": r.text[:300]},
    )
    body = r.json() if r.ok else {}
    step(
        "10. POST /improve com feedback → HTTP 200, status='improve'",
        passed=r.status_code == 200 and body.get("status") == "improve",
        detail=f"HTTP {r.status_code} | body={json.dumps(body)[:150]}",
    )

    # ── 11: DB após improve ───────────────────────────────────────────────────
    session = get_db_session()
    try:
        row = session.execute(
            text(
                """
                SELECT al.status, al.feedback
                FROM assets a
                LEFT JOIN approving_logs al ON a.status_id = al.id
                WHERE a.asset_id = :aid
            """
            ),
            {"aid": a_improve},
        ).first()
    finally:
        session.close()

    save_output("11_db_after_improve", dict(row._mapping) if row else {})
    feedback_ok = row and row[0] == "improve" and row[1] == feedback_txt
    step(
        "11. DB confirma status='improve' e feedback salvo em approving_logs",
        passed=bool(feedback_ok),
        detail=f"status={row[0] if row else None} | feedback={row[1][:50] + '…' if row and row[1] else None}",
    )

    # ── 12: improve sem feedback → 400 ───────────────────────────────────────
    r = _http("post", f"/api/chat/{chat_id}/asset/{a_improve}/improve", json={})
    save_output(
        "12_improve_no_feedback", {"status_code": r.status_code, "text": r.text[:300]}
    )
    step(
        "12. POST /improve sem feedback → HTTP 400",
        passed=r.status_code == 400,
        detail=f"HTTP {r.status_code}",
    )

    # ── 13: GET /api/chat retorna variation_id e approval_status ─────────────
    r = _http("get", f"/api/chat/{chat_id}")
    save_output(
        "13_get_chat_response", r.json() if r.ok else {"status_code": r.status_code}
    )

    if not r.ok:
        step(
            "13. GET /api/chat/{chat_id} retorna variation_id e approval_status",
            passed=False,
            detail=f"HTTP {r.status_code}",
        )
        return

    chat_data = r.json()
    assets = chat_data.get("assets", [])
    save_output("13_get_chat_assets", assets)

    has_vid = all("variation_id" in a for a in assets)
    has_status = all("approval_status" in a for a in assets)
    approved = next((a for a in assets if a.get("asset_id") == a_approve), None)
    status_ok = approved is not None and approved.get("approval_status") == "approved"

    step(
        "13. GET /api/chat/{chat_id} retorna variation_id e approval_status corretos",
        passed=has_vid and has_status and status_ok,
        detail=(
            f"assets={len(assets)} | has_variation_id={has_vid} "
            f"| has_approval_status={has_status} | approved_asset_ok={status_ok}"
        ),
    )


# ── Cleanup ───────────────────────────────────────────────────────────────────


def cleanup():
    chat_id = TEST_STATE.get("chat_id")
    user_id = TEST_STATE.get("user_id")
    if not chat_id:
        return

    session = get_db_session()
    try:
        # approving_logs são excluídos em cascata por assets (ON DELETE CASCADE)
        session.execute(
            text("DELETE FROM assets WHERE chat_id = :cid"), {"cid": chat_id}
        )
        session.execute(
            text("DELETE FROM documents WHERE chat_id = :cid"), {"cid": chat_id}
        )
        session.execute(
            text("DELETE FROM chats WHERE chat_id = :cid"), {"cid": chat_id}
        )
        if user_id:
            session.execute(
                text("DELETE FROM access_tokens WHERE user_id = :uid"), {"uid": user_id}
            )
            session.execute(
                text("DELETE FROM users WHERE user_id = :uid"), {"uid": user_id}
            )
        session.commit()
        print(f"\n  [CLEAN] chat={chat_id} e dados removidos.")
    finally:
        session.close()


# ── Main ──────────────────────────────────────────────────────────────────────


def run():
    print(f"\n{SEP}\n  ASSET VARIATION + JUDGE TEST\n{SEP}")

    run_health_check(backend_url=BASE_URL, check_frontend=False)
    setup()
    run_generation_tests()
    run_http_tests()

    if CLEANUP:
        cleanup()


if __name__ == "__main__":
    run()

    print(f"\n{SEP}\nRESULTADO FINAL\n{SEP}")
    all_pass = True
    skipped = 0
    for r in results:
        if r["passed"] is None:
            print(f"  [SKIP] {r['label']}")
            skipped += 1
        else:
            icon = "[OK]  " if r["passed"] else "[FAIL]"
            print(f"  {icon} {r['label']}")
            if not r["passed"]:
                all_pass = False

    total = len(results) - skipped
    passed = sum(1 for r in results if r["passed"] is True)
    print(f"\n  {passed}/{total} testes passaram ({skipped} pulados)")
    print(f"  Outputs: {OUTPUT_DIR}\n")

    sys.exit(0 if all_pass else 1)
