"""Diagnóstico sintético de la custodia actual; no prueba un protocolo nuevo."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from atlas_core.estado_confirmado import CustodiaEstado


class ClienteInterrumpido:
    def __init__(self):
        self.objetos = {}
        self.archivos = {}
        self.version = 0

    def faltantes(self, huellas):
        return [h for h in huellas if h not in self.objetos]

    def subir(self, sha, datos, lease_token):
        assert hashlib.sha256(datos).hexdigest() == sha
        self.objetos[sha] = datos

    def confirmar(self, lease_token, version_base, archivos):
        assert version_base == self.version
        if self.version == 1:
            raise OSError("interrupción sintética antes del segundo lote")
        self.archivos.update(archivos)
        self.version += 1
        return self.version


def test_interrupcion_entre_lotes_deja_estado_parcial_y_diario_con_base_superada(tmp_path):
    raiz = tmp_path / "empresa"
    actual = raiz / "operacion" / "actual"
    actual.mkdir(parents=True)
    rutas = [f"operacion/actual/{n:03}.json" for n in range(51)]
    for n, ruta in enumerate(rutas):
        (raiz / ruta).write_text(f"nuevo-{n}", encoding="utf-8")
    cliente = ClienteInterrumpido()
    custodia = CustodiaEstado(raiz, cliente, carpeta_local=tmp_path / "cache")
    lease = SimpleNamespace(escritor_id="sintetico", lease_token="lease-sintetico")
    custodia.local.mkdir()
    custodia._ruta_pendiente.write_text(json.dumps({
        "escritor_id": lease.escritor_id, "version_base": 0,
        "raiz": str(custodia.raiz), "rutas": rutas,
    }), encoding="utf-8")

    with pytest.raises(OSError, match="segundo lote"):
        custodia._confirmar_rutas(lease, rutas)
    assert cliente.version == custodia.version == 1
    assert len(cliente.archivos) == 50 and rutas[-1] not in cliente.archivos

    resumen = {"pendiente_confirmado": 0}
    custodia._recuperar_pendiente(lease, resumen)
    assert resumen["pendiente_confirmado"] == 0
    assert not custodia._ruta_pendiente.exists()
    assert rutas[-1] not in cliente.archivos
