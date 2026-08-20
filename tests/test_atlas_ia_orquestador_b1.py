"""Pruebas del orquestador multicampo B1, sin red ni escrituras."""

from __future__ import annotations

import pytest

from atlas_core.atlas_ia.contratos import (
    ContextoRazonamiento,
    EvidenciaIA,
    HipotesisIA,
    RESULTADO_HIPOTESIS_ABSTENCION,
    RESULTADO_HIPOTESIS_PROPUESTA,
    RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA,
    calcular_hipotesis_id,
)
from atlas_core.atlas_ia.herramientas import herramienta_documentos_relacionados
from atlas_core.atlas_ia.orquestador import (
    ABSTENCION_IA,
    BLOQUEADO_POR_VALIDACION,
    CLASIFICACION_A,
    CLASIFICACION_B,
    CLASIFICACION_C,
    CLASIFICACION_D,
    ERROR_PROVEEDOR,
    NO_APLICA_IA,
    REQUIERE_HERRAMIENTA,
    RESUELTO_POR_IA,
    OrquestadorAtlasIA,
)
from atlas_core.atlas_ia.proveedor import ProveedorModeloIASimulado, RespuestaSimulada
from atlas_core.atlas_ia.proveedor_groq import ProveedorGroqNoDisponible


def _evidencia(
    valor: str, *, identificador: str = "e1", nivel: str = "DOCUMENTAL_DEBIL",
    humana: bool = False,
) -> EvidenciaIA:
    return EvidenciaIA(
        identificador=identificador, campo="cliente", valor=valor,
        tipo_fuente="DECISION_HUMANA" if humana else "DOCUMENTAL",
        nivel=nivel, es_decision_humana=humana,
    )


def _contexto(**cambios: object) -> ContextoRazonamiento:
    datos: dict[str, object] = {
        "campo": "cliente", "valor_documental": "No encontrado",
        "rut_chofer": "15489424-1", "numero_guia": "464265",
        "numero_transporte": "0000351135",
        "evidencias": (_evidencia("SODIMAC SA"),),
        "resultado_motor": "CONTRADICCION_DOCUMENTAL",
    }
    datos.update(cambios)
    return ContextoRazonamiento(**datos)


def _proveedor(resultado: str, valor: str = "") -> ProveedorModeloIASimulado:
    return ProveedorModeloIASimulado(respuestas_por_valor_documental={
        "No encontrado": RespuestaSimulada(resultado=resultado, valor_propuesto=valor),
    })


def test_no_invoca_ia_si_motor_ya_resolvio() -> None:
    proveedor = _proveedor(RESULTADO_HIPOTESIS_PROPUESTA, "SODIMAC SA")
    resultado = OrquestadorAtlasIA(proveedor=proveedor).resolver(
        _contexto(resultado_motor="RESUELTO_AUTOMATICAMENTE")
    )
    assert (resultado.estado, resultado.clasificacion, resultado.rondas) == (
        NO_APLICA_IA, CLASIFICACION_A, 0,
    )
    assert proveedor.contextos_recibidos == []


def test_propuesta_documental_valida_es_asistencia_b() -> None:
    resultado = OrquestadorAtlasIA(
        proveedor=_proveedor(RESULTADO_HIPOTESIS_PROPUESTA, "SODIMAC SA")
    ).resolver(_contexto())
    assert (resultado.estado, resultado.clasificacion) == (RESUELTO_POR_IA, CLASIFICACION_B)
    assert resultado.validacion and resultado.validacion.aceptada


def test_confirmacion_humana_sin_conflicto_es_candidata_a() -> None:
    contexto = _contexto(evidencias=(
        _evidencia("SODIMAC SA", nivel="CONFIRMACION_HUMANA", humana=True),
    ))
    resultado = OrquestadorAtlasIA(
        proveedor=_proveedor(RESULTADO_HIPOTESIS_PROPUESTA, "SODIMAC SA")
    ).resolver(contexto)
    assert resultado.clasificacion == CLASIFICACION_A


def test_abstencion_es_clase_c() -> None:
    resultado = OrquestadorAtlasIA(
        proveedor=_proveedor(RESULTADO_HIPOTESIS_ABSTENCION)
    ).resolver(_contexto())
    assert (resultado.estado, resultado.clasificacion) == (ABSTENCION_IA, CLASIFICACION_C)


def test_valor_inventado_es_bloqueado_clase_d() -> None:
    resultado = OrquestadorAtlasIA(
        proveedor=_proveedor(RESULTADO_HIPOTESIS_PROPUESTA, "CLIENTE INVENTADO")
    ).resolver(_contexto())
    assert (resultado.estado, resultado.clasificacion) == (
        BLOQUEADO_POR_VALIDACION, CLASIFICACION_D,
    )
    assert resultado.validacion and resultado.validacion.motivo_rechazo == "VALOR_NO_RESPALDADO_POR_EVIDENCIA"


def test_caida_de_groq_es_resultado_controlado() -> None:
    class ProveedorCaido:
        def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:
            raise ProveedorGroqNoDisponible("HTTP 429 controlado")

    resultado = OrquestadorAtlasIA(proveedor=ProveedorCaido()).resolver(_contexto())
    assert (resultado.estado, resultado.clasificacion) == (ERROR_PROVEEDOR, CLASIFICACION_D)
    assert "429" in resultado.detalle


class _ProveedorSecuencial:
    def __init__(self) -> None:
        self.ronda = 0

    def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:
        self.ronda += 1
        if self.ronda == 1:
            resultado, valor, herramienta = RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA, "", "DOCUMENTOS_RELACIONADOS"
        else:
            resultado, valor, herramienta = RESULTADO_HIPOTESIS_PROPUESTA, "SODIMAC SA", ""
        return HipotesisIA(
            hipotesis_id=calcular_hipotesis_id(contexto, valor), campo=contexto.campo,
            valor_observado=contexto.valor_documental, valor_propuesto=valor,
            resultado=resultado, herramienta_faltante=herramienta,
        )


def test_segunda_ronda_usa_herramienta_read_only() -> None:
    filas = (
        {"numero_guia": "464265", "numero_transporte": "0000351135", "cliente": "No encontrado"},
        {"numero_guia": "464264", "numero_transporte": "0000351135", "cliente": "SODIMAC SA"},
    )
    herramienta = herramienta_documentos_relacionados(filas)
    contexto = _contexto(evidencias=(), herramientas_disponibles=(herramienta.nombre,))
    resultado = OrquestadorAtlasIA(
        proveedor=_ProveedorSecuencial(), herramientas={herramienta.nombre: herramienta},
    ).resolver(contexto)
    assert (resultado.estado, resultado.rondas, resultado.herramientas_usadas) == (
        RESUELTO_POR_IA, 2, ("DOCUMENTOS_RELACIONADOS",),
    )
    assert resultado.contexto_final.valores_evidencia() == ("SODIMAC SA",)
    assert filas[1]["cliente"] == "SODIMAC SA"


def test_no_supera_dos_rondas() -> None:
    proveedor = _proveedor(RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA)
    # El doble requiere un nombre; se configura directamente para este caso.
    proveedor = ProveedorModeloIASimulado(respuestas_por_valor_documental={
        "No encontrado": RespuestaSimulada(
            resultado=RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA,
            herramienta_faltante="DOCUMENTOS_RELACIONADOS",
        ),
    })
    herramienta = herramienta_documentos_relacionados(())
    resultado = OrquestadorAtlasIA(
        proveedor=proveedor, herramientas={herramienta.nombre: herramienta},
    ).resolver(_contexto(herramientas_disponibles=(herramienta.nombre,)))
    assert (resultado.estado, resultado.clasificacion, resultado.rondas) == (
        REQUIERE_HERRAMIENTA, CLASIFICACION_C, 2,
    )
    assert len(proveedor.contextos_recibidos) == 2


@pytest.mark.parametrize(
    ("campo", "valor"),
    (("patente_tracto", "MALA"), ("rut_chofer", "12-3"), ("fecha", "32-13-2026")),
)
def test_formatos_especificos_invalidos_se_bloquean(campo: str, valor: str) -> None:
    contexto = _contexto(
        campo=campo, valor_documental="No encontrado",
        evidencias=(EvidenciaIA(
            identificador="formato", campo=campo, valor=valor,
            tipo_fuente="DOCUMENTAL", nivel="DOCUMENTAL_DEBIL",
        ),),
    )
    resultado = OrquestadorAtlasIA(
        proveedor=_proveedor(RESULTADO_HIPOTESIS_PROPUESTA, valor)
    ).resolver(contexto)
    assert resultado.clasificacion == CLASIFICACION_D
    assert resultado.validacion and resultado.validacion.motivo_rechazo == "FORMATO_INVALIDO"
