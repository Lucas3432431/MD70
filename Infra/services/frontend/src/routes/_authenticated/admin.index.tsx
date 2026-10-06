import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { AdminHeading, useAdmin } from "@/components/admin/AdminLayout";
import { PrevistVsRealizadoChart } from "@/components/admin/PrevistVsRealizadoChart";
import { sum } from "@/lib/data/admin-calculations";
import { brlShort } from "@/lib/format";
import { cn } from "@/lib/utils";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, ReferenceLine, LabelList } from "recharts";

export const Route = createFileRoute("/_authenticated/admin/")({
  head: () => ({
    meta: [
      { title: "Visão geral administrativa — MD70" },
      { name: "description", content: "Painel interno de empreendimentos, caixa e orçamento MD70." },
      { property: "og:title", content: "Administração MD70" },
      { property: "og:type", content: "website" },
    ],
  }),
  component: AdminHome,
});

function AdminHome() {
  const { data } = useAdmin();

  const patrimonioSobGestao = sum(
    data.movements
      .filter((m) => m.status === "Realizado" && m.category === "Capital")
      .map((m) => m.direction === "Entrada" ? m.value : -m.value),
  );

  const currentYear = new Date().getFullYear().toString();
  const OPERATIONAL_CATEGORIES = ["Comissão", "Receita", "Operação", "Serviços"];
  const faturamentoAno = sum(
    data.movements
      .filter((m) => m.direction === "Entrada" && m.status === "Realizado" && m.date.startsWith(currentYear) && OPERATIONAL_CATEGORIES.includes(m.category))
      .map((m) => m.value),
  );

  return (
    <div className="lg:w-1/2 lg:mx-auto">
      <AdminHeading title="Visão geral">Caixa, orçamento e compras em um único lugar.</AdminHeading>

      {/* Hero KPI cards */}
      <div className="grid gap-px border bg-border md:grid-cols-2">
        <div className="bg-primary p-7 text-primary-foreground">
          <p className="text-xs uppercase tracking-[0.14em] opacity-60">Patrimônio sob gestão</p>
          <p className="num mt-4 font-display text-4xl md:text-5xl">{brlShort(patrimonioSobGestao)}</p>
          <p className="mt-3 text-sm opacity-70">Aportes menos resgates realizados</p>
        </div>
        <div className="bg-card p-7">
          <p className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Faturamento {currentYear}</p>
          <p className="num mt-4 font-display text-4xl text-primary md:text-5xl">{brlShort(faturamentoAno)}</p>
          <p className="mt-3 text-sm text-muted-foreground">Entradas operacionais realizadas no ano</p>
        </div>
      </div>

      <Charts />
    </div>
  );
}

// ─── TOC Flow steps ───────────────────────────────────────────────────────────

const FLOW_STEPS = [
  {
    id: "E1",
    label: "Prospecção",
    sublabel: "Imóveis",
    currentX: 1.0,
    capacityX: 1.25,
    potentialX: 1.25,
    badge: "próx. gargalo",
    badgeColor: "bg-warning/20 text-warning",
    note: ["cap: 1.25×", "atual: 1×", "pouca folga"],
    barColor: "bg-warning",
  },
  {
    id: "E2",
    label: "Capital",
    sublabel: "Aquisição",
    currentX: 1.0,
    capacityX: 1.0,
    potentialX: 3.5,
    badge: "via ① otimização",
    badgeColor: "bg-blue-500/20 text-blue-500",
    note: ["pot: 2–3×+", "atual: 1×", "+ consórcio"],
    barColor: "bg-blue-500",
  },
  {
    id: "E3",
    label: "MO",
    sublabel: "Mão de obra",
    currentX: 1.0,
    capacityX: 1.0,
    potentialX: 1.0,
    badge: "⚠ gargalo",
    badgeColor: "bg-destructive/20 text-destructive",
    note: ["cap: 1×", "atual: 1×", "sem folga"],
    barColor: "bg-destructive",
  },
  {
    id: "E4",
    label: "Reforma",
    sublabel: "Lead time",
    currentX: 1.0,
    capacityX: 1.2,
    potentialX: 2.5,
    badge: "⚠ gargalo",
    badgeColor: "bg-destructive/20 text-destructive",
    note: ["9 meses preso", "cap: ~1.2×", "2.25–4× c/ ①"],
    barColor: "bg-destructive",
  },
  {
    id: "E5",
    label: "Venda",
    sublabel: "→ Reinício",
    currentX: 1.0,
    capacityX: null,
    potentialX: 3.5,
    badge: "resultado",
    badgeColor: "bg-positive/20 text-positive",
    note: ["~R$67k/op", "2.25–4× c/ ①", ""],
    barColor: "bg-positive",
    isResult: true,
  },
] as const;

// Hex colors for recharts (can't use Tailwind classes inside SVG)
const STEP_COLORS: Record<string, { solid: string; light: string }> = {
  E1: { solid: "#f59e0b", light: "#fde68a" },
  E2: { solid: "#3b82f6", light: "#bfdbfe" },
  E3: { solid: "#ef4444", light: "#fca5a5" },
  E4: { solid: "#ef4444", light: "#fca5a5" },
  E5: { solid: "#22c55e", light: "#bbf7d0" },
};

const TOC_CHART_DATA = FLOW_STEPS.map((s) => ({
  id: s.id,
  label: s.label,
  sublabel: s.sublabel,
  badge: s.badge,
  badgeColor: s.badgeColor,
  atual: s.currentX,
  potencial: Math.max(0, s.potentialX - s.currentX),
  solidColor: STEP_COLORS[s.id]?.solid ?? "#94a3b8",
  lightColor: STEP_COLORS[s.id]?.light ?? "#e2e8f0",
}));

const MAX_SCALE = 4;

// ─── TOC Analysis text ────────────────────────────────────────────────────────

function TocAnalysis({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <div className="mt-4 border bg-card">
      <button
        onClick={onToggle}
        className="flex w-full items-center justify-between px-5 py-4 text-left text-sm font-semibold text-primary hover:bg-accent/10 transition-colors"
      >
        Análise detalhada (TOC · Goldratt)
        <span className="ml-2 shrink-0 text-muted-foreground">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="border-t px-5 py-6 text-sm leading-relaxed space-y-6 text-foreground">
          <p className="text-muted-foreground">
            A <strong className="text-foreground">Teoria das Restrições (TOC · Goldratt)</strong> diz que todo sistema tem um gargalo — um ponto que limita o resultado do todo. Melhorar qualquer outro ponto sem desbloqueá-lo apenas acumula trabalho antes da fila. Para a MD70, o gargalo não é a competência operacional nem a capacidade de encontrar imóveis: é o <strong className="text-foreground">capital imobilizado por operação multiplicado pelo lead time de aquisição→venda</strong>. Cada operação prende capital durante meses — e enquanto esse capital está preso em estoque, não pode ser alocado em novas operações. A questão central não é "como capto mais parceiros?" mas sim: "como aumento o número de operações simultâneas com o capital disponível — e como reduzo o tempo que esse capital fica parado?"
          </p>

          <div>
            <p className="font-semibold text-primary mb-3">Fluxo de Receita — Ciclo de House Flipping</p>
            <div className="overflow-x-auto pb-2">
              <div className="flex gap-0 min-w-max">
                {FLOW_STEPS.map((step, i) => (
                  <div key={step.id} className="flex items-center">
                    <div className="w-32 shrink-0 border bg-muted/30 p-3 text-xs">
                      <p className="font-bold text-primary">{step.id} · {step.label}</p>
                      <p className="text-muted-foreground mt-0.5">{step.sublabel}</p>
                      <span className={cn("mt-2 inline-block rounded-sm px-1.5 py-0.5 text-[9px] font-semibold", step.badgeColor)}>
                        {step.badge}
                      </span>
                      <div className="mt-2 space-y-0.5">
                        {step.note.filter(Boolean).map((n, j) => (
                          <p key={j} className="text-[10px] text-muted-foreground">{n}</p>
                        ))}
                      </div>
                    </div>
                    {i < FLOW_STEPS.length - 1 && (
                      <div className="px-1 text-muted-foreground">→</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div>
            <p className="font-semibold text-primary mb-3">Explorar e Subordinar o Gargalo — Quatro Alavancas</p>
            <div className="space-y-4">
              {[
                {
                  num: "①",
                  title: "Leilões — remoção do gargalo de obra + spread alto",
                  body: "Imóveis em leilão extrajudicial têm dívida menor que o valor de mercado. Quando em bom estado, elimina E4 (reforma) — o principal gargalo — e reduz o lead time para compra e venda direta. Estrutura win-win: o devedor se livra da dívida; a MD70 adquire com margem elevada e sem imobilizar capital em obra. Requer due diligence jurídica e curva de aprendizado antes de escalar.",
                },
                {
                  num: "②",
                  title: "Otimizar emprego de capital — maior alavancagem por operação",
                  body: "Com aquisição ~R$200k e reforma ~R$150k: saindo da obrigação de imobilizar o valor da aquisição, o capital por operação cai para R$150k. O mesmo pool passa a suportar ~2,33 ops simultâneas. Com consórcio, chega a 3–4×. Métodos: (a) sociedade com o proprietário — capital cobre só reforma; (b) financiamento bancário / parcelamento; (c) consórcio.",
                },
                {
                  num: "③",
                  title: "Menor lead time — reduzir capital ocioso em estoque",
                  body: "Cada dia sem venda é custo de oportunidade. Formas: (a) fila de imóveis para eliminar ociosidade entre operações; (b) iniciar vendas no D0 — vender antes de concluir gera adiantamento; (c) projeto fechado antes de imobilizar capital; (d) métodos alternativos — steel frame, casas montáveis, containers — e redução de escopo focada em fachada, cozinha, banheiro.",
                },
                {
                  num: "④",
                  title: "Capital ocioso de parceiros — ativação sem fricção",
                  body: "Parceiros com interesse expresso podem ter capital parado em CDB de baixa liquidez ou aguardando oportunidade. O 'sim' já foi dado. Mapear e mobilizar esse capital é a opção de menor ciclo de venda — sem necessidade de construir nova confiança.",
                },
                {
                  num: "⑤",
                  title: "Mais parceiros investidores — maior trabalho, menor retorno imediato",
                  body: "Expande E2, mas sem otimizar o emprego de capital ou o lead time o ganho é marginal. Deve ser construído em paralelo com ①②③④, não como substituto. Parceiros bem integrados geram indicação — o canal mais eficiente de longo prazo.",
                },
              ].map(({ num, title, body }) => (
                <div key={num} className="flex gap-3">
                  <span className="mt-0.5 shrink-0 font-bold text-primary">{num}</span>
                  <div>
                    <p className="font-semibold">{title}</p>
                    <p className="mt-1 text-muted-foreground">{body}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="border-l-2 border-primary bg-primary/5 px-4 py-3">
            <p className="font-semibold text-primary mb-2">A lógica TOC para a MD70</p>
            <p className="text-muted-foreground">
              Desbloqueie o gargalo em ordem: ① explore leilões extrajudiciais — remove E4, maximiza margem e otimiza capital; ② otimize o emprego (sociedade → financiamento → consórcio) e passe de 1× para 2,25–4× o throughput; ③ reduza o lead time (fila de imóveis → vendas antecipadas → projeto no D0 → métodos alternativos); ④ ative capital ocioso de parceiros já dispostos; ⑤ expanda o pool via novos parceiros. <strong className="text-foreground">Subordine a captação à capacidade real de absorção: mais capital sem otimização apenas aumenta o tamanho das apostas — não o volume.</strong>
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Charts section ───────────────────────────────────────────────────────────

function Charts() {
  const [analysisOpen, setAnalysisOpen] = useState(false);

  return (
    <div className="mt-8 space-y-8">
      {/* Previsto vs Realizado */}
      <div className="border bg-card p-4 md:p-6">
        <h2 className="mb-4 font-display text-xl text-primary">Previsto vs Realizado</h2>
        <PrevistVsRealizadoChart />
      </div>

      {/* TOC Pipeline */}
      <div className="border bg-card p-4 md:p-6">
        <h2 className="mb-4 font-display text-xl text-primary">Pipeline MD70 (TOC)</h2>

        {/* TOC operational flow — XY bar chart */}
        <div className="mt-6">
          <p className="mb-4 text-xs font-semibold uppercase tracking-wide text-muted-foreground">% de Capacidade Utilizada por Etapa do Fluxo</p>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={TOC_CHART_DATA} margin={{ top: 8, right: 8, left: 0, bottom: 56 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
              <XAxis
                dataKey="id"
                interval={0}
                tick={(props) => {
                  const { x, y, payload } = props as { x: number; y: number; payload: { value: string } };
                  const step = TOC_CHART_DATA.find((s) => s.id === payload.value);
                  if (!step) return <g />;
                  const badgeTextColor = step.badge === "⚠ gargalo" ? "#ef4444" : step.badge === "próx. gargalo" ? "#f59e0b" : step.badge === "resultado" ? "#22c55e" : "#3b82f6";
                  return (
                    <g transform={`translate(${x},${y})`}>
                      <text x={0} y={10} textAnchor="middle" fontSize={12} fontWeight="700" fill="hsl(var(--foreground))">{step.id}</text>
                      <text x={0} y={24} textAnchor="middle" fontSize={10} fill="hsl(var(--muted-foreground))">{step.label}</text>
                      <text x={0} y={38} textAnchor="middle" fontSize={9} fill="hsl(var(--muted-foreground))">{step.sublabel}</text>
                      <text x={0} y={52} textAnchor="middle" fontSize={9} fontWeight="600" fill={badgeTextColor}>{step.badge}</text>
                    </g>
                  );
                }}
              />
              <YAxis
                domain={[0, MAX_SCALE]}
                ticks={[0, 1, 2, 3, 4]}
                tickFormatter={(v: number) => `${v}×`}
                tick={{ fontSize: 11 }}
                width={36}
              />
              <Tooltip
                formatter={(value: number, name: string) => [`${value}×`, name === "atual" ? "Atual" : "Potencial adicional"]}
                contentStyle={{ fontSize: 12 }}
              />
              <ReferenceLine y={1} stroke="hsl(var(--border))" strokeDasharray="4 2" label={{ value: "1× atual", position: "insideTopRight", fontSize: 9, fill: "hsl(var(--muted-foreground))" }} />
              {/* Current utilization — solid, label "atual Nx" inside bar */}
              <Bar dataKey="atual" stackId="a" name="atual">
                {TOC_CHART_DATA.map((entry) => (
                  <Cell key={entry.id} fill={entry.solidColor} />
                ))}
                <LabelList
                  dataKey="atual"
                  position="insideTop"
                  content={(props) => {
                    const { x, y, width, value } = props as { x: number; y: number; width: number; value: number };
                    return (
                      <text x={(x ?? 0) + (width ?? 0) / 2} y={(y ?? 0) + 16} textAnchor="middle" fontSize={10} fontWeight="700" fill="#fff">
                        atual {value}×
                      </text>
                    );
                  }}
                />
              </Bar>
              {/* Idle / potential — lighter, label "pot Nx" on top */}
              <Bar dataKey="potencial" stackId="a" name="potencial" radius={[3, 3, 0, 0]}>
                {TOC_CHART_DATA.map((entry) => (
                  <Cell key={entry.id} fill={entry.lightColor} />
                ))}
                <LabelList
                  dataKey="potencial"
                  position="top"
                  content={(props) => {
                    const { x, y, width, index } = props as { x: number; y: number; width: number; index: number };
                    const entry = TOC_CHART_DATA[index];
                    if (!entry || entry.potencial === 0) return null;
                    return (
                      <text x={(x ?? 0) + (width ?? 0) / 2} y={(y ?? 0) - 4} textAnchor="middle" fontSize={10} fontWeight="600" fill="hsl(var(--muted-foreground))">
                        pot {entry.atual + entry.potencial}×
                      </text>
                    );
                  }}
                />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <p className="mt-1 text-[10px] text-muted-foreground">cor sólida = capacidade atual (1×) · cor clara = potencial com alavancas · ⟳ = próximo gargalo após E4</p>
        </div>

        <TocAnalysis open={analysisOpen} onToggle={() => setAnalysisOpen((v) => !v)} />
      </div>
    </div>
  );
}
