"""Provider Meta Ads para MCP nativo."""
from typing import Dict, Any, List, Optional
import json
import httpx

from App.Core.Logs import debug

TOOL_DEFINITIONS: List[Dict] = [
    {
        "name": "mcp__meta-ads__list_campaigns",
        "description": "[META-ADS] Lista campanhas da conta de anúncios Meta (Facebook/Instagram Ads).",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filtrar por status: ACTIVE, PAUSED, DELETED (opcional)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Máximo de resultados. OBRIGATÓRIO — passe 100 por padrão.",
                },
            },
            "required": ["limit"],
        },
    },
    {
        "name": "mcp__meta-ads__get_campaign_insights",
        "description": "[META-ADS] Obtém métricas de desempenho de uma campanha Meta.",
        "parameters": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string", "description": "ID da campanha"},
                "date_preset": {
                    "type": "string",
                    "description": "Período: last_7d, last_30d, last_90d, this_month (padrão last_30d)",
                },
            },
            "required": ["campaign_id"],
        },
    },
    {
        "name": "mcp__meta-ads__create_campaign",
        "description": "[META-ADS] Cria uma nova campanha de anúncios Meta.",
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "ID da conta (ex: act_759233534882637). Se omitido usa a conta configurada.",
                },
                "name": {"type": "string", "description": "Nome da campanha"},
                "objective": {
                    "type": "string",
                    "description": "Objetivo: OUTCOME_AWARENESS, OUTCOME_TRAFFIC, OUTCOME_ENGAGEMENT, OUTCOME_LEADS, OUTCOME_SALES",
                },
                "status": {
                    "type": "string",
                    "description": "Status inicial: ACTIVE ou PAUSED (padrão PAUSED)",
                },
                "daily_budget": {
                    "type": "integer",
                    "description": "Orçamento diário em centavos (ex: 1000 = R$10,00)",
                },
                "special_ad_categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Categorias especiais de anúncio. Use [] para nenhuma, ou inclua: CREDIT, EMPLOYMENT, HOUSING, ISSUES_ELECTIONS_POLITICS",
                },
            },
            "required": ["name", "objective"],
        },
    },
    {
        "name": "mcp__meta-ads__create_ad_set",
        "description": (
            "[META-ADS] Cria um Ad Set dentro de uma campanha Meta com targeting e placements completos. "
            "Controla público (idade, gênero, geo, interesses, comportamentos, custom audiences), "
            "canais/posicionamentos (Facebook, Instagram, Messenger, Audience Network), "
            "dispositivos, orçamento, lance e otimização. "
            "\n\n"
            "=== COMBINAÇÃO VALIDADA (TESTADA E FUNCIONANDO EM 2026-06-24) ===\n"
            "Para campanhas OUTCOME_LEADS com CBO (daily_budget no nível da campanha):\n"
            "  optimization_goal=OFFSITE_CONVERSIONS (NUNCA LEAD_GENERATION para OUTCOME_LEADS)\n"
            "  billing_event=IMPRESSIONS\n"
            "  bid_strategy=LOWEST_COST_WITH_BID_CAP\n"
            "  bid_amount=5000 (= R$50,00 em centavos)\n"
            "  advantage_audience=0 (obrigatório desde API v19+; 0=manual, 1=Meta expande)\n"
            "  promoted_object={pixel_id: '870523582149794', custom_event_type: 'LEAD'}\n"
            "  SEM daily_budget no ad set (campanha CBO controla o orçamento)\n"
            "  targeting={age_min, age_max, genders, geo_locations, targeting_automation: {advantage_audience: 0}}\n"
            "IMPORTANTE: NÃO enviar daily_budget no ad set quando a campanha tem daily_budget (modo CBO).\n"
            "IMPORTANTE: LOWEST_COST_WITHOUT_CAP NÃO funciona nesta conta — use LOWEST_COST_WITH_BID_CAP.\n"
            "IMPORTANTE: LEAD_GENERATION é incompatível com OUTCOME_LEADS — use OFFSITE_CONVERSIONS + pixel.\n"
            "IMPORTANTE: advantage_audience é OBRIGATÓRIO — inclua sempre (0 ou 1).\n"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                # ── Identificação ────────────────────────────────────────────
                "account_id": {
                    "type": "string",
                    "description": "ID da conta (ex: act_759233534882637). Se omitido usa a conta configurada.",
                },
                "campaign_id": {
                    "type": "string",
                    "description": "ID da campanha pai",
                },
                "name": {"type": "string", "description": "Nome do ad set"},
                "status": {
                    "type": "string",
                    "description": "Status inicial: ACTIVE ou PAUSED (padrão PAUSED)",
                },
                # ── Orçamento ────────────────────────────────────────────────
                "daily_budget": {
                    "type": "integer",
                    "description": "Orçamento diário em centavos (ex: 1000 = R$10,00). Use daily_budget OU lifetime_budget.",
                },
                "lifetime_budget": {
                    "type": "integer",
                    "description": "Orçamento total da vigência em centavos. Requer end_time.",
                },
                "start_time": {
                    "type": "string",
                    "description": "Início ISO 8601 (ex: '2025-07-01T00:00:00-0300'). Opcional.",
                },
                "end_time": {
                    "type": "string",
                    "description": "Fim ISO 8601. Obrigatório se usar lifetime_budget.",
                },
                # ── Otimização e Lance ───────────────────────────────────────
                "optimization_goal": {
                    "type": "string",
                    "description": (
                        "Meta de otimização da entrega. Valores comuns: "
                        "REACH (alcance máximo), LINK_CLICKS (cliques no link), "
                        "LANDING_PAGE_VIEWS (visualizações de página), "
                        "IMPRESSIONS (impressões), "
                        "OFFSITE_CONVERSIONS (conversões via pixel em site externo — USE ESTE quando tiver pixel_id), "
                        "LEAD_GENERATION (formulário nativo do Facebook — NÃO usa pixel, requer lead_form_id; incompatível com pixel_id), "
                        "APP_INSTALLS (instalações de app), VIDEO_VIEWS (visualizações de vídeo), "
                        "QUALITY_LEAD (leads qualificados via pixel)."
                    ),
                },
                "billing_event": {
                    "type": "string",
                    "description": (
                        "Evento de cobrança: IMPRESSIONS (por mil impressões, padrão), "
                        "LINK_CLICKS (por clique), APP_INSTALLS (por instalação). "
                        "Nem todas as combinações com optimization_goal são válidas."
                    ),
                },
                "bid_strategy": {
                    "type": "string",
                    "description": (
                        "Estratégia de lance. "
                        "ATENÇÃO: nesta conta LOWEST_COST_WITHOUT_CAP NÃO funciona para campanhas CBO — use LOWEST_COST_WITH_BID_CAP. "
                        "Valores: "
                        "LOWEST_COST_WITH_BID_CAP (RECOMENDADO para campanhas CBO; requer bid_amount em centavos), "
                        "COST_CAP (custo médio máximo; requer bid_amount), "
                        "LOWEST_COST_WITHOUT_CAP (menor custo, sem limite — NÃO aceito nesta conta em modo CBO), "
                        "LOWEST_COST_WITH_MIN_ROAS (menor custo com ROAS mínimo)."
                    ),
                },
                "bid_amount": {
                    "type": "integer",
                    "description": "Valor máximo de lance em centavos. Requerido para LOWEST_COST_WITH_BID_CAP e COST_CAP.",
                },
                "pacing_type": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tipo de pacing: ['standard'] (distribuição uniforme, padrão) ou ['day_parting'] (programação por horário).",
                },
                "destination_type": {
                    "type": "string",
                    "description": (
                        "Destino dos cliques: WEBSITE, APP, MESSENGER, WHATSAPP, INSTAGRAM_DIRECT. "
                        "Padrão WEBSITE."
                    ),
                },
                # ── Público Advantage (OBRIGATÓRIO) ─────────────────────────
                "advantage_audience": {
                    "type": "integer",
                    "enum": [0, 1],
                    "description": "OBRIGATÓRIO. Público Advantage (targeting_automation): 0 = público manual (você controla o targeting — recomendado para anunciantes experientes), 1 = Meta expande automaticamente o público além do targeting definido. SEMPRE inclua este campo.",
                },
                # ── Público — Demográfico ────────────────────────────────────
                "age_min": {
                    "type": "integer",
                    "description": "Idade mínima (18–64). Padrão 18.",
                },
                "age_max": {
                    "type": "integer",
                    "description": "Idade máxima (18–65). 65 = 65+. Padrão 65.",
                },
                "genders": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Gêneros: [1] = masculino, [2] = feminino, [] ou omitido = todos.",
                },
                # ── Público — Localização ────────────────────────────────────
                "countries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Códigos ISO de países (ex: ['BR', 'PT']). Padrão ['BR'].",
                },
                "regions": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "Estados/regiões. Array de objetos {key: string}. "
                        "Ex: [{key:'3837'}] = São Paulo. Use mcp__meta-ads__search_targeting para obter keys."
                    ),
                },
                "cities": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "Cidades. Array de {key: string, radius: int (km), distance_unit: 'kilometer'}. "
                        "Ex: [{key:'1058277', radius:25, distance_unit:'kilometer'}] = São Paulo 25km."
                    ),
                },
                "location_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tipo de localização: home (mora lá), recent (esteve recente), travel_in (está viajando). Padrão: ['home','recent'].",
                },
                "locales": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "IDs de idioma para filtrar usuários. Ex: [5] = português (Brasil), [6] = português (Portugal).",
                },
                # ── Público — Interesses, Comportamentos, Dados Demo ─────────
                "interests": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "Interesses do Facebook. Array de {id: string, name: string}. "
                        "Ex: [{id:'6003139266461', name:'Empreendedorismo'}]. "
                        "Use mcp__meta-ads__search_targeting com type=interest para obter IDs."
                    ),
                },
                "behaviors": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "Comportamentos. Array de {id: string, name: string}. "
                        "Ex: compradores online, pequenos negócios, viajantes frequentes. "
                        "Use mcp__meta-ads__search_targeting com type=behavior para obter IDs."
                    ),
                },
                "education_statuses": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Nível de educação: 1=Ensino Médio, 2=Ensino Superior, 3=Pós-graduação.",
                },
                "relationship_statuses": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Estado civil: 1=Solteiro(a), 2=Em um relacionamento, 3=Casado(a), 4=Noivo(a), 6=Separado(a), 7=Divorciado(a), 8=Viúvo(a).",
                },
                "life_events": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Eventos de vida. Array de {id: string, name: string}. Ex: recém-casados, pais de recém-nascido.",
                },
                "flexible_spec": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "Targeting flexível (OR entre grupos, AND entre items do mesmo grupo). "
                        "Array de objetos, cada um com chaves como 'interests', 'behaviors'. "
                        "Ex: [{interests:[{id:'X'}]}, {behaviors:[{id:'Y'}]}] = interesses X OU comportamento Y."
                    ),
                },
                # ── Público — Custom Audiences ───────────────────────────────
                "custom_audiences": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "Custom audiences para incluir. Array de {id: string, name: string}. "
                        "Pode ser Lookalike Audience, Lista de clientes, Pixel audience, etc."
                    ),
                },
                "excluded_custom_audiences": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Custom audiences para excluir (ex: clientes atuais). Array de {id: string, name: string}.",
                },
                "exclusions": {
                    "type": "object",
                    "description": (
                        "Exclusões de interesses/comportamentos/dados demográficos. "
                        "Objeto com chaves interests, behaviors, demographics. "
                        "Ex: {interests: [{id:'X', name:'Y'}]}."
                    ),
                },
                # ── Dispositivos ─────────────────────────────────────────────
                "device_platforms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Dispositivos: ['mobile'], ['desktop'] ou ['mobile','desktop'] (padrão ambos).",
                },
                "user_os": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Sistema operacional: ['iOS'], ['Android'], ['iOS','Android']. Omitir = todos.",
                },
                "user_device": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Modelos específicos de dispositivo (ex: ['iPhone_8', 'Samsung_Galaxy_S21']). Raramente necessário.",
                },
                "wireless_carrier": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filtrar por operadora: ['Wifi'] para apenas Wi-Fi. Omitir = todos.",
                },
                # ── Placements / Canais ──────────────────────────────────────
                "publisher_platforms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Plataformas onde o anúncio aparece: "
                        "facebook, instagram, audience_network, messenger. "
                        "Omitir = Meta seleciona automaticamente (Advantage+ Placements). "
                        "Ex: ['facebook','instagram'] = apenas FB e IG."
                    ),
                },
                "facebook_positions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Posicionamentos no Facebook (requer publisher_platforms incluindo 'facebook'): "
                        "feed (feed principal), right_hand_column (coluna direita, só desktop), "
                        "marketplace (marketplace), video_feeds (feed de vídeos), "
                        "story (stories), search (resultados de busca), "
                        "instream_video (mid-roll em vídeos), facebook_reels (Reels FB), "
                        "profile_feed (perfil do usuário)."
                    ),
                },
                "instagram_positions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Posicionamentos no Instagram (requer 'instagram' em publisher_platforms): "
                        "stream (feed), story (stories), explore (explorar), "
                        "explore_home (home de explorar), reels (Reels IG), "
                        "igtv (IGTV), ig_search (busca IG), profile_feed (perfil)."
                    ),
                },
                "audience_network_positions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Posicionamentos na Audience Network (requer 'audience_network'): "
                        "classic (banner/interstitial em apps parceiros), "
                        "rewarded_video (vídeo recompensado em games/apps)."
                    ),
                },
                "messenger_positions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Posicionamentos no Messenger (requer 'messenger'): "
                        "messenger_home (inbox do Messenger), story (stories do Messenger), "
                        "sponsored_messages (mensagens patrocinadas para conversas ativas)."
                    ),
                },
                # ── Pixel / Evento de Conversão ──────────────────────────────
                "pixel_id": {
                    "type": "string",
                    "description": "ID do Meta Pixel para rastreamento de conversões. Requerido quando optimization_goal=CONVERSIONS ou OFFSITE_CONVERSIONS.",
                },
                "custom_event_type": {
                    "type": "string",
                    "description": (
                        "Evento do pixel a otimizar: PURCHASE, LEAD, COMPLETE_REGISTRATION, "
                        "ADD_TO_CART, INITIATED_CHECKOUT, SEARCH, VIEW_CONTENT, ADD_PAYMENT_INFO, "
                        "CONTACT, FIND_LOCATION, SCHEDULE, START_TRIAL, SUBSCRIBE, OTHER."
                    ),
                },
            },
            "required": ["campaign_id", "name", "optimization_goal"],
        },
    },
    {
        "name": "mcp__meta-ads__upload_ad_image",
        "description": (
            "[META-ADS] Faz upload de uma imagem para a biblioteca da Meta e retorna um image_hash permanente. "
            "Use o hash em create_ad_creative (image_hash / image_hashes) — sem depender de URL pública ou túnel.\n\n"
            "DOIS MODOS:\n"
            "1. VIA BYTES (base64) — gere o base64 com terminal (`base64 -w0 /caminho/imagem.jpg`) "
            "e passe em `bytes`. Aceita JPG ou PNG — use terminal para converter se necessário "
            "(`convert imagem.webp imagem.jpg`).\n"
            "2. VIA URL — forneça `image_url` e a Meta baixa diretamente.\n\n"
            "O hash retornado é permanente e pode ser reutilizado em qualquer criativo futuro."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "ID da conta (ex: act_759233534882637). Se omitido usa a conta configurada.",
                },
                "bytes": {
                    "type": "string",
                    "description": "Imagem codificada em base64. Gere com terminal: `base64 -w0 /caminho/imagem.jpg`. Deve ser JPG ou PNG — converta antes se necessário: `convert imagem.webp imagem.jpg`.",
                },
                "image_url": {
                    "type": "string",
                    "description": "URL pública da imagem. A Meta baixa e armazena, retornando hash permanente.",
                },
                "filename": {
                    "type": "string",
                    "description": "Nome do arquivo na biblioteca da Meta (ex: 'criativo_A.jpg'). Opcional.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "mcp__meta-ads__create_ad_creative",
        "description": (
            "[META-ADS] Cria um criativo Meta Ads com copy, mídia e CTA. "
            "\n\n"
            "=== MODO PADRÃO: MULTI-ASSET com variações (USE SEMPRE) ===\n"
            "Use os campos PLURAIS para fornecer variações que a Meta rotaciona:\n"
            "  bodies      → lista de textos principais (até 5) ex: ['Texto A', 'Texto B']\n"
            "  titles      → lista de headlines (até 5) ex: ['Título 1', 'Título 2']\n"
            "  descriptions → lista de descrições (até 5) ex: ['Desc A', 'Desc B']\n"
            "  cta_types   → lista de botões CTA (até 5) ex: ['LEARN_MORE', 'SIGN_UP']\n"
            "  image_urls  → lista de imagens (até 10)\n"
            "SEMPRE forneça pelo menos 2-3 variações de bodies, titles e descriptions. "
            "SEMPRE defina cta_types — nunca deixe o CTA sem definir. "
            "Valores válidos de CTA: LEARN_MORE, SIGN_UP, SUBSCRIBE, CONTACT_US, "
            "GET_QUOTE, APPLY_NOW, DOWNLOAD, SHOP_NOW, BOOK_TRAVEL, WATCH_MORE, NO_BUTTON.\n"
            "\n"
            "=== MODO ÚNICO (use só se quiser controle absoluto de 1 combinação) ===\n"
            "Use body/title/description/call_to_action_type (singular) + image_url/video_id.\n"
            "\n"
            "Advantage+ OFF por padrão — a Meta não reescreve seu copy nem altera sua imagem."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                # ── Identificação ────────────────────────────────────────────
                "account_id": {
                    "type": "string",
                    "description": "ID da conta (ex: act_759233534882637). Se omitido usa a conta configurada.",
                },
                "name": {
                    "type": "string",
                    "description": "Nome interno do criativo (não aparece no anúncio)",
                },
                "page_id": {
                    "type": "string",
                    "description": "ID da Página do Facebook. O anúncio é publicado como esta página.",
                },
                "instagram_actor_id": {
                    "type": "string",
                    "description": "ID da conta do Instagram vinculada. Quando fornecido, o anúncio aparece como essa conta no IG. Se omitido, usa a identidade da Página.",
                },
                # ── Copy — Multi-asset PREFERIDO ─────────────────────────────
                "bodies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "PREFERIDO. Lista de textos principais (primary text) para rotacionar (até 5). "
                        "Ex: ['Você perde dinheiro todo mês sem saber por quê.', 'Sua loja vende mas não sobra nada?']. "
                        "A Meta mostra cada variação para públicos diferentes e aprende o que converte mais."
                    ),
                },
                "titles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "PREFERIDO. Lista de headlines/títulos para rotacionar (até 5). "
                        "Aparecem abaixo da imagem em destaque. "
                        "Ex: ['Diagnóstico gratuito do seu funil', 'Descubra onde você perde clientes']."
                    ),
                },
                "descriptions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "PREFERIDO. Lista de descrições do link para rotacionar (até 5). "
                        "Aparecem abaixo do título em alguns posicionamentos. "
                        "Ex: ['Análise completa em 5 minutos', 'Sem compromisso, 100% gratuito']."
                    ),
                },
                "cta_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "OBRIGATÓRIO no modo multi-asset. Lista de botões CTA (até 5). "
                        "SEMPRE defina pelo menos um. "
                        "Ex: ['LEARN_MORE'] ou ['LEARN_MORE', 'SIGN_UP']. "
                        "Valores: LEARN_MORE, SIGN_UP, SUBSCRIBE, CONTACT_US, GET_QUOTE, "
                        "APPLY_NOW, DOWNLOAD, SHOP_NOW, NO_BUTTON."
                    ),
                },
                # ── Copy — Singular (modo único apenas) ──────────────────────
                "body": {
                    "type": "string",
                    "description": "Texto principal. Use APENAS no modo único (quando não usar bodies). Prefira bodies para variações.",
                },
                "title": {
                    "type": "string",
                    "description": "Headline. Use APENAS no modo único (quando não usar titles). Prefira titles para variações.",
                },
                "description": {
                    "type": "string",
                    "description": "Descrição do link. Use APENAS no modo único (quando não usar descriptions). Prefira descriptions para variações.",
                },
                "caption": {
                    "type": "string",
                    "description": "URL de exibição (ex: 'meusite.com.br'). Opcional — Meta usa o domínio do link se omitido.",
                },
                # ── Mídia — Imagem ───────────────────────────────────────────
                "image_url": {
                    "type": "string",
                    "description": "URL pública da imagem (JPG/PNG). Para criativo único. Mínimo 600x314px, ideal 1200x628px (feed) ou 1080x1080px (feed quadrado). ALTERNATIVA SEM URL: use image_hash após upload_ad_image.",
                },
                "image_urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Múltiplas URLs de imagem para teste A/B (até 10). Use com 'bodies' para multi-asset. ALTERNATIVA SEM URL: use image_hashes.",
                },
                "image_hash": {
                    "type": "string",
                    "description": "Hash da imagem já upada na Meta via upload_ad_image. PREFERIDO quando não há URL pública disponível. Elimina dependência de túnel/cloudflare.",
                },
                "image_hashes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Múltiplos hashes de imagem para multi-asset A/B. Use upload_ad_image para cada arquivo e passe os hashes aqui.",
                },
                # ── Mídia — Vídeo ────────────────────────────────────────────
                "video_id": {
                    "type": "string",
                    "description": "ID de vídeo já upado na biblioteca de mídia do Facebook. Para criativo único.",
                },
                "video_thumbnail_url": {
                    "type": "string",
                    "description": "URL da thumbnail do vídeo. Obrigatório quando usar video_id.",
                },
                "video_ids": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Múltiplos vídeos para multi-asset. Array de {video_id: string, thumbnail_url: string}.",
                },
                # ── CTA ──────────────────────────────────────────────────────
                "call_to_action_type": {
                    "type": "string",
                    "description": (
                        "CTA do botão. Use APENAS no modo único (quando não usar cta_types). "
                        "No modo multi-asset, use cta_types. "
                        "Valores: LEARN_MORE, SHOP_NOW, SIGN_UP, SUBSCRIBE, CONTACT_US, "
                        "BOOK_TRAVEL, DOWNLOAD, GET_OFFER, GET_QUOTE, APPLY_NOW, "
                        "WATCH_MORE, LISTEN_NOW, OPEN_LINK, NO_BUTTON. Padrão: LEARN_MORE."
                    ),
                },
                # ── Destino ──────────────────────────────────────────────────
                "link": {
                    "type": "string",
                    "description": "URL de destino (página de vendas, landing page, etc.).",
                },
                "url_tags": {
                    "type": "string",
                    "description": (
                        "Parâmetros UTM / tracking appended à URL de destino. "
                        "Ex: 'utm_source=facebook&utm_medium=paid&utm_campaign=nome&utm_content={{ad.name}}'. "
                        "Suporta macros Meta: {{ad.name}}, {{adset.name}}, {{campaign.name}}, {{placement}}."
                    ),
                },
                # ── Controle Advantage+ Creative ─────────────────────────────
                "advantage_plus": {
                    "type": "boolean",
                    "description": (
                        "PADRÃO FALSE. "
                        "Quando false: desativa TODAS as 'otimizações' Advantage+ Creative — "
                        "a Meta não vai reescrever copy, não vai aplicar filtros na imagem, "
                        "não vai adicionar música, não vai mudar o CTA, não vai fazer 3D, "
                        "não vai mostrar 'comentários relevantes', não vai recortar a imagem. "
                        "Seu criativo sai EXATAMENTE como você definiu. "
                        "Quando true: a Meta faz o que quiser com seus assets."
                    ),
                },
                "disable_text_optimizations": {
                    "type": "boolean",
                    "description": "Desativa geração de variações de texto pela Meta (parte do standard_enhancements). Ignorado se advantage_plus=false (já desabilitado).",
                },
                "disable_image_enhancements": {
                    "type": "boolean",
                    "description": "Desativa ajustes de brilho/contraste, filtros e melhorias de imagem pela Meta.",
                },
                "disable_image_cropping": {
                    "type": "boolean",
                    "description": "Desativa recorte automático da imagem para diferentes proporções de posicionamento.",
                },
                "disable_image_uncrop": {
                    "type": "boolean",
                    "description": "Desativa o 'image uncrop' — a IA da Meta que expande as bordas da imagem com conteúdo gerado.",
                },
                "disable_music": {
                    "type": "boolean",
                    "description": "Desativa adição automática de música de fundo em anúncios de vídeo.",
                },
                "disable_video_auto_crop": {
                    "type": "boolean",
                    "description": "Desativa recorte automático de vídeo para diferentes formatos de tela.",
                },
                "disable_enhance_cta": {
                    "type": "boolean",
                    "description": "Desativa a 'melhoria' automática do botão CTA pela Meta.",
                },
                "disable_inline_comment": {
                    "type": "boolean",
                    "description": "Desativa exibição de 'comentários relevantes' ao lado do anúncio (feature que a Meta adiciona sem pedir).",
                },
                "disable_3d_animation": {
                    "type": "boolean",
                    "description": "Desativa o efeito 3D que a Meta aplica automaticamente em imagens estáticas.",
                },
                "disable_site_extensions": {
                    "type": "boolean",
                    "description": "Desativa extensões automáticas de site (lead gen capture, informações adicionais extraídas do site).",
                },
                # ── Multi-asset config ───────────────────────────────────────
                "ad_format": {
                    "type": "string",
                    "description": "Formato para multi-asset: SINGLE_IMAGE (padrão), SINGLE_VIDEO, CAROUSEL. Inferido automaticamente se não fornecido.",
                },
            },
            "required": ["name", "page_id", "link"],
        },
    },
    {
        "name": "mcp__meta-ads__create_ad",
        "description": (
            "[META-ADS] Cria um anúncio vinculando criativo a um ad set. "
            "Suporta tracking specs explícito para pixel e conversões customizadas."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "ID da conta (ex: act_759233534882637). Se omitido usa a conta configurada.",
                },
                "ad_set_id": {"type": "string", "description": "ID do ad set pai"},
                "creative_id": {
                    "type": "string",
                    "description": "ID do criativo criado com create_ad_creative",
                },
                "name": {"type": "string", "description": "Nome do anúncio"},
                "status": {
                    "type": "string",
                    "description": "Status inicial: ACTIVE ou PAUSED (padrão PAUSED)",
                },
                "pixel_id": {
                    "type": "string",
                    "description": "ID do pixel Meta para tracking deste anúncio. Quando fornecido, adiciona tracking_specs automaticamente.",
                },
                "conversion_domain": {
                    "type": "string",
                    "description": "Domínio verificado onde ocorrem as conversões (ex: 'meusite.com.br'). Aumenta confiança do sinal para o CAPI.",
                },
                "tracking_specs": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "Specs de tracking customizadas. Exemplo para pixel padrão: "
                        '[{"action.type": ["offsite_conversion"], "fb_pixel": ["SEU_PIXEL_ID"]}]. '
                        "Use pixel_id para o caso simples — tracking_specs é para configurações avançadas."
                    ),
                },
            },
            "required": ["ad_set_id", "creative_id", "name"],
        },
    },
    {
        "name": "mcp__meta-ads__update_campaign",
        "description": "[META-ADS] Atualiza nome, status ou orçamento de uma campanha Meta.",
        "parameters": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string", "description": "ID da campanha"},
                "name": {"type": "string", "description": "Novo nome (opcional)"},
                "status": {
                    "type": "string",
                    "description": "Novo status: ACTIVE ou PAUSED (opcional)",
                },
                "daily_budget": {
                    "type": "integer",
                    "description": "Novo orçamento diário em centavos (opcional)",
                },
            },
            "required": ["campaign_id"],
        },
    },
    {
        "name": "mcp__meta-ads__pause_campaign",
        "description": "[META-ADS] Pausa uma campanha Meta ativa.",
        "parameters": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string", "description": "ID da campanha"},
            },
            "required": ["campaign_id"],
        },
    },
    {
        "name": "mcp__meta-ads__enable_campaign",
        "description": "[META-ADS] Ativa uma campanha Meta pausada.",
        "parameters": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string", "description": "ID da campanha"},
            },
            "required": ["campaign_id"],
        },
    },
    {
        "name": "mcp__meta-ads__delete_campaign",
        "description": "[META-ADS] Remove uma campanha Meta.",
        "parameters": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string", "description": "ID da campanha"},
            },
            "required": ["campaign_id"],
        },
    },
    # ── Targeting Search ─────────────────────────────────────────────────
    {
        "name": "mcp__meta-ads__search_targeting",
        "description": (
            "[META-ADS] Busca IDs válidos de interesses, comportamentos, localizações ou idiomas "
            "para usar em create_ad_set. Retorna id + name para incluir no targeting."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Termo de busca (ex: 'empreendedorismo', 'São Paulo', 'iOS')",
                },
                "type": {
                    "type": "string",
                    "description": (
                        "Tipo de targeting a buscar: "
                        "interest (interesses), behavior (comportamentos), "
                        "location (cidades/estados/países), locale (idiomas), "
                        "custom_audience (audiências customizadas da conta)."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Máximo de resultados (padrão 10)",
                },
            },
            "required": ["query", "type"],
        },
    },
    # ── Ad Sets ──────────────────────────────────────────────────────────
    {
        "name": "mcp__meta-ads__list_ad_sets",
        "description": "[META-ADS] Lista conjuntos de anúncios (ad sets) de uma campanha ou de toda a conta. Sempre passe limit explicitamente.",
        "parameters": {
            "type": "object",
            "properties": {
                "campaign_id": {
                    "type": "string",
                    "description": "ID da campanha para filtrar (opcional — se omitido lista todos da conta)",
                },
                "status": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filtrar por effective_status: ACTIVE, PAUSED, CAMPAIGN_PAUSED (opcional — sem filtro retorna todos os não-deletados)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Máximo de resultados. OBRIGATÓRIO — passe 100 por padrão, aumente se souber que há mais.",
                },
            },
            "required": ["limit"],
        },
    },
    {
        "name": "mcp__meta-ads__get_ad_set_insights",
        "description": "[META-ADS] Obtém métricas de desempenho de um ad set.",
        "parameters": {
            "type": "object",
            "properties": {
                "ad_set_id": {"type": "string", "description": "ID do ad set"},
                "date_preset": {
                    "type": "string",
                    "description": "Período: last_7d, last_30d, last_90d, this_month (padrão last_30d)",
                },
            },
            "required": ["ad_set_id"],
        },
    },
    {
        "name": "mcp__meta-ads__update_ad_set",
        "description": "[META-ADS] Atualiza nome, status ou orçamento de um ad set.",
        "parameters": {
            "type": "object",
            "properties": {
                "ad_set_id": {"type": "string", "description": "ID do ad set"},
                "name": {"type": "string", "description": "Novo nome (opcional)"},
                "status": {
                    "type": "string",
                    "description": "Novo status: ACTIVE ou PAUSED (opcional)",
                },
                "daily_budget": {
                    "type": "integer",
                    "description": "Novo orçamento diário em centavos (opcional)",
                },
            },
            "required": ["ad_set_id"],
        },
    },
    {
        "name": "mcp__meta-ads__pause_ad_set",
        "description": "[META-ADS] Pausa um ad set ativo.",
        "parameters": {
            "type": "object",
            "properties": {
                "ad_set_id": {"type": "string", "description": "ID do ad set"},
            },
            "required": ["ad_set_id"],
        },
    },
    {
        "name": "mcp__meta-ads__enable_ad_set",
        "description": "[META-ADS] Ativa um ad set pausado.",
        "parameters": {
            "type": "object",
            "properties": {
                "ad_set_id": {"type": "string", "description": "ID do ad set"},
            },
            "required": ["ad_set_id"],
        },
    },
    {
        "name": "mcp__meta-ads__delete_ad_set",
        "description": "[META-ADS] Apaga permanentemente um ad set. Use com cuidado — ação irreversível.",
        "parameters": {
            "type": "object",
            "properties": {
                "ad_set_id": {
                    "type": "string",
                    "description": "ID do ad set a apagar",
                },
            },
            "required": ["ad_set_id"],
        },
    },
    # ── Ads (criativos) ───────────────────────────────────────────────────
    {
        "name": "mcp__meta-ads__list_ads",
        "description": "[META-ADS] Lista anúncios de um ad set ou da conta inteira. Sempre passe limit explicitamente — use 100 para contas pequenas, 200+ se souber que tem muitos ads.",
        "parameters": {
            "type": "object",
            "properties": {
                "ad_set_id": {
                    "type": "string",
                    "description": "ID do ad set para filtrar (opcional — se omitido lista todos da conta)",
                },
                "status": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filtrar por effective_status: ACTIVE, PAUSED, CAMPAIGN_PAUSED, ADSET_PAUSED (opcional — sem filtro retorna todos os não-deletados)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Máximo de resultados. OBRIGATÓRIO — passe 100 por padrão, aumente se souber que há mais ads.",
                },
            },
            "required": ["limit"],
        },
    },
    {
        "name": "mcp__meta-ads__get_ad",
        "description": "[META-ADS] Obtém detalhes de um anúncio específico (nome, status, criativo).",
        "parameters": {
            "type": "object",
            "properties": {
                "ad_id": {"type": "string", "description": "ID do anúncio"},
            },
            "required": ["ad_id"],
        },
    },
    {
        "name": "mcp__meta-ads__get_ad_insights",
        "description": "[META-ADS] Obtém métricas de desempenho de um anúncio.",
        "parameters": {
            "type": "object",
            "properties": {
                "ad_id": {"type": "string", "description": "ID do anúncio"},
                "date_preset": {
                    "type": "string",
                    "description": "Período: last_7d, last_30d, last_90d, this_month (padrão last_30d)",
                },
            },
            "required": ["ad_id"],
        },
    },
    {
        "name": "mcp__meta-ads__pause_ad",
        "description": "[META-ADS] Pausa um anúncio ativo.",
        "parameters": {
            "type": "object",
            "properties": {
                "ad_id": {"type": "string", "description": "ID do anúncio"},
            },
            "required": ["ad_id"],
        },
    },
    {
        "name": "mcp__meta-ads__enable_ad",
        "description": "[META-ADS] Ativa um anúncio pausado.",
        "parameters": {
            "type": "object",
            "properties": {
                "ad_id": {"type": "string", "description": "ID do anúncio"},
            },
            "required": ["ad_id"],
        },
    },
    {
        "name": "mcp__meta-ads__get_ad_creative",
        "description": "[META-ADS] Retorna o criativo de um anúncio: imagem, vídeo (thumbnail + URL), título, corpo, call-to-action e page_id. Use para descobrir o page_id antes de criar um novo criativo.",
        "parameters": {
            "type": "object",
            "properties": {
                "ad_id": {
                    "type": "string",
                    "description": "ID do anúncio (ad_id)",
                },
            },
            "required": ["ad_id"],
        },
    },
    {
        "name": "mcp__meta-ads__list_pages",
        "description": "[META-ADS] Lista as Páginas do Facebook conectadas a esta conta de anúncios. Use para obter o page_id necessário em create_ad_creative.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
]


def _meta_error_message(data: dict) -> str:
    """
    Converte resposta de erro da Meta Graph API em mensagem clara com todos os detalhes.
    """
    err = data.get("error", {})
    code = err.get("code", 0)
    msg = err.get("message", str(err))
    subcode = err.get("error_subcode")
    user_title = err.get("error_user_title", "")
    user_msg = err.get("error_user_msg", "")
    fbtrace = err.get("fbtrace_id", "")

    if code == 190:
        return f"Token da sua conta Meta expirou ou foi revogado — reconecte em Configurações → Integrações. (detalhe: {msg})"
    if code in (200, 10, 273):
        return f"Permissão ausente na conta Meta — verifique os escopos autorizados no app. (detalhe: {msg})"

    parts = [f"({code}) {msg}"]
    if subcode:
        parts.append(f"subcode={subcode}")
    if user_title:
        parts.append(f"título: {user_title}")
    if user_msg:
        parts.append(f"detalhe: {user_msg}")
    if fbtrace:
        parts.append(f"trace={fbtrace}")
    return " | ".join(parts)


def _meta_effective_status(status_filter) -> str:
    """Serializa lista de status sem espaços — Meta rejeita JSON com espaços."""
    statuses = status_filter if isinstance(status_filter, list) else [status_filter]
    return json.dumps(statuses, separators=(",", ":"))


def _meta_insights_content(
    entity_label: str, entity_id: str, date_preset: str, r: dict
) -> str:
    return (
        f"{entity_label} {entity_id} ({date_preset}):\n"
        f"Impressões: {r.get('impressions','0')} | Cliques: {r.get('clicks','0')} | "
        f"Gasto: R${r.get('spend','0')} | CTR: {r.get('ctr','0')} | "
        f"CPC: {r.get('cpc','0')} | Alcance: {r.get('reach','0')}"
    )


async def call(tool_name: str, args: Dict, env: Dict) -> Dict:
    access_token = env.get("META_ACCESS_TOKEN", "")
    base_url = "https://graph.facebook.com/v21.0"

    if not access_token:
        return {
            "success": False,
            "error": "Token Meta não configurado — conecte em Configurações → Integrações.",
        }

    account_id = env.get("META_AD_ACCOUNT_ID", "").strip().lstrip("act_")

    if not account_id:
        return {
            "success": False,
            "error": "Conta de anúncios não configurada — selecione a conta em Configurações → Integrações → Meta Ads → Gerenciar Conta.",
        }

    debug(f"[META-ADS] tool={tool_name} account_id={account_id!r}")

    async with httpx.AsyncClient(timeout=30.0) as http:
        # ── helper: checa erro e retorna dict ─────────────────────────────────
        def _check_err(data: dict):
            if "error" in data:
                debug(f"[META-ADS] API error: {data['error']}")
                return {"success": False, "error": _meta_error_message(data)}
            return None

        # ── Campaigns ────────────────────────────────────────────────────────
        if tool_name == "list_campaigns":
            params: Dict = {
                "access_token": access_token,
                "fields": "id,name,status,objective,daily_budget,lifetime_budget,budget_rebalance_flag,bid_strategy,bid_amount,spend_cap,created_time",
                "limit": args.get("limit", 25),
            }
            status_filter = args.get("status")
            if status_filter:
                params["effective_status"] = _meta_effective_status(status_filter)
            resp = await http.get(
                f"{base_url}/act_{account_id}/campaigns", params=params
            )
            data = resp.json()
            if err := _check_err(data):
                return err
            campaigns = data.get("data", [])
            if not campaigns and status_filter:
                # Retry sem filtro para dar contexto melhor ao agente
                params.pop("effective_status", None)
                resp2 = await http.get(
                    f"{base_url}/act_{account_id}/campaigns", params=params
                )
                data2 = resp2.json()
                if not _check_err(data2):
                    campaigns = data2.get("data", [])
                    if campaigns:
                        lines = [
                            f"ID: {c['id']} | {c['name']} | {c.get('status')} | {c.get('objective')}"
                            for c in campaigns
                        ]
                        return {
                            "success": True,
                            "content": (
                                f"Nenhuma campanha com os status solicitados. "
                                f"Todas as campanhas ({len(campaigns)}):\n"
                                + "\n".join(lines)
                            ),
                        }
            if not campaigns:
                return {
                    "success": True,
                    "content": (
                        f"Nenhuma campanha encontrada. Verifique se a conta correta está selecionada "
                        f"em Configurações → Integrações → Meta Ads → Gerenciar Conta."
                    ),
                }

            def _fmt_campaign(c: dict) -> str:
                # CBO = orçamento na campanha (daily_budget ou lifetime_budget no nível da campanha).
                # budget_rebalance_flag NÃO indica CBO — é "Ad Set Budget Rebalancing", outra feature.
                camp_daily = c.get("daily_budget")
                camp_lifetime = c.get("lifetime_budget")
                is_cbo = bool(camp_daily or camp_lifetime)
                bid_strat = c.get("bid_strategy", "")
                bid_amt = c.get("bid_amount")
                budget = camp_daily or camp_lifetime or "—"
                line = f"ID: {c['id']} | {c['name']} | {c.get('status')} | {c.get('objective')}"
                if is_cbo:
                    line += f" | CBO=ON budget={budget}"
                    if bid_strat:
                        line += f" | bid_strategy={bid_strat}"
                    if bid_amt:
                        line += f" bid_amount={bid_amt}"
                    line += " — NÃO envie daily_budget no ad set; use bid_strategy=LOWEST_COST_WITH_BID_CAP + bid_amount"
                else:
                    line += " | CBO=OFF (envie daily_budget no ad set)"
                return line

            lines = [_fmt_campaign(c) for c in campaigns]
            return {
                "success": True,
                "content": f"{len(campaigns)} campanha(s):\n" + "\n".join(lines),
            }

        elif tool_name == "get_campaign_insights":
            campaign_id = args.get("campaign_id")
            date_preset = args.get("date_preset", "last_30d")
            params = {
                "access_token": access_token,
                "date_preset": date_preset,
                "fields": "impressions,clicks,spend,ctr,cpc,conversions,reach",
            }
            resp = await http.get(f"{base_url}/{campaign_id}/insights", params=params)
            data = resp.json()
            if err := _check_err(data):
                return err
            rows = data.get("data", [])
            if not rows:
                return {
                    "success": True,
                    "content": "Sem dados para o período selecionado",
                }
            return {
                "success": True,
                "content": _meta_insights_content(
                    "Campanha", campaign_id, date_preset, rows[0]
                ),
            }

        elif tool_name == "create_campaign":
            special_ad_categories = args.get("special_ad_categories", [])
            payload = {
                "access_token": access_token,
                "name": args["name"],
                "objective": args["objective"],
                "status": args.get("status", "PAUSED"),
                "special_ad_categories": json.dumps(special_ad_categories),
            }
            if args.get("daily_budget"):
                payload["daily_budget"] = str(args["daily_budget"])
            resp = await http.post(
                f"{base_url}/act_{account_id}/campaigns", data=payload
            )
            data = resp.json()
            if err := _check_err(data):
                return err
            return {
                "success": True,
                "campaign_id": data.get("id"),
                "content": f"Campanha criada: {data.get('id')}",
            }

        elif tool_name == "create_ad_set":
            # ── Targeting object ────────────────────────────────────────────────
            targeting: Dict = {}

            # Demográfico
            if args.get("age_min"):
                targeting["age_min"] = args["age_min"]
            if args.get("age_max"):
                targeting["age_max"] = args["age_max"]
            if args.get("genders"):
                targeting["genders"] = args["genders"]

            # Geo
            geo: Dict = {}
            if args.get("countries"):
                geo["countries"] = args["countries"]
            else:
                geo["countries"] = ["BR"]
            if args.get("regions"):
                geo["regions"] = args["regions"]
            if args.get("cities"):
                geo["cities"] = args["cities"]
            if args.get("location_types"):
                geo["location_types"] = args["location_types"]
            targeting["geo_locations"] = geo

            # Idioma
            if args.get("locales"):
                targeting["locales"] = args["locales"]

            # Interesses / Comportamentos / Dados demo
            if args.get("interests"):
                targeting["interests"] = args["interests"]
            if args.get("behaviors"):
                targeting["behaviors"] = args["behaviors"]
            if args.get("education_statuses"):
                targeting["education_statuses"] = args["education_statuses"]
            if args.get("relationship_statuses"):
                targeting["relationship_statuses"] = args["relationship_statuses"]
            if args.get("life_events"):
                targeting["life_events"] = args["life_events"]
            if args.get("flexible_spec"):
                targeting["flexible_spec"] = args["flexible_spec"]

            # Custom audiences
            if args.get("custom_audiences"):
                targeting["custom_audiences"] = args["custom_audiences"]
            if args.get("excluded_custom_audiences"):
                targeting["excluded_custom_audiences"] = args[
                    "excluded_custom_audiences"
                ]
            if args.get("exclusions"):
                targeting["exclusions"] = args["exclusions"]

            # Dispositivos
            if args.get("device_platforms"):
                targeting["device_platforms"] = args["device_platforms"]
            if args.get("user_os"):
                targeting["user_os"] = args["user_os"]
            if args.get("user_device"):
                targeting["user_device"] = args["user_device"]
            if args.get("wireless_carrier"):
                targeting["wireless_carrier"] = args["wireless_carrier"]

            # Placements
            if args.get("publisher_platforms"):
                targeting["publisher_platforms"] = args["publisher_platforms"]
            if args.get("facebook_positions"):
                targeting["facebook_positions"] = args["facebook_positions"]
            if args.get("instagram_positions"):
                targeting["instagram_positions"] = args["instagram_positions"]
            if args.get("audience_network_positions"):
                targeting["audience_network_positions"] = args[
                    "audience_network_positions"
                ]
            if args.get("messenger_positions"):
                targeting["messenger_positions"] = args["messenger_positions"]

            # Advantage Audience — deve ser declarado explicitamente (0 ou 1)
            if "advantage_audience" in args:
                targeting["targeting_automation"] = {
                    "advantage_audience": args["advantage_audience"]
                }

            # ── Verificar dados da campanha ──────────────────────────────────────
            campaign_id_arg = args["campaign_id"]
            camp_resp = await http.get(
                f"{base_url}/{campaign_id_arg}",
                params={
                    "access_token": access_token,
                    "fields": "bid_strategy,bid_amount,budget_rebalance_flag,daily_budget,objective",
                },
            )
            camp_data = camp_resp.json()
            camp_bid_strategy = camp_data.get("bid_strategy", "")
            camp_bid_amount = camp_data.get("bid_amount")
            camp_cbo = camp_data.get("budget_rebalance_flag", False)
            camp_objective = camp_data.get("objective", "")
            camp_daily_budget = camp_data.get("daily_budget")
            debug(
                f"[META-ADS] campaign {campaign_id_arg}: objective={camp_objective!r} bid_strategy={camp_bid_strategy!r} bid_amount={camp_bid_amount!r} cbo={camp_cbo!r} daily_budget={camp_daily_budget!r}"
            )

            # ── Validação: optimization_goal incompatível com objetivo da campanha ──
            opt_goal = args.get("optimization_goal", "")
            pixel_id_arg = args.get("pixel_id")

            # LEAD_GENERATION é para formulários nativos do Facebook, NÃO para pixel.
            # Para OUTCOME_LEADS com pixel → usar OFFSITE_CONVERSIONS.
            if opt_goal == "LEAD_GENERATION" and camp_objective == "OUTCOME_LEADS":
                return {
                    "success": False,
                    "error": (
                        "ERRO DE CONFIGURAÇÃO: optimization_goal='LEAD_GENERATION' é INCOMPATÍVEL com "
                        f"a campanha '{campaign_id_arg}' (objetivo: OUTCOME_LEADS com pixel de conversão). "
                        "LEAD_GENERATION é SOMENTE para formulários nativos do Facebook (sem pixel). "
                        "Para campanhas OUTCOME_LEADS com pixel, o setup CORRETO é:\n"
                        "  optimization_goal=OFFSITE_CONVERSIONS\n"
                        "  billing_event=IMPRESSIONS\n"
                        "  bid_strategy=LOWEST_COST_WITH_BID_CAP\n"
                        "  bid_amount=5000  (= R$50,00 — ajuste ao seu CPA alvo)\n"
                        "  advantage_audience=0\n"
                        f"  pixel_id={pixel_id_arg or '870523582149794'}\n"
                        "  custom_event_type=LEAD\n"
                        "  NÃO enviar daily_budget no ad set (campanha está em CBO — orçamento já está na campanha)\n"
                        "NÃO use LEAD_GENERATION, REACH, LINK_CLICKS nem nenhum outro. Use OFFSITE_CONVERSIONS."
                    ),
                }

            if opt_goal == "LEAD_GENERATION" and pixel_id_arg:
                return {
                    "success": False,
                    "error": (
                        "CONFLITO: optimization_goal='LEAD_GENERATION' NÃO usa pixel. "
                        "LEAD_GENERATION é para formulários nativos do Facebook. "
                        "Se você quer rastrear conversões via pixel, use optimization_goal='OFFSITE_CONVERSIONS'. "
                        "Setup correto: optimization_goal=OFFSITE_CONVERSIONS, billing_event=IMPRESSIONS, "
                        f"daily_budget=<centavos>, pixel_id={pixel_id_arg}, custom_event_type=LEAD, SEM bid_strategy."
                    ),
                }

            # ── Detecção de CBO: campanha com daily_budget no nível de campanha ──────
            # IMPORTANTE: budget_rebalance_flag NÃO indica CBO. CBO é detectado pela
            # presença de daily_budget ou lifetime_budget na CAMPANHA.
            # Em modo CBO: ad sets NÃO podem ter budget próprio (erro 1885621).
            # Em modo ABO: ad sets DEVEM ter budget próprio.
            is_cbo = bool(camp_daily_budget)
            debug(
                f"[META-ADS] CBO detection: camp_daily_budget={camp_daily_budget!r} → is_cbo={is_cbo}"
            )

            # ── Validação: advantage_audience obrigatório na API v19+ ────────────
            # targeting_automation.advantage_audience deve ser 0 (manual) ou 1 (expansão automática).
            if "advantage_audience" not in args:
                return {
                    "success": False,
                    "error": (
                        "Campo obrigatório ausente: advantage_audience\n\n"
                        "A Meta Ads API v19+ exige que você declare explicitamente se quer ou não "
                        "o público Advantage (expansão automática de audiência pela Meta).\n\n"
                        "Adicione ao create_ad_set:\n"
                        "  advantage_audience=0  → público MANUAL (você controla o targeting)\n"
                        "  advantage_audience=1  → Meta expande automaticamente o público\n\n"
                        "Para anunciantes experientes que querem controle total: use advantage_audience=0."
                    ),
                }

            # ── Estratégias que exigem bid_amount no ad set ──────────────────────
            _BID_AMOUNT_REQUIRED = {
                "LOWEST_COST_WITH_BID_CAP",
                "COST_CAP",
                "TARGET_COST",
            }

            if camp_bid_strategy in _BID_AMOUNT_REQUIRED and not args.get("bid_amount"):
                return {
                    "success": False,
                    "error": (
                        f"A campanha usa bid_strategy='{camp_bid_strategy}' "
                        f"o que exige que o ad set forneça 'bid_amount'. "
                        f"Reenvie incluindo bid_amount (em centavos, ex: 5000 = R$50,00)."
                    ),
                }

            # ── Validação: campanha CBO exige bid_amount no ad set ───────────────
            # Em contas com CBO + OUTCOME_LEADS + OFFSITE_CONVERSIONS, a Meta rejeita
            # LOWEST_COST_WITHOUT_CAP (implícito ou explícito) com erro 1815857.
            # O único bid_strategy que funciona é LOWEST_COST_WITH_BID_CAP + bid_amount.
            if is_cbo:
                bid_arg = args.get("bid_strategy", "")
                if not args.get("bid_amount"):
                    return {
                        "success": False,
                        "error": (
                            "Campanha em modo CBO (orçamento na campanha) requer bid_amount no ad set.\n\n"
                            "LOWEST_COST_WITHOUT_CAP não é aceito nesta conta para campanhas CBO com "
                            "OUTCOME_LEADS + OFFSITE_CONVERSIONS. Use:\n"
                            "  bid_strategy=LOWEST_COST_WITH_BID_CAP\n"
                            "  bid_amount=5000  (= R$50,00 — seu CPA máximo alvo)\n\n"
                            "NÃO envie daily_budget no ad set (orçamento já está na campanha)."
                        ),
                    }
                if bid_arg == "LOWEST_COST_WITHOUT_CAP":
                    return {
                        "success": False,
                        "error": (
                            "LOWEST_COST_WITHOUT_CAP não é aceito nesta conta para campanhas CBO "
                            "com OUTCOME_LEADS + OFFSITE_CONVERSIONS (causa erro 1815857 na Meta API).\n\n"
                            "Use: bid_strategy=LOWEST_COST_WITH_BID_CAP + bid_amount=5000 (= R$50,00)."
                        ),
                    }

            # ── Payload principal ───────────────────────────────────────────────
            payload: Dict = {
                "access_token": access_token,
                "campaign_id": args["campaign_id"],
                "name": args["name"],
                "optimization_goal": args["optimization_goal"],
                "billing_event": args.get("billing_event", "IMPRESSIONS"),
                "status": args.get("status", "PAUSED"),
                "targeting": json.dumps(targeting),
            }

            # ── Orçamento ───────────────────────────────────────────────────────
            if is_cbo:
                # Campanha em modo CBO: orçamento está na campanha, ad set NÃO pode ter budget.
                # Qualquer daily_budget/lifetime_budget no ad set causaria erro 1885621.
                pass  # não adicionar budget ao payload do ad set
            else:
                # Campanha em modo ABO: ad set precisa de budget próprio.
                if args.get("daily_budget"):
                    payload["daily_budget"] = str(args["daily_budget"])
                elif args.get("lifetime_budget"):
                    payload["lifetime_budget"] = str(args["lifetime_budget"])

            # Datas
            if args.get("start_time"):
                payload["start_time"] = args["start_time"]
            if args.get("end_time"):
                from datetime import datetime, timezone

                try:
                    end_dt = datetime.fromisoformat(
                        args["end_time"].replace("Z", "+00:00")
                    )
                    if end_dt < datetime.now(timezone.utc):
                        return {
                            "success": False,
                            "error": (
                                f"end_time='{args['end_time']}' está no passado (erro 1487033). "
                                "Informe uma data futura ou omita end_time para deixar o ad set sem data de término."
                            ),
                        }
                    payload["end_time"] = args["end_time"]
                except Exception:
                    payload["end_time"] = args["end_time"]

            # ── Lance ───────────────────────────────────────────────────────────
            bid_strategy = args.get("bid_strategy")
            if bid_strategy and bid_strategy in _BID_AMOUNT_REQUIRED:
                # Estratégia que exige bid_amount — ambas obrigatórias
                payload["bid_strategy"] = bid_strategy
                if args.get("bid_amount"):
                    payload["bid_amount"] = str(args["bid_amount"])
            elif bid_strategy and bid_strategy == "LOWEST_COST_WITHOUT_CAP":
                # Enviar explicitamente para garantir que Meta não use BID_CAP como default
                payload["bid_strategy"] = bid_strategy
            # Se nenhum bid_strategy: Meta usa o default da campanha (geralmente LOWEST_COST_WITHOUT_CAP)
            if args.get("bid_amount") and "bid_amount" not in payload:
                payload["bid_amount"] = str(args["bid_amount"])
            if args.get("pacing_type"):
                payload["pacing_type"] = json.dumps(args["pacing_type"])
            # "WEBSITE" é o default implícito da Meta — enviar explicitamente pode
            # causar conflito com certas combinações de bid_strategy/optimization_goal.
            # Só envia se for um valor não-padrão (WEBSITE_AND_PHONE_CALL, APP, etc.)
            dest_type = args.get("destination_type")
            if dest_type and dest_type != "WEBSITE":
                payload["destination_type"] = dest_type

            # Pixel / evento de conversão
            if args.get("pixel_id"):
                promoted_object: Dict = {"pixel_id": args["pixel_id"]}
                if args.get("custom_event_type"):
                    promoted_object["custom_event_type"] = args["custom_event_type"]
                payload["promoted_object"] = json.dumps(promoted_object)

            debug(
                f"[META-ADS] create_ad_set payload: {json.dumps({k: v for k, v in payload.items() if k != 'access_token'})}"
            )
            resp = await http.post(f"{base_url}/act_{account_id}/adsets", data=payload)
            data = resp.json()
            debug(f"[META-ADS] create_ad_set response: {json.dumps(data)}")

            # Tratar erros conhecidos com mensagem acionável
            if "error" in data:
                err_obj = data["error"]
                subcode = err_obj.get("error_subcode")

                if subcode == 1815857:
                    meta_msg = _meta_error_message(data)
                    return {
                        "success": False,
                        "error": (
                            f"bid_amount obrigatório (1815857). {meta_msg}\n"
                            "A bid_strategy ativa exige bid_amount. "
                            "Reenvie incluindo bid_strategy=LOWEST_COST_WITH_BID_CAP e bid_amount=<centavos> (ex: 5000 = R$50,00)."
                        ),
                    }

                if subcode == 1885621:
                    meta_msg = _meta_error_message(data)
                    return {
                        "success": False,
                        "error": (
                            f"Conflito de orçamento (1885621). {meta_msg}\n\n"
                            f"A campanha '{campaign_id_arg}' está em modo CBO (tem daily_budget no nível de campanha). "
                            "Em modo CBO, o ad set NÃO pode ter daily_budget nem lifetime_budget próprios. "
                            "Reenvie o create_ad_set SEM daily_budget e SEM lifetime_budget. "
                            "A campanha já fornece o orçamento para todos os ad sets."
                        ),
                    }

                if subcode == 1870227:
                    return {
                        "success": False,
                        "error": (
                            "Campo advantage_audience ausente ou inválido (1870227). "
                            "Reenvie o create_ad_set incluindo advantage_audience=0 (público manual) "
                            "ou advantage_audience=1 (Meta expande automaticamente)."
                        ),
                    }

                if subcode == 2490408:
                    return {
                        "success": False,
                        "error": (
                            f"optimization_goal='{args.get('optimization_goal')}' é incompatível com esta campanha (OUTCOME_LEADS). "
                            "Para campanhas OUTCOME_LEADS com pixel de conversão, use optimization_goal=OFFSITE_CONVERSIONS."
                        ),
                    }

                if err := _check_err(data):
                    return err

            return {
                "success": True,
                "ad_set_id": data.get("id"),
                "content": f"Ad Set criado: {data.get('id')}",
            }

        elif tool_name == "upload_ad_image":
            img_bytes_b64 = (args.get("bytes") or "").strip()
            image_url_arg = (args.get("image_url") or "").strip()
            upload_name = (args.get("filename") or "criativo.jpg").strip()

            if not img_bytes_b64 and not image_url_arg:
                return {
                    "success": False,
                    "error": "Forneça 'bytes' (base64 gerado via terminal) ou 'image_url'.",
                }

            upload_payload: Dict = {"access_token": access_token, "name": upload_name}
            if img_bytes_b64:
                upload_payload["bytes"] = img_bytes_b64
            else:
                upload_payload["url"] = image_url_arg

            resp = await http.post(
                f"{base_url}/act_{account_id}/adimages", data=upload_payload
            )
            data = resp.json()
            if err := _check_err(data):
                return err

            images_map = data.get("images", {})
            if not images_map:
                return {
                    "success": False,
                    "error": "Meta não retornou hash da imagem.",
                    "raw": data,
                }
            first_key = next(iter(images_map))
            img_info = images_map[first_key]
            image_hash = img_info.get("hash", "")
            image_url_meta = img_info.get("url", "")
            return {
                "success": True,
                "image_hash": image_hash,
                "image_url": image_url_meta,
                "content": f"Imagem upada. Hash: {image_hash} — use em create_ad_creative como image_hash (único) ou image_hashes (multi-asset).",
            }

        elif tool_name == "create_ad_creative":
            page_id = args["page_id"]
            link = args["link"]

            # ── Advantage+ Creative: desativa tudo por padrão ──────────────────
            # advantage_plus=True  → deixa Meta fazer o que quiser
            # advantage_plus=False (padrão) → OPT_OUT de tudo
            allow_advantage = args.get("advantage_plus", False)

            if allow_advantage:
                degrees_spec: Dict = {
                    "creative_features_spec": {
                        "standard_enhancements": {"enroll_status": "OPT_IN"},
                    }
                }
            else:
                # Monta a lista de features a desativar
                features_off: Dict = {
                    "standard_enhancements": {"enroll_status": "OPT_OUT"},
                }
                # Granular overrides (quando advantage_plus=True mas usuario quer desligar específicos)
                if args.get("disable_text_optimizations"):
                    features_off["text_optimizations"] = {"enroll_status": "OPT_OUT"}
                if args.get("disable_image_enhancements"):
                    features_off["image_touchups"] = {"enroll_status": "OPT_OUT"}
                if args.get("disable_image_cropping"):
                    features_off["image_cropping"] = {"enroll_status": "OPT_OUT"}
                if args.get("disable_image_uncrop"):
                    features_off["image_uncrop"] = {"enroll_status": "OPT_OUT"}
                if args.get("disable_music"):
                    features_off["music"] = {"enroll_status": "OPT_OUT"}
                if args.get("disable_video_auto_crop"):
                    features_off["video_auto_crop"] = {"enroll_status": "OPT_OUT"}
                if args.get("disable_enhance_cta"):
                    features_off["enhance_cta"] = {"enroll_status": "OPT_OUT"}
                if args.get("disable_inline_comment"):
                    features_off["inline_comment"] = {"enroll_status": "OPT_OUT"}
                if args.get("disable_3d_animation"):
                    features_off["3d_animation"] = {"enroll_status": "OPT_OUT"}
                if args.get("disable_site_extensions"):
                    features_off["site_extensions"] = {"enroll_status": "OPT_OUT"}
                degrees_spec = {"creative_features_spec": features_off}

            payload: Dict = {
                "access_token": access_token,
                "name": args["name"],
                "degrees_of_freedom_spec": json.dumps(degrees_spec),
            }

            if args.get("url_tags"):
                payload["url_tags"] = args["url_tags"]

            # ── Multi-asset (asset_feed_spec) ─────────────────────────────────
            # Ativado quando qualquer campo plural for fornecido
            is_multi = any(
                args.get(k)
                for k in (
                    "bodies",
                    "titles",
                    "descriptions",
                    "cta_types",
                    "image_urls",
                    "image_hashes",
                    "video_ids",
                )
            )

            if is_multi:
                feed: Dict = {}
                if args.get("bodies"):
                    feed["bodies"] = [{"text": t} for t in args["bodies"]]
                if args.get("titles"):
                    feed["titles"] = [{"text": t} for t in args["titles"]]
                if args.get("descriptions"):
                    feed["descriptions"] = [{"text": d} for d in args["descriptions"]]
                cta_types = args.get("cta_types") or (
                    [args["call_to_action_type"]]
                    if args.get("call_to_action_type")
                    else ["LEARN_MORE"]
                )
                feed["call_to_action_types"] = cta_types
                feed["link_urls"] = [
                    {"website_url": link, "display_url": args.get("caption", "")}
                ]
                if args.get("image_hashes"):
                    feed["images"] = [{"hash": h} for h in args["image_hashes"]]
                elif args.get("image_urls"):
                    feed["images"] = [{"url": u} for u in args["image_urls"]]
                if args.get("video_ids"):
                    feed["videos"] = args["video_ids"]  # [{video_id, thumbnail_url}]
                ad_format = args.get("ad_format", "SINGLE_IMAGE")
                if (
                    args.get("video_ids")
                    and not args.get("image_urls")
                    and not args.get("image_hashes")
                ):
                    ad_format = "SINGLE_VIDEO"
                feed["ad_formats"] = [ad_format]
                payload["asset_feed_spec"] = json.dumps(feed)
                payload["object_story_spec"] = json.dumps({"page_id": page_id})
                if args.get("instagram_actor_id"):
                    spec = json.loads(payload["object_story_spec"])
                    spec["instagram_actor_id"] = args["instagram_actor_id"]
                    payload["object_story_spec"] = json.dumps(spec)

            else:
                # ── Criativo único (controle absoluto) ────────────────────────
                cta_type = args.get("call_to_action_type", "LEARN_MORE")

                if args.get("video_id"):
                    # Criativo de vídeo
                    video_data: Dict = {
                        "video_id": args["video_id"],
                        "call_to_action": {"type": cta_type, "value": {"link": link}},
                    }
                    if args.get("body"):
                        video_data["message"] = args["body"]
                    if args.get("title"):
                        video_data["title"] = args["title"]
                    if args.get("description"):
                        video_data["description"] = args["description"]
                    if args.get("video_thumbnail_url"):
                        video_data["image_url"] = args["video_thumbnail_url"]
                    story_spec: Dict = {"page_id": page_id, "video_data": video_data}
                else:
                    # Criativo de imagem / link
                    link_data: Dict = {
                        "link": link,
                        "call_to_action": {"type": cta_type, "value": {"link": link}},
                    }
                    if args.get("body"):
                        link_data["message"] = args["body"]
                    if args.get("title"):
                        link_data["name"] = args["title"]
                    if args.get("description"):
                        link_data["description"] = args["description"]
                    if args.get("caption"):
                        link_data["caption"] = args["caption"]
                    if args.get("image_hash"):
                        link_data["image_hash"] = args["image_hash"]
                    elif args.get("image_url"):
                        link_data["picture"] = args["image_url"]
                    story_spec = {"page_id": page_id, "link_data": link_data}

                if args.get("instagram_actor_id"):
                    story_spec["instagram_actor_id"] = args["instagram_actor_id"]

                payload["object_story_spec"] = json.dumps(story_spec)

            resp = await http.post(
                f"{base_url}/act_{account_id}/adcreatives", data=payload
            )
            data = resp.json()
            if err := _check_err(data):
                return err
            creative_id = data.get("id")
            mode = "multi-asset" if is_multi else "único"
            adv_label = (
                "Advantage+ ON"
                if allow_advantage
                else "Advantage+ OFF (controle total)"
            )
            return {
                "success": True,
                "creative_id": creative_id,
                "content": f"Criativo {mode} criado: {creative_id} | {adv_label}",
            }

        elif tool_name == "create_ad":
            creative_id = args["creative_id"]
            payload: Dict = {
                "access_token": access_token,
                "adset_id": args["ad_set_id"],
                "name": args["name"],
                "creative": json.dumps({"creative_id": creative_id}),
                "status": args.get("status", "PAUSED"),
            }
            # Tracking specs
            if args.get("tracking_specs"):
                payload["tracking_specs"] = json.dumps(args["tracking_specs"])
            elif args.get("pixel_id"):
                payload["tracking_specs"] = json.dumps(
                    [
                        {
                            "action.type": ["offsite_conversion"],
                            "fb_pixel": [args["pixel_id"]],
                        }
                    ]
                )
            if args.get("conversion_domain"):
                payload["conversion_domain"] = args["conversion_domain"]
            resp = await http.post(f"{base_url}/act_{account_id}/ads", data=payload)
            data = resp.json()
            if err := _check_err(data):
                return err
            return {
                "success": True,
                "ad_id": data.get("id"),
                "content": f"Anúncio criado: {data.get('id')}",
            }

        elif tool_name in ("update_campaign", "pause_campaign", "enable_campaign"):
            campaign_id = args.get("campaign_id")
            payload: Dict = {"access_token": access_token}
            if tool_name == "pause_campaign":
                payload["status"] = "PAUSED"
            elif tool_name == "enable_campaign":
                payload["status"] = "ACTIVE"
            else:
                if args.get("name"):
                    payload["name"] = args["name"]
                if args.get("status"):
                    payload["status"] = args["status"]
                if args.get("daily_budget"):
                    payload["daily_budget"] = str(args["daily_budget"])
            resp = await http.post(f"{base_url}/{campaign_id}", data=payload)
            data = resp.json()
            if err := _check_err(data):
                return err
            return {"success": True, "content": f"Campanha {campaign_id} atualizada"}

        elif tool_name == "delete_campaign":
            campaign_id = args.get("campaign_id")
            resp = await http.delete(
                f"{base_url}/{campaign_id}", params={"access_token": access_token}
            )
            data = resp.json()
            if err := _check_err(data):
                return err
            return {"success": True, "content": f"Campanha {campaign_id} removida"}

        elif tool_name == "delete_ad_set":
            ad_set_id = args.get("ad_set_id")
            resp = await http.delete(
                f"{base_url}/{ad_set_id}", params={"access_token": access_token}
            )
            data = resp.json()
            if err := _check_err(data):
                return err
            return {"success": True, "content": f"Ad Set {ad_set_id} removido"}

        elif tool_name == "list_pages":
            # /me/accounts retorna páginas que o token tem acesso
            resp = await http.get(
                f"{base_url}/me/accounts",
                params={"access_token": access_token, "fields": "id,name,category"},
            )
            data = resp.json()
            pages = data.get("data", [])
            if pages:
                lines = [
                    f"ID: {p['id']} | {p.get('name','')} | {p.get('category','')}"
                    for p in pages
                ]
                return {
                    "success": True,
                    "content": "Páginas conectadas:\n" + "\n".join(lines),
                }
            # Fallback: extrair page_id de um criativo existente
            resp2 = await http.get(
                f"{base_url}/act_{account_id}/ads",
                params={
                    "access_token": access_token,
                    "fields": "creative{object_story_spec}",
                    "limit": "5",
                },
            )
            ads_data = resp2.json()
            page_ids = set()
            for ad in ads_data.get("data", []):
                spec = (ad.get("creative") or {}).get("object_story_spec") or {}
                if spec.get("page_id"):
                    page_ids.add(spec["page_id"])
                if spec.get("instagram_user_id"):
                    page_ids.add(f"instagram_actor_id={spec['instagram_user_id']}")
            if page_ids:
                return {
                    "success": True,
                    "content": "Page IDs extraídos de anúncios existentes:\n"
                    + "\n".join(page_ids),
                }
            return {
                "success": True,
                "content": (
                    "Nenhuma página encontrada. Use get_ad_creative em um anúncio existente para extrair o page_id."
                ),
            }

        # ── Targeting Search ─────────────────────────────────────────────────
        elif tool_name == "search_targeting":
            query = args.get("query", "")
            search_type = args.get("type", "interest")
            limit = args.get("limit", 10)

            if search_type == "custom_audience":
                resp = await http.get(
                    f"{base_url}/act_{account_id}/customaudiences",
                    params={
                        "access_token": access_token,
                        "fields": "id,name,subtype,approximate_count",
                        "limit": limit,
                    },
                )
                data = resp.json()
                if err := _check_err(data):
                    return err
                items = data.get("data", [])
                filtered = [
                    i
                    for i in items
                    if not query or query.lower() in i.get("name", "").lower()
                ]
                lines = [
                    f"id={i['id']} | {i['name']} | tipo: {i.get('subtype','')} | ~{i.get('approximate_count','?')} pessoas"
                    for i in filtered[:limit]
                ]
                return {
                    "success": True,
                    "content": f"{len(lines)} custom audience(s):\n" + "\n".join(lines),
                }

            elif search_type == "location":
                resp = await http.get(
                    "https://graph.facebook.com/v19.0/search",
                    params={
                        "access_token": access_token,
                        "type": "adgeolocation",
                        "q": query,
                        "limit": limit,
                    },
                )
                data = resp.json()
                if err := _check_err(data):
                    return err
                items = data.get("data", [])
                lines = [
                    f"key={i.get('key')} | {i.get('name')} | tipo: {i.get('type')} | {i.get('country_name','')}"
                    for i in items
                ]
                return {
                    "success": True,
                    "content": f"{len(lines)} localização(ões):\n" + "\n".join(lines),
                }

            elif search_type == "locale":
                resp = await http.get(
                    "https://graph.facebook.com/v19.0/search",
                    params={
                        "access_token": access_token,
                        "type": "adlocale",
                        "q": query,
                        "limit": limit,
                    },
                )
                data = resp.json()
                if err := _check_err(data):
                    return err
                items = data.get("data", [])
                lines = [f"key={i.get('key')} | {i.get('name')}" for i in items]
                return {
                    "success": True,
                    "content": f"{len(lines)} idioma(s):\n" + "\n".join(lines),
                }

            else:
                # interest or behavior
                fb_type = "adinterest" if search_type == "interest" else "adbehavior"
                resp = await http.get(
                    "https://graph.facebook.com/v19.0/search",
                    params={
                        "access_token": access_token,
                        "type": fb_type,
                        "q": query,
                        "limit": limit,
                    },
                )
                data = resp.json()
                if err := _check_err(data):
                    return err
                items = data.get("data", [])
                lines = [
                    f"id={i.get('id')} | {i.get('name')} | audiência: ~{i.get('audience_size_lower_bound','?')}-{i.get('audience_size_upper_bound','?')}"
                    for i in items
                ]
                type_label = (
                    "interesse(s)" if search_type == "interest" else "comportamento(s)"
                )
                return {
                    "success": True,
                    "content": f"{len(lines)} {type_label}:\n" + "\n".join(lines),
                }

        # ── Ad Sets ──────────────────────────────────────────────────────────
        elif tool_name == "list_ad_sets":
            campaign_id = args.get("campaign_id")
            endpoint = (
                f"{base_url}/{campaign_id}/adsets"
                if campaign_id
                else f"{base_url}/act_{account_id}/adsets"
            )
            params = {
                "access_token": access_token,
                "fields": (
                    "id,name,status,effective_status,campaign_id,daily_budget,lifetime_budget,"
                    "start_time,end_time,optimization_goal,billing_event,"
                    "bid_strategy,bid_amount,pacing_type,destination_type,"
                    "targeting,promoted_object"
                ),
                "limit": args.get("limit", 25),
            }
            status_filter = args.get("status")
            if status_filter:
                params["effective_status"] = _meta_effective_status(status_filter)
            else:
                params["effective_status"] = json.dumps(
                    [
                        "ACTIVE",
                        "PAUSED",
                        "CAMPAIGN_PAUSED",
                        "IN_PROCESS",
                        "WITH_ISSUES",
                        "DISAPPROVED",
                        "PENDING_REVIEW",
                        "PREAPPROVED",
                    ],
                    separators=(",", ":"),
                )
            resp = await http.get(endpoint, params=params)
            data = resp.json()
            if err := _check_err(data):
                return err
            items = data.get("data", [])

            def _fmt_adset(i: dict) -> str:
                cfg = i.get("status", "?")
                eff = i.get("effective_status", "?")
                status_str = f"cfg={cfg} eff={eff}" if cfg != eff else cfg
                lines = [
                    f"── Ad Set: {i['id']} | {i['name']} | {status_str}",
                    f"   Campanha: {i.get('campaign_id','')}",
                    f"   Otimização: {i.get('optimization_goal','')} | Cobrança: {i.get('billing_event','')}",
                    f"   Lance: {i.get('bid_strategy','')} {'bid='+str(i['bid_amount']) if i.get('bid_amount') else ''}",
                ]
                budget = (
                    f"daily={i['daily_budget']}¢"
                    if i.get("daily_budget")
                    else f"lifetime={i['lifetime_budget']}¢"
                    if i.get("lifetime_budget")
                    else "—"
                )
                lines.append(f"   Orçamento: {budget}")
                if i.get("start_time"):
                    end_t = i.get("end_time", "sem fim")
                    end_note = ""
                    if end_t and end_t != "sem fim":
                        from datetime import datetime, timezone as _tz

                        try:
                            if datetime.fromisoformat(
                                end_t.replace("Z", "+00:00")
                            ) < datetime.now(_tz.utc):
                                end_note = " ⚠️ PASSADO — não use este end_time ao copiar targeting"
                        except Exception:
                            pass
                    lines.append(
                        f"   Período: {i.get('start_time','')} → {end_t}{end_note}"
                    )
                if i.get("destination_type"):
                    lines.append(f"   Destino: {i['destination_type']}")
                # Targeting
                t = i.get("targeting") or {}
                if t:
                    demo = []
                    if t.get("age_min") or t.get("age_max"):
                        demo.append(
                            f"idade {t.get('age_min',18)}-{t.get('age_max',65)}"
                        )
                    g = t.get("genders", [])
                    if g == [1]:
                        demo.append("masculino")
                    elif g == [2]:
                        demo.append("feminino")
                    else:
                        demo.append("todos gêneros")
                    if demo:
                        lines.append(f"   Demo: {', '.join(demo)}")
                    geo = t.get("geo_locations") or {}
                    if geo:
                        parts = []
                        if geo.get("countries"):
                            parts.append("países: " + ",".join(geo["countries"]))
                        if geo.get("regions"):
                            parts.append(f"{len(geo['regions'])} estado(s)")
                        if geo.get("cities"):
                            parts.append(f"{len(geo['cities'])} cidade(s)")
                        lines.append(f"   Geo: {' | '.join(parts)}")
                    if t.get("interests"):
                        names = [
                            x.get("name", x.get("id", "")) for x in t["interests"][:5]
                        ]
                        lines.append(
                            f"   Interesses ({len(t['interests'])}): {', '.join(names)}"
                        )
                    if t.get("behaviors"):
                        names = [
                            x.get("name", x.get("id", "")) for x in t["behaviors"][:5]
                        ]
                        lines.append(
                            f"   Comportamentos ({len(t['behaviors'])}): {', '.join(names)}"
                        )
                    if t.get("flexible_spec"):
                        for gi, group in enumerate(t["flexible_spec"]):
                            prefix = f"   Flexible spec grupo {gi + 1}"
                            for ftype, fitems in group.items():
                                if isinstance(fitems, list):
                                    ids_names = [
                                        f"{x.get('name', '')} (id:{x.get('id', '')})"
                                        for x in fitems
                                    ]
                                    lines.append(
                                        f"{prefix} [{ftype}]: {', '.join(ids_names)}"
                                    )
                    if t.get("exclusions"):
                        excl = t["exclusions"]
                        for etype, eitems in excl.items():
                            if isinstance(eitems, list):
                                ids_names = [
                                    f"{x.get('name', '')} (id:{x.get('id', '')})"
                                    for x in eitems
                                ]
                                lines.append(
                                    f"   Exclusões [{etype}]: {', '.join(ids_names)}"
                                )
                    if t.get("custom_audiences"):
                        names = [
                            x.get("name", x.get("id", ""))
                            for x in t["custom_audiences"]
                        ]
                        lines.append(f"   Custom audiences incl.: {', '.join(names)}")
                    if t.get("excluded_custom_audiences"):
                        names = [
                            x.get("name", x.get("id", ""))
                            for x in t["excluded_custom_audiences"]
                        ]
                        lines.append(f"   Custom audiences excl.: {', '.join(names)}")
                    # Placements
                    pub = t.get("publisher_platforms")
                    if pub:
                        lines.append(f"   Plataformas: {', '.join(pub)}")
                    if t.get("facebook_positions"):
                        lines.append(
                            f"   FB posições: {', '.join(t['facebook_positions'])}"
                        )
                    if t.get("instagram_positions"):
                        lines.append(
                            f"   IG posições: {', '.join(t['instagram_positions'])}"
                        )
                    if t.get("audience_network_positions"):
                        lines.append(
                            f"   AudienceNet: {', '.join(t['audience_network_positions'])}"
                        )
                    if t.get("messenger_positions"):
                        lines.append(
                            f"   Messenger: {', '.join(t['messenger_positions'])}"
                        )
                    if t.get("device_platforms"):
                        lines.append(
                            f"   Dispositivos: {', '.join(t['device_platforms'])}"
                        )
                    if t.get("user_os"):
                        lines.append(f"   OS: {', '.join(t['user_os'])}")
                    if t.get("wireless_carrier"):
                        lines.append(f"   Carrier: {', '.join(t['wireless_carrier'])}")
                po = i.get("promoted_object") or {}
                if po.get("pixel_id"):
                    lines.append(
                        f"   Pixel: {po['pixel_id']} | evento: {po.get('custom_event_type','')}"
                    )
                return "\n".join(lines)

            blocks = [_fmt_adset(i) for i in items]
            return {
                "success": True,
                "content": f"{len(items)} ad set(s):\n\n" + "\n\n".join(blocks),
                "ad_sets": items,
            }

        elif tool_name == "get_ad_set_insights":
            ad_set_id = args.get("ad_set_id")
            date_preset = args.get("date_preset", "last_30d")
            params = {
                "access_token": access_token,
                "date_preset": date_preset,
                "fields": "impressions,clicks,spend,ctr,cpc,reach",
            }
            resp = await http.get(f"{base_url}/{ad_set_id}/insights", params=params)
            data = resp.json()
            if err := _check_err(data):
                return err
            rows = data.get("data", [])
            if not rows:
                return {
                    "success": True,
                    "content": "Sem dados para o período selecionado",
                }
            return {
                "success": True,
                "content": _meta_insights_content(
                    "Ad Set", ad_set_id, date_preset, rows[0]
                ),
            }

        elif tool_name in ("update_ad_set", "pause_ad_set", "enable_ad_set"):
            ad_set_id = args.get("ad_set_id")
            payload: Dict = {"access_token": access_token}
            if tool_name == "pause_ad_set":
                payload["status"] = "PAUSED"
            elif tool_name == "enable_ad_set":
                payload["status"] = "ACTIVE"
            else:
                if args.get("name"):
                    payload["name"] = args["name"]
                if args.get("status"):
                    payload["status"] = args["status"]
                if args.get("daily_budget"):
                    payload["daily_budget"] = str(args["daily_budget"])
            resp = await http.post(f"{base_url}/{ad_set_id}", data=payload)
            data = resp.json()
            if err := _check_err(data):
                return err
            return {"success": True, "content": f"Ad Set {ad_set_id} atualizado"}

        # ── Ads ───────────────────────────────────────────────────────────────
        elif tool_name == "list_ads":
            ad_set_id = args.get("ad_set_id")
            endpoint = (
                f"{base_url}/{ad_set_id}/ads"
                if ad_set_id
                else f"{base_url}/act_{account_id}/ads"
            )
            params = {
                "access_token": access_token,
                "fields": "id,name,status,effective_status,adset_id,campaign_id,creative{id,name,body,title}",
                "limit": args.get("limit", 50),
            }
            status_filter = args.get("status")
            if status_filter:
                params["effective_status"] = _meta_effective_status(status_filter)
            else:
                # Sem filtro explícito: replicar o que o Manager mostra por padrão.
                # Inclui CAMPAIGN_PAUSED e ADSET_PAUSED (pai pausado, ad em si pode ser ACTIVE).
                # Exclui apenas DELETED e ARCHIVED.
                params["effective_status"] = json.dumps(
                    [
                        "ACTIVE",
                        "PAUSED",
                        "CAMPAIGN_PAUSED",
                        "ADSET_PAUSED",
                        "IN_PROCESS",
                        "WITH_ISSUES",
                        "DISAPPROVED",
                        "PENDING_REVIEW",
                        "PREAPPROVED",
                    ],
                    separators=(",", ":"),
                )
            resp = await http.get(endpoint, params=params)
            data = resp.json()
            if err := _check_err(data):
                return err
            items = data.get("data", [])

            def _fmt_ad(i: dict) -> str:
                cfg = i.get("status", "?")  # status configurado pelo usuário
                eff = i.get("effective_status", "?")  # status efetivo (considera pai)
                status_str = f"cfg={cfg} eff={eff}" if cfg != eff else cfg
                creative = i.get("creative", {})
                title = creative.get("title", "") or creative.get("name", "")
                line = f"ID: {i['id']} | {i['name']} | {status_str} | ad set: {i.get('adset_id','')}"
                if title:
                    line += f" | criativo: {title}"
                return line

            lines = [_fmt_ad(i) for i in items]
            return {
                "success": True,
                "content": f"{len(items)} anúncio(s):\n" + "\n".join(lines),
            }

        elif tool_name == "get_ad":
            ad_id = args.get("ad_id")
            params = {
                "access_token": access_token,
                "fields": "id,name,status,effective_status,adset_id,campaign_id,creative{id,name,body,title,image_url,call_to_action_type}",
            }
            resp = await http.get(f"{base_url}/{ad_id}", params=params)
            data = resp.json()
            if err := _check_err(data):
                return err
            cfg = data.get("status", "?")
            eff = data.get("effective_status", "?")
            status_str = f"cfg={cfg} eff={eff}" if cfg != eff else cfg
            creative = data.get("creative", {})
            return {
                "success": True,
                "content": (
                    f"ID: {data.get('id')} | {data.get('name')} | {status_str}\n"
                    f"Ad Set: {data.get('adset_id')} | Campanha: {data.get('campaign_id')}\n"
                    f"Criativo: {creative.get('name','')} — {creative.get('title','')} | {creative.get('body','')}"
                ),
            }

        elif tool_name == "get_ad_insights":
            ad_id = args.get("ad_id")
            date_preset = args.get("date_preset", "last_30d")
            params = {
                "access_token": access_token,
                "date_preset": date_preset,
                "fields": "impressions,clicks,spend,ctr,cpc,reach",
            }
            resp = await http.get(f"{base_url}/{ad_id}/insights", params=params)
            data = resp.json()
            if err := _check_err(data):
                return err
            rows = data.get("data", [])
            if not rows:
                return {
                    "success": True,
                    "content": "Sem dados para o período selecionado",
                }
            return {
                "success": True,
                "content": _meta_insights_content(
                    "Anúncio", ad_id, date_preset, rows[0]
                ),
            }

        elif tool_name in ("pause_ad", "enable_ad"):
            ad_id = args.get("ad_id")
            payload = {
                "access_token": access_token,
                "status": "PAUSED" if tool_name == "pause_ad" else "ACTIVE",
            }
            resp = await http.post(f"{base_url}/{ad_id}", data=payload)
            data = resp.json()
            if err := _check_err(data):
                return err
            action = "pausado" if tool_name == "pause_ad" else "ativado"
            return {"success": True, "content": f"Anúncio {ad_id} {action}"}

        elif tool_name == "get_ad_creative":
            ad_id = args.get("ad_id")
            # Passo 1: busca o creative_id vinculado ao ad
            resp = await http.get(
                f"{base_url}/{ad_id}",
                params={"access_token": access_token, "fields": "creative"},
            )
            data = resp.json()
            if err := _check_err(data):
                return err
            creative_id = (data.get("creative") or {}).get("id")
            if not creative_id:
                return {
                    "success": False,
                    "error": "Creative não encontrado para este anúncio.",
                }

            # Passo 2: busca detalhes completos do creative
            resp2 = await http.get(
                f"{base_url}/{creative_id}",
                params={
                    "access_token": access_token,
                    "fields": "name,title,body,call_to_action_type,image_url,thumbnail_url,video_id,object_story_spec,asset_feed_spec,degrees_of_freedom_spec",
                },
            )
            c = resp2.json()
            if err := _check_err(c):
                return err

            lines = [f"Creative ID: {creative_id}"]
            if c.get("name"):
                lines.append(f"Nome: {c['name']}")

            # ── Multi-asset (asset_feed_spec) ─────────────────────────────────
            feed = c.get("asset_feed_spec") or {}
            if feed:
                lines.append("\n[MULTI-ASSET]")
                bodies = [b.get("text", "") for b in feed.get("bodies", [])]
                if bodies:
                    lines.append("Bodies:")
                    for i, b in enumerate(bodies, 1):
                        lines.append(f"  {i}. {b}")
                titles = [t.get("text", "") for t in feed.get("titles", [])]
                if titles:
                    lines.append("Titles:")
                    for i, t in enumerate(titles, 1):
                        lines.append(f"  {i}. {t}")
                descs = [d.get("text", "") for d in feed.get("descriptions", [])]
                if descs:
                    lines.append("Descriptions:")
                    for i, d in enumerate(descs, 1):
                        lines.append(f"  {i}. {d}")
                ctas = feed.get("call_to_action_types", [])
                if ctas:
                    lines.append(f"CTAs: {', '.join(ctas)}")
                imgs = [
                    img.get("url", "")
                    for img in feed.get("images", [])
                    if img.get("url")
                ]
                if imgs:
                    lines.append("Images:")
                    for i, u in enumerate(imgs, 1):
                        lines.append(f"  {i}. {u}")
                vids = feed.get("videos", [])
                if vids:
                    lines.append("Videos:")
                    for i, v in enumerate(vids, 1):
                        lines.append(
                            f"  {i}. video_id={v.get('video_id','')} thumb={v.get('thumbnail_url','')}"
                        )
                lurls = feed.get("link_urls", [])
                if lurls:
                    lines.append(f"Link: {lurls[0].get('website_url','')}")
                ad_formats = feed.get("ad_formats", [])
                if ad_formats:
                    lines.append(f"Format: {', '.join(ad_formats)}")
            else:
                # ── Criativo único ────────────────────────────────────────────
                lines.append("\n[CRIATIVO ÚNICO]")
                if c.get("title"):
                    lines.append(f"Título: {c['title']}")
                if c.get("body"):
                    lines.append(f"Texto: {c['body']}")
                if c.get("call_to_action_type"):
                    lines.append(f"CTA: {c['call_to_action_type']}")
                img_url = c.get("image_url") or c.get("thumbnail_url")
                if img_url:
                    lines.append(f"Imagem: {img_url}")
                video_id = c.get("video_id")
                if video_id:
                    lines.append(f"Video ID: {video_id}")
                    resp3 = await http.get(
                        f"{base_url}/{video_id}",
                        params={
                            "access_token": access_token,
                            "fields": "thumbnails,source,permalink_url",
                        },
                    )
                    vdata = resp3.json()
                    if not _check_err(vdata):
                        if vdata.get("source"):
                            lines.append(f"Vídeo URL: {vdata['source']}")
                        if vdata.get("permalink_url"):
                            lines.append(f"Permalink: {vdata['permalink_url']}")
                        thumbs = (vdata.get("thumbnails") or {}).get("data", [])
                        if thumbs:
                            lines.append(f"Thumbnail: {thumbs[0].get('uri', '')}")

            # ── object_story_spec — page_id e link ────────────────────────────
            spec = c.get("object_story_spec") or {}
            spec_page_id = spec.get("page_id")
            if spec_page_id:
                lines.append(f"\nPage ID: {spec_page_id}")
            if spec.get("instagram_actor_id") or spec.get("instagram_user_id"):
                lines.append(
                    f"Instagram Actor ID: {spec.get('instagram_actor_id') or spec.get('instagram_user_id')}"
                )
            link_data = spec.get("link_data") or spec.get("video_data") or {}
            if link_data.get("link"):
                lines.append(f"Link: {link_data['link']}")
            if not feed:
                # só exibe no modo único (multi-asset já tem link na feed)
                if link_data.get("image_url") and not c.get("image_url"):
                    lines.append(f"Imagem (spec): {link_data['image_url']}")
                if link_data.get("call_to_action"):
                    cta = link_data["call_to_action"]
                    if isinstance(cta, dict):
                        lines.append(f"CTA (spec): {cta.get('type','')}")

            # ── Advantage+ / degrees_of_freedom_spec ─────────────────────────
            dof = c.get("degrees_of_freedom_spec") or {}
            cfs = dof.get("creative_features_spec") or {}
            if cfs:
                lines.append("\n[ADVANTAGE+ CREATIVE]")
                _FEATURE_LABELS = {
                    "standard_enhancements": "Otimizações padrão (pacote completo)",
                    "text_optimizations": "Variações de texto pela Meta",
                    "image_touchups": "Ajustes de imagem (brilho/contraste/filtros)",
                    "image_cropping": "Recorte automático de imagem",
                    "image_uncrop": "Expansão de imagem com IA",
                    "music": "Música de fundo automática",
                    "video_auto_crop": "Recorte automático de vídeo",
                    "enhance_cta": "Melhoria automática do botão CTA",
                    "inline_comment": "Comentários relevantes no anúncio",
                    "3d_animation": "Efeito 3D em imagens estáticas",
                    "site_extensions": "Extensões automáticas de site",
                }
                for feature, label in _FEATURE_LABELS.items():
                    status = (cfs.get(feature) or {}).get("enroll_status")
                    if status:
                        icon = "✓ ON" if status == "OPT_IN" else "✗ OFF"
                        lines.append(f"  {icon}  {label}")

            return {"success": True, "content": "\n".join(lines)}

    return {"success": False, "error": "Ferramenta não reconhecida"}
