import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { Bell, BriefcaseBusiness, FileText, LayoutDashboard, LogOut, UserRound } from "lucide-react";
import { Logo } from "@/components/site/Logo";
import { Button } from "@/components/ui/button";
import { supabase } from "@/integrations/supabase/client";
import { notifications } from "@/lib/data/portal";
import { IS_DEV, getDevRole, clearDevRole } from "@/lib/dev-auth";
import { cn } from "@/lib/utils";

const categories = {
  carteira: { label: "Carteira", icon: BriefcaseBusiness, links: [
    { to: "/portal/investimentos", label: "Investimentos" },
    { to: "/portal/empreendimentos", label: "Empreendimentos" },
  ] },
  atualizacoes: { label: "Atualizações", icon: FileText, links: [
    { to: "/portal/documentos", label: "Documentos" },
    { to: "/portal/comunicados", label: "Comunicados" },
  ] },
  minhaConta: { label: "Minha conta", icon: UserRound, links: [
    { to: "/portal/perfil", label: "Perfil" },
    { to: "/portal/indique", label: "Indique" },
  ] },
} as const;

type CategoryKey = keyof typeof categories;

export function PortalLayout({ children }: { children: ReactNode }) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [noticeOpen, setNoticeOpen] = useState(false);
  const [openCategory, setOpenCategory] = useState<CategoryKey | null>(null);

  useEffect(() => {
    if (!openCategory) return;
    const onEscape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpenCategory(null); };
    window.addEventListener("keydown", onEscape);
    return () => window.removeEventListener("keydown", onEscape);
  }, [openCategory]);

  async function signOut() {
    if (IS_DEV && getDevRole()) {
      clearDevRole();
      queryClient.clear();
      await navigate({ to: "/auth", replace: true });
      return;
    }
    await queryClient.cancelQueries();
    queryClient.clear();
    await supabase.auth.signOut();
    await navigate({ to: "/auth", replace: true });
  }

  return (
    <div className="min-h-screen bg-background pb-[calc(5rem+env(safe-area-inset-bottom))]">
      {/* Header */}
      <header className="sticky top-0 z-20 border-b bg-background/95 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-[90rem] items-center justify-between px-4 md:px-8">
          <Link to="/" className="text-primary" aria-label="MD70 — página inicial"><Logo sub={false} /></Link>
          <span className="hidden text-xs uppercase text-muted-foreground sm:block">Portal do investidor</span>
          <div className="flex items-center gap-1">
            <div className="relative">
              <Button variant="ghost" size="icon" aria-label="Notificações" onClick={() => setNoticeOpen(!noticeOpen)} className="relative">
                <Bell />
                <span className="absolute right-2 top-2 h-1.5 w-1.5 rounded-full bg-positive" />
              </Button>
              {noticeOpen && (
                <div className="absolute right-0 top-12 z-30 w-[min(22rem,calc(100vw-2rem))] border bg-popover p-4 shadow-soft">
                  <div className="mb-3 flex items-center justify-between"><p className="font-semibold">Notificações</p><span className="text-xs text-muted-foreground">2 novas</span></div>
                  <div className="divide-y">
                    {notifications.map((n) => (
                      <div key={n.id} className="py-3">
                        <div className="flex gap-2">
                          <span className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", n.unread ? "bg-positive" : "bg-muted-foreground/30")} />
                          <div><p className="text-sm font-medium">{n.title}</p><p className="mt-1 text-xs text-muted-foreground">{n.body}</p></div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <Button variant="ghost" size="icon" onClick={signOut} aria-label="Sair" title="Sair"><LogOut /></Button>
          </div>
        </div>
      </header>

      {/* Content */}
      <main className="mx-auto max-w-[90rem] px-4 py-7 md:px-8 md:py-10">
        <MockNotice />
        {children}
      </main>

      {/* Category drawer */}
      {openCategory && (
        <>
          <Button variant="ghost" className="fixed inset-0 z-20 h-auto rounded-none bg-ink/30 hover:bg-ink/30" aria-label="Fechar navegação" onClick={() => setOpenCategory(null)} />
          <div
            id={`portal-category-${openCategory}`}
            aria-label={categories[openCategory].label}
            className="fixed inset-x-0 bottom-[calc(4rem+env(safe-area-inset-bottom))] z-30 border-t bg-background px-6 py-4 shadow-soft md:bottom-[calc(4.5rem+env(safe-area-inset-bottom))] md:mx-auto md:max-w-md md:border md:shadow-soft"
          >
            <p className="eyebrow mb-2">{categories[openCategory].label}</p>
            {categories[openCategory].links.map(({ to, label }) => (
              <Link key={to} to={to} onClick={() => setOpenCategory(null)} aria-current={pathname === to || pathname.startsWith(`${to}/`) ? "page" : undefined} className={cn("block border-b py-3 text-sm text-foreground last:border-0", (pathname === to || pathname.startsWith(`${to}/`)) && "font-semibold text-primary")}>{label}</Link>
            ))}
          </div>
        </>
      )}

      {/* Bottom nav — all screen sizes, centered on desktop */}
      <nav aria-label="Navegação do portal" className="fixed inset-x-0 bottom-0 z-30 border-t bg-background/95 pb-[env(safe-area-inset-bottom)] shadow-soft backdrop-blur">
        <div className="mx-auto grid h-16 grid-cols-4 px-1 md:flex md:h-[4.5rem] md:items-stretch md:justify-center md:gap-1 md:px-8">
          <Link to="/portal" onClick={() => setOpenCategory(null)} aria-current={pathname === "/portal" ? "page" : undefined} className={navClass(pathname === "/portal")}>
            <LayoutDashboard className="size-5 shrink-0" aria-hidden="true" /><span>Visão geral</span>
          </Link>
          {(Object.keys(categories) as CategoryKey[]).map((key) => {
            const category = categories[key];
            const Icon = category.icon;
            const active = openCategory === key || category.links.some(({ to }) => pathname === to || pathname.startsWith(`${to}/`));
            return (
              <Button key={key} variant="ghost" aria-expanded={openCategory === key} aria-controls={`portal-category-${key}`} onClick={() => setOpenCategory(openCategory === key ? null : key)} className={cn("h-16 min-w-0 flex-col gap-1 rounded-none border-t-2 px-0.5 text-[10px] font-normal md:h-[4.5rem] md:w-32 md:shrink-0 md:text-xs", active ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:bg-accent hover:text-accent-foreground")}>
                <Icon className="size-5 shrink-0" aria-hidden="true" /><span className="truncate">{category.label}</span>
              </Button>
            );
          })}
        </div>
      </nav>
    </div>
  );
}

function navClass(active: boolean) {
  return cn("flex min-w-0 flex-col items-center justify-center gap-1 border-t-2 px-0.5 text-center text-[10px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:w-32 md:shrink-0 md:text-xs", active ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:bg-accent hover:text-accent-foreground");
}

export function PortalHeading({ eyebrow, title, children, action }: { eyebrow?: string; title: string; children?: ReactNode; action?: ReactNode }) {
  return <div className="mb-8 flex flex-col justify-between gap-4 sm:flex-row sm:items-end"><div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h1 className="mt-2 font-display text-4xl text-primary md:text-5xl">{title}</h1>{children && <div className="mt-2 text-sm text-muted-foreground">{children}</div>}</div>{action}</div>;
}

export function MockNotice() {
  return <div className="mb-6 border-l-2 border-warning bg-warning/10 px-4 py-3 text-xs text-muted-foreground"><strong className="text-foreground">Ambiente de demonstração.</strong> Projetos, documentos, comunicados, investimentos, valores financeiros e taxas de CDI são ilustrativos; não representam dados reais da sua conta.</div>;
}
