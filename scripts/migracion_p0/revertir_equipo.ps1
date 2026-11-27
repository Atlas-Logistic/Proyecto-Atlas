# Reversion de la migracion P0 de UN equipo. Sin -Aplicar es simulacion.
# PRECONDICION en Cloud: protocolo_minimo <= 2 (protocolo_d1.ps1 -Nivel 2)
# ANTES de volver a un Motor de protocolo 2; si no, ese Motor no obtiene lease.
# La raiz publicada (Drive) ya tiene el ultimo estado confirmado: el Motor
# anterior vuelve a escribir en ella. La raiz de trabajo se conserva.
param(
    [string]$LocalAppData = $env:LOCALAPPDATA,
    [string]$Python = '',
    [switch]$SinTareas,
    [switch]$Forzar,          # revertir aunque haya publicacion pendiente (Drive atrasado)
    [switch]$Aplicar
)
. (Join-Path $PSScriptRoot 'comun.ps1')
Iniciar-Registro $LocalAppData 'migracion_p0_reversion'
$rutaEstado = Join-Path $LocalAppData 'Atlas\migracion_p0_estado.json'
$e = Leer-Json $rutaEstado
if (-not $e) { throw "No hay migracion registrada en $rutaEstado." }
$Motor = $e.motor
if (-not $Python) { $Python = Join-Path $Motor '.venv\Scripts\python.exe' }
Anotar "Reversion P0 de $($e.equipo) ($(if ($Aplicar) {'APLICAR'} else {'SIMULACION'})): Motor $(Git $Motor rev-parse HEAD) -> $($e.motor_antes)"

$pendiente = Join-Path $LocalAppData 'Atlas\cache\estado_confirmado\publicacion_pendiente.json'
if ((Test-Path -LiteralPath $pendiente) -and -not $Forzar) {
    throw "Hay publicacion pendiente ($pendiente): Drive no tiene todo lo confirmado. Ejecutar un PULL y reintentar, o -Forzar."
}

$tareas = @(Tareas-Pull -SinTareas:$SinTareas)
Ejecutar $Aplicar "pausar $($tareas.Count) tarea(s) PULL/mantenimiento" {
    foreach ($t in $tareas) { Disable-ScheduledTask -TaskPath $t.TaskPath -TaskName $t.TaskName | Out-Null }
}
try {
    if ($Aplicar) {
        $limite = (Get-Date).AddMinutes(20)
        while (@(Procesos-Motor).Count) {
            if ((Get-Date) -gt $limite) { throw 'Un proceso del Motor sigue en curso tras 20 minutos.' }
            Start-Sleep -Seconds 5
        }
    }
    Ejecutar $Aplicar "Motor de vuelta a $($e.motor_antes) (git reset --keep)" {
        Git $Motor reset --keep $e.motor_antes | Out-Null
        Anotar "Motor en $(Git $Motor rev-parse HEAD)"
    }
    $config = Join-Path $LocalAppData 'Atlas\raiz_publicada.json'
    Ejecutar $Aplicar "desactivar la raiz de trabajo (raiz_publicada.json -> .revertido): el Motor vuelve a $($e.raiz_publicada)" {
        if (Test-Path -LiteralPath $config) { Move-Item -LiteralPath $config -Destination "$config.revertido-$(Get-Date -Format yyyyMMdd-HHmmss)" }
    }
    $accesos = @($e.accesos_directos)
    $copias = @($e.accesos_directos_respaldo)
    for ($j = 0; $j -lt $accesos.Count; $j++) {
        $destino, $copia = $accesos[$j], $copias[$j]
        Ejecutar $Aplicar "restaurar el acceso directo $destino" {
            if (Test-Path -LiteralPath $copia) { Copy-Item -LiteralPath $copia -Destination $destino -Force }
            else { Remove-Item -LiteralPath $destino -ErrorAction SilentlyContinue }
        }
    }
    $asar = Join-Path (Split-Path -Parent $e.asar_respaldo) 'app.asar'
    Ejecutar $Aplicar "restaurar Desktop desde $($e.asar_respaldo) si fue actualizado" {
        if ((Test-Path -LiteralPath $e.asar_respaldo) -and (Get-FileHash $asar).Hash -ne (Get-FileHash $e.asar_respaldo).Hash) {
            Copy-Item -LiteralPath $e.asar_respaldo -Destination $asar -Force
        }
    }
    Ejecutar $Aplicar "archivar el estado de migracion" {
        Move-Item -LiteralPath $rutaEstado -Destination "$rutaEstado.revertido-$(Get-Date -Format yyyyMMdd-HHmmss)"
    }
} finally {
    Ejecutar $Aplicar "reactivar las tareas pausadas" {
        foreach ($t in $tareas) { Enable-ScheduledTask -TaskPath $t.TaskPath -TaskName $t.TaskName | Out-Null }
    }
}
Anotar "Reversion terminada. La raiz de trabajo $($e.raiz_trabajo) queda para inspeccion."
