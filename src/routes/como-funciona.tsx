import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { SiteLayout, PageIntro, InvestCta } from "@/components/site/SiteLayout";
import { steps } from "@/lib/data/site";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/como-funciona")({
  head: () => ({
    meta: [
      { title: "Como funciona — MD70 Imóveis e Negócios" },
      { name: "description", content: "Do imóvel ao resultado: como funciona investir com a MD70, estrutura SCP, prazo e riscos explicados para quem não é do mercado." },
      { property: "og:title", content: "Como funciona investir com a MD70" },
      { property: "og:description", content: "Estrutura SCP, prazo de 8 a 14 meses, risco de capital explicado. Para quem quer entender antes de decidir." },
    ],
  }),
  component: ComoFunciona,
});

const faqItems = [
  {
    q: "O que é uma SCP e por que vocês usam essa estrutura?",
    a: "SCP é Sociedade em Conta de Participação — uma sociedade prevista no Código Civil Brasileiro (art. 991). Funciona assim: a MD70 é o sócio ostensivo (quem executa e assina contratos) e você entra como sócio participante (quem aporta capital e compartilha o resultado). Cada operação tem sua própria SCP, então o risco de um projeto não contamina o outro. A SCP não exige registro em junta comercial, mas todos os termos ficam definidos em contrato assinado antes de qualquer movimentação de capital.",
  },
  {
    q: "Qual o prazo do investimento?",
    a: "Cada ciclo dura entre 8 e 14 meses — da aquisição do imóvel à venda e distribuição do resultado. Esse prazo está previsto em contrato e inclui a reforma, a comercialização e o fechamento do negócio. Você não pode resgatar o capital antes do encerramento da operação: o dinheiro está imobilizado durante esse período. Quando a operação fecha, o valor principal mais o resultado proporcional são distribuídos.",
  },
  {
    q: "Qual é o risco real?",
    a: "O principal risco é o risco de capital: o imóvel pode não vender no preço esperado, a reforma pode custar mais do que o orçado, ou o prazo pode se estender. Em qualquer desses cenários, o resultado diminui — e pode, em casos extremos, ser negativo. Não existe garantia de retorno. O que existe é análise prévia rigorosa, orçamento conservador e acompanhamento mensal para limitar esses riscos. Nenhuma operação é iniciada sem análise de viabilidade aprovada.",
  },
  {
    q: "Preciso falar com meu cônjuge antes de investir?",
    a: "Sim, e recomendamos isso ativamente. Investimentos com imobilização de capital por 8 a 14 meses afetam o planejamento financeiro da família inteira. Se o capital está comprometido com fundo de emergência ou com outra obrigação, isso precisa estar claro para ambos. Em nossa conversa inicial, podemos incluir seu cônjuge ou parceiro — apresentamos tudo em conjunto para que a decisão seja tomada com informação completa.",
  },
  {
    q: "Quanto preciso ter disponível?",
    a: "Cada operação tem um valor mínimo de participação, apresentado na conversa inicial conforme o projeto disponível. O importante é que o capital aportado seja capital de risco — não deve ser seu fundo de emergência nem dinheiro que você vai precisar nos próximos 12 meses. A primeira conversa é gratuita e sem compromisso; é lá que apresentamos os números concretos.",
  },
  {
    q: "Como acompanho o que está acontecendo com meu dinheiro?",
    a: "Pelo portal do investidor, com atualizações mensais: fotos da obra, relatório financeiro, cronograma atualizado e qualquer desvio relevante. Você recebe acesso ao portal assim que a operação começa. Nossa política é comunicar problemas antes de solucioná-los — você nunca fica sabendo de um atraso depois do fato.",
  },
  {
    q: "Isso é regulamentado? É seguro juridicamente?",
    a: "A SCP é uma estrutura prevista em lei e amplamente utilizada no mercado imobiliário. O contrato de participação define direitos e obrigações de cada parte, distribuição de resultados e o que acontece em cenários negativos. Recomendamos que você leve o contrato para um advogado de confiança antes de assinar — esse passo nos agrada, não nos incomoda. A documentação completa está disponível antes de qualquer compromisso financeiro.",
  },
  {
    q: "Como o resultado se compara ao CDI?",
    a: "Nosso objetivo é entregar retorno significativamente acima do CDI — mas isso não é garantido. O CDI remunera risco de crédito bancário; o que a MD70 oferece é participação em operação imobiliária real, com risco de capital. O prêmio pelo risco é a diferença. Para quem tem capital parado em CDB de baixa rentabilidade e horizonte de 12 meses, a relação risco-retorno pode fazer sentido. Para quem precisa do capital no curto prazo, não faz.",
  },
];

function FaqItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b last:border-b-0">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-start justify-between gap-4 py-5 text-left"
        aria-expanded={open}
      >
        <span className="font-medium text-primary">{q}</span>
        <span className={cn("mt-0.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-45")}>+</span>
      </button>
      {open && <p className="pb-5 text-sm leading-relaxed text-muted-foreground">{a}</p>}
    </div>
  );
}

function ComoFunciona() {
  return (
    <SiteLayout>
      <PageIntro eyebrow="Como funciona" title="Do imóvel ao resultado, passo a passo.">
        Você não precisa entender de obra nem de mercado financeiro. Precisa saber onde seu dinheiro está, quanto tempo fica lá e o que pode dar errado. Explicamos tudo abaixo.
      </PageIntro>

      {/* Steps */}
      <section className="mx-auto max-w-7xl px-6 py-20">
        <div className="grid gap-px bg-border md:grid-cols-5">
          {steps.map((s) => (
            <div key={s.n} className="bg-background p-8">
              <span className="font-display text-5xl text-primary/30">{s.n}</span>
              <h3 className="mt-6 font-semibold text-primary">{s.title}</h3>
              <p className="mt-3 text-sm text-muted-foreground">{s.text}</p>
            </div>
          ))}
        </div>
      </section>

      {/* O que você está comprando */}
      <section className="border-t bg-muted/30">
        <div className="mx-auto max-w-7xl px-6 py-20">
          <p className="eyebrow">Estrutura</p>
          <h2 className="mt-5 font-display text-4xl text-primary md:text-5xl">O que você está comprando.</h2>
          <p className="mt-6 max-w-2xl text-lg text-muted-foreground">
            Você não compra um imóvel. Você entra como sócio de uma operação específica, com contrato, prazo e resultado definidos antes do primeiro real aportar.
          </p>
          <div className="mt-12 grid gap-px bg-border md:grid-cols-3">
            {[
              {
                title: "Participação via SCP",
                body: "Cada operação tem sua própria Sociedade em Conta de Participação — estrutura prevista no Código Civil. Você é sócio participante; a MD70 é o sócio ostensivo. O risco de uma operação não contamina outra.",
              },
              {
                title: "Prazo definido em contrato",
                body: "Cada ciclo dura entre 8 e 14 meses — da aquisição à venda. O capital fica imobilizado durante esse período. O resultado é distribuído quando a operação fecha.",
              },
              {
                title: "Acompanhamento pelo portal",
                body: "Fotos mensais, relatório financeiro, cronograma e qualquer desvio relevante disponíveis no portal. Você sabe o que está acontecendo antes de precisar perguntar.",
              },
            ].map(({ title, body }) => (
              <div key={title} className="bg-background p-8">
                <h3 className="font-semibold text-primary">{title}</h3>
                <p className="mt-3 text-sm text-muted-foreground">{body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* De onde vem o resultado */}
      <section className="border-t">
        <div className="mx-auto max-w-7xl px-6 py-20">
          <p className="eyebrow">Modelo</p>
          <h2 className="mt-5 font-display text-4xl text-primary md:text-5xl">De onde vem o resultado.</h2>
          <div className="mt-10 grid gap-10 md:grid-cols-2">
            <div>
              <p className="text-muted-foreground leading-relaxed">
                O modelo é direto: identificamos imóveis com potencial de valorização abaixo do preço de mercado — seja pelo estado de conservação, localização ou condição do vendedor. Adquirimos, reformamos com orçamento definido, e vendemos no mercado livre.
              </p>
              <p className="mt-4 text-muted-foreground leading-relaxed">
                A margem vem da diferença entre o custo total da operação (aquisição + reforma + encargos) e o preço de venda. Quanto mais eficiente a execução e menor o tempo de imobilização, maior o resultado proporcional.
              </p>
            </div>
            <div className="space-y-4">
              {[
                ["Aquisição", "Compra abaixo do valor de mercado — análise de viabilidade antes de qualquer compromisso."],
                ["Reforma", "Orçamento fechado antes de iniciar. Foco em valorização com custo controlado."],
                ["Venda", "Comercialização com meta de prazo. Cada dia a mais é custo de oportunidade."],
                ["Resultado", "Distribuído ao encerrar a operação — proporcional à participação de cada sócio."],
              ].map(([t, d]) => (
                <div key={t} className="flex gap-4 border-b pb-4 last:border-b-0 last:pb-0">
                  <span className="mt-0.5 shrink-0 font-display text-xl text-primary/30">→</span>
                  <div>
                    <p className="font-semibold text-primary">{t}</p>
                    <p className="mt-1 text-sm text-muted-foreground">{d}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Perguntas frequentes */}
      <section className="border-t bg-muted/30">
        <div className="mx-auto max-w-7xl px-6 py-20">
          <p className="eyebrow">Perguntas frequentes</p>
          <h2 className="mt-5 font-display text-4xl text-primary md:text-5xl">Para quem está decidindo.</h2>
          <p className="mt-4 max-w-2xl text-muted-foreground">Respostas diretas para as dúvidas mais comuns — especialmente para quem não investe em imóveis habitualmente.</p>
          <div className="mt-10 max-w-3xl divide-y border-t">
            {faqItems.map((item) => (
              <FaqItem key={item.q} {...item} />
            ))}
          </div>
        </div>
      </section>

      {/* Quick reference cards */}
      <section className="border-t">
        <div className="mx-auto max-w-7xl px-6 py-20">
          <div className="grid gap-10 md:grid-cols-3">
            {[
              ["Quanto investir", "O valor mínimo de cada operação é apresentado na conversa inicial. O capital deve ser disponível por 8 a 14 meses."],
              ["Quanto tempo", "Cada ciclo dura entre 8 e 14 meses — da aquisição ao resultado. Prazo definido em contrato."],
              ["Como acompanhar", "Portal do investidor com atualizações mensais: fotos, financeiro, cronograma e comunicados."],
            ].map(([t, d]) => (
              <div key={t} className="border-t pt-6">
                <h3 className="font-display text-2xl text-primary">{t}</h3>
                <p className="mt-3 text-muted-foreground">{d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <InvestCta />
    </SiteLayout>
  );
}
