# Bandeja tras corregir el transporte: cada tarjeta depende de su condición (23/10/2026)

## Causa
`CapaAccionesOperacionales._aplicar_confirmado` reconciliaba la bandeja (`_reconciliar`, focal por guía) y
DESPUÉS aplicaba la red de seguridad `_retirar_obsoletas_por_campo`. Al corregir `numero_transporte`, esa
red quita toda tarjeta del archivo que aún identifica el documento por el transporte anterior, sin mirar su
condición. Como la reconciliación ya había corrido, nadie la republicaba: 482580 perdía CLIENTE_AUSENTE con el
cliente aún ausente; en 482661 VEHICULO_DESCONOCIDO (J56468) sólo reaparecía con la acción siguiente.

## Cambio
La red de seguridad corre ANTES de la reconciliación (la canónica republica, con el transporte nuevo, toda
tarjeta cuya condición siga vigente) y otra vez después, para que ninguna tarjeta republicada pregunte por el
valor anterior. Sin cambios en detectores, OCR, Mobile, Cloud ni catálogos.

## Verificación
- `tests/test_bandeja_condicion_real_transporte.py` (482580, 482661): transporte corregido conserva sus
  tarjetas una sola vez; se cierran sólo al resolver su condición; un campo ajeno no las recrea ni altera.
  Base: 3 de 6 fallan; corregido: 6 de 6.
- Laboratorio sobre copia productiva: corregir el transporte de 482580 republica CLIENTE_AUSENTE con
  0000365023; sólo cambia esa fila; catálogos, agrupaciones y eventos idénticos.
