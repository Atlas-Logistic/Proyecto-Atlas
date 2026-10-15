# Lanzador de la tarea PULL: conserva el contrato operativo y evita que el
# host visible de PowerShell sea la acción directa del Programador de tareas.
$ErrorActionPreference = 'Stop'

$env:ATLAS_OCR_PROVIDER = 'rapidocr'
$env:ATLAS_RAPIDOCR_PYTHON = 'C:\Users\corte\AppData\Local\Atlas\runtime\rapidocr\Scripts\python.exe'
$env:PYTHONUNBUFFERED = '1'

$python = 'C:\Users\corte\AppData\Local\Programs\Python\Python312\python.exe'
$pull = Join-Path (Split-Path $PSScriptRoot -Parent) 'sincronizar_mobile_cloud.py'
$log = 'C:\Users\corte\AppData\Local\Atlas\logs\mobile_pull_cloud.log'

& $python $pull '--raiz-atlas' 'G:\Mi unidad\Atlas' *> $log
exit $LASTEXITCODE
