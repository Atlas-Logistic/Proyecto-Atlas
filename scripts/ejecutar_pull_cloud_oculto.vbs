' Host sin consola para el PULL programado. WScript no crea ventana ni toma foco.
Option Explicit

Dim shell, carpeta, comilla, comando
Set shell = CreateObject("WScript.Shell")
carpeta = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
comilla = Chr(34)
comando = comilla & "C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe" & comilla _
    & " -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File " _
    & comilla & carpeta & "\ejecutar_pull_cloud_oculto.ps1" & comilla
' Espera el cierre del PULL: mantiene la protección MultipleInstances de la tarea.
shell.Run comando, 0, True
