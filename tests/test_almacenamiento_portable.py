"""INFRAESTRUCTURA S2.1 -- resolución centralizada de la raíz portable."""

from __future__ import annotations

import time

import pytest

from atlas_core.almacenamiento_portable import (
    FALLBACK_LOCAL,
    SesionOcupadaError,
    autodetectar_raiz_drive,
    bloqueo_sesion,
    escribir_estado_operacion,
    escribir_json_atomico,
    leer_estado_operacion,
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


# --- INFRAESTRUCTURA S2.2: manifiesto portable de operación vigente ---
# (contrato compartido con Atlas Desktop -- ver src/estado_operacion.js)

def test_leer_estado_operacion_sin_manifiesto_es_caso_valido(tmp_path):
    assert leer_estado_operacion(raiz=tmp_path) is None


def test_escribir_y_releer_estado_operacion_redondea_bien(tmp_path):
    raiz = tmp_path
    (raiz / "reportes" / "actual").mkdir(parents=True)
    (raiz / "operacion" / "procesamiento").mkdir(parents=True)
    dataset = raiz / "operacion" / "procesamiento" / "analisis_completo_guias.csv"
    dataset.write_text("archivo\n", encoding="utf-8")

    ruta_manifiesto = escribir_estado_operacion(
        reporte_vigente=raiz / "reportes" / "actual",
        dataset_operacional=dataset,
        origen="oficina",
        raiz=raiz,
    )
    assert ruta_manifiesto == raiz / "operacion" / "actual" / "estado_operacion.json"

    leido = leer_estado_operacion(raiz=raiz)
    assert leido["schema_version"] == 1
    assert leido["reporte_vigente"] == "reportes/actual"
    assert leido["dataset_operacional"] == "operacion/procesamiento/analisis_completo_guias.csv"
    assert leido["origen"] == "oficina"
    assert leido["fecha_actualizacion"]


def test_escribir_estado_operacion_fuera_de_raiz_no_escribe_nada(tmp_path):
    raiz = tmp_path / "Atlas"
    raiz.mkdir()
    fuera = tmp_path / "fuera_de_atlas"
    fuera.mkdir()
    resultado = escribir_estado_operacion(reporte_vigente=fuera, raiz=raiz)
    assert resultado is None
    assert not (raiz / "operacion" / "actual" / "estado_operacion.json").exists()


def test_escribir_estado_operacion_dataset_fuera_de_raiz_aborta_todo_el_manifiesto(tmp_path):
    raiz = tmp_path / "Atlas"
    (raiz / "reportes" / "actual").mkdir(parents=True)
    dataset_fuera = tmp_path / "fuera.csv"
    dataset_fuera.write_text("x", encoding="utf-8")
    resultado = escribir_estado_operacion(
        reporte_vigente=raiz / "reportes" / "actual", dataset_operacional=dataset_fuera, raiz=raiz,
    )
    assert resultado is None
    assert not (raiz / "operacion" / "actual" / "estado_operacion.json").exists()


def test_escribir_estado_operacion_sin_dataset_es_valido(tmp_path):
    raiz = tmp_path
    (raiz / "reportes" / "actual").mkdir(parents=True)
    escribir_estado_operacion(reporte_vigente=raiz / "reportes" / "actual", raiz=raiz)
    leido = leer_estado_operacion(raiz=raiz)
    assert leido["dataset_operacional"] is None


def test_leer_estado_operacion_manifiesto_corrupto_se_abstiene(tmp_path):
    ruta_manifiesto = tmp_path / "operacion" / "actual" / "estado_operacion.json"
    ruta_manifiesto.parent.mkdir(parents=True)
    ruta_manifiesto.write_text("{ esto no es json valido", encoding="utf-8")
    assert leer_estado_operacion(raiz=tmp_path) is None


def test_leer_estado_operacion_schema_no_soportada_se_abstiene(tmp_path):
    ruta_manifiesto = tmp_path / "operacion" / "actual" / "estado_operacion.json"
    ruta_manifiesto.parent.mkdir(parents=True)
    ruta_manifiesto.write_text('{"schema_version": 99, "reporte_vigente": "reportes/actual"}', encoding="utf-8")
    assert leer_estado_operacion(raiz=tmp_path) is None


def test_escribir_estado_operacion_es_atomico_nunca_deja_manifiesto_truncado(tmp_path, monkeypatch):
    raiz = tmp_path
    (raiz / "reportes" / "actual").mkdir(parents=True)
    escribir_estado_operacion(reporte_vigente=raiz / "reportes" / "actual", raiz=raiz, origen="v1")

    def _dump_falla(*_args, **_kwargs):
        raise OSError("disco lleno simulado")

    monkeypatch.setattr("atlas_core.almacenamiento_portable.json.dump", _dump_falla)
    with pytest.raises(OSError):
        escribir_estado_operacion(reporte_vigente=raiz / "reportes" / "actual", raiz=raiz, origen="v2")

    leido = leer_estado_operacion(raiz=raiz)
    assert leido["origen"] == "v1"  # el manifiesto anterior sigue intacto, no quedo truncado
