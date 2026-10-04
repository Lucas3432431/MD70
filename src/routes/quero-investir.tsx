import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { z } from "zod";
import { toast } from "sonner";
import { SiteLayout } from "@/components/site/SiteLayout";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { supabase } from "@/integrations/supabase/client";

const searchSchema = z.object({ ref: z.string().max(20).optional() });

export const Route = createFileRoute("/quero-investir")({
  validateSearch: searchSchema,
  head: () => ({
    meta: [
      { title: "Quero investir — MD70 Imóveis e Negócios" },
      { name: "description", content: "Deixe seus dados e um especialista da MD70 apresenta as oportunidades atuais." },
      { property: "og:title", content: "Quero investir com a MD70" },
      { property: "og:description", content: "Um formulário curto para conhecermos você." },
    ],
  }),
  component: QueroInvestir,
});

const leadSchema = z.object({
  name: z.string().trim().min(2, "Informe seu nome").max(120),
  whatsapp: z.string().trim().min(8, "Informe um WhatsApp válido").max(30),
  email: z.string().trim().email("E-mail inválido").max(200),
  city: z.string().trim().max(100).optional(),
  capital_range: z.string().max(60).optional(),
  message: z.string().trim().max(2000).optional(),
});

const ranges = ["Até R$ 100 mil", "R$ 100 a 300 mil", "R$ 300 mil a 1 mi", "Acima de R$ 1 mi"];

function QueroInvestir() {
  const { ref } = Route.useSearch();
  const [range, setRange] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = Object.fromEntries(new FormData(e.currentTarget)) as Record<string, string>;
    const parsed = leadSchema.safeParse({ ...fd, capital_range: range || undefined });
    if (!parsed.success) {
      setErrors(Object.fromEntries(parsed.error.issues.map((i) => [i.path[0], i.message])));
      return;
    }
    setErrors({});
    setLoading(true);
    const { error } = await supabase.from("leads").insert({
      name: parsed.data.name,
      whatsapp: parsed.data.whatsapp,
      email: parsed.data.email,
      city: parsed.data.city ?? null,
      capital_range: parsed.data.capital_range ?? null,
      message: parsed.data.message ?? null,
      referral_code: ref ?? null,
      source: ref ? "indicacao" : "site",
    });
    setLoading(false);
    if (error) { toast.error("Não foi possível enviar agora. Tente novamente."); return; }
    setDone(true);
  }

  return (
    <SiteLayout>
      <section className="mx-auto grid max-w-7xl gap-16 px-6 py-20 md:grid-cols-[1fr_1.2fr] md:py-28">
        <div>
          <p className="eyebrow">Quero investir</p>
          <h1 className="mt-5 font-display text-5xl leading-[1.02] text-primary md:text-6xl">Conheça as oportunidades da MD70.</h1>
          <p className="mt-6 text-lg text-muted-foreground">Deixe seus dados. Um especialista entra em contato para entender seu perfil e apresentar os projetos disponíveis — sem compromisso.</p>
          {ref && <p className="mt-6 border-l-2 border-primary pl-4 text-sm">Você chegou por um link de indicação MD70.</p>}

          <div className="mt-10 space-y-6 text-sm">
            <div className="border-t pt-6">
              <p className="font-semibold text-primary">O que você entra comprando</p>
              <p className="mt-2 text-muted-foreground">Participação em operação imobiliária real — compra, reforma e venda — via SCP. Contrato assinado antes de qualquer movimentação, prazo de 8 a 14 meses por ciclo.</p>
            </div>
            <div className="border-t pt-6">
              <p className="font-semibold text-primary">Transparência sobre o risco</p>
              <p className="mt-2 text-muted-foreground">Não existe retorno garantido. O capital fica imobilizado no período. O que existe é análise prévia rigorosa, orçamento conservador e comunicação imediata de desvios.</p>
            </div>
            <div className="border-t pt-6">
              <p className="font-semibold text-primary">Recomendamos decidir em conjunto</p>
              <p className="mt-2 text-muted-foreground">Se você tem cônjuge ou parceiro, traga-o para a conversa. Podemos apresentar tudo em conjunto — a decisão é melhor quando tomada com informação completa.</p>
            </div>
          </div>
        </div>
        {done ? (
          <div className="flex flex-col justify-center border bg-card p-10 shadow-soft fade-up">
            <p className="eyebrow">Recebido</p>
            <h2 className="mt-4 font-display text-4xl text-primary">Obrigado pelo interesse.</h2>
            <p className="mt-4 text-muted-foreground">Seus dados foram enviados à equipe da MD70.</p>
          </div>
        ) : (
          <form onSubmit={onSubmit} className="space-y-6 border bg-card p-8 shadow-soft md:p-10" noValidate>
            <Field label="Nome" name="name" error={errors["name"]} />
            <div className="grid gap-6 sm:grid-cols-2">
              <Field label="WhatsApp" name="whatsapp" type="tel" error={errors["whatsapp"]} />
              <Field label="E-mail" name="email" type="email" error={errors["email"]} />
            </div>
            <Field label="Cidade" name="city" error={errors["city"]} />
            <div>
              <Label>Faixa aproximada de capital disponível</Label>
              <div className="mt-2 grid grid-cols-2 gap-2">
                {ranges.map((r) => (
                  <button type="button" key={r} onClick={() => setRange(r)} className={`border px-3 py-3 text-left text-sm transition-colors ${range === r ? "border-primary bg-primary text-primary-foreground" : "hover:border-primary"}`}>{r}</button>
                ))}
              </div>
            </div>
            <div>
              <Label htmlFor="message">Mensagem <span className="text-muted-foreground">(opcional)</span></Label>
              <Textarea id="message" name="message" maxLength={2000} className="mt-2" rows={3} />
            </div>
            <Button type="submit" size="lg" className="w-full" disabled={loading}>{loading ? "Enviando…" : "Enviar"}</Button>
          </form>
        )}
      </section>
    </SiteLayout>
  );
}

function Field({ label, name, type = "text", error }: { label: string; name: string; type?: string; error: string | undefined }) {
  return (
    <div>
      <Label htmlFor={name}>{label}</Label>
      <Input id={name} name={name} type={type} className="mt-2 h-11" aria-invalid={!!error} />
      {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
    </div>
  );
}
