# Análisis profundo de casos REVISAR — Fase 1

Fecha: 2026-08-03
Alcance: diagnóstico de solo lectura sobre ATLAS-E2E-002, 005, 007 y 010.

## Resultado ejecutivo

Los cuatro documentos originales son legibles y conservan las regiones
necesarias. Ningún `REVISAR` es provocado por el Orquestador, Destinos,
Materiales o la Política de Activación. La marca nace exclusivamente de la
integración conservadora de Cliente/Chofer y del uso de recuperación
geométrica.

## ATLAS-E2E-002 — CHOFER-002.jpeg

- OCR: 40 párrafos y 157 bloques. La lectura lineal no extrae Cliente; la
  región geométrica recupera `ACKA`, variante aprobada de `ACMA SA`.
- Ground Truth: ACMA SA; CONSTRUCTORA POCURO SPA; PATRICIO VILLAGRA;
  transporte 0000347050.
- Resultado: todos esos campos terminan correctos. Cliente confirma por
  `ALIAS_HUMANO_UNICO` (0,90), Chofer por RUT y nombre (1,00), Destino exacto
  (0,95). Política publica los estados vigentes.
- Bloqueo exacto: `recuperacion_geometrica=True` fuerza `REVISAR` aunque la
  evidencia recuperada sea posteriormente confirmada sin contradicciones.
- Causa raíz: **Regla demasiado conservadora**.
- Evidencia faltante: ninguna después de resolver; falta una distinción entre
  recuperación geométrica confirmada y recuperación incierta.
- Mejora mínima: adjudicar revisión después de los resolvers y permitir `OK`
  solo cuando toda recuperación quede confirmada inequívocamente.
- Impacto esperado: 1 documento menos en revisión.
- Riesgo técnico: medio; relajar el indicador sin condiciones estrictas podría
  ocultar recuperaciones erróneas.

## ATLAS-E2E-005 — CHOFER-005.jpeg

- OCR: 39 párrafos y 166 bloques. La región de cliente es correcta, pero el
  RUT visible `93.772.000-9` llega al resolver como `93.772.000`, sin DV.
- Ground Truth y resultado final coinciden en guía, transporte, Chofer,
  Cliente y Destino.
- Cliente queda `REQUIERE_REVISION/CONTRADICCION` porque el RUT truncado es
  inválido; Chofer y Destino confirman. Orquestador y Política no agregan
  revisión. Material se abstiene y no propaga revisión.
- Bloqueo exacto: pérdida OCR/extracción del sufijo `-9` del RUT de Cliente.
- Causa raíz: **OCR insuficiente**.
- Evidencia faltante: lectura confiable del DV, aunque está visible en imagen y
  el catálogo contiene el RUT canónico 93772000-9.
- Mejora mínima: relectura focal conservadora del RUT de Cliente con validación
  módulo 11 y abstención si no existe consenso.
- Impacto esperado: 1 documento menos en revisión.
- Riesgo técnico: bajo si solo se acepta un RUT completo y módulo 11 válido.

## ATLAS-E2E-007 — CHOFER-007.jpeg

- OCR: 36 párrafos y 168 bloques. El RUT visible `91.410.000-3` llega al
  resolver como `91.410.000`, sin DV.
- Ground Truth y salida final coinciden en todos los campos evaluables.
  Material confirma GT-MAT-009 por alias (1,00); Chofer y Destino confirman.
- Cliente queda `REQUIERE_REVISION/CONTRADICCION` exclusivamente por el RUT
  truncado. El nombre y el contexto son compatibles, pero la política
  conservadora no ignora una observación de RUT inválida.
- Bloqueo exacto: pérdida OCR/extracción del sufijo `-3` del RUT de Cliente.
- Causa raíz: **OCR insuficiente**.
- Evidencia faltante: lectura completa y validada del DV visible.
- Mejora mínima: la misma relectura focal conservadora del RUT de Cliente.
- Impacto esperado: 1 documento menos en revisión.
- Riesgo técnico: bajo con consenso y módulo 11; alto si se intenta completar
  el DV por inferencia sin evidencia OCR.

## ATLAS-E2E-010 — CHOFER-010.jpeg

- OCR: 26 párrafos y 169 bloques. Cliente se recupera como `EEKA` y confirma
  EBEKA por alias. La extracción lineal asigna la etiqueta `COMUNA` a Obra
  Destino, aunque la región geométrica observa `EAEKA`. No se extrae el RUT
  visible del chofer (`7.814.310-K`).
- Ground Truth: EBEKA como Cliente y Destino; LUIS REYES como Chofer. El
  transporte y material no son evaluables en el Ground Truth oficial.
- Resultado: Cliente EBEKA confirmado; Chofer `NO_RESUELTO`; Destino
  `NO_RESUELTO` y conserva `COMUNA`; Material propuesto. El catálogo de
  Choferes no contiene LUIS REYES. El catálogo de Destinos sí contiene EBEKA,
  pero `COMUNA` se excluye correctamente como alias genérico.
- Bloqueo exacto: concurren recuperación geométrica, RUT de Chofer ausente,
  Chofer fuera de catálogo y región lineal de Destino mal asociada.
- Causa raíz: **Otro — bloqueo compuesto** (`Región OCR incorrecta`, `OCR
  insuficiente` y `Catálogo insuficiente`).
- Evidencia faltante: RUT de Chofer confiable y entrada canónica de LUIS REYES;
  asociación robusta entre `OBRA DESTINO` y su valor.
- Mejora mínima: primero extracción focal estructurada de RUT de Chofer y Obra
  Destino; el caso no puede salir de revisión hasta validar documentalmente al
  Chofer e incorporarlo en una fase de catálogo autorizada.
- Impacto esperado: mejora de Cliente/Destino, pero cierre de revisión solo
  después de completar la identidad del Chofer.
- Riesgo técnico: medio-alto por la concurrencia de causas; convertir `COMUNA`
  en alias sería un falso positivo y queda expresamente descartado.

## Ranking de impacto

1. Relectura focal estructurada de RUT de Cliente: resuelve potencialmente 005
   y 007 con una condición verificable por módulo 11 (2/4 casos, riesgo bajo).
2. Adjudicación post-resolución de recuperaciones geométricas: puede resolver
   002 (1/4, riesgo medio).
3. Evidencia estructurada de Chofer y Destino más cierre documental de LUIS
   REYES: necesaria para 010 (1/4, riesgo medio-alto y dependencia de catálogo).

## Único bloque recomendado

**OCR focal estructurado de RUT de Cliente — Fase 1.** Debe releer únicamente
la celda de RUT asociada a `SEÑOR(ES)`, exigir consenso entre variantes y
módulo 11 válido, y abstenerse ante conflicto. Es el único bloque homogéneo
que puede reducir inmediatamente 2 de 4 revisiones sin relajar resolvers,
reglas de negocio ni política, y sin inventar datos. Los casos 002 y 010 deben
permanecer separados porque requieren, respectivamente, una decisión sobre la
regla de revisión y evidencia/catalogación adicional del Chofer.
