"""B1 -- DESTINO de una guía con la propuesta ESTRUCTURADA de la
investigación inmediatamente anterior ("corrige el destino de la guía N
usando la dirección que acabas de identificar"). Preview limpio +
confirmación; aplica por el mismo camino que Revisión (DESTINO_NO_RESUELTO ->
REGISTRAR_DIRECCION vía DECISION_APLICAR). Separación de intenciones de
destino. Fixtures sintéticas de R6; nunca G: ni red."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.atlas_ia import investigacion_revision
from atlas_core.b1_operador import (
    ACCION_DESDE_INVESTIGACION, ACCION_INVESTIGAR_REVISION, OperadorB1, interpretar_determinista,
    registro_investigacion_destino,
)
from atlas_core.decisiones_pendientes import detectar_decision_destino_no_resuelto
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from tests.test_b1_obra_desde_investigacion import Reloj
from tests.test_destino_no_resuelto_r6 import _cliente_dict, _entorno, _fila_csv, _leer_csv, _obra_dict, _publicar

GUIA = "472037"
DOCUMENTAL = "AV APOQUINDO LAS CONDES"
INVESTIGA = (f"Investiga el destino de la guía {GUIA} y dime cuál es la dirección completa. "
             "No hagas ningún cambio; solo dame la propuesta y la evidencia.")
CORRIGE = f"Corrige el destino de la guía {GUIA} usando la dirección que acabas de identificar."
PROPUESTO = "AVENIDA APOQUINDO 1234, LAS CONDES"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def _fuente(dominio, *, numero="1234", calle="AVENIDA APOQUINDO", comuna="LAS CONDES", verificada=True):
    return {"direccion": calle, "numero": numero, "comuna": comuna, "url": f"https://{dominio}/contacto",
            "verificacion": "VERIFICADA" if verificada else "NO_VERIFICABLE", "nombre": "OBRA"}


def _expediente(*, fuentes=None, numero_documental="", estado="PROPUESTA_RESOLUBLE", nivel="PROPUESTA_RESOLUBLE",
                accion="PROPONER_A_HUMANO", comparaciones=None, propuesta=PROPUESTO):
    fuentes = fuentes if fuentes is not None else [_fuente("a.example"), _fuente("b.example")]
    ganador = {"direccion": propuesta, "fuentes": fuentes, "fuentes_independientes": ["a.example", "b.example"],
               "comparaciones": comparaciones or {"CALLE": "COMPATIBLE", "NUMERO": "NO_APORTA",
                                                  "COMUNA": "COINCIDE", "ENTIDAD": "COMPATIBLE"}}
    return {"CAMPO": "despachar_a_crudo",
            "HECHOS_DOCUMENTALES": {"valor_extraido": DOCUMENTAL, "destino_original": DOCUMENTAL},
            "PROPUESTA": propuesta if estado == "PROPUESTA_RESOLUBLE" else "",
            "NIVEL_EVIDENCIA": nivel, "ACCION_RECOMENDADA": accion,
            "EVALUACION_CANDIDATOS_EXTERNOS": {
                "estado": estado, "propuesta": ganador if estado == "PROPUESTA_RESOLUBLE" else None,
                "razon": "Dos fuentes independientes verificadas y anclajes documentales compatibles",
                "numero_documental": numero_documental},
            "PREVIEW_OPERACIONAL": None}


def _resultado(*expedientes, busqueda="EJECUTADA"):
    return {"numero_guia": GUIA, "expedientes": list(expedientes), "BUSQUEDA_EXTERNA": {"estado": busqueda}}


def _proveedor():
    # Con comuna humana la consulta real es "<dirección> <Comuna>, Chile" y el
    # candidato trae códigos territoriales (mismo patrón que
    # test_registro_direccion_contexto_territorial).
    candidato = CandidatoGeocodificacion(Coordenadas(-70.58, -33.41), "AVENIDA APOQUINDO 1234, Las Condes, RM, Chile",
                                         0.95, "Las Condes", "Metropolitana",
                                         codigo_pais="CL", codigo_unidad="13114", codigo_contexto="13")
    geo = ResultadoGeocodificacion(EstadoRuta.REQUIERE_REVISION, (candidato,), "")
    consultas = ["AVENIDA APOQUINDO 1234 Las Condes, Chile", "AVENIDA APOQUINDO 1234 LAS CONDES, Chile",
                 "AVENIDA APOQUINDO 1234, Chile"]
    return ProveedorRutasSimulado(geocodificaciones={c: geo for c in consultas},
                                  resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 25.4, 38.2, "SINTETICO"))


@pytest.fixture
def b1(tmp_path, monkeypatch):
    fila = _fila_csv(despachar_a_crudo=DOCUMENTAL)
    entorno = _entorno(tmp_path, filas_csv=[fila], clientes=[_cliente_dict()], obras=[_obra_dict()])
    decision = detectar_decision_destino_no_resuelto(archivo="472037.jpeg", fila=fila)
    assert decision is not None
    _publicar(entorno, decision)
    reloj = Reloj()
    operador = OperadorB1(entorno["raiz"], capa=CapaAccionesOperacionales(entorno["raiz"], proveedor_rutas=_proveedor()),
                          reloj=reloj)
    operador.entorno, operador.decision, operador.reloj_prueba = entorno, decision, reloj
    respuesta = {"valor": _resultado(_expediente())}
    operador.respuesta_investigacion, operador.investigaciones = respuesta, []

    def investigar(numero_guia, **kwargs):
        operador.investigaciones.append((numero_guia, kwargs.get("campos_solicitados")))
        if isinstance(respuesta["valor"], Exception):
            raise respuesta["valor"]
        return respuesta["valor"]

    monkeypatch.setattr(investigacion_revision, "investigar_revision", investigar)
    return operador


def _sha(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest() if ruta.exists() else None


def _huellas(b1):
    actual = b1.entorno["actual"]
    return {n: _sha(actual / n) for n in ("analisis_completo_guias.csv", "decisiones_aplicadas.json",
                                          "decisiones_pendientes.json")}


# ------------------------------------------------------------ intenciones de destino


def test_separacion_de_intenciones_de_destino():
    assert interpretar_determinista(f"¿Cuál es el destino de la guía {GUIA}?") is None  # consulta interna
    asignacion = interpretar_determinista(f"El destino de la guía {GUIA} es Avenida Apoquindo 1234")
    assert asignacion.accion == "DECISION_APLICAR"
    investigacion = interpretar_determinista(INVESTIGA)
    assert investigacion.accion == ACCION_INVESTIGAR_REVISION
    assert investigacion.parametros == {"numero_guia": GUIA, "campos": ("despachar_a_crudo",)}
    reutilizacion = interpretar_determinista(CORRIGE)
    assert reutilizacion.accion == ACCION_DESDE_INVESTIGACION
    assert reutilizacion.parametros == {"numero_guia": GUIA, "campo": "despachar_a_crudo"}
    # "por la dirección que acabas de identificar" nunca se lee como dirección literal
    assert interpretar_determinista(
        f"Corrige el destino de la guía {GUIA} por la dirección que acabas de identificar").accion \
        == ACCION_DESDE_INVESTIGACION


def test_consulta_simple_no_investiga(b1):
    r = b1.atender("c", f"¿Cuál es el destino de la guía {GUIA}?")
    assert r["estado"] == "NO_INTERPRETADA" and b1.investigaciones == []


def test_asignacion_explicita_sigue_generando_preview(b1):
    r = b1.atender("c", f"El destino de la guía {GUIA} es Avenida Apoquindo 1234")
    assert r["estado"] == "PREVIEW_PENDIENTE" and r["accion"] == "DECISION_APLICAR"
    assert b1.investigaciones == []


def test_investigacion_explicita_de_destino(b1):
    r = b1.atender("c", INVESTIGA)
    assert r["estado"] == "RESULTADO_INVESTIGACION" and b1.pendiente("c") is None
    assert b1.investigaciones == [(GUIA, ("despachar_a_crudo",))]
    previa = b1.investigacion_previa("c")["destino"]
    assert previa["estado"] == "PROPUESTA" and previa["propuesta_publicada"] == PROPUESTO
    assert (previa["calle"], previa["numero"], previa["comuna"]) == ("AVENIDA APOQUINDO", "1234", "LAS CONDES")


# ------------------------------------------------------------ flujo feliz


def test_investigacion_luego_correccion_preview_limpio_sin_aplicar(b1):
    b1.atender("c", INVESTIGA)
    antes = _huellas(b1)
    p = b1.atender("c", CORRIGE)
    assert p["estado"] == "PREVIEW_PENDIENTE", p
    assert len(b1.investigaciones) == 1  # no re-investiga
    assert p["mensaje"].startswith(f"Guía: {GUIA}\nDestino actual: {DOCUMENTAL}\nDestino propuesto: {PROPUESTO}\n")
    assert "Evidencia: Dos fuentes independientes" in p["mensaje"] and "a.example, b.example" in p["mensaje"]
    assert "¿Confirmas?" in p["mensaje"]
    assert p["preview"]["valor_actual"] == {"destino": DOCUMENTAL}
    assert p["preview"]["valor_propuesto"] == {"destino": PROPUESTO}
    visible = json.dumps({"mensaje": p["mensaje"], "preview": p["preview"]}, ensure_ascii=False)
    for ruido in (b1.decision["decision_id"], "decision_id", "token", "DECISION_APLICAR", "REGISTRAR_DIRECCION",
                  "PROPUESTA_RESOLUBLE", "CORRECCION_DESDE", "COMPATIBLE", "NO_APORTA", "score"):
        assert ruido not in visible, ruido
    assert not UUID.search(visible)
    # no aplica antes de confirmar
    assert _huellas(b1) == antes and b1.capa.auditoria() == []
    assert b1.pendiente("c")["accion"] == "DECISION_APLICAR"


def test_confirmacion_usa_mecanismo_controlado_y_preserva_documental(b1):
    b1.atender("c", INVESTIGA)
    b1.atender("c", CORRIGE)
    e = b1.atender("c", "sí")
    assert e["estado"] == "EJECUTADA", e
    assert e["mensaje"] == f"Aplicado: la guía {GUIA} queda con el destino {PROPUESTO}."
    fila = _leer_csv(b1.entorno["dataset"])[0]
    # El mecanismo existente (mismo que Revisión) deja la dirección operacional
    # en el dataset; el texto documental original queda en el ledger.
    assert fila["despachar_a_crudo"] == "AVENIDA APOQUINDO 1234"
    assert fila["estado_ruta"] == "RUTA_CALCULADA", {k: fila[k] for k in ("motivo_ruta", "estado_entrega", "direccion_entrega", "localidad_entrega")}
    actual = b1.entorno["actual"]
    bandeja = json.loads((actual / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    assert b1.decision["decision_id"] not in {d["decision_id"] for d in bandeja["decisiones"]}
    ledger = json.loads((actual / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]
    aplicadas = [a for a in ledger if a["decision_id"] == b1.decision["decision_id"]]
    assert len(aplicadas) == 1 and aplicadas[0]["accion"] == "REGISTRAR_DIRECCION" and aplicadas[0]["actor"] == "B1"
    assert aplicadas[0]["valor_documental_anterior"] == DOCUMENTAL
    assert (aplicadas[0]["direccion_manual"], aplicadas[0]["comuna_manual"]) == ("AVENIDA APOQUINDO 1234", "LAS CONDES")
    auditoria = b1.capa.auditoria()
    assert len(auditoria) == 1 and auditoria[0]["accion"] == "DECISION_APLICAR"
    assert auditoria[0]["confirmado_por"] == "JAVIER" and auditoria[0]["origen"] == "B1"
    registro = json.loads((actual / "acciones_operacionales.json").read_text(encoding="utf-8"))
    assert "Investigación B1 previa" in json.dumps(registro, ensure_ascii=False)
    assert "https://a.example/contacto" in json.dumps(registro, ensure_ascii=False)
    # idempotencia: el mismo token no reaplica y la investigación ya se consumió
    huellas = _huellas(b1)
    assert b1.capa.ejecutar(auditoria[0]["token"], actor="B1", origen="B1", confirmado_por="JAVIER")["idempotente"]
    assert b1.atender("c", CORRIGE)["estado"] == "RECHAZADA"
    assert _huellas(b1) == huellas and len(b1.capa.auditoria()) == 1


# ------------------------------------------------------------ rechazos seguros


def _rechaza_sin_escribir(b1, conversacion="c", texto=CORRIGE):
    antes = _huellas(b1)
    r = b1.atender(conversacion, texto)
    assert r["estado"] == "RECHAZADA", r
    assert b1.pendiente(conversacion) is None and _huellas(b1) == antes and b1.capa.auditoria() == []
    assert b1.atender(conversacion, "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert not UUID.search(r["mensaje"]) and "_" not in r["mensaje"]
    return r


def test_otra_guia_rechazada(b1):
    b1.atender("c", INVESTIGA)
    r = _rechaza_sin_escribir(b1, texto="Corrige el destino de la guía 999999 usando la dirección que acabas de identificar")
    assert "otra guía" in r["mensaje"]


def test_otra_conversacion_rechazada(b1):
    b1.atender("c", INVESTIGA)
    _rechaza_sin_escribir(b1, "otra")


def test_investigacion_de_obra_no_sirve_para_destino(b1):
    b1.atender("c", f"Investiga la obra de la guía {GUIA}")
    assert "no fue sobre ese dato" in _rechaza_sin_escribir(b1)["mensaje"]


def test_investigacion_fallida_rechazada(b1):
    b1.respuesta_investigacion["valor"] = OSError("sin acceso")
    b1.atender("c", INVESTIGA)
    assert "no se completó" in _rechaza_sin_escribir(b1)["mensaje"]


def test_busqueda_externa_caida_rechazada(b1):
    b1.respuesta_investigacion["valor"] = _resultado(_expediente(estado="BUSQUEDA_NO_DISPONIBLE", nivel="INSUFICIENTE",
                                                                 accion="ABSTENERSE"), busqueda="FALLIDA")
    b1.atender("c", INVESTIGA)
    assert b1.investigacion_previa("c")["destino"]["estado"] == "FALLIDA"
    _rechaza_sin_escribir(b1)


def test_evidencia_insuficiente_rechazada(b1):
    b1.respuesta_investigacion["valor"] = _resultado(_expediente(estado="ABSTENCION", nivel="INSUFICIENTE",
                                                                 accion="ABSTENERSE"))
    b1.atender("c", INVESTIGA)
    assert "evidencia suficiente" in _rechaza_sin_escribir(b1)["mensaje"]


def test_propuesta_ambigua_rechazada(b1):
    otra = [_fuente("c.example", numero="900", calle="AVENIDA KENNEDY"), _fuente("d.example", numero="900",
                                                                                  calle="AVENIDA KENNEDY")]
    b1.respuesta_investigacion["valor"] = _resultado(_expediente(), _expediente(fuentes=otra,
                                                                               propuesta="AVENIDA KENNEDY 900, LAS CONDES"))
    b1.atender("c", INVESTIGA)
    assert "más de un valor" in _rechaza_sin_escribir(b1)["mensaje"]


def test_contradiccion_rechazada(b1):
    b1.respuesta_investigacion["valor"] = _resultado(_expediente(comparaciones={"CALLE": "COMPATIBLE",
                                                                                "COMUNA": "CONTRADICE"}))
    b1.atender("c", INVESTIGA)
    assert "contradice" in _rechaza_sin_escribir(b1)["mensaje"]


def test_numero_documental_distinto_es_contradiccion(b1):
    b1.respuesta_investigacion["valor"] = _resultado(_expediente(numero_documental="1250"))
    b1.atender("c", INVESTIGA)
    assert b1.investigacion_previa("c")["destino"]["estado"] == "CONTRADICCION"
    _rechaza_sin_escribir(b1)


@pytest.mark.parametrize("fuentes", [
    [_fuente("a.example", numero=""), _fuente("b.example", numero="")],          # sólo calle/comuna
    [_fuente("a.example", numero="1234"), _fuente("b.example", numero="1240")],  # fuentes no coinciden
    [_fuente("a.example", numero="1234", verificada=False)],                      # sin fuente verificada
])
def test_numero_no_sustentado_no_se_inventa(b1, fuentes):
    b1.respuesta_investigacion["valor"] = _resultado(_expediente(fuentes=fuentes))
    b1.atender("c", INVESTIGA)
    assert b1.investigacion_previa("c")["destino"]["estado"] == "NUMERO_NO_SUSTENTADO"
    assert "no completo el número" in _rechaza_sin_escribir(b1)["mensaje"]


def test_sin_revision_de_destino_pendiente_rechazada(tmp_path, b1):
    from atlas_core.decisiones_pendientes import generar_artefacto  # noqa: F401
    ruta = b1.entorno["actual"] / "decisiones_pendientes.json"
    bandeja = json.loads(ruta.read_text(encoding="utf-8"))
    bandeja["decisiones"] = []
    ruta.write_text(json.dumps(bandeja), encoding="utf-8")
    b1.atender("c", INVESTIGA)
    assert "no tiene una revisión de destino pendiente" in _rechaza_sin_escribir(b1)["mensaje"]


def test_instruccion_intermedia_o_vencida_invalida(b1):
    b1.atender("c", INVESTIGA)
    b1.atender("c", "¿Qué decisiones hay pendientes?")
    _rechaza_sin_escribir(b1)
    b1.atender("c", INVESTIGA)
    b1.reloj_prueba.ahora += timedelta(minutes=31)
    _rechaza_sin_escribir(b1)


def test_corregir_obra_y_destino_a_la_vez_no_adivina(b1):
    b1.atender("c", INVESTIGA)
    r = _rechaza_sin_escribir(b1, texto=f"Corrige la obra y el destino de la guía {GUIA} con lo que acabas de identificar")
    assert "obra o el destino" in r["mensaje"]


def test_registro_no_depende_del_texto_visible():
    registro = registro_investigacion_destino(GUIA, ("despachar_a_crudo",), _resultado(_expediente()), "x")
    assert registro["estado"] == "PROPUESTA" and registro["valor_documental"] == DOCUMENTAL
    assert registro["fuentes"] == ["https://a.example/contacto", "https://b.example/contacto"]
    assert registro_investigacion_destino(GUIA, ("obra_destino",), _resultado(_expediente()), "x")["estado"] \
        == "NO_SOLICITADA"
