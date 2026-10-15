"""Caché de veredictos de validación de catálogos de destinos y obras.

Contrato: mismos objetos, mismas excepciones y mismas validaciones que sin
caché; sólo se omite revalidar un contenido EXACTO ya validado. Cualquier
cambio de contenido -- de este proceso, de otro proceso o de un archivo
del que depende la validación (clientes/destinos para obras) -- vuelve a
validar."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from atlas_core import cache_validacion_catalogos
from atlas_core.catalogo_clientes import CatalogoClientes
from atlas_core.catalogo_destinos import CatalogoDestinos, CatalogoDestinosCorruptoError
from atlas_core.catalogo_obras_destinos import (
    CatalogoObrasDestinos, CatalogoObrasDestinosCorruptoError, Evidencia, TipoEvidencia,
)


class _Reloj:
    def __init__(self):
        self.actual = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self):
        valor = self.actual
        self.actual += timedelta(seconds=1)
        return valor


class _Ids:
    def __init__(self, prefijo: str):
        self.prefijo, self.valor = prefijo, 0

    def __call__(self):
        self.valor += 1
        return f"{self.prefijo}-{self.valor}"


@pytest.fixture(autouse=True)
def _cache_limpio(monkeypatch):
    monkeypatch.delenv(cache_validacion_catalogos.VARIABLE_DESACTIVAR, raising=False)
    cache_validacion_catalogos.limpiar()
    yield
    cache_validacion_catalogos.limpiar()


def _entorno(tmp_path: Path):
    carpeta = tmp_path / "catalogos_privados"
    clientes = carpeta / "clientes.json"
    destinos = carpeta / "destinos_maestros.json"
    reloj = _Reloj()
    cliente = CatalogoClientes(clientes, reloj=reloj, generador_id=_Ids("cli")).crear(
        razon_social="CLIENTE SINTETICO SA", fuente="PRUEBA"
    )
    catalogo_destinos = CatalogoDestinos(destinos, ruta_clientes=clientes, reloj=reloj, generador_id=_Ids("des"))
    destino = catalogo_destinos.crear(
        cliente_id=cliente.cliente_id, nombre_destino="DESTINO SINTETICO",
        direccion="CALLE PRUEBA 123", pais="CHILE", fuente="PRUEBA",
    )
    catalogo_destinos.crear(
        cliente_id=cliente.cliente_id, nombre_destino="OTRO DESTINO",
        direccion="CALLE OTRA 456", pais="CHILE", fuente="PRUEBA",
    )
    obras = CatalogoObrasDestinos(
        carpeta / "obras_destinos.json", ruta_clientes=clientes, ruta_destinos=destinos,
        reloj=reloj, generador_id=_Ids("obra"),
    )
    obras.registrar_observacion(
        cliente_id=cliente.cliente_id, nombre_obra="OBRA SINTETICA", destino_id=destino.destino_id,
        evidencia=Evidencia(
            tipo=TipoEvidencia.GUIA.value, identificador_fuente="guia-1", referencia_hash="a" * 64,
            campos_observados={"obra": "OBRA SINTETICA"}, fecha="2026-01-01T00:00:00+00:00",
            actor_proceso="test", resultado="SOPORTA",
        ),
    )
    return catalogo_destinos, obras, cliente, destino


def _contar(monkeypatch, clase, nombre: str) -> list[int]:
    llamadas = [0]
    original = getattr(clase, nombre)

    def contado(*args, **kwargs):
        llamadas[0] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(clase, nombre, staticmethod(contado) if isinstance(clase.__dict__[nombre], staticmethod) else contado)
    return llamadas


def _agregar_destino_duplicado(ruta: Path) -> None:
    contenido = json.loads(ruta.read_text(encoding="utf-8"))
    copia = dict(contenido["destinos"][0])
    copia["destino_id"] = "des-duplicado"
    contenido["destinos"].append(copia)
    ruta.write_text(json.dumps(contenido, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_misma_lectura_que_sin_cache_y_validacion_omitida_solo_al_repetir(tmp_path, monkeypatch):
    catalogo_destinos, obras, _, _ = _entorno(tmp_path)
    monkeypatch.setenv(cache_validacion_catalogos.VARIABLE_DESACTIVAR, "0")
    destinos_sin_cache = catalogo_destinos.listar()
    obras_sin_cache = (obras.listar_obras(), obras.listar_relaciones())
    monkeypatch.delenv(cache_validacion_catalogos.VARIABLE_DESACTIVAR)
    cache_validacion_catalogos.limpiar()  # `_entorno` ya leyó (y validó) estos contenidos

    duplicados = _contar(monkeypatch, CatalogoDestinos, "_validar_duplicado")
    validaciones_obras = _contar(monkeypatch, CatalogoObrasDestinos, "_validar_catalogo")
    for _ in range(3):
        assert catalogo_destinos.listar() == destinos_sin_cache
        assert (obras.listar_obras(), obras.listar_relaciones()) == obras_sin_cache
    # Destinos: 2 validaciones por lectura completa (una por destino) sólo
    # la primera vez. Obras: una validación sólo la primera vez.
    assert duplicados[0] == 2
    assert validaciones_obras[0] == 1


def test_cada_lectura_entrega_objetos_nuevos_no_compartidos(tmp_path):
    _, obras, _, _ = _entorno(tmp_path)
    primera = obras.listar_obras()
    primera[0].evidencias[0].campos_observados["obra"] = "MUTADO POR UN LLAMADOR"
    primera.clear()
    segunda = obras.listar_obras()
    assert len(segunda) == 1
    assert segunda[0].evidencias[0].campos_observados["obra"] == "OBRA SINTETICA"
    assert segunda[0] is not obras.listar_obras()[0]


def test_escritura_interna_invalida_el_veredicto(tmp_path):
    catalogo_destinos, _, cliente, _ = _entorno(tmp_path)
    assert len(catalogo_destinos.listar()) == 2
    catalogo_destinos.crear(
        cliente_id=cliente.cliente_id, nombre_destino="TERCER DESTINO",
        direccion="CALLE TRES 789", pais="CHILE", fuente="PRUEBA",
    )
    assert [d.nombre_destino for d in catalogo_destinos.listar()][-1] == "TERCER DESTINO"


def test_modificacion_externa_que_rompe_el_catalogo_vuelve_a_fallar(tmp_path):
    catalogo_destinos, _, _, _ = _entorno(tmp_path)
    catalogo_destinos.listar()  # contenido válido ya validado
    _agregar_destino_duplicado(catalogo_destinos.ruta)
    with pytest.raises(CatalogoDestinosCorruptoError):
        catalogo_destinos.listar()


def test_modificacion_desde_otro_proceso_se_detecta(tmp_path):
    catalogo_destinos, _, _, _ = _entorno(tmp_path)
    catalogo_destinos.listar()
    codigo = (
        "import json,sys\n"
        "from pathlib import Path\n"
        "r=Path(sys.argv[1]); c=json.loads(r.read_text(encoding='utf-8'))\n"
        "x=dict(c['destinos'][0]); x['destino_id']='des-otro-proceso'; c['destinos'].append(x)\n"
        "r.write_text(json.dumps(c, ensure_ascii=False, indent=2)+'\\n', encoding='utf-8')\n"
    )
    subprocess.run([sys.executable, "-c", codigo, str(catalogo_destinos.ruta)], check=True)
    with pytest.raises(CatalogoDestinosCorruptoError):
        catalogo_destinos.listar()


def test_archivo_corrupto_lanza_la_misma_excepcion_que_sin_cache(tmp_path, monkeypatch):
    catalogo_destinos, obras, _, _ = _entorno(tmp_path)
    catalogo_destinos.listar()
    obras.listar_obras()
    for ruta in (catalogo_destinos.ruta, obras.ruta):
        ruta.write_text('{"version_formato": 1, "destinos": [', encoding="utf-8")
    errores = {}
    for modo in ("1", "0", "1"):
        monkeypatch.setenv(cache_validacion_catalogos.VARIABLE_DESACTIVAR, modo)
        for nombre, leer, tipo in (
            ("destinos", catalogo_destinos.listar, CatalogoDestinosCorruptoError),
            ("obras", obras.listar_obras, CatalogoObrasDestinosCorruptoError),
        ):
            with pytest.raises(tipo) as excinfo:
                leer()
            errores.setdefault(nombre, set()).add(str(excinfo.value))
    assert all(len(mensajes) == 1 for mensajes in errores.values()), errores


def test_obras_revalida_si_cambia_clientes(tmp_path):
    _, obras, cliente, _ = _entorno(tmp_path)
    obras.listar_obras()
    contenido = json.loads(obras.ruta.read_text(encoding="utf-8"))
    assert contenido["obras"][0]["cliente_id"] == cliente.cliente_id
    clientes = json.loads(obras.ruta_clientes.read_text(encoding="utf-8"))
    clientes["clientes"] = []
    obras.ruta_clientes.write_text(json.dumps(clientes), encoding="utf-8")
    with pytest.raises(CatalogoObrasDestinosCorruptoError, match="cliente inexistente"):
        obras.listar_obras()


def test_obras_revalida_si_cambia_destinos(tmp_path):
    catalogo_destinos, obras, _, destino = _entorno(tmp_path)
    obras.listar_relaciones()
    contenido = json.loads(catalogo_destinos.ruta.read_text(encoding="utf-8"))
    contenido["destinos"] = [d for d in contenido["destinos"] if d["destino_id"] != destino.destino_id]
    catalogo_destinos.ruta.write_text(json.dumps(contenido), encoding="utf-8")
    with pytest.raises(CatalogoObrasDestinosCorruptoError, match="destino inexistente"):
        obras.listar_relaciones()


def test_contenido_que_cambia_durante_el_parseo_no_se_recuerda(tmp_path, monkeypatch):
    catalogo_destinos, _, _, _ = _entorno(tmp_path)
    huellas = iter([("catalogo_destinos", "antes"), ("catalogo_destinos", "despues")])
    monkeypatch.setattr(
        "atlas_core.catalogo_destinos.huella_contenido", lambda *a: next(huellas, ("otra",)),
    )
    catalogo_destinos.listar()
    assert not cache_validacion_catalogos.ya_validado(("catalogo_destinos", "antes"))
    assert not cache_validacion_catalogos.ya_validado(("catalogo_destinos", "despues"))


def test_desactivado_valida_en_cada_lectura(tmp_path, monkeypatch):
    catalogo_destinos, _, _, _ = _entorno(tmp_path)
    monkeypatch.setenv(cache_validacion_catalogos.VARIABLE_DESACTIVAR, "0")
    duplicados = _contar(monkeypatch, CatalogoDestinos, "_validar_duplicado")
    for _ in range(3):
        catalogo_destinos.listar()
    assert duplicados[0] == 6
