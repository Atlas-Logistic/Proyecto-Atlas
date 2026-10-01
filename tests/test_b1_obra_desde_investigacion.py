"""B1 -- corregir la obra de una guía con la propuesta ESTRUCTURADA de la
investigación inmediatamente anterior de la MISMA conversación y la MISMA
guía ("corrige la obra ... con el nombre que acabas de identificar").
Preview limpio + confirmación humana; aplica por DOCUMENTO_ASIGNAR_OBRA
(obra existente, ledger con el valor documental). Copias sintéticas; nunca G:."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales, TIPO_LEDGER_CORRECCION
from atlas_core.atlas_ia import investigacion_revision
from atlas_core.catalogo_obras_destinos import normalizar_nombre_obra
from atlas_core.b1_operador import (
    ACCION_INVESTIGAR_REVISION, ACCION_OBRA_DESDE_INVESTIGACION, OperadorB1, interpretar_determinista,
    registro_investigacion_obra,
)
from atlas_core.identidad_canonica import clave_identidad, misma_identidad, nombre_visible
from tests.test_acciones_operacionales import entorno  # noqa: F401 -- fixture

INVESTIGA = "Investiga la obra de la guía 500001 y dime cuál es su nombre completo. No hagas ningún cambio."
CORRIGE = "Corrige el nombre de la obra de la guía 500001 usando el nombre completo que acabas de identificar."
OBRA_ID = "obra-completa"
PUBLICADO = "OBRA VIEJA COMPLETA LIMITADA"   # tal como lo publica la fuente
VISIBLE = "OBRA VIEJA COMPLETA LTDA"         # convención operacional Atlas
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def _obra(obra_id, nombre, cliente_id, aliases=()):
    return {"obra_id": obra_id, "cliente_id": cliente_id, "nombre_canonico": nombre,
            "nombre_normalizado": normalizar_nombre_obra(nombre), "aliases_documentales": list(aliases),
            "estado": "OBSERVADA", "estado_vigencia": "ACTIVO", "evidencias": [],
            "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00"}


def _expediente(propuesta=PUBLICADO, *, nivel="PROPUESTA_RESOLUBLE", accion="PROPONER_A_HUMANO",
                estado_externo="PROPUESTA_RESOLUBLE"):
    return {"CAMPO": "obra_destino", "HECHOS_DOCUMENTALES": {"valor_extraido": "OBRA VIEJA"},
            "PROPUESTA": propuesta, "NIVEL_EVIDENCIA": nivel, "ACCION_RECOMENDADA": accion,
            "EVALUACION_CANDIDATOS_EXTERNOS": {"estado": estado_externo, "razon": "Dos fuentes públicas convergen."},
            "EVIDENCIA_EXTERNA": [{"referencias_fuente": ["https://fuente.example/obra", "fragmento"]}],
            "PREVIEW_OPERACIONAL": {"valor_actual": "OBRA VIEJA", "valor_propuesto": propuesta,
                                    "evidencia_relevante": "Dos fuentes públicas convergen."} if propuesta else None}


def _resultado(*expedientes, busqueda="OK"):
    return {"numero_guia": "500001", "numero_transporte": "0000900001", "expedientes": list(expedientes),
            "BUSQUEDA_EXTERNA": {"estado": busqueda}}


class Reloj:
    def __init__(self):
        self.ahora = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.ahora


@pytest.fixture
def b1(entorno, monkeypatch):  # noqa: F811
    cliente_id = entorno["cliente"].cliente_id
    obras = [_obra(OBRA_ID, PUBLICADO, cliente_id, ["OBRA VIEJA COMPLETA"]),
             _obra("sur-a", "EDIFICIO SUR UNO SPA", cliente_id), _obra("sur-b", "EDIFICIO SUR DOS SPA", cliente_id)]
    (entorno["cat"] / "obras_destinos.json").write_text(
        json.dumps({"version_formato": 1, "obras": obras, "relaciones": []}), encoding="utf-8")
    reloj = Reloj()
    capa = CapaAccionesOperacionales(entorno["raiz"])
    revalidadas: list[set[str]] = []
    capa._revalidar_guias = lambda guias: revalidadas.append(set(guias)) or {"ejecutado": True}
    operador = OperadorB1(entorno["raiz"], capa=capa, reloj=reloj)
    operador.revalidadas, operador.reloj_prueba = revalidadas, reloj
    operador.investigaciones = []
    respuesta = {"valor": _resultado(_expediente())}

    def investigar(numero_guia, **kwargs):
        operador.investigaciones.append(numero_guia)
        if isinstance(respuesta["valor"], Exception):
            raise respuesta["valor"]
        return {**respuesta["valor"], "numero_guia": numero_guia}

    monkeypatch.setattr(investigacion_revision, "investigar_revision", investigar)
    operador.respuesta_investigacion = respuesta
    return operador


def _sha(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest() if ruta.exists() else None


def _huellas(entorno):
    return {n: _sha(p) for n, p in {
        "dataset": entorno["dataset"], "obras": entorno["cat"] / "obras_destinos.json",
        "ledger": entorno["actual"] / "decisiones_aplicadas.json",
        "bandeja": entorno["actual"] / "decisiones_pendientes.json"}.items()}


def _fila(entorno, guia="500001"):
    return next(f for f in csv.DictReader(entorno["dataset"].open(encoding="utf-8-sig", newline=""), delimiter=";")
                if f["numero_guia"] == guia)


# ------------------------------------------------------------ identidad canónica (gemelo Desktop)


def test_identidad_societaria_igual_que_desktop():
    assert misma_identidad("FOO LIMITADA", "Foo Ltda.") and misma_identidad("FOO LTDA", "FOO, LTDA")
    assert misma_identidad("FOO SOCIEDAD ANÓNIMA", "FOO S. A.") and misma_identidad("FOO SA", "foo s.a.")
    assert misma_identidad("FOO SOCIEDAD POR ACCIONES", "Foo SpA")
    assert misma_identidad("FOO EMPRESA INDIVIDUAL DE RESPONSABILIDAD LIMITADA", "FOO E.I.R.L.")
    assert not misma_identidad("FOO SPA", "FOO LTDA") and not misma_identidad("FOO S.A.", "FOO LTDA")
    assert clave_identidad("Ingeniería  y Cía. Ltda.") == "INGENIERIA Y CIA LTDA"
    assert nombre_visible("FOO SOCIEDAD ANÓNIMA") == "FOO S.A." and nombre_visible("FOO S.P.A.") == "FOO SpA"
    assert nombre_visible(PUBLICADO) == VISIBLE and nombre_visible("FOO E.I.R.L.") == "FOO EIRL"


# ------------------------------------------------------------ intención


def test_intencion_reutilizacion_va_antes_que_investigar():
    assert interpretar_determinista(CORRIGE).accion == ACCION_OBRA_DESDE_INVESTIGACION
    assert interpretar_determinista(CORRIGE).parametros == {"numero_guia": "500001"}
    assert interpretar_determinista("Aplica la propuesta anterior a la obra de la guía 500001").accion \
        == ACCION_OBRA_DESDE_INVESTIGACION
    assert interpretar_determinista(INVESTIGA).accion == ACCION_INVESTIGAR_REVISION
    # la corrección explícita con nombre sigue siendo DOCUMENTO_ASIGNAR_OBRA
    assert interpretar_determinista("Corrige la obra de la guía 500001 a OBRA DOS").accion == "DOCUMENTO_ASIGNAR_OBRA"


# ------------------------------------------------------------ flujo feliz


def test_investigacion_luego_correccion_produce_preview_limpio_sin_aplicar(entorno, b1):
    r = b1.atender("chat", INVESTIGA)
    assert r["estado"] == "RESULTADO_INVESTIGACION" and b1.pendiente("chat") is None
    previa = b1.investigacion_previa("chat")
    assert previa["estado"] == "PROPUESTA" and previa["propuesta_publicada"] == PUBLICADO
    antes = _huellas(entorno)

    p = b1.atender("chat", CORRIGE)
    assert p["estado"] == "PREVIEW_PENDIENTE", p
    assert b1.investigaciones == ["500001"]  # no re-investiga
    assert p["mensaje"].startswith(f"Guía: 500001\nObra actual: OBRA VIEJA\nObra propuesta: {VISIBLE}\n")
    assert "¿Confirmas?" in p["mensaje"]
    assert p["preview"]["valor_actual"] == {"obra_destino": "OBRA VIEJA"}
    assert p["preview"]["valor_propuesto"] == {"obra_destino": VISIBLE}
    # sin IDs/UUID/tokens/acciones internas/códigos en lo visible
    visible = json.dumps({"mensaje": p["mensaje"], "preview": p["preview"]}, ensure_ascii=False)
    for ruido in (OBRA_ID, entorno["cliente"].cliente_id, "obra_id", "token", "DOCUMENTO_ASIGNAR_OBRA",
                  "OBRA_DESDE_INVESTIGACION", "PROPUESTA_RESOLUBLE", "LIMITADA"):
        assert ruido not in visible, ruido
    assert not UUID.search(visible)
    # no aplica antes de confirmar
    assert _huellas(entorno) == antes and b1.revalidadas == []
    assert b1.pendiente("chat")["accion"] == "DOCUMENTO_ASIGNAR_OBRA"


def test_confirmacion_usa_mecanismo_controlado_y_preserva_documental_y_evidencia(entorno, b1):
    obras_antes = _sha(entorno["cat"] / "obras_destinos.json")
    b1.atender("chat", INVESTIGA)
    b1.atender("chat", CORRIGE)
    e = b1.atender("chat", "sí")
    assert e["estado"] == "EJECUTADA", e
    assert e["mensaje"] == f"Aplicado: la guía 500001 queda con la obra {VISIBLE}."
    assert e["resultado"]["antes"] == {"obra_destino": "OBRA VIEJA"}
    assert e["resultado"]["despues"] == {"obra_destino": VISIBLE}
    # dato operacional: nombre canónico tal como se publicó (Viajes lo presenta abreviado)
    assert _fila(entorno)["obra_destino"] == PUBLICADO
    assert _fila(entorno, "500002")["obra_destino"] == "OBRA OTRA"
    assert b1.revalidadas == [{"500001"}]
    # mecanismo controlado existente: auditoría de la capa + ledger con el documental
    auditoria = b1.capa.auditoria()
    assert len(auditoria) == 1 and auditoria[0]["accion"] == "DOCUMENTO_ASIGNAR_OBRA"
    assert auditoria[0]["confirmado_por"] == "JAVIER" and auditoria[0]["origen"] == "B1"
    assert auditoria[0]["despues"] == {"obra_destino": PUBLICADO, "obra_id": OBRA_ID}
    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]
    correcciones = [a for a in ledger if a["tipo"] == TIPO_LEDGER_CORRECCION]
    assert [(a["campo"], a["valor_documental"], a["valor_corregido"]) for a in correcciones] == [
        ("obra_destino", "OBRA VIEJA", PUBLICADO)]
    referencia = correcciones[0]["referencia"]
    assert "Investigación B1 previa" in referencia and PUBLICADO in referencia
    assert "https://fuente.example/obra" in referencia
    # catálogo intacto: ni obra nueva ni alias
    assert _sha(entorno["cat"] / "obras_destinos.json") == obras_antes
    # la investigación ya se consumió
    assert b1.investigacion_previa("chat") is None
    assert b1.atender("chat", CORRIGE)["estado"] == "RECHAZADA"


def test_cancelar_no_aplica(entorno, b1):
    b1.atender("chat", INVESTIGA)
    antes = _huellas(entorno)
    assert b1.atender("chat", CORRIGE)["estado"] == "PREVIEW_PENDIENTE"
    assert b1.atender("chat", "no")["estado"] == "CANCELADA"
    assert _huellas(entorno) == antes and b1.capa.auditoria() == []


# ------------------------------------------------------------ rechazos seguros


def _rechaza_sin_escribir(entorno, b1, conversacion, texto=CORRIGE):
    antes = _huellas(entorno)
    r = b1.atender(conversacion, texto)
    assert r["estado"] == "RECHAZADA", r
    assert b1.pendiente(conversacion) is None and _huellas(entorno) == antes
    assert b1.atender(conversacion, "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    visible = r["mensaje"]
    assert not UUID.search(visible) and OBRA_ID not in visible and "_" not in visible
    return r


def test_otra_guia_rechazo_seguro(entorno, b1):
    b1.atender("chat", INVESTIGA)
    r = _rechaza_sin_escribir(entorno, b1, "chat",
                              "Corrige la obra de la guía 500002 con el nombre que acabas de identificar")
    assert "guía 500001" in r["mensaje"] and "otra guía" in r["mensaje"]


def test_otra_conversacion_rechazo_seguro(entorno, b1):
    b1.atender("chat", INVESTIGA)
    r = _rechaza_sin_escribir(entorno, b1, "otro-chat")
    assert "investigación reciente" in r["mensaje"]


def test_sin_investigacion_previa_rechazo_seguro(entorno, b1):
    _rechaza_sin_escribir(entorno, b1, "chat")


def test_investigacion_sin_propuesta_rechazo_seguro(entorno, b1):
    b1.respuesta_investigacion["valor"] = _resultado(_expediente("", nivel="INSUFICIENTE", accion="ABSTENERSE",
                                                                 estado_externo="ABSTENCION"))
    b1.atender("chat", INVESTIGA)
    assert b1.investigacion_previa("chat")["estado"] == "SIN_PROPUESTA"
    assert "evidencia suficiente" in _rechaza_sin_escribir(entorno, b1, "chat")["mensaje"]


def test_investigacion_fallida_rechazo_seguro(entorno, b1):
    b1.respuesta_investigacion["valor"] = OSError("sin acceso al documento")
    assert b1.atender("chat", INVESTIGA)["estado"] == "INVESTIGACION_NO_DISPONIBLE"
    assert b1.investigacion_previa("chat")["estado"] == "FALLIDA"
    assert "no se completó" in _rechaza_sin_escribir(entorno, b1, "chat")["mensaje"]


def test_busqueda_externa_caida_cuenta_como_fallida(entorno, b1):
    b1.respuesta_investigacion["valor"] = _resultado(_expediente("", nivel="INSUFICIENTE", accion="ABSTENERSE",
                                                                 estado_externo="BUSQUEDA_NO_DISPONIBLE"),
                                                     busqueda="FALLIDA")
    b1.atender("chat", INVESTIGA)
    assert b1.investigacion_previa("chat")["estado"] == "FALLIDA"
    _rechaza_sin_escribir(entorno, b1, "chat")


def test_fallida_posterior_anula_propuesta_exitosa_anterior(entorno, b1):
    b1.atender("chat", INVESTIGA)
    b1.respuesta_investigacion["valor"] = OSError("caída")
    b1.atender("chat", INVESTIGA)
    _rechaza_sin_escribir(entorno, b1, "chat")


def test_propuesta_ambigua_rechazo_seguro(entorno, b1):
    b1.respuesta_investigacion["valor"] = _resultado(_expediente(PUBLICADO), _expediente("OTRA OBRA DISTINTA SPA"))
    b1.atender("chat", INVESTIGA)
    assert b1.investigacion_previa("chat")["estado"] == "AMBIGUA"
    assert "más de un nombre" in _rechaza_sin_escribir(entorno, b1, "chat")["mensaje"]


def test_mismo_nombre_con_otra_forma_societaria_escrita_no_es_ambiguo(entorno, b1):
    b1.respuesta_investigacion["valor"] = _resultado(_expediente(PUBLICADO), _expediente("Obra Vieja Completa Ltda."))
    b1.atender("chat", INVESTIGA)
    assert b1.investigacion_previa("chat")["estado"] == "PROPUESTA"
    assert b1.atender("chat", CORRIGE)["estado"] == "PREVIEW_PENDIENTE"


def test_propuesta_con_contradiccion_documental_no_es_reutilizable(entorno, b1):
    b1.respuesta_investigacion["valor"] = _resultado(_expediente(nivel="CONTRADICCION_DOCUMENTAL",
                                                                 accion="REVISAR_ORIGINAL_Y_CONFIRMAR"))
    b1.atender("chat", INVESTIGA)
    _rechaza_sin_escribir(entorno, b1, "chat")


def test_obra_propuesta_inexistente_no_se_crea(entorno, b1):
    b1.respuesta_investigacion["valor"] = _resultado(_expediente("TORRE INVENTADA SPA"))
    b1.atender("chat", INVESTIGA)
    r = _rechaza_sin_escribir(entorno, b1, "chat")
    assert "no está registrada" in r["mensaje"] and "TORRE INVENTADA SpA" in r["mensaje"]


def test_propuesta_coincide_con_varias_obras_no_elige(entorno, b1):
    cliente_id = entorno["cliente"].cliente_id
    ruta = entorno["cat"] / "obras_destinos.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["obras"].append(_obra("gemela", "Obra Vieja Completa Ltda.", cliente_id))
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    b1.atender("chat", INVESTIGA)
    assert "más de una obra" in _rechaza_sin_escribir(entorno, b1, "chat")["mensaje"]


def test_otra_instruccion_intermedia_invalida_la_investigacion(entorno, b1):
    b1.atender("chat", INVESTIGA)
    b1.atender("chat", "¿Qué decisiones hay pendientes?")
    _rechaza_sin_escribir(entorno, b1, "chat")


def test_investigacion_vencida_no_se_reutiliza(entorno, b1):
    b1.atender("chat", INVESTIGA)
    b1.reloj_prueba.ahora += timedelta(minutes=31)
    _rechaza_sin_escribir(entorno, b1, "chat")


def test_registro_estructurado_no_depende_del_texto_mostrado():
    registro = registro_investigacion_obra("1", ("obra_destino",), _resultado(_expediente()), "2026-10-01T00:00:00+00:00")
    assert registro["estado"] == "PROPUESTA" and registro["valor_documental"] == "OBRA VIEJA"
    assert registro["fuentes"] == ["https://fuente.example/obra"]
    assert registro_investigacion_obra("1", ("despachar_a_crudo",), _resultado(_expediente()), "x")["estado"] \
        == "NO_SOLICITADA"
