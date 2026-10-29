# Actualiza el Motor de ESTE equipo a un commit publicado del relevo automático
# (protocolo 2 del lease) sin interrumpir ciclos: pausa PULL y mantenimiento,
# espera su término natural, fast-forward, reactiva lo que estaba activo y
# verifica en sólo lectura la copia local contra la marca Cloud.
# No toca datos operacionales; no corre PULL ni OCR.
param(
    [Parameter(Mandatory)][string]$Commit,
    [Parameter(Mandatory)][string]$Rama,
    [string]$Config = (Join-Path $env:LOCALAPPDATA 'Atlas\desktop_operacion.json')
)
$ErrorActionPreference = 'Stop'
$logs = Join-Path $env:LOCALAPPDATA 'Atlas\logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$log = Join-Path $logs 'actualizacion_relevo.log'
function Anotar([string]$texto) { $linea = "$(Get-Date -Format o) $texto"; Add-Content -LiteralPath $log -Value $linea -Encoding UTF8; Write-Host $texto }

$c = Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
$motor = (Resolve-Path -LiteralPath $c.proyecto).Path
$raiz = $c.raiz
$git = (Get-Command git -ErrorAction SilentlyContinue).Source
if (!$git) { $git = 'C:\Program Files\Git\cmd\git.exe' }
$python = Join-Path $motor '.venv\Scripts\python.exe'
if ($c.python) { $python = $c.python }

$actual = (& $git -C $motor rev-parse HEAD).Trim()
Anotar "Motor $motor en $actual; objetivo $Commit ($Rama)"
$tareas = @()
if ($actual -ne $Commit) {
    if (& $git -C $motor status --porcelain --untracked-files=no) { throw 'El Motor tiene cambios sin commit; no se actualiza.' }
    & $git -C $motor fetch --quiet origin $Rama
    if ($LASTEXITCODE -ne 0) { throw "git fetch de $Rama falló" }
    $remoto = (& $git -C $motor rev-parse FETCH_HEAD).Trim()
    & $git -C $motor merge-base --is-ancestor $Commit $remoto
    if ($LASTEXITCODE -ne 0) { throw "$Commit no está publicado en origin/$Rama" }
    & $git -C $motor merge-base --is-ancestor HEAD $Commit
    if ($LASTEXITCODE -ne 0) { throw "HEAD $actual no es ancestro de $Commit; se requiere revisión." }

    # Mismos criterios que instalar_tarea_pull.ps1 para reconocer consumidores.
    $tareas = @(Get-ScheduledTask | Where-Object {
        $_.State -ne 'Disabled' -and ($_.TaskName -match '(?i)atlas.*pull|pull.*atlas|atlas.*mantenimiento' -or
            ($_.Actions.Arguments -join ' ') -match '(?i)pull_cloud|sincronizar_mobile|pull_pc_nuevo|mantenimiento_pendientes')
    })
    foreach ($t in $tareas) { Disable-ScheduledTask -TaskPath $t.TaskPath -TaskName $t.TaskName | Out-Null; Anotar "Pausada: $($t.TaskName)" }
    try {
        $limite = (Get-Date).AddMinutes(20)
        do {
            $corriendo = @($tareas | Where-Object { (Get-ScheduledTask -TaskPath $_.TaskPath -TaskName $_.TaskName).State -eq 'Running' })
            $procesos = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '(?i)sincronizar_mobile_cloud|mantener_pendientes_tecnicos' })
            if (!$corriendo.Count -and !$procesos.Count) { break }
            if ((Get-Date) -gt $limite) { throw 'Un ciclo sigue en curso tras 20 minutos; no se actualiza.' }
            Start-Sleep -Seconds 5
        } while ($true)
        & $git -C $motor merge --ff-only --quiet $Commit
        if ($LASTEXITCODE -ne 0) { throw 'fast-forward falló' }
        Anotar "Motor actualizado a $((& $git -C $motor rev-parse HEAD).Trim())"
    } finally {
        foreach ($t in $tareas) { Enable-ScheduledTask -TaskPath $t.TaskPath -TaskName $t.TaskName | Out-Null; Anotar "Reactivada: $($t.TaskName)" }
    }
}

$verificacion = ''
if ($env:ATLAS_CLOUD_MOTOR_TOKEN) {
    Push-Location -LiteralPath $motor
    try { $verificacion = (& $python -B -m atlas_core.estado_confirmado --verificar --raiz-atlas $raiz 2>&1 | Out-String).Trim() } finally { Pop-Location }
} else { $verificacion = 'SIN_TOKEN_MOTOR' }
Anotar "Verificación sólo lectura: $verificacion"

$idEscritor = ''
$rutaId = Join-Path $env:LOCALAPPDATA 'Atlas\escritor_operativo_id.txt'
if (Test-Path -LiteralPath $rutaId) { $idEscritor = (Get-Content -LiteralPath $rutaId -Raw).Trim() }
$guid = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Cryptography').MachineGuid
$estado = [pscustomobject]@{
    equipo = $env:COMPUTERNAME; machine_guid = $guid; escritor_id = $idEscritor
    commit = (& $git -C $motor rev-parse HEAD).Trim(); fecha = (Get-Date).ToString('o')
    tareas_reactivadas = @($tareas | ForEach-Object { $_.TaskName }); verificacion = $verificacion
}
# Constancia para el otro equipo; fuera de las carpetas operacionales.
$destino = Join-Path $raiz 'coordinacion\estado_equipos'
New-Item -ItemType Directory -Path $destino -Force | Out-Null
$estado | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $destino "$guid.json") -Encoding UTF8
Anotar 'Listo.'
