"""
Exporta documentos e isolated_messages de um usuário real do banco para um arquivo fixture JSON.

Uso:
    python export_fixture.py --user-id <user_id> --stage <bmc|brandIdentity|product>
"""

import sys
import json
import argparse
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).parent.parent.parent.parent.parent.absolute()
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv

_env = BACKEND_DIR.parent.parent / ".env.development"
if _env.exists():
    load_dotenv(dotenv_path=str(_env), override=True)

DB_PATH = BACKEND_DIR / "Data" / "Database" / "MD70.db"

STAGE_CONFIG = {
    "bmc": {
        "tool_types": ["business_canvas"],
        "description": "Usuário com Business Canvas já criado. Próximo passo: BrandIdentity.",
        "output": "StageSettedUp-BMC.json",
    },
    "brandIdentity": {
        "tool_types": ["business_canvas", "brand_communication"],
        "description": "Usuário com Business Canvas e Brand Identity já criados. Próximo passo: Product.",
        "output": "StageSettedUp-BMC_N_BrandIdentity.json",
    },
    "product": {
        "tool_types": ["business_canvas", "brand_communication", "product"],
        "description": "Usuário com Business Canvas, Brand Identity e Product já criados. Próximo passo: Copywriting.",
        "output": "StageSettedUp-BMC_N_BrandIdentity_N_Product.json",
    },
}


def export_fixture(user_id: str, stage: str):
    cfg = STAGE_CONFIG[stage]
    engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"timeout": 10})
    session = sessionmaker(bind=engine)()
    try:
        placeholders = ", ".join(f"'{t}'" for t in cfg["tool_types"])

        doc_rows = session.execute(
            text(
                f"""
            SELECT tool_type, title, content, chat_id
            FROM documents
            WHERE user_id = :uid AND tool_type IN ({placeholders})
            ORDER BY created_at ASC, id ASC
        """
            ),
            {"uid": user_id},
        ).fetchall()

        if not doc_rows:
            print(
                f"❌ Nenhum documento encontrado para user_id={user_id} com tool_types={cfg['tool_types']}"
            )
            sys.exit(1)

        chat_ids = list(
            dict.fromkeys(row[3] for row in doc_rows)
        )  # preserva ordem, sem duplicatas
        chat_placeholders = ", ".join(f"'{cid}'" for cid in chat_ids)

        iso_rows = session.execute(
            text(
                f"""
            SELECT isolated_message_id, tool_call_id, tool_called, tool_call_type, fk_tool_id,
                   agent_id, agent, role, content, input_tokens, output_tokens, type,
                   context_window, provider_type, created_at
            FROM isolated_messages
            WHERE isolated_chat_id IN ({chat_placeholders})
            ORDER BY created_at ASC, id ASC
        """
            )
        ).fetchall()

    finally:
        session.close()

    documents = []
    for row in doc_rows:
        tool_type, title, content_raw, _ = row
        try:
            content = json.loads(content_raw)
        except (json.JSONDecodeError, TypeError):
            content = content_raw
        documents.append({"tool_type": tool_type, "title": title, "content": content})

    isolated_messages = []
    for row in iso_rows:
        (
            msg_id,
            tool_call_id,
            tool_called,
            tool_call_type,
            fk_tool_id,
            agent_id,
            agent,
            role,
            content_raw,
            input_tokens,
            output_tokens,
            msg_type,
            context_window,
            provider_type,
            created_at,
        ) = row
        try:
            content = json.loads(content_raw)
        except (json.JSONDecodeError, TypeError):
            content = content_raw
        isolated_messages.append(
            {
                "isolated_message_id": msg_id,
                "tool_call_id": tool_call_id,
                "tool_called": tool_called,
                "tool_call_type": tool_call_type,
                "fk_tool_id": fk_tool_id,
                "agent_id": agent_id,
                "agent": agent,
                "role": role,
                "content": content,
                "input_tokens": input_tokens or 0,
                "output_tokens": output_tokens or 0,
                "type": msg_type,
                "context_window": context_window,
                "provider_type": provider_type,
                "created_at": created_at,
            }
        )

    fixture = {
        "stage": stage,
        "description": cfg["description"],
        "documents": documents,
        "isolated_messages": isolated_messages,
    }

    out_path = Path(__file__).parent / cfg["output"]
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(fixture, f, ensure_ascii=False, indent=2)

    print(f"✅ Fixture exportado: {out_path.name}")
    print(f"   {len(documents)} documento(s):")
    for doc in documents:
        print(f"   - {doc['tool_type']}: {doc['title']}")
    print(f"   {len(isolated_messages)} isolated_message(s)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--user-id", required=True, help="user_id do usuário real no banco"
    )
    parser.add_argument(
        "--stage",
        required=True,
        choices=list(STAGE_CONFIG.keys()),
        help="Estágio a exportar: bmc, brandIdentity ou product",
    )
    args = parser.parse_args()
    export_fixture(args.user_id, args.stage)
