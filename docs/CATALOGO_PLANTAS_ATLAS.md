# Catálogo Maestro de Plantas — Atlas

## 1. Alcance

Esta primera infraestructura administra exclusivamente plantas. No detecta plantas desde documentos, no participa en OCR, no modifica la extracción productiva y no calcula rutas ni distancias.

El catálogo real se guarda localmente en `catalogos/plantas.json`. Ese archivo está excluido de Git porque puede contener información operacional. La plantilla `catalogos/templates/plantas_ejemplo.json` contiene solo información sintética y puede versionarse.

## 2. Arquitectura

- `atlas_core/catalogo_plantas.py`: modelo, validaciones, lectura y escritura atómica.
- `gestionar_catalogos.py`: interfaz de terminal en español.
- `catalogos/plantas.json`: almacenamiento privado creado al agregar la primera planta.
- `catalogos/templates/plantas_ejemplo.json`: ejemplo público sintético.
- `tests/test_catalogo_plantas.py`: pruebas aisladas con directorios temporales.

Se utilizó un módulo independiente porque el proyecto ya posee `atlas_core/catalogos.py`, conectado a comportamientos existentes. Esta separación evita cambiar producción y permite una migración futura controlada.

## 3. Formato del archivo

```json
{
  "version_formato": 1,
  "plantas": []
}
```

Cada planta contiene:

- `planta_id`: UUID estable;
- `nombre`: texto original conservado;
- `nombre_normalizado`: valor derivado para comparar duplicados;
- `direccion`, `comuna`, `region` y `pais`;
- `latitud` y `longitud` opcionales;
- `estado_calidad`: `PENDIENTE`, `CONFIRMADA` o `REQUIERE_REVISION`;
- `estado_vigencia`: `ACTIVA` o `INACTIVA`;
- `fuente` y `observacion`;
- `fecha_creacion` y `fecha_modificacion` en UTC con zona horaria.

## 4. Reglas

1. `nombre`, `pais` y `fuente` son obligatorios.
2. Dirección, comuna y región pueden quedar vacías; Atlas no completa datos inventados.
3. Las coordenadas deben entregarse juntas y respetar sus rangos geográficos.
4. El nombre se compara sin acentos, sin diferencias de mayúsculas y con espacios consolidados.
5. El texto original del nombre permanece almacenado.
6. Dos plantas no pueden compartir el mismo nombre normalizado, aunque una esté inactiva.
7. Cambiar el nombre no cambia `planta_id`.
8. Una planta `CONFIRMADA` requiere la opción explícita `--confirmar-modificacion` para editarse o desactivarse.
9. La desactivación conserva físicamente el registro.
10. Un archivo inexistente representa un catálogo vacío; un archivo corrupto produce un error visible.
11. Cada escritura se realiza primero en un archivo temporal del mismo directorio, se sincroniza y luego reemplaza el archivo destino.

## 5. Uso desde PowerShell

Ver ayuda:

```powershell
python gestionar_catalogos.py --help
python gestionar_catalogos.py agregar --help
```

Listar todas las plantas:

```powershell
python gestionar_catalogos.py listar
```

Agregar una planta sintética:

```powershell
python gestionar_catalogos.py agregar --nombre "PLANTA DEMO" --pais "PAÍS DEMO" --fuente "INGRESO_MANUAL"
```

Mostrar una planta usando el UUID informado al crearla:

```powershell
python gestionar_catalogos.py mostrar "PLANTA_ID"
```

Editar una planta pendiente:

```powershell
python gestionar_catalogos.py editar "PLANTA_ID" --direccion "DIRECCIÓN CONFIRMADA"
```

Editar una planta confirmada:

```powershell
python gestionar_catalogos.py editar "PLANTA_ID" --observacion "MOTIVO DEL CAMBIO" --confirmar-modificacion
```

Desactivar sin eliminar:

```powershell
python gestionar_catalogos.py desactivar "PLANTA_ID"
```

Para una planta confirmada, la desactivación también requiere `--confirmar-modificacion`.

## 6. Ejemplos sintéticos de carga manual

La implementación no crea registros automáticamente. Un usuario autorizado puede registrar plantas manualmente con estos comandos completamente sintéticos.

Planta pendiente, sin inventar una dirección:

```powershell
python gestionar_catalogos.py agregar --nombre "PLANTA DEMO NORTE" --comuna "COMUNA DEMO" --region "REGIÓN DEMO" --pais "PAÍS DEMO" --estado-calidad PENDIENTE --fuente "INGRESO_MANUAL" --observacion "Dirección sintética pendiente"
```

Planta sintética con dirección confirmada:

```powershell
python gestionar_catalogos.py agregar --nombre "PLANTA DEMO SUR" --direccion "AV. EJEMPLO 1234" --comuna "COMUNA DEMO" --region "REGIÓN DEMO" --pais "PAÍS DEMO" --estado-calidad CONFIRMADA --fuente "INGRESO_MANUAL"
```

Estos comandos escriben en `catalogos/plantas.json`, que permanece privado e ignorado por Git.

## 7. Recuperación y seguridad

- Antes de reemplazar el archivo, la versión completa nueva queda escrita y sincronizada en el mismo directorio.
- Si la escritura temporal falla, el catálogo anterior permanece intacto.
- Si el archivo está corrupto, Atlas se detiene y lo informa; no lo reemplaza por un catálogo vacío.
- No se ofrece eliminación física.
- Se recomienda incluir el archivo privado en una política de respaldo local controlada.

## 8. Fuera de alcance

- detección automática de planta;
- conexión con documentos o viajes;
- clientes, destinos u otros catálogos;
- mapas, coordenadas automáticas, rutas o distancias;
- interfaz gráfica e integraciones externas.

Cualquier conexión con el flujo productivo requiere una autorización posterior.
