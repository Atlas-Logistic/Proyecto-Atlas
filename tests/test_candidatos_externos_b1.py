"""Búsqueda adaptativa y decisión por anclajes estructurales, sin red real."""
import json
from types import SimpleNamespace

from atlas_core.atlas_ia.candidatos_externos import (
    CandidatoExterno, buscar_adaptativamente, comparar_localidad,
    comparar_numero, evaluar_candidatos, extraer_candidatos_respuesta,
)


def _candidato(url, *, direccion="Calle Lago", numero="361", comuna="Puerto Claro",
               rut="", anclajes=("DIRECCION", "NUMERO", "COMUNA", "ENTIDAD", "NOMBRE_COMPLETO")):
    return CandidatoExterno(nombre="Ferretería Azul Centro", direccion=direccion,
        numero=numero, comuna=comuna, rut=rut, url=url, verificacion="VERIFICADA",
        anclajes_verificados=anclajes, fragmento="texto original", fragmento_fuente="texto verificado")


def _evaluar(*candidatos, **cambios):
    datos = dict(candidatos=list(candidatos), obra="Ferreteria Azul Centra",
        cliente="Ferreteria Azul SA", rut_cliente="12.345.678-9",
        direccion_documental="Calle Laga J61 Puerto Claro", localidad="Puerto Claro")
    datos.update(cambios)
    return evaluar_candidatos(**datos)


def test_candidato_estructurado_conserva_original_y_verifica_fuente():
    url = "https://ejemplo.cl/tienda"
    bruto = {"nombre": "Ferretería Azul Centro", "razon_social": "Azul S.A.",
             "direccion": "Calle Lago", "numero": "361", "comuna": "Puerto Claro",
             "ciudad": "Puerto Claro", "region": "Sur", "rut": "12.345.678-9",
             "codigo": "T9", "tipo_entidad": "establecimiento", "tipo_fuente": "directorio",
             "url": url, "fragmento": "Calle Lago 361"}
    respuesta = SimpleNamespace(respuesta_texto=json.dumps({"candidatos": [bruto]}),
        citas=(SimpleNamespace(url=url),), consulta="entidad y calle", fecha="2026-01-01")
    candidatos = extraer_candidatos_respuesta(respuesta,
        leer_fuente=lambda _: "Ferretería Azul Centro. Calle Lago 361, Puerto Claro. RUT 12.345.678-9")
    assert len(candidatos) == 1
    c = candidatos[0]
    assert c.verificacion == "VERIFICADA"
    assert {"DIRECCION", "NUMERO", "COMUNA", "RUT"} <= set(c.anclajes_verificados)
    assert c.fragmento == "Calle Lago 361" and c.fragmento_fuente
    assert c.url == url and c.consultado_en == "2026-01-01"


def test_fuente_no_citada_o_sin_texto_es_no_verificable():
    respuesta = SimpleNamespace(respuesta_texto=json.dumps({"candidatos": [{
        "nombre": "Azul", "direccion": "Calle Lago", "numero": "361",
        "comuna": "Puerto Claro", "url": "https://inventada.cl"}]}),
        citas=(SimpleNamespace(url="https://otra.cl"),), consulta="q", fecha="hoy")
    c = extraer_candidatos_respuesta(respuesta, leer_fuente=lambda _: "Calle Lago 361 Puerto Claro")[0]
    assert c.verificacion == "NO_VERIFICABLE"


def test_dos_fuentes_independientes_convergentes():
    r = _evaluar(_candidato("https://uno.cl/a"), _candidato("https://dos.cl/b"))
    assert r["estado"] == "PROPUESTA_RESOLUBLE"
    assert r["propuesta"]["comparaciones"]["NUMERO"] == "COMPATIBLE"
    assert r["propuesta"]["fuentes_independientes"] == ["dos.cl", "uno.cl"]


def test_fuente_unica_insuficiente():
    assert _evaluar(_candidato("https://uno.cl/a"))["estado"] == "ABSTENCION"


def test_dos_paginas_misma_direccion_sin_misma_entidad_no_convergen():
    ajeno = CandidatoExterno(nombre="Centro Comercial Verde", direccion="Calle Lago",
        numero="361", comuna="Puerto Claro", url="https://dos.cl/b",
        verificacion="VERIFICADA", anclajes_verificados=("DIRECCION", "NUMERO", "COMUNA", "ENTIDAD"))
    r = _evaluar(_candidato("https://uno.cl/a"), ajeno)
    assert r["estado"] == "ABSTENCION"
    assert r["candidatos_evaluados"][0]["fuentes_independientes"] == ["uno.cl"]


def test_numero_contradictorio_bloquea():
    r = _evaluar(_candidato("https://uno.cl/a", numero="725"),
                 _candidato("https://dos.cl/b", numero="725"))
    assert r["estado"] == "ABSTENCION"
    assert r["candidatos_evaluados"][0]["comparaciones"]["NUMERO"] == "CONTRADICE"


def test_comuna_contradictoria_bloquea():
    r = _evaluar(_candidato("https://uno.cl/a", comuna="Puerto Gris"),
                 _candidato("https://dos.cl/b", comuna="Puerto Gris"))
    assert r["estado"] == "ABSTENCION"
    assert r["candidatos_evaluados"][0]["comparaciones"]["COMUNA"] == "CONTRADICE"
    assert comparar_localidad("San Bernardo", "San Miguel") == "CONTRADICE"


def test_rut_contradictorio_bloquea():
    anclajes = ("DIRECCION", "NUMERO", "COMUNA", "ENTIDAD", "RUT")
    r = _evaluar(_candidato("https://uno.cl/a", rut="11.111.111-1", anclajes=anclajes),
                 _candidato("https://dos.cl/b", rut="11.111.111-1", anclajes=anclajes))
    assert r["estado"] == "ABSTENCION"
    assert r["candidatos_evaluados"][0]["comparaciones"]["RUT"] == "CONTRADICE"


def test_dos_candidatos_plausibles_abstienen():
    r = _evaluar(_candidato("https://uno.cl/a"), _candidato("https://dos.cl/b"),
                 _candidato("https://tres.cl/c", numero="461"),
                 _candidato("https://cuatro.cl/d", numero="461"))
    assert r["estado"] == "ABSTENCION"
    assert "Dos candidatos" in r["razon"]


def test_busqueda_adaptativa_trazable_y_acotada():
    fuente = "https://uno.cl/a"
    bruto = {"nombre": "Ferretería Azul Centro", "direccion": "Calle Lago",
             "numero": "361", "comuna": "Puerto Claro", "url": fuente}
    llamadas = []

    class Buscador:
        def buscar(self, consulta):
            llamadas.append(consulta)
            return SimpleNamespace(consulta=consulta, fecha="2026-01-01",
                respuesta_texto=json.dumps({"candidatos": [bruto] if len(llamadas) == 1 else []}),
                citas=(SimpleNamespace(url=fuente),))

    r = buscar_adaptativamente(buscador=Buscador(), entidad="Ferreteria Azul Centra",
        direccion="Calle Laga J61 Puerto Claro", localidad="Puerto Claro",
        leer_fuente=lambda _: "Ferretería Azul Centro, Calle Lago 361, Puerto Claro", max_consultas=2)
    assert len(r.traza) == len(llamadas) == 2
    assert r.traza[0]["incertidumbre"] == "IDENTIDAD_Y_DIRECCION"
    assert "361" in r.traza[1]["consulta"]
    assert r.traza[1]["incertidumbre"].startswith("CORROBORAR:")


def test_busqueda_corrobora_nombre_aunque_no_haya_direccion_publicada():
    primero, segundo = "https://minvu.gob.cl/ficha", "https://diariooficial.cl/aviso"
    bruto = {"razon_social": "EMPRESA CONSTRUCTORA BRAVO E IZQUIERDO LIMITADA",
             "rut": "84.102.200-9", "url": primero}
    llamadas = []

    class Buscador:
        def buscar(self, consulta):
            llamadas.append(consulta)
            url = primero if len(llamadas) == 1 else segundo
            candidato = {**bruto, "url": url}
            return SimpleNamespace(consulta=consulta, fecha="2026-01-01",
                respuesta_texto=json.dumps({"candidatos": [candidato]}),
                citas=(SimpleNamespace(url=url),))

    resultado = buscar_adaptativamente(buscador=Buscador(), entidad="EMPRESA CONSTRUCTORA BRAVO E",
        direccion="", localidad="", leer_fuente=lambda _: "EMPRESA CONSTRUCTORA BRAVO E IZQUIERDO LIMITADA 84.102.200-9")
    from atlas_core.atlas_ia.candidatos_externos import evaluar_nombre_obra
    evaluacion = evaluar_nombre_obra(candidatos=resultado.candidatos,
                                     obra_documental="EMPRESA CONSTRUCTORA BRAVO E")
    assert len(llamadas) == 2
    assert resultado.traza[1]["incertidumbre"].startswith("CORROBORAR_NOMBRE:")
    assert evaluacion["estado"] == "PROPUESTA_RESOLUBLE"


def test_numero_ocr_ambiguo_no_equivale_a_numero_limpio():
    assert comparar_numero("J61", "361") == "COMPATIBLE"
    assert comparar_numero("461", "361") == "CONTRADICE"
