from atlas_core.atlas_ia import proveedor_groq


def test_credencial_explicita_tiene_prioridad(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "entorno")
    assert proveedor_groq.resolver_groq_api_key("explicita") == "explicita"


def test_credencial_de_entorno_es_configurable(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "entorno")
    assert proveedor_groq.resolver_groq_api_key() == "entorno"
