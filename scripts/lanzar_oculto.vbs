' Adaptaci?n de 6589e2a: ejecuci?n oculta, espera y c?digo del proceso hijo.
Option Explicit
Dim shell, args, comando, i, arg, resultado
Set shell = CreateObject("WScript.Shell")
Set args = WScript.Arguments
If args.Count = 0 Then WScript.Quit 64
comando = ""
For i = 0 To args.Count - 1
    arg = args(i)
    If InStr(arg, Chr(34)) > 0 Or Right(arg, 1) = "\" Then WScript.Quit 65
    If i > 0 Then comando = comando & " "
    comando = comando & Chr(34) & arg & Chr(34)
Next
resultado = shell.Run(comando, 0, True)
WScript.Quit resultado
