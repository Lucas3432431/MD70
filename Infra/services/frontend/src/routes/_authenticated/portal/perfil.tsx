import { createFileRoute } from "@tanstack/react-router";
import { useState, useCallback } from "react";
import { toast } from "sonner";
import { PortalHeading } from "@/components/portal/PortalLayout";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";

export const Route = createFileRoute("/_authenticated/portal/perfil")({
  head: () => ({ meta: [
    { title: "Meu perfil — Portal MD70" },
    { name: "description", content: "Dados cadastrais e preferências de comunicação." },
  ] }),
  component: Perfil,
});

function Perfil() {
  const { user } = Route.useRouteContext();
  const [profile, setProfile] = useState({ full_name: user.full_name ?? "", phone: "", pref_email: true });

  const save = useCallback(async (patch: Partial<typeof profile>) => {
    try {
      await api.patch("/auth/profile", patch);
      toast.success("Salvo.");
    } catch {
      toast.error("Não foi possível salvar.");
    }
  }, []);

  return (
    <div className="lg:w-1/2 lg:mx-auto">
      <PortalHeading eyebrow="Minha conta" title="Perfil">
        <p>Atualize seus dados de contato e como prefere receber informações.</p>
      </PortalHeading>
      <div className="max-w-3xl border bg-card p-6 md:p-9">
        <div className="grid gap-6 sm:grid-cols-2">
          <Field
            label="Nome completo"
            value={profile.full_name}
            onChange={v => setProfile(p => ({ ...p, full_name: v }))}
            onBlur={v => save({ full_name: v })}
          />
          <div>
            <Label>E-mail</Label>
            <Input value={user.email ?? ""} disabled className="mt-2 h-11" />
            <p className="mt-1 text-xs text-muted-foreground">O e-mail de acesso não pode ser alterado aqui.</p>
          </div>
          <Field
            label="Telefone"
            value={profile.phone}
            onChange={v => setProfile(p => ({ ...p, phone: v }))}
            onBlur={v => save({ phone: v })}
          />
        </div>
        <div className="mt-9 border-t pt-7">
          <h2 className="font-display text-2xl text-primary">Preferências de comunicação</h2>
          <div className="mt-5 space-y-4">
            <Toggle
              label="Receber comunicados por e-mail"
              checked={profile.pref_email}
              set={v => { setProfile(p => ({ ...p, pref_email: v })); save({ pref_email: v }); }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, value, onChange, onBlur }: { label: string; value: string; onChange: (v: string) => void; onBlur: (v: string) => void }) {
  return (
    <div>
      <Label>{label}</Label>
      <Input
        value={value}
        onChange={e => onChange(e.target.value)}
        onBlur={e => onBlur(e.target.value)}
        maxLength={200}
        className="mt-2 h-11"
      />
    </div>
  );
}

function Toggle({ label, checked, set }: { label: string; checked: boolean; set: (v: boolean) => void }) {
  return <label className="flex items-center justify-between gap-4 border p-4 text-sm"><span>{label}</span><Switch checked={checked} onCheckedChange={set} /></label>;
}
