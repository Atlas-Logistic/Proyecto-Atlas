"""Almacén de confirmaciones humanas independientes -- pieza nueva de
"aprendizaje operacional": Atlas deja de repetir la misma pregunta cuando
la misma relación (RUT/contexto -> entidad canónica) ya fue confirmada
por un humano, en transportes distintos, al menos
`UMBRAL_CONFIRMACIONES_PARA_CONOCIMIENTO_FUERTE` veces."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from atlas_core.evidencia_entidades import (
    UMBRAL_CONFIRMACIONES_PARA_CONOCIMIENTO_FUERTE, AlmacenEvidenciaEntidades, ErrorEvidenciaEntidades,
    transportes_independientes,
)

FECHA = datetime(2026, 8, 19, tzinfo=timezone.utc)


def _almacen(tmp_path):
    return AlmacenEvidenciaEntidades(tmp_path / "evidencia_entidades.json")


def test_umbral_de_conocimiento_fuerte_es_dos():
    # Constante nombrada, no un número mágico repetido -- este test
    # protege que el valor documentado en el módulo es el que de verdad
    # rige el comportamiento.
    assert UMBRAL_CONFIRMACIONES_PARA_CONOCIMIENTO_FUERTE == 2


def test_almacen_vacio_no_falla_y_no_inventa_archivo(tmp_path):
    almacen = _almacen(tmp_path)
    assert almacen.listar() == []
    assert not (tmp_path / "evidencia_entidades.json").exists()


def test_registrar_confirmacion_persiste_y_se_puede_releer(tmp_path):
    almacen = _almacen(tmp_path)
    confirmacion = almacen.registrar_confirmacion(
        dominio="CLIENTE", contexto_clave="76000000-K", valor_documental="PPP CONSTRUCCIONES",
        valor_confirmado="EBEMA SA", identificador_confirmado="cliente-ebema",
        numero_guia="1", numero_transporte="T-1", actor="JAVIER_MBT", fuente_decision="TEST", fecha=FECHA,
    )
    assert confirmacion.valor_confirmado == "EBEMA SA"
    releido = AlmacenEvidenciaEntidades(almacen.ruta).listar()
    assert len(releido) == 1
    assert releido[0].confirmacion_id == confirmacion.confirmacion_id


def test_registrar_la_misma_confirmacion_dos_veces_es_idempotente(tmp_path):
    """Duplicado del mismo documento no debe sumar evidencia -- registrar
    la misma confirmación (mismo dominio/contexto/valor/guía/transporte)
    dos veces no crea un segundo registro."""
    almacen = _almacen(tmp_path)
    kwargs = dict(
        dominio="CLIENTE", contexto_clave="76000000-K", valor_documental="PPP CONSTRUCCIONES",
        valor_confirmado="EBEMA SA", identificador_confirmado="cliente-ebema",
        numero_guia="1", numero_transporte="T-1", actor="JAVIER_MBT", fuente_decision="TEST", fecha=FECHA,
    )
    almacen.registrar_confirmacion(**kwargs)
    almacen.registrar_confirmacion(**kwargs)
    assert len(almacen.listar()) == 1


def test_confirmacion_requiere_actor_y_contexto(tmp_path):
    almacen = _almacen(tmp_path)
    with pytest.raises(ErrorEvidenciaEntidades):
        almacen.registrar_confirmacion(
            dominio="CLIENTE", contexto_clave="76000000-K", valor_documental="X", valor_confirmado="Y",
            numero_guia="1", numero_transporte="T-1", actor="", fuente_decision="TEST", fecha=FECHA,
        )
    with pytest.raises(ErrorEvidenciaEntidades):
        almacen.registrar_confirmacion(
            dominio="CLIENTE", contexto_clave="", valor_documental="X", valor_confirmado="Y",
            numero_guia="1", numero_transporte="T-1", actor="JAVIER_MBT", fuente_decision="TEST", fecha=FECHA,
        )


def test_transportes_independientes_no_cuenta_el_mismo_transporte_dos_veces(tmp_path):
    """Mismo transporte, dos documentos -- 1 confirmación independiente,
    no 2 (mismo principio ya validado para vehículos)."""
    almacen = _almacen(tmp_path)
    almacen.registrar_confirmacion(
        dominio="CLIENTE", contexto_clave="76000000-K", valor_documental="PPP CONSTRUCCIONES",
        valor_confirmado="EBEMA SA", numero_guia="1", numero_transporte="T-1",
        actor="JAVIER_MBT", fuente_decision="TEST", fecha=FECHA,
    )
    almacen.registrar_confirmacion(
        dominio="CLIENTE", contexto_clave="76000000-K", valor_documental="PPP CONST",
        valor_confirmado="EBEMA SA", numero_guia="2", numero_transporte="T-1",
        actor="JAVIER_MBT", fuente_decision="TEST", fecha=FECHA,
    )
    confirmaciones = almacen.confirmaciones_para(dominio="CLIENTE", contexto_clave="76000000-K", valor_confirmado="EBEMA SA")
    assert transportes_independientes(confirmaciones) == 1


def test_dos_confirmaciones_de_transportes_distintos_si_son_independientes(tmp_path):
    almacen = _almacen(tmp_path)
    almacen.registrar_confirmacion(
        dominio="CLIENTE", contexto_clave="76000000-K", valor_documental="PPP CONSTRUCCIONES",
        valor_confirmado="EBEMA SA", numero_guia="1", numero_transporte="T-1",
        actor="JAVIER_MBT", fuente_decision="TEST", fecha=FECHA,
    )
    almacen.registrar_confirmacion(
        dominio="CLIENTE", contexto_clave="76000000-K", valor_documental="OTRO NOMBRE MAL",
        valor_confirmado="EBEMA SA", numero_guia="2", numero_transporte="T-2",
        actor="JAVIER_MBT", fuente_decision="TEST", fecha=FECHA,
    )
    confirmaciones = almacen.confirmaciones_para(dominio="CLIENTE", contexto_clave="76000000-K", valor_confirmado="EBEMA SA")
    assert transportes_independientes(confirmaciones) == UMBRAL_CONFIRMACIONES_PARA_CONOCIMIENTO_FUERTE
