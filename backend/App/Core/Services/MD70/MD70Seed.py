"""
MD70 Seed — inserts illustrative demo data into the MD70 tables.
Idempotent: skips all inserts if md70_developments already has rows.
"""

import json

from sqlalchemy import text
from App.Core.Logs import info, warning


# ---------------------------------------------------------------------------
# CDI monthly rates (illustrative, out/2024 → set/2026)
# ---------------------------------------------------------------------------
CDI_RATES = [
    ("2024-10", 0.93), ("2024-11", 0.79), ("2024-12", 0.93),
    ("2025-01", 1.01), ("2025-02", 0.99), ("2025-03", 0.96),
    ("2025-04", 1.06), ("2025-05", 1.14), ("2025-06", 1.10),
    ("2025-07", 1.28), ("2025-08", 1.16), ("2025-09", 1.22),
    ("2025-10", 1.16), ("2025-11", 1.05), ("2025-12", 1.22),
    ("2026-01", 1.16), ("2026-02", 1.00), ("2026-03", 1.04),
    ("2026-04", 1.06), ("2026-05", 1.10), ("2026-06", 1.02),
    ("2026-07", 1.08), ("2026-08", 1.04), ("2026-09", 0.98),
]

MONTHS = [m for m, _ in CDI_RATES]
CDI_MAP = {m: r for m, r in CDI_RATES}


def _build_snapshots(invested: float, excess_monthly: float):
    """
    Generate 24 monthly snapshots starting from month index 0.
    Returns list of (month, invested_cum, value, cdi_value).
    """
    value = invested
    cdi_value = invested
    snapshots = []
    for month, cdi_rate in CDI_RATES:
        value = value * (1 + (cdi_rate + excess_monthly) / 100)
        cdi_value = cdi_value * (1 + cdi_rate / 100)
        snapshots.append((month, invested, round(value, 2), round(cdi_value, 2)))
    return snapshots


def seed_md70_data(engine) -> None:
    """Insert all demo data if md70_developments is empty."""
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM md70_developments")).scalar()
        if count and count > 0:
            info("[MD70Seed] Tables already seeded — skipping.")
            return

    info("[MD70Seed] Seeding MD70 demo data...")

    with engine.connect() as conn:
        # ------------------------------------------------------------------ #
        # md70_developments
        # ------------------------------------------------------------------ #
        developments = [
            ("residencial-aurora",    "Residencial Aurora",    "Construção / Reforma",    67,  32_000_000, 29_400_000,  9_250_000, "2027-06-30", None),
            ("edificio-horizonte",    "Edifício Horizonte",    "Projeto",                 34,  14_000_000, 18_000_000,  8_600_000, "2027-12-31", None),
            ("vila-jardins",          "Vila Jardins",          "Business Plan / Capital", 12,   7_000_000, 11_000_000,  8_200_000, "2028-06-30", None),
            ("complexo-bela-vista",   "Complexo Bela Vista",   "Proposta / Negociação",    5,   3_000_000, 22_000_000, 21_500_000, None,         None),
            ("torre-pinheiros",       "Torre Pinheiros",       "Visita",                   0,           0,          0,          0, None,         None),
            ("residencia-ibirapuera", "Residência Ibirapuera", "Oferecido / Interessado",  0,           0,          0,          0, None,         None),
            ("morada-carioca",        "Morada Carioca",        "Vendido",                100,  18_000_000, 17_800_000,          0, "2026-03-31", None),
        ]
        for dev_id, name, status, progress, capital, budget, remaining, forecast, image_url in developments:
            conn.execute(text(
                "INSERT OR IGNORE INTO md70_developments "
                "(id, name, city, status, progress, capital, budget, remaining, forecast, image_url) "
                "VALUES (:id, :name, :city, :status, :progress, :capital, :budget, :remaining, :forecast, :image_url)"
            ), {
                "id": dev_id, "name": name, "city": "São Paulo",
                "status": status, "progress": progress,
                "capital": capital, "budget": budget, "remaining": remaining,
                "forecast": forecast, "image_url": image_url,
            })

        # ------------------------------------------------------------------ #
        # md70_budget_lines
        # ------------------------------------------------------------------ #
        budget_lines = [
            # id, development_id, category, item, planned, realized, committed, remaining
            ("a1", "residencial-aurora",  "Obra / Materiais",  "Estrutura",                  12_000_000, 9_600_000, 1_100_000,   650_000),
            ("a2", "residencial-aurora",  "Obra / Mão de obra","Equipes",                    10_000_000, 7_000_000, 1_250_000, 1_750_000),
            ("a3", "residencial-aurora",  "Projeto",           "Arquitetura e engenharia",    3_400_000, 2_600_000,   200_000,   600_000),
            ("a4", "residencial-aurora",  "Outros",            "Comercialização",             4_000_000,   900_000,   350_000, 2_750_000),
            ("h1", "edificio-horizonte",  "Obra / Materiais",  "Retrofit",                    9_000_000, 5_800_000, 2_100_000, 1_100_000),
            ("h2", "edificio-horizonte",  "Obra / Serviços",   "Instalações",                 6_000_000, 2_900_000, 1_500_000, 1_600_000),
            ("h3", "edificio-horizonte",  "Projeto",           "Licenciamento",               3_000_000,   700_000,   250_000, 2_050_000),
            ("v1", "vila-jardins",        "Terreno",           "Aquisição",                   6_000_000, 2_100_000,   700_000, 3_200_000),
            ("v2", "vila-jardins",        "Projeto",           "Estudos",                     2_000_000,   450_000,   250_000, 1_300_000),
            ("v3", "vila-jardins",        "Obra / Materiais",  "Preparação",                  3_000_000,   150_000,   200_000, 2_650_000),
        ]
        for bl_id, dev_id, category, item, planned, realized, committed, remaining in budget_lines:
            conn.execute(text(
                "INSERT OR IGNORE INTO md70_budget_lines "
                "(id, development_id, category, item, planned, realized, committed, remaining) "
                "VALUES (:id, :dev_id, :category, :item, :planned, :realized, :committed, :remaining)"
            ), {
                "id": bl_id, "dev_id": dev_id, "category": category, "item": item,
                "planned": planned, "realized": realized, "committed": committed,
                "remaining": remaining,
            })

        # ------------------------------------------------------------------ #
        # md70_suppliers
        # ------------------------------------------------------------------ #
        suppliers = [
            ("s1", "Construtora Alfa",  "12.345.678/0001-90", "Carlos Menezes", "(11) 98765-4321", "carlos@construtoraalfa.com.br"),
            ("s2", "Materiais Beta",    "23.456.789/0001-01", "Ana Paula Ramos","(11) 91234-5678", "compras@materiaisbet.com.br"),
            ("s3", "Serviços Gama",     "34.567.890/0001-12", "Roberto Lima",   "(11) 94567-8901", "roberto@servicosgama.com.br"),
            ("s4", "Engenharia Delta",  "45.678.901/0001-23", "Marina Costa",   "(11) 97890-1234", "marina@engenhariadelta.com.br"),
        ]
        for sup_id, name, cnpj, contact, phone, email in suppliers:
            conn.execute(text(
                "INSERT OR IGNORE INTO md70_suppliers (id, name, cnpj, contact, phone, email) "
                "VALUES (:id, :name, :cnpj, :contact, :phone, :email)"
            ), {"id": sup_id, "name": name, "cnpj": cnpj, "contact": contact,
                "phone": phone, "email": email})

        # ------------------------------------------------------------------ #
        # md70_purchases  (id, dev_id, budget_line_id, description, quantity, unit,
        #                   estimate, requester, date, status,
        #                   selected_quote_id, approved_by, approved_at, paid_at, note)
        # ------------------------------------------------------------------ #
        purchases = [
            ("c1", "residencial-aurora",  "a1", "Lote de aço estrutural",          1, "lote",    850_000, "Equipe de obra", "2026-09-29", "Orçamento 3",      None,  None,         None,         None,         None),
            ("c2", "edificio-horizonte",  "h2", "Instalações elétricas",           1, "serviço", 420_000, "Engenharia",     "2026-09-30", "Orçamento 1",      None,  None,         None,         None,         None),
            ("c3", "vila-jardins",        "v1", "Topografia complementar",         1, "serviço",  75_000, "Projetos",       "2026-09-25", "Aguardando entrega","q5", "Equipe MD70","2026-09-28", None,         None),
            ("c4", "residencial-aurora",  "a2", "Reforço de equipes de acabamento",1, "serviço", 320_000, "Equipe de obra", "2026-10-02", "Solicitado",       None,  None,         None,         None,         None),
            ("c5", "edificio-horizonte",  "h1", "Vidros e esquadrias",             1, "lote",    580_000, "Engenharia",     "2026-09-15", "Orçamento 2",      None,  None,         None,         None,         None),
            ("c6", "residencial-aurora",  "a3", "Revisão de projetos estruturais", 1, "serviço",  95_000, "Projetos",       "2026-08-10", "Entregue",         "q9",  "Equipe MD70","2026-08-15", "2026-08-20", None),
            ("c7", "vila-jardins",        "v2", "Levantamento planialtimétrico",   1, "serviço",  45_000, "Projetos",       "2026-09-10", "Cancelado",        None,  None,         None,         None,         "Escopo absorvido em outro contrato"),
        ]
        for (pur_id, dev_id, bl_id, desc, qty, unit, estimate, requester,
             date, status, sel_q, appr_by, appr_at, paid_at, note) in purchases:
            conn.execute(text(
                "INSERT OR IGNORE INTO md70_purchases "
                "(id, development_id, budget_line_id, description, quantity, unit, "
                " estimate, requester, date, status, "
                " selected_quote_id, approved_by, approved_at, paid_at, note) "
                "VALUES (:id, :dev_id, :bl_id, :desc, :qty, :unit, "
                " :estimate, :requester, :date, :status, "
                " :sel_q, :appr_by, :appr_at, :paid_at, :note)"
            ), {
                "id": pur_id, "dev_id": dev_id, "bl_id": bl_id,
                "desc": desc, "qty": qty, "unit": unit,
                "estimate": estimate, "requester": requester,
                "date": date, "status": status,
                "sel_q": sel_q, "appr_by": appr_by, "appr_at": appr_at,
                "paid_at": paid_at, "note": note,
            })

        # ------------------------------------------------------------------ #
        # md70_quotes  (id, purchase_id, supplier_id, value, shipping, discount,
        #               payment, delivery, validity, notes)
        # ------------------------------------------------------------------ #
        quotes = [
            ("q1",  "c1", "s1", 810_000, 18_000,  0,  "30 dias", "12 dias", "2026-10-20", None),
            ("q2",  "c1", "s2", 795_000, 28_000,  0,  "À vista", "18 dias", "2026-10-18", None),
            ("q3",  "c1", "s3", 840_000,      0, 15_000, "45 dias", "10 dias", "2026-10-22", None),
            ("q4",  "c2", "s3", 415_000,      0,  0,  "30 dias", "20 dias", "2026-10-25", None),
            ("q5",  "c3", "s4",  68_000,      0,  0,  "30 dias",  "7 dias", "2026-10-15", None),
            ("q6",  "c3", "s3",  73_000,      0,  0,  "30 dias", "10 dias", "2026-10-15", None),
            ("q7",  "c5", "s1", 560_000, 12_000,  0,  "30 dias", "25 dias", "2026-10-30", None),
            ("q8",  "c5", "s4", 545_000, 18_000,  0,  "30 dias", "30 dias", "2026-10-28", None),
            ("q9",  "c6", "s4",  88_000,      0,  0,  "30 dias", "14 dias", "2026-08-25", None),
            ("q10", "c6", "s3",  95_000,      0,  0,  "30 dias", "10 dias", "2026-08-25", None),
        ]
        for (q_id, pur_id, sup_id, value, shipping, discount,
             payment, delivery, validity, notes) in quotes:
            conn.execute(text(
                "INSERT OR IGNORE INTO md70_quotes "
                "(id, purchase_id, supplier_id, value, shipping, discount, "
                " payment, delivery, validity, notes) "
                "VALUES (:id, :pur_id, :sup_id, :value, :shipping, :discount, "
                " :payment, :delivery, :validity, :notes)"
            ), {
                "id": q_id, "pur_id": pur_id, "sup_id": sup_id,
                "value": value, "shipping": shipping, "discount": discount,
                "payment": payment, "delivery": delivery,
                "validity": validity, "notes": notes,
            })

        # ------------------------------------------------------------------ #
        # md70_movements + md70_documents
        # ------------------------------------------------------------------ #
        movements = [
            # id, dev_id, date, description, category, direction, value, status, attachments
            ("m1", "residencial-aurora",  "2026-09-01", "Aportes",           "Capital",  "Entrada", 32_000_000, "Realizado", []),
            ("m2", "residencial-aurora",  "2026-09-20", "Obra e serviços",   "Obra",     "Saída",   20_100_000, "Realizado",
             ["https://placehold.co/80x80/f3f4f6/6b7280?text=NF",
              "https://placehold.co/80x80/f3f4f6/6b7280?text=REC"]),
            ("m3", "edificio-horizonte",  "2026-09-01", "Aportes",           "Capital",  "Entrada", 14_000_000, "Realizado", []),
            ("m4", "edificio-horizonte",  "2026-09-18", "Obra e serviços",   "Obra",     "Saída",    9_400_000, "Realizado",
             ["https://placehold.co/80x80/f3f4f6/6b7280?text=NF"]),
            ("m5", "vila-jardins",        "2026-09-01", "Aportes",           "Capital",  "Entrada",  7_000_000, "Realizado", []),
            ("m6", "vila-jardins",        "2026-09-19", "Estudos e terreno", "Terreno",  "Saída",    2_700_000, "Realizado",
             ["https://placehold.co/80x80/f3f4f6/6b7280?text=NF",
              "https://placehold.co/80x80/f3f4f6/6b7280?text=REC",
              "https://placehold.co/80x80/f3f4f6/6b7280?text=CTR"]),
        ]
        doc_idx = 1
        for (mov_id, dev_id, date, description, category,
             direction, value, status, attachments) in movements:
            conn.execute(text(
                "INSERT OR IGNORE INTO md70_movements "
                "(id, development_id, date, description, category, direction, value, status) "
                "VALUES (:id, :dev_id, :date, :desc, :category, :dir, :value, :status)"
            ), {
                "id": mov_id, "dev_id": dev_id, "date": date,
                "desc": description, "category": category,
                "dir": direction, "value": value, "status": status,
            })
            for url in attachments:
                doc_id = f"doc-{mov_id}-{doc_idx}"
                conn.execute(text(
                    "INSERT OR IGNORE INTO md70_documents (id, movement_id, url, label) "
                    "VALUES (:id, :mov_id, :url, :label)"
                ), {"id": doc_id, "mov_id": mov_id, "url": url, "label": None})
                doc_idx += 1

        # ------------------------------------------------------------------ #
        # md70_leads
        # ------------------------------------------------------------------ #
        leads = [
            ("l1",  "Ricardo Fonseca",    "ricardo@example.com",     "(11) 99123-4567", "residencial-aurora",  "Investidor ativo", "Indicação", 2_000_000, None,                                    "2026-07-10"),
            ("l2",  "Larissa Pinto",      "larissa@example.com",     "(11) 90012-3456", "residencial-aurora",  "Investidor ativo", "Indicação", 3_500_000, None,                                    "2026-06-22"),
            ("l3",  "Camila Torres",      "camila@example.com",      "(11) 98234-5678", "residencial-aurora",  "Investidor ativo", "Site",      1_500_000, None,                                    "2026-07-15"),
            ("l4",  "Thiago Mendes",      "thiago@example.com",      "(11) 93789-0123", "residencial-aurora",  "Qualificado",      "Site",      1_200_000, "Perguntou sobre prazo de retorno",      "2026-09-12"),
            ("l5",  "Fernando Alves",     "fernando@example.com",    "(11) 97345-6789", "edificio-horizonte",  "Em negociação",    "Evento",    3_000_000, "Quer participar como sócio cotista",    "2026-08-02"),
            ("l6",  "Juliana Carvalho",   "juliana@example.com",     "(11) 92890-1234", "edificio-horizonte",  "Em negociação",    "Indicação", 2_500_000, "Aguarda documentação do empreendimento","2026-09-14"),
            ("l7",  "Beatriz Lima",       "beatriz@example.com",     "(11) 96456-7890", "edificio-horizonte",  "Qualificado",      "Indicação", 1_000_000, None,                                    "2026-08-18"),
            ("l8",  "Roberto Gomes",      "roberto@example.com",     "(11) 99876-5432", "edificio-horizonte",  "Interesse",        "Evento",      800_000, None,                                    "2026-09-20"),
            ("l9",  "Ana Cristina",       "anacristina@example.com", "(11) 98765-4321", "vila-jardins",        "Qualificado",      "Indicação", 1_000_000, "Já é investidora de outro FII",         "2026-09-22"),
            ("l10", "Marcelo Santos",     "marcelo@example.com",     "(11) 95567-8901", "vila-jardins",        "Interesse",        "Site",        500_000, None,                                    "2026-09-05"),
            ("l11", "Patrícia Rocha",     "patricia@example.com",    None,              "vila-jardins",        "Interesse",        "Evento",      750_000, None,                                    "2026-09-08"),
            ("l12", "André Fernandes",    "andre@example.com",       None,              "vila-jardins",        "Descartado",       "Site",        300_000, "Perfil fora do ticket mínimo",          "2026-09-01"),
        ]
        for (l_id, name, email, phone, proj_interest, status, source,
             value, notes, created_at) in leads:
            conn.execute(text(
                "INSERT OR IGNORE INTO md70_leads "
                "(id, name, email, phone, project_interest, status, source, value, notes, created_at) "
                "VALUES (:id, :name, :email, :phone, :proj, :status, :source, :value, :notes, :created_at)"
            ), {
                "id": l_id, "name": name, "email": email, "phone": phone,
                "proj": proj_interest, "status": status, "source": source,
                "value": value, "notes": notes, "created_at": created_at,
            })

        # ------------------------------------------------------------------ #
        # md70_investors  (linked to leads l1, l2, l3)
        # ------------------------------------------------------------------ #
        investors = [
            ("inv-ricardo", "l1", "Ricardo Fonseca", "ricardo@example.com"),
            ("inv-larissa",  "l2", "Larissa Pinto",   "larissa@example.com"),
            ("inv-camila",   "l3", "Camila Torres",   "camila@example.com"),
        ]
        for inv_id, lead_id, name, email in investors:
            conn.execute(text(
                "INSERT OR IGNORE INTO md70_investors (id, lead_id, name, email) "
                "VALUES (:id, :lead_id, :name, :email)"
            ), {"id": inv_id, "lead_id": lead_id, "name": name, "email": email})

        # ------------------------------------------------------------------ #
        # md70_investments  (Ricardo, Larissa, Camila all in residencial-aurora)
        # ------------------------------------------------------------------ #
        investments_data = [
            ("invest-ricardo", "inv-ricardo", "residencial-aurora", 2_000_000),
            ("invest-larissa",  "inv-larissa",  "residencial-aurora", 3_500_000),
            ("invest-camila",   "inv-camila",   "residencial-aurora", 1_500_000),
        ]
        for inv_id, investor_id, dev_id, invested in investments_data:
            conn.execute(text(
                "INSERT OR IGNORE INTO md70_investments (id, investor_id, development_id, invested) "
                "VALUES (:id, :investor_id, :dev_id, :invested)"
            ), {"id": inv_id, "investor_id": investor_id,
                "dev_id": dev_id, "invested": invested})

        # ------------------------------------------------------------------ #
        # md70_cdi_rates
        # ------------------------------------------------------------------ #
        for i, (month, rate) in enumerate(CDI_RATES):
            conn.execute(text(
                "INSERT OR IGNORE INTO md70_cdi_rates (id, month, rate) "
                "VALUES (:id, :month, :rate)"
            ), {"id": f"cdi-{i+1}", "month": month, "rate": rate})

        # ------------------------------------------------------------------ #
        # md70_investment_snapshots
        # ------------------------------------------------------------------ #
        excess_monthly = 0.22  # same for all three investors
        for inv_id, investor_id, dev_id, invested in investments_data:
            snapshots = _build_snapshots(invested, excess_monthly)
            for idx, (month, invested_cum, value, cdi_value) in enumerate(snapshots):
                snap_id = f"snap-{inv_id}-{idx+1}"
                conn.execute(text(
                    "INSERT OR IGNORE INTO md70_investment_snapshots "
                    "(id, investment_id, month, invested, value, cdi_value) "
                    "VALUES (:id, :inv_id, :month, :invested, :value, :cdi_value)"
                ), {
                    "id": snap_id, "inv_id": inv_id, "month": month,
                    "invested": invested_cum, "value": value, "cdi_value": cdi_value,
                })

        # ------------------------------------------------------------------ #
        # md70_announcements
        # ------------------------------------------------------------------ #
        announcements = [
            ("a1", "residencial-aurora", "2026-09-30",
             "Relatório mensal — Residencial Aurora",
             "A estrutura avançou 8% e os custos de materiais ficaram abaixo do previsto. Veja o resumo completo do mês."),
            ("a2", "edificio-horizonte", "2026-09-18",
             "Edifício Horizonte: alvará emitido",
             "Com a liberação, a fase de demolições internas segue conforme o cronograma."),
            ("a3", "vila-jardins", "2026-08-30",
             "Vila Jardins entra em aprovação",
             "O projeto foi protocolado na prefeitura. Prazo estimado de análise: 90 dias."),
            # a4 has no developmentId in the mock, but the table requires one;
            # we link it to residencial-aurora as a portfolio-level announcement.
            ("a4", "residencial-aurora", "2026-07-10",
             "Encontro semestral de investidores",
             "Apresentamos a carteira, os resultados do semestre e as próximas oportunidades."),
        ]
        for ann_id, dev_id, created_at, title, body in announcements:
            conn.execute(text(
                "INSERT OR IGNORE INTO md70_announcements "
                "(id, development_id, title, body, created_at) "
                "VALUES (:id, :dev_id, :title, :body, :created_at)"
            ), {
                "id": ann_id, "dev_id": dev_id, "title": title,
                "body": body, "created_at": created_at,
            })

        # ------------------------------------------------------------------ #
        # md70_investor_documents
        # ------------------------------------------------------------------ #
        doc_count = conn.execute(text("SELECT COUNT(*) FROM md70_investor_documents")).fetchone()[0]
        if not doc_count:
            investor_documents = [
                ("idoc-1", "residencial-aurora",  "Relatório Mensal — Set/2026",       "Relatório",   "2026-09-30", "842 KB",  None),
                ("idoc-2", "residencial-aurora",  "Memorial Descritivo",               "Técnico",     "2026-07-15", "1.2 MB",  None),
                ("idoc-3", "edificio-horizonte",  "Relatório Mensal — Set/2026",       "Relatório",   "2026-09-18", "654 KB",  None),
                ("idoc-4", "edificio-horizonte",  "Estudo de Viabilidade Econômica",   "Financeiro",  "2026-06-01", "2.3 MB",  None),
                ("idoc-5", "vila-jardins",        "Protocolo de Aprovação Prefeitura", "Jurídico",    "2026-08-30", "320 KB",  None),
            ]
            for doc_id, dev_id, name, category, date, size, file_url in investor_documents:
                conn.execute(text(
                    "INSERT OR IGNORE INTO md70_investor_documents "
                    "(id, development_id, name, category, date, size, file_url) "
                    "VALUES (:id, :dev_id, :name, :category, :date, :size, :file_url)"
                ), {
                    "id": doc_id, "dev_id": dev_id, "name": name, "category": category,
                    "date": date, "size": size, "file_url": file_url,
                })

        # ------------------------------------------------------------------ #
        # Rich JSON columns for residencial-aurora and edificio-horizonte
        # ------------------------------------------------------------------ #
        # Only update if category is not yet set (first-time enrichment)
        aurora_row = conn.execute(text(
            "SELECT category FROM md70_developments WHERE id = 'residencial-aurora'"
        )).fetchone()
        if aurora_row is not None and aurora_row[0] is None:
            conn.execute(text(
                "UPDATE md70_developments SET "
                "category = :category, summary = :summary, planned_progress = :planned_progress, "
                "current_stage = :current_stage, next_stage = :next_stage, "
                "gallery_json = :gallery_json, plan_json = :plan_json, "
                "scenarios_json = :scenarios_json, milestones_json = :milestones_json, "
                "gantt_months_json = :gantt_months_json, diary_json = :diary_json, "
                "budget_series_json = :budget_series_json, budget_items_json = :budget_items_json, "
                "result_json = :result_json, month_changes_json = :month_changes_json, "
                "month_impact = :month_impact "
                "WHERE id = 'residencial-aurora'"
            ), {
                "category": "Residencial",
                "summary": "Condomínio residencial de alto padrão com 120 unidades em São Paulo. Obra em fase de acabamentos, com entrega prevista para junho de 2027.",
                "planned_progress": 60,
                "current_stage": "Acabamentos",
                "next_stage": "Comissionamento",
                "gallery_json": json.dumps([
                    {"url": None, "caption": "Estrutura — setembro/2026"},
                    {"url": None, "caption": "Fachada — agosto/2026"},
                ]),
                "plan_json": json.dumps({
                    "opportunity": "Demanda reprimida por unidades de alto padrão na zona sul de São Paulo.",
                    "market": "Mercado imobiliário residencial premium com VGV estimado em R$ 45 MM.",
                    "strategy": "Aquisição e desenvolvimento com foco em acabamentos diferenciados e localização.",
                    "assumptions": [
                        "VGV médio de R$ 375 k/unidade",
                        "Velocidade de vendas de 8 unidades/mês",
                        "Custo de obra dentro do orçamento aprovado",
                    ],
                }),
                "scenarios_json": json.dumps([
                    {"row": "Receita Total",    "conservative": "R$ 39 MM", "base": "R$ 45 MM", "optimistic": "R$ 50 MM"},
                    {"row": "Margem Líquida",   "conservative": "18%",      "base": "22%",      "optimistic": "27%"},
                    {"row": "TIR do Projeto",   "conservative": "19%",      "base": "23%",      "optimistic": "28%"},
                ]),
                "milestones_json": json.dumps([
                    {"stage": "Fundação",       "start": 0, "end": 2,  "done": 100},
                    {"stage": "Estrutura",      "start": 2, "end": 8,  "done": 100},
                    {"stage": "Alvenaria",      "start": 7, "end": 12, "done": 85},
                    {"stage": "Acabamentos",    "start": 11, "end": 18, "done": 30},
                    {"stage": "Comissionamento","start": 17, "end": 20, "done": 0},
                ]),
                "gantt_months_json": json.dumps(["Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]),
                "diary_json": json.dumps([
                    {
                        "date": "2026-09-30",
                        "title": "Alvenaria avança para o 12° andar",
                        "description": "Equipes concluíram alvenaria dos andares 10 e 11. Ritmo acima do previsto.",
                        "images": [],
                    },
                    {
                        "date": "2026-08-31",
                        "title": "Estrutura concluída",
                        "description": "Concretagem do último pavimento realizada sem intercorrências.",
                        "images": [],
                    },
                ]),
                "budget_series_json": json.dumps([
                    {"month": "2026-04", "planned": 1_800_000, "actual": 1_720_000},
                    {"month": "2026-05", "planned": 2_100_000, "actual": 2_050_000},
                    {"month": "2026-06", "planned": 2_300_000, "actual": 2_410_000},
                    {"month": "2026-07", "planned": 2_500_000, "actual": 2_380_000},
                    {"month": "2026-08", "planned": 2_700_000, "actual": 2_650_000},
                    {"month": "2026-09", "planned": 2_900_000, "actual": 2_890_000},
                ]),
                "budget_items_json": json.dumps([
                    {"category": "Estrutura",       "planned": 12_000_000, "actual": 9_600_000},
                    {"category": "Mão de obra",     "planned": 10_000_000, "actual": 7_000_000},
                    {"category": "Projeto",         "planned":  3_400_000, "actual": 2_600_000},
                    {"category": "Comercialização", "planned":  4_000_000, "actual":   900_000},
                ]),
                "result_json": json.dumps([
                    {"label": "TIR do Projeto",  "planned": "22%",      "updated": "23%",      "kind": "Estimado atualizado"},
                    {"label": "Margem Líquida",  "planned": "20%",      "updated": "21,5%",    "kind": "Estimado atualizado"},
                    {"label": "Prazo de entrega","planned": "Jun/2027", "updated": "Jun/2027", "kind": "Confirmado"},
                ]),
                "month_changes_json": json.dumps([
                    {"tone": "positive", "text": "Alvenaria avança acima do cronograma previsto."},
                    {"tone": "neutral",  "text": "Custos de materiais estáveis em relação ao mês anterior."},
                ]),
                "month_impact": "Projeto dentro do orçamento e do cronograma previsto. TIR estimada mantida em 23%.",
            })

        horizonte_row = conn.execute(text(
            "SELECT category FROM md70_developments WHERE id = 'edificio-horizonte'"
        )).fetchone()
        if horizonte_row is not None and horizonte_row[0] is None:
            conn.execute(text(
                "UPDATE md70_developments SET "
                "category = :category, summary = :summary, planned_progress = :planned_progress, "
                "current_stage = :current_stage, next_stage = :next_stage, "
                "gallery_json = :gallery_json, plan_json = :plan_json, "
                "scenarios_json = :scenarios_json, milestones_json = :milestones_json, "
                "gantt_months_json = :gantt_months_json, diary_json = :diary_json, "
                "budget_series_json = :budget_series_json, budget_items_json = :budget_items_json, "
                "result_json = :result_json, month_changes_json = :month_changes_json, "
                "month_impact = :month_impact "
                "WHERE id = 'edificio-horizonte'"
            ), {
                "category": "Comercial",
                "summary": "Retrofit de edifício comercial de 15 andares no centro expandido. Em fase de instalações e licenciamento.",
                "planned_progress": 25,
                "current_stage": "Instalações",
                "next_stage": "Revestimentos",
                "gallery_json": json.dumps([
                    {"url": None, "caption": "Fachada atual — setembro/2026"},
                ]),
                "plan_json": json.dumps({
                    "opportunity": "Edifício comercial subutilizado com potencial de retrofit e conversão de uso.",
                    "market": "Demanda crescente por escritórios modernos no centro expandido de São Paulo.",
                    "strategy": "Retrofit completo com foco em eficiência energética e áreas comuns diferenciadas.",
                    "assumptions": [
                        "Absorção de 85% das lajes em 18 meses após entrega",
                        "Aluguel médio de R$ 95/m²",
                        "Custo de retrofit dentro do orçamento de R$ 18 MM",
                    ],
                }),
                "scenarios_json": json.dumps([
                    {"row": "Receita Anual (aluguel)", "conservative": "R$ 7 MM",  "base": "R$ 9 MM",  "optimistic": "R$ 11 MM"},
                    {"row": "Margem Operacional",      "conservative": "20%",      "base": "25%",      "optimistic": "31%"},
                    {"row": "TIR do Projeto",          "conservative": "16%",      "base": "20%",      "optimistic": "25%"},
                ]),
                "milestones_json": json.dumps([
                    {"stage": "Demolições internas", "start": 0,  "end": 2,  "done": 100},
                    {"stage": "Estrutura reforço",   "start": 2,  "end": 5,  "done": 70},
                    {"stage": "Instalações",         "start": 4,  "end": 10, "done": 40},
                    {"stage": "Revestimentos",       "start": 9,  "end": 14, "done": 0},
                    {"stage": "Entrega",             "start": 13, "end": 16, "done": 0},
                ]),
                "gantt_months_json": json.dumps(["Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]),
                "diary_json": json.dumps([
                    {
                        "date": "2026-09-18",
                        "title": "Alvará de reforma emitido",
                        "description": "Prefeitura liberou o alvará. Equipes de instalações elétricas iniciaram trabalho nos andares 1–5.",
                        "images": [],
                    },
                ]),
                "budget_series_json": json.dumps([
                    {"month": "2026-04", "planned": 900_000,   "actual": 870_000},
                    {"month": "2026-05", "planned": 1_100_000, "actual": 1_050_000},
                    {"month": "2026-06", "planned": 1_300_000, "actual": 1_380_000},
                    {"month": "2026-07", "planned": 1_500_000, "actual": 1_420_000},
                    {"month": "2026-08", "planned": 1_700_000, "actual": 1_650_000},
                    {"month": "2026-09", "planned": 1_900_000, "actual": 1_800_000},
                ]),
                "budget_items_json": json.dumps([
                    {"category": "Retrofit / Materiais", "planned": 9_000_000, "actual": 5_800_000},
                    {"category": "Instalações",          "planned": 6_000_000, "actual": 2_900_000},
                    {"category": "Licenciamento",        "planned": 3_000_000, "actual":   700_000},
                ]),
                "result_json": json.dumps([
                    {"label": "TIR do Projeto",  "planned": "20%",      "updated": "20%",      "kind": "Estimado"},
                    {"label": "Margem Líquida",  "planned": "25%",      "updated": "24%",      "kind": "Revisado levemente"},
                    {"label": "Prazo de entrega","planned": "Dez/2027", "updated": "Dez/2027", "kind": "Confirmado"},
                ]),
                "month_changes_json": json.dumps([
                    {"tone": "positive", "text": "Alvará de reforma emitido, desbloqueando fase de instalações."},
                    {"tone": "neutral",  "text": "Pequeno atraso em reforço estrutural absorvido no cronograma geral."},
                ]),
                "month_impact": "Progresso alinhado com o planejado após emissão do alvará. TIR estimada mantida em 20%.",
            })

        conn.commit()

    info("[MD70Seed] Demo data seeded successfully.")
