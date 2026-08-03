# Transcripción de cierre — Análisis de casos REVISAR, Fase 1

Fecha: 2026-08-03

Se ejecutó un diagnóstico de solo lectura sobre las cuatro guías `REVISAR`.
No se modificaron OCR, Orquestador, Política, resolvers, catálogos,
infraestructura, Desktop ni reglas de negocio.

- 002: recuperación geométrica confirmada, pero la regla fuerza revisión.
- 005: RUT Cliente `93.772.000-9` llega truncado como `93.772.000`.
- 007: RUT Cliente `91.410.000-3` llega truncado como `91.410.000`.
- 010: Destino toma `COMUNA`, falta RUT canónico de Chofer y LUIS REYES no
  existe en el catálogo operativo.

Recomendación única: OCR focal estructurado de RUT de Cliente, con consenso,
módulo 11 y abstención conservadora.
