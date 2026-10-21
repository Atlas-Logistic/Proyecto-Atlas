# OCR manual CASA — corrección focal 21/10/2026

La selección manual de Desktop usa RapidOCR por defecto. Se conserva EasyOCR como selección reversible y como dependencia instalada, sin inferencia EasyOCR durante la validación aprobada. No se cambió el extractor compartido, la selección de PULL, OFICINA, catálogos ni revisiones productivas.

## Corrección

`RapidOCRManualProvider` implementa el mismo contrato de proveedor y solo se selecciona con ATLAS_OCR_MANUAL=1; desktop_operacion lo limita a la acción ingresar y restaura el entorno al finalizar. PULL sigue creando RapidOCRProvider original. La normalización exclusiva de etiquetas completas recupera GUIA DE DESPACHO, FECHA DE EMISION y las etiquetas temporales cuyos espacios desaparecían. No sustituye números ni utiliza el nombre del archivo.

En 482722 el año de emisión llegaba truncado como 21-10-202. El buscador geométrico general se abstenía por ambigüedad con el RUT cercano; el parser lineal acababa usando la fecha de salida leída como 2024. El adaptador manual localiza una sola fecha con sintaxis temporal a la derecha y en la misma fila de EMISIÓN, excluyendo RUT y fechas de salida/llegada. Si está incompleta o es inválida, solo relee ese recorte.

La operación nueva focal_linea usa la caja exacta sin márgenes, reconocimiento directo sin segunda detección y cuatro vistas: RGB y canales R/G/B. En esta foto, los márgenes contaminaban la línea con bordes/filas vecinas y la detección de un recorte pequeño no encontraba texto. Los canales G/B del mismo modelo RapidOCR recuperaron 21-10-2026 con confianza 0,905/0,909. Se exige fecha completa válida, al menos dos variantes distintas concordantes con confianza >=0,70 y ausencia de otro candidato válido de alta confianza. Sin consenso se informa error técnico; no se completa el año desde la fecha actual, otras guías o el archivo. Se conserva la evidencia original y se reutiliza el resultado entre texto y bloques. No se necesitó otro modelo ni EasyOCR focal.

Las tres trazas de orientación conservan 0 grados: no se resolvió inventando una rotación ni cambiando el tratamiento EXIF. El worker aplica la transposición EXIF ya existente. La operación focal original permanece igual para PULL.

El permiso de subprocess de Desktop admite exclusivamente el intérprete Python configurado y el worker rapidocr_worker.py, sin argumentos adicionales. Se verifica el escritor antes del arranque. Windows audita executable=None y una cadena generada con list2cmdline; se compara con la cadena exacta esperada, sin analizar ni ejecutar shell. El cierre por timeout tiene permiso temporal para taskkill de ese PID únicamente, incluso si se perdió el lease. Scripts operacionales, comandos arbitrarios, otros workers y otros PID siguen bloqueados.

## Aceptación sobre copias locales

Se reutilizaron las mismas tres imágenes y la copia de catálogos de la evaluación 985b1e5, bajo C:/Atlas/pruebas/ocr-manual-20261021. No se reingresó producción ni se alteraron estados/revisiones de esas guías. Las filas de laboratorio conservan las revisiones documentales que corresponden; no se aceptaron automáticamente campos distintos de los evaluados.

| Folio | Fecha de emisión | Transporte | Extracción (s) |
|---|---|---|---:|
| 482553 | 19-10-2026 | 0000365008 | 12,726 |
| 482661 | 20-10-2026 | 0000365214 | 11,793 |
| 482722 | 21-10-2026 | 0000365200 | 11,350 |

Total de extracción: 35,869 s frente a 258,17 s de EasyOCR, aproximadamente 7,2 veces más rápido en la muestra. Canal completo candidato, usando el ejecutable real, Python -I -B -u, progreso, copia, OCR y publicación en laboratorio: 77,789 s. Los CSV de salida verifican nueve campos críticos correctos y las tres trazas identifican atlas_core.ocr_manual.RapidOCRManualProvider. Son tiempos observados, no CPU exclusiva.

82 pruebas Motor y 9 Desktop aprobadas: etiquetas, ubicación de fecha frente a RUT/salida, consenso/abstención, calendario inválido, caché sin relectura completa, conservación del original, selector PULL intacto, protocolo focal, auditoría real Windows, argumentos arbitrarios, timeout/PID, pérdida de exclusividad, permisos operacionales y progreso.

## Selección y despliegue

Desktop: ocr_provider en desktop_operacion.json tiene precedencia sobre ATLAS_DESKTOP_OCR_PROVIDER; sin ambos usa rapidocr. Valores actuales: rapidocr/easyocr. El intérprete admite rapidocr_python, después ATLAS_RAPIDOCR_PYTHON, después LOCALAPPDATA/Atlas/runtime/rapidocr/Scripts/python.exe. La configuración de CASA no se editó. Las variables solo se entregan al hijo manual; no se modificó el entorno de usuario/máquina ni los lanzadores de PULL.

Se preservó el contrato de proveedores para futuras implementaciones/hardware; un nuevo worker requerirá autorización explícita de su comando, no un permiso de procesos abierto. Se conservan las dependencias EasyOCR y la reversión por configuración. Fallos RapidOCR no cambian silenciosamente el backend.

El app.asar de CASA cambia únicamente src/operacion_desktop.js, con inventario y flags unpacked preservados. SHA256 anterior: 9ae1904cdf38977a1348dd1788e920b039e2f330b77affad78a40a9071f7d04d; nuevo: c6736b98a5cf35d028e305a52e8cb2cd008231b9fb60635fb70080228199e4b5. Respaldo/manifiesto en correccion-despliegue dentro del laboratorio. Se comprobó ausencia de ingresos Python descendientes del Desktop antes de reiniciarlo; el proceso de decisiones de Claude, independiente de Desktop, no se interrumpió.
Validacion posterior a instalar: ejecutable instalado + modulo de app.asar real + canal manual completo sobre tres copias locales: 72,223 s, cantidad=3, tres filas OK, nueve campos criticos correctos y tres trazas RapidOCRManualProvider. Evidencia canal-corregido-instalado/aceptacion.json. Instalacion CASA actualizada y aceptada.
