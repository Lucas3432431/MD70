import { createServerFn } from "@tanstack/react-start";
import { requireSupabaseAuth } from "@/integrations/supabase/auth-middleware";

export const checkAdminAccess = createServerFn({ method: "GET" })
  .middleware([requireSupabaseAuth])
  .handler(async ({ context }) => {
    const { data, error } = await context.supabase.rpc("has_role", { _user_id: context.userId, _role: "admin" });
    if (error || !data) throw new Response("Acesso negado", { status: 403 });
    return true;
  });

export const getAdminDemo = createServerFn({ method: "GET" })
  .middleware([requireSupabaseAuth])
  .handler(async ({ context }) => {
    const { data, error } = await context.supabase.rpc("has_role", { _user_id: context.userId, _role: "admin" });
    if (error || !data) throw new Response("Acesso negado", { status: 403 });
    const { adminDemo } = await import("@/lib/data/admin.server");
    return adminDemo;
  });

/** Apenas em desenvolvimento — sem verificação de JWT. Bloqueado em produção. */
export const getAdminDemoBypass = createServerFn({ method: "GET" })
  .handler(async () => {
    if (process.env["NODE_ENV"] !== "development") {
      throw new Response("Acesso negado", { status: 403 });
    }
    const { adminDemo } = await import("@/lib/data/admin.server");
    return adminDemo;
  });