# Diseño: coherencia operacional entre escritores (generaciones)

Estado: **diseño, sin implementar.** Base Motor `a9b5649` (descriptor v2). Solo hay documento
y un modelo sintético en `tests/modelo_coherencia/` con sus pruebas en
`tests/test_modelo_coherencia_generaciones.py`. No se cambió ningún escritor, lector, lock,
PULL, B1, Desktop, Mobile, Cloud ni el descriptor v2.

Referencias: `docs/FUENTES_GENERACION.md`, `docs/DESCRIPTOR_GENERACION.md`,
`docs/CONTRATO_COHERENCIA_LECTURA_LOTES.md` (51167a7), `docs/VERIFICACION_CUSTODIA_GENERACIONES.md`
(625ab15) y la custodia de generaciones Cloud (`61c2872`).

## 0. Qué existe hoy (evidencia del código)

| Mecanismo | Dónde | Qué garantiza | Qué no |
| --- | --- | --- | --- |
| **Turno local** | `exclusion_local.py` | Un escritor por raíz, equipo y perfil (lock de bytes del kernel). Lo toman `LeaseEscritorOperativo` y `EscritorEquipoUnico`; PULL, la sesión Desktop, B1, mantenimiento y migración lo heredan. La guardia (audit hook, `exigir` por defecto) rechaza escrituras sin turno en raíces protegidas. | Según su propio docstring no cubre: descriptores abiertos antes, llamadas nativas, alias de ruta, procesos hijos, procesos ajenos al Motor ni otros equipos. |
| **Lease Cloud** | `escritor_operativo.py` (heartbeat 30 s), Worker `LEASE_ESCRITOR_SEGUNDOS = 120`, prioridad del último escritor 10 min, `epoca` | Un escritor por empresa entre CASA y OFICINA. | No da a los lectores una instantánea. |
| **Protocolo 2 de custodia** | `vincular_raiz`; `estado_confirmado` | Antes de escribir, la copia local debe coincidir con la marca Cloud (`ESTADO_NO_VERIFICADO` si no). | Confirma por lotes de 50 al cerrar el turno (`LeaseEscritorOperativo.cerrar` → `_cerrar_custodia`) y libera el lease aunque la confirmación falle: no hay estado global `COMPLETA`. |
| **Sesión Desktop** | `desktop_operacion.sesion` / `ejecutar` | Cada invocación de Desktop (ingresar o un script de `ESCRITORES`) corre con turno + lease + lock `desktop_manual`. `ingresar` copia la evidencia a `operacion/entradas/<marca>` **dentro** de la sesión. | — |
| **PULL** | `sincronizar_mobile_cloud.ejecutar_pull_con_escritor` | Una pasada por lease; `vincular_raiz` y `guardia_pull.proteger_escrituras`. | — |
| **Locks por recurso** | `almacenamiento_portable.bloqueo_sesion`, archivo `.atlas_lock_<nombre>` | Exclusión dentro de una misma raíz (huérfano tras 6 h). | Nombres distintos por fuente; `revalidacion_dataset` no es reentrante y se suelta entre ventanas de `aplicar_decision_obra` (`aplicacion_decisiones.py:1404-1412`; *GAP RESIDUAL* en `mobile.py:1400-1419`). |
| **Marca de publicación documental** | `acciones_operacionales.publicacion_documental_incompleta` y los métodos `recuperar_*` | Recuperación por token de las acciones protegidas. | No cubre `aplicar_decision_obra` ni otros escritores. |

**Conclusión:** entre escritores **gobernados** ya hay exclusión global (turno + lease): dos de
ellos no escriben a la vez. La incoherencia observada viene de:
1. **Lectores sin lease** (SOLO CONSULTA, B1 de consulta, preview de lotes, Desktop leyendo G:)
   que leen archivos vivos a mitad de una operación lógica de varios archivos.
2. **Caídas o pérdida del lease** a mitad de operación, que dejan estado parcial sin marca
   global.
3. **Escritores no gobernados** (ver §2.3).
4. **La réplica Drive**, que lleva archivos sueltos y desordenados entre CASA y OFICINA.
5. **Lectores que convierten ausente o ilegible en vacío.**

## 1. Arquitectura recomendada

**Generaciones inmutables publicadas al cierre del turno de escritor que ya existe, con una
frontera durable `PENDIENTE` en Cloud y una única transición CAS a `COMPLETA`.** Es la
alternativa 2, usando el turno actual como frontera de escritura, más una pieza mínima de la
alternativa 3: un diario de intención para las operaciones de varios archivos que hoy no lo
tienen.

1. Al obtener el turno (turno local + lease + protocolo 2), y antes de la primera mutación,
   el escritor abre la **frontera**: control Cloud por empresa `PENDIENTE(época, titular)`.
2. Las operaciones del turno escriben como hoy, con sus locks.
3. Al cerrar el turno, **sólo si todas sus operaciones terminaron sin error**, el escritor
   (todavía con lease):
   * captura el inventario del contrato de fuentes con dos pasadas de huella;
   * construye el descriptor v2;
   * sube los objetos que falten;
   * publica con **un solo CAS** que mueve el puntero a la nueva generación y vacía el control.

   Sin cambios, cierra la frontera con otro CAS («sin cambios»).
4. Si el turno falla, cae o pierde el lease, el control queda `PENDIENTE` de esa época: la
   siguiente época lo ve como `INTERRUMPIDA`.
5. Los lectores coherentes **nunca combinan archivos vivos**. Leen la última generación
   `COMPLETA` y verifican cada objeto por SHA-256; la copia local sólo vale si su huella
   coincide. Reciben `CONFIABLE(generación, fuentes, frescura)` o `NO_CONFIABLE(código)`.

### Por qué es la opción mínima segura (comparación)

| Criterio | 1. Lock global + marca durable | 2. Generaciones inmutables + puntero (**recomendada**) | 3. Coordinación transaccional sobre escritores |
| --- | --- | --- | --- |
| Seguridad para lectores | Sólo si el lector toma el lock. Entre equipos exige un lock Cloud, y la marca en Drive llega desordenada. | El lector ve una generación completa o `NO_CONFIABLE`. No depende del orden de Drive. | Hace atómica cada operación, pero el lector sigue necesitando una frontera común. |
| Bloqueo | Los lectores bloquean al escritor, y PULL espera a la UI o B1. | Los lectores no bloquean. | No bloquea. |
| Complejidad | Baja local, alta entre equipos. | Media: captura, objetos, CAS Cloud (en parte ya existe en 61c2872). | Alta: cada escritor necesita diario y doble fase. |
| Recuperación | No resuelve un estado parcial tras una caída. | Los lectores siguen en la última `COMPLETA`; la recuperación es local y explícita. | La mejor por operación, pero sólo donde se implementó. |
| Compatibilidad | Cambia a todos los lectores, que deben esperar. | Los escritores no cambian; se agrega el cierre del turno. | Toca muchos escritores. |
| Portabilidad CASA/OFICINA | Mala: la marca va por Drive. | Buena: el control y los objetos están en Cloud por empresa. | Neutra. |
| Riesgo para PULL | Alto (esperas). | Costo de capturar en cada cierre (ver §10). | Medio. |

La 2 reutiliza la exclusión que ya existe en lugar de reemplazar locks. De la 3 sólo se toma
el diario de intención donde falta (§5), porque sin él una caída deja estado parcial que nadie
sabe completar.

## 2. Fuentes y escritores que participan

### 2.1 Fuentes

Las del contrato `atlas_core/fuentes_generacion.py` (matriz en `docs/FUENTES_GENERACION.md`):
* identidad (excepto MBT), dataset, ledger, los dos registros de decisiones humanas, bandeja,
  agrupaciones e investigación;
* catálogos con rol, que incluyen las fuentes de la derivación `ASIGNACIONES`;
* evidencia referida por el dataset y sus índices.

Lo que queda en `FUERA_DE_TABLA_V1` no forma parte de la generación hasta que se clasifique.

### 2.2 Escritores gobernados: punto mínimo de participación

Ya corren dentro de un turno. Su única participación nueva es **informar al cierre del turno
si todas sus operaciones terminaron bien** (`exito`). Sin ese dato no se captura.

| Escritor | Turno hoy | Punto de participación |
| --- | --- | --- |
| Decisiones humanas desde la bandeja (`aplicar_decision_obra` vía `aplicar_decision_pendiente.py`) | sesión Desktop | `exito` al cerrar la sesión; además, **diario de intención** (§5), porque hoy no hay recuperación por token. |
| Acciones operacionales (B1, `acciones_operacionales_cli.py`) | sesión Desktop, `escritor_global` | `exito`; ya tienen tokens y `recuperar_*`. |
| Correcciones automáticas, revalidación, reconciliación (`revalidacion_documental`, `reconciliar_estado_derivado`, `mantenimiento_pendientes_tecnicos`) | sesión / lease propio | `exito`. Lo derivado (bandeja) se puede regenerar en la recuperación. |
| PULL (envíos y licencias Mobile) | lease por pasada | `exito` de la pasada. Una pasada parcial queda `PENDIENTE` y no se publica. |
| Ingreso Desktop (`desktop_operacion.ingresar`, incluida la copia de evidencia) | sesión | `exito`. |
| Agrupaciones, investigación, catálogos y asignaciones (vía `gestionar_catalogos.py`, acciones y conversacionales) | sesión Desktop | `exito`. |

**Locks:** no se reemplazan. Mientras se cumpla la regla de capturar después de liberar todos
los locks de operación (§6), no afectan a la frontera.

### 2.3 Escritores NO gobernados o no localizados (identificados expresamente)

| Escritor | Evidencia | Tratamiento propuesto |
| --- | --- | --- |
| **Electron en modo legado** (`operacionDesktop` sin preparar): `fs.copyFileSync` a `operacion/entradas/<marca>` y llamadas directas a Python | `main.js:1382-1395` (sólo lectura) | Contrato Desktop (§7): prohibido en raíces operacionales. |
| **Retomar lote desde Electron** (`retomar_entradas_desktop.py` por `ejecutarPython`) | `main.js` ~1447; `entradas_desktop.py:148` sólo toma `bloqueo_sesion` | Debe ir por `desktop_operacion.ejecutar` (ya figura en `ESCRITORES`). |
| **CLIs ejecutados a mano** fuera de Desktop: `reproceso_cuarentena.py`, `aplicar_decision_pendiente.py`, `gestionar_catalogos.py`, `corregir_fechas_documento.py`, `reprocesar_lote_reparador.py`, entre otros (no abren sesión) | censo de los scripts de la raíz | La guardia los rechazaría en una raíz protegida con `exigir`, **sin verificar en CASA**. Deben exigir la sesión o rechazar (§11, E7). |
| **Cliente Google Drive** (réplica) | `envio-mobile-sin-original` y protocolo 2 | No es un escritor lógico: la generación no depende de él; el protocolo 2 bloquea al escritor cuya copia esté desfasada. |
| `servidor_mobile.py` | no abre sesión | **No localizado:** confirmar si sigue activo. |
| Escritores de `empresas.json`, `plantas.json` y `rutas.json` | sin escritor en `atlas_core` | **No localizados**; probablemente gestión manual. |
| Contenido de `operacion/procesamiento/` y `fichas_digitales/` | en la semilla, no auditado | **No localizado** en detalle. |
| Modo **equipo único** (`EscritorEquipoUnico`) | mutex local, sin Cloud ni PULL | Sin Cloud no hay control ni generaciones: el lector coherente responde `NO_CONFIABLE("SIN_ARBITRO_CLOUD")`. Una variante local queda fuera de esta etapa. |

## 3. Estados y transiciones (por empresa)

Control Cloud propuesto: `control = null | {estado: "PENDIENTE", epoca, titular}` junto al
puntero de generación (`custodia_generacion_actual`) y el lease (`escritores_operativos`).

| Estado | Condición | Lo ve el lector como |
| --- | --- | --- |
| **ESTABLE** | `control = null`, puntero a la generación G | `CONFIABLE`, frescura `ESTABLE` |
| **EN_OPERACION** | `control = PENDIENTE(e, t)` y el lease de la época `e` vigente | `CONFIABLE` de G (anterior), frescura `OPERACION_EN_CURSO` |
| **CAPTURA** | igual que EN_OPERACION; el escritor ya terminó y está capturando | igual |
| **COMPLETA** | CAS: `puntero := G'` y `control := null` en **una sentencia** | `CONFIABLE` de G', `ESTABLE` |
| **INTERRUMPIDA** | `control = PENDIENTE(e, t)` y el lease de `e` ya no está vigente, o hay otra época `e' > e` | `CONFIABLE` de G, frescura `INTERRUMPIDA` |
| **RECUPERANDO** | el titular `t`, con una época nueva `e'`, asumió el control: `PENDIENTE(e', t)` | `CONFIABLE` de G, `OPERACION_EN_CURSO` |
| *(resultado)* **NO_CONFIABLE** | sin generación, descriptor u objeto inválido o ausente, fuente ilegible, sin árbitro Cloud | sin datos |

Transiciones:
1. `adquirir` (turno local, lease `e`, protocolo 2) → si `control = null`, `abrir_frontera` →
   **EN_OPERACION**.
2. Si `control = PENDIENTE(e_prev, t)` y `t` es este equipo → **INTERRUMPIDA** → recuperar (§5)
   → `asumir_recuperacion` → **RECUPERANDO**. Sólo en este caso se omite la verificación
   estricta del protocolo 2: las escrituras parciales están en esta raíz.
3. Si `control = PENDIENTE(e_prev, t)` y `t` es otro equipo → **INTERRUMPIDA_EN_OTRO_EQUIPO**:
   no escribe. Opciones: esperar al titular, o un relevo con **autorización humana explícita**
   que restaura la última COMPLETA y descarta lo parcial no publicado.
4. Operaciones (locks propios) → cierre: con éxito → captura → `publicar` (CAS) →
   **COMPLETA/ESTABLE**; sin cambios → `cerrar_sin_cambios` (CAS) → **ESTABLE**.
5. Fallo, caída o pérdida del lease → el control queda → **INTERRUMPIDA** cuando expira el
   lease.

**CAS de publicación** (extensión de `publicarGeneracion`): exige lease vigente,
`control.epoca = epoca del lease`, generación anterior igual al puntero y objetos verificados.
Si se cumple, en la misma sentencia mueve el puntero y vacía el control. Un escritor de otra
época **no puede** publicar sobre una interrupción sin recuperar
(`SIN_FRONTERA_DE_ESTA_EPOCA`).

## 4. Protocolo de lectura coherente

1. `GET actual`: puntero, descriptor Cloud, hash y **control**. Sin generación →
   `NO_CONFIABLE(SIN_GENERACION_PUBLICADA)`; sin Cloud o en equipo único →
   `NO_CONFIABLE(SIN_ARBITRO_CLOUD)`.
2. Descargar el objeto `_atlas/descriptor_generacion.json` y verificar con
   `verificar_generacion_custodia` (contrato v2). Comprobar `version_contrato`.
3. Para cada fuente: usar la copia local **sólo si su SHA coincide**; si no, descargar por
   empresa y SHA. Si falta → `NO_CONFIABLE(OBJETO_NO_DISPONIBLE)`.
4. Clasificar cada fuente:

   | Clase | Condición |
   | --- | --- |
   | `AUSENTE` | no está en el inventario: el descriptor la rechaza antes |
   | `ILEGIBLE` | no se puede decodificar o parsear → `NO_CONFIABLE(FUENTE_ILEGIBLE)` |
   | `VACIA` | colección legítimamente vacía, declarada en el contenido |
   | `CON_DATOS` | — |

5. La frescura sale del control: `ESTABLE`, `OPERACION_EN_CURSO` o `INTERRUMPIDA`. La
   generación es coherente pero puede ser anterior a la operación en curso. Si el consumidor
   exige el estado vigente, debe rechazar cualquier frescura distinta de `ESTABLE`.
6. Nunca se devuelve una colección vacía en lugar de un error. El lector no toma locks ni el
   lease, así que no bloquea a PULL.

Los lectores actuales que leen archivos vivos siguen igual. Su resultado **no es coherente**
y no debe alimentar previews de lotes ni decisiones (§11, E2).

## 5. Recuperación

| Caída | Estado resultante | Recuperación | Prueba del modelo |
| --- | --- | --- | --- |
| Antes de marcar `PENDIENTE` (lease tomado) | control vacío; el lease expira | nada que recuperar | `test_caida_antes_de_marcar_pendiente` |
| Tras `PENDIENTE`, sin escrituras | `INTERRUMPIDA` | recuperar no reaplica nada; cierre sin cambios | `test_caida_en_cada_punto_y_recuperacion[0]` |
| Entre dos escrituras (acciones, ledger, ventanas del dataset) | `INTERRUMPIDA`; lectores en G | reaplicar **sólo** confirmaciones humanas registradas (token con `confirmacion_recuperable`), de forma idempotente | `[1]`–`[4]` |
| Tras escribir todos los archivos, antes de cerrar | `INTERRUMPIDA` | nada que reaplicar; capturar y publicar | `[5]` |
| Error con el proceso vivo (`exito=False`) | `INTERRUMPIDA` sin esperar a la expiración | igual que una caída | `test_error_a_mitad_de_operacion_no_publica` |
| Tras subir objetos, antes de `COMPLETA` | puntero en G; objetos huérfanos e inocuos | recuperar y publicar | `test_caida_antes_de_completa` |
| Inmediatamente después de `COMPLETA` (lease sin liberar) | `ESTABLE` en G' (puntero y control en el mismo CAS) | ninguna; el lease expira | `test_caida_inmediatamente_despues_de_completa` |
| Pérdida del lease a mitad de operación | el escritor ya no puede escribir ni publicar; otra época ve `INTERRUMPIDA` | titular o relevo autorizado | `test_perdida_de_lease_durante_operacion` |
| Cambio de equipo tras una caída | `INTERRUMPIDA_EN_OTRO_EQUIPO` | esperar al titular, o relevo con autorización humana que **restaura la última COMPLETA** | ídem |
| Cambio normal de equipo (sin caída) | protocolo 2: `ESTADO_NO_VERIFICADO` mientras Drive no sincroniza; después escribe sin intervención | ninguna | `test_competencia_casa_oficina_y_replica_desfasada` |

Reglas:
* La recuperación **nunca convierte una decisión pendiente en confirmación**. Un preview sin
  confirmar queda como preview (`test_preview_no_confirmado_nunca_se_confirma_al_recuperar`).
* Sólo se reaplica una confirmación humana ya registrada antes de la caída. Ese es el patrón
  `confirmacion_recuperable` y `recuperar_*` de `acciones_operacionales`.
* `aplicar_decision_obra` no tiene diario equivalente: su recuperación necesita uno (E4).
  Hasta entonces, una interrupción durante ella exige revisión humana antes de publicar.

## 6. Locks y leases

* **No se reemplaza ningún lock.** La frontera global es el **turno** que ya existe (turno
  local + lease); los locks por recurso siguen protegiendo dentro del turno.
* **Orden:** el turno se toma primero (como hoy); la frontera se abre después de `vincular_raiz`.
  La captura ocurre **después de liberar todos los locks de operación** y antes de soltar el
  lease. Así no hay anidamiento nuevo ni posibilidad de deadlock con `revalidacion_dataset`
  (no reentrante).
* **Lectores:** no toman locks ni el lease.
* **Heartbeat:** la captura debe completarse con el lease vigente. Si se pierde, el CAS Cloud
  la rechaza. Una captura larga debe renovar el lease (hoy lo hace el hilo de heartbeat).
* **Locks huérfanos (6 h):** no inciden en la coherencia, que depende del control y no de los
  archivos de lock. `recuperar_bloqueos_huerfanos` sigue bajo lease, como hoy.
* **PULL:** la pasada es un turno. Se publica al final de una pasada exitosa; una pasada sin
  cambios cierra con «sin cambios». No se agregan esperas a PULL.

## 7. Coordinación con Desktop (contrato; Desktop no se modifica ahora)

1. Desktop **sólo** escribe en una raíz operacional mediante `desktop_operacion.ejecutar` con
   la operación preparada. El modo legado (`fs.copyFileSync` a `operacion/entradas`) queda
   prohibido en raíces operacionales.
2. «Retomar lote» se invoca por `desktop_operacion.ejecutar` (script `retomar_entradas_desktop.py`,
   ya en `ESCRITORES`), no por `ejecutarPython` directo.
3. Cada invocación devuelve su resultado, que ya incluye el error: el cierre del turno lo usa
   como `exito`.
4. Las vistas que deban ser coherentes (previews, conteos para decisiones) consumen el lector
   de generación del Motor (§4) y muestran la frescura. La vista de archivos vivos se rotula
   como no coherente.
5. Desktop no lee ni interpreta el control Cloud por su cuenta.

## 8. Compatibilidad con el descriptor v2

* La captura usa exactamente el contrato `fuentes_generacion` y `construir_descriptor` v2:
  * los dos registros humanos con rol;
  * la derivación `ASIGNACIONES` sin objeto propio;
  * evidencia con `evidencia/<sha256(documento)>/<rol>/<sha256 contenido>`.

  El modelo lo ejerce con el código real.
* Identidad de generación propuesta:
  * `generacion_id` único (p. ej. `g-<epoca>-<n>`);
  * `previa_id` = puntero vigente (coincide con el `anterior_id` del CAS Cloud);
  * `secuencia` = la previa + 1.
* No hace falta cambiar el descriptor. El estado de publicación nunca entra en él (sigue
  `PENDIENTE_PROTOCOLO_OFICIAL`).

## 9. Relación con la custodia Cloud

**Reutiliza** (61c2872): objetos por empresa y SHA, `preparar` y `publicar` con CAS sobre el
puntero, `actual`.

**Requiere de Codex** (no implementado):
1. **Control por empresa** `PENDIENTE(epoca, titular)`:
   * `abrir_frontera(lease_token)`: no sobrescribe una época anterior y devuelve `INTERRUMPIDA`
     con su titular;
   * `asumir_recuperacion(lease_token)`;
   * `cerrar_sin_cambios(lease_token)`.

   `titular` puede ser el `escritor_id` que ya se envía al adquirir.
2. **`publicar`** exige además `control.epoca = epoca del lease` y vacía el control en la misma
   sentencia.
3. **`GET actual`** devuelve el control y si el lease del titular está vigente.
4. Retención de objetos y descriptores, límite de 1000 objetos e inventario por partes (ya
   documentados en 57e5173).

La custodia actual (`estado_confirmado`, lotes de 50 al cerrar) **se mantiene** para alinear y
restaurar la copia local. Los lectores coherentes no la usan: sus versiones intermedias no son
generaciones.

## 10. Riesgos y garantías

**Demostrado sólo en el modelo** (32 pruebas; 10 reglas del protocolo: quitar cualquiera hace
fallar alguna prueba):
* no se publica una mezcla tras una caída en cualquier punto ni tras un error;
* los lectores ven siempre la última COMPLETA verificada, también con réplica desfasada o
  desordenada;
* una interrupción sin recuperar no se puede tapar publicando;
* la recuperación no confirma previews;
* el relevo entre equipos exige autorización;
* las empresas están separadas;
* `AUSENTE`, `ILEGIBLE` y `VACIA` se distinguen, y la evidencia referida que falta no se omite.

**Límite demostrado** (`test_limite_escritor_no_gobernado_detenido_no_se_detecta`): la doble
pasada **no** detecta a un escritor no gobernado que se detiene a mitad de operación, y se
publica una mezcla. **La seguridad depende de que todo escritor participe del turno (§2.3);
no se puede compensar detectando.**

**No demostrado (pendiente):**
* semántica real de transacciones D1 y retención R2;
* cobertura real de la guardia en CASA (`exigir` sobre G:);
* comportamiento del heartbeat durante capturas largas;
* atomicidad de las escrituras de Drive y de `escribir_json_atomico` sobre G:;
* costo de capturar en cada cierre de turno PULL (hashear la evidencia), que necesita caché
  de huellas o captura incremental y medición;
* reglas de evidencia `PURGADA` y de movimiento a `evidencia_resuelta`;
* el diario de `aplicar_decision_obra`;
* el modo equipo único;
* los escritores no localizados (§2.3).

**Riesgos:**
* el crecimiento de generaciones (una por turno con cambios) exige una política de retención;
* el relevo autorizado descarta trabajo parcial no publicado, aunque nunca lo publica a medias;
* mientras haya escritores no gobernados, ninguna generación es una garantía.

## 11. Etapas mínimas de implementación (por componente)

| Etapa | Componente | Contenido | Depende de |
| --- | --- | --- | --- |
| E0 | Decisión | Aprobar este diseño; Codex revisa §9. | — |
| E1 | Cloud (Codex) | Control `PENDIENTE` y sus endpoints, `publicar` condicionado, control en `actual`, pruebas D1/R2 reales, retención y límite. | E0 |
| E2 | Motor, lector | Lector de generación estricto (`CONFIABLE`/`NO_CONFIABLE`, clasificación, frescura), sin tocar escritores. Lo adopta el preview de lotes. | E1 |
| E3 | Motor, cierre del turno | Abrir la frontera en `LeaseEscritorOperativo` tras `vincular_raiz`; captura y publicación al cerrar **sólo con `exito`**. Puntos: `desktop_operacion.sesion`, `ejecutar_pull_con_escritor` y los CLIs con lease. | E1, E2 |
| E4 | Motor, recuperación | `INTERRUMPIDA` al adquirir; diario de intención para `aplicar_decision_obra` (patrón token); relevo autorizado entre equipos. | E3 |
| E5 | Desktop | Eliminar el modo legado en raíces operacionales; «retomar lote» por `ejecutar`; vistas coherentes con frescura. | E2 |
| E6 | Evidencia | Binarios a custodia, reglas de purga y resolución coordinadas con la frontera, límite Cloud. | E1, E3 |
| E7 | Escritores no gobernados | CLIs manuales: exigir sesión o rechazar; verificar la guardia `exigir` en CASA; localizar los escritores de §2.3. | E0 |

Cada etapa se instala por separado y con reversión. Hasta E3, ninguna generación refleja la
operación real. Hasta E5 y E7, la garantía queda condicionada a que no haya escritores fuera
del turno.
