"""Caso real 0000368327 (PATRICK ORTIZ, guías 483935/483938/483939/483940/
483941): las cinco imprimen obra "INMOB Y CONST TERRATEC LTDA" y DESPACHAR A
"MAESTRA LIDIA TORRES 92 SANTIAGO RECOLETA". El OCR capturó como obra de
483940/483941 la etiqueta "Nro. TRANSPORTE" sin espacio y antepuso el valor
de RETIRA al destino de 483939. Valores almacenados reales del dataset."""

import pytest

from atlas_core.extractor import clasificar_valor_obra_destino
from atlas_core.gestor_viajes import agrupar_viajes

DESTINO = "MAESTRA LIDIA TORRES 92 SANTIAGO RECOLETA"
TERRATEC = "INMOBILIARIA Y CONSTRUCTORA TERRATEC LIMITADA"


def _fila(guia, obra=TERRATEC, destino=DESTINO, **cambios):
    fila = {"archivo": f"mobile/{guia}/original.jpg", "numero_guia": guia, "numero_transporte": "0000368327",
            "fecha": "03-11-2026", "chofer": "PATRICK ORTIZ", "rut_chofer": "18626166-6",
            "cliente": "EASY RETAIL SA", "rut_cliente": "76.568.660-1", "obra_destino": obra,
            "patente_tracto": "XF3629", "descripcion_material": f"MATERIAL {guia}", "tipo_carga": "BARRAS",
            "peso_kg": "1500", "hora_entrada_aza": "09:17", "hora_salida_aza": "11:39",
            "despachar_a_crudo": destino, "direccion_entrega": destino, "localidad_entrega": "Recoleta",
            "region_entrega": "Metropolitana", "estado_entrega": "RESUELTO", "codigo_pais": "CL",
            "codigo_unidad": "13127", "codigo_contexto": "13", "distancia_km": "18.0149", "duracion_min": "30.0",
            "proveedor_ruta": "openrouteservice", "estado_ruta": "RUTA_CALCULADA"}
    fila.update(cambios)
    return fila


def _caso_real():
    return [_fila("483940", obra="NRO.TRANSPORTE"), _fila("483941", obra="NRO.TRANSPORTE"),
            _fila("483935"), _fila("483939", destino="PATRICK ORTIZ " + DESTINO), _fila("483938")]


def _entregas(filas):
    viajes, _ = agrupar_viajes(filas)
    assert len(viajes) == 1
    return viajes[0].entregas


def _guias(entregas):
    return sorted(tuple(e["numeros_guia"]) for e in entregas)


def test_las_cinco_guias_reales_son_una_entrega():
    entregas = _entregas(_caso_real())
    assert _guias(entregas) == [("483935", "483938", "483939", "483940", "483941")]
    assert entregas[0]["destino_operacional"] == DESTINO
    # La lista publicada refleja lo almacenado (483940/483941 siguen en revisión
    # por su obra); la etiqueta sólo deja de ser identidad de entrega.
    assert TERRATEC in entregas[0]["obras_destino"]


def test_destinos_y_obras_almacenados_no_cambian():
    filas = _caso_real()
    copias = [dict(f) for f in filas]
    _entregas(filas)
    assert filas == copias


@pytest.mark.parametrize("etiqueta", ["NRO.TRANSPORTE", "NRO. TRANSPORTE", "Nro.Transporte", "COD.DESTINATARIO"])
def test_etiquetas_del_formulario_no_son_obras(etiqueta):
    assert clasificar_valor_obra_destino(etiqueta) == "ADMINISTRATIVO"


@pytest.mark.parametrize("nombre", [
    "INMOB Y CONST TERRATEC LTDA", TERRATEC, "TRANSPORTES Y EXCAVACIONES L", "CONSTRUCTORA S.A.",
    "EMPRESA CONST SIGRO", "ING. Y CONST. SIGRO S.A.", "AMERICAN SCREW CHILE SPA",
])
def test_nombres_legitimos_siguen_siendo_nominales(nombre):
    assert clasificar_valor_obra_destino(nombre) == "NOMINAL"


def test_prefijo_distinto_del_chofer_no_se_elimina():
    entregas = _entregas([_fila("1"), _fila("2", destino="PEDRO SOTO " + DESTINO)])
    assert len(entregas) == 2


def test_prefijo_del_chofer_no_tolera_numero_distinto():
    entregas = _entregas([_fila("1"), _fila("2", destino="PATRICK ORTIZ MAESTRA LIDIA TORRES 920 SANTIAGO RECOLETA")])
    assert len(entregas) == 2


def test_prefijo_del_chofer_no_tolera_comuna_distinta():
    entregas = _entregas([_fila("1"), _fila("2", destino="PATRICK ORTIZ MAESTRA LIDIA TORRES 92 SANTIAGO INDEPENDENCIA",
                                             localidad_entrega="Independencia", codigo_unidad="13108")])
    assert len(entregas) == 2


def test_calle_realmente_distinta_no_se_fusiona():
    entregas = _entregas([_fila("1"), _fila("2", destino="PATRICK ORTIZ AVENIDA RECOLETA 92 SANTIAGO RECOLETA")])
    assert len(entregas) == 2


def test_obras_reales_distintas_en_la_misma_direccion_siguen_separadas():
    entregas = _entregas([_fila("1"), _fila("2", obra="CONSTRUCTORA OTRA OBRA SPA")])
    assert len(entregas) == 2


def test_obra_real_que_empieza_con_palabra_de_etiqueta_sigue_siendo_identidad():
    entregas = _entregas([_fila("1"), _fila("2", obra="CLIENTE EJEMPLO SPA 2")])
    assert len(entregas) == 2


def test_cliente_distinto_sigue_separando():
    entregas = _entregas([_fila("1"), _fila("2", obra="NRO.TRANSPORTE", cliente="OTRO CLIENTE SPA", rut_cliente="77.000.000-0")])
    assert len(entregas) == 2
