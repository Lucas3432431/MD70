"""
Simulação end-to-end: business_canvas -> brand_communication -> product -> copywriting -> assets.

Replica o comportamento da IA passo a passo num único chat, injetando tool calls
em isolated_messages e chamando document()/asset() para validar cada etapa.

Fluxo simulado:
  ── BUSINESS CANVAS ──
  00. web-search visual-analysis sem canvas           -> bloqueado
  00b/c. web-search searches/insta sem canvas         -> bloqueado
  01. quiz sem lookup                                 -> bloqueado
  03. quiz com TAM/SAM/SOM (proibido)                 -> bloqueado
  04b. document após quiz correto: bloqueia por web-search, não quiz
  05/06. web-search sem orçamento                    -> bloqueado
  08. document(business_canvas)                       -> SUCESSO

  ── BRAND COMMUNICATION ──
  08b. web-search visual-analysis após canvas         -> guard liberado
  09. document(brand_comm) sem lookup brand           -> bloqueado
  11. document(brand_comm) sem web-search             -> bloqueado
  13. web-search incompleto (falta branding)          -> bloqueado
  15. document(brand_communication)                   -> SUCESSO

  ── PRODUCT ──
  16. document(copywriting) sem product               -> bloqueado
  17. document(product) sem lookup                    -> bloqueado
  20. document(product) dados inválidos               -> bloqueado
  21. document(product)                               -> SUCESSO

  ── COPYWRITING ──
  22. document(copywriting) sem lookup                -> bloqueado
  23. document(copywriting) sem quiz                  -> bloqueado
  24. document(copywriting) sem tasks                 -> bloqueado
  25. document(copywriting SLAP)                      -> SUCESSO
  26. document(copywriting PAS)                       -> SUCESSO
  27. document(copywriting inválido)                  -> bloqueado

  ── ASSET GENERATION ──
  28. asset(document_ids=[slap, pas])                 -> 2 processados
  29. asset([slap, canvas_id])                        -> canvas rejeitado, slap processado
  30. asset() sem document_id                         -> bloqueado
  31-32. asset(document_id) sequencial                -> SUCESSO

  ── COMPOSIÇÃO VALIDAÇÃO ──
  F6-1..F6-11. Diretivas bg_type + angle + novos frameworks

  ── GATE SYSTEM + PARTIAL DOCUMENT ──
  F7-1. gate doc completo pendente + quiz         -> bloqueado
  F7-2. gate doc completo pendente + document     -> bloqueado
  F7-3. document parcial (variation.count=2, só v1) -> success=false, status=partial
  F7-4. gate parcial + asset()                    -> bloqueado
  F7-5. gate parcial + quiz                       -> bloqueado
  F7-6. continuação document(document_id=..., v2) -> success=true
  F7-7. após conclusão: partial=False, gate ativo  -> verificado

  ── CRÉDITOS ──
  F8-1. resposta asset contém credits_consumed e credits_remaining
  F8-2. DB debitado após geração
  F8-3. credits_remaining na resposta ≈ saldo no DB

  ── CHAT CONNECTIONS ──
  C1. connections=NULL → mcp tool NÃO bloqueada por connections
  C2. connections exclui provider → mcp tool BLOQUEADA
  C3. connections inclui provider → mcp tool NÃO bloqueada por connections

  ── SCHEDULER ──
  S1. process_scheduled_tasks() cria task_execution para task vencida
  S2. scheduler cria chat 'Agendamento: <nome>'
  S3. connections do chat bate com integrations da task
  S4. next_execution_at atualizado para próxima execução (futuro)
  S5. agente processou prompt 'oi' e respondeu (mensagem assistant no chat)

  ── TRIGGERS (webhooks externos) ──
  T1–T25. Ver Scripts/Tests/TriggersValidation/test_triggers_flow.py

Uso:
    cd App/mvp/services/backend
    python3 Scripts/Tests/FullFlowValidation/test_full_flow_simulation.py
    python3 Scripts/Tests/FullFlowValidation/test_full_flow_simulation.py --cleanup
    python3 Scripts/Tests/FullFlowValidation/test_full_flow_simulation.py --env-file .env.development
"""

import sys, os, uuid, json, argparse, time
from datetime import datetime, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from Scripts.HealthCheck.health_check import run_health_check

_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--env-file", default=str(BACKEND_DIR / ".env.wsl"))
_parser.add_argument("--cleanup", action="store_true")
_args, _ = _parser.parse_known_args()

os.environ["ENV_FILE"] = _args.env_file

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS — configuração, dados de teste e strings esperadas
# ══════════════════════════════════════════════════════════════════════════════

# ── Runtime ───────────────────────────────────────────────────────────────────

SEP = "=" * 70
SEP2 = "-" * 70
CLEANUP = _args.cleanup
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

HEALTH_URL = "http://localhost:4001/api/health"

AGENT_ID = "orchestrator-global"
AGENT_NAME = "ORCHESTRATOR_GLOBAL"
CHAT_ID = f"sim-{str(uuid.uuid4())[:8]}"

results: list[dict] = []

# ── Strings esperadas nos erros (expect_in_error) ─────────────────────────────
# Centralizadas aqui para facilitar manutenção quando mensagens de erro mudarem.

E_CANVAS_NO_LOOKUP = ["lookup"]
E_CANVAS_QUIZ_FORBIDDEN = ["quiz"]
E_CANVAS_WS_MISSING = ["orçamento"]
E_CANVAS_VS_BLOCKED = ["business_canvas", "fetch", "query"]
E_CANVAS_VS_BLOCKED_MULTI = ["business_canvas"]

E_BRAND_NO_LOOKUP = ["lookup"]
E_BRAND_WS_MISSING = ["brand"]

E_PRODUCT_MISSING_IN_COPY = ["product"]
E_PRODUCT_NO_LOOKUP = ["lookup"]
E_PRODUCT_INVALID = [
    "product_page_url",
    "site_description",
    "consciousness_level",
    "icp",
]

E_COPY_NO_LOOKUP = ["lookup"]
E_COPY_NO_QUIZ = ["quiz"]
E_COPY_NO_TASKS = ["task"]
E_COPY_INVALID = ["aspect_ratio", "minicopy", "archetype", "moodboard"]
E_COPY_ANGLE_INVALID = ["angle"]
E_COPY_NO_MAIN_OBJ = ["main_object"]
E_COPY_NO_ARCHETYPE = ["archetype"]
E_COPY_NO_MOODBOARD = ["moodboard"]

E_ASSET_NO_DOC = ["copywriting"]

E_GATE_PENDING_DOC = ["obrigatória", "asset"]  # doc completo salvo, asset() não chamado
E_GATE_PARTIAL_DOC = [
    "documento parcial",
    "variações",
]  # doc parcial, tool não-document bloqueada

# ── Document data ─────────────────────────────────────────────────────────────

CANVAS_DATA = {
    "favicon": "https://example.com/favicon.ico",
    "public_target": "smb",
    "consciousness_level": "Consciente da Solução",
    "icp": [
        {
            "title": "Gestores de Marketing em SMBs",
            "firmografia": {
                "annual_revenue": "R$500k-R$5M",
                "sector": "SaaS / MarTech",
                "employees": "10-50",
                "digital_maturity": "Alta",
                "technology": "Cloud-native, IA",
                "motivator": {
                    "type": "pain",
                    "explanation": "Perde vantagem competitiva por lentidão na produção de conteúdo — concorrentes publicam mais e melhor.",
                },
            },
        }
    ],
    "lifecycle_crm": {
        "acquisition": "Inbound via conteúdo educativo e indicações",
        "qualification": "Trial de 7 dias + uso real da plataforma",
        "conversion": "Proposta consultiva após ativação no trial",
        "onboarding": "Setup guiado + call de boas-vindas em 24h",
        "activation": "Primeiro criativo gerado em menos de 5 minutos",
        "retention": "Templates salvos e histórico de campanhas recorrentes",
        "expansion": "Upgrade ao atingir limite de créditos mensais",
        "indication": "Programa de referral + NPS alto",
        "churn": "Falta de ativação nos primeiros 14 dias do trial",
    },
    "lifecycle_value": {
        "aha_moment": "Primeiro criativo gerado em menos de 5 minutos",
        "value_moment": "Calendário da primeira semana completo com resultado mensurável",
        "habit": "Uso semanal para planejamento e produção de conteúdo",
        "advocacy": "Compartilha resultados nas redes e indica para outros gestores",
    },
    "pains_gains": {
        "pain": {
            "psychological_effect": "Sensação de estar sendo ultrapassado por concorrentes que comunicam melhor",
            "perceived_impact": "Perda de vantagem competitiva por incapacidade de transformar visão em presença consistente",
        },
        "gain": "Produção em escala com controle criativo e estruturação de empresa de alta performance",
    },
    "market_sizing": {"tam": 50000000000, "sam": 5000000000, "som": 50000000},
    "viability": {
        "customer_bargaining_power": 6,
        "threat_new_entrants": 7,
        "rivalry": 8,
    },
    "gtm_strategy": {
        "value_proposition": "IA assistiva para produção de marketing em escala",
        "customer_relationship": "Onboarding guiado, suporte via chat, comunidade",
        "channels": ["LinkedIn", "Google Ads", "Parcerias com agências"],
        "revenue_streams": ["Assinatura mensal SaaS", "Planos anuais com desconto"],
    },
    "competitors": [
        {"name": "HubSpot", "favicon_url": "https://hubspot.com/favicon.ico"},
        {"name": "Canva", "favicon_url": "https://canva.com/favicon.ico"},
    ],
    "obs": "SMB define comunicação consultiva com construção de autoridade. Nível Consciente da Solução permite comunicação de diferenciação. Rivalidade alta (8/10) exige diferenciação clara.",
}

BRAND_DATA = {
    "favicon": "https://example.com/favicon.ico",
    "brand_archetype": {
        "archetype": "racional",
        "slogan": "Produza mais, pense melhor.",
        "unicity": 80,
    },
    "color_palette": {
        "colors": [
            {
                "hex": "#0055FF",
                "name": "Azul",
                "feeling": {"name": "Confiança", "value": 90},
            },
            {
                "hex": "#FFFFFF",
                "name": "Branco",
                "feeling": {"name": "Clareza", "value": 85},
            },
            {
                "hex": "#222222",
                "name": "Preto",
                "feeling": {"name": "Autoridade", "value": 75},
            },
        ]
    },
    "font": {"primary": "Inter", "secondary": "Roboto"},
    "voice_tone": {"seriousness": 8, "exclusivity": 6, "tradition": 4},
    "target_pulse": {
        "provocation": 3,
        "warmth": 4,
        "precision": 5,
        "energy": 4,
        "mystery": 2,
    },
    "moodboard": {"description": "Visual limpo, moderno, data-driven."},
    "brand_matrix": {
        "dimensions": [
            {"is": "Intuitivo e rápido", "is_not": "Complexo e técnico"},
            {"is": "Resultados mensuráveis", "is_not": "Promessa sem entrega"},
        ]
    },
    "exclusive_avatar": {"url": "https://example.com/avatar.png"},
    "models": {
        "inspirations": [
            {"brand_name": "HubSpot", "favicon_url": "https://hubspot.com/favicon.ico"},
            {"brand_name": "Canva", "favicon_url": "https://canva.com/favicon.ico"},
        ]
    },
}

PRODUCT_DATA = {
    "product_page_url": "https://prox.com.br/",
    "product_image": "https://prox.com.br/og-image.jpg",
    "price": "R$297/mês",
    "value_proposition": "Escale sua produção de marketing 10x mais rápido com IA enterprise.",
    "pain": "Gestores SMB perdem horas criando conteúdo manualmente e perdem competitividade.",
    "solution": "MD70 centraliza pesquisa, roteiro e geração de criativos numa única IA.",
    "site_description": "MD70 é uma plataforma de IA enterprise para produção de marketing em escala. Do briefing ao criativo publicável em 5 minutos.",
    "consciousness_level": "Consciente da Solução",
    "brand": {"name": "MD70", "ownership": "own"},
    "icp": [
        {
            "title": "Gestores de Marketing em SMBs",
            "demographics": {
                "age_range": "28-45",
                "gender": "Masculino/Feminino",
                "location": "Brasil",
                "social_class": "Classe A/B",
                "consumption_habits": "SaaS-first, compra por ROI demonstrável",
                "values": "Eficiência, resultado mensurável, escala",
                "motivator": {
                    "type": "pain",
                    "explanation": "Perde vantagem competitiva por lentidão na produção de conteúdo — concorrentes publicam mais e melhor.",
                },
            },
        }
    ],
    "reviews": [
        "Economizo 3h por dia — antes levava uma manhã para criar um post, agora faço em 5 minutos.",
        "A qualidade dos criativos aumentou muito e meu engajamento dobrou em 3 semanas.",
    ],
    "feedbacks": [
        "Seria ótimo ter integração direta com o TikTok Ads.",
        "Mais templates para nicho de saúde seriam bem-vindos.",
    ],
    "availability": True,
    "stock_quantity": None,
}

# Inválido: faltam product_page_url, site_description, consciousness_level, icp
PRODUCT_INVALID = {
    "price": "R$297/mês",
    "value_proposition": "Escale sua produção.",
    "pain": "Gestores perdem tempo.",
    "solution": "IA resolve.",
}

# ── Narrative (base compartilhada por todos os frameworks) ────────────────────

_NARRATIVE = {
    "archetype": "O Herói",
    "moodboard": "Visual limpo, moderno, data-driven. Tons frios corporativos com acento azul.",
    "hypothesy": "Gestores SMB perdem competitividade por lentidão na produção de conteúdo.",
    "problem": "Criar criativos de qualidade consome horas e exige múltiplas ferramentas.",
    "solution": "MD70 centraliza pesquisa, roteiro e geração de imagem numa única IA.",
    "transformation": "De horas de trabalho manual para minutos de produção automatizada.",
    "hook_pain_awareness": "Você sente que seus concorrentes publicam mais e melhor que você?",
    "empathy": "Eu entendo — produzir conteúdo consistente sem equipe grande é exaustivo.",
    "autority": "Analisamos 500+ campanhas de SMBs para construir o MD70.",
    "solution_contious": "A resposta é centralizar estratégia, criativo e execução numa única plataforma de IA.",
    "product_contious": "MD70: do briefing ao criativo publicável em 5 minutos.",
    "offer_concious": "Teste grátis 7 dias. Cancele quando quiser.",
}

_MINICOPY_TOPO = {
    "post_type": "topo_de_funil",
    "hook": "Você ainda cria post manual?",
    "trigger": "Escassez de tempo",
    "cta": "Teste grátis no link da bio",
}
_MINICOPY_MEIO = {
    "post_type": "meio_de_funil",
    "hook": "Seu concorrente já usa IA. Você não?",
    "trigger": "Comparação social",
    "cta": "Comece agora — 7 dias grátis",
}
_MINICOPY_FUND = {
    "post_type": "fundo_de_funil",
    "hook": "Pronto para escalar seu marketing?",
    "trigger": "Urgência + prova social",
    "cta": "Assine o Plano Pro agora",
}

# ── Asset prompt base (FASE de copywriting principal) ─────────────────────────

_PROMPT_STRUCT = {
    "has_realistic_people": True,
    "subject_context": "empresário brasileiro bem-sucedido — dono de PME, no controle do seu negócio",
    "models": [
        {
            "sex": "male",
            "age": "36-44",
            "skin_color": "caucasian",
            "style": "camisa social off-white slim fit, relógio de aço escovado, sem gravata",
            "skin_texture_moisture": "natural_glow",
        }
    ],
    "pose": "Standing slightly leaned against executive desk. Direct eye contact. Composed, self-assured.",
    "description": (
        "Direct portrait of a Brazilian male entrepreneur, mid-30s to mid-40s. "
        "Leaned against executive desk, composed self-assured expression. "
        "Cinematic executive photography. Aspirational solo composition."
    ),
    "composition": {
        "angle": "HyperCloseUpShot",
        "main_object": "eye — direct gaze, strong jaw partially visible",
        "grid": "Face centered, window light spilling as blurred background",
    },
    "environment": {
        "place": "Premium private executive office in São Paulo — floor-to-ceiling window with blurred urban skyline.",
        "objects": [
            {"item": "sleek closed laptop on desk corner", "focus": False},
            {"item": "architectural art frame on wall behind", "focus": False},
        ],
    },
    "colors": {
        "background": {
            "hex": ["#EDE8E0", "#1C1C2E"],
            "detail": "Warm off-white wall + deep navy skyline",
            "bg_type": "window",
        },
        "subject": {
            "hex": ["#F2EDE4", "#C4956A"],
            "detail": "Off-white shirt against warm moreno skin",
        },
        "accent": {
            "hex": ["#0055FF", "#2A2A5A"],
            "detail": "Deep confident blue — technology and trust",
        },
        "saturation_contrast": "Muted warm editorial, single cool blue accent.",
        "harmony": "Analogous warm neutrals with precise cool blue anchor",
    },
    "illumination": "Soft natural daylight from left window + warm amber fill from sconce. Cinematic portrait lighting.",
    "emotion_style": "Quiet authority and calm confidence — clarity, agency, the lightness of having the right tool.",
    "negative_prompt": (
        "No broad smiles. No theatrical poses. No second person. "
        "No cluttered office. No visible text. No suit jacket or tie."
    ),
}

_ASSET = [{"asset_type": "img", "prompt": _PROMPT_STRUCT}]

# ── Copy frameworks (FASE copywriting principal: SLAP + PAS) ──────────────────

COPY_SLAP = {
    **_NARRATIVE,
    "is_paid_ad": False,
    "aspect_ratio": "9:16",
    "framework": "SLAP",
    "stop_hook": "Você demora mais de 1 hora pra criar um post?",
    "look_proposition": "MD70 gera criativos em menos de 5 minutos com IA enterprise.",
    "act_urgency": "Teste grátis por 7 dias — sem cartão.",
    "purchase_cta": "Acesse prox.com.br agora",
    "minicopy": _MINICOPY_TOPO,
    "caption": "Crie posts profissionais em minutos com IA. Teste grátis 7 dias.",
    "assets": _ASSET,
}

COPY_PAS = {
    **_NARRATIVE,
    "is_paid_ad": True,
    "aspect_ratio": "1:1",
    "framework": "PAS",
    "problem": "Gestores SMB perdem horas criando conteúdo manualmente.",
    "agitate": "Enquanto você gasta 3 horas num único post, seu concorrente publicou 5 criativos com IA. Cada dia sem automação é receita perdida.",
    "solution": "MD70 automatiza sua produção do briefing ao criativo em minutos com IA enterprise.",
    "minicopy": _MINICOPY_MEIO,
    "caption": "Automatize sua produção. IA enterprise que aprende sua marca. Teste 7 dias grátis.",
    "assets": _ASSET,
}

# Inválido: aspect_ratio + minicopy + narrative ausentes
COPY_INVALID = {
    "is_paid_ad": False,
    "framework": "SLAP",
    "stop_hook": "Hook válido para parar o scroll e capturar atenção imediata",
    "look_proposition": "Proposição de valor clara e diferenciada para o público-alvo",
    "act_urgency": "Urgência real com prazo definido para criar senso de escassez",
    "purchase_cta": "CTA direto e objetivo para conversão imediata do lead",
    "caption": "Caption válida e completa para o post.",
    "assets": _ASSET,
}

# ── Copy frameworks adicionais (FASE 6: composição) ───────────────────────────

COPY_ACC = {
    **_NARRATIVE,
    "is_paid_ad": False,
    "aspect_ratio": "1:1",
    "framework": "ACC",
    "awareness_problem": "Você sente que está perdendo clientes por comunicar mal?",
    "comprehension_explanation": "A maioria dos SMBs perde market share por lentidão criativa, não por produto ruim.",
    "conversion_solution": "MD70 automatiza sua produção — do briefing ao criativo em 5 minutos.",
    "minicopy": _MINICOPY_TOPO,
    "caption": "Comunicação consistente é vantagem competitiva. MD70 entrega isso.",
    "assets": _ASSET,
}

COPY_4CS = {
    **_NARRATIVE,
    "is_paid_ad": True,
    "aspect_ratio": "4:5",
    "framework": "4CS",
    "clear_message": "MD70 gera criativos profissionais em minutos, não horas.",
    "concise_copy": "IA enterprise. Do briefing ao post em 5 min. Teste grátis.",
    "compelling_angle": "Cada hora perdida criando conteúdo manual é receita entregue ao concorrente.",
    "credible_proof": "Mais de 10.000 criativos gerados por mês para SMBs brasileiros.",
    "minicopy": _MINICOPY_MEIO,
    "caption": "IA que entende sua marca e produz criativos sob medida. Teste agora.",
    "assets": _ASSET,
}

COPY_AIDA = {
    **_NARRATIVE,
    "is_paid_ad": False,
    "aspect_ratio": "9:16",
    "framework": "AIDA",
    "attention": "Você sabia que 73% das PMEs perdem clientes por comunicação inconsistente?",
    "interest": "MD70 usa IA enterprise para aprender o tom da sua marca e produzir criativos sob medida.",
    "desire": "Imagine ter um calendário de conteúdo completo, pronto em menos de 1 hora por semana.",
    "action": "Comece grátis hoje — sem cartão de crédito.",
    "minicopy": _MINICOPY_FUND,
    "caption": "Da estratégia ao criativo em minutos. IA que entende sua marca.",
    "assets": _ASSET,
}

COPY_FAB = {
    **_NARRATIVE,
    "is_paid_ad": True,
    "aspect_ratio": "16:9",
    "framework": "FAB",
    "features": "IA enterprise multimodal — gera texto, imagem e estratégia de funil integrados.",
    "advantages": "Diferente de ferramentas genéricas, o MD70 aprende o tom e estilo da sua marca.",
    "benefits": "Você produz criativos de alta qualidade em minutos, não horas — sem precisar de agência.",
    "minicopy": _MINICOPY_FUND,
    "caption": "Features que entregam resultados reais. IA que cresce junto com seu negócio.",
    "assets": _ASSET,
}

# ── Asset prompts de composição (FASE 6) ──────────────────────────────────────

_PROMPT_HIGH_ANGLE = {
    "has_realistic_people": True,
    "subject_context": "mulher empreendedora B2C — aspiracional, representando o resultado que o produto entrega",
    "models": [
        {
            "sex": "female",
            "age": "28-36",
            "skin_color": "parda",
            "style": "blusa de lã cream slim fit",
            "skin_texture_moisture": "dewy",
        }
    ],
    "description": (
        "Posed portrait of a strikingly attractive Brazilian woman. "
        "Camera 28 degrees above eye-line. Expression: hopeful confidence. Cinematic B2C lifestyle."
    ),
    "pose": "Upper body upright, chin slightly lifted toward camera. Warm open expression.",
    "composition": {
        "angle": "HighAngleShot",
        "grid": "subject centered, generous breathing room",
    },
    "environment": {
        "place": "bright minimal apartment, soft warm natural light",
        "objects": [{"item": "clean white wall", "focus": False}],
    },
    "colors": {
        "background": {
            "hex": ["#F5EDE0", "#FFFFFF"],
            "detail": "warm cream wall",
            "bg_type": "outside",
        },
        "subject": {"hex": ["#F2EDE4", "#C4956A"]},
        "accent": {"hex": ["#D4A574"], "detail": "warm golden amber"},
        "saturation_contrast": "warm muted editorial",
        "harmony": "analogous warm neutrals",
    },
    "illumination": "soft diffused daylight from left window, warm reflector right",
    "emotion_style": "aspirational warmth — hopeful, open, relatable confidence",
    "negative_prompt": "No loose or baggy clothing. No male in image.",
}

_PROMPT_LOW_ANGLE = {
    "has_realistic_people": True,
    "subject_context": "executivo B2B — autoridade natural, presença de liderança sem esforço",
    "models": [
        {
            "sex": "male",
            "age": "40-50",
            "skin_color": "moreno claro",
            "style": "terno escuro slim, camisa azul oxford, relógio discreto",
            "skin_texture_moisture": "natural_glow",
        }
    ],
    "description": (
        "Powerful low-angle portrait of a commanding Brazilian executive. "
        "Camera below waist — subject fills frame from below. Calm authority."
    ),
    "pose": "Standing tall, shoulders back. Looking slightly above camera toward horizon.",
    "composition": {"angle": "LowAngleShot", "grid": "subject fills left two-thirds"},
    "environment": {
        "place": "premium executive building lobby — marble floors, glass panels",
        "objects": [{"item": "architectural glass panel", "focus": False}],
    },
    "colors": {
        "background": {
            "hex": ["#1C1C2E", "#2C3E50"],
            "detail": "deep corporate navy",
            "bg_type": "outside",
        },
        "subject": {"hex": ["#1A1A2E", "#4A90D9"]},
        "accent": {"hex": ["#0055FF"], "detail": "corporate blue"},
        "saturation_contrast": "high contrast, cool corporate",
        "harmony": "cool blues with warm skin",
    },
    "illumination": "dramatic directional key light above right + upward fill",
    "emotion_style": "natural authority — dominant presence without aggression",
    "negative_prompt": "No casual attire. No female in image.",
}

_PROMPT_POV = {
    "has_realistic_people": True,
    "subject_context": "POV experiencial B2C — espectador vive o momento em primeira pessoa",
    "models": [
        {
            "sex": "female",
            "age": "25-35",
            "skin_color": "branca",
            "style": "mãos com manicure discreta, anel minimalista",
            "skin_texture_moisture": "dewy",
        }
    ],
    "description": (
        "First-person POV — viewer looking down from subject's perspective. "
        "Well-manicured female hands holding a premium laptop. No face visible."
    ),
    "pose": "Both hands extended holding laptop. Camera from subject's eyes looking down.",
    "composition": {
        "angle": "POVShot",
        "grid": "hands lower-center, laptop as focal center",
    },
    "environment": {
        "place": "premium home studio desk — warm marble, soft morning light",
        "objects": [
            {"item": "sleek laptop open on desk", "focus": True},
            {"item": "espresso cup steaming", "focus": False},
        ],
    },
    "colors": {
        "background": {
            "hex": ["#F5EDE0", "#DDD8C4"],
            "detail": "warm marble desk",
            "bg_type": "outside",
        },
        "subject": {"hex": ["#F2EDE4", "#D4A574"]},
        "accent": {"hex": ["#D4A574", "#2D5F4F"], "detail": "warm amber and sage"},
        "saturation_contrast": "warm lifestyle editorial",
        "harmony": "warm earth tones",
    },
    "illumination": "soft diffused morning light, gentle desk shadows",
    "emotion_style": "aspirational ease — quiet pleasure of being in control",
    "negative_prompt": "No face visible. No body beyond hands and wrists.",
}

_PROMPT_FACELESS = {
    "has_realistic_people": True,
    "subject_context": "empresário de alto padrão — autoridade sem identidade, projeção universal de sucesso",
    "models": [
        {
            "sex": "male",
            "age": "38-52",
            "skin_color": "moreno",
            "style": "terno charcoal premium, abotoadura de prata, relógio de luxo",
            "skin_texture_moisture": "natural_glow",
        }
    ],
    "description": (
        "Close-up of a high-status businessman — no face in frame. "
        "Crop at chin/neck. Charcoal suit lapel, silver cufflinks, crystal whisky glass."
    ),
    "pose": "Torso turned 3/4. One hand holding whisky glass at chest. Face cropped at chin.",
    "composition": {"angle": "DetailShot", "grid": "torso and hands fill frame"},
    "environment": {
        "place": "upscale private club — dark walnut paneling",
        "objects": [{"item": "crystal whisky glass with ice", "focus": True}],
    },
    "colors": {
        "background": {
            "hex": ["#1A1208", "#2C1F0E"],
            "detail": "dark warm walnut",
            "bg_type": "product_closeup",
        },
        "subject": {"hex": ["#2C2C2C", "#C0A882"]},
        "accent": {
            "hex": ["#C0A882", "#F5A623"],
            "detail": "silver cufflinks and whisky amber",
        },
        "saturation_contrast": "rich warm, high contrast",
        "harmony": "dark analogous — charcoal, walnut, amber",
    },
    "illumination": "dramatic Rembrandt single source — warm amber right, golden specular on watch",
    "emotion_style": "power and exclusivity — the aesthetic of someone who has already won",
    "negative_prompt": "No face in frame — crop at chin/neck. No casual clothing.",
}

_PROMPT_BW = {
    "has_realistic_people": True,
    "subject_context": "modelo fashion — elegância atemporal em preto e branco",
    "models": [
        {
            "sex": "female",
            "age": "22-32",
            "skin_color": "clara",
            "style": "vestido preto de alfaiataria slim — linha limpa",
            "skin_texture_moisture": "natural_glow",
        }
    ],
    "description": (
        "Black and white fashion portrait — full monochromatic, no color. "
        "Fitted tailored black dress, direct intense gaze. High contrast B&W."
    ),
    "pose": "Standing tall, one shoulder forward. Direct intense eye contact. No smile.",
    "composition": {
        "angle": "HighAngleShot",
        "grid": "model centered, strong negative space",
    },
    "environment": {
        "place": "minimal neutral studio — clean gray backdrop",
        "objects": [{"item": "seamless gray backdrop", "focus": False}],
    },
    "colors": {
        "background": {
            "hex": ["#000000", "#FFFFFF"],
            "detail": "full monochromatic",
            "bg_type": "black_white",
        },
        "subject": {"hex": ["#808080"]},
        "accent": {"hex": ["#404040"], "detail": "mid gray"},
        "saturation_contrast": "pure monochromatic",
        "harmony": "monochromatic",
    },
    "illumination": "strong directional studio light — Hurrell-style Hollywood glamour for B&W",
    "emotion_style": "timeless fashion elegance — cool, intense, classically authoritative",
    "negative_prompt": "No color anywhere. No loose clothing. Strictly monochromatic.",
}

_PROMPT_HYPER_CLOSEUP = {
    "has_realistic_people": True,
    "subject_context": "hiper close-up — detalhe facial que transmite emoção intensa",
    "models": [
        {
            "sex": "female",
            "age": "28-36",
            "skin_color": "parda",
            "style": "brinco minimalista dourado",
            "skin_texture_moisture": "dewy",
        }
    ],
    "description": (
        "Extreme hyper close-up — eye fills 90% of frame. Long lashes, dewy skin, amber iris. "
        "Gold earring at frame edge. Zero background visible."
    ),
    "pose": "Face slightly tilted, eye open and relaxed. Camera extremely close.",
    "composition": {
        "angle": "HyperCloseUpShot",
        "main_object": "eye — long lashes, warm amber iris, dewy skin",
        "grid": "eye as absolute center, micro-detail composition",
    },
    "environment": {
        "place": "indoors with soft diffused window light",
        "objects": [{"item": "minimal gold earring at frame edge", "focus": False}],
    },
    "colors": {
        "background": {
            "hex": ["#F5EDE0", "#FFFFFF"],
            "detail": "warm skin tones fill frame",
            "bg_type": "window",
        },
        "subject": {
            "hex": ["#C4956A", "#8B5E3C"],
            "detail": "warm parda skin and amber iris",
        },
        "accent": {"hex": ["#D4A574"], "detail": "gold earring highlight"},
        "saturation_contrast": "warm editorial, medium contrast",
        "harmony": "warm skin tones with gold",
    },
    "illumination": "soft diffused window light from left, hyper-detailed skin rendering",
    "emotion_style": "intimate vulnerability — one eye tells the whole story",
    "negative_prompt": "No full face visible. No body beyond eye and cheekbone area.",
}

# ── Copy frameworks de composição (FASE 6) ────────────────────────────────────

COPY_HIGH_ANGLE = {
    **_NARRATIVE,
    "is_paid_ad": False,
    "aspect_ratio": "4:5",
    "framework": "AIDA",
    "attention": "A ferramenta que transforma gestores SMBs em máquinas de marketing.",
    "interest": "MD70 usa IA enterprise para produzir sob medida.",
    "desire": "Calendário completo em menos de 1 hora por semana, sem equipe.",
    "action": "Comece grátis hoje — sem cartão.",
    "minicopy": {
        "post_type": "topo_de_funil",
        "hook": "Marketing no automático começa aqui.",
        "trigger": "Aspiração",
        "cta": "Teste grátis no link",
    },
    "caption": "Marketing escalável começa com a ferramenta certa.",
    "assets": [{"asset_type": "img", "prompt": _PROMPT_HIGH_ANGLE}],
}

COPY_LOW_ANGLE = {
    **_NARRATIVE,
    "is_paid_ad": True,
    "aspect_ratio": "9:16",
    "framework": "FAB",
    "features": "IA enterprise com análise de funil integrada e produção de criativos em minutos.",
    "advantages": "Aprende o tom da marca e produz criativos sob medida.",
    "benefits": "De horas de trabalho manual para minutos de produção automatizada, sem agência.",
    "minicopy": {
        "post_type": "fundo_de_funil",
        "hook": "Liderança começa com decisões inteligentes.",
        "trigger": "Autoridade",
        "cta": "Assine o Plano Pro",
    },
    "caption": "Tome decisões de marketing com autoridade e dados.",
    "assets": [{"asset_type": "img", "prompt": _PROMPT_LOW_ANGLE}],
}

COPY_POV = {
    **_NARRATIVE,
    "is_paid_ad": False,
    "aspect_ratio": "1:1",
    "framework": "SLAP",
    "stop_hook": "E se seu marketing se fizesse sozinho?",
    "look_proposition": "MD70 gera criativos profissionais em 5 minutos com IA enterprise.",
    "act_urgency": "Teste grátis por 7 dias — sem cartão de crédito.",
    "purchase_cta": "Acesse no link da bio agora",
    "minicopy": {
        "post_type": "topo_de_funil",
        "hook": "POV: você no controle do seu marketing.",
        "trigger": "Imersão",
        "cta": "Descubra no link da bio",
    },
    "caption": "POV: sua produção de conteúdo no automático com IA.",
    "assets": [{"asset_type": "img", "prompt": _PROMPT_POV}],
}

COPY_FACELESS = {
    **_NARRATIVE,
    "is_paid_ad": True,
    "aspect_ratio": "1:1",
    "framework": "PAS",
    "problem": "Executivos perdem credibilidade por comunicação inconsistente e amadora.",
    "agitate": "Cada post abaixo do padrão corrói a autoridade que levou anos para construir.",
    "solution": "MD70 entrega criativos de nível corporativo em minutos, sem agência.",
    "minicopy": {
        "post_type": "meio_de_funil",
        "hook": "Status não se grita. Se comunica.",
        "trigger": "Autoridade",
        "cta": "Conheça o MD70 Pro",
    },
    "caption": "Autoridade se constrói post a post. Com IA.",
    "assets": [{"asset_type": "img", "prompt": _PROMPT_FACELESS}],
}

COPY_BW = {
    **_NARRATIVE,
    "is_paid_ad": False,
    "aspect_ratio": "4:5",
    "framework": "4CS",
    "clear_message": "MD70: criativos premium em minutos com IA enterprise.",
    "concise_copy": "Do briefing ao post em 5 min. IA que aprende sua marca.",
    "compelling_angle": "Cada hora perdida criando conteúdo manual é vantagem entregue ao concorrente.",
    "credible_proof": "Mais de 10.000 criativos gerados por mês para SMBs brasileiros.",
    "minicopy": {
        "post_type": "branding",
        "hook": "Elegância e performance. Sem escolher um.",
        "trigger": "Exclusividade",
        "cta": "Conheça o MD70",
    },
    "caption": "Produção de conteúdo premium. Atemporal como a sua marca.",
    "assets": [{"asset_type": "img", "prompt": _PROMPT_BW}],
}

COPY_HYPER_CLOSEUP = {
    **_NARRATIVE,
    "is_paid_ad": False,
    "aspect_ratio": "1:1",
    "framework": "SLAP",
    "stop_hook": "O detalhe que ninguem percebe faz toda a diferenca.",
    "look_proposition": "MD70 captura a essencia da sua marca em cada detalhe.",
    "act_urgency": "Teste gratis — sem cartao de credito.",
    "purchase_cta": "Acesse no link da bio",
    "minicopy": {
        "post_type": "branding",
        "hook": "Beleza nos detalhes.",
        "trigger": "Exclusividade",
        "cta": "Descubra no link",
    },
    "caption": "Cada detalhe conta. Sua marca no proximo nivel.",
    "assets": [{"asset_type": "img", "prompt": _PROMPT_HYPER_CLOSEUP}],
}

NEW_COMPOSITION_FRAMEWORKS = [
    ("HIGH_ANGLE", COPY_HIGH_ANGLE),
    ("LOW_ANGLE", COPY_LOW_ANGLE),
    ("POV", COPY_POV),
    ("FACELESS", COPY_FACELESS),
    ("BW", COPY_BW),
    ("HYPER_CLOSEUP", COPY_HYPER_CLOSEUP),
]

# ── Partial document data (FASE 7: gate + continuação) ───────────────────────
# variation.count=2, apenas variation_1 enviada → partial save (variation_2 faltando)

_COPY_PARTIAL_BASE = {
    **_NARRATIVE,
    "is_paid_ad": False,
    "aspect_ratio": "1:1",
    "framework": "PAS",
    "problem": "Gestores SMB perdem horas criando conteúdo manualmente.",
    "agitate": "Cada hora perdida é vantagem entregue ao concorrente que já usa IA.",
    "solution": "MD70 automatiza a produção em minutos com IA enterprise.",
    "minicopy": _MINICOPY_TOPO,
    "caption": "Sua produção no automático. IA que aprende sua marca.",
    "assets": _ASSET,
    "variation": {"category": "Gatilhos", "count": 2},
    "variation_1": {
        "hook": "Hook 1: urgência — você ainda cria posts manualmente?",
        "body": "Body 1: cada minuto manual é desvantagem competitiva. MD70 resolve em 5 minutos.",
    },
    # variation_2 intencionalmente ausente → partial save com missing_variations=[2]
}

_COPY_PARTIAL_COMPLETE = {
    **_NARRATIVE,
    "is_paid_ad": False,
    "aspect_ratio": "1:1",
    "framework": "PAS",
    "problem": "Gestores SMB perdem horas criando conteúdo manualmente.",
    "agitate": "Cada hora perdida é vantagem entregue ao concorrente que já usa IA.",
    "solution": "MD70 automatiza a produção em minutos com IA enterprise.",
    "minicopy": _MINICOPY_TOPO,
    "caption": "Sua produção no automático. IA que aprende sua marca.",
    "assets": _ASSET,
    "variation": {"category": "Gatilhos", "count": 2},
    "variation_1": {
        "hook": "Hook 1: urgência — você ainda cria posts manualmente?",
        "body": "Body 1: cada minuto manual é desvantagem competitiva. MD70 resolve em 5 minutos.",
    },
    "variation_2": {
        "hook": "Hook 2: prova social — 10k criativos gerados por SMBs brasileiros.",
        "body": "Body 2: resultado concreto, sem agência. MD70 entrega criativos em 5 minutos.",
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS — DB, injeção de tool calls, step assertion
# ══════════════════════════════════════════════════════════════════════════════

# ── DB ────────────────────────────────────────────────────────────────────────


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
                chat_name="[SIM] full flow",
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


def make_core(session, user_id: str):
    from App.Features.Tools.Core import Core

    class LiveDB:
        def get_session(self):
            return session

    core = Core(db_manager=LiveDB())
    core.current_chat_id = CHAT_ID
    core.current_user_id = user_id
    return core


def wipe_test_documents(session, user_id: str):
    session.execute(
        text(
            "DELETE FROM documents WHERE user_id = :uid "
            "AND tool_type IN ('business_canvas', 'brand_communication', 'copywriting', 'product')"
        ),
        {"uid": user_id},
    )
    session.commit()
    print("  [CLEAN] Documentos de test anteriores removidos do DB")


def get_user_credits(session, user_id: str) -> float:
    row = session.execute(
        text("SELECT credits FROM users WHERE user_id = :uid"), {"uid": user_id}
    ).fetchone()
    return float(row[0]) if row else 0.0


# ── Injeção de tool calls ─────────────────────────────────────────────────────


def inject(
    session, tool_called: str, tc_type: str, content: str, tool_call_id: str = None
) -> str:
    from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager

    time.sleep(0.5)
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


def inject_product_lookup(session):
    lid = str(uuid.uuid4())
    inject(
        session,
        "lookup",
        "input",
        'Tool: lookup\nArgs: {"file": "SkillProduct.md"}',
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
                "file": "SkillProduct.md",
                "content": "Skill loaded.",
            }
        ),
        lid,
    )
    session.commit()


def inject_product_web_search(session):
    wid = str(uuid.uuid4())
    inject(
        session,
        "web-search",
        "input",
        f'Tool: web-search\nArgs: {json.dumps({"fetch": "https://prox.com.br/"}, ensure_ascii=False)}',
        wid,
    )
    inject(
        session,
        "web-search",
        "output",
        json.dumps(
            {
                "success": True,
                "type": "fetch",
                "content": "MD70 — plataforma de IA para marketing. Preço: R$297/mês. Avaliações: 4.8/5.",
            }
        ),
        wid,
    )
    session.commit()


def inject_product_quiz(session):
    qid = str(uuid.uuid4())
    quiz_args = {
        "quiz": [
            {
                "question": "Qual é o ICP do produto?",
                "options": ["Gestores SMB 28-45 anos", "Freelancers"],
                "type": "validação",
            },
            {
                "question": "Qual é o nível de consciência do ICP?",
                "options": ["Consciente do Problema", "Consciente da Solução"],
                "type": "validação",
            },
            {
                "question": "Qual é a dor principal que o produto resolve?",
                "options": ["Lentidão na criação de conteúdo", "Custo de agência"],
                "type": "validação",
            },
        ]
    }
    inject(
        session,
        "quiz",
        "input",
        f"Tool: quiz\nArgs: {json.dumps(quiz_args, ensure_ascii=False)}",
        qid,
    )
    inject(
        session,
        "quiz",
        "output",
        json.dumps(
            {
                "success": True,
                "final_answers": [
                    {
                        "question": "Qual é o ICP do produto?",
                        "answer": "Gestores SMB — decisores de marketing digital.",
                    },
                    {
                        "question": "Qual o nível de consciência?",
                        "answer": "Consciente da Solução — conhecem o problema.",
                    },
                    {
                        "question": "Qual a dor principal?",
                        "answer": "Perdem horas criando conteúdo manualmente.",
                    },
                ],
            }
        ),
        qid,
    )
    session.commit()


def inject_copywriting_lookups(session):
    """Injeta lookup de SkillCopywriting.md (única skill obrigatória para copywriting)."""
    lid = str(uuid.uuid4())
    inject(
        session,
        "lookup",
        "input",
        'Tool: lookup\nArgs: {"file": "SkillCopywriting.md"}',
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
                "file": "SkillCopywriting.md",
                "content": "Skill loaded.",
            }
        ),
        lid,
    )
    session.commit()


def inject_copywriting_quiz(session):
    """Quiz com keywords obrigatórios: quantos assets + o que validar."""
    qid = str(uuid.uuid4())
    quiz_args = {
        "quiz": [
            {
                "question": "Quantos assets você quer gerar para este copywriting?",
                "options": ["1", "2", "3", "IA decide"],
                "type": "asset_quantity",
            },
            {
                "question": "O que você quer validar neste criativo?",
                "options": [
                    "headline",
                    "ângulo de comunicação",
                    "cor e estilo visual",
                    "IA decide",
                ],
                "type": "validation_focus",
            },
        ]
    }
    inject(
        session,
        "quiz",
        "input",
        f"Tool: quiz\nArgs: {json.dumps(quiz_args, ensure_ascii=False)}",
        qid,
    )
    inject(
        session,
        "quiz",
        "output",
        json.dumps(
            {
                "success": True,
                "final_answers": [
                    {"question": "Quantos assets?", "answer": "2 assets por criativo."},
                    {
                        "question": "O que validar?",
                        "answer": "headline e ângulo de comunicação.",
                    },
                ],
            }
        ),
        qid,
    )
    session.commit()


def inject_copywriting_tasks(session):
    """2 tasks de postagens propostas (pré-requisito para copywriting)."""
    for title, desc in [
        (
            "Post 1: Hook SLAP para gestor SMB",
            "Stop hook direto para gestor que perde 1h/dia em conteúdo manual",
        ),
        (
            "Post 2: PAS para decisor de marketing",
            "Dor, agitação e solução para decisores que perdem clientes por comunicação ruim",
        ),
    ]:
        tid = str(uuid.uuid4())
        inject(
            session,
            "task",
            "input",
            f'Tool: task\nArgs: {json.dumps({"title": title, "description": desc}, ensure_ascii=False)}',
            tid,
        )
        inject(
            session,
            "task",
            "output",
            json.dumps({"success": True, "task_id": str(uuid.uuid4()), "title": title}),
            tid,
        )
    session.commit()


# ── Step assertion ────────────────────────────────────────────────────────────


def step(
    label: str, expect_success: bool, result_str: str, expect_in_error: list[str] = None
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
        + result.get("warning", "")
        + " "
        + result.get("status", "")
        + " "
        + str(result.get("missing_variations", []))
        + " "
        + str(result.get("missing_steps", []))
        + " "
        + str(result.get("correction_required", []))
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
    slug = label[:40].replace(" ", "_").replace("->", "").replace("/", "")
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


# ── BG / Angle unit test helpers ──────────────────────────────────────────────


def _build_bg_test_prompt(bg_type: str) -> dict:
    return {
        "has_realistic_people": False,
        "description": "BG type directive injection test.",
        "composition": {"angle": "CloseUpShot", "grid": "center"},
        "environment": {"place": "studio", "objects": []},
        "colors": {
            "background": {
                "hex": ["#000000", "#FFFFFF"],
                "detail": "test",
                "bg_type": bg_type,
            },
            "subject": {"hex": ["#808080"]},
            "accent": {"hex": ["#404040"], "detail": "gray"},
            "saturation_contrast": "high contrast",
            "harmony": "monochromatic",
        },
        "illumination": "dramatic studio",
        "emotion_style": "elegant",
    }


def check_bg_type_injection(bg_type: str, required_strings: list) -> str:
    from App.Features.Tools.Tools.Assets import assemble_asset_prompt

    assembled = assemble_asset_prompt(_build_bg_test_prompt(bg_type))
    missing = [s for s in required_strings if s.lower() not in assembled.lower()]
    return json.dumps(
        {
            "success": len(missing) == 0,
            "bg_type": bg_type,
            "missing_strings": missing,
            "assembled_length": len(assembled),
        }
    )


def check_framing_directive(angle: str, required_strings: list) -> str:
    from App.Features.Tools.Tools.Assets import assemble_asset_prompt

    _comp = {"angle": angle, "grid": "center"}
    if angle == "HyperCloseUpShot":
        _comp["main_object"] = "eye"
    p = {
        "has_realistic_people": False,
        "description": "Framing directive test.",
        "composition": _comp,
        "environment": {
            "place": "studio",
            "objects": [{"item": "backdrop", "focus": False}],
        },
        "colors": {
            "background": {
                "hex": ["#000000"],
                "detail": "dark",
                "bg_type": "product_closeup",
            },
            "subject": {"hex": ["#808080"]},
            "accent": {"hex": ["#404040"], "detail": "gray"},
            "saturation_contrast": "high",
            "harmony": "mono",
        },
        "illumination": "studio",
        "emotion_style": "neutral",
    }
    assembled = assemble_asset_prompt(p)
    missing = [s for s in required_strings if s.lower() not in assembled.lower()]
    return json.dumps(
        {
            "success": len(missing) == 0,
            "angle": angle,
            "missing_strings": missing,
            "assembled_length": len(assembled),
        }
    )


def _make_bg_angle_copy(bg_type: str, angle: str, hrp: bool = True) -> dict:
    _comp = {"angle": angle, "grid": "center"}
    if angle == "HyperCloseUpShot":
        _comp["main_object"] = "eye"
    _prompt = {
        "has_realistic_people": hrp,
        "description": "Validation test.",
        "composition": _comp,
        "environment": {
            "place": "studio",
            "objects": [{"item": "backdrop", "focus": False}],
        },
        "colors": {
            "background": {"hex": ["#FFFFFF"], "detail": "test", "bg_type": bg_type},
            "subject": {"hex": ["#C4956A"]},
            "accent": {"hex": ["#0055FF"], "detail": "blue"},
            "saturation_contrast": "medium",
            "harmony": "neutral",
        },
        "illumination": "soft studio",
        "emotion_style": "neutral",
    }
    if hrp:
        _prompt["subject_context"] = "validation subject"
        _prompt["models"] = [
            {
                "sex": "female",
                "age": "25-35",
                "skin_color": "parda",
                "style": "casual",
                "skin_texture_moisture": "natural_glow",
            }
        ]
        _prompt["pose"] = "Standing upright, facing camera directly."
    return {
        **_NARRATIVE,
        "is_paid_ad": False,
        "aspect_ratio": "1:1",
        "framework": "SLAP",
        "stop_hook": "Hook",
        "look_proposition": "Prop",
        "act_urgency": "Urgency",
        "purchase_cta": "CTA",
        "minicopy": {
            "post_type": "topo_de_funil",
            "hook": "Hook",
            "trigger": "T",
            "cta": "CTA",
        },
        "caption": "Caption.",
        "assets": [{"asset_type": "img", "prompt": _prompt}],
    }


# ══════════════════════════════════════════════════════════════════════════════
# TEST FLOW
# ══════════════════════════════════════════════════════════════════════════════


def run():
    run_health_check(
        backend_url=HEALTH_URL.replace("/api/health", ""), check_frontend=False
    )

    session = get_session()
    user_id = get_user_id(session)
    setup_chat(session, user_id)
    wipe_test_documents(session, user_id)
    core = make_core(session, user_id)

    canvas_document_id = None
    product_document_id = None
    copy_doc_ids = {}  # {"SLAP": uuid, "PAS": uuid}

    print(f"\n{'#' * 70}")
    print("  SIMULAÇÃO END-TO-END: canvas + brand + product + copywriting + assets")
    print(f"  chat_id: {CHAT_ID}")
    print(f"{'#' * 70}")

    # ── FASE 1: BUSINESS CANVAS ───────────────────────────────────────────────
    print(f"\n{SEP}\n  FASE 1: BUSINESS CANVAS\n{SEP}")

    step(
        "00. web-search visual-analysis sem canvas -> bloqueado",
        expect_success=False,
        result_str=core._execute_web_search(
            {"visual-analysis": "http://localhost:8081/"}
        ),
        expect_in_error=E_CANVAS_VS_BLOCKED,
    )

    step(
        "00b. web-search searches[visual-analysis] sem canvas -> bloqueado",
        expect_success=False,
        result_str=core._execute_web_search(
            {
                "searches": [
                    {"query": "marketing SaaS"},
                    {"visual-analysis": "http://localhost:8081/"},
                ]
            }
        ),
        expect_in_error=E_CANVAS_VS_BLOCKED_MULTI,
    )

    step(
        "00c. web-search insta sem canvas -> bloqueado",
        expect_success=False,
        result_str=core._execute_web_search({"insta": "@prox"}),
        expect_in_error=E_CANVAS_VS_BLOCKED_MULTI,
    )

    # 01. quiz sem lookup -> bloqueado
    qid = str(uuid.uuid4())
    inject(
        session,
        "quiz",
        "input",
        f'Tool: quiz\nArgs: {json.dumps({"quiz": [{"question": "Qual a proposta de valor?", "options": ["IA assistiva", "Consultoria"], "type": "validação"}]}, ensure_ascii=False)}',
        qid,
    )
    inject(
        session,
        "quiz",
        "output",
        json.dumps(
            {
                "success": True,
                "final_answers": [
                    {
                        "question": "Qual a proposta de valor?",
                        "answer": "IA assistiva para produção em escala",
                    }
                ],
            }
        ),
        qid,
    )
    session.commit()
    step(
        "01. quiz feito sem lookup -> bloqueado",
        expect_success=False,
        result_str=core._execute_document(
            {"type": "business_canvas", "title": "Canvas", "data": CANVAS_DATA}
        ),
        expect_in_error=E_CANVAS_NO_LOOKUP,
    )

    # 02. lookup SkillBusinessCanvas.md
    lid = str(uuid.uuid4())
    inject(
        session,
        "lookup",
        "input",
        'Tool: lookup\nArgs: {"file": "SkillBusinessCanvas.md"}',
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
                "file": "SkillBusinessCanvas.md",
                "content": "Skill loaded.",
            }
        ),
        lid,
    )
    session.commit()

    # 03. quiz com TAM/SAM/SOM -> bloqueado (strings proibidas)
    qid2 = str(uuid.uuid4())
    inject(
        session,
        "quiz",
        "input",
        f'Tool: quiz\nArgs: {json.dumps({"quiz": [{"question": "Qual o TAM do mercado?", "options": ["SAM grande", "SOM médio"], "type": "validação"}]}, ensure_ascii=False)}',
        qid2,
    )
    inject(
        session,
        "quiz",
        "output",
        json.dumps(
            {
                "success": True,
                "final_answers": [
                    {
                        "question": "Qual o TAM do mercado?",
                        "answer": "TAM de R$50B, SAM R$5B, SOM R$50M",
                    }
                ],
            }
        ),
        qid2,
    )
    session.commit()
    step(
        "03. quiz com TAM/SAM/SOM -> bloqueado (strings proibidas)",
        expect_success=False,
        result_str=core._execute_document(
            {"type": "business_canvas", "title": "Canvas", "data": CANVAS_DATA}
        ),
        expect_in_error=E_CANVAS_QUIZ_FORBIDDEN,
    )

    # 04. quiz correto INPUT + OUTPUT com strings proibidas (OUTPUT ignorado)
    qid3 = str(uuid.uuid4())
    quiz_input_data = {
        "quiz": [
            {
                "question": "Qual é a proposta de valor principal?",
                "options": ["Automação com IA", "Consultoria"],
                "type": "validação",
            },
            {
                "question": "Qual é a principal dor dos clientes?",
                "options": ["Falta de tempo", "Trabalho manual"],
                "type": "validação",
            },
            {
                "question": "Qual é a firmografia da empresa?",
                "options": ["SaaS", "Agência"],
                "type": "validação",
            },
            {
                "question": "Nível de consciência dos clientes?",
                "options": ["Baixo", "Médio", "Alto — buscam soluções"],
                "type": "validação",
            },
        ]
    }
    inject(
        session,
        "quiz",
        "input",
        f"Tool: quiz\nArgs: {json.dumps(quiz_input_data, ensure_ascii=False)}",
        qid3,
    )
    inject(
        session,
        "quiz",
        "output",
        json.dumps(
            {
                "success": True,
                "final_answers": [
                    {
                        "question": "Proposta de valor?",
                        "answer": "IA assistiva — o TAM do mercado é R$50B, SAM R$5B.",
                    },
                    {
                        "question": "Dor dos clientes?",
                        "answer": "Síndrome da folha em branco.",
                    },
                    {
                        "question": "Firmografia?",
                        "answer": "SaaS — orçamento mensal de R$5.000.",
                    },
                    {
                        "question": "Nível de consciência?",
                        "answer": "Alto — conhecem o problema.",
                    },
                ],
            }
        ),
        qid3,
    )
    session.commit()
    print(
        f"\n  [INFO] [04] quiz correto injetado — OUTPUT contém TAM/SAM/orçamento (deve ser ignorado)"
    )

    # 04b. document: ainda bloqueia por web-search, NÃO por quiz
    result_04b = json.loads(
        core._execute_document(
            {"type": "business_canvas", "title": "Canvas", "data": CANVAS_DATA}
        )
    )
    quiz_not_blamed = (
        "quiz invalido" not in result_04b.get("error", "").lower()
        and "strings proibidas" not in result_04b.get("error", "").lower()
    )
    results.append(
        {
            "label": "04b. output quiz proibido ignorado — não bloqueia por quiz",
            "passed": quiz_not_blamed,
            "result": result_04b,
        }
    )
    icon = "[OK]" if quiz_not_blamed else "[FAIL]"
    print(f"\n{SEP2}")
    print(f"{icon}  04b. output quiz proibido ignorado — não bloqueia por quiz")
    print(
        f"     quiz_not_blamed={quiz_not_blamed}  erro: {result_04b.get('error','')[:120]}"
    )

    # 05/06. web-search incompleto (sem orçamento) -> bloqueado
    ws1 = str(uuid.uuid4())
    inject(
        session,
        "web-search",
        "input",
        f'Tool: web-search\nArgs: {json.dumps({"searches": [{"query": "TAM Total Addressable Market MarTech"}, {"query": "SAM Serviceable Addressable Market SaaS"}, {"query": "SOM Serviceable Obtainable Market"}, {"query": "barriers to entry SaaS marketing platform"}, {"query": "market age MarTech"}]}, ensure_ascii=False)}',
        ws1,
    )
    inject(
        session,
        "web-search",
        "output",
        json.dumps(
            {
                "success": True,
                "type": "multiple_searches",
                "results": [
                    {"query": "p1", "content": "Resultado genérico."},
                    {"query": "p2", "content": "Outro resultado."},
                    {"query": "p3", "content": "Mais um resultado."},
                    {"query": "p4", "content": "Conteúdo qualitativo."},
                    {"query": "p5", "content": "Análise sem valores."},
                ],
            }
        ),
        ws1,
    )
    session.commit()
    step(
        "05/06. web-search sem orçamento -> document bloqueado (só INPUT conta)",
        expect_success=False,
        result_str=core._execute_document(
            {"type": "business_canvas", "title": "Canvas", "data": CANVAS_DATA}
        ),
        expect_in_error=E_CANVAS_WS_MISSING,
    )

    # 07. web-search com orçamento
    ws2 = str(uuid.uuid4())
    inject(
        session,
        "web-search",
        "input",
        f'Tool: web-search\nArgs: {json.dumps({"query": "budget marketing digital investimento mensal PME"}, ensure_ascii=False)}',
        ws2,
    )
    inject(
        session,
        "web-search",
        "output",
        json.dumps(
            {
                "success": True,
                "type": "query",
                "content": "PMEs gastam entre R$5k e R$15k/mês em marketing digital.",
            }
        ),
        ws2,
    )
    session.commit()
    print(f"\n  [INFO] [07] web-search com orçamento injetado")

    # 08. document(business_canvas) -> SUCESSO
    _canvas_str = core._execute_document(
        {
            "type": "business_canvas",
            "title": "Business Canvas MD70",
            "data": CANVAS_DATA,
        }
    )
    step(
        "08. document(business_canvas) -> SUCESSO",
        expect_success=True,
        result_str=_canvas_str,
    )
    try:
        canvas_document_id = json.loads(_canvas_str).get("id")
        print(f"     canvas_document_id: {canvas_document_id}")
    except Exception:
        pass

    # ── FASE 2: BRAND COMMUNICATION ───────────────────────────────────────────
    print(f"\n{SEP}\n  FASE 2: BRAND COMMUNICATION\n{SEP}")

    # 08b. visual-analysis após canvas -> guard liberado
    result_08b = json.loads(
        core._execute_web_search({"visual-analysis": "http://localhost:8081/"})
    )
    guard_passed = (
        result_08b.get("error", "")
        != "web-search com visual-analysis ou insta só é permitido após criar document(type='business_canvas')."
    )
    results.append(
        {
            "label": "08b. web-search visual-analysis após canvas -> guard liberado",
            "passed": guard_passed,
            "result": result_08b,
        }
    )
    icon = "[OK]" if guard_passed else "[FAIL]"
    print(f"\n{SEP2}")
    print(f"{icon}  08b. web-search visual-analysis após canvas -> guard liberado")
    print(f"     guard_passed={guard_passed}  (erro de rede/timeout é aceitável)")

    # 09. brand_comm sem lookup brand -> bloqueado
    session.close()
    session = get_session()
    core = make_core(session, user_id)
    step(
        "09. document(brand_comm) sem lookup brand -> bloqueado",
        expect_success=False,
        result_str=core._execute_document(
            {"type": "brand_communication", "title": "Brand", "data": BRAND_DATA}
        ),
        expect_in_error=E_BRAND_NO_LOOKUP,
    )

    # 10. lookup SkillBrandIdentity.md + quiz cor/tom
    lid2 = str(uuid.uuid4())
    inject(
        session,
        "lookup",
        "input",
        'Tool: lookup\nArgs: {"file": "SkillBrandIdentity.md"}',
        lid2,
    )
    inject(
        session,
        "lookup",
        "output",
        json.dumps(
            {
                "success": True,
                "tool": "lookup",
                "file": "SkillBrandIdentity.md",
                "content": "Skill loaded.",
            }
        ),
        lid2,
    )
    session.commit()
    qid4 = str(uuid.uuid4())
    inject(
        session,
        "quiz",
        "input",
        f'Tool: quiz\nArgs: {json.dumps({"quiz": [{"question": "Quais são as cores da sua marca?", "options": ["Azul e branco", "Verde"], "type": "multiple_choice"}, {"question": "Qual é o tom de comunicação da sua marca?", "options": ["Profissional", "Descontraído"], "type": "multiple_choice"}]}, ensure_ascii=False)}',
        qid4,
    )
    inject(
        session,
        "quiz",
        "output",
        json.dumps(
            {
                "success": True,
                "final_answers": [
                    {
                        "question": "Quais são as cores?",
                        "answer": "Cores: azul #0055FF e branco #FFFFFF.",
                    },
                    {
                        "question": "Qual é o tom?",
                        "answer": "Tom profissional e direto.",
                    },
                ],
            }
        ),
        qid4,
    )
    session.commit()
    print(f"\n  [INFO] [10] lookup SkillBrandIdentity.md + quiz cor/tom injetados")

    # 11. brand_comm sem web-search -> bloqueado
    step(
        "11. document(brand_comm) sem web-search -> bloqueado",
        expect_success=False,
        result_str=core._execute_document(
            {"type": "brand_communication", "title": "Brand", "data": BRAND_DATA}
        ),
        expect_in_error=E_BRAND_WS_MISSING,
    )

    # 13. web-search incompleto (falta branding)
    ws3 = str(uuid.uuid4())
    inject(
        session,
        "web-search",
        "input",
        f'Tool: web-search\nArgs: {json.dumps({"searches": [{"query": "top of funnel marketing conteúdo awareness"}, {"query": "mid funnel estratégia consideração leads"}, {"query": "bottom funnel conversão vendas"}]}, ensure_ascii=False)}',
        ws3,
    )
    inject(
        session,
        "web-search",
        "output",
        json.dumps(
            {
                "success": True,
                "type": "multiple_searches",
                "results": [
                    {
                        "query": "p1",
                        "content": "Estratégia de conteúdo para etapas iniciais.",
                    },
                    {
                        "query": "p2",
                        "content": "Nutrição de leads em fase intermediária.",
                    },
                    {
                        "query": "p3",
                        "content": "Foco em conversão: demonstrações e provas sociais.",
                    },
                ],
            }
        ),
        ws3,
    )
    session.commit()
    step(
        "13. web-search incompleto -> bloqueado (falta branding)",
        expect_success=False,
        result_str=core._execute_document(
            {"type": "brand_communication", "title": "Brand", "data": BRAND_DATA}
        ),
        expect_in_error=E_BRAND_WS_MISSING,
    )

    # 14. web-search completo (branding + visual-analysis)
    ws4 = str(uuid.uuid4())
    inject(
        session,
        "web-search",
        "input",
        f'Tool: web-search\nArgs: {json.dumps({"searches": [{"query": "funil de vendas completo top mid bottom funnel"}, {"query": "branding identidade visual estratégia de marca"}]}, ensure_ascii=False)}',
        ws4,
    )
    inject(
        session,
        "web-search",
        "output",
        json.dumps(
            {
                "success": True,
                "type": "multiple_searches",
                "results": [
                    {"query": "p4", "content": "Cobertura completa da jornada."},
                    {"query": "p5", "content": "Identidade visual consistente."},
                ],
            }
        ),
        ws4,
    )
    ws5 = str(uuid.uuid4())
    inject(
        session,
        "web-search",
        "input",
        f'Tool: web-search\nArgs: {json.dumps({"visual-analysis": "http://localhost:8081/", "fetch": "http://localhost:8081/"}, ensure_ascii=False)}',
        ws5,
    )
    inject(
        session,
        "web-search",
        "output",
        json.dumps({"success": True, "type": "fetch", "content": "Página carregada."}),
        ws5,
    )
    session.commit()
    print(f"\n  [INFO] [14] web-search funnel+branding+visual-analysis injetados")

    # 15. document(brand_communication) -> SUCESSO
    step(
        "15. document(brand_communication) -> SUCESSO",
        expect_success=True,
        result_str=core._execute_document(
            {
                "type": "brand_communication",
                "title": "Brand Communication MD70",
                "data": BRAND_DATA,
            }
        ),
    )

    # ── FASE 3: PRODUCT ───────────────────────────────────────────────────────
    print(f"\n{SEP}\n  FASE 3: PRODUCT\n{SEP}")

    # 16. copywriting sem product -> bloqueado
    step(
        "16. document(copywriting) sem product -> bloqueado",
        expect_success=False,
        result_str=core._execute_document(
            {"type": "copywriting", "title": "Copy sem product", "data": COPY_SLAP}
        ),
        expect_in_error=E_PRODUCT_MISSING_IN_COPY,
    )

    # 17. product sem lookup -> bloqueado
    step(
        "17. document(product) sem lookup -> bloqueado",
        expect_success=False,
        result_str=core._execute_document(
            {"type": "product", "title": "Product sem lookup", "data": PRODUCT_DATA}
        ),
        expect_in_error=E_PRODUCT_NO_LOOKUP,
    )

    # Injetar lookup + web-search + quiz do produto
    # (web-search e quiz já estão satisfeitos pelo histórico do canvas neste fluxo sequencial)
    print(f"\n  [INFO] [17b] Injetando lookup + web-search + quiz do produto")
    inject_product_lookup(session)
    inject_product_web_search(session)
    inject_product_quiz(session)

    # 20. product dados inválidos -> bloqueado
    step(
        "20. document(product) dados inválidos -> bloqueado",
        expect_success=False,
        result_str=core._execute_document(
            {"type": "product", "title": "Product Inválido", "data": PRODUCT_INVALID}
        ),
        expect_in_error=E_PRODUCT_INVALID,
    )

    # 21. document(product) -> SUCESSO
    _product_str = core._execute_document(
        {"type": "product", "title": "Product MD70", "data": PRODUCT_DATA}
    )
    step(
        "21. document(product) -> SUCESSO", expect_success=True, result_str=_product_str
    )
    try:
        product_document_id = json.loads(_product_str).get("id")
        print(f"     product_document_id: {product_document_id}")
    except Exception:
        pass

    # ── FASE 4: COPYWRITING (SLAP + PAS) ─────────────────────────────────────
    print(f"\n{SEP}\n  FASE 4: COPYWRITING (SLAP + PAS)\n{SEP}")

    # 22. sem lookup -> bloqueado
    step(
        "22. document(copywriting) sem lookup -> bloqueado",
        expect_success=False,
        result_str=core._execute_document(
            {"type": "copywriting", "title": "Copy sem lookup", "data": COPY_SLAP}
        ),
        expect_in_error=E_COPY_NO_LOOKUP,
    )

    # Injetar lookup SkillCopywriting.md
    print(f"\n  [INFO] [22b] Injetando lookup(file=SkillCopywriting.md)")
    inject_copywriting_lookups(session)

    # 23. sem quiz -> bloqueado
    step(
        "23. document(copywriting) sem quiz -> bloqueado",
        expect_success=False,
        result_str=core._execute_document(
            {"type": "copywriting", "title": "Copy sem quiz", "data": COPY_SLAP}
        ),
        expect_in_error=E_COPY_NO_QUIZ,
    )

    # Injetar quiz de copywriting
    print(f"\n  [INFO] [23b] Injetando quiz de copywriting")
    inject_copywriting_quiz(session)

    # 24. sem tasks -> bloqueado
    step(
        "24. document(copywriting) sem tasks -> bloqueado",
        expect_success=False,
        result_str=core._execute_document(
            {"type": "copywriting", "title": "Copy sem tasks", "data": COPY_SLAP}
        ),
        expect_in_error=E_COPY_NO_TASKS,
    )

    # Injetar tasks (2 postagens)
    print(f"\n  [INFO] [24b] Injetando 2 tasks de postagens")
    inject_copywriting_tasks(session)

    # 25. document(copywriting SLAP) -> SUCESSO
    _slap_str = core._execute_document(
        {"type": "copywriting", "title": "Copy SLAP MD70", "data": COPY_SLAP}
    )
    step(
        "25. document(copywriting SLAP) -> SUCESSO",
        expect_success=True,
        result_str=_slap_str,
    )
    try:
        slap_id = json.loads(_slap_str).get("id")
        if slap_id:
            copy_doc_ids["SLAP"] = slap_id
            print(f"     SLAP_document_id: {slap_id}")
    except Exception:
        pass

    # 26. document(copywriting PAS) -> SUCESSO
    inject_copywriting_lookups(session)
    _pas_str = core._execute_document(
        {"type": "copywriting", "title": "Copy PAS MD70", "data": COPY_PAS}
    )
    step(
        "26. document(copywriting PAS) -> SUCESSO",
        expect_success=True,
        result_str=_pas_str,
    )
    try:
        pas_id = json.loads(_pas_str).get("id")
        if pas_id:
            copy_doc_ids["PAS"] = pas_id
            print(f"     PAS_document_id: {pas_id}")
    except Exception:
        pass

    # 27. dados inválidos -> bloqueado
    inject_copywriting_lookups(session)
    step(
        "27. document(copywriting) dados inválidos -> bloqueado",
        expect_success=False,
        result_str=core._execute_document(
            {"type": "copywriting", "title": "Copy Inválido", "data": COPY_INVALID}
        ),
        expect_in_error=E_COPY_INVALID,
    )

    # ── FASE 5: ASSET GENERATION (SLAP + PAS) ────────────────────────────────
    print(f"\n{SEP}\n  FASE 5: ASSET GENERATION (SLAP + PAS)\n{SEP}")

    available_ids = [copy_doc_ids[k] for k in ["SLAP", "PAS"] if k in copy_doc_ids]

    # 28. asset simultâneo SLAP + PAS
    if len(available_ids) >= 2:
        _multi = json.loads(core._execute_asset({"document_ids": available_ids}))
        _assets_valid = all(
            _ga.get("asset_url") and _ga.get("caption") and _ga.get("minicopy")
            for _proc in _multi.get("processed", [])
            for _ga in _proc.get("result", {}).get("generated_assets", [])
        )
        _multi_ok = (
            _multi.get("success", False)
            and _multi.get("total_documents") == len(available_ids)
            and len(_multi.get("processed", [])) == len(available_ids)
            and len(_multi.get("errors", [])) == 0
            and _assets_valid
        )
        results.append(
            {
                "label": "28. asset(document_ids=[SLAP, PAS]) -> 2 processados",
                "passed": _multi_ok,
                "result": _multi,
            }
        )
        _icon = "[OK]" if _multi_ok else "[FAIL]"
        print(
            f"\n{SEP2}\n{_icon}  28. asset(document_ids=[SLAP, PAS]) -> 2 processados"
        )
        print(
            f"     success={_multi.get('success')}  total={_multi.get('total_documents')}  processed={len(_multi.get('processed',[]))}  errors={len(_multi.get('errors',[]))}  assets_valid={_assets_valid}"
        )
    else:
        print(f"\n  [WARN] [28] Pulado — documentos insuficientes")

    # 29. asset misto: SLAP (válido) + canvas_id (não-copywriting)
    slap_id = copy_doc_ids.get("SLAP")
    if slap_id and canvas_document_id:
        _mixed = json.loads(
            core._execute_asset({"document_ids": [slap_id, canvas_document_id]})
        )
        _canvas_rej = any(
            e.get("document_id") == canvas_document_id for e in _mixed.get("errors", [])
        )
        _slap_proc = any(
            p.get("document_id") == slap_id for p in _mixed.get("processed", [])
        )
        _mixed_ok = _canvas_rej and _slap_proc
        results.append(
            {
                "label": "29. asset([slap, canvas_id]) -> canvas rejeitado, slap processado",
                "passed": _mixed_ok,
                "result": _mixed,
            }
        )
        _icon = "[OK]" if _mixed_ok else "[FAIL]"
        print(
            f"\n{SEP2}\n{_icon}  29. asset([slap, canvas_id]) -> canvas rejeitado, slap processado"
        )
        print(f"     canvas_rejected={_canvas_rej}  slap_processed={_slap_proc}")
    else:
        print(f"\n  [WARN] [29] Pulado — IDs não disponíveis")

    # 30. asset sem document_id -> bloqueado
    step(
        "30. asset() sem document_id -> bloqueado",
        expect_success=False,
        result_str=core._execute_asset({}),
        expect_in_error=E_ASSET_NO_DOC,
    )

    # 31-32. asset sequencial (SLAP + PAS) — verifica doc.status=done
    seq_step = 31
    session2 = get_session()
    for fw_name, doc_id in copy_doc_ids.items():
        _seq = json.loads(core._execute_asset({"document_id": doc_id}))
        _doc_row = session2.execute(
            text("SELECT content FROM documents WHERE document_id = :did"),
            {"did": doc_id},
        ).first()
        _doc_status_done = False
        if _doc_row:
            try:
                _doc_status_done = json.loads(_doc_row[0]).get("status") == "done"
            except Exception:
                pass
        _seq_ok = (
            _seq.get("success", False)
            and _seq.get("total_documents") == 1
            and len(_seq.get("processed", [])) == 1
            and _doc_status_done
        )
        results.append(
            {
                "label": f"{seq_step}. asset({fw_name}) sequencial -> SUCESSO + status=done",
                "passed": _seq_ok,
                "result": _seq,
            }
        )
        _icon = "[OK]" if _seq_ok else "[FAIL]"
        print(
            f"\n{SEP2}\n{_icon}  {seq_step}. asset({fw_name}) sequencial -> SUCESSO + status=done"
        )
        print(
            f"     success={_seq.get('success')}  processed={len(_seq.get('processed',[]))}  doc_status_done={_doc_status_done}"
        )
        seq_step += 1
    session2.close()

    # ── FASE 6: VALIDAÇÃO DE COMPOSIÇÃO ──────────────────────────────────────
    print(f"\n{SEP}\n  FASE 6: VALIDAÇÃO DE COMPOSIÇÃO (Assets.py + Core.py)\n{SEP}")

    step(
        "F6-1. bg=black_white -> injeta 'black and white' + monochromatic",
        expect_success=True,
        result_str=check_bg_type_injection(
            "black_white", ["black and white", "monochromatic"]
        ),
    )

    step(
        "F6-2. bg=product_closeup -> injeta 'shallow depth' + 'sharp focus'",
        expect_success=True,
        result_str=check_bg_type_injection(
            "product_closeup", ["shallow depth", "sharp focus"]
        ),
    )

    step(
        "F6-3. angle=HyperCloseUpShot -> injeta 'hyper close-up' + 'micro-detail'",
        expect_success=True,
        result_str=check_framing_directive(
            "HyperCloseUpShot", ["hyper close-up", "micro-detail"]
        ),
    )

    step(
        "F6-4. angle=CloseUpShot -> injeta 'close-up' + 'blurred'",
        expect_success=True,
        result_str=check_framing_directive("CloseUpShot", ["close-up", "blurred"]),
    )

    inject_copywriting_lookups(session)
    step(
        "F6-5. bg=window + MidBodyShot (HRP) -> bloqueado (exige closeup)",
        expect_success=False,
        result_str=core._execute_document(
            {
                "type": "copywriting",
                "title": "BG-angle-invalid-1",
                "data": _make_bg_angle_copy("window", "MidBodyShot"),
            }
        ),
        expect_in_error=E_COPY_ANGLE_INVALID,
    )

    inject_copywriting_lookups(session)
    step(
        "F6-6. bg=color + EyeLevelShot (HRP) -> bloqueado (exige closeup)",
        expect_success=False,
        result_str=core._execute_document(
            {
                "type": "copywriting",
                "title": "BG-angle-invalid-2",
                "data": _make_bg_angle_copy("color", "EyeLevelShot"),
            }
        ),
        expect_in_error=E_COPY_ANGLE_INVALID,
    )

    inject_copywriting_lookups(session)
    _hyper_no_main = _make_bg_angle_copy("window", "HyperCloseUpShot")
    _hyper_no_main["assets"][0]["prompt"]["composition"].pop("main_object", None)
    step(
        "F6-7a. HyperCloseUpShot sem main_object -> bloqueado",
        expect_success=False,
        result_str=core._execute_document(
            {
                "type": "copywriting",
                "title": "BG-no-main-object",
                "data": _hyper_no_main,
            }
        ),
        expect_in_error=E_COPY_NO_MAIN_OBJ,
    )

    inject_copywriting_lookups(session)
    step(
        "F6-7b. bg=window + HyperCloseUpShot (HRP) -> aceito",
        expect_success=True,
        result_str=core._execute_document(
            {
                "type": "copywriting",
                "title": "BG-angle-valid-1",
                "data": _make_bg_angle_copy("window", "HyperCloseUpShot"),
            }
        ),
    )

    inject_copywriting_lookups(session)
    step(
        "F6-8. bg=color + CloseUpShot (HRP=false) -> aceito",
        expect_success=True,
        result_str=core._execute_document(
            {
                "type": "copywriting",
                "title": "BG-angle-valid-2",
                "data": _make_bg_angle_copy("color", "CloseUpShot", hrp=False),
            }
        ),
    )

    inject_copywriting_lookups(session)
    _copy_no_archetype = {k: v for k, v in COPY_SLAP.items() if k != "archetype"}
    step(
        "F6-9. copywriting sem archetype -> bloqueado",
        expect_success=False,
        result_str=core._execute_document(
            {
                "type": "copywriting",
                "title": "Copy sem archetype",
                "data": _copy_no_archetype,
            }
        ),
        expect_in_error=E_COPY_NO_ARCHETYPE,
    )

    inject_copywriting_lookups(session)
    _copy_no_moodboard = {k: v for k, v in COPY_SLAP.items() if k != "moodboard"}
    step(
        "F6-10. copywriting sem moodboard -> bloqueado",
        expect_success=False,
        result_str=core._execute_document(
            {
                "type": "copywriting",
                "title": "Copy sem moodboard",
                "data": _copy_no_moodboard,
            }
        ),
        expect_in_error=E_COPY_NO_MOODBOARD,
    )

    print(f"\n  [INFO] Testando novos ângulos de composição...")
    for fw_name, fw_data in NEW_COMPOSITION_FRAMEWORKS:
        inject_copywriting_lookups(session)
        _r = core._execute_document(
            {"type": "copywriting", "title": f"Copy {fw_name}", "data": fw_data}
        )
        step(
            f"F6-11-{fw_name}. document(copywriting {fw_name}) -> aceito",
            expect_success=True,
            result_str=_r,
        )
        try:
            doc_id = json.loads(_r).get("id")
            if doc_id:
                print(f"     {fw_name}_document_id: {doc_id}")
        except Exception:
            pass

    # ── FASE 7: GATE SYSTEM + PARTIAL DOCUMENT ────────────────────────────────
    print(f"\n{SEP}\n  FASE 7: GATE SYSTEM + PARTIAL DOCUMENT\n{SEP}")

    # F7-1 & F7-2: Gate — doc completo pendente bloqueia outras tools
    # Simula o estado logo após document(copywriting) → sucesso, asset() ainda não chamado
    _slap_pending_id = copy_doc_ids.get("SLAP", str(uuid.uuid4()))
    core7 = make_core(session, user_id)
    core7._pending_document_id = _slap_pending_id
    core7._pending_document_partial = False

    step(
        "F7-1. gate: doc completo pendente + quiz → bloqueado",
        expect_success=False,
        result_str=core7.execute_tool(
            "quiz",
            json.dumps(
                {"quiz": [{"question": "Q?", "options": ["A"], "type": "validação"}]}
            ),
            AGENT_ID,
        ),
        expect_in_error=E_GATE_PENDING_DOC,
    )

    step(
        "F7-2. gate: doc completo pendente + document(brand_comm) → bloqueado",
        expect_success=False,
        result_str=core7.execute_tool(
            "document",
            json.dumps(
                {"type": "brand_communication", "title": "test", "data": BRAND_DATA}
            ),
            AGENT_ID,
        ),
        expect_in_error=E_GATE_PENDING_DOC,
    )

    # F7-3: Salvar documento parcial (variation.count=2, só variation_1)
    # Usa fresh core sem pendências; os pre-requisitos do CHAT_ID ainda são válidos
    core7b = make_core(session, user_id)
    inject_copywriting_lookups(session)

    _partial_str = core7b._execute_document(
        {
            "type": "copywriting",
            "title": "Copy Parcial Gatilhos",
            "data": _COPY_PARTIAL_BASE,
        }
    )
    step(
        "F7-3. document parcial (variation.count=2, só variation_1) → success=false, status=partial",
        expect_success=False,
        result_str=_partial_str,
        expect_in_error=["partial", "variation_2"],
    )
    _partial_r = json.loads(_partial_str)
    _partial_doc_id = _partial_r.get("next_action", {}).get("document_id")
    print(f"     partial_doc_id: {_partial_doc_id}")
    print(f"     missing_variations: {_partial_r.get('missing_variations')}")

    # F7-4: Gate parcial + asset() bloqueado
    step(
        "F7-4. gate: doc parcial pendente + asset() → bloqueado",
        expect_success=False,
        result_str=core7b.execute_tool(
            "asset",
            json.dumps({"document_id": _partial_doc_id or "fake-id"}),
            AGENT_ID,
        ),
        expect_in_error=E_GATE_PARTIAL_DOC,
    )

    # F7-5: Gate parcial + quiz bloqueado (document() passa, mas quiz não)
    step(
        "F7-5. gate: doc parcial pendente + quiz → bloqueado",
        expect_success=False,
        result_str=core7b.execute_tool(
            "quiz",
            json.dumps(
                {"quiz": [{"question": "Q?", "options": ["A"], "type": "validação"}]}
            ),
            AGENT_ID,
        ),
        expect_in_error=E_GATE_PARTIAL_DOC,
    )

    # F7-6: Continuação — enviar variation_2 via document(document_id=...) → completo
    # O agente deve reenviar o documento completo + variation_2; merge sobrescreve apenas variation_N novos
    inject_copywriting_lookups(session)
    _complete_str = core7b._execute_document(
        {
            "document_id": _partial_doc_id,
            "type": "copywriting",
            "title": "Copy Parcial Gatilhos",
            "data": _COPY_PARTIAL_COMPLETE,
        }
    )
    step(
        "F7-6. continuação: document(document_id=..., data completo+variation_2) → success=true",
        expect_success=True,
        result_str=_complete_str,
    )
    _complete_r = json.loads(_complete_str)
    print(
        f"     missing_variations após merge: {_complete_r.get('missing_variations', [])}"
    )

    # F7-7: Após conclusão — _pending_document_partial limpado, doc gate ativo para asset()
    _partial_flag_cleared = not getattr(core7b, "_pending_document_partial", True)
    _doc_gate_set = getattr(core7b, "_pending_document_id", None) == _partial_doc_id
    _f77_ok = _partial_flag_cleared and _doc_gate_set
    results.append(
        {
            "label": "F7-7. após conclusão: partial=False, pending_document_id mantido para asset()",
            "passed": _f77_ok,
            "result": {
                "pending_partial": getattr(core7b, "_pending_document_partial", "?"),
                "pending_doc_id": getattr(core7b, "_pending_document_id", "?"),
            },
        }
    )
    _icon = "[OK]" if _f77_ok else "[FAIL]"
    print(f"\n{SEP2}")
    print(f"{_icon}  F7-7. após conclusão: partial=False, pending_document_id mantido")
    print(
        f"     pending_partial={getattr(core7b, '_pending_document_partial', '?')}  "
        f"pending_doc_id={getattr(core7b, '_pending_document_id', '?')}"
    )

    # ── FASE 8: VERIFICAÇÃO DE CRÉDITOS ──────────────────────────────────────
    print(f"\n{SEP}\n  FASE 8: VERIFICAÇÃO DE CRÉDITOS\n{SEP}")

    if _partial_doc_id:
        session_cr = get_session()
        credits_before = get_user_credits(session_cr, user_id)
        session_cr.close()
        print(f"\n  [INFO] Créditos antes da geração: {credits_before:.6f}")

        _cr_asset_str = core7b._execute_asset({"document_id": _partial_doc_id})
        _cr_asset = json.loads(_cr_asset_str)

        _proc_result = (
            _cr_asset.get("processed", [{}])[0].get("result", {})
            if _cr_asset.get("processed")
            else {}
        )
        _credits_consumed = _proc_result.get("credits_consumed", -1.0)
        _credits_remaining = _proc_result.get("credits_remaining", -1.0)

        # F8-1: resposta contém credits_consumed e credits_remaining
        _fields_ok = (
            isinstance(_credits_consumed, (int, float))
            and _credits_consumed >= 0
            and isinstance(_credits_remaining, (int, float))
            and _credits_remaining >= 0
        )
        results.append(
            {
                "label": "F8-1. resposta asset() contém credits_consumed e credits_remaining ≥ 0",
                "passed": _fields_ok,
                "result": {
                    "credits_consumed": _credits_consumed,
                    "credits_remaining": _credits_remaining,
                },
            }
        )
        _icon = "[OK]" if _fields_ok else "[FAIL]"
        print(f"\n{SEP2}")
        print(
            f"{_icon}  F8-1. resposta asset() contém credits_consumed e credits_remaining"
        )
        print(
            f"     credits_consumed={_credits_consumed}  credits_remaining={_credits_remaining}"
        )

        # F8-2: saldo no DB foi debitado
        session_cr2 = get_session()
        credits_after = get_user_credits(session_cr2, user_id)
        session_cr2.close()
        _db_deducted = credits_after < credits_before
        _db_diff = credits_before - credits_after
        results.append(
            {
                "label": "F8-2. créditos deduzidos do DB após geração de assets",
                "passed": _db_deducted,
                "result": {
                    "credits_before": credits_before,
                    "credits_after": credits_after,
                    "db_diff": _db_diff,
                    "response_consumed": _credits_consumed,
                },
            }
        )
        _icon = "[OK]" if _db_deducted else "[FAIL]"
        print(f"\n{SEP2}")
        print(f"{_icon}  F8-2. créditos deduzidos do DB após geração de assets")
        print(
            f"     before={credits_before:.6f}  after={credits_after:.6f}  diff={_db_diff:.6f}"
        )

        # F8-3: credits_remaining na resposta bate com saldo no DB (tolerância 0.001)
        _remaining_matches = (
            isinstance(_credits_remaining, (int, float))
            and abs(_credits_remaining - credits_after) < 0.001
        )
        results.append(
            {
                "label": "F8-3. credits_remaining na resposta ≈ saldo no DB (±0.001)",
                "passed": _remaining_matches,
                "result": {
                    "response_remaining": _credits_remaining,
                    "db_after": credits_after,
                    "delta": abs(_credits_remaining - credits_after)
                    if isinstance(_credits_remaining, (int, float))
                    else "N/A",
                },
            }
        )
        _icon = "[OK]" if _remaining_matches else "[FAIL]"
        print(f"\n{SEP2}")
        print(f"{_icon}  F8-3. credits_remaining na resposta ≈ saldo no DB")
        print(
            f"     response={_credits_remaining:.6f}  db={credits_after:.6f}  "
            f"delta={abs(_credits_remaining - credits_after):.8f}"
            if isinstance(_credits_remaining, (int, float))
            else f"     response={_credits_remaining}  db={credits_after:.6f}"
        )
    else:
        print(f"\n  [WARN] [F8] Pulado — partial_doc_id não disponível (F7-3 falhou)")

    # ── FASE C: CHAT CONNECTIONS ──────────────────────────────────────────────
    run_connections_test(session, user_id)

    # ── FASE S: SCHEDULER ────────────────────────────────────────────────────
    run_scheduler_test(user_id)

    # ── FASE T: TRIGGERS / WEBHOOKS ──────────────────────────────────────────
    run_triggers_test(user_id)

    session.close()


# ══════════════════════════════════════════════════════════════════════════════
# FASE C — CHAT CONNECTIONS
# Valida que connections bloqueia/libera MCPs por chat no Core.execute_tool()
# ══════════════════════════════════════════════════════════════════════════════


def run_connections_test(session, user_id: str):
    from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
    from App.Features.Tools.Core import Core

    print(f"\n{SEP}\n  FASE C: CHAT CONNECTIONS\n{SEP}")

    CONN_CHAT_ID = f"sim-conn-{str(uuid.uuid4())[:8]}"
    FAKE_PROVIDER = "test-mcp-provider"

    session.execute(
        text(
            """INSERT INTO chats (chat_id, user_id, chat_name, connections, status, created_at, updated_at)
               VALUES (:cid, :uid, :name, NULL, 'active', :now, :now)"""
        ),
        {
            "cid": CONN_CHAT_ID,
            "uid": user_id,
            "name": "[SIM] connections test",
            "now": datetime.utcnow().isoformat(),
        },
    )
    session.commit()

    class _LiveDB:
        def get_session(self_inner):
            return session

    conn_core = Core(db_manager=_LiveDB())

    db = DatabaseManager()

    # C1. connections=NULL → provider NÃO bloqueado por connections
    result_c1 = conn_core.execute_tool(
        f"mcp__{FAKE_PROVIDER}__test_action",
        "{}",
        chat_id=CONN_CHAT_ID,
        user_id=user_id,
    )
    blocked_c1 = "não está ativa neste chat" in result_c1.lower()
    step(
        f"C1. connections=NULL → mcp__{FAKE_PROVIDER} NÃO bloqueado por connections",
        expect_success=True,
        result_str=json.dumps({"success": not blocked_c1, "detail": result_c1[:200]}),
    )

    # C2. connections exclui provider → BLOQUEADO
    db.execute_query(
        "UPDATE chats SET connections = :conn WHERE chat_id = :cid",
        {"conn": json.dumps(["other-provider"]), "cid": CONN_CHAT_ID},
    )
    result_c2 = conn_core.execute_tool(
        f"mcp__{FAKE_PROVIDER}__test_action",
        "{}",
        chat_id=CONN_CHAT_ID,
        user_id=user_id,
    )
    blocked_c2 = "não está ativa neste chat" in result_c2.lower()
    step(
        f"C2. connections exclui provider → mcp__{FAKE_PROVIDER} BLOQUEADO",
        expect_success=True,
        result_str=json.dumps({"success": blocked_c2, "detail": result_c2[:200]}),
    )

    # C3. connections inclui provider → NÃO bloqueado por connections
    db.execute_query(
        "UPDATE chats SET connections = :conn WHERE chat_id = :cid",
        {"conn": json.dumps(["other-provider", FAKE_PROVIDER]), "cid": CONN_CHAT_ID},
    )
    result_c3 = conn_core.execute_tool(
        f"mcp__{FAKE_PROVIDER}__test_action",
        "{}",
        chat_id=CONN_CHAT_ID,
        user_id=user_id,
    )
    blocked_c3 = "não está ativa neste chat" in result_c3.lower()
    step(
        f"C3. connections inclui provider → mcp__{FAKE_PROVIDER} NÃO bloqueado por connections",
        expect_success=True,
        result_str=json.dumps({"success": not blocked_c3, "detail": result_c3[:200]}),
    )

    # Cleanup do chat de teste
    session.execute(
        text("DELETE FROM chats WHERE chat_id = :cid"), {"cid": CONN_CHAT_ID}
    )
    session.commit()
    print(f"\n  [CLEAN] Chat {CONN_CHAT_ID} removido.")


# ══════════════════════════════════════════════════════════════════════════════
# FASE S — SCHEDULER
# Cria scheduled task vencida via DB, dispara via HTTP /api/scheduler/trigger e valida:
#   S1. task_execution criada (status running)
#   S2. chat "Agendamento: <nome>" criado
#   S3. connections do chat bate com integrations da task
#   S4. next_execution_at avançou para o futuro
#   S5. agente processou o prompt "oi" e respondeu (mensagem assistant no chat)
# ══════════════════════════════════════════════════════════════════════════════

_TRIGGER_URL = "http://localhost:4001/api/scheduler/trigger"
_POLL_INTERVAL_S = 3
_POLL_TIMEOUT_S = 45


def _http_trigger(dev_bypass_key: str) -> tuple[bool, str]:
    """POST /api/scheduler/trigger. Retorna (ok, erro)."""
    import urllib.request, urllib.error

    req = urllib.request.Request(
        _TRIGGER_URL,
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "X-Dev-Bypass-Key": dev_bypass_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200, ""
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()}"
    except Exception as e:
        return False, str(e)


def _poll_assistant_message(
    db, chat_id: str, timeout: int = _POLL_TIMEOUT_S
) -> dict | None:
    """Aguarda até `timeout` segundos por uma mensagem message_type='assistant' no chat."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        row = db.fetch_one(
            "SELECT message_id, content FROM messages WHERE chat_id = :cid AND message_type = 'assistant' LIMIT 1",
            {"cid": chat_id},
        )
        if row:
            return row
        time.sleep(_POLL_INTERVAL_S)
    return None


def run_scheduler_test(user_id: str):
    from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
    from App.Core.Settings.Settings import GLOBAL_CONFIG

    print(f"\n{SEP}\n  FASE S: SCHEDULER\n{SEP}")

    dev_key = GLOBAL_CONFIG.get("dev_bypass_key", "") or os.environ.get(
        "DEV_BYPASS_KEY", ""
    )
    if not dev_key:
        print(
            "  [WARN] DEV_BYPASS_KEY não configurado — trigger via HTTP indisponível, S5 pulado"
        )

    TASK_ID = str(uuid.uuid4())
    TASK_NAME = f"[SIM] Scheduler Test {TASK_ID[:8]}"
    TASK_INTEGRATIONS = ["meta-ads", "google-drive"]
    TASK_PROMPT = "oi"

    db = DatabaseManager()
    now = datetime.utcnow()
    past_time = (now - timedelta(seconds=10)).isoformat()

    db.execute_query(
        """INSERT INTO scheduled_tasks
               (id, user_id, name, cron_expression, prompt, integrations,
                status, next_execution_at, created_at, updated_at)
           VALUES (:id, :uid, :name, :cron, :prompt, :integrations,
                   'active', :next_exec, :now, :now)""",
        {
            "id": TASK_ID,
            "uid": user_id,
            "name": TASK_NAME,
            "cron": "* * * * *",
            "prompt": TASK_PROMPT,
            "integrations": json.dumps(TASK_INTEGRATIONS),
            "next_exec": past_time,
            "now": now.isoformat(),
        },
    )
    print(
        f"\n  [INFO] Task criada: '{TASK_NAME}' (id={TASK_ID}, prompt='{TASK_PROMPT}')"
    )
    print(f"  [INFO] next_execution_at: {past_time} (passado — due imediatamente)")

    # Disparo via HTTP para que o servidor vivo (com queue_manager) processe
    if dev_key:
        print(f"  [INFO] Chamando POST {_TRIGGER_URL}...")
        ok, err = _http_trigger(dev_key)
        if ok:
            print("  [INFO] Trigger HTTP: 200 OK")
        else:
            print(
                f"  [WARN] Trigger HTTP falhou: {err} — usando process_scheduled_tasks() direto"
            )
            from App.Core.Scheduler.SchedulerManager import process_scheduled_tasks

            process_scheduled_tasks()
    else:
        print(
            "  [INFO] Chamando process_scheduled_tasks() diretamente (sem dev_key)..."
        )
        from App.Core.Scheduler.SchedulerManager import process_scheduled_tasks

        process_scheduled_tasks()

    # S1. task_execution criada
    exec_row = db.fetch_one(
        "SELECT id, status FROM task_executions WHERE task_id = :tid",
        {"tid": TASK_ID},
    )
    has_execution = exec_row is not None
    exec_status = exec_row.get("status", "?") if exec_row else "NOT FOUND"
    step(
        "S1. process_scheduled_tasks() cria task_execution para task vencida",
        expect_success=True,
        result_str=json.dumps({"success": has_execution, "status": exec_status}),
    )

    # S2. chat "Agendamento: <nome>" criado
    chat_row = db.fetch_one(
        "SELECT chat_id, connections FROM chats WHERE chat_name = :name",
        {"name": f"Agendamento: {TASK_NAME}"},
    )
    has_chat = chat_row is not None
    step(
        "S2. scheduler cria chat 'Agendamento: <nome>'",
        expect_success=True,
        result_str=json.dumps(
            {
                "success": has_chat,
                "chat_id": chat_row.get("chat_id") if chat_row else None,
                "connections": chat_row.get("connections") if chat_row else None,
            }
        ),
    )

    # S3. connections do chat bate com integrations da task
    if chat_row:
        raw_conn = chat_row.get("connections")
        got_connections = json.loads(raw_conn) if raw_conn else None
        connections_match = got_connections == TASK_INTEGRATIONS
        step(
            "S3. connections do chat bate com integrations da task",
            expect_success=True,
            result_str=json.dumps(
                {
                    "success": connections_match,
                    "expected": TASK_INTEGRATIONS,
                    "got": got_connections,
                }
            ),
        )
    else:
        print(f"\n  [WARN] [S3] Pulado — chat não criado (S2 falhou)")

    # S4. next_execution_at avançou
    task_row = db.fetch_one(
        "SELECT next_execution_at, last_executed_at FROM scheduled_tasks WHERE id = :tid",
        {"tid": TASK_ID},
    )
    if task_row:
        next_exec = task_row.get("next_execution_at", "")
        next_exec_updated = next_exec > now.isoformat()
        step(
            "S4. next_execution_at atualizado para próxima execução (futuro)",
            expect_success=True,
            result_str=json.dumps(
                {
                    "success": next_exec_updated,
                    "next_execution_at": next_exec,
                    "last_executed_at": task_row.get("last_executed_at"),
                }
            ),
        )

    # S5. agente respondeu ao prompt "oi" (mensagem assistant no chat do scheduler)
    sched_chat_id = chat_row.get("chat_id") if chat_row else None
    if sched_chat_id and dev_key:
        print(
            f"\n  [INFO] Aguardando resposta do agente em chat={sched_chat_id} (até {_POLL_TIMEOUT_S}s)..."
        )
        assistant_msg = _poll_assistant_message(db, sched_chat_id)
        has_response = assistant_msg is not None
        preview = (assistant_msg.get("content", "") or "")[:80] if assistant_msg else ""
        step(
            "S5. agente processou prompt 'oi' e respondeu (mensagem assistant no chat)",
            expect_success=True,
            result_str=json.dumps(
                {
                    "success": has_response,
                    "message_id": assistant_msg.get("message_id")
                    if assistant_msg
                    else None,
                    "preview": preview,
                }
            ),
        )
        # limpar mensagens do chat do scheduler
        if has_response:
            db.execute_query(
                "DELETE FROM messages WHERE chat_id = :cid", {"cid": sched_chat_id}
            )
    else:
        if not sched_chat_id:
            print(f"\n  [WARN] [S5] Pulado — chat não criado (S2 falhou)")
        else:
            print(
                f"\n  [WARN] [S5] Pulado — DEV_BYPASS_KEY não configurado (trigger HTTP indisponível)"
            )

    # Cleanup
    exec_row = db.fetch_one(
        "SELECT id FROM task_executions WHERE task_id = :tid", {"tid": TASK_ID}
    )
    if exec_row:
        db.execute_query(
            "DELETE FROM task_executions WHERE task_id = :tid", {"tid": TASK_ID}
        )
    if chat_row:
        db.execute_query(
            "DELETE FROM messages WHERE chat_id = :cid", {"cid": chat_row["chat_id"]}
        )
        db.execute_query(
            "DELETE FROM chats WHERE chat_id = :cid", {"cid": chat_row["chat_id"]}
        )
    db.execute_query("DELETE FROM scheduled_tasks WHERE id = :tid", {"tid": TASK_ID})
    print(f"\n  [CLEAN] Scheduler test: task '{TASK_NAME}' e artefatos removidos.")


# ══════════════════════════════════════════════════════════════════════════════
# FASE T — TRIGGERS / WEBHOOKS
# Delega para o módulo dedicado TriggersValidation/test_triggers_flow.py,
# reutilizando o mesmo DB e dev_key já disponíveis neste contexto.
# ══════════════════════════════════════════════════════════════════════════════


def run_triggers_test(user_id: str):
    from App.Core.Settings.Settings import GLOBAL_CONFIG

    dev_key = GLOBAL_CONFIG.get("dev_bypass_key", "") or os.environ.get(
        "DEV_BYPASS_KEY", ""
    )

    try:
        from Scripts.Tests.TriggersValidation.test_triggers_flow import (
            run_triggers_test as _run,
        )

        _run(user_id, dev_key)
    except Exception as exc:
        print(f"\n  [WARN] [T] Fase Triggers falhou com exceção: {exc}")


def cleanup():
    from App.Core.Crunch.TablesSQL.Models import IsolatedChat, IsolatedMessage, Chat

    session = get_session()
    ic = session.query(IsolatedChat).filter(IsolatedChat.chat_id == CHAT_ID).first()
    if ic:
        session.query(IsolatedMessage).filter(
            IsolatedMessage.isolated_chat_id.in_([CHAT_ID, str(ic.id)])
        ).delete(synchronize_session=False)
        session.delete(ic)
    chat = session.query(Chat).filter(Chat.chat_id == CHAT_ID).first()
    if chat:
        session.delete(chat)
    session.commit()
    session.close()
    print(f"\n  [CLEAN] Cleanup: chat {CHAT_ID} removido.")


if __name__ == "__main__":
    run()

    print(f"\n{SEP}\nRESULTADO FINAL\n{SEP}")
    all_pass = True
    for r in results:
        icon = "[OK]" if r["passed"] else "[FAIL]"
        print(f"  {icon}  {r['label']}")
        if not r["passed"]:
            all_pass = False

    print(f"\n  Outputs em: {OUTPUT_DIR}\n")

    if CLEANUP:
        cleanup()

    sys.exit(0 if all_pass else 1)
