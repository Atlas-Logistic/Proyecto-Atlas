from datetime import datetime, timezone

from atlas_core.registro_eventos_operacionales import (
    ESTADO_INCIDENCIA_ESTADIA_APROBADA,
    ESTADO_INCIDENCIA_ESPERA_ESTADIA,
    estado_estadia_vigente,
    leer_eventos_operacionales,
    registrar_estado_estadia,
)


def _reloj():
    return datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


def _registrar(raiz, estado):
    return registrar_estado_estadia(
        raiz=raiz,
        numero_transporte="T-ESTADIA-1",
        estado_incidencia=estado,
        origen="TEST",
        enriquecimiento={"viaje_id": "v1", "numeros_guia": ["471111"],
                        "fecha_operacional": "2026-09-22", "snapshot": {},
                        "vinculo_completo": True, "motivo_vinculo_incompleto": ""},
        reloj=_reloj,
    )


def test_espera_a_aprobada_conserva_un_evento_y_historial(tmp_path):
    espera = _registrar(tmp_path, ESTADO_INCIDENCIA_ESPERA_ESTADIA)
    aprobada = _registrar(tmp_path, ESTADO_INCIDENCIA_ESTADIA_APROBADA)

    eventos = leer_eventos_operacionales(raiz=tmp_path)["eventos"]
    assert len(eventos) == 1
    evento = eventos[0]
    assert espera["evento"]["evento_id"] == aprobada["evento"]["evento_id"]
    assert estado_estadia_vigente(evento) == ESTADO_INCIDENCIA_ESTADIA_APROBADA
    assert evento["estado_gestion"] == "APROBADA"
    assert any(h["accion"] == "ESTADO_ESTADIA_ACTUALIZADO" and h["detalle"]["anterior"] == ESTADO_INCIDENCIA_ESPERA_ESTADIA for h in evento["historial"])


def test_repetir_cada_estado_es_idempotente(tmp_path):
    primera = _registrar(tmp_path, ESTADO_INCIDENCIA_ESPERA_ESTADIA)
    repetida = _registrar(tmp_path, ESTADO_INCIDENCIA_ESPERA_ESTADIA)
    assert primera["creado"] is True
    assert repetida["cambio"] is False

    _registrar(tmp_path, ESTADO_INCIDENCIA_ESTADIA_APROBADA)
    aprobada_repetida = _registrar(tmp_path, ESTADO_INCIDENCIA_ESTADIA_APROBADA)
    assert aprobada_repetida["cambio"] is False
    assert len(leer_eventos_operacionales(raiz=tmp_path)["eventos"]) == 1


def test_aprobacion_directa_es_valida(tmp_path):
    resultado = _registrar(tmp_path, ESTADO_INCIDENCIA_ESTADIA_APROBADA)
    assert resultado["creado"] is True
    assert estado_estadia_vigente(resultado["evento"]) == ESTADO_INCIDENCIA_ESTADIA_APROBADA


def test_compatibilidad_historica_no_infiere_evento_ambiguo():
    espera = {"tipo_evento": "TIENE_ESTADIA", "nota": "El chofer espera autorizacion de estadia"}
    aprobada = {"tipo_evento": "TIENE_ESTADIA", "nota": "Este viaje tiene estadia, se envio guia firmada al correo"}
    ambiguo = {"tipo_evento": "TIENE_ESTADIA", "nota": "Estadia"}
    assert estado_estadia_vigente(espera) == ESTADO_INCIDENCIA_ESPERA_ESTADIA
    assert estado_estadia_vigente(aprobada) == ESTADO_INCIDENCIA_ESTADIA_APROBADA
    assert estado_estadia_vigente(ambiguo) is None
