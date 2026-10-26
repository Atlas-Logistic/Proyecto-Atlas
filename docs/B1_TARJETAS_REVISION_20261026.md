# B1 en las tarjetas de Revisión de Atlas (26/10/2026)

Cada tarjeta de Revisión de Atlas tiene un campo «Corregir con B1». No es otro asistente:
es el mismo B1 (mismas acciones, preview, fotografía, confirmación, permisos y auditoría).

## Contrato

- Desktop envía `@revision:<decision_id> <lo que escribió el operador>` por el IPC existente
  `atlas:b1-atender`, en una conversación propia por tarjeta (`revision-<decision_id>`).
  El marcador nunca se muestra.
- `b1_consulta_cli` deriva siempre ese texto al operador si Desktop está autorizado; en
  SOLO CONSULTA lo rechaza.
- El Motor lee la tarjeta **vigente** de la bandeja (nunca datos enviados por Desktop) y
  reescribe la instrucción a la frase canónica que B1 ya interpreta
  (`b1_operador.instruccion_en_revision`). La intención resultante se limita a la guía y al
  campo de la tarjeta (`ajustar_a_revision`); el documento exacto se fija cuando el archivo de
  la tarjeta existe en el dataset (si no, se resuelve por guía y la ambigüedad se rechaza).
  Una revisión de destino usa su propia decisión, sin adivinar entre varias.

## Correcciones disponibles desde la tarjeta (acciones ya existentes)

| Campo de la tarjeta | Ejemplos | Acción |
|---|---|---|
| `peso_kg` | «12.450 kg», «el peso correcto es 12.450 kg» | `DOCUMENTO_CORREGIR_CAMPO` |
| `patente_tracto`, `patente_rampla` | «JC4178», «la patente correcta es JC4178» | `DOCUMENTO_CORREGIR_CAMPO` |
| `cliente` | «el cliente es …» | `DOCUMENTO_CORREGIR_CAMPO` |
| `obra_destino` | «la obra es …» (obra existente) | `DOCUMENTO_ASIGNAR_OBRA` |
| `despachar_a_crudo` (DESTINO_NO_RESUELTO) | «el destino es Av. … 123, comuna de …» | `DECISION_APLICAR` / `REGISTRAR_DIRECCION` |

Sin soporte desde la tarjeta (la respuesta lo explica y remite a las opciones de la tarjeta):
chofer (`CHOFER_CANDIDATO`), planta de origen, `DESTINO_SIN_CONFIRMAR`, y documentos sin número
de guía. Lo que nombra otra guía u otro dato pide aclaración; nada se escribe sin «sí».

Tras aplicar, Desktop relee la bandeja: se cierran sólo las tarjetas que preguntaban por el
valor corregido; las demás siguen.

Pruebas: `tests/test_b1_revision_tarjetas.py`, `Atlas-Viajes-Desktop/test/b1_revision_tarjetas.test.js`.
