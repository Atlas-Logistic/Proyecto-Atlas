# Plantas configurables: avance parcial

Base Motor 59c3f33. El catalogo existente ya tiene planta_id, nombre, direccion, comuna, coordenadas y vigencia. La resolucion de evidencia Mobile admite ahora el identificador estable de una planta confirmada y activa del catalogo recibido; mantiene el camino legado por nombre de AZA y rechaza IDs inactivos o de otra empresa. Es un componente aislado: no habilita la funcionalidad completa.

El receptor local del Motor ya valida contra `catalogos_privados/plantas.json` de la empresa: una empresa no MBT sólo admite el `planta_id` activo y confirmado de su propio catálogo. MBT conserva AZA_COLINA/AZA_RENCA como compatibilidad con PWA antiguas. La prueba sintética Transportes Andes rechaza AZA_COLINA y acepta únicamente su ID.

Pendiente antes de integrar: Mobile y Worker todavía ofrecen o aceptan sólo AZA_COLINA y AZA_RENCA. Falta distribuir el catálogo por empresa autenticada y mantener su vigencia, sin acoplar la cola offline a otra empresa ni perder envíos capturados antes de una desactivación. El resolver no demuestra por sí solo que una revalidación o reproceso preserve rutas históricas.

Coordinar el contrato y las escrituras con el trabajo de identidad y permisos de Code. Probar recepcion y procesamiento completos con MBT y Andes ficticias, sincronizacion y aislamiento de catalogos, alteracion de catalogo, reintentos offline y desactivacion tras un viaje. No instalar ni activar este cambio aislado.
