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
        normalizador_chofer=lambda nombre, rut: "JOSÉ PÉREZ",
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


def test_origen_opcional_contradictorio_activa_revision():
    filas = [
        _fila(archivo="a.jpg", origen="PLANTA NORTE"),
        _fila(archivo="b.jpg", origen="PLANTA SUR"),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert MotivoRevision.CONFLICTO_ORIGEN in viajes[0].motivos_revision


def test_conflictos_multiples_se_declaran_juntos_sin_perder_evidencia():
    filas = [
        _fila(archivo="a.jpg", origen="ORIGEN BASE"),
        _fila(
            archivo="b.jpg",
            fecha="2026-07-29",
            chofer="OTRO CHOFER",
            rut_chofer="9.999.999-9",
            cliente="OTRO CLIENTE",
            obra_destino="OTRA OBRA",
            origen="OTRO ORIGEN",
            patente_tracto="ZZZZ99",
            patente_rampla="YYYY88",
        ),
    ]
    viajes, _ = agrupar_viajes(filas)
    viaje = viajes[0]
    assert viaje.estado == EstadoViaje.REQUIERE_REVISION
    assert set(viaje.motivos_revision) == set(MotivoRevision) - {
        MotivoRevision.FECHA_NO_COMPATIBLE_DESKTOP,
        MotivoRevision.DOCUMENTO_REQUIERE_REVISION,
        MotivoRevision.ERROR_TECNICO_DOCUMENTO,
    }
    assert len(viaje.a_dict()["evidencias_documentos"]) == 2


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
