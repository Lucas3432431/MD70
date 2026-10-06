import { Link, useRouterState } from "@tanstack/react-router";
import { useEffect, useState, type ReactNode } from "react";
import { BookOpen, Compass, House, UserRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Logo } from "./Logo";
import { cn } from "@/lib/utils";

const nav = [
  { to: "/sobre", label: "Sobre" },
  { to: "/como-funciona", label: "Como funciona" },
  { to: "/metodologia", label: "Metodologia" },
  { to: "/empreendimentos", label: "Empreendimentos" },
  { to: "/insights", label: "Insights" },
  { to: "/contato", label: "Contato" },
] as const;

const mobileCategories = {
  conheca: {
    label: "Conheça",
    icon: BookOpen,
    links: [
      { to: "/sobre", label: "Sobre a MD70" },
      { to: "/como-funciona", label: "Como funciona" },
      { to: "/metodologia", label: "Metodologia" },
    ],
  },
  explorar: {
    label: "Explorar",
    icon: Compass,
    links: [
      { to: "/empreendimentos", label: "Empreendimentos" },
      { to: "/insights", label: "Insights" },
      { to: "/quero-investir", label: "Quero investir" },
    ],
  },
} as const;

type MobileCategory = keyof typeof mobileCategories;

export function SiteLayout({ children, overlay = false }: { children: ReactNode; overlay?: boolean }) {
  const [open, setOpen] = useState<MobileCategory | null>(null);
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  useEffect(() => {
    if (!open) return;
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(null);
    };
    window.addEventListener("keydown", onEscape);
    return () => window.removeEventListener("keydown", onEscape);
  }, [open]);
  const linkClass = (active: boolean) => cn(
    "flex min-w-0 flex-col items-center justify-center gap-1 border-t-2 px-0.5 text-center text-[10px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:w-32 md:shrink-0 md:text-xs",
    active ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground",
  );
  return (
    <div className="min-h-screen flex flex-col pb-[calc(4rem+env(safe-area-inset-bottom))]">
      <header className={cn("z-30 w-full", overlay ? "absolute top-0 text-primary-foreground" : "border-b bg-background text-primary")}>
        <div className="mx-auto flex h-20 max-w-7xl items-center justify-between px-6">
          <Link to="/" aria-label="MD70 — início"><Logo /></Link>
          <nav className="hidden">
            {nav.map((n) => (
              <Link key={n.to} to={n.to} className="text-[0.8rem] tracking-wide opacity-80 transition-opacity hover:opacity-100" activeProps={{ className: "opacity-100 underline underline-offset-8" }}>
                {n.label}
              </Link>
            ))}
          </nav>
          <div className="hidden">
            <Link to="/portal" className="text-[0.8rem] tracking-wide opacity-80 hover:opacity-100">Área do investidor</Link>
            <Link to="/quero-investir" className={cn("px-4 py-2 text-[0.72rem] uppercase tracking-[0.16em] border", overlay ? "border-primary-foreground/50 hover:bg-primary-foreground/10" : "border-primary hover:bg-primary hover:text-primary-foreground transition-colors")}>
              Quero investir
            </Link>
          </div>
        </div>
      </header>
      <main className="flex-1">{children}</main>
      <footer className="bg-ink text-ink-foreground">
        <div className="mx-auto grid max-w-7xl gap-10 px-6 py-16 md:grid-cols-3">
          <div>
            <Logo />
            <p className="mt-6 max-w-xs text-sm opacity-70">Investimentos em negócios reais, com acompanhamento de verdade.</p>
          </div>
          <div className="text-sm opacity-80 space-y-2">
            <p className="eyebrow !text-ink-foreground/60">Contato</p>
            <p>Entre em contato pelo formulário para falar com a equipe.</p>
          </div>
          <div className="text-sm space-y-2">
            <p className="eyebrow !text-ink-foreground/60">Navegação</p>
            <div className="grid grid-cols-2 gap-2 opacity-80">
              {nav.map((n) => <Link key={n.to} to={n.to} className="hover:opacity-100">{n.label}</Link>)}
            </div>
          </div>
        </div>
        <div className="border-t border-ink-foreground/10">
          <div className="mx-auto flex max-w-7xl flex-col gap-2 px-6 py-6 text-xs opacity-60 md:flex-row md:justify-between">
            <span>© {new Date().getFullYear()} MD70 Imóveis e Negócios</span>
            <span>Imóveis e Negócios &nbsp;|&nbsp; CRECI: 47.204.J</span>
          </div>
        </div>
      </footer>
      {open && (
        <>
          <Button variant="ghost" className="fixed inset-0 z-30 h-auto rounded-none bg-ink/30 hover:bg-ink/30" aria-label="Fechar navegação" onClick={() => setOpen(null)} />
          <div id={`site-category-${open}`} aria-label={mobileCategories[open].label} className="fixed inset-x-0 bottom-[calc(4rem+env(safe-area-inset-bottom))] z-40 border-t bg-background px-6 py-4 shadow-soft">
            <p className="eyebrow mb-2">{mobileCategories[open].label}</p>
            {mobileCategories[open].links.map(({ to, label }) => (
              <Link key={to} to={to} onClick={() => setOpen(null)} aria-current={pathname === to ? "page" : undefined} className={cn("block border-b py-3 text-sm text-foreground last:border-0", pathname === to && "font-semibold text-primary")}>{label}</Link>
            ))}
          </div>
        </>
      )}
      <nav aria-label="Navegação institucional" className="fixed inset-x-0 bottom-0 z-40 border-t bg-background/95 pb-[env(safe-area-inset-bottom)] shadow-soft backdrop-blur">
        <div className="mx-auto grid h-16 grid-cols-5 px-1 md:flex md:h-[4.5rem] md:items-stretch md:justify-center md:gap-1 md:px-8">
          <Link to="/" onClick={() => setOpen(null)} aria-current={pathname === "/" ? "page" : undefined} className={linkClass(pathname === "/")}>
            <House className="size-5 shrink-0" aria-hidden="true" /><span>Início</span>
          </Link>
          {(Object.keys(mobileCategories) as MobileCategory[]).map((key) => {
            const category = mobileCategories[key];
            const Icon = category.icon;
            const active = open === key || category.links.some(({ to }) => pathname === to);
            return (
              <Button key={key} variant="ghost" aria-expanded={open === key} aria-controls={`site-category-${key}`} onClick={() => setOpen(open === key ? null : key)} className={cn("h-16 min-w-0 flex-col gap-1 rounded-none border-t-2 px-0.5 text-[10px] font-normal md:h-[4.5rem] md:w-32 md:shrink-0 md:text-xs", active ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground")}>
                <Icon className="size-5 shrink-0" aria-hidden="true" /><span>{category.label}</span>
              </Button>
            );
          })}
          <Link to="/contato" onClick={() => setOpen(null)} aria-current={pathname === "/contato" ? "page" : undefined} className={linkClass(pathname === "/contato")}>
            <span className="flex size-5 shrink-0 items-center justify-center text-lg leading-none" aria-hidden="true">@</span><span>Contato</span>
          </Link>
          <Link to="/portal" onClick={() => setOpen(null)} aria-label="Portal do investidor" aria-current={pathname.startsWith("/portal") ? "page" : undefined} className={linkClass(pathname.startsWith("/portal"))}>
            <UserRound className="size-5 shrink-0" aria-hidden="true" /><span className="leading-tight">Portal do<br />investidor</span>
          </Link>
        </div>
      </nav>
    </div>
  );
}

export function PageIntro({ eyebrow, title, children }: { eyebrow: string; title: ReactNode; children?: ReactNode }) {
  return (
    <section className="border-b">
      <div className="mx-auto max-w-7xl px-6 pb-16 pt-20 md:pt-28">
        <p className="eyebrow fade-up">{eyebrow}</p>
        <h1 className="mt-5 max-w-4xl font-display text-5xl leading-[1.02] text-primary md:text-7xl fade-up">{title}</h1>
        {children && <div className="mt-6 max-w-2xl text-lg text-muted-foreground fade-up">{children}</div>}
      </div>
    </section>
  );
}

export function InvestCta() {
  return (
    <section className="bg-primary text-primary-foreground">
      <div className="mx-auto flex max-w-7xl flex-col items-start justify-between gap-8 px-6 py-20 md:flex-row md:items-end">
        <div>
          <p className="eyebrow !text-primary-foreground/60">Próximo passo</p>
          <h2 className="mt-4 font-display text-4xl md:text-5xl">Conheça as oportunidades da MD70.</h2>
        </div>
        <Link to="/quero-investir" className="border border-primary-foreground/50 px-7 py-4 text-[0.78rem] uppercase tracking-[0.16em] hover:bg-primary-foreground hover:text-primary transition-colors">
          Quero investir
        </Link>
      </div>
    </section>
  );
}
