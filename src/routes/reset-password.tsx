import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Logo } from "@/components/site/Logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { supabase } from "@/integrations/supabase/client";

export const Route = createFileRoute("/reset-password")({ head: () => ({ meta: [
  { title: "Redefinir senha — MD70" }, { name: "description", content: "Defina uma nova senha para o portal MD70." },
  { property: "og:title", content: "Redefinir senha — MD70" }, { property: "og:description", content: "Acesso seguro ao portal do investidor." },
] }), component: ResetPassword });
function ResetPassword() {
  const [valid, setValid] = useState(false); const [message, setMessage] = useState(""); const [error, setError] = useState("");
  useEffect(() => { const hash = new URLSearchParams(window.location.hash.slice(1)); setValid(hash.get("type") === "recovery" || hash.has("access_token")); }, []);
  async function submit(e: React.FormEvent<HTMLFormElement>) { e.preventDefault(); const password = String(new FormData(e.currentTarget).get("password") ?? ""); const { error: err } = await supabase.auth.updateUser({ password }); if (err) setError("Não foi possível atualizar a senha."); else setMessage("Senha atualizada. Você já pode acessar o portal."); }
  return <main className="flex min-h-screen items-center justify-center px-6"><div className="w-full max-w-md"><Link to="/"><Logo className="text-primary" /></Link><h1 className="mt-12 font-display text-4xl text-primary">Crie uma nova senha.</h1>{message ? <div className="mt-8 border-l-2 border-positive bg-positive/10 p-4 text-sm">{message}<div className="mt-4"><Link to="/portal" className="text-primary underline">Ir para o portal</Link></div></div> : valid ? <form onSubmit={submit} className="mt-8 space-y-5"><div><Label htmlFor="password">Nova senha</Label><Input id="password" name="password" type="password" minLength={6} required className="mt-2 h-11" /></div>{error && <p className="text-sm text-destructive">{error}</p>}<Button size="lg" className="w-full">Atualizar senha</Button></form> : <p className="mt-6 text-muted-foreground">Abra esta página pelo link enviado ao seu e-mail.</p>}</div></main>;
}
