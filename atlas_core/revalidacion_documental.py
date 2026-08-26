"""R3.4/R3.6.2: revalidación de resultados documentales YA procesados contra
el estado VIGENTE de los catálogos, sin ejecutar OCR ni volver a extraer
ningún campo.

Resuelve dos casos concretos y generales, cada uno restringido a su propio
motivo -- nunca se mezclan ni se generaliza a una limpieza indiscriminada de
REVISAR:
  - ``OBRA_DESTINO_SIN_CORROBORAR`` queda obsoleto cuando, después de
    generado el dataset, la relación obra<->destino global fue confirmada
    (por la misma guía o por cualquier otra -- ver R3.3.1/R3.4.1).
  - ``PATENTE_SIN_HOMOLOGAR`` (R3.6.2) queda obsoleto cuando TODAS las
    patentes documentales relevantes de la fila (patente_tracto/
    patente_rampla) ya resuelven, de forma inequívoca, contra un vehículo
    CONFIRMADO+ACTIVO del catálogo vigente, con un tipo canónico compatible
    con el rol documental observado -- ver `revalidar_patente_sin_homologar_sin_ocr`.
Ante cualquier duda, ausencia de evidencia o incompatibilidad, la fila se
conserva intacta. El resto de la fila -- todo dato documental -- permanece
byte por byte igual.
"""
from __future__ import annotations

import csv
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from atlas_core.almacenamiento_portable import bloqueo_sesion
from atlas_core.aplicacion_decisiones import (
    resolver_clientes_confirmados_por_ledger,
    resolver_patentes_confirmadas_por_ledger,
)
from atlas_core.catalogo_clientes import CatalogoClientes, normalizar_nombre_cliente
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, normalizar_nombre_obra
from atlas_core.catalogo_plantas import CatalogoPlantas
from atlas_core.catalogo_vehiculos import (
    CatalogoVehiculosAusenteError,
    CatalogoVehiculosCorruptoError,
    VersionCatalogoVehiculosDesconocidaError,
    Vehiculo,
    VehiculoDuplicadoError,
    cargar_catalogo_vehiculos,
    normalizar_patente_vehiculo,
)
from atlas_core.catalogos import buscar_chofer_por_nombre_exacto, cargar_catalogo_json
from atlas_core.extractor import _patente_valida
from atlas_core.incidencias_documentales import (
    TIPO_RUT_DOCUMENTAL_INVALIDO,
    TIPO_TRANSPORTE_AUSENTE_DOCUMENTAL,
    VALOR_CANONICO_CAMPO_REQUERIDO,
    VALOR_CANONICO_RUT_NO_CONFIRMADO,
    VALOR_DOCUMENTAL_CAMPO_AUSENTE,
    AlmacenIncidenciasDocumentales,
)
from atlas_core.modelos import EstadoValidacion
from atlas_core.procesamiento_masivo import (
    COLUMNAS,
    MOTIVOS_NO_BLOQUEANTES,
    MotivoRevisionDocumento,
    _combinar_fecha_hora,
    _parsear_fecha_dd_mm_yyyy,
)
from atlas_core.reporte_viajes import generar_reporte_viajes
from atlas_core.rutas.modelos import EstadoRuta
from atlas_core.telemetria.enriquecimiento import enriquecer_documento_con_telemetria
from atlas_core.telemetria.modelos import EstadoSeleccionRecorrido
from atlas_core.telemetria.proveedor import ProveedorTelemetriaSoloCache
from atlas_core.telemetria.repositorio import RepositorioTelemetria
from atlas_core.telemetria.seleccion_recorrido import (
    ORIGEN_GPS_CONFIRMADO,
    ORIGEN_GPS_CONFLICTO,
    ORIGEN_GPS_ESTADIA_SIN_PLANTA,
    ORIGEN_GPS_NO_DETERMINADO,
)
from atlas_core.telemetria.servicio import ServicioTelemetria
from atlas_core.validadores import rut_documentalmente_confirmado_invalido, validar_rut_chileno

SEPARADOR_MOTIVOS = " | "
_AUSENTES = {"", "No encontrado"}
_TIPO_TRACTO = "TRACTO"
_TIPO_CARRO = "CARRO"
_TIPO_CAMION_RIGIDO = "CAMION_RIGIDO"
_ERRORES_CATALOGO_VEHICULOS = (
    CatalogoVehiculosAusenteError,
    CatalogoVehiculosCorruptoError,
    VersionCatalogoVehiculosDesconocidaError,
    VehiculoDuplicadoError,
    OSError,
    ValueError,
)


def derivar_estado_ruta_tras_cambio_origen(fila: Mapping[str, object]) -> dict[str, str]:
    """Bloque OBSERVABILIDAD D1 -- deriva `estado_ruta`/`motivo_ruta` desde
    el estado REAL ya persistido (origen + destino), sin llamar ORS ni
    Onelogis. Corrige el hallazgo real (464717/464522): un origen resuelto
    DESPUÉS de que `motivo_ruta` quedó fijado en un texto relacionado a
    origen (por `revalidar_telemetria_sin_ocr` o por una confirmación
    humana de `ORIGEN_NO_CONFIRMADO`, ninguna de las dos toca estas dos
    columnas) deja esas columnas describiendo un problema que ya no
    existe -- y, peor, oculta que el destino de ese mismo documento
    también puede seguir bloqueado (enmascaramiento ya conocido).

    Función pura: recibe una fila y devuelve sólo los campos que deberían
    cambiar (`{}` si no hay nada que corregir) -- quien llama decide si
    y cómo fusionarlos. Reglas, en orden:
    - Si el origen sigue sin determinar: no hay nada que derivar -- el
      bloqueo real HOY es el origen, el texto ya es correcto tal cual.
    - Si ya existe una ruta calculada (`distancia_km` no vacío): no hay
      nada que derivar -- ya está correcto.
    - Si el origen ya está determinado pero el destino todavía no
      (`estado_entrega` distinto de `RESUELTO`): el texto pasa a
      expresar el bloqueo de DESTINO -- nunca inventa el detalle exacto
      (para eso habría que volver a geocodificar, fuera de alcance
      aquí); se deriva directamente de `estado_entrega`, que ya es la
      fuente de verdad confiable de si el destino está resuelto."""
    if not str(fila.get("planta_origen_nombre", "")).strip():
        return {}
    if str(fila.get("distancia_km", "")).strip():
        return {}
    estado_entrega = str(fila.get("estado_entrega", "")).strip()
    if not estado_entrega or estado_entrega == "RESUELTO":
        return {}
    return {"estado_ruta": "REQUIERE_REVISION", "motivo_ruta": f"DESTINO_{estado_entrega}"}


def _leer_filas(ruta_csv: Path) -> list[dict[str, str]]:
    with ruta_csv.open("r", newline="", encoding="utf-8-sig") as archivo:
        lector = csv.DictReader(archivo, delimiter=";")
        if lector.fieldnames != COLUMNAS:
            raise ValueError(
                "El dataset tiene un esquema incompatible; se esperaba el encabezado oficial."
            )
        return list(lector)


def _escribir_filas_completas(ruta_csv: Path, filas: list[dict[str, str]]) -> None:
    temporal: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", newline="", encoding="utf-8-sig", dir=ruta_csv.parent,
            prefix=f".{ruta_csv.name}.", suffix=".tmp", delete=False,
        ) as archivo:
            temporal = Path(archivo.name)
            escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";", extrasaction="ignore")
            escritor.writeheader()
            escritor.writerows(filas)
            archivo.flush()
            os.fsync(archivo.fileno())
        os.replace(temporal, ruta_csv)
    except OSError:
        if temporal is not None:
            temporal.unlink(missing_ok=True)
        raise


def resolver_obras_resueltas_por_ledger(ruta_ledger: str | Path) -> set[str]:
    """R4.9 -- índice de solo lectura del ledger: `numero_guia` de todo
    documento con AL MENOS una aplicación TERMINAL de `OBRA_DESCONOCIDA`
    (`REGISTRAR`/`NO_REGISTRAR`) o `DESTINO_SIN_CONFIRMAR`
    (`CONFIRMAR`/`NO_CONFIRMAR`) -- cualquiera sea el resultado, un humano
    ya revisó y decidió sobre la obra/destino de ESE documento exacto.

    Necesario porque `REGISTRAR` sin destino documental capturado (CASO C
    de `decision_destino_para_obra_registrada`: el documento nunca trajo
    un destino que preguntar) es, por diseño, terminal -- no genera ninguna
    decisión siguiente. Sin este índice, `OBRA_DESTINO_SIN_CORROBORAR`
    quedaba fijado para siempre en esa fila aunque la obra ya estuviera
    registrada y no hubiera ninguna pregunta pendiente que un humano
    pudiera responder -- caso real 472037 (`REGISTRAR` de "ING Y CONST
    FUNDAMENTA SPA", sin `despachar_a_crudo`)."""
    guias: set[str] = set()
    try:
        ledger = json.loads(Path(ruta_ledger).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return guias
    terminales = {
        ("OBRA_DESCONOCIDA", "REGISTRAR"), ("OBRA_DESCONOCIDA", "NO_REGISTRAR"),
        ("DESTINO_SIN_CONFIRMAR", "CONFIRMAR"), ("DESTINO_SIN_CONFIRMAR", "NO_CONFIRMAR"),
    }
    for aplicacion in ledger.get("aplicaciones", []):
        if (aplicacion.get("tipo"), aplicacion.get("accion")) not in terminales:
            continue
        numero_guia = str((aplicacion.get("documento") or {}).get("numero_guia", ""))
        if numero_guia:
            guias.add(numero_guia)
    return guias


def revalidar_obra_destino_sin_ocr(
    *, ruta_dataset: str | Path, carpeta_catalogos: str | Path, ruta_ledger: str | Path | None = None,
) -> dict[str, object]:
    """Relee cada fila del dataset y reevalúa ÚNICAMENTE el motivo
    ``OBRA_DESTINO_SIN_CORROBORAR`` contra `resolver_obra_destino_confirmada_global`
    (sin cliente_id -- ver R3.4/R3.3.1). Si ahora resuelve, retira el motivo
    de esa fila y recalcula `indicador_revision`; nunca toca ningún otro
    campo. No ejecuta OCR ni vuelve a extraer nada -- sólo lee el dataset ya
    persistido y los catálogos vigentes. Se abstiene fila por fila ante
    cualquier duda (obra ausente/"No encontrado", error de catálogo, etc.).

    R4.8 -- además, retira el motivo cuando el texto de `obra_destino` de
    ESA misma fila normaliza EXACTO (sin fuzzy, misma comparación que ya
    usa `detectar_decisiones_documento`) al `cliente` de esa misma fila:
    "es el mismo hecho documental dos veces, no dos entidades" -- Motor ya
    reconoce este caso en detección (se abstiene de generar una pregunta,
    ver el bloque `claves_cliente`/`pass` de `detectar_decisiones_documento`),
    pero antes de este fix el motivo documental seguía fijado en el CSV sin
    ninguna vía para retirarse -- caso real 464981 (obra_destino ==
    cliente == "AMERICAN SCREW CHILE SPA"). Comparación puramente textual
    dentro del mismo documento, sin consultar catálogo -- no hace falta: si
    ambos campos ya dicen lo mismo, no hay identidad que corroborar.

    R4.9 -- `ruta_ledger` (opcional, compatible hacia atrás): si YA hay una
    aplicación terminal de obra/destino para ESTE `numero_guia` exacto (ver
    `resolver_obras_resueltas_por_ledger`), el motivo se retira aunque no
    exista relación destino CONFIRMADA -- un humano ya revisó este
    documento y no queda ninguna pregunta pendiente que responder."""
    ruta = Path(ruta_dataset)
    carpeta = Path(carpeta_catalogos)
    catalogo_obras = CatalogoObrasDestinos(
        ruta=carpeta / "obras_destinos.json",
        ruta_clientes=carpeta / "clientes.json",
        ruta_destinos=carpeta / "destinos_maestros.json",
    )
    motivo_objetivo = MotivoRevisionDocumento.OBRA_DESTINO_SIN_CORROBORAR.value
    guias_resueltas_ledger = (
        resolver_obras_resueltas_por_ledger(Path(ruta_ledger)) if ruta_ledger is not None else set()
    )

    with bloqueo_sesion(ruta.parent, "revalidacion_dataset"):
        filas = _leer_filas(ruta)
        guias_actualizadas: list[str] = []
        for fila in filas:
            motivos = [m for m in fila.get("motivos_revision_documento", "").split(SEPARADOR_MOTIVOS) if m]
            if motivo_objetivo not in motivos:
                continue
            obra_documental = str(fila.get("obra_destino", "")).strip()
            if obra_documental in _AUSENTES:
                continue
            numero_guia = str(fila.get("numero_guia", ""))
            cliente_documental = str(fila.get("cliente", "")).strip()
            mismo_hecho_que_cliente = (
                cliente_documental not in _AUSENTES
                and normalizar_nombre_obra(obra_documental) == normalizar_nombre_obra(cliente_documental)
            )
            ya_revisado_por_humano = numero_guia in guias_resueltas_ledger
            if not mismo_hecho_que_cliente and not ya_revisado_por_humano:
                try:
                    resuelto = catalogo_obras.resolver_obra_destino_confirmada_global(
                        nombre_obra=obra_documental
                    )
                except (OSError, ValueError):
                    continue
                if resuelto is None:
                    continue
            motivos = [m for m in motivos if m != motivo_objetivo]
            fila["motivos_revision_documento"] = SEPARADOR_MOTIVOS.join(motivos)
            fila["indicador_revision"] = (
                "REVISAR" if any(m not in MOTIVOS_NO_BLOQUEANTES for m in motivos) else "OK"
            )
            guias_actualizadas.append(str(fila.get("numero_guia", "")))
        if guias_actualizadas:
            _escribir_filas_completas(ruta, filas)

    return {"filas_totales": len(filas), "guias_actualizadas": guias_actualizadas}


def revalidar_cliente_sin_corroborar_sin_ocr(
    *, ruta_dataset: str | Path, ruta_ledger: str | Path,
) -> dict[str, object]:
    """R4.8: relee cada fila del dataset y reevalúa ÚNICAMENTE el motivo
    ``CLIENTE_SIN_CORROBORAR`` contra el ledger (`resolver_clientes_confirmados_por_ledger`)
    -- sin OCR, sin volver a extraer nada, sin tocar catálogos. Este motivo
    (documento sin RUT de cliente corroborable) nunca lo puede resolver un
    recálculo automático por sí solo -- la única forma de que deje de ser
    válido es que un humano confirme explícitamente la identidad candidata
    (`CLIENTE_CANDIDATO`/`CONFIRMAR`, ver `aplicar_decision_obra`). Retira
    el motivo de una fila sólo cuando el ledger tiene una confirmación para
    ESE `numero_guia` exacto (nunca por coincidencia de texto con otra
    fila) y el `cliente` ya persistido en esa fila coincide (comparación
    exacta normalizada, sin fuzzy -- la confirmación humana ya hizo el
    trabajo difuso una sola vez) con el nombre canónico confirmado. Se
    abstiene fila por fila ante cualquier duda."""
    ruta = Path(ruta_dataset)
    motivo_objetivo = MotivoRevisionDocumento.CLIENTE_SIN_CORROBORAR.value
    confirmados_por_guia = resolver_clientes_confirmados_por_ledger(Path(ruta_ledger))

    with bloqueo_sesion(ruta.parent, "revalidacion_dataset"):
        filas = _leer_filas(ruta)
        guias_actualizadas: list[str] = []
        for fila in filas:
            motivos = [m for m in fila.get("motivos_revision_documento", "").split(SEPARADOR_MOTIVOS) if m]
            if motivo_objetivo not in motivos:
                continue
            numero_guia = str(fila.get("numero_guia", ""))
            valor_canonico_confirmado = confirmados_por_guia.get(numero_guia)
            if valor_canonico_confirmado is None:
                continue
            cliente_documental = str(fila.get("cliente", "")).strip()
            if cliente_documental in _AUSENTES:
                continue
            if normalizar_nombre_cliente(cliente_documental) != normalizar_nombre_cliente(valor_canonico_confirmado):
                continue
            motivos = [m for m in motivos if m != motivo_objetivo]
            fila["motivos_revision_documento"] = SEPARADOR_MOTIVOS.join(motivos)
            fila["indicador_revision"] = (
                "REVISAR" if any(m not in MOTIVOS_NO_BLOQUEANTES for m in motivos) else "OK"
            )
            guias_actualizadas.append(numero_guia)
        if guias_actualizadas:
            _escribir_filas_completas(ruta, filas)

    return {"filas_totales": len(filas), "guias_actualizadas": guias_actualizadas}


def revalidar_cliente_ausente_por_obra_coincidente_sin_ocr(
    *, ruta_dataset: str | Path, carpeta_catalogos: str | Path,
) -> dict[str, object]:
    """Bloque R13 -- caso real 472238/472239 (TORRES OCARANZA LTDA): el
    campo `cliente` quedó genuinamente vacío en la extracción original
    (`CLIENTE_AUSENTE`, nada que corroborar), pero `obra_destino` de ESA
    MISMA fila -- resuelto por catálogo (`CATALOGO_OBRA_DESTINO`) -- ya
    normaliza EXACTO (sin fuzzy) contra un cliente CONFIRMADO/ACTIVO del
    catálogo: el mismo patrón de autodespacho ("cliente == obra") que
    `revalidar_obra_destino_sin_ocr` ya reconoce en sentido inverso (obra
    == cliente retira `OBRA_DESTINO_SIN_CORROBORAR`), aplicado aquí para
    RELLENAR un cliente genuinamente ausente -- nunca para corregir uno
    ya presente mal leído (eso es `CLIENTE_SIN_CORROBORAR`, dominio
    distinto). Sin esa coincidencia exacta, se abstiene -- nunca inventa
    un cliente a partir de una obra distinta."""
    ruta = Path(ruta_dataset)
    carpeta = Path(carpeta_catalogos)
    motivo_objetivo = MotivoRevisionDocumento.CLIENTE_AUSENTE.value
    try:
        clientes_confirmados = {
            normalizar_nombre_cliente(c.razon_social): c
            for c in CatalogoClientes(carpeta / "clientes.json").listar()
            if c.estado_calidad == "CONFIRMADO" and c.estado_vigencia == "ACTIVO"
        }
    except (OSError, ValueError):
        clientes_confirmados = {}

    with bloqueo_sesion(ruta.parent, "revalidacion_dataset"):
        filas = _leer_filas(ruta)
        guias_actualizadas: list[str] = []
        for fila in filas:
            motivos = [m for m in fila.get("motivos_revision_documento", "").split(SEPARADOR_MOTIVOS) if m]
            if motivo_objetivo not in motivos:
                continue
            cliente_actual = str(fila.get("cliente", "")).strip()
            if cliente_actual not in _AUSENTES:
                continue  # ya no está genuinamente ausente -- otra vía ya lo resolvió
            obra_documental = str(fila.get("obra_destino", "")).strip()
            if obra_documental in _AUSENTES:
                continue
            cliente_coincidente = clientes_confirmados.get(normalizar_nombre_cliente(obra_documental))
            if cliente_coincidente is None:
                continue
            fila["cliente"] = cliente_coincidente.razon_social
            motivos = [m for m in motivos if m != motivo_objetivo]
            fila["motivos_revision_documento"] = SEPARADOR_MOTIVOS.join(motivos)
            fila["indicador_revision"] = (
                "REVISAR" if any(m not in MOTIVOS_NO_BLOQUEANTES for m in motivos) else "OK"
            )
            guias_actualizadas.append(str(fila.get("numero_guia", "")))
        if guias_actualizadas:
            _escribir_filas_completas(ruta, filas)

    return {"filas_totales": len(filas), "guias_actualizadas": guias_actualizadas}


def _vehiculo_homologado(
    vehiculos_homologables: tuple[Vehiculo, ...], patente_normalizada: str,
) -> Vehiculo | None:
    """Busca, entre los vehículos CONFIRMADO+ACTIVO (o legacy V0, siempre
    homologables), uno cuya patente canónica o alias coincida EXACTAMENTE
    con la patente documental ya normalizada. No corrige OCR ni asume
    ambigüedad -- `_validar_unicidad` del catálogo ya garantiza que un
    alias jamás colisiona con la patente canónica de otro vehículo, así
    que a lo sumo hay una coincidencia."""
    for vehiculo in vehiculos_homologables:
        if vehiculo.patente_canonica == patente_normalizada or patente_normalizada in vehiculo.aliases:
            return vehiculo
    return None


def revalidar_patente_sin_homologar_sin_ocr(
    *, ruta_dataset: str | Path, carpeta_catalogos: str | Path, ruta_ledger: str | Path | None = None,
) -> dict[str, object]:
    """R3.6.2: relee cada fila del dataset y reevalúa ÚNICAMENTE el motivo
    ``PATENTE_SIN_HOMOLOGAR`` contra el estado VIGENTE del catálogo de
    vehículos (sin OCR, sin re-extraer nada). Retira el motivo de una fila
    sólo cuando TODAS las patentes documentales relevantes presentes en esa
    fila (``patente_tracto``/``patente_rampla``) resuelven de forma
    inequívoca contra un vehículo CONFIRMADO+ACTIVO con un tipo canónico
    compatible con el rol documental observado -- misma regla final ya
    validada en R3.6.1:
      - ``patente_rampla`` presente debe resolver a tipo CARRO.
      - ``patente_tracto`` presente, con ``patente_rampla`` también
        presente y resuelta a CARRO, debe resolver a tipo TRACTO.
      - ``patente_tracto`` presente y aislada (sin rampla documental
        relevante) puede resolver a TRACTO o a CAMION_RIGIDO -- ambas
        resuelven el motivo si el vehículo está CONFIRMADO y ACTIVO.

    Bloque CIERRE OPERACIONAL D1 -- ``ruta_ledger`` (opcional, compatible
    hacia atrás): cuando la patente documental NUNCA va a homologar por sí
    sola (p. ej. ``JD6659``, una lectura OCR de una rampla cuya canónica
    real es ``JD8659``, confirmada por `USAR_PATENTE_EXISTENTE`/
    `SELECCIONAR_OTRA_PATENTE`), se consulta el ledger para esa fila/campo
    exactos -- si existe una confirmación humana ya aplicada, se trata
    igual que si la propia canónica confirmada hubiera homologado
    directamente. Caso real que motivó esto: 464265 (Carlos Simón, tracto
    VP6521->VP8521 confirmado por Javier) seguía mostrando
    `PATENTE_SIN_HOMOLOGAR` después de la confirmación -- el valor
    documental jamás iba a homologar solo, la revalidación anterior nunca
    podía resolverlo. Un `NO_REGISTRAR` (p. ej. 464036, error documental
    sin canónica -- ver `_confirmaciones_ledger_por_guia_campo`) NUNCA
    entra en este índice, así que sigue conservando el motivo, tal como
    corresponde a un caso real sin resolución.

    Se abstiene fila por fila ante cualquier duda: patente ausente pero
    relevante sin resolver, catálogo ambiguo/inactivo/no confirmado, tipo
    incompatible con el rol documental, o error de catálogo. Nunca crea
    relación chofer<->vehículo (fuera de alcance de R3.6.2)."""
    ruta = Path(ruta_dataset)
    carpeta = Path(carpeta_catalogos)
    motivo_objetivo = MotivoRevisionDocumento.PATENTE_SIN_HOMOLOGAR.value
    confirmaciones_ledger = (
        resolver_patentes_confirmadas_por_ledger(Path(ruta_ledger)) if ruta_ledger is not None else {}
    )

    with bloqueo_sesion(ruta.parent, "revalidacion_dataset"):
        filas = _leer_filas(ruta)
        guias_actualizadas: list[str] = []
        try:
            catalogo = cargar_catalogo_vehiculos(carpeta / "vehiculos.json")
        except _ERRORES_CATALOGO_VEHICULOS:
            return {"filas_totales": len(filas), "guias_actualizadas": guias_actualizadas}
        vehiculos_homologables = catalogo.homologables()

        for fila in filas:
            motivos = [m for m in fila.get("motivos_revision_documento", "").split(SEPARADOR_MOTIVOS) if m]
            if motivo_objetivo not in motivos:
                continue
            tracto_doc = str(fila.get("patente_tracto", "")).strip()
            rampla_doc = str(fila.get("patente_rampla", "")).strip()
            tracto_presente = tracto_doc not in _AUSENTES
            rampla_presente = rampla_doc not in _AUSENTES
            if not tracto_presente and not rampla_presente:
                continue  # sin ninguna patente documental relevante -> conservar

            numero_guia = str(fila.get("numero_guia", ""))

            if rampla_presente:
                rampla_resuelta = _vehiculo_homologado(
                    vehiculos_homologables, normalizar_patente_vehiculo(rampla_doc)
                )
                if rampla_resuelta is None:
                    canonica = confirmaciones_ledger.get((numero_guia, "patente_rampla", rampla_doc))
                    if canonica:
                        rampla_resuelta = _vehiculo_homologado(vehiculos_homologables, normalizar_patente_vehiculo(canonica))
                if rampla_resuelta is None or rampla_resuelta.tipo != _TIPO_CARRO:
                    continue  # rampla sin resolver o tipo incompatible -> conservar

            if tracto_presente:
                tracto_resuelto = _vehiculo_homologado(
                    vehiculos_homologables, normalizar_patente_vehiculo(tracto_doc)
                )
                if tracto_resuelto is None:
                    canonica = confirmaciones_ledger.get((numero_guia, "patente_tracto", tracto_doc))
                    if canonica:
                        tracto_resuelto = _vehiculo_homologado(vehiculos_homologables, normalizar_patente_vehiculo(canonica))
                if tracto_resuelto is None:
                    continue  # tracto sin resolver -> conservar
                tipos_compatibles = (
                    (_TIPO_TRACTO,) if rampla_presente
                    else (_TIPO_TRACTO, _TIPO_CAMION_RIGIDO)
                )
                if tracto_resuelto.tipo not in tipos_compatibles:
                    continue  # tipo canónico incompatible con el rol documental -> conservar

            motivos = [m for m in motivos if m != motivo_objetivo]
            fila["motivos_revision_documento"] = SEPARADOR_MOTIVOS.join(motivos)
            fila["indicador_revision"] = (
                "REVISAR" if any(m not in MOTIVOS_NO_BLOQUEANTES for m in motivos) else "OK"
            )
            guias_actualizadas.append(str(fila.get("numero_guia", "")))
        if guias_actualizadas:
            _escribir_filas_completas(ruta, filas)

    return {"filas_totales": len(filas), "guias_actualizadas": guias_actualizadas}


def revalidar_telemetria_sin_ocr(
    *, ruta_dataset: str | Path, carpeta_catalogos: str | Path,
    proveedor_nombre: str = "onelogis",
    servicio_telemetria: ServicioTelemetria | None = None,
) -> dict[str, object]:
    """Bloque ONELOGIS/DESTINO/KM -- conecta a filas YA procesadas la
    telemetría GPS que ya existe en `telemetria_cache.json` pero nunca
    llegó a persistirse en el dataset (causa raíz documentada en
    `docs/BITACORA_TECNICA_CRONOLOGICA.md`: un reprocesamiento posterior
    de un documento en particular, sin telemetría conectada, puede
    sobrescribir su fila con columnas de telemetría vacías aunque el
    proveedor ya tenga sus trips en caché). Sin OCR, sin volver a extraer
    ningún campo documental -- sólo lee el dataset y la caché de
    telemetría ya persistidos.

    Nunca llama a la red: usa `ProveedorTelemetriaSoloCache`, que se
    abstiene con `SIN_CONEXION` ante cualquier consulta no ya resuelta
    por la caché -- una fila cuya patente/fecha no tiene ningún trip
    cacheado queda intacta (abstención real, nunca inventa telemetría ni
    persiste un estado engañoso). Idempotente: una fila que ya tiene
    `estado_telemetria` poblado (por esta función o por el procesamiento
    original) se conserva tal cual, nunca se reconsulta.

    Deliberadamente NO recalcula ruta/kilómetros (nunca llama a ORS):
    sólo actualiza las columnas de telemetría y, si la telemetría
    confirma o descarta origen por GPS, las columnas de planta de origen
    -- misma regla ya vigente en `procesamiento_masivo.procesar_archivo`
    (Bloque OPERACIÓN REAL R1/R1.1: GPS inequívoco gana siempre; sin
    confirmación GPS con telemetría que sí corrió sobre datos reales, el
    origen documental heredado se descarta explícitamente, nunca se
    conserva en silencio). Si el origen cambia y la fila YA traía una
    ruta/km calculados con el origen ANTERIOR (posiblemente la planta
    matriz documental, no la real), esos campos se INVALIDAN (nunca se
    deja un kilometraje que ya no corresponde al origen vigente) pero NO
    se recalculan -- eso sí requeriría ORS, fuera de alcance de este
    bloque; queda `estado_ruta=REQUIERE_REVISION`,
    `motivo_ruta=ORIGEN_ACTUALIZADO_PENDIENTE_RECALCULO_RUTA`. Si el
    origen no cambia (o no había ruta previa), `distancia_km`/
    `estado_ruta`/`motivo_ruta`/`proveedor_ruta` quedan intactos.

    `servicio_telemetria` (opcional, uso en tests): inyecta un
    `ServicioTelemetria` ya construido en vez del `ProveedorTelemetriaSoloCache`
    + `RepositorioTelemetria(carpeta_catalogos/telemetria_cache.json)`
    predeterminado -- permite verificar en tests que la caché real nunca
    se toca de más."""
    ruta = Path(ruta_dataset)
    carpeta = Path(carpeta_catalogos)
    servicio = servicio_telemetria or ServicioTelemetria(
        ProveedorTelemetriaSoloCache(nombre=proveedor_nombre),
        RepositorioTelemetria(carpeta / "telemetria_cache.json"),
    )
    plantas_catalogo = CatalogoPlantas(carpeta / "plantas.json").listar()

    with bloqueo_sesion(ruta.parent, "revalidacion_dataset"):
        filas = _leer_filas(ruta)
        guias_actualizadas: list[str] = []
        for fila in filas:
            # Bloque ORIGEN D1 -- una confirmación humana explícita
            # (`atlas_core.aplicacion_decisiones.FUENTE_ORIGEN_CONFIRMACION_HUMANA`)
            # nunca se sobrescribe silenciosamente: se comprueba ANTES de
            # cualquier otro chequeo, incluso si `estado_telemetria` llegara
            # vacío por cualquier motivo futuro. Sólo una NUEVA decisión
            # humana explícita puede cambiarla -- nunca un reprocesamiento
            # automático.
            if str(fila.get("origen_determinado_por", "")).strip() == "CONFIRMACION_HUMANA":
                continue
            if str(fila.get("estado_telemetria", "")).strip():
                continue  # ya tiene telemetría -- idempotente, no se reconsulta

            patente = str(fila.get("patente_tracto", "")).strip().upper()
            if not _patente_valida(patente):
                continue
            fecha_doc = _parsear_fecha_dd_mm_yyyy(fila.get("fecha"))
            if fecha_doc is None:
                continue
            hora_entrada_dt = _combinar_fecha_hora(fecha_doc, fila.get("hora_entrada_aza"))
            hora_salida_dt = _combinar_fecha_hora(fecha_doc, fila.get("hora_salida_aza"))
            if hora_entrada_dt is None and hora_salida_dt is None:
                continue

            # Chequeo de caché ANTES de invocar el enriquecimiento: si no
            # hay ningún trip cacheado para esta patente/fecha exacta, se
            # abstiene sin dejar rastro -- nunca persiste un estado
            # sintético (p. ej. SIN_CONEXION) que pueda confundirse con un
            # fallo real de conectividad.
            if servicio.repositorio.buscar_viajes(
                servicio.proveedor.nombre, patente, fecha_doc, fecha_doc
            ) is None:
                continue

            resultado_gps = enriquecer_documento_con_telemetria(
                servicio=servicio, patente=patente, fecha=fecha_doc,
                hora_entrada=hora_entrada_dt, hora_salida=hora_salida_dt,
                plantas=plantas_catalogo,
            )
            campos = resultado_gps.campos
            for campo, valor in campos.items():
                fila[campo] = valor

            planta_origen_id_previo = str(fila.get("planta_origen_id", "")).strip()
            planta_gps_id = campos.get("planta_gps_id", "")
            origen_cambio = False
            if campos.get("origen_gps") == ORIGEN_GPS_CONFIRMADO and planta_gps_id:
                origen_cambio = planta_gps_id != planta_origen_id_previo
                fila["planta_origen_id"] = planta_gps_id
                fila["planta_origen_nombre"] = campos.get("planta_gps_nombre", "")
                fila["origen_determinado_por"] = "TELEMETRIA_GPS"
                fila["evidencia_origen"] = campos.get("evidencia_telemetria", "") or "GEOCERCA_PLANTA"
            elif (
                campos.get("estado_telemetria") == EstadoSeleccionRecorrido.SELECCIONADO.value
                and campos.get("origen_gps")
                in (ORIGEN_GPS_CONFLICTO, ORIGEN_GPS_NO_DETERMINADO, ORIGEN_GPS_ESTADIA_SIN_PLANTA)
                and planta_origen_id_previo
            ):
                # Fase R1.1 (ya vigente en procesamiento_masivo): sin
                # confirmación GPS con telemetría que sí corrió sobre datos
                # reales, un origen heredado del documento nunca se
                # conserva en silencio.
                origen_cambio = True
                fila["planta_origen_id"] = ""
                fila["planta_origen_nombre"] = ""
                fila["origen_determinado_por"] = ""
                fila["evidencia_origen"] = campos.get("origen_gps", "")

            # El origen cambió y había una ruta/km ya calculados con el
            # origen ANTERIOR (posiblemente equivocado, p. ej. la planta
            # matriz documental) -- se invalida (nunca se deja un km
            # numérico que ya no corresponde al origen vigente) pero no se
            # recalcula: eso requeriría ORS, explícitamente fuera de
            # alcance de esta revalidación (Bloque ONELOGIS/DESTINO/KM).
            if origen_cambio and str(fila.get("distancia_km", "")).strip():
                fila["distancia_km"] = ""
                fila["duracion_min"] = ""
                fila["proveedor_ruta"] = ""
                fila["estado_ruta"] = "REQUIERE_REVISION"
                fila["motivo_ruta"] = "ORIGEN_ACTUALIZADO_PENDIENTE_RECALCULO_RUTA"
            elif origen_cambio:
                # Bloque OBSERVABILIDAD D1 -- no había ruta que invalidar
                # (el destino nunca se había resuelto), pero si SIGUE sin
                # resolverse tras este cambio de origen, `estado_ruta`/
                # `motivo_ruta` no deben seguir describiendo el origen que
                # ya cambió (caso real 464522: origen resuelto por GPS,
                # motivo_ruta seguía diciendo "sin evidencia GPS" para
                # siempre). Nunca fuerza RUTA_CALCULADA.
                fila.update(derivar_estado_ruta_tras_cambio_origen(fila))

            guias_actualizadas.append(str(fila.get("numero_guia", "")))
        if guias_actualizadas:
            _escribir_filas_completas(ruta, filas)

    return {"filas_totales": len(filas), "guias_actualizadas": guias_actualizadas}


# Bloque FINAL CORE V1 -- caso real 464981: ventana en días para
# considerar un viaje del MISMO vehículo "vecino temporal" -- calibrada
# sobre el caso real (los vecinos GPS-confirmados quedaron a 1-2 días),
# nunca "el patrón habitual del chofer" sin límite temporal.
_VENTANA_DIAS_VECINOS_TEMPORALES = 5


def revalidar_origen_por_vecinos_temporales_gps_sin_ocr(
    *, ruta_dataset: str | Path,
) -> dict[str, object]:
    """Bloque FINAL CORE V1 -- caso real 464981 (SIN_EVIDENCIA_GPS: sin
    trips telemetría en la ventana documental exacta de ESE viaje) --
    "no tener GPS en esa ventana no significa que no se pueda inferir el
    origen": si el MISMO vehículo tiene viajes vecinos (dentro de
    `_VENTANA_DIAS_VECINOS_TEMPORALES`) cuyo origen SÍ fue confirmado
    por GPS (nunca por documento -- ese origen ya es, por diseño del
    resto del sistema, menos confiable que uno GPS-confirmado), y TODOS
    esos vecinos convergen en la MISMA planta, esa planta se acepta como
    hipótesis fuerte -- nunca "el chofer normalmente carga en X" (no hay
    umbral de frecuencia ni promedio: exige convergencia ABSOLUTA entre
    al menos 2 observaciones GPS reales, y CERO vecinos GPS-confirmados
    en desacuerdo). Con una sola observación, sin vecinos, o con
    vecinos que no coinciden entre sí, se abstiene -- la fila queda
    exactamente como estaba (`ORIGEN_NO_DETERMINADO`/`SIN_EVIDENCIA_GPS`
    siguen siendo la causa final honesta).

    Sólo resuelve la PLANTA -- nunca toca ruta/km/tiempo aquí (eso lo
    hace, en la misma pasada de revalidación, `revalidar_ruta_sin_
    destino_calculado_sin_ocr`, que ya sabe reintentar en cuanto
    `planta_origen_id` deja de estar vacío). Sin OCR, sin red -- sólo
    relee el dataset ya persistido."""
    ruta = Path(ruta_dataset)
    with bloqueo_sesion(ruta.parent, "revalidacion_dataset"):
        filas = _leer_filas(ruta)
        gps_confirmados_por_patente: dict[str, list[tuple]] = {}
        for fila in filas:
            if str(fila.get("origen_determinado_por", "")).strip() != "TELEMETRIA_GPS":
                continue
            patente = str(fila.get("patente_tracto", "")).strip().upper()
            planta_id = str(fila.get("planta_origen_id", "")).strip()
            if patente in ("", "NO ENCONTRADO") or not planta_id:
                continue
            fecha = _parsear_fecha_dd_mm_yyyy(fila.get("fecha"))
            if fecha is None:
                continue
            gps_confirmados_por_patente.setdefault(patente, []).append(
                (fecha, planta_id, str(fila.get("planta_origen_nombre", "")), str(fila.get("numero_guia", "")))
            )

        guias_actualizadas: list[str] = []
        for fila in filas:
            if str(fila.get("planta_origen_id", "")).strip():
                continue  # ya tiene origen -- nunca se reinvestiga
            patente = str(fila.get("patente_tracto", "")).strip().upper()
            if patente in ("", "NO ENCONTRADO"):
                continue
            fecha_objetivo = _parsear_fecha_dd_mm_yyyy(fila.get("fecha"))
            if fecha_objetivo is None:
                continue
            vecinos = [
                registro for registro in gps_confirmados_por_patente.get(patente, ())
                if abs((registro[0] - fecha_objetivo).days) <= _VENTANA_DIAS_VECINOS_TEMPORALES
            ]
            plantas_distintas = {registro[1] for registro in vecinos}
            if len(vecinos) < 2 or len(plantas_distintas) != 1:
                continue  # sin convergencia real (o dos plantas plausibles) -- se abstiene
            planta_id, planta_nombre = vecinos[0][1], vecinos[0][2]
            fila["planta_origen_id"] = planta_id
            fila["planta_origen_nombre"] = planta_nombre
            fila["origen_determinado_por"] = "PATRON_VEHICULO_GPS_VECINOS"
            fila["evidencia_origen"] = (
                f"vecinos_gps_confirmados={len(vecinos)};ventana_dias={_VENTANA_DIAS_VECINOS_TEMPORALES};"
                f"guias_vecinas={','.join(sorted({r[3] for r in vecinos}))}"
            )
            guias_actualizadas.append(str(fila.get("numero_guia", "")))
        if guias_actualizadas:
            _escribir_filas_completas(ruta, filas)

    return {"guias_actualizadas": guias_actualizadas}


def revalidar_destino_contra_comuna_documental_sin_ocr(
    *, ruta_dataset: str | Path,
) -> dict[str, object]:
    """Bloque F (R4.10) -- limpieza retroactiva, sin OCR y sin red: releé
    cada fila con `direccion_entrega` YA persistida (de una corrida
    anterior al fix de `resolver_destino_entrega_validado`, que ahora
    aplica estas mismas reglas ANTES de calcular la ruta) y la retira si
    demuestra ser un destino degradado/absurdo -- mismos criterios ya
    usados en vivo, nunca una regla nueva. Nunca vuelve a golpear el
    geocodificador -- trabaja sólo con columnas ya escritas.

    Dos motivos, cada uno restringido a su propia evidencia:
    - `GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL`: el propio
      `despachar_a_crudo` menciona de forma INEQUÍVOCA (exactamente una
      comuna real distinta, nunca varias en conflicto -- ver
      `_comuna_documental_inequivoca`, caso real 472002 "GALVARINO 8501
      QUILICURA": "Galvarino" es la calle, pero también existe una comuna
      real con ese nombre en otra región -- ambigüedad léxica, nunca se
      usa como evidencia) una comuna del catálogo territorial cerrado que
      NO coincide con la localidad geocodificada -- caso real 460807
      ("SAN BERNARDO" documental, sin ninguna otra comuna en el texto, vs
      "Angol" geocodificado).
    - `GEOCODIFICACION_DEMASIADO_GENERICA`: el resultado no trae
      localidad NI región (coincidencia a nivel país, p. ej. la etiqueta
      "Chile" sola) -- nunca un destino operacional útil, sin importar la
      confianza informada. Restringido a filas que NO quedaron
      `RUTA_CALCULADA` (nunca toca una ruta ya completa y confiable) --
      caso real 472008 (misma obra que 460807, degradado a "Chile").

    Cualquiera sea el estado actual (incluso si una corrida anterior a
    este fix llegó a calcular una ruta completa hasta el destino
    contradicho), se retira por completo: nunca se deja un km/tiempo
    calculado hacia un destino ya demostrado incorrecto. Se abstiene fila
    por fila si no hay evidencia demostrable (nunca inventa una)."""
    from atlas_core.rutas.destino_entrega import (
        _comuna_documental_inequivoca, _comunas_territorialmente_compatibles, _texto_normalizado_sin_acentos,
    )

    ruta = Path(ruta_dataset)
    with bloqueo_sesion(ruta.parent, "revalidacion_dataset"):
        filas = _leer_filas(ruta)
        guias_actualizadas: list[str] = []
        for fila in filas:
            direccion = str(fila.get("direccion_entrega", "")).strip()
            if not direccion:
                continue
            localidad = str(fila.get("localidad_entrega", "")).strip()
            region = str(fila.get("region_entrega", "")).strip()
            despachar_a = str(fila.get("despachar_a_crudo", "")).strip()
            estado_ruta_actual = str(fila.get("estado_ruta", "")).strip()

            motivo_rechazo = ""
            if despachar_a and localidad:
                comuna_documental = _comuna_documental_inequivoca(despachar_a)
                if (
                    comuna_documental
                    and _texto_normalizado_sin_acentos(comuna_documental)
                    != _texto_normalizado_sin_acentos(localidad)
                    and not _comunas_territorialmente_compatibles(comuna_documental, localidad)
                ):
                    motivo_rechazo = (
                        "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL: "
                        f"{comuna_documental} != {localidad}"
                    )
            if (
                not motivo_rechazo and not localidad and not region
                and estado_ruta_actual != EstadoRuta.RUTA_CALCULADA.value
            ):
                motivo_rechazo = "GEOCODIFICACION_DEMASIADO_GENERICA"
            if not motivo_rechazo:
                continue

            fila["direccion_entrega"] = ""
            fila["localidad_entrega"] = ""
            fila["region_entrega"] = ""
            fila["distancia_km"] = ""
            fila["duracion_min"] = ""
            fila["estado_ruta"] = EstadoRuta.REQUIERE_REVISION.value
            fila["motivo_ruta"] = motivo_rechazo
            guias_actualizadas.append(str(fila.get("numero_guia", "")))
        if guias_actualizadas:
            _escribir_filas_completas(ruta, filas)

    return {"filas_totales": len(filas), "guias_actualizadas": guias_actualizadas}


def revalidar_destino_operacional_sin_numero_de_calle_sin_ocr(
    *, ruta_dataset: str | Path,
) -> dict[str, object]:
    """Bloque CONFIRMACIÓN D2 -- limpieza retroactiva, sin OCR y sin red,
    hermana de `revalidar_destino_contra_comuna_documental_sin_ocr`: caso
    real 472044 (PUERTA DEL SOL 83 LAS CONDES), donde `direccion_entrega`
    quedó persistida a nivel comuna ("Las Condes, RM, Chile", sin número
    de calle) de una corrida ANTERIOR a Bloque F (que ya impide que un
    candidato rechazado se exponga como destino operacional) -- ese valor
    sobrevivía para siempre a cualquier confirmación humana posterior,
    porque `revalidar_ruta_sin_destino_calculado_sin_ocr` sólo reescribe
    esta columna cuando el MOTIVO cambia (aquí no cambiaba: seguía siendo
    `CONFIANZA_INSUFICIENTE`, una causa técnica ya correcta -- el problema
    era sólo la etiqueta, no el motivo).

    Mismo criterio EXACTO ya usado prospectivamente por
    `_etiqueta_geocodificada_o_texto_documental` (dentro de
    `resolver_destino_entrega`, nunca duplicado aquí): si `despachar_a_
    crudo` trae un número de calle y `direccion_entrega` NO, la etiqueta
    geocodificada es MENOS específica que lo documental -- se retira.
    Nunca inventa un reemplazo: `despachar_a_crudo` (columna separada,
    intacta) sigue siendo la evidencia documental; Desktop ya cae de
    vuelta a ella cuando `direccion_entrega` queda vacía (mismo mecanismo
    que usa ahora mismo para cualquier fila sin ruta calculada).

    A propósito, NUNCA toca `motivo_ruta`/`estado_ruta` -- a diferencia de
    `revalidar_destino_contra_comuna_documental_sin_ocr` (que sí describe
    una causa de rechazo nueva), aquí el motivo YA persistido sigue siendo
    la causa técnica correcta (p. ej. `CONFIANZA_INSUFICIENTE`); cambiarlo
    a algo de `MOTIVOS_DESTINO_NO_RESUELTO` resucitaría una pregunta sobre
    una identidad que un humano ya confirmó -- exactamente lo que este
    bloque existe para evitar."""
    from atlas_core.rutas.destino_entrega import _trae_numero_calle

    ruta = Path(ruta_dataset)
    with bloqueo_sesion(ruta.parent, "revalidacion_dataset"):
        filas = _leer_filas(ruta)
        guias_actualizadas: list[str] = []
        for fila in filas:
            direccion = str(fila.get("direccion_entrega", "")).strip()
            if not direccion:
                continue
            if str(fila.get("estado_ruta", "")).strip() == EstadoRuta.RUTA_CALCULADA.value:
                continue
            despachar_a = str(fila.get("despachar_a_crudo", "")).strip()
            if not (despachar_a and _trae_numero_calle(despachar_a) and not _trae_numero_calle(direccion)):
                continue
            fila["direccion_entrega"] = ""
            fila["localidad_entrega"] = ""
            fila["region_entrega"] = ""
            guias_actualizadas.append(str(fila.get("numero_guia", "")))
        if guias_actualizadas:
            _escribir_filas_completas(ruta, filas)

    return {"filas_totales": len(filas), "guias_actualizadas": guias_actualizadas}


def revalidar_destinos_confirmados_sin_coordenadas_sin_ocr(
    *, carpeta_catalogos: str | Path, proveedor_rutas=None,
) -> dict[str, object]:
    """Bloque RESOLUCIÓN R18 -- causa raíz real de que Vía A (Bloque
    RESOLUCIÓN R16) nunca pudiera desbloquear guías hermanas pese a que
    Javier YA había confirmado la dirección (casos reales 460807/472008
    -- AUSIN SAN BERNARDO; 472073/472163): la confirmación humana de un
    destino (`DESTINO_SIN_CONFIRMAR`/CONFIRMAR, o una reconciliación
    anterior) sólo registra identidad -- nunca geocodifica, así que el
    destino queda `estado_calidad=CONFIRMADO` para siempre SIN
    coordenadas. "¿Es correcta esta dirección?" ya tiene respuesta
    humana real; lo único que falta es un dato que Atlas puede obtener
    solo, sin volver a preguntar nada.

    Geocodifica (con caché, restringido a Chile -- mismo criterio que el
    resto del sistema) cada destino `CONFIRMADO` sin coordenadas, con el
    mismo mecanismo determinista ya calibrado
    (`resolver_destino_entrega_validado` -- nunca lógica nueva). Si
    resuelve con confianza suficiente, persiste latitud/longitud; si no
    resuelve (limitación real del proveedor, ambigüedad, etc.), el
    destino queda exactamente como estaba -- nunca inventa un punto,
    nunca sobreescribe una coordenada ya presente."""
    from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
    from atlas_core.rutas.destino_entrega import ESTADO_RESUELTO, resolver_destino_entrega_validado

    carpeta = Path(carpeta_catalogos)
    if proveedor_rutas is None:
        from atlas_core.procesamiento_masivo import PAIS_OPERACION_PREDETERMINADO
        from atlas_core.rutas.cache_geocodificacion import (
            ProveedorRutasConCacheGeocodificacion,
            RepositorioCacheGeocodificacion,
        )
        from atlas_core.rutas.openrouteservice import OpenRouteService

        proveedor_rutas = ProveedorRutasConCacheGeocodificacion(
            OpenRouteService(pais=PAIS_OPERACION_PREDETERMINADO), RepositorioCacheGeocodificacion(),
        )
    catalogo = CatalogoDestinos(carpeta / "destinos_maestros.json", ruta_clientes=carpeta / "clientes.json")
    destinos_actualizados: list[str] = []
    try:
        destinos = catalogo.listar()
    except (OSError, ValueError):
        return {"destinos_actualizados": destinos_actualizados}
    for destino in destinos:
        if destino.estado_calidad != EstadoCalidadDestino.CONFIRMADO.value:
            continue
        if destino.estado_vigencia != "ACTIVO":
            continue
        if destino.latitud is not None or destino.longitud is not None:
            continue
        texto = destino.direccion.strip()
        if not texto:
            continue
        if destino.comuna and destino.comuna.upper() not in texto.upper():
            texto = f"{texto}, {destino.comuna}"
        try:
            resultado = resolver_destino_entrega_validado(texto, proveedor_rutas, contexto_territorial="Chile")
        except (OSError, ValueError):
            continue
        if resultado.estado == ESTADO_RESUELTO and resultado.coordenadas is not None:
            catalogo.editar(
                destino.destino_id, modificacion_manual=True,
                latitud=resultado.coordenadas.latitud, longitud=resultado.coordenadas.longitud,
            )
            destinos_actualizados.append(destino.destino_id)
    return {"destinos_actualizados": destinos_actualizados}


def revalidar_obra_desconocida_por_variacion_ortografica_sin_ocr(
    *, ruta_decisiones: str | Path, carpeta_catalogos: str | Path, ruta_dataset: str | Path,
) -> dict[str, object]:
    """Bloque FIX DE ACEPTACION -- caso real 460861: "SALOMON SACK SA SAN
    BERNGARDO" (OCR) vs la obra ya CONFIRMADA "SALOMON SACK SA SAN
    BERNARDO" (mismo cliente). `_decisiones_obra_para_cliente` ya evita
    generar la pregunta para procesamiento NUEVO (Bloque SEGURIDAD, ver
    `resolver_obra_por_variacion_ortografica_menor`), pero una decisión
    `OBRA_DESCONOCIDA` YA PERSISTIDA de una corrida anterior a este fix
    no se corrige sola -- esta función revisa cada decisión pendiente de
    ese tipo contra el mismo mecanismo y, si resuelve, la retira.

    Aprendizaje reutilizable (Bloque APRENDIZAJE): el texto documental
    exacto que motivó la decisión se persiste como ALIAS de la obra ya
    confirmada (`actualizar_identidad_obra`, evidencia tipo GUIA -- no
    decisional, nunca `CONFIRMACION_HUMANA`) -- la MISMA guía u otra con
    idéntico texto resuelve por comparación EXACTA la próxima vez, sin
    recalcular la variación ortográfica. Nunca una regla global de texto
    -- el alias queda atado a ESTA obra, nunca a un patrón de caracteres."""
    from atlas_core.catalogo_obras_destinos import EstadoObra, Evidencia, ResultadoEvidencia, TipoEvidencia
    from atlas_core.decisiones_pendientes import generar_artefacto
    from atlas_core.motor_evidencia_obras import resolver_obra_por_variacion_ortografica_menor

    ruta = Path(ruta_decisiones)
    catalogos = Path(carpeta_catalogos)
    try:
        bandeja = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"decisiones_resueltas": []}

    catalogo_obras = CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    )
    try:
        obras_activas = catalogo_obras.listar_obras()
    except (OSError, ValueError):
        return {"decisiones_resueltas": []}

    decisiones_restantes: list[dict[str, object]] = []
    decisiones_resueltas: list[dict[str, object]] = []
    for decision in bandeja.get("decisiones", []):
        if decision.get("tipo") != "OBRA_DESCONOCIDA" or decision.get("estado", "PENDIENTE") != "PENDIENTE":
            decisiones_restantes.append(decision)
            continue
        contexto = decision.get("contexto") or {}
        cliente_id = str(contexto.get("cliente_id", ""))
        documental = str(decision.get("valor_documental", ""))
        obras_confirmadas_mismo_cliente = tuple(
            obra for obra in obras_activas
            if obra.cliente_id == cliente_id
            and obra.estado == EstadoObra.CONFIRMADA.value
            and obra.estado_vigencia == "ACTIVO"
        )
        obra = resolver_obra_por_variacion_ortografica_menor(
            nombre_documental=documental, obras_confirmadas_mismo_cliente=obras_confirmadas_mismo_cliente,
        )
        if obra is None:
            decisiones_restantes.append(decision)
            continue
        numero_guia = str((decision.get("documento") or {}).get("numero_guia") or "")
        evidencia = Evidencia(
            tipo=TipoEvidencia.GUIA.value,
            identificador_fuente=numero_guia or str((decision.get("documento") or {}).get("archivo") or ""),
            referencia_hash=str(decision.get("decision_id", "")),
            campos_observados={
                "obra_documental": documental, "obra_canonica": obra.nombre_canonico,
                "numero_guia": numero_guia, "decision_id": str(decision.get("decision_id", "")),
            },
            fecha=datetime.now(timezone.utc).isoformat(),
            actor_proceso="RESOLUCION_AUTOMATICA_VARIACION_ORTOGRAFICA_MENOR",
            resultado=ResultadoEvidencia.SOPORTA.value,
        )
        try:
            catalogo_obras.actualizar_identidad_obra(
                obra.obra_id, nombre_canonico=obra.nombre_canonico,
                aliases_documentales=(documental,), evidencia=evidencia,
            )
        except (OSError, ValueError):
            decisiones_restantes.append(decision)
            continue
        decisiones_resueltas.append({
            "decision_id": decision.get("decision_id"), "numero_guia": numero_guia,
            "obra_documental": documental, "obra_canonica": obra.nombre_canonico,
        })

    if not decisiones_resueltas:
        return {"decisiones_resueltas": []}

    generar_artefacto(
        ruta_dataset=ruta_dataset, carpeta_catalogos=catalogos,
        decisiones=decisiones_restantes, ruta_salida=ruta,
    )
    return {"decisiones_resueltas": decisiones_resueltas}


def revalidar_destino_confirmado_desde_ledger_sin_ocr(
    *, carpeta_catalogos: str | Path, ruta_ledger: str | Path,
) -> dict[str, object]:
    """Bloque CIERRE LOGÍSTICA RESIDUAL -- caso real 472044 (destino
    ``0036d792-...``): una confirmación humana histórica
    (``REGISTRAR_DIRECCION`` sobre ``DESTINO_NO_RESUELTO``, actor
    JAVIER_DESKTOP) quedó persistida en el catálogo con la etiqueta
    degradada a nivel comuna ("Las Condes, RM, Chile") en vez de la
    dirección específica que el propio ledger ya registra como
    ``direccion_manual`` ("PUERTA DEL SOL 83") -- un residuo de un bug de
    especificidad corregido en un bloque anterior para la fila del
    dataset (`revalidar_direccion_entrega_degradada_sin_ocr`) pero nunca
    aplicado retroactivamente al CATÁLOGO, porque esta entrada se creó
    ANTES de ese fix. Consecuencia real: `_destino_confirmado_coincide_
    texto` nunca puede volver a emparejar este destino CONFIRMADO contra
    el texto documental real ("PUERTA DEL SOL 83"), así que Vía A/Vía C
    quedan permanentemente ciegas a un destino que un humano YA confirmó.

    El ledger es la fuente de verdad de esa confirmación (mismo
    `destino_id` que `CatalogoDestinos` usa) -- nunca inventa nada, sólo
    reescribe la etiqueta con el mismo texto que el propio Javier
    confirmó, y sólo cuando esa reescritura es estrictamente MÁS
    específica (misma regla de especificidad que ya usa
    `revalidar_direccion_entrega_degradada_sin_ocr`,
    `_etiqueta_geocodificada_o_texto_documental` -- calle+número gana a
    una etiqueta sin número). Nunca toca un destino cuya dirección actual
    ya sea igual o más específica que la del ledger. General -- recorre
    TODAS las aplicaciones `REGISTRAR_DIRECCION` del ledger, no una guía
    en particular."""
    from atlas_core.catalogo_destinos import CatalogoDestinos, DestinoNoEncontradoError
    from atlas_core.rutas.destino_entrega import _etiqueta_geocodificada_o_texto_documental

    try:
        ledger = json.loads(Path(ruta_ledger).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"destinos_corregidos": []}
    carpeta = Path(carpeta_catalogos)
    catalogo = CatalogoDestinos(carpeta / "destinos_maestros.json", ruta_clientes=carpeta / "clientes.json")
    destinos_corregidos: list[str] = []
    for aplicacion in ledger.get("aplicaciones", []):
        if aplicacion.get("tipo") != "DESTINO_NO_RESUELTO" or aplicacion.get("accion") != "REGISTRAR_DIRECCION":
            continue
        destino_id = str(aplicacion.get("destino_id") or "").strip()
        direccion_manual = str(aplicacion.get("direccion_manual") or "").strip()
        if not destino_id or not direccion_manual:
            continue
        try:
            destino = catalogo.obtener(destino_id)
        except (DestinoNoEncontradoError, OSError, ValueError):
            continue
        direccion_corregida = _etiqueta_geocodificada_o_texto_documental(
            etiqueta=destino.direccion, texto_documental=direccion_manual,
        )
        if direccion_corregida == destino.direccion:
            continue
        catalogo.editar(
            destino.destino_id, modificacion_manual=True,
            direccion=direccion_corregida,
            nombre_destino=direccion_corregida if destino.nombre_destino == destino.direccion else None,
        )
        destinos_corregidos.append(destino.destino_id)
    return {"destinos_corregidos": destinos_corregidos}


def revalidar_ruta_por_convergencia_gps_historica_sin_ocr(
    *, ruta_dataset: str | Path, carpeta_catalogos: str | Path,
    proveedor_rutas=None, perfil: str = "driving-hgv",
    servicio_telemetria: ServicioTelemetria | None = None, proveedor_nombre: str = "onelogis",
) -> dict[str, object]:
    """Bloque FINAL CORE V1 -- caso real 460807/472008 (obra ya
    CONFIRMADA "AUSIN SAN BERNARDO", dirección postal "INTERIOR NUEVA
    O1148 SAN BERNARDO" que ningún geocodificador indexa a nivel de
    número): cuando el destino no es geocodificable, el punto real de
    entrega puede seguir siendo derivable de evidencia GPS ya cacheada,
    SI converge entre entregas HISTÓRICAS independientes -- "una sola
    observación GPS aislada no basta" (Bloque C del bloque).

    Para cada `obra_destino` (identidad ya conocida, nunca se
    reinvestiga), calcula `punto_gps_destino` (recorrido de entrega
    seleccionado por telemetría YA CACHEADA -- `enriquecer_documento_
    con_telemetria`, `ProveedorTelemetriaSoloCache`, nunca red) para
    CADA fila de esa obra con patente/fecha/horas y telemetría cacheada
    -- resueltas o no, cualquier entrega histórica cuenta como
    evidencia. Si al menos DOS observaciones caen dentro de
    `MARGEN_MISMO_LUGAR_KM` (mismo criterio ya calibrado que usa Vía A
    para "mismo lugar"), ese punto convergente se acepta como PUNTO
    OPERACIONAL/RUTEABLE real -- nunca con una sola observación.

    Con el punto ya validado, calcula ruta real (ORS) SOLO para las
    filas de esa obra que siguen sin `RUTA_CALCULADA` -- nunca
    recalcula una fila ya resuelta por otra vía. Persiste también el
    punto en cualquier destino ya CONFIRMADO de esa misma obra sin
    coordenadas (`CatalogoDestinos.editar`, evidencia GPS -- nunca
    `CONFIRMACION_HUMANA`) para que futuras guías de la misma obra lo
    reutilicen directo, sin volver a calcular convergencia."""
    from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
    from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos
    from atlas_core.catalogo_plantas import CatalogoPlantas
    from atlas_core.rutas.destino_entrega import MARGEN_MISMO_LUGAR_KM
    from atlas_core.rutas.geocerca import distancia_km_haversine
    from atlas_core.rutas.modelos import Coordenadas

    ruta = Path(ruta_dataset)
    carpeta = Path(carpeta_catalogos)
    if proveedor_rutas is None:
        from atlas_core.procesamiento_masivo import PAIS_OPERACION_PREDETERMINADO
        from atlas_core.rutas.cache_geocodificacion import (
            ProveedorRutasConCacheGeocodificacion, RepositorioCacheGeocodificacion,
        )
        from atlas_core.rutas.openrouteservice import OpenRouteService
        proveedor_rutas = ProveedorRutasConCacheGeocodificacion(
            OpenRouteService(pais=PAIS_OPERACION_PREDETERMINADO), RepositorioCacheGeocodificacion(),
        )
    servicio = servicio_telemetria or ServicioTelemetria(
        ProveedorTelemetriaSoloCache(nombre=proveedor_nombre),
        RepositorioTelemetria(carpeta / "telemetria_cache.json"),
    )
    try:
        plantas_por_id = {p.planta_id: p for p in CatalogoPlantas(carpeta / "plantas.json").listar()}
    except (OSError, ValueError):
        plantas_por_id = {}

    with bloqueo_sesion(ruta.parent, "revalidacion_dataset"):
        filas = _leer_filas(ruta)
        filas_por_obra: dict[str, list[dict[str, str]]] = {}
        for fila in filas:
            obra = normalizar_nombre_obra(str(fila.get("obra_destino", "")))
            if obra:
                filas_por_obra.setdefault(obra, []).append(fila)

        guias_actualizadas: list[str] = []
        destinos_aprendidos: list[str] = []
        for obra_clave, filas_obra in filas_por_obra.items():
            if len(filas_obra) < 2:
                continue  # nunca converge con una sola fila de esa obra
            puntos: list[tuple[dict[str, str], object]] = []
            for fila in filas_obra:
                patente = str(fila.get("patente_tracto", "")).strip().upper()
                if patente in ("", "NO ENCONTRADO"):
                    continue
                fecha_doc = _parsear_fecha_dd_mm_yyyy(fila.get("fecha"))
                if fecha_doc is None:
                    continue
                hora_entrada_dt = _combinar_fecha_hora(fecha_doc, fila.get("hora_entrada_aza"))
                hora_salida_dt = _combinar_fecha_hora(fecha_doc, fila.get("hora_salida_aza"))
                if hora_entrada_dt is None and hora_salida_dt is None:
                    continue
                if servicio.repositorio.buscar_viajes(
                    servicio.proveedor.nombre, patente, fecha_doc, fecha_doc
                ) is None:
                    continue  # sin trip cacheado -- nunca llama a la red aquí
                resultado_gps = enriquecer_documento_con_telemetria(
                    servicio=servicio, patente=patente, fecha=fecha_doc,
                    hora_entrada=hora_entrada_dt, hora_salida=hora_salida_dt,
                    plantas=list(plantas_por_id.values()),
                )
                if resultado_gps.punto_gps_destino is not None:
                    puntos.append((fila, resultado_gps.punto_gps_destino))

            if len(puntos) < 2:
                continue  # una sola observación GPS no basta
            base_fila, base_punto = puntos[0]
            convergentes = [
                punto for _fila, punto in puntos
                if distancia_km_haversine(base_punto, punto) <= MARGEN_MISMO_LUGAR_KM
            ]
            if len(convergentes) < 2:
                continue  # sin convergencia real -- se abstiene, nunca elige un punto aislado
            punto_convergente = base_punto

            for fila in filas_obra:
                if str(fila.get("estado_ruta", "")).strip() == EstadoRuta.RUTA_CALCULADA.value:
                    continue
                planta_id = str(fila.get("planta_origen_id", "")).strip()
                planta = plantas_por_id.get(planta_id)
                if planta is None:
                    continue
                origen = Coordenadas(planta.longitud, planta.latitud)
                try:
                    resultado_ruta = proveedor_rutas.calcular_ruta(origen, punto_convergente, perfil)
                except (OSError, ValueError):
                    continue
                if resultado_ruta.estado != EstadoRuta.RUTA_CALCULADA:
                    continue
                fila["distancia_km"] = str(resultado_ruta.distancia_km)
                fila["duracion_min"] = str(resultado_ruta.duracion_estimada_min)
                fila["proveedor_ruta"] = proveedor_rutas.nombre
                fila["estado_ruta"] = EstadoRuta.RUTA_CALCULADA.value
                fila["motivo_ruta"] = ""
                despachar_a = str(fila.get("despachar_a_crudo", "")).strip()
                if despachar_a:
                    fila["direccion_entrega"] = despachar_a
                guias_actualizadas.append(str(fila.get("numero_guia", "")))

            # Aprendizaje -- persiste el punto convergente en cualquier
            # destino ya CONFIRMADO de esta obra que aún no tenga
            # coordenadas, para que futuras guías lo reutilicen directo.
            try:
                catalogo_obras = CatalogoObrasDestinos(
                    ruta=carpeta / "obras_destinos.json", ruta_clientes=carpeta / "clientes.json",
                    ruta_destinos=carpeta / "destinos_maestros.json",
                )
                obra_registro = next(
                    (o for o in catalogo_obras.listar_obras() if o.nombre_normalizado == obra_clave), None,
                )
                if obra_registro is not None:
                    catalogo_destinos = CatalogoDestinos(
                        carpeta / "destinos_maestros.json", ruta_clientes=carpeta / "clientes.json",
                    )
                    destino_ids = {
                        r.destino_id for r in catalogo_obras.listar_relaciones()
                        if r.obra_id == obra_registro.obra_id and r.estado == "CONFIRMADA"
                    }
                    for destino_id in destino_ids:
                        try:
                            destino = catalogo_destinos.obtener(destino_id)
                        except (OSError, ValueError):
                            continue
                        if (
                            destino.estado_calidad == EstadoCalidadDestino.CONFIRMADO.value
                            and destino.latitud is None and destino.longitud is None
                        ):
                            catalogo_destinos.editar(
                                destino_id, modificacion_manual=True,
                                latitud=punto_convergente.latitud, longitud=punto_convergente.longitud,
                            )
                            destinos_aprendidos.append(destino_id)
            except (OSError, ValueError):
                pass

        if guias_actualizadas:
            _escribir_filas_completas(ruta, filas)

    return {"guias_actualizadas": guias_actualizadas, "destinos_aprendidos": destinos_aprendidos}


def revalidar_ruta_sin_destino_calculado_sin_ocr(
    *, ruta_dataset: str | Path, carpeta_catalogos: str | Path,
    proveedor_rutas=None, perfil: str = "driving-hgv",
    proveedor_rutas_fallback=None,
) -> dict[str, object]:
    """Bloque H (R4.10) -- para filas con planta de origen y
    `despachar_a_crudo` YA persistidos (documento ya procesado, sin OCR
    aquí) pero sin ruta calculada, reintenta geocodificación/ruta con las
    reglas ya corregidas (`resolver_destino_entrega_validado`, vía
    `calcular_ruta_con_planta_conocida`) -- nunca vuelve a leer el
    documento, pero SÍ puede consultar el proveedor de geocodificación/
    rutas real: con caché (una dirección ya geocodificada, como en el
    caso real que motivó esto, no vuelve a pagar la consulta).

    Caso real 464991: DESPACHAR A menciona "PROVIDENCIA" Y "SANTIAGO" --
    dos comunas reales en el mismo texto (ver
    `_comuna_documental_inequivoca`) -- así que la comuna documental es
    ambigua y nunca contradice nada; el candidato geocodificado
    (confianza 1.0, "Avenida Providencia, Santiago, RM, Chile") ya era
    válido, sólo que el código anterior lo rechazaba por error (comparaba
    contra la primera comuna mencionada, "Providencia", sin considerar la
    ambigüedad). Corregido ese error, la ruta sí puede calcularse.

    Ejecutar DESPUÉS de `revalidar_destino_contra_comuna_documental_sin_ocr`
    (que ya retira cualquier destino degradado/absurdo persistido): filas
    con un motivo de rechazo real (comuna inequívocamente contradicha,
    resultado demasiado genérico, múltiples ubicaciones dispersas, origen
    no determinado) vuelven a fallar exactamente igual y quedan intactas
    -- nunca inventa, nunca fuerza un resultado. `proveedor_rutas=None`
    (por defecto) usa `OpenRouteService` + caché de geocodificación real,
    igual que el pipeline en vivo -- inyectable para tests.

    Bloque R9 -- caso real 472044: `estado_ruta` había quedado en
    `PROVEEDOR_NO_DISPONIBLE` (el proveedor externo falló durante el
    procesamiento original) y, al reintentar aquí, el proveedor SÍ
    respondía pero con confianza insuficiente (un resultado real, no una
    falla técnica). Antes de este bloque la fila quedaba con el motivo
    técnico viejo, aunque la causa real ya hubiera cambiado -- confundía
    "proveedor caído" con "evidencia insuficiente" (exactamente lo que
    Bloque 6.3/R7 exige distinguir). Ahora, si el motivo YA persistido es
    una falla puramente técnica conocida (`MOTIVOS_RUTA_TECNICOS_NO_
    ELEGIBLES`, mismo catálogo que ya usa `atlas_ia.registro_problemas`
    para B1) y el reintento no llega a `RUTA_CALCULADA`, se actualiza
    igual el motivo al resultado FRESCO del reintento -- nunca se inventa
    una ruta, sólo se corrige la etiqueta para que diga la verdad
    vigente. Un motivo de rechazo YA basado en evidencia real (comuna
    contradicha, genérico, disperso) nunca se reintenta ni se reescribe
    aquí -- es estable por diseño, no ruido técnico."""
    from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
    from atlas_core.catalogo_plantas import CatalogoPlantas
    from atlas_core.procesamiento_masivo import PAIS_OPERACION_PREDETERMINADO
    from atlas_core.rutas.destino_entrega import calcular_ruta_con_planta_conocida

    ruta = Path(ruta_dataset)
    carpeta = Path(carpeta_catalogos)
    if proveedor_rutas is None:
        from atlas_core.rutas.cache_geocodificacion import (
            ProveedorRutasConCacheGeocodificacion,
            RepositorioCacheGeocodificacion,
        )
        from atlas_core.rutas.openrouteservice import OpenRouteService

        # Bloque RESOLUCIÓN R16 -- causa raíz real del caso 472037 (VICUÑA
        # MACKENNA resuelto en Córdoba, Argentina): esta reconciliación
        # retroactiva construía el proveedor SIN el filtro de país que ya
        # usa el procesamiento en vivo (`procesamiento_masivo.py`, mismo
        # `OpenRouteService(pais=pais_operacion)`) -- la búsqueda quedaba
        # sin restricción territorial alguna, dejando competir candidatos
        # de cualquier país contra los chilenos. `GEOCODIFICACION_FUERA_
        # DE_CHILE` (Bloque TERRITORIAL T1) sigue como red de seguridad
        # para cualquier proveedor que no respete el filtro, pero la
        # consulta ahora ya llega restringida a Chile por diseño, igual
        # que el resto del sistema -- un solo criterio, sin ruta paralela.
        proveedor_rutas = ProveedorRutasConCacheGeocodificacion(
            OpenRouteService(pais=PAIS_OPERACION_PREDETERMINADO), RepositorioCacheGeocodificacion(),
        )
    if proveedor_rutas_fallback is None:
        # Bloque B1 OBSERVADOR + FALLBACK GEOGRÁFICO -- geocodificador de
        # RESPALDO estructurado (Nominatim/OSM, sin credencial, con la
        # MISMA caché de geocodificación -- nunca paga dos veces la misma
        # consulta), consultado por `resolver_destino_entrega` SÓLO
        # cuando el principal (ORS) deja una ambigüedad sin resolver y
        # ni el catálogo confirmado ni GPS pueden desambiguar ("sólo si A
        # falla", Bloque J). Reutiliza `ProveedorRutasConCacheGeocodificacion`
        # -- la clave de caché ya incluye `proveedor_nombre`, así que
        # comparte archivo con ORS sin colisionar.
        from atlas_core.rutas.cache_geocodificacion import (
            ProveedorRutasConCacheGeocodificacion as _ProveedorConCache,
            RepositorioCacheGeocodificacion as _RepositorioCache,
        )
        from atlas_core.rutas.nominatim import NominatimGeocoder

        proveedor_rutas_fallback = _ProveedorConCache(
            NominatimGeocoder(pais=PAIS_OPERACION_PREDETERMINADO), _RepositorioCache(),
        )
    try:
        destinos_confirmados = [
            d for d in CatalogoDestinos(
                carpeta / "destinos_maestros.json", ruta_clientes=carpeta / "clientes.json",
            ).listar()
            if d.estado_calidad == EstadoCalidadDestino.CONFIRMADO.value
        ]
    except (OSError, ValueError):
        destinos_confirmados = []
    try:
        plantas_por_id = {p.planta_id: p for p in CatalogoPlantas(carpeta / "plantas.json").listar()}
    except (OSError, ValueError):
        plantas_por_id = {}

    from atlas_core.atlas_ia.registro_problemas import (
        MOTIVOS_RUTA_TECNICOS_NO_ELEGIBLES,
        motivo_ruta_base,
    )
    from atlas_core.decisiones_pendientes import resumen_hallazgo_b1

    with bloqueo_sesion(ruta.parent, "revalidacion_dataset"):
        filas = _leer_filas(ruta)
        guias_actualizadas: list[str] = []
        for fila in filas:
            if str(fila.get("estado_ruta", "")).strip() == EstadoRuta.RUTA_CALCULADA.value:
                continue
            despachar_a = str(fila.get("despachar_a_crudo", "")).strip()
            planta_id = str(fila.get("planta_origen_id", "")).strip()
            if not despachar_a or not planta_id:
                continue
            planta = plantas_por_id.get(planta_id)
            if planta is None:
                continue
            motivo_previo_crudo = str(fila.get("motivo_ruta", "")).strip()
            motivo_previo_tecnico = motivo_ruta_base(motivo_previo_crudo) in MOTIVOS_RUTA_TECNICOS_NO_ELEGIBLES
            # Bloque LOGÍSTICA L1 -- caso real (460807/472008/472018/
            # 472037/472073/472099/472163): `motivo_ruta` había quedado
            # en blanco (reset por un intento anterior -- p. ej.
            # REGISTRAR_DIRECCION, ver `aplicar_decision_obra` -- que
            # nunca llegó a persistir un motivo fresco si el reintento
            # fallaba). Un motivo en blanco NUNCA es una causa estable
            # basada en evidencia real (a diferencia de un rechazo ya
            # explicado) -- "Atlas no sabe por qué" no es lo mismo que
            # "Atlas ya investigó y rechazó por evidencia real". Se
            # trata igual que un motivo técnico obsoleto: el resultado
            # FRESCO del reintento (sea cual sea) se registra siempre,
            # nunca se deja un "No disponible" silencioso.
            motivo_previo_sin_causa = not motivo_previo_crudo
            # Bloque TERRITORIAL T1 -- caso real 472037 (VICUÑA MACKENNA):
            # `GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL` no es una
            # respuesta externa del proveedor -- es la comparación
            # TERRITORIAL propia de Atlas (`_comuna_documental_
            # inequivoca`/`_comunas_territorialmente_compatibles`), que
            # este mismo bloque acaba de corregir (nombres compuestos de
            # calle, jerarquía Santiago/comuna). Un rechazo con esta causa
            # exacta merece un reintento con la lógica FRESCA, a
            # diferencia de un rechazo por evidencia real e inmutable
            # (comuna genuinamente distinta, SIN_ACCESO_VIAL) -- reintentar
            # una contradicción real de todas formas da el mismo resultado
            # (nunca se afloja la protección), sólo cuesta una consulta
            # más, ya cacheada.
            #
            # Bloque RESOLUCIÓN R19 -- mismo criterio, extendido a
            # `GEOCODIFICACION_FUERA_DE_CHILE` (Bloque TERRITORIAL T1):
            # también es una verificación propia de Atlas (`region_valida`
            # contra el candidato del proveedor), no evidencia externa
            # inmutable. Caso real 472037: antes de este bloque, el
            # proveedor construía la consulta SIN restricción de país
            # (Bloque RESOLUCIÓN R16 lo corrigió, `pais=CL`), así que la
            # fila quedó persistida con "GEOCODIFICACION_FUERA_DE_CHILE:
            # Cordoba" -- un candidato que, reintentado con la consulta ya
            # restringida a Chile, ya NO vuelve a aparecer. Sin esta
            # extensión, esa fila quedaba con una causa obsoleta/engañosa
            # para siempre (la reconciliación automática nunca la
            # reintentaba).
            motivo_previo_reevaluable = motivo_ruta_base(motivo_previo_crudo) in (
                "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL", "GEOCODIFICACION_FUERA_DE_CHILE",
            )
            # Bloque VALIDACIÓN TERRITORIAL T2 -- caso real 472037: B1 ya
            # investigó y dejó evidencia PERSISTIDA (`resultado_atlas_ia_
            # json`, misma fuente de verdad que usa `decisiones_pendientes.
            # resumen_hallazgo_b1`, nunca una llamada nueva) -- se lee aquí
            # para que la Vía C del fallback estructurado pueda corroborar
            # un candidato contra una mención territorial de nivel ciudad
            # ("Santiago") cuando el destino confirmado no trae comuna
            # propia. Texto compacto (explicación + resumen de evidencia),
            # nunca un dump de la fila completa.
            hallazgo_b1 = resumen_hallazgo_b1(fila, dominio="DESTINO", campo="despachar_a_crudo")
            contexto_evidencia_b1 = " ".join(
                str(hallazgo_b1.get(clave, "")) for clave in ("b1_resumen_hallazgo", "b1_evidencia_resumida")
            ) if hallazgo_b1 else ""
            try:
                resultado = calcular_ruta_con_planta_conocida(
                    planta=planta, despachar_a_crudo=despachar_a, proveedor_rutas=proveedor_rutas,
                    origen_determinado_por=str(fila.get("origen_determinado_por", "")),
                    evidencia_origen=str(fila.get("evidencia_origen", "")),
                    perfil=perfil, destinos_confirmados=destinos_confirmados,
                    proveedor_geocodificacion_fallback=proveedor_rutas_fallback,
                    contexto_evidencia_b1=contexto_evidencia_b1,
                )
            except (OSError, ValueError):
                continue
            if resultado.estado_ruta != EstadoRuta.RUTA_CALCULADA.value:
                # Bloque R9 -- sigue sin resolver con evidencia suficiente
                # -- nunca inventa. Pero si el motivo YA persistido era
                # una falla puramente técnica (proveedor caído/sin
                # credencial/etc.) y el reintento sí llegó a una
                # respuesta real (aunque rechazada), esa etiqueta técnica
                # quedó obsoleta -- se corrige para que nunca se confunda
                # "proveedor no disponible" con "evidencia insuficiente".
                # Un rechazo YA basado en evidencia real nunca se toca.
                #
                # Bloque CONFIRMACIÓN D2 -- una única excepción, estrecha
                # a propósito (nunca se agregó `MULTIPLES_UBICACIONES_
                # DISPERSAS` al conjunto general de arriba: ese motivo
                # sigue siendo estable frente a cualquier reintento que
                # simplemente vuelva a fallar distinto, ver `test_
                # motivo_de_evidencia_externa_inmutable_nunca_se_
                # reescribe`). Caso real 472037: Javier confirmó la
                # dirección en Revisión de Atlas DESPUÉS de que esta
                # función ya había persistido `MULTIPLES_UBICACIONES_
                # DISPERSAS` -- el catálogo confirmado no existía todavía
                # en ese reintento. La ÚNICA transición que se acepta aquí
                # es exactamente esa: de `MULTIPLES_UBICACIONES_DISPERSAS`
                # a `COORDENADA_NO_CONFIRMADA` (`resolver_destino_entrega`
                # sólo produce ese motivo cuando encuentra, en el
                # catálogo, un destino CONFIRMADO cuya dirección coincide
                # textualmente -- evidencia real de una decisión humana,
                # nunca una respuesta distinta del proveedor por azar).
                identidad_recien_confirmada = (
                    motivo_ruta_base(motivo_previo_crudo) == "MULTIPLES_UBICACIONES_DISPERSAS"
                    and motivo_ruta_base(resultado.motivo_ruta or "") == "COORDENADA_NO_CONFIRMADA"
                )
                if (
                    motivo_previo_tecnico or motivo_previo_sin_causa
                    or motivo_previo_reevaluable or identidad_recien_confirmada
                ) and resultado.motivo_ruta:
                    motivo_nuevo = motivo_ruta_base(resultado.motivo_ruta)
                    if (
                        motivo_previo_sin_causa
                        or motivo_nuevo != motivo_ruta_base(motivo_previo_crudo)
                    ):
                        fila["estado_ruta"] = resultado.estado_ruta
                        fila["motivo_ruta"] = resultado.motivo_ruta
                        # Bloque CONFIRMACIÓN D2 -- caso real 472044
                        # (PUERTA DEL SOL 83 LAS CONDES): estas tres
                        # columnas quedaban SIN TOCAR en esta rama (sólo
                        # se escribían en el camino RUTA_CALCULADA, más
                        # abajo) -- un valor DEGRADADO que quedó
                        # persistido en un intento anterior (p. ej. "Las
                        # Condes, RM, Chile", de antes del fix de Bloque F
                        # que ya impide que un candidato descartado se
                        # exponga como destino operacional) sobrevivía
                        # para siempre a cualquier reintento posterior,
                        # incluida una confirmación humana nueva -- porque
                        # `calcular_ruta_con_planta_conocida` YA calcula
                        # el valor fresco correcto (vacío cuando el
                        # candidato no queda resuelto, per Bloque F;
                        # `_etiqueta_geocodificada_o_texto_documental`
                        # cuando sí), pero nadie lo escribía aquí. Se
                        # sincroniza siempre que se reescribe el motivo --
                        # mismos tres campos que ya escribe la rama
                        # RUTA_CALCULADA, nunca inventa nada nuevo.
                        fila["direccion_entrega"] = resultado.direccion_entrega_geocodificada
                        fila["localidad_entrega"] = resultado.localidad_entrega
                        fila["region_entrega"] = resultado.region_entrega
                        guias_actualizadas.append(str(fila.get("numero_guia", "")))
                continue
            fila["direccion_entrega"] = resultado.direccion_entrega_geocodificada
            fila["localidad_entrega"] = resultado.localidad_entrega
            fila["region_entrega"] = resultado.region_entrega
            fila["distancia_km"] = resultado.distancia_km
            fila["duracion_min"] = resultado.duracion_min
            fila["proveedor_ruta"] = resultado.proveedor_ruta
            fila["estado_ruta"] = resultado.estado_ruta
            fila["motivo_ruta"] = ""
            guias_actualizadas.append(str(fila.get("numero_guia", "")))
        if guias_actualizadas:
            _escribir_filas_completas(ruta, filas)

    return {"filas_totales": len(filas), "guias_actualizadas": guias_actualizadas}


def revalidar_direccion_entrega_degradada_sin_ocr(*, ruta_dataset: str | Path) -> dict[str, object]:
    """Bloque LOGÍSTICA L1 -- caso real (472044/472227/472247 y otras
    filas con ruta YA calculada antes del fix de especificidad): filas
    con `estado_ruta == RUTA_CALCULADA` nunca pasan por `revalidar_ruta_
    sin_destino_calculado_sin_ocr` (se saltan por diseño -- ya no
    necesitan reintentar geocodificación/routing), así que una etiqueta
    degradada (p. ej. "Las Condes, RM, Chile" en vez de "PUERTA DEL SOL
    83 LAS CONDES") que quedó persistida ANTES de ese fix nunca se
    corregía sola. Esta revalidación es puramente de ETIQUETA -- nunca
    toca coordenadas/km/tiempo/localidad/región (esos ya son válidos, la
    ruta no cambia) -- sin OCR, sin red, sólo relee lo ya persistido y
    aplica el mismo criterio de especificidad
    (`_etiqueta_geocodificada_o_texto_documental`)."""
    from atlas_core.rutas.destino_entrega import _etiqueta_geocodificada_o_texto_documental

    ruta = Path(ruta_dataset)
    with bloqueo_sesion(ruta.parent, "revalidacion_dataset"):
        filas = _leer_filas(ruta)
        guias_actualizadas: list[str] = []
        for fila in filas:
            if str(fila.get("estado_ruta", "")).strip() != EstadoRuta.RUTA_CALCULADA.value:
                continue
            entrega_actual = str(fila.get("direccion_entrega", "")).strip()
            crudo = str(fila.get("despachar_a_crudo", "")).strip()
            if not entrega_actual or not crudo:
                continue
            entrega_corregida = _etiqueta_geocodificada_o_texto_documental(
                etiqueta=entrega_actual, texto_documental=crudo,
            )
            if entrega_corregida != entrega_actual:
                fila["direccion_entrega"] = entrega_corregida
                guias_actualizadas.append(str(fila.get("numero_guia", "")))
        if guias_actualizadas:
            _escribir_filas_completas(ruta, filas)

    return {"filas_totales": len(filas), "guias_actualizadas": guias_actualizadas}


def revalidar_direccion_entrega_por_documentos_hermanos_sin_ocr(
    *, ruta_dataset: str | Path, carpeta_catalogos: str | Path,
) -> dict[str, object]:
    """Bloque FIX FINAL DE ACEPTACION -- caso real 472247/472212: el OCR
    corrompió DOS tokens de la misma dirección real ("CAMINO A MELIFILLA
    1OBOD SANTIAGO MAIPU" / "CAMINO A MELIPILLA 10B00 SANTIAGO MAIPU")
    -- `revalidar_direccion_entrega_degradada_sin_ocr` ya preserva un
    texto documental específico sobre una etiqueta genérica, pero no
    tiene forma de saber que ESE texto específico está, a su vez,
    corrompido. Otro documento del mismo cliente (464981) ya trae la
    misma dirección real sin ruido -- comparar contra ese "documento
    hermano" (y contra cualquier destino ya CONFIRMADO compatible) es
    evidencia real, nunca un mapeo de caracteres inventado.

    Restringida a filas con `estado_ruta == RUTA_CALCULADA` (mismo
    alcance que su función hermana) -- nunca toca coordenadas/km/tiempo/
    ruta, sólo la ETIQUETA `direccion_entrega`; `despachar_a_crudo`
    (evidencia documental original) nunca se modifica. Sin OCR, sin red
    -- sólo relee el dataset y catálogos ya persistidos."""
    from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
    from atlas_core.rutas.destino_entrega import resolver_direccion_canonica_mas_limpia

    ruta = Path(ruta_dataset)
    catalogos = Path(carpeta_catalogos)
    candidatos_catalogo: list[str] = []
    try:
        candidatos_catalogo = [
            d.direccion for d in CatalogoDestinos(
                catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json",
            ).listar()
            if d.estado_calidad == EstadoCalidadDestino.CONFIRMADO.value
            and d.estado_vigencia == "ACTIVO" and d.direccion.strip()
        ]
    except (OSError, ValueError):
        pass

    with bloqueo_sesion(ruta.parent, "revalidacion_dataset"):
        filas = _leer_filas(ruta)
        # Candidatos "documento hermano": texto documental de CUALQUIER
        # otra fila del mismo cliente -- el propio dataset ya persistido
        # es el histórico, sin necesidad de un catálogo aparte.
        crudos_por_cliente: dict[str, list[str]] = {}
        for fila in filas:
            cliente = str(fila.get("cliente", "")).strip()
            crudo = str(fila.get("despachar_a_crudo", "")).strip()
            if cliente and crudo:
                crudos_por_cliente.setdefault(cliente, []).append(crudo)

        guias_actualizadas: list[str] = []
        for fila in filas:
            if str(fila.get("estado_ruta", "")).strip() != EstadoRuta.RUTA_CALCULADA.value:
                continue
            entrega_actual = str(fila.get("direccion_entrega", "")).strip()
            cliente = str(fila.get("cliente", "")).strip()
            if not entrega_actual:
                continue
            candidatos = [*candidatos_catalogo, *crudos_por_cliente.get(cliente, ())]
            entrega_corregida = resolver_direccion_canonica_mas_limpia(
                texto_objetivo=entrega_actual, candidatos=candidatos,
            )
            if entrega_corregida is not None and entrega_corregida != entrega_actual:
                fila["direccion_entrega"] = entrega_corregida
                guias_actualizadas.append(str(fila.get("numero_guia", "")))
        if guias_actualizadas:
            _escribir_filas_completas(ruta, filas)

    return {"filas_totales": len(filas), "guias_actualizadas": guias_actualizadas}


def revalidar_y_regenerar_reporte(
    *, raiz_atlas: str | Path, nombre_carpeta_reporte: str, reloj=None, proveedor_rutas=None,
) -> dict[str, object]:
    """Orquesta la revalidación del dataset (R3.4 obra/destino + R3.6.2
    patente de vehículo, cada una restringida a su propio motivo) y, sólo
    si algo cambió, regenera el reporte oficial (`generar_reporte_viajes`)
    para que `reportes/actual`/Desktop dejen de mostrar un motivo ya
    resuelto -- sin OCR, usando exclusivamente el dataset ya persistido y
    los catálogos vigentes. Publica el nuevo `reporte_vigente` en
    `estado_operacion.json` mediante la misma infraestructura oficial que
    usa el CLI de reportes."""
    raiz = Path(raiz_atlas)
    actual = raiz / "operacion" / "actual"
    catalogos = raiz / "catalogos_privados"
    dataset = actual / "analisis_completo_guias.csv"

    # Bloque R13 -- caso real 472238/472239 (TORRES OCARANZA LTDA): corre
    # ANTES que `revalidar_obra_destino_sin_ocr` a propósito -- si esta
    # rellena `cliente` desde `obra_destino` en esta misma pasada, la
    # comparación "obra == cliente" de abajo ya puede aprovecharlo sin
    # esperar un segundo ciclo de reconciliación.
    resultado_cliente_ausente = revalidar_cliente_ausente_por_obra_coincidente_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=catalogos,
    )
    # R3.6.2: cada revalidación es un pase atómico independiente que sólo
    # toca su propio motivo -- se ejecutan en secuencia (no anidadas) y son
    # conmutativas/idempotentes entre sí, así que el orden no importa. Se
    # combina el resultado para decidir si hace falta regenerar el reporte.
    resultado_obra_destino = revalidar_obra_destino_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, ruta_ledger=actual / "decisiones_aplicadas.json",
    )
    resultado_patente = revalidar_patente_sin_homologar_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, ruta_ledger=actual / "decisiones_aplicadas.json",
    )
    # R4.8: mismo patrón, restringido a CLIENTE_SIN_CORROBORAR -- ver
    # `revalidar_cliente_sin_corroborar_sin_ocr`.
    resultado_cliente = revalidar_cliente_sin_corroborar_sin_ocr(
        ruta_dataset=dataset, ruta_ledger=actual / "decisiones_aplicadas.json",
    )
    # Bloque F (R4.10): limpieza retroactiva de destinos degradados/
    # absurdos que quedaron persistidos antes del fix de
    # `resolver_destino_entrega_validado` -- sin OCR, sin red.
    resultado_destino_contradicho = revalidar_destino_contra_comuna_documental_sin_ocr(
        ruta_dataset=dataset,
    )
    # Bloque CONFIRMACIÓN D2 -- caso real 472044: hermana de la anterior,
    # misma filosofía (limpieza retroactiva, sin OCR, sin red, nunca toca
    # motivo_ruta/estado_ruta), para filas SIN ruta calculada cuya
    # `direccion_entrega` quedó a nivel comuna (sin número de calle)
    # mientras `despachar_a_crudo` sí lo trae -- `revalidar_ruta_sin_
    # destino_calculado_sin_ocr` sólo refresca esta columna cuando el
    # MOTIVO cambia entre reintentos; una fila estable en el mismo motivo
    # técnico (p. ej. `CONFIANZA_INSUFICIENTE`) podía quedar con la
    # etiqueta degradada para siempre.
    resultado_destino_sin_numero = revalidar_destino_operacional_sin_numero_de_calle_sin_ocr(
        ruta_dataset=dataset,
    )
    # Bloque CIERRE LOGÍSTICA RESIDUAL -- corre ANTES que R18 y que la
    # revalidación de ruta a propósito: si la propia etiqueta del destino
    # CONFIRMADO quedó degradada en el catálogo (caso real 472044), Vía
    # A/Vía C nunca podrán emparejarlo contra el texto documental sin
    # importar cuántas veces se reintente geocodificación después -- hay
    # que corregir la IDENTIDAD antes de intentar resolver la RUTA.
    resultado_destino_confirmado_ledger = revalidar_destino_confirmado_desde_ledger_sin_ocr(
        carpeta_catalogos=catalogos, ruta_ledger=actual / "decisiones_aplicadas.json",
    )
    # Bloque FINAL CORE V1 -- caso real 464981: corre ANTES que la
    # revalidación de ruta a propósito -- resuelve la PLANTA (vecinos
    # temporales GPS del mismo vehículo) para que la revalidación de
    # ruta, más abajo, ya tenga `planta_origen_id` con qué intentar
    # geocodificación/routing en esta MISMA pasada.
    resultado_origen_vecinos = revalidar_origen_por_vecinos_temporales_gps_sin_ocr(ruta_dataset=dataset)
    # Bloque FINAL CORE V1 -- caso real 460807/472008 (AUSIN SAN
    # BERNARDO): corre ANTES también -- resuelve un punto operacional
    # por convergencia GPS histórica cuando la dirección postal no es
    # geocodificable por ningún proveedor, calculando la ruta
    # directamente (no depende de la revalidación de ruta genérica de
    # abajo, que sí necesita un candidato geocodificado).
    resultado_ruta_convergencia_gps = revalidar_ruta_por_convergencia_gps_historica_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, proveedor_rutas=proveedor_rutas,
    )
    # Bloque RESOLUCIÓN R18 -- corre ANTES que la revalidación de ruta a
    # propósito: un destino recién geocodificado aquí (confirmado por
    # Javier, pero sin coordenadas hasta ahora) es exactamente lo que Vía
    # A necesita para desbloquear, en esta misma pasada, cualquier guía
    # hermana que comparta esa dirección -- ver docstring de la función.
    resultado_destinos_confirmados = revalidar_destinos_confirmados_sin_coordenadas_sin_ocr(
        carpeta_catalogos=catalogos, proveedor_rutas=proveedor_rutas,
    )
    # Bloque LOGÍSTICA L1 -- caso real (11 viajes sin km/tiempo pese a
    # tener origen+destino documental ya persistidos): a diferencia de
    # las revalidaciones anteriores, ÉSTA sí puede tocar red (geocodificación/
    # routing, con caché -- nunca vuelve a leer el documento). Se ejecuta
    # AL FINAL, después de que cliente/obra/destino ya quedaron al día en
    # esta misma pasada (una obra recién corroborada puede ser la que
    # faltaba para intentar de nuevo con datos frescos). Origen+destino
    # confiables nunca deben depender de que alguien corra un script
    # aparte -- "Atlas debe automáticamente".
    resultado_ruta = revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, proveedor_rutas=proveedor_rutas,
    )
    # Bloque LOGÍSTICA L1 -- caso real 472044/472227/472247: filas YA con
    # `RUTA_CALCULADA` nunca pasan por la revalidación anterior (no lo
    # necesitan) -- si su etiqueta quedó degradada (persistida antes del
    # fix de especificidad), sólo esta pasada la corrige. Nunca toca
    # km/tiempo/coordenadas -- sólo la etiqueta.
    resultado_direccion_degradada = revalidar_direccion_entrega_degradada_sin_ocr(ruta_dataset=dataset)
    # Bloque FIX FINAL DE ACEPTACION -- caso real 472247/472212: corre
    # DESPUÉS de la anterior a propósito (esa ya deja `direccion_entrega`
    # igual al texto documental específico cuando corresponde; ésta
    # revisa si ESE texto, a su vez, tiene una variante más limpia entre
    # los documentos hermanos del mismo cliente o los destinos ya
    # CONFIRMADOS).
    resultado_direccion_hermanos = revalidar_direccion_entrega_por_documentos_hermanos_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=catalogos,
    )
    guias_actualizadas = sorted(
        set(resultado_obra_destino["guias_actualizadas"])
        | set(resultado_patente["guias_actualizadas"])
        | set(resultado_cliente["guias_actualizadas"])
        | set(resultado_destino_contradicho["guias_actualizadas"])
        | set(resultado_destino_sin_numero["guias_actualizadas"])
        | set(resultado_cliente_ausente["guias_actualizadas"])
        | set(resultado_ruta["guias_actualizadas"])
        | set(resultado_direccion_degradada["guias_actualizadas"])
        | set(resultado_direccion_hermanos["guias_actualizadas"])
        | set(resultado_origen_vecinos["guias_actualizadas"])
        | set(resultado_ruta_convergencia_gps["guias_actualizadas"])
    )
    resultado_revalidacion: dict[str, object] = {
        "filas_totales": resultado_patente["filas_totales"],
        "guias_actualizadas": guias_actualizadas,
        "obra_destino": resultado_obra_destino,
        "patente": resultado_patente,
        "cliente": resultado_cliente,
        "direccion_degradada": resultado_direccion_degradada,
        "direccion_hermanos": resultado_direccion_hermanos,
        "destino_contradicho": resultado_destino_contradicho,
        "destino_sin_numero": resultado_destino_sin_numero,
        "cliente_ausente": resultado_cliente_ausente,
        "destino_confirmado_ledger": resultado_destino_confirmado_ledger,
        "origen_vecinos_temporales_gps": resultado_origen_vecinos,
        "ruta_convergencia_gps_historica": resultado_ruta_convergencia_gps,
        "destinos_confirmados_geocodificados": resultado_destinos_confirmados,
        "ruta": resultado_ruta,
    }

    # Bloque R11 -- causa raíz de "la decisión quedó obsoleta porque cambió
    # el dataset" reapareciendo indefinidamente (caso real: catch-up de R10
    # aplicado directo contra producción, sin pasar por `aplicar_decision_obra`):
    # esta función podía cambiar el dataset (arriba) sin nunca republicar
    # `decisiones_pendientes.json` -- su `dataset_sha256` grabado quedaba
    # apuntando al dataset ANTERIOR, y la comprobación de obsolescencia de
    # `aplicar_decision_obra` (que compara ese hash contra el dataset actual,
    # a nivel de archivo completo -- nunca por documento) empezaba a
    # rechazar TODAS las decisiones pendientes, no sólo las de la guía que
    # cambió. "Refrescar datos" en Desktop sólo relee archivos -- nunca
    # revalida -- así que sin este bloque el usuario quedaba atrapado para
    # siempre. Se regenera SIEMPRE que se llega hasta aquí (barato, sin OCR,
    # sin red, idempotente si nada cambió) -- nunca condicionado a
    # `guias_actualizadas`: el hash pudo quedar desincronizado en una
    # corrida ANTERIOR de esta misma función, no sólo en la actual.
    from atlas_core.decisiones_pendientes import (
        NOMBRE_ARTEFACTO, generar_artefacto, regenerar_decisiones_persistidas,
    )
    ruta_decisiones = actual / NOMBRE_ARTEFACTO
    if ruta_decisiones.is_file():
        # Bloque FIX DE ACEPTACION -- caso real 460861: una `OBRA_
        # DESCONOCIDA` YA PERSISTIDA (de una corrida anterior a este fix)
        # cuya única causa era una variación ortográfica/OCR menor contra
        # una obra ya CONFIRMADA del mismo cliente se retira aquí, ANTES
        # de la regeneración de abajo (para que la lista base que ésta
        # recibe ya no la incluya). Sin OCR, sin red -- sólo catálogo y
        # decisiones ya persistidas.
        resultado_obra_por_variacion = revalidar_obra_desconocida_por_variacion_ortografica_sin_ocr(
            ruta_decisiones=ruta_decisiones, carpeta_catalogos=catalogos, ruta_dataset=dataset,
        )
        if resultado_obra_por_variacion["decisiones_resueltas"]:
            resultado_revalidacion["obra_por_variacion_ortografica"] = resultado_obra_por_variacion
        try:
            bandeja_previa = json.loads(ruta_decisiones.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            bandeja_previa = None
        if bandeja_previa is not None:
            # Bloque RESOLUCIÓN R18 -- causa raíz real de "requiere
            # confirmación humana + 0 decisiones en Revisión de Atlas"
            # (casos 460807/472008/472037/472044/472073/472163):
            # `detectar_decisiones_origen_sin_ocr`/`_destino_no_resuelto_
            # sin_ocr`/`_cliente_ausente_sin_ocr` (Bloques ORIGEN D1/R6
            # A-B-E/R9) ya existían, ya probadas, cada una con su propia
            # función `reconciliar_decisiones_*` -- pero NINGUNA de esas
            # tres estaba conectada al auto-republicado de la bandeja que
            # esta función SÍ corre siempre (después de cada revalidación
            # retroactiva de ruta/destino/origen). Sólo se PODABAN
            # decisiones ya publicadas; nunca se DESCUBRÍAN candidatas
            # nuevas que la revalidación de arriba acababa de habilitar.
            # Mismo patrón ya usado 3 veces por separado -- unificado aquí
            # para que corra siempre, automáticamente, sin script manual.
            # `generar_artefacto` deduplica por `decision_id` (determinista
            # por evidencia) -- nunca produce una tarjeta repetida ni
            # resucita una ya cerrada en el ledger.
            candidatas_nuevas = [
                *detectar_decisiones_origen_sin_ocr(raiz_atlas=raiz),
                *detectar_decisiones_destino_no_resuelto_sin_ocr(raiz_atlas=raiz),
                *detectar_decisiones_cliente_ausente_sin_ocr(raiz_atlas=raiz),
            ]
            restantes = regenerar_decisiones_persistidas(
                decisiones=[*bandeja_previa.get("decisiones", []), *candidatas_nuevas],
                carpeta_catalogos=catalogos, ruta_dataset=dataset,
            )
            kwargs_artefacto = {"reloj": reloj} if reloj is not None else {}
            generar_artefacto(
                ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=restantes,
                ruta_salida=ruta_decisiones, **kwargs_artefacto,
            )
            resultado_revalidacion["bandeja_republicada"] = True
            resultado_revalidacion["decisiones_candidatas_descubiertas"] = len(candidatas_nuevas)

    if not guias_actualizadas:
        return {**resultado_revalidacion, "reporte_regenerado": False}

    from atlas_core.almacenamiento_portable import escribir_estado_operacion

    salida = raiz / "reportes" / nombre_carpeta_reporte
    kwargs = {"carpeta_catalogos": catalogos, "ruta_ledger": actual / "decisiones_aplicadas.json"}
    if reloj is not None:
        kwargs["reloj"] = reloj
    manifest = generar_reporte_viajes(dataset, salida, **kwargs)
    escribir_estado_operacion(
        reporte_vigente=salida,
        dataset_operacional=dataset,
        decisiones_pendientes=(ruta_decisiones if ruta_decisiones.is_file() else None),
        raiz=raiz,
    )
    return {**resultado_revalidacion, "reporte_regenerado": True, "reporte_vigente": str(salida)}


def detectar_decisiones_destino_historicas_sin_ocr(
    *, raiz_atlas: str | Path,
) -> list[dict[str, object]]:
    """R3.4.3: reconciliación histórica, READ-ONLY -- nunca escribe nada.

    Para cada aplicación ``OBRA_DESCONOCIDA``/``REGISTRAR`` ya persistida en
    el ledger (``decisiones_aplicadas.json``) -- una obra que Atlas ya
    conoce porque Javier la registró, antes de que R3.4.2 existiera --
    reconstruye, si corresponde, la decisión ``DESTINO_SIN_CONFIRMAR`` que
    R3.4.2 habría generado en el momento de aplicar si el fix ya hubiera
    existido. Reutiliza exclusivamente identidad canónica ya persistida por
    Atlas: ``obra_id``/``cliente_id`` vienen del propio ledger (nunca se
    infieren por nombre); el destino documental viene de la fila del
    dataset con el MISMO ``numero_guia`` que el ledger asocia a esa
    aplicación -- la misma clave exacta que todo el resto del sistema usa
    para correlacionar decisión <-> documento, nunca coincidencia de texto
    ni heurística. Sin OCR, sin volver a leer nada del documento original.

    Elegibilidad (todas deben cumplirse; ante cualquier duda se abstiene,
    nunca inventa ni adivina):
      - la obra referenciada por el ledger existe y sigue ``ACTIVA``;
      - el cliente referenciado por el ledger existe y sigue ``ACTIVO``;
      - existe EXACTAMENTE una fila en el dataset con ese ``numero_guia``
        (cero o varias -> correlación no confiable, se descarta);
      - esa fila trae ``obra_destino`` documental que normaliza EXACTO (sin
        fuzzy, misma comparación que usa el resto del módulo obra/destino)
        al nombre canónico o a un alias de la MISMA obra que el ledger
        asoció -- si no coincide, la fila no corrobora ser el mismo hecho
        y se descarta (nunca se asume);
      - esa fila trae ``despachar_a_crudo`` no ausente -- si no lo trae, no
        hay destino documental que preguntar (CASO C, no se inventa nada);
      - CASO A (la obra ya tiene una relación ``CONFIRMADA`` única): se
        delega en `decision_destino_para_obra_registrada`, que se abstiene
        -- no hay pregunta redundante que hacer.

    No decide ni publica nada por sí sola: sólo devuelve decisiones
    candidatas. Igual que el resto del sistema, la idempotencia y la
    no-resurrección de decisiones ya terminales las garantiza
    `generar_artefacto` al publicar (filtra contra el ledger) -- no esta
    función.
    """
    raiz = Path(raiz_atlas)
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    dataset = actual / "analisis_completo_guias.csv"
    ledger_ruta = actual / "decisiones_aplicadas.json"

    try:
        ledger = json.loads(ledger_ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    registros_obra = [
        a for a in ledger.get("aplicaciones", [])
        if a.get("tipo") == "OBRA_DESCONOCIDA" and a.get("accion") == "REGISTRAR"
        and a.get("obra_id") and a.get("cliente_id")
    ]
    if not registros_obra:
        return []

    try:
        filas = _leer_filas(dataset)
    except (OSError, ValueError):
        return []
    filas_por_guia: dict[str, list[dict[str, str]]] = {}
    for fila in filas:
        filas_por_guia.setdefault(str(fila.get("numero_guia", "")), []).append(fila)

    catalogo_obras = CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    )
    try:
        obras_por_id = {o.obra_id: o for o in catalogo_obras.listar_obras()}
    except (OSError, ValueError):
        return []
    try:
        clientes_por_id = {c.cliente_id: c for c in CatalogoClientes(catalogos / "clientes.json").listar()}
    except (OSError, ValueError):
        clientes_por_id = {}

    from atlas_core.decisiones_pendientes import decision_destino_para_obra_registrada

    candidatas: list[dict[str, object]] = []
    for aplicacion in registros_obra:
        obra = obras_por_id.get(str(aplicacion.get("obra_id")))
        if obra is None or obra.estado_vigencia != "ACTIVO":
            continue
        cliente = clientes_por_id.get(str(aplicacion.get("cliente_id")))
        if cliente is None or cliente.estado_vigencia != "ACTIVO":
            continue
        guia = str((aplicacion.get("documento") or {}).get("numero_guia") or "")
        filas_guia = filas_por_guia.get(guia, [])
        if len(filas_guia) != 1:
            continue  # sin fila, o ambigua entre varias -- no se adivina
        fila = filas_guia[0]
        obra_documental = str(fila.get("obra_destino", "")).strip()
        if obra_documental in _AUSENTES:
            continue
        claves_obra = {
            normalizar_nombre_obra(obra.nombre_canonico),
            *(normalizar_nombre_obra(alias) for alias in obra.aliases_documentales),
        }
        if normalizar_nombre_obra(obra_documental) not in claves_obra:
            continue  # la fila no corrobora ser la MISMA obra que registró el ledger
        decision = decision_destino_para_obra_registrada(
            obra=obra, cliente_id=cliente.cliente_id, cliente_canonico=cliente.razon_social,
            destino_documental=fila.get("despachar_a_crudo", ""),
            documento={
                "archivo": fila.get("archivo", ""), "numero_guia": guia,
                "numero_transporte": fila.get("numero_transporte", ""),
            },
            catalogo_obras=catalogo_obras,
        )
        if decision is not None:
            candidatas.append(decision)
    return candidatas


def reconciliar_decisiones_destino_historicas(
    *, raiz_atlas: str | Path, reloj=lambda: datetime.now(timezone.utc),
) -> dict[str, object]:
    """Publica en `decisiones_pendientes.json` la unión de la bandeja
    pendiente vigente con las decisiones reconciliadas desde el histórico
    (ver `detectar_decisiones_destino_historicas_sin_ocr`). No toca ningún
    catálogo, el CSV documental ni el ledger -- sólo (re)escribe la bandeja,
    igual que cualquier otra regeneración del sistema. Misma garantía de
    idempotencia y no-resurrección de decisiones terminales que el resto
    del sistema: `generar_artefacto` filtra contra el ledger al publicar.
    """
    from atlas_core.decisiones_pendientes import (
        NOMBRE_ARTEFACTO, generar_artefacto, regenerar_decisiones_persistidas,
    )

    raiz = Path(raiz_atlas)
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    dataset = actual / "analisis_completo_guias.csv"
    artefacto_ruta = actual / NOMBRE_ARTEFACTO

    try:
        artefacto_actual = json.loads(artefacto_ruta.read_text(encoding="utf-8"))
        pendientes_actuales = artefacto_actual.get("decisiones", [])
    except (OSError, json.JSONDecodeError):
        pendientes_actuales = []

    candidatas = detectar_decisiones_destino_historicas_sin_ocr(raiz_atlas=raiz)
    restantes = regenerar_decisiones_persistidas(
        decisiones=[*pendientes_actuales, *candidatas], carpeta_catalogos=catalogos,
    )
    bandeja = generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos,
        decisiones=restantes, ruta_salida=artefacto_ruta, reloj=reloj,
    )
    return {"decisiones_candidatas": len(candidatas), "decisiones_publicadas": len(bandeja["decisiones"]), "bandeja": bandeja}


def detectar_decisiones_cliente_candidato_sin_ocr(
    *, raiz_atlas: str | Path,
) -> list[dict[str, object]]:
    """R4.8 -- READ-ONLY, nunca escribe nada, sin OCR. A diferencia de
    `VEHICULO_DESCONOCIDO` (donde la decisión SIEMPRE existió y sólo había
    que reconciliarla contra el catálogo vigente, ver
    `regenerar_decisiones_persistidas`), `CLIENTE_CANDIDATO` nunca llegó a
    generarse para documentos ya procesados ANTES de este bloque -- no hay
    nada que reconciliar, hay que reconstruir la decisión desde cero, sólo
    con datos YA PERSISTIDOS (el dataset no retiene el RUT documental del
    cliente por guía, pero `CLIENTE_CANDIDATO` no lo necesita: opera
    exclusivamente sobre el nombre ya persistido en `cliente`).

    Para cada fila con el motivo `CLIENTE_SIN_CORROBORAR`, reconstruye un
    `datos` sintético mínimo (guía, transporte, cliente) y llama
    directamente a `detectar_decisiones_documento` -- el mismo mecanismo
    canónico de detección, nunca una segunda regla en paralelo -- filtrando
    sólo las decisiones `CLIENTE_CANDIDATO` que produce. Idéntico
    resultado, byte a byte, al que habría generado el procesamiento
    original si esta función ya hubiera existido entonces."""
    from atlas_core.decisiones_pendientes import detectar_decisiones_documento

    raiz = Path(raiz_atlas)
    catalogos = raiz / "catalogos_privados"
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    motivo_objetivo = MotivoRevisionDocumento.CLIENTE_SIN_CORROBORAR.value

    try:
        filas = _leer_filas(dataset)
    except (OSError, ValueError):
        return []

    candidatas: list[dict[str, object]] = []
    for fila in filas:
        motivos = [m for m in fila.get("motivos_revision_documento", "").split(SEPARADOR_MOTIVOS) if m]
        if motivo_objetivo not in motivos:
            continue
        cliente_documental = str(fila.get("cliente", "")).strip()
        if cliente_documental in _AUSENTES:
            continue
        datos_sinteticos = {
            "número de guía": fila.get("numero_guia", ""),
            "número de transporte": fila.get("numero_transporte", ""),
            "cliente": cliente_documental,
            "RUT del cliente": "",
        }
        try:
            decisiones = detectar_decisiones_documento(
                archivo=str(fila.get("archivo", "")), datos=datos_sinteticos, carpeta_catalogos=catalogos,
            )
        except (OSError, ValueError):
            continue
        candidatas.extend(d for d in decisiones if d.get("tipo") == "CLIENTE_CANDIDATO")
    return candidatas


def reconciliar_decisiones_cliente_candidato_historico(
    *, raiz_atlas: str | Path, reloj=lambda: datetime.now(timezone.utc),
) -> dict[str, object]:
    """Publica en `decisiones_pendientes.json` la unión de la bandeja
    pendiente vigente con las decisiones `CLIENTE_CANDIDATO` reconstruidas
    desde el histórico (ver `detectar_decisiones_cliente_candidato_sin_ocr`)
    -- mismo patrón que `reconciliar_decisiones_destino_historicas`/
    `reconciliar_decisiones_origen`. No toca ningún catálogo, el CSV
    documental ni el ledger -- sólo (re)escribe la bandeja."""
    from atlas_core.decisiones_pendientes import (
        NOMBRE_ARTEFACTO, generar_artefacto, regenerar_decisiones_persistidas,
    )

    raiz = Path(raiz_atlas)
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    dataset = actual / "analisis_completo_guias.csv"
    artefacto_ruta = actual / NOMBRE_ARTEFACTO

    try:
        artefacto_actual = json.loads(artefacto_ruta.read_text(encoding="utf-8"))
        pendientes_actuales = artefacto_actual.get("decisiones", [])
    except (OSError, json.JSONDecodeError):
        pendientes_actuales = []

    candidatas = detectar_decisiones_cliente_candidato_sin_ocr(raiz_atlas=raiz)
    restantes = regenerar_decisiones_persistidas(
        decisiones=[*pendientes_actuales, *candidatas], carpeta_catalogos=catalogos,
    )
    bandeja = generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos,
        decisiones=restantes, ruta_salida=artefacto_ruta, reloj=reloj,
    )
    return {"decisiones_candidatas": len(candidatas), "decisiones_publicadas": len(bandeja["decisiones"]), "bandeja": bandeja}


def detectar_decisiones_origen_sin_ocr(
    *, raiz_atlas: str | Path,
) -> list[dict[str, object]]:
    """Bloque ORIGEN D1 -- READ-ONLY, nunca escribe nada. Recorre el
    dataset vigente (ya persistido, sin OCR, sin red) y devuelve una
    decisión `ORIGEN_NO_CONFIRMADO` candidata por cada documento que hoy
    quedó sin planta de origen pero SÍ trae evidencia GPS suficiente para
    formular una sugerencia útil -- ver
    `atlas_core.decisiones_pendientes.detectar_decision_origen_no_confirmado`
    para el criterio exacto de abstención (nunca genera nada para un
    documento con telemetría demasiado escasa, tipo 464479/464529)."""
    from atlas_core.catalogo_plantas import CatalogoPlantas
    from atlas_core.decisiones_pendientes import detectar_decision_origen_no_confirmado

    raiz = Path(raiz_atlas)
    catalogos = raiz / "catalogos_privados"
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"

    try:
        filas = _leer_filas(dataset)
    except (OSError, ValueError):
        return []
    try:
        plantas = CatalogoPlantas(catalogos / "plantas.json").listar()
    except (OSError, ValueError):
        return []

    candidatas: list[dict[str, object]] = []
    for fila in filas:
        decision = detectar_decision_origen_no_confirmado(
            archivo=fila.get("archivo", ""), fila=fila, plantas=plantas,
        )
        if decision is not None:
            candidatas.append(decision)
    return candidatas


def reconciliar_decisiones_origen(
    *, raiz_atlas: str | Path, reloj=lambda: datetime.now(timezone.utc),
) -> dict[str, object]:
    """Bloque ORIGEN D1 -- publica en `decisiones_pendientes.json` la unión
    de la bandeja pendiente vigente con las decisiones `ORIGEN_NO_CONFIRMADO`
    recién detectadas (mismo patrón que `reconciliar_decisiones_destino_historicas`).
    No toca ningún catálogo, el CSV documental ni el ledger -- sólo
    (re)escribe la bandeja. `generar_artefacto` filtra contra el ledger al
    publicar, así que una decisión ya aplicada (CONFIRMAR_PLANTA/
    SELECCIONAR_OTRA_PLANTA/NO_PUEDO_DETERMINAR, todas terminales) nunca
    resucita mientras la evidencia (parte del `decision_id`) no cambie."""
    from atlas_core.decisiones_pendientes import (
        NOMBRE_ARTEFACTO, generar_artefacto, regenerar_decisiones_persistidas,
    )

    raiz = Path(raiz_atlas)
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    dataset = actual / "analisis_completo_guias.csv"
    artefacto_ruta = actual / NOMBRE_ARTEFACTO

    try:
        artefacto_actual = json.loads(artefacto_ruta.read_text(encoding="utf-8"))
        pendientes_actuales = artefacto_actual.get("decisiones", [])
    except (OSError, json.JSONDecodeError):
        pendientes_actuales = []

    candidatas = detectar_decisiones_origen_sin_ocr(raiz_atlas=raiz)
    restantes = regenerar_decisiones_persistidas(
        decisiones=[*pendientes_actuales, *candidatas], carpeta_catalogos=catalogos,
    )
    bandeja = generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos,
        decisiones=restantes, ruta_salida=artefacto_ruta, reloj=reloj,
    )
    return {"decisiones_candidatas": len(candidatas), "decisiones_publicadas": len(bandeja["decisiones"]), "bandeja": bandeja}


def detectar_decisiones_destino_no_resuelto_sin_ocr(
    *, raiz_atlas: str | Path,
) -> list[dict[str, object]]:
    """Bloque R6 A/B/E -- READ-ONLY, nunca escribe nada. Recorre el
    dataset vigente y devuelve una decisión `DESTINO_NO_RESUELTO`
    candidata por cada documento con origen ya resuelto pero cuya ruta
    quedó bloqueada por un problema de destino reconocido -- ver
    `atlas_core.decisiones_pendientes.detectar_decision_destino_no_resuelto`."""
    from atlas_core.decisiones_pendientes import detectar_decision_destino_no_resuelto

    raiz = Path(raiz_atlas)
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    try:
        filas = _leer_filas(dataset)
    except (OSError, ValueError):
        return []
    candidatas: list[dict[str, object]] = []
    for fila in filas:
        decision = detectar_decision_destino_no_resuelto(
            archivo=fila.get("archivo", ""), fila=fila,
        )
        if decision is not None:
            candidatas.append(decision)
    return candidatas


def reconciliar_decisiones_destino_no_resuelto(
    *, raiz_atlas: str | Path, reloj=lambda: datetime.now(timezone.utc),
) -> dict[str, object]:
    """Bloque R6 A/B/E -- publica en `decisiones_pendientes.json` la unión
    de la bandeja pendiente vigente con las decisiones `DESTINO_NO_RESUELTO`
    recién detectadas (mismo patrón que `reconciliar_decisiones_origen`). No
    toca el CSV documental, el ledger ni ningún catálogo -- sólo
    (re)escribe la bandeja."""
    from atlas_core.decisiones_pendientes import (
        NOMBRE_ARTEFACTO, generar_artefacto, regenerar_decisiones_persistidas,
    )

    raiz = Path(raiz_atlas)
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    dataset = actual / "analisis_completo_guias.csv"
    artefacto_ruta = actual / NOMBRE_ARTEFACTO

    try:
        artefacto_actual = json.loads(artefacto_ruta.read_text(encoding="utf-8"))
        pendientes_actuales = artefacto_actual.get("decisiones", [])
    except (OSError, json.JSONDecodeError):
        pendientes_actuales = []

    candidatas = detectar_decisiones_destino_no_resuelto_sin_ocr(raiz_atlas=raiz)
    restantes = regenerar_decisiones_persistidas(
        decisiones=[*pendientes_actuales, *candidatas], carpeta_catalogos=catalogos,
    )
    bandeja = generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos,
        decisiones=restantes, ruta_salida=artefacto_ruta, reloj=reloj,
    )
    return {"decisiones_candidatas": len(candidatas), "decisiones_publicadas": len(bandeja["decisiones"]), "bandeja": bandeja}


def detectar_decisiones_cliente_ausente_sin_ocr(
    *, raiz_atlas: str | Path,
) -> list[dict[str, object]]:
    """Bloque R9 -- READ-ONLY, nunca escribe nada. Recorre el dataset
    vigente y devuelve una decisión `CLIENTE_AUSENTE` candidata por cada
    documento con el campo cliente genuinamente vacío y el motivo
    bloqueante todavía presente -- ver
    `atlas_core.decisiones_pendientes.detectar_decision_cliente_ausente`."""
    from atlas_core.decisiones_pendientes import detectar_decision_cliente_ausente

    raiz = Path(raiz_atlas)
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    try:
        filas = _leer_filas(dataset)
    except (OSError, ValueError):
        return []
    candidatas: list[dict[str, object]] = []
    for fila in filas:
        decision = detectar_decision_cliente_ausente(archivo=fila.get("archivo", ""), fila=fila)
        if decision is not None:
            candidatas.append(decision)
    return candidatas


def reconciliar_decisiones_cliente_ausente(
    *, raiz_atlas: str | Path, reloj=lambda: datetime.now(timezone.utc),
) -> dict[str, object]:
    """Bloque R9 -- publica en `decisiones_pendientes.json` la unión de la
    bandeja pendiente vigente con las decisiones `CLIENTE_AUSENTE` recién
    detectadas (mismo patrón que `reconciliar_decisiones_destino_no_
    resuelto`). No toca el CSV documental, el ledger ni ningún catálogo
    -- sólo (re)escribe la bandeja."""
    from atlas_core.decisiones_pendientes import (
        NOMBRE_ARTEFACTO, generar_artefacto, regenerar_decisiones_persistidas,
    )

    raiz = Path(raiz_atlas)
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    dataset = actual / "analisis_completo_guias.csv"
    artefacto_ruta = actual / NOMBRE_ARTEFACTO

    try:
        artefacto_actual = json.loads(artefacto_ruta.read_text(encoding="utf-8"))
        pendientes_actuales = artefacto_actual.get("decisiones", [])
    except (OSError, json.JSONDecodeError):
        pendientes_actuales = []

    candidatas = detectar_decisiones_cliente_ausente_sin_ocr(raiz_atlas=raiz)
    restantes = regenerar_decisiones_persistidas(
        decisiones=[*pendientes_actuales, *candidatas], carpeta_catalogos=catalogos,
    )
    bandeja = generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos,
        decisiones=restantes, ruta_salida=artefacto_ruta, reloj=reloj,
    )
    return {"decisiones_candidatas": len(candidatas), "decisiones_publicadas": len(bandeja["decisiones"]), "bandeja": bandeja}


def detectar_incidencias_transporte_ausente_sin_ocr(
    *, raiz_atlas: str | Path,
) -> list[dict[str, str]]:
    """Bloque R5 I -- READ-ONLY, nunca escribe nada. Recorre el dataset
    vigente (ya persistido, sin OCR, sin red) y devuelve un candidato por
    cada documento marcado `TRANSPORTE_AUSENTE_SIN_ETIQUETA` (la etiqueta
    "NRO...TRANSPORTE" nunca apareció en el texto OCR y el documento no
    está degradado en general -- ver
    `atlas_core.procesamiento_masivo.MotivoRevisionDocumento`): omisión
    documental atribuible al mandante, candidata a Incidencia Documental."""
    raiz = Path(raiz_atlas)
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    try:
        filas = _leer_filas(dataset)
    except (OSError, ValueError):
        return []
    candidatas = []
    for fila in filas:
        motivos = {m.strip() for m in str(fila.get("motivos_revision_documento", "")).split("|")}
        if MotivoRevisionDocumento.TRANSPORTE_AUSENTE_SIN_ETIQUETA.value not in motivos:
            continue
        candidatas.append({
            "numero_guia": str(fila.get("numero_guia", "")),
            "numero_transporte": str(fila.get("numero_transporte", "")),
            "cliente": str(fila.get("cliente", "")),
        })
    return candidatas


def reconciliar_incidencias_transporte_documental(
    *, raiz_atlas: str | Path, reloj=lambda: datetime.now(timezone.utc),
) -> dict[str, object]:
    """Bloque R5 I -- registra, en el almacén ya existente de Incidencias
    Documentales (`atlas_core.incidencias_documentales`), una incidencia
    por cada documento detectado por
    `detectar_incidencias_transporte_ausente_sin_ocr`. Idempotente
    (`AlmacenIncidenciasDocumentales.registrar` no duplica por
    `incidencia_id`). No toca el CSV documental, el ledger de decisiones ni
    ningún catálogo -- sólo agrega al almacén de incidencias, que ya
    alimenta la pestaña Incidencias Documentales. `actor=""` porque la
    detección es automática, sin intervención humana puntual (mismo
    criterio documentado en `AlmacenIncidenciasDocumentales.registrar`)."""
    raiz = Path(raiz_atlas)
    ruta_incidencias = raiz / "catalogos_privados" / "incidencias_documentales.json"
    almacen = AlmacenIncidenciasDocumentales(ruta_incidencias)
    candidatas = detectar_incidencias_transporte_ausente_sin_ocr(raiz_atlas=raiz)
    registradas = []
    for candidata in candidatas:
        incidencia = almacen.registrar(
            contexto=candidata["cliente"], numero_guia=candidata["numero_guia"],
            numero_transporte=candidata["numero_transporte"], campo="numero_transporte",
            valor_documental=VALOR_DOCUMENTAL_CAMPO_AUSENTE, valor_canonico=VALOR_CANONICO_CAMPO_REQUERIDO,
            tipo_incidencia=TIPO_TRANSPORTE_AUSENTE_DOCUMENTAL,
            evidencia=("ETIQUETA_NRO_TRANSPORTE_NO_ENCONTRADA_EN_OCR", "DOCUMENTO_NO_DEGRADADO"),
            fecha=reloj(), fuente_resolucion="DETECCION_AUTOMATICA_SIN_ETIQUETA",
        )
        registradas.append(incidencia.incidencia_id)
    return {"candidatas": len(candidatas), "incidencias_registradas": registradas}


def _rut_canonico_para_chofer(
    *, nombre_chofer: str, filas: list[dict[str, str]], numero_guia_excluir: str,
    catalogo_choferes: dict[str, object],
) -> str | None:
    """Bloque FIX RUT DOCUMENTAL -- busca un RUT canónico confiable para
    `nombre_chofer` -- primero en el catálogo (nombre/alias exacto, único
    match, RUT confirmado -- nunca un placeholder `PENDIENTE...`), si no
    en el histórico del propio dataset (otras filas del MISMO nombre
    exacto de chofer cuyo `rut_chofer` persistido SÍ pasa validación
    estructural). Sólo lo usa si hay un único valor válido consistente
    entre los candidatos; nunca inventa, nunca promedia ni elige por
    mayoría entre valores distintos."""
    coincidencia = buscar_chofer_por_nombre_exacto(catalogo_choferes, nombre_chofer)
    if coincidencia is not None:
        identificador, _registro = coincidencia
        if len(identificador) >= 2 and not identificador.upper().startswith("PENDIENTE"):
            candidato = validar_rut_chileno(f"{identificador[:-1]}-{identificador[-1]}")
            if candidato.estado == EstadoValidacion.VALIDO:
                return candidato.valor

    vistos: set[str] = set()
    for fila in filas:
        if str(fila.get("numero_guia", "")) == numero_guia_excluir:
            continue
        if str(fila.get("chofer", "")).strip() != nombre_chofer:
            continue
        candidato = validar_rut_chileno(str(fila.get("rut_chofer", "")).strip())
        if candidato.estado == EstadoValidacion.VALIDO:
            vistos.add(candidato.valor)
    return next(iter(vistos)) if len(vistos) == 1 else None


def detectar_incidencias_rut_chofer_invalido_sin_ocr(
    *, raiz_atlas: str | Path,
) -> list[dict[str, str]]:
    """Bloque FIX RUT DOCUMENTAL -- READ-ONLY, nunca escribe nada, nunca
    OCR ni red. A diferencia de `detectar_incidencias_transporte_ausente_
    sin_ocr` (que lee un motivo ya fijado por el pipeline al momento del
    procesamiento), ésta RE-VALIDA directamente el `rut_chofer` ya
    persistido en el dataset -- necesario porque documentos procesados
    ANTES de que `atlas_core.validadores.validar_rut_chileno` incorporara
    el chequeo de plausibilidad nunca tuvieron oportunidad de fijar
    `RUT_CHOFER_INVALIDO` en `motivos_revision_documento` (caso real:
    guía de WLADIMIR AGUILAR con "55.555.555-5", dígito verificador
    correcto pero cuerpo implausible).

    Devuelve un candidato por cada fila con chofer identificado por
    nombre pero `rut_chofer` inválido, junto con el RUT canónico
    encontrado (catálogo o histórico del propio dataset), si lo hay --
    `rut_canonico` viene vacío cuando no hay ninguno confiable."""
    raiz = Path(raiz_atlas)
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    catalogo_ruta = raiz / "catalogos_privados" / "choferes.json"
    try:
        filas = _leer_filas(dataset)
    except (OSError, ValueError):
        return []
    catalogo_choferes = cargar_catalogo_json(catalogo_ruta)

    candidatas = []
    for fila in filas:
        nombre_chofer = str(fila.get("chofer", "")).strip()
        rut_chofer = str(fila.get("rut_chofer", "")).strip()
        if not nombre_chofer or nombre_chofer == "No encontrado" or not rut_chofer:
            continue
        # Sección 2 del bloque: sólo se trata como error documental
        # confirmado (nunca duda de OCR) -- mismo criterio que el
        # tiempo real en `procesamiento_masivo`.
        if not rut_documentalmente_confirmado_invalido(rut_chofer):
            continue
        canonico = _rut_canonico_para_chofer(
            nombre_chofer=nombre_chofer, filas=filas,
            numero_guia_excluir=str(fila.get("numero_guia", "")),
            catalogo_choferes=catalogo_choferes,
        )
        candidatas.append({
            "numero_guia": str(fila.get("numero_guia", "")),
            "numero_transporte": str(fila.get("numero_transporte", "")),
            "cliente": str(fila.get("cliente", "")),
            "chofer": nombre_chofer,
            "rut_documental": rut_chofer,
            "rut_canonico": canonico or "",
        })
    return candidatas


def reconciliar_incidencias_rut_chofer_documental(
    *, raiz_atlas: str | Path, reloj=lambda: datetime.now(timezone.utc),
) -> dict[str, object]:
    """Bloque FIX RUT DOCUMENTAL -- registra, en el almacén ya existente
    de Incidencias Documentales (`atlas_core.incidencias_documentales`),
    una incidencia por cada documento detectado por
    `detectar_incidencias_rut_chofer_invalido_sin_ocr`. Idempotente
    (`AlmacenIncidenciasDocumentales.registrar` no duplica por
    `incidencia_id`). Cuando hay un RUT canónico confiable (catálogo o
    histórico consistente), además CORRIGE ese `rut_chofer` en el
    dataset -- el valor documental inválido queda conservado como
    evidencia sólo en la incidencia, nunca en el dato operacional (ver
    Sección 3 del bloque: nunca se contamina catálogo/dataset con el
    valor inválido). Cuando no hay RUT canónico confiable, el dataset se
    deja intacto -- nunca se inventa un valor -- y la incidencia queda
    para revisión humana. `actor=""` porque la detección es automática."""
    raiz = Path(raiz_atlas)
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    ruta_incidencias = raiz / "catalogos_privados" / "incidencias_documentales.json"
    almacen = AlmacenIncidenciasDocumentales(ruta_incidencias)
    candidatas = detectar_incidencias_rut_chofer_invalido_sin_ocr(raiz_atlas=raiz)

    registradas = []
    corregidas = []
    filas: list[dict[str, str]] = []
    por_guia: dict[str, dict[str, str]] = {}
    if candidatas:
        filas = _leer_filas(dataset)
        por_guia = {str(fila.get("numero_guia", "")): fila for fila in filas}

    for candidata in candidatas:
        valor_canonico = candidata["rut_canonico"] or VALOR_CANONICO_RUT_NO_CONFIRMADO
        incidencia = almacen.registrar(
            contexto=candidata["cliente"], numero_guia=candidata["numero_guia"],
            numero_transporte=candidata["numero_transporte"], campo="RUT del chofer",
            valor_documental=candidata["rut_documental"], valor_canonico=valor_canonico,
            tipo_incidencia=TIPO_RUT_DOCUMENTAL_INVALIDO,
            evidencia=(
                f"CHOFER_IDENTIFICADO_POR_NOMBRE:{candidata['chofer']}",
                "RUT_CANONICO_CORROBORADO_CATALOGO_O_HISTORICO" if candidata["rut_canonico"]
                else "SIN_CANDIDATO_CANONICO_CONFIABLE",
            ),
            fecha=reloj(), fuente_resolucion="DETECCION_AUTOMATICA_RUT_INVALIDO",
        )
        registradas.append(incidencia.incidencia_id)
        if candidata["rut_canonico"]:
            fila = por_guia.get(candidata["numero_guia"])
            if fila is not None and fila.get("rut_chofer") == candidata["rut_documental"]:
                fila["rut_chofer"] = candidata["rut_canonico"]
                corregidas.append(candidata["numero_guia"])

    if corregidas:
        _escribir_filas_completas(dataset, filas)

    return {
        "candidatas": len(candidatas), "incidencias_registradas": registradas,
        "rut_corregido_en_dataset": corregidas,
    }


# MOTOR DE EVIDENCIA FASE 4 -- tope del punto fijo de auto-resolución en
# `reconciliar_bandeja_decisiones`: nunca un bucle infinito, aunque las
# aplicaciones se desbloqueen en cadena unas a otras.
MAX_ITERACIONES_AUTO_RESOLUCION = 10


def reconciliar_bandeja_decisiones(
    *, raiz_atlas: str | Path, reloj=lambda: datetime.now(timezone.utc),
) -> dict[str, object]:
    """Bloque RECONCILIACIÓN D1 -- re-publica la bandeja de decisiones
    pendientes vigente con un `dataset_sha256`/`catalogos_sha256` frescos,
    sin re-ejecutar OCR ni tocar el CSV documental. Necesario después de
    cualquier escritura controlada del dataset que no haya pasado por
    `generar_artefacto` (p. ej. la aplicación directa de ruta/km de un
    bloque anterior, que deja el `dataset_sha256` del artefacto desalineado
    del dataset real -- `aplicar_decision_obra` seguiría rechazando
    correctamente CUALQUIER decisión con `DecisionObsoletaError` hasta
    reconciliar).

    Reutiliza exclusivamente mecanismos ya existentes, en este orden:
    1. `regenerar_decisiones_persistidas` -- conserva sólo las decisiones
       todavía vigentes (descarta, por ejemplo, cualquier
       `VEHICULO_DESCONOCIDO` cuya patente documental ya homologó por otra
       vía), refresca contexto de apoyo (cliente/obra) por ID, y normaliza
       `acciones_permitidas` a la base de cada tipo.
    2. `enriquecer_decisiones_vehiculo` -- SÓLO DESPUÉS del paso anterior
       (que resetea `acciones_permitidas`): añade candidatos por
       asociación histórica de RUT de chofer a las `VEHICULO_DESCONOCIDO`
       que todavía no traigan ninguno, sumando `USAR_PATENTE_EXISTENTE`/
       `SELECCIONAR_OTRA_PATENTE` a las acciones ya normalizadas. Nunca
       autocorrige, nunca decide por mayoría/repetición documental.
    2b. MOTOR DE EVIDENCIA FASE 3 -- `enriquecer_decisiones_cliente`/
       `enriquecer_decisiones_obra`: añaden `evaluacion_evidencia`/
       `candidatos_evidencia` (informativo -- nunca cambia qué acciones
       puede aplicar el humano) a `CLIENTE_DESCONOCIDO`/`ALIAS_CANDIDATO`/
       `OBRA_DESCONOCIDA`, usando confirmaciones humanas independientes ya
       registradas y evidencia externa cacheada, si existen.
    3. `generar_artefacto` -- filtra contra el ledger (ninguna decisión ya
       cerrada, de cualquier tipo, resucita mientras su `decision_id` --
       que depende de la evidencia -- no cambie) y publica con los hashes
       actuales.
    4. MOTOR DE EVIDENCIA FASE 4 -- decisión de producto de Javier:
       `RESUELTO_AUTOMATICAMENTE` se aplica SOLO, sin pedir un clic.
       Reutiliza `aplicar_decision_obra` (nunca un segundo camino de
       escritura), `actor="ATLAS_AUTOMATICO"` -- auditable y
       distinguible de una confirmación humana en el ledger.
       `ALIAS_CANDIDATO` (CONFIRMAR_ALIAS) y, desde Bloque VEHÍCULO E2,
       `VEHICULO_DESCONOCIDO` (USAR_PATENTE_EXISTENTE -- sólo cuando
       `evaluar_evidencia_patente` encuentra un único candidato con
       corroboración documental independiente Y similitud OCR calibrada,
       ver `decisiones_pendientes.evaluar_evidencia_patente`) pueden
       alcanzar `RESUELTO_AUTOMATICAMENTE` hoy (`OBRA_DESCONOCIDA`/
       `CLIENTE_DESCONOCIDO` todavía no tienen una fuente de evidencia
       calibrada para ese nivel -- ver
       `atlas_core.motor_evidencia_obras`/`motor_evidencia_clientes`);
       cuando la tengan, este mismo mecanismo las cubre sin cambios.
       Punto fijo acotado (`MAX_ITERACIONES_AUTO_RESOLUCION`): una
       aplicación puede desbloquear otra (una confirmación nueva puede
       cruzar el umbral de independencia para una decisión hermana), así
       que se repite hasta que una pasada no aplique nada más.

    No modifica ningún catálogo ni el CSV documental por sí sola (el paso
    4 SÍ escribe catálogos/ledger -- exactamente lo mismo que ya hace
    `aplicar_decision_obra` para una confirmación humana, con el mismo
    respaldo/rollback transaccional)."""
    from atlas_core.aplicacion_decisiones import aplicar_decision_obra
    from atlas_core.catalogo_clientes import CatalogoClientes
    from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos
    from atlas_core.decisiones_pendientes import (
        NOMBRE_ARTEFACTO, enriquecer_decisiones_cliente, enriquecer_decisiones_obra,
        enriquecer_decisiones_vehiculo, generar_artefacto, regenerar_decisiones_persistidas,
    )
    from atlas_core.evidencia_entidades import AlmacenEvidenciaEntidades
    from atlas_core.verificacion_externa import CacheVerificacionExterna

    raiz = Path(raiz_atlas)
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    dataset = actual / "analisis_completo_guias.csv"
    artefacto_ruta = actual / NOMBRE_ARTEFACTO

    def _regenerar_enriquecer_publicar(pendientes: list[dict[str, object]]) -> dict[str, object]:
        vigentes_locales = regenerar_decisiones_persistidas(
            decisiones=pendientes, carpeta_catalogos=catalogos, ruta_dataset=dataset,
        )
        filas = _leer_filas(dataset)
        try:
            vehiculos = cargar_catalogo_vehiculos(catalogos / "vehiculos.json").homologables()
        except (OSError, CatalogoVehiculosAusenteError, CatalogoVehiculosCorruptoError, VersionCatalogoVehiculosDesconocidaError):
            vehiculos = ()
        enriquecidas_locales = enriquecer_decisiones_vehiculo(decisiones=vigentes_locales, filas=filas, vehiculos=vehiculos)

        try:
            clientes_confirmados = [
                c for c in CatalogoClientes(catalogos / "clientes.json").listar()
                if c.estado_calidad == "CONFIRMADO" and c.estado_vigencia == "ACTIVO"
            ]
        except (OSError, ValueError):
            clientes_confirmados = ()
        try:
            confirmaciones = AlmacenEvidenciaEntidades(catalogos / "evidencia_entidades.json").listar()
        except (OSError, ValueError):
            confirmaciones = ()
        try:
            cache_externa = CacheVerificacionExterna.desde_dict(
                json.loads((catalogos / "verificacion_externa_cache.json").read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError, ValueError):
            cache_externa = CacheVerificacionExterna()
        evidencia_externa_clientes = {clave: cache_externa.obtener(clave) or () for clave in cache_externa.entradas}
        enriquecidas_locales = enriquecer_decisiones_cliente(
            decisiones=enriquecidas_locales, clientes=clientes_confirmados, confirmaciones=confirmaciones,
            evidencia_externa_por_clave=evidencia_externa_clientes,
        )
        try:
            obras_vigentes = CatalogoObrasDestinos(
                ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
                ruta_destinos=catalogos / "destinos_maestros.json",
            ).listar_obras()
        except (OSError, ValueError):
            obras_vigentes = ()
        enriquecidas_locales = enriquecer_decisiones_obra(
            decisiones=enriquecidas_locales, obras=obras_vigentes, evidencia_externa_por_clave=evidencia_externa_clientes,
        )

        bandeja_local = generar_artefacto(
            ruta_dataset=dataset, carpeta_catalogos=catalogos,
            decisiones=enriquecidas_locales, ruta_salida=artefacto_ruta, reloj=reloj,
        )
        return {"vigentes": vigentes_locales, "bandeja": bandeja_local}

    try:
        artefacto_actual = json.loads(artefacto_ruta.read_text(encoding="utf-8"))
        pendientes_actuales = artefacto_actual.get("decisiones", [])
    except (OSError, json.JSONDecodeError):
        pendientes_actuales = []

    resultado_primero = _regenerar_enriquecer_publicar(pendientes_actuales)
    vigentes = resultado_primero["vigentes"]
    bandeja = resultado_primero["bandeja"]

    # Bloque VEHÍCULO E2 -- acción de aplicación automática por tipo:
    # ALIAS_CANDIDATO vincula la canónica sugerida vía CONFIRMAR_ALIAS
    # (ya existente); VEHICULO_DESCONOCIDO hace lo mismo vía
    # USAR_PATENTE_EXISTENTE (exige exactamente un candidato en
    # `decision["candidatos"]" -- garantizado por
    # `evaluar_evidencia_patente`, que sólo alcanza
    # RESUELTO_AUTOMATICAMENTE con un único competidor en el nivel más
    # alto). Nunca CLIENTE_DESCONOCIDO/OBRA_DESCONOCIDA con REGISTRAR:
    # eso crearía una entidad nueva, no aplicaría una ya conocida, y no
    # es lo que este resultado significa.
    _ACCION_AUTO_POR_TIPO = {"ALIAS_CANDIDATO": "CONFIRMAR_ALIAS", "VEHICULO_DESCONOCIDO": "USAR_PATENTE_EXISTENTE"}

    aplicadas_automaticamente: list[dict[str, object]] = []
    for _ in range(MAX_ITERACIONES_AUTO_RESOLUCION):
        candidatas = [
            d for d in bandeja["decisiones"]
            if d.get("tipo") in _ACCION_AUTO_POR_TIPO
            and (d.get("evaluacion_evidencia") or {}).get("resultado") == "RESUELTO_AUTOMATICAMENTE"
        ]
        if not candidatas:
            break
        for decision in candidatas:
            resultado_aplicacion = aplicar_decision_obra(
                raiz_atlas=raiz, decision_id=decision["decision_id"],
                accion=_ACCION_AUTO_POR_TIPO[decision["tipo"]],
                actor="ATLAS_AUTOMATICO", reloj=reloj,
            )
            aplicadas_automaticamente.append({
                "decision_id": decision["decision_id"], "documento": decision.get("documento"),
                "valor_documental": decision.get("valor_documental"), "resultado": resultado_aplicacion,
            })
        pendientes_tras_aplicar = json.loads(artefacto_ruta.read_text(encoding="utf-8")).get("decisiones", [])
        resultado_pasada = _regenerar_enriquecer_publicar(pendientes_tras_aplicar)
        bandeja = resultado_pasada["bandeja"]

    return {
        "decisiones_antes": len(pendientes_actuales),
        "decisiones_conservadas": len(vigentes),
        "decisiones_publicadas": len(bandeja["decisiones"]),
        "decisiones_aplicadas_automaticamente": aplicadas_automaticamente,
        "bandeja": bandeja,
    }
