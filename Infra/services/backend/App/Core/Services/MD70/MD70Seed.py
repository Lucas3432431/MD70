"""
MD70 Seed — inserts real project data into the MD70 tables.
Idempotent: deletes all existing seed data first, then re-inserts.
"""

import json

from sqlalchemy import text
from App.Core.Logs import info, warning


# ---------------------------------------------------------------------------
# CDI monthly rates (out/2024 → dez/2026; 0.00 = future/unknown)
# ---------------------------------------------------------------------------
CDI_RATES = [
    ("2024-10", 0.93), ("2024-11", 0.79), ("2024-12", 0.93),
    ("2025-01", 1.01), ("2025-02", 0.99), ("2025-03", 0.96),
    ("2025-04", 1.06), ("2025-05", 1.14), ("2025-06", 1.10),
    ("2025-07", 1.28), ("2025-08", 1.16), ("2025-09", 1.22),
    ("2025-10", 1.16), ("2025-11", 1.05), ("2025-12", 1.22),
    ("2026-01", 1.16), ("2026-02", 1.00), ("2026-03", 1.04),
    ("2026-04", 1.06), ("2026-05", 1.10), ("2026-06", 1.12),
    ("2026-07", 1.22), ("2026-08", 1.09), ("2026-09", 0.98),
    ("2026-10", 0.00), ("2026-11", 0.00), ("2026-12", 0.00),
]

MONTHS = [m for m, _ in CDI_RATES]
CDI_MAP = {m: r for m, r in CDI_RATES}


def _build_snapshots(invested: float, excess_monthly: float):
    """
    Generate monthly snapshots for the CDI_RATES period.
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
    """Delete all existing seed data and re-insert real project data."""
    info("[MD70Seed] Seeding MD70 real data (delete + re-insert)...")

    with engine.connect() as conn:
        # ------------------------------------------------------------------ #
        # DELETE all tables in reverse dependency order
        # ------------------------------------------------------------------ #
        conn.execute(text("DELETE FROM md70_investment_snapshots"))
        conn.execute(text("DELETE FROM md70_investments"))
        conn.execute(text("DELETE FROM md70_investors"))
        conn.execute(text("DELETE FROM md70_quotes"))
        conn.execute(text("DELETE FROM md70_purchases"))
        conn.execute(text("DELETE FROM md70_documents"))
        conn.execute(text("DELETE FROM md70_movements"))
        conn.execute(text("DELETE FROM md70_leads"))
        conn.execute(text("DELETE FROM md70_budget_lines"))
        conn.execute(text("DELETE FROM md70_announcements"))
        conn.execute(text("DELETE FROM md70_investor_documents"))
        conn.execute(text("DELETE FROM md70_cdi_rates"))
        conn.execute(text("DELETE FROM md70_developments"))
        conn.execute(text("DELETE FROM md70_suppliers"))

        # ------------------------------------------------------------------ #
        # md70_developments — one real project
        # ------------------------------------------------------------------ #
        conn.execute(text(
            "INSERT INTO md70_developments "
            "(id, name, city, status, progress, capital, budget, remaining, forecast, image_url) "
            "VALUES (:id, :name, :city, :status, :progress, :capital, :budget, :remaining, :forecast, :image_url)"
        ), {
            "id": "saude-rio-claro",
            "name": "Saúde, Rio Claro",
            "city": "Rio Claro",
            "status": "Construção / Reforma",
            "progress": 35,
            "capital": 400_000,
            "budget": 400_000,
            "remaining": 80_000,
            "forecast": "2027-01-27",
            "image_url": None,
        })

        # ------------------------------------------------------------------ #
        # md70_budget_lines
        # ------------------------------------------------------------------ #
        budget_lines = [
            # id, development_id, category, item, planned, realized, committed, remaining
            ("bl1", "saude-rio-claro", "Aquisição e Docs", "Aquisição do imóvel e documentação", 215_000, 210_000, 0, 5_000),
            ("bl2", "saude-rio-claro", "Projeto / Estudos", "Projeto e estudos técnicos",          5_000,   5_000, 0,     0),
            ("bl3", "saude-rio-claro", "Obra",              "Construção e reforma",               180_000,  90_000, 0, 55_000),
        ]
        for bl_id, dev_id, category, item, planned, realized, committed, remaining in budget_lines:
            conn.execute(text(
                "INSERT INTO md70_budget_lines "
                "(id, development_id, category, item, planned, realized, committed, remaining) "
                "VALUES (:id, :dev_id, :category, :item, :planned, :realized, :committed, :remaining)"
            ), {
                "id": bl_id, "dev_id": dev_id, "category": category, "item": item,
                "planned": planned, "realized": realized, "committed": committed,
                "remaining": remaining,
            })

        # md70_suppliers — empty (no inserts)

        # md70_purchases — empty (no inserts)

        # md70_quotes — empty (no inserts)

        # ------------------------------------------------------------------ #
        # md70_movements — real construction expenses (Saúde, Rio Claro)
        # ------------------------------------------------------------------ #
        # id, dev_id, date, description, category, direction, value, status
        movements = [
            # Aportes e resgates de investidores
            ("mv00a", "saude-rio-claro", "2026-06-01", "Daniel Guedes — Aporte",  "Capital", "Entrada", 173_000.00, "Realizado"),
            ("mv00b", "saude-rio-claro", "2026-06-15", "Cachorrão — Aporte",      "Capital", "Entrada",  65_000.00, "Realizado"),
            ("mv00c", "saude-rio-claro", "2026-07-01", "Fernando — Aporte",       "Capital", "Entrada",  92_000.00, "Realizado"),
            ("mv00d", "saude-rio-claro", "2026-07-01", "Cachorrão — Aporte",      "Capital", "Entrada",  20_000.00, "Realizado"),
            ("mv00e", "saude-rio-claro", "2026-07-10", "Daniel Guedes — Resgate", "Capital", "Saída",    43_000.00, "Realizado"),
            ("mv00f", "saude-rio-claro", "2026-08-24", "Cachorrão — Aporte",      "Capital", "Entrada",  10_000.00, "Realizado"),
            ("mv00g", "saude-rio-claro", "2026-09-11", "Cachorrão — Aporte",      "Capital", "Entrada",  10_000.00, "Realizado"),
            # Receita operacional
            ("mv00h", "saude-rio-claro", "2026-06-15", "Comissão na compra",      "Comissão","Entrada",  12_600.00, "Realizado"),
            ("mv01", "saude-rio-claro", "2026-06-01", "Compra da casa — Entrada",           "Aquisição do imóvel",    "Saída", 168_000.00, "Realizado"),
            ("mv02", "saude-rio-claro", "2026-06-15", "Compra da casa — Parcela",            "Aquisição do imóvel",    "Saída",   5_000.00, "Realizado"),
            ("mv03", "saude-rio-claro", "2026-07-01", "Arquiteta — 1° parcela",              "Projetos",               "Saída",   1_600.00, "Realizado"),
            ("mv04", "saude-rio-claro", "2026-07-10", "Cadeado e corrente",                  "Outros",                 "Saída",      45.59, "Realizado"),
            ("mv05", "saude-rio-claro", "2026-07-10", "ITBI",                                "Aquisição do imóvel",    "Saída",   3_100.00, "Realizado"),
            ("mv06", "saude-rio-claro", "2026-07-10", "Escritura",                           "Aquisição do imóvel",    "Saída",   3_169.00, "Realizado"),
            ("mv07", "saude-rio-claro", "2026-07-10", "Compra da casa — Última parcela",     "Aquisição do imóvel",    "Saída",  50_000.00, "Realizado"),
            ("mv08", "saude-rio-claro", "2026-08-10", "Água e esgoto",                       "Custo recorrente",       "Saída",      75.06, "Realizado"),
            ("mv09", "saude-rio-claro", "2026-09-01", "Rio Cópias",                          "Outros",                 "Saída",       9.10, "Realizado"),
            ("mv10", "saude-rio-claro", "2026-09-01", "Rio Cópias",                          "Outros",                 "Saída",       6.40, "Realizado"),
            ("mv11", "saude-rio-claro", "2026-09-01", "Tributos Municipais",                 "Aprovação",              "Saída",     277.77, "Realizado"),
            ("mv12", "saude-rio-claro", "2026-09-02", "Ferragem para reforço do alicerce",   "Fundação",               "Saída",     980.00, "Realizado"),
            ("mv13", "saude-rio-claro", "2026-09-08", "Depósito Constru F",                  "Fundação",               "Saída",   1_448.87, "Realizado"),
            ("mv14", "saude-rio-claro", "2026-09-10", "Depósito Constru F",                  "Fundação",               "Saída",     275.00, "Realizado"),
            ("mv15", "saude-rio-claro", "2026-09-11", "Pedreiro — 1° etapa",                 "Mão de obra",            "Saída",   5_833.33, "Realizado"),
            ("mv16", "saude-rio-claro", "2026-09-14", "Depósito Constru F",                  "Fundação",               "Saída",     645.45, "Realizado"),
            ("mv17", "saude-rio-claro", "2026-09-15", "Claret materiais elétricos e hid.",   "Hidráulica",             "Saída",      59.00, "Realizado"),
            ("mv18", "saude-rio-claro", "2026-09-15", "Depósito Santa Rosa",                 "Elétrica",               "Saída",     134.00, "Realizado"),
            ("mv19", "saude-rio-claro", "2026-09-15", "Depósito Santa Rosa",                 "Hidráulica",             "Saída",     111.00, "Realizado"),
            ("mv20", "saude-rio-claro", "2026-09-15", "Cata-entulho",                        "Máquinas e equipamentos","Saída",     840.00, "Realizado"),
            ("mv21", "saude-rio-claro", "2026-09-16", "Cópia da chave",                      "Outros",                 "Saída",      12.00, "Realizado"),
            ("mv22", "saude-rio-claro", "2026-09-17", "Depósito Santa Rosa",                 "Hidráulica",             "Saída",     295.00, "Realizado"),
            ("mv23", "saude-rio-claro", "2026-09-17", "Elektro",                             "Custo recorrente",       "Saída",     207.63, "Realizado"),
            ("mv24", "saude-rio-claro", "2026-09-17", "Claret materiais elétricos e hid.",   "Hidráulica",             "Saída",      10.90, "Realizado"),
            ("mv25", "saude-rio-claro", "2026-09-18", "Claret materiais elétricos e hid.",   "Hidráulica",             "Saída",      18.05, "Realizado"),
            ("mv26", "saude-rio-claro", "2026-09-19", "Depósito Constru F",                  "Alvenaria",              "Saída",     624.00, "Realizado"),
            ("mv27", "saude-rio-claro", "2026-09-21", "Depósito Santa Rosa",                 "Elétrica",               "Saída",      83.50, "Realizado"),
            ("mv28", "saude-rio-claro", "2026-09-22", "Depósito Santa Rosa",                 "Hidráulica",             "Saída",     124.73, "Realizado"),
            ("mv29", "saude-rio-claro", "2026-09-22", "Depósito Santa Rosa",                 "Elétrica",               "Saída",      62.76, "Realizado"),
            ("mv30", "saude-rio-claro", "2026-09-22", "Claret materiais elétricos e hid.",   "Hidráulica",             "Saída",     128.00, "Realizado"),
            ("mv31", "saude-rio-claro", "2026-09-23", "Cata-entulho",                        "Máquinas e equipamentos","Saída",   1_120.00, "Realizado"),
            ("mv32", "saude-rio-claro", "2026-09-23", "Depósito Brazão",                     "Alvenaria",              "Saída",     228.00, "Realizado"),
            ("mv33", "saude-rio-claro", "2026-09-23", "Material esgoto",                     "Hidráulica",             "Saída",     609.00, "Realizado"),
            ("mv34", "saude-rio-claro", "2026-09-23", "Elétrica e Hidráulica — 1° etapa",    "Mão de obra",            "Saída",   8_000.00, "Realizado"),
            ("mv35", "saude-rio-claro", "2026-09-24", "Depósito Brazão",                     "Alvenaria",              "Saída",     160.00, "Realizado"),
            ("mv36", "saude-rio-claro", "2026-09-25", "Depósito Constru F",                  "Alvenaria",              "Saída",     556.35, "Realizado"),
            ("mv37", "saude-rio-claro", "2026-09-25", "MB Materiais para construção",        "Alvenaria",              "Saída",     861.60, "Realizado"),
            ("mv38", "saude-rio-claro", "2026-09-25", "Pedreiro — 2° etapa",                 "Mão de obra",            "Saída",   5_833.33, "Realizado"),
            ("mv39", "saude-rio-claro", "2026-09-25", "Pedreiro — Parte da 3° etapa",        "Mão de obra",            "Saída",   3_000.00, "Realizado"),
            ("mv40", "saude-rio-claro", "2026-09-28", "Depósito Santa Rosa",                 "Hidráulica",             "Saída",     141.26, "Realizado"),
            ("mv41", "saude-rio-claro", "2026-09-28", "Claret materiais elétricos e hid.",   "Hidráulica",             "Saída",     146.40, "Realizado"),
            ("mv42", "saude-rio-claro", "2026-09-28", "Alugatec",                            "Máquinas e equipamentos","Saída",     950.00, "Realizado"),
            ("mv43", "saude-rio-claro", "2026-09-29", "Constru F",                           "Alvenaria",              "Saída",     657.80, "Realizado"),
            ("mv44", "saude-rio-claro", "2026-09-30", "Conexões hidráulicas",                "Hidráulica",             "Saída",     162.00, "Realizado"),
            ("mv45", "saude-rio-claro", "2026-09-30", "Constru F",                           "Alvenaria",              "Saída",     195.00, "Realizado"),
            ("mv46", "saude-rio-claro", "2026-09-30", "Claret materiais elétricos e hid.",   "Hidráulica",             "Saída",     189.00, "Realizado"),
            ("mv47", "saude-rio-claro", "2026-10-01", "Pedreiro — Etapa contrapiso e laje",  "Mão de obra",            "Saída",   5_300.00, "Realizado"),
            ("mv48", "saude-rio-claro", "2026-10-02", "Oxirio",                              "Outros",                 "Saída",     141.55, "Realizado"),
            ("mv49", "saude-rio-claro", "2026-10-02", "Depósito Santa Rosa",                 "Hidráulica",             "Saída",     457.04, "Realizado"),
            ("mv50", "saude-rio-claro", "2026-10-02", "Pedreiro — Parte da 3° etapa",        "Mão de obra",            "Saída",   1_000.00, "Realizado"),
            ("mv51", "saude-rio-claro", "2026-10-05", "Pedreiro — Parte final da 3° etapa",  "Mão de obra",            "Saída",   1_833.33, "Realizado"),
            ("mv52", "saude-rio-claro", "2026-10-06", "Alugatec",                            "Máquinas e equipamentos","Saída",     320.00, "Realizado"),
            ("mv53", "saude-rio-claro", "2026-10-06", "Claret materiais elétricos e hid.",   "Hidráulica",             "Saída",     967.20, "Realizado"),
            ("mv54", "saude-rio-claro", "2026-10-06", "Claret materiais elétricos e hid.",   "Elétrica",               "Saída",     357.60, "Realizado"),
        ]
        for mov_id, dev_id, date, description, category, direction, value, status in movements:
            conn.execute(text(
                "INSERT INTO md70_movements "
                "(id, development_id, date, description, category, direction, value, status) "
                "VALUES (:id, :dev_id, :date, :desc, :category, :dir, :value, :status)"
            ), {
                "id": mov_id, "dev_id": dev_id, "date": date,
                "desc": description, "category": category,
                "dir": direction, "value": value, "status": status,
            })

        # ------------------------------------------------------------------ #
        # md70_leads
        # ------------------------------------------------------------------ #
        leads = [
            # id, name, email, phone, project_interest, status, source, value, notes, created_at
            ("l1", "Cachorrão",     "cachorrão@md70.local",     None, "saude-rio-claro", "Investidor ativo", "Indicação", 105_000, None, "2026-01-10"),
            ("l2", "Mexicano",      "mexicano@md70.local",      None, "saude-rio-claro", "Em negociação",   "Indicação",       0, None, "2026-01-10"),
            ("l3", "Fernando",      "fernando@md70.local",      None, "saude-rio-claro", "Investidor ativo", "Indicação",  92_000, None, "2026-01-10"),
            ("l4", "Du",            "du@md70.local",            None, "saude-rio-claro", "Em negociação",   "Indicação",       0, None, "2026-01-10"),
            ("l5", "Daniel Guedes", "daniel@md70.local",        None, "saude-rio-claro", "Investidor ativo", "Indicação", 130_000, None, "2026-01-10"),
        ]
        for l_id, name, email, phone, proj_interest, status, source, value, notes, created_at in leads:
            conn.execute(text(
                "INSERT INTO md70_leads "
                "(id, name, email, phone, project_interest, status, source, value, notes, created_at) "
                "VALUES (:id, :name, :email, :phone, :proj, :status, :source, :value, :notes, :created_at)"
            ), {
                "id": l_id, "name": name, "email": email, "phone": phone,
                "proj": proj_interest, "status": status, "source": source,
                "value": value, "notes": notes, "created_at": created_at,
            })

        # md70_investors — empty (no inserts)
        # md70_investments — empty (no inserts)
        # md70_investment_snapshots — empty (no inserts)

        # ------------------------------------------------------------------ #
        # md70_cdi_rates
        # ------------------------------------------------------------------ #
        for i, (month, rate) in enumerate(CDI_RATES):
            conn.execute(text(
                "INSERT INTO md70_cdi_rates (id, month, rate) "
                "VALUES (:id, :month, :rate)"
            ), {"id": f"cdi-{i+1}", "month": month, "rate": rate})

        # md70_announcements — empty (no inserts)

        # md70_investor_documents — empty (no inserts)

        conn.commit()

    info("[MD70Seed] Real data seeded successfully.")
