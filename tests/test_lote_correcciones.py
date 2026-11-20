from dataclasses import replace
import copy
import pytest
from atlas_core.lote_correcciones import (DestinoOperacional, EquipoOperacionalInstantanea, InstantaneaLote,
    ReferenciaDocumento, SolicitudLote, previsualizar_lote)


def datos(n=2):
    filas = tuple({"numero_guia": str(482000+i), "archivo": f"{i}.jpg", "numero_transporte": "0000364898", "fecha": "18-10-2026", "despachar_a_crudo": "SAN LUIS 1201 QUILICURA"} for i in range(n))
    refs = tuple(ReferenciaDocumento(f["numero_guia"]) for f in filas)
    return SolicitudLote("op-1", "mbt", "FECHA_EMISION", "19-10-2026", refs), InstantaneaLote("mbt", filas, (), (), frozenset(),
                                                                       agrupaciones=(), equipo=EquipoOperacionalInstantanea((), {}))


@pytest.mark.parametrize("n", [2, 10, 100])
def test_lotes_completos(n):
    s, i = datos(n); r = previsualizar_lote(s, i)
    assert r["estado"] == "PREVIEW" and r["resumen"]["total"] == n
    assert len(r["documentos"]) == n and r["resumen"]["CAMBIARIA"] == n
    assert r["autoriza_escritura"] is False and "token" not in r


def test_duplicados_y_referencias_contradictorias():
    s, i = datos(); a = s.documentos[0]
    for refs, motivo in [((a,a), "GUIA_DUPLICADA"), ((a,replace(a, archivo="x")), "REFERENCIAS_CONTRADICTORIAS")]:
        r = previsualizar_lote(replace(s, documentos=refs), i)
        assert r["estado"] == "NO_APLICABLE"
        assert all(motivo in x["motivos"] for x in r["documentos"])


def test_ambigua_ausente_y_otra_empresa():
    s, i = datos()
    ambigua = replace(i, filas=i.filas + ({**i.filas[0], "archivo": "otra.jpg"},))
    assert "DOCUMENTO_AMBIGUO" in next(x for x in previsualizar_lote(s, ambigua)["documentos"] if x["numero_guia"] == "482000")["motivos"]
    for ref, motivo in [(ReferenciaDocumento("999999"), "DOCUMENTO_NO_ENCONTRADO"),
                        (replace(s.documentos[0], empresa_id="otra"), "EMPRESA_DISTINTA")]:
        r=previsualizar_lote(replace(s, documentos=(ref,)), i)
        assert motivo in r["documentos"][0]["motivos"] and r["estado"] == "NO_APLICABLE"
    with pytest.raises(ValueError): previsualizar_lote(s, replace(i, empresa_id="otra"))


def test_protegida_y_cuarentena():
    s, i = datos(); doc = {"archivo": "0.jpg", "numero_guia": "482000"}
    ledger = ({"documento": doc, "campo": "fecha", "actor": "OPERADOR", "tipo": "REVISION"},)
    r = previsualizar_lote(s, replace(i, aplicaciones=ledger, archivos_en_investigacion=frozenset({"0.jpg"})))
    assert r["estado"] == "NO_APLICABLE"
    assert {"CAMPO_PROTEGIDO", "EN_INVESTIGACION"} <= set(next(x for x in r["documentos"] if x["numero_guia"] == "482000")["motivos"])


@pytest.mark.parametrize("valor", ["2026-10-19", "31-02-2026", "19-10-2201"])
def test_fecha_invalida(valor):
    s,i=datos(); r=previsualizar_lote(replace(s, valor=valor), i)
    assert r["estado"] == "NO_APLICABLE" and all("VALOR_INVALIDO" in x["motivos"] for x in r["documentos"])


def test_destino_valida_sin_ruta_y_exige_comuna():
    s,i=datos(); s=replace(s,campo="DESTINO_OPERACIONAL",valor=DestinoOperacional("SAN LUIS 1201", "QUILICURA"))
    r=previsualizar_lote(s,i)
    assert r["estado"] == "PREVIEW"
    assert r["documentos"][0]["dependencias"]["ruta_y_coordenadas"] == "PENDIENTE_EVALUACION"
    assert r["documentos"][0]["dependencias"]["destino_documental"] == "SAN LUIS 1201 QUILICURA"
    assert previsualizar_lote(replace(s,valor=DestinoOperacional("SAN LUIS 1201", "")),i)["estado"] == "NO_APLICABLE"


def test_sin_cambios_y_huella():
    s,i=datos(); base=previsualizar_lote(s,i)
    invertida=previsualizar_lote(replace(s, documentos=tuple(reversed(s.documentos))), replace(i,filas=tuple(reversed(i.filas))))
    assert base["huella_plan"] == invertida["huella_plan"]
    cambiado=replace(i, filas=({**i.filas[0], "cliente": "CAMBIO"}, *i.filas[1:]))
    assert base["huella_plan"] != previsualizar_lote(s,cambiado)["huella_plan"]
    assert previsualizar_lote(replace(s,valor="18-10-2026"),i)["estado"] == "SIN_CAMBIOS"


def test_puro_sin_escrituras_ni_mutaciones(monkeypatch):
    s,i=datos(); anterior=copy.deepcopy((s,i))
    import builtins
    def prohibido(*a, **k): raise AssertionError("E/S no permitida")
    monkeypatch.setattr(builtins, "open", prohibido)
    monkeypatch.setattr("pathlib.Path.open", prohibido)
    previsualizar_lote(s,i)
    assert (s,i) == anterior


def test_destino_igual_sin_confirmacion_no_es_sin_cambios():
    s,i=datos(1); fila={**i.filas[0], "direccion_entrega": "SAN LUIS 1201", "localidad_entrega": "QUILICURA"}
    s=replace(s,campo="DESTINO_OPERACIONAL",valor=DestinoOperacional("SAN LUIS 1201", "Quilicura"))
    r=previsualizar_lote(s,replace(i,filas=(fila,)))
    assert r["documentos"][0]["resultado"] == "CAMBIARIA"
    assert not r["documentos"][0]["dependencias"]["destino_operacional_confirmado"]
    entrada={"tipo":"DESTINO_OPERACIONAL_DOCUMENTO", "documento":{"archivo":"0.jpg","numero_guia":"482000"},
             "destino_operacional":{"direccion":"SAN LUIS 1201","comuna":"QUILICURA"}, "conservar_estado_operacional":True}
    assert previsualizar_lote(s,replace(i,filas=(fila,),aplicaciones=(entrada,)))["estado"] == "SIN_CAMBIOS"


def test_estado_esperado_y_protecciones_cambian_huella():
    s,i=datos(); base=previsualizar_lote(s,i)
    d=next(x for x in base["documentos"] if x["numero_guia"] == "482000")
    r=replace(s.documentos[0],estado_esperado=d["huella_estado"])
    assert previsualizar_lote(replace(s,documentos=(r,)),i)["estado"] == "PREVIEW"
    assert previsualizar_lote(replace(s,documentos=(replace(r,estado_esperado="obsoleto"),)),i)["estado"] == "NO_APLICABLE"
    assert base["huella_plan"] != previsualizar_lote(s,replace(i,archivos_en_investigacion=frozenset({"0.jpg"})))["huella_plan"]


def test_empresa_en_fila_se_rechaza():
    s,i=datos(1); i=replace(i,filas=({**i.filas[0],"empresa_id":"otra"},))
    assert "EMPRESA_DISTINTA" in previsualizar_lote(s,i)["documentos"][0]["motivos"]


def test_archivo_reutilizado_por_otra_guia_es_ambiguo():
    s,i=datos(1); otra={**i.filas[0], "numero_guia":"499999"}
    r=previsualizar_lote(s,replace(i,filas=(*i.filas,otra)))
    assert "DOCUMENTO_AMBIGUO" in r["documentos"][0]["motivos"]


# ------------------------------------------------- protecciones de FECHA_EMISION
# Mismas reglas que la corrección individual instalada (agrupación humana,
# patente por asignación vigente, guías del mismo transporte), evaluadas sobre
# la instantánea y el lote completo. Sólo datos sintéticos en memoria.
import json
from atlas_core.catalogo_vehiculos import cargar_catalogo_vehiculos
from atlas_core.equipo_operacional import ResolutorEquipoOperacional, sustituciones_automaticas_patente
from atlas_core.lote_correcciones import _ResolutorEquipoInstantanea

RUT = "12345678-5"
CHOFERES = {"123456785": {"nombre": "LUIS REYES", "rut": RUT, "aliases": [], "activo": True}}
T1, T2 = "0000900001", "0000900002"


def _vehiculo(patente, tipo, desde, rut=RUT):
    evidencia = {"tipo": "CONFIRMACION_HUMANA", "identificador_fuente": "TEST", "referencia_hash": "",
                 "campos_observados": {"patente": patente, "tipo": tipo, "observacion": "", "rut_chofer_asociado": rut},
                 "fecha": f"{desde}T00:00:00+00:00", "actor_proceso": "TEST", "resultado": "SOPORTA"}
    return {"vehiculo_id": patente, "patente_canonica": patente, "tipo": tipo, "estado_calidad": "CONFIRMADO",
            "estado_vigencia": "ACTIVO", "aliases": [], "evidencias": [evidencia], "procedencia": "CONFIRMACION_HUMANA",
            "confirmado_por": "TEST", "fecha_confirmacion": "2026-01-01T00:00:00+00:00", "observaciones": "",
            "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00"}


def _equipo(*vehiculos):
    cargados = cargar_catalogo_vehiculos({"version": 1, "vehiculos": list(vehiculos)}).vehiculos if vehiculos else ()
    return EquipoOperacionalInstantanea(tuple(cargados), CHOFERES)


def _fila(guia, transporte=T1, fecha="18-10-2026", **extra):
    return {"numero_guia": guia, "archivo": f"{guia}.jpg", "numero_transporte": transporte, "fecha": fecha,
            "chofer": "LUIS REYES", "rut_chofer": RUT, "patente_tracto": "KN5439", "patente_rampla": "",
            "despachar_a_crudo": "SAN LUIS 1201 QUILICURA", **extra}


def _caso(filas, guias, valor="19-10-2026", agrupaciones=(), equipo=None):
    equipo = _equipo() if equipo is None else equipo
    s = SolicitudLote("op-f", "mbt", "FECHA_EMISION", valor, tuple(ReferenciaDocumento(g) for g in guias))
    return s, InstantaneaLote("mbt", tuple(filas), (), (), frozenset(), agrupaciones=agrupaciones, equipo=equipo)


def _doc(r, guia):
    return next(x for x in r["documentos"] if x["numero_guia"] == guia)


AGRUPACION = {"agrupacion_id": "g1", "estado": "ACTIVA", "transportes": [T1, T2], "confirmado_por": "JAVIER"}


def _metricas_asignacion(campo="patente_rampla", ocr="", aplicado="JF4288"):
    return json.dumps({"patentes_por_asignacion_chofer": {
        "resultado": "RESUELTO", "valor_ocr": {campo: ocr or "No encontrado"}, "valor_aplicado": {campo: aplicado}}})


# --- agrupaciones humanas

def test_agrupacion_humana_incompatible_bloquea_y_no_se_deshace():
    filas = [_fila("482001"), _fila("482002", T2)]
    s, i = _caso(filas, ["482001"], agrupaciones=(AGRUPACION,))
    r = previsualizar_lote(s, i)
    d = _doc(r, "482001")
    assert r["estado"] == "NO_APLICABLE" and d["resultado"] == "BLOQUEADA"
    assert "AGRUPACION_HUMANA_INCOMPATIBLE" in d["motivos"]
    assert d["dependencias"]["agrupaciones"] == [{"agrupacion_id": "g1", "transportes": [T1, T2],
                                                  "fechas_resultantes": ["18-10-2026", "19-10-2026"], "compatible": False}]
    assert i.agrupaciones == (AGRUPACION,)


def test_agrupacion_humana_compatible_cuando_el_lote_cubre_todo_el_viaje():
    filas = [_fila("482001"), _fila("482002", T2)]
    r = previsualizar_lote(*_caso(filas, ["482001", "482002"], agrupaciones=(AGRUPACION,)))
    assert r["estado"] == "PREVIEW" and r["resumen"]["CAMBIARIA"] == 2
    assert all(x["dependencias"]["agrupaciones"][0]["compatible"] for x in r["documentos"])


def test_agrupacion_compatible_cuando_la_guia_se_iguala_al_resto():
    filas = [_fila("482001", fecha="18-10-2026"), _fila("482002", T2, fecha="19-10-2026")]
    r = previsualizar_lote(*_caso(filas, ["482001"], agrupaciones=(AGRUPACION,)))
    assert r["estado"] == "PREVIEW"
    assert _doc(r, "482001")["dependencias"]["agrupaciones"][0]["fechas_resultantes"] == ["19-10-2026"]


def test_agrupacion_inactiva_o_de_otro_transporte_no_bloquea():
    filas = [_fila("482001"), _fila("482002", T2)]
    otras = ({**AGRUPACION, "estado": "ANULADA"},
             {"agrupacion_id": "g9", "estado": "ACTIVA", "transportes": ["0000900007", "0000900008"]})
    r = previsualizar_lote(*_caso(filas, ["482001"], agrupaciones=otras))
    assert r["estado"] == "PREVIEW" and _doc(r, "482001")["dependencias"]["agrupaciones"] == []


# --- asignaciones de vehículos

def test_patente_fijada_por_asignacion_vigente_respaldada_no_bloquea():
    fila = _fila("482001", patente_rampla="JF4288", metricas_procesamiento_json=_metricas_asignacion())
    equipo = _equipo(_vehiculo("KN5439", "TRACTO", "2026-01-01"), _vehiculo("JF4288", "CARRO", "2026-10-01"))
    r = previsualizar_lote(*_caso([fila], ["482001"], equipo=equipo))
    d = _doc(r, "482001")
    assert r["estado"] == "PREVIEW" and d["motivos"] == []
    assert d["dependencias"]["equipo_operacional"]["patentes_fijadas"] == [
        {"campo": "patente_rampla", "patente": "JF4288", "asignacion_desde": "2026-10-01", "respaldada": True}]


def test_fecha_anterior_a_la_asignacion_que_fundamenta_la_patente_bloquea():
    fila = _fila("482001", patente_rampla="JF4288", metricas_procesamiento_json=_metricas_asignacion())
    equipo = _equipo(_vehiculo("KN5439", "TRACTO", "2026-01-01"), _vehiculo("JF4288", "CARRO", "2026-10-01"))
    r = previsualizar_lote(*_caso([fila], ["482001"], valor="30-09-2026", equipo=equipo))
    d = _doc(r, "482001")
    assert r["estado"] == "NO_APLICABLE" and d["motivos"] == ["FECHA_ANTERIOR_A_ASIGNACION"]
    assert d["dependencias"]["equipo_operacional"]["patentes_fijadas"][0]["respaldada"] is False
    assert fila["patente_rampla"] == "JF4288"  # nunca se modifica


def test_patente_fijada_sin_asignacion_vigente_no_es_verificable():
    fila = _fila("482001", patente_rampla="JF4288", metricas_procesamiento_json=_metricas_asignacion())
    r = previsualizar_lote(*_caso([fila], ["482001"], equipo=_equipo(_vehiculo("KN5439", "TRACTO", "2026-01-01"))))
    assert _doc(r, "482001")["motivos"] == ["ASIGNACION_NO_VERIFICABLE"] and r["estado"] == "NO_APLICABLE"


def test_patente_proyectada_que_cambia_con_la_fecha_se_informa_sin_ejecutar():
    # Impresa AB1234; desde el 19-10 el chofer tiene KN5439: con 18-10 no se
    # infiere hacia atrás, con 19-10 el canal existente la recalcularía.
    fila = _fila("482001", patente_tracto="AB1234")
    r = previsualizar_lote(*_caso([fila], ["482001"], equipo=_equipo(_vehiculo("KN5439", "TRACTO", "2026-10-19"))))
    d = _doc(r, "482001")
    assert r["estado"] == "PREVIEW" and d["motivos"] == []
    assert d["dependencias"]["equipo_operacional"]["recalculo_proyectado"] == [{
        "campo": "patente_tracto", "patente_documental": "AB1234", "operacional_actual": None,
        "operacional_resultante": "KN5439", "asignacion_desde": "2026-10-19", "ejecucion": "PENDIENTE_CANAL_EXISTENTE"}]
    assert fila["patente_tracto"] == "AB1234"


def test_resolutor_de_instantanea_equivale_al_oficial(tmp_path):
    vehiculos = [_vehiculo("KN5439", "TRACTO", "2026-10-19"), _vehiculo("JF4288", "CARRO", "2026-10-01")]
    (tmp_path / "vehiculos.json").write_text(json.dumps({"version": 1, "vehiculos": vehiculos}), encoding="utf-8")
    (tmp_path / "choferes.json").write_text(json.dumps(CHOFERES), encoding="utf-8")
    ledger = {"aplicaciones": [{"tipo": "CORRECCION_DOCUMENTAL_OPERADOR", "campo": "patente_tracto", "actor": "JAVIER",
                                "confirmado_por": "JAVIER", "documento": {"archivo": "482003.jpg", "numero_guia": "482003"}}]}
    (tmp_path / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
    oficial = ResolutorEquipoOperacional(carpeta_catalogos=tmp_path, ruta_ledger=tmp_path / "ledger.json")
    propio = _ResolutorEquipoInstantanea(_equipo(*vehiculos), ledger["aplicaciones"])
    filas = [_fila("482001", patente_tracto="AB1234"), _fila("482003", patente_tracto="AB1234"),
             _fila("482002", patente_rampla="JF4288", metricas_procesamiento_json=_metricas_asignacion())]
    vistos = 0
    for fila in filas:
        for fecha in ("18-10-2026", "19-10-2026", "30-09-2026"):
            f = {**fila, "fecha": fecha}
            assert propio.discrepancias(f) == oficial.discrepancias(f)
            sustituciones = sustituciones_automaticas_patente(f, resolutor=propio)
            assert sustituciones == sustituciones_automaticas_patente(f, resolutor=oficial)
            vistos += bool(sustituciones)
    assert vistos >= 3  # el caso no es trivial: hay sustituciones que comparar


# --- dependencias ausentes

def test_dependencia_ausente_bloquea_en_vez_de_asumir_que_no_existe():
    filas = [_fila("482001")]
    s, i = _caso(filas, ["482001"])
    for cambio, motivo in ((dict(agrupaciones=None), "DEPENDENCIA_AUSENTE_AGRUPACIONES"),
                           (dict(equipo=None), "DEPENDENCIA_AUSENTE_EQUIPO")):
        r = previsualizar_lote(s, replace(i, **cambio))
        assert r["estado"] == "NO_APLICABLE" and _doc(r, "482001")["motivos"] == [motivo]
    sin_nada = previsualizar_lote(s, InstantaneaLote("mbt", tuple(filas), (), (), frozenset()))
    assert set(_doc(sin_nada, "482001")["motivos"]) == {"DEPENDENCIA_AUSENTE_AGRUPACIONES", "DEPENDENCIA_AUSENTE_EQUIPO"}


def test_destino_operacional_no_exige_dependencias_de_fecha():
    s, _ = _caso([_fila("482001")], ["482001"])
    s = replace(s, campo="DESTINO_OPERACIONAL", valor=DestinoOperacional("SAN LUIS 1201", "QUILICURA"))
    r = previsualizar_lote(s, InstantaneaLote("mbt", (_fila("482001"),), (), (), frozenset()))
    assert r["estado"] == "PREVIEW" and "agrupaciones" not in r["documentos"][0]["dependencias"]


@pytest.mark.parametrize("cambio", [dict(agrupaciones=[AGRUPACION]), dict(agrupaciones=("x",)),
                                    dict(equipo={"vehiculos": ()}), dict(equipo=EquipoOperacionalInstantanea([], {})),
                                    dict(equipo=EquipoOperacionalInstantanea(({"patente": "X"},), {}))])
def test_dependencias_con_forma_invalida_se_rechazan(cambio):
    s, i = _caso([_fila("482001")], ["482001"])
    with pytest.raises(ValueError):
        previsualizar_lote(s, replace(i, **cambio))


# --- mismo transporte: advertencia, no bloqueo

def test_fechas_distintas_en_el_mismo_transporte_es_advertencia_no_bloqueo():
    filas = [_fila("482001"), _fila("482002")]
    r = previsualizar_lote(*_caso(filas, ["482001"]))
    d = _doc(r, "482001")
    assert r["estado"] == "PREVIEW" and d["resultado"] == "CAMBIARIA" and d["motivos"] == []
    assert d["advertencias"] == [{"codigo": "FECHAS_DISTINTAS_EN_TRANSPORTE", "transporte": T1,
                                  "numero_guia": "482002", "fecha": "18-10-2026"}]
    assert r["resumen"]["CON_ADVERTENCIAS"] == 1 and r["resumen"]["BLOQUEADA"] == 0
    completo = previsualizar_lote(*_caso(filas, ["482001", "482002"]))
    assert completo["resumen"]["CON_ADVERTENCIAS"] == 0 and all(not x["advertencias"] for x in completo["documentos"])


# --- lote completo

def test_una_guia_bloqueada_impide_todo_el_lote():
    filas = [_fila(str(482100 + n), transporte=f"00009{n:05d}") for n in range(10)]
    filas[3] = {**filas[3], "patente_rampla": "JF4288", "metricas_procesamiento_json": _metricas_asignacion()}
    equipo = _equipo(_vehiculo("KN5439", "TRACTO", "2026-01-01"), _vehiculo("JF4288", "CARRO", "2026-10-20"))
    r = previsualizar_lote(*_caso(filas, [f["numero_guia"] for f in filas], equipo=equipo))
    assert r["estado"] == "NO_APLICABLE" and r["resumen"]["BLOQUEADA"] == 1 and r["resumen"]["CAMBIARIA"] == 9
    assert _doc(r, "482103")["motivos"] == ["FECHA_ANTERIOR_A_ASIGNACION"]


@pytest.mark.parametrize("n", [2, 10, 100])
def test_lotes_con_dependencias_reales(n):
    filas = [_fila(str(483000 + k), transporte=f"0000{910000 + k // 2}") for k in range(n)]
    agrupaciones = ({"agrupacion_id": "g", "estado": "ACTIVA",
                     "transportes": [filas[0]["numero_transporte"], filas[-1]["numero_transporte"]]},)
    equipo = _equipo(_vehiculo("KN5439", "TRACTO", "2026-01-01"), _vehiculo("JF4288", "CARRO", "2026-10-01"))
    r = previsualizar_lote(*_caso(filas, [f["numero_guia"] for f in filas], agrupaciones=agrupaciones, equipo=equipo))
    assert r["estado"] == "PREVIEW" and r["resumen"]["CAMBIARIA"] == n and r["resumen"]["CON_ADVERTENCIAS"] == 0
    assert r["autoriza_escritura"] is False and "token" not in r


# --- huellas

def test_huella_cambia_con_una_dependencia_relevante():
    fila = _fila("482001", patente_rampla="JF4288", metricas_procesamiento_json=_metricas_asignacion())
    otra = _fila("482002", T2)
    base_equipo = (_vehiculo("KN5439", "TRACTO", "2026-01-01"), _vehiculo("JF4288", "CARRO", "2026-10-01"))
    s, i = _caso([fila, otra], ["482001", "482002"], agrupaciones=(AGRUPACION,), equipo=_equipo(*base_equipo))
    base = previsualizar_lote(s, i)
    estado = {x["numero_guia"]: x["huella_estado"] for x in base["documentos"]}
    assert base["huella_plan"] == previsualizar_lote(s, i)["huella_plan"]
    # asignación que fundamenta la patente fijada
    otra_asig = previsualizar_lote(s, replace(i, equipo=_equipo(base_equipo[0], _vehiculo("JF4288", "CARRO", "2026-10-05"))))
    assert otra_asig["huella_plan"] != base["huella_plan"]
    assert _doc(otra_asig, "482001")["huella_estado"] != estado["482001"]
    # agrupación humana
    sin_agr = previsualizar_lote(s, replace(i, agrupaciones=()))
    assert sin_agr["huella_plan"] != base["huella_plan"] and _doc(sin_agr, "482001")["huella_estado"] != estado["482001"]
    # fecha de otra guía del viaje agrupado
    movida = previsualizar_lote(s, replace(i, filas=(fila, {**otra, "fecha": "17-10-2026"})))
    assert _doc(movida, "482001")["huella_estado"] != estado["482001"]
    # vehículo ajeno: cambia la instantánea, no el estado del documento
    ajeno = previsualizar_lote(s, replace(i, equipo=_equipo(
        *base_equipo, _vehiculo("ZZ1111", "TRACTO", "2026-01-01", rut="11111111-1"))))
    assert ajeno["huella_plan"] != base["huella_plan"]
    assert _doc(ajeno, "482001")["huella_estado"] == estado["482001"]


def test_huella_de_documento_no_depende_de_la_composicion_del_lote():
    filas = [_fila("482001"), _fila("482002")]
    uno = previsualizar_lote(*_caso(filas, ["482001"]))
    dos = previsualizar_lote(*_caso(filas, ["482001", "482002"]))
    assert _doc(uno, "482001")["huella_estado"] == _doc(dos, "482001")["huella_estado"]
    s, i = _caso(filas, ["482001"])
    esperado = replace(s.documentos[0], estado_esperado=_doc(dos, "482001")["huella_estado"])
    assert previsualizar_lote(replace(s, documentos=(esperado,)), i)["estado"] == "PREVIEW"


# --- pureza

def test_dependencias_sin_escrituras_ni_mutaciones(monkeypatch):
    fila = _fila("482001", patente_rampla="JF4288", metricas_procesamiento_json=_metricas_asignacion())
    s, i = _caso([fila, _fila("482002", T2)], ["482001"], agrupaciones=(AGRUPACION,),
                 equipo=_equipo(_vehiculo("KN5439", "TRACTO", "2026-01-01"), _vehiculo("JF4288", "CARRO", "2026-10-01")))
    anterior = copy.deepcopy((s, i))
    import builtins
    import os
    import pathlib
    import shutil

    def prohibido(*a, **k):
        raise AssertionError("E/S no permitida")
    with monkeypatch.context() as m:  # sólo durante el preview: pytest necesita E/S para informar
        m.setattr(builtins, "open", prohibido)
        for nombre in ("open", "read_text", "read_bytes", "write_text", "write_bytes", "exists", "is_file", "mkdir"):
            m.setattr(pathlib.Path, nombre, prohibido)
        for nombre in ("replace", "rename", "remove", "makedirs", "listdir", "scandir"):
            m.setattr(os, nombre, prohibido)
        m.setattr(shutil, "copy2", prohibido)
        r = previsualizar_lote(s, i)
    assert r["estado"] == "NO_APLICABLE" and r["autoriza_escritura"] is False
    assert (s, i) == anterior
