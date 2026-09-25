# Tarea exclusiva de pendientes técnicos. No invoca PULL Mobile.
# -SoloPlan: read-only, sin red; sirve para verificar la tarea instalada.
param(
    [string]$Datos = 'G:\Mi unidad\Atlas',
    [switch]$SoloPlan
)
$ErrorActionPreference = 'Stop'
$motor = $PSScriptRoot
$python = 'C:\Users\Jjjc0508\AppData\Local\Programs\Python\Python312\python.exe'
$logDir = Join-Path $env:LOCALAPPDATA 'AtlasMantenimientoTecnico'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$log = Join-Path $logDir 'mantenimiento.log'
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
    Add-Content -LiteralPath $log -Value "$(Get-Date -Format o) codigo=$codigo $($salida -join ' ')" -Encoding UTF8
    exit $codigo
} finally {
    Pop-Location
}
