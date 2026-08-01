# Catálogo Maestro de Clientes — Atlas

## 1. Alcance

Este catálogo administra identidades de clientes sin integrarse con OCR, extractor, destinos, viajes ni producción. Su finalidad es reconocer de forma estable razones sociales y alias confirmados, conservando siempre el texto original.

El catálogo privado se guarda en `catalogos/clientes.json` y está ignorado por Git. La plantilla pública `catalogos/templates/clientes_ejemplo.json` contiene únicamente información sintética.

## 2. Arquitectura

- `atlas_core/catalogo_clientes.py`: modelo, RUT, normalización, búsqueda y persistencia atómica.
- `gestionar_catalogos.py clientes`: interfaz de terminal en español.
- `catalogos/clientes.json`: archivo privado, creado únicamente al registrar el primer cliente.
- `catalogos/templates/clientes_ejemplo.json`: contrato público sintético.
- `tests/test_catalogo_clientes.py`: pruebas aisladas.

El módulo heredado `atlas_core/catalogos.py` no fue modificado.

## 3. Modelo

Cada registro contiene:

- `cliente_id`: UUID estable;
- `razon_social`: texto original;
- `nombre_normalizado`: clave derivada para comparación;
- `nombre_comercial`: opcional;
- `rut`: opcional, validado y almacenado canónicamente;
- `aliases`: textos alternativos originales;
- `estado_calidad`: `PENDIENTE`, `CONFIRMADO` o `REQUIERE_REVISION`;
- `estado_vigencia`: `ACTIVO` o `INACTIVO`;
- `fuente`, `observacion`, `fecha_creacion` y `fecha_modificacion`.

## 4. Normalización, alias y duplicados

La normalización:

- elimina diferencias de mayúsculas, acentos, puntuación y espacios;
- reconoce como equivalente el sufijo final `SA`, `S.A.` o `SOCIEDAD ANÓNIMA`;
- no realiza coincidencias aproximadas ni por fragmentos;
- nunca reemplaza el texto original.

Reglas:

1. razón social y fuente son obligatorias;
2. el UUID no cambia al editar la razón social;
3. razones sociales y alias normalizados son únicos globalmente;
4. un RUT válido no puede pertenecer a dos clientes;
5. el nombre comercial puede compartirse y, en ese caso, una búsqueda devuelve `AMBIGUA`;
6. una búsqueda ambigua se abstiene y no selecciona cliente;
7. un cliente confirmado requiere `--confirmar-modificacion` para editar, agregar alias o desactivar;
8. un registro inactivo se conserva;
9. un archivo corrupto produce un error y no se reemplaza silenciosamente.

## 5. RUT y privacidad

El RUT es opcional. Cuando existe:

- se valida estructura y dígito verificador;
- se almacena sin puntos y con guion;
- no forma parte del UUID;
- la CLI lo muestra como `PROTEGIDO`, no como valor completo.

## 6. Comandos

Ayuda:

```powershell
python gestionar_catalogos.py clientes --help
```

Listar:

```powershell
python gestionar_catalogos.py clientes listar
```

Agregar un cliente sintético:

```powershell
python gestionar_catalogos.py clientes agregar --razon-social "EMPRESA DEMO S.A." --nombre-comercial "MARCA DEMO" --fuente "INGRESO_MANUAL"
```

Agregar con uno o varios alias:

```powershell
python gestionar_catalogos.py clientes agregar --razon-social "EMPRESA DEMO S.A." --fuente "INGRESO_MANUAL" --alias "EMPRESA DEMO" --alias "MARCA DEMO"
```

Mostrar por UUID:

```powershell
python gestionar_catalogos.py clientes mostrar "CLIENTE_ID"
```

Editar:

```powershell
python gestionar_catalogos.py clientes editar "CLIENTE_ID" --nombre-comercial "NUEVA MARCA DEMO"
```

Agregar alias:

```powershell
python gestionar_catalogos.py clientes agregar-alias "CLIENTE_ID" --alias "NOMBRE ALTERNATIVO"
```

Buscar por razón social, nombre comercial o alias completo:

```powershell
python gestionar_catalogos.py clientes buscar --texto "NOMBRE"
```

Desactivar:

```powershell
python gestionar_catalogos.py clientes desactivar "CLIENTE_ID"
```

En clientes confirmados, las operaciones de modificación requieren agregar:

```text
--confirmar-modificacion
```

## 7. Compatibilidad con Plantas

Los comandos originales continúan disponibles:

```powershell
python gestionar_catalogos.py listar
python gestionar_catalogos.py agregar ...
python gestionar_catalogos.py mostrar "PLANTA_ID"
python gestionar_catalogos.py editar "PLANTA_ID" ...
python gestionar_catalogos.py desactivar "PLANTA_ID"
```

También se admite la forma explícita:

```powershell
python gestionar_catalogos.py plantas listar
```

## 8. Persistencia y recuperación

Cada actualización se escribe en un temporal dentro del mismo directorio, se sincroniza y luego reemplaza atómicamente el archivo vigente. Si el reemplazo falla, el archivo anterior permanece intacto y el temporal se elimina.

Un archivo inexistente representa un catálogo vacío. Un archivo existente pero corrupto genera un error visible.

## 9. Fuera de alcance

- carga de clientes reales;
- aprendizaje desde OCR;
- modificación automática de registros confirmados;
- clientes aproximados por similitud;
- destinos, viajes, rutas, distancias o integraciones externas.

La carga de información real requiere autorización posterior.
