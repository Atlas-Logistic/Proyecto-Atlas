# Atlas — Diseño de Catálogos Maestros

## 1. Propósito

Los Catálogos Maestros permiten que Atlas mantenga conocimiento operacional propio y reutilizable. Su función es transformar valores variables provenientes de documentos en entidades estables: una planta, un cliente, un destino, un vehículo, un chofer, un material, una empresa transportista o una ruta.

El OCR continúa siendo una fuente de observaciones. No se convierte en la autoridad del catálogo.

Este diseño debe permitir que una corrección realizada una vez beneficie viajes futuros sin alterar silenciosamente información ya confirmada ni borrar la evidencia original.

## 2. Principios obligatorios

1. Cada entidad maestra tiene un identificador interno inmutable y sin significado operacional.
2. El texto original detectado siempre se conserva como evidencia.
3. Una coincidencia automática puede proponer una asociación, pero solo las reglas autorizadas pueden confirmarla.
4. Un valor nuevo crea una propuesta pendiente, no un registro confirmado.
5. Atlas nunca modifica automáticamente un registro maestro confirmado.
6. Las correcciones manuales quedan auditadas con usuario, fecha, motivo, valores anterior y nuevo.
7. Las variantes y alias no sustituyen ni reescriben el nombre oficial.
8. Los registros no se eliminan si tienen historia; se desactivan, fusionan de forma trazable o sustituyen mediante una relación explícita.
9. Una ausencia no equivale a una coincidencia.
10. Ante ambigüedad, conflicto o evidencia insuficiente, Atlas se abstiene.
11. Los datos personales se muestran y exportan según permisos.
12. Los reportes consumen entidades confirmadas y declaran su cobertura.

## 3. Modelo común de un catálogo

Todos los catálogos comparten una estructura mínima.

| Campo común | Finalidad |
|---|---|
| Identificador interno | Identidad estable, recomendada como UUID |
| Nombre o descripción oficial | Valor visible aprobado por operaciones |
| Estado de calidad | Grado de confianza del registro |
| Estado de vigencia | Indica si está activo, inactivo o sustituido |
| Alias y variantes | Formas históricas o documentales reconocidas |
| Fuente de creación | Manual, documento, importación o integración futura |
| Evidencia | Referencias que sustentan el registro o la asociación |
| Creado y actualizado | Fechas de auditoría |
| Creado o actualizado por | Usuario, regla o sistema responsable |
| Motivo de cambio | Explicación obligatoria para cambios sensibles |
| Versión | Permite reproducir decisiones históricas |

### 3.1 Identificador interno

El identificador interno:

- no se construye con RUT, patente, dirección, nombre ni código visible;
- no cambia cuando cambia el nombre oficial;
- no se reutiliza;
- permanece disponible para relaciones históricas aunque el registro se desactive.

### 3.2 Estados de calidad comunes

| Estado | Significado | Uso automático |
|---|---|---|
| `CONFIRMADO` | Identidad y datos mínimos revisados o provenientes de una fuente autorizada | Puede participar en asociaciones y reportes según sus campos validados |
| `PENDIENTE_VALIDACION` | Registro nuevo con evidencia insuficiente para confirmar | No participa en indicadores oficiales como entidad confirmada |
| `PROPUESTO` | Posible registro o posible asociación generado automáticamente | Solo aparece en la bandeja de revisión |
| `AMBIGUO` | La observación podría corresponder a más de un registro | Atlas se abstiene de asociar |
| `CONFLICTIVO` | Existen evidencias válidas contradictorias | Bloquea el uso del dato afectado |
| `INCOMPLETO` | La identidad es conocida, pero falta información obligatoria para cierto uso | Solo participa en usos que no requieren el campo faltante |
| `RECHAZADO` | La propuesta fue revisada y no representa una entidad válida | No se usa; conserva auditoría para evitar repetición |

El estado de calidad es distinto del estado de vigencia:

- `ACTIVO`: puede usarse en nuevas asociaciones;
- `INACTIVO`: se conserva para historia, pero no se propone para nuevos viajes;
- `SUSTITUIDO`: apunta al registro maestro que lo reemplaza;
- `FUSIONADO`: su historia se conserva, pero la identidad canónica es otra.

## 4. Catálogo de Plantas

### 4.1 Propósito

Representar los puntos de origen administrados por Atlas. En la primera etapa contempla las plantas operacionales autorizadas, sin inferir el origen cuando la evidencia sea insuficiente.

### 4.2 Identificador

`planta_id`: UUID inmutable.

### 4.3 Campos

| Campo | Tipo conceptual | Obligatorio para confirmar |
|---|---|---:|
| `planta_id` | UUID | Sí |
| `nombre_oficial` | Texto | Sí |
| `codigo_operacional` | Texto | No |
| `direccion_oficial` | Texto estructurado | Sí para rutas |
| `comuna` | Referencia geográfica | Sí para rutas |
| `region` | Referencia geográfica | Sí para rutas |
| `latitud`, `longitud` | Coordenadas | No; necesarias para ciertas fuentes de distancia |
| `zona_horaria` | Identificador | Sí |
| `alias` | Colección | No |
| `estado_calidad`, `estado_vigencia` | Enumeraciones | Sí |
| Campos de auditoría | Auditoría | Sí |

### 4.4 Información editable

- nombre y código oficiales;
- dirección, comuna y región;
- coordenadas validadas;
- alias autorizados;
- vigencia;
- motivo y fuente de validación.

### 4.5 Información calculada

- cantidad de viajes asociados;
- última fecha de uso;
- cobertura de destinos y rutas;
- cantidad de alias observados pendientes;
- coordenadas normalizadas o verificadas por una fuente futura, siempre como propuesta hasta su validación.

### 4.6 Relaciones

- origina muchos viajes;
- es origen de muchas rutas;
- puede relacionarse con vehículos, choferes o empresas solo como asociación histórica, no como pertenencia permanente salvo fuente autorizada.

### 4.7 Validación

- nombre oficial único dentro de las plantas activas;
- código operacional único cuando exista;
- dirección suficiente y coherente con comuna y región;
- coordenadas dentro de un rango geográfico válido y coherentes con la dirección;
- un alias no puede apuntar automáticamente a dos plantas activas;
- si dos plantas son candidatas, el origen del viaje permanece vacío.

### 4.8 Calidad específica

- `CONFIRMADO`: identidad y ubicación aprobadas;
- `INCOMPLETO`: planta conocida sin ubicación suficiente para rutas;
- `AMBIGUO`: alias compatible con más de una planta;
- `CONFLICTIVO`: dirección o coordenadas contradicen otra fuente válida.

## 5. Catálogo de Clientes

### 5.1 Propósito

Representar la entidad comercial que recibe o encarga la operación, separada del lugar físico de entrega.

### 5.2 Identificador

`cliente_id`: UUID inmutable. Un identificador tributario, si se incorpora, es un atributo protegido y no la clave interna.

### 5.3 Campos

| Campo | Tipo conceptual | Obligatorio para confirmar |
|---|---|---:|
| `cliente_id` | UUID | Sí |
| `razon_social_oficial` | Texto | Sí |
| `nombre_fantasia` | Texto | No |
| `identificador_externo` | Texto | No |
| `identificador_tributario` | Dato protegido | No |
| `alias` | Colección | No |
| `estado_calidad`, `estado_vigencia` | Enumeraciones | Sí |
| Campos de auditoría | Auditoría | Sí |

### 5.4 Información editable

- razón social y nombre visible;
- identificadores oficiales autorizados;
- alias documentales;
- vigencia;
- relaciones autorizadas con destinos.

### 5.5 Información calculada

- cantidad de viajes confirmados;
- destinos utilizados;
- materiales y toneladas, cuando esos datos estén validados;
- primera y última operación observada;
- variantes nuevas pendientes.

### 5.6 Relaciones

- tiene cero o muchos destinos;
- participa en muchos viajes;
- puede compartir un destino con otros clientes;
- consume materiales y rutas a través de viajes, no mediante relaciones inventadas.

### 5.7 Validación

- un identificador oficial no puede pertenecer a dos clientes activos;
- el nombre aislado no basta para fusionar clientes;
- nombres normalizados iguales con identificadores distintos generan conflicto;
- un alias confirmado apunta a un único cliente activo;
- cliente y destino se validan por separado.

### 5.8 Calidad específica

- `CONFIRMADO`: identidad comercial aprobada;
- `INCOMPLETO`: nombre conocido sin identificador oficial, usable solo cuando la política lo permita;
- `AMBIGUO`: variante compatible con varios clientes;
- `CONFLICTIVO`: identificadores o nombres oficiales contradictorios.

## 6. Catálogo de Destinos

### 6.1 Propósito

Representar lugares físicos de entrega de forma reutilizable, independientemente de las variantes de obra, sucursal o dirección observadas en documentos.

### 6.2 Identificador

`destino_id`: UUID inmutable.

### 6.3 Campos

| Campo | Tipo conceptual | Obligatorio para confirmar |
|---|---|---:|
| `destino_id` | UUID | Sí |
| `nombre_oficial` | Texto | Sí |
| `tipo_destino` | Obra, sucursal, bodega u otro vocabulario | Sí |
| `direccion` | Texto estructurado | Sí para rutas |
| `comuna` | Referencia geográfica | Sí para rutas |
| `region` | Referencia geográfica | Sí para rutas |
| `latitud`, `longitud` | Coordenadas | No |
| `alias` | Colección | No |
| `estado_calidad`, `estado_vigencia` | Enumeraciones | Sí |
| Campos de auditoría | Auditoría | Sí |

### 6.4 Información editable

- nombre y tipo;
- dirección, comuna y región;
- coordenadas validadas;
- alias;
- clientes relacionados;
- vigencia y notas operacionales no sensibles.

### 6.5 Información calculada

- clientes y viajes asociados;
- plantas de origen observadas;
- rutas disponibles;
- frecuencia y última utilización;
- variantes pendientes de resolución.

### 6.6 Relaciones

- puede servir a uno o varios clientes;
- recibe muchos viajes;
- es destino de rutas desde una o más plantas.

La relación cliente–destino debe ser explícita y puede tener vigencia. Atlas no debe duplicar un destino físico solo porque aparece bajo otro cliente.

### 6.7 Validación

- dirección, comuna y región deben ser coherentes;
- coordenadas y dirección no pueden contradecirse;
- un nombre de obra aislado no basta para fusionar destinos;
- un alias ambiguo bloquea la asignación;
- direcciones similares se proponen como posibles coincidencias, nunca se fusionan automáticamente;
- una ruta solo se habilita cuando origen y destino son confiables.

### 6.8 Calidad específica

- `CONFIRMADO`: lugar físico identificado;
- `INCOMPLETO`: destino conocido sin georreferencia suficiente;
- `AMBIGUO`: texto aplicable a varios lugares;
- `CONFLICTIVO`: fuentes válidas señalan ubicaciones diferentes.

## 7. Catálogo de Vehículos

### 7.1 Propósito

Representar tractos y ramplas como activos distintos y relacionarlos con viajes sin asumir propiedad permanente a partir de una sola observación.

### 7.2 Identificador

`vehiculo_id`: UUID inmutable. La patente es una clave de negocio validable, no la identidad técnica.

### 7.3 Campos

| Campo | Tipo conceptual | Obligatorio para confirmar |
|---|---|---:|
| `vehiculo_id` | UUID | Sí |
| `patente_oficial` | Texto normalizado | Sí |
| `tipo_vehiculo` | `TRACTO`, `RAMPLA` u otro autorizado | Sí |
| `identificador_externo` | Texto | No |
| `empresa_propietaria_id` | Referencia nullable | No |
| `empresa_operadora_id` | Referencia nullable y con vigencia | No |
| `capacidad_kg` | Decimal | No |
| `alias_observados` | Colección | No |
| `estado_calidad`, `estado_vigencia` | Enumeraciones | Sí |
| Campos de auditoría | Auditoría | Sí |

### 7.4 Información editable

- patente confirmada;
- tipo de vehículo;
- identificadores externos;
- capacidad autorizada;
- relaciones vigentes con empresas;
- vigencia y correcciones justificadas.

### 7.5 Información calculada

- viajes y kilómetros asociados;
- choferes y empresas observados por período;
- primera y última aparición;
- variantes OCR pendientes;
- utilización, cuando la definición operacional esté aprobada.

### 7.6 Relaciones

- participa en muchos viajes;
- puede relacionarse con empresas mediante períodos de vigencia;
- puede combinarse con otros vehículos en un viaje;
- no tiene una relación permanente con un chofer por defecto.

### 7.7 Validación

- formato de patente conforme a vocabularios autorizados;
- unicidad de patente oficial entre vehículos activos;
- tipo compatible con el rol ocupado en el viaje;
- una patente plausible detectada por OCR no se confirma sin evidencia suficiente;
- variantes que podrían ser dos patentes distintas quedan ambiguas;
- los cambios de empresa deben conservar su período histórico.

### 7.8 Calidad específica

- `CONFIRMADO`: patente y tipo validados;
- `INCOMPLETO`: vehículo identificado sin empresa o capacidad;
- `AMBIGUO`: lectura compatible con más de una patente;
- `CONFLICTIVO`: patente vinculada simultáneamente a identidades incompatibles.

## 8. Catálogo de Choferes

### 8.1 Propósito

Representar personas de manera estable y protegida para asociar viajes, evitando usar variaciones del nombre como identidades distintas.

### 8.2 Identificador

`chofer_id`: UUID inmutable. El RUT no se utiliza como identificador interno ni se expone innecesariamente.

### 8.3 Campos

| Campo | Tipo conceptual | Obligatorio para confirmar |
|---|---|---:|
| `chofer_id` | UUID | Sí |
| `nombre_oficial` | Texto | Sí |
| `rut_protegido` | Dato personal validado | Según política de identidad |
| `identificador_externo` | Texto | No |
| `empresa_transportista_id` | Referencia nullable y con vigencia | No |
| `alias_nombre` | Colección | No |
| `estado_calidad`, `estado_vigencia` | Enumeraciones | Sí |
| Campos de auditoría restringida | Auditoría | Sí |

### 8.4 Información editable

- nombre oficial;
- identificadores autorizados;
- relación vigente con empresa;
- alias revisados;
- vigencia.

Los datos personales requieren permisos específicos y no deben aparecer en reportes generales si no son necesarios.

### 8.5 Información calculada

- viajes y kilómetros confirmados;
- vehículos y empresas observados por período;
- primera y última operación;
- variantes de nombre pendientes.

### 8.6 Relaciones

- conduce muchos viajes;
- puede trabajar con varias empresas a lo largo del tiempo;
- utiliza distintos vehículos;
- no queda unido permanentemente a una patente por coincidencia histórica.

### 8.7 Validación

- RUT con formato y dígito verificador válidos cuando se utilice;
- un RUT válido no puede pertenecer a dos choferes activos;
- nombres iguales sin otra evidencia no se fusionan;
- nombres distintos con el mismo identificador válido generan revisión, no duplicación automática;
- la relación con empresa debe tener fuente y vigencia.

### 8.8 Calidad específica

- `CONFIRMADO`: identidad validada bajo la política vigente;
- `INCOMPLETO`: nombre conocido sin identificador suficiente para indicadores personales;
- `AMBIGUO`: homónimos o variantes no resueltas;
- `CONFLICTIVO`: identificadores válidos contradictorios.

## 9. Catálogo de Materiales

### 9.1 Propósito

Normalizar materiales y familias de carga manteniendo separadas descripción, tipo de carga, unidad, cantidad y peso.

### 9.2 Identificador

`material_id`: UUID inmutable. Un código comercial o de producto es un atributo externo.

### 9.3 Campos

| Campo | Tipo conceptual | Obligatorio para confirmar |
|---|---|---:|
| `material_id` | UUID | Sí |
| `codigo_material` | Texto | No |
| `descripcion_oficial` | Texto | Sí |
| `familia_material` | Vocabulario controlado | Sí |
| `tipo_carga` | Vocabulario controlado | Sí |
| `unidad_base` | Unidad | No |
| `alias_descripcion` | Colección | No |
| `estado_calidad`, `estado_vigencia` | Enumeraciones | Sí |
| Campos de auditoría | Auditoría | Sí |

### 9.4 Información editable

- código y descripción oficiales;
- familia y tipo de carga;
- unidad base;
- alias autorizados;
- vigencia.

### 9.5 Información calculada

- viajes, clientes y destinos asociados;
- cantidades y toneladas solo cuando su alcance sea válido;
- descripciones nuevas pendientes;
- frecuencia y última utilización.

### 9.6 Relaciones

- aparece en muchos documentos y viajes;
- un viaje puede incluir varios materiales;
- puede tener cantidades o pesos por documento, línea o viaje, cuyo alcance debe conservarse.

### 9.7 Validación

- código único cuando sea oficial;
- familia y tipo de carga pertenecen a vocabularios aprobados;
- una descripción parecida no implica el mismo material;
- unidad, cantidad y peso no se infieren de la descripción;
- alias ambiguos no se asocian automáticamente;
- una modificación de clasificación no reescribe viajes históricos sin un proceso explícito de recalculo.

### 9.8 Calidad específica

- `CONFIRMADO`: identidad y clasificación aprobadas;
- `INCOMPLETO`: material conocido sin código, unidad o clasificación completa;
- `AMBIGUO`: descripción aplicable a varios materiales;
- `CONFLICTIVO`: código o clasificación contradictorios.

## 10. Catálogo de Empresas Transportistas

### 10.1 Propósito

Representar la empresa responsable de ejecutar o administrar el transporte y permitir análisis por empresa sin inferirla únicamente desde un chofer o patente.

### 10.2 Identificador

`empresa_transportista_id`: UUID inmutable.

### 10.3 Campos

| Campo | Tipo conceptual | Obligatorio para confirmar |
|---|---|---:|
| `empresa_transportista_id` | UUID | Sí |
| `razon_social_oficial` | Texto | Sí |
| `nombre_fantasia` | Texto | No |
| `identificador_tributario` | Dato protegido | Según fuente oficial |
| `identificador_externo` | Texto | No |
| `alias` | Colección | No |
| `estado_calidad`, `estado_vigencia` | Enumeraciones | Sí |
| Campos de auditoría | Auditoría | Sí |

### 10.4 Información editable

- razón social y nombre visible;
- identificadores autorizados;
- alias;
- vigencia;
- relaciones temporales con choferes y vehículos.

### 10.5 Información calculada

- viajes, kilómetros y toneladas con cobertura válida;
- choferes y vehículos observados por período;
- clientes, destinos y rutas atendidos;
- primera y última operación.

### 10.6 Relaciones

- participa en muchos viajes;
- mantiene relaciones con choferes y vehículos con fecha de vigencia;
- puede operar para múltiples clientes y plantas.

### 10.7 Validación

- identificador oficial único cuando exista;
- nombres similares no se fusionan automáticamente;
- la empresa de un viaje requiere evidencia directa o una relación vigente autorizada;
- observar un vehículo una vez no establece propiedad permanente;
- conflictos de responsabilidad bloquean el indicador por empresa.

### 10.8 Calidad específica

- `CONFIRMADO`: identidad empresarial aprobada;
- `INCOMPLETO`: empresa conocida sin identificador suficiente;
- `AMBIGUO`: variante compatible con varias empresas;
- `CONFLICTIVO`: fuentes autorizadas atribuyen responsables diferentes.

## 11. Catálogo de Rutas

### 11.1 Propósito

Representar un trayecto reutilizable entre una planta de origen y un destino confirmados. Evita consultar repetidamente un proveedor externo y evita multiplicar distancia por documento.

### 11.2 Identificador

`ruta_id`: UUID inmutable. El par origen–destino es una clave lógica versionable, no el identificador interno.

### 11.3 Campos

| Campo | Tipo conceptual | Obligatorio para confirmar |
|---|---|---:|
| `ruta_id` | UUID | Sí |
| `planta_origen_id` | Referencia | Sí |
| `destino_id` | Referencia | Sí |
| `distancia_km` | Decimal | Sí |
| `tipo_distancia` | Vocabulario: vial, contractual u otro autorizado | Sí |
| `proveedor_fuente` | Texto controlado | Sí |
| `fecha_calculo` | Fecha-hora | Sí |
| `version_fuente` | Texto | No |
| `criterios_ruta` | Texto estructurado | No |
| `vigente_desde`, `vigente_hasta` | Fechas | Sí/No |
| `estado_calidad`, `estado_vigencia` | Enumeraciones | Sí |
| Campos de auditoría | Auditoría | Sí |

### 11.4 Información editable

- aprobación o rechazo de una ruta propuesta;
- tipo y fuente de distancia;
- criterios autorizados;
- vigencia;
- motivo de sustitución.

La distancia obtenida de un proveedor no se edita silenciosamente. Una corrección crea una nueva versión o una nueva fuente trazable.

### 11.5 Información calculada

- distancia propuesta por proveedor autorizado;
- cantidad de viajes que reutilizan la ruta;
- kilómetros acumulados por período;
- última utilización;
- fecha sugerida de revalidación;
- diferencias entre fuentes, mostradas como conflicto.

### 11.6 Relaciones

- pertenece a una planta y un destino;
- puede ser utilizada por muchos viajes;
- alimenta kilómetros por planta, cliente, chofer, vehículo y empresa solamente a través de viajes únicos confirmados.

### 11.7 Validación

- origen y destino deben estar confirmados y geográficamente completos;
- distancia mayor que cero y dentro de límites razonables definidos por negocio;
- unidad explícita;
- fuente, fecha y criterios obligatorios;
- no se consulta una ruta si ya existe una versión vigente compatible;
- valores distintos entre fuentes generan conflicto;
- si origen o destino son ambiguos, no se crea ni consulta la ruta;
- una ruta se aplica una sola vez a cada viaje.

### 11.8 Calidad específica

- `CONFIRMADO`: extremos y distancia aprobados;
- `INCOMPLETO`: extremos válidos sin distancia vigente;
- `PROPUESTO`: resultado nuevo aún no aprobado;
- `CONFLICTIVO`: distancias o extremos incompatibles;
- `INACTIVO`: versión histórica no aplicable a viajes nuevos.

## 12. Cómo aprenderá Atlas

### 12.1 Ciclo de aprendizaje gobernado

```text
Documento conserva el valor observado
                ↓
Atlas normaliza para buscar, sin cambiar el original
                ↓
Consulta alias e identidades confirmadas del catálogo
                ↓
Coincidencia única y segura ──→ propone o aplica asociación autorizada
Sin coincidencia ─────────────→ crea propuesta pendiente
Varias coincidencias ─────────→ marca ambigüedad y se abstiene
                ↓
Usuario revisa evidencia
                ↓
Confirma, vincula, crea, rechaza o corrige
                ↓
La decisión queda auditada y beneficia observaciones futuras
```

### 12.2 Ejemplo sintético

Un documento contiene el texto ficticio `CLIENTE DEMO SOCIEDAD`.

1. Atlas conserva ese texto exactamente como fue observado.
2. Genera una forma normalizada solo para buscar coincidencias.
3. Si existe un alias confirmado y único, asocia la observación al `cliente_id` correspondiente y registra la regla utilizada.
4. Si no existe, crea una propuesta `PENDIENTE_VALIDACION`; no crea un cliente confirmado.
5. Si dos clientes podrían coincidir, marca `AMBIGUO` y no elige.
6. Si el usuario confirma que es un alias de un cliente existente, Atlas agrega el alias con auditoría.
7. Las apariciones futuras pueden reutilizar el alias, sin modificar el nombre oficial.

### 12.3 Qué significa aprender

Atlas aprende mediante decisiones explícitas y reutilizables:

- nuevos alias confirmados;
- nuevas entidades maestras validadas;
- relaciones cliente–destino;
- vínculos temporales empresa–chofer y empresa–vehículo;
- clasificaciones de materiales;
- rutas validadas;
- propuestas rechazadas que no deben repetirse sin evidencia nueva.

Aprender no significa entrenar automáticamente sobre toda corrección ni reemplazar reglas sin validación. Cualquier modelo futuro debe seguir respetando los estados, permisos y auditoría del catálogo.

### 12.4 Protección de registros confirmados

Una observación nueva que contradice un registro confirmado:

- no modifica el registro;
- no reemplaza su alias;
- crea una alerta o propuesta conflictiva;
- conserva ambas evidencias;
- requiere decisión humana o una fuente superior previamente autorizada.

## 13. Correcciones del usuario

### 13.1 Acciones disponibles

Desde un documento, viaje o bandeja de catálogo, un usuario autorizado puede:

- **Vincular:** asociar una observación con una entidad existente.
- **Crear:** convertir una propuesta en una nueva entidad maestra.
- **Agregar alias:** enseñar que una variante corresponde a una entidad.
- **Corregir atributo:** modificar un dato editable con motivo.
- **Separar:** deshacer una asociación incorrecta sin borrar evidencia.
- **Fusionar:** declarar que dos registros representan la misma entidad, conservando historia.
- **Rechazar:** marcar una propuesta como inválida.
- **Desactivar:** impedir nuevos usos sin eliminar relaciones históricas.
- **Reabrir:** devolver una entidad a revisión cuando aparece evidencia contradictoria.

### 13.2 Flujo de corrección

1. Atlas muestra el valor observado, la propuesta, el registro maestro y los viajes afectados.
2. El usuario selecciona una acción y explica el motivo.
3. Atlas valida permisos, campos obligatorios, duplicados y conflictos.
4. Se presenta una vista previa del impacto: asociaciones futuras, viajes abiertos y reportes potencialmente afectados.
5. El usuario confirma la decisión.
6. Atlas registra una nueva versión y conserva el valor anterior.
7. La decisión se aplica a observaciones futuras compatibles.
8. Los viajes históricos no se recalculan silenciosamente; quedan marcados para actualización controlada cuando corresponda.

### 13.3 Propagación de una corrección

| Corrección | Beneficio futuro | Tratamiento histórico |
|---|---|---|
| Alias de cliente | Reconoce la variante en documentos posteriores | Viajes abiertos pueden proponerse para actualizar; cierres no cambian sin proceso autorizado |
| Dirección de destino | Mejora validación de rutas nuevas | Rutas existentes se revisan si existe impacto |
| Patente corregida | Mejora asociación del vehículo | Observaciones anteriores quedan trazadas y requieren actualización controlada |
| Identidad de chofer | Evita fragmentación de actividad | Indicadores históricos solo se recalculan mediante proceso explícito |
| Clasificación de material | Mejora futuras clasificaciones | No cambia toneladas ni categorías cerradas silenciosamente |
| Nueva ruta validada | Evita consultas repetidas | Se aplica a viajes elegibles según vigencia |

### 13.4 Auditoría mínima

Toda corrección registra:

- catálogo y entidad;
- campo afectado;
- valor anterior y nuevo;
- acción realizada;
- motivo;
- usuario y rol;
- fecha y hora;
- evidencia consultada;
- viajes o relaciones potencialmente afectados;
- versión resultante.

## 14. Documento, Viaje, Catálogos y Reportes

```text
DOCUMENTO
  conserva texto observado, evidencia y calidad técnica
        ↓ aporta hechos candidatos
VIAJE
  agrupa documentos compatibles y define el movimiento físico
        ↓ referencia identidades estables
CATÁLOGOS MAESTROS
  resuelven planta, cliente, destino, vehículo, chofer,
  material, empresa y ruta
        ↓ entregan dimensiones confirmadas
REPORTES
  calculan indicadores sobre viajes únicos y datos validados
```

### 14.1 Documento

- Es evidencia inmutable de lo observado.
- Puede contener uno o varios valores candidatos.
- Conserva el texto original aunque una asociación sea corregida.
- No altera directamente un catálogo confirmado.

### 14.2 Viaje

- Es la unidad de conteo operacional.
- Relaciona documentos y referencias maestras mediante identificadores internos.
- Puede estar confirmado aunque algunos atributos secundarios estén incompletos.
- Declara qué campos son aptos para cada indicador.

### 14.3 Catálogos

- Dan identidad y significado estable a los valores del viaje.
- Conservan alias, vigencia, calidad y auditoría.
- No convierten automáticamente un viaje probable en confirmado.
- Pueden mejorar la completitud de viajes futuros.

### 14.4 Reportes

- Consumen viajes únicos, no documentos aislados.
- Usan solo dimensiones y medidas con calidad suficiente.
- Muestran cobertura y exclusiones.
- Conservan el significado histórico de cierres o exigen una actualización explícita.

## 15. Conflictos, fusiones y vigencia

### 15.1 Conflictos

Cuando una observación contradice información confirmada, Atlas crea un caso con:

- entidades involucradas;
- campos contradictorios;
- fuentes;
- viajes potencialmente afectados;
- nivel de impacto;
- acción requerida.

No decide según la frecuencia del texto ni según el valor más reciente por defecto.

### 15.2 Fusiones

Una fusión requiere usuario autorizado y vista previa. El registro secundario se marca `FUSIONADO`, apunta al canónico y conserva todas sus referencias históricas. Los identificadores nunca se borran ni se reciclan.

### 15.3 Separaciones

Si dos identidades fueron fusionadas erróneamente, la separación debe reconstruir relaciones desde la auditoría. No se permite una edición directa que deje viajes sin trazabilidad.

### 15.4 Vigencia temporal

Las relaciones que cambian en el tiempo deben tener inicio y fin, especialmente:

- empresa–chofer;
- empresa–vehículo;
- cliente–destino;
- ruta y versión de distancia;
- nombres o códigos oficiales sustituidos.

## 16. Roles y gobierno

### 16.1 Roles funcionales sugeridos

- **Consulta:** visualiza catálogos y reportes según permisos.
- **Supervisor:** resuelve asociaciones operacionales y confirma propuestas de bajo riesgo.
- **Administrador de catálogos:** crea, fusiona, desactiva y modifica atributos maestros.
- **Auditor:** revisa historia y evidencia sin modificar.

### 16.2 Controles

- permisos por catálogo y acción;
- doble confirmación para fusiones o cambios de identidad;
- exposición restringida de datos personales;
- historial no editable;
- motivo obligatorio para cambios;
- reportes de propuestas, rechazos, conflictos y cambios recientes.

## 17. Prioridad de implementación futura

Este documento no autoriza implementación. Cuando se autorice, el orden recomendado es:

1. modelo común de estados, auditoría, alias y vigencia;
2. Plantas;
3. Clientes y Destinos, incluyendo su relación;
4. Vehículos y Choferes;
5. Materiales;
6. Empresas transportistas y relaciones temporales;
7. Rutas, después de validar origen y destino;
8. flujo de propuestas y correcciones;
9. integración con Viajes;
10. incorporación gradual a Reportes.

Cada catálogo debe comenzar con datos sintéticos y pruebas de reglas antes de cargar información operacional.

## 18. Criterios de aceptación del diseño

El sistema de catálogos será seguro cuando:

1. ninguna observación automática pueda modificar un registro confirmado;
2. toda entidad tenga identidad interna, calidad, vigencia y auditoría;
3. un valor ambiguo produzca abstención;
4. toda corrección pueda explicarse y revertirse mediante su historia;
5. los viajes históricos no cambien silenciosamente;
6. las variantes confirmadas beneficien documentos futuros;
7. las relaciones temporales conserven su vigencia;
8. los reportes distingan cobertura, pendientes y datos confirmados;
9. el catálogo de rutas evite consultas repetidas y doble conteo de distancia;
10. los datos personales estén protegidos por rol y finalidad.

## 19. Alcance explícito

Este documento define la arquitectura funcional y las reglas de gobierno de los Catálogos Maestros de Atlas. No implementa bases de datos, interfaces, OCR, búsquedas, servicios de mapas ni integraciones.

Los nombres y situaciones utilizados son exclusivamente conceptuales o sintéticos. No se incluyen datos operacionales reales.
