# Instala deshabilitada; activacion es un paso operacional separado.
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$TaskName = 'Atlas PULL PC nuevo - DESHABILITADO',
    [string]$Config = (Join-Path $env:LOCALAPPDATA 'Atlas\desktop_operacion.json'),
    [string]$Autorizacion = (Join-Path $env:LOCALAPPDATA 'Atlas\pull_autorizacion.json'),
    [string]$BackupDir = (Join-Path $env:LOCALAPPDATA 'Atlas\respaldos_pull'),
    [ValidateRange(1,60)][int]$CadaMinutos = 5,
    [string]$Empresa = '',
    [switch]$Plan
)
$ErrorActionPreference = 'Stop'
# -Empresa <id>: tarea propia de esa empresa (pull_pc_nuevo.ps1 -Empresa), con su
# configuracion y autorizacion en LOCALAPPDATA\Atlas\empresas\<id>. Convive con la
# de MBT y con las de otras empresas; sigue sin admitir dos de la misma empresa.
# Sin -Empresa todo es exactamente MBT.
$argEmpresa = ''
if ($Empresa) {
    if ($Empresa -cnotmatch '^[a-z][a-z0-9-]{1,38}[a-z0-9]$') { throw 'Empresa invalida.' }
    $localEmpresa = Join-Path $env:LOCALAPPDATA "Atlas\empresas\$Empresa"
    if (!$PSBoundParameters.ContainsKey('TaskName')) { $TaskName = "Atlas PULL $Empresa - DESHABILITADO" }
    if (!$PSBoundParameters.ContainsKey('Config')) { $Config = Join-Path $localEmpresa 'desktop_operacion.json' }
    if (!$PSBoundParameters.ContainsKey('Autorizacion')) { $Autorizacion = Join-Path $localEmpresa 'pull_autorizacion.json' }
    if (!$PSBoundParameters.ContainsKey('BackupDir')) { $BackupDir = Join-Path $localEmpresa 'respaldos_pull' }
    $argEmpresa = ' -Empresa "{0}"' -f $Empresa
}
$c = Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
$launcher = Join-Path $c.proyecto 'scripts\pull_pc_nuevo.ps1'
$ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
foreach ($ruta in @($launcher, $ps, $Config, $Autorizacion)) {
    # El plan de una empresa nueva se muestra antes de que Javier autorice su PULL.
    if ($Empresa -and $Plan -and $ruta -eq $Autorizacion) { continue }
    if (!(Test-Path -LiteralPath $ruta -PathType Leaf)) { throw "Falta archivo: $ruta" }
    if ($ruta.Contains('"')) { throw 'Ruta con comillas no permitida.' }
}
$argumentos = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -Config "{1}" -Autorizacion "{2}"' -f $launcher,$Config,$Autorizacion
$argumentos += $argEmpresa
if ($Plan) {
    [pscustomobject]@{TaskName=$TaskName;Execute=$ps;Arguments=$argumentos;CadaMinutos=$CadaMinutos;AlIniciarSesion=$true;Enabled=$false;MultipleInstances='IgnoreNew'} | ConvertTo-Json
    return
}
$otras = @(Get-ScheduledTask | Where-Object {
    $args_ = ($_.Actions.Arguments -join ' ')
    # Una tarea es de una empresa si lleva -Empresa; si no, es de MBT.
    $mismaEmpresa = if ($Empresa) { $args_ -match ('(?i)-Empresa "?' + [regex]::Escape($Empresa) + '"?(\s|$)') -or $_.TaskName -match ('(?i)^atlas pull ' + [regex]::Escape($Empresa) + ' - ') }
                    else { $args_ -notmatch '(?i)-Empresa ' -and $_.TaskName -notmatch '(?i)^atlas pull [a-z][a-z0-9-]+ - ' }
    $_.TaskName -ne $TaskName -and $mismaEmpresa -and ($_.TaskName -match '(?i)atlas.*pull|pull.*atlas' -or
        $args_ -match '(?i)pull_cloud|sincronizar_mobile|pull_pc_nuevo')
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
