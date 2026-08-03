# Handoff — Orquestador Multicampo, Fase 1

Fecha: 2026-08-03
Estado: LISTO PARA AUDITORÍA INDEPENDIENTE

## Alcance cerrado

Se incorporó una capa de orquestación reutilizable y exclusivamente en modo
sombra. No está conectada a `procesamiento_masivo`, extractor, Desktop o
producción y no publica ni reemplaza valores actuales.

- Rama: `feature-orquestador-multicampo-fase1`.
- Base: `bce3e98c536cbff1b686140952f10d0b7aea8d99` (`origin/main`).
- Commit técnico: `acfe3f19854043fa5c824a14e50a47618b7c3a35`.

## Diseño

`SolicitudResolucionSombra` encapsula campo, resolver, argumentos y opciones.
`OrquestadorMulticampoSombra` ejecuta en orden, conserva cada resultado crudo
y genera un `ResumenResolucionSombra` común con estado, confianza, revisión y
cantidad de contradicciones. Un fallo queda aislado al campo y solo registra
el tipo de excepción; no expone mensajes que puedan contener datos.

El resultado agregado y sus mappings son inmutables. Campos duplicados se
rechazan antes de ejecutar. La fase 1 rechaza expresamente cualquier modo
distinto de `SOMBRA`.

## Decisión de menor riesgo

Se eligió composición por inyección de resolvers en lugar de crear un
`DocumentoMulticampoInput` universal. Las firmas actuales difieren y cada
resolver ya controla sus catálogos, snapshots y políticas. Un input universal
habría duplicado conocimiento y creado acoplamiento prematuro.

Los seis resolvers estándar funcionan directamente. Contratos externos, como
rutas, pueden aportar un adaptador explícito de resumen; el orquestador no
inventa equivalencias entre estados ni replica reglas externas.

## Archivos

- `atlas_core/inteligencia/orquestador_multicampo.py`
- `atlas_core/inteligencia/__init__.py`
- `tests/test_orquestador_multicampo.py`
- `docs/BITACORA_EJECUTIVA.md`
- `docs/BITACORA_TECNICA_CRONOLOGICA.md`
- `04_TRABAJOS_ACTIVOS_ATLAS.md`

## Pruebas

- Específicas: 12/12.
- Consumidores afectados de `atlas_core.inteligencia`: 217/217.
- `python -m compileall -q atlas_core/inteligencia tests/test_orquestador_multicampo.py`: aprobado.
- `git diff --check`: aprobado.

Se probaron resolvers reales de chofer, cliente, vehículo, destino, documento
y material; igualdad entre ejecución directa y orquestada; contratos
especializados; adaptador externo; inmutabilidad; orden; duplicados; fallo
aislado; contrato inválido y prohibición de modo productivo.

## Integridad

No se modificaron reglas de negocio, resolvers, políticas, snapshots,
extractor, procesamiento masivo, Desktop, catálogos o producción. No se
procesaron guías reales. La evidencia E2E preservada y no rastreada permaneció
intacta y fuera de los commits.

## Auditoría solicitada

Confirmar que la capa es puramente compositiva, que no existe ruta de
publicación productiva y que ningún resultado directo cambia al ejecutarse a
través del orquestador.
