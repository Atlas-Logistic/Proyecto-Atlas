# Protocolo minimo de lease en la D1 de Cloud (mismo mecanismo que activo el
# protocolo 2 el 29/10/2026). Sin -Aplicar solo muestra los comandos.
#   -Nivel 3: SOLO cuando CASA y OFICINA ya tienen el Motor P0 (protocolo 3).
#   -Nivel 2: reversion; ANTES de devolver cualquier equipo a un Motor anterior.
param(
    [Parameter(Mandatory)][ValidateSet(2, 3)][int]$Nivel,
    [string]$CloudRepo = 'C:\Atlas\Atlas-Mobile-Cloud',
    [string]$BaseDatos = 'atlas-mobile-recepcion-prueba',
    [switch]$Aplicar
)
$ErrorActionPreference = 'Stop'
$consulta = 'SELECT empresa_id, version, protocolo_minimo, confirmado_en FROM estado_operativo_marca'
$cambio = "UPDATE estado_operativo_marca SET protocolo_minimo = $Nivel"
$comandos = @(
    @('npx', 'wrangler', 'd1', 'execute', $BaseDatos, '--remote', '--command', $consulta),
    @('npx', 'wrangler', 'd1', 'execute', $BaseDatos, '--remote', '--command', $cambio),
    @('npx', 'wrangler', 'd1', 'execute', $BaseDatos, '--remote', '--command', $consulta)
)
foreach ($c in $comandos) {
    $texto = ($c | ForEach-Object { if ($_ -match '\s') { "`"$_`"" } else { $_ } }) -join ' '
    if (-not $Aplicar) { Write-Host "SIMULACION (en $CloudRepo): $texto"; continue }
    Push-Location -LiteralPath $CloudRepo
    try {
        & $c[0] $c[1..($c.Count - 1)]
        if ($LASTEXITCODE -ne 0) { throw "Fallo: $texto" }
    } finally { Pop-Location }
}
