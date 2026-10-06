import { createFileRoute, Link } from "@tanstack/react-router";
import { Logo } from "@/components/site/Logo";

export const Route = createFileRoute("/reset-password")({
  head: () => ({ meta: [{ title: "Redefinir senha — MD70" }] }),
  component: ResetPassword,
});

function ResetPassword() {
  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <div className="w-full max-w-md">
        <Link to="/"><Logo className="text-primary" /></Link>
        <h1 className="mt-12 font-display text-4xl text-primary">Redefinição de senha.</h1>
        <p className="mt-6 text-muted-foreground">Para redefinir sua senha, entre em contato com a equipe MD70.</p>
        <div className="mt-8">
          <Link to="/login" className="text-primary underline underline-offset-4">Voltar para o login</Link>
        </div>
      </div>
    </main>
  );
}
