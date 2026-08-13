"""INFRAESTRUCTURA S2.1 -- resolución centralizada de la raíz portable."""

from __future__ import annotations

import time

import pytest

from atlas_core.almacenamiento_portable import (
    FALLBACK_LOCAL,
    SesionOcupadaError,
    autodetectar_raiz_drive,
    bloqueo_sesion,
    escribir_json_atomico,
    resolver_raiz_atlas,
    ruta_cache,
    ruta_catalogos_privados,
    ruta_coordinacion,
    ruta_datos_privados,
    ruta_operacion,
    ruta_reportes,
    ruta_respaldos,
)


def test_override_explicito_tiene_prioridad_maxima(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path / "desde_env"))
    assert resolver_raiz_atlas(tmp_path / "override") == tmp_path / "override"


def test_variable_entorno_tiene_prioridad_sobre_autodeteccion(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path / "desde_env"))
    monkeypatch.setattr(
        "atlas_core.almacenamiento_portable.autodetectar_raiz_drive",
        lambda: tmp_path / "nunca_deberia_usarse",
    )
    assert resolver_raiz_atlas() == tmp_path / "desde_env"


def test_autodeteccion_se_usa_si_no_hay_env_ni_override(tmp_path, monkeypatch):
    monkeypatch.delenv("ATLAS_DATA_DIR", raising=False)
    monkeypatch.setattr(
        "atlas_core.almacenamiento_portable.autodetectar_raiz_drive",
        lambda: tmp_path / "drive_simulado" / "Atlas",
    )
    assert resolver_raiz_atlas() == tmp_path / "drive_simulado" / "Atlas"


def test_fallback_local_controlado_si_nada_mas_aplica(monkeypatch):
    monkeypatch.delenv("ATLAS_DATA_DIR", raising=False)
    monkeypatch.setattr(
        "atlas_core.almacenamiento_portable.autodetectar_raiz_drive", lambda: None
    )
    assert resolver_raiz_atlas() == FALLBACK_LOCAL


def test_resolucion_no_depende_del_usuario_de_windows(tmp_path, monkeypatch):
    # Simula "casa" (usuario Jjjc0508, letra G:) y "oficina" (usuario
    # corte, letra distinta) resolviendo a la MISMA estructura relativa
    # sin que el código conozca ninguno de los dos nombres de usuario.
    raiz_casa = tmp_path / "casa" / "Atlas"
    raiz_oficina = tmp_path / "oficina_otra_letra" / "Atlas"
    monkeypatch.setenv("ATLAS_DATA_DIR", str(raiz_casa))
    assert ruta_catalogos_privados().name == "catalogos_privados"
    assert ruta_catalogos_privados() == raiz_casa / "catalogos_privados"
    monkeypatch.setenv("ATLAS_DATA_DIR", str(raiz_oficina))
    assert ruta_catalogos_privados() == raiz_oficina / "catalogos_privados"


def test_autodetectar_raiz_drive_real_no_encuentra_nada_en_sandbox():
    # La función real (sin mockear) no debe reventar ni encontrar nada
    # "inventado" en un entorno de pruebas -- o encuentra una carpeta
    # Atlas que realmente existe en el filesystem, o devuelve None.
    resultado = autodetectar_raiz_drive()
    assert resultado is None or resultado.is_dir()


def test_subcarpetas_derivan_todas_de_la_misma_raiz(tmp_path):
    raiz = tmp_path / "Atlas"
    assert ruta_operacion(raiz=raiz) == raiz / "operacion"
    assert ruta_operacion("actual", raiz=raiz) == raiz / "operacion" / "actual"
    assert ruta_catalogos_privados(raiz=raiz) == raiz / "catalogos_privados"
    assert ruta_cache("rutas", raiz=raiz) == raiz / "cache" / "rutas"
    assert ruta_reportes(raiz=raiz) == raiz / "reportes" / "actual"
    assert ruta_reportes("historicos", raiz=raiz) == raiz / "reportes" / "historicos"
    assert ruta_respaldos(raiz=raiz) == raiz / "respaldos"
    assert ruta_datos_privados(raiz=raiz) == raiz / "datos_privados"
    assert ruta_coordinacion(raiz=raiz) == raiz / "coordinacion"


def test_escritura_atomica_no_deja_archivo_parcial_si_falla_a_mitad(tmp_path, monkeypatch):
    destino = tmp_path / "estado.json"
    escribir_json_atomico(destino, {"version": 1})
    assert destino.read_text(encoding="utf-8").strip().endswith("}")

    def _dump_falla(*_args, **_kwargs):
        raise OSError("disco lleno simulado")

    monkeypatch.setattr("atlas_core.almacenamiento_portable.json.dump", _dump_falla)
    with pytest.raises(OSError):
        escribir_json_atomico(destino, {"version": 2})
    # El archivo original permanece intacto -- nunca queda truncado ni a medio escribir.
    assert destino.read_text(encoding="utf-8").strip().endswith('"version": 1\n}')
    sobrantes = [p for p in tmp_path.iterdir() if p.name.startswith(".estado.json.")]
    assert sobrantes == []


def test_bloqueo_sesion_impide_escritura_concurrente_del_mismo_nombre(tmp_path):
    with bloqueo_sesion(tmp_path, "operacion"):
        with pytest.raises(SesionOcupadaError):
            with bloqueo_sesion(tmp_path, "operacion"):
                pass
    # Liberado al salir del `with` -- una segunda sesión ya puede entrar.
    with bloqueo_sesion(tmp_path, "operacion"):
        pass


def test_bloqueo_sesion_no_bloquea_nombres_distintos(tmp_path):
    with bloqueo_sesion(tmp_path, "geocodificacion"):
        with bloqueo_sesion(tmp_path, "operacion"):
            pass


def test_bloqueo_huerfano_se_reemplaza_tras_expirar(tmp_path):
    with bloqueo_sesion(tmp_path, "operacion", tiempo_expiracion_segundos=0.01):
        pass
    ruta_lock = tmp_path / ".atlas_lock_operacion"
    ruta_lock.write_text("{}", encoding="utf-8")
    tiempo_pasado = time.time() - 10
    import os as _os

    _os.utime(ruta_lock, (tiempo_pasado, tiempo_pasado))
    with bloqueo_sesion(tmp_path, "operacion", tiempo_expiracion_segundos=0.01):
        pass
