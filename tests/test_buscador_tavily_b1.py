"""Tavily como buscador externo de la investigación adaptativa B1.

Fixtures = resultados reales de Tavily (01-10-2026) para la consulta
documental de la guía 474993. Nunca hay llamadas reales a Tavily."""
import csv
import json
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from atlas_core.almacenamiento_portable import VARIABLE_ENTORNO
from atlas_core.atlas_ia import buscador_web, credenciales, investigacion_revision
from atlas_core.atlas_ia.buscador_tavily import (
    BuscadorWebTavily, buscar_adaptativamente_tavily, candidatos_desde_tavily, construir_consulta_tavily,
)
from atlas_core.atlas_ia.buscador_web import BuscadorWebConCache, RepositorioCacheBusquedaWeb, RespuestaHTTP
from atlas_core.atlas_ia.candidatos_externos import CandidatoExterno, evaluar_nombre_obra

CLAVE = "clave-prueba-tavily-no-real"
OBRA = "EMPRESA CONSTRUCTORA BRAVO E"
DESTINO = "AV. CAM. LOS TRAPENSES LO BARNECHEA LO BARNE"
ESPERADO = "EMPRESA CONSTRUCTORA BRAVO E IZQUIERDO LIMITADA"

RESULTADOS_REALES = [
    {"title": "Empresa Constructora Bravo E Izquierdo Limitada (Chile)", "url": "https://www.emis.com/php/company-profile/CL/Empresa_Constructora_Bravo_E_Izquierdo_Limitada_es_3448613.html", "content": "Empresa Constructora Bravo E Izquierdo Limitada es una empresa en Chile, con sede principal en Santiago. Opera en Construcción de Edificios", "score": 0.57},
    {"title": "Empresa Constructora Bravo E Izquierdo Lt…", "url": "https://datalux.cl/empresa/84102200-9-empresa-constructora-bravo-e-izquierdo-ltda", "content": "Empresa Constructora Bravo E Izquierdo Ltda. forma parte del sector arquitectura y construccion en LAS CONDES, Región Metropolitana, Chile y su estado", "score": 0.51},
    {"title": "Empresa Constructora Bravo E Izquierdo Ltda.", "url": "https://www.dateas.com/es/explore/proveedores-direccion-obras-publicas-chile/empresa-constructora-bravo-e-izquierdo-ltda-240", "content": "EMPRESA CONSTRUCTORA BRAVO E IZQUIERDO LTDA. Rut, 84102200-9. Dirección, PEDRO DE VALDIVIA N° 0193 PISO 7. Ciudad, SANTIAGO. Teléfono, 2332399 Llamar.", "score": 0.4},
    {"title": "EMPRESA CONSTRUCTORA BRAVO E IZQUIERDO LTDA.", "url": "https://licitapyme.cl/proveedor/84.102.200-9/empresa-constructora-bravo-e-izquierdo-ltda", "content": "RUT: 84.102.200-9 • EMPRESA CONSTRUCTORA BRAVO E IZQUIERDO LIMITADA. Canal Principal. Licitaciones. Tamaño. Grande. Tramo Ventas. Más de 1.000.000 UF.", "score": 0.38},
    {"title": "BRAVO E IZQUIERDO EMPRESA CONSTRUCTORA", "url": "https://obramaestra.com/proveedores/bravo-e-izquierdo-empresa-constructora", "content": "CONSTRUCTORA: Empresas constructoras y contratistas en Santiago. Pedro de Valdivia 0193 Piso 7 Providencia. ES Disponible enGoogle Play Disponible enApp Store", "score": 0.36},
    {"title": "Constructora Bravo SPA: Inicio", "url": "https://cbravo.cl", "content": "Construimos el futuro con precisión. Obras civiles, remodelaciones, estructuras metálicas e inspección técnica, con altos estándares de calidad, seguridad y", "score": 0.33},
    {"title": "EMPRESA CONSTRUCTORA BRAVO E IZQUIERDO", "url": "https://www.yelp.com/biz/empresa-constructora-bravo-e-izquierdo-santiago", "content": "Avenida Pedro de Valdivia 0193 Piso 7 RM Santiago Chile Providencia Directions 02 339 3300 Call Now Hours", "score": 0.3},
    {"title": "Constructora Bravo Spa | Santiago", "url": "https://www.facebook.com/constructorabravospa.cl", "content": "CONSTRUCTORA BRAVO SPA Obras Civiles, Gasfiteria, Electricidad, Estructuras Metalicas, Remodelaciones, Ampliaciones. Personal blog · +56 2 2840 9946.", "score": 0.29},
    {"title": "Contactanos | Constructora Bravo", "url": "https://constructorabravo.cl/contactanos", "content": "Constructora Bravo. Nuestros proyectos · Contactanos. Seleccionar página. Nuestros proyectos · Contactanos. Contactanos en. Diseñado por Funcolor.", "score": 0.27},
    {"title": "constructorabravo (@constructora_bravo_lanco) · Lanco", "url": "https://www.instagram.com/constructora_bravo_lanco", "content": "Fabricación e instalación de **portones en fierro y madera de pino Oregón**. ✨ Terminaciones pensadas para mantener la armonía con la vivienda existente. Un", "score": 0.22},
]


def _transporte(resultados, capturas=None):
    def transportar(solicitud, timeout):
        if capturas is not None:
            capturas.append(solicitud)
        return RespuestaHTTP(200, json.dumps({"results": resultados, "usage": {"credits": 1}}).encode())
    return transportar


def _candidatos(resultados, entidad=OBRA):
    respuesta = BuscadorWebTavily(api_key=CLAVE, transporte=_transporte(resultados)).buscar("consulta")
    return candidatos_desde_tavily(respuesta, entidad)


def _r(url, title="", content=""):
    return {"title": title, "url": url, "content": content, "score": 0.5}


# ------------------------------------------------------------- extracción + convergencia

def test_regresion_474993_propone_nombre_completo_con_dos_dominios():
    candidatos = _candidatos(RESULTADOS_REALES)
    evaluacion = evaluar_nombre_obra(candidatos=candidatos, obra_documental=OBRA)
    assert evaluacion["estado"] == "PROPUESTA_RESOLUBLE"
    assert evaluacion["propuesta"]["nombre_candidato"] == ESPERADO
    assert len(evaluacion["propuesta"]["fuentes_independientes"]) >= 2
    # Texto original de cada fuente conservado como evidencia.
    publicados = {c.nombre for c in candidatos}
    assert "Empresa Constructora Bravo E Izquierdo Ltda." in publicados
    assert "Empresa Constructora Bravo E Izquierdo Limitada" in publicados
    assert {c.rut for c in candidatos if c.rut} == {"84.102.200-9"}
    assert all(c.verificacion == "VERIFICADA" and c.fragmento_fuente for c in candidatos)


def test_limitada_y_ltda_convergen_y_se_prefiere_limitada():
    candidatos = _candidatos([
        _r("https://uno.cl/a", "Constructora Alfa Beta Gamma Ltda."),
        _r("https://dos.cl/b", content="Ficha: CONSTRUCTORA ALFA BETA GAMMA LIMITADA, Santiago."),
    ], "CONSTRUCTORA ALFA BETA")
    evaluacion = evaluar_nombre_obra(candidatos=candidatos, obra_documental="CONSTRUCTORA ALFA BETA")
    assert evaluacion["estado"] == "PROPUESTA_RESOLUBLE"
    assert evaluacion["propuesta"]["nombre_candidato"] == "CONSTRUCTORA ALFA BETA GAMMA LIMITADA"
    assert evaluacion["propuesta"]["fuentes_independientes"] == ["dos.cl", "uno.cl"]


def test_equivalencia_societaria_no_toca_palabras_no_societarias():
    candidatos = [
        CandidatoExterno(nombre=n, url=u, verificacion="VERIFICADA", anclajes_verificados=("NOMBRE_COMPLETO",))
        for n, u in (("CONSTRUCTORA ALFA LTDA SPA", "https://uno.cl"), ("CONSTRUCTORA ALFA LIMITADA SPA", "https://dos.cl"))]
    evaluacion = evaluar_nombre_obra(candidatos=candidatos, obra_documental="CONSTRUCTORA ALFA")
    assert evaluacion["estado"] == "ABSTENCION"


def test_dos_nombres_sustancialmente_distintos_abstienen():
    candidatos = _candidatos([
        _r("https://uno.cl/a", "Constructora Alfa Beta Gamma Limitada"),
        _r("https://dos.cl/a", "Constructora Alfa Beta Gamma Limitada"),
        _r("https://tres.cl/a", "Constructora Alfa Beta Delta Limitada"),
        _r("https://cuatro.cl/a", "Constructora Alfa Beta Delta Limitada"),
    ], "CONSTRUCTORA ALFA BETA")
    evaluacion = evaluar_nombre_obra(candidatos=candidatos, obra_documental="CONSTRUCTORA ALFA BETA")
    assert evaluacion["estado"] == "ABSTENCION" and evaluacion["propuesta"] is None


def test_una_sola_fuente_abstiene():
    candidatos = _candidatos([_r("https://uno.cl/a", "Constructora Alfa Beta Gamma Limitada"),
                              _r("https://uno.cl/b", content="CONSTRUCTORA ALFA BETA GAMMA LIMITADA")],
                             "CONSTRUCTORA ALFA BETA")
    evaluacion = evaluar_nombre_obra(candidatos=candidatos, obra_documental="CONSTRUCTORA ALFA BETA")
    assert evaluacion["estado"] == "ABSTENCION" and evaluacion["propuesta"] is None


def test_titulo_truncado_sin_recuperacion_se_descarta():
    assert _candidatos([
        _r("https://uno.cl/a", "Empresa Constructora Bravo E Izquierdo Lt…", "Perfil de empresa en Santiago."),
        _r("https://dos.cl/a", "Empresa Constructora Bravo E Izquierdo Limitada…", ""),
        _r("https://tres.cl/a", "", "EMPRESA CONSTRUCTORA BRAVO E IZQUIERDO LIMITADA... ver más"),
    ]) == []


def test_ruido_constructora_bravo_spa_no_es_compatible():
    ruido = [r for r in RESULTADOS_REALES if "BRAVO SPA" in (r["title"] + r["content"]).upper()]
    assert ruido and _candidatos(ruido) == []


def test_rut_con_digito_verificador_invalido_no_se_extrae():
    candidatos = _candidatos([_r("https://uno.cl/a", content="RUT 84.102.200-1 EMPRESA CONSTRUCTORA BRAVO E IZQUIERDO LIMITADA")])
    assert [c.rut for c in candidatos] == [""]


def test_consulta_usa_solo_datos_documentales():
    consulta = construir_consulta_tavily(OBRA, DESTINO, "LO BARNECHEA")
    assert consulta == f"{OBRA} {DESTINO}"
    assert "IZQUIERDO" not in consulta and "LIMITADA" not in consulta


# ------------------------------------------------------------- disponibilidad y credencial

def test_sin_credencial_es_busqueda_no_disponible_y_no_llama():
    llamadas = []
    resultado = buscar_adaptativamente_tavily(
        buscador=BuscadorWebTavily(api_key="", transporte=lambda *a: llamadas.append(a)),
        entidad=OBRA, direccion=DESTINO, localidad="LO BARNECHEA")
    assert llamadas == [] and resultado.candidatos == []
    assert resultado.traza[0]["error"].startswith("CredencialBuscadorWebAusente")


def test_fallo_http_es_busqueda_no_disponible_sin_exponer_clave():
    def falla(solicitud, timeout):
        raise HTTPError(solicitud.full_url, 432, "limit", {}, None)
    resultado = buscar_adaptativamente_tavily(buscador=BuscadorWebTavily(api_key=CLAVE, transporte=falla),
                                              entidad=OBRA, direccion=DESTINO, localidad="LO BARNECHEA")
    assert resultado.traza[0]["error"] == "BuscadorWebNoDisponible: Tavily devolvió HTTP 432."
    assert CLAVE not in json.dumps(resultado.traza)


def test_clave_solo_viaja_en_cabecera_nunca_en_cuerpo_cache_ni_traza(tmp_path):
    capturas = []
    repositorio = RepositorioCacheBusquedaWeb(tmp_path / "cache.json")
    buscador = BuscadorWebConCache(BuscadorWebTavily(api_key=CLAVE, transporte=_transporte(RESULTADOS_REALES, capturas)),
                                   repositorio)
    assert buscador.nombre == "tavily"
    resultado = buscar_adaptativamente_tavily(buscador=buscador, entidad=OBRA, direccion=DESTINO, localidad="LO BARNECHEA")
    assert capturas[0].get_header("Authorization") == f"Bearer {CLAVE}"
    assert CLAVE not in capturas[0].data.decode()
    assert CLAVE not in (tmp_path / "cache.json").read_text(encoding="utf-8")
    assert CLAVE not in json.dumps(resultado.traza, ensure_ascii=False)
    # Segunda vez desde caché: sin nueva llamada.
    buscar_adaptativamente_tavily(buscador=buscador, entidad=OBRA, direccion=DESTINO, localidad="LO BARNECHEA")
    assert len(capturas) == 1


# ------------------------------------------------------------- investigación completa

@pytest.fixture
def raiz(tmp_path, monkeypatch):
    actual = tmp_path / "operacion" / "actual"
    actual.mkdir(parents=True)
    with (actual / "analisis_completo_guias.csv").open("w", encoding="utf-8-sig", newline="") as flujo:
        escritor = csv.DictWriter(flujo, fieldnames=["numero_guia", "numero_transporte", "archivo",
            "motivos_revision_documento", "despachar_a_crudo", "obra_destino", "cliente",
            "metodos_recuperacion_documento"], delimiter=";")
        escritor.writeheader()
        escritor.writerow({"numero_guia": "474993", "numero_transporte": "2", "archivo": "prueba.jpg",
            "motivos_revision_documento": "", "despachar_a_crudo": DESTINO, "obra_destino": OBRA,
            "cliente": "CLIENTE", "metodos_recuperacion_documento": "GEOMETRICO"})
    (tmp_path / "catalogos_privados").mkdir()
    (tmp_path / "catalogos_privados" / "obras_destinos.json").write_text("{}", encoding="utf-8")
    (actual / "decisiones_aplicadas.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv(VARIABLE_ENTORNO, str(tmp_path))
    for nombre in ("TAVILY_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(nombre, raising=False)
    monkeypatch.setattr(credenciales, "_leer_entorno_usuario_windows", lambda nombre: "")
    monkeypatch.setattr(investigacion_revision, "_lectura_original",
        lambda *a, **k: {"ruta": "original.jpg", "sha256": "abc", "lineas": [], "destino_geometrico": DESTINO,
                         "fuente": "test", "error": ""})
    return tmp_path


class _B1:
    def resolver(self, contexto):
        return SimpleNamespace(contexto_final=contexto, hipotesis=None, estado="ABSTENCION_IA",
                               validacion=None, a_dict=lambda: {"estado": "ABSTENCION_IA"})


def _obra(resultado):
    return next(e for e in resultado["expedientes"] if e["CAMPO"] == "obra_destino")


def test_investigacion_usa_tavily_con_credencial_sin_openrouter(raiz, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", CLAVE)
    class Respuesta:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return json.dumps({"results": RESULTADOS_REALES}).encode()

    monkeypatch.setattr(buscador_web, "urlopen", lambda solicitud, timeout: Respuesta())
    resultado = investigacion_revision.investigar_revision(
        "474993", raiz_atlas=raiz, orquestador=_B1(), campos_solicitados=("obra_destino",), permitir_ocr_nuevo=False)
    assert resultado["BUSQUEDA_EXTERNA"] == {"estado": "EJECUTADA", "proveedor": "tavily", "motivo": ""}
    assert _obra(resultado)["PROPUESTA"] == ESPERADO
    assert CLAVE not in json.dumps(resultado, ensure_ascii=False, default=str)
    assert (raiz / "cache" / "busqueda_web" / "busqueda_web_tavily_cache.json").exists()


def test_investigacion_sin_credenciales_marca_busqueda_no_disponible(raiz):
    resultado = investigacion_revision.investigar_revision(
        "474993", raiz_atlas=raiz, orquestador=_B1(), campos_solicitados=("obra_destino",), permitir_ocr_nuevo=False)
    obra = _obra(resultado)
    assert resultado["BUSQUEDA_EXTERNA"]["estado"] == "NO_DISPONIBLE"
    assert obra["EVALUACION_CANDIDATOS_EXTERNOS"]["estado"] == "BUSQUEDA_NO_DISPONIBLE"
    assert "Falta corroboración" not in obra["RAZON_ABSTENCION"]
    assert "Búsqueda externa no disponible" in obra["RAZON_ABSTENCION"]


def test_investigacion_fallo_http_tavily_no_es_evidencia_insuficiente(raiz):
    def falla(solicitud, timeout):
        raise HTTPError(solicitud.full_url, 500, "error", {}, None)
    buscador = BuscadorWebConCache(BuscadorWebTavily(api_key=CLAVE, transporte=falla),
                                   RepositorioCacheBusquedaWeb(raiz / "cache.json"))
    resultado = investigacion_revision.investigar_revision(
        "474993", raiz_atlas=raiz, orquestador=_B1(), buscador_externo=buscador,
        campos_solicitados=("obra_destino",), permitir_ocr_nuevo=False)
    obra = _obra(resultado)
    assert resultado["BUSQUEDA_EXTERNA"] == {"estado": "FALLIDA", "proveedor": "tavily",
                                             "motivo": "BuscadorWebNoDisponible: Tavily devolvió HTTP 500."}
    assert obra["EVALUACION_CANDIDATOS_EXTERNOS"]["razon"] == (
        "Búsqueda externa no disponible: BuscadorWebNoDisponible: Tavily devolvió HTTP 500.")
    assert "Falta corroboración" not in obra["RAZON_ABSTENCION"]
    assert CLAVE not in json.dumps(resultado, ensure_ascii=False, default=str)
