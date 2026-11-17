import csv
import json
from types import SimpleNamespace

import pytest
from atlas_core.coherencia_comuna_derivada import revalidar_comunas_confirmadas
from atlas_core.revalidacion_documental import COLUMNAS, _leer_filas


def fila(guia):
    return {"archivo": guia + ".jpeg", "numero_guia": guia, "numero_transporte": "T" + guia,
            "despachar_a_crudo": "VISTA CLARA 2351, CERRILLOS", "direccion_entrega": "VISTA CLARA 2351, CERRILLOS",
            "localidad_entrega": "Santiago", "codigo_unidad": "13101", "codigo_contexto": "13", "codigo_pais": "CL",
            "distancia_km": "30.77", "duracion_min": "42", "estado_ruta": "RUTA_CALCULADA", "descripcion_material": "ACERO", "peso_kg": "2222"}


def decision(f):
    return {"tipo": "DESTINO_NO_RESUELTO", "accion": "REGISTRAR_DIRECCION", "actor": "JAVIER_DESKTOP", "documento": {c: f[c] for c in ("archivo", "numero_guia", "numero_transporte")}, "direccion_manual": f["despachar_a_crudo"], "comuna_manual": ""}


def setup(tmp_path, filas, decisiones):
    ruta = tmp_path / "analisis_completo_guias.csv"
    with ruta.open("w", encoding="utf-8", newline="") as out:
        w = csv.DictWriter(out, fieldnames=COLUMNAS, delimiter=";", extrasaction="ignore")
        w.writeheader(); w.writerows(filas)
    ledger = ruta.parent / "decisiones_aplicadas.json"
    ledger.write_text(json.dumps({"aplicaciones": decisiones}), encoding="utf-8")
    return ruta, ledger


def test_confirmacion_humana_se_proyecta_solo_en_su_guia_y_es_idempotente(tmp_path):
    a, b = fila("483267"), fila("483552")
    ruta, ledger = setup(tmp_path, [a, b], [decision(a)])
    antes, decisiones = _leer_filas(ruta), ledger.read_bytes()
    assert revalidar_comunas_confirmadas(ruta_dataset=ruta, carpeta_catalogos=tmp_path, aplicar=False)["guias_actualizadas"] == ["483267"]
    assert _leer_filas(ruta) == antes
    assert revalidar_comunas_confirmadas(ruta_dataset=ruta, carpeta_catalogos=tmp_path)["guias_actualizadas"] == ["483267"]
    despues = _leer_filas(ruta)
    assert despues[0] == {**antes[0], "localidad_entrega": "Cerrillos", "codigo_unidad": "13102"}
    assert despues[1] == antes[1]
    assert ledger.read_bytes() == decisiones
    assert revalidar_comunas_confirmadas(ruta_dataset=ruta, carpeta_catalogos=tmp_path)["guias_actualizadas"] == []


def test_convergencia_confirmada_y_alcance(tmp_path, monkeypatch):
    from atlas_core import convergencia_destino_confirmado as convergencia
    a, b = fila("484907"), fila("484123")
    evidencia = {"fuente": "CLIENTE_RUT_OBRA_DIRECCION_CATALOGO_CONFIRMADO", "destino_id": "d", "obra_id": "o"}
    a["metricas_procesamiento_json"] = b["metricas_procesamiento_json"] = json.dumps({"convergencia_destino_confirmado": evidencia})
    monkeypatch.setattr(convergencia, "resolver_destino_confirmado", lambda *a, **k: (SimpleNamespace(obra_id="o"), SimpleNamespace(destino_id="d", direccion="VISTA CLARA 2351, CERRILLOS", comuna="Cerrillos"), ""))
    ruta, _ = setup(tmp_path, [a, b], [])
    antes = _leer_filas(ruta)
    assert revalidar_comunas_confirmadas(ruta_dataset=ruta, carpeta_catalogos=tmp_path, guias_objetivo={"484907"})["guias_actualizadas"] == ["484907"]
    despues = _leer_filas(ruta)
    assert despues[0] == {**antes[0], "localidad_entrega": "Cerrillos", "codigo_unidad": "13102"}
    assert despues[1] == antes[1]


@pytest.mark.parametrize("variante", ["comunas", "numero", "posterior", "manual", "ledger"])
def test_abstencion_ante_ambiguedad_o_decision_posterior(tmp_path, variante):
    a = fila("483267")
    d = decision(a)
    decisiones = [d]
    if variante == "comunas":
        a["direccion_entrega"] += " PROVIDENCIA"
    elif variante == "numero":
        a["direccion_entrega"] = "VISTA CLARA 2352, CERRILLOS"
    elif variante == "manual":
        d["comuna_manual"] = "Providencia"
    elif variante == "posterior":
        decisiones.append({"tipo": "DESTINO_OPERACIONAL_DOCUMENTO", "accion": "CORREGIR_DESTINO_OPERACIONAL", "documento": d["documento"], "destino_operacional": {"direccion": "OTRA 10", "comuna": "Providencia"}})
    ruta, ledger = setup(tmp_path, [a], decisiones)
    if variante == "ledger": ledger.write_text("{", encoding="utf-8")
    antes = ruta.read_bytes()
    assert not revalidar_comunas_confirmadas(ruta_dataset=ruta, carpeta_catalogos=tmp_path)["guias_actualizadas"]
    assert ruta.read_bytes() == antes

def test_convergencia_reutiliza_resolutor_y_respeta_catalogo_vigente(tmp_path, monkeypatch):
    from atlas_core import convergencia_destino_confirmado as c
    cliente = SimpleNamespace(cliente_id="cliente", razon_social="CLIENTE SA", rut="77004250-K", aliases=(), estado_calidad="CONFIRMADO", estado_vigencia="ACTIVO")
    obra = SimpleNamespace(obra_id="obra", cliente_id="cliente", nombre_canonico="CLIENTE SA", aliases_documentales=(), estado="CONFIRMADA", estado_vigencia="ACTIVO", evidencias=[])
    destino = SimpleNamespace(destino_id="destino", direccion="VISTA CLARA 2351, CERRILLOS", comuna="CERRILLOS", region="Metropolitana")
    monkeypatch.setattr(c, "CatalogoClientes", lambda *a, **k: SimpleNamespace(listar=lambda: [cliente]))
    monkeypatch.setattr(c, "CatalogoObrasDestinos", lambda *a, **k: SimpleNamespace(listar_obras=lambda: [obra], listar_destinos_confirmados_para_obra=lambda **k: [destino]))
    f = fila("484907")
    f.update(cliente="CLIENTE SA", rut_cliente="77.004.250-K", obra_destino="CLIENTE SA", metricas_procesamiento_json=json.dumps({"convergencia_destino_confirmado": {"fuente": "CLIENTE_RUT_OBRA_DIRECCION_CATALOGO_CONFIRMADO", "destino_id": "destino", "obra_id": "obra"}}))
    ruta, _ = setup(tmp_path, [f], [])
    assert revalidar_comunas_confirmadas(ruta_dataset=ruta, carpeta_catalogos=tmp_path)["guias_actualizadas"] == ["484907"]
    assert _leer_filas(ruta)[0]["codigo_unidad"] == "13102"


def test_decision_posterior_con_identidad_parcial_bloquea_proyeccion(tmp_path):
    a = fila("483267")
    posterior = {"tipo": "DESTINO_NO_RESUELTO", "accion": "REGISTRAR_DIRECCION", "documento": {"numero_guia": "483267"}, "direccion_manual": "OTRA 45, PROVIDENCIA"}
    ruta, _ = setup(tmp_path, [a], [decision(a), posterior])
    antes = ruta.read_bytes()
    assert not revalidar_comunas_confirmadas(ruta_dataset=ruta, carpeta_catalogos=tmp_path)["guias_actualizadas"]
    assert ruta.read_bytes() == antes

def test_decision_b1_no_se_atribuye_a_un_humano_sin_respaldo(tmp_path):
    a = fila("483267")
    d = {**decision(a), "actor": "B1"}
    ruta, _ = setup(tmp_path, [a], [d])
    antes = ruta.read_bytes()
    assert not revalidar_comunas_confirmadas(ruta_dataset=ruta, carpeta_catalogos=tmp_path)["guias_actualizadas"]
    assert ruta.read_bytes() == antes

def test_decision_humana_previa_impide_que_b1_revierta_comuna(tmp_path, monkeypatch):
    from atlas_core import convergencia_destino_confirmado as c
    a = fila("483267")
    previa = {**decision(a), "direccion_manual": "OTRA 1, PROVIDENCIA"}
    automatica = {**decision(a), "actor": "B1"}
    monkeypatch.setattr(c, "resolver_destino_confirmado", lambda *args, **kwargs: (SimpleNamespace(obra_id="o"), SimpleNamespace(destino_id="d", direccion=a["direccion_entrega"], comuna="Cerrillos"), ""))
    ruta, _ = setup(tmp_path, [a], [previa, automatica])
    antes = ruta.read_bytes()
    assert not revalidar_comunas_confirmadas(ruta_dataset=ruta, carpeta_catalogos=tmp_path)["guias_actualizadas"]
    assert ruta.read_bytes() == antes

def test_agrupacion_de_viaje_y_datos_operacionales_no_cambian(tmp_path):
    from atlas_core.gestor_viajes import agrupar_viajes
    a, b = fila("483267"), fila("483552")
    a["numero_transporte"] = b["numero_transporte"] = "0000366468"
    ruta, _ = setup(tmp_path, [a, b], [decision(a)])
    antes = _leer_filas(ruta)
    viajes_antes, _ = agrupar_viajes(antes)
    revalidar_comunas_confirmadas(ruta_dataset=ruta, carpeta_catalogos=tmp_path)
    despues = _leer_filas(ruta)
    viajes_despues, _ = agrupar_viajes(despues)
    assert [(v.numero_transporte, [d.numero_guia for d in v.documentos]) for v in viajes_antes] == [(v.numero_transporte, [d.numero_guia for d in v.documentos]) for v in viajes_despues]
    assert despues[0] == {**antes[0], "localidad_entrega": "Cerrillos", "codigo_unidad": "13102"}
    assert despues[1] == antes[1]

def test_b1_con_destino_confirmado_y_sin_decisiones_humanas_en_conflicto(tmp_path, monkeypatch):
    from atlas_core import convergencia_destino_confirmado as c
    a = fila("483267")
    d = {**decision(a), "actor": "B1"}
    monkeypatch.setattr(c, "resolver_destino_confirmado", lambda *args, **kwargs: (SimpleNamespace(obra_id="o"), SimpleNamespace(destino_id="d", direccion=a["direccion_entrega"], comuna="Cerrillos"), ""))
    ruta, _ = setup(tmp_path, [a], [d])
    assert revalidar_comunas_confirmadas(ruta_dataset=ruta, carpeta_catalogos=tmp_path)["guias_actualizadas"] == ["483267"]
    assert _leer_filas(ruta)[0]["codigo_unidad"] == "13102"
