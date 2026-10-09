# Liga a máquina do Podman, atualiza o código (git pull), faz o build e sobe o
# stack de produção do MD70 (túnel incluso).
# Registrado como tarefa agendada "MD70 Boot" no logon do usuário (ver README.md).
# Log: %LOCALAPPDATA%\md70-boot.log
#
# Fluxo:
#   1. podman machine start (se parada)
#   2. git pull no clone do Windows  (GitHub → Windows)
#   3. git pull no clone da máquina   (Windows → ~/MD70) + start_prod.sh (build + up)
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

$remote = @(
    'cd ~/MD70 && git pull --ff-only && (cd Infra/services && ./scripts/start_prod.sh)'
    '|| echo AVISO: pull/build falhou na maquina, religando os containers existentes;'
    'bash ~/MD70/Infra/services/scripts/boot_prod.sh'
) -join ' '
& $podman machine ssh $remote

Stop-Transcript | Out-Null
