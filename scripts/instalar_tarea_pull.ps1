# Instala deshabilitada; activacion es un paso operacional separado.
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$TaskName = 'Atlas PULL PC nuevo - DESHABILITADO',
    [string]$Config = (Join-Path $env:LOCALAPPDATA 'Atlas\desktop_operacion.json'),
    [string]$Autorizacion = (Join-Path $env:LOCALAPPDATA 'Atlas\pull_autorizacion.json'),
    [string]$BackupDir = (Join-Path $env:LOCALAPPDATA 'Atlas\respaldos_pull'),
    [ValidateRange(1,60)][int]$CadaMinutos = 5,
    [switch]$Plan
)
$ErrorActionPreference = 'Stop'
$c = Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
$launcher = Join-Path $c.proyecto 'scripts\pull_pc_nuevo.ps1'
$ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
foreach ($ruta in @($launcher, $ps, $Config, $Autorizacion)) {
    if (!(Test-Path -LiteralPath $ruta -PathType Leaf)) { throw "Falta archivo: $ruta" }
    if ($ruta.Contains('"')) { throw 'Ruta con comillas no permitida.' }
}
$argumentos = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -Config "{1}" -Autorizacion "{2}"' -f $launcher,$Config,$Autorizacion
if ($Plan) {
    [pscustomobject]@{TaskName=$TaskName;Execute=$ps;Arguments=$argumentos;CadaMinutos=$CadaMinutos;AlIniciarSesion=$true;Enabled=$false;MultipleInstances='IgnoreNew'} | ConvertTo-Json
    return
}
$otras = @(Get-ScheduledTask | Where-Object {
    $_.TaskName -ne $TaskName -and ($_.TaskName -match '(?i)atlas.*pull|pull.*atlas' -or
        ($_.Actions.Arguments -join ' ') -match '(?i)pull_cloud|sincronizar_mobile|pull_pc_nuevo')
})
if ($otras.Count) { throw 'Existen otras tareas consumidoras; no se instala una duplicada.' }
$previa = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($previa -and $previa.State -ne 'Disabled') { throw 'Deshabilitar y esperar cierre antes de reinstalar.' }
if (!$PSCmdlet.ShouldProcess($TaskName, 'Respaldar y registrar deshabilitada')) { return }
New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
if ($previa) {
    $backup = Join-Path $BackupDir ('tarea-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.xml')
    Export-ScheduledTask -TaskName $TaskName | Set-Content -LiteralPath $backup -Encoding Unicode
}
$accion = New-ScheduledTaskAction -Execute $ps -Argument $argumentos -WorkingDirectory $c.proyecto
$periodico = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes($CadaMinutos) -RepetitionInterval (New-TimeSpan -Minutes $CadaMinutos)
$usuario = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$sesion = New-ScheduledTaskTrigger -AtLogOn -User $usuario
$principal = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -Disable
$tarea = New-ScheduledTask -Action $accion -Trigger @($periodico,$sesion) -Principal $principal -Settings $settings
Register-ScheduledTask -TaskName $TaskName -InputObject $tarea -Force | Out-Null
