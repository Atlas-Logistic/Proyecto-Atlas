import json

import pytest

from atlas_core.reset_operacional import reset_operacional_aislado


def test_reset_exige_marcador_y_preserva_conocimiento(tmp_path):
    (tmp_path / "operacion/actual").mkdir(parents=True)
    (tmp_path / "reportes/actual").mkdir(parents=True)
    (tmp_path / "catalogos_privados").mkdir()
    conocimiento = tmp_path / "catalogos_privados/vehiculos.json"
    conocimiento.write_text('{"vehiculos":[{"patente":"XF3629"}]}', encoding="utf-8")
    ledger = tmp_path / "operacion/actual/decisiones_aplicadas.json"
    ledger.write_text('{"decisiones":[1]}', encoding="utf-8")
    with pytest.raises(PermissionError):
        reset_operacional_aislado(tmp_path)
    (tmp_path / ".atlas_reset_aislado_autorizado").touch()
    assert reset_operacional_aislado(tmp_path) == {"documentos": 0, "viajes": 0, "revisiones": 0}
    assert "XF3629" in conocimiento.read_text(encoding="utf-8")
    assert json.loads(ledger.read_text(encoding="utf-8"))["decisiones"] == [1]
    assert len((tmp_path / "operacion/actual/analisis_completo_guias.csv").read_text(encoding="utf-8-sig").splitlines()) == 1
