from types import SimpleNamespace as NS

from atlas_core.fichas_choferes import asignaciones_de_chofer
from atlas_core.catalogo_fichas import construir_snapshot_fichas


def vehiculo(patente, tipo, eventos=(), calidad="CONFIRMADO", vigencia="ACTIVO"):
    return NS(patente_canonica=patente, tipo=tipo, estado_calidad=calidad, estado_vigencia=vigencia,
              evidencias=[NS(tipo=t, resultado=res, fecha=fecha, campos_observados={"rut_chofer_asociado": rut})
                          for t, res, fecha, rut in eventos])


def evento(rut="123456785", fecha="2026-01-01", tipo="CONFIRMACION_HUMANA", resultado="SOPORTA"):
    return tipo, resultado, fecha, rut


def test_rigido_vigente_solo_confirmacion_humana_y_traspaso():
    vs = [vehiculo("ZZ0001", "CAMION_RIGIDO", [evento(), evento("111111111", "2026-02-01")]),
          vehiculo("ZZ0002", "CAMION_RIGIDO", [evento(tipo="OCR")]),
          vehiculo("ZZ0003", "CAMION_RIGIDO", [evento()], vigencia="INACTIVO"),
          vehiculo("ZZ0004", "CAMION_RIGIDO", [evento()], calidad="CANDIDATO"),
          vehiculo("ZZ0005", "CAMION_RIGIDO", [evento(resultado="CONTRADICE")]),
          vehiculo("ZZ0006", "CAMION_RIGIDO")]
    assert asignaciones_de_chofer("123456785", vs)["camion_rigido"]["estado"] == "SIN_ASIGNACION"
    assert asignaciones_de_chofer("111111111", vs)["camion_rigido"] == {"estado": "CONFIRMADO", "patente": "ZZ0001", "candidatos": ["ZZ0001"]}
    assert asignaciones_de_chofer("", vs)["camion_rigido"]["estado"] == "SIN_ASIGNACION"


def test_conflicto_rigidos_y_coexistencia_no_alteran_otros_roles():
    vs = [vehiculo("ZZ0001", "TRACTO", [evento()]), vehiculo("ZZ0002", "CARRO", [evento()]),
          vehiculo("ZZ0003", "CAMION_RIGIDO", [evento()]), vehiculo("ZZ0004", "CAMION_RIGIDO", [evento()])]
    r = asignaciones_de_chofer("123456785", vs)
    assert r["tracto"]["patente"] == "ZZ0001"
    assert r["rampla"]["patente"] == "ZZ0002"
    assert r["camion_rigido"] == {"estado": "CONFLICTO", "patente": None, "candidatos": ["ZZ0003", "ZZ0004"]}
    r = asignaciones_de_chofer("123456785", vs[:-1])
    assert r["tracto"]["patente"] == "ZZ0001" and r["camion_rigido"]["patente"] == "ZZ0003"


def test_snapshot_catalogo_no_disponible_no_inventa_ausencia(tmp_path, monkeypatch):
    import atlas_core.catalogo_fichas as modulo
    monkeypatch.setattr(modulo, "_leer_filas_dataset", lambda raiz: [])
    monkeypatch.setattr(modulo, "_cargar_vehiculos_por_patente", lambda *a, **k: (_ for _ in ()).throw(OSError("no disponible")))
    monkeypatch.setattr(modulo, "cargar_catalogo_json", lambda ruta: {"123456785": {"nombre": "TEST", "activo": True}} if ruta.name == "choferes.json" else {})
    snap = construir_snapshot_fichas(raiz_atlas=tmp_path)
    ficha = snap["choferes"][0]
    for rol in ("tracto", "rampla", "camion_rigido"):
        assert ficha["asignaciones_vigentes"][rol] == {"estado": "NO_DISPONIBLE", "patente": None, "candidatos": []}

