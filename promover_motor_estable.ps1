# Promueve un commit ya publicado al worktree estable que ejecuta la tarea
# \Atlas\MantenimientoPendientesTecnicos. El árbol de desarrollo nunca escribe
# en los datos por esa vía: sólo lo que pasa por aquí.
# Uso: .\promover_motor_estable.ps1 [-Commit <sha|ref>]   (default: HEAD de este árbol)
param(
    [string]$Commit = 'HEAD'
)
$ErrorActionPreference = 'Stop'
$git = 'C:\Program Files\Git\cmd\git.exe'
$desarrollo = $PSScriptRoot
$estable = Join-Path (Split-Path $desarrollo -Parent) 'Proyecto-Atlas-Estable'
$rutaTarea = '\Atlas\'
$nombreTarea = 'MantenimientoPendientesTecnicos'

& $git -C $desarrollo fetch --quiet origin
if ($LASTEXITCODE -ne 0) { throw 'git fetch falló' }
$sha = & $git -C $desarrollo rev-parse --verify "$Commit^{commit}"
if ($LASTEXITCODE -ne 0) { throw "Commit inválido: $Commit" }
$publicado = & $git -C $desarrollo branch -r --contains $sha
if (-not $publicado) { throw "El commit $sha no está publicado en origin; haz push antes de promover." }

if (Test-Path -LiteralPath $estable) {
    $sucio = & $git -C $estable status --porcelain --untracked-files=no
    if ($sucio) { throw "El worktree estable tiene cambios sin commit: $estable" }
}

# Sin escritores a medio actualizar: se pausa la tarea durante el checkout.
Disable-ScheduledTask -TaskPath $rutaTarea -TaskName $nombreTarea | Out-Null
try {
    while ((Get-ScheduledTask -TaskPath $rutaTarea -TaskName $nombreTarea).State -eq 'Running') {
        Start-Sleep -Seconds 5
    }
    if (Test-Path -LiteralPath $estable) {
        & $git -C $estable checkout --quiet --detach $sha
    } else {
        & $git -C $desarrollo worktree add --detach $estable $sha
    }
    if ($LASTEXITCODE -ne 0) { throw 'checkout del worktree estable falló' }
} finally {
    Enable-ScheduledTask -TaskPath $rutaTarea -TaskName $nombreTarea | Out-Null
}
$vigente = & $git -C $estable rev-parse --short HEAD
Write-Output "Motor estable en $estable -> $vigente"
