# Soporte cronologico de viajes B1

Base operativa confirmada:13c1af6, limpia. Worktree aislado y reserva en coordinacion.

Generalidad: el parser temporal instalado es compartido por cualquier chofer y no requiere cambio. Se prueba con ANA TORRES y PEDRO SOTO, resolucion por apellido, fechas con y sin anio y reloj sintetico2031. No se agregan condiciones por nombre.

El conteo de viajes conservaba el orden de origen. Se extrae el ordenamiento de LISTAR_VIAJES en una funcion compartida del mismo modulo, que reutiliza _parsear_fecha_dataset (DD-MM-AAAA convertido a date). Se reutiliza para soporte de COUNT_VIAJES y LISTAR_VIAJES: ascendente, desempate transporte y viaje_id, sort estable para igualdad completa. Fechas ausentes o invalidas al final en ambas direcciones del listado. El resultado del listado conserva su direccion solicitada y el soporte es ascendente. La proyeccion semantica identifica Sin fecha / Fecha no interpretable y conserva el texto original de la fecha invalida; no se modifica la fila fuente.

El conteo se calcula antes de ordenar; mismos filtros, total y objetos de viaje. Sin cambios de agrupaciones ni Desktop: la tabla presenta el soporte de Motor, sin ordenar por segunda vez.

Pruebas:190 aprobadas (9 nuevas mas181 previas), datos sinteticos. Dos choferes, cruce diciembre/enero y anio, ambos limites, mismo dia/transporte con IDs distintos, entrada invertida, fechas invalidas/ausentes, pertenencia por identidad de objetos, ausencia de mutaciones, igualdad total/soporte y contrato CLI/proyeccion. Regresion en base demuestra enero2031 antes de diciembre2030.

Verificacion lectora con reporte vigente: consulta Villagra02-08octubre2026 conserva6 viajes y mismos transportes; soporte02,05,05,06,07,08octubre, desempate05octubre por transporte0000362271 antes0000362384. Evidencia privada fuera de Git en C:/Atlas/pruebas/b1-orden-20261023. Publicacion/instalacion con respaldo y sin interrumpir procesos activos autorizadas. No se modifican datos, agrupaciones, OCR, PULL, Cloud ni trabajo Code.
