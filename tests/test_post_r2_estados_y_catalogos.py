import csv
from types import SimpleNamespace

from atlas_core.catalogo_fichas import construir_ficha_vehiculo
from atlas_core.gestor_viajes import EstadoViaje, agrupar_viajes
from atlas_core.procesamiento_masivo import COLUMNAS


def _fila(**cambios):
    fila = {
        "archivo": "1.jpeg", "numero_guia": "1", "numero_transporte": "100",
        "fecha": "31-08-2026", "indicador_revision": "OK",
        "estado_operacional": "OK", "estado_ruta": "RUTA_CALCULADA",
    }
    fila.update(cambios)
    return fila


def _vehiculo(*, calidad):
    return SimpleNamespace(
        vehiculo_id="v1", patente_canonica="AL1879", tipo="TRACTO",
        estado_calidad=calidad, estado_vigencia="ACTIVO", aliases=(),
        procedencia="CATALOGO_LEGACY", confirmado_por="",
    )


def test_catalogo_confirmado_sin_viajes_sigue_confirmado():
    vehiculo = _vehiculo(calidad="CONFIRMADO")
    ficha = construir_ficha_vehiculo(
        vehiculo=vehiculo, filas=[], vehiculos_por_patente={"AL1879": vehiculo},
    )
    assert ficha["guias_relacionadas"] == []
    assert ficha["clasificacion_visual"] == "CONFIRMADO"


def test_catalogo_observado_sin_viajes_sigue_por_verificar():
    vehiculo = _vehiculo(calidad="OBSERVADO")
    ficha = construir_ficha_vehiculo(
        vehiculo=vehiculo, filas=[], vehiculos_por_patente={"AL1879": vehiculo},
    )
    assert ficha["clasificacion_visual"] == "OBSERVADO"


def test_fallo_tecnico_sin_decision_no_es_ok_ni_revision_humana():
    viajes, _ = agrupar_viajes([
        _fila(estado_operacional="REQUIERE_REVISION", estado_ruta="REQUIERE_REVISION",
              motivo_ruta="MULTIPLES_UBICACIONES_DISPERSAS(5)"),
    ], guias_revision_humana=set())
    assert viajes[0].estado == EstadoViaje.INCOMPLETO_TECNICO


def test_problema_humano_con_decision_es_revision():
    viajes, _ = agrupar_viajes([
        _fila(estado_operacional="REQUIERE_REVISION", estado_ruta="REQUIERE_REVISION",
              motivo_ruta="DESTINO_SIN_DATO"),
    ], guias_revision_humana={"1"})
    assert viajes[0].estado == EstadoViaje.REQUIERE_REVISION


def test_resuelto_es_confirmado():
    viajes, _ = agrupar_viajes([_fila()], guias_revision_humana=set())
    assert viajes[0].estado == EstadoViaje.CONFIRMADO


def test_motivo_destino_confirmado_se_reconcilia(tmp_path, monkeypatch):
    from atlas_core import revalidacion_documental as modulo

    class CatalogoFalso:
        def __init__(self, **_kwargs):
            pass

        def listar_destinos_confirmados_para_obra(self, *, nombre_obra):
            assert nombre_obra == "OBRA CONFIRMADA"
            return [SimpleNamespace(direccion="URUGUAY 15, LA CISTERNA")]

    monkeypatch.setattr(modulo, "CatalogoObrasDestinos", CatalogoFalso)
    fila = {c: "" for c in COLUMNAS}
    fila.update(_fila(
        numero_guia="464491", obra_destino="OBRA CONFIRMADA",
        despachar_a_crudo="URUGUAY 15 SANTIAGO LA CISTERNA",
        motivos_revision_documento="DESTINO_CONTAMINADO_POR_OTRA_SECCION",
        indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION",
        estado_operacional="REQUIERE_REVISION",
    ))
    ruta = tmp_path / "dataset.csv"
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerow(fila)

    resultado = modulo.revalidar_motivo_destino_ya_confirmado_sin_ocr(
        ruta_dataset=ruta, carpeta_catalogos=tmp_path,
    )
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        final = next(csv.DictReader(archivo, delimiter=";"))
    assert resultado["guias_actualizadas"] == ["464491"]
    assert final["motivos_revision_documento"] == ""
    assert final["indicador_revision"] == "OK"
    assert final["estado_operacional"] == "OK"
