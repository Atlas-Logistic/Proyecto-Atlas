# Comun a la migracion P0 (P0.1-P0.6). Dot-source desde los demas scripts.
# Sin -Aplicar todo es SIMULACION: se anota lo que se haria y no se cambia nada.
$ErrorActionPreference = 'Stop'

function Iniciar-Registro([string]$LocalAppData, [string]$Nombre) {
    $script:Logs = Join-Path $LocalAppData 'Atlas\logs'
    New-Item -ItemType Directory -Path $script:Logs -Force | Out-Null
    $script:Log = Join-Path $script:Logs "$Nombre.log"
}

function Anotar([string]$texto) {
    $linea = "$(Get-Date -Format o) $texto"
    if ($script:Log) { Add-Content -LiteralPath $script:Log -Value $linea -Encoding UTF8 }
    Write-Host $texto
}

function Leer-Json([string]$ruta) {
    if (-not (Test-Path -LiteralPath $ruta)) { return $null }
    return (Get-Content -LiteralPath $ruta -Raw -Encoding UTF8 | ConvertFrom-Json)
}

function Escribir-Json([string]$ruta, $objeto) {
    $dir = Split-Path -Parent $ruta
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    $tmp = "$ruta.$PID.tmp"
    # UTF-8 sin BOM: lo leen Python y Node.
    [System.IO.File]::WriteAllText($tmp, ($objeto | ConvertTo-Json -Depth 8), (New-Object System.Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $tmp -Destination $ruta -Force
}

function Git([string]$repo) {
    $git = (Get-Command git -ErrorAction SilentlyContinue).Source
    if (-not $git) { $git = 'C:\Program Files\Git\cmd\git.exe' }
    # PowerShell 5.1: el stderr de un nativo con Stop lanza aunque git termine bien.
    $previa = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $salida = & $git -C $repo @args 2>&1 | ForEach-Object { "$_" } }
    finally { $ErrorActionPreference = $previa }
    if ($LASTEXITCODE -ne 0) { throw "git $($args -join ' '): $($salida -join ' ')" }
    return (($salida | Where-Object { $_ -notmatch '^(warning|hint):' }) -join "`n").Trim()
}

function Tareas-Pull([switch]$SinTareas) {
    if ($SinTareas) { return @() }
    # Mismo criterio que scripts/actualizar_equipo_relevo.ps1.
    return @(Get-ScheduledTask | Where-Object {
        $_.State -ne 'Disabled' -and ($_.TaskName -match '(?i)atlas.*pull|pull.*atlas|atlas.*mantenimiento' -or
            ($_.Actions.Arguments -join ' ') -match '(?i)pull_cloud|sincronizar_mobile|pull_pc_nuevo|mantenimiento_pendientes')
    })
}

function Procesos-Motor() {
    return @(Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -match '(?i)sincronizar_mobile_cloud|mantener_pendientes_tecnicos|desktop_operacion_cli|b1_operador_cli|actualizar_atlas'
    })
}

function Ejecutar([bool]$Aplicar, [string]$descripcion, [scriptblock]$accion) {
    if ($Aplicar) { Anotar "APLICAR: $descripcion"; & $accion }
    else { Anotar "SIMULACION: $descripcion" }
}
