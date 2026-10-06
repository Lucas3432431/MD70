import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/convite/$codigo")({
  head: () => ({
    meta: [
      { title: "Convite para conhecer a MD70" },
      { name: "description", content: "Conheça oportunidades em negócios reais estruturadas e acompanhadas pela MD70." },
      { property: "og:title", content: "Convite para conhecer a MD70" },
      { property: "og:description", content: "Investimentos em negócios reais, com acompanhamento de verdade." },
    ],
  }),
  beforeLoad: ({ params }) => {
    const ref = params.codigo.replace(/[^a-zA-Z0-9]/g, "").slice(0, 20);
    throw redirect({ to: "/quero-investir", search: { ref } });
  },
});
