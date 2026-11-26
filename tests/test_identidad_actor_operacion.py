"""Actor auditable de B1 con identidad exigida (integración multiempresa 26/11/2026).

Desktop invoca b1_operador_cli con ``--usuario JAVIER_DESKTOP`` sea quien sea
el usuario de la sesión; con identidad exigida el ledger debe nombrar a la
persona identificada. Sin exigencia (MBT hoy) nada cambia."""
from __future__ import annotations

import pytest

from atlas_core import identidad


@pytest.fixture
def sesion(monkeypatch):
    def fijar(valor):
        monkeypatch.setattr(identidad, "_sesion_proceso", valor)
    return fijar


def test_sin_exigencia_conserva_el_actor_declarado(sesion):
    sesion(None)
    assert identidad.actor_operacion("JAVIER_DESKTOP") == "JAVIER_DESKTOP"


def test_con_sesion_de_empresa_el_actor_es_la_persona_identificada(sesion):
    sesion({"tipo": "empresa", "empresa_id": "transportes-andes", "usuario": "ana.sup", "rol": "supervisor"})
    assert identidad.actor_operacion("JAVIER_DESKTOP") == "transportes-andes:ana.sup"


def test_sesion_de_plataforma_no_suplanta_ni_inventa_empresa(sesion):
    sesion({"tipo": "plataforma", "empresa_id": None, "usuario": "propietario", "rol": "superadministrador_atlas"})
    assert identidad.actor_operacion("JAVIER_DESKTOP") == "JAVIER_DESKTOP"


def test_b1_operador_cli_usa_el_actor_de_la_sesion(sesion, monkeypatch, tmp_path):
    import b1_operador_cli

    usados = []

    class Operador:
        def __init__(self, raiz, usuario):
            usados.append(usuario)

        def atender(self, conversacion, texto):
            return {"estado": "PREVIEW_PENDIENTE"}

    monkeypatch.setattr(b1_operador_cli, "OperadorB1", Operador)
    monkeypatch.setattr(b1_operador_cli, "resolver_raiz_atlas", lambda r: tmp_path)
    sesion({"tipo": "empresa", "empresa_id": "transportes-andes", "usuario": "ana.sup", "rol": "supervisor"})
    assert b1_operador_cli.main(["--conversacion", "c1", "--texto", "x", "--usuario", "JAVIER_DESKTOP"]) == 0
    sesion(None)
    assert b1_operador_cli.main(["--conversacion", "c1", "--texto", "x", "--usuario", "JAVIER_DESKTOP"]) == 0
    assert usados == ["transportes-andes:ana.sup", "JAVIER_DESKTOP"]
