"""El Python que Desktop lanza para B1 puede no heredar OPENROUTER_API_KEY.

Mismo patrón que GROQ_API_KEY: entorno del proceso primero; en Windows,
fallback de sólo lectura a HKCU\\Environment (aquí simulado)."""
import csv
import io
import json
from types import SimpleNamespace

import b1_operador_cli
from atlas_core.almacenamiento_portable import VARIABLE_ENTORNO
from atlas_core.atlas_ia import buscador_web, candidatos_externos, credenciales, investigacion_revision
from atlas_core.atlas_ia.proveedor_groq import resolver_groq_api_key


def _registro_usuario(monkeypatch, valores: dict[str, str]) -> None:
    monkeypatch.setattr(credenciales, "_leer_entorno_usuario_windows", lambda nombre: valores.get(nombre, ""))


def test_entorno_del_proceso_tiene_prioridad_sobre_registro(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", " entorno ")
    _registro_usuario(monkeypatch, {"OPENROUTER_API_KEY": "registro"})
    assert credenciales.resolver_openrouter_api_key() == "entorno"
    assert credenciales.resolver_openrouter_api_key("explicita") == "explicita"


def test_sin_entorno_usa_registro_de_usuario(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    _registro_usuario(monkeypatch, {"OPENROUTER_API_KEY": "or-hkcu", "GROQ_API_KEY": "groq-hkcu"})
    assert credenciales.resolver_openrouter_api_key() == "or-hkcu"
    assert resolver_groq_api_key() == "groq-hkcu"
    assert buscador_web.BuscadorWebOpenRouter()._api_key == "or-hkcu"


def test_sin_entorno_ni_registro_queda_vacia(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    _registro_usuario(monkeypatch, {})
    assert credenciales.resolver_openrouter_api_key() == ""


def test_herramienta_verificacion_externa_se_registra_con_clave_de_registro(monkeypatch):
    from atlas_core.procesamiento_masivo import _herramientas_b1_disponibles

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    _registro_usuario(monkeypatch, {"OPENROUTER_API_KEY": "or-hkcu"})
    assert "VERIFICACION_EXTERNA" in _herramientas_b1_disponibles()


def _raiz(tmp_path):
    actual = tmp_path / "operacion" / "actual"
    actual.mkdir(parents=True)
    with (actual / "analisis_completo_guias.csv").open("w", encoding="utf-8-sig", newline="") as flujo:
        escritor = csv.DictWriter(flujo, fieldnames=["numero_guia", "numero_transporte", "archivo",
            "motivos_revision_documento", "despachar_a_crudo", "obra_destino", "cliente",
            "metodos_recuperacion_documento"], delimiter=";")
        escritor.writeheader()
        escritor.writerow({"numero_guia": "474993", "numero_transporte": "2", "archivo": "prueba.jpg",
            "motivos_revision_documento": "DESTINO_CONTAMINADO_POR_OTRA_SECCION",
            "despachar_a_crudo": "CALLE REAL 1", "obra_destino": "OBRA PARCIAL", "cliente": "CLIENTE",
            "metodos_recuperacion_documento": "GEOMETRICO"})
    (tmp_path / "catalogos_privados").mkdir()
    (tmp_path / "catalogos_privados" / "obras_destinos.json").write_text("{}", encoding="utf-8")
    (actual / "decisiones_aplicadas.json").write_text("{}", encoding="utf-8")


def test_ruta_desktop_cli_instancia_buscador_y_ejecuta_busqueda_adaptativa(tmp_path, monkeypatch):
    _raiz(tmp_path)
    monkeypatch.setenv(VARIABLE_ENTORNO, str(tmp_path))  # caché de búsqueda dentro de tmp
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)  # como el hijo de Electron
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)  # este test cubre la ruta OpenRouter
    _registro_usuario(monkeypatch, {"OPENROUTER_API_KEY": "or-hkcu"})
    monkeypatch.setattr(investigacion_revision, "_lectura_original",
        lambda *args, **kwargs: {"ruta": "original.jpg", "sha256": "abc", "lineas": ["DESPACHAR A", "CALLE REAL 1"],
                                 "destino_geometrico": "CALLE REAL 1", "fuente": "test", "error": ""})

    class B1:
        def resolver(self, contexto):
            return SimpleNamespace(contexto_final=contexto, hipotesis=None, estado="ABSTENCION_IA",
                validacion=None, a_dict=lambda: {"estado": "ABSTENCION_IA"})

    monkeypatch.setattr("atlas_core.procesamiento_masivo._crear_orquestador_ia_configurado", lambda **_: B1())
    monkeypatch.setattr(candidatos_externos, "obtener_texto_fuente", lambda url: "")

    instancias = []
    original_cache = buscador_web.BuscadorWebConCache

    class CacheEspia(original_cache):
        def __init__(self, interno, repositorio):
            instancias.append(interno)
            super().__init__(interno, repositorio)

    monkeypatch.setattr(buscador_web, "BuscadorWebConCache", CacheEspia)

    adaptativas = []
    original_adaptativa = candidatos_externos.buscar_adaptativamente

    def adaptativa_espia(**kwargs):
        resultado = original_adaptativa(**kwargs)
        adaptativas.append(resultado)
        return resultado

    monkeypatch.setattr(candidatos_externos, "buscar_adaptativamente", adaptativa_espia)

    autorizaciones = []
    candidato = {"nombre": "OBRA PARCIAL COMPLETA", "direccion": "CALLE REAL", "numero": "1",
                 "comuna": "SANTIAGO", "url": "https://fuente.example/obra"}

    class RespuestaHTTP:
        status = 200

        def __init__(self, cuerpo):
            self._cuerpo = cuerpo

        def read(self):
            return self._cuerpo

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def urlopen_falso(solicitud, timeout):
        autorizaciones.append(solicitud.get_header("Authorization"))
        return RespuestaHTTP(json.dumps({"model": "perplexity/sonar", "choices": [{"message": {
            "content": json.dumps({"candidatos": [candidato]}),
            "annotations": [{"type": "url_citation", "url_citation": {"url": candidato["url"], "title": "t"}}],
        }}]}).encode())

    monkeypatch.setattr(buscador_web, "urlopen", urlopen_falso)

    salida = io.StringIO()
    monkeypatch.setattr("sys.stdout", salida)
    codigo = b1_operador_cli.main(["--raiz-atlas", str(tmp_path), "--conversacion", "c1",
                                   "--texto", "Investiga la obra de la guía 474993"])
    respuesta = json.loads(salida.getvalue())

    assert codigo == 0
    assert respuesta["estado"] == "RESULTADO_INVESTIGACION"
    assert len(instancias) == 1 and instancias[0]._api_key == "or-hkcu"
    assert len(adaptativas) == 1 and len(adaptativas[0].candidatos) > 0
    assert autorizaciones and set(autorizaciones) == {"Bearer or-hkcu"}
