"""Caso real 0000371984 (SALOMÓN PIZARRO, 23/11/2026, guías 485458/485459):
ambas guías imprimen "SANTA ISABEL 585 SANTIAGO LAMPA", pero el OCR leyó
"SANTA ISABEL S85 ..." en una y "SANTAISABEL 585 ..." en la otra. Las dos
calcularon la misma ruta (8,5231 km) contra el destino confirmado del
catálogo y aun así Atlas publicaba dos entregas.

La identidad física del destino (`atlas_core.identidad_destino`) separa el
lugar de su escritura OCR, reutilizando la equivalencia vigente del catálogo.
Valores de las filas tomados del dataset real; catálogo mínimo sintético
con el mismo formato que `destinos_maestros.json`."""

import csv
import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from atlas_core.destino_operacional import TIPO
from atlas_core.gestor_viajes import agrupar_viajes
from atlas_core.identidad_destino import IndiceIdentidadDestinos, identidad_de_fila
from atlas_core.reporte_viajes import COLUMNAS_OFICIALES, generar_reporte_viajes

RELOJ = lambda: datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)  # noqa: E731
RUTA = {"distancia_km": "8.523100000000001", "duracion_min": "13.231666666666666",
        "proveedor_ruta": "openrouteservice", "estado_ruta": "RUTA_CALCULADA", "motivo_ruta": ""}


def _fila(guia, direccion, *, localidad="Lampa", codigo_unidad="13302", **cambios):
    fila = {columna: "" for columna in COLUMNAS_OFICIALES}
    fila.update({
        "archivo": f"mobile/{guia}/original.jpg", "estado_procesamiento": "OK", "numero_guia": guia,
        "numero_transporte": "0000371984", "fecha": "23-11-2026", "chofer": "SALOMÓN PIZARRO",
        "rut_chofer": "18091588-5", "cliente": "ARMACERO MATCO SA", "rut_cliente": "78.170.790-2",
        "obra_destino": "ARMACERO MATCO SA", "patente_tracto": "TG8925", "patente_rampla": "JF9575",
        "descripcion_material": f"MATERIAL {guia}", "tipo_carga": "BARRAS", "indicador_revision": "OK",
        "peso_kg": "13469", "hora_entrada_aza": "07:32", "hora_salida_aza": "09:51",
        "despachar_a_crudo": direccion, "direccion_entrega": direccion, "localidad_entrega": localidad,
        "region_entrega": "Metropolitana", "estado_entrega": "RESUELTO", "codigo_pais": "CL",
        "codigo_unidad": codigo_unidad, "codigo_contexto": "13", "planta_origen_nombre": "AZA COLINA",
        **RUTA,
    })
    fila.update(cambios)
    return fila


def _485458(**cambios):
    return _fila("485458", "SANTA ISABEL S85 SANTIAGO LAMPA", **cambios)


def _485459(**cambios):
    return _fila("485459", "SANTAISABEL 585 SANTIAGO LAMPA", **cambios)


def _destino(destino_id, direccion, comuna="LAMPA", *, aliases=(), calidad="CONFIRMADO", vigencia="ACTIVO",
             lat=-33.310665, lon=-70.737609):
    nombre = direccion.split(",", 1)[0]
    return {"destino_id": destino_id, "cliente_id": "", "nombre_destino": nombre, "nombre_normalizado": nombre,
            "codigo_destino": "", "direccion": direccion, "comuna": comuna, "region": "RM", "pais": "CHILE",
            "latitud": lat, "longitud": lon, "aliases": list(aliases), "estado_calidad": calidad,
            "estado_vigencia": vigencia, "fuente": "PRUEBA", "observacion": "",
            "fecha_creacion": "2026-10-21T18:40:24+00:00", "fecha_modificacion": "2026-10-21T18:40:24+00:00"}


# Catálogo real: SANTA ISABEL 585 confirmado dos veces con distinto formato
# (51b4cd04 y b45d6f2f, a 535 m) y CALLE INTERIOR 700 -- otro destino real
# del mismo cliente, alias "SANTA ISABEL 700" -- que nunca se fusiona.
DESTINOS_REALES = [
    _destino("51b4cd04-0c4c-41f1-9fd2-3da535148c24", "SANTA ISABEL 585, LAMPA, CHILE"),
    _destino("b45d6f2f-f63d-4059-9c64-2c84c4a5c221", "SANTA ISABEL 585", lat=-33.307635, lon=-70.733135),
    _destino("aefa98d8-62b5-4538-b8d2-4e16f6ac5b15", "CALLE INTERIOR 700, FUNDO LA MONTAÑA, LAMPA, CHILE",
             aliases=("SANTA ISABEL 700",)),
    _destino("a0a73ffe-85e5-4413-843a-71972b5a3aac", "SANTA ISABEL 586, LAMPA, CHILE",
             calidad="PENDIENTE", vigencia="INACTIVO"),
]


def _indice(destinos=DESTINOS_REALES):
    from atlas_core.catalogo_destinos import Destino
    return IndiceIdentidadDestinos([Destino.desde_dict(dict(d)) for d in destinos])


def _anotar(filas, indice):
    salida = []
    for fila in filas:
        fila = dict(fila)
        identidad = identidad_de_fila(fila, indice)
        if identidad is not None:
            fila["_identidad_destino"] = (identidad.clave, identidad.direccion, identidad.comuna)
        salida.append(fila)
    return salida


def _viaje(*filas, indice=None):
    filas = _anotar(filas, indice) if indice is not None else list(filas)
    viajes, _ = agrupar_viajes(filas)
    assert len(viajes) == 1
    return viajes[0]


def _guias(viaje):
    return sorted(tuple(e["numeros_guia"]) for e in viaje.entregas)


# --- identidad -------------------------------------------------------------

def test_las_dos_lecturas_ocr_tienen_la_misma_identidad_fisica():
    indice = _indice()
    a, b = identidad_de_fila(_485458(), indice), identidad_de_fila(_485459(), indice)
    assert a is not None and a == b
    assert a.clave == "SANTA ISABEL 585@LAMPA"
    assert a.direccion == "SANTA ISABEL 585"


@pytest.mark.parametrize("direccion, localidad, codigo", [
    ("SANTA ISABEL 586 SANTIAGO LAMPA", "Lampa", "13302"),       # otro número
    ("SANTA ISABEL 58 SANTIAGO LAMPA", "Lampa", "13302"),        # número incompleto
    ("SANTA ISABEL S85 SANTIAGO COLINA", "Colina", "13301"),      # otra comuna
    ("SANTA ISABEL 585 SANTIAGO COLINA", "Lampa", "13302"),       # comuna impresa contradice
    ("SANTA ISABEL S85", "", ""),                                  # sin comuna conocida
    ("SANTA ISABEL", "Lampa", "13302"),                            # sin numeración
])
def test_sin_evidencia_suficiente_no_hay_identidad(direccion, localidad, codigo):
    fila = _fila("1", direccion, localidad_entrega=localidad, codigo_unidad=codigo)
    assert identidad_de_fila(fila, _indice()) is None


def test_destino_pendiente_o_inactivo_no_da_identidad():
    fila = _fila("1", "SANTA ISABEL 586 SANTIAGO LAMPA")
    assert identidad_de_fila(fila, _indice()) is None


def test_lecturas_del_mismo_documento_deben_converger():
    fila = _fila("1", "SANTA ISABEL S85 SANTIAGO LAMPA", direccion_entrega="SANTA ISABEL 700 SANTIAGO LAMPA")
    assert identidad_de_fila(fila, _indice()) is None


def test_dos_identidades_fisicas_coincidentes_se_abstiene():
    ambiguo = _indice([*DESTINOS_REALES, _destino("x", "CAMINO INTERIOR 9, LAMPA, CHILE",
                                                  aliases=("SANTA ISABEL 585",))])
    assert identidad_de_fila(_485459(), ambiguo) is None


def test_catalogo_vacio_o_ausente_no_da_identidad(tmp_path):
    assert identidad_de_fila(_485459(), IndiceIdentidadDestinos(())) is None
    assert identidad_de_fila(_485459(), IndiceIdentidadDestinos.desde_carpeta(tmp_path)) is None


# --- entregas --------------------------------------------------------------

def test_caso_real_485458_485459_una_sola_entrega():
    viaje = _viaje(_485458(), _485459(), indice=_indice())
    assert _guias(viaje) == [("485458", "485459")]
    entrega = viaje.entregas[0]
    assert entrega["destino_operacional"] == "SANTA ISABEL 585"
    assert entrega["localidad_entrega"] == "Lampa"
    assert entrega["distancia_km"] == "8.523100000000001"
    assert viaje.direccion_entrega == "SANTA ISABEL 585"
    assert viaje.distancia_km == "8.523100000000001"


def test_sin_catalogo_s85_no_se_reconcilia_por_texto():
    # Sin destino confirmado no hay evidencia de que S85 sea 585.
    assert _guias(_viaje(_485458(), _485459())) == [("485458",), ("485459",)]


def test_espacio_omitido_no_genera_destinos_distintos():
    con_espacio = _fila("1", "SANTA ISABEL 585 SANTIAGO LAMPA")
    sin_espacio = _fila("2", "SANTAISABEL 585 SANTIAGO LAMPA")
    assert _guias(_viaje(con_espacio, sin_espacio)) == [("1", "2")]
    assert _guias(_viaje(con_espacio, sin_espacio, indice=_indice())) == [("1", "2")]


def test_585_y_586_siguen_separados():
    viaje = _viaje(_fila("1", "SANTA ISABEL 585 SANTIAGO LAMPA"), _fila("2", "SANTA ISABEL 586 SANTIAGO LAMPA"),
                   indice=_indice())
    assert _guias(viaje) == [("1",), ("2",)]


def test_585_y_700_del_mismo_cliente_obra_y_transporte_siguen_separados():
    viaje = _viaje(_485458(), _fila("2", "SANTA ISABEL 700 SANTIAGO LAMPA"), indice=_indice())
    assert _guias(viaje) == [("2",), ("485458",)]


def test_comunas_distintas_no_se_unen():
    colina = _fila("2", "SANTA ISABEL 585 SANTIAGO COLINA", localidad_entrega="Colina", codigo_unidad="13301")
    assert _guias(_viaje(_485458(), colina, indice=_indice())) == [("2",), ("485458",)]


def test_cliente_distinto_no_se_une_aunque_compartan_identidad():
    otro = _485459(cliente="AMERICAN SCREW CHILE SPA", rut_cliente="91.410.000-3",
                   obra_destino="AMERICAN SCREW CHILE SPA")
    assert _guias(_viaje(_485458(), otro, indice=_indice())) == [("485458",), ("485459",)]


def test_mayoria_documental_se_conserva_como_representacion():
    viaje = _viaje(_485458(), _485459(), _fila("3", "SANTAISABEL 585 SANTIAGO LAMPA"), indice=_indice())
    assert _guias(viaje) == [("3", "485458", "485459")]
    assert viaje.entregas[0]["destino_operacional"] == "SANTAISABEL 585 SANTIAGO LAMPA"


def test_empate_prefiere_lectura_que_ya_trae_la_direccion_canonica():
    viaje = _viaje(_485458(), _fila("2", "SANTA ISABEL 585"), indice=_indice())
    assert _guias(viaje) == [("2", "485458")]
    assert viaje.entregas[0]["destino_operacional"] == "SANTA ISABEL 585"


# --- reporte sobre archivos ----------------------------------------------------

def _entorno(tmp_path, filas, *, destinos=DESTINOS_REALES, ledger=None):
    actual = tmp_path / "operacion" / "actual"
    actual.mkdir(parents=True)
    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(COLUMNAS_OFICIALES), delimiter=";",
                                  extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(filas)
    (actual / "decisiones_aplicadas.json").write_text(json.dumps(ledger or {"aplicaciones": []}), encoding="utf-8")
    catalogos = tmp_path / "catalogos"
    catalogos.mkdir()
    (catalogos / "destinos_maestros.json").write_text(
        json.dumps({"version_formato": 1, "destinos": destinos}), encoding="utf-8")
    return dataset, catalogos


def _generar(tmp_path, dataset, catalogos):
    salida = tmp_path / "reporte"
    generar_reporte_viajes(dataset, salida, carpeta_catalogos=catalogos, reloj=RELOJ)
    with (salida / "viajes.csv").open(newline="", encoding="utf-8-sig") as archivo:
        viajes = list(csv.DictReader(archivo, delimiter=";"))
    assert len(viajes) == 1
    return viajes[0]


def test_reporte_publica_una_entrega_y_preserva_originales(tmp_path):
    dataset, catalogos = _entorno(tmp_path, [_485458(), _485459()])
    huella_dataset = hashlib.sha256(dataset.read_bytes()).hexdigest()
    huella_catalogo = hashlib.sha256((catalogos / "destinos_maestros.json").read_bytes()).hexdigest()
    viaje = _generar(tmp_path, dataset, catalogos)
    entregas = json.loads(viaje["entregas"])
    assert [e["numeros_guia"] for e in entregas] == [["485458", "485459"]]
    assert entregas[0]["destino_operacional"] == "SANTA ISABEL 585"
    assert viaje["direccion_entrega"] == "SANTA ISABEL 585"
    assert viaje["distancia_km"] == "8.523100000000001"
    # La evidencia documental (OCR) se publica intacta.
    evidencias = {e["numero_guia"]: e for e in json.loads(viaje["evidencias_documentos"])}
    assert evidencias["485458"]["despachar_a_crudo"] == "SANTA ISABEL S85 SANTIAGO LAMPA"
    assert evidencias["485459"]["direccion_entrega"] == "SANTAISABEL 585 SANTIAGO LAMPA"
    assert "_identidad_destino" not in viaje["evidencias_documentos"]
    assert hashlib.sha256(dataset.read_bytes()).hexdigest() == huella_dataset
    assert hashlib.sha256((catalogos / "destinos_maestros.json").read_bytes()).hexdigest() == huella_catalogo


def test_reporte_sin_destino_confirmado_conserva_dos_entregas(tmp_path):
    dataset, catalogos = _entorno(tmp_path, [_485458(), _485459()], destinos=[])
    viaje = _generar(tmp_path, dataset, catalogos)
    assert len(json.loads(viaje["entregas"])) == 2


def test_confirmacion_humana_no_se_sobrescribe(tmp_path):
    """485458 con destino operacional fijado por un humano a SANTA ISABEL
    700: su identidad la fija la decisión, nunca la lectura OCR."""
    fila = _485458()
    ledger = {"aplicaciones": [{
        "tipo": TIPO, "documento": {"archivo": fila["archivo"], "numero_guia": "485458"},
        "destino_operacional": {"direccion": "SANTA ISABEL 700", "comuna": "LAMPA"},
        "ruta_operacional": dict(RUTA, distancia_km="9.1", comuna="LAMPA"),
    }]}
    dataset, catalogos = _entorno(tmp_path, [fila, _485459()], ledger=ledger)
    viaje = _generar(tmp_path, dataset, catalogos)
    entregas = {tuple(e["numeros_guia"]): e for e in json.loads(viaje["entregas"])}
    assert set(entregas) == {("485458",), ("485459",)}
    assert entregas[("485458",)]["destino_operacional"] == "SANTA ISABEL 700"
    assert entregas[("485459",)]["destino_operacional"] == "SANTAISABEL 585 SANTIAGO LAMPA"


def test_objeto_sin_campo_identidad_conserva_regla_documental():
    from atlas_core.entregas import representacion_canonica
    assert representacion_canonica([SimpleNamespace(direccion_entrega="X 1")]) == ""
