# Arnés sintético M1

Estas pruebas usan únicamente datos ficticios y dobles locales. El oráculo de `integridad.py` detecta generaciones, documentos, reportes y decisiones inconsistentes y enumera envíos Cloud posteriores sin modificarlos. El proceso hijo llama `CustodiaEstado._confirmar_rutas` real con Cloud falsa persistente y termina abruptamente después de cada lote; evidencia que una marca intermedia puede mezclar G0/G1. El bloqueo lo implementa el oráculo del arnés, no el Motor productivo.

Ejecutar exclusivamente en un entorno de pruebas aislado, sin credenciales ni acceso a Drive/Cloud; no ejecutar sobre datos reales:

```powershell
python -m pytest -q pruebas_m1/test_integridad_m1.py -p no:cacheprovider
```

Las pruebas filtran el entorno del hijo y bloquean conexiones Python en el proceso de pruebas. Esto no es aislamiento de sistema operativo: no garantiza bloqueo de red de bibliotecas nativas ni de otros procesos. Para el simulacro integral se requiere VM sin red ni carpetas compartidas, controles de rutas y permisos del plan M1. No se invoca PULL, OCR ni Worker real. No se han implementado ni validado restauración completa, reinicio tras el corte, lectores Desktop/B1, lease real o recuperación física de envíos: quedan pendientes y no deben interpretarse como aprobados. No habilitar escritura basándose en este oráculo.
