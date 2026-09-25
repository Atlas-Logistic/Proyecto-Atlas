"""Vía humana visible para pendientes agotados + comuna documental válida.

Regresiones de dos defectos demostrados sobre la operación real:
1. Un AGOTABLE agotado anunciaba ESPERANDO_ACCION_HUMANA sin tarjeta.
2. Una variante OCR inválida de la comuna desplazaba a la comuna válida
   que el mismo documento traía.
Todo sobre `tmp_path`, proveedores simulados, sin red.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from atlas_core import mantenimiento_pendientes_tecnicos as mantenimiento
from atlas_core import reconciliacion_estado_derivado as reconciliacion
from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.catalogo_destinos import CatalogoDestinos
from atlas_core.rutas.destino_entrega import (
    comuna_territorial_desde_evidencia, textos_documentales_destino,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from atlas_core.revalidacion_documental import revalidar_ruta_sin_destino_calculado_sin_ocr
from test_ciclo_pendientes_tecnicos_simulado import AHORA, DIRECCION, Operacion, _escribir_csv, _fila
from test_destinos_confirmacion_r34 import _entorno as _entorno_r34, _fila_csv as _fila_r34

AGOTABLE = "COORDENADA_NO_CONFIRMADA(5)"


def _b1_con_direccion(texto: str) -> str:
    """Traza B1 persistida mínima: identidad operacional del documento."""
    return json.dumps([{"contexto_final": {"identidad_operacional": {"direccion_entrega": texto}}}])


def _tarjetas(op: Operacion, guia: str) -> list[dict]:
    return [d for d in op.decisiones() if d["documento"]["numero_guia"] == guia]


def _sin_limbo(op: Operacion) -> None:
    """Invariante: ningún pendiente anuncia acción humana sin tarjeta."""
    con_tarjeta = {d["documento"]["numero_guia"] for d in op.decisiones() if d.get("estado") == "PENDIENTE"}
    for guia, registro in op.pendientes().items():
        if registro.get("estado_espera") == "ESPERANDO_ACCION_HUMANA":
            assert guia in con_tarjeta, guia


@pytest.fixture
def op(tmp_path):
    return Operacion(tmp_path)


# ------------------------------------- 1. AGOTABLE agotado => tarjeta visible


def test_1_agotable_agotado_con_identidad_confirmada_publica_tarjeta(op):
    op.confirmar_destino_de_obra(con_coordenadas=False)
    op.sembrar([_fila("480001", AGOTABLE, op.planta_id)], intentos=2)
    op.mantener()  # 3er intento: agota
    tarjetas = _tarjetas(op, "480001")
    assert [t["tipo"] for t in tarjetas] == ["DESTINO_NO_RESUELTO"]
    assert "REGISTRAR_DIRECCION" in tarjetas[0]["acciones_permitidas"]
    assert tarjetas[0]["motivos"] == ["COORDENADA_NO_CONFIRMADA"]
    # La pregunta no es la identidad (ya confirmada) sino su ubicación.
    assert tarjetas[0]["contexto"]["identidad_destino_confirmada"] is True
    assert tarjetas[0]["contexto"]["falta"] == "UBICACION_RUTEABLE"
    assert "480001" not in op.pendientes()


def test_1b_antes_del_limite_no_hay_tarjeta_ni_limbo(op):
    op.confirmar_destino_de_obra(con_coordenadas=False)
    op.sembrar([_fila("480001", AGOTABLE, op.planta_id)], intentos=0)
    op.mantener()
    assert _tarjetas(op, "480001") == []
    assert op.pendientes()["480001"]["estado_espera"] == "ESPERANDO_COOLDOWN"


# ------------------------- 2. nunca ESPERANDO_ACCION_HUMANA sin tarjeta


def test_2_invariante_en_un_dia_completo_de_mantenimiento(op):
    op.confirmar_destino_de_obra(con_coordenadas=False)
    op.sembrar([
        _fila("480001", AGOTABLE, op.planta_id),
        _fila("480002", "GEOCODIFICACION_SIN_CONEXION", op.planta_id),
        _fila("480003", "GEOCODIFICACION_NUMERO_INCOMPATIBLE: 38 != 3800", op.planta_id),
    ], intentos=0)
    for paso in range(0, 24 * 60, 5):
        op.mantener(AHORA + timedelta(minutes=paso))
        _sin_limbo(op)


def test_2b_sin_pregunta_publicable_queda_evidencia_nueva_con_causa(op):
    """Un DETERMINISTA cuya tarjeta la política suprime (identidad ya
    respondida) no puede anunciar acción humana: queda esperando evidencia
    con causa explícita."""
    op.confirmar_destino_de_obra(con_coordenadas=False)
    op.sembrar([_fila("480003", "GEOCODIFICACION_NUMERO_INCOMPATIBLE: 38 != 3800", op.planta_id)])
    op.mantener()
    registro = op.pendientes()["480003"]
    assert registro["estado_espera"] == "ESPERANDO_EVIDENCIA_NUEVA"
    assert registro["causa_siguiente_accion"] == reconciliacion.CAUSA_SIN_PREGUNTA_HUMANA_PUBLICABLE
    assert _tarjetas(op, "480003") == []


def test_2c_helper_de_reconciliacion_publica_o_degrada(op):
    op.confirmar_destino_de_obra(con_coordenadas=False)
    op.sembrar([_fila("480001", AGOTABLE, op.planta_id)], intentos=3)
    registros = list(op.pendientes().values())
    for r in registros:
        r["estado_espera"] = "ESPERANDO_ACCION_HUMANA"
    persistidos = []
    resultado = reconciliacion._asegurar_via_humana(
        raiz=op.raiz, registros=registros, previos={}, instante=AHORA,
        persistir=lambda regs: persistidos.append(regs) or op.escribir_pendientes(regs),
    )
    assert resultado == []  # con tarjeta: sale de la cola técnica
    assert persistidos  # la detección leyó los intentos vigentes
    assert [t["tipo"] for t in _tarjetas(op, "480001")] == ["DESTINO_NO_RESUELTO"]


# ------------------------------------------------- 3. sin duplicados


def test_3_ejecuciones_repetidas_no_duplican_tarjeta_ni_reescriben(op, monkeypatch):
    op.confirmar_destino_de_obra(con_coordenadas=False)
    op.sembrar([
        _fila("480001", AGOTABLE, op.planta_id),
        _fila("480003", "GEOCODIFICACION_NUMERO_INCOMPATIBLE: 38 != 3800", op.planta_id),
    ], intentos=3)
    op.mantener()
    ids = [t["decision_id"] for t in _tarjetas(op, "480001")]
    assert len(ids) == 1
    decisiones = (op.actual / "decisiones_pendientes.json").read_bytes()
    pendientes = (op.actual / "pendientes_tecnicos.json").read_bytes()
    llamadas = []
    original = reconciliacion.reconciliar_decisiones_destino_no_resuelto
    monkeypatch.setattr(reconciliacion, "reconciliar_decisiones_destino_no_resuelto",
                        lambda **kw: llamadas.append(kw) or original(**kw))
    for minutos in (5, 10, 60, 24 * 60):
        assert op.mantener(AHORA + timedelta(minutes=minutos))["motivo"] == "SIN_ELEGIBLES"
    assert [t["decision_id"] for t in _tarjetas(op, "480001")] == ids
    assert (op.actual / "decisiones_pendientes.json").read_bytes() == decisiones
    assert (op.actual / "pendientes_tecnicos.json").read_bytes() == pendientes
    assert llamadas == []  # la degradación previa no se re-evalúa sin cambios


# ----------------------------- 4. confirmación humana previa bien leída


def test_4_registrar_direccion_previa_no_se_vuelve_a_preguntar(op):
    op.confirmar_destino_de_obra(con_coordenadas=False)
    (op.actual / "decisiones_aplicadas.json").write_text(json.dumps({"aplicaciones": [{
        "decision_id": "r-1", "tipo": "DESTINO_NO_RESUELTO", "accion": "REGISTRAR_DIRECCION",
        "documento": {"numero_guia": "480001"},
    }]}), encoding="utf-8")
    op.sembrar([_fila("480001", AGOTABLE, op.planta_id)], intentos=3)
    op.mantener()
    assert _tarjetas(op, "480001") == []
    registro = op.pendientes()["480001"]
    assert registro["estado_espera"] == "ESPERANDO_EVIDENCIA_NUEVA"
    assert registro["causa_siguiente_accion"] == "DIRECCION_CONFIRMADA_POR_HUMANO__GEOCODER_NO_RESUELVE"


def test_4b_identidad_confirmada_con_ubicacion_no_pregunta(op):
    """Destino confirmado CON coordenada: ya es ruteable, no hay acción
    humana que pedir (se resuelve por conocimiento interno)."""
    op.confirmar_destino_de_obra(con_coordenadas=True)
    op.sembrar([_fila("480001", AGOTABLE, op.planta_id)], intentos=2)
    resultado = op.mantener()
    assert resultado["resueltas"] == ["480001"]
    assert _tarjetas(op, "480001") == []


def test_4c_identidad_confirmada_sin_ubicacion_si_pregunta_otra_cosa(op):
    op.confirmar_destino_de_obra(con_coordenadas=False)
    op.sembrar([_fila("480001", AGOTABLE, op.planta_id)], intentos=3)
    op.mantener()
    (tarjeta,) = _tarjetas(op, "480001")
    assert tarjeta["contexto"]["falta"] == "UBICACION_RUTEABLE"


# --------------------------- 5. variante OCR inválida + comuna válida


def test_5_helper_conserva_la_comuna_valida_de_la_evidencia():
    evidencia = ["LOS ALERCES 120", "LOS ALERCES 120 PUDAHEL PUDAHUEL"]
    assert comuna_territorial_desde_evidencia("PUDAHEL", evidencia) == "Pudahuel"
    assert comuna_territorial_desde_evidencia("", evidencia) == "Pudahuel"
    assert comuna_territorial_desde_evidencia("XQZW", evidencia) == "Pudahuel"
    # Una comuna declarada válida siempre se respeta tal cual.
    assert comuna_territorial_desde_evidencia("MAIPU", evidencia) == "MAIPU"
    # Sin evidencia, una variante segura del motor territorial igual sirve.
    assert comuna_territorial_desde_evidencia("PUDAHEL", []) == "Pudahuel"
    # Nunca inventa.
    assert comuna_territorial_desde_evidencia("XQZW", []) == ""


def test_5b_textos_documentales_incluyen_traza_b1_persistida():
    fila = {"despachar_a_crudo": "LOS ALERCES 120", "direccion_entrega": "",
            "resultado_atlas_ia_json": _b1_con_direccion("LOS ALERCES 120 PUDAHEL PUDAHUEL")}
    assert textos_documentales_destino(fila) == ("LOS ALERCES 120", "LOS ALERCES 120 PUDAHEL PUDAHUEL")
    assert textos_documentales_destino({"resultado_atlas_ia_json": "no-json"}) == ()


def test_5c_tarjeta_sugiere_la_comuna_valida_aunque_el_catalogo_tenga_la_variante(op):
    destino_id = op.confirmar_destino_de_obra(con_coordenadas=False)
    catalogo = op.catalogos / "destinos_maestros.json"
    contenido = json.loads(catalogo.read_text(encoding="utf-8"))
    for d in contenido["destinos"]:
        if d["destino_id"] == destino_id:
            d["comuna"] = "PUDAHEL"  # variante inválida ya aprendida
    catalogo.write_text(json.dumps(contenido), encoding="utf-8")
    op.sembrar([_fila("480001", AGOTABLE, op.planta_id,
                      resultado_atlas_ia_json=_b1_con_direccion(f"{DIRECCION} PUDAHEL PUDAHUEL"))], intentos=3)
    op.mantener()
    (tarjeta,) = _tarjetas(op, "480001")
    assert tarjeta["contexto"]["comuna_sugerida"] == "Pudahuel"
    # No se inventan coordenadas ni se reescribe el catálogo.
    destino = op.destinos.obtener(destino_id)
    assert destino.latitud is None and destino.longitud is None and destino.comuna == "PUDAHEL"


class _ProveedorQueAnota(ProveedorRutasSimulado):
    def __init__(self):
        super().__init__(geocodificaciones={})
        self.consultas: list[str] = []

    def geocodificar(self, direccion):
        self.consultas.append(direccion)
        return super().geocodificar(direccion)


def test_5d_reintento_geocodifica_con_la_comuna_valida_no_con_la_variante(op):
    destino_id = op.confirmar_destino_de_obra(con_coordenadas=False)
    catalogo = op.catalogos / "destinos_maestros.json"
    contenido = json.loads(catalogo.read_text(encoding="utf-8"))
    for d in contenido["destinos"]:
        if d["destino_id"] == destino_id:
            d["comuna"] = "PUDAHEL"
    catalogo.write_text(json.dumps(contenido), encoding="utf-8")
    _escribir_csv(op.dataset, [_fila("480001", AGOTABLE, op.planta_id,
                                     resultado_atlas_ia_json=_b1_con_direccion(f"{DIRECCION} PUDAHEL PUDAHUEL"))])
    proveedor, respaldo = _ProveedorQueAnota(), _ProveedorQueAnota()
    revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=op.dataset, carpeta_catalogos=op.catalogos,
        proveedor_rutas=proveedor, proveedor_rutas_fallback=respaldo, guias_objetivo={"480001"},
    )
    consultas = proveedor.consultas + respaldo.consultas
    assert consultas and all("PUDAHEL " not in f"{c} " for c in consultas)
    assert any("Pudahuel" in c for c in proveedor.consultas)


def test_5e_confirmar_destino_aprende_la_comuna_valida_documental(tmp_path):
    fila = _fila_r34(despachar_a_crudo="LOS ALERCES 120",
                     resultado_atlas_ia_json=_b1_con_direccion("LOS ALERCES 120 PUDAHEL PUDAHUEL"))
    raiz, catalogos, actual, *_resto, decision = _entorno_r34(
        tmp_path, filas_csv=[fila], destino_texto="LOS ALERCES 120")
    resultado = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR", comuna_manual="PUDAHEL",
        proveedor_rutas=ProveedorRutasSimulado(geocodificaciones={}),
        proveedor_rutas_fallback=ProveedorRutasSimulado(geocodificaciones={}),
    )
    assert resultado["ok"]
    (destino,) = CatalogoDestinos(catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json").listar()
    assert destino.comuna == "Pudahuel"
    assert destino.region  # completada desde el catálogo territorial, nunca inventada
    assert destino.latitud is None and destino.longitud is None


def test_5f_confirmar_con_comuna_valida_distinta_la_respeta(tmp_path):
    fila = _fila_r34(despachar_a_crudo="LOS ALERCES 120",
                     resultado_atlas_ia_json=_b1_con_direccion("LOS ALERCES 120 PUDAHEL PUDAHUEL"))
    raiz, catalogos, actual, *_resto, decision = _entorno_r34(
        tmp_path, filas_csv=[fila], destino_texto="LOS ALERCES 120")
    aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR", comuna_manual="Maipú",
        proveedor_rutas=ProveedorRutasSimulado(geocodificaciones={}),
        proveedor_rutas_fallback=ProveedorRutasSimulado(geocodificaciones={}),
    )
    (destino,) = CatalogoDestinos(catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json").listar()
    assert destino.comuna == "Maipú"


# ------------------------------------------- 6. ambigüedad => abstención


def test_6_dos_comunas_validas_en_la_evidencia_se_abstiene():
    assert comuna_territorial_desde_evidencia("", ["LOS ALERCES 120 MAIPU PUDAHUEL"]) == ""
    assert comuna_territorial_desde_evidencia("", ["LOS ALERCES 120 MAIPU", "LOS ALERCES 120 PUDAHUEL"]) == ""
    assert comuna_territorial_desde_evidencia("XQZW", ["LOS ALERCES 120 MAIPU", "LOS ALERCES 120 PUDAHUEL"]) == ""


def test_6b_variante_que_apunta_a_otra_comuna_que_la_documental_se_abstiene():
    assert comuna_territorial_desde_evidencia("PUDAHEL", ["LOS ALERCES 120 MAIPU"]) == ""


def test_6c_confirmar_con_evidencia_ambigua_conserva_lo_declarado(tmp_path):
    fila = _fila_r34(despachar_a_crudo="LOS ALERCES 120",
                     resultado_atlas_ia_json=_b1_con_direccion("LOS ALERCES 120 MAIPU PUDAHUEL"))
    raiz, catalogos, actual, *_resto, decision = _entorno_r34(
        tmp_path, filas_csv=[fila], destino_texto="LOS ALERCES 120")
    aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR", comuna_manual="XQZW",
        proveedor_rutas=ProveedorRutasSimulado(geocodificaciones={}),
        proveedor_rutas_fallback=ProveedorRutasSimulado(geocodificaciones={}),
    )
    (destino,) = CatalogoDestinos(catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json").listar()
    assert destino.comuna == "XQZW"  # nunca elige entre dos comunas reales
