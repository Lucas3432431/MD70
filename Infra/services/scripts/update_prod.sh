#!/bin/bash
# Atualiza o código (git pull) e faz o rebuild do stack de produção só se o
# código em Infra/services mudou desde o último deploy bem-sucedido.
# Chamado pelo boot_windows.ps1 (tarefa agendada "MD70 Boot": no logon e diário).
#
# O último commit deployado fica em ~/.md70_deployed_commit. Comparar com ele
# (e não só com o HEAD de antes do pull) faz um build que falhou ser tentado de
# novo na próxima execução. Sem esse arquivo, faz o rebuild.
#
# Saída: 0 = atualizado ou nada a fazer; != 0 = build falhou (containers antigos ficam).
#
# Usage: ./update_prod.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"   # scripts → services → Infra → MD70
MARKER="$HOME/.md70_deployed_commit"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

cd "$REPO_ROOT" || exit 1

git pull --ff-only || log "AVISO: git pull falhou na máquina; verificando o commit atual."

HEAD_HASH="$(git rev-parse HEAD)"
DEPLOYED="$(cat "$MARKER" 2>/dev/null || true)"

if [ -n "$DEPLOYED" ] && git cat-file -e "$DEPLOYED^{commit}" 2>/dev/null \
    && git diff --quiet "$DEPLOYED" HEAD -- Infra/services; then
    log "Sem mudanças em Infra/services desde ${DEPLOYED:0:7} (HEAD ${HEAD_HASH:0:7}) — sem rebuild."
    exit 0
fi

log "Mudanças desde ${DEPLOYED:0:7} — rebuild em $(git log -1 --format='%h %s')"
if (cd Infra/services && ./scripts/start_prod.sh); then
    echo "$HEAD_HASH" > "$MARKER"
    log "Deploy de ${HEAD_HASH:0:7} concluído."
else
    log "AVISO: build falhou; os containers existentes serão religados."
    exit 1
fi
