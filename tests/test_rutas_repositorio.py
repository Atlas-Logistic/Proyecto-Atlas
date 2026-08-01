from dataclasses import replace
from datetime import datetime, timezone

import pytest

import atlas_core.rutas.repositorio as modulo
from atlas_core.rutas.modelos import EstadoRuta, RegistroRuta
from atlas_core.rutas.repositorio import (
    CatalogoRutasCorruptoError, RepositorioRutas, RutaDuplicadaError,
)


FECHA = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()


def registro(**cambios):
    datos = dict(
        ruta_id="RUTA-DEMO-1", planta_id="PLANTA-DEMO", destino_id="DESTINO-DEMO",
        perfil_ruta="driving-car", proveedor="simulado", version_proveedor="1",
        distancia_km=12.5, duracion_estimada_min=24.0,
        longitud_origen=-20.0, latitud_origen=-10.0,
        longitud_destino=-20.1, latitud_destino=-10.1,
        direccion_origen_normalizada="ORIGEN DEMO",
        direccion_destino_normalizada="DESTINO DEMO",
        huella_direccion_origen="HUELLA-ORIGEN-1",
        huella_direccion_destino="HUELLA-DESTINO-1",
        estado=EstadoRuta.RUTA_CALCULADA.value, motivo="PRUEBA_SINTETICA",
        vigente=True, fecha_calculo=FECHA, fecha_creacion=FECHA, fecha_modificacion=FECHA,
    )
    datos.update(cambios)
    return RegistroRuta(**datos)


def test_archivo_inexistente_no_se_crea(tmp_path):
    repo = RepositorioRutas(tmp_path / "rutas.json")
    assert repo.listar() == []
    assert not repo.ruta.exists()


@pytest.mark.parametrize("contenido", ["{", "[]", '{"version_formato": 2, "rutas": []}'])
def test_archivo_corrupto_se_detecta(tmp_path, contenido):
    ruta = tmp_path / "rutas.json"
    ruta.write_text(contenido, encoding="utf-8")
    with pytest.raises(CatalogoRutasCorruptoError):
        RepositorioRutas(ruta).listar()


def test_guardado_atomico_y_lectura(tmp_path, monkeypatch):
    repo = RepositorioRutas(tmp_path / "privado" / "rutas.json")
    reemplazos = []
    real = modulo.os.replace
    def observar(origen, destino):
        reemplazos.append((origen, destino)); real(origen, destino)
    monkeypatch.setattr(modulo.os, "replace", observar)
    guardada = repo.guardar(registro())
    assert repo.listar() == [guardada]
    assert len(reemplazos) == 1


def test_fallo_atomico_conserva_archivo(tmp_path, monkeypatch):
    repo = RepositorioRutas(tmp_path / "rutas.json")
    repo.guardar(registro())
    original = repo.ruta.read_bytes()
    monkeypatch.setattr(modulo.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("fallo sintético")))
    with pytest.raises(OSError):
        repo.guardar(registro(ruta_id="RUTA-DEMO-2", huella_direccion_origen="OTRA"))
    assert repo.ruta.read_bytes() == original


def test_clave_logica_y_huellas_duplicadas_se_rechazan(tmp_path):
    repo = RepositorioRutas(tmp_path / "rutas.json")
    repo.guardar(registro())
    with pytest.raises(RutaDuplicadaError):
        repo.guardar(registro(ruta_id="RUTA-DEMO-2"))


def test_cambio_direccion_invalida_cache_y_conserva_historial(tmp_path):
    repo = RepositorioRutas(tmp_path / "rutas.json")
    primera = repo.guardar(registro())
    segunda = repo.guardar(registro(
        ruta_id="RUTA-DEMO-2", huella_direccion_destino="HUELLA-DESTINO-2",
        direccion_destino_normalizada="DESTINO DEMO CAMBIADO",
    ))
    rutas = repo.listar()
    assert len(rutas) == 2
    assert rutas[0].vigente is False
    assert rutas[1] == segunda
    assert repo.buscar_vigente(primera.clave_logica, "HUELLA-ORIGEN-1", "HUELLA-DESTINO-1") is None
