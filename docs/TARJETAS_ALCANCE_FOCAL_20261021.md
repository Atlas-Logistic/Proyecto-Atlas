# Tarjetas de obra y vehiculo: alcance focal (21/10/2026)

## Causa y cambio
reconciliar_bandeja_decisiones completaba tarjetas faltantes de obra y vehiculo
antes de aplicar guias_objetivo. Los agregados ajenos se confundian con tarjetas
preexistentes y se publicaban como conservados.

Se limita la lectura de ambos detectores con alcance_guias, reutilizando el
alcance causal de d2bcbe3. Se intersecta con cualquier alcance heredado y se aplica
el mismo contexto a generar_artefacto, que conserva las tarjetas ajenas exactas.
No cambia el calculo de dependencias, los detectores, el extractor, las reglas de
resolucion ni la politica de errores. Un conjunto vacio nunca significa global.

## Evidencia sintetica
tests/test_bandeja_alcance_focal_p0.py reproduce DOCUMENTO_CORREGIR_CAMPO sobre
482673 (despachar_a_crudo). Antes del arreglo se publicaban las cuatro tarjetas
latentes de 475510, 482631, 482487 y 482597; despues no se publican. Si ya existen,
se conservan completas e iguales. Las cuatro filas ajenas y los catalogos
sinteticos permanecen identicos, y el motivo FECHA_SIN_CORROBORAR de 482673 no
se oculta ni se resuelve artificialmente.

Ocho casos cubren tambien generacion de obra y vehiculo dentro del alcance,
alcance vacio, interseccion heredada con/sin argumento explicito y propagacion
de errores reales de ambos detectores sin republicar la bandeja.
La suite focal incluye decisiones causales, acciones operacionales, redes de
seguridad, cache historica y evidencia de obra/vehiculo. No se ejecutan guias
reales ni reconciliacion global sobre produccion.

## Instalacion CASA
Desktop instalado invoca en cada operacion un proceso corto de
C:\Atlas\Proyecto-Atlas\.venv\Scripts\python.exe, con el CLI del mismo Motor.
Integracion prevista por fast-forward desde el worktree aislado, con respaldo
local previo y el mutex existente EscritorEquipoUnico, comprobando que no hay
procesos Python operacionales y conservando configuracion/binario Desktop.
No exige reinstalacion ni reinicio. Se valida de nuevo el Motor operativo con
fixtures locales, sin token Cloud ni escrituras productivas.
Evidencia local: C:\Atlas\pruebas\tarjetas-focal-casa-20261021.
