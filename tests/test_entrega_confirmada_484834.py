"""Confirmaciones humanas de cat?logo s?lo afectan identidad de entrega."""
from copy import deepcopy
from types import SimpleNamespace as NS

from atlas_core.identidad_entrega_confirmada import identidades_confirmadas
from atlas_core.destino_operacional import proyectar_destino
from atlas_core.gestor_viajes import agrupar_viajes

DIRECCION = "CERRO SAN LUIS 9890 B SANTIAGO"

def caso(monkeypatch):
    import atlas_core.identidad_entrega_confirmada as m
    obra = NS(obra_id="o", cliente_id="c", nombre_canonico="TORRES OCARANZA LTDA QUILICURA", aliases_documentales=("TORRES OCARANZA LTDA QUILICU",), estado="CONFIRMADA", estado_vigencia="ACTIVO")
    ev = NS(tipo="GUIA", identificador_fuente="484835", referencia_hash="dec", resultado="SOPORTA")
    relacion = NS(relacion_id="r", obra_id="o", destino_id="d", estado="CONFIRMADA", fuente_confirmacion="CONFIRMACION_HUMANA", evidencias=[ev])
    destino = NS(destino_id="d", direccion=DIRECCION, comuna="QUILICURA", estado_calidad="CONFIRMADO", estado_vigencia="ACTIVO")
    monkeypatch.setattr(m, "CatalogoObrasDestinos", lambda **kw: NS(listar_obras=lambda:[obra], listar_relaciones=lambda:[relacion]))
    monkeypatch.setattr(m, "CatalogoDestinos", lambda *a: NS(obtener=lambda ident: destino if ident == "d" else None))
    base = dict(numero_transporte="0000370628", fecha="16-11-2026", chofer="LUIS REYES", cliente="TORRES OCARANZA LTDA", rut_cliente="50.234.350-5", patente_tracto="KN5439", patente_rampla="JF6468")
    a = dict(base, archivo="484834.jpeg", numero_guia="484834", obra_destino=obra.nombre_canonico, despachar_a_crudo=DIRECCION+" QUILICURA", direccion_entrega=DIRECCION+" QUILICURA", localidad_entrega="QUILICURA", descripcion_material="B HORMIGON 25MM BMA630-420HS (N)", peso_kg="21063", estado_ruta="RUTA_CALCULADA", distancia_km="11.7456")
    b = dict(base, archivo="484835.jpeg", numero_guia="484835", obra_destino="TORRES OCARANZA LTDA QUILICU", despachar_a_crudo=DIRECCION, descripcion_material="HORMIGON 25M11MA630 420HS(N)", peso_kg="6042", estado_ruta="REQUIERE_REVISION", motivo_ruta="GEOCODIFICACION_NUMERO_INCOMPATIBLE")
    doc = lambda f: {k:f[k] for k in ("archivo", "numero_guia", "numero_transporte")}
    ledger = {"aplicaciones":[dict(tipo="DESTINO_OPERACIONAL_DOCUMENTO", documento=doc(a), destino_operacional=dict(direccion=DIRECCION, comuna="QUILICURA")), dict(tipo="DESTINO_SIN_CONFIRMAR", accion="CONFIRMAR", actor="JAVIER_DESKTOP", documento=doc(b), decision_id="dec", cliente_id="c", obra_id="o", relacion_id="r", destino_id="d", valor_documental=DIRECCION)]}
    return [a,b], ledger

def derivar(filas, ledger):
    identidades = identidades_confirmadas(filas, ledger, "unused")
    proyectadas = []
    for fila in filas:
        p = proyectar_destino(fila, ledger)
        if p != fila:
            p["_evidencia_documental_original"] = dict(fila)
        else:
            key = tuple(fila[k] for k in ("archivo", "numero_guia", "numero_transporte"))
            if key in identidades:
                p["_identidad_entrega_confirmada"] = identidades[key]
        proyectadas.append(p)
    return agrupar_viajes(proyectadas)[0]

def test_caso_confirmado_conserva_documentos(monkeypatch):
    filas, ledger = caso(monkeypatch)
    originales = deepcopy(filas)
    viajes = derivar(filas, ledger)
    assert len(viajes) == 1
    v = viajes[0]
    assert len(v.entregas) == 1
    assert v.entregas[0]["numeros_guia"] == ["484834", "484835"]
    assert v.entregas[0]["estado_ruta"] == "REQUIERE_REVISION"
    assert v.entregas[0]["motivo_ruta"] == "GEOCODIFICACION_NUMERO_INCOMPATIBLE"
    assert v.estado_ruta == "REQUIERE_REVISION"
    assert v.motivo_ruta == "GEOCODIFICACION_NUMERO_INCOMPATIBLE"
    assert filas == originales
    assert [d.peso_kg for d in v.documentos] == ["21063", "6042"]
    assert [d.descripcion_material for d in v.documentos] == [f["descripcion_material"] for f in filas]
    assert [d.evidencia["despachar_a_crudo"] for d in v.documentos] == [f["despachar_a_crudo"] for f in filas]
    assert v.documentos[1].estado_ruta == "REQUIERE_REVISION"

def test_correccion_posterior_prevalece(monkeypatch):
    filas, ledger = caso(monkeypatch)
    ledger["aplicaciones"].append(dict(tipo="DESTINO_OPERACIONAL_DOCUMENTO", documento={k:filas[1][k] for k in ("archivo", "numero_guia", "numero_transporte")}, destino_operacional=dict(direccion="OTRA CALLE 100", comuna="QUILICURA")))
    assert len(derivar(filas, ledger)[0].entregas) == 2

def test_catalogo_distinto_o_confirmacion_ausente_no_fusiona(monkeypatch):
    filas, ledger = caso(monkeypatch)
    ledger["aplicaciones"][0]["destino_operacional"]["direccion"] = "OTRA CALLE 100"
    assert len(derivar(filas, ledger)[0].entregas) == 2
    ledger["aplicaciones"].pop()
    assert len(derivar(filas, ledger)[0].entregas) == 2


def test_decision_posterior_rechazada_y_obra_cambiada_no_reutilizan_confirmacion(monkeypatch):
    filas, ledger = caso(monkeypatch)
    key = {k: filas[1][k] for k in ("archivo", "numero_guia", "numero_transporte")}
    ledger["aplicaciones"].append(dict(tipo="DESTINO_SIN_CONFIRMAR", accion="NO_CONFIRMAR", documento=key))
    assert identidades_confirmadas(filas, ledger, "unused") == {}
    ledger["aplicaciones"].pop()
    filas[1]["obra_destino"] = "OBRA DIFERENTE"
    assert identidades_confirmadas(filas, ledger, "unused") == {}
