"""Bloque AUTORIDAD OPERACIONAL -- Fase 1 (Bloques D + B).

B1 debe recibir el CONOCIMIENTO INTERNO CANÓNICO que Atlas ya posee
(catálogos, aliases, RUT, confirmaciones humanas de identidad, relación
chofer↔vehículo, obra↔destino confirmado) como evidencia estructurada --
nunca `evidencias: []` cuando esa información existe -- y la barrera
anti-alucinación (`validar_hipotesis_multicampo`) debe reconocer ese
valor como respaldado en vez de bloquear una conclusión correcta por
"VALOR_NO_RESPALDADO_POR_EVIDENCIA".

Casos reales congelados que motivan cada prueba:
- 472096 / obra "INMOB CASA HELSINSKI SPA" (variante OCR de "CASA
  HELSINSKI", alias previo "INMOB CASA RELSINSKI SPA") -> evidencia
  interna vacía; B1 propuso el valor bueno y fue bloqueado.
- 472477 / PRODALAM SA con RUT no extraído -> CLIENTE_CANDIDATO aunque
  la identidad es exacta/única/canónica/confirmada.
- 472477 / rampla JD8629 (chofer Carlos Simón, RUT 15489424-1; rampla
  canónica confirmada por un humano: JD8659) -> VEHICULO_DESCONOCIDO;
  B1 con evidencias vacías + 429.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from atlas_core.atlas_ia.contratos import (
    ContextoRazonamiento,
    HipotesisIA,
    MOTIVO_VALOR_NO_RESPALDADO,
    RESULTADO_HIPOTESIS_ABSTENCION,
    RESULTADO_HIPOTESIS_PROPUESTA,
    calcular_hipotesis_id,
)
from atlas_core.atlas_ia.evidencia_dominios import (
    evidencia_cliente_interna,
    evidencia_obra_interna,
    evidencia_vehiculo_interna,
)
from atlas_core.atlas_ia.registro_problemas import (
    recopilar_evidencia_cliente,
    recopilar_evidencia_obra_destino,
    recopilar_evidencia_vehiculo,
)
from atlas_core.atlas_ia.validadores import validar_hipotesis_multicampo
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_destinos import CatalogoDestinos
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, TipoEvidencia
from atlas_core.catalogo_vehiculos import TipoVehiculo, confirmar_vehiculo


# --------------------------------------------------------------------------
# Fixtures -- catálogos tmp reales (nunca G:\ real), mismo patrón que
# `tests/test_destinos_internos_v1.py` / `tests/test_motor_evidencia_vehiculos.py`.
# --------------------------------------------------------------------------


def _carpeta(tmp_path):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    return carpeta


def _rut(cuerpo: str) -> str:
    """RUT chileno válido a partir del cuerpo -- dígito verificador real,
    nunca uno inventado (los catálogos rechazan un DV incorrecto)."""
    suma = sum(int(d) * f for d, f in zip(reversed(cuerpo), (2, 3, 4, 5, 6, 7) * 3))
    resto = 11 - suma % 11
    dv = "0" if resto == 11 else "K" if resto == 10 else str(resto)
    return f"{cuerpo}-{dv}"


def _crear_cliente(carpeta, *, razon_social, rut, estado=EstadoCalidadCliente.CONFIRMADO):
    return CatalogoClientes(carpeta / "clientes.json").crear(
        razon_social=razon_social, rut=rut, fuente="PRUEBA", estado_calidad=estado,
    )


def _evidencia(ident="guia-1"):
    return Evidencia(
        tipo=TipoEvidencia.GUIA.value, identificador_fuente=ident, referencia_hash="a" * 64,
        campos_observados={"obra": "X"}, fecha="2026-01-01T00:00:00+00:00",
        actor_proceso="test", resultado="SOPORTA",
    )


def _obra_confirmada(carpeta, cliente, *, nombre_obra, direccion, aliases=()):
    destino = CatalogoDestinos(
        carpeta / "destinos_maestros.json", ruta_clientes=carpeta / "clientes.json",
    ).crear(
        cliente_id=cliente.cliente_id, nombre_destino=nombre_obra, direccion=direccion,
        comuna="LA REINA", region="RM", pais="CHILE", fuente="PRUEBA",
    )
    catalogo = CatalogoObrasDestinos(
        carpeta / "obras_destinos.json", ruta_clientes=carpeta / "clientes.json",
        ruta_destinos=carpeta / "destinos_maestros.json",
    )
    resultado = catalogo.registrar_observacion(
        cliente_id=cliente.cliente_id, nombre_obra=nombre_obra, destino_id=destino.destino_id,
        evidencia=_evidencia(),
    )
    catalogo.confirmar_relacion(resultado.relacion.relacion_id, actor="HUMANO")
    if aliases:
        catalogo.actualizar_identidad_obra(
            resultado.obra.obra_id, nombre_canonico=nombre_obra,
            aliases_documentales=list(aliases), evidencia=_evidencia("alias"),
        )
    return resultado.obra, destino


def _confirmar_vehiculo(carpeta, patente, tipo, *, rut_chofer_asociado=""):
    ruta = carpeta / "vehiculos.json"
    if not ruta.exists():
        ruta.write_text(json.dumps({"version": 1, "vehiculos": []}), encoding="utf-8")
    return confirmar_vehiculo(
        ruta, patente=patente, tipo=tipo, actor="JAVIER_MBT", fuente_decision="TEST",
        fecha=datetime.now(timezone.utc), rut_chofer_asociado=rut_chofer_asociado,
    )


def _contexto(campo, valor_documental, evidencias, *, rut_chofer=""):
    return ContextoRazonamiento(
        campo=campo, valor_documental=valor_documental, rut_chofer=rut_chofer,
        numero_guia="G", numero_transporte="T", evidencias=tuple(evidencias),
        resultado_motor="REQUIERE_REVISION",
    )


def _propuesta(contexto, valor):
    return HipotesisIA(
        hipotesis_id=calcular_hipotesis_id(contexto, valor), campo=contexto.campo,
        valor_observado=contexto.valor_documental, valor_propuesto=valor,
        resultado=RESULTADO_HIPOTESIS_PROPUESTA,
    )


# ==========================================================================
# 1. Obra conocida con variante OCR + cliente/destino confirmados
# ==========================================================================


def test_1_obra_variante_ocr_con_cliente_y_destino_confirmados_es_evidencia(tmp_path):
    carpeta = _carpeta(tmp_path)
    cliente = _crear_cliente(carpeta, razon_social="YOLITO BALART HNOS LTDA", rut="80.565.900-9")
    _obra_confirmada(
        carpeta, cliente, nombre_obra="CASA HELSINSKI",
        direccion="HELSINSKI 5810 LA REINA SANTIAGO",
        aliases=("INMOB CASA RELSINSKI SPA",),
    )
    evs = evidencia_obra_interna(
        nombre_documental="INMOB CASA HELSINSKI SPA",
        cliente_documental="INMOB CASA HELSINSKI SPA", rut_cliente_documental="80.565.900-9",
        despachar_a_documental="HELSINSKI 5810 LA REINA SANTIAGO", carpeta_catalogos=carpeta,
    )
    assert [e.valor for e in evs] == ["CASA HELSINSKI"]
    ev = evs[0]
    assert "CLIENTE_CANONICO_COINCIDE" in ev.a_favor
    assert "DESTINO_CONFIRMADO_COINCIDE" in ev.a_favor
    assert ev.es_decision_humana is True  # conjunción -> evidencia fuerte

    contexto = _contexto("obra_destino", "INMOB CASA HELSINSKI SPA", evs)
    assert validar_hipotesis_multicampo(_propuesta(contexto, "CASA HELSINSKI"), contexto).aceptada
    # tolerancia de formato (Bloque D) -- mismo valor, otra grafía
    assert validar_hipotesis_multicampo(_propuesta(contexto, "Casa Helsinski"), contexto).aceptada


# ==========================================================================
# 2. Mismo nombre parecido pero dos obras plausibles -> NO autoconfirmar
# ==========================================================================


def test_2_dos_obras_plausibles_no_autoconfirma(tmp_path):
    carpeta = _carpeta(tmp_path)
    cliente = _crear_cliente(carpeta, razon_social="CONSTRUCTORA X SPA", rut=_rut("76111111"))
    _obra_confirmada(carpeta, cliente, nombre_obra="TORRE NORTE", direccion="ALFA 100 SANTIAGO")
    _obra_confirmada(carpeta, cliente, nombre_obra="TORRE NORESTE", direccion="BETA 200 SANTIAGO")
    evs = evidencia_obra_interna(
        nombre_documental="TORRE NORE", cliente_documental="CONSTRUCTORA X SPA",
        rut_cliente_documental=_rut("76111111"), despachar_a_documental="GAMMA 300 SANTIAGO",
        carpeta_catalogos=carpeta,
    )
    # Prefijo ambiguo entre dos obras confirmadas -> ninguna candidata.
    assert evs == ()


# ==========================================================================
# 3. Cliente canónico exacto/único + RUT OCR ausente -> evidencia real
# ==========================================================================


def test_3_cliente_canonico_exacto_unico_sin_rut_es_evidencia(tmp_path):
    carpeta = _carpeta(tmp_path)
    _crear_cliente(carpeta, razon_social="PRODALAM SA", rut="93.772.000-9")
    _crear_cliente(carpeta, razon_social="CONSTRUMART SA", rut=_rut("81111111"))
    evs = evidencia_cliente_interna(
        nombre_documental="PRODALAM SA", rut_documental="No encontrado",
        numero_guia="472477", numero_transporte="0000354870", carpeta_catalogos=carpeta,
    )
    assert [e.valor for e in evs] == ["PRODALAM SA"]
    assert "IDENTIDAD_CANONICA_EXACTA_UNICA" in evs[0].a_favor

    contexto = _contexto("cliente", "PRODALAM SA", evs)
    assert validar_hipotesis_multicampo(_propuesta(contexto, "PRODALAM SA"), contexto).aceptada


# ==========================================================================
# 4. Cliente con competidor plausible -> revisión (sin evidencia fuerte)
# ==========================================================================


def test_4_cliente_nombre_ambiguo_no_produce_evidencia(tmp_path):
    carpeta = _carpeta(tmp_path)
    _crear_cliente(carpeta, razon_social="COMERCIAL ANDES SPA", rut=_rut("76222222"))
    _crear_cliente(carpeta, razon_social="COMERCIAL ANDES LIMITADA", rut=_rut("77333333"))
    evs = evidencia_cliente_interna(
        nombre_documental="COMERCIAL ANDE", rut_documental="",
        numero_guia="1", numero_transporte="1", carpeta_catalogos=carpeta,
    )
    assert evs == ()


# ==========================================================================
# 5. Patente variante + relación humana fuerte chofer↔vehículo -> resolver
# ==========================================================================


def test_5_patente_variante_con_confirmacion_humana_del_chofer_es_evidencia(tmp_path):
    carpeta = _carpeta(tmp_path)
    _confirmar_vehiculo(carpeta, "JD8659", TipoVehiculo.CARRO, rut_chofer_asociado="15489424-1")
    _confirmar_vehiculo(carpeta, "JE8659", TipoVehiculo.CARRO)  # confirmada, pero NO de este chofer

    fila = {
        "patente_rampla": "JD8629", "rut_chofer": "15489424-1",
        "numero_transporte": "0000354870", "numero_guia": "472477", "estado_procesamiento": "OK",
    }
    evs = recopilar_evidencia_vehiculo("patente_rampla")(fila, [fila], carpeta_catalogos=carpeta)
    valores = {e.valor for e in evs}
    assert "JD8659" in valores
    assert "JE8659" not in valores  # nunca un competidor no asociado a este RUT
    humana = next(e for e in evs if e.valor == "JD8659")
    assert humana.es_decision_humana is True

    contexto = _contexto("patente_rampla", "JD8629", evs, rut_chofer="15489424-1")
    assert validar_hipotesis_multicampo(_propuesta(contexto, "JD8659"), contexto).aceptada
    # "2↔5" NO es una confusión OCR global: una patente distinta sin
    # respaldo sigue bloqueada.
    assert not validar_hipotesis_multicampo(_propuesta(contexto, "JX1234"), contexto).aceptada


# ==========================================================================
# 6. Patente variante con dos vehículos plausibles -> revisión
# ==========================================================================


def test_6_patente_variante_dos_candidatos_no_resuelve_sola(tmp_path):
    carpeta = _carpeta(tmp_path)
    # Dos ramplas confirmadas para el MISMO RUT: ninguna gana sola.
    _confirmar_vehiculo(carpeta, "JD8659", TipoVehiculo.CARRO, rut_chofer_asociado="15489424-1")
    _confirmar_vehiculo(carpeta, "JD8658", TipoVehiculo.CARRO, rut_chofer_asociado="15489424-1")
    evs = evidencia_vehiculo_interna(
        campo="patente_rampla", valor_documental="JD8629", rut_chofer="15489424-1",
        numero_transporte="T", filas=[], carpeta_catalogos=carpeta,
    )
    valores = sorted(e.valor for e in evs)
    assert valores == ["JD8658", "JD8659"]  # ambos candidatos expuestos, ninguno único


# ==========================================================================
# 10. B1 recibe evidencia interna no vacía cuando existe (colector real)
# ==========================================================================


def test_10_colector_cliente_entrega_evidencia_interna(tmp_path):
    carpeta = _carpeta(tmp_path)
    _crear_cliente(carpeta, razon_social="PRODALAM SA", rut="93.772.000-9")
    fila = {
        "cliente": "PRODALAM SA", "rut_cliente": "No encontrado",
        "numero_guia": "472477", "numero_transporte": "0000354870",
    }
    evs = recopilar_evidencia_cliente("cliente")(fila, [fila], carpeta_catalogos=carpeta)
    assert any(e.valor == "PRODALAM SA" for e in evs)


# ==========================================================================
# 11 / 12. Propuesta respaldada aplica; propuesta sin respaldo sigue bloqueada
# ==========================================================================


def test_11_propuesta_respaldada_por_conocimiento_interno_pasa_el_gate(tmp_path):
    carpeta = _carpeta(tmp_path)
    _confirmar_vehiculo(carpeta, "JD8659", TipoVehiculo.CARRO, rut_chofer_asociado="15489424-1")
    evs = evidencia_vehiculo_interna(
        campo="patente_rampla", valor_documental="JD8629", rut_chofer="15489424-1",
        numero_transporte="T", filas=[], carpeta_catalogos=carpeta,
    )
    contexto = _contexto("patente_rampla", "JD8629", evs, rut_chofer="15489424-1")
    assert validar_hipotesis_multicampo(_propuesta(contexto, "JD8659"), contexto).aceptada


def test_12_propuesta_sin_respaldo_sigue_bloqueada():
    contexto = _contexto("cliente", "ALGO SA", ())
    resultado = validar_hipotesis_multicampo(_propuesta(contexto, "INVENTADO SA"), contexto)
    assert not resultado.aceptada
    assert resultado.motivo_rechazo == MOTIVO_VALOR_NO_RESPALDADO


# ==========================================================================
# 13. B1 abstención -> humano (el validador nunca convierte abstención en error)
# ==========================================================================


def test_13_abstencion_siempre_aceptada_estructuralmente():
    contexto = _contexto("obra_destino", "OBRA RARA", ())
    hipotesis = HipotesisIA(
        hipotesis_id=calcular_hipotesis_id(contexto, ""), campo="obra_destino",
        valor_observado="OBRA RARA", valor_propuesto="", resultado=RESULTADO_HIPOTESIS_ABSTENCION,
    )
    assert validar_hipotesis_multicampo(hipotesis, contexto).aceptada


# ==========================================================================
# Control anti-alucinación: nombre basura nunca produce evidencia de cliente
# ==========================================================================


def test_control_nombre_basura_no_produce_evidencia_cliente(tmp_path):
    carpeta = _carpeta(tmp_path)
    _crear_cliente(carpeta, razon_social="PRODALAM SA", rut="93.772.000-9")
    evs = evidencia_cliente_interna(
        nombre_documental="EMPRESA QUE NO EXISTE XYZ SPA", rut_documental="",
        numero_guia="1", numero_transporte="1", carpeta_catalogos=carpeta,
    )
    assert evs == ()
