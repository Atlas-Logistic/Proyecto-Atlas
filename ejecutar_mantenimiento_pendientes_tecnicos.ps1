# Tarea exclusiva de pendientes técnicos. No invoca PULL Mobile.
# -SoloPlan: read-only, sin red; sirve para verificar la tarea instalada.
# PC nuevo: la tarea "Atlas Mantenimiento tecnico" ejecuta esta copia, en el
# mismo árbol del Motor que usa PULL (sólo commits publicados, árbol limpio),
# con el Python de su .venv. Cada pasada atiende a lo sumo 10 guías; sin
# trabajo no toma el escritor, y con el escritor ocupado (PULL) o una acción
# de B1 en curso la omite sin esperar (ver mantener_pendientes_tecnicos.py).
param(
    [string]$Datos = 'G:\Mi unidad\Atlas',
    [switch]$SoloPlan
)
$ErrorActionPreference = 'Stop'
$motor = $PSScriptRoot
$python = Join-Path $motor '.venv\Scripts\python.exe'
$git = 'C:\Program Files\Git\cmd\git.exe'
$logDir = Join-Path $env:LOCALAPPDATA 'AtlasMantenimientoTecnico'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$log = Join-Path $logDir 'mantenimiento.log'
# Log acotado: al superar 5 MB se conserva sólo la versión anterior.
if ((Test-Path -LiteralPath $log) -and (Get-Item -LiteralPath $log).Length -gt 5MB) {
    Move-Item -LiteralPath $log -Destination "$log.1" -Force
}
# Nunca escribir sobre los datos con código sin commit.
$commit = & $git -C $motor rev-parse --short HEAD
$sucio = & $git -C $motor status --porcelain --untracked-files=no
if ($LASTEXITCODE -ne 0 -or -not $commit -or $sucio) {
    Add-Content -LiteralPath $log -Value "$(Get-Date -Format o) MOTOR_CON_CAMBIOS_SIN_COMMIT motor=$motor commit=$commit" -Encoding UTF8
    exit 3
}
if (-not (Test-Path -LiteralPath (Join-Path $Datos 'operacion\actual\analisis_completo_guias.csv'))) {
    Add-Content -LiteralPath $log -Value "$(Get-Date -Format o) SIN_DATASET" -Encoding UTF8
    exit 2
}
$argumentos = @('-B', 'mantener_pendientes_tecnicos.py', '--raiz-atlas', $Datos)
if ($SoloPlan) { $argumentos += '--solo-plan' } else { $argumentos += '--tarea-programada' }
$env:PYTHONIOENCODING = 'utf-8'
Push-Location -LiteralPath $motor
try {
    $ErrorActionPreference = 'Continue'
    $salida = & $python @argumentos 2>&1
    $codigo = $LASTEXITCODE
    Add-Content -LiteralPath $log -Value "$(Get-Date -Format o) commit=$commit codigo=$codigo $($salida -join ' ')" -Encoding UTF8
    exit $codigo
} finally {
    Pop-Location
}
