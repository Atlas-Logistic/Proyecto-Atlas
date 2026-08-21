# R4 — RUN real y holdout (2026-08-20)

Checkpoint inicial: rama `lector-mvp-guia-nueva`, HEAD
`695eacf46c5ffc9494f900d27d948c0b36005e3c`, árbol limpio y 0/0 con origin.
La operación real permaneció fuera del circuito de escritura. El entorno de
trabajo fue `C:\Users\Jjjc0508\Desktop\Atlas\R4_REPLAY_AISLADO_20260820`,
creado desde el baseline PRE-RUN de 43 documentos.

## Contrato R4

El dataset separa `estado_documental`, `estado_operacional`, `estado_ruta` y
la evidencia de corroboración. Cada documento conserva métricas JSON por fase.
Atlas IA B1 entra únicamente después de una revisión determinista, con al menos
tres señales coincidentes y candidatos provenientes de documentos reales. Su
resultado queda en `resultado_atlas_ia_json` como shadow: no cambia campos, no
escribe catálogos y no evita por sí solo intervención humana.

## Replay RUN #1

| Guía | Resultado R4 frente al RUN original |
|---|---|
| 460807 | MEJORÓ: material multilínea recuperado y ruta Angol bloqueada; obra sigue en revisión. |
| 464945 | MEJORÓ: histórico repetido corroboró el destino; documento OK. |
| 464959 | IGUAL_CORRECTO: conserva 5.431 kg y consolidación. |
| 464960 | IGUAL_CORRECTO: conserva 5.998 kg y consolidación; total 11.429 kg. |
| 464981 | MEJORÓ: J28529 se reconcilia inequívocamente a JB8529; obra sigue pendiente. |
| 464991 | MEJORÓ documentalmente: XF3629 conocida como camión rígido; NUEVO_ERROR de routing: Providencia fue contrastada literalmente con localidad Santiago. |
| 472002 | IGUAL_CORRECTO: no se degrada el resultado operacional previo. |
| 472008 | MEJORÓ: RUT corroborado y material B/8 normalizado; obra y carro leído JK2501 siguen sin coincidir con ground truth IX2501. |
| 472018 | IGUAL_CORRECTO: documento OK y routing separado en revisión. |
| 472037 | MEJORÓ: fecha 2026 y peso 9.231 recuperados; cliente/obra siguen pendientes. |

El RUN original tenía 3 documentos OK y 6 en revisión (un transporte de dos
documentos). R4 deja 6 documentos OK y 4 en revisión. Eliminó dos revisiones
completamente evitables y dos motivos de chofer evitables; mantiene cuatro
revisiones documentales legítimas. No hubo regresiones de extracción ni de
consolidación. Se registró una regresión de routing en 464991, sin corregir tras
el holdout para respetar su condición de muestra cerrada.

Tiempo: 112,17 s total, 11,22 s/documento, frente a ~254 s y ~25 s/documento
del RUN original. Las métricas individuales quedan en el CSV aislado; OCR fue
la fase dominante (2,04–6,89 s), resolución/corroboración 2,36–8,48 s,
geocodificación/routing 0,003–1,30 s y telemetría 0,07–7,11 s. B1 realizó cero
llamadas reales porque el entorno no tenía una consulta elegible con credencial;
la ruta operacional y su abstención están cubiertas por regresión sin red.

## Holdout cerrado

- 472044: extracción documental OK; 10.753 kg, BKYK63 y tres materiales. La
  ruta no se calculó por proveedor no disponible, sin degradar el documento.
- 472073: extracción documental OK; 12.388 kg, XF3629 y cuatro materiales. La
  ruta quedó en revisión por ubicaciones dispersas, separada del documento.

No se ajustó código ni umbrales después de observar estos resultados. Para R5:
modelar equivalencia comuna/localidad metropolitana (Providencia/Santiago),
resolver el desacuerdo de carro IX2501/JK2501 sólo con evidencia confirmada y
ampliar la instrumentación de persistencia, consolidación y reporte.
