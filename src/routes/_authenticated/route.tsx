import { createFileRoute, Outlet, redirect } from "@tanstack/react-router";
import { supabase } from "@/integrations/supabase/client";
import { IS_DEV, getDevRole, DEV_USERS } from "@/lib/dev-auth";

export const Route = createFileRoute("/_authenticated")({
  ssr: false,
  beforeLoad: async ({ location }) => {
    if (IS_DEV) {
      const role = getDevRole();
      if (role) return { user: DEV_USERS[role] };
    }
    const { data, error } = await supabase.auth.getUser();
    if (error || !data.user) throw redirect({ to: "/auth", search: { next: location.href } });
    return { user: data.user };
  },
  component: () => <Outlet />,
});
