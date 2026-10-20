# Preparado para activación explícita. No usar el lanzador histórico de oficina.
$ErrorActionPreference = 'Stop'
$base = Split-Path $PSScriptRoot -Parent
$gate = 'C:\Atlas\activacion-operativa\autorizacion.json'
if (!(Test-Path -LiteralPath $gate)) { throw 'PULL DESACTIVADO: falta autorización explícita y verificación de exclusividad.' }
$autorizacion = Get-Content -LiteralPath $gate -Raw | ConvertFrom-Json
if ($autorizacion.autor -ne 'Javier' -or !$autorizacion.exclusividad_verificada -or [datetime]$autorizacion.vence_utc -le [datetime]::UtcNow) {
    throw 'Autorización operacional inválida o vencida.'
}
if (!$env:ATLAS_CLOUD_MOTOR_TOKEN) { throw 'Falta credencial del escritor Cloud.' }
$env:ATLAS_DATA_DIR = 'G:\Mi unidad\Atlas'
$env:ATLAS_CATALOGOS_DIR = Join-Path $env:ATLAS_DATA_DIR 'catalogos_privados'
$env:ATLAS_OCR_PROVIDER = 'easyocr'
$pythonAtlas = Join-Path $base '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $pythonAtlas)) { throw 'Falta Python real .venv.' }
# sincronizar_mobile_cloud exige lease global y falla cerrado sin exclusividad.
& $pythonAtlas -B (Join-Path $base 'sincronizar_mobile_cloud.py') --raiz-atlas $env:ATLAS_DATA_DIR
exit $LASTEXITCODE
