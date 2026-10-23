# Asignación vigente única chofer-camión (23/10/2026)

## Causa raíz
La homologación automática de una patente exige que el vehículo esté confirmado PARA el chofer
(`CONFIRMACION_HUMANA` con `rut_chofer_asociado`). Esa búsqueda (`_vehiculos_confirmados_para_rut`) contaba
cualquier asociación pasada, sin distinguir la vigente de la histórica (un chofer reasignado seguía
"confirmado" para su camión anterior y un camión reasignado quedaba con dos choferes), y la tolerancia sólo
comparaba posiciones de igual largo: una omisión o adición de un carácter nunca se homologaba. Sólo 6 de 31
choferes tienen asignación confirmada; el historial de viajes nunca cuenta como asignación.

## Regla
- Fuente única: evidencias `CONFIRMACION_HUMANA` con `rut_chofer_asociado` del catálogo de vehículos
  (append-only; `CHOFER_ASIGNAR_VEHICULO`/`confirmar_vehiculo`). `_asignaciones_vigentes`: cada camión tiene un
  único chofer vigente, el de su asignación explícita más reciente; las anteriores son historial.
- Un cambio sólo ocurre por una asignación explícita nueva, nunca por OCR ni viajes.
- Con chofer identificado y camión vigente confirmado, una lectura a <= 2 ediciones (sustitución, omisión,
  adición, transposición; `_distancia_edicion_patente`) se homologa sola. El tipo sale del campo leído
  (tracto/carro) cuando la tarjeta no lo trae: la patente de uno nunca corrige la del otro.
- Revisión humana si: no hay asignación vigente confirmada; el chofer tiene dos camiones vigentes del mismo
  tipo; otro vehículo confirmado del mismo tipo queda igual de cerca (`OTRO_VEHICULO_CONFIRMADO_IGUAL_DE_CERCANO`);
  la patente es desconocida o lejana. Una decisión humana anterior sobre otra patente no compite con la
  asignación vigente (`NO_ES_LA_ASIGNACION_VIGENTE`).
- Misma decisión en ingreso, reconciliación y tarjetas (`evaluar_evidencia_patente`); también la usa
  `resolver_patente_operacional_canonica_por_chofer`. La patente leída se conserva; la homologada va al ledger.

## Verificación
`tests/test_asignacion_vigente_chofer_camion.py` (10). Suites focales de vehículos: 554 aprobadas, 4 fallos
preexistentes de destino/obra. Copia productiva: reconciliación global idéntica a la actual (sin
autoaplicaciones nuevas ni tarjetas distintas).
