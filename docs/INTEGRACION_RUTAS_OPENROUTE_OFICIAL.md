# Integración aislada de rutas y OpenRouteService

## Alcance

Esta capa calcula una ruta entre coordenadas ya confirmadas. No depende de OCR,
Desktop, procesamiento masivo, viajes, reportes ni datos operacionales. No
geocodifica, no persiste y no realiza consultas al importar módulos.

La geocodificación y el cálculo de rutas son procesos distintos:

- geocodificación: convierte una consulta de dirección en candidatos que
  requieren validación;
- rutas: calcula distancia y duración entre dos coordenadas confirmadas.

Una coordenada dudosa o un candidato de geocodificación no debe presentarse a
`CalculadorRutas` como confirmado.

## Inventario de la referencia

Componentes revisados en la copia de referencia:

- `atlas_core/rutas/modelos.py`: **PORTADO**, ya coincidía por hash con la base.
- `atlas_core/rutas/proveedor.py`: **ADAPTADO** para registrar perfiles y pares
  de coordenadas en el proveedor simulado.
- `atlas_core/rutas/openrouteservice.py`: **PORTADO**, ya coincidía por hash;
  se reforzaron sus pruebas de respuestas HTTP y JSON.
- `atlas_core/rutas/repositorio.py`: **REFERENCIA**. No participa en el nuevo
  cálculo sin I/O.
- `calcular_muestra_rutas.py`: **EXCLUIDO**. Contiene destinos privados, una
  muestra fija, escritura en catálogo y fallback a `driving-car`.
- `docs/INFORME_GEOCODIFICACION_LOTE_48.md`: **REFERENCIA PRIVADA**, no copiada.
- catálogos reales y `catalogos/rutas.json`: **EXCLUIDOS**.

La base oficial ya tenía además `servicio.py`, pruebas aisladas y los documentos
de diseño. El nuevo `calculo.py` expone el contrato requerido sin reemplazar ni
conectar esos componentes históricos.

## API oficial

```python
from atlas_core.rutas import (
    CalculadorRutas,
    ProveedorRutasSimulado,
    SolicitudCalculoRuta,
)

proveedor = ProveedorRutasSimulado()
calculador = CalculadorRutas(proveedor)
resultado = calculador.calcular(
    SolicitudCalculoRuta(
        planta="AZA Renca",
        planta_confirmada=True,
        coordenadas_origen={"longitud": -70.70, "latitud": -33.40},
        destino="Destino sintético",
        destino_confirmado=True,
        coordenadas_destino={"longitud": -70.60, "latitud": -33.50},
        proveedor="simulado",
        perfil="driving-hgv",
        evidencia={"fuente": "ejemplo sintético"},
    )
)
```

El contrato devuelve:

- estado;
- proveedor y perfil;
- distancia en metros y kilómetros;
- duración en segundos y texto legible;
- coordenadas usadas;
- planta y destino usados;
- fecha con zona horaria;
- copia inmutable de la evidencia;
- error controlado;
- indicador de revisión.

## Estados

- `CALCULADA`
- `SIN_COORDENADAS_ORIGEN`
- `SIN_COORDENADAS_DESTINO`
- `CREDENCIAL_NO_DISPONIBLE`
- `PROVEEDOR_NO_DISPONIBLE`
- `ERROR_PROVEEDOR`
- `DATOS_INVALIDOS`
- `REVISAR`

Un resultado fallido nunca contiene distancia ni duración. Una ruta calculada
solo acepta métricas finitas y positivas.

## Plantas

La capa declara explícitamente `AZA RENCA` y `AZA COLINA` como plantas
operacionales conocidas, pero no contiene sus coordenadas. La planta, su estado
de confirmación y sus coordenadas deben llegar en cada solicitud.

No existe una planta global y no se infiere origen por cercanía. Una planta no
confirmada produce `REVISAR` sin invocar al proveedor.

## Proveedores reemplazables

`ProveedorRutas` es el puerto. Un adaptador implementa:

- `nombre`;
- `version`;
- `geocodificar(direccion)`;
- `calcular_ruta(origen, destino, perfil)`.

`ProveedorRutasSimulado` es determinista y no abre conexiones.
`OpenRouteService` usa un transporte HTTP inyectable, timeout finito y valida
código HTTP, UTF-8, JSON, rutas, distancia y duración.

Un proveedor futuro puede reemplazar a OpenRouteService sin modificar
`CalculadorRutas`.

## Perfil de vehículo

El perfil predeterminado es `driving-hgv`. Puede configurarse otro perfil
explícito y el resultado registra el valor utilizado.

No hay fallback automático a `driving-car`. Un perfil alternativo requiere una
nueva solicitud explícita.

## Credencial

OpenRouteService obtiene la credencial únicamente desde:

`OPENROUTESERVICE_API_KEY`

La ausencia de credencial produce `CREDENCIAL_NO_DISPONIBLE` y no rompe Atlas.
La clave no forma parte de resultados, errores, evidencia ni documentación. No
se usan archivos `.env`.

## Funcionamiento sin conexión

La importación y las pruebas normales no acceden a red. El proveedor simulado
permite verificar toda la lógica sin credencial. Timeout, errores de conexión,
HTTP y respuestas inválidas se convierten en estados controlados.

## Límites actuales

- No está conectado a viajes ni reportes.
- No escribe en `catalogos/rutas.json`.
- No está conectado a la raíz única de datos.
- No selecciona ni infiere plantas.
- No confirma resultados de geocodificación.
- No aplica restricciones adicionales de camión fuera del perfil solicitado.
- No contiene reintentos ni fallback automático.
- No existe todavía política productiva de cuota, caché o renovación.

## Integración futura con viajes

La integración futura debe tomar una planta ya confirmada por el viaje y un
destino ya confirmado con coordenadas aprobadas. Debe conservar el resultado
completo y su evidencia, y tratar cualquier estado distinto de `CALCULADA` como
revisión sin alterar los 15 campos oficiales del lector.
