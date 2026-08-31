from datetime import datetime, timezone

import pytest

from atlas_core.gestor_viajes import (
    EstadoViaje,
    MotivoRevision,
    agrupar_viajes,
)


def _fila(**cambios):
    fila = {
        "archivo": "guía ñ.jpg",
        "numero_guia": "000101",
        "numero_transporte": "00002001",
        "fecha": "2026-07-28",
        "chofer": "JOSÉ PÉREZ",
        "rut_chofer": "12.345.678-5",
        "cliente": "CLIENTE ÑUBLE",
        "obra_destino": "OBRA ÁGUILA",
        "patente_tracto": "ABCD12",
        "patente_rampla": "EFGH34",
        "descripcion_material": "BARRAS",
        "tipo_carga": "BARRAS",
        "peso_kg": "1000",
        "hora_entrada_aza": "07:00",
        "hora_salida_aza": "18:00",
    }
    fila.update(cambios)
    return fila


def test_una_guia_con_transporte_conserva_ceros_y_campos():
    viajes, pendientes = agrupar_viajes([_fila()])
    assert not pendientes
    assert len(viajes) == 1
    assert viajes[0].numero_transporte == "00002001"
    assert viajes[0].numeros_guia == ["000101"]
    assert viajes[0].clientes == ["CLIENTE ÑUBLE"]


def test_routing_multidocumento_no_mezcla_ruta_valida_con_fallo_geocodificacion():
    filas = [
        _fila(
            archivo="ruta.jpg", numero_guia="464264",
            distancia_km="546.8017", duracion_min="621.88",
            proveedor_ruta="openrouteservice", estado_ruta="RUTA_CALCULADA",
            motivo_ruta="",
        ),
        _fila(
            archivo="fallo.jpg", numero_guia="464265",
            distancia_km="", duracion_min="", proveedor_ruta="",
            estado_ruta="REQUIERE_REVISION",
            motivo_ruta="GEOCODIFICACION_DIRECCION_NO_ENCONTRADA",
        ),
    ]

    viajes, _ = agrupar_viajes(filas)
    viaje = viajes[0].a_dict()

    assert viaje["distancia_km"] == ""
    assert viaje["duracion_min"] == ""
    assert viaje["proveedor_ruta"] == ""
    assert viaje["estado_ruta"] == "REQUIERE_REVISION"
    assert viaje["motivo_ruta"] == "GEOCODIFICACION_DIRECCION_NO_ENCONTRADA"


@pytest.mark.parametrize("transporte", ["0000349935", "  0000349935  "])
def test_transporte_numerico_conserva_ceros_y_admite_espacios_exteriores(
    transporte,
):
    viajes, pendientes = agrupar_viajes([_fila(numero_transporte=transporte)])
    assert not pendientes
    assert viajes[0].numero_transporte == "0000349935"


def test_tres_guias_mismo_transporte_se_agrupan_sin_duplicar_guias():
    filas = [
        _fila(archivo="a.jpg", numero_guia="000101"),
        _fila(archivo="b.jpg", numero_guia="000102"),
        _fila(archivo="c.jpg", numero_guia="000102"),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert len(viajes) == 1
    assert viajes[0].numeros_guia == ["000101", "000102"]
    assert len(viajes[0].documentos) == 3


def test_fila_exactamente_duplicada_no_duplica_documento():
    fila = _fila()
    viajes, _ = agrupar_viajes([fila, dict(fila)])
    assert len(viajes[0].documentos) == 1


@pytest.mark.parametrize(
    "transporte",
    ["", "No encontrado", "REVISAR", "ILEGIBLE", "ABC0349935", "valor inválido !"],
)
def test_transporte_ausente_o_invalido_queda_pendiente(transporte):
    viajes, pendientes = agrupar_viajes([_fila(numero_transporte=transporte)])
    assert not viajes
    assert pendientes == [_fila(numero_transporte=transporte)]


def test_chofer_canonico_fuzzy_se_conserva():
    viajes, _ = agrupar_viajes(
        [_fila(chofer="J0SE PEREZ")],
        normalizador_chofer=lambda _: "JOSÉ PÉREZ",
    )
    assert viajes[0].choferes == ["JOSÉ PÉREZ"]
    assert viajes[0].documentos[0].evidencia["chofer"] == "J0SE PEREZ"


@pytest.mark.parametrize(
    ("campo", "valor", "motivo"),
    [
        ("chofer", "OTRO CHOFER", MotivoRevision.CONFLICTO_CHOFER),
        ("rut_chofer", "9.999.999-9", MotivoRevision.CONFLICTO_RUT_CHOFER),
        ("cliente", "OTRO CLIENTE", MotivoRevision.CONFLICTO_CLIENTE),
        ("obra_destino", "OTRA OBRA", MotivoRevision.CONFLICTO_OBRA_DESTINO),
        ("patente_tracto", "ZZZZ99", MotivoRevision.CONFLICTO_PATENTE_TRACTO),
        ("patente_rampla", "YYYY88", MotivoRevision.CONFLICTO_PATENTE_RAMPLA),
        ("fecha", "2026-07-29", MotivoRevision.CONFLICTO_FECHA),
        ("hora_entrada_aza", "09:00", MotivoRevision.CONFLICTO_HORA_ENTRADA),
        ("hora_salida_aza", "19:00", MotivoRevision.CONFLICTO_HORA_SALIDA),
    ],
)
def test_contradicciones_activan_revision_y_preservan_evidencia(
    campo, valor, motivo
):
    filas = [_fila(archivo="a.jpg"), _fila(archivo="b.jpg", **{campo: valor})]
    viajes, _ = agrupar_viajes(filas)
    viaje = viajes[0]
    assert viaje.estado == EstadoViaje.REQUIERE_REVISION
    assert motivo in viaje.motivos_revision
    assert viaje.documentos[0].evidencia[campo] != viaje.documentos[1].evidencia[campo]


@pytest.mark.parametrize(
    ("rut_a", "rut_b"),
    [
        ("10.833.150-K", "10833150-K"),  # caso real: 464641/464642, transporte 0000352752
        ("10.833.150-K", "10833150-k"),  # dígito verificador en minúscula
        ("10.833.150-k", "10833150-K"),
        ("  10.833.150-K  ", "10833150-K"),  # espacios exteriores
    ],
)
def test_rut_chofer_equivalente_en_formato_no_genera_conflicto(rut_a, rut_b):
    filas = [
        _fila(archivo="a.jpg", rut_chofer=rut_a),
        _fila(archivo="b.jpg", rut_chofer=rut_b),
    ]
    viajes, _ = agrupar_viajes(filas)
    viaje = viajes[0]
    assert MotivoRevision.CONFLICTO_RUT_CHOFER not in viaje.motivos_revision
    assert viaje.estado == EstadoViaje.CONFIRMADO
    # La evidencia documental original -- con o sin puntuación -- se
    # preserva byte a byte; sólo cambia si se considera conflicto.
    assert viaje.documentos[0].evidencia["rut_chofer"] == rut_a
    assert viaje.documentos[1].evidencia["rut_chofer"] == rut_b


def test_rut_chofer_realmente_distinto_sigue_generando_conflicto():
    filas = [
        _fila(archivo="a.jpg", rut_chofer="10.833.150-K"),
        _fila(archivo="b.jpg", rut_chofer="12.345.678-5"),
    ]
    viajes, _ = agrupar_viajes(filas)
    viaje = viajes[0]
    assert viaje.estado == EstadoViaje.REQUIERE_REVISION
    assert MotivoRevision.CONFLICTO_RUT_CHOFER in viaje.motivos_revision


@pytest.mark.parametrize("rut_ausente", ["", "No encontrado", "REVISAR", "ILEGIBLE"])
def test_rut_chofer_ausente_en_un_documento_no_genera_conflicto(rut_ausente):
    # Mismo comportamiento previo: un valor ausente nunca compite con el
    # valor presente del otro documento.
    filas = [
        _fila(archivo="a.jpg", rut_chofer="10.833.150-K"),
        _fila(archivo="b.jpg", rut_chofer=rut_ausente),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert MotivoRevision.CONFLICTO_RUT_CHOFER not in viajes[0].motivos_revision


def test_rut_chofer_no_parseable_distinto_sigue_generando_conflicto():
    # Texto sin ningún dígito/"K": no tiene forma de RUT, así que se
    # compara literalmente (normalizado por acentos/mayúsculas, igual que
    # antes) en vez de intentar normalizar como RUT -- no se oculta el
    # conflicto ni se degrada a una igualdad artificial.
    filas = [
        _fila(archivo="a.jpg", rut_chofer="SIN RUT VISIBLE"),
        _fila(archivo="b.jpg", rut_chofer="OTRO TEXTO SIN RUT"),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert MotivoRevision.CONFLICTO_RUT_CHOFER in viajes[0].motivos_revision


def test_rut_chofer_no_parseable_identico_no_genera_conflicto():
    # Mismo texto no-RUT en ambos documentos: ya era compatible antes del
    # cambio (misma clave normalizada) y sigue siéndolo -- el fallback a
    # comparación literal no introduce una regresión aquí.
    filas = [
        _fila(archivo="a.jpg", rut_chofer="SIN RUT VISIBLE"),
        _fila(archivo="b.jpg", rut_chofer="sin rut visible"),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert MotivoRevision.CONFLICTO_RUT_CHOFER not in viajes[0].motivos_revision


def test_otros_campos_de_conflicto_no_cambian_su_comparacion():
    # La tolerancia de formato es exclusiva de rut_chofer: dos valores de
    # chofer que sólo difieren en puntuación/formato (no en contenido real)
    # deben seguir comparándose tal como antes -- literalmente (salvo
    # acentos/mayúsculas/espacios, como ya hacía _clave_normalizada).
    filas = [
        _fila(archivo="a.jpg", chofer="JOSE LAZCANO"),
        _fila(archivo="b.jpg", chofer="JOSE  LAZCANO."),
    ]
    viajes, _ = agrupar_viajes(filas)
    # "JOSE  LAZCANO." (con punto final) no es la misma clave normalizada
    # que "JOSE LAZCANO" -- el comportamiento de chofer no cambió.
    assert MotivoRevision.CONFLICTO_CHOFER in viajes[0].motivos_revision


def test_origen_opcional_contradictorio_activa_revision():
    """`origen=...` (columna sintética, nunca existió en el esquema real)
    reemplazado por los campos reales que sí llegan de
    `analisis_completo_guias.csv` -- mismo escenario, misma fuente
    (DOCUMENTO en ambos, mismo nivel de jerarquía) pero plantas distintas."""
    filas = [
        _fila(
            archivo="a.jpg",
            planta_origen_id="PLANTA-NORTE", planta_origen_nombre="PLANTA NORTE",
            origen_determinado_por="DOCUMENTO",
        ),
        _fila(
            archivo="b.jpg",
            planta_origen_id="PLANTA-SUR", planta_origen_nombre="PLANTA SUR",
            origen_determinado_por="DOCUMENTO",
        ),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert MotivoRevision.CONFLICTO_ORIGEN in viajes[0].motivos_revision


def test_conflictos_multiples_se_declaran_juntos_sin_perder_evidencia():
    filas = [
        _fila(
            archivo="a.jpg",
            planta_origen_id="PLANTA-BASE", planta_origen_nombre="ORIGEN BASE",
            origen_determinado_por="DOCUMENTO",
            hora_entrada_aza="07:00", hora_salida_aza="08:00",
        ),
        _fila(
            archivo="b.jpg",
            fecha="2026-07-29",
            chofer="OTRO CHOFER",
            rut_chofer="9.999.999-9",
            cliente="OTRO CLIENTE",
            obra_destino="OTRA OBRA",
            planta_origen_id="PLANTA-OTRA", planta_origen_nombre="OTRO ORIGEN",
            origen_determinado_por="DOCUMENTO",
            patente_tracto="ZZZZ99",
            patente_rampla="YYYY88",
            hora_entrada_aza="09:00", hora_salida_aza="10:00",
        ),
    ]
    viajes, _ = agrupar_viajes(filas)
    viaje = viajes[0]
    assert viaje.estado == EstadoViaje.REQUIERE_REVISION
    assert set(viaje.motivos_revision) == set(MotivoRevision) - {
        MotivoRevision.FECHA_NO_COMPATIBLE_DESKTOP,
        # Ninguna fila de este escenario trae indicador_revision=REVISAR;
        # ese motivo es independiente de los conflictos entre documentos.
        MotivoRevision.DOCUMENTO_REQUIERE_REVISION,
    }
    assert len(viaje.a_dict()["evidencias_documentos"]) == 2


# ---- Bloque ORIGEN DE VIAJE: consolidación jerárquica GPS > documento ----


def test_origen_dos_documentos_gps_misma_planta_sin_conflicto():
    """CASO 1: dos documentos confirman la misma planta por GPS -- el
    viaje la usa, sin conflicto."""
    filas = [
        _fila(
            archivo="a.jpg",
            planta_origen_id="PLANTA-A", planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
        ),
        _fila(
            archivo="b.jpg",
            planta_origen_id="PLANTA-A", planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
        ),
    ]
    viajes, _ = agrupar_viajes(filas)
    viaje = viajes[0]
    assert viaje.planta_origen_nombre == "AZA COLINA"
    assert viaje.origen_determinado_por == "TELEMETRIA_GPS"
    assert MotivoRevision.CONFLICTO_ORIGEN not in viaje.motivos_revision


def test_origen_gps_gana_sobre_documental_distinto_sin_degradarse():
    """CASO 2 (y CASO REAL, estructuralmente equivalente a 0000351135,
    sin hardcodear guía/transporte/planta reales): un documento confirma
    por GPS, el otro cae al respaldo documental con una planta distinta
    (p. ej. porque su propia patente no permitió ubicar el vehículo) -- el
    viaje debe conservar la planta GPS, nunca degradarse a la documental."""
    filas = [
        _fila(
            archivo="a.jpg",
            planta_origen_id="PLANTA-GPS", planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
        ),
        _fila(
            archivo="b.jpg",
            planta_origen_id="PLANTA-DOC", planta_origen_nombre="AZA RENCA",
            origen_determinado_por="DOCUMENTO",
        ),
    ]
    viajes, _ = agrupar_viajes(filas)
    viaje = viajes[0]
    assert viaje.planta_origen_id == "PLANTA-GPS"
    assert viaje.planta_origen_nombre == "AZA COLINA"
    assert viaje.origen_determinado_por == "TELEMETRIA_GPS"
    assert MotivoRevision.CONFLICTO_ORIGEN not in viaje.motivos_revision


def test_origen_dos_gps_distintos_genera_conflicto_real():
    """CASO 3: dos documentos, ambos confirmados por GPS, pero en plantas
    distintas -- conflicto real, ninguna se elige arbitrariamente."""
    filas = [
        _fila(
            archivo="a.jpg",
            planta_origen_id="PLANTA-A", planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
        ),
        _fila(
            archivo="b.jpg",
            planta_origen_id="PLANTA-B", planta_origen_nombre="AZA RENCA",
            origen_determinado_por="TELEMETRIA_GPS",
        ),
    ]
    viajes, _ = agrupar_viajes(filas)
    viaje = viajes[0]
    assert viaje.planta_origen_nombre == ""
    assert MotivoRevision.CONFLICTO_ORIGEN in viaje.motivos_revision


def test_origen_sin_gps_documentos_coinciden_usa_origen_documental():
    """CASO 4: sin evidencia GPS en ningún documento, pero todos los
    orígenes documentales coinciden -- el viaje usa ese origen común, con
    fuente DOCUMENTO."""
    filas = [
        _fila(
            archivo="a.jpg",
            planta_origen_id="PLANTA-A", planta_origen_nombre="AZA RENCA",
            origen_determinado_por="DOCUMENTO",
        ),
        _fila(
            archivo="b.jpg",
            planta_origen_id="PLANTA-A", planta_origen_nombre="AZA RENCA",
            origen_determinado_por="DOCUMENTO",
        ),
    ]
    viajes, _ = agrupar_viajes(filas)
    viaje = viajes[0]
    assert viaje.planta_origen_nombre == "AZA RENCA"
    assert viaje.origen_determinado_por == "DOCUMENTO"
    assert MotivoRevision.CONFLICTO_ORIGEN not in viaje.motivos_revision


def test_origen_sin_gps_documentos_discrepan_genera_conflicto():
    """CASO 5: sin GPS, orígenes documentales discrepan -- conflicto real."""
    filas = [
        _fila(
            archivo="a.jpg",
            planta_origen_id="PLANTA-A", planta_origen_nombre="AZA RENCA",
            origen_determinado_por="DOCUMENTO",
        ),
        _fila(
            archivo="b.jpg",
            planta_origen_id="PLANTA-B", planta_origen_nombre="AZA COLINA",
            origen_determinado_por="DOCUMENTO",
        ),
    ]
    viajes, _ = agrupar_viajes(filas)
    viaje = viajes[0]
    assert viaje.planta_origen_nombre == ""
    assert MotivoRevision.CONFLICTO_ORIGEN in viaje.motivos_revision


def test_origen_un_documento_sin_origen_otro_con_gps_usa_gps():
    """CASO 6: un documento no tiene origen resuelto en absoluto (campos
    vacíos), el otro sí lo confirma por GPS -- el viaje usa el GPS, el
    documento vacío no impide ni degrada la consolidación."""
    filas = [
        _fila(archivo="a.jpg"),  # sin planta_origen_id/nombre/determinado_por
        _fila(
            archivo="b.jpg",
            planta_origen_id="PLANTA-A", planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
        ),
    ]
    viajes, _ = agrupar_viajes(filas)
    viaje = viajes[0]
    assert viaje.planta_origen_nombre == "AZA COLINA"
    assert viaje.origen_determinado_por == "TELEMETRIA_GPS"
    assert MotivoRevision.CONFLICTO_ORIGEN not in viaje.motivos_revision


def test_origen_ningun_documento_resuelve_queda_no_determinado():
    """CASO 7: ningún documento del viaje tiene origen -- el viaje queda
    honestamente sin determinar, sin conflicto (no hay nada que comparar)."""
    filas = [_fila(archivo="a.jpg"), _fila(archivo="b.jpg")]
    viajes, _ = agrupar_viajes(filas)
    viaje = viajes[0]
    assert viaje.planta_origen_id == ""
    assert viaje.planta_origen_nombre == ""
    assert viaje.origen_determinado_por == ""
    assert MotivoRevision.CONFLICTO_ORIGEN not in viaje.motivos_revision


def test_origen_diferencias_de_formato_en_id_no_crean_conflicto_falso():
    """Negativo: el mismo identificador de planta con diferencias de
    mayúsculas/espacios (ruido de formato, nunca de identidad real) no
    genera un conflicto -- la comparación usa la misma normalización
    canónica ya usada para el resto de campos de este módulo."""
    filas = [
        _fila(
            archivo="a.jpg",
            planta_origen_id="planta-colina", planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
        ),
        _fila(
            archivo="b.jpg",
            planta_origen_id="  PLANTA-COLINA  ", planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
        ),
    ]
    viajes, _ = agrupar_viajes(filas)
    viaje = viajes[0]
    assert MotivoRevision.CONFLICTO_ORIGEN not in viaje.motivos_revision


def test_origen_no_se_hereda_entre_viajes_distintos():
    """Negativo: dos transportes distintos, cada uno con su propio origen
    -- nunca se mezclan ni se hereda evidencia de un viaje a otro."""
    filas = [
        _fila(
            archivo="a.jpg", numero_transporte="00002001",
            planta_origen_id="PLANTA-A", planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
        ),
        _fila(
            archivo="b.jpg", numero_transporte="00002002",
            planta_origen_id="PLANTA-B", planta_origen_nombre="AZA RENCA",
            origen_determinado_por="TELEMETRIA_GPS",
        ),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert len(viajes) == 2
    por_transporte = {v.numero_transporte: v for v in viajes}
    assert por_transporte["00002001"].planta_origen_nombre == "AZA COLINA"
    assert por_transporte["00002002"].planta_origen_nombre == "AZA RENCA"
    for viaje in viajes:
        assert MotivoRevision.CONFLICTO_ORIGEN not in viaje.motivos_revision


def test_origenes_lista_auditoria_ahora_refleja_las_plantas_reales_vistas():
    """`Viaje.origenes` (lista de auditoría, todas las plantas distintas
    vistas en los documentos del viaje -- nunca el origen ya resuelto del
    viaje) dependía de la misma columna inexistente que `CONFLICTO_ORIGEN`
    -- confirma que ahora sí refleja los valores reales, incluso cuando el
    origen consolidado del viaje (jerarquía GPS) elige sólo uno de ellos."""
    filas = [
        _fila(
            archivo="a.jpg",
            planta_origen_id="PLANTA-GPS", planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
        ),
        _fila(
            archivo="b.jpg",
            planta_origen_id="PLANTA-DOC", planta_origen_nombre="AZA RENCA",
            origen_determinado_por="DOCUMENTO",
        ),
    ]
    viajes, _ = agrupar_viajes(filas)
    viaje = viajes[0]
    assert set(viaje.origenes) == {"AZA COLINA", "AZA RENCA"}
    # ... pero el origen consolidado del viaje sigue siendo el de GPS, no una mezcla.
    assert viaje.planta_origen_nombre == "AZA COLINA"


def test_ausencia_no_copia_valor_ni_genera_conflicto():
    filas = [
        _fila(archivo="a.jpg", cliente="CLIENTE UNO"),
        _fila(archivo="b.jpg", cliente="No encontrado"),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert viajes[0].estado == EstadoViaje.CONFIRMADO
    assert viajes[0].clientes == ["CLIENTE UNO"]
    assert viajes[0].documentos[1].evidencia["cliente"] == "No encontrado"


def test_tres_guias_una_sola_con_campo_legible_no_inventa_ni_genera_conflicto():
    filas = [
        _fila(archivo="a.jpg", numero_guia="1", cliente="No encontrado"),
        _fila(archivo="b.jpg", numero_guia="2", cliente="CLIENTE ÚNICO"),
        _fila(archivo="c.jpg", numero_guia="3", cliente=""),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert viajes[0].estado == EstadoViaje.CONFIRMADO
    assert viajes[0].clientes == ["CLIENTE ÚNICO"]
    assert [
        documento.evidencia["cliente"] for documento in viajes[0].documentos
    ] == ["No encontrado", "CLIENTE ÚNICO", ""]


def test_misma_guia_en_archivos_distintos_no_elimina_documentos():
    filas = [_fila(archivo="a.jpg"), _fila(archivo="b.jpg")]
    viajes, _ = agrupar_viajes(filas)
    assert len(viajes[0].documentos) == 2
    assert viajes[0].numeros_guia == ["000101"]


def test_misma_guia_con_transportes_distintos_forma_viajes_separados():
    filas = [
        _fila(archivo="a.jpg", numero_transporte="0000349935"),
        _fila(archivo="b.jpg", numero_transporte="0000349936"),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert [viaje.numero_transporte for viaje in viajes] == [
        "0000349935",
        "0000349936",
    ]


def test_id_es_determinista_entre_reejecuciones():
    reloj = lambda: datetime(2026, 7, 28, tzinfo=timezone.utc)
    primero, _ = agrupar_viajes([_fila()], reloj=reloj)
    segundo, _ = agrupar_viajes([_fila()], reloj=reloj)
    assert primero[0].a_dict() == segundo[0].a_dict()


def test_fecha_se_normaliza_al_contrato_desktop_sin_falso_conflicto():
    filas = [
        _fila(archivo="a.jpg", fecha="2026-07-28"),
        _fila(archivo="b.jpg", fecha="28/07/2026"),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert viajes[0].fecha == "28-07-2026"
    assert viajes[0].estado == EstadoViaje.CONFIRMADO
    assert [d.evidencia["fecha"] for d in viajes[0].documentos] == [
        "2026-07-28",
        "28/07/2026",
    ]


def test_fecha_no_compatible_no_se_publica_como_confirmada():
    viajes, _ = agrupar_viajes([_fila(fecha="fecha ambigua")])
    assert viajes[0].fecha == ""
    assert viajes[0].estado == EstadoViaje.REQUIERE_REVISION
    assert (
        MotivoRevision.FECHA_NO_COMPATIBLE_DESKTOP
        in viajes[0].motivos_revision
    )
    assert viajes[0].documentos[0].evidencia["fecha"] == "fecha ambigua"


def test_orden_invertido_produce_el_mismo_resultado():
    reloj = lambda: datetime(2026, 7, 28, tzinfo=timezone.utc)
    filas = [
        _fila(archivo="b.jpg", numero_guia="000102"),
        _fila(archivo="a.jpg", numero_guia="000101"),
    ]
    primero, _ = agrupar_viajes(filas, reloj=reloj)
    segundo, _ = agrupar_viajes(list(reversed(filas)), reloj=reloj)
    assert [viaje.a_dict() for viaje in primero] == [
        viaje.a_dict() for viaje in segundo
    ]


def test_acentos_y_espacios_no_crean_conflicto():
    filas = [
        _fila(archivo="a.jpg", chofer="  JOSE   PEREZ "),
        _fila(archivo="b.jpg", chofer="JOSÉ PÉREZ"),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert viajes[0].estado == EstadoViaje.CONFIRMADO


# --- Bloque C1 Parte E: indicador_revision del documento a nivel de viaje ---


def test_documento_revisar_impide_confirmacion_silenciosa():
    """Un único documento marcado REVISAR por el pipeline de extracción
    (`indicador_revision`) no puede producir un viaje CONFIRMADO en
    silencio, aunque sea el único documento del transporte."""
    viajes, _ = agrupar_viajes([_fila(indicador_revision="REVISAR")])
    assert viajes[0].estado == EstadoViaje.REQUIERE_REVISION
    assert MotivoRevision.DOCUMENTO_REQUIERE_REVISION in viajes[0].motivos_revision


def test_documento_ok_simple_puede_quedar_confirmado():
    """Un documento único sin motivos válidos de revisión (indicador_revision
    OK, sin contradicciones, sin problema operacional) sí puede quedar
    CONFIRMADO."""
    viajes, _ = agrupar_viajes([_fila(indicador_revision="OK")])
    assert viajes[0].estado == EstadoViaje.CONFIRMADO
    assert viajes[0].motivos_revision == []


# --- Bloque R2: un problema operacional (ruta/origen/destino) bloqueante
# nunca puede convivir con un viaje CONFIRMADO, aunque el documento venga
# indicador_revision=OK (esa columna sólo refleja extracción documental,
# nunca ruta/origen/destino) -- casos reales obligatorios del primer lote
# real post-limpieza: 464170 (CONTRADICCION_OPERACIONAL_ORIGEN),
# 464493/464511 (MULTIPLES_UBICACIONES_DISPERSAS), los tres con
# indicador_revision=OK y por eso, antes de este bloque, CONFIRMADOS en
# silencio.

def test_problema_operacional_impide_confirmacion_aunque_indicador_sea_ok():
    """Caso real obligatorio (guía 464170): indicador_revision=OK pero
    estado_operacional=REQUIERE_REVISION (origen contradictorio sin
    resolver) -- el viaje no puede quedar CONFIRMADO."""
    viajes, _ = agrupar_viajes([
        _fila(indicador_revision="OK", estado_operacional="REQUIERE_REVISION")
    ])
    assert viajes[0].estado == EstadoViaje.REQUIERE_REVISION
    assert MotivoRevision.DOCUMENTO_REQUIERE_REVISION in viajes[0].motivos_revision


def test_problema_operacional_multiples_ubicaciones_impide_confirmacion():
    """Caso real obligatorio (guías 464493/464511): mismo patrón, motivo
    real distinto (MULTIPLES_UBICACIONES_DISPERSAS -- destino sin resolver
    para routing)."""
    viajes, _ = agrupar_viajes([
        _fila(indicador_revision="OK", estado_operacional="REQUIERE_REVISION")
    ])
    assert viajes[0].estado == EstadoViaje.REQUIERE_REVISION


def test_indicador_ok_y_estado_operacional_ok_confirma_normal():
    """Control: cuando AMBAS señales están limpias (caso normal, la
    mayoría de los documentos), el viaje sigue pudiendo confirmarse --
    este bloque no convierte todo en revisión."""
    viajes, _ = agrupar_viajes([
        _fila(indicador_revision="OK", estado_operacional="OK")
    ])
    assert viajes[0].estado == EstadoViaje.CONFIRMADO
    assert viajes[0].motivos_revision == []


def test_estado_operacional_ausente_no_rompe_compatibilidad():
    """Filas que nunca traen `estado_operacional` (fixtures antiguas,
    otras fuentes) siguen comportándose exactamente igual que antes de
    este bloque -- sólo `indicador_revision` decide."""
    viajes, _ = agrupar_viajes([_fila(indicador_revision="OK")])
    assert viajes[0].estado == EstadoViaje.CONFIRMADO


def test_conflicto_multiguia_persiste_con_documentos_ok():
    """Los conflictos entre documentos (ya existentes) siguen funcionando
    igual aunque ambos documentos vengan indicador_revision=OK."""
    filas = [
        _fila(archivo="a.jpg", indicador_revision="OK"),
        _fila(archivo="b.jpg", indicador_revision="OK", chofer="OTRO CHOFER"),
    ]
    viajes, _ = agrupar_viajes(filas)
    viaje = viajes[0]
    assert viaje.estado == EstadoViaje.REQUIERE_REVISION
    assert MotivoRevision.CONFLICTO_CHOFER in viaje.motivos_revision
    assert MotivoRevision.DOCUMENTO_REQUIERE_REVISION not in viaje.motivos_revision


# --- Bloque O1: política de peso/horas multiguía (evidencia real: 2
# transportes reales, 0000279246 y 0000297304, ver bitácora técnica) ---


def test_horas_coincidentes_entre_documentos_consolidan():
    # Caso real (transporte 0000297304, 3 guías): las 3 traen la misma
    # hora de entrada y de salida -- se consolidan a nivel de viaje.
    filas = [
        _fila(archivo="a.jpg", hora_entrada_aza="10:08", hora_salida_aza="12:27"),
        _fila(archivo="b.jpg", hora_entrada_aza="10:08", hora_salida_aza="12:27"),
        _fila(archivo="c.jpg", hora_entrada_aza="10:08", hora_salida_aza="12:27"),
    ]
    viajes, _ = agrupar_viajes(filas)
    viaje = viajes[0]
    assert viaje.hora_entrada_aza == "10:08"
    assert viaje.hora_salida_aza == "12:27"
    assert viaje.permanencia_minutos == "139"
    assert MotivoRevision.CONFLICTO_HORA_ENTRADA not in viaje.motivos_revision
    assert MotivoRevision.CONFLICTO_HORA_SALIDA not in viaje.motivos_revision


def test_horas_conflictivas_no_se_eligen_arbitrariamente():
    filas = [
        _fila(archivo="a.jpg", hora_entrada_aza="07:00", hora_salida_aza="09:00"),
        _fila(archivo="b.jpg", hora_entrada_aza="08:00", hora_salida_aza="09:00"),
    ]
    viajes, _ = agrupar_viajes(filas)
    viaje = viajes[0]
    assert viaje.estado == EstadoViaje.REQUIERE_REVISION
    assert MotivoRevision.CONFLICTO_HORA_ENTRADA in viaje.motivos_revision
    # A nivel de viaje, ninguna de las dos horas contradictorias se elige.
    assert viaje.hora_entrada_aza == ""
    assert viaje.permanencia_minutos == ""


def test_horas_faltantes_en_algunos_documentos_consolidan_con_los_validos():
    # Un documento sin hora legible no debe impedir consolidar si TODOS
    # los que sí tienen dato coinciden.
    filas = [
        _fila(archivo="a.jpg", hora_entrada_aza="10:08", hora_salida_aza="12:27"),
        _fila(archivo="b.jpg", hora_entrada_aza="No encontrado", hora_salida_aza="No encontrado"),
    ]
    viajes, _ = agrupar_viajes(filas)
    viaje = viajes[0]
    assert viaje.hora_entrada_aza == "10:08"
    assert viaje.hora_salida_aza == "12:27"
    assert MotivoRevision.CONFLICTO_HORA_ENTRADA not in viaje.motivos_revision


def test_peso_multiguia_suma_cuando_todos_los_documentos_tienen_dato():
    # Caso real (transporte 0000297304): 6.971 + 3.100 + 4.256 = 14.327
    # kg -- cada documento trae el peso PARCIAL de su propia línea de
    # carga (materiales distintos), sumar no duplica.
    filas = [
        _fila(archivo="a.jpg", peso_kg="6971"),
        _fila(archivo="b.jpg", peso_kg="3100"),
        _fila(archivo="c.jpg", peso_kg="4256"),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert viajes[0].peso_total_viaje_kg == "14327"


def test_fila_sin_columnas_o1_no_rompe_agrupacion():
    """Una fila que no trae peso_kg/hora_entrada_aza/hora_salida_aza en
    absoluto (esquema anterior a este bloque, a nivel de `Mapping` crudo,
    sin pasar por la validación estricta de `generar_reporte_viajes`) no
    rompe la agrupación -- los campos nuevos quedan vacíos."""
    fila = _fila()
    for campo in ("peso_kg", "hora_entrada_aza", "hora_salida_aza"):
        del fila[campo]
    viajes, _ = agrupar_viajes([fila])
    viaje = viajes[0]
    assert viaje.peso_total_viaje_kg == ""
    assert viaje.hora_entrada_aza == ""
    assert viaje.permanencia_minutos == ""
    assert viaje.clientes == ["CLIENTE ÑUBLE"]


def test_peso_multiguia_no_suma_si_falta_en_algun_documento():
    # Si un documento no aporta peso_kg, no puede demostrarse que la
    # suma esté completa -- se deja vacío en vez de sumar un subconjunto.
    filas = [
        _fila(archivo="a.jpg", peso_kg="6971"),
        _fila(archivo="b.jpg", peso_kg="No encontrado"),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert viajes[0].peso_total_viaje_kg == ""


def test_conflicto_y_documento_revisar_coexisten():
    """indicador_revision no elimina motivos de conflicto existentes: un
    documento REVISAR y una contradicción entre documentos deben quedar
    ambos registrados como motivos, no uno reemplazando al otro."""
    filas = [
        _fila(archivo="a.jpg"),
        _fila(archivo="b.jpg", chofer="OTRO CHOFER", indicador_revision="REVISAR"),
    ]
    viajes, _ = agrupar_viajes(filas)
    viaje = viajes[0]
    assert viaje.estado == EstadoViaje.REQUIERE_REVISION
    assert MotivoRevision.CONFLICTO_CHOFER in viaje.motivos_revision
    assert MotivoRevision.DOCUMENTO_REQUIERE_REVISION in viaje.motivos_revision


def test_motivos_y_metodos_estados_s2_se_preservan_en_evidencia_del_documento():
    """Bloque ESTADOS S2 (Fase G): `agrupar_viajes` no necesita cambios de
    código para preservar los motivos/métodos explícitos del documento --
    `_documento_desde_fila` ya copia toda la fila a `evidencia`, así que
    `motivos_revision_documento`/`metodos_recuperacion_documento` (si el
    CSV de origen los trae) llegan intactos hasta el viaje, trazables por
    documento, sin perderse ni colapsarse en el booleano agregado."""
    filas = [
        _fila(
            archivo="a.jpg",
            indicador_revision="REVISAR",
            motivos_revision_documento="CHOFER_SIN_CORROBORAR",
            metodos_recuperacion_documento="GEOMETRICO",
        ),
    ]
    viajes, _ = agrupar_viajes(filas)
    viaje = viajes[0]
    assert MotivoRevision.DOCUMENTO_REQUIERE_REVISION in viaje.motivos_revision
    assert viaje.documentos[0].evidencia["motivos_revision_documento"] == "CHOFER_SIN_CORROBORAR"
    assert viaje.documentos[0].evidencia["metodos_recuperacion_documento"] == "GEOMETRICO"


# Bloque VEHÍCULO D1 (cierre, G1) -- `resolver_patente` es el "consumidor
# futuro del ledger" que la propia `aplicacion_decisiones.aplicar_decision_obra`
# dejó pendiente: una decisión humana ya aplicada (`USAR_PATENTE_EXISTENTE`/
# `SELECCIONAR_OTRA_PATENTE`) debe convertirse en el VALOR OPERACIONAL del
# viaje, sin tocar nunca la evidencia documental. Caso real que motivó esto:
# transporte 0000351135 (464264/464265).

def test_resolver_patente_produce_valor_operacional_resuelto_t1():
    """T1: documento con patente incorrecta A + decisión humana selecciona
    B -> resultado operacional = B; la evidencia documental A sigue
    disponible/trazable en `evidencia`."""

    def resolver(numero_guia, campo, valor_documental):
        if campo == "patente_rampla" and valor_documental == "JD6659":
            return "JD8659"
        return valor_documental

    viajes, _ = agrupar_viajes(
        [_fila(patente_rampla="JD6659")], resolver_patente=resolver,
    )
    viaje = viajes[0]
    assert viaje.patentes_rampla == ["JD8659"]
    assert viaje.documentos[0].patente_rampla == "JD8659"
    assert viaje.documentos[0].evidencia["patente_rampla"] == "JD6659"


def test_resolver_patente_multiguia_consolida_sin_publicar_variantes_t2():
    """T2 -- caso real 0000351135: dos guías del mismo viaje traen variantes
    conflictivas de patente rampla (JD6659/JD0659); Javier seleccionó
    JD8659 como canónica para ambas. La consolidación final debe usar
    JD8659 -- nunca "JD0659 | JD6659" como si la decisión no hubiese
    ocurrido -- y el conflicto correspondiente no debe dispararse (ambos
    documentos ya resuelven al mismo valor operacional)."""

    def resolver(numero_guia, campo, valor_documental):
        if campo == "patente_rampla" and valor_documental in ("JD6659", "JD0659"):
            return "JD8659"
        return valor_documental

    filas = [
        _fila(archivo="464264.jpeg", numero_guia="464264", patente_rampla="JD6659"),
        _fila(archivo="464265.jpeg", numero_guia="464265", patente_rampla="JD0659"),
    ]
    viajes, _ = agrupar_viajes(filas, resolver_patente=resolver)
    assert len(viajes) == 1
    viaje = viajes[0]
    assert viaje.patentes_rampla == ["JD8659"]
    assert MotivoRevision.CONFLICTO_PATENTE_RAMPLA not in viaje.motivos_revision
    evidencias = {d.numero_guia: d.evidencia["patente_rampla"] for d in viaje.documentos}
    assert evidencias == {"464264": "JD6659", "464265": "JD0659"}


@pytest.mark.parametrize(
    ("campo", "propiedad"),
    [
        ("patente_tracto", "patentes_tracto"),
        ("patente_rampla", "patentes_rampla"),
    ],
)
def test_resolver_patente_es_generico_para_tracto_y_rampla_t3_t4(campo, propiedad):
    """T3/T4: el mismo mecanismo, sin ningún caso hardcodeado, funciona
    igual para TRACTO que para CARRO/RAMPLA -- no cambia ninguna regla de
    clasificación vehicular, sólo qué texto se publica como operacional."""

    def resolver(numero_guia, campo_resuelto, valor_documental):
        return "CANONICA99" if campo_resuelto == campo else valor_documental

    viajes, _ = agrupar_viajes(
        [_fila(**{campo: "OCR-ERRADO"})], resolver_patente=resolver,
    )
    assert getattr(viajes[0], propiedad) == ["CANONICA99"]


def test_patente_sin_decision_humana_conserva_comportamiento_actual_t5():
    """T5: sin `resolver_patente`, o con uno que no tiene ninguna decisión
    aplicable a este caso exacto, el comportamiento es idéntico al de
    siempre -- nunca se convierte automáticamente cualquier discrepancia
    en una corrección."""
    viajes_sin_resolver, _ = agrupar_viajes([_fila(patente_rampla="JD6659")])
    assert viajes_sin_resolver[0].patentes_rampla == ["JD6659"]

    def resolver_sin_coincidencia(numero_guia, campo, valor_documental):
        return valor_documental  # ninguna decisión humana aplica aquí

    viajes_con_resolver, _ = agrupar_viajes(
        [_fila(patente_rampla="JD6659")], resolver_patente=resolver_sin_coincidencia,
    )
    assert viajes_con_resolver[0].patentes_rampla == ["JD6659"]


def test_resolver_patente_no_afecta_otros_campos_de_consolidacion_t7():
    """T7 (alcance de gestor_viajes): `resolver_patente` sólo toca
    patente_tracto/patente_rampla -- cliente, chofer, obra/destino,
    material y peso siguen consolidando exactamente igual."""

    def resolver(numero_guia, campo, valor_documental):
        return "CANONICA99" if valor_documental == "OCR-ERRADO" else valor_documental

    viajes, _ = agrupar_viajes(
        [_fila(patente_tracto="OCR-ERRADO")], resolver_patente=resolver,
    )
    viaje = viajes[0]
    assert viaje.clientes == ["CLIENTE ÑUBLE"]
    assert viaje.choferes == ["JOSÉ PÉREZ"]
    assert viaje.obras_destino == ["OBRA ÁGUILA"]
    assert viaje.materiales == ["BARRAS"]
