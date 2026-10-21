# Demora del lote Desktop en JAVO (21/10/2026)

Lote: `20261021_104632_bac79e44`. Diagn?stico inicial de solo lectura:
PID real 21316 (wrapper 18440), entrada ?nica, cinco im?genes y manifiesto.
Las cinco filas ya estaban persistidas OK; la publicaci?n segu?a pendiente.
No se reinici? ni reingres? el lote ni se repiti? OCR.

Causa comprobada: `reconciliar_estado_derivado` ->
`reconciliar_bandeja_decisiones` -> `_leer_relaciones_historicas_reportadas`
-> `_leer_reporte_historico` -> `Path.open`, esperando Drive.
Varias muestras de py-spy corroboraron la misma etapa. Los locales mostraron
`cache_valido=False`, `carpetas_cache={}` y reconstrucci?n del hist?rico
(incluido un reporte `mantenimiento_tecnico_20261001_200038_046395`).
El filtro focal de decisiones no imped?a consultar TODOS los reportes cuando
una decisi?n VEHICULO_DESCONOCIDO pertenec?a al propio lote. No era una cola
sin iniciar ni un lock hu?rfano: el escritor vivo reten?a los locks mientras
esperaba I/O. OCR ya hab?a terminado; el proveedor se comparte por lote.
No hay medici?n retrospectiva que permita atribuirle tiempo a inicializaci?n
OCR por separado, ni cronometrar individualmente cada gu?a.

Cambio: el enriquecimiento con reportes hist?ricos se reserva a reconciliaci?n
global. La focal sigue usando dataset/ledger/cat?logos vigentes y sus mismos
umbrales: sin evidencia suficiente conserva revisi?n humana. No se modifica
el lector hist?rico ni su cach? ni las reglas de resoluci?n global.

Recuperaci?n: tras verificar las cinco filas ?nicas OK y el stack de espera,
se detuvo exclusivamente PID 21316 a las 10:55:07 (hora Chile).
El wrapper termin?. Bajo el mismo mutex Global del Motor y comprobaci?n PULL
se recuperaron los dos locks hu?rfanos del PID muerto. Se public? ?nicamente
el reporte desde el CSV existente, sin ejecutar ingesta ni reconciliaci?n.
El manifiesto vigente apunta a `reportes/reporte_desktop_20261021_104632_bac79e44`.
CSV: 560 filas (555 previas + 5). Cada gu?a fue verificada en el reporte
(viajes o documentos sin transporte). Sin procesos de ingesta/PULL activos
ni locks restantes al cierre. Desktop no se modific?.

| Gu?a | Filas | Procesamiento | Estado documental | Transporte |
|---|---:|---|---|---|
| 482580 | 1 | OK, sin error | REQUIERE_REVISION | No encontrado |
| 482631 | 1 | OK, sin error | REQUIERE_REVISION | No encontrado |
| 482634 | 1 | OK, sin error | REQUIERE_REVISION | No encontrado |
| 482661 | 1 | OK, sin error | REQUIERE_REVISION | 0000363214 |
| 482722 | 1 | OK, sin error | REQUIERE_REVISION | No encontrado |

Tiempos observados (Chile, UTC-3):

- Copia/entrada: 10:46:32; manifiesto: 10:46:33.383.
- Fin de procesamiento/B1 registrado: 10:51:05.751; latencia B1: 0 s.
  Entrada a ese hito: aproximadamente 273 s (incluye OCR y procesamiento;
  no equivale a tiempo exclusivo de OCR).
- Inicio de reconciliaci?n: 10:51:09.585, seg?n sello de respaldo en stack.
- Muestra de espera hist?rica conservada: 10:52:57; segu?a esperando al
  detenerlo a las 10:55:07: al menos 130 s de espera observada, dentro de
  unos 238 s transcurridos en reconciliaci?n hasta la detenci?n.
- Publicaci?n vigente: 10:56:56.418; total desde entrada: unos 624 s
  (10 min 24 s), incluida investigaci?n y recuperaci?n manual.
- Prueba sint?tica focal, sin abrir hist?rico: 0.06 s sin evidencia suficiente;
  0.14 s con confirmaci?n local suficiente. No es un benchmark del lote real.

Validaci?n: 86 tests focales/regresi?n aprobados en 25.22 s (OCR provider,
reutilizaci?n OCR, ingesta focal, canal Desktop, cach? hist?rica y lectura
robusta). Tras agregar la variante de evidencia local: 34 tests de ingesta/
canal/cach? aprobados en 3.12 s. Las dos nuevas variantes prueban que jam?s
se abre hist?rico en focal, conservando abstenci?n o resoluci?n seg?n evidencia
local. Las pruebas globales existentes siguen pasando.

Integridad de recuperaci?n: SHA-256 de los 17 archivos protegidos
(dataset, cat?logos JSON y decisiones) id?nticos antes/despu?s de publicar.
Esta comprobaci?n cubre nuestra recuperaci?n; no afirma que la ejecuci?n
original anterior a la intervenci?n no actualizara su bandeja normalmente.
No se editaron cat?logos, decisiones ni PULL. Evidencia local (fuera de Git):
`C:/Atlas/diagnostico-lote-20261021/` (stacks, hashes, resultado y publicaci?n).
No se versionan originales, datos operacionales ni configuraci?n del equipo.
