# Transcripción técnica — Calidad de Datos Operacionales, Fase 1

Se auditó OCR → extracción → Resolver/catálogo → Política → procesamiento → CSV/reporte → Desktop para Clientes, Destinos, Patentes, Peso/Cantidad, Materiales y Kilómetros.

Defectos corregidos: el RUT ausente no activaba la relectura focal aun con etiqueta documental; el Resolver rechazaba un prefijo OCR único aunque el RUT exacto apuntara a la misma entidad; peso se extraía pero era eliminado antes del CSV. La guía real 464089 confirma las tres correcciones.

No se corrigieron sin evidencia suficiente: Destinos con discrepancias documentales, cantidad independiente, materiales sin alias aprobados y origen de rutas. La pérdida tipada de patentes en 464106 quedó demostrada y delimitada para el siguiente bloque.
