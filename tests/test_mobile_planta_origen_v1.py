"""Bloque MOBILE V1 -- selector de planta de origen (COLINA/RENCA) en la
app del chofer. Cubre el lado Core del contrato: `RepositorioEnviosMobile.
recibir` exige `planta_origen_informada` (mismo criterio ya vigente para
tipo_novedad -- Core nunca confía sólo en la validación del cliente), la
persiste tal cual en el envío (trazabilidad -- Sección 8 del bloque:
planta informada + timestamp + chofer_id, sin mezclarla con la planta
operacional final), y NUNCA la usa para decidir `planta_origen_id`/
`planta_origen_nombre` de la fila que termina en el dataset -- esos
siguen viniendo exclusivamente del pipeline determinista ya existente
(GPS/documento). "Mobile informa, nunca decide" (Sección 6)."""
from __future__ import annotations

from pathlib import Path

import pytest

from atlas_core.mobile import ErrorEnvioMobile, PLANTAS_ORIGEN_MOBILE, RepositorioEnviosMobile


def _repo(tmp_path: Path) -> RepositorioEnviosMobile:
    return RepositorioEnviosMobile(tmp_path)


def _metadata(**cambios):
    base = {
        "chofer_id": "chofer-1", "tipo_novedad": "", "guia_firmada_correo": False,
        "planta_origen_informada": "AZA_COLINA",
    }
    base.update(cambios)
    return base


def test_exige_planta_origen_informada_igual_que_tipo_novedad(tmp_path: Path) -> None:
    metadata = _metadata()
    del metadata["planta_origen_informada"]
    with pytest.raises(ErrorEnvioMobile):
        _repo(tmp_path).recibir(envio_id="envio-planta-1234", imagen=b"foto", mime="image/jpeg", metadata=metadata)


def test_rechaza_un_valor_que_no_sea_uno_de_los_dos_ids_canonicos(tmp_path: Path) -> None:
    with pytest.raises(ErrorEnvioMobile):
        _repo(tmp_path).recibir(
            envio_id="envio-planta-1235", imagen=b"foto", mime="image/jpeg",
            metadata=_metadata(planta_origen_informada="COLINA"),  # texto libre, no el ID canónico
        )


@pytest.mark.parametrize("valor", PLANTAS_ORIGEN_MOBILE)
def test_acepta_los_dos_ids_canonicos(tmp_path: Path, valor: str) -> None:
    registro, nuevo = _repo(tmp_path).recibir(
        envio_id=f"envio-planta-{valor.lower()}", imagen=b"foto", mime="image/jpeg",
        metadata=_metadata(planta_origen_informada=valor),
    )
    assert nuevo is True
    assert registro["planta_origen_informada"] == valor


def test_trazabilidad_planta_informada_timestamp_chofer_id_en_el_mismo_registro(tmp_path: Path) -> None:
    """Sección 8: debe ser posible saber 'el chofer informó COLINA al
    enviar esta guía' -- los tres datos viven en el MISMO registro
    persistido (envio.json), nunca en un almacén paralelo."""
    registro, _ = _repo(tmp_path).recibir(
        envio_id="envio-planta-trazabilidad", imagen=b"foto", mime="image/jpeg",
        metadata=_metadata(planta_origen_informada="AZA_RENCA"),
    )
    assert registro["planta_origen_informada"] == "AZA_RENCA"
    assert registro["chofer_id"] == "chofer-1"
    assert registro["recibido_en"]  # timestamp real, no vacío


def test_reintento_con_el_mismo_envio_id_conserva_la_misma_planta(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    primero, nuevo1 = repo.recibir(
        envio_id="envio-planta-reintento", imagen=b"foto", mime="image/jpeg",
        metadata=_metadata(planta_origen_informada="AZA_RENCA"),
    )
    segundo, nuevo2 = repo.recibir(
        envio_id="envio-planta-reintento", imagen=b"foto", mime="image/jpeg",
        metadata=_metadata(planta_origen_informada="AZA_RENCA"),
    )
    assert nuevo1 is True and nuevo2 is False  # idempotente -- el reintento no crea un segundo envío
    assert primero["planta_origen_informada"] == segundo["planta_origen_informada"] == "AZA_RENCA"


def test_planta_informada_nunca_se_mezcla_en_datos_del_documento(tmp_path: Path) -> None:
    """Sección 6/8: evidencia informada por el chofer, NUNCA verdad
    absoluta -- `procesar_envio_mobile` arma la fila del dataset
    exclusivamente desde `datos` (salida de `procesar_archivo`, el
    pipeline determinista GPS/documento); `planta_origen_informada`
    vive sólo en el envío (registro), nunca se mezcla en `datos` ni
    puede sobrescribir `planta_origen_id`/`planta_origen_nombre`."""
    import inspect

    from atlas_core.mobile import procesar_envio_mobile

    codigo = inspect.getsource(procesar_envio_mobile)
    # La construcción de la fila del CSV usa únicamente `datos` -- nunca
    # `registro`/metadata (donde vive planta_origen_informada).
    indice_fila = codigo.index('fila = {columna: str(datos.get(columna, "")) for columna in COLUMNAS}')
    assert "registro.get(\"planta_origen_informada\"" not in codigo[:indice_fila + 200]
    assert "planta_origen_informada" not in codigo[indice_fila:indice_fila + 400]
