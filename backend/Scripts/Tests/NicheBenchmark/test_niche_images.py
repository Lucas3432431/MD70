"""
Benchmark: geração de imagens para 5 nichos sem brand_communication.
Testa a qualidade criativa e consistência do pipeline end-to-end.

Uso:
    cd App/mvp/services/backend
    python -m Scripts.Tests.NicheBenchmark.test_niche_images
    python -m Scripts.Tests.NicheBenchmark.test_niche_images --env-file .env.wsl
"""

import sys, os, uuid, json, argparse, time
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--env-file", default=str(BACKEND_DIR / ".env.wsl"))
_args, _ = _parser.parse_known_args()
os.environ["ENV_FILE"] = _args.env_file

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

AGENT_ID = "orchestrator-global"
AGENT_NAME = "ORCHESTRATOR_GLOBAL"
CHAT_ID = f"bench-{str(uuid.uuid4())[:8]}"
SEP = "=" * 70
SEP2 = "-" * 70


# ── Infrastructure ────────────────────────────────────────────────────────────


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


def setup_chat(session, user_id: str):
    from App.Core.Crunch.TablesSQL.Models import IsolatedChat, Chat

    if not session.query(Chat).filter(Chat.chat_id == CHAT_ID).first():
        session.add(
            Chat(
                chat_id=CHAT_ID,
                user_id=user_id,
                chat_name="[BENCH] niche images",
                status="active",
            )
        )
        session.flush()
    ic = (
        session.query(IsolatedChat)
        .filter(IsolatedChat.chat_id == CHAT_ID, IsolatedChat.agent_id == AGENT_ID)
        .first()
    )
    if not ic:
        ic = IsolatedChat(chat_id=CHAT_ID, agent_id=AGENT_ID)
        session.add(ic)
        session.commit()
        session.refresh(ic)
    return ic


def inject(
    session, tool_called: str, tc_type: str, content: str, tool_call_id: str = None
) -> str:
    from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager

    time.sleep(0.3)
    mid = str(uuid.uuid4())
    tid = tool_call_id or mid
    DatabaseManager.save_isolated_message(
        session=session,
        isolated_chat_id=CHAT_ID,
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


def inject_copywriting_lookups(session):
    lid = str(uuid.uuid4())
    files = ["SkillCopywriting.md", "SkillCaption.md"]
    inject(
        session,
        "lookup",
        "input",
        f'Tool: lookup\nArgs: {json.dumps({"files": files}, ensure_ascii=False)}',
        lid,
    )
    inject(
        session,
        "lookup",
        "output",
        json.dumps(
            {
                "success": True,
                "tool": "lookup",
                "files": [
                    {
                        "file": "SkillCopywriting.md",
                        "success": True,
                        "content": "Skill loaded.",
                    },
                    {
                        "file": "SkillCaption.md",
                        "success": True,
                        "content": "Skill loaded.",
                    },
                ],
            }
        ),
        lid,
    )
    session.commit()


def make_core(session, user_id: str):
    from App.Features.Tools.Core import Core

    class LiveDB:
        def get_session(self):
            return session

    core = Core(db_manager=LiveDB())
    core.current_chat_id = CHAT_ID
    core.current_user_id = user_id
    return core


# ── Niche copywriting documents ───────────────────────────────────────────────

NICHES = [
    # ── 1. B2B: Marketing automation SaaS ─────────────────────────────────────
    (
        "B2B_Marketing",
        {
            "archetype": "O Sábio",
            "moodboard": "Editorial tech — azul profundo, branco frio, cinza aço. Corporativo premium. Fotografia limpa, sem ruído visual.",
            "is_paid_ad": True,
            "aspect_ratio": "4:5",
            "framework": "SLAP",
            "stop_hook": "Sua equipe de marketing trabalha mais do que o necessário.",
            "look_proposition": "Automatize campanhas completas em minutos — sem agência, sem overhead.",
            "act_urgency": "14 dias grátis. Sem cartão.",
            "purchase_cta": "Começar agora",
            "minicopy": {
                "post_type": "topo_de_funil",
                "hook": "Marketing que se gerencia sozinho.",
                "trigger": "Autoridade",
                "cta": "Saiba mais",
            },
            "caption": "Sua equipe de marketing merece ferramentas que trabalhem por ela. Automatize, escale, domine.",
            "assets": [
                {
                    "asset_type": "img",
                    "prompt": {
                        "has_realistic_people": True,
                        "subject_context": "Gestora de marketing B2B — analítica, estratégica, no controle dos resultados. Representa o profissional que a ferramenta transforma.",
                        "models": [
                            {
                                "sex": "female",
                                "age": "34-42",
                                "skin_color": "caucasian",
                                "style": "blazer estruturado azul marinho com camiseta off-white — profissional sem ser formal demais, cabelo preso",
                                "skin_texture_moisture": "natural_glow",
                            }
                        ],
                        "pose": "Standing on sidewalk in front of modern glass office building. Arms loosely at sides, weight balanced. Direct, calm eye contact into camera. Slight confident composure — not smiling broadly, just at ease with authority.",
                        "description": (
                            "Full editorial portrait of a confident female marketing executive, early-to-mid 40s. "
                            "She stands on the sidewalk outside a premium glass corporate tower, urban São Paulo in the background. "
                            "Navy structured blazer, off-white tee underneath — polished but approachable. "
                            "Her posture is grounded: weight centered, arms relaxed, looking directly into the camera with quiet authority. "
                            "This is not a stock photo smile — it's the composed presence of someone who knows exactly what they're doing. "
                            "The glass building behind her is softly blurred, reflecting morning light. "
                            "Editorial corporate photography. Premium campaign quality."
                        ),
                        "composition": {
                            "angle": "EyeLevelShot",
                            "grid": "Subject centered, glass facade fills background in soft bokeh — strong vertical lines frame the subject",
                        },
                        "environment": {
                            "place": "Calçada em frente a torre corporativa de vidro, São Paulo — manhã, luz natural lateral",
                            "objects": [
                                {
                                    "item": "glass corporate tower facade in background",
                                    "focus": False,
                                },
                                {
                                    "item": "urban street with soft morning light",
                                    "focus": False,
                                },
                            ],
                        },
                        "colors": {
                            "background": {
                                "hex": ["#D6E0EB", "#1A2B3C"],
                                "detail": "cool glass facade bokeh, deep navy sky at top",
                                "bg_type": "outside",
                            },
                            "subject": {
                                "hex": ["#1A2B4A", "#F5F0E8"],
                                "detail": "navy blazer and off-white tee",
                            },
                            "accent": {
                                "hex": ["#0055FF"],
                                "detail": "subtle electric blue from glass reflections",
                            },
                            "saturation_contrast": "medium-high contrast, cool editorial palette",
                            "harmony": "navy and white with steel-blue architectural accent",
                        },
                        "illumination": "Soft directional morning light from left, slight rim light from glass reflection on right. No harsh shadows. Clean, editorial corporate.",
                        "emotion_style": "Quiet authority — competent, in control, approachable. The professional others want to become.",
                    },
                }
            ],
        },
    ),
    # ── 2. B2C: Cosmetics / skincare ──────────────────────────────────────────
    (
        "B2C_Cosmetics",
        {
            "archetype": "O Amante",
            "moodboard": "Editorial beleza — creme, ouro rosé, branco puro. Minimalismo sensorial. Pele como tela.",
            "is_paid_ad": True,
            "aspect_ratio": "4:5",
            "framework": "PAS",
            "problem": "Pele sem viço, opaca, sem o brilho que você merecia ter todo dia.",
            "agitate": "Você experimenta produto atrás de produto e nada transforma de verdade.",
            "solution": "Uma rotina com o que a sua pele realmente precisa — e o resultado aparece no espelho.",
            "minicopy": {
                "post_type": "branding",
                "hook": "Essa luminosidade é real.",
                "trigger": "Exclusividade",
                "cta": "Descobrir no link",
            },
            "caption": "Pele que fala por si. Sem filtro. Sem edição. Só resultado.",
            "assets": [
                {
                    "asset_type": "img",
                    "prompt": {
                        "has_realistic_people": True,
                        "subject_context": "Mulher que reencontrou a própria beleza — não performática, genuína",
                        "models": [
                            {
                                "sex": "female",
                                "age": "26-34",
                                "skin_color": "parda",
                                "style": "sem roupas visíveis — frame fecha no rosto e clavícula. Pele limpa, sem maquiagem pesada — apenas leve toque de creme.",
                                "skin_texture_moisture": "dewy",
                            }
                        ],
                        "pose": "Face slightly tilted 15 degrees, chin softly down, eyes looking upward into camera — intimate, inviting, warm. Shoulders relaxed. No tension in jaw or brow. Natural, unheld expression.",
                        "description": (
                            "Beauty editorial close-up — a woman in her late 20s to early 30s, parda skin, "
                            "face luminous with natural dewy radiance. "
                            "The frame closes on her face and upper neck — no clothing visible, just skin. "
                            "Her skin texture is the protagonist: visible pores, natural micro-asymmetries, "
                            "warm honey-caramel tones catching soft light. "
                            "She looks upward into the camera with an intimate, slightly tilted gaze — "
                            "not posed, not stock photo. The expression is genuine warmth and ease. "
                            "Cream and gold-rose tones. Hyper-realistic skin rendering. "
                            "Zero background elements — pure skin and warmth."
                        ),
                        "composition": {
                            "angle": "CloseUpShot",
                            "grid": "Face centered, eyes at upper golden ratio line — chin at frame edge",
                        },
                        "environment": {
                            "place": "Estúdio neutro com fundo creme puro — iluminação de beleza suave e difusa",
                            "objects": [
                                {
                                    "item": "soft cream background seamless paper",
                                    "focus": False,
                                }
                            ],
                        },
                        "colors": {
                            "background": {
                                "hex": ["#F5EDE0", "#FFFFFF"],
                                "detail": "warm cream seamless background — minimal, pure",
                                "bg_type": "color",
                            },
                            "subject": {
                                "hex": ["#C4956A", "#8B5E3C", "#E8C5A0"],
                                "detail": "warm parda skin — honey caramel mid-tones, warm shadows",
                            },
                            "accent": {
                                "hex": ["#D4A574", "#F0C9A0"],
                                "detail": "gold-rose highlight on cheekbone and brow ridge",
                            },
                            "saturation_contrast": "warm medium contrast — skin tones dominant, no harsh blacks",
                            "harmony": "monochromatic warm skin tones with gold-rose highlight accent",
                        },
                        "illumination": "Soft diffused beauty light from upper left — large softbox. Subtle fill from right. Warm white temperature. Catches dewy skin luminosity without specular hot spots.",
                        "emotion_style": "Intimate warmth — beauty that belongs to the person, not to the camera.",
                    },
                }
            ],
        },
    ),
    # ── 3. B2C: Automotive ────────────────────────────────────────────────────
    (
        "B2C_Cars",
        {
            "archetype": "O Herói",
            "moodboard": "Fotografia automotiva de campanha — preto profundo, prata escovado, vermelho aceso. Dramático, noturno, cinético.",
            "is_paid_ad": True,
            "aspect_ratio": "1:1",
            "framework": "SLAP",
            "stop_hook": "Alguns carros são transportes. Este é uma declaração.",
            "look_proposition": "Performance que você sente antes de ligar o motor.",
            "act_urgency": "Test drive disponível este fim de semana.",
            "purchase_cta": "Agendar test drive",
            "minicopy": {
                "post_type": "topo_de_funil",
                "hook": "Feito para quem dirige, não só chega.",
                "trigger": "Exclusividade",
                "cta": "Agendar",
            },
            "caption": "Cada detalhe é intencional. Cada curva, calculada. Dirija o que você merece.",
            "assets": [
                {
                    "asset_type": "img",
                    "prompt": {
                        "has_realistic_people": False,
                        "description": (
                            "Extreme hyper close-up of a sports car front hood badge — chrome emblem on matte dark metallic paint. "
                            "The logo fills the entire frame. Surface shows ultra-fine brushed metallic texture with micro-rain droplets "
                            "catching LED light reflections from below. "
                            "The badge itself is perfectly sharp — chrome with beveled edges catching warm amber and cool blue reflections. "
                            "Zero surrounding car body visible beyond the immediate hood surface. "
                            "Deep black paint surface, almost mirror-like despite being matte. "
                            "The image communicates precision engineering and exclusivity through pure materiality. "
                            "Automotive campaign macro photography. Commercial-grade product shot."
                        ),
                        "composition": {
                            "angle": "HyperCloseUpShot",
                            "main_object": "front hood chrome badge — emblem fills frame, rain droplets on surrounding matte dark metallic paint",
                            "grid": "Badge centered with slight upper-left offset — negative space in lower right suggests speed and direction",
                        },
                        "environment": {
                            "place": "Exterior noturno — pista molhada, reflexos de luzes urbanas no asfalto",
                            "objects": [
                                {
                                    "item": "matte dark metallic hood surface surrounding badge",
                                    "focus": False,
                                },
                                {
                                    "item": "micro rain droplets on paint catching LED reflections",
                                    "focus": True,
                                },
                            ],
                        },
                        "colors": {
                            "background": {
                                "hex": ["#0A0A0A", "#1A1A1A"],
                                "detail": "near-black matte metallic hood surface",
                                "bg_type": "product_closeup",
                            },
                            "subject": {
                                "hex": ["#C0C0C0", "#E8E8E8", "#F5F5F5"],
                                "detail": "chrome badge — silver to near-white specular",
                            },
                            "accent": {
                                "hex": ["#CC2200", "#FF4422"],
                                "detail": "deep red accent — warm LED reflection in chrome edges",
                            },
                            "saturation_contrast": "very high contrast — near-black matte vs chrome specular. Dramatic.",
                            "harmony": "monochromatic dark with chrome and single red accent",
                        },
                        "illumination": "Dramatic low-key LED rig — single warm amber source from lower left, cold blue rim from right. Creates depth in chrome via dual-color reflection.",
                        "emotion_style": "Precision and desire — the object as art. No humans needed.",
                    },
                }
            ],
        },
    ),
    # ── 4. B2C: Real estate ───────────────────────────────────────────────────
    (
        "B2C_Imoveis",
        {
            "archetype": "O Explorador",
            "moodboard": "Arquitetura premium — branco, vidro, madeira clara. Luz natural generosa. Espaço como aspiração.",
            "is_paid_ad": True,
            "aspect_ratio": "4:5",
            "framework": "AIDA",
            "attention": "O imóvel que você imaginou existe. E está esperando por você.",
            "interest": "Localização premium, arquitetura contemporânea, acabamento de alto padrão.",
            "desire": "Imagine acorda todo dia com essa vista. Essa cozinha. Esse silêncio.",
            "action": "Agende sua visita hoje.",
            "minicopy": {
                "post_type": "topo_de_funil",
                "hook": "Esse pode ser o seu endereço.",
                "trigger": "Fomo",
                "cta": "Ver imóvel",
            },
            "caption": "Não vendemos imóveis. Vendemos o lugar onde você vai viver a sua melhor fase.",
            "assets": [
                {
                    "asset_type": "img",
                    "prompt": {
                        "has_realistic_people": True,
                        "subject_context": "Corretora de alto padrão — confiante, elegante, apresentando o imóvel como se fosse o lar dela também",
                        "models": [
                            {
                                "sex": "female",
                                "age": "32-42",
                                "skin_color": "caucasian",
                                "style": "vestido midi off-white com cinto fino dourado — elegância discreta, cabelo solto com ondas leves",
                                "skin_texture_moisture": "natural_glow",
                            }
                        ],
                        "pose": "Standing at entrance of modern luxury property, one arm gesturing gently toward the open glass door inviting viewer inside. Slight warm smile, direct eye contact. Weight on back foot — open, welcoming, not salesy.",
                        "description": (
                            "Editorial real estate portrait — a polished female agent, early-to-mid 40s, "
                            "standing at the entrance of a stunning contemporary luxury home. "
                            "She wears an off-white midi dress with a delicate gold belt. "
                            "Her posture is open and welcoming: one arm gestures softly toward the glass entrance door, "
                            "the other relaxed at her side. Her expression is warm — a genuine, knowing smile "
                            "that says 'I already know you're going to love this.' "
                            "Behind her: floor-to-ceiling glass, exposed concrete, warm wood detailing, "
                            "manicured green garden softly blurred in the far background. "
                            "The architecture itself communicates luxury without ostentation. "
                            "Midday light floods the entrance naturally. "
                            "Premium real estate campaign photography."
                        ),
                        "composition": {
                            "angle": "HighAngleShot",
                            "grid": "Subject positioned lower-center frame, architecture fills upper two-thirds — property as protagonist, agent as guide",
                        },
                        "environment": {
                            "place": "Entrada de mansão contemporânea de alto padrão — São Paulo, Jardins ou Alphaville. Fachada de concreto aparente, vidro e madeira clara. Jardim verde na lateral.",
                            "objects": [
                                {
                                    "item": "glass double-door entrance, slightly open",
                                    "focus": False,
                                },
                                {
                                    "item": "manicured green garden on left side",
                                    "focus": False,
                                },
                                {
                                    "item": "warm wood architectural detail on facade",
                                    "focus": False,
                                },
                            ],
                        },
                        "colors": {
                            "background": {
                                "hex": ["#F0ECE4", "#2C3E2D", "#8B7355"],
                                "detail": "warm off-white concrete, deep green garden, warm wood facade tones",
                                "bg_type": "outside",
                            },
                            "subject": {
                                "hex": ["#F5F0E8", "#D4AF70"],
                                "detail": "off-white dress and gold belt accent",
                            },
                            "accent": {
                                "hex": ["#C9A96E", "#2C5F2E"],
                                "detail": "gold belt and garden green create warm-cool balance",
                            },
                            "saturation_contrast": "medium contrast, warm natural tones — premium and livable",
                            "harmony": "warm neutrals (concrete, wood, cream) with green garden accent",
                        },
                        "illumination": "Midday natural light from above and left — fills entrance warmly. No artificial lighting. Soft shadow on right side of facade creates architectural depth.",
                        "emotion_style": "Aspirational belonging — this is not just a house, it's the version of your life you've been imagining.",
                    },
                }
            ],
        },
    ),
    # ── 5. B2C: Fashion ──────────────────────────────────────────────────────
    (
        "B2C_Fashion",
        {
            "archetype": "O Rebelde",
            "moodboard": "Street editorial noturno — preto, couro, asfalto molhado, néon. Cru, urbano, sem concessões.",
            "is_paid_ad": True,
            "aspect_ratio": "4:5",
            "framework": "SLAP",
            "stop_hook": "Moda não é o que você veste. É o que você comunica.",
            "look_proposition": "Peças que falam antes de você abrir a boca.",
            "act_urgency": "Coleção limitada — peças numeradas.",
            "purchase_cta": "Ver coleção",
            "minicopy": {
                "post_type": "branding",
                "hook": "Você não combina. Você define.",
                "trigger": "Exclusividade",
                "cta": "Ver coleção",
            },
            "caption": "Não é roupa. É identidade. Cada peça conta algo que você ainda não disse.",
            "assets": [
                {
                    "asset_type": "img",
                    "prompt": {
                        "has_realistic_people": True,
                        "subject_context": "Mulher que não pede permissão — sua presença é a declaração",
                        "models": [
                            {
                                "sex": "female",
                                "age": "22-30",
                                "skin_color": "caucasian",
                                "style": "jaqueta de couro preta oversized com ombros estruturados, calça de couro slim preta, botas cano alto preto — monocromático total, agressivo e preciso",
                                "skin_texture_moisture": "natural_glow",
                            }
                        ],
                        "pose": "Standing dead-center of wet urban street at night. Weight shifted to right hip — one hip out, stance wide. Arms loose at sides. Head slightly tilted back, looking directly into camera from above — total ownership of the space. No smile. Absolute confidence.",
                        "description": (
                            "Night street fashion editorial — a young woman, early-to-late 20s, "
                            "caucasian, standing in the dead center of a wet urban street at night. "
                            "All-black leather: oversized structured leather jacket with sharp shoulders, "
                            "slim leather pants, knee-high black boots. "
                            "Her stance is wide and grounded — weight on one hip, arms loose, claiming every inch of the frame. "
                            "Head slightly tilted back, looking directly into the camera: "
                            "not a challenge, not a pose — pure ownership. "
                            "The wet asphalt reflects neon signs: electric pink, cold blue, amber. "
                            "Her jacket catches the neon, adding colour to the otherwise all-black silhouette. "
                            "Camera is below her foot level — she towers over the viewer. "
                            "Night fashion campaign. Raw, cinematic, editorial."
                        ),
                        "composition": {
                            "angle": "LowAngleShot",
                            "grid": "Subject centered full-vertical — street receding in forced perspective behind her, neon reflections in wet asphalt frame her below",
                        },
                        "environment": {
                            "place": "Rua urbana noturna molhada — São Paulo, centro. Asfalto refletindo néons de lojas. Calçada vazia. Postes de luz ao fundo.",
                            "objects": [
                                {
                                    "item": "wet asphalt reflecting neon signs",
                                    "focus": True,
                                },
                                {
                                    "item": "distant urban street lights creating depth",
                                    "focus": False,
                                },
                                {
                                    "item": "pink and blue neon sign reflections on jacket surface",
                                    "focus": False,
                                },
                            ],
                        },
                        "colors": {
                            "background": {
                                "hex": ["#0A0A0A", "#1A0A1A", "#0A0A2E"],
                                "detail": "near-black wet street, deep midnight blue and purple shadows from neon wash",
                                "bg_type": "outside",
                            },
                            "subject": {
                                "hex": ["#0D0D0D", "#1A1A1A"],
                                "detail": "all-black leather — matte jacket body with semi-gloss highlights",
                            },
                            "accent": {
                                "hex": ["#FF2D7A", "#4488FF"],
                                "detail": "electric pink and cold blue neon reflections on jacket and asphalt",
                            },
                            "saturation_contrast": "extreme contrast — near-black subject against neon-lit wet street. Vivid accent colors only where neon touches.",
                            "harmony": "monochromatic black with dual neon accent (pink + blue) — graphic, night-editorial",
                        },
                        "illumination": "Hard backlit neon from behind and sides — no fill, intentional deep shadows on face and body. Single cold-blue rim from left, warm pink spill from right neon. Dramatic low-key night editorial.",
                        "emotion_style": "Defiance and ownership — she doesn't dress for the room, she IS the room.",
                    },
                }
            ],
        },
    ),
]


# ── Runner ────────────────────────────────────────────────────────────────────


def run():
    print(f"\n{SEP}")
    print("  NICHE IMAGE BENCHMARK - 5 nichos, sem brand_communication")
    print(SEP)

    session = get_session()
    user_id = get_user_id(session)
    setup_chat(session, user_id)
    core = make_core(session, user_id)

    results = []

    for niche_name, copy_data in NICHES:
        print(f"\n{SEP2}")
        print(f"  [{niche_name}]")

        inject_copywriting_lookups(session)

        doc_result_str = core._execute_document(
            {"type": "copywriting", "title": f"[BENCH] {niche_name}", "data": copy_data}
        )
        doc_result = json.loads(doc_result_str)

        if not doc_result.get("success"):
            errors = doc_result.get("errors", doc_result.get("correction_required", []))
            print("  [FAIL] COPYWRITING REJEITADO:")
            for e in errors:
                print(f"     {e}")
            results.append({"niche": niche_name, "doc_ok": False, "asset_ok": False})
            continue

        doc_id = doc_result.get("id")
        print(f"  [OK] Document criado: {doc_id}")

        asset_result_str = core._execute_asset(
            {"document_id": doc_id, "human_mode": False}
        )
        asset_result = json.loads(asset_result_str)

        processed = asset_result.get("processed", [])
        asset_url = None
        if processed:
            generated = processed[0].get("result", {}).get("generated_assets", [])
            if generated:
                asset_url = generated[0].get("asset_url", "")

        ok = asset_result.get("success") and bool(asset_url)
        icon = "[OK]" if ok else "[FAIL]"
        print(f"  {icon} Asset: {asset_url or asset_result.get('error', 'sem url')}")

        results.append(
            {
                "niche": niche_name,
                "doc_ok": True,
                "asset_ok": ok,
                "asset_url": asset_url,
            }
        )

    print(f"\n{SEP}")
    print("  RESULTADO FINAL")
    print(SEP)
    passed = sum(1 for r in results if r["asset_ok"])
    print(f"  {passed}/{len(results)} imagens geradas com sucesso\n")
    for r in results:
        icon = "[OK]" if r["asset_ok"] else "[FAIL]"
        print(f"  {icon}  {r['niche']}")

    session.close()


if __name__ == "__main__":
    run()
