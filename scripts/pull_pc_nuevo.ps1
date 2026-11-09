# Consumidor autorizado: mismo lease Cloud que las operaciones manuales compartidas.
[CmdletBinding()]
param(
    [string]$Config = (Join-Path $env:LOCALAPPDATA 'Atlas\desktop_operacion.json'),
    [string]$Autorizacion = (Join-Path $env:LOCALAPPDATA 'Atlas\pull_autorizacion.json'),
    [string]$Empresa = '',
    [switch]$Validar
)
$ErrorActionPreference = 'Stop'
# Sin -Empresa todo es exactamente MBT. Con -Empresa, configuracion, autorizacion,
# logs y credencial son los de esa empresa; atlas_core aplica la frontera.
$localEmpresa = $null
if ($Empresa) {
    if ($Empresa -cnotmatch '^[a-z][a-z0-9-]{1,38}[a-z0-9]$') { throw 'Empresa invalida.' }
    $localEmpresa = Join-Path $env:LOCALAPPDATA "Atlas\empresas\$Empresa"
    if (!$PSBoundParameters.ContainsKey('Config')) { $Config = Join-Path $localEmpresa 'desktop_operacion.json' }
    if (!$PSBoundParameters.ContainsKey('Autorizacion')) { $Autorizacion = Join-Path $localEmpresa 'pull_autorizacion.json' }
}
$c = Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
if ($c.modo_escritor -ne 'lease_cloud' -or !$c.autorizada -or !$c.habilitada) {
    throw 'PULL requiere politica explicita lease_cloud habilitada; equipo_unico no es compatible.'
}
if ($Empresa) {
    if (!$c.raiz_mbt) { throw 'Configuracion de empresa sin raiz_mbt.' }
    $variableToken = 'ATLAS_CLOUD_MOTOR_TOKEN__' + $Empresa.ToUpperInvariant().Replace('-', '_')
    if (![Environment]::GetEnvironmentVariable($variableToken)) { throw 'Falta credencial Motor de la empresa.' }
    $env:ATLAS_EMPRESA_ID = $Empresa
    $env:ATLAS_RAIZ_MBT = (Resolve-Path -LiteralPath $c.raiz_mbt).Path
} elseif (!$env:ATLAS_CLOUD_MOTOR_TOKEN) { throw 'Falta credencial Motor del usuario.' }
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
$env:ATLAS_PULL_AUTORIZACION = (Resolve-Path -LiteralPath $Autorizacion).Path
& $pythonAtlas -B (Join-Path $base 'atlas_core\autorizacion_pull.py') --autorizacion $env:ATLAS_PULL_AUTORIZACION --config $env:ATLAS_OPERACION_CONFIG
if ($LASTEXITCODE -ne 0) { throw 'Autorizacion PULL ausente, invalida, revocada o vencida.' }
$env:ATLAS_DATA_DIR = $raiz
$env:ATLAS_CATALOGOS_DIR = Join-Path $raiz 'catalogos_privados'
$env:ATLAS_OCR_PROVIDER = 'rapidocr'
$env:ATLAS_OCR_MANUAL = '0'
$env:ATLAS_RAPIDOCR_PYTHON = $rapid
$env:PYTHONUNBUFFERED = '1'
if ($Validar) {
    $resumen = [ordered]@{Proyecto=$base;Raiz=$raiz;Python=$pythonAtlas;RapidPython=$rapid;OCR=$env:ATLAS_OCR_PROVIDER;Modo=$c.modo_escritor}
    if ($Empresa) { $resumen.Empresa = $Empresa; $resumen.Config = $env:ATLAS_OPERACION_CONFIG }
    [pscustomobject]$resumen | ConvertTo-Json
    return
}
$logs = if ($localEmpresa) { Join-Path $localEmpresa 'logs' } else { Join-Path $env:LOCALAPPDATA 'Atlas\logs' }
New-Item -ItemType Directory -Path $logs -Force | Out-Null
# cmdlets de redireccion convierten stderr nativo en errores terminantes en PS5.
$ErrorActionPreference = 'Continue'
& $pythonAtlas -B (Join-Path $base 'sincronizar_mobile_cloud.py') --raiz-atlas $raiz *> (Join-Path $logs 'mobile_pull_cloud.log')
exit $LASTEXITCODE
