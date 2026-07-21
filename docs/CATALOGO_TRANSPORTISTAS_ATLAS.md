# Catálogo Maestro de Empresas Transportistas — Atlas

## 1. Propósito y alcance

Una empresa transportista representa a una persona jurídica o persona natural responsable de operar, prestar o asumir operacionalmente el servicio de transporte asociado a uno o más viajes. Para una persona natural, `razon_social` puede contener el nombre legal confirmado. Su identidad debe ser estable aunque cambien su razón social visible, nombre comercial, personal, vehículos o relaciones operacionales.

El catálogo permitirá responder en etapas posteriores:

- qué transportista realizó o tuvo responsabilidad operacional en un viaje;
- qué choferes prestaron servicios para cada transportista durante un período;
- qué tractos y ramplas administró, operó o utilizó durante un período;
- cuántos viajes realizó y qué peso transportó;
- cuántos kilómetros acumuló sobre viajes y rutas confirmados;
- qué plantas, clientes y destinos atendió.

Este documento diseña exclusivamente la identidad de empresas transportistas. No implementa catálogos de choferes o vehículos, asignaciones, viajes, integraciones, costos, productividad ni interfaces.

## 2. Separación de conceptos

Atlas debe mantener entidades diferentes incluso cuando un nombre aparezca en más de un rol.

| Entidad | Representa | Ejemplo sintético |
|---|---|---|
| Empresa transportista | Responsable u operador del servicio de transporte | `TRANSPORTES DEMO NORTE` |
| Cliente | Entidad comercial que encarga, compra o recibe una operación | `CLIENTE DEMO CENTRAL` |
| Planta | Punto físico de origen de la carga | `PLANTA DEMO ORIGEN` |
| Destino | Punto físico donde se entrega la carga | `CENTRO DEMO DESTINO` |
| Destinatario o receptor | Empresa o persona que recibe material en un viaje particular | `RECEPTOR DEMO` |

Un transportista puede también ser cliente en otro contexto, pero eso no autoriza a reutilizar automáticamente el mismo registro ni a fusionar ambos catálogos. La equivalencia jurídica futura debe representarse mediante una relación explícita entre identidades, con evidencia y vigencia.

El transportista tampoco es sinónimo de propietario del vehículo, empleador del chofer o destinatario. Esas relaciones pueden ser temporales, contractuales o desconocidas.

## 3. Modelo de datos propuesto

Ubicación privada futura:

```text
catalogos/transportistas.json
```

Raíz versionada propuesta:

```json
{
  "version_formato": 1,
  "transportistas": []
}
```

### 3.1 Campos

| Campo | Tipo | Obligatorio | Nulabilidad | Regla principal |
|---|---|---:|---:|---|
| `transportista_id` | UUID como texto | Sí | No | Único, inmutable y sin significado operacional |
| `razon_social` | texto UTF-8 | Sí | No | Conserva el texto original del valor vigente, sea propuesto o confirmado según `estado_calidad` |
| `fuente_razon_social` | texto/código | Sí | No | Conserva la procedencia del valor vigente; no implica por sí sola que la identidad esté confirmada |
| `fecha_confirmacion_razon_social` | fecha-hora ISO 8601 | No | Sí, representado como vacío | Instante UTC en que Atlas confirmó la denominación vigente; depende del estado de calidad y no implica la fecha legal del cambio |
| `nombre_normalizado` | texto derivado | Sí | No | Se calcula determinísticamente desde `razon_social`; no es editable |
| `nombre_comercial` | texto | No | Sí, representado como vacío | No participa por sí solo en fusiones |
| `rut` | texto canónico protegido | No | Sí, representado como vacío | Nunca numérico; validado y canonizado cuando exista |
| `aliases` | lista de objetos confirmados | No | No; lista vacía permitida | Cada objeto conserva identidad, vigencia, procedencia y fechas propias; su normalización es derivada |
| `pais` | código ISO 3166-1 alpha-2 | Sí | No | Inicialmente `CL` para Chile |
| `estado_calidad` | enumeración | Sí | No | `PENDIENTE`, `CONFIRMADO` o `REQUIERE_REVISION` |
| `estado_vigencia` | enumeración | Sí | No | Estado actual `ACTIVO` o `INACTIVO`; no reemplaza un historial |
| `fuente` | texto/código | Sí | No | Procedencia que sustenta creación o última validación |
| `observacion` | texto | No | Sí, representado como vacío | Nunca es criterio automático de identidad |
| `fecha_creacion` | fecha-hora ISO 8601 | Sí | No | Instante UTC con desplazamiento `+00:00` |
| `fecha_modificacion` | fecha-hora ISO 8601 | Sí | No | UTC; igual o posterior a creación y cambia con toda modificación |

### 3.2 Ejemplo sintético conceptual

```json
{
  "transportista_id": "00000000-0000-4000-8000-000000000001",
  "razon_social": "TRANSPORTES DEMOSTRACION DEL SUR SPA",
  "fuente_razon_social": "PLANTILLA_SINTETICA",
  "fecha_confirmacion_razon_social": "",
  "nombre_normalizado": "TRANSPORTES DEMOSTRACION DEL SUR SPA",
  "nombre_comercial": "FLOTA DEMO SUR",
  "rut": "",
  "aliases": [],
  "pais": "CL",
  "estado_calidad": "PENDIENTE",
  "estado_vigencia": "ACTIVO",
  "fuente": "PLANTILLA_SINTETICA",
  "observacion": "Registro ficticio sin relación con una empresa real",
  "fecha_creacion": "2026-01-01T00:00:00+00:00",
  "fecha_modificacion": "2026-01-01T00:00:00+00:00"
}
```

El ejemplo omite deliberadamente un RUT. La documentación, plantillas y pruebas públicas no deben incorporar identificadores tributarios completos, aunque sean presentados como ejemplos.

### 3.3 Ejemplo sintético de objeto alias confirmado

```json
{
  "alias_id": "00000000-0000-4000-8000-000000000002",
  "valor": "TRANSPORTE DEMO SUR",
  "tipo": "ALIAS",
  "estado_vigencia": "ACTIVO",
  "fuente": "PLANTILLA_SINTETICA",
  "observacion": "Alias sintético confirmado",
  "fecha_confirmacion_valor": "2026-01-01T00:00:00+00:00",
  "fecha_creacion": "2026-01-01T00:00:00+00:00",
  "fecha_modificacion": "2026-01-01T00:00:00+00:00"
}
```

Este objeto es completamente sintético, representa un alias ya confirmado y pertenecería conceptualmente a un transportista confirmado. No forma parte del registro `PENDIENTE` mostrado anteriormente y no contiene datos privados.

## 4. Estados

### 4.1 Calidad

| Estado | Significado | Uso permitido |
|---|---|---|
| `PENDIENTE` | Propuesta con evidencia insuficiente o no revisada | Bandeja de revisión; no asociación oficial automática |
| `CONFIRMADO` | Identidad revisada manualmente o proveniente de fuente autorizada | Asociaciones exactas y reportes según cobertura |
| `REQUIERE_REVISION` | Existe ambigüedad, contradicción o cambio sensible pendiente | Abstención hasta resolución |

### 4.2 Vigencia

| Estado | Significado |
|---|---|
| `ACTIVO` | Puede participar en nuevas asociaciones confirmadas |
| `INACTIVO` | Se conserva para historia, pero no se propone para nuevas operaciones |

Calidad y vigencia son independientes. Un transportista puede estar confirmado e inactivo, preservando todos sus viajes históricos.

La confirmación de la razón social se determina conjuntamente mediante `estado_calidad` y `fecha_confirmacion_razon_social`. En `PENDIENTE`, la fecha está vacía; en `CONFIRMADO`, está informada; en `REQUIERE_REVISION`, conserva la fecha si la razón social actual había sido confirmada anteriormente y permanece vacía si la propuesta nunca fue confirmada. `fuente_razon_social` siempre permanece informada porque representa la procedencia del valor actual, no una confirmación automática.

### 4.3 Transiciones permitidas

| Transición | Condición |
|---|---|
| `PENDIENTE` → `CONFIRMADO` | Decisión humana autorizada con evidencia suficiente; completa `fecha_confirmacion_razon_social` con una fecha-hora ISO 8601 UTC |
| `PENDIENTE` → `REQUIERE_REVISION` | Revisión iniciada pero no resuelta, ambigüedad o conflicto |
| `CONFIRMADO` → `REQUIERE_REVISION` | Decisión humana explícita ante un conflicto que requiere análisis; conserva los valores confirmados |
| `REQUIERE_REVISION` → `CONFIRMADO` | Conflicto resuelto con evidencia y decisión humana autorizada |
| `REQUIERE_REVISION` → `PENDIENTE` | La contradicción fue descartada, pero todavía no existe evidencia suficiente para confirmar |
| `ACTIVO` → `INACTIVO` | Desactivación humana explícita sin eliminación física |
| `INACTIVO` → `ACTIVO` | Reactivación explícita del mismo `transportista_id` |

Una observación automática solo puede crear una propuesta o alerta separada. Aunque sea contradictoria, no cambia por sí misma un transportista maestro `CONFIRMADO` a `REQUIERE_REVISION` ni ejecuta otra transición de calidad. Solo una decisión humana explícita puede cambiar el estado de calidad del registro maestro. Un transportista inactivo continúa disponible para consultas y asociaciones históricas; su estado actual no invalida viajes antiguos.

## 5. Identidad, normalización y duplicados

### 5.1 Identidad estable

1. `transportista_id` se genera como UUID y no se deriva de nombre, RUT, código externo o fuente.
2. Cambiar la razón social, nombre comercial o alias no cambia el UUID.
3. Un UUID nunca se reutiliza, incluso si el registro queda inactivo.
4. Toda relación futura referencia el UUID, no el texto observado.
5. `fuente_razon_social` conserva la procedencia del valor vigente. `fecha_confirmacion_razon_social`, cuando está informada, registra en UTC cuándo Atlas confirmó esa denominación. Esta fecha no representa la fecha legal del cambio societario, salvo que una futura fuente autorizada lo informe expresamente.
6. Cambios ajenos a la razón social no reemplazan `fuente_razon_social` ni `fecha_confirmacion_razon_social`; `fecha_modificacion` continúa representando la última modificación general del registro.
7. Si cambia una razón social confirmada, se mantiene `transportista_id`, la nueva pasa a ser la vigente y la anterior se conserva en `aliases` como objeto `RAZON_SOCIAL_ANTERIOR` con la fuente y `fecha_confirmacion_valor` tomada de la `fecha_confirmacion_razon_social` que tenía esa denominación.
8. La nueva razón social recibe su propia `fuente_razon_social` y `fecha_confirmacion_razon_social`; el cambio requiere acción humana explícita.

### 5.2 Conservación y normalización

- `razon_social` y el `valor` de cada alias conservan el texto original autorizado.
- `nombre_normalizado` se calcula determinísticamente desde `razon_social`, no se edita manualmente y se valida nuevamente al cargar el catálogo.
- `nombre_normalizado` no es una segunda fuente de verdad: cualquier discrepancia con `razon_social` hace que el archivo sea inválido.
- Cada alias incorporado al arreglo es una denominación confirmada. Una denominación solamente propuesta no se incorpora como alias activo.
- Cada alias contiene, como mínimo, `alias_id`, `valor`, `tipo`, `estado_vigencia`, `fuente`, `observacion`, `fecha_confirmacion_valor`, `fecha_creacion` y `fecha_modificacion`. `alias_id` es un UUID estable, único e inmutable.
- `estado_vigencia` admite `ACTIVO` e `INACTIVO`. La desactivación requiere acción humana explícita y no existe eliminación física de alias confirmados.
- `observacion` es opcional y nunca constituye criterio automático de identidad. `fecha_confirmacion_valor` es obligatoria, usa ISO 8601 UTC y representa cuándo Atlas confirmó el valor, no necesariamente cuándo se creó el objeto alias.
- `fecha_confirmacion_valor` debe ser anterior o igual a `fecha_creacion`; ambas pueden coincidir cuando el valor se confirma y el objeto se crea en el mismo momento. `fecha_creacion` representa la creación del objeto y `fecha_modificacion` su última modificación, siempre igual o posterior a `fecha_creacion`.
- Los tipos conceptuales iniciales son `ALIAS`, `RAZON_SOCIAL_ANTERIOR` y `NOMBRE_COMERCIAL_ANTERIOR`. La enumeración puede ampliarse, pero todo nuevo tipo requiere autorización y documentación.
- La clave normalizada del `valor` de un alias es derivada, no editable y validada al cargar, se almacene o se calcule durante la consulta.
- La normalización puede uniformar mayúsculas, diacríticos, puntuación y espacios bajo reglas documentadas. En sufijos societarios puede normalizar conservadoramente su puntuación, por ejemplo `S.P.A.` → `SPA` y `L.T.D.A.` → `LTDA`.
- La normalización nunca elimina un sufijo societario, lo ignora como palabra irrelevante ni convierte empresas con tipos societarios distintos en una misma identidad.
- No se usa coincidencia parcial, distancia de edición ni similitud fonética para seleccionar automáticamente una empresa.
- Los resultados aproximados pueden presentarse como propuestas, nunca como asociaciones.

### 5.3 RUT

- Es opcional porque una fuente inicial puede no proporcionarlo.
- Cuando existe, se valida estructura y dígito verificador y se guarda en forma canónica privada.
- No forma parte del UUID.
- Un RUT canónico confirmado pertenece a un único `transportista_id` dentro del catálogo, sin importar si el registro está `ACTIVO` o `INACTIVO`.
- Si una empresa inactiva vuelve a operar, se reactiva el mismo registro; no se crea otro transportista con su RUT.
- Una futura excepción requeriría una migración o corrección explícita, justificada y auditada.
- Un conflicto de RUT bloquea creación o modificación y produce revisión; no fusiona registros automáticamente.
- CLI, logs y reportes generales deben mostrarlo redactado o protegido.

### 5.4 Razones sociales, nombre comercial y alias

- La unicidad y detección de colisiones se aplican dentro del ámbito del catálogo operacional actual. Esto no impone unicidad entre futuras organizaciones SaaS independientes.
- No se implementa todavía `tenant_id` ni infraestructura multiempresa.
- Las búsquedas comparan la clave consultada con razón social, nombre comercial y el `valor` normalizado de todos los alias, tanto `ACTIVO` como `INACTIVO`, para detectar candidatos y colisiones exactas. Solo identificadores vigentes y elegibles pueden proponer asociación; una coincidencia exacta con un alias `INACTIVO` produce revisión, nunca asociación automática.
- Razones sociales y alias no deben producir identidades contradictorias dentro del catálogo actual.
- Un alias no puede duplicar la razón social del mismo registro.
- Nombre comercial compartido no prueba identidad.
- Cero `transportista_id` candidatos produce una propuesta `PENDIENTE`.
- Un candidato único solo permite proponer una asociación si está `CONFIRMADO` y `ACTIVO`; los demás estados se resuelven conforme a la matriz de búsqueda.
- Más de un `transportista_id` candidato produce resultado `AMBIGUA` y abstención.
- Varias coincidencias —por ejemplo razón social y alias— pertenecientes al mismo `transportista_id` siguen constituyendo una única coincidencia.

## 6. Reglas de integridad y gobierno

1. El UUID es estable e independiente del nombre.
2. Una edición de razón social conserva el UUID y la fecha de creación.
3. El RUT es opcional, pero siempre validado cuando se informa.
4. Un RUT confirmado no puede pertenecer a dos `transportista_id`, estén activos o inactivos.
5. Nunca se fusionan identidades por similitud aproximada.
6. Las colisiones de razón social, nombre comercial y alias se resuelven dentro del catálogo operacional actual.
7. Una coincidencia ambigua produce abstención y revisión.
8. Un registro `CONFIRMADO` solo puede editarse, desactivarse o recibir alias mediante confirmación manual explícita.
9. No existe eliminación física; se usa `INACTIVO`.
10. Siempre se conserva el texto original y la evidencia de observación fuera del valor canónico.
11. Toda modificación actualiza `fecha_modificacion`.
12. Una observación automática nunca modifica campos de un registro confirmado.
13. Choferes y vehículos no se asignan sin evidencia específica.
14. Las relaciones futuras permiten vigencia temporal y fuente.
15. Un archivo corrupto produce error visible y nunca se reemplaza silenciosamente por un catálogo vacío.
16. Las escrituras futuras deben usar temporal, sincronización y reemplazo atómico.
17. Las modificaciones sensibles deben registrar motivo y actor cuando exista gestión de usuarios.
18. Un cambio de razón social confirmada conserva el nombre anterior y su procedencia como alias histórico o futuro evento de historial.
19. `nombre_normalizado` y cualquier clave normalizada de alias son derivados verificables, nunca campos editables independientes.
20. Todo alias tiene UUID estable y vigencia propia; desactivarlo exige acción humana y no lo elimina físicamente.
21. Solo alias activos son elegibles para asociaciones automáticas; los inactivos se conservan para trazabilidad y sus coincidencias requieren revisión.
22. La procedencia y fecha de confirmación de la razón social vigente solo cambian junto con una modificación humana explícita de esa razón social.
23. `fecha_confirmacion_razon_social` está vacía en pendientes, informada en confirmados y se conserva condicionalmente en revisión según si el valor actual fue confirmado.
24. Cada alias confirmado conserva `fecha_confirmacion_valor` separada de sus fechas de creación y modificación.
25. Los alias inactivos participan en la detección de candidatos y colisiones, nunca se reactivan automáticamente y nunca son elegibles por sí solos para asociación automática.

## 7. Búsqueda y abstención

Las búsquedas consideran razón social, nombre comercial, alias `ACTIVO` y alias `INACTIVO` de registros de todos los estados de calidad y vigencia para detectar candidatos, duplicados y colisiones exactas, aunque no todos los identificadores sean elegibles para nuevas asociaciones. Primero se determina el conjunto de `transportista_id` candidatos y luego se evalúa la elegibilidad. Resultado conceptual:

| Resultado | Condición | Acción |
|---|---|---|
| `COINCIDENCIA` | Candidato único `CONFIRMADO` y `ACTIVO` | Puede proponerse la asociación según la política de la fuente |
| `REQUIERE_REACTIVACION` | Candidato único `CONFIRMADO` e `INACTIVO` | Abstenerse para operaciones nuevas y proponer revisión o reactivación explícita del mismo UUID |
| `PROPUESTA_EXISTENTE` | Candidato único `PENDIENTE` | Identificar y reutilizar la propuesta existente; no duplicar el registro ni realizar asociación oficial |
| `EN_REVISION` | Candidato único `REQUIERE_REVISION` | Abstenerse hasta que una persona autorizada resuelva el registro |
| `AMBIGUA` | Las coincidencias exactas apuntan a más de un `transportista_id`, aunque alguna provenga de un alias `INACTIVO` | Abstenerse y solicitar revisión; ninguna coincidencia activa se impone sobre la colisión |
| `SIN_COINCIDENCIA` | Ninguna razón social, nombre comercial o alias exacto produce candidato | Crear una propuesta `PENDIENTE`, sin alterar catálogos confirmados |

Los registros inactivos pueden aparecer como evidencia histórica, pero no se seleccionan para viajes nuevos sin reactivación explícita.

El conteo se realiza por `transportista_id`, no por número de campos coincidentes. Si todas las coincidencias apuntan al mismo `transportista_id`, se contabiliza un solo candidato; que razón social, nombre comercial y uno o más alias coincidan con ese registro no transforma el resultado en ambiguo.

Si el único identificador coincidente es un alias `INACTIVO`, Atlas conserva la trazabilidad, se abstiene y solicita revisión; nunca reactiva el alias automáticamente. Una coincidencia activa de un transportista no puede ignorar una colisión exacta con un alias inactivo de otro transportista: existen dos candidatos y el resultado es `AMBIGUA`.

## 8. Relaciones futuras

El catálogo de Transportistas representa identidad empresarial. Las pertenencias y operaciones se modelan en tablas o catálogos relacionales separados.

### 8.1 Choferes

```text
transportista_chofer
- relacion_id
- transportista_id
- chofer_id
- tipo_relacion
- fecha_desde
- fecha_hasta
- estado
- fuente
- observacion
- fecha_creacion
- fecha_modificacion
```

`tipo_relacion` podrá distinguir empleo, prestación de servicios u otra categoría autorizada. Dos períodos no pueden solaparse de forma contradictoria para la misma relación, pero un chofer puede prestar servicios a distintas empresas en períodos diferentes o incluso simultáneos cuando la evidencia lo permita.

### 8.2 Tractos y ramplas

```text
transportista_vehiculo
- relacion_id
- transportista_id
- vehiculo_id
- rol_empresa
- fecha_desde
- fecha_hasta
- estado
- fuente
- observacion
- fecha_creacion
- fecha_modificacion
```

`rol_empresa` podrá diferenciar propietario, operador, administrador o contratante. Tracto y rampla son vehículos distintos; compartir un viaje no implica propiedad común ni relación permanente.

### 8.3 Viajes

El catálogo actual solo implementará la identidad de empresas transportistas. Antes de integrar con Viajes se diseñarán los roles y una relación separada conceptual, sin fijar todavía una enumeración definitiva:

```text
viaje_transportista
- viaje_id
- transportista_id
- rol_transportista
- estado
- fuente
- evidencia
```

Una misma empresa puede cumplir más de un rol y empresas distintas pueden cumplir roles diferentes en un mismo viaje, por ejemplo responsabilidad contractual y ejecución operacional. Atlas no inferirá esos roles desde choferes, patentes o nombres aislados. Esta relación no se implementa en la etapa actual.

El texto de empresa transportista observado en una guía es evidencia documental, no una asociación operacional independiente. Las guías se agrupan primero conforme al contrato de Viajes; el transportista confirmado se asocia al `viaje_id` resultante.

Si las guías agrupadas en un mismo viaje entregan transportistas incompatibles, Atlas:

1. se abstiene de asignar un transportista;
2. marca el viaje o la asociación como `REQUIERE_REVISION`;
3. conserva cada observación documental y su fuente;
4. no elige arbitrariamente una empresa;
5. no duplica el viaje para ocultar el conflicto.

Los indicadores se calculan desde viajes confirmados y atribuyen viajes, peso y kilómetros según un `rol_transportista` seleccionado explícitamente. Un mismo viaje no se duplica ni se cuenta varias veces dentro de una misma métrica y rol:

- viajes por transportista: conteo de `viaje_id`, no documentos;
- peso por transportista: suma de pesos validados sin duplicar guías;
- kilómetros por transportista: suma de una distancia vigente por viaje;
- cobertura operacional: relaciones observadas con plantas, clientes y destinos.

### 8.4 Plantas, clientes y destinos

No se propone una pertenencia directa permanente. La atención de una planta, cliente o destino se deriva de viajes confirmados o de contratos futuros con vigencia explícita. Una aparición aislada no crea una relación maestra.

### 8.5 Integridad temporal

- `fecha_desde` es obligatoria para una relación confirmada.
- `fecha_hasta` es nullable y representa vigencia abierta.
- `fecha_hasta` nunca puede preceder a `fecha_desde`.
- Cerrar un vínculo conserva el período histórico.
- Corregir un período genera auditoría; no reescribe evidencia de viajes anteriores.
- Una relación vigente hoy no debe proyectarse retrospectivamente a viajes antiguos.

## 9. Aprendizaje gobernado

Flujo futuro:

```text
OCR o fuente operacional observa un nombre empresarial
↓
Atlas conserva el texto original y genera una clave normalizada
↓
Busca razón social, nombre comercial o alias exacto
↓
Coincidencia única: resuelve según calidad, vigencia y elegibilidad
↓
Sin coincidencia: crea una propuesta PENDIENTE
↓
Coincidencia ambigua: se abstiene y marca REQUIERE_REVISION
↓
Una persona autorizada confirma, rechaza o corrige
↓
La razón social o alias confirmado beneficia viajes futuros
```

La observación automática debe conservar fuente, valor original, fecha y contexto. Puede proponer un alias nuevo o una posible corrección, pero nunca agregarlo ni modificar una empresa `CONFIRMADO` sin una operación manual explícita.

La coincidencia única se resuelve conforme a las reglas de Búsqueda y abstención: un registro `CONFIRMADO` y `ACTIVO`, sin colisiones, puede proponer asociación según la política de la fuente; un `CONFIRMADO` e `INACTIVO` requiere revisión o reactivación; un `PENDIENTE` devuelve `PROPUESTA_EXISTENTE`; y un `REQUIERE_REVISION` produce abstención. Cualquier colisión entre distintos `transportista_id` produce `AMBIGUA`, y una coincidencia mediante alias inactivo nunca habilita asociación automática.

Cuando la búsqueda encuentra un único transportista `PENDIENTE`, devuelve `PROPUESTA_EXISTENTE`, identifica y reutiliza esa misma propuesta, no crea otro transportista y no realiza una asociación oficial. Tampoco sobrescribe `fuente` u `observacion` del transportista para acumular observaciones repetidas, pues destruiría su procedencia original.

El almacenamiento acumulativo de nuevas observaciones pertenecerá a futuras estructuras independientes, conceptualmente `propuesta_transportista` y `evidencia_transportista`. Esas estructuras no se diseñan ni implementan en la primera etapa. Hasta que existan, la búsqueda solo identifica y reutiliza la propuesta existente sin destruir ni reemplazar su procedencia original.

Una corrección no modifica retroactivamente el texto extraído de documentos. Los viajes conservan trazabilidad hasta la observación original y la versión de la decisión utilizada.

## 10. Privacidad y publicación

El futuro archivo real `catalogos/transportistas.json` contendrá datos empresariales privados y debe permanecer ignorado por Git. No debe crearse hasta recibir autorización de implementación y carga.

La futura plantilla pública será:

```text
catalogos/templates/transportistas_ejemplo.json
```

Reglas de publicación:

- solo nombres, direcciones e identificadores inequívocamente sintéticos;
- ningún RUT completo en plantillas, documentación o pruebas;
- ningún UUID privado;
- ninguna ruta absoluta local;
- ninguna copia parcial del catálogo real;
- ningún `alias_id` ni dato de procedencia perteneciente al catálogo privado;
- fuentes de prueba como `PLANTILLA_SINTETICA` o `PRUEBA_SINTETICA`;
- pruebas con archivos temporales, nunca sobre el catálogo operacional.

El RUT empresarial se almacena solo en el catálogo privado. La CLI debe ocultarlo en listados y vistas generales. Exportaciones posteriores deben aplicar minimización y permisos.

## 11. Implementación gradual

### Etapa 1 — Infraestructura del catálogo

Implementar modelo, validación de RUT, búsqueda exacta, alias, protección de confirmados, vigencia, persistencia atómica, CLI, plantilla y pruebas sintéticas.

Utilizable para crear y revisar registros DEMO en rutas temporales. No contiene empresas reales ni se integra con viajes.

### Etapa 2 — Carga manual confirmada

Crear el catálogo privado y cargar únicamente transportistas reales autorizados, verificando identidad, RUT y duplicados antes de cada alta.

Utilizable como fuente maestra manual y para búsquedas controladas. Aún no asigna choferes, vehículos o viajes.

### Etapa 3 — Catálogo de Choferes

Implementar identidades personales protegidas por separado. No incluir una empresa fija dentro de la identidad del chofer.

Utilizable para reconocer personas, todavía sin asumir vínculos empresariales permanentes.

### Etapa 4 — Vehículos y Ramplas

Implementar tractos y ramplas como activos distintos, con patentes validadas y sin propietario u operador inferido.

Utilizable para reconocer vehículos y roles en documentos o viajes.

### Etapa 5 — Relaciones temporales

Implementar `transportista_chofer` y `transportista_vehiculo`, períodos, fuentes, conflictos y auditoría.

Utilizable para responder quién prestaba servicios u operaba un activo en una fecha determinada.

### Etapa 6 — Viajes y reportes

Diseñar definitivamente los roles autorizados e implementar la relación `viaje_transportista` para asociar transportistas a viajes mediante roles explícitos y evidencia suficiente. Construir métricas atribuidas por rol, evitando el doble conteo de un mismo viaje dentro de una misma métrica y rol, sin cerrar anticipadamente la enumeración de roles.

Utilizable para indicadores operacionales con denominadores, cobertura, exclusiones y trazabilidad explícitos.

## 12. Riesgos

| Riesgo | Consecuencia | Mitigación propuesta |
|---|---|---|
| Nombre compartido o genérico | Asociación a empresa incorrecta | Búsqueda exacta, RUT cuando exista y abstención ambigua |
| Cambio de razón social | Fragmentación histórica | UUID estable, nombre anterior conservado y edición humana explícita |
| Empresas relacionadas jurídicamente | Fusión indebida | Identidades separadas y relación explícita futura |
| Transportista confundido con cliente | Métricas comerciales y logísticas mezcladas | Catálogos y roles separados |
| Patente o chofer usado como prueba única | Pertenencia inventada | Relaciones con evidencia, fuente y vigencia |
| RUT expuesto | Filtración empresarial | Catálogo privado, redacción de CLI y ausencia en artefactos públicos |
| Alias automático incorrecto | Errores repetidos en viajes futuros | Confirmación manual para registros confirmados |
| Períodos solapados | Responsabilidad operacional contradictoria | Validación temporal y estado de conflicto |
| Datos históricos reescritos | Indicadores no reproducibles | Relaciones versionadas y trazabilidad por viaje |
| Conteo por documento | Viajes, peso y kilómetros duplicados | Indicadores basados en `viaje_id` confirmado |

## 13. Criterios de aceptación para implementar

- El catálogo es independiente de Clientes, Plantas, Destinos, OCR y producción.
- El archivo inexistente representa un catálogo vacío y no se crea al listar.
- La primera escritura es atómica y nunca destruye un archivo válido ante fallo.
- UUID estable y único; cambios de nombre no lo alteran.
- Razón social vigente propuesta o confirmada según `estado_calidad` y `fecha_confirmacion_razon_social`; su fuente conserva procedencia sin confirmar por sí sola la identidad.
- Nombre comercial y valores de alias exactos, controlados dentro del catálogo operacional actual.
- Alias confirmados como objetos trazables con UUID estable, valor, tipo, vigencia, fuente, observación, fecha propia de confirmación y fechas de creación y modificación; su normalización es derivada, no editable y validada al cargar.
- `fecha_confirmacion_valor` es obligatoria, UTC y anterior o igual a la creación del objeto; para una razón social anterior conserva la fecha de confirmación que tenía esa denominación.
- Solo alias activos participan en asociaciones automáticas; los inactivos se conservan sin eliminación física y sus coincidencias producen revisión.
- Tipos iniciales de alias `ALIAS`, `RAZON_SOCIAL_ANTERIOR` y `NOMBRE_COMERCIAL_ANTERIOR`; toda ampliación requiere autorización y documentación.
- Campos normalizados derivados, no editables y validados al cargar.
- RUT opcional, validado, único por `transportista_id` incluso en inactivos y protegido en salidas.
- Búsqueda exacta sobre todos los estados e identificadores, incluidos alias inactivos, con resolución según calidad y vigencia, identificación y reutilización no destructiva de propuestas pendientes y abstención ante inactividad, revisión o ambigüedad.
- Toda colisión entre distintos `transportista_id` produce `AMBIGUA`, incluso si interviene un alias inactivo; una coincidencia activa nunca prevalece sobre ella.
- Normalización conservadora de puntuación en sufijos societarios, sin eliminarlos, ignorarlos ni equiparar tipos societarios distintos.
- Registros confirmados protegidos mediante modificación manual explícita.
- Desactivación lógica sin eliminación física.
- Reactivación del mismo UUID y conservación histórica de razones sociales anteriores.
- Procedencia obligatoria y fecha UTC nullable de confirmación para la razón social vigente, con reglas explícitas para `PENDIENTE`, `CONFIRMADO` y `REQUIERE_REVISION`, independientes de la fecha de modificación general.
- Los cambios de razón social conservan el UUID y crean un alias `RAZON_SOCIAL_ANTERIOR` con la procedencia y fecha de confirmación anteriores.
- Ningún aprendizaje automático modifica identidades confirmadas.
- Una alerta automática contradictoria permanece separada; solo una decisión humana explícita cambia la calidad del registro maestro.
- Plantilla y pruebas exclusivamente sintéticas y sin RUT completos.
- `catalogos/transportistas.json` ignorado antes de cargar datos reales.
- Suite específica y suite completa sin regresiones.
- Ninguna integración con choferes, vehículos, viajes o reportes en la primera etapa.
- `propuesta_transportista` y `evidencia_transportista` permanecen como infraestructura conceptual futura y no se implementan en la primera etapa.
- La futura integración con Viajes usa conceptualmente `viaje_transportista`, con roles diseñados antes de implementarse y métricas atribuidas a un rol explícito sin doble conteo por viaje, métrica y rol.

## 14. Fuera de alcance

- implementación o carga del catálogo;
- choferes, tractos y ramplas;
- relaciones temporales persistidas;
- inferencia desde OCR;
- Unigis, OneLogis u otras integraciones;
- productividad, costos o interfaz gráfica;
- reportes e indicadores productivos.

Cada ampliación requiere autorización y una auditoría de privacidad independiente.
