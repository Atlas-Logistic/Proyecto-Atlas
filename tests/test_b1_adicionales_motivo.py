"""Motivo libre en adicionales de B1 (caso real 483082/483043, segunda vuelta
del viernes 23/10/2026). Datos sintéticos; nunca la raíz real."""
import json

import pytest

from atlas_core.b1_operador import OperadorB1, interpretar_determinista
from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.consulta_adicionales import consultar_adicionales
from atlas_core.registro_eventos_operacionales import leer_eventos_operacionales, registrar_evento

from tests.test_b1_adicionales_operacion import Escritor, raiz  # noqa: F401  (fixture sintética de Codex)

CASO = ("Agrega un adicional de $15.000 por segunda vuelta del viernes 23/10/2026 a cada uno de estos viajes, "
        "guías 483082 y 483043")
TEXTO_CASO = "ESTE VIAJE TIENE ADICIONAL DE $15.000 POR SEGUNDA VUELTA DEL VIERNES 23/10/2026"


def operador(raiz):
    return OperadorB1(raiz, capa=CapaAccionesOperacionales(raiz, fabrica_escritor=lambda: Escritor()))


def eventos(raiz):
    return leer_eventos_operacionales(raiz=raiz)["eventos"]


def notas(raiz):
    return {e["numero_transporte"]: e["nota"] for e in eventos(raiz)
            if e.get("estado") == "ACTIVO" and e["tipo_evento"] == "OBSERVACION_OPERACIONAL"}


@pytest.mark.parametrize("orden,texto,guias", [
    (CASO, TEXTO_CASO, ["483082", "483043"]),
    ("Agrega un adicional de $15.000 a las guías 483082 y 483043 por espera en obra",
     "ESTE VIAJE TIENE ADICIONAL DE $15.000 POR ESPERA EN OBRA", ["483082", "483043"]),
    ("Registra un adicional de 20 mil por descarga en Ñuñoa el lunes 26/10/2026 a la guía 483082",
     "ESTE VIAJE TIENE ADICIONAL DE $20.000 POR DESCARGA EN ÑUÑOA EL LUNES 26/10/2026", ["483082"]),
    ("Agrega un adicional de 30000 debido a cambio de obra a las guias 483043",
     "ESTE VIAJE TIENE ADICIONAL DE $30.000 DEBIDO A CAMBIO DE OBRA", ["483043"]),
    ("Agrega un adicional de 12 lucas correspondiente a peaje 2 del 21/10/26 a las guías 483082, 483043",
     "ESTE VIAJE TIENE ADICIONAL DE $12.000 CORRESPONDIENTE A PEAJE 2 DEL 21/10/26", ["483082", "483043"]),
    ("Agrega un adicional de $15.000 a cada uno de estos viajes, guias 483082 y 483043",
     "ESTE VIAJE TIENE ADICIONAL DE $15.000", ["483082", "483043"]),  # sin motivo: igual que antes
])
def test_motivo_libre_se_conserva_tal_cual(orden, texto, guias):
    intencion = interpretar_determinista(orden)
    assert intencion.accion == "VIAJE_AGREGAR_OBSERVACION"
    assert intencion.parametros == {"guias": guias, "texto": texto}


@pytest.mark.parametrize("orden,motivo", [
    ("Agrega un adicional de $15.000 por peaje de $5.000 a las guías 483082 y 483043", "otro importe"),
    ("Agrega un adicional de $15.000 por cada guía a las guías 483082 y 483043", "por viaje o por guía"),
    ("Agrega un adicional de $15.000 por espera a las guías 483082 por segunda vuelta", "dos motivos"),
    ("Agrega un adicional de $15.000 por segunda vuelta del 31/02/2026 a las guías 483082", "no existe"),
    ("Agrega un adicional de $15.000 por segunda vuelta del jueves 23/10/2026 a las guías 483082", "no fue jueves"),
    ("Agrega un adicional de $15.000 segunda vuelta a las guías 483082 y 483043", "no pude separar"),
])
def test_ambiguedad_pide_aclaracion_sin_proponer(raiz, orden, motivo):
    antes = json.dumps(eventos(raiz), sort_keys=True)
    r = operador(raiz).atender("c", orden)
    assert r["estado"] == "ACLARACION_REQUERIDA", r
    assert motivo in r["mensaje"] and "No se guardó ningún cambio" in r["mensaje"]
    assert interpretar_determinista(orden) is None
    assert json.dumps(eventos(raiz), sort_keys=True) == antes


def test_caso_real_vista_previa_dos_viajes_independientes_sin_escribir(raiz):
    b = operador(raiz)
    antes = json.dumps(eventos(raiz), sort_keys=True)
    r = b.atender("c", CASO)
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    propuesto = r["preview"]["valor_propuesto"]
    assert propuesto["texto"] == TEXTO_CASO
    assert propuesto["observaciones"] == {"0000366043": "NOTA ANTERIOR\n" + TEXTO_CASO, "0000365998": TEXTO_CASO}
    assert json.dumps(eventos(raiz), sort_keys=True) == antes
    assert b.atender("c", "no")["estado"] == "CANCELADA"
    assert json.dumps(eventos(raiz), sort_keys=True) == antes


def test_confirmado_es_idempotente_y_las_consultas_lo_cuentan(raiz):
    b = operador(raiz)
    assert b.atender("c", CASO)["estado"] == "PREVIEW_PENDIENTE"
    assert b.atender("c", "si")["estado"] == "EJECUTADA"
    assert notas(raiz) == {"0000366043": "NOTA ANTERIOR\n" + TEXTO_CASO, "0000365998": TEXTO_CASO}
    assert b.atender("c", CASO)["estado"] == "SIN_CAMBIOS"
    viajes = [{"viaje_id": "v1", "numero_transporte": "0000366043"}, {"viaje_id": "v2", "numero_transporte": "0000365998"},
              {"viaje_id": "v3", "numero_transporte": "0000900001"}]
    tipo, resultado, mensaje = consultar_adicionales("¿Cuántos viajes tienen adicional de $15.000?", viajes, raiz)
    assert (tipo, resultado.resultado) == ("resultado", 2), mensaje
    assert consultar_adicionales("¿Cuántos viajes tienen adicional superior a $20.000?", viajes, raiz)[1].resultado == 0


@pytest.mark.parametrize("previa", ["ESTE VIAJE TIENE ADICIONAL DE $15.000",
                                    "ESTE VIAJE TIENE ADICIONAL DE $15.000 POR ESPERA EN OBRA"])
def test_mismo_importe_con_otro_motivo_no_se_adivina(raiz, previa):
    registrar_evento(raiz=raiz, tipo_evento="OBSERVACION_OPERACIONAL", numero_transporte="0000365998", nota=previa,
                     origen="TEST")
    antes = json.dumps(eventos(raiz), sort_keys=True)
    r = operador(raiz).atender("c", CASO)
    assert r["estado"] == "RECHAZADA" and "otro motivo" in r["mensaje"], r
    assert json.dumps(eventos(raiz), sort_keys=True) == antes


def test_orden_sin_motivo_frente_a_adicional_previo_con_motivo_no_duplica(raiz):
    registrar_evento(raiz=raiz, tipo_evento="OBSERVACION_OPERACIONAL", numero_transporte="0000365998", nota=TEXTO_CASO,
                     origen="TEST")
    r = operador(raiz).atender("c", "Agrega un adicional de $15.000 a las guías 483043")
    assert r["estado"] == "RECHAZADA" and "otro motivo" in r["mensaje"], r


def test_motivo_sobrevive_dos_pull_y_regeneracion(raiz, tmp_path, monkeypatch):
    from atlas_core.mobile import RepositorioEnviosMobile
    from atlas_core.cloud_mobile_sync_cliente import sincronizar_envios_cloud
    from atlas_core.reporte_viajes import generar_reporte_viajes
    import atlas_core.cloud_mobile_sync_cliente as cloud
    b = operador(raiz)
    assert b.atender("c", CASO)["estado"] == "PREVIEW_PENDIENTE"
    assert b.atender("c", "si")["estado"] == "EJECUTADA"
    anteriores = json.dumps(eventos(raiz), sort_keys=True)
    monkeypatch.setattr(cloud, "_json", lambda *args, **kwargs: {"envios": []})
    dataset = raiz / "operacion/actual/analisis_completo_guias.csv"
    for _ in range(2):
        r = sincronizar_envios_cloud(base_url="https://cloud.test", token_motor="sintetico", consumidor="prueba",
                                     repositorio=RepositorioEnviosMobile(raiz), procesar=True, dataset=dataset,
                                     carpeta_catalogos=raiz / "catalogos_privados")
        assert r["encontrados"] == 0 and not r["fallidos"]
    generar_reporte_viajes(dataset, tmp_path / "reporte", carpeta_catalogos=raiz / "catalogos_privados")
    assert json.dumps(eventos(raiz), sort_keys=True) == anteriores
    assert b.atender("c", CASO)["estado"] == "SIN_CAMBIOS"


def test_caso_real_por_canal_desktop_con_lease_de_la_sesion(raiz, monkeypatch):
    """Como en producción: B1 corre dentro de la sesión Desktop, que ya tiene el lease
    (el árbitro no es reentrante). La confirmación usa ese mismo lease."""
    from atlas_core import desktop_operacion as d
    from tests.test_b1_canal_desktop_regresion import _Arbitro, _Lease
    arbitro = _Arbitro()
    monkeypatch.setattr(d, "compartida", lambda r: True)
    monkeypatch.setitem(d.sesion.__wrapped__.__kwdefaults__, "fabrica", lambda: _Lease(arbitro))

    def turno(texto):
        r = d.ejecutar({"raiz": str(raiz), "accion": "script", "argumentos": [
            "b1_operador_cli.py", "--raiz-atlas", str(raiz), "--conversacion", "real", "--texto", texto]})
        return json.loads(r["salida"])

    antes = json.dumps(eventos(raiz), sort_keys=True)
    assert turno(CASO)["estado"] == "PREVIEW_PENDIENTE"
    assert json.dumps(eventos(raiz), sort_keys=True) == antes
    assert turno("sí")["estado"] == "EJECUTADA"
    assert notas(raiz) == {"0000366043": "NOTA ANTERIOR\n" + TEXTO_CASO, "0000365998": TEXTO_CASO}
    assert arbitro.titular is None
    assert turno(CASO)["estado"] == "SIN_CAMBIOS"
