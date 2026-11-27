# Desktop P1.1+P1.2 (ficha B1 integral y edicion) en un equipo ya migrado al P0.
#   powershell -NoProfile -ExecutionPolicy Bypass -File instalar_desktop.ps1            (simulacion)
#   powershell -NoProfile -ExecutionPolicy Bypass -File instalar_desktop.ps1 -Aplicar   (instala)
# Arma el candidato con parchar_asar.py desde el app.asar instalado (debe ser E2C7E61B = Desktop 2914483) y exige el
# SHA-256 del manifiesto: el resultado es byte a byte el mismo app.asar instalado en CASA (38DBCEDE). Respalda el
# anterior en resources\app.asar.antes-p1-ficha-<fecha> y, ante cualquier falla, lo restaura. No toca datos ni el Motor.
param(
    [switch]$Aplicar,
    [string]$DesktopDir = (Join-Path $env:LOCALAPPDATA 'Programs\Atlas Viajes'),
    [string]$Python = 'C:\Atlas\Proyecto-Atlas\.venv\Scripts\python.exe'
)
$ErrorActionPreference = 'Stop'
$aqui = $PSScriptRoot
$manifiesto = Get-Content -LiteralPath (Join-Path $aqui 'manifiesto.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$resources = Join-Path $DesktopDir 'resources'
$actual = Join-Path $resources 'app.asar'
$exe = Join-Path $DesktopDir 'Atlas Viajes.exe'
function Huella([string]$ruta) { (Get-FileHash -LiteralPath $ruta -Algorithm SHA256).Hash.ToLowerInvariant() }

$hashActual = Huella $actual
if ($hashActual -eq $manifiesto.asar_salida_sha256) { Write-Output 'Desktop ya esta en P1.1+P1.2 (38DBCEDE); nada que hacer.'; return }
if ($hashActual -ne $manifiesto.asar_entrada_sha256) {
    throw "app.asar instalado $hashActual no es el esperado E2C7E61B (Desktop 2914483): detenerse y pedir revision."
}
$trabajo = Join-Path $env:TEMP ("atlas-desktop-p1-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $trabajo | Out-Null
$entrada = Join-Path $trabajo 'app-instalado.asar'
$candidato = Join-Path $trabajo 'candidato.asar'
Copy-Item -LiteralPath $actual -Destination $entrada
& $Python -I -X utf8 (Join-Path $aqui 'parchar_asar.py') --entrada $entrada --salida $candidato
if ($LASTEXITCODE -ne 0) { throw 'No se pudo armar el candidato (ver mensaje anterior).' }
if ((Huella $candidato) -ne $manifiesto.asar_salida_sha256) { throw 'Candidato con SHA-256 distinto del de CASA.' }
Write-Output "Candidato verificado: $($manifiesto.asar_salida_sha256)"
if (-not $Aplicar) { Write-Output "SIMULACION: se instalaria $candidato sobre $actual (respaldo en resources). Repetir con -Aplicar."; return }

$abiertos = @(Get-Process -Name 'Atlas Viajes' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe })
if ($abiertos.Count) {
    $abiertos | ForEach-Object { [void]$_.CloseMainWindow() }
    $limite = (Get-Date).AddSeconds(30)
    while ((Get-Process -Name 'Atlas Viajes' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe }) -and (Get-Date) -lt $limite) { Start-Sleep -Seconds 1 }
    if (Get-Process -Name 'Atlas Viajes' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe }) { throw 'Cierre Atlas Viajes y vuelva a ejecutar.' }
}
$respaldo = Join-Path $resources ('app.asar.antes-p1-ficha-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
Copy-Item -LiteralPath $actual -Destination $respaldo
if ((Huella $respaldo) -ne $manifiesto.asar_entrada_sha256) { throw 'Respaldo incorrecto; no se instala.' }
try {
    Copy-Item -LiteralPath $candidato -Destination $actual -Force
    if ((Huella $actual) -ne $manifiesto.asar_salida_sha256) { throw 'El app.asar instalado no coincide con el candidato.' }
    Write-Output "Desktop P1.1+P1.2 instalado (38DBCEDE). Respaldo: $respaldo"
} catch {
    Copy-Item -LiteralPath $respaldo -Destination $actual -Force
    throw "Instalacion revertida: $_"
}
