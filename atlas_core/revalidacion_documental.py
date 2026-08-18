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

from atlas_core.almacenamiento_portable import bloqueo_sesion
from atlas_core.catalogo_clientes import CatalogoClientes
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, normalizar_nombre_obra
from atlas_core.catalogo_vehiculos import (
    CatalogoVehiculosAusenteError,
    CatalogoVehiculosCorruptoError,
    VersionCatalogoVehiculosDesconocidaError,
    Vehiculo,
    VehiculoDuplicadoError,
    cargar_catalogo_vehiculos,
    normalizar_patente_vehiculo,
)
from atlas_core.procesamiento_masivo import (
    COLUMNAS,
    MOTIVOS_NO_BLOQUEANTES,
    MotivoRevisionDocumento,
)
from atlas_core.reporte_viajes import generar_reporte_viajes

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


def revalidar_obra_destino_sin_ocr(
    *, ruta_dataset: str | Path, carpeta_catalogos: str | Path,
) -> dict[str, object]:
    """Relee cada fila del dataset y reevalúa ÚNICAMENTE el motivo
    ``OBRA_DESTINO_SIN_CORROBORAR`` contra `resolver_obra_destino_confirmada_global`
    (sin cliente_id -- ver R3.4/R3.3.1). Si ahora resuelve, retira el motivo
    de esa fila y recalcula `indicador_revision`; nunca toca ningún otro
    campo. No ejecuta OCR ni vuelve a extraer nada -- sólo lee el dataset ya
    persistido y los catálogos vigentes. Se abstiene fila por fila ante
    cualquier duda (obra ausente/"No encontrado", error de catálogo, etc.)."""
    ruta = Path(ruta_dataset)
    carpeta = Path(carpeta_catalogos)
    catalogo_obras = CatalogoObrasDestinos(
        ruta=carpeta / "obras_destinos.json",
        ruta_clientes=carpeta / "clientes.json",
        ruta_destinos=carpeta / "destinos_maestros.json",
    )
    motivo_objetivo = MotivoRevisionDocumento.OBRA_DESTINO_SIN_CORROBORAR.value

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
    *, ruta_dataset: str | Path, carpeta_catalogos: str | Path,
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
    Se abstiene fila por fila ante cualquier duda: patente ausente pero
    relevante sin resolver, catálogo ambiguo/inactivo/no confirmado, tipo
    incompatible con el rol documental, o error de catálogo. Nunca crea
    relación chofer<->vehículo (fuera de alcance de R3.6.2)."""
    ruta = Path(ruta_dataset)
    carpeta = Path(carpeta_catalogos)
    motivo_objetivo = MotivoRevisionDocumento.PATENTE_SIN_HOMOLOGAR.value

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

            if rampla_presente:
                rampla_resuelta = _vehiculo_homologado(
                    vehiculos_homologables, normalizar_patente_vehiculo(rampla_doc)
                )
                if rampla_resuelta is None or rampla_resuelta.tipo != _TIPO_CARRO:
                    continue  # rampla sin resolver o tipo incompatible -> conservar

            if tracto_presente:
                tracto_resuelto = _vehiculo_homologado(
                    vehiculos_homologables, normalizar_patente_vehiculo(tracto_doc)
                )
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
        ruta_dataset=dataset, carpeta_catalogos=catalogos,
    )
    resultado_patente = revalidar_patente_sin_homologar_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=catalogos,
    )
    guias_actualizadas = sorted(
        set(resultado_obra_destino["guias_actualizadas"]) | set(resultado_patente["guias_actualizadas"])
    )
    resultado_revalidacion: dict[str, object] = {
        "filas_totales": resultado_patente["filas_totales"],
        "guias_actualizadas": guias_actualizadas,
        "obra_destino": resultado_obra_destino,
        "patente": resultado_patente,
    }
    if not guias_actualizadas:
        return {**resultado_revalidacion, "reporte_regenerado": False}

    from atlas_core.almacenamiento_portable import escribir_estado_operacion
    from atlas_core.decisiones_pendientes import NOMBRE_ARTEFACTO

    salida = raiz / "reportes" / nombre_carpeta_reporte
    kwargs = {"carpeta_catalogos": catalogos}
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
