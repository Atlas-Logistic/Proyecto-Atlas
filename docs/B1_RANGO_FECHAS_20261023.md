# B1: rango inclusivo de fechas

Base operativa: c7a7fec, limpia; desarrollo en worktree aislado.

La pregunta `cuantos viajes tiene villagra del 02/10 al 08/10` daba 58 viajes: el primer fallo estaba en `_filtros_periodo`, que solo reconocia ENTRE/DESDE con ambos anios completos. El filtro de chofer se conservaba, pero no existia filtro temporal al ejecutar. El ejecutor ya usa la misma lista de coincidencias para COUNT_VIAJES y viajes_soporte; no fue modificado ni se cuentan guias.

Cambio: ampliar el parser existente para DEL/AL y anio opcional; heredar el anio explicito o usar date.today().year, igual reloj que resolver_periodo. Validar fechas y orden antes del proveedor o la ejecucion; no degradar una fecha invalida a historico. Reutilizar el parser en ingesta para mantener su espacio de nombres y mostrar periodo inclusivo en la respuesta.

Aceptacion sintetica: 13 pruebas nuevas (incluyen reloj 2031, con/sin anio, anio solo en extremo final, sintaxis previa, ambos limites, guias multiples por viaje, invalido/invertido/incompleto, fecha puntual, RUT, sin periodo e ingesta). 181 pruebas pertinentes aprobadas. Suite ampliada previa: 201 aprobadas y 6 fallos temporales preexistentes; mismos seis en c7a7fec (190 aprobadas), fixtures fijas de septiembre contra reloj de octubre. Regresion roja en base: falta fecha_desde; evidencia privada fuera de Git.

Verificacion lectora del reporte vigente reporte_mobile_20261022_200310_998146: 6 viajes de PATRICIO VILLAGRA MUNOZ, periodo 2026-10-02 a 2026-10-08 inclusive. Total = total_coincidencias = len(viajes_soporte) = 6; cada fecha del soporte dentro del rango. SHA256 de fuente/dataset/agrupaciones/estado/catalogos identicos antes y despues. Evidencia local C:/Atlas/pruebas/b1-rango-20261023, sin datos privados publicados.

Instalacion: fast-forward exclusivo sobre la base verificada, con respaldo Git y copia de los dos modulos. Desktop llama Motor externo por consulta y no requiere cierre. No se alteran PULL, OCR, Cloud, guias, catalogos, fechas documentales ni agrupaciones.
