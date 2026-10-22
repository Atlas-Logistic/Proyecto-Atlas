# Consumidor autorizado: mismo lease Cloud que las operaciones manuales compartidas.
[CmdletBinding()]
param(
    [string]$Config = (Join-Path $env:LOCALAPPDATA 'Atlas\desktop_operacion.json'),
    [string]$Autorizacion = (Join-Path $env:LOCALAPPDATA 'Atlas\pull_autorizacion.json'),
    [switch]$Validar
)
$ErrorActionPreference = 'Stop'
$c = Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
if ($c.modo_escritor -ne 'lease_cloud' -or !$c.autorizada -or !$c.habilitada) {
    throw 'PULL requiere politica explicita lease_cloud habilitada; equipo_unico no es compatible.'
}
$a = Get-Content -LiteralPath $Autorizacion -Raw -Encoding UTF8 | ConvertFrom-Json
if ($a.autor -ne 'Javier' -or !$a.exclusividad_verificada -or
    [datetime]$a.vence_utc -le [datetime]::UtcNow) { throw 'Autorizacion PULL invalida o vencida.' }
if (!$env:ATLAS_CLOUD_MOTOR_TOKEN) { throw 'Falta credencial Motor del usuario.' }
$base = (Resolve-Path -LiteralPath $c.proyecto).Path
$raiz = (Resolve-Path -LiteralPath $c.raiz).Path
$pythonAtlas = Join-Path $base '.venv\Scripts\python.exe'
if ($c.python) { $pythonAtlas = $c.python }
$rapid = $env:ATLAS_RAPIDOCR_PYTHON
if (!$rapid) { $rapid = Join-Path $env:LOCALAPPDATA 'Atlas\runtime\rapidocr\Scripts\python.exe' }
foreach ($ruta in @($pythonAtlas, $rapid, (Join-Path $base 'sincronizar_mobile_cloud.py'))) {
    if (!(Test-Path -LiteralPath $ruta -PathType Leaf)) { throw "Falta runtime o Motor: $ruta" }
}
$env:ATLAS_OPERACION_CONFIG = (Resolve-Path -LiteralPath $Config).Path
$env:ATLAS_DATA_DIR = $raiz
$env:ATLAS_CATALOGOS_DIR = Join-Path $raiz 'catalogos_privados'
$env:ATLAS_OCR_PROVIDER = 'rapidocr'
$env:ATLAS_OCR_MANUAL = '0'
$env:ATLAS_RAPIDOCR_PYTHON = $rapid
$env:PYTHONUNBUFFERED = '1'
if ($Validar) {
    [pscustomobject]@{Proyecto=$base;Raiz=$raiz;Python=$pythonAtlas;RapidPython=$rapid;OCR=$env:ATLAS_OCR_PROVIDER;Modo=$c.modo_escritor} | ConvertTo-Json
    return
}
$logs = Join-Path $env:LOCALAPPDATA 'Atlas\logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
# cmdlets de redireccion convierten stderr nativo en errores terminantes en PS5.
$ErrorActionPreference = 'Continue'
& $pythonAtlas -B (Join-Path $base 'sincronizar_mobile_cloud.py') --raiz-atlas $raiz *> (Join-Path $logs 'mobile_pull_cloud.log')
exit $LASTEXITCODE
