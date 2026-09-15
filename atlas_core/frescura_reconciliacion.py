"""Frescura entre Fase 1 (``revalidar_y_regenerar_reporte``, disparada por
``aplicar_decision_obra``) y Fase 2 (``reconciliar_estado_derivado``,
disparada por ``atlas:cargar-automatico`` en Desktop).

Origen -- PERFIL FOCAL DE LATENCIA / P1 ELIMINAR DOBLE RECONCILIACIÓN:
medido sobre el dataset real (183 filas), aplicar una decisión corre la
batería de Fase 1 (~26 s) y, segundos después, Desktop dispara Fase 2,
que vuelve a correr gran parte de esa misma batería (~27 s) sobre el
dataset que Fase 1 ya dejó reconciliado -- sin que nada haya cambiado
entre medio.

Auditoría función por función (no por nombre de bloque): de los ~30
revalidadores que corren en Fase 2, sólo los listados en
``FUNCIONES_BATERIA_COMPARTIDA`` aparecen en AMBAS fases con EXACTAMENTE
los mismos argumentos (mismo `ruta_dataset`/`carpeta_catalogos`/
`ruta_ledger`, sin parámetro adicional que cambie su alcance). El resto
de la batería de Fase 2 (recuperación P0/replay OCR, convergencia de
identidad, corroboración de chofer por RUT, asociación Mobile, y --
crucial -- el revalidador más costoso medido, `revalidar_ruta_con_
destino_confirmado_en_catalogo_sin_ocr`, ~6-7 s) NO tiene equivalente en
Fase 1 y por lo tanto NUNCA puede omitirse por este mecanismo: seguirá
corriendo siempre, igual que las 3 pasadas exclusivas de Fase 2
(`reconciliar_bandeja_decisiones` / B1, `reconciliar_segunda_pasada_
universal_sin_ocr`, `reconciliar_decisiones_destino_no_resuelto`).

Contrato de la firma: pura función determinística de
(dataset + catálogos + ledger + versión de reglas + versiones de
capacidades). Fase 1 la calcula sobre el estado FINAL, ya con las 18
funciones compartidas aplicadas, justo antes de publicar
`estado_operacion.json`, y la persiste ahí bajo `firma_bateria_
compartida`. Fase 2 recalcula la MISMA firma sobre el estado ACTUAL
(antes de repetir las 18 llamadas) y sólo si coincide BYTE A BYTE se
abstiene de repetirlas -- cualquier duda (campo ausente, error de
lectura de un catálogo, versión de reglas/capacidades distinta, dataset
o ledger tocado por cualquier otra vía) hace que la firma no coincida y
cae al comportamiento de siempre: correr la batería completa. Nunca hay
lectura parcial ni comparación aproximada -- coincidencia total o
batería completa, sin término medio.

`firma_bateria_compartida` NUNCA se arrastra entre escrituras de
`estado_operacion.json` (a diferencia de `version_estado_derivado`/
`versiones_capacidades`) -- sólo `revalidar_y_regenerar_reporte` la
escribe, inmediatamente después de correr las 18 funciones. Cualquier
otra escritura del manifiesto (incluida la que hace la propia Fase 2 al
terminar) simplemente no la pasa, así que desaparece del manifiesto en
esa escritura -- la oportunidad de omitir sólo existe para el ciclo
Fase1->Fase2 inmediato, nunca sobrevive a una reconciliación posterior
ni a un reinicio de Desktop."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

# Auditados 1 a 1 contra las llamadas reales de ambas fases (ver
# docstring del módulo). Agregar una función aquí sin repetir esa
# auditoría (mismo nombre, mismos argumentos exactos en las dos fases,
# función pura de dataset+catálogos+ledger) puede introducir un falso
# positivo -- saltar trabajo que en realidad hacía falta.
FUNCIONES_BATERIA_COMPARTIDA: tuple[str, ...] = (
    "revalidar_destino_propio_respaldado_por_b1_sin_ocr",
    "revalidar_motivo_destino_ya_confirmado_sin_ocr",
    "revalidar_destino_contra_comuna_documental_sin_ocr",
    "revalidar_material_estampado_persistido_sin_ocr",
    "revalidar_fecha_por_telemetria_de_transporte_compartido_sin_ocr",
    "revalidar_obra_destino_sin_ocr",
    "revalidar_origen_encabezado_no_confiable_sin_ocr",
    "revalidar_origen_gps_candidato_unico_sin_contacto_sin_ocr",
    "revalidar_origen_por_eliminacion_categoria_sin_ocr",
    "revalidar_origen_por_categoria_sin_candidato_sin_ocr",
    "revalidar_origen_por_documento_hermano_de_transporte_sin_ocr",
    "revalidar_origen_vecinos_gps_contra_evidencia_propia_real_sin_ocr",
    "revalidar_origen_por_vecinos_temporales_gps_sin_ocr",
    "revalidar_origen_por_historial_de_cliente_sin_ocr",
    "revalidar_ruta_por_historial_de_obra_sin_ocr",
    "revalidar_destinos_confirmados_sin_coordenadas_sin_ocr",
    "revalidar_destino_vacio_confirmado_por_documento_sin_ocr",
    "revalidar_indicadores_documentales_sin_ocr",
)

# Sube si `FUNCIONES_BATERIA_COMPARTIDA` cambia de forma incompatible
# (una función deja de ser segura de saltar) -- aunque el contenido de la
# tupla ya participa de la firma (ver `calcular_firma_bateria_
# compartida`), este entero es una defensa explícita y legible aparte.
VERSION_CONTRATO_BATERIA_COMPARTIDA = 1


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_archivo_o_ausente(ruta: Path) -> str:
    try:
        return _sha256_hex(ruta.read_bytes())
    except OSError:
        return "AUSENTE"


def _sha256_catalogos(carpeta_catalogos: Path) -> str:
    """Huella determinística de TODOS los archivos directos de
    `catalogos_privados` (nombre + contenido, orden estable por nombre).
    Deliberadamente conservador: no se asume de antemano cuáles catálogos
    lee cada una de las 18 funciones -- un catálogo agregado, borrado o
    modificado (cualquiera, no sólo los que hoy se sabe que se leen)
    invalida la firma. Esto puede producir algún falso NEGATIVO (correr
    la batería completa cuando en rigor no hacía falta) pero nunca un
    falso positivo -- el costado aceptado explícitamente en este bloque.
    """
    try:
        archivos = sorted(p for p in carpeta_catalogos.iterdir() if p.is_file())
    except OSError:
        return "AUSENTE"
    hasher = hashlib.sha256()
    for archivo in archivos:
        try:
            contenido = archivo.read_bytes()
        except OSError:
            return "AUSENTE"
        hasher.update(archivo.name.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(hashlib.sha256(contenido).digest())
        hasher.update(b"\0")
    return hasher.hexdigest()


def calcular_firma_bateria_compartida(
    *,
    dataset: Path,
    carpeta_catalogos: Path,
    ruta_ledger: Path,
    ruleset_version: int,
    versiones_capacidades: dict[str, int],
) -> str:
    """Firma determinística de todo aquello de lo que dependen,
    EXCLUSIVAMENTE, las funciones en `FUNCIONES_BATERIA_COMPARTIDA`.
    Fase 1 y Fase 2 importan y llaman esta MISMA función -- ninguna
    reimplementa el cálculo por su cuenta, así que no puede haber drift
    entre lo que una escribe y lo que la otra compara."""
    payload = {
        "version_contrato": VERSION_CONTRATO_BATERIA_COMPARTIDA,
        "funciones": list(FUNCIONES_BATERIA_COMPARTIDA),
        "dataset_sha256": _sha256_archivo_o_ausente(dataset),
        "catalogos_sha256": _sha256_catalogos(carpeta_catalogos),
        "ledger_sha256": _sha256_archivo_o_ausente(ruta_ledger),
        "ruleset_version": ruleset_version,
        "versiones_capacidades": dict(sorted(versiones_capacidades.items())),
    }
    return _sha256_hex(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))
