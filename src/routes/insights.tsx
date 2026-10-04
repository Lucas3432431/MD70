import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { SiteLayout, PageIntro, InvestCta } from "@/components/site/SiteLayout";
import { insights } from "@/lib/data/site";
import { dateBR } from "@/lib/format";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/insights")({
  head: () => ({
    meta: [
      { title: "Insights — MD70 Imóveis e Negócios" },
      { name: "description", content: "Análises sobre mercado, imóveis, investimentos e bastidores dos projetos da MD70." },
      { property: "og:title", content: "Insights MD70" },
      { property: "og:description", content: "Como pensamos o mercado imobiliário e nossos projetos." },
    ],
  }),
  component: Insights,
});

const cats = ["Todos", "Mercado", "Investimentos", "Imóveis", "Negócios", "Bastidores dos projetos"];

function Insights() {
  const [cat, setCat] = useState("Todos");
  const list = insights.filter((i) => cat === "Todos" || i.category === cat);
  return (
    <SiteLayout>
      <PageIntro eyebrow="Insights" title="Como pensamos o mercado.">Os conteúdos abaixo são exemplos editoriais, não artigos publicados pela MD70.</PageIntro>
      <section className="mx-auto max-w-7xl px-6 py-16">
        <div className="flex flex-wrap gap-2">
          {cats.map((c) => (
            <button key={c} onClick={() => setCat(c)} className={cn("border px-4 py-2 text-xs tracking-wide transition-colors", cat === c ? "bg-primary text-primary-foreground border-primary" : "hover:border-primary")}>{c}</button>
          ))}
        </div>
        <div className="mt-12 grid gap-px bg-border md:grid-cols-3">
          {list.map((a) => (
            <article key={a.id} className="bg-background p-8 transition-colors hover:bg-card">
              <p className="eyebrow">{a.category}</p>
              <h2 className="mt-4 font-display text-2xl text-primary">{a.title}</h2>
              <p className="mt-3 text-sm text-muted-foreground">{a.excerpt}</p>
              <p className="mt-8 text-xs text-muted-foreground">{dateBR(a.date)} · {a.read} de leitura</p>
            </article>
          ))}
        </div>
      </section>
      <InvestCta />
    </SiteLayout>
  );
}
