# Plantas configurables por empresa — estado (26-11-2026)

Implementado y validado en aislamiento (`C:/Atlas/pruebas/plantas-empresas-20261126`). **Sin desplegar**: Cloud requiere la migración D1 `0013`, Worker nuevo y PWA 0.17.24; Motor requiere actualizar Estable. Nada de esto se ha activado.

## Contrato

1. **Motor → Cloud** (`atlas_core/cloud_plantas_mobile.py`, en cada ciclo PULL bajo el lease del escritor): `POST /api/motor/plantas {plantas:[{planta_id, nombre}]}` con la lista COMPLETA de plantas `CONFIRMADA` + `ACTIVA` del `catalogos_privados/plantas.json` de la empresa. La empresa la fija el token de Motor. Catálogo ausente, ilegible o fuera de contrato (ID, nombre > 80, > 50 plantas) → no publica nada. **MBT nunca publica.**
2. **Cloud** (migración aditiva `0013_plantas_mobile.sql`): lo no publicado queda `activa = 0` con `desactivada_en` (nunca se borra); lo que vuelve se reactiva. `GET /api/mobile/plantas` (token Mobile) devuelve las activas de la empresa de la sesión; la empresa histórica (`CLOUD_MOTOR_EMPRESA_ID`) sin filas recibe `AZA_COLINA`/`AZA_RENCA` (`origen: LEGADO`); otra empresa sin catálogo recibe `[]`.
3. **Recepción Cloud**: códigos AZA sólo para la empresa histórica; cualquier otro `planta_id` debe estar publicado para la empresa del token y activo, o desactivado DESPUÉS de `capturado_en` (cola offline). Un reintento de un envío ya `RECIBIDO` sigue siendo idempotente. D1 sin `0013`: sólo valen los códigos AZA.
4. **Mobile 0.17.24**: entra con el catálogo guardado de esa sesión (usuario+chofer) o, sin él, con Colina/Renca; consulta Cloud en segundo plano (timeout 8 s, sin bloquear la entrada) y guarda lo recibido. Selector y tarjetas por guía usan el catálogo; los nombres de plantas retiradas se conservan para guías ya capturadas. El teléfono valida sólo la forma del ID; la pertenencia la decide Cloud.
5. **Motor (recepción)**: `validar_planta_origen_mobile` acepta, para no-MBT, un `planta_id` confirmado de su propio catálogo (activo o no: la vigencia la controla Cloud por fecha de captura); MBT conserva los códigos AZA. `resolver_planta_por_codigo_mobile` resuelve por ID aunque la planta esté desactivada, de modo que reproceso y revalidación conservan el origen histórico.

## Validación

- Cloud `test/plantas_empresa.test.js` (9) y suite completa; Mobile `test/mobile-plantas-empresa.test.js` (6) y suite completa (400/400); Motor `tests/test_plantas_configurables_empresa.py` + `tests/test_plantas_id_mobile.py` y suites relacionadas.
- Integrada `scripts/validacion_multiempresa/validar_plantas.py <mundo> <cloud> <mobile>`: Motor real + Worker real (HTTPS local, D1/R2 en memoria) + código real de Mobile en Node; MBT y Transportes Andes ficticia: 14/14 (publicación, aislamiento en ambos sentidos, planta no confirmada, baja con cola offline, PULL por empresa).

## Pendiente para activar

Aplicar `0013` en D1 antes del Worker nuevo (el Worker tolera su ausencia), desplegar Worker + PWA 0.17.24 por `preparar_despliegue`, y actualizar Motor en el equipo escritor. MBT no necesita configuración.
