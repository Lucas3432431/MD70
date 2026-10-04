// Dev-only auth bypass. Never ships to production (import.meta.env.DEV is false-out in build).
export const IS_DEV = import.meta.env.DEV;

const KEY = "md70_dev_role";

export type DevRole = "admin" | "investor";

export const DEV_CREDS: Record<DevRole, { email: string; password: string }> = {
  admin: { email: "admin@md70.com.br", password: "Admin123@" },
  investor: { email: "investidor@md70.com.br", password: "Senha123@" },
};

export function getDevRole(): DevRole | null {
  if (!IS_DEV || typeof localStorage === "undefined") return null;
  return (localStorage.getItem(KEY) as DevRole) ?? null;
}

export function setDevRole(role: DevRole): void {
  if (!IS_DEV) return;
  localStorage.setItem(KEY, role);
}

export function clearDevRole(): void {
  if (typeof localStorage !== "undefined") localStorage.removeItem(KEY);
}

export const DEV_USERS = {
  admin: { id: "dev-admin-000", email: "admin@md70.com.br", user_metadata: { full_name: "Admin MD70" } },
  investor: { id: "dev-investor-000", email: "investidor@md70.com.br", user_metadata: { full_name: "Investidor Demo" } },
} satisfies Record<DevRole, { id: string; email: string; user_metadata: Record<string, string> }>;
