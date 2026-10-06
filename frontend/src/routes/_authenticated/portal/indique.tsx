import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Check, Copy, Mail } from "lucide-react";
import { PortalHeading } from "@/components/portal/PortalLayout";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/_authenticated/portal/indique")({
  head: () => ({ meta: [
    { title: "Indique a MD70 — Portal" },
    { name: "description", content: "Compartilhe a MD70 com alguém que possa se interessar." },
  ] }),
  component: Indique,
});

function Indique() {
  const { user } = Route.useRouteContext();
  const code = user.user_id.slice(0, 8);
  const link = `${window.location.origin}/convite/${code}`;
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(link);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  const text = encodeURIComponent("Conheça a MD70 Imóveis e Negócios: " + link);

  return (
    <>
      <PortalHeading eyebrow="Indicação" title="Conhece alguém que também busca oportunidades de investimento?">
        <p>Compartilhe a MD70 com alguém que possa se interessar.</p>
      </PortalHeading>
      <section className="max-w-3xl border bg-card p-7 md:p-10">
        <p className="text-sm text-muted-foreground">Este é seu link individual. Quando alguém se cadastra por ele, a indicação fica associada ao seu perfil.</p>
        <div className="mt-7 flex flex-col gap-2 sm:flex-row">
          <div className="min-w-0 flex-1 border bg-background px-4 py-3 text-sm truncate">{link}</div>
          <Button onClick={copy}>{copied ? <Check /> : <Copy />}{copied ? "Copiado" : "Copiar"}</Button>
        </div>
        <div className="mt-8 flex flex-wrap gap-3">
          <Button asChild variant="outline"><a href={`https://wa.me/?text=${text}`} target="_blank" rel="noreferrer">Compartilhar no WhatsApp</a></Button>
          <Button asChild variant="outline"><a href={`mailto:?subject=${encodeURIComponent("Conheça a MD70")}&body=${text}`}><Mail />Compartilhar por e-mail</a></Button>
        </div>
      </section>
    </>
  );
}
