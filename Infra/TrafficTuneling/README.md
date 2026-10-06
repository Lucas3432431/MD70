# TrafficTuneling — MD70 em produção via Cloudflare Tunnel

Como o tráfego público chega ao servidor MD70 de produção, que roda num PC Windows
sem IP fixo e sem porta aberta no roteador.

## Visão geral

```
Usuário ──HTTPS──▶ Cloudflare (DNS + TLS + proxy)
                        │  CNAME md70.zera.tec.br → <TUNNEL_ID>.cfargotunnel.com
                        ▼
              conexões de saída (QUIC) abertas pelo cloudflared
                        │
┌─ Windows ─────────────┼──────────────────────────────────────────────┐
│  ┌─ Podman machine (WSL2, Fedora) ──────────────────────────────────┐ │
│  │                     ▼                                            │ │
│  │   md70_cloudflared  (--network host)                             │ │
│  │                     │ http://localhost:8080                      │ │
│  │                     ▼                                            │ │
│  │   md70_gateway  (nginx + ModSecurity, 0.0.0.0:8080 → 8181)       │ │
│  │        ├─▶ frontend:5182                                         │ │
│  │        └─▶ backend:4101 ─▶ redis, sandbox, browser, egress_proxy │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────┘
```

- **TLS termina na Cloudflare.** Do túnel até o gateway o tráfego é HTTP puro, dentro da máquina.
- **Nenhuma porta de entrada é aberta.** O `cloudflared` só faz conexões de saída para a Cloudflare.
- O gateway separa os sites pelo `Host` (`server_name`). Hoje só `DOMAIN_NAME=md70.zera.tec.br` está publicado.

## Componentes

| Item | Valor |
|---|---|
| Conta / zona | Cloudflare, zona `zera.tec.br` |
| Túnel | `md70`, ID `0ef4fe3c-875e-4893-ad30-2e4c742a18e1` (locally-managed) |
| DNS | `md70.zera.tec.br` CNAME → `0ef4fe3c-875e-4893-ad30-2e4c742a18e1.cfargotunnel.com` (proxied) |
| Conector | container `md70_cloudflared`, imagem `docker.io/cloudflare/cloudflared:2026.10.0` |
| Origem | `http://localhost:8080` → container `md70_gateway_<APP_VERSION>` |
| Config do túnel | `~/cloudflared/config.yml` na máquina (modelo: [`config.yml.example`](config.yml.example)) |
| Credencial do túnel | `~/cloudflared/<TUNNEL_ID>.json` na máquina, **fora do git** |
| Código em produção | `~/MD70` dentro da máquina do Podman (clone do repositório do Windows) |

## Onde cada coisa vive

Tudo de produção roda **dentro da máquina do Podman** (`podman-machine-default`, WSL2, Fedora),
não na pasta do Windows:

- `~/MD70`: clone do repositório. O `origin` aponta para o clone do Windows (`/mnt/c/Users/<user>/Trabalho/MD70`).
- `~/MD70/Infra/services/secrets/`: `compose.env`, `app.secrets`, `frontend.secrets` e `redis.conf`, gerados pelo `start_prod.sh`.
- `~/cloudflared/`: `config.yml` e a credencial do túnel (uid 65532, modo 600).
- `~/.config/containers/containers.conf`: `cgroups = "disabled"` (ver [Limitações](#limitações-conhecidas)).

Rodar a partir de `/mnt/c` (a pasta do Windows) **não funciona** por dois motivos:
1. O Git do Windows (`core.autocrlf=true`) faz checkout dos `.sh` com CRLF, e os entrypoints quebram (`/bin/bash^M`).
2. O `podman unshare chown` do `start_prod.sh` não tem efeito no 9p/drvfs (tudo fica root/777).

No Windows ainda ficam:
- `%USERPROFILE%\.cloudflared\cert.pem`: login da Cloudflare (zona `zera.tec.br`). Só serve para *administrar* túneis e DNS (`cloudflared tunnel create/route/delete`).
- `C:\ProgramData\cloudflared\`: cópia do `config.yml` e da credencial, com ACL restrita a SYSTEM, Administradores e o usuário.

## Operação

Entrar na máquina: `podman machine ssh`

| Ação | Comando |
|---|---|
| Ver containers | `podman ps -a --format '{{.Names}} \| {{.Status}}'` |
| Logs do túnel | `podman logs -f md70_cloudflared` |
| Reiniciar o túnel | `podman restart md70_cloudflared` |
| Logs do gateway | `podman logs -f md70_gateway_v1.0` |
| Religar tudo sem build | `bash ~/MD70/Infra/services/scripts/boot_prod.sh` |
| Deploy / atualizar | ver abaixo |

### Deploy de uma nova versão

```bash
# no Windows: atualizar o clone local
git -C "$env:USERPROFILE\Trabalho\MD70" pull

# na máquina (podman machine ssh)
cd ~/MD70 && git pull
cd Infra/services && ./scripts/start_prod.sh
```

Para trocar variáveis de ambiente, coloque um `.env.production` novo em `~/MD70/Infra/services/` antes do `start_prod.sh`. O script regenera os secrets e **apaga o `.env.production`**.

### Diagnóstico rápido

| Resposta em `https://md70.zera.tec.br` | Significado |
|---|---|
| **530** / erro 1033 | Túnel desconectado: o container `md70_cloudflared` está parado, ou a máquina do Podman está desligada |
| **502** | Túnel OK, mas nada responde em `localhost:8080`: gateway parado ou ainda subindo |
| **503/504** | Gateway OK, upstream (frontend/backend) indisponível ou lento |

O túnel também pode ser conferido no painel: Zero Trust → Networks → Tunnels → `md70`.

## Recriar do zero

1. **Login (Windows):** `cloudflared tunnel login` → escolher a zona **zera.tec.br**. Atenção: o `cert.pem` é por zona. Se escolher outra zona, o `route dns` cria o registro errado (por exemplo `md70.zera.tec.br.prox.dev.br`).
2. **Túnel (Windows):** `cloudflared tunnel create md70` gera `%USERPROFILE%\.cloudflared\<TUNNEL_ID>.json`.
3. **DNS (Windows):** `cloudflared tunnel route dns md70 md70.zera.tec.br`. Se já existir um registro com esse nome, use `--overwrite-dns`.
4. **Credencial para a máquina:**
   ```bash
   podman machine ssh
   mkdir -p ~/cloudflared && cp /mnt/c/Users/<user>/.cloudflared/<TUNNEL_ID>.json ~/cloudflared/
   ```
5. **Conector:** `~/MD70/Infra/TrafficTuneling/setup_tunnel.sh` (aceita `TUNNEL_ID`, `HOSTNAME_PUBLIC`, `ORIGIN` e `IMAGE` por variável de ambiente).

## Limitações conhecidas

- **Sem limites de CPU e memória.** Na máquina do Podman sobre WSL, os controladores de cgroup não são delegados ao usuário rootless (o processo fica em `/non-systemd/...`), e qualquer `deploy.resources.limits` falha com `crun: open memory.max`. Por isso `~/.config/containers/containers.conf` tem `cgroups = "disabled"`: os containers sobem, mas **os limites do compose são ignorados**. Rodar com root (`sudo podman`) aplicaria os limites, mas o `start_prod.sh` usa `podman unshare`, que exige rootless.
- **Por que não o serviço do Windows?** O `cloudflared service install` no Windows foi testado e descartado. Com `--config` no `ImagePath`, o serviço encerra com `flag provided but not defined: -config`. Sem argumentos, lendo `systemprofile\.cloudflared\config.yml`, cai em loop sem logar o motivo. Rodar o conector como container junto do MD70 evita isso e não exige administrador.
- **Reboot do Windows.** A tarefa agendada **"MD70 Boot"** (no logon do usuário, com 30s de atraso) roda [`boot_windows.ps1`](boot_windows.ps1). Ele liga a máquina do Podman, se precisar, e chama `Infra/services/scripts/boot_prod.sh`, que religa o túnel e os containers já criados, na ordem dos `depends_on` e esperando cada um ficar healthy. Não faz build. O log fica em `%LOCALAPPDATA%\md70-boot.log`. Como a máquina do Podman pertence ao usuário, **o MD70 só volta depois que alguém entra no Windows**: configure o login automático se o PC precisar se recuperar sozinho. Para recriar a tarefa:
  ```powershell
  $s = "$env:USERPROFILE\Trabalho\MD70\Infra\TrafficTuneling\boot_windows.ps1"
  $a = New-ScheduledTaskAction -Execute powershell.exe -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$s`""
  $t = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"; $t.Delay = 'PT30S'
  Register-ScheduledTask -TaskName 'MD70 Boot' -Action $a -Trigger $t -Force
  ```

- **Frontend self-hosted.** O `@lovable.dev/vite-tanstack-config` faz o build com o nitro no preset `cloudflare-module` (bundle de Worker), que não roda aqui. O `frontend/entrypoint.sh` de produção exporta `NITRO_PRESET=bun` e serve `.output/server/index.mjs`. Como o build roda no start do container, o frontend de prod não usa `read_only`.

## Segurança

- Credenciais (`<TUNNEL_ID>.json`, `cert.pem`) e secrets (`secrets/`, `.env.*`) **nunca** vão para o git. O `.gitignore` já cobre `secrets/`, `*.secrets` e `.env.*`.
- Quem tem o `<TUNNEL_ID>.json` consegue servir tráfego como `md70.zera.tec.br`. Se vazar: `cloudflared tunnel delete md70` e recriar.
- O gateway publica `0.0.0.0:8080` dentro da máquina. O acesso público passa **só** pelo túnel, então o ModSecurity e as regras do nginx continuam valendo.
