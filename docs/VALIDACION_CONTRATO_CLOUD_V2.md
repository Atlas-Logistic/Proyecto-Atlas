# Validación cruzada del contrato Motor–Cloud v2

Fecha: 20/11/2026. Responsable: Claude Code.

Estado: **validación terminada, adaptador sin implementar**. No se modificaron
`atlas_core/`, el repositorio Cloud, escritores, lectores, PULL, B1, Desktop,
Mobile, datos reales ni la instalación. CASA sigue en `c08bc38`.

**Conclusión:** el descriptor Motor v2 se representa y se comprueba con el contrato Cloud v2 sin
cambiar su semántica ni sus bytes. No hay incompatibilidades que bloqueen. Hay dos reglas que el
adaptador v2 debe agregar (§7, I1 e I2) y tres puntos pendientes del lado Cloud o del contrato
(I4, I5 e I7). Los cambios necesarios en `descriptor_custodia.py` son **aditivos**: el camino v1
queda intacto (§8).

## 1. Referencias

| Elemento | Commit / blob |
|---|---|
| Descriptor Motor v2 | `a9b5649399ff0978aa478f7f0f8992d5df264766` |
| Adaptador Motor–Cloud v1 | `57e5173136759e4680cd7c12befcd8b2ce7957a1` |
| Diseño de coherencia | `ed84c9477110e37ba3b5074e651fff7b6aecf294` |
| Base de esta rama | `d7e66e9` (contiene los tres anteriores) |
| Contrato Cloud v2 | Atlas-Mobile-Cloud `79de40805cc746254ef09e9a80e8b5e2ab2944fc` |
| `docs/contrato-cloud-v2-inventarios.md` | blob `4e6e2eaffa6bf3d99e59365629d2edb4a80936e1` |
| `test/vectores_cloud_v2.json` | blob `d1eede606da9128e357413ec1167fbf9089a59a9` |
| `test/fixture_motor_v2_sintetico.json` | blob `e99aa4e2c25db8262e4a311e3a2607cbaa3e95b3`, SHA-256 `e11f3779…532932` |
| `test/contrato_cloud_v2_modelo.test.js` | blob `48f634d82720cf0334b45de6475236ee3a331057` |

El trabajo se hizo en la rama `docs/validacion-contrato-cloud-v2-20261120`, en el worktree
`C:/Atlas/pruebas/validacion-cloud-v2-20261120/motor`. Cloud se leyó desde una copia hecha con
`git archive` en `C:/Atlas/pruebas/validacion-cloud-v2-20261120/cloud-79de408`, sin tocar su
repositorio.

## 2. Método

Archivos nuevos:

- `tests/contrato_cloud_v2/referencia_cloud_v2.py`: **verificador de referencia, solo para
  pruebas**. Es una implementación Python independiente de las secciones 1 a 3 del contrato, escrita
  desde su texto. No se importa desde `atlas_core`.
- `tests/contrato_cloud_v2/modelo_cloud_v2.mjs`: evalúa **sin modificar** las funciones
  `crear`/`verificar` del modelo Node de Codex y responde a casos JSON.
- `tests/contrato_cloud_v2/{vectores_cloud_v2.json, fixture_motor_v2_sintetico.json}`: copias
  cuya identidad con los blobs de `79de408` se comprueba en cada ejecución.
- `tests/test_validacion_contrato_cloud_v2.py`: 48 pruebas en tres grupos, distinguibles por el
  prefijo del nombre:
  - **`test_oficial_*` (5):** solo bytes y resultados publicados por Codex. Ningún valor esperado
    se calcula aquí.
  - **`test_cruzado_*` (3):** el modelo Node original y la referencia Python reciben las mismas
    entradas y deben producir bytes y hashes idénticos. Requiere `DESCRIPTOR_CLOUD_V2_DIR` apuntando
    a la copia `git archive` y `node`; sin ellos se omite.
  - **`test_sintetico_*` y `test_compat_*` (40):** casos adicionales sin resultado publicado.
- `conciliar_motor` y `proyectar_motor` (en el archivo de pruebas): especificación ejecutable de
  las reglas mínimas del futuro adaptador. No son el adaptador.

Mutaciones de la referencia que los vectores oficiales detectan:

- duplicar el nodo impar en vez de promoverlo;
- omitir el separador `0x00`;
- invertir el orden de los hijos;
- particionar en grupos de 101.

La mutación `sort_keys=False` solo la detectan las pruebas sintéticas de serialización no canónica,
porque los vectores ya traen las claves en orden.

Ejecución:

```
TEMP=C:/t  DESCRIPTOR_CLOUD_V2_DIR=C:/Atlas/pruebas/validacion-cloud-v2-20261120/cloud-79de408 \
  python -m pytest tests/test_validacion_contrato_cloud_v2.py -q -p no:cacheprovider
```

Resultados:

- Con el modelo Node: **48 passed**.
- Sin él: 45 passed y 3 skipped.
- Focales `test_descriptor_generacion*.py` y `test_descriptor_custodia.py` junto con las nuevas:
  186 passed y 5 skipped. Las omitidas son los cruces opcionales con Worker y Node.
- Modelo original de Codex (`node --test test/contrato_cloud_v2_modelo.test.js` en la copia):
  5/5.

## 3. Verificación cruzada (punto 2 del encargo)

| # | Aspecto | Resultado | Evidencia |
|---|---|---|---|
| 1 | Serialización canónica | **Coincide.** Python `json.dumps(sort_keys, separators=(",",":"), ensure_ascii=True)` reproduce los bytes publicados de parte y cabecera. El modelo JS confía en el orden de inserción; la referencia exige claves ordenadas y rechaza claves duplicadas, escapes alternativos, espacios y saltos finales. | oficial 1 parte; sintético no canónico |
| 2 | Identidad empresarial | **Coincide.** El patrón de empresa de Motor y Cloud es textualmente el mismo. La empresa queda comprometida en la cabecera y en cada parte: el mismo ID e inventario en otra empresa da otra raíz y otra huella. Motor es más estricto (rechaza `mbt` y `oficina`, que el patrón Cloud admite). | sintético empresa cruzada |
| 3 | Identificador de generación | **Coincide.** El patrón es idéntico y `anterior_id ≠ generacion_id` en ambos lados. Diferencia: Cloud no compara `anterior_id` con `previa_id` de Motor (ver I1). | sintético anterior |
| 4 | Orden de objetos y partes | **Coincide.** El orden es por bytes ASCII (Python `sorted` = comparación JS para ASCII). `_atlas/…` se ordena antes de las identidades Motor (`_` < `a-z`). Índices consecutivos; todas las partes con 100 objetos salvo la última. | oficial 3 partes; sintético orden |
| 5 | SHA-256 de objetos | **Coincide.** `sha256` es la huella Motor sin `sha256:`. Las rutas distintas con el mismo contenido se admiten. | oficial; fixture |
| 6 | SHA-256 de partes | **Coincide.** El SHA ordinario (clave R2) y la hoja con dominio `atlas-custodia-v2/parte\0` son valores distintos y se verifican por separado. | oficial `parte_sha256_bytes` / `parte_sha256_dominio` |
| 7 | Raíz Merkle | **Coincide.** El impar se promueve sin duplicarse; con una parte, la raíz es la hoja. Se reprodujeron las 3 hojas y la raíz `21c06611…` publicadas. | oficial 3 partes |
| 8 | Huella de generación | **Coincide.** `H("atlas-custodia-v2/cabecera\0" ‖ cabecera)` reproduce `55a4a404…` y `0a7843ca…`. | oficial |
| 9 | `_atlas/descriptor_generacion.json` | **Coincide.** El fixture Motor v2 se regenera byte a byte con el código de `a9b5649`. Viaja intacto, `sha_descriptor_motor` = SHA de sus bytes (≠ `huella_descriptor` interna) y sus 19 fuentes forman los otros 19 objetos. | oficial fixture |
| 10 | Versiones Motor v1/v2 y Cloud v1/v2 | **Compatibles**, con las reglas de §5 y §6. | compat |

## 4. Casos obligatorios (punto 3)

### 4.1 Tamaños

| Objetos | Partes | Sintético (referencia + Node) | Descriptor Motor v2 real | Camino v1 |
|---:|---:|---|---|---|
| 1 | 1 | válido Cloud | **imposible**: el v2 mínimo tiene 10 fuentes (9 sin marca) | — |
| 100 | 1 | OK | OK | admite |
| 101 | 2 | OK | OK | admite |
| 999 | 10 | OK | OK | admite |
| 1.000 | 10 | OK | OK | **admite** (999 fuentes + descriptor) |
| 1.001 | 11 | OK | OK | `LIMITE_CUSTODIA` |
| 2.500 | 25 | OK | OK | `LIMITE_CUSTODIA` |
| 5.000 | 50 | OK | OK | `LIMITE_CUSTODIA` |

En cada tamaño se comprobaron conteos, índices, suma exacta y la prueba Merkle de cada página contra
la raíz comprometida. Los tamaños medidos con descriptores Motor reales:

| Objetos | Cabecera | Parte máxima | Descriptor Motor | Construir + verificar + conciliar |
|---:|---:|---:|---:|---:|
| 100 | 304 B | 21.979 B | 43.998 B | 0,01 s |
| 1.000 | 306 B | 23.716 B | 439.901 B | 0,11 s |
| 5.000 | 306 B | 23.717 B | 2.203.904 B | 0,59 s |

Una parte con 100 rutas de 256 bytes, empresa de 40 y generación de 128 queda por debajo de 40.000 B.
Con entradas válidas, el límite de 65.536 B es inalcanzable.

### 4.2 Rechazos

| Caso | Oficial / cruzado | Código de la referencia |
|---|---|---|
| Parte alterada (SHA de un objeto) | cruzado (Node también rechaza) | `RAIZ_INCORRECTA` |
| Parte alterada (bytes no canónicos) | sintético | `NO_CANONICO` |
| Objeto duplicado (mismo o distinto SHA; dentro y entre partes) | sintético | `IDENTIDAD_DUPLICADA` |
| Empresa cruzada (cabecera, parte, Motor ajeno en generación propia) | cruzado + sintético | `EMPRESA_INCORRECTA` |
| Versión desconocida (1, 3, 0, `true`, `"2"`, `null`) en cabecera o parte | cruzado + sintético | `VERSION_INCOMPATIBLE` |
| Descriptor Motor inválido | **oficial**: el objeto del vector 1, `{"version_contrato":2}`, es válido para Cloud y Motor lo rechaza con `FORMATO_INVALIDO`. También sintéticos: bytes con otro SHA → `DESCRIPTOR_ALTERADO`; bytes recalculados → `ErrorDescriptor`; autodeclarado `COMPLETA` → `DESCRIPTOR_AUTODECLARADO` | |
| Inventario sobrante, faltante o con otra huella frente al Motor | sintético | `INVENTARIO_INCONSISTENTE` / `INVENTARIO_INCOMPLETO` |
| Parte ausente / sobrante / sólo la primera | cruzado + sintético | `PARTE_AUSENTE` / `PARTE_SOBRANTE` |
| Orden incorrecto (partes, objetos, partición 99/101) | cruzado + sintético | `ORDEN_INCORRECTO` / `CONTEO_INCORRECTO` |
| Huella incorrecta / raíz / `sha_descriptor_motor` / conteo | cruzado + sintético | `HUELLA_INCORRECTA` / `RAIZ_INCORRECTA` / `DESCRIPTOR_INCONSISTENTE` / `CONTEO_INCORRECTO` |
| Prueba Merkle de otro índice, truncada, sobrante, otro total | sintético | rechazada |

## 5. Compatibilidad retroactiva (punto 4)

| Requisito | Resultado |
|---|---|
| Cloud v1 sigue legible | Sí. `proyectar_para_custodia` y `verificar_generacion_custodia` funcionan igual con Motor v2 de hasta 1.000 objetos. La huella v1 del fixture queda fijada en `7094e7c4…490d0e`. |
| Lector v1 frente a cabecera v2 | `VERSION_INCOMPATIBLE`; nunca se lee como v1 parcial. El verificador v2 rechaza el cuerpo v1 con `VERSION_INCOMPATIBLE`. |
| Descriptor Motor v1 conserva bytes y huella | Sí. Todos los casos de `tests/fixtures/descriptor_generacion_v1.json` se releen con su `huella_descriptor` y sus bytes idénticos. |
| Motor v2 no se convierte en v1 | Sí. En Cloud v1 y en Cloud v2 los bytes conservan `version_contrato: 2`. El mismo inventario no es válido con reglas v1. Un Motor v1 transportado en Cloud v2 se relee como v1, sin promoverse. |
| Decisiones humanas, asignaciones y evidencia sin alterar | Sí. La proyección usa solo `fuentes`. Los 2 roles de decisiones, la derivación `ASIGNACIONES` y los roles de evidencia vuelven idénticos (`leido == motor`). No se tocó `descriptor_generacion.py`. |
| Leer v1 no depende de v2 | Sí. `descriptor_custodia.py` no referencia v2. `VERSION_CUSTODIA = 1`, `VERSIONES_CUSTODIA_COMPATIBLES = {1}` y `MAX_OBJETOS_CUSTODIA = 1000` quedan fijados por prueba. |

## 6. Matriz de compatibilidad Motor–Cloud

| Descriptor Motor ↓ / Custodia Cloud → | **Cloud v1** (`/custodia/v1`, `{version:1,…}`) | **Cloud v2** (`/custodia/v2`, cabecera + partes) |
|---|---|---|
| **Motor v1** (`version_contrato: 1`) | **Soportado** (57e5173). Hasta 1.000 objetos. Bytes y huella preservados. | **Representable y verificable**: el descriptor viaja intacto y se relee como v1. Recomendación: **no proyectar** nuevas generaciones v1 (ver I7). Solo leer las existentes, si alguna llegara a existir. |
| **Motor v2** (`version_contrato: 2`) | **Soportado** hasta 1.000 objetos (999 fuentes). Bytes v2 intactos; `anterior_id` no comprometido en el descriptor Cloud. Con evidencia real probablemente no alcanza. | **Objetivo.** Sin límite de objetos. Requiere el adaptador de §8 con la regla `anterior_id == previa_id`. |
| **Motor v3+** | `VERSION_INCOMPATIBLE` (en `leer_descriptor`) | `VERSION_INCOMPATIBLE` (en `leer_descriptor`) |
| **Cabecera Cloud v3+ / cuerpo con versión desconocida** | `VERSION_INCOMPATIBLE` | `VERSION_INCOMPATIBLE` |

Las dos versiones son independientes: `version` Cloud la decide el endpoint y `version_contrato` va
dentro de los bytes Motor. La cabecera Cloud v2 no revela la versión Motor, así que el lector la
conoce solo después de descargar y verificar el objeto reservado.

## 7. Incompatibilidades y observaciones

Ninguna obliga a modificar el contrato Cloud v2 ni el descriptor Motor.

- **I1 — `anterior_id` (Motor, obligatoria).** Cloud v2 compromete `anterior_id` en la cabecera,
  pero no puede compararlo con `generacion.previa_id`, que va dentro de los bytes Motor. El
  adaptador v1 tampoco lo hace, porque el descriptor v1 no lo transporta. Una cabecera con anterior
  `null` o ajeno pasa la verificación Cloud y solo `conciliar_motor` la detecta. Regla nueva:
  `anterior_id == previa_id`; si no, `GENERACION_INVALIDA`.
- **I2 — Serialización (Motor, obligatoria).** No reutilizar `_bytes_cloud`, que sigue el orden de
  inserción v1 (`version, empresa_id, …`), ni `_canonico` de Motor (`ensure_ascii=False`). Cloud v2
  exige claves ordenadas y ASCII. Hoy coinciden solo porque los patrones fuerzan ASCII. El
  verificador v2 debe comprobar que los bytes recibidos son canónicos y no tienen claves duplicadas,
  algo que el modelo Node no hace porque compara objetos ya parseados.
- **I3 — Límite v1 (aclaración).** `MAX_OBJETOS_CUSTODIA = 1000` incluye el descriptor: admite 999
  fuentes y el rechazo empieza con 1.001 objetos. v2 no lo aplica, como fija el contrato.
- **I4 — Lectores v1 frente a generaciones v2 (Cloud, pendiente).** Hoy el Worker v1
  (`descriptorGeneracion`) lanza un error y `GET …/v1/generaciones/actual` respondería `503
  NO_CONFIABLE`, no "versión incompatible" como pide §4 del contrato. Tampoco está definida la
  cadena `anterior_id` entre una generación v2 y una v1 anterior (puntero unificado). No afecta a
  Motor.
- **I5 — Prueba Merkle por página (contrato, pendiente).** No está fijada la forma serializada (lado,
  codificación, orden). Además, la prueba de una hoja **no fija por sí sola el total**: con 11
  partes, la prueba de la hoja 7 es válida para totales de 9 a 12. El verificador debe tomar
  `numero_partes` de la cabecera ya verificada por huella, nunca del cliente. Faltan vectores
  oficiales de pruebas por página.
- **I6 — 1 objeto (sin cambio).** Una generación Cloud con solo el descriptor es válida para Cloud y
  nunca puede venir de un Motor v2 válido. La igualdad exacta de inventarios la rechaza.
- **I7 — Motor v1 en Cloud v2 (decisión).** El contrato lo permite y técnicamente funciona. Se
  recomienda que la **proyección v2 exija `version_contrato == 2`**, porque el escritor solo debe
  publicar v2, y que la **verificación v2 acepte lo que acepte `leer_descriptor`** ({1, 2}). Javier y
  Codex deben confirmarlo.
- **I8 — Catálogos globales (sin cambio).** Las fuentes con `empresa_id: null` (`COMPARTIDA_GLOBAL`)
  viajan bajo el namespace de la empresa autenticada con la misma identidad. Dos empresas almacenan
  copias independientes.

## 8. Cambios mínimos en `descriptor_custodia.py` (sin implementar)

Son todos **aditivos**. No se modifican `VERSION_CUSTODIA`, `VERSIONES_CUSTODIA_COMPATIBLES`,
`MAX_OBJETOS_CUSTODIA`, `_bytes_cloud`, `ProyeccionCustodia`, `proyectar_para_custodia` ni
`verificar_generacion_custodia`. No hace falta tocar `descriptor_generacion.py`, porque `CODIGOS` no
se aplica y los errores se mapean a códigos existentes.

1. **Constantes:** `VERSION_CUSTODIA_V2 = 2`, `OBJETOS_POR_PARTE = 100`, `MAX_BYTES_PARTE = 65536`,
   dominios `atlas-custodia-v2/{parte,nodo,cabecera}` y los patrones de ruta y SHA, compartiendo
   `RUTA_DESCRIPTOR`.
2. **Funciones privadas:** `_canonico_cloud_v2` (`sort_keys`, `ensure_ascii=True`,
   `allow_nan=False`), `_hash_dominio`, `_raiz` con promoción del impar, `_cargar_canonico` (rechaza
   claves duplicadas, campos extra, `bool` como entero y bytes no canónicos).
3. **`ProyeccionCustodiaV2`:** `cabecera_bytes`, `huella`, `partes_bytes`, `partes_sha256` (clave R2),
   `objeto_descriptor`, `objeto_descriptor_sha256` y `anterior_id`. No incluye token, lease, época
   ni estado.
4. **`proyectar_para_custodia_v2(descriptor, empresa_custodia)`:** valida la empresa igual que v1,
   revalida el descriptor con `leer_descriptor(serializar_descriptor(...))`, exige
   `version_contrato == 2` (I7), toma `anterior_id = previa_id`, ordena y particiona. No aplica
   límite total.
5. **`verificar_generacion_custodia_v2(cabecera_bytes, partes_bytes, datos_descriptor,
   empresa_custodia, *, huella_esperada, generacion_esperada=None)`:**
   1. Cabecera: versión, campos y canonicidad, y huella igual a la fijada por el lector.
   2. Todas las partes `0..numero_partes-1`, una sola vez: versión, empresa, generación, índice,
      cantidades, orden estricto global y raíz.
   3. Descriptor: SHA del objeto reservado igual a `sha_descriptor_motor` y a sus bytes.
   4. `leer_descriptor`; empresa, generación y **`anterior_id == previa_id`** (I1).
   5. Igualdad exacta de fuentes, con la misma distinción v1 entre `REFERENCIA_INCONSISTENTE` e
      `INVENTARIO_INCONSISTENTE`.

   Devuelve el `DescriptorPreparado` sin estado de publicación.
6. **Mapeo de códigos:**
   - versión → `VERSION_INCOMPATIBLE`;
   - empresa → `EMPRESA_INCORRECTA`;
   - generación o anterior → `GENERACION_INVALIDA`;
   - duplicado → `IDENTIDAD_DUPLICADA`;
   - parte ausente o fuente faltante → `INVENTARIO_INCOMPLETO`;
   - orden, conteo o sobrante → `INVENTARIO_INCONSISTENTE`;
   - no canónico, raíz, huella o SHA del descriptor → `DESCRIPTOR_ALTERADO`;
   - forma → `FORMATO_INVALIDO`.
7. **Pruebas por página:** posponerlas hasta que el contrato fije su forma (I5).

`tests/contrato_cloud_v2/referencia_cloud_v2.py` y `conciliar_motor` sirven de oráculo para
el adaptador: las 48 pruebas deben seguir pasando cuando se reemplacen por las funciones de
`atlas_core`.

## 9. Pendientes

- **Codex:**
  - forma y vectores de la prueba Merkle por página (I5);
  - respuesta v1 ante una generación v2 y puntero unificado entre versiones (I4);
  - visto bueno a I1 e I7.
- **Integración:** implementar §8 en una rama aparte, sin conectarlo al escritor, que sigue
  sujeto a E1–E7 de `ed84c94`.
- **Sin verificar aquí:** D1, R2, retención, CAS, límites de Workers y autenticación. Son pruebas
  del entorno Cloud, fuera de este encargo.
