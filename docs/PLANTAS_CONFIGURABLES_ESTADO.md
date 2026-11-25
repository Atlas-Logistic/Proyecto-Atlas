# Plantas configurables: avance parcial

Base Motor 59c3f33. El catalogo existente ya tiene planta_id, nombre, direccion, comuna, coordenadas y vigencia. La resolucion de evidencia Mobile admite ahora el identificador estable de una planta confirmada y activa del catalogo recibido; mantiene el camino legado por nombre de AZA y rechaza IDs inactivos o de otra empresa. Es un componente aislado: no habilita la funcionalidad completa.

Pendiente antes de integrar: Mobile y Worker todavia ofrecen o aceptan solo AZA_COLINA y AZA_RENCA; RepositorioEnviosMobile hace la misma validacion. Falta distribuir el catalogo por empresa autenticada y mantener su vigencia, sin acoplar la cola offline a otra empresa ni perder envios capturados antes de una desactivacion. El resolver no demuestra por si solo que una revalidacion o reproceso preserve rutas historicas.

Coordinar el contrato y las escrituras con el trabajo de identidad y permisos de Code. Probar recepcion y procesamiento completos con MBT y Andes ficticias, sincronizacion y aislamiento de catalogos, alteracion de catalogo, reintentos offline y desactivacion tras un viaje. No instalar ni activar este cambio aislado.
