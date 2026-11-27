# Migracion P0 de UN equipo (CASA u OFICINA). Sin -Aplicar es simulacion.
# Fases, en orden: Respaldo -> Motor -> RaizTrabajo -> Inicio -> Verificar.
# Deja migracion_p0_estado.json (LOCALAPPDATA\Atlas) para revertir_equipo.ps1.
# No toca Cloud: el protocolo 3 se activa aparte (protocolo_d1.ps1) cuando
# AMBOS equipos ya estan migrados.
param(
    [Parameter(Mandatory)][string]$Motor,             # C:\Atlas\Proyecto-Atlas
    [Parameter(Mandatory)][string]$Raiz,              # G:\Mi unidad\Atlas (pasa a ser la raiz PUBLICADA)
    [Parameter(Mandatory)][string]$RaizTrabajo,       # C:\AtlasTrabajo\Atlas (nueva, local, fuera de Drive)
    [Parameter(Mandatory)][string]$Commit,            # commit P0 publicado
    [Parameter(Mandatory)][string]$Rama,              # rama de origin que lo contiene
    [Parameter(Mandatory)][string]$Equipo,            # CASA | OFICINA (nombre del respaldo)
    [string]$LocalAppData = $env:LOCALAPPDATA,
    [string]$DesktopDir = (Join-Path $env:LOCALAPPDATA 'Programs\Atlas Viajes'),
    [string]$AccesoDirecto = '',                      # .lnk de Atlas a redirigir (varios separados por ';'; vacio: no se toca)
    [string]$Python = '',
    [switch]$SinTareas,                               # pruebas: no tocar tareas programadas
    [switch]$Aplicar
)
. (Join-Path $PSScriptRoot 'comun.ps1')
Iniciar-Registro $LocalAppData 'migracion_p0'
if (-not $Python) { $Python = Join-Path $Motor '.venv\Scripts\python.exe' }
$fecha = Get-Date -Format 'yyyyMMdd-HHmmss'
$rutaEstado = Join-Path $LocalAppData 'Atlas\migracion_p0_estado.json'
$estado = Leer-Json $rutaEstado
if ($estado -and $Aplicar) { throw "Ya existe $rutaEstado (migracion previa). Revertir primero o revisar." }
$antes = Git $Motor rev-parse HEAD
$respaldoDir = Join-Path $LocalAppData "Atlas\respaldo-p0-$fecha"
$ramaRespaldo = "respaldo/antes-p0-$($Equipo.ToLower())-$fecha"
$asar = Join-Path $DesktopDir 'resources\app.asar'
$accesos = @($AccesoDirecto -split ';' | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim() })
$i = 0
$respaldosAccesos = @($accesos | ForEach-Object { $i++; Join-Path $respaldoDir ("acceso$i-" + (Split-Path -Leaf $_)) })
$nuevoEstado = [ordered]@{
    equipo = $Equipo; fecha = $fecha; motor = $Motor; motor_antes = $antes; commit_nuevo = $Commit; rama = $Rama
    rama_respaldo = $ramaRespaldo; respaldo_dir = $respaldoDir; raiz_publicada = $Raiz; raiz_trabajo = $RaizTrabajo
    asar_respaldo = "$asar.antes-p0-$fecha"; accesos_directos = $accesos; accesos_directos_respaldo = $respaldosAccesos
}
Anotar "Migracion P0 de $Equipo ($(if ($Aplicar) {'APLICAR'} else {'SIMULACION'})): Motor $antes -> $Commit"

# ------------------------------------------------------------- Respaldo
Ejecutar $Aplicar "respaldo remoto del Motor en origin/$ramaRespaldo" { Git $Motor push --quiet origin "HEAD:refs/heads/$ramaRespaldo" | Out-Null }
Ejecutar $Aplicar "respaldo de la configuracion local en $respaldoDir" {
    New-Item -ItemType Directory -Path $respaldoDir -Force | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $LocalAppData 'Atlas') -File | Where-Object { $_.Extension -in '.json', '.txt' } |
        ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $respaldoDir }
}
Ejecutar $Aplicar "respaldo de Desktop ($($nuevoEstado.asar_respaldo))" {
    if (Test-Path -LiteralPath $asar) { Copy-Item -LiteralPath $asar -Destination $nuevoEstado.asar_respaldo }
}
for ($j = 0; $j -lt $accesos.Count; $j++) {
    $origen, $copia = $accesos[$j], $respaldosAccesos[$j]
    Ejecutar $Aplicar "respaldo del acceso directo $origen" {
        New-Item -ItemType Directory -Path $respaldoDir -Force | Out-Null
        if (Test-Path -LiteralPath $origen) { Copy-Item -LiteralPath $origen -Destination $copia }
    }
}
if ($Aplicar) { Escribir-Json $rutaEstado $nuevoEstado; Anotar "Estado de migracion: $rutaEstado" }

# ------------------------------------------------- Motor + RaizTrabajo
$tareas = Tareas-Pull -SinTareas:$SinTareas
Ejecutar $Aplicar "pausar $($tareas.Count) tarea(s) PULL/mantenimiento hasta preparar la raiz de trabajo" {
    foreach ($t in $tareas) { Disable-ScheduledTask -TaskPath $t.TaskPath -TaskName $t.TaskName | Out-Null; Anotar "Pausada: $($t.TaskName)" }
}
try {
    if ($Aplicar) {
        $limite = (Get-Date).AddMinutes(20)
        while ((Procesos-Motor).Count) {
            if ((Get-Date) -gt $limite) { throw 'Un proceso del Motor sigue en curso tras 20 minutos.' }
            Start-Sleep -Seconds 5
        }
        if (Git $Motor status --porcelain --untracked-files=no) { throw 'El Motor tiene cambios sin commit.' }
    }
    Ejecutar $Aplicar "Motor: fast-forward a $Commit desde origin/$Rama" {
        Git $Motor fetch --quiet origin $Rama | Out-Null
        $remoto = Git $Motor rev-parse FETCH_HEAD
        Git $Motor merge-base --is-ancestor $Commit $remoto | Out-Null
        Git $Motor merge-base --is-ancestor HEAD $Commit | Out-Null
        Git $Motor merge --ff-only --quiet $Commit | Out-Null
        Anotar "Motor en $(Git $Motor rev-parse HEAD)"
    }
    Ejecutar $Aplicar "raiz de trabajo $RaizTrabajo desde $Raiz (Drive pasa a ser la raiz publicada)" {
        $env:LOCALAPPDATA = $LocalAppData
        Push-Location -LiteralPath $Motor
        try {
            $r = (& $Python -B -m atlas_core.estado_confirmado --raiz-atlas $RaizTrabajo --preparar-raiz-trabajo $Raiz 2>&1 | Out-String).Trim()
            if ($LASTEXITCODE -ne 0) { throw "preparar-raiz-trabajo: $r" }
            Anotar "Raiz de trabajo: $r"
        } finally { Pop-Location }
    }
} finally {
    Ejecutar $Aplicar "reactivar las tareas pausadas" {
        foreach ($t in $tareas) { Enable-ScheduledTask -TaskPath $t.TaskPath -TaskName $t.TaskName | Out-Null; Anotar "Reactivada: $($t.TaskName)" }
    }
}

# ---------------------------------------------------------------- Inicio
foreach ($acceso in $accesos) {
    Ejecutar $Aplicar "acceso directo $acceso -> scripts\iniciar_atlas.ps1 (actualizacion automatica al iniciar)" {
        # Un acceso directo del escritorio puede sincronizarse (OneDrive) a un
        # equipo aun no migrado: sin iniciar_atlas.ps1 abre Atlas como antes.
        $iniciar = Join-Path $Motor 'scripts\iniciar_atlas.ps1'
        $exe = '$env:LOCALAPPDATA\Programs\Atlas Viajes\Atlas Viajes.exe'
        $comando = "if (Test-Path -LiteralPath '$iniciar') { & '$iniciar' } else { Start-Process -FilePath `"$exe`" }"
        $shell = New-Object -ComObject WScript.Shell
        $lnk = $shell.CreateShortcut($acceso)
        $lnk.TargetPath = (Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe')
        $lnk.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"$($comando.Replace('"', '\"'))`""
        $lnk.IconLocation = (Join-Path $DesktopDir 'Atlas Viajes.exe')
        $lnk.WorkingDirectory = $Motor
        $lnk.Save()
    }
}

# ------------------------------------------------------------- Verificar
if ($Aplicar -and $env:ATLAS_CLOUD_MOTOR_TOKEN) {
    Push-Location -LiteralPath $Motor
    try {
        Anotar "Verificacion (raiz publicada -> raiz de trabajo): $((& $Python -B -m atlas_core.estado_confirmado --verificar --raiz-atlas $Raiz 2>$null | Out-String).Trim())"
        Anotar "Diarios abiertos: $((& $Python -B -m atlas_core.estado_confirmado --diarios --raiz-atlas $Raiz 2>$null | Out-String).Trim())"
    } finally { Pop-Location }
}
Anotar "Migracion P0 de $Equipo terminada ($(if ($Aplicar) {'aplicada'} else {'simulada'}))."
