import { Link, useRouterState, Outlet } from "@tanstack/react-router";
import { useServerFn } from "@tanstack/react-start";
import { useQuery } from "@tanstack/react-query";
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { LayoutDashboard, Building2, Wallet, BarChart3, ShoppingCart, Users } from "lucide-react";
import { Logo } from "@/components/site/Logo";
import { getAdminDemo, getAdminDemoBypass } from "@/lib/admin-access.functions";
import type { AdminData } from "@/lib/data/admin-types";
import { IS_DEV, getDevRole } from "@/lib/dev-auth";
import { cn } from "@/lib/utils";

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

export function AdminGate() {
  const isDevAdmin = IS_DEV && getDevRole() === "admin";
  const fetchNormal = useServerFn(getAdminDemo);
  const fetchBypass = useServerFn(getAdminDemoBypass);
  const { data, isPending, error } = useQuery({ queryKey: ["admin-access-demo", isDevAdmin ? "dev" : "prod"], queryFn: isDevAdmin ? fetchBypass : fetchNormal, retry: false, staleTime: 60_000 });
  if (isPending) return <main className="grid min-h-screen place-items-center text-sm text-muted-foreground">Verificando acesso…</main>;
  if (error || !data) return <main className="mx-auto flex min-h-screen max-w-xl flex-col items-center justify-center gap-5 px-6 text-center"><Logo sub={false}/><h1 className="font-display text-4xl text-primary">Acesso restrito</h1><p className="text-sm text-muted-foreground">Esta área é exclusiva da equipe administrativa MD70.</p><Link to="/portal" className="text-sm font-medium text-primary underline underline-offset-4">Ir para o portal do investidor</Link></main>;
  return <AdminWorkspace initialData={data} />;
}

function AdminWorkspace({ initialData }: { initialData: AdminData }) {
  const [data, setData] = useState<AdminData>(initialData);
  const value = useMemo(() => ({ data, setData }), [data]);
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const badges = useMemo(() => ({
    "/admin/crm": data.leads.filter(l => l.status === "Interesse").length,
    "/admin/compras": data.purchases.filter(p => p.status === "Solicitado" || p.status === "Fornecedores Contatados").length,
    "/admin/empreendimentos": data.projects.filter(p => p.status === "Oferecido / Interessado").length,
  }), [data]);
  return (
    <AdminContext.Provider value={value}>
      <div className="min-h-screen bg-background pb-[calc(4rem+env(safe-area-inset-bottom))] md:pb-[calc(4.5rem+env(safe-area-inset-bottom))]">
        {/* Header */}
        <header className="sticky top-0 z-20 border-b bg-background/95 backdrop-blur">
          <div className="mx-auto flex h-16 max-w-[90rem] items-center gap-4 px-4 md:px-8">
            <Link to="/" className="min-w-0 shrink-0 text-primary" aria-label="MD70 — página inicial"><Logo sub={false}/></Link>
            <span className="hidden text-xs uppercase text-muted-foreground md:block">Administração</span>
            <Link to="/portal" className="ml-auto shrink-0 text-xs text-muted-foreground underline underline-offset-4">Portal do investidor</Link>
          </div>
        </header>

        {/* Main */}
        <main className="mx-auto max-w-[90rem] px-4 py-8 md:px-8 md:py-10">
          <div className="mb-8 border-l-2 border-warning bg-warning/10 px-4 py-3 text-xs text-muted-foreground">
            <strong className="text-foreground">Ambiente de demonstração.</strong> Todos os valores e registros abaixo são fictícios. Alterações ficam nesta sessão e não são salvas.
          </div>
          <Outlet />
        </main>

        {/* Bottom nav */}
        <nav aria-label="Navegação administrativa" className="fixed inset-x-0 bottom-0 z-20 border-t bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur">
          <div className="mx-auto grid h-16 grid-cols-6 px-1 md:flex md:h-[4.5rem] md:items-stretch md:justify-center md:gap-1 md:px-8">
            {links.map(({ to, label, short, icon: Icon }) => {
              const active = to === "/admin" ? pathname === to : pathname.startsWith(to);
              const badgeCount = badges[to as keyof typeof badges] ?? 0;
              return (
                <Link key={to} to={to} aria-current={active ? "page" : undefined} className={cn(
                  "flex min-w-0 flex-col items-center justify-center gap-0.5 border-t-2 px-0.5 text-center text-[9px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-[10px] md:w-24 md:shrink-0 md:gap-1 md:text-xs",
                  active ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-primary",
                )}>
                  <div className="relative">
                    <Icon className="size-5 shrink-0" aria-hidden="true" />
                    {badgeCount > 0 && (
                      <span className="absolute -right-1.5 -top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-destructive text-[9px] font-bold text-destructive-foreground leading-none">
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
