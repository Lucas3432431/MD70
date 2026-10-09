# MD70

## ⚠️ TEMPORÁRIO — Login anônimo

O botão "Área restrita" na página `/login/admin` está configurado como um **bypass de autenticação temporário**. Ao clicar, ele chama `POST /api/auth/anonymous` e gera uma sessão de admin sem credenciais.

**Isso deve ser removido antes de qualquer release público.**

Para remover:
1. **Backend** — deletar o endpoint `@auth_router.post("/anonymous")` em `Infra/services/backend/App/Core/Services/Auth/AuthRoutes.py`
2. **Frontend** — substituir o `<button>` de volta por `<p className="eyebrow">Área restrita</p>` em `Infra/services/frontend/src/routes/login/admin.tsx` e remover `handleAnonymousLogin` e `anonLoading`

## Produção

Deploy, túnel da Cloudflare, boot automático e configuração do computador servidor (energia, BIOS, login automático): ver [`Infra/TrafficTuneling/README.md`](Infra/TrafficTuneling/README.md).
