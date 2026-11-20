"""Contrato de fuentes reales de una generación operacional (declarativo).

Mapea cada tipo de ``descriptor_generacion.TIPOS`` a los archivos y
mecanismos reales del Motor (base CASA ``c08bc38``), con su escritor,
lock, dependencias, cobertura de custodia y la forma de distinguir ausencia
de vacío. Es **sólo datos** más una validación pura: no lee archivos, no
captura, no adapta lectores y no publica. Detalle y referencias de código:
``docs/FUENTES_GENERACION.md``.

Una lista de archivos no es una instantánea coherente. Toda fuente mutable
exige la frontera común del escritor oficial (``PENDIENTE`` durable antes de
la primera mutación, ver ``docs/CONTRATO_COHERENCIA_LECTURA_LOTES.md``);
``integracion`` sólo dice si, además de esa frontera, falta algo propio de
la fuente.
"""
from __future__ import annotations

from dataclasses import dataclass

from atlas_core import descriptor_generacion as _dg

# --------------------------------------------------------------- estados
# Mapeo: qué tan bien se sabe cuál es la fuente real.
RESUELTO = "RESUELTO"                    # archivo/mecanismo y escritor identificados en el código
AMBIGUO = "AMBIGUO"                      # varias fuentes reales candidatas para un tipo de cardinalidad 1
SIN_ALMACEN_PROPIO = "SIN_ALMACEN_PROPIO"  # el concepto existe, pero vive dentro de otra fuente
NO_RESUELTO = "NO_RESUELTO"              # falta evidencia para fijar la fuente
MAPEOS = frozenset({RESUELTO, AMBIGUO, SIN_ALMACEN_PROPIO, NO_RESUELTO})

# Integración: qué falta además de la frontera común del escritor oficial.
LISTA_TRAS_FRONTERA = "LISTA_TRAS_FRONTERA"  # mapeo cerrado; sólo espera la frontera común
DECLARAR_CERO = "DECLARAR_CERO"              # el tipo se declara 0 explícitamente
BLOQUEADA = "BLOQUEADA"                      # requiere una decisión o un cambio antes de integrar
# Sin almacén propio: el descriptor v2 la representa como derivación de sus
# fuentes originales (descriptor_generacion.DERIVACIONES), sin objeto propio.
DEPENDENCIAS_DECLARADAS = "DEPENDENCIAS_DECLARADAS"
INTEGRACIONES = frozenset({LISTA_TRAS_FRONTERA, DECLARAR_CERO, BLOQUEADA, DEPENDENCIAS_DECLARADAS})

# Cobertura de la custodia actual (estado_confirmado.SEMILLA_*).
EN_SEMILLA = "EN_SEMILLA"
FUERA_DE_SEMILLA = "FUERA_DE_SEMILLA"      # rastreable() pero sólo si un escritor observado la toca
VERSIONADA_EN_CODIGO = "VERSIONADA_EN_CODIGO"  # vive en el repositorio Motor, no en la raíz de la empresa
NO_APLICA = "NO_APLICA"
CUSTODIAS = frozenset({EN_SEMILLA, FUERA_DE_SEMILLA, VERSIONADA_EN_CODIGO, NO_APLICA})

PROPIA = "PROPIA"
GLOBAL = "COMPARTIDA_GLOBAL"

LOCK_DATASET = "revalidacion_dataset"


@dataclass(frozen=True)
class FuenteReal:
    clave: str                     # nombre estable de esta fila del contrato
    tipo: str                      # tipo del descriptor
    identidad: str                 # identidad lógica propuesta (plantilla si contiene "<")
    ruta: str | None               # ruta relativa a la raíz de la empresa (o al repo si GLOBAL)
    mapeo: str
    integracion: str
    empresa: str
    custodia: str
    escritores: tuple[str, ...]    # "modulo.funcion" que escriben
    locks: tuple[str, ...]         # nombres de bloqueo_sesion usados por esos escritores
    dependencias: tuple[str, ...]  # claves de otras filas que deben ser de la misma generación
    ausencia_vs_vacio: str         # cómo se distingue en el estado actual del código
    lectores_tolerantes: tuple[str, ...]  # lectores que hoy convierten ausencia/error en vacío
    riesgo: str
    bloqueo: str = ""              # motivo concreto cuando integracion == BLOQUEADA
    rol: str | None = None         # rol del objeto en el descriptor v2, si el tipo lo exige


_ACT = "operacion/actual/"
_CAT = "catalogos_privados/"

FUENTES: tuple[FuenteReal, ...] = (
    FuenteReal(
        "identidad_empresa", "IDENTIDAD_EMPRESA", "empresa/identidad", _CAT + "empresa_identidad.json",
        RESUELTO, LISTA_TRAS_FRONTERA, PROPIA, EN_SEMILLA,
        ("aislamiento_empresas.inicializar_empresa",), (), (),
        "Obligatoria salvo MBT (cloud_id en EMPRESAS_SIN_MARCA): MBT no tiene marca y se declara 0; "
        "una marca en MBT es custodia ajena. Otra empresa sin marca es ausencia, nunca vacío.",
        ("aislamiento_empresas._leer_marca",),
        "Bajo: se escribe una vez al dar de alta la empresa."),
    FuenteReal(
        "dataset", "DATASET_OPERACIONAL", "operacion/dataset", _ACT + "analisis_completo_guias.csv",
        RESUELTO, LISTA_TRAS_FRONTERA, PROPIA, EN_SEMILLA,
        ("procesamiento_masivo", "revalidacion_documental", "aplicacion_decisiones", "acciones_operacionales",
         "mobile", "recuperacion_numero_guia", "recuperacion_material", "recuperacion_fila_custodia",
         "recuperacion_incremental", "reprocesamiento_reparador", "recalculo_ruta_planta",
         "reproceso_cuarentena.promover_candidato"),
        (LOCK_DATASET, "promocion_reproceso_cuarentena", "aplicar_decision_obra"),
        ("ledger", "bandeja", "investigacion", "evidencia"),
        "Archivo con encabezado: CSV sin filas es vacío legítimo; inexistente es ausencia.",
        ("acciones_operacionales._Contexto._filas_sin_bloqueo",),
        "Alto: muchos escritores. aplicar_decision_obra es la transacción lógica exterior y "
        "revalidacion_dataset (no reentrante) se toma y suelta en varias ventanas dentro de ella, así que "
        "entre ventanas se observa estado intermedio (mobile.py, comentario GAP CERRADO/RESIDUAL). "
        "reproceso_cuarentena.promover_candidato escribe bajo promocion_reproceso_cuarentena, que no "
        "excluye a revalidacion_dataset."),
    FuenteReal(
        "ledger", "LEDGER_DECISIONES", "operacion/ledger", _ACT + "decisiones_aplicadas.json",
        RESUELTO, LISTA_TRAS_FRONTERA, PROPIA, EN_SEMILLA,
        ("aplicacion_decisiones.aplicar_decision_obra", "acciones_operacionales"), ("aplicar_decision_obra",),
        ("dataset",),
        "JSON con lista 'aplicaciones' (vacía es legítima); inexistente es ausencia. Las decisiones "
        "humanas se distinguen por actor (decisiones_pendientes._actor_es_humano).",
        ("acciones_operacionales._Contexto.instantanea_documental", "equipo_operacional.errores_documentales_aza_por_ledger",
         "equipo_operacional.ResolutorEquipoOperacional"),
        "Alto: se escribe en la misma transacción lógica que el dataset (lock exterior "
        "aplicar_decision_obra), pero el dataset se publica en ventanas separadas."),
    FuenteReal(
        "acciones_operacionales", "DECISIONES_HUMANAS", "operacion/acciones-operacionales",
        _ACT + "acciones_operacionales.json",
        RESUELTO, LISTA_TRAS_FRONTERA, PROPIA, EN_SEMILLA,
        ("acciones_operacionales.CapaAccionesOperacionales._guardar_registro",), ("acciones_operacionales",),
        ("dataset", "ledger", "bandeja"),
        "Obligatorio en v2 (rol acciones_operacionales). Inexistente se trata hoy como registro vacío "
        "(_leer_registro). Contiene previews, auditoría de confirmaciones y marcas de publicación en curso "
        "(publicacion_iniciada/confirmacion_recuperable).",
        ("acciones_operacionales._leer_json", "acciones_operacionales.publicacion_documental_incompleta"),
        "Alto: es a la vez registro de confirmaciones y marca de publicación documental incompleta.",
        rol="acciones_operacionales"),
    FuenteReal(
        "operaciones_conversacionales", "DECISIONES_HUMANAS", "operacion/operaciones-conversacionales",
        _ACT + "operaciones_conversacionales.json",
        RESUELTO, LISTA_TRAS_FRONTERA, PROPIA, EN_SEMILLA,
        ("operaciones_conversacionales",), ("operaciones_conversacionales", "catalogo_vehiculos"),
        ("catalogo_vehiculos", "catalogo_choferes"),
        "Obligatorio en v2 (rol operaciones_conversacionales). Inexistente se trata hoy como ledger vacío "
        "(_leer_ledger).",
        ("operaciones_conversacionales._leer_ledger",),
        "Medio: escribe además vehiculos.json bajo otro lock (catalogo_vehiculos).",
        rol="operaciones_conversacionales"),
    FuenteReal(
        "bandeja", "BANDEJA_REVISION", "operacion/bandeja", _ACT + "decisiones_pendientes.json",
        RESUELTO, LISTA_TRAS_FRONTERA, PROPIA, EN_SEMILLA,
        ("decisiones_pendientes._generar_artefacto_sin_lock", "revalidacion_documental", "mobile",
         "acciones_operacionales"),
        ("decisiones_pendientes",),
        ("dataset", "ledger", "investigacion"),
        "Artefacto derivado y regenerable; 'decisiones' vacía es legítima; inexistente es ausencia.",
        ("acciones_operacionales._Contexto._decisiones_sin_bloqueo",),
        "Alto: se regenera desde dataset, ledger e investigación bajo un lock distinto del dataset."),
    FuenteReal(
        "agrupaciones", "AGRUPACIONES_CONFIRMADAS", "operacion/agrupaciones", _ACT + "agrupaciones_viaje.json",
        RESUELTO, LISTA_TRAS_FRONTERA, PROPIA, EN_SEMILLA,
        ("agrupacion_viajes.registrar_agrupacion",), ("agrupaciones_viaje",), ("dataset",),
        "schema_version 1 con lista 'agrupaciones'. Hoy un archivo inexistente equivale a vacío "
        "(agrupacion_viajes._leer) y cualquier error a vacío (agrupaciones_activas).",
        ("agrupacion_viajes._leer", "agrupacion_viajes.agrupaciones_activas"),
        "Medio: sin él el reporte cambia de cardinalidad de viajes (699 vs 703 observado en copia)."),
    FuenteReal(
        "investigacion", "REGISTRO_INVESTIGACION", "operacion/investigacion", _ACT + "documentos_en_investigacion.json",
        RESUELTO, LISTA_TRAS_FRONTERA, PROPIA, EN_SEMILLA,
        ("investigacion_documental",), ("decisiones_pendientes",), ("evidencia", "bandeja"),
        "Lista 'registros' (vacía legítima). Hoy ilegible o inexistente devuelve registro vacío (leer_registro).",
        ("investigacion_documental.leer_registro",),
        "Medio: su vigencia depende del SHA-256 de la evidencia documental."),
    FuenteReal(
        "cuarentena", "CUARENTENA", "operacion/cuarentena", None,
        SIN_ALMACEN_PROPIO, DECLARAR_CERO, PROPIA, NO_APLICA, (), (), ("investigacion",),
        "La cuarentena operacional es el estado EN_INVESTIGACION dentro de REGISTRO_INVESTIGACION. "
        "reproceso_cuarentena usa un --workspace elegido por el operador (no es estado de la generación) "
        "y estado_confirmado tiene una cuarentena local de custodia (LOCALAPPDATA).",
        (), "Ninguno propio."),
    FuenteReal(
        "evidencia", "EVIDENCIA_DOCUMENTAL", "evidencia/<sha256(documento)>/<rol>/<sha256 contenido>",
        "operacion/{entradas/<lote>,mobile/envios/<envio_id>,evidencia_pdf,evidencia_orientada,evidencia_resuelta/<entrada>}/<archivo>",
        RESUELTO, BLOQUEADA, PROPIA, FUERA_DE_SEMILLA,
        ("externo:Desktop atlas:procesar-imagenes (Electron)", "mobile.RepositorioEnviosMobile", "ingesta_pdf",
         "orientacion_documental", "evidencia_documental.mover_evidencia_resuelta_sin_revision_pendiente",
         "evidencia_documental.purgar_evidencia_resuelta_vencida"),
        ("evidencia_documental", "evidencias_adicionales"),
        ("dataset", "relecturas", "evidencias_adicionales_pdf"),
        "Se resuelve por documento.archivo en orden Mobile, relectura vigente, lotes de entradas, "
        "depósito resuelto: NO_ENCONTRADA y PURGADA son explícitas. 0 sólo si el dataset no referencia evidencia.",
        ("evidencia_documental.resolver_ruta_evidencia",),
        "Alto: binarios fuera de la semilla; Desktop (Electron) escribe fuera del hook de custodia; "
        "se mueven a evidencia_resuelta y se purgan a los 30 días.",
        "Representación resuelta en el descriptor v2 (rol documental, documento e identidad verificable). "
        "Siguen bloqueando la integración: binarios fuera de custodia; inventario derivado de dataset "
        "(archivo, evidencia_documentos_relacionados) y relecturas; límite Cloud de 1000 objetos; "
        "movimientos/purgas sin coordinación con la frontera."),
    FuenteReal(
        "relecturas", "EVIDENCIA_DOCUMENTAL", "evidencia/registro-relecturas", "operacion/relecturas_documentales.json",
        RESUELTO, BLOQUEADA, PROPIA, FUERA_DE_SEMILLA,
        ("evidencia_documental.registrar_relectura",), ("evidencia_documental",), ("evidencia",),
        "Inexistente o ilegible se trata como registro vacío (leer_registro_relecturas).",
        ("evidencia_documental.leer_registro_relecturas",),
        "Medio: decide cuál foto es la evidencia vigente de un documento.",
        "Fuera de la semilla de custodia (operacion/, no operacion/actual).", rol="registro-relecturas"),
    FuenteReal(
        "evidencias_adicionales_pdf", "EVIDENCIA_DOCUMENTAL", "evidencia/pdf/evidencias-adicionales",
        "operacion/evidencia_pdf/evidencias_adicionales.json",
        RESUELTO, BLOQUEADA, PROPIA, FUERA_DE_SEMILLA,
        ("ingesta_pdf.registrar_evidencia_adicional",), ("evidencias_adicionales",), ("dataset", "evidencia"),
        "Inexistente o ilegible se trata como lista vacía (leer_evidencias_adicionales).",
        ("ingesta_pdf.leer_evidencias_adicionales",),
        "Medio: asocia páginas PDF a documentos existentes sin fila propia.",
        "Fuera de la semilla de custodia (operacion/evidencia_pdf).", rol="registro-evidencias-adicionales"),
    *(FuenteReal(
        f"catalogo_{nombre}", "CATALOGO", f"catalogos/{nombre.replace('_', '-')}", _CAT + f"{nombre}.json",
        RESUELTO, LISTA_TRAS_FRONTERA, PROPIA, EN_SEMILLA, escritores, locks, (),
        "Archivo de catálogo obligatorio: inexistente es ausencia (fuente_catalogos exige los requeridos).",
        lectores, riesgo, rol=nombre)
      # Escritores verificados en atlas_core; puede haber otros no auditados.
      for nombre, escritores, locks, lectores, riesgo in (
          ("choferes", ("catalogos.cambiar_estado_chofer",), ("choferes",),
           ("equipo_operacional.ResolutorEquipoOperacional",), "Medio: lleva FLAG_ASIGNACION_VARIABLE."),
          ("vehiculos", ("catalogo_vehiculos.confirmar_vehiculo", "catalogo_vehiculos.asociar_chofer_a_vehiculo_confirmado"),
           ("catalogo_vehiculos",), ("equipo_operacional.ResolutorEquipoOperacional",),
           "Alto: contiene también las asignaciones chofer-vehículo."),
          ("clientes", ("catalogo_clientes",), ("catalogo_clientes",), (), "Bajo."),
          ("empresas", ("externo:sin escritor identificado en atlas_core",), (), (), "Bajo."),
          ("destinos_maestros", ("catalogo_destinos",), ("catalogo_destinos",), (), "Medio."),
          ("plantas", ("externo:sin escritor identificado en atlas_core",), (), (), "Bajo."),
          ("rutas", ("externo:sin escritor identificado en atlas_core",), (), (), "Bajo."),
          ("obras_destinos", ("catalogo_obras_destinos",), ("obras_destinos",), (), "Medio."),
          ("incidencias_documentales", ("incidencias_documentales",), ("incidencias_documentales",), (), "Medio."),
      )),
    FuenteReal(
        "geografia", "CATALOGO", "global/geografia-chile", "catalogos_privados/geografia_chile.json",
        RESUELTO, LISTA_TRAS_FRONTERA, GLOBAL, VERSIONADA_EN_CODIGO, ("externo:repositorio Motor",), (), (),
        "Versionado en el repositorio (atlas_core/geografia/cl.py); ausente es error de instalación.",
        (), "Bajo: cambia con el código, no con la operación.", rol="geografia_chile"),
    FuenteReal(
        "asignaciones", "ASIGNACIONES", "derivacion/asignaciones", None,
        SIN_ALMACEN_PROPIO, DEPENDENCIAS_DECLARADAS, PROPIA, NO_APLICA, (), (),
        ("catalogo_vehiculos", "catalogo_choferes", "ledger"),
        "No hay archivo propio: asignaciones_vigentes_con_fecha las deriva de las evidencias "
        "CONFIRMACION_HUMANA con rut_chofer_asociado de vehiculos.json, más FLAG_ASIGNACION_VARIABLE "
        "de choferes.json y decisiones del ledger.",
        ("equipo_operacional.ResolutorEquipoOperacional",),
        "Alto: derivado de tres fuentes; cualquier error de lectura anula la regla general. En v2 es la "
        "derivación ASIGNACIONES (vehiculos, choferes, ledger), sin objeto propio ni confirmación humana."),
)

# Ranura de la derivación ASIGNACIONES -> clave de la fila del contrato que la satisface.
RANURAS_ASIGNACIONES = {"vehiculos": "catalogo_vehiculos", "choferes": "catalogo_choferes", "ledger": "ledger"}

# Archivos reales observados que la tabla de tipos v1 no clasifica. No se
# incluyen en FUENTES: decidir si las precondiciones del preview los leen.
FUERA_DE_TABLA_V1: tuple[tuple[str, str], ...] = (
    (_ACT + "eventos_operacionales.json", "registro_eventos_operacionales: estadías, devoluciones, dobles vueltas"),
    (_ACT + "pendientes_tecnicos.json", "reconciliacion_estado_derivado: cola técnica de reintentos"),
    (_ACT + "estado_operacion.json", "almacenamiento_portable: manifiesto del reporte vigente"),
    (_ACT + "b1_operador_conversaciones.json", "b1_operador: estado conversacional de B1"),
    (_ACT + "recuperaciones_incrementales.json", "recuperacion_incremental: registro de recuperaciones"),
    (_CAT + "registro_relaciones_operacionales.json", "registro_relaciones_operacionales"),
    (_CAT + "evidencia_entidades.json", "aplicacion_decisiones: catálogo no listado en fuente_catalogos.ARCHIVOS_REQUERIDOS"),
    ("operacion/procesamiento/", "carpeta en la semilla de custodia; contenido no auditado aquí"),
    ("fichas_digitales/", "expediente_digital: fichas de choferes y vehículos; en la semilla de custodia"),
)

_PROHIBIDO_EN_RUTA = ("..", "\\", ":")


# Identidad y roles de evidencia: los define el descriptor v2 (una sola fuente de verdad).
identidad_evidencia = _dg.identidad_evidencia
ROLES_EVIDENCIA = _dg.ROLES_EVIDENCIA_DOCUMENTO


def fuentes_por_tipo() -> dict[str, tuple[FuenteReal, ...]]:
    salida: dict[str, list[FuenteReal]] = {}
    for f in FUENTES:
        salida.setdefault(f.tipo, []).append(f)
    return {t: tuple(v) for t, v in salida.items()}


def validar_contrato() -> list[str]:
    """Problemas internos del contrato (vacío si es coherente). Puro."""
    problemas: list[str] = []
    claves = [f.clave for f in FUENTES]
    identidades = [f.identidad for f in FUENTES if "<" not in f.identidad]
    rutas = [f.ruta for f in FUENTES if f.ruta and "<" not in f.ruta and "{" not in f.ruta]
    for nombre, valores in (("clave", claves), ("identidad", identidades), ("ruta", rutas)):
        repetidos = sorted({v for v in valores if valores.count(v) > 1})
        if repetidos:
            problemas.append(f"{nombre} repetida: {repetidos}")
    conocidas = set(claves)
    for f in FUENTES:
        if f.mapeo not in MAPEOS or f.integracion not in INTEGRACIONES or f.custodia not in CUSTODIAS:
            problemas.append(f"{f.clave}: estado desconocido")
        if f.empresa not in (PROPIA, GLOBAL):
            problemas.append(f"{f.clave}: empresa {f.empresa!r}")
        if f.ruta and (f.ruta.startswith("/") or any(p in f.ruta for p in _PROHIBIDO_EN_RUTA)):
            problemas.append(f"{f.clave}: ruta no relativa {f.ruta!r}")
        if f.integracion == BLOQUEADA and not f.bloqueo:
            problemas.append(f"{f.clave}: bloqueada sin motivo")
        if f.integracion == LISTA_TRAS_FRONTERA and f.mapeo != RESUELTO:
            problemas.append(f"{f.clave}: lista sin mapeo resuelto")
        if f.integracion == DECLARAR_CERO and (f.mapeo != SIN_ALMACEN_PROPIO or f.ruta is not None):
            problemas.append(f"{f.clave}: declarar cero exige no tener almacén propio")
        if f.integracion == DEPENDENCIAS_DECLARADAS and (f.ruta is not None or f.tipo not in _dg.DERIVACIONES):
            problemas.append(f"{f.clave}: dependencias declaradas exige derivación v2 sin almacén propio")
        if f.tipo == "DECISIONES_HUMANAS" and f.rol not in _dg.ROLES_DECISIONES_HUMANAS:
            problemas.append(f"{f.clave}: rol de decisión humana {f.rol!r}")
        if f.tipo == "CATALOGO" and not f.rol:
            problemas.append(f"{f.clave}: catálogo sin rol")
        if not f.ausencia_vs_vacio:
            problemas.append(f"{f.clave}: sin regla ausencia/vacío")
        for d in f.dependencias:
            if d not in conocidas:
                problemas.append(f"{f.clave}: dependencia desconocida {d!r}")
    return problemas
