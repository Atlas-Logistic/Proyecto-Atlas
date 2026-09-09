"""Bloque AUTORIDAD OPERACIONAL -- Fase 2 (Bloque A): criterio GENERAL de
convergencia. Un error pequeño de OCR NO puede convertir conocimiento
fuertemente establecido en desconocido; si la evidencia acumulada
converge de forma ÚNICA en un canónico dentro de una variación pequeña,
se resuelve SILENCIOSAMENTE (OCR conservado + auditado). Nunca fuzzy
libre: dos candidatos plausibles -> no resolver; contradicción documental
real -> no ocultar.

Pruebas obligatorias A-E del criterio, más la guarda DIRECCION->OBRA y la
recuperación general de RUT del cliente.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from atlas_core import procesamiento_masivo
from atlas_core.atlas_ia.convergencia import (
    CONTRADICCION_FUERTE,
    MANTENER_REVISION,
    RESOLVER_SILENCIOSO,
    SEÑAL_CATALOGO_CANONICO,
    SEÑAL_CONFIRMACION_HUMANA,
    SEÑAL_HISTORIAL_CONSISTENTE,
    CandidatoConvergencia,
    evaluar_convergencia,
)
from atlas_core.atlas_ia.evidencia_dominios import (
    convergencia_cliente,
    convergencia_obra,
    convergencia_vehiculo,
)
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_destinos import CatalogoDestinos
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, TipoEvidencia
from atlas_core.catalogo_vehiculos import TipoVehiculo, confirmar_vehiculo
from atlas_core.extractor import _parece_direccion_calle
from atlas_core.procesamiento_masivo import _convergencia_documental, procesar_archivo


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


def _evidencia(ident="g1"):
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
        evidencia=_evidencia(),
    )
    cat.confirmar_relacion(r.relacion.relacion_id, actor="HUMANO")
    if aliases:
        cat.actualizar_identidad_obra(
            r.obra.obra_id, nombre_canonico=nombre_obra,
            aliases_documentales=list(aliases), evidencia=_evidencia("alias"),
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


# ==========================================================================
# evaluar_convergencia -- núcleo del criterio de seguridad
# ==========================================================================


def _cand(valor, distancia, señales):
    return CandidatoConvergencia(valor_canonico=valor, distancia_ocr=distancia, señales=frozenset(señales))


def test_nucleo_unico_fuerte_dentro_de_tolerancia_resuelve():
    r = evaluar_convergencia(
        dominio="X", valor_ocr="JD8629", metodo="M",
        candidatos=(_cand("JD8659", 1, {SEÑAL_CONFIRMACION_HUMANA, SEÑAL_CATALOGO_CANONICO}),),
    )
    assert r.decision == RESOLVER_SILENCIOSO and r.valor_canonico == "JD8659"


def test_nucleo_dos_candidatos_plausibles_no_resuelve():
    r = evaluar_convergencia(
        dominio="X", valor_ocr="JD8629", metodo="M",
        candidatos=(
            _cand("JD8659", 1, {SEÑAL_CONFIRMACION_HUMANA, SEÑAL_CATALOGO_CANONICO}),
            _cand("JD8658", 1, {SEÑAL_CATALOGO_CANONICO}),
        ),
    )
    assert r.decision == MANTENER_REVISION
    assert set(r.competidores) == {"JD8659", "JD8658"}


def test_nucleo_variante_demasiado_lejana_no_resuelve():
    r = evaluar_convergencia(
        dominio="X", valor_ocr="GFZW99", metodo="M",
        candidatos=(_cand("JD8659", 5, {SEÑAL_CONFIRMACION_HUMANA, SEÑAL_CATALOGO_CANONICO}),),
    )
    assert r.decision == MANTENER_REVISION


def test_nucleo_un_solo_indicio_no_es_fuerte():
    r = evaluar_convergencia(
        dominio="X", valor_ocr="ABC123", metodo="M",
        candidatos=(_cand("ABC124", 1, {SEÑAL_CATALOGO_CANONICO}),),
    )
    assert r.decision == MANTENER_REVISION


def test_nucleo_contradiccion_fuerte_nunca_se_oculta():
    r = evaluar_convergencia(
        dominio="X", valor_ocr="ABC123", metodo="M",
        candidatos=(_cand("ABC124", 1, {SEÑAL_CONFIRMACION_HUMANA, SEÑAL_CATALOGO_CANONICO}),),
        contradicciones_fuertes=("el RUT es de otra empresa",),
    )
    assert r.decision == CONTRADICCION_FUERTE and r.contradiccion


# ==========================================================================
# A. Conocimiento histórico fuerte + variante OCR + candidato único -> resuelve
# ==========================================================================


def test_A_patente_variante_con_confirmacion_humana_resuelve_silencioso(tmp_path):
    carpeta = _carpeta(tmp_path)
    _confirmar_vehiculo(carpeta, "JD8659", TipoVehiculo.CARRO, rut_chofer_asociado="15489424-1")
    r = convergencia_vehiculo(
        campo="patente_rampla", valor_documental="JD8629", rut_chofer="15489424-1",
        numero_transporte="T", filas=[], carpeta_catalogos=carpeta,
    )
    assert r.decision == RESOLVER_SILENCIOSO
    assert r.valor_canonico == "JD8659"
    assert r.valor_ocr_original == "JD8629"  # OCR conservado
    assert SEÑAL_CONFIRMACION_HUMANA in r.evidencias


def test_A_obra_variante_con_cliente_y_destino_confirmados_resuelve(tmp_path):
    carpeta = _carpeta(tmp_path)
    cliente = _cliente(carpeta, razon_social="YOLITO BALART HNOS LTDA", rut="80.565.900-9")
    _obra_confirmada(
        carpeta, cliente, nombre_obra="CASA HELSINSKI",
        direccion="HELSINSKI 5810 LA REINA SANTIAGO", aliases=("INMOB CASA RELSINSKI SPA",),
    )
    r = convergencia_obra(
        nombre_documental="INMOB CASA HELSINSKI SPA", cliente_documental="INMOB CASA HELSINSKI SPA",
        rut_cliente_documental="80.565.900-9", despachar_a_documental="HELSINSKI 5810 LA REINA SANTIAGO",
        carpeta_catalogos=carpeta,
    )
    assert r.decision == RESOLVER_SILENCIOSO and r.valor_canonico == "CASA HELSINSKI"


def test_A_cliente_canonico_exacto_sin_rut_resuelve(tmp_path):
    carpeta = _carpeta(tmp_path)
    _cliente(carpeta, razon_social="PRODALAM SA", rut="93.772.000-9")
    r = convergencia_cliente(
        nombre_documental="PRODALAM SA", rut_documental="No encontrado", carpeta_catalogos=carpeta,
    )
    assert r.decision == RESOLVER_SILENCIOSO and r.valor_canonico == "PRODALAM SA"


# ==========================================================================
# B. Misma variante pero dos candidatos plausibles -> NO resolver
# ==========================================================================


def test_B_dos_ramplas_confirmadas_del_mismo_rut_no_resuelve(tmp_path):
    carpeta = _carpeta(tmp_path)
    _confirmar_vehiculo(carpeta, "JD8659", TipoVehiculo.CARRO, rut_chofer_asociado="15489424-1")
    _confirmar_vehiculo(carpeta, "JD8658", TipoVehiculo.CARRO, rut_chofer_asociado="15489424-1")
    r = convergencia_vehiculo(
        campo="patente_rampla", valor_documental="JD8629", rut_chofer="15489424-1",
        numero_transporte="T", filas=[], carpeta_catalogos=carpeta,
    )
    assert r.decision == MANTENER_REVISION


def test_B_dos_obras_del_cliente_dentro_de_variacion_no_resuelve(tmp_path):
    carpeta = _carpeta(tmp_path)
    cliente = _cliente(carpeta, razon_social="CONSTRUCTORA X SPA", rut=_rut("76111111"))
    _obra_confirmada(carpeta, cliente, nombre_obra="TORRE NORTE", direccion="ALFA 100 SANTIAGO")
    _obra_confirmada(carpeta, cliente, nombre_obra="TORRE NORESTE", direccion="ALFA 100 PROVIDENCIA")
    # "ALFA 100" calza (substring) con AMBOS destinos confirmados -> dos
    # obras dentro de una variación pequeña del nombre: nunca autoconfirma.
    # "TORRE NORSTE" está a distancia 1 de AMBAS ("NORTE" y "NORESTE"):
    # dos obras igualmente plausibles -> nunca autoconfirma.
    r = convergencia_obra(
        nombre_documental="TORRE NORSTE", cliente_documental="CONSTRUCTORA X SPA",
        rut_cliente_documental=_rut("76111111"), despachar_a_documental="ALFA 100",
        carpeta_catalogos=carpeta,
    )
    assert r.decision == MANTENER_REVISION
    assert set(r.competidores) == {"TORRE NORTE", "TORRE NORESTE"}


# ==========================================================================
# C. Variante radicalmente diferente sin respaldo -> NO resolver
# ==========================================================================


def test_C_patente_radicalmente_distinta_no_resuelve(tmp_path):
    carpeta = _carpeta(tmp_path)
    _confirmar_vehiculo(carpeta, "JD8659", TipoVehiculo.CARRO, rut_chofer_asociado="15489424-1")
    r = convergencia_vehiculo(
        campo="patente_rampla", valor_documental="GFZW99", rut_chofer="15489424-1",
        numero_transporte="T", filas=[], carpeta_catalogos=carpeta,
    )
    assert r.decision == MANTENER_REVISION


# ==========================================================================
# D. Contradicción documental fuerte -> NO esconderla
# ==========================================================================


def test_D_rut_valido_de_otra_empresa_es_contradiccion_no_resolucion(tmp_path):
    carpeta = _carpeta(tmp_path)
    _cliente(carpeta, razon_social="PRODALAM SA", rut="93.772.000-9")
    otra = _cliente(carpeta, razon_social="SODIMAC SA", rut=_rut("96792430"))
    r = convergencia_cliente(
        nombre_documental="PRODALAM SA", rut_documental=otra.rut, carpeta_catalogos=carpeta,
    )
    assert r.decision == CONTRADICCION_FUERTE
    assert "SODIMAC SA" in r.contradiccion


def test_D_patente_canonica_real_distinta_no_se_autocorrige(tmp_path):
    carpeta = _carpeta(tmp_path)
    _confirmar_vehiculo(carpeta, "JD8659", TipoVehiculo.CARRO, rut_chofer_asociado="15489424-1")
    _confirmar_vehiculo(carpeta, "JE8659", TipoVehiculo.CARRO)  # patente real de otro vehículo
    r = convergencia_vehiculo(
        campo="patente_rampla", valor_documental="JE8659", rut_chofer="15489424-1",
        numero_transporte="T", filas=[], carpeta_catalogos=carpeta,
    )
    assert r.decision == CONTRADICCION_FUERTE


# ==========================================================================
# E. El OCR original permanece trazable aunque el canónico se resuelva solo
# ==========================================================================


def test_E_ocr_original_queda_en_auditoria_de_metricas(tmp_path):
    carpeta = _carpeta(tmp_path)
    _confirmar_vehiculo(carpeta, "JD8659", TipoVehiculo.CARRO, rut_chofer_asociado="15489424-1")
    datos = {
        "número de guía": "472477", "número de transporte": "0000354870",
        "patente del carro": "JD8629", "RUT del chofer": "15489424-1",
    }
    delta = _convergencia_documental(carpeta, datos, despachar_a_documental="")
    assert delta["datos"]["patente del carro"] == "JD8659"
    assert delta["resoluciones"] == [{
        "campo": "patente_rampla", "valor_ocr": "JD8629", "valor_canonico": "JD8659",
        "metodo": "CONVERGENCIA_VEHICULO",
        "evidencias": list(delta["resoluciones"][0]["evidencias"]), "confianza": "ALTA",
    }]
    assert "CONVERGENCIA_VEHICULO" in delta["metodos_agregar"]
    assert "PATENTE_SIN_HOMOLOGAR" in delta["motivos_quitar"]


def test_E_pipeline_completo_resuelve_silencioso_y_audita(tmp_path, monkeypatch):
    carpeta = _carpeta(tmp_path)
    _confirmar_vehiculo(carpeta, "JD8659", TipoVehiculo.CARRO, rut_chofer_asociado="15489424-1")
    base = {
        "número de guía": "900777", "número de transporte": "0000900777",
        "cliente": "CLIENTE X", "obra destino": "OBRA X",
        "chofer": "CARLOS SIMON", "RUT del cliente": "No encontrado",
        "RUT del chofer": "15489424-1", "patente del tracto": "No encontrado",
        "patente del carro": "JD8629",
    }
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["DESPACHAR A CALLE 1"]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=dict(base)))
    salida = procesar_archivo(tmp_path / "g.jpg", carpeta_catalogos=carpeta, proveedor_rutas=object())

    assert salida["patente_rampla"] == "JD8659"  # canónico aplicado
    assert "PATENTE_SIN_HOMOLOGAR" not in salida["motivos_revision_documento"]
    metricas = json.loads(salida["metricas_procesamiento_json"])
    audit = metricas["resoluciones_convergentes"]
    assert audit[0]["valor_ocr"] == "JD8629"  # OCR original trazable
    assert audit[0]["valor_canonico"] == "JD8659"
    assert "CONVERGENCIA_VEHICULO" in salida["metodos_recuperacion_documento"]


# ==========================================================================
# Guarda DIRECCION -> OBRA (caso 472414 SALOMON SACK)
# ==========================================================================


@pytest.mark.parametrize("texto,esperado", [
    ("AV PRESID EDO FREI MONTALVA 9770", True),
    ("AVENIDA LAS CONDES 12000", True),
    ("TRANSPORTES Y EXCAVACIONES L", False),
    ("CASA HELSINSKI", False),
    ("CONSTRUCTORA SAN CRISTOBAL LTDA", False),
    ("AMERICAN SCREW CHILE SPA", False),
])
def test_parece_direccion_calle(texto, esperado):
    assert _parece_direccion_calle(texto) is esperado


def test_direccion_no_contamina_obra_destino_por_geometria(tmp_path, monkeypatch):
    """El bloque geométrico nunca elige, para OBRA DESTINO, un candidato
    con morfología de dirección de calle -- preserva el valor real."""
    from atlas_core.extractor import _extraer_asociaciones_geometricas

    class B:
        def __init__(self, texto, x1, y1, x2, y2):
            self.texto = texto
            self.x0, self.y0, self.x1, self.y1 = x1, y1, x2, y2
            self.bbox = (x1, y1, x2, y2)
            self.confianza = 0.99

    bloques = [
        B("OBRA DESTINO", 400, 100, 520, 120),
        B("DIRECCION", 40, 100, 130, 120),
        B("AV PRESID EDO FREI MONTALVA 9770", 140, 100, 380, 120),
        B("TRANSPORTES Y EXCAVACIONES L", 530, 100, 760, 120),
    ]
    r = _extraer_asociaciones_geometricas(bloques)
    assert r.get("obra destino") != "AV PRESID EDO FREI MONTALVA 9770"
