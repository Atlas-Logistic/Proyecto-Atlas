# Catálogo Maestro de Destinos — Atlas

## 1. Alcance

Este catálogo representa puntos físicos de entrega asociados a clientes activos. No se integra con OCR, extractor, procesamiento masivo, viajes, mapas ni distancias.

El contrato privado vigente usa `catalogos/destinos.json`. La plantilla pública `catalogos/templates/destinos_ejemplo.json` contiene únicamente información sintética.

## 2. Seguridad respecto del archivo legado

Al comenzar esta fase ya existía un archivo privado `catalogos/destinos.json` con un formato anterior. Esta implementación no lo migra, modifica ni reemplaza.

El nuevo servicio exige una raíz versionada con `version_formato` y `destinos`. Si encuentra un archivo incompatible, genera un error visible. Antes de utilizar la ruta predeterminada deberá autorizarse una migración o respaldo explícito del archivo legado.

## 3. Arquitectura

- `atlas_core/catalogo_destinos.py`: modelo, asociación con Clientes, búsqueda y persistencia.
- `gestionar_catalogos.py destinos`: CLI en español.
- `catalogos/destinos.json`: ubicación privada, ya ignorada por Git.
- `catalogos/templates/destinos_ejemplo.json`: plantilla pública sintética.
- `tests/test_catalogo_destinos.py`: pruebas con catálogos temporales.

`atlas_core/catalogos.py` y el procesamiento productivo no participan en esta arquitectura.

## 4. Modelo

Cada destino contiene:

- UUID estable `destino_id`;
- `cliente_id` existente y activo al crear o reasignar;
- nombre original y nombre normalizado;
- código opcional;
- dirección, comuna, región y país separados;
- coordenadas opcionales;
- alias manuales;
- calidad `PENDIENTE`, `CONFIRMADO` o `REQUIERE_REVISION`;
- vigencia `ACTIVO` o `INACTIVO`;
- fuente, observación y fechas UTC de auditoría.

Dirección, comuna y región pueden quedar vacías. Atlas no inventa valores ni coordenadas.

## 5. Clientes y asociaciones

Al crear un destino o cambiar su cliente:

1. se consulta `catalogos/clientes.json`;
2. el UUID debe existir;
3. el cliente debe estar `ACTIVO`;
4. si no se cumplen las condiciones, no se escribe el destino.

La desactivación posterior de un cliente no elimina sus destinos históricos. Para nuevas asociaciones se exige vigencia activa.

## 6. Alias, búsqueda y duplicados

- Los nombres se comparan sin diferencias de mayúsculas, acentos, puntuación o espacios.
- No se utiliza similitud parcial.
- Nombre y alias son únicos dentro de un mismo cliente.
- Un código no puede repetirse dentro del cliente.
- Una misma dirección y comuna no se duplican dentro del cliente.
- El mismo nombre puede existir para clientes distintos.
- Una búsqueda global con varios resultados devuelve `AMBIGUA` y se abstiene.
- La búsqueda puede limitarse con `--cliente-id`.
- Un destino `CONFIRMADO` requiere `--confirmar-modificacion` para cambiarse.

## 7. Comandos

```powershell
python gestionar_catalogos.py destinos --help

python gestionar_catalogos.py destinos listar

python gestionar_catalogos.py destinos listar --cliente-id "CLIENTE_ID"

python gestionar_catalogos.py destinos agregar --cliente-id "CLIENTE_ID" --nombre "DESTINO DEMO" --direccion "DIRECCIÓN DEMO" --comuna "COMUNA DEMO" --region "REGIÓN DEMO" --pais "PAÍS DEMO" --fuente "INGRESO_MANUAL"

python gestionar_catalogos.py destinos mostrar "DESTINO_ID"

python gestionar_catalogos.py destinos editar "DESTINO_ID" --direccion "NUEVA DIRECCIÓN DEMO"

python gestionar_catalogos.py destinos agregar-alias "DESTINO_ID" --alias "NOMBRE ALTERNATIVO"

python gestionar_catalogos.py destinos buscar --texto "NOMBRE"

python gestionar_catalogos.py destinos buscar --texto "NOMBRE" --cliente-id "CLIENTE_ID"

python gestionar_catalogos.py destinos desactivar "DESTINO_ID"
```

En un destino confirmado, agregar `--confirmar-modificacion` a editar, agregar-alias o desactivar.

Para pruebas o migraciones controladas se pueden indicar rutas alternativas antes del subcomando:

```powershell
python gestionar_catalogos.py destinos --archivo "RUTA_DESTINOS" --archivo-clientes "RUTA_CLIENTES" listar
```

## 8. Compatibilidad

Se conservan:

```powershell
python gestionar_catalogos.py listar
python gestionar_catalogos.py plantas listar
python gestionar_catalogos.py clientes listar
```

## 9. Persistencia

La escritura se realiza en un temporal del mismo directorio, se sincroniza y luego reemplaza atómicamente el destino. Un fallo conserva el archivo anterior. Un archivo corrupto o incompatible genera error visible y no se sobrescribe.

## 10. Fuera de alcance

- cargar destinos reales;
- migrar el archivo legado;
- reconocer destinos desde OCR;
- calcular coordenadas, rutas o distancias;
- modificar Clientes o Plantas;
- integrar mapas o producción.

La carga o migración de destinos reales requiere autorización posterior.
