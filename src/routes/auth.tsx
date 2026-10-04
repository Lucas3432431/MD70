import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { z } from "zod";
import { Logo } from "@/components/site/Logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { supabase } from "@/integrations/supabase/client";
import { lovable } from "@/integrations/lovable";
import { IS_DEV, DEV_CREDS, setDevRole, type DevRole } from "@/lib/dev-auth";

const searchSchema = z.object({ next: z.string().optional() });
function safeNext(value?: string) { return value && /^\/(portal|admin)(\/|$)/.test(value) ? value : "/portal"; }

export const Route = createFileRoute("/auth")({
  validateSearch: searchSchema,
  head: () => ({ meta: [
    { title: "Acesso aos portais — MD70" },
    { name: "description", content: "Acesse com segurança as áreas privadas da MD70." },
    { property: "og:title", content: "Acesso aos portais MD70" },
    { property: "og:description", content: "Acesso seguro às áreas privadas da MD70." },
    { property: "og:type", content: "website" }, { name: "twitter:card", content: "summary" },
  ] }),
  component: AuthPage,
});

function AuthPage() {
  const { next } = Route.useSearch();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"signin" | "signup" | "forgot">("signin");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => { supabase.auth.getUser().then(({ data }) => { if (data.user) void navigate({ to: safeNext(next) }); }); }, [navigate, next]);

  async function devLogin(role: DevRole) {
    setDevRole(role);
    await navigate({ to: role === "admin" ? "/admin" : "/portal", replace: true });
  }

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault(); setLoading(true); setError(""); setMessage("");
    const fd = new FormData(e.currentTarget); const email = String(fd.get("email") ?? ""); const password = String(fd.get("password") ?? "");
    if (IS_DEV && mode === "signin") {
      const match = (Object.entries(DEV_CREDS) as [DevRole, { email: string; password: string }][]).find(([, c]) => c.email === email && c.password === password);
      if (match) { setLoading(false); await devLogin(match[0]); return; }
    }
    if (mode === "forgot") {
      const { error: err } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: `${window.location.origin}/reset-password` });
      setLoading(false); if (err) setError("Não foi possível enviar o e-mail agora."); else setMessage("Enviamos um link de recuperação para o seu e-mail."); return;
    }
    if (mode === "signup") {
      const fullName = String(fd.get("full_name") ?? "");
      const { data, error: err } = await supabase.auth.signUp({ email, password, options: { data: { full_name: fullName }, emailRedirectTo: window.location.origin } });
      setLoading(false); if (err) setError(err.message); else if (!data.session) setMessage("Confira seu e-mail para confirmar o cadastro."); else await navigate({ to: safeNext(next) }); return;
    }
    const { error: err } = await supabase.auth.signInWithPassword({ email, password }); setLoading(false);
    if (err) setError("E-mail ou senha incorretos."); else await navigate({ to: safeNext(next) });
  }

  async function google() {
    setError(""); sessionStorage.setItem("md70-auth-next", safeNext(next));
    const result = await lovable.auth.signInWithOAuth("google", { redirect_uri: window.location.origin });
    if (result.error) setError("Não foi possível entrar com o Google.");
    if (!result.redirected) await navigate({ to: safeNext(next) });
  }

  return <main className="grid min-h-screen bg-background lg:grid-cols-[1fr_1fr]">
    <div className="hidden bg-primary p-14 text-primary-foreground lg:flex lg:flex-col lg:justify-between">
      <Link to="/"><Logo /></Link>
      <div><p className="eyebrow !text-primary-foreground/60">Portal do investidor</p><h1 className="mt-5 max-w-lg font-display text-6xl leading-none">Acompanhe onde seu dinheiro está.</h1><p className="mt-7 max-w-md opacity-70">Veja a evolução dos investimentos, o andamento dos projetos e seus documentos em um único lugar.</p></div>
      <p className="text-xs opacity-50">Ambiente privado e protegido.</p>
    </div>
    <div className="flex items-center justify-center px-6 py-12">
      <div className="w-full max-w-md">
        <Link to="/" className="mb-12 inline-block text-primary lg:hidden"><Logo /></Link>
        <p className="eyebrow">{mode === "signin" ? "Bem-vindo de volta" : mode === "signup" ? "Novo investidor" : "Recuperar acesso"}</p>
        <h1 className="mt-3 font-display text-4xl text-primary">{mode === "signin" ? "Entre no seu portal." : mode === "signup" ? "Crie seu acesso." : "Redefina sua senha."}</h1>
        {message ? <div className="mt-8 border-l-2 border-positive bg-positive/10 p-4 text-sm">{message}</div> : <form onSubmit={submit} className="mt-8 space-y-5">
          {mode === "signup" && <div><Label htmlFor="full_name">Nome completo</Label><Input id="full_name" name="full_name" required minLength={2} className="mt-2 h-11" /></div>}
          <div><Label htmlFor="email">E-mail</Label><Input id="email" name="email" type="email" required className="mt-2 h-11" autoComplete="email" /></div>
          {mode !== "forgot" && <div><Label htmlFor="password">Senha</Label><Input id="password" name="password" type="password" required minLength={6} className="mt-2 h-11" autoComplete={mode === "signin" ? "current-password" : "new-password"} /></div>}
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button type="submit" size="lg" className="w-full" disabled={loading}>{loading ? "Aguarde…" : mode === "signin" ? "Entrar" : mode === "signup" ? "Criar acesso" : "Enviar link"}</Button>
        </form>}
        {mode !== "forgot" && <><div className="my-6 flex items-center gap-3 text-xs text-muted-foreground"><span className="h-px flex-1 bg-border" />ou<span className="h-px flex-1 bg-border" /></div><Button variant="outline" size="lg" className="w-full" onClick={google}>Continuar com Google</Button></>}
        {IS_DEV && mode === "signin" && (
          <div className="mt-8 border-t pt-6">
            <p className="mb-3 text-xs text-muted-foreground">Atalhos de desenvolvimento</p>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" className="flex-1 text-xs" onClick={() => devLogin("admin")}>Admin</Button>
              <Button variant="outline" size="sm" className="flex-1 text-xs" onClick={() => devLogin("investor")}>Investidor</Button>
            </div>
          </div>
        )}
        <div className="mt-7 flex flex-wrap gap-x-6 gap-y-2 text-sm">
          {mode === "signin" ? <><button onClick={() => setMode("signup")} className="text-primary underline underline-offset-4">Criar acesso</button><button onClick={() => setMode("forgot")} className="text-muted-foreground underline underline-offset-4">Esqueci minha senha</button></> : <button onClick={() => { setMode("signin"); setMessage(""); }} className="text-primary underline underline-offset-4">Voltar para o login</button>}
        </div>
      </div>
    </div>
  </main>;
}
