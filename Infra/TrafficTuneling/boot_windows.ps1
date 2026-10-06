# Liga a máquina do Podman e religa o stack de produção do MD70 (túnel incluso).
# Registrado como tarefa agendada "MD70 Boot" no logon do usuário (ver README.md).
# Log: %LOCALAPPDATA%\md70-boot.log

$ErrorActionPreference = 'Continue'
$log = Join-Path $env:LOCALAPPDATA 'md70-boot.log'
Start-Transcript -Path $log -Append | Out-Null

$podman = 'C:\Program Files\RedHat\Podman\podman.exe'

$state = & $podman machine inspect --format '{{.State}}' 2>$null
if ($state -ne 'running') {
    Write-Output "Iniciando podman machine (estado: $state)..."
    & $podman machine start
}

& $podman machine ssh 'bash ~/MD70/Infra/services/scripts/boot_prod.sh'

Stop-Transcript | Out-Null
