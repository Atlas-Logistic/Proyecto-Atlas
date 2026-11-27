# Comprobacion previa de la migracion P0, SOLO LECTURA. Codigo 0 = listo.
# Verifica: Motor instalado limpio y en el commit esperado, sin procesos del
# Motor en curso, custodia Cloud alineada (0 distintos), sin diarios abiertos,
# Desktop presente y espacio para la raiz de trabajo.
param(
    [Parameter(Mandatory)][string]$Motor,
    [Parameter(Mandatory)][string]$Raiz,              # raiz actual (Drive): G:\Mi unidad\Atlas
    [Parameter(Mandatory)][string]$RaizTrabajo,       # destino local: p. ej. C:\AtlasTrabajo\Atlas
    [string]$CommitEsperado = '',                     # commit instalado antes de migrar
    [string]$LocalAppData = $env:LOCALAPPDATA,
    [string]$DesktopRecursos = (Join-Path $env:LOCALAPPDATA 'Programs\Atlas Viajes\resources'),
    [string]$Python = ''
)
. (Join-Path $PSScriptRoot 'comun.ps1')
Iniciar-Registro $LocalAppData 'migracion_p0_preflight'
$fallas = @()
if (-not $Python) { $Python = Join-Path $Motor '.venv\Scripts\python.exe' }

$head = Git $Motor rev-parse HEAD
Anotar "Motor $Motor en $head"
if ($CommitEsperado -and $head -ne $CommitEsperado) { $fallas += "Motor en $head, se esperaba $CommitEsperado" }
if (Git $Motor status --porcelain --untracked-files=no) { $fallas += 'Motor con cambios sin commit' }
$procesos = Procesos-Motor
if ($procesos.Count) { $fallas += "Procesos del Motor en curso: $($procesos.Count)" }
if (-not (Test-Path -LiteralPath $Raiz)) { $fallas += "Raiz $Raiz no disponible" }
if (Test-Path -LiteralPath $RaizTrabajo) {
    if (@(Get-ChildItem -LiteralPath $RaizTrabajo -Force).Count) { $fallas += "La raiz de trabajo $RaizTrabajo ya existe y no esta vacia" }
}
$unidad = (Split-Path -Qualifier $RaizTrabajo).TrimEnd(':')
$libre = (Get-PSDrive -Name $unidad).Free
Anotar "Espacio libre en ${unidad}: $([math]::Round($libre/1GB,1)) GB"
if ($libre -lt 5GB) { $fallas += 'Menos de 5 GB libres para la raiz de trabajo' }
if (-not (Test-Path -LiteralPath (Join-Path $DesktopRecursos 'app.asar'))) { $fallas += "Desktop sin app.asar en $DesktopRecursos" }
if (-not $env:ATLAS_CLOUD_MOTOR_TOKEN) { $fallas += 'Sin ATLAS_CLOUD_MOTOR_TOKEN: no se puede verificar la custodia' }
else {
    Push-Location -LiteralPath $Motor
    try {
        $v = (& $Python -B -m atlas_core.estado_confirmado --verificar --raiz-atlas $Raiz 2>$null | Out-String).Trim()
        Anotar "Custodia: $v"
        $j = $v | ConvertFrom-Json
        if ($j.distintos -ne 0) { $fallas += "Custodia con $($j.distintos) archivo(s) distintos de Cloud" }
        if ($j.PSObject.Properties.Name -contains 'diarios_abiertos' -and @($j.diarios_abiertos).Count) {
            $fallas += "Diarios abiertos en Cloud: $(@($j.diarios_abiertos) -join ', ')"
        }
    } catch { $fallas += "Verificacion de custodia fallida: $($_.Exception.Message)" }
    finally { Pop-Location }
}
if ($fallas.Count) { foreach ($f in $fallas) { Anotar "NO LISTO: $f" }; exit 1 }
Anotar 'LISTO para migrar'
exit 0
