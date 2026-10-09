# Liga a máquina do Podman, atualiza o código (git pull), faz o build se o código
# mudou e sobe o stack de produção do MD70 (túnel incluso).
# Registrado como tarefa agendada "MD70 Boot": no logon do usuário e diariamente
# às 03:00 (ver README.md).
# Log: %LOCALAPPDATA%\md70-boot.log
#
# Fluxo:
#   1. podman machine start (se parada)
#   2. git pull no clone do Windows  (GitHub → Windows)
#   3. update_prod.sh na máquina: git pull (Windows → ~/MD70) e start_prod.sh
#      (build + up) só se Infra/services mudou desde o último deploy
#   4. boot_prod.sh: liga o túnel e espera cada container ficar healthy
# Se o pull ou o build falharem, o passo 4 religa os containers que já existiam,
# então o site volta na versão anterior em vez de ficar fora do ar.

$ErrorActionPreference = 'Continue'
$log = Join-Path $env:LOCALAPPDATA 'md70-boot.log'
Start-Transcript -Path $log -Append | Out-Null

$podman = 'C:\Program Files\RedHat\Podman\podman.exe'
$repo   = Join-Path $PSScriptRoot '..\..' | Resolve-Path

$state = & $podman machine inspect --format '{{.State}}' 2>$null
if ($state -ne 'running') {
    Write-Output "Iniciando podman machine (estado: $state)..."
    & $podman machine start
}

# BatchMode: sem terminal, o ssh falha em vez de ficar esperando senha/confirmação.
# Tenta algumas vezes porque logo após o logon a rede pode ainda não estar pronta.
$env:GIT_SSH_COMMAND = 'ssh -o BatchMode=yes -o ConnectTimeout=15'
$pulled = $false
for ($i = 1; $i -le 5 -and -not $pulled; $i++) {
    Write-Output "git pull no Windows ($repo), tentativa $i..."
    & git -C $repo pull --ff-only
    if ($LASTEXITCODE -eq 0) { $pulled = $true } else { Start-Sleep -Seconds 15 }
}
if (-not $pulled) {
    Write-Output "AVISO: git pull no Windows falhou; a máquina vai usar o último commit local."
}

# update_prod.sh só faz rebuild se Infra/services mudou desde o último deploy.
# boot_prod.sh não mexe em container que já está rodando.
$remote = 'bash ~/MD70/Infra/services/scripts/update_prod.sh; bash ~/MD70/Infra/services/scripts/boot_prod.sh'
& $podman machine ssh $remote

Stop-Transcript | Out-Null
