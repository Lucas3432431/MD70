/**
 * Camada de dados do portal.
 * Mock investments and CDI rates have been replaced by /api/portal/data — see src/lib/hooks/usePortalData.ts.
 * This file retains only pure functions (summarize) and static/display data.
 */

export type TxType = "Aporte" | "Reinvestimento" | "Resgate";

export interface MonthPoint {
  month: string; invested: number; value: number; cdiValue: number; cdiRate: number; returnRate: number;
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
