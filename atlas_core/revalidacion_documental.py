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
from atlas_core.extractor import _patente_valida
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
    from atlas_core.rutas.destino_entrega import _comuna_documental_inequivoca, _texto_normalizado_sin_acentos

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


def revalidar_ruta_sin_destino_calculado_sin_ocr(
    *, ruta_dataset: str | Path, carpeta_catalogos: str | Path,
    proveedor_rutas=None, perfil: str = "driving-hgv",
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
    igual que el pipeline en vivo -- inyectable para tests."""
    from atlas_core.catalogo_plantas import CatalogoPlantas
    from atlas_core.rutas.destino_entrega import calcular_ruta_con_planta_conocida

    ruta = Path(ruta_dataset)
    carpeta = Path(carpeta_catalogos)
    if proveedor_rutas is None:
        from atlas_core.rutas.cache_geocodificacion import (
            ProveedorRutasConCacheGeocodificacion,
            RepositorioCacheGeocodificacion,
        )
        from atlas_core.rutas.openrouteservice import OpenRouteService

        proveedor_rutas = ProveedorRutasConCacheGeocodificacion(
            OpenRouteService(), RepositorioCacheGeocodificacion(),
        )
    try:
        plantas_por_id = {p.planta_id: p for p in CatalogoPlantas(carpeta / "plantas.json").listar()}
    except (OSError, ValueError):
        plantas_por_id = {}

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
            try:
                resultado = calcular_ruta_con_planta_conocida(
                    planta=planta, despachar_a_crudo=despachar_a, proveedor_rutas=proveedor_rutas,
                    origen_determinado_por=str(fila.get("origen_determinado_por", "")),
                    evidencia_origen=str(fila.get("evidencia_origen", "")),
                    perfil=perfil,
                )
            except (OSError, ValueError):
                continue
            if resultado.estado_ruta != EstadoRuta.RUTA_CALCULADA.value:
                continue  # sigue sin resolver con evidencia suficiente -- nunca inventa
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


def revalidar_y_regenerar_reporte(
    *, raiz_atlas: str | Path, nombre_carpeta_reporte: str, reloj=None,
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
    guias_actualizadas = sorted(
        set(resultado_obra_destino["guias_actualizadas"])
        | set(resultado_patente["guias_actualizadas"])
        | set(resultado_cliente["guias_actualizadas"])
        | set(resultado_destino_contradicho["guias_actualizadas"])
    )
    resultado_revalidacion: dict[str, object] = {
        "filas_totales": resultado_patente["filas_totales"],
        "guias_actualizadas": guias_actualizadas,
        "obra_destino": resultado_obra_destino,
        "patente": resultado_patente,
        "cliente": resultado_cliente,
        "destino_contradicho": resultado_destino_contradicho,
    }
    if not guias_actualizadas:
        return {**resultado_revalidacion, "reporte_regenerado": False}

    from atlas_core.almacenamiento_portable import escribir_estado_operacion
    from atlas_core.decisiones_pendientes import NOMBRE_ARTEFACTO

    salida = raiz / "reportes" / nombre_carpeta_reporte
    kwargs = {"carpeta_catalogos": catalogos, "ruta_ledger": actual / "decisiones_aplicadas.json"}
    if reloj is not None:
        kwargs["reloj"] = reloj
    manifest = generar_reporte_viajes(dataset, salida, **kwargs)
    ruta_decisiones = actual / NOMBRE_ARTEFACTO
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
       distinguible de una confirmación humana en el ledger. Hoy sólo
       `ALIAS_CANDIDATO` puede alcanzar `RESUELTO_AUTOMATICAMENTE`
       (`OBRA_DESCONOCIDA`/`CLIENTE_DESCONOCIDO` todavía no tienen una
       fuente de evidencia calibrada para ese nivel -- ver
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
            decisiones=pendientes, carpeta_catalogos=catalogos,
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

    aplicadas_automaticamente: list[dict[str, object]] = []
    for _ in range(MAX_ITERACIONES_AUTO_RESOLUCION):
        candidatas = [
            d for d in bandeja["decisiones"]
            # Hoy sólo ALIAS_CANDIDATO tiene una acción de aplicación
            # capaz de vincular la canónica sugerida sin más datos que
            # los que ya trae la propia decisión (CONFIRMAR_ALIAS) --
            # ver docstring. Nunca CLIENTE_DESCONOCIDO/OBRA_DESCONOCIDA
            # con REGISTRAR: eso crearía una entidad nueva, no aplicaría
            # una ya conocida, y no es lo que este resultado significa.
            if d.get("tipo") == "ALIAS_CANDIDATO"
            and (d.get("evaluacion_evidencia") or {}).get("resultado") == "RESUELTO_AUTOMATICAMENTE"
        ]
        if not candidatas:
            break
        for decision in candidatas:
            resultado_aplicacion = aplicar_decision_obra(
                raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR_ALIAS",
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
