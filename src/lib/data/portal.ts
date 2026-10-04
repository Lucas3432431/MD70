/**
 * Camada de dados do portal.
 * MOCK: todos os valores abaixo são ilustrativos (inclusive as taxas de CDI) e existem
 * apenas para validar a experiência. Substituir estas funções por consultas às tabelas
 * investments / investment_transactions / cdi_rates mantendo as mesmas assinaturas.
 */
import { developments, getDevelopment } from "./developments";

export const IS_MOCK = true;

export type TxType = "Aporte" | "Reinvestimento" | "Resgate";
export interface Transaction { date: string; type: TxType; amount: number }
export interface Investment {
  id: string;
  developmentId: string;
  entryDate: string;
  status: "Ativo" | "Encerrado";
  share: number; // participação %
  transactions: Transaction[];
  excessMonthly: number; // performance mensal acima do CDI (mock)
}

// Taxas mensais de CDI ILUSTRATIVAS (%), out/2024 → set/2026. Não são dados oficiais.
const MOCK_CDI: Record<string, number> = {};
(() => {
  const base = [0.93, 0.79, 0.93, 1.01, 0.99, 0.96, 1.06, 1.14, 1.1, 1.28, 1.16, 1.22,
    1.16, 1.05, 1.22, 1.16, 1.0, 1.04, 1.06, 1.1, 1.02, 1.08, 1.04, 0.98];
  let y = 2024, m = 10;
  for (const r of base) {
    MOCK_CDI[`${y}-${String(m).padStart(2, "0")}`] = r;
    m++; if (m > 12) { m = 1; y++; }
  }
})();
export const getCdiRates = () => Object.entries(MOCK_CDI).map(([month, rate]) => ({ month, rate, source: "mock" }));
const MONTHS = Object.keys(MOCK_CDI);

const investments: Investment[] = [
  {
    id: "inv-aurora", developmentId: "residencial-aurora", entryDate: "2024-10-05", status: "Ativo", share: 0.68, excessMonthly: 0.22,
    transactions: [
      { date: "2024-10-05", type: "Aporte", amount: 150_000 },
      { date: "2025-04-10", type: "Aporte", amount: 50_000 },
      { date: "2026-01-15", type: "Reinvestimento", amount: 12_000 },
    ],
  },
  {
    id: "inv-horizonte", developmentId: "edificio-horizonte", entryDate: "2025-03-12", status: "Ativo", share: 0.45, excessMonthly: 0.18,
    transactions: [
      { date: "2025-03-12", type: "Aporte", amount: 120_000 },
      { date: "2026-06-20", type: "Resgate", amount: -15_000 },
    ],
  },
  {
    id: "inv-vila", developmentId: "vila-jardins", entryDate: "2025-09-02", status: "Ativo", share: 0.3, excessMonthly: 0.15,
    transactions: [{ date: "2025-09-02", type: "Aporte", amount: 80_000 }],
  },
];

export interface MonthPoint {
  month: string; invested: number; value: number; cdiValue: number; cdiRate: number; returnRate: number;
}

function seriesFor(inv: Investment): MonthPoint[] {
  let value = 0, cdi = 0, invested = 0;
  const out: MonthPoint[] = [];
  for (const month of MONTHS) {
    const flows = inv.transactions.filter((t) => t.date.startsWith(month) && t.type !== "Reinvestimento");
    const cdiRate = MOCK_CDI[month] ?? 0;
    const r = value > 0 ? cdiRate + inv.excessMonthly : 0;
    value = value * (1 + r / 100);
    cdi = cdi * (1 + (value > 0 ? cdiRate : 0) / 100);
    for (const f of flows) { value += f.amount; cdi += f.amount; invested += f.amount; }
    if (invested > 0) out.push({ month, invested, value, cdiValue: cdi, cdiRate, returnRate: r });
  }
  return out;
}

export function getPortfolioSeries(): MonthPoint[] {
  const all = investments.map(seriesFor);
  return MONTHS.map((month) => {
    const pts = all.map((s) => s.find((p) => p.month === month)).filter(Boolean) as MonthPoint[];
    const invested = pts.reduce((a, p) => a + p.invested, 0);
    const value = pts.reduce((a, p) => a + p.value, 0);
    const cdiValue = pts.reduce((a, p) => a + p.cdiValue, 0);
    const weighted = value ? pts.reduce((a, p) => a + p.returnRate * p.value, 0) / value : 0;
    return { month, invested, value, cdiValue, cdiRate: MOCK_CDI[month] ?? 0, returnRate: weighted };
  }).filter((p) => p.invested > 0);
}

export function summarize(series: MonthPoint[]) {
  const last = series[series.length - 1];
  if (!last) return { invested: 0, value: 0, gain: 0, cdiGain: 0, excessGain: 0, rent: 0, cdiRent: 0, excessPp: 0 };
  const invested = last.invested;
  const gain = last.value - invested;
  const cdiGain = last.cdiValue - invested;
  const rent = (gain / invested) * 100;
  const cdiRent = (cdiGain / invested) * 100;
  return { invested, value: last.value, gain, cdiGain, excessGain: gain - cdiGain, rent, cdiRent, excessPp: rent - cdiRent };
}

export function getInvestments() {
  return investments.map((inv) => {
    const s = seriesFor(inv);
    const last = s[s.length - 1];
    const dev = getDevelopment(inv.developmentId);
    if (!last || !dev) return null;
    return { ...inv, development: dev, invested: last.invested, value: last.value, rent: ((last.value - last.invested) / last.invested) * 100 };
  }).filter((investment): investment is NonNullable<typeof investment> => investment !== null);
}

export const getInvestorDevelopments = () => {
  const ids = new Set(investments.map((i) => i.developmentId));
  return developments.filter((d) => ids.has(d.id));
};

export const getInvestmentByDevelopment = (devId: string) => getInvestments().find((i) => i.developmentId === devId);

export type DocCategory = "Contratos" | "Relatórios" | "Extratos" | "Informes" | "Documentos do empreendimento" | "Comunicados" | "Outros";
export const documents: { id: string; name: string; category: DocCategory; developmentId?: string; date: string; size: string }[] = [
  { id: "d1", name: "Relatório mensal — setembro/2026", category: "Relatórios", developmentId: "residencial-aurora", date: "2026-09-30", size: "2,4 MB" },
  { id: "d2", name: "Extrato consolidado — 3º trimestre", category: "Extratos", date: "2026-09-30", size: "380 KB" },
  { id: "d3", name: "Contrato de participação — Residencial Aurora", category: "Contratos", developmentId: "residencial-aurora", date: "2024-10-05", size: "1,1 MB" },
  { id: "d4", name: "Contrato de participação — Edifício Horizonte", category: "Contratos", developmentId: "edificio-horizonte", date: "2025-03-12", size: "1,0 MB" },
  { id: "d5", name: "Informe de rendimentos 2025", category: "Informes", date: "2026-02-20", size: "240 KB" },
  { id: "d6", name: "Alvará de reforma", category: "Documentos do empreendimento", developmentId: "edificio-horizonte", date: "2026-09-18", size: "620 KB" },
  { id: "d7", name: "Relatório mensal — agosto/2026", category: "Relatórios", developmentId: "residencial-aurora", date: "2026-08-31", size: "2,2 MB" },
  { id: "d8", name: "Contrato de participação — Vila Jardins", category: "Contratos", developmentId: "vila-jardins", date: "2025-09-02", size: "980 KB" },
];

export const announcements = [
  { id: "a1", date: "2026-09-30", title: "Relatório mensal — Residencial Aurora", summary: "A estrutura avançou 8% e os custos de materiais ficaram abaixo do previsto. Veja o resumo completo do mês.", developmentId: "residencial-aurora" },
  { id: "a2", date: "2026-09-18", title: "Edifício Horizonte: alvará emitido", summary: "Com a liberação, a fase de demolições internas segue conforme o cronograma.", developmentId: "edificio-horizonte" },
  { id: "a3", date: "2026-08-30", title: "Vila Jardins entra em aprovação", summary: "O projeto foi protocolado na prefeitura. Prazo estimado de análise: 90 dias.", developmentId: "vila-jardins" },
  { id: "a4", date: "2026-07-10", title: "Encontro semestral de investidores", summary: "Apresentamos a carteira, os resultados do semestre e as próximas oportunidades.", developmentId: undefined },
];

export const notifications = [
  { id: "n1", title: "Seu investimento foi atualizado", body: "O relatório de setembro do Residencial Aurora está disponível.", date: "2026-09-30", unread: true },
  { id: "n2", title: "Novo documento", body: "Extrato consolidado do 3º trimestre.", date: "2026-09-30", unread: true },
  { id: "n3", title: "Atualização da obra", body: "Fundação concluída no Residencial Aurora.", date: "2026-09-28", unread: false },
];
