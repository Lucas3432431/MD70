import { createFileRoute, Link, Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import { useRef, useState } from "react";
import { useGoogleLogin } from "@react-oauth/google";
import { Logo } from "@/components/site/Logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PeekPasswordInput } from "@/components/ui/peek-password-input";
import { getFingerprint } from "@/lib/fingerprint";
import { api, ApiError } from "@/lib/api";

export const Route = createFileRoute("/login")({
  head: () => ({ meta: [{ title: "Acesso ao Portal — MD70" }] }),
  component: LoginLayout,
});

function LoginLayout() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  if (pathname !== "/login") return <Outlet />;
  return <LoginPage />;
}

function LoginPage() {
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [emailSubmitted, setEmailSubmitted] = useState(false);
  const [emailValidating, setEmailValidating] = useState(false);
  const [userExists, setUserExists] = useState<number | null>(null);

  const [requires2fa, setRequires2fa] = useState(false);
  const [pendingToken, setPendingToken] = useState("");
  const [twoFactorCode, setTwoFactorCode] = useState("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [forgotSent, setForgotSent] = useState(false);

  const passwordRef = useRef<HTMLInputElement>(null);

  const googleLogin = useGoogleLogin({
    flow: "auth-code",
    onSuccess: async ({ code }) => {
      setLoading(true); setError("");
      try {
        const res = await fetch(
          `/api/auth/callback?code=${encodeURIComponent(code)}&redirect_uri=postmessage`,
          { credentials: "include" },
        );
        if (!res.ok) { setError("Falha no login com Google."); return; }
        window.dispatchEvent(new Event("md70:auth"));
        await navigate({ to: "/portal", replace: true });
      } catch {
        setError("Erro de conexão. Tente novamente.");
      } finally {
        setLoading(false);
      }
    },
    onError: () => setError("Login com Google cancelado ou falhou."),
  });

  async function handleEmailSubmit(e: React.FormEvent) {
    e.preventDefault();
    setEmailValidating(true); setError("");
    try {
      const data = await api.post<{ is_valid: boolean; user_exists: number }>("/validate-email", { value: email.trim() });
      if (!data.is_valid) { setError("E-mail inválido."); return; }
      setUserExists(data.user_exists);
      setEmailSubmitted(true);
      setTimeout(() => passwordRef.current?.focus(), 50);
    } catch {
      setError("Erro de conexão. Tente novamente.");
    } finally {
      setEmailValidating(false);
    }
  }

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true); setError("");
    try {
      const data = await api.post<{ requires_2fa?: boolean; pending_token?: string }>("/auth/login", { email: email.trim(), password, ...getFingerprint() });
      if (data.requires_2fa && data.pending_token) {
        setPendingToken(data.pending_token);
        setRequires2fa(true);
        return;
      }
      window.dispatchEvent(new Event("md70:auth"));
      await navigate({ to: "/portal", replace: true });
    } catch (e) {
      setError(e instanceof ApiError && e.status === 401 ? (userExists === 0 ? "Conta não encontrada." : "E-mail ou senha incorretos.") : "Erro de conexão. Tente novamente.");
    } finally {
      setLoading(false);
    }
  }

  async function handleTwoFactorSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true); setError("");
    try {
      await api.post("/auth/2fa/login", { pending_token: pendingToken, code: twoFactorCode });
      window.dispatchEvent(new Event("md70:auth"));
      await navigate({ to: "/portal", replace: true });
    } catch (e) {
      setError(e instanceof ApiError && e.status === 401 ? "Código inválido ou expirado." : "Erro de conexão. Tente novamente.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="grid min-h-screen bg-background lg:grid-cols-[1fr_1fr]">
      <div className="hidden bg-primary p-14 text-primary-foreground lg:flex lg:flex-col lg:justify-between">
        <Link to="/"><Logo /></Link>
        <div>
          <p className="eyebrow !text-primary-foreground/60">Portal do investidor</p>
          <h1 className="mt-5 max-w-lg font-display text-6xl leading-none">Acompanhe onde seu dinheiro está.</h1>
          <p className="mt-7 max-w-md opacity-70">Veja a evolução dos investimentos, o andamento dos projetos e seus documentos em um único lugar.</p>
        </div>
        <p className="text-xs opacity-50">Ambiente privado e protegido.</p>
      </div>

      <div className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-md">
          <Link to="/" className="mb-12 inline-block text-primary lg:hidden"><Logo /></Link>
          <p className="eyebrow">
            {requires2fa ? "Verificação em duas etapas" : "Bem-vindo de volta"}
          </p>
          <h1 className="mt-3 font-display text-4xl text-primary">
            {requires2fa ? "Confirme seu acesso." : "Entre no seu portal."}
          </h1>

          <div className="mt-8">
            {requires2fa ? (
              <form onSubmit={handleTwoFactorSubmit} className="space-y-4">
                <div>
                  <Label htmlFor="code">Código de 6 dígitos</Label>
                  <p className="mt-1 text-xs text-muted-foreground">Insira o código do seu app autenticador.</p>
                  <Input
                    id="code" type="text" inputMode="numeric" maxLength={6}
                    value={twoFactorCode}
                    onChange={(e) => setTwoFactorCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                    placeholder="000000"
                    className="mt-2 h-11 text-center tracking-widest text-lg"
                    autoComplete="one-time-code" autoFocus required
                  />
                </div>
                {error && <p className="text-sm text-destructive">{error}</p>}
                <Button type="submit" size="lg" className="w-full" disabled={loading || twoFactorCode.length !== 6}>
                  {loading ? "Verificando…" : "Verificar"}
                </Button>
                <button
                  type="button"
                  onClick={() => { setRequires2fa(false); setTwoFactorCode(""); setError(""); }}
                  className="w-full text-center text-sm text-muted-foreground underline underline-offset-4"
                >
                  Voltar ao login
                </button>
              </form>
            ) : (
              <div className="space-y-4">
                <Button
                  type="button" variant="outline" size="lg" className="w-full gap-3"
                  disabled={loading} onClick={() => googleLogin()}
                >
                  <GoogleIcon />
                  Continuar com Google
                </Button>
                <div className="relative flex items-center gap-3">
                  <div className="h-px flex-1 bg-border" />
                  <span className="text-xs text-muted-foreground">ou continue com e-mail</span>
                  <div className="h-px flex-1 bg-border" />
                </div>

                <form onSubmit={emailSubmitted ? handleLogin : handleEmailSubmit} className="space-y-3">
                  <div>
                    <Label htmlFor="email">E-mail</Label>
                    <Input
                      id="email" type="email" value={email}
                      onChange={(e) => { setEmail(e.target.value); if (emailSubmitted) { setEmailSubmitted(false); setPassword(""); setError(""); } }}
                      placeholder="seu@email.com"
                      className="mt-2 h-11" autoComplete="email" required
                    />
                  </div>

                  {emailSubmitted && (
                    <div>
                      <Label htmlFor="password">Senha</Label>
                      <PeekPasswordInput
                        ref={passwordRef}
                        id="password" value={password}
                        onChange={setPassword}
                        placeholder="Digite sua senha"
                        className="mt-2 h-11" autoComplete="current-password" required
                      />
                    </div>
                  )}

                  {error && <p className="text-sm text-destructive">{error}</p>}

                  <Button
                    type="submit" size="lg" className="w-full"
                    disabled={loading || emailValidating}
                  >
                    {emailValidating ? "Validando…" : loading ? "Aguarde…" : emailSubmitted ? "Entrar" : "Continuar"}
                  </Button>
                </form>

                {emailSubmitted && !forgotSent && (
                  <button
                    type="button"
                    onClick={() => setForgotSent(true)}
                    className="w-full text-center text-sm text-muted-foreground underline underline-offset-4"
                  >
                    Esqueci minha senha
                  </button>
                )}
                {forgotSent && (
                  <p className="text-center text-sm text-muted-foreground">
                    Entre em contato com a equipe MD70 para redefinir sua senha.
                  </p>
                )}
              </div>
            )}
          </div>

          <p className="mt-8 text-center text-xs text-muted-foreground">
            Equipe interna? <Link to="/login/admin" className="text-primary underline underline-offset-4">Acesso administrativo</Link>
          </p>
        </div>
      </div>
    </main>
  );
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden>
      <path d="M17.64 9.205c0-.639-.057-1.252-.164-1.841H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z" fill="#4285F4"/>
      <path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z" fill="#34A853"/>
      <path d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" fill="#FBBC05"/>
      <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/>
    </svg>
  );
}
