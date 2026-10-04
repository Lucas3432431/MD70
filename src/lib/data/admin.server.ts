/** Dados inteiramente ilustrativos do administrativo. Nunca importar no portal do investidor. */
import type { AdminData } from "./admin-types";
export const ADMIN_DEMO = true;

export const adminDemo: AdminData = {
  minQuotes: 2,
  projects: [
    { id: "residencial-aurora",   name: "Residencial Aurora",   status: "Construção / Reforma",       progress: 67, capital: 32_000_000, budget: 29_400_000, remaining: 9_250_000 },
    { id: "edificio-horizonte",   name: "Edifício Horizonte",   status: "Projeto",                    progress: 34, capital: 14_000_000, budget: 18_000_000, remaining: 8_600_000 },
    { id: "vila-jardins",         name: "Vila Jardins",         status: "Business Plan / Capital",    progress: 12, capital: 7_000_000,  budget: 11_000_000, remaining: 8_200_000 },
    { id: "complexo-bela-vista",  name: "Complexo Bela Vista",  status: "Proposta / Negociação",      progress: 5,  capital: 3_000_000,  budget: 22_000_000, remaining: 21_500_000 },
    { id: "torre-pinheiros",      name: "Torre Pinheiros",      status: "Visita",                     progress: 0,  capital: 0,          budget: 0,          remaining: 0 },
    { id: "residencia-ibirapuera",name: "Residência Ibirapuera",status: "Oferecido / Interessado",    progress: 0,  capital: 0,          budget: 0,          remaining: 0 },
    { id: "morada-carioca",       name: "Morada Carioca",       status: "Vendido",                    progress: 100,capital: 18_000_000, budget: 17_800_000, remaining: 0 },
  ],
  budgets: [
    { id: "a1", projectId: "residencial-aurora", category: "Obra / Materiais", item: "Estrutura", planned: 12_000_000, realized: 9_600_000, committed: 1_100_000, remaining: 1_650_000 },
    { id: "a2", projectId: "residencial-aurora", category: "Obra / Mão de obra", item: "Equipes", planned: 10_000_000, realized: 7_000_000, committed: 1_250_000, remaining: 1_700_000 },
    { id: "a3", projectId: "residencial-aurora", category: "Projeto", item: "Arquitetura e engenharia", planned: 3_400_000, realized: 2_600_000, committed: 200_000, remaining: 600_000 },
    { id: "a4", projectId: "residencial-aurora", category: "Outros", item: "Comercialização", planned: 4_000_000, realized: 900_000, committed: 350_000, remaining: 2_750_000 },
    { id: "h1", projectId: "edificio-horizonte", category: "Obra / Materiais", item: "Retrofit", planned: 9_000_000, realized: 5_800_000, committed: 2_100_000, remaining: 2_600_000 },
    { id: "h2", projectId: "edificio-horizonte", category: "Obra / Serviços", item: "Instalações", planned: 6_000_000, realized: 2_900_000, committed: 1_500_000, remaining: 2_800_000 },
    { id: "h3", projectId: "edificio-horizonte", category: "Projeto", item: "Licenciamento", planned: 3_000_000, realized: 700_000, committed: 250_000, remaining: 2_000_000 },
    { id: "v1", projectId: "vila-jardins", category: "Terreno", item: "Aquisição", planned: 6_000_000, realized: 2_100_000, committed: 700_000, remaining: 3_000_000 },
    { id: "v2", projectId: "vila-jardins", category: "Projeto", item: "Estudos", planned: 2_000_000, realized: 450_000, committed: 250_000, remaining: 1_300_000 },
    { id: "v3", projectId: "vila-jardins", category: "Obra / Materiais", item: "Preparação", planned: 3_000_000, realized: 150_000, committed: 200_000, remaining: 2_500_000 },
  ],
  suppliers: [
    { id: "s1", name: "Construtora Alfa", cnpj: "12.345.678/0001-90", contact: "Carlos Menezes", phone: "(11) 98765-4321", email: "carlos@construtoraalfa.com.br" },
    { id: "s2", name: "Materiais Beta", cnpj: "23.456.789/0001-01", contact: "Ana Paula Ramos", phone: "(11) 91234-5678", email: "compras@materiaisbet.com.br" },
    { id: "s3", name: "Serviços Gama", cnpj: "34.567.890/0001-12", contact: "Roberto Lima", phone: "(11) 94567-8901", email: "roberto@servicosgama.com.br" },
    { id: "s4", name: "Engenharia Delta", cnpj: "45.678.901/0001-23", contact: "Marina Costa", phone: "(11) 97890-1234", email: "marina@engenhariadelta.com.br" },
  ],
  purchases: [
    { id: "c1", projectId: "residencial-aurora", budgetId: "a1", description: "Lote de aço estrutural", quantity: 1, unit: "lote", estimate: 850_000, requester: "Equipe de obra", date: "2026-09-29", status: "Orçamento 3", quotes: [
      { id: "q1", supplierId: "s1", value: 810_000, shipping: 18_000, discount: 0, payment: "30 dias", delivery: "12 dias", validity: "2026-10-20" },
      { id: "q2", supplierId: "s2", value: 795_000, shipping: 28_000, discount: 0, payment: "À vista", delivery: "18 dias", validity: "2026-10-18" },
      { id: "q3", supplierId: "s3", value: 840_000, shipping: 0, discount: 15_000, payment: "45 dias", delivery: "10 dias", validity: "2026-10-22" },
    ] },
    { id: "c2", projectId: "edificio-horizonte", budgetId: "h2", description: "Instalações elétricas", quantity: 1, unit: "serviço", estimate: 420_000, requester: "Engenharia", date: "2026-09-30", status: "Orçamento 1", quotes: [
      { id: "q4", supplierId: "s3", value: 415_000, shipping: 0, discount: 0, payment: "30 dias", delivery: "20 dias", validity: "2026-10-25" },
    ] },
    { id: "c3", projectId: "vila-jardins", budgetId: "v1", description: "Topografia complementar", quantity: 1, unit: "serviço", estimate: 75_000, requester: "Projetos", date: "2026-09-25", status: "Aguardando entrega", selectedQuoteId: "q5", approvedBy: "Equipe MD70", approvedAt: "2026-09-28", quotes: [
      { id: "q5", supplierId: "s4", value: 68_000, shipping: 0, discount: 0, payment: "30 dias", delivery: "7 dias", validity: "2026-10-15" },
      { id: "q6", supplierId: "s3", value: 73_000, shipping: 0, discount: 0, payment: "30 dias", delivery: "10 dias", validity: "2026-10-15" },
    ] },
    { id: "c4", projectId: "residencial-aurora", budgetId: "a2", description: "Reforço de equipes de acabamento", quantity: 1, unit: "serviço", estimate: 320_000, requester: "Equipe de obra", date: "2026-10-02", status: "Solicitado", quotes: [] },
    { id: "c5", projectId: "edificio-horizonte", budgetId: "h1", description: "Vidros e esquadrias", quantity: 1, unit: "lote", estimate: 580_000, requester: "Engenharia", date: "2026-09-15", status: "Orçamento 2", quotes: [
      { id: "q7", supplierId: "s1", value: 560_000, shipping: 12_000, discount: 0, payment: "30 dias", delivery: "25 dias", validity: "2026-10-30" },
      { id: "q8", supplierId: "s4", value: 545_000, shipping: 18_000, discount: 0, payment: "30 dias", delivery: "30 dias", validity: "2026-10-28" },
    ] },
    { id: "c6", projectId: "residencial-aurora", budgetId: "a3", description: "Revisão de projetos estruturais", quantity: 1, unit: "serviço", estimate: 95_000, requester: "Projetos", date: "2026-08-10", status: "Entregue", selectedQuoteId: "q9", approvedBy: "Equipe MD70", approvedAt: "2026-08-15", paidAt: "2026-08-20", quotes: [
      { id: "q9", supplierId: "s4", value: 88_000, shipping: 0, discount: 0, payment: "30 dias", delivery: "14 dias", validity: "2026-08-25" },
      { id: "q10", supplierId: "s3", value: 95_000, shipping: 0, discount: 0, payment: "30 dias", delivery: "10 dias", validity: "2026-08-25" },
    ] },
    { id: "c7", projectId: "vila-jardins", budgetId: "v2", description: "Levantamento planialtimétrico", quantity: 1, unit: "serviço", estimate: 45_000, requester: "Projetos", date: "2026-09-10", status: "Cancelado", note: "Escopo absorvido em outro contrato", quotes: [] },
  ],
  leads: [
    { id: "l1",  name: "Ricardo Fonseca",   email: "ricardo@example.com",    phone: "(11) 99123-4567", projectInterest: "residencial-aurora",  status: "Investidor ativo", source: "Indicação",  value: 2_000_000, createdAt: "2026-07-10" },
    { id: "l2",  name: "Larissa Pinto",     email: "larissa@example.com",    phone: "(11) 90012-3456", projectInterest: "residencial-aurora",  status: "Investidor ativo", source: "Indicação",  value: 3_500_000, createdAt: "2026-06-22" },
    { id: "l3",  name: "Camila Torres",     email: "camila@example.com",     phone: "(11) 98234-5678", projectInterest: "residencial-aurora",  status: "Investidor ativo", source: "Site",       value: 1_500_000, createdAt: "2026-07-15" },
    { id: "l4",  name: "Thiago Mendes",     email: "thiago@example.com",     phone: "(11) 93789-0123", projectInterest: "residencial-aurora",  status: "Qualificado",      source: "Site",       value: 1_200_000, notes: "Perguntou sobre prazo de retorno", createdAt: "2026-09-12" },
    { id: "l5",  name: "Fernando Alves",    email: "fernando@example.com",   phone: "(11) 97345-6789", projectInterest: "edificio-horizonte", status: "Em negociação",    source: "Evento",     value: 3_000_000, notes: "Quer participar como sócio cotista", createdAt: "2026-08-02" },
    { id: "l6",  name: "Juliana Carvalho",  email: "juliana@example.com",    phone: "(11) 92890-1234", projectInterest: "edificio-horizonte", status: "Em negociação",    source: "Indicação",  value: 2_500_000, notes: "Aguarda documentação do empreendimento", createdAt: "2026-09-14" },
    { id: "l7",  name: "Beatriz Lima",      email: "beatriz@example.com",    phone: "(11) 96456-7890", projectInterest: "edificio-horizonte", status: "Qualificado",      source: "Indicação",  value: 1_000_000, createdAt: "2026-08-18" },
    { id: "l8",  name: "Roberto Gomes",     email: "roberto@example.com",    phone: "(11) 99876-5432", projectInterest: "edificio-horizonte", status: "Interesse",        source: "Evento",     value: 800_000,   createdAt: "2026-09-20" },
    { id: "l9",  name: "Ana Cristina",      email: "anacristina@example.com",phone: "(11) 98765-4321", projectInterest: "vila-jardins",       status: "Qualificado",      source: "Indicação",  value: 1_000_000, notes: "Já é investidora de outro FII", createdAt: "2026-09-22" },
    { id: "l10", name: "Marcelo Santos",    email: "marcelo@example.com",    phone: "(11) 95567-8901", projectInterest: "vila-jardins",       status: "Interesse",        source: "Site",       value: 500_000,   createdAt: "2026-09-05" },
    { id: "l11", name: "Patrícia Rocha",    email: "patricia@example.com",                             projectInterest: "vila-jardins",       status: "Interesse",        source: "Evento",     value: 750_000,   createdAt: "2026-09-08" },
    { id: "l12", name: "André Fernandes",   email: "andre@example.com",                                projectInterest: "vila-jardins",       status: "Descartado",       source: "Site",       value: 300_000,   notes: "Perfil fora do ticket mínimo", createdAt: "2026-09-01" },
  ],
  movements: [
    { id: "m1", projectId: "residencial-aurora", date: "2026-09-01", description: "Aportes", category: "Capital", direction: "Entrada", value: 32_000_000, status: "Realizado" },
    { id: "m2", projectId: "residencial-aurora", date: "2026-09-20", description: "Obra e serviços", category: "Obra", direction: "Saída", value: 20_100_000, status: "Realizado" },
    { id: "m3", projectId: "edificio-horizonte", date: "2026-09-01", description: "Aportes", category: "Capital", direction: "Entrada", value: 14_000_000, status: "Realizado" },
    { id: "m4", projectId: "edificio-horizonte", date: "2026-09-18", description: "Obra e serviços", category: "Obra", direction: "Saída", value: 9_400_000, status: "Realizado" },
    { id: "m5", projectId: "vila-jardins", date: "2026-09-01", description: "Aportes", category: "Capital", direction: "Entrada", value: 7_000_000, status: "Realizado" },
    { id: "m6", projectId: "vila-jardins", date: "2026-09-19", description: "Estudos e terreno", category: "Terreno", direction: "Saída", value: 2_700_000, status: "Realizado" },
  ],
};