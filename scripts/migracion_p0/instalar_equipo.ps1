# Instalador P0 de UN equipo (CASA u OFICINA), mismo commit en ambos.
# Sin -Aplicar es simulacion. Envuelve preflight.ps1 y migrar_equipo.ps1:
#   1. identifica el equipo (host, MachineGuid, escritor_id; -EscritorEsperado lo exige)
#   2. respalda y guarda en stash los cambios locales sin commit del Motor
#   3. cierra Atlas Viajes (solo el instalado en -DesktopDir)
#   4. preflight hasta que no haya un ciclo del Motor en curso (max. 15 min)
#   5. migrar_equipo.ps1 (respaldos, PULL pausado, Motor, raiz de trabajo, accesos)
#   6. verifica el siguiente ciclo PULL y la custodia (0 distintos, sin diarios)
# No activa el protocolo 3 ni publica versiones (pasos coordinados aparte).
param(
    [Parameter(Mandatory)][ValidateSet('CASA', 'OFICINA')][string]$Equipo,
    [Parameter(Mandatory)][string]$Commit,
    [Parameter(Mandatory)][string]$Rama,
    [string]$EscritorEsperado = '',
    [string]$RaizTrabajo = 'C:\AtlasTrabajo\Atlas',
    [string]$LocalAppData = $env:LOCALAPPDATA,
    [string]$DesktopDir = (Join-Path $env:LOCALAPPDATA 'Programs\Atlas Viajes'),
    [string]$AccesoDirecto = '',      # vacio: los .lnk de escritorio y menu Inicio que abren el exe instalado
    [string]$Python = '',
    [switch]$SinTareas,
    [switch]$SinEsperarPull,
    [switch]$Aplicar
)
. (Join-Path $PSScriptRoot 'comun.ps1')
Iniciar-Registro $LocalAppData 'migracion_p0_instalar'
$config = Leer-Json (Join-Path $LocalAppData 'Atlas\desktop_operacion.json')
if (-not $config) { throw 'Sin desktop_operacion.json: no es un equipo Atlas configurado.' }
$Motor = (Resolve-Path -LiteralPath $config.proyecto).Path
$Raiz = $config.raiz
if (-not $Python) { $Python = if ($config.python) { $config.python } else { Join-Path $Motor '.venv\Scripts\python.exe' } }
$fecha = Get-Date -Format 'yyyyMMdd-HHmmss'

# 1. Identidad
$idRuta = Join-Path $LocalAppData 'Atlas\escritor_operativo_id.txt'
$escritor = if (Test-Path -LiteralPath $idRuta) { (Get-Content -LiteralPath $idRuta -Raw).Trim() } else { '' }
$guid = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Cryptography').MachineGuid
Anotar "Equipo ${Equipo}: host $env:COMPUTERNAME, MachineGuid $guid, escritor $escritor; Motor $Motor; raiz $Raiz"
if ($EscritorEsperado -and $escritor -ne $EscritorEsperado) { throw "Escritor $escritor no es el esperado ($EscritorEsperado): equipo equivocado." }

# Accesos directos productivos (no los de prueba)
if (-not $AccesoDirecto) {
    $exe = Join-Path $DesktopDir 'Atlas Viajes.exe'
    $sh = New-Object -ComObject WScript.Shell
    $lugares = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs')) | Where-Object { $_ -and (Test-Path $_) }
    $AccesoDirecto = (@($lugares | ForEach-Object { Get-ChildItem -LiteralPath $_ -Filter 'Atlas Viajes.lnk' -ErrorAction SilentlyContinue } |
        Where-Object { $sh.CreateShortcut($_.FullName).TargetPath -eq $exe } | ForEach-Object { $_.FullName }) -join ';')
}
Anotar "Accesos directos: $AccesoDirecto"

# 2. Cambios locales sin commit del Motor (p. ej. notas): respaldo + stash
$sucios = @((Git $Motor diff --name-only HEAD) -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($sucios.Count) {
    $dir = Join-Path $LocalAppData "Atlas\respaldo-p0-cambios-locales-$fecha"
    Ejecutar $Aplicar "respaldar y guardar en stash cambios locales del Motor: $($sucios -join ', ')" {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        foreach ($f in $sucios) { Copy-Item -LiteralPath (Join-Path $Motor $f) -Destination (Join-Path $dir (Split-Path -Leaf $f)) }
        # git directo: PowerShell consumiria el "--" al llamar a la funcion Git.
        $git = (Get-Command git -ErrorAction SilentlyContinue).Source
        if (-not $git) { $git = 'C:\Program Files\Git\cmd\git.exe' }
        $previa = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        try { & $git -C $Motor stash push -m "antes-p0-$($Equipo.ToLower())-$fecha" '--' @sucios 2>&1 | Out-Null }
        finally { $ErrorActionPreference = $previa }
        if ($LASTEXITCODE -ne 0) { throw 'git stash de los cambios locales fallo.' }
        Escribir-Json (Join-Path $LocalAppData 'Atlas\migracion_p0_cambios_locales.json') ([ordered]@{
            archivos = $sucios; copia = $dir; stash = "antes-p0-$($Equipo.ToLower())-$fecha"; motor = $Motor })
    }
}

# 3. Cerrar Atlas Viajes (solo el instalado)
$exeDesktop = Join-Path $DesktopDir 'Atlas Viajes.exe'
$abiertos = @(Get-Process -Name 'Atlas Viajes' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exeDesktop })
if ($abiertos.Count) {
    Ejecutar $Aplicar "cerrar Atlas Viajes ($($abiertos.Count) proceso(s))" {
        $abiertos | ForEach-Object { [void]$_.CloseMainWindow() }
        $limite = (Get-Date).AddSeconds(30)
        while ((Get-Process -Name 'Atlas Viajes' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exeDesktop }) -and (Get-Date) -lt $limite) { Start-Sleep -Seconds 1 }
        Get-Process -Name 'Atlas Viajes' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exeDesktop } | Stop-Process -Force
    }
}

# 4. Preflight (espera que termine un ciclo en curso)
$pf = @{ Motor = $Motor; Raiz = $Raiz; RaizTrabajo = $RaizTrabajo; LocalAppData = $LocalAppData
         DesktopRecursos = (Join-Path $DesktopDir 'resources'); Python = $Python }
$limite = (Get-Date).AddMinutes(15)
do {
    & (Join-Path $PSScriptRoot 'preflight.ps1') @pf
    $listo = $LASTEXITCODE -eq 0
    if ($listo -or -not $Aplicar) { break }
    if ((Get-Date) -gt $limite) { throw 'Preflight no quedo LISTO en 15 minutos; no se migra.' }
    Start-Sleep -Seconds 20
} while ($true)
if (-not $listo -and $Aplicar) { throw 'Preflight no LISTO.' }

# 5. Migracion
$inicio = Get-Date
$mig = @{ Motor = $Motor; Raiz = $Raiz; RaizTrabajo = $RaizTrabajo; Commit = $Commit; Rama = $Rama; Equipo = $Equipo
          LocalAppData = $LocalAppData; DesktopDir = $DesktopDir; AccesoDirecto = $AccesoDirecto; Python = $Python
          SinTareas = $SinTareas; Aplicar = $Aplicar }
& (Join-Path $PSScriptRoot 'migrar_equipo.ps1') @mig
if (-not $Aplicar) { Anotar 'Instalacion simulada.'; exit 0 }

# 6. Verificacion
if (-not $SinTareas -and -not $SinEsperarPull) {
    $log = Join-Path $LocalAppData 'Atlas\logs\mobile_pull_cloud.log'
    $limite = (Get-Date).AddMinutes(8)
    do { Start-Sleep -Seconds 15 } while (((-not (Test-Path $log)) -or (Get-Item $log).LastWriteTime -lt $inicio -or (Procesos-Motor).Count) -and (Get-Date) -lt $limite)
    $texto = if (Test-Path $log) { Get-Content -LiteralPath $log -Raw } else { '' }
    Anotar "Primer ciclo PULL tras migrar: $(if ($texto -match '"escritor_operativo"\s*:\s*"NO_ADQUIRIDO"') {'NO_ADQUIRIDO'} elseif ($texto -match '"recuperacion_turnos"') {'OK (Motor P0)'} else {'revisar ' + $log})"
}
Push-Location -LiteralPath $Motor
try {
    Anotar "Custodia: $((& $Python -B -m atlas_core.estado_confirmado --verificar --raiz-atlas $Raiz 2>$null | Out-String).Trim())"
    Anotar "Diarios: $((& $Python -B -m atlas_core.estado_confirmado --diarios --raiz-atlas $Raiz 2>$null | Out-String).Trim())"
} finally { Pop-Location }
if ($sucios.Count) { Anotar "Cambios locales en stash 'antes-p0-$($Equipo.ToLower())-$fecha' (copia en respaldo-p0-cambios-locales-$fecha): reaplicar a mano si corresponde." }
Anotar "Instalacion P0 de $Equipo terminada."
