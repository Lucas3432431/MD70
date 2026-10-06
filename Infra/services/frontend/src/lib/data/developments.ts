/**
 * MOCK DATA — empreendimentos ilustrativos.
 * Substituir por consultas às tabelas developments / development_* quando houver dados reais.
 */
import aurora from "@/assets/dev-aurora.jpg";
import horizonte from "@/assets/dev-horizonte.jpg";
import vila from "@/assets/dev-vila.jpg";
import city from "@/assets/hero-city.jpg";

export type DevStatus = "Em desenvolvimento" | "Em obra" | "Concluído" | "Em captação";

export interface Milestone { stage: string; start: number; end: number; done: number } // months index 0..5
export interface DiaryEntry { date: string; title: string; description: string; images: string[]; video?: boolean }
export interface BudgetItem { category: string; planned: number; actual: number }
export interface MonthChange { tone: "positive" | "neutral" | "attention"; text: string }

export interface Development {
  id: string;
  name: string;
  city: string;
  category: string;
  status: DevStatus;
  summary: string;
  image: string;
  gallery: { src: string; caption: string }[];
  progress: number; // realizado
  plannedProgress: number;
  forecast: string;
  currentStage: string;
  nextStage: string;
  plan: { opportunity: string; market: string; strategy: string; assumptions: { label: string; value: string }[] };
  scenarios: { row: string; conservative: string; base: string; optimistic: string }[];
  ganttMonths: string[];
  milestones: Milestone[];
  diary: DiaryEntry[];
  budgetSeries: { month: string; planned: number; actual: number | null }[];
  budgetItems: BudgetItem[];
  result: { label: string; planned: string; updated: string; kind: "Realizado" | "Estimado atualizado" }[];
  monthChanges: MonthChange[];
  monthImpact: string;
}

const gantt = ["Abr", "Mai", "Jun", "Jul", "Ago", "Set"];

export const developments: Development[] = [
  {
    id: "residencial-aurora",
    name: "Residencial Aurora",
    city: "Campinas, SP",
    category: "Residencial vertical",
    status: "Em obra",
    summary: "Torre residencial de 18 pavimentos em bairro consolidado, com unidades de 2 e 3 dormitórios.",
    image: aurora,
    gallery: [
      { src: aurora, caption: "Estrutura — setembro/2026" },
      { src: city, caption: "Entorno e acesso viário" },
      { src: horizonte, caption: "Referência de fachada" },
    ],
    progress: 67,
    plannedProgress: 71,
    forecast: "2027-08-30",
    currentStage: "Alvenaria",
    nextStage: "Instalações",
    plan: {
      opportunity: "Terreno adquirido abaixo do valor de mercado em região com baixa oferta de lançamentos recentes.",
      market: "A região teve absorção média de 4,1% do estoque ao mês nos últimos 24 meses, acima da média da cidade.",
      strategy: "Produto compacto e eficiente, com custo de obra controlado e vendas escalonadas por fase.",
      assumptions: [
        { label: "Receita (VGV)", value: "R$ 42,0 mi" },
        { label: "Custo total", value: "R$ 29,4 mi" },
        { label: "Prazo", value: "30 meses" },
        { label: "Margem", value: "30%" },
        { label: "Velocidade de vendas", value: "6 unid./mês" },
      ],
    },
    scenarios: [
      { row: "Receita", conservative: "R$ 38,6 mi", base: "R$ 42,0 mi", optimistic: "R$ 45,1 mi" },
      { row: "Custos", conservative: "R$ 30,8 mi", base: "R$ 29,4 mi", optimistic: "R$ 28,9 mi" },
      { row: "Margem", conservative: "20%", base: "30%", optimistic: "36%" },
      { row: "Prazo", conservative: "36 meses", base: "30 meses", optimistic: "28 meses" },
    ],
    ganttMonths: gantt,
    milestones: [
      { stage: "Fundação", start: 0, end: 1, done: 100 },
      { stage: "Estrutura", start: 1, end: 3, done: 92 },
      { stage: "Alvenaria", start: 2, end: 4, done: 48 },
      { stage: "Instalações", start: 3, end: 4, done: 12 },
      { stage: "Acabamento", start: 4, end: 5, done: 0 },
    ],
    diary: [
      { date: "2026-09-28", title: "Fundação concluída", description: "Última etapa de fundações finalizada e aprovada pela fiscalização.", images: [aurora, city] },
      { date: "2026-09-22", title: "Estrutura do pavimento 2 iniciada", description: "Início da concretagem das lajes do segundo pavimento.", images: [horizonte], video: true },
      { date: "2026-09-05", title: "Chegada da segunda grua", description: "Equipamento adicional para acelerar a estrutura.", images: [aurora] },
    ],
    budgetSeries: [
      { month: "Abr", planned: 3.1, actual: 3.0 },
      { month: "Mai", planned: 6.4, actual: 6.1 },
      { month: "Jun", planned: 9.8, actual: 9.5 },
      { month: "Jul", planned: 13.2, actual: 12.9 },
      { month: "Ago", planned: 16.5, actual: 16.2 },
      { month: "Set", planned: 19.6, actual: 19.1 },
    ],
    budgetItems: [
      { category: "Materiais", planned: 9_200_000, actual: 8_980_000 },
      { category: "Mão de obra", planned: 6_400_000, actual: 6_470_000 },
      { category: "Projetos", planned: 1_800_000, actual: 1_760_000 },
      { category: "Outros", planned: 2_200_000, actual: 1_890_000 },
    ],
    result: [
      { label: "Receita", planned: "R$ 42,0 mi", updated: "R$ 42,6 mi", kind: "Estimado atualizado" },
      { label: "Custos", planned: "R$ 29,4 mi", updated: "R$ 29,0 mi", kind: "Estimado atualizado" },
      { label: "Margem", planned: "30,0%", updated: "31,9%", kind: "Estimado atualizado" },
      { label: "ROI", planned: "42,9%", updated: "46,9%", kind: "Estimado atualizado" },
      { label: "Prazo", planned: "30 meses", updated: "30,4 meses", kind: "Estimado atualizado" },
      { label: "Vendas", planned: "58 unid.", updated: "61 unid.", kind: "Realizado" },
    ],
    monthChanges: [
      { tone: "positive", text: "A estrutura avançou 8% no mês." },
      { tone: "positive", text: "Custos de materiais ficaram 2,4% abaixo do previsto." },
      { tone: "attention", text: "O prazo estimado foi ajustado em 12 dias por conta das chuvas." },
      { tone: "neutral", text: "3 novas unidades vendidas, dentro do ritmo planejado." },
    ],
    monthImpact: "As alterações deste mês representam uma variação estimada de +0,3 p.p. no retorno projetado.",
  },
  {
    id: "edificio-horizonte",
    name: "Edifício Horizonte",
    city: "São Paulo, SP",
    category: "Corporativo",
    status: "Em desenvolvimento",
    summary: "Retrofit de edifício comercial com lajes corporativas para locação de médio prazo.",
    image: horizonte,
    gallery: [
      { src: horizonte, caption: "Fachada — estudo de retrofit" },
      { src: city, caption: "Região da Faria Lima" },
    ],
    progress: 34,
    plannedProgress: 32,
    forecast: "2027-12-15",
    currentStage: "Demolições internas",
    nextStage: "Estrutura de reforço",
    plan: {
      opportunity: "Edifício com localização privilegiada e potencial construtivo subaproveitado.",
      market: "Vacância de lajes AAA na região abaixo de 9%, com contratos de longo prazo em alta.",
      strategy: "Modernização completa e locação para empresas, com possibilidade de venda do ativo estabilizado.",
      assumptions: [
        { label: "Receita (locação + venda)", value: "R$ 31,5 mi" },
        { label: "Custo total", value: "R$ 22,8 mi" },
        { label: "Prazo", value: "26 meses" },
        { label: "Margem", value: "27%" },
      ],
    },
    scenarios: [
      { row: "Receita", conservative: "R$ 28,9 mi", base: "R$ 31,5 mi", optimistic: "R$ 34,0 mi" },
      { row: "Custos", conservative: "R$ 23,9 mi", base: "R$ 22,8 mi", optimistic: "R$ 22,1 mi" },
      { row: "Margem", conservative: "17%", base: "27%", optimistic: "35%" },
      { row: "Prazo", conservative: "32 meses", base: "26 meses", optimistic: "24 meses" },
    ],
    ganttMonths: gantt,
    milestones: [
      { stage: "Projetos e aprovações", start: 0, end: 2, done: 100 },
      { stage: "Demolições internas", start: 2, end: 4, done: 60 },
      { stage: "Estrutura de reforço", start: 4, end: 5, done: 0 },
    ],
    diary: [
      { date: "2026-09-18", title: "Alvará de reforma emitido", description: "Liberação oficial para início das obras.", images: [horizonte] },
    ],
    budgetSeries: [
      { month: "Abr", planned: 0.8, actual: 0.8 },
      { month: "Mai", planned: 1.6, actual: 1.5 },
      { month: "Jun", planned: 2.6, actual: 2.5 },
      { month: "Jul", planned: 3.9, actual: 3.7 },
      { month: "Ago", planned: 5.1, actual: 5.0 },
      { month: "Set", planned: 6.4, actual: 6.2 },
    ],
    budgetItems: [
      { category: "Materiais", planned: 2_100_000, actual: 2_040_000 },
      { category: "Mão de obra", planned: 2_300_000, actual: 2_260_000 },
      { category: "Projetos", planned: 1_400_000, actual: 1_420_000 },
      { category: "Outros", planned: 600_000, actual: 480_000 },
    ],
    result: [
      { label: "Receita", planned: "R$ 31,5 mi", updated: "R$ 31,5 mi", kind: "Estimado atualizado" },
      { label: "Custos", planned: "R$ 22,8 mi", updated: "R$ 22,6 mi", kind: "Estimado atualizado" },
      { label: "Margem", planned: "27,6%", updated: "28,3%", kind: "Estimado atualizado" },
      { label: "Prazo", planned: "26 meses", updated: "26 meses", kind: "Estimado atualizado" },
    ],
    monthChanges: [
      { tone: "positive", text: "Alvará de reforma emitido dentro do prazo." },
      { tone: "neutral", text: "Negociação com 2 potenciais locatários em andamento." },
    ],
    monthImpact: "Sem variação relevante no retorno projetado neste mês.",
  },
  {
    id: "vila-jardins",
    name: "Vila Jardins",
    city: "Valinhos, SP",
    category: "Residencial horizontal",
    status: "Em captação",
    summary: "Condomínio de 24 casas com áreas verdes, voltado a famílias que buscam espaço e segurança.",
    image: vila,
    gallery: [{ src: vila, caption: "Referência arquitetônica" }],
    progress: 8,
    plannedProgress: 8,
    forecast: "2028-06-30",
    currentStage: "Aprovação do projeto",
    nextStage: "Terraplenagem",
    plan: {
      opportunity: "Demanda crescente por casas em condomínio na região metropolitana de Campinas.",
      market: "Baixa oferta de produtos novos nessa faixa de preço num raio de 10 km.",
      strategy: "Construção em duas fases, com vendas na planta para reduzir a exposição de capital.",
      assumptions: [
        { label: "Receita (VGV)", value: "R$ 36,0 mi" },
        { label: "Custo total", value: "R$ 26,1 mi" },
        { label: "Prazo", value: "28 meses" },
        { label: "Margem", value: "27%" },
      ],
    },
    scenarios: [
      { row: "Receita", conservative: "R$ 32,4 mi", base: "R$ 36,0 mi", optimistic: "R$ 38,9 mi" },
      { row: "Custos", conservative: "R$ 27,4 mi", base: "R$ 26,1 mi", optimistic: "R$ 25,5 mi" },
      { row: "Margem", conservative: "15%", base: "27%", optimistic: "34%" },
      { row: "Prazo", conservative: "34 meses", base: "28 meses", optimistic: "26 meses" },
    ],
    ganttMonths: gantt,
    milestones: [
      { stage: "Aquisição do terreno", start: 0, end: 1, done: 100 },
      { stage: "Projeto e aprovação", start: 1, end: 5, done: 40 },
    ],
    diary: [
      { date: "2026-08-30", title: "Projeto protocolado na prefeitura", description: "Início do processo de aprovação.", images: [vila] },
    ],
    budgetSeries: [
      { month: "Abr", planned: 0.2, actual: 0.2 },
      { month: "Mai", planned: 0.4, actual: 0.4 },
      { month: "Jun", planned: 0.6, actual: 0.6 },
      { month: "Jul", planned: 0.9, actual: 0.8 },
      { month: "Ago", planned: 1.1, actual: 1.1 },
      { month: "Set", planned: 1.3, actual: null },
    ],
    budgetItems: [
      { category: "Projetos", planned: 700_000, actual: 690_000 },
      { category: "Outros", planned: 400_000, actual: 410_000 },
    ],
    result: [
      { label: "Receita", planned: "R$ 36,0 mi", updated: "R$ 36,0 mi", kind: "Estimado atualizado" },
      { label: "Margem", planned: "27,5%", updated: "27,5%", kind: "Estimado atualizado" },
    ],
    monthChanges: [{ tone: "neutral", text: "Projeto em análise na prefeitura, dentro do prazo esperado." }],
    monthImpact: "Sem variação no retorno projetado neste mês.",
  },
];

export const getDevelopment = (id: string) => developments.find((d) => d.id === id);
