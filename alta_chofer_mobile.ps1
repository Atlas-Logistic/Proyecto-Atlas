param([string]$Usuario, [string]$Rut, [string]$Nombre)
# Alta interactiva de un chofer MBT en Atlas Mobile (catalogo + credencial local + D1 + prueba de ingreso).
# Uso: doble clic en alta_chofer_mobile.cmd (o con -Usuario -Rut -Nombre). La contrasena SOLO se escribe
# cuando se pide (no se muestra); nunca va en argumentos, archivos ni registros.
#   1) valida datos y duplicados (sin escribir)       4) publica en D1 y prueba el ingreso (script Cloud oficial)
#   2) respaldo de los dos catalogos (solo su usuario) 5) prueba de ingreso en mobile.dttacgroup.cl
#   3) alta local con el escritor oficial (lease); si PULL lo ocupa: pausa controlada, reintento,
#      reactivacion y verificacion de 2 ciclos PULL con codigo 0.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$motor = $PSScriptRoot
$py = Join-Path $motor '.venv\Scripts\python.exe'
$cloud = 'C:\Atlas\Atlas-Mobile-Cloud'
$empresaCloud = 'empresa-prueba-javier'   # = CLOUD_MBT en atlas_core/aislamiento_empresas.py
$urlMobile = 'https://mobile.dttacgroup.cl/api/mobile/login'
$config = Join-Path $env:LOCALAPPDATA 'Atlas\desktop_operacion.json'
$respaldos = 'C:\Atlas\backups_catalogos'

function Paso([string]$t) { Write-Host ''; Write-Host "=== $t" -ForegroundColor Cyan }
function Fin([string]$t, [int]$codigo) {
  Write-Host ''; Write-Host $t -ForegroundColor $(if ($codigo) { 'Red' } else { 'Green' })
  Read-Host 'Pulse Enter para cerrar' | Out-Null; exit $codigo
}
function Confirmar([string]$pregunta) { "$(Read-Host "$pregunta Escriba SI para continuar")".Trim() -ieq 'SI' }

function Alta([switch]$SoloValidar) {
  $a = @('-B', (Join-Path $motor 'alta_chofer_mobile.py'), '--raiz-atlas', $raiz, '--usuario', $Usuario, '--rut', $Rut,
         '--nombre', $Nombre, '--empresa', $empresaCloud)
  if ($SoloValidar) { $a += '--solo-validar' }
  $ErrorActionPreference = 'Continue'
  $linea = & $py @a | Select-Object -Last 1
  $codigo = $LASTEXITCODE
  $ErrorActionPreference = 'Stop'
  try { $r = $linea | ConvertFrom-Json } catch { $r = [pscustomobject]@{ resultado = 'ERROR'; codigo = 'SALIDA_ILEGIBLE'; detalle = "$linea" } }
  [pscustomobject]@{ codigo = $codigo; r = $r }
}

function TareasPull {
  @(Get-ScheduledTask | Where-Object { $_.State -ne 'Disabled' -and ($_.TaskName -match '(?i)atlas.*pull|pull.*atlas|atlas.*mantenimiento' -or
    ($_.Actions.Arguments -join ' ') -match '(?i)pull_cloud|sincronizar_mobile|pull_pc_nuevo|mantenimiento_pendientes') })
}
function EsperarSinPull([int]$minutos) {
  $fin = (Get-Date).AddMinutes($minutos)
  while (@(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and
           $_.CommandLine -match '(?i)pull_pc_nuevo|sincronizar_mobile_cloud|mantener_pendientes_tecnicos|rapidocr_worker' }).Count) {
    if ((Get-Date) -gt $fin) { throw "PULL sigue en ejecucion tras $minutos min" }
    Start-Sleep -Seconds 3
  }
}
function VerificarCiclosPull([datetime]$desde, [int]$ciclos = 2, [int]$minutos = 12) {
  $logs = Join-Path $env:LOCALAPPDATA 'Atlas\logs\pull_ciclos'; $fin = (Get-Date).AddMinutes($minutos)
  Write-Host "Esperando $ciclos ciclos PULL completos (max $minutos min)..."
  do {
    $nuevos = @(Get-ChildItem $logs -Filter 'pull_*.log' | Where-Object { $_.CreationTime -gt $desde } |
                Where-Object { (Get-Content $_.FullName -Tail 1 -Encoding UTF8) -match '### FIN' })
    if ($nuevos.Count -ge $ciclos) { break }
    if ((Get-Date) -gt $fin) { throw "Solo $($nuevos.Count) ciclos PULL completos en $minutos min" }
    Start-Sleep -Seconds 10
  } while ($true)
  foreach ($n in $nuevos) {
    $ultima = Get-Content $n.FullName -Tail 1 -Encoding UTF8
    if ($ultima -notmatch '"codigo": 0') { throw "Ciclo PULL fallido: $($n.Name)" }
    Write-Host "PULL $($n.Name): codigo 0"
  }
}

try {
  Write-Host 'ATLAS MOBILE - Alta de chofer (empresa MBT)' -ForegroundColor Cyan
  if (!(Test-Path -LiteralPath $py)) { throw "No existe $py" }
  $c = Get-Content -LiteralPath $config -Raw -Encoding UTF8 | ConvertFrom-Json
  $raiz = [string]$c.raiz
  if (!$raiz -or !(Test-Path -LiteralPath (Join-Path $raiz 'catalogos_privados'))) { throw "Raiz Atlas no disponible: '$raiz'" }
  # Mismo entorno que el lanzador PULL (scripts/pull_pc_nuevo.ps1).
  $env:ATLAS_OPERACION_CONFIG = $config; $env:ATLAS_DATA_DIR = $raiz
  $env:ATLAS_CATALOGOS_DIR = Join-Path $raiz 'catalogos_privados'; $env:PYTHONIOENCODING = 'utf-8'
  if (!$Usuario) { $Usuario = Read-Host 'Usuario Mobile (ej. nombre.apellido)' }
  if (!$Rut) { $Rut = Read-Host 'RUT con digito verificador (ej. 11.640.500-8)' }
  if (!$Nombre) { $Nombre = Read-Host 'Nombre completo (ej. RAIMUNDO PINEDA)' }

  Paso '1/5 Validacion de datos y duplicados (no escribe)'
  $v = Alta -SoloValidar
  if ($v.codigo -ne 0) { Fin "RECHAZADO: $($v.r.codigo) - $($v.r.detalle)" 1 }
  Write-Host "Usuario: $($v.r.usuario)   RUT: $($v.r.chofer_id)   Nombre: $($v.r.nombre)   Empresa: $($v.r.empresa_cloud)"
  if (!(Confirmar 'Datos correctos?')) { Fin 'Cancelado. No se escribio nada.' 1 }

  Paso '2/5 Respaldo de catalogos'
  if (!(Test-Path -LiteralPath $respaldos)) {
    New-Item -ItemType Directory $respaldos | Out-Null
    $u = "$env:USERDOMAIN\$env:USERNAME"; & icacls.exe $respaldos /inheritance:r /grant:r "${u}:(OI)(CI)F" | Out-Null
  }
  $destino = Join-Path $respaldos ("alta-{0}-{1}" -f $v.r.usuario, (Get-Date -Format 'yyyyMMdd-HHmmss'))
  New-Item -ItemType Directory $destino | Out-Null
  foreach ($n in 'choferes.json', 'usuarios_mobile.json') {
    $o = Join-Path $raiz "catalogos_privados\$n"; Copy-Item -LiteralPath $o (Join-Path $destino "$n.antes")
    if ((Get-FileHash $o).Hash -ne (Get-FileHash (Join-Path $destino "$n.antes")).Hash) { throw "Respaldo incorrecto: $n" }
  }
  Write-Host "Respaldo verificado (acceso solo de su usuario): $destino"

  Paso '3/5 Alta local con el escritor oficial'
  Write-Host 'Escriba la contrasena inicial cuando se pida (no se muestra) y repitala.'
  $a = Alta
  if ($a.codigo -eq 3) {
    Write-Host 'El escritor sigue ocupado (normalmente PULL procesando envios). No se escribio nada.' -ForegroundColor Yellow
    if (!(Confirmar 'Pausar PULL de forma controlada, reintentar el alta y reactivarlo?')) { Fin 'Cancelado. No se escribio nada.' 1 }
    $pausadas = @(); $reactivado = $null
    try {
      foreach ($t in TareasPull) { Disable-ScheduledTask -TaskPath $t.TaskPath -TaskName $t.TaskName | Out-Null; $pausadas += $t; Write-Host "Pausada: $($t.TaskName) $(Get-Date -Format HH:mm:ss)" }
      EsperarSinPull 10
      Write-Host 'PULL detenido. Escriba otra vez la contrasena inicial y repitala.'
      $a = Alta
    } finally {
      foreach ($t in $pausadas) { Enable-ScheduledTask -TaskPath $t.TaskPath -TaskName $t.TaskName | Out-Null; Write-Host "Reactivada: $($t.TaskName) $(Get-Date -Format HH:mm:ss)" }
      $reactivado = Get-Date
    }
    if ($pausadas.Count) { VerificarCiclosPull $reactivado }
  }
  if ($a.codigo -ne 0 -or $a.r.resultado -ne 'ALTA_APLICADA') { Fin "ALTA LOCAL NO APLICADA: $($a.r.codigo) - $($a.r.detalle)" 1 }
  Write-Host "Alta local aplicada y verificada: $($a.r.verificacion | ConvertTo-Json -Compress)" -ForegroundColor Green

  Paso '4/5 Publicacion en Cloud (D1) y prueba de ingreso'
  Write-Host 'Escriba la misma contrasena (se comprueba contra la recien guardada).'
  Push-Location $cloud
  try {
    $ErrorActionPreference = 'Continue'
    $linea = & $py -B 'scripts\migrar_usuario_mobile_cloud.py' --usuario $v.r.usuario --empresa-id $empresaCloud --aplicar --probar-login | Select-Object -Last 1
    $codigo = $LASTEXITCODE; $ErrorActionPreference = 'Stop'
  } finally { Pop-Location }
  try { $m = $linea | ConvertFrom-Json } catch { $m = $null }
  if ($codigo -ne 0 -or !$m -or $m.d1 -ne 'UPSERT aplicado') { Fin "PUBLICACION EN D1 FALLIDA (el alta local quedo hecha; reintente solo este paso): $linea" 1 }
  if ($m.login_cloud.http -ne 200 -or -not $m.login_cloud.token) { Fin "Publicado en D1 pero el ingreso de prueba fallo (HTTP $($m.login_cloud.http))." 1 }
  Write-Host 'D1 publicado e ingreso de prueba correcto.' -ForegroundColor Green

  Paso '5/5 Ingreso en mobile.dttacgroup.cl'
  $s = Read-Host -AsSecureString 'Escriba la contrasena una ultima vez'
  $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
  try {
    $cuerpo = @{ usuario = $v.r.usuario; password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) } | ConvertTo-Json -Compress
    try {
      $resp = Invoke-WebRequest -Uri $urlMobile -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($cuerpo)) -ContentType 'application/json' -UseBasicParsing -TimeoutSec 30
      $ok = $resp.StatusCode -eq 200 -and [bool](($resp.Content | ConvertFrom-Json).token)
      $http = $resp.StatusCode
    } catch { $ok = $false; $http = $_.Exception.Response.StatusCode.value__ }
  } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b); $cuerpo = $null; $s = $null; $resp = $null }
  if (!$ok) { Fin "El ingreso en mobile.dttacgroup.cl fallo (HTTP $http). La cuenta existe en D1; revise la contrasena escrita." 1 }
  Fin "LISTO: $($v.r.usuario) ($($v.r.nombre), RUT $($v.r.chofer_id)) puede ingresar en mobile.dttacgroup.cl. Sin vehiculos asignados." 0
} catch {
  Fin "ERROR: $($_.Exception.Message)" 1
}
