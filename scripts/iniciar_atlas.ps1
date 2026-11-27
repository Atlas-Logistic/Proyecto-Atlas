# Inicio de Atlas con actualización automática (P0.5).
# 1. Actualiza Motor y Desktop a la versión publicada en la custodia Cloud
#    (con respaldo y vuelta atrás automática; ver actualizar_atlas.py).
# 2. Abre Desktop con lo que quede instalado, pase lo que pase en el paso 1.
# No escribe datos operacionales. Reemplazar el acceso directo por este
# script es un paso de instalación (no se hace aquí).
param(
    [string]$Config = (Join-Path $env:LOCALAPPDATA 'Atlas\desktop_operacion.json'),
    [string]$Desktop = (Join-Path $env:LOCALAPPDATA 'Programs\Atlas Viajes\Atlas Viajes.exe'),
    [switch]$SoloActualizar
)
$ErrorActionPreference = 'Continue'
$logs = Join-Path $env:LOCALAPPDATA 'Atlas\logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$log = Join-Path $logs 'actualizacion_inicio.log'
function Anotar([string]$texto) { Add-Content -LiteralPath $log -Value "$(Get-Date -Format o) $texto" -Encoding UTF8 }

try {
    $c = Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
    $motor = (Resolve-Path -LiteralPath $c.proyecto).Path
    $python = Join-Path $motor '.venv\Scripts\python.exe'
    if ($c.python) { $python = $c.python }
    Push-Location -LiteralPath $motor
    try {
        $salida = (& $python -B (Join-Path $motor 'actualizar_atlas.py') 2>&1 | Out-String).Trim()
    } finally { Pop-Location }
    Anotar "Actualización: $salida"
} catch {
    Anotar "Actualización no ejecutada: $($_.Exception.Message)"
}

if (-not $SoloActualizar) {
    # Electron arrancaría como Node si la variable viene heredada (VS Code).
    Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
    Start-Process -FilePath $Desktop
}
