import { createFileRoute, Outlet, redirect } from "@tanstack/react-router";
import { IS_DEV, getDevRole, DEV_USERS } from "@/lib/dev-auth";
import { api } from "@/lib/api";

async function checkAuth() {
  try {
    const data = await api.post<{ authenticated: boolean; user: { user_id: string; email: string; full_name: string } | null }>("/auth/check");
    return data.authenticated ? data.user : null;
  } catch {
    return null;
  }
}

async function tryRefresh() {
  try {
    await api.post("/auth/refresh");
    return true;
  } catch {
    return false;
  }
}

export const Route = createFileRoute("/_authenticated")({
  ssr: false,
  beforeLoad: async ({ location }) => {
    if (IS_DEV) {
      const role = getDevRole();
      if (role) return { user: DEV_USERS[role] };
    }

    let user = await checkAuth();
    if (!user) {
      const refreshed = await tryRefresh();
      if (refreshed) user = await checkAuth();
    }

    if (!user) {
      const isAdmin = location.pathname.startsWith("/admin");
      throw redirect({ to: isAdmin ? "/login/admin" : "/login" });
    }
    return { user };
  },
  component: () => <Outlet />,
});
