"""
Gate Validation — testa o sistema de gate sequencial para SkillCopywriting (hardcoded)
e SkillCatalog (JSON engine), nos dois fluxos possíveis do copywriting.

Fluxos testados:
  ── COPYWRITING ATTACHMENT FLOW ──
  A1. Após lookup, web-search bloqueado (quiz obrigatório primeiro)
  A2. Após lookup, document bloqueado (quiz obrigatório primeiro)
  A3. Quiz respondido com attach_id → document bloqueado (vision obrigatório)
  A4. Quiz respondido com attach_id → web-search bloqueado (só vision permitido)
  A5. Após vision → gate liberado (document permitido)
  A6. Documento salvo → gate pendente (só asset permitido)

  ── COPYWRITING URL FLOW ──
  U1. Após lookup, document bloqueado (quiz obrigatório)
  U2. Quiz respondido com URL → vision bloqueada (web-search obrigatório primeiro)
  U3. Após web-search → document bloqueado (image_selection quiz obrigatório)
  U4. Após image_selection → document bloqueado (vision obrigatório)
  U5. Após vision → gate liberado
  U6. Documento salvo → gate pendente (só asset permitido)

  ── CATALOG JSON GATE (novo fluxo: quiz→produto→inspiração→document→asset) ──
  C1.  Após lookup, document bloqueado (quiz obrigatório)
  C2.  Após lookup, vision bloqueado (quiz obrigatório)
  C3.  Quiz (5 respostas) respondido → s-product-analyze: document bloqueado (vision/web_search 1º)
  C3b. s-product-analyze(attach): vision não é bloqueado pelo gate
  C3c. s-product-analyze(url): quiz Q1=URL + vision injetado → gate NÃO avança (document ainda bloqueado)
  C4.  Após product-analyze → s-inspiration-analyze: asset bloqueado (vision/web_search 2º)
  C4b. s-inspiration-analyze: vision passa o gate
  C5.  Após inspiration-analyze → s-document: asset bloqueado (document obrigatório)
  C6.  Documento salvo → s-asset: quiz bloqueado (só asset permitido)
  C7.  Asset executado → gate reset (ciclo encerrado, próxima chamada livre)

  ── ALLOW_MESSAGE_RESPONSE ──
  M1. SkillCatalog ativa + quiz pendente → _gate_blocks_message_response() = True
  M2. SkillCatalog + ciclo completo → _gate_blocks_message_response() = False

  ── EDGE CASES — completion fns e whitelist ──
  E1. Quiz sem attachment=true no input → gate fica em s-quiz, vision bloqueada
  E2. Quiz com success=false no output → gate fica em s-quiz, vision bloqueada
  E3. Quiz com 5 perguntas agrupadas em 1 resposta → gate NÃO avança (min_answers=5 não satisfeito)
  E4. Vision com success=false em s-product-analyze → gate não avança, document bloqueado
  E5. Asset com success=false → ciclo não encerra, _gate_blocks_message_response()=True
  E6. Tool em exempt_tools (chain_of_thought) → liberada mesmo com gate ativo em s-quiz
  E7. Tool fora de allowed_tools em s-product-analyze (document) → bloqueada (só vision/web_search)
  E8. Asset com document_id de outro chat → gate libera (erro é da tool, sem correction_required)

Uso:
    cd App/mvp/services/backend
    python3 Scripts/Tests/GateValidation/test_gate_validation.py
    python3 Scripts/Tests/GateValidation/test_gate_validation.py --env-file .env.development
"""

import sys, os, uuid, json, argparse, time
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument(
    "--env-file", default=str(BACKEND_DIR.parent.parent.parent / ".env.development")
)
_args, _ = _parser.parse_known_args()
os.environ["ENV_FILE"] = _args.env_file

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

SEP = "=" * 70
SEP2 = "-" * 70

AGENT_ID = "orchestrator-global"
AGENT_NAME = "ORCHESTRATOR_GLOBAL"

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

results: list[dict] = []

# Strings esperadas nas mensagens de gate (para verificar que é o gate bloqueando, não outro erro)
E_GATE_QUIZ_FIRST = [
    "quiz"
]  # Gate de copywriting: quiz obrigatório antes de outras tools
E_GATE_VISION_ATTACH = ["vision"]  # Attachment flow: vision obrigatório após quiz
E_GATE_WEB_SEARCH = ["web-search", "fetch"]  # URL flow: web-search obrigatório
E_GATE_IMAGE_SEL = ["image_selection"]  # URL flow: quiz image_selection obrigatório
E_GATE_VISION_URL = ["vision"]  # URL flow: vision obrigatório após image_selection
E_GATE_ASSET = ["asset"]  # Pending doc gate: asset obrigatório
E_GATE_CAT_QUIZ = ["quiz"]  # Catalog JSON gate: quiz obrigatório
E_GATE_CAT_ANALYZE = [
    "vision",
    "web_search",
]  # Catalog: vision ou web_search obrigatório
E_GATE_CAT_DOC = ["document"]  # Catalog JSON gate: document obrigatório
E_GATE_CAT_ASSET = ["asset"]  # Catalog JSON gate: asset obrigatório

# Document mínimo válido para copywriting (só para passar validação de schema)
_COPY_DOC = {
    "is_paid_ad": False,
    "should_keep_brand_identity": False,
    "aspect_ratio": "9:16",
    "channels": ["instagram"],
    "framework": "PAS",
    "archetype": "O Herói",
    "moodboard": "Visual limpo, moderno.",
    "hypothesy": "Hipótese de campanha.",
    "problem": "Problema claro e urgente.",
    "agitate": "Agitação do problema com impacto emocional.",
    "solution": "MD70 resolve em minutos.",
    "caption": "Caption do post.",
    "assets": [
        {
            "asset_type": "img",
            "prompt": {
                "description": "Empresário confiante em escritório moderno.",
                "has_realistic_people": False,
                "composition": {"angle": "CloseUpShot", "grid": "Centralized"},
                "environment": {"place": "Estúdio clean", "objects": ["Produto"]},
                "colors": {
                    "background": {"hex": ["#FFFFFF"], "bg_type": "color"},
                    "subject": {"hex": ["#0055FF"]},
                    "accent": {"hex": ["#000000"]},
                    "saturation_contrast": "High contrast",
                    "harmony": "Complementary",
                },
                "illumination": "3-point studio",
                "emotion_style": "Professional, clean",
            },
        }
    ],
}

# Documento mínimo válido para catalog (novo schema: mesmo formato que copywriting)
_CATALOG_DOC = {
    "product_category": "retail",
    "aspect_ratio": "1:1",
    "assets": [
        {
            "asset_type": "img",
            "prompt": {
                "description": "Garrafa azul premium centralizada em fundo branco",
                "has_realistic_people": False,
                "composition": {"angle": "CloseUpShot", "grid": "Centralized"},
                "environment": {
                    "place": "Estúdio clean fundo branco",
                    "objects": ["Garrafa centralizada"],
                },
                "colors": {
                    "background": {"hex": ["#FFFFFF"], "bg_type": "color"},
                    "subject": {"hex": ["#0055FF"]},
                    "accent": {"hex": ["#000000"]},
                    "saturation_contrast": "Natural, fiel ao produto",
                    "harmony": "Neutral",
                },
                "illumination": "Iluminação de estúdio uniforme",
                "emotion_style": "Professional, clean",
            },
        }
    ],
}

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS — DB, injeção de mensagens, step assertion
# ══════════════════════════════════════════════════════════════════════════════


def get_session():
    db_path = BACKEND_DIR / "Data" / "Database" / "MD70.db"
    engine = create_engine(f"sqlite:///{db_path}")

    @event.listens_for(engine, "connect")
    def _fk_off(conn, _):
        conn.execute("PRAGMA foreign_keys = OFF")

    return sessionmaker(bind=engine)()


def get_user_id(session) -> str:
    row = session.execute(text("SELECT user_id FROM users LIMIT 1")).fetchone()
    if not row:
        raise RuntimeError("Nenhum usuário no DB")
    return row[0]


def setup_chat(session, user_id: str, chat_id: str):
    from App.Core.Crunch.TablesSQL.Models import IsolatedChat, Chat

    if not session.query(Chat).filter(Chat.chat_id == chat_id).first():
        session.add(
            Chat(
                chat_id=chat_id,
                user_id=user_id,
                chat_name="[GATE-TEST]",
                status="active",
            )
        )
        session.flush()
    ic = (
        session.query(IsolatedChat)
        .filter(IsolatedChat.chat_id == chat_id, IsolatedChat.agent_id == AGENT_ID)
        .first()
    )
    if not ic:
        ic = IsolatedChat(chat_id=chat_id, agent_id=AGENT_ID)
        session.add(ic)
        session.commit()
        session.refresh(ic)
    return ic


def make_core(session, user_id: str, chat_id: str):
    from App.Features.Tools.Core import Core

    class LiveDB:
        def get_session(self):
            return session

    core = Core(db_manager=LiveDB())
    core.current_chat_id = chat_id
    core.current_user_id = user_id
    return core


def inject(
    session,
    chat_id: str,
    tool_called: str,
    tc_type: str,
    content: str,
    tool_call_id: str = None,
) -> str:
    from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager

    time.sleep(0.05)
    mid = str(uuid.uuid4())
    tid = tool_call_id or mid
    DatabaseManager.save_isolated_message(
        session=session,
        isolated_chat_id=chat_id,
        agent_id=AGENT_ID,
        agent=AGENT_NAME,
        role="assistant" if tc_type == "input" else "user",
        content=content,
        message_type="tool_call",
        isolated_message_id=mid,
        tool_call_id=tid,
        tool_called=tool_called,
        tool_call_type=tc_type,
    )
    return tid


# ── Skill lookup injectors ─────────────────────────────────────────────────────


def inject_lookup(session, chat_id: str, skill_file: str):
    lid = str(uuid.uuid4())
    inject(
        session,
        chat_id,
        "lookup",
        "input",
        f'Tool: lookup\nArgs: {{"file": "{skill_file}"}}',
        lid,
    )
    inject(
        session,
        chat_id,
        "lookup",
        "output",
        json.dumps(
            {
                "success": True,
                "tool": "lookup",
                "file": skill_file,
                "content": "Skill loaded.",
            }
        ),
        lid,
    )
    session.commit()


# ── Copywriting quiz injectors ─────────────────────────────────────────────────


def inject_variation_quiz_attachment(session, chat_id: str) -> str:
    """Quiz de variação com resposta contendo attach_id (fluxo attachment)."""
    attach_id = f"attach_{uuid.uuid4().hex[:12]}"
    qid = str(uuid.uuid4())
    quiz_args = {
        "quiz": [
            {
                "question": "Qual a imagem de referencia? (cole URL ou faca upload do attachment)",
                "type": "url",
                "options": [],
                "attachment": True,
            },
            {
                "question": "Qual o formato (aspect ratio) das variacoes?",
                "type": "multiple_choice",
                "options": ["1:1", "4:5", "9:16", "16:9"],
            },
            {
                "question": "O que voce quer validar neste batch de variacoes?",
                "type": "multiple_choice",
                "options": ["Estilos", "Ambientes", "Emocoes"],
            },
            {
                "question": "Quantas variacoes?",
                "type": "multiple_choice",
                "options": ["2 (A/B)", "3 (A/B tres)", "5 (A/B intermediario)"],
            },
            {"question": "Descreva brevemente o estilo.", "type": "url"},
        ]
    }
    inject(
        session,
        chat_id,
        "quiz",
        "input",
        f"Tool: quiz\nArgs: {json.dumps(quiz_args, ensure_ascii=False)}",
        qid,
    )
    inject(
        session,
        chat_id,
        "quiz",
        "output",
        json.dumps(
            {
                "success": True,
                "final_answers": [
                    {"question": "Qual a imagem?", "answer": attach_id},
                    {"question": "Qual o formato?", "answer": "9:16"},
                    {"question": "O que validar?", "answer": "Estilos"},
                    {"question": "Quantas?", "answer": "3 (A/B tres variacoes)"},
                    {"question": "Estilo?", "answer": "."},
                ],
            }
        ),
        qid,
    )
    session.commit()
    return attach_id


def inject_variation_quiz_url(session, chat_id: str) -> str:
    """Quiz de variação com resposta contendo URL (fluxo URL)."""
    product_url = "https://example.com/produto"
    qid = str(uuid.uuid4())
    quiz_args = {
        "quiz": [
            {
                "question": "Qual a imagem de referencia? (cole URL ou faca upload do attachment)",
                "type": "url",
                "options": [],
                "attachment": True,
            },
            {
                "question": "Qual o formato (aspect ratio) das variacoes?",
                "type": "multiple_choice",
                "options": ["1:1", "4:5", "9:16", "16:9"],
            },
            {
                "question": "O que voce quer validar neste batch de variacoes?",
                "type": "multiple_choice",
                "options": ["Estilos", "Ambientes", "Emocoes"],
            },
            {
                "question": "Quantas variacoes?",
                "type": "multiple_choice",
                "options": ["2 (A/B)", "3 (A/B tres)", "5 (A/B intermediario)"],
            },
            {"question": "Descreva brevemente o estilo.", "type": "url"},
        ]
    }
    inject(
        session,
        chat_id,
        "quiz",
        "input",
        f"Tool: quiz\nArgs: {json.dumps(quiz_args, ensure_ascii=False)}",
        qid,
    )
    inject(
        session,
        chat_id,
        "quiz",
        "output",
        json.dumps(
            {
                "success": True,
                "final_answers": [
                    {
                        "question": "Qual a imagem?",
                        "answer": product_url,
                    },  # URL, não attach_id
                    {"question": "Qual o formato?", "answer": "16:9"},
                    {"question": "O que validar?", "answer": "Estilos"},
                    {"question": "Quantas?", "answer": "2 (A/B)"},
                    {"question": "Estilo?", "answer": "."},
                ],
            }
        ),
        qid,
    )
    session.commit()
    return product_url


def inject_web_search_visual(session, chat_id: str, url: str):
    """Web-search com fetch + visual-analysis (URL flow)."""
    wid = str(uuid.uuid4())
    inject(
        session,
        chat_id,
        "web-search",
        "input",
        f'Tool: web-search\nArgs: {json.dumps({"fetch": url, "visual-analysis": url})}',
        wid,
    )
    inject(
        session,
        chat_id,
        "web-search",
        "output",
        json.dumps(
            {
                "success": True,
                "type": "visual-analysis",
                "content": "Produto: garrafa azul premium. Imagens: https://example.com/p1.jpg",
            }
        ),
        wid,
    )
    session.commit()


def inject_image_selection_quiz(session, chat_id: str) -> str:
    """Quiz de image_selection após web-search (URL flow)."""
    selected_url = "https://example.com/p1.jpg"
    qid = str(uuid.uuid4())
    quiz_args = {
        "quiz": [
            {
                "question": "Extrai algumas imagens do seu produto, qual imagem voce prefere usar como referencia?",
                "type": "image_selection",
                "options": [selected_url, "https://example.com/p2.jpg"],
            }
        ]
    }
    inject(
        session,
        chat_id,
        "quiz",
        "input",
        f"Tool: quiz\nArgs: {json.dumps(quiz_args, ensure_ascii=False)}",
        qid,
    )
    inject(
        session,
        chat_id,
        "quiz",
        "output",
        json.dumps(
            {
                "success": True,
                "final_answers": [{"question": "Qual imagem?", "answer": selected_url}],
            }
        ),
        qid,
    )
    session.commit()
    return selected_url


def inject_vision(session, chat_id: str, image_ref: str):
    """Vision executado com sucesso."""
    vid = str(uuid.uuid4())
    inject(
        session,
        chat_id,
        "vision",
        "input",
        f'Tool: vision\nArgs: {json.dumps({"image_input": image_ref})}',
        vid,
    )
    inject(
        session,
        chat_id,
        "vision",
        "output",
        json.dumps(
            {"success": True, "analysis": "Produto identificado: garrafa azul premium."}
        ),
        vid,
    )
    session.commit()


# ── Catalog quiz injector ──────────────────────────────────────────────────────


def inject_catalog_quiz_attachment(session, chat_id: str) -> str:
    """Quiz de catálogo com 5 perguntas e attachment (novo fluxo)."""
    attach_id = f"attach_{uuid.uuid4().hex[:12]}"
    insp_id = f"attach_{uuid.uuid4().hex[:12]}"  # inspiração também como attachment
    qid = str(uuid.uuid4())
    quiz_args = {
        "quiz": [
            {
                "question": "Faca o upload das imagens do produto",
                "type": "url",
                "options": [],
                "attachment": True,
            },
            {
                "question": "Imagens de inspiração (upload ou URL)",
                "type": "url",
                "options": [],
                "multiple_attach": True,
            },
            {
                "question": "Qual a categoria do produto?",
                "type": "multiple_choice",
                "options": ["Roupas & Moda", "Cosmeticos & Skincare", "Varejo Geral"],
            },
            {
                "question": "Qual o estilo do catalogo?",
                "type": "multiple_choice",
                "options": ["Editorial", "Clean Studio", "Lifestyle", "E-commerce"],
            },
            {
                "question": "Breve especificacao do copywriting",
                "type": "text",
                "options": [],
            },
        ]
    }
    inject(
        session,
        chat_id,
        "quiz",
        "input",
        f"Tool: quiz\nArgs: {json.dumps(quiz_args, ensure_ascii=False)}",
        qid,
    )
    inject(
        session,
        chat_id,
        "quiz",
        "output",
        json.dumps(
            {
                "success": True,
                "final_answers": [
                    {"question": "Upload do produto?", "answer": attach_id},
                    {"question": "Inspiracao?", "answer": insp_id},
                    {"question": "Categoria?", "answer": "Varejo Geral"},
                    {"question": "Estilo?", "answer": "Clean Studio"},
                    {
                        "question": "Especificacao?",
                        "answer": "Foco em fundo branco clean studio",
                    },
                ],
            }
        ),
        qid,
    )
    session.commit()
    return attach_id


def inject_web_search_catalog(
    session, chat_id: str, query: str = "https://example.com/produto"
):
    """Web-search com visual_analysis=true (alternativa ao vision em s-product-analyze ou s-inspiration-analyze)."""
    wid = str(uuid.uuid4())
    inject(
        session,
        chat_id,
        "web_search",
        "input",
        f'Tool: web_search\nArgs: {json.dumps({"query": query, "visual_analysis": True})}',
        wid,
    )
    inject(
        session,
        chat_id,
        "web_search",
        "output",
        json.dumps(
            {
                "success": True,
                "type": "visual_analysis",
                "content": "Produto identificado: garrafa azul premium 500ml.",
            }
        ),
        wid,
    )
    session.commit()


def inject_asset_called(session, chat_id: str):
    """Simula asset() executado com sucesso (para encerrar ciclo)."""
    aid = str(uuid.uuid4())
    inject(
        session,
        chat_id,
        "asset",
        "input",
        f'Tool: asset\nArgs: {json.dumps({"document_id": str(uuid.uuid4())})}',
        aid,
    )
    inject(
        session,
        chat_id,
        "asset",
        "output",
        json.dumps({"success": True, "generated_assets": []}),
        aid,
    )
    session.commit()


def inject_catalog_quiz_url(session, chat_id: str) -> tuple:
    """Quiz de catálogo com 5 perguntas e Q1=URL (produto) e Q2=URL (inspiração)."""
    product_url = "https://example.com/produto"
    insp_url = "https://example.com/inspiracao"
    qid = str(uuid.uuid4())
    quiz_args = {
        "quiz": [
            {
                "question": "Cole a URL ou faca upload das imagens do produto",
                "type": "url",
                "options": [],
                "attachment": True,
            },
            {
                "question": "Imagens de inspiração (upload ou URL)",
                "type": "url",
                "options": [],
                "multiple_attach": True,
            },
            {
                "question": "Qual a categoria do produto?",
                "type": "multiple_choice",
                "options": ["Roupas & Moda", "Cosmeticos & Skincare", "Varejo Geral"],
            },
            {
                "question": "Qual o estilo do catalogo?",
                "type": "multiple_choice",
                "options": ["Editorial", "Clean Studio", "Lifestyle", "E-commerce"],
            },
            {
                "question": "Breve especificacao do copywriting",
                "type": "text",
                "options": [],
            },
        ]
    }
    inject(
        session,
        chat_id,
        "quiz",
        "input",
        f"Tool: quiz\nArgs: {json.dumps(quiz_args, ensure_ascii=False)}",
        qid,
    )
    inject(
        session,
        chat_id,
        "quiz",
        "output",
        json.dumps(
            {
                "success": True,
                "final_answers": [
                    {
                        "question": "Upload do produto?",
                        "answer": product_url,
                    },  # URL — não attach
                    {"question": "Inspiracao?", "answer": insp_url},  # URL
                    {"question": "Categoria?", "answer": "Varejo Geral"},
                    {"question": "Estilo?", "answer": "Clean Studio"},
                    {
                        "question": "Especificacao?",
                        "answer": "Foco em fundo branco clean studio",
                    },
                ],
            }
        ),
        qid,
    )
    session.commit()
    return product_url, insp_url


def inject_document_output(
    session, chat_id: str, user_id: str, doc_type: str = "catalog"
) -> str:
    """Injeta document em IsolatedMessage E na tabela documents (ambos necessários para document_saved)."""
    document_id = str(uuid.uuid4())
    # Tabela documents: document_saved completion fn faz SELECT nela
    session.execute(
        text(
            "INSERT INTO documents (document_id, chat_id, user_id, title, content, extension, tool_type, created_at, updated_at) "
            "VALUES (:did, :cid, :uid, :title, :content, :ext, :tt, datetime('now'), datetime('now'))"
        ),
        {
            "did": document_id,
            "cid": chat_id,
            "uid": user_id,
            "title": "Gate Test",
            "content": "{}",
            "ext": "json",
            "tt": doc_type,
        },
    )
    # IsolatedMessage: para aparecer no histórico de tool calls
    mid = str(uuid.uuid4())
    inject(
        session,
        chat_id,
        "document",
        "input",
        f'Tool: document\nArgs: {json.dumps({"type": doc_type, "title": "Gate Test"})}',
        mid,
    )
    inject(
        session,
        chat_id,
        "document",
        "output",
        json.dumps({"success": True, "id": document_id, "document_type": doc_type}),
        mid,
    )
    session.commit()
    return document_id


# ── Edge-case injectors ────────────────────────────────────────────────────────


def inject_catalog_quiz_no_attachment(session, chat_id: str):
    """Quiz de catálogo SEM 'attachment: true' no input — gate não deve avançar."""
    qid = str(uuid.uuid4())
    quiz_args = {
        "quiz": [
            {"question": "Qual produto catalogar?", "type": "text", "options": []},
            {
                "question": "Qual a categoria?",
                "type": "multiple_choice",
                "options": ["Roupas", "Cosméticos", "Varejo"],
            },
        ]
    }
    inject(
        session,
        chat_id,
        "quiz",
        "input",
        f"Tool: quiz\nArgs: {json.dumps(quiz_args, ensure_ascii=False)}",
        qid,
    )
    inject(
        session,
        chat_id,
        "quiz",
        "output",
        json.dumps(
            {
                "success": True,
                "final_answers": [
                    {"question": "Produto?", "answer": "Garrafa azul"},
                    {"question": "Categoria?", "answer": "Varejo"},
                ],
            }
        ),
        qid,
    )
    session.commit()


def inject_catalog_quiz_failed_output(session, chat_id: str) -> str:
    """Quiz com attachment=true no input mas output com success=false — gate não avança."""
    attach_id = f"attach_{uuid.uuid4().hex[:12]}"
    qid = str(uuid.uuid4())
    quiz_args = {
        "quiz": [
            {
                "question": "Upload do produto",
                "type": "url",
                "options": [],
                "attachment": True,
            }
        ]
    }
    inject(
        session,
        chat_id,
        "quiz",
        "input",
        f"Tool: quiz\nArgs: {json.dumps(quiz_args, ensure_ascii=False)}",
        qid,
    )
    inject(
        session,
        chat_id,
        "quiz",
        "output",
        json.dumps(
            {"success": False, "error": "Timeout aguardando resposta do usuário"}
        ),
        qid,
    )
    session.commit()
    return attach_id


def inject_catalog_quiz_options_bundled(session, chat_id: str) -> str:
    """Quiz com attachment=true mas todas as 5 respostas agrupadas em 1 — gate NÃO avança (min_answers=5)."""
    attach_id = f"attach_{uuid.uuid4().hex[:12]}"
    qid = str(uuid.uuid4())
    quiz_args = {
        "quiz": [
            {
                "question": "Upload produto + inspiracao + categoria + estilo + specs",
                "type": "url",
                "options": [],
                "attachment": True,
            },
        ]
    }
    inject(
        session,
        chat_id,
        "quiz",
        "input",
        f"Tool: quiz\nArgs: {json.dumps(quiz_args, ensure_ascii=False)}",
        qid,
    )
    inject(
        session,
        chat_id,
        "quiz",
        "output",
        json.dumps(
            {
                "success": True,
                "final_answers": [
                    # Apenas 1 resposta para 5 perguntas → min_answers=5 não satisfeito
                    {
                        "question": "Tudo junto?",
                        "answer": f"{attach_id}, Varejo, CleanStudio, 3cenas, fundo branco",
                    },
                ],
            }
        ),
        qid,
    )
    session.commit()
    return attach_id


def inject_vision_failed(session, chat_id: str):
    """Vision com success=false — gate não avança em s-vision."""
    vid = str(uuid.uuid4())
    inject(
        session,
        chat_id,
        "vision",
        "input",
        f'Tool: vision\nArgs: {json.dumps({"image_input": ["fake-attach"]})}',
        vid,
    )
    inject(
        session,
        chat_id,
        "vision",
        "output",
        json.dumps({"success": False, "error": "Imagem não encontrada ou inacessível"}),
        vid,
    )
    session.commit()


def inject_asset_failed(session, chat_id: str):
    """Asset com success=false — ciclo não encerra."""
    aid = str(uuid.uuid4())
    inject(
        session,
        chat_id,
        "asset",
        "input",
        f'Tool: asset\nArgs: {json.dumps({"document_id": str(uuid.uuid4())})}',
        aid,
    )
    inject(
        session,
        chat_id,
        "asset",
        "output",
        json.dumps(
            {"success": False, "error": "Documento não encontrado para gerar assets"}
        ),
        aid,
    )
    session.commit()


def inject_catalog_document_row(session, chat_id: str, user_id: str) -> str:
    """Insere documento catalog diretamente na tabela documents (para simular document_saved sem validação completa)."""
    document_id = str(uuid.uuid4())
    session.execute(
        text(
            "INSERT INTO documents (document_id, chat_id, user_id, title, content, extension, tool_type, created_at, updated_at) "
            "VALUES (:did, :cid, :uid, :title, :content, :ext, :tt, datetime('now'), datetime('now'))"
        ),
        {
            "did": document_id,
            "cid": chat_id,
            "uid": user_id,
            "title": "Catálogo Gate Test",
            "content": "{}",
            "ext": "json",
            "tt": "catalog",
        },
    )
    session.commit()
    return document_id


# ── Step assertion ─────────────────────────────────────────────────────────────


def step(
    label: str, expect_success: bool, result_str: str, expect_in_error: list = None
):
    try:
        result = json.loads(result_str) if isinstance(result_str, str) else result_str
    except Exception:
        result = {"success": False, "error": str(result_str)}

    ok = result.get("success", False)
    passed = ok == expect_success

    error_text = (
        result.get("error", "")
        + " "
        + result.get("message", "")
        + " "
        + str(result.get("correction_required", ""))
    ).lower()

    if expect_in_error:
        strings_ok = all(kw.lower() in error_text for kw in expect_in_error)
        passed = passed and strings_ok
    else:
        strings_ok = True

    icon = "[OK]" if passed else "[FAIL]"
    exp = "sucesso" if expect_success else "bloqueado"
    got = "sucesso" if ok else "bloqueado"

    print(f"\n{SEP2}")
    print(f"{icon}  {label}")
    print(f"     esperado={exp}  obtido={got}  strings_ok={strings_ok}")
    if not passed:
        print(f"     error: {result.get('error', '')[:200]}")
        if expect_in_error:
            for kw in expect_in_error:
                mark = "✓" if kw.lower() in error_text else "✗"
                print(f"     {mark} '{kw}'")

    results.append({"label": label, "passed": passed, "result": result})

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = label[:45].replace(" ", "_").replace("→", "").replace("/", "")
    st = "pass" if passed else "fail"
    (OUTPUT_DIR / f"{slug}_{st}_{ts}.json").write_text(
        json.dumps(
            {"label": label, "expect_success": expect_success, "result": result},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return passed


def gate_step(
    label: str,
    core,
    tool_name: str,
    args: dict,
    chat_id: str,
    user_id: str,
    expect_blocked: bool,
    expect_in_error: list = None,
):
    """Chama execute_tool e valida bloqueio/liberação do gate."""
    result_str = core.execute_tool(
        tool_name=tool_name,
        arguments=json.dumps(args),
        agent_id=AGENT_ID,
        chat_id=chat_id,
        user_id=user_id,
    )
    return step(
        label,
        expect_success=not expect_blocked,
        result_str=result_str,
        expect_in_error=expect_in_error,
    )


def check_bool(label: str, value: bool, expected: bool):
    passed = value == expected
    icon = "[OK]" if passed else "[FAIL]"
    print(f"\n{SEP2}")
    print(f"{icon}  {label}")
    print(f"     esperado={expected}  obtido={value}")
    results.append(
        {
            "label": label,
            "passed": passed,
            "result": {"value": value, "expected": expected},
        }
    )
    return passed


# ══════════════════════════════════════════════════════════════════════════════
# TEST FLOWS
# ══════════════════════════════════════════════════════════════════════════════


def run_copywriting_attachment_flow(session, user_id: str):
    """Testa gate sequencial do copywriting no fluxo attachment."""
    print(f"\n{SEP}\n  COPYWRITING — FLUXO ATTACHMENT\n{SEP}")

    chat_id = f"gate-attach-{uuid.uuid4().hex[:8]}"
    setup_chat(session, user_id, chat_id)
    core = make_core(session, user_id, chat_id)

    # A1: Após lookup, web-search deve ser bloqueado (quiz obrigatório primeiro)
    inject_lookup(session, chat_id, "SkillCopywriting.md")
    gate_step(
        "A1. lookup+sem quiz → web-search bloqueado",
        core,
        "web-search",
        {"fetch": "https://example.com"},
        chat_id,
        user_id,
        expect_blocked=True,
        expect_in_error=E_GATE_QUIZ_FIRST,
    )

    # A2: Após lookup, document também deve ser bloqueado
    gate_step(
        "A2. lookup+sem quiz → document bloqueado",
        core,
        "document",
        {"type": "copywriting", "title": "T", "data": _COPY_DOC},
        chat_id,
        user_id,
        expect_blocked=True,
        expect_in_error=E_GATE_QUIZ_FIRST,
    )

    # A3: Quiz respondido com attach_id — document bloqueado (vision obrigatório)
    attach_id = inject_variation_quiz_attachment(session, chat_id)
    gate_step(
        "A3. quiz(attach)+sem vision → document bloqueado",
        core,
        "document",
        {"type": "copywriting", "title": "T", "data": _COPY_DOC},
        chat_id,
        user_id,
        expect_blocked=True,
        expect_in_error=E_GATE_VISION_ATTACH,
    )

    # A4: Quiz attachment — web-search também bloqueado (só vision permitido)
    gate_step(
        "A4. quiz(attach)+sem vision → web-search bloqueado",
        core,
        "web-search",
        {"fetch": "https://example.com"},
        chat_id,
        user_id,
        expect_blocked=True,
        expect_in_error=E_GATE_VISION_ATTACH,
    )

    # A5: Após vision → gate liberado (document não é mais bloqueado pelo gate de sequência)
    # O retorno pode ser erro de validação do document, mas NÃO deve ser erro de gate sequencial
    inject_vision(session, chat_id, attach_id)
    result_str = core.execute_tool(
        tool_name="document",
        arguments=json.dumps(
            {"type": "copywriting", "title": "Copy Attach Test", "data": _COPY_DOC}
        ),
        agent_id=AGENT_ID,
        chat_id=chat_id,
        user_id=user_id,
    )
    result = json.loads(result_str)
    # Gate sequencial não deve bloquear — o erro (se houver) deve ser de validação do documento
    _corr = str(result.get("correction_required", "")).lower()
    gate_sequence_blocked = "correction_required" in result and (
        "vision" in _corr or "web-search" in _corr
    )
    check_bool(
        "A5. após vision → gate sequencial liberado para document",
        not gate_sequence_blocked,
        True,
    )

    # A6: Documento salvo → gate pendente (só asset permitido)
    # Injetar documento salvo no DB
    doc_id = None
    if result.get("success") and result.get("id"):
        doc_id = result["id"]
        # Gate pendente: quiz deve ser bloqueado agora
        gate_step(
            "A6. documento salvo → quiz bloqueado (só asset)",
            core,
            "quiz",
            {"quiz": [{"question": "Nova pergunta", "options": ["A"], "type": "mc"}]},
            chat_id,
            user_id,
            expect_blocked=True,
            expect_in_error=E_GATE_ASSET,
        )
    else:
        print(
            f"     [SKIP] A6 — documento não salvo (erro de validação): {result.get('error', '')[:100]}"
        )


def run_copywriting_url_flow(session, user_id: str):
    """Testa gate sequencial do copywriting no fluxo URL."""
    print(f"\n{SEP}\n  COPYWRITING — FLUXO URL\n{SEP}")

    chat_id = f"gate-url-{uuid.uuid4().hex[:8]}"
    setup_chat(session, user_id, chat_id)
    core = make_core(session, user_id, chat_id)

    # U1: Após lookup, document bloqueado (quiz obrigatório)
    inject_lookup(session, chat_id, "SkillCopywriting.md")
    gate_step(
        "U1. lookup+sem quiz → document bloqueado",
        core,
        "document",
        {"type": "copywriting", "title": "T", "data": _COPY_DOC},
        chat_id,
        user_id,
        expect_blocked=True,
        expect_in_error=E_GATE_QUIZ_FIRST,
    )

    # U2: Quiz respondido com URL — vision bloqueada (web-search obrigatório primeiro)
    product_url = inject_variation_quiz_url(session, chat_id)
    gate_step(
        "U2. quiz(url)+sem web-search → vision bloqueada",
        core,
        "vision",
        {"image_input": product_url},
        chat_id,
        user_id,
        expect_blocked=True,
        expect_in_error=E_GATE_WEB_SEARCH,
    )

    # U3: Após web-search — document bloqueado (image_selection quiz obrigatório)
    inject_web_search_visual(session, chat_id, product_url)
    gate_step(
        "U3. web-search feito+sem image_selection → document bloqueado",
        core,
        "document",
        {"type": "copywriting", "title": "T", "data": _COPY_DOC},
        chat_id,
        user_id,
        expect_blocked=True,
        expect_in_error=E_GATE_IMAGE_SEL,
    )

    # U4: Após image_selection — document bloqueado (vision obrigatório)
    selected_img = inject_image_selection_quiz(session, chat_id)
    gate_step(
        "U4. image_selection feito+sem vision → document bloqueado",
        core,
        "document",
        {"type": "copywriting", "title": "T", "data": _COPY_DOC},
        chat_id,
        user_id,
        expect_blocked=True,
        expect_in_error=E_GATE_VISION_URL,
    )

    # U5: Após vision → gate liberado
    inject_vision(session, chat_id, selected_img)
    result_str = core.execute_tool(
        tool_name="document",
        arguments=json.dumps(
            {"type": "copywriting", "title": "Copy URL Test", "data": _COPY_DOC}
        ),
        agent_id=AGENT_ID,
        chat_id=chat_id,
        user_id=user_id,
    )
    result = json.loads(result_str)
    gate_sequence_blocked = "correction_required" in result and any(
        kw in str(result.get("correction_required", "")).lower()
        for kw in ["vision", "web-search", "image_selection"]
    )
    check_bool(
        "U5. após vision (url flow) → gate sequencial liberado para document",
        not gate_sequence_blocked,
        True,
    )

    # U6: Documento salvo → gate pendente
    doc_id = None
    if result.get("success") and result.get("id"):
        doc_id = result["id"]
        gate_step(
            "U6. documento salvo → vision bloqueado (só asset)",
            core,
            "vision",
            {"image_input": "https://example.com/img.jpg"},
            chat_id,
            user_id,
            expect_blocked=True,
            expect_in_error=E_GATE_ASSET,
        )
    else:
        print(
            f"     [SKIP] U6 — documento não salvo (erro de validação): {result.get('error', '')[:100]}"
        )


def run_catalog_json_gate(session, user_id: str):
    """Testa o gate JSON (engine) para SkillCatalog — novo fluxo 5 steps."""
    print(
        f"\n{SEP}\n  CATALOG — JSON GATE ENGINE (quiz→produto→inspiração→document→asset)\n{SEP}"
    )

    chat_id = f"gate-cat-{uuid.uuid4().hex[:8]}"
    setup_chat(session, user_id, chat_id)
    core = make_core(session, user_id, chat_id)

    # C1: Após lookup, document bloqueado (quiz obrigatório)
    inject_lookup(session, chat_id, "SkillCatalog.md")
    gate_step(
        "C1. lookup+sem quiz → document bloqueado",
        core,
        "document",
        {"type": "catalog", "title": "T", "data": _CATALOG_DOC},
        chat_id,
        user_id,
        expect_blocked=True,
        expect_in_error=E_GATE_CAT_QUIZ,
    )

    # C2: vision também bloqueado (quiz primeiro)
    gate_step(
        "C2. lookup+sem quiz → vision bloqueado",
        core,
        "vision",
        {"image_input": "https://example.com/img.jpg"},
        chat_id,
        user_id,
        expect_blocked=True,
        expect_in_error=E_GATE_CAT_QUIZ,
    )

    # C3: Quiz com 5 respostas → s-product-analyze ativo; document bloqueado (vision/web_search 1º)
    attach_id = inject_catalog_quiz_attachment(session, chat_id)
    gate_step(
        "C3. quiz(5 respostas)+sem product-analyze → document bloqueado",
        core,
        "document",
        {"type": "catalog", "title": "T", "data": _CATALOG_DOC},
        chat_id,
        user_id,
        expect_blocked=True,
        expect_in_error=["vision", "web_search"],
    )

    # C3b: vision passa o gate em s-product-analyze
    result_str = core.execute_tool(
        tool_name="vision",
        arguments=json.dumps({"image_input": attach_id}),
        agent_id=AGENT_ID,
        chat_id=chat_id,
        user_id=user_id,
    )
    result = json.loads(result_str)
    gate_blocked = (
        "correction_required" in result
        and "quiz" in str(result.get("error", "")).lower()
    )
    check_bool(
        "C3b. s-product-analyze: vision passa o gate JSON (erro eventual é da tool)",
        not gate_blocked,
        True,
    )

    # C3c: quiz Q1=URL → vision injetada (ferramenta errada para URL) → gate NÃO avança
    # document ainda bloqueado (gate permanece em s-product-analyze)
    chat_c3c = f"gate-cat-c3c-{uuid.uuid4().hex[:8]}"
    setup_chat(session, user_id, chat_c3c)
    core_c3c = make_core(session, user_id, chat_c3c)
    inject_lookup(session, chat_c3c, "SkillCatalog.md")
    inject_catalog_quiz_url(session, chat_c3c)  # Q1=URL, Q2=URL
    inject_vision(
        session, chat_c3c, "https://example.com/produto-img.jpg"
    )  # errado para URL path
    gate_step(
        "C3c. quiz(url)+vision(errado) → gate não avança, document bloqueado em s-product-analyze",
        core_c3c,
        "document",
        {"type": "catalog", "title": "T", "data": _CATALOG_DOC},
        chat_c3c,
        user_id,
        expect_blocked=True,
        expect_in_error=["vision", "web_search"],
    )

    # C4: Após product-analyze → s-inspiration-analyze: asset bloqueado (vision/web_search 2º)
    inject_vision(session, chat_id, attach_id)  # product analysis done
    gate_step(
        "C4. product-analyze feito+sem inspiration-analyze → asset bloqueado",
        core,
        "asset",
        {"document_id": str(uuid.uuid4())},
        chat_id,
        user_id,
        expect_blocked=True,
        expect_in_error=["vision", "web_search"],
    )

    # C4b: vision passa o gate em s-inspiration-analyze
    result_str = core.execute_tool(
        tool_name="vision",
        arguments=json.dumps({"image_input": "https://example.com/inspiration.jpg"}),
        agent_id=AGENT_ID,
        chat_id=chat_id,
        user_id=user_id,
    )
    result = json.loads(result_str)
    gate_blocked = (
        "correction_required" in result
        and "quiz" in str(result.get("error", "")).lower()
    )
    check_bool(
        "C4b. s-inspiration-analyze: vision passa o gate (pode falhar por outros motivos)",
        not gate_blocked,
        True,
    )

    # C5: Após inspiration-analyze → s-document: asset bloqueado (document obrigatório)
    inject_vision(
        session, chat_id, "https://example.com/inspiration.jpg"
    )  # inspiration done
    gate_step(
        "C5. inspiration-analyze feito+sem document → asset bloqueado",
        core,
        "asset",
        {"document_id": str(uuid.uuid4())},
        chat_id,
        user_id,
        expect_blocked=True,
        expect_in_error=E_GATE_CAT_DOC,
    )

    # C6: Salvar documento de catálogo com novo schema → quiz bloqueado (só asset permitido)
    doc_result_str = core.execute_tool(
        tool_name="document",
        arguments=json.dumps(
            {"type": "catalog", "title": "Catálogo Gate Test", "data": _CATALOG_DOC}
        ),
        agent_id=AGENT_ID,
        chat_id=chat_id,
        user_id=user_id,
    )
    doc_result = json.loads(doc_result_str)
    if doc_result.get("success") and doc_result.get("id"):
        cat_doc_id = doc_result["id"]
        gate_step(
            "C6. documento salvo → quiz bloqueado (só asset permitido)",
            core,
            "quiz",
            {"quiz": [{"question": "Nova pergunta?", "options": ["A"], "type": "mc"}]},
            chat_id,
            user_id,
            expect_blocked=True,
            expect_in_error=E_GATE_CAT_ASSET,
        )

        # C7: asset passa o gate (ciclo encerrado após execução)
        result_str = core.execute_tool(
            tool_name="asset",
            arguments=json.dumps({"document_id": cat_doc_id}),
            agent_id=AGENT_ID,
            chat_id=chat_id,
            user_id=user_id,
        )
        result = json.loads(result_str)
        gate_blocked = (
            "correction_required" in result
            and "quiz" in str(result.get("error", "")).lower()
        )
        check_bool(
            "C7. asset → passa o gate JSON (pode falhar por outros motivos)",
            not gate_blocked,
            True,
        )

        # Após asset executado → gate deve resetar
        inject_asset_called(session, chat_id)
        after_result_str = core.execute_tool(
            tool_name="document",
            arguments=json.dumps({"type": "catalog", "title": "T", "data": {}}),
            agent_id=AGENT_ID,
            chat_id=chat_id,
            user_id=user_id,
        )
        after_result = json.loads(after_result_str)
        gate_still_seq = (
            "correction_required" in after_result
            and "quiz" in str(after_result.get("correction_required", "")).lower()
            and "catálogo" in str(after_result.get("error", "")).lower()
        )
        check_bool(
            "C8. após ciclo completo → gate JSON resetado (próxima chamada livre)",
            not gate_still_seq,
            True,
        )
    else:
        print(
            f"     [SKIP] C6-C8 — documento catalog não salvo: {doc_result.get('error', '')[:200]}"
        )


def run_allow_message_response(session, user_id: str):
    """Testa _gate_blocks_message_response() para SkillCatalog."""
    print(f"\n{SEP}\n  ALLOW_MESSAGE_RESPONSE — JSON GATE\n{SEP}")

    chat_id = f"gate-msg-{uuid.uuid4().hex[:8]}"
    setup_chat(session, user_id, chat_id)
    core = make_core(session, user_id, chat_id)

    # M1: SkillCatalog ativa + quiz pendente → deve bloquear texto
    inject_lookup(session, chat_id, "SkillCatalog.md")
    check_bool(
        "M1. SkillCatalog ativa+sem quiz → _gate_blocks_message_response()=True",
        core._gate_blocks_message_response(),
        True,
    )

    # M2: Após ciclo completo (5 steps) → não bloqueia
    attach_id = inject_catalog_quiz_attachment(session, chat_id)
    inject_vision(session, chat_id, attach_id)  # s-product-analyze concluído
    inject_vision(session, chat_id, "insp-ref")  # s-inspiration-analyze concluído
    inject_document_output(
        session, chat_id, user_id
    )  # s-document concluído (documents table + IsolatedMessage)
    inject_asset_called(session, chat_id)  # s-asset concluído → ciclo encerrado
    check_bool(
        "M2. ciclo completo → _gate_blocks_message_response()=False",
        core._gate_blocks_message_response(),
        False,
    )


def run_gate_edge_cases(session, user_id: str):
    """
    Testa edge cases do gate engine:
    - completion fns com inputs inválidos (sem attachment, success=false, etc.)
    - exempt_tools sempre liberadas
    - tool fora do whitelist bloqueada no step errado
    - gate libera tool mesmo que a tool em si falhe por outros motivos
    """
    print(f"\n{SEP}\n  EDGE CASES — GATE ENGINE\n{SEP}")

    # ── E1: Quiz sem attachment=true no input → s-quiz NÃO avança ──────────────
    chat_e1 = f"gate-edge-{uuid.uuid4().hex[:8]}"
    setup_chat(session, user_id, chat_e1)
    core_e1 = make_core(session, user_id, chat_e1)
    inject_lookup(session, chat_e1, "SkillCatalog.md")
    inject_catalog_quiz_no_attachment(session, chat_e1)
    gate_step(
        "E1. quiz sem attachment=true → gate fica em s-quiz, vision bloqueada",
        core_e1,
        "vision",
        {"image_input": [str(uuid.uuid4())]},
        chat_e1,
        user_id,
        expect_blocked=True,
        expect_in_error=["quiz"],
    )

    # ── E2: Quiz output com success=false → s-quiz NÃO avança ──────────────────
    chat_e2 = f"gate-edge-{uuid.uuid4().hex[:8]}"
    setup_chat(session, user_id, chat_e2)
    core_e2 = make_core(session, user_id, chat_e2)
    inject_lookup(session, chat_e2, "SkillCatalog.md")
    inject_catalog_quiz_failed_output(session, chat_e2)
    gate_step(
        "E2. quiz com success=false no output → gate fica em s-quiz, vision bloqueada",
        core_e2,
        "vision",
        {"image_input": [str(uuid.uuid4())]},
        chat_e2,
        user_id,
        expect_blocked=True,
        expect_in_error=["quiz"],
    )

    # ── E3: Quiz com 5 perguntas agrupadas em 1 resposta → gate NÃO avança (min_answers=5) ──
    chat_e3 = f"gate-edge-{uuid.uuid4().hex[:8]}"
    setup_chat(session, user_id, chat_e3)
    core_e3 = make_core(session, user_id, chat_e3)
    inject_lookup(session, chat_e3, "SkillCatalog.md")
    inject_catalog_quiz_options_bundled(session, chat_e3)
    # quiz tem 1 final_answer para 5 perguntas obrigatórias → min_answers=5 não satisfeito → vision bloqueada
    gate_step(
        "E3. quiz com 5 perguntas em 1 resposta → gate NÃO avança (min_answers=5 não satisfeito)",
        core_e3,
        "vision",
        {"image_input": [str(uuid.uuid4())]},
        chat_e3,
        user_id,
        expect_blocked=True,
        expect_in_error=["quiz"],
    )

    # ── E4: Vision com success=false em s-product-analyze → gate NÃO avança ───
    chat_e4 = f"gate-edge-{uuid.uuid4().hex[:8]}"
    setup_chat(session, user_id, chat_e4)
    core_e4 = make_core(session, user_id, chat_e4)
    inject_lookup(session, chat_e4, "SkillCatalog.md")
    inject_catalog_quiz_attachment(session, chat_e4)
    inject_vision_failed(session, chat_e4)
    gate_step(
        "E4. vision com success=false → gate fica em s-product-analyze, document bloqueado",
        core_e4,
        "document",
        {"type": "catalog", "title": "T", "data": {}},
        chat_e4,
        user_id,
        expect_blocked=True,
        expect_in_error=["vision"],
    )

    # ── E5: Asset com success=false → ciclo NÃO encerra ───────────────────────
    chat_e5 = f"gate-edge-{uuid.uuid4().hex[:8]}"
    setup_chat(session, user_id, chat_e5)
    core_e5 = make_core(session, user_id, chat_e5)
    inject_lookup(session, chat_e5, "SkillCatalog.md")
    inject_catalog_quiz_attachment(session, chat_e5)  # s-quiz → s-product-analyze
    inject_vision(
        session, chat_e5, "fake-attach"
    )  # s-product-analyze → s-inspiration-analyze
    inject_vision(session, chat_e5, "insp-ref")  # s-inspiration-analyze → s-document
    inject_document_output(
        session, chat_e5, user_id
    )  # s-document → s-asset (documents table + IsolatedMessage)
    inject_asset_failed(session, chat_e5)  # asset com success=false → ciclo NÃO encerra
    # Ciclo NÃO encerrou → _gate_blocks_message_response() ainda True
    check_bool(
        "E5. asset com success=false → ciclo não encerra, gate ainda bloqueia texto",
        core_e5._gate_blocks_message_response(),
        True,
    )

    # ── E6: Tool em exempt_tools → liberada mesmo com gate ativo ──────────────
    chat_e6 = f"gate-edge-{uuid.uuid4().hex[:8]}"
    setup_chat(session, user_id, chat_e6)
    core_e6 = make_core(session, user_id, chat_e6)
    inject_lookup(session, chat_e6, "SkillCatalog.md")
    # Gate em s-quiz; chain_of_thought está em exempt_tools → não deve ser bloqueada
    result_str = core_e6.execute_tool(
        tool_name="chain_of_thought",
        arguments=json.dumps({"steps": ["Analisando produto para catálogo..."]}),
        agent_id=AGENT_ID,
        chat_id=chat_e6,
        user_id=user_id,
    )
    result = json.loads(result_str)
    gate_blocked = not result.get("success", False) and "correction_required" in result
    check_bool(
        "E6. exempt tool (chain_of_thought) → gate não bloqueia em s-quiz",
        not gate_blocked,
        True,
    )

    # ── E7: Tool fora de allowed_tools em s-product-analyze → bloqueada ─────
    chat_e7 = f"gate-edge-{uuid.uuid4().hex[:8]}"
    setup_chat(session, user_id, chat_e7)
    core_e7 = make_core(session, user_id, chat_e7)
    inject_lookup(session, chat_e7, "SkillCatalog.md")
    inject_catalog_quiz_attachment(session, chat_e7)
    # Gate em s-product-analyze; allowed_tools=["vision","web_search"]
    # "document" não está em allowed_tools nem em exempt_tools → deve ser bloqueado
    gate_step(
        "E7. document em s-product-analyze → bloqueado (não está em allowed_tools)",
        core_e7,
        "document",
        {"type": "catalog", "title": "T", "data": _CATALOG_DOC},
        chat_e7,
        user_id,
        expect_blocked=True,
        expect_in_error=["vision"],
    )

    # ── E8: Asset com document_id de OUTRO chat → gate libera, erro é da tool ──
    # Cenário: LLM reutiliza document_id de sessão anterior em vez do recém-criado.
    chat_e8_other = f"gate-edge-other-{uuid.uuid4().hex[:8]}"
    setup_chat(session, user_id, chat_e8_other)
    other_doc_id = inject_catalog_document_row(session, chat_e8_other, user_id)

    chat_e8 = f"gate-edge-{uuid.uuid4().hex[:8]}"
    setup_chat(session, user_id, chat_e8)
    core_e8 = make_core(session, user_id, chat_e8)
    inject_lookup(session, chat_e8, "SkillCatalog.md")
    inject_catalog_quiz_attachment(session, chat_e8)
    inject_vision(session, chat_e8, "fake-attach")
    inject_catalog_document_row(
        session, chat_e8, user_id
    )  # documento correto criado no chat atual
    # Gate em s-asset; LLM passa document_id de outro chat (não o recém-criado)
    result_str = core_e8.execute_tool(
        tool_name="asset",
        arguments=json.dumps({"document_id": other_doc_id}),
        agent_id=AGENT_ID,
        chat_id=chat_e8,
        user_id=user_id,
    )
    result = json.loads(result_str)
    # Gate NÃO deve bloquear (asset está em allowed_tools em s-asset); erro vem da tool
    gate_blocked_by_json = (
        "correction_required" in result
        and "catálogo" in str(result.get("error", "")).lower()
    )
    check_bool(
        "E8. asset com document_id de outro chat → gate não bloqueia (erro é da tool)",
        not gate_blocked_by_json,
        True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════


def run():
    session = get_session()
    user_id = get_user_id(session)

    print(f"\n{'#' * 70}")
    print("  GATE VALIDATION — SkillCopywriting + SkillCatalog")
    print(f"{'#' * 70}")

    run_copywriting_attachment_flow(session, user_id)
    run_copywriting_url_flow(session, user_id)
    run_catalog_json_gate(session, user_id)
    run_allow_message_response(session, user_id)
    run_gate_edge_cases(session, user_id)

    # ── Sumário ──────────────────────────────────────────────────────────────
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed

    print(f"\n{'#' * 70}")
    print(f"  RESULTADO FINAL: {passed}/{total} passou  ({failed} falhou)")
    print(f"{'#' * 70}\n")

    for r in results:
        icon = "[OK]" if r["passed"] else "[FAIL]"
        print(f"  {icon}  {r['label']}")

    if failed > 0:
        print(f"\n  {failed} teste(s) falharam.")
        sys.exit(1)
    else:
        print("\n  Todos os testes passaram.")


if __name__ == "__main__":
    run()
