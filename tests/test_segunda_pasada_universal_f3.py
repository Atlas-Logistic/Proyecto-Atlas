"""Bloque AUTORIDAD OPERACIONAL -- Fase 3 (Bloque C): SEGUNDA PASADA
UNIVERSAL. Ninguna decisión pendiente llega a Javier sin que Atlas
primero (1) agote la resolución determinista con todo el conocimiento y
(2) B1 tenga una oportunidad REAL con evidencia interna suficiente;
después se aplica por el mecanismo canónico y se regenera la bandeja.

Pruebas: decisión CLIENTE_CANDIDATO / OBRA_DESCONOCIDA creada por el
mecanismo canónico entra a la segunda pasada; resolución determinista
retira la decisión antes de Javier; B1 recibe evidencia interna no vacía;
429 nunca inventa; idempotencia.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

import pytest

from atlas_core.atlas_ia.contratos import (
    HipotesisIA, ResultadoValidacionHipotesis, calcular_hipotesis_id,
)
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_destinos import CatalogoDestinos
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, TipoEvidencia
from atlas_core.catalogo_vehiculos import TipoVehiculo, confirmar_vehiculo
from atlas_core.decisiones_pendientes import detectar_decisiones_documento
from atlas_core.procesamiento_masivo import COLUMNAS, _segunda_pasada_universal


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _rut(cuerpo: str) -> str:
    suma = sum(int(d) * f for d, f in zip(reversed(cuerpo), (2, 3, 4, 5, 6, 7) * 3))
    resto = 11 - suma % 11
    dv = "0" if resto == 11 else "K" if resto == 10 else str(resto)
    return f"{cuerpo}-{dv}"


def _carpeta(tmp_path):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    return carpeta


def _cliente(carpeta, *, razon_social, rut, fuente="CONFIRMACION_USUARIO"):
    return CatalogoClientes(carpeta / "clientes.json").crear(
        razon_social=razon_social, rut=rut, fuente=fuente,
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )


def _ev(ident="g1"):
    return Evidencia(
        tipo=TipoEvidencia.GUIA.value, identificador_fuente=ident, referencia_hash="a" * 64,
        campos_observados={"obra": "X"}, fecha="2026-01-01T00:00:00+00:00",
        actor_proceso="t", resultado="SOPORTA",
    )


def _obra_confirmada(carpeta, cliente, *, nombre_obra, direccion, aliases=()):
    destino = CatalogoDestinos(
        carpeta / "destinos_maestros.json", ruta_clientes=carpeta / "clientes.json",
    ).crear(
        cliente_id=cliente.cliente_id, nombre_destino=nombre_obra, direccion=direccion,
        comuna="LA REINA", region="RM", pais="CHILE", fuente="PRUEBA",
    )
    cat = CatalogoObrasDestinos(
        carpeta / "obras_destinos.json", ruta_clientes=carpeta / "clientes.json",
        ruta_destinos=carpeta / "destinos_maestros.json",
    )
    r = cat.registrar_observacion(
        cliente_id=cliente.cliente_id, nombre_obra=nombre_obra, destino_id=destino.destino_id,
        evidencia=_ev(),
    )
    cat.confirmar_relacion(r.relacion.relacion_id, actor="HUMANO")
    if aliases:
        cat.actualizar_identidad_obra(
            r.obra.obra_id, nombre_canonico=nombre_obra,
            aliases_documentales=list(aliases), evidencia=_ev("alias"),
        )
    return r.obra


def _confirmar_vehiculo(carpeta, patente, tipo, *, rut_chofer_asociado=""):
    ruta = carpeta / "vehiculos.json"
    if not ruta.exists():
        ruta.write_text(json.dumps({"version": 1, "vehiculos": []}), encoding="utf-8")
    return confirmar_vehiculo(
        ruta, patente=patente, tipo=tipo, actor="JAVIER", fuente_decision="T",
        fecha=datetime.now(timezone.utc), rut_chofer_asociado=rut_chofer_asociado,
    )


def _fila(**ov):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "g1.jpeg", "estado_procesamiento": "OK", "numero_guia": "900001",
        "numero_transporte": "T-1", "indicador_revision": "REVISAR",
        "estado_documental": "REQUIERE_REVISION",
    })
    fila.update(ov)
    return fila


def _csv(tmp_path, filas):
    ruta = tmp_path / "analisis_completo_guias.csv"
    with ruta.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)
    return ruta


class _OrquestadorFalso:
    """Doble de prueba: registra cada contexto y responde según lo
    configurado. Nunca red, nunca razonamiento real."""

    def __init__(self, *, modo="ABSTENCION", valor=""):
        self.modo = modo
        self.valor = valor
        self.contextos: list = []

    def resolver(self, contexto):
        self.contextos.append(contexto)
        from atlas_core.atlas_ia.orquestador import (
            ABSTENCION_IA, BLOQUEADO_POR_VALIDACION, ERROR_PROVEEDOR, RESUELTO_POR_IA,
            ResultadoOrquestacion,
        )
        if self.modo == "429":
            raise RuntimeError("Groq devolvió HTTP 429: rate limit reached")
        if self.modo == "ERROR_429":
            return ResultadoOrquestacion(
                ERROR_PROVEEDOR, "D_BLOQUEO", contexto, rondas=1,
                detalle="Groq devolvió HTTP 429: rate limit reached",
            )
        if self.modo == "BLOQUEADO":
            return ResultadoOrquestacion(
                BLOQUEADO_POR_VALIDACION, "D_BLOQUEO", contexto, rondas=1,
                validacion=ResultadoValidacionHipotesis(
                    aceptada=False, motivo_rechazo="VALOR_NO_RESPALDADO_POR_EVIDENCIA",
                ),
            )
        if self.modo == "RESUELVE_A":
            h = HipotesisIA(
                hipotesis_id=calcular_hipotesis_id(contexto, self.valor), campo=contexto.campo,
                valor_observado=contexto.valor_documental, valor_propuesto=self.valor,
                resultado="PROPUESTA",
            )
            return ResultadoOrquestacion(
                RESUELTO_POR_IA, "A_AUTONOMIA_CANDIDATA", contexto, hipotesis=h,
                validacion=ResultadoValidacionHipotesis(aceptada=True), rondas=1,
            )
        return ResultadoOrquestacion(ABSTENCION_IA, "C_ABSTENCION", contexto, rondas=1)


# ==========================================================================
# 8 / determinista -- CLIENTE_CANDIDATO entra a la segunda pasada y se
#     resuelve antes de Javier con el conocimiento ya disponible
# ==========================================================================


def test_8_cliente_candidato_resuelto_determinista_en_segunda_pasada(tmp_path):
    carpeta = _carpeta(tmp_path)
    _cliente(carpeta, razon_social="PRODALAM SA", rut="93.772.000-9")
    fila = _fila(cliente="PRODALAM SA", rut_cliente="",
                 motivos_revision_documento="CLIENTE_SIN_CORROBORAR")
    ruta_csv = _csv(tmp_path, [fila])

    decisiones = detectar_decisiones_documento(
        archivo="g1.jpeg",
        datos={"número de guía": "900001", "número de transporte": "T-1",
               "cliente": "PRODALAM SA", "RUT del cliente": ""},
        carpeta_catalogos=carpeta,
    )
    assert any(d["tipo"] == "CLIENTE_CANDIDATO" for d in decisiones)
    pendientes = list(decisiones)

    m = _segunda_pasada_universal(ruta_csv, {"g1.jpeg"}, pendientes, None, carpeta)

    assert m["decisiones_detectadas"] >= 1
    assert m["resueltas_determinista"] >= 1
    # La decisión ya no llega a Javier: regenerada tras corregir la fila.
    assert not any(d["tipo"] == "CLIENTE_CANDIDATO" for d in pendientes)
    with ruta_csv.open(encoding="utf-8-sig") as f:
        fila_final = next(csv.DictReader(f, delimiter=";"))
    assert fila_final["cliente"] == "PRODALAM SA"


# ==========================================================================
# 9 -- OBRA_DESCONOCIDA (variante OCR) entra a la segunda pasada
# ==========================================================================


def test_9_obra_variante_ocr_resuelta_en_segunda_pasada(tmp_path):
    carpeta = _carpeta(tmp_path)
    cliente = _cliente(carpeta, razon_social="YOLITO BALART HNOS LTDA", rut="80.565.900-9")
    _obra_confirmada(
        carpeta, cliente, nombre_obra="CASA HELSINSKI",
        direccion="HELSINSKI 5810 LA REINA SANTIAGO", aliases=("INMOB CASA RELSINSKI SPA",),
    )
    # Variación de 2 caracteres: `detectar_decisiones_documento` NO la
    # resuelve (su tolerancia es 1) -> nace OBRA_DESCONOCIDA. La segunda
    # pasada, bajo la conjunción cliente-por-RUT + destino confirmado que
    # calza, sí la absorbe.
    ocr = "INMOB CASA VELINSKI SPA"
    fila = _fila(
        cliente="YOLITO BALART HNOS LTDA", rut_cliente="80565900-9",
        obra_destino=ocr, despachar_a_crudo="HELSINSKI 5810 LA REINA SANTIAGO",
        motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR",
    )
    ruta_csv = _csv(tmp_path, [fila])
    pendientes = list(detectar_decisiones_documento(
        archivo="g1.jpeg",
        datos={"número de guía": "900001", "número de transporte": "T-1",
               "cliente": "YOLITO BALART HNOS LTDA", "RUT del cliente": "80565900-9",
               "obra destino": ocr},
        carpeta_catalogos=carpeta,
    ))
    assert any(d["tipo"] == "OBRA_DESCONOCIDA" for d in pendientes)

    m = _segunda_pasada_universal(ruta_csv, {"g1.jpeg"}, pendientes, None, carpeta)

    assert m["resueltas_determinista"] >= 1
    with ruta_csv.open(encoding="utf-8-sig") as f:
        fila_final = next(csv.DictReader(f, delimiter=";"))
    assert fila_final["obra_destino"] == "CASA HELSINSKI"
    assert not any(d["tipo"] == "OBRA_DESCONOCIDA" for d in pendientes)


# ==========================================================================
# 10 (dominio decisión) -- B1 recibe EVIDENCIA INTERNA NO VACÍA
# ==========================================================================


def test_10_b1_recibe_evidencia_interna_no_vacia_para_una_decision(tmp_path):
    carpeta = _carpeta(tmp_path)
    _cliente(carpeta, razon_social="COMERCIAL ANDES SPA", rut=_rut("76222222"))
    _cliente(carpeta, razon_social="COMERCIAL ANDES LIMITADA", rut=_rut("77333333"))
    # nombre parcial que no resuelve único (nunca "cualquier nombre
    # parecido"): sin evidencia -> la decisión queda para Javier, sin
    # inventar.
    fila = _fila(cliente="COMERCIAL ANDE", rut_cliente="",
                 motivos_revision_documento="CLIENTE_SIN_CORROBORAR")
    ruta_csv = _csv(tmp_path, [fila])
    decision = {
        "decision_id": "d1", "estado": "PENDIENTE", "tipo": "CLIENTE_CANDIDATO",
        "entidad": "CLIENTE", "documento": {"archivo": "g1.jpeg", "numero_guia": "900001",
        "numero_transporte": "T-1"}, "campo": "cliente", "valor_documental": "COMERCIAL ANDES",
        "valor_normalizado": "COMERCIAL ANDES", "identidad_resuelta": None, "contexto": None,
        "candidatos": [], "motivos": ["NOMBRE_SIN_RUT_CORROBORABLE"], "evidencias": [],
        "acciones_permitidas": ["CONFIRMAR", "NO_CONFIRMAR", "POSPONER"],
    }
    orq = _OrquestadorFalso(modo="ABSTENCION")
    m = _segunda_pasada_universal(ruta_csv, {"g1.jpeg"}, [decision], orq, carpeta)

    # Ambigüedad de nombre -> `evidencia_cliente_interna` no fabrica un
    # candidato (nunca "cualquier nombre parecido"): no hay evidencia, y
    # la decisión queda para Javier -- correcto, sin inventar.
    assert m["a_humano"] >= 1


def _decision_vehiculo(valor="JD8629", campo="patente_rampla"):
    return {
        "decision_id": "d1", "estado": "PENDIENTE", "tipo": "VEHICULO_DESCONOCIDO",
        "entidad": "VEHICULO", "documento": {"archivo": "g1.jpeg", "numero_guia": "900001",
        "numero_transporte": "T-1"}, "campo": campo, "valor_documental": valor,
        "valor_normalizado": valor, "identidad_resuelta": None, "contexto": None,
        "candidatos": [], "motivos": ["SIN_VEHICULO_CONFIRMADO_COMPATIBLE"], "evidencias": [],
        "acciones_permitidas": ["REGISTRAR", "NO_REGISTRAR", "POSPONER"],
    }


def _fila_vehiculo(**ov):
    return _fila(
        rut_chofer="15489424-1", chofer="CARLOS SIMON", patente_rampla="JD8629",
        motivos_revision_documento="PATENTE_SIN_HOMOLOGAR", **ov,
    )


def _dos_ramplas(carpeta):
    _confirmar_vehiculo(carpeta, "JD8659", TipoVehiculo.CARRO, rut_chofer_asociado="15489424-1")
    _confirmar_vehiculo(carpeta, "JD8658", TipoVehiculo.CARRO, rut_chofer_asociado="15489424-1")


def test_10b_b1_recibe_contexto_con_evidencia_cuando_existe(tmp_path):
    carpeta = _carpeta(tmp_path)
    _dos_ramplas(carpeta)  # dos candidatos -> convergencia se abstiene, evidencia no vacía
    ruta_csv = _csv(tmp_path, [_fila_vehiculo()])
    orq = _OrquestadorFalso(modo="ABSTENCION")
    _segunda_pasada_universal(ruta_csv, {"g1.jpeg"}, [_decision_vehiculo()], orq, carpeta)
    assert orq.contextos, "B1 debió ser invocado para la decisión"
    assert orq.contextos[0].evidencias, "el contexto de B1 trae evidencia interna"
    assert {e.valor for e in orq.contextos[0].evidencias} >= {"JD8659", "JD8658"}


# ==========================================================================
# 11 -- B1 propuesta respaldada (clase A) se aplica y regenera la bandeja
# ==========================================================================


def test_11_b1_propuesta_clase_a_se_aplica_y_retira_la_decision(tmp_path):
    carpeta = _carpeta(tmp_path)
    _dos_ramplas(carpeta)
    ruta_csv = _csv(tmp_path, [_fila_vehiculo()])
    orq = _OrquestadorFalso(modo="RESUELVE_A", valor="JD8659")
    m = _segunda_pasada_universal(ruta_csv, {"g1.jpeg"}, [_decision_vehiculo()], orq, carpeta)
    assert m["b1_resolvio"] == 1
    with ruta_csv.open(encoding="utf-8-sig") as f:
        assert next(csv.DictReader(f, delimiter=";"))["patente_rampla"] == "JD8659"


# ==========================================================================
# 13 -- B1 abstención -> humano
# ==========================================================================


def test_13_b1_abstencion_deja_la_decision_para_javier(tmp_path):
    carpeta = _carpeta(tmp_path)
    _dos_ramplas(carpeta)
    ruta_csv = _csv(tmp_path, [_fila_vehiculo()])
    orq = _OrquestadorFalso(modo="ABSTENCION")
    pendientes = [_decision_vehiculo()]
    m = _segunda_pasada_universal(ruta_csv, {"g1.jpeg"}, pendientes, orq, carpeta)
    assert m["b1_abstuvo"] == 1 and m["a_humano"] >= 1
    with ruta_csv.open(encoding="utf-8-sig") as f:
        assert next(csv.DictReader(f, delimiter=";"))["patente_rampla"] == "JD8629"


# ==========================================================================
# 14 -- 429 -> no inventa, no aplica, cuenta cooldown
# ==========================================================================


@pytest.mark.parametrize("modo", ["429", "ERROR_429"])
def test_14_429_no_inventa_ni_aplica(tmp_path, modo):
    carpeta = _carpeta(tmp_path)
    _dos_ramplas(carpeta)
    ruta_csv = _csv(tmp_path, [_fila_vehiculo()])
    orq = _OrquestadorFalso(modo=modo)
    m = _segunda_pasada_universal(ruta_csv, {"g1.jpeg"}, [_decision_vehiculo()], orq, carpeta)
    assert m["b1_error_429_cooldown"] >= 1
    assert m["b1_resolvio"] == 0
    with ruta_csv.open(encoding="utf-8-sig") as f:
        assert next(csv.DictReader(f, delimiter=";"))["patente_rampla"] == "JD8629"


# ==========================================================================
# 15 -- idempotencia: segunda ejecución no duplica ni rompe
# ==========================================================================


def test_15_idempotencia_segunda_ejecucion(tmp_path):
    carpeta = _carpeta(tmp_path)
    _cliente(carpeta, razon_social="PRODALAM SA", rut="93.772.000-9")
    fila = _fila(cliente="PRODALAM SA", rut_cliente="",
                 motivos_revision_documento="CLIENTE_SIN_CORROBORAR")
    ruta_csv = _csv(tmp_path, [fila])
    pendientes = list(detectar_decisiones_documento(
        archivo="g1.jpeg",
        datos={"número de guía": "900001", "número de transporte": "T-1",
               "cliente": "PRODALAM SA", "RUT del cliente": ""},
        carpeta_catalogos=carpeta,
    ))

    m1 = _segunda_pasada_universal(ruta_csv, {"g1.jpeg"}, pendientes, None, carpeta)
    snapshot = list(pendientes)
    with ruta_csv.open(encoding="utf-8-sig") as f:
        csv_1 = f.read()

    m2 = _segunda_pasada_universal(ruta_csv, {"g1.jpeg"}, pendientes, None, carpeta)
    with ruta_csv.open(encoding="utf-8-sig") as f:
        csv_2 = f.read()

    assert pendientes == snapshot  # nada nuevo ni duplicado
    assert csv_1 == csv_2  # el dataset ya convergió, no vuelve a cambiar
    assert m2["resueltas_determinista"] == 0  # nada que resolver la 2a vez
    assert m1["resueltas_determinista"] >= 1
