# Cierre del progreso del ingreso manual (21/10/2026)

Progreso funcional en el ejecutable instalado de Atlas Viajes, usando el
Motor de `C:/Atlas/Proyecto-Atlas` y un perfil de prueba local separado.
No se procesaron las gu?as reales 482580, 482631, 482634, 482661 ni 482722;
no se escribi? producci?n, no se modific? Desktop ni revalidacion_documental.py.

## Cambio Motor

`9abba19` ya era ancestro de HEAD al comenzar. No hizo falta integrarlo.
`_cli()` redirig?a todo stdout a StringIO; el analizador imprime ah? los
inicios de documento, por lo que Desktop no recib?a progreso hasta terminar.
Ahora `_SalidaCLI` reconoce l?neas completas `[i/N] archivo`, incluso si
llegan en escrituras fragmentadas, las env?a inmediatamente a stderr y hace
flush. No incluye esos eventos en la respuesta interna. El resto de la salida
sigue capturado para los comandos que devuelven JSON o res?menes; el canal
exterior desktop_operacion_cli.py conserva exclusivamente el JSON final en stdout.
La restauraci?n de argv/stdin tambi?n se ejecuta si el comando falla.

## Validaci?n en instalaci?n

Ejecutable: `C:/Users/corte/AppData/Local/Programs/Atlas Viajes/Atlas Viajes.exe`.
Se cotejaron main.js, preload.js, operacion_desktop.js, ingreso_guias_estado.js
y atlas_viajes.html extra?dos de app.asar con las fuentes de Desktop 0f93ab0:
los cinco coinciden byte por byte. No se reconstruy? ni reemplaz? app.asar.
La configuraci?n habitual (config_usuario.json y pol?tica operacional local)
apunta a `C:/Atlas/Proyecto-Atlas`, el mismo Motor modificado y probado.

Perfil de ensayo: `C:/Atlas/pruebas/progreso-manual-20261021`, marcado
SOLO_DATOS_SINTETICOS; userData, configuraci?n operacional, cat?logos y entradas
propios. Se usaron las protecciones ATLAS_PRUEBA_ROOT/ATLAS_E2E_ROOT y se
deshabilitaron actualizador/B1. No se cambiaron las preferencias habituales.
El selector nativo del bot?n Ingresar gu?as se abri?. La prueba del lote se
inici? mediante un evento drop sint?tico sobre zona-soltar-caja, ejecutando
el manejador real de la interfaz, preload, IPC, operacion_desktop y el proceso
Python real. No se simularon eventos de progreso ni resultados del Motor.
Un observador del renderer registr? IPC y cambios DOM; computer-use verific?
visualmente la aplicaci?n instalada y la lista final.

| Hito (hora Chile) | Tiempo desde inicio | Interfaz |
|---|---:|---|
| 11:12:32.714 | 0 s | 991101.pdf y 991102.pdf: Esperando |
| 11:12:33.342 | 0.628 s | 991101.pdf: Procesando; 991102.pdf: Esperando |
| 11:12:37.624 | 4.910 s | 991102.pdf: Procesando; primera lectura terminada |
| 11:12:38.505 | 5.791 s | Ambas: Completado, con resultado sin transporte |

Los eventos reales fueron `[1/2] 991101.pdf::pagina=0001` y
`[2/2] 991102.pdf::pagina=0001`; el renderer los asoci? a sus PDFs.
El resultado final se mostr? como Guardado y se carg? el reporte autom?ticamente.
La medici?n local contiene registros de varios observadores de diagn?stico:
las notificaciones repetidas en ese archivo corresponden a esos listeners;
la verificaci?n de duplicados se hizo sobre dataset/manifiestos, no contando
registros del observador. Solo hay dos filas, ambas OK, una por gu?a.

Reintento sint?tico por el canal desktop_operacion_cli.py: cantidad nueva 0,
existentes 2, ning?n evento OCR, SHA-256 del CSV y lista de lotes id?nticos.
No se volvi? a procesar ninguno de esos documentos sint?ticos.

## Pruebas focales y rendimiento

37 tests Motor aprobados en 3.45 s:

- test_desktop_progreso_cli.py: fragmentaci?n, flush inmediato dentro del
  comando, stdout separado, restauraci?n al fallar, progreso por pipe antes
  del JSON incluso sin Python -u (handshake, sin esperas artificiales).
- test_desktop_operacion.py: permisos, exclusividad, canal y deduplicaci?n.
- test_cache_relaciones_historicas_p0.py y lectura_robusta: el caso focal con
  VEHICULO_DESCONOCIDO propio proh?be llamar al lector hist?rico, con y sin
  evidencia local suficiente; la reconciliaci?n global conserva sus pruebas.
- test_ingesta_focal_p0.py: alcance causal y ausencia de recorrido del backlog.

8 tests Desktop de operacion_desktop e ingreso_guias_estado aprobados, sin
editar sus archivos. `git diff 9abba19 -- atlas_core/revalidacion_documental.py`
es vac?o. El nuevo adaptador solo inspecciona l?neas de salida; no a?ade
consultas, OCR, locks, reconciliaciones ni recorridos de Drive.

Evidencia local, fuera de Git: `C:/Atlas/pruebas/progreso-manual-20261021/evidencia/`:
transiciones-ingreso.json, completado-instalado.png, instalacion.json,
antes-deduplicacion.json y deduplicacion.json. Sin dependencia de Desktop
pendiente para el progreso validado. La prueba no implica una nueva ingesta real.
