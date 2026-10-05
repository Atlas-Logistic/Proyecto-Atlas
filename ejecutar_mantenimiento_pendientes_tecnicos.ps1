# Tarea exclusiva de pendientes técnicos. No invoca PULL Mobile.
# -SoloPlan: read-only, sin red; sirve para verificar la tarea instalada.
# La tarea programada ejecuta la copia de este script que vive en el worktree
# estable (Proyecto-Atlas-Estable, HEAD desprendido en un commit publicado),
# nunca la del árbol de desarrollo. Se actualiza con promover_motor_estable.ps1.
param(
    [string]$Datos = 'G:\Mi unidad\Atlas',
    [switch]$SoloPlan
)
$ErrorActionPreference = 'Stop'
$motor = $PSScriptRoot
$python = 'C:\Users\Jjjc0508\AppData\Local\Programs\Python\Python312\python.exe'
$git = 'C:\Program Files\Git\cmd\git.exe'
$logDir = Join-Path $env:LOCALAPPDATA 'AtlasMantenimientoTecnico'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$log = Join-Path $logDir 'mantenimiento.log'
# Nunca escribir sobre los datos con código sin commit.
$commit = & $git -C $motor rev-parse --short HEAD
$sucio = & $git -C $motor status --porcelain --untracked-files=no
if ($LASTEXITCODE -ne 0 -or -not $commit -or $sucio) {
    Add-Content -LiteralPath $log -Value "$(Get-Date -Format o) MOTOR_CON_CAMBIOS_SIN_COMMIT motor=$motor commit=$commit" -Encoding UTF8
    exit 3
}
if (-not (Test-Path -LiteralPath (Join-Path $datos 'operacion\actual\analisis_completo_guias.csv'))) {
    Add-Content -LiteralPath $log -Value "$(Get-Date -Format o) SIN_DATASET" -Encoding UTF8
    exit 2
}
$argumentos = @('mantener_pendientes_tecnicos.py', '--raiz-atlas', $Datos)
if ($SoloPlan) { $argumentos += '--solo-plan' }
Push-Location -LiteralPath $motor
try {
    $salida = & $python @argumentos 2>&1
    $codigo = $LASTEXITCODE
    Add-Content -LiteralPath $log -Value "$(Get-Date -Format o) commit=$commit codigo=$codigo $($salida -join ' ')" -Encoding UTF8
    exit $codigo
} finally {
    Pop-Location
}
