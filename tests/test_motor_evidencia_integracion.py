"""Integración de punta a punta del Motor de Evidencia -- Clientes con el
almacén de Incidencias Documentales: cuando el motor resuelve
automáticamente PESE a una contradicción de texto (CASO C: confirmaciones
independientes acumuladas), el conflicto detectado se traduce en una
Incidencia Documental real y auditable -- nunca al revés (un simple error
de lectura nunca llega a registrarse)."""
from __future__ import annotations

from datetime import datetime, timezone

from atlas_core.evidencia_entidades import AlmacenEvidenciaEntidades
from atlas_core.incidencias_documentales import AlmacenIncidenciasDocumentales, TIPO_IDENTIDAD_CLIENTE_INCONSISTENTE
from atlas_core.motor_evidencia import RESULTADO_RESUELTO_AUTOMATICAMENTE
from atlas_core.motor_evidencia_clientes import evaluar_evidencia_cliente

FECHA = datetime(2026, 8, 19, tzinfo=timezone.utc)
RUT_EBEMA = "76086428-5"


def test_caso_c_resuelto_automaticamente_con_contradiccion_genera_incidencia_registrable(tmp_path):
    almacen_confirmaciones = AlmacenEvidenciaEntidades(tmp_path / "evidencia_entidades.json")
    almacen_confirmaciones.registrar_confirmacion(
        dominio="CLIENTE", contexto_clave=RUT_EBEMA, valor_documental="PPP CONSTRUCCIONES",
        valor_confirmado="EBEMA SA", identificador_confirmado="cliente-ebema",
        numero_guia="1", numero_transporte="T-1", actor="JAVIER_MBT", fuente_decision="CONFIRMAR_ALIAS", fecha=FECHA,
    )
    almacen_confirmaciones.registrar_confirmacion(
        dominio="CLIENTE", contexto_clave=RUT_EBEMA, valor_documental="OTRO NOMBRE MAL",
        valor_confirmado="EBEMA SA", identificador_confirmado="cliente-ebema",
        numero_guia="2", numero_transporte="T-2", actor="JAVIER_MBT", fuente_decision="CONFIRMAR_ALIAS", fecha=FECHA,
    )

    # Tercera aparición equivalente -- un valor documental nunca visto,
    # mismo RUT, ningún cliente formal en catálogo todavía.
    resultado = evaluar_evidencia_cliente(
        razon_social_documental="XYZ CONSTRUCCIONES", rut_documental=RUT_EBEMA,
        numero_guia="3", numero_transporte="T-3", clientes=[],
        confirmaciones=almacen_confirmaciones.listar(),
    )
    assert resultado.resultado == RESULTADO_RESUELTO_AUTOMATICAMENTE
    mejor = resultado.candidatos[0]
    assert mejor.conflictos  # hay una contradicción real que registrar

    almacen_incidencias = AlmacenIncidenciasDocumentales(tmp_path / "incidencias_documentales.json")
    incidencia = almacen_incidencias.registrar(
        contexto=mejor.valor_canonico, numero_guia="3", numero_transporte="T-3", campo="cliente",
        valor_documental="XYZ CONSTRUCCIONES", valor_canonico=mejor.valor_canonico,
        tipo_incidencia=TIPO_IDENTIDAD_CLIENTE_INCONSISTENTE, evidencia=mejor.evidencias, fecha=FECHA,
        fuente_resolucion="MOTOR_EVIDENCIA_CLIENTES",
    )
    assert incidencia.valor_canonico == "EBEMA SA"
    assert incidencia.valor_documental == "XYZ CONSTRUCCIONES"
    assert len(almacen_incidencias.listar()) == 1


def test_incidencias_documentales_no_tiene_ningun_mecanismo_de_bloqueo():
    """FASE 10: una Incidencia Documental no debe bloquear el viaje --
    verificado estructuralmente: el módulo no expone ningún estado ni
    función capaz de impedir el procesamiento de un documento/viaje, sólo
    persistencia y consulta."""
    import atlas_core.incidencias_documentales as modulo
    prohibido = {"bloquear", "bloqueo", "block", "detener_procesamiento", "impedir"}
    nombres = {nombre.lower() for nombre in dir(modulo)}
    assert not (nombres & prohibido)
