# Integración conjunta multiempresa — 26/11/2026

Rama `integracion/multiempresa-20261126` en los cuatro repositorios. **Nada desplegado ni instalado**: no se tocó producción, G:, PULL, Cloudflare real, OFICINA/CASA ni las ramas B1 de Codex.

| Componente | Base integrada | Integración |
|---|---|---|
| Motor | plantas `4b6ba30` (⊃ identidad `e1fa560`) | + `b0b42e4` (Motor de OFICINA), + `b09bd28` (ingreso Desktop / perfiles documentales), + fix de atribución, + validación |
| Cloud (Worker) | plantas `fcc2051` (⊃ identidad `117899d`) | sin cambios |
| Mobile | `94099ef` (0.17.24) | sin cambios |
| Desktop | identidad `5665982` | + arnés Electron de la validación |

## Incompatibilidades resueltas

1. **El Motor de plantas no traía la contraparte del ingreso de Desktop.** `5665982` contiene el ingreso multiempresa de Desktop (`15f8799`, acción `capacidades` y `--perfil-documental`). `4b6ba30` no tenía `f4b7775`/`12c630d` (`b09bd28`), así que se fusionaron. El único conflicto fue `COORDINACION.md`, y se conservaron ambas secciones.
2. **La rama quedaba por detrás del Motor de OFICINA.** Se fusionó `b0b42e4`, el Motor que Desktop `2914483` usa en producción (B1 adicionales). No hubo conflictos.
3. **La corrección se atribuía a `JAVIER_DESKTOP`.** Desktop invoca `b1_operador_cli` con `--usuario JAVIER_DESKTOP` sea quien sea el usuario, y con identidad exigida el ledger de Andes registraba ese actor. Ahora `identidad.actor_operacion` usa `<empresa>:<usuario>` de la sesión validada por la puerta. MBT, sin exigencia, conserva el actor declarado. Pruebas: `tests/test_identidad_actor_operacion.py` (4).

## Validación integral

```
python -B scripts/validacion_multiempresa/validar_integracion.py <mundo bajo C:\Atlas\pruebas> <cloud> <mobile> <desktop> <python RapidOCR> --desktop
```

Usa Transportes Andes y MBT, ambas ficticias, con componentes reales: Motor, Worker (D1/R2 en memoria, HTTPS local), código Mobile en Node, OCR RapidOCR y Electron con el Motor. La preparación reutiliza los procedimientos ya validados (`validar_alta`, `validar_identidad`) sin volver a evaluarlos. Las 24 verificaciones cubren lo que solo existe al unir las piezas:

- **Alta.** Alta integral de Andes con sus plantas como catálogo inicial (sin AZA), administrador y supervisor, y exigencia de identidad en ambas empresas.
- **Plantas.** El primer PULL de Andes, un proceso de sistema sin sesión, publica sus 2 plantas. MBT no publica.
- **Mobile.** El chofer creado por el alta ve solo las plantas de Andes y envía su guía (200); con `AZA_COLINA` recibe 400. El chofer MBT ve Colina/Renca y no puede usar una planta de Andes.
- **Recepción y procesamiento.** El PULL de Andes con OCR real recibe el envío con su `planta_id`, lo procesa en su dataset y Cloud lo marca confirmado. MBT recibe solo lo suyo, y su raíz y su estado local quedan idénticos byte a byte.
- **Permisos.** Sin sesión, la consulta B1 sobre la guía nueva se niega con código 77 `SIN_SESION`.
- **Desktop (Electron real) con el supervisor de Andes:**
  - historial Mobile solo de Andes;
  - dos correcciones B1, transporte y peso, con vista previa y confirmación humana;
  - ledger atribuido a `andes-prueba:andes.sup`;
  - reporte vigente regenerado;
  - consulta (B1 → Consultas Atlas) con el peso corregido;
  - informe armado con el exportador real y vista previa PDF abierta;
  - ingreso de guías por Desktop detenido antes de copiar;
  - MBT intacta.

Resultado: **24/24**. Evidencia: `docs/evidencia/integracion_multiempresa_20261126.json` (incluye el HTML del informe).

Regresión del Motor integrado: 269 aprobadas en las suites focales (aislamiento, alta, identidad, plantas, ingreso/perfiles, B1 adicionales, exclusión local). Regresión amplia (B1, acciones, Mobile, procesamiento): 1566 aprobadas y 15 fallidas, todas en `tests/test_procesamiento_masivo.py`. Esas mismas pruebas fallan sin la integración: 8 en `4b6ba30`, 13 en `b09bd28` y 8 en `b0b42e4`. La comparación fue por conteo; queda pendiente revisarlas una por una, sobre todo las que heredó `b09bd28` (Codex).

### Límites de la prueba

- Las raíces del mundo están en C:, por lo que no se consideran compartidas. Por eso Desktop escribe sin lease ni turno, como en el validador Electron de identidad. El escritor con lease de Drive no se ejerce desde Desktop. Sí lo ejercen el PULL y el alta.
- Las guías son imágenes sintéticas con texto. El OCR es real, pero el formato no corresponde a ninguna guía real.

## Dependencias funcionales pendientes (registradas, no desarrolladas)

1. **Perfil documental de otra empresa.** No existe un implementador de perfil documental para Andes. El ingreso por Desktop se bloquea correctamente (`FORMATO_DOCUMENTAL_DESCONOCIDO`, sin copiar). En cambio, la recepción Mobile/PULL procesa la guía con el pipeline **AZA**, porque `procesar_archivo` sin perfil usa `PERFIL_AZA`. La guía queda `REQUIERE_REVISION` con campos AZA (`hora_entrada_aza`…). Hay que decidir si el PULL de una empresa sin perfil debe abstenerse o usar su propio perfil.
2. **Modelo de viaje atado al «número de transporte» AZA.** Una guía sin ese dato queda en `documentos_sin_transporte` y no aparece en viajes, consultas ni informe hasta que una persona le asigna uno por B1.
3. **Primer reporte de una empresa nueva.** El PULL procesa, pero `revalidar_y_regenerar_reporte` nunca fuerza la primera regeneración, y el alta no la crea. Desktop ya no reconcilia al abrir, y `generar_reporte_viajes.py` en raíz compartida falla por `EscrituraSinTurno`. El primer reporte aparece recién con una corrección.
4. **Informe con rótulo MBT.** El exportador es `AtlasExportacionMBT*`: el encabezado dice «Informe MBT», la vista previa se titula «Informe MBT PDF» y el formato no incluye el peso. Falta un rótulo o plantilla por empresa (ya figuraba en ALTA_EMPRESA §6).
5. **Usuario de solo consulta.** `usuarios_atlas.py` admite solo `administrador_empresa` y `supervisor` (`ROLES_EMPRESA`), aunque `PERMISOS` y Desktop reconocen `consulta`.
6. **Atribución en otros escritores.** Aún usan un actor fijo con identidad exigida: `confirmar_incidencias_operacionales` (`JAVIER_DESKTOP`), `asociar_evidencia_mobile` (`DESKTOP`), `aplicar_decisiones_multiples` y `operaciones_conversacionales_cli` (`JAVIER_DESKTOP` por defecto), y `acciones_operacionales_cli`, donde el actor lo fija el llamador. Basta aplicarles `identidad.actor_operacion`.

Además, siguen pendientes las activaciones ya conocidas: D1 `0013`, Worker y PWA 0.17.24 vía `preparar_despliegue`, el secreto `CLOUD_MOTOR_TOKENS_JSON`, un Motor escritor con esta rama, y Desktop con `desktop_acceso.json`.
