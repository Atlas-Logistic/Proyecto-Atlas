"""Credenciales locales por usuario/PC: registro y resolución.

El registro de Windows se simula con un dict por "PC"; nunca se escribe
HKCU real ni una credencial real."""
import os
import uuid

import pytest

import registrar_credencial
from atlas_core.atlas_ia import credenciales

pytestmark = pytest.mark.skipif(os.name != "nt", reason="credenciales locales: sólo Windows")


class RegistroSimulado:
    def __init__(self):
        self.valores: dict[str, str] = {}
        self.notificaciones = 0

    def instalar(self, monkeypatch):
        monkeypatch.setattr(credenciales, "_leer_entorno_usuario_windows", lambda n: self.valores.get(n, ""))
        monkeypatch.setattr(credenciales, "_escribir_entorno_usuario_windows", self.valores.__setitem__)
        monkeypatch.setattr(credenciales, "_notificar_cambio_entorno_windows", self._notificar)
        return self

    def _notificar(self):
        self.notificaciones += 1


@pytest.fixture
def registro(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    return RegistroSimulado().instalar(monkeypatch)


def _marcador() -> str:
    return f"marcador-{uuid.uuid4().hex}"


def _registrar(valor: str, nombre: str = "TAVILY_API_KEY", interactivo: bool = True) -> tuple[int, list[str]]:
    pedidos = []

    def leer(prompt):
        pedidos.append(prompt)
        return valor

    return registrar_credencial.main([nombre], leer_secreto=leer, interactivo=interactivo), pedidos


def test_tavily_entorno_tiene_prioridad_y_hkcu_es_respaldo(registro, monkeypatch):
    assert credenciales.resolver_tavily_api_key() == ""
    registro.valores["TAVILY_API_KEY"] = "desde-hkcu"
    assert credenciales.resolver_tavily_api_key() == "desde-hkcu"
    monkeypatch.setenv("TAVILY_API_KEY", "desde-entorno")
    assert credenciales.resolver_tavily_api_key() == "desde-entorno"


def test_cli_registra_en_hkcu_notifica_y_nunca_imprime_el_valor(registro, capsys):
    valor = _marcador()
    codigo, pedidos = _registrar(f"  {valor}  ")
    salida = capsys.readouterr()
    assert codigo == 0
    assert registro.valores == {"TAVILY_API_KEY": valor}
    assert registro.notificaciones == 1
    assert len(pedidos) == 1 and valor not in pedidos[0]
    assert valor not in salida.out + salida.err
    assert "TAVILY_API_KEY registrada" in salida.out
    assert credenciales.resolver_tavily_api_key() == valor


def test_cli_no_acepta_el_secreto_como_argumento_ni_nombres_no_permitidos(registro, capsys):
    valor = _marcador()
    for argv in (["TAVILY_API_KEY", valor], ["TAVILY_API_KEY", f"--valor={valor}"], ["OTRA_API_KEY"]):
        with pytest.raises(SystemExit) as salida:
            registrar_credencial.main(argv, leer_secreto=lambda _: pytest.fail("no debe pedir valor"), interactivo=True)
        assert salida.value.code == 2
    assert registro.valores == {}


def test_cli_no_interactivo_no_lee_ni_escribe(registro):
    codigo, pedidos = _registrar(_marcador(), interactivo=False)
    assert codigo == 2 and pedidos == [] and registro.valores == {}


@pytest.mark.parametrize("invalido", ["", "   ", "con espacio", "con\nsalto"])
def test_valor_vacio_o_con_espacios_se_rechaza_sin_mostrarlo(registro, capsys, invalido):
    codigo, _ = _registrar(invalido)
    salida = capsys.readouterr()
    assert codigo == 1 and registro.valores == {} and registro.notificaciones == 0
    if invalido.strip():
        assert invalido not in salida.err


def test_casa_y_oficina_registran_una_vez_y_resuelven_con_el_mismo_codigo(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    valores = {}
    for pc in ("casa", "oficina"):
        with monkeypatch.context() as m:
            RegistroSimulado().instalar(m)
            assert credenciales.resolver_tavily_api_key() == ""
            valores[pc] = _marcador()
            assert _registrar(valores[pc])[0] == 0
            assert credenciales.resolver_tavily_api_key() == valores[pc]
    with monkeypatch.context() as m:  # PC sin registrar: ausente, nunca lee de otra fuente
        RegistroSimulado().instalar(m)
        assert credenciales.resolver_tavily_api_key() == ""
