import { Link, useRouterState, useNavigate, Outlet } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { LayoutDashboard, Building2, LogOut, Wallet, BarChart3, ShoppingCart, Users } from "lucide-react";
import { Logo } from "@/components/site/Logo";
import { Button } from "@/components/ui/button";
import { useAdminData } from "@/lib/hooks/useAdminData";
import type { AdminData } from "@/lib/data/admin-types";
import { IS_DEV, getDevRole, clearDevRole } from "@/lib/dev-auth";
import { cn } from "@/lib/utils";
import { AdminFloatingChat } from "./AdminFloatingChat";

const links = [
  { to: "/admin",                label: "Dashboard",      short: "Dashboard",  icon: LayoutDashboard },
  { to: "/admin/empreendimentos",label: "Projetos",       short: "Projetos",   icon: Building2 },
  { to: "/admin/compras",        label: "Compras",        short: "Compras",    icon: ShoppingCart },
  { to: "/admin/crm",            label: "CRM",            short: "CRM",        icon: Users },
  { to: "/admin/financeiro",     label: "Financeiro",     short: "Financeiro", icon: Wallet },
  { to: "/admin/relatorios",     label: "Relatórios",     short: "Relatórios", icon: BarChart3 },
] as const;

type AdminContextValue = { data: AdminData; setData: React.Dispatch<React.SetStateAction<AdminData>> };
const AdminContext = createContext<AdminContextValue | null>(null);
export function useAdmin() { const value = useContext(AdminContext); if (!value) throw new Error("Admin context unavailable"); return value; }

// AdminGate always renders AdminWorkspace so the context provider is always in
// the tree — avoids "Admin context unavailable" when child routes render
// before the async data resolves in concurrent React.
export function AdminGate() {
  const { data, isPending, isError } = useAdminData();
  return <AdminWorkspace initialData={data ?? null} isPending={isPending} isError={isError} />;
}

function AdminWorkspace({ initialData, isPending, isError }: { initialData: AdminData | null; isPending: boolean; isError: boolean }) {
  const [mutatedData, setMutatedData] = useState<AdminData | null>(null);
  const effectiveData = mutatedData ?? initialData ?? null;
  const [panelState, setPanelState] = useState<"closed" | "collapsed" | "open">("closed");

  const value = useMemo(
    () => (effectiveData ? { data: effectiveData, setData: setMutatedData as React.Dispatch<React.SetStateAction<AdminData>> } : null),
    [effectiveData],
  );
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const badges = useMemo(() => ({
    "/admin/crm": effectiveData?.leads.filter(l => l.status === "Interesse").length ?? 0,
    "/admin/compras": effectiveData?.purchases.filter(p => p.status === "Solicitado" || p.status === "Fornecedores Contatados").length ?? 0,
    "/admin/empreendimentos": effectiveData?.projects.filter(p => p.status === "Oferecido / Interessado").length ?? 0,
  }), [effectiveData]);

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

  if (isPending || (!value && !isError)) {
    return <main className="grid min-h-screen place-items-center text-sm text-muted-foreground">Verificando acesso…</main>;
  }

  if (isError || !value) {
    return (
      <main className="mx-auto flex min-h-screen max-w-xl flex-col items-center justify-center gap-5 px-6 text-center">
        <Logo sub={false} />
        <h1 className="font-display text-4xl text-primary">Acesso restrito</h1>
        <p className="text-sm text-muted-foreground">Esta área é exclusiva da equipe administrativa MD70.</p>
      </main>
    );
  }

  return (
    <AdminContext.Provider value={value}>
      <div className="min-h-screen bg-background pb-[calc(2.75rem+env(safe-area-inset-bottom))] md:pb-[calc(3rem+env(safe-area-inset-bottom))] lg:pr-0">
        {/* Header */}
        <header className="sticky top-0 z-20 border-b bg-background/95 backdrop-blur">
          <div className="mx-auto grid h-16 max-w-[90rem] grid-cols-[auto_1fr_auto] items-center gap-4 px-4 md:px-8">
            <Link to="/" className="min-w-0 shrink-0 text-primary" aria-label="MD70 — página inicial"><Logo sub={false}/></Link>
            <span className="text-center text-xs uppercase text-muted-foreground">Administração</span>
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="icon" onClick={signOut} aria-label="Sair" title="Sair">
                <LogOut className="size-5" />
              </Button>
            </div>
          </div>
        </header>

        <div className={cn(
          "transition-[padding] duration-300",
          panelState === "open" && "lg:pr-[calc(33vw+1rem)]",
          panelState === "collapsed" && "lg:pr-16",
        )}>
          <main className="mx-auto max-w-[90rem] px-4 py-8 md:px-8 md:py-10">
            <Outlet />
          </main>
        </div>

        <AdminFloatingChat onPanelChange={setPanelState} />

        {/* Bottom nav — compact */}
        <nav aria-label="Navegação administrativa" className="fixed inset-x-0 bottom-0 z-20 border-t bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur">
          <div className="mx-auto grid h-11 grid-cols-6 px-1 md:flex md:h-12 md:items-stretch md:justify-center md:gap-1 md:px-8">
            {links.map(({ to, label, short, icon: Icon }) => {
              const active = to === "/admin" ? pathname === to : pathname.startsWith(to);
              const badgeCount = badges[to as keyof typeof badges] ?? 0;
              return (
                <Link key={to} to={to} search={(prev: Record<string, unknown>) => ({ chat: (prev as { chat?: string }).chat })} aria-current={active ? "page" : undefined} className={cn(
                  "flex min-w-0 flex-col items-center justify-center gap-0.5 border-t-2 px-0.5 text-center text-[8px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-[9px] md:w-20 md:shrink-0 md:text-[10px]",
                  active ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-primary",
                )}>
                  <div className="relative">
                    <Icon className="size-4 shrink-0" aria-hidden="true" />
                    {badgeCount > 0 && (
                      <span className="absolute -right-1.5 -top-1.5 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-destructive text-[8px] font-bold text-destructive-foreground leading-none">
                        {badgeCount}
                      </span>
                    )}
                  </div>
                  <span className="truncate leading-tight">{short}</span>
                </Link>
              );
            })}
          </div>
        </nav>
      </div>
    </AdminContext.Provider>
  );
}

export function AdminHeading({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-8 grid grid-cols-[minmax(0,1fr)_auto] items-end gap-4">
      <div className="min-w-0">
        <p className="eyebrow">Administração MD70</p>
        <h1 className="mt-2 font-display text-4xl text-primary md:text-5xl">{title}</h1>
        {children && <p className="mt-2 text-sm text-muted-foreground">{children}</p>}
      </div>
      {action}
    </div>
  );
}
