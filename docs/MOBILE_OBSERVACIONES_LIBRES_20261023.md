# Observaciones Mobile: proyeccion independiente de incidencias

Base operativa9abdd5d, desarrollo en worktree aislado. Sin cambios Desktop/Mobile/Cloud/PULL ni acciones/reconciliacion/catalogos de otro trabajo.

## Causa demostrada

Mobile envia observacion en el payload. Cloud la persiste y el cliente PULL la pasa a RepositorioEnviosMobile.recibir; el texto original sobrevive en envio.json. registrar_eventos_canonicos_mobile solo proyectaba tipos_novedad de incidencia y continuaba si no habia pendientes. Por ello una observacion libre sin incidencia no llegaba a eventos_operacionales.json. Los eventos anteriores a3eb85b8(06/10), creados sin nota, tampoco se rellenaban: su marca de incidencia ya existia.

74237db Desktop(29/09) corrige otra capa: recargar observaciones ANTES de pintar. Sigue instalado.3746923 Motor y06b845f Desktop(16/10) agregan y presentan OBSERVACION_OPERACIONAL para observaciones administrativas B1; tampoco fueron revertidos. Faltaba conectar a ese mismo contrato las observaciones libres Mobile. No hay evidencia de borrado de los originales por Cloud/PULL/B1.

## Correccion

Extraer la prueba de vinculo existente y reutilizarla para una proyeccion de texto separada de las incidencias. Publicar OBSERVACION_OPERACIONAL con procedencia por envio, enriquecer con el viaje vigente, conservar observacion original y recordar publicacion de texto por separado. No adivinar transporte ante falta/ambiguedad/contradiccion; en revision exigir documento propio en un unico viaje del reporte; excluir evidencias firmadas y no reactivar observaciones anuladas.

registrar_evento incorpora anexar_nota optativo, bajo su bloqueo atomico existente. El valor por defecto conserva los contratos anteriores. Mobile anexa bloques de texto exactos, sin sustituir notas administrativas, y registra procedencias distintas aunque el texto ya exista. Reintento tras fallo entre evento/marca no duplica. La proyeccion corre despues del reporte, sin OCR, escrituras documentales, catalogos ni tarjetas. Desktop existente ya muestra los anexos y evita duplicados visuales.

## Validacion

108 pruebas Motor pertinentes aprobadas,13 nuevas;36 Desktop aprobadas, incluidos refresco74237db, anexo06b845f y notas administrativas. Regresion roja reproducida en9abdd5d: fuente conservada sin evento. Casos nuevos: sin incidencia, varios envios/mismo viaje, multilinea, deduplicacion y procedencia, B1 antes/despues, anulados, evidencia firmada, revision independiente del vinculo, transporte ausente/ambiguo/contradictorio y reintento tras fallo.

Inventario privado:28fuentes con texto conservado,19textos ausentes en eventos(17libres+2incidencias antiguas creadas vacias). Ensayo en copia de28fuentes:98->122eventos; todos los textos visibles en contrato canonico, eventos de incidencia originales identicos, idempotencia de segunda pasada. Una observacion libre ya registrada por B1 se conserva sin duplicar su texto. No se publican datos privados; evidencia local pruebas/mobile-observaciones-20261023.

Cloud GET lector de pendientes:0en la comprobacion. La API Motor no permite releer metadata de envios ya consumidos; el texto preservado en la recepcion local demuestra que no se perdio antes de la proyeccion. No se consumieron/confirmaron envios ni se solicitaron pruebas a choferes.

## Despliegue y recuperacion

Integracion solo en ventana coordinada sin escritores Code, con lease y respaldo. Recuperacion por lista explicita de envios con original verificable y viaje unico del reporte vigente; excluir guias protegidas por Code y abstenerse ante cambios de fuente/vinculo. Solo eventos y marca de publicacion en envio.json; conservar bytes originales del campo observacion y de las fotos, dataset/catalogos/bandeja/ledger/agrupaciones y eventos tipificados previos. No reingesta ni reconciliacion. Verificar idempotencia y app instalada antes de cerrar. Reversion de codigo y fuentes respaldadas, sin restauraciones indiscriminadas de datos.
