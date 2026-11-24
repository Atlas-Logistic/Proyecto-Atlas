# Ficha documental selectiva

La operacion `inicializar_fichas_choferes.py --raiz-atlas RAIZ --actor ACTOR --referencia REFERENCIA` prepara exclusivamente la ficha de un chofer activo del catalogo con RUT valido y unico. Usa el almacen oficial de la empresa, el turno de escritura y el respaldo existente. No crea documentos, asignaciones ni cuentas. La repeticion conserva el mismo UUID y no vuelve a escribir.

Se rechazan almacenes incompatibles, identidades ambiguas, fichas huerfanas y documentos legados del mismo RUT que necesitan revision. No se infiere continuidad de identidad por nombre. La inicializacion masiva anterior permanece sin cambios.

El alta de un chofer nuevo prepara la ficha dentro del mismo turno oficial y sin asignacion de vehiculo. Si falla despues de crear el chofer y la credencial, informa `FICHA_DOCUMENTAL_PENDIENTE`; debe repararse con la operacion selectiva. No se repite el alta ni se vuelve a crear la cuenta. Esta secuencia no es una transaccion atomica entre los tres archivos: ante perdida de turno o interrupcion, verificar el estado y reparar selectivamente.
