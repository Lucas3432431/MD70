import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Bell, BriefcaseBusiness, FileText, LayoutDashboard, LogOut, UserRound } from "lucide-react";
import { Logo } from "@/components/site/Logo";
import { Button } from "@/components/ui/button";
import { notifications } from "@/lib/data/portal";
import { IS_DEV, getDevRole, clearDevRole } from "@/lib/dev-auth";
import { cn } from "@/lib/utils";

export function PortalLayout({ children }: { children: ReactNode }) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [noticeOpen, setNoticeOpen] = useState(false);

  async function signOut() {
    if (IS_DEV && getDevRole()) {
      clearDevRole();
      queryClient.clear();
      await navigate({ to: "/login", replace: true });
      return;
    }
    await queryClient.cancelQueries();
    queryClient.clear();
    await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    window.dispatchEvent(new Event("md70:auth"));
    await navigate({ to: "/login", replace: true });
  }

  const investimentosBadge = notifications.filter(
    (n) => n.unread && /investimento|obra/i.test(n.title),
  ).length;

  const atualizacoesBadge = notifications.filter(
    (n) => n.unread && /documento|comunicado/i.test(n.title),
  ).length;

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
        {children}
      </main>

      {/* Bottom nav — all screen sizes, centered on desktop */}
      <nav aria-label="Navegação do portal" className="fixed inset-x-0 bottom-0 z-30 border-t bg-background/95 pb-[env(safe-area-inset-bottom)] shadow-soft backdrop-blur">
        <div className="mx-auto grid h-16 grid-cols-4 px-1 md:flex md:h-[4.5rem] md:items-stretch md:justify-center md:gap-1 md:px-8">

          {/* Visão geral */}
          <Link
            to="/portal"
            aria-current={pathname === "/portal" ? "page" : undefined}
            className={navClass(pathname === "/portal")}
          >
            <LayoutDashboard className="size-5 shrink-0" aria-hidden="true" />
            <span>Visão geral</span>
          </Link>

          {/* Investimentos */}
          <Link
            to="/portal/empreendimentos"
            aria-current={pathname.startsWith("/portal/empreendimentos") ? "page" : undefined}
            className={navClass(pathname.startsWith("/portal/empreendimentos"))}
          >
            <div className="relative">
              <BriefcaseBusiness className="size-5 shrink-0" aria-hidden="true" />
              {investimentosBadge > 0 && (
                <div className="absolute -right-1.5 -top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-destructive text-[9px] font-bold text-destructive-foreground leading-none">
                  {investimentosBadge}
                </div>
              )}
            </div>
            <span>Investimentos</span>
          </Link>

          {/* Atualizações */}
          <Link
            to="/portal/comunicados"
            aria-current={pathname.startsWith("/portal/comunicados") ? "page" : undefined}
            className={navClass(pathname.startsWith("/portal/comunicados"))}
          >
            <div className="relative">
              <FileText className="size-5 shrink-0" aria-hidden="true" />
              {atualizacoesBadge > 0 && (
                <div className="absolute -right-1.5 -top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-destructive text-[9px] font-bold text-destructive-foreground leading-none">
                  {atualizacoesBadge}
                </div>
              )}
            </div>
            <span>Atualizações</span>
          </Link>

          {/* Indique — temporariamente desabilitado */}
          {/* <Link
            to="/portal/indique"
            aria-current={pathname.startsWith("/portal/indique") ? "page" : undefined}
            className={navClass(pathname.startsWith("/portal/indique"))}
          >
            <Gift className="size-5 shrink-0" aria-hidden="true" />
            <span>Indique</span>
          </Link> */}

          {/* Perfil */}
          <Link
            to="/portal/perfil"
            aria-current={pathname.startsWith("/portal/perfil") ? "page" : undefined}
            className={navClass(pathname.startsWith("/portal/perfil"))}
          >
            <UserRound className="size-5 shrink-0" aria-hidden="true" />
            <span>Perfil</span>
          </Link>

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
