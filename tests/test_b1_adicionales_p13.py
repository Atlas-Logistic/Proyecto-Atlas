"""P1.3: adicionales por lenguaje natural para una o varias guías o transportes,
una vez por viaje (también viajes agrupados), con lo no encontrado explícito."""
import csv
import json

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.b1_operador import OperadorB1, interpretar_determinista
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.registro_eventos_operacionales import leer_eventos_operacionales, registrar_evento
from tests.adicional_preview_por_guia import por_guia

GUIAS = [("483732", "0000367477"), ("483934", "0000368298"), ("482634", "0000365167"),
         ("474597", "0000360122"), ("480603", "0000360179"), ("474598", "0000360122")]


class Escritor:
    vigente = True

    def adquirir(self):
        return True

    def cerrar(self):
        pass


@pytest.fixture
def raiz(tmp_path):
    raiz = tmp_path / "Atlas"
    actual = raiz / "operacion" / "actual"
    actual.mkdir(parents=True)
    (raiz / "catalogos_privados").mkdir()
    with (actual / "analisis_completo_guias.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        for guia, transporte in GUIAS:
            fila = {c: "" for c in COLUMNAS}
            fila.update(archivo=guia + ".jpg", numero_guia=guia, numero_transporte=transporte)
            w.writerow(fila)
    # Viaje físico agrupado real: 0000360122 (principal) + 0000360179.
    (actual / "agrupaciones_viaje.json").write_text(json.dumps({"schema_version": 1, "agrupaciones": [{
        "agrupacion_id": "a1", "estado": "ACTIVA", "tipo": "VIAJE_FISICO_MULTITRANSPORTE",
        "transportes": ["0000360122", "0000360179"], "transporte_principal": "0000360122",
        "guias": ["474597", "474598", "480603"]}]}), encoding="utf-8")
    registrar_evento(raiz=raiz, tipo_evento="OBSERVACION_OPERACIONAL", numero_transporte="0000365167",
                     nota="CARGA LISTA A LAS 9", origen="TEST")
    return raiz


def operador(raiz):
    return OperadorB1(raiz, usuario="JAVIER_DESKTOP",
                      capa=CapaAccionesOperacionales(raiz, fabrica_escritor=lambda: Escritor()))


def notas(raiz):
    return {e["numero_transporte"]: e["nota"] for e in leer_eventos_operacionales(raiz=raiz)["eventos"]
            if e["tipo_evento"] == "OBSERVACION_OPERACIONAL" and e.get("estado", "ACTIVO") == "ACTIVO"}


@pytest.mark.parametrize("frase,clave,numeros,texto", [
    ("Las guías 483732 y 483934 tienen adicional de 30.000 por retiro de materiales en Portezuelo.", "guias",
     ["483732", "483934"], "ESTE VIAJE TIENE ADICIONAL DE $30.000 POR RETIRO DE MATERIALES EN PORTEZUELO"),
    ("La guía 482634 tiene adicional de 30.000 por carga en Versalles.", "guias", ["482634"],
     "ESTE VIAJE TIENE ADICIONAL DE $30.000 POR CARGA EN VERSALLES"),
    ("Agrega un adicional de $30.000 por carga en Versalles al viaje de la guía 482634.", "guias", ["482634"],
     "ESTE VIAJE TIENE ADICIONAL DE $30.000 POR CARGA EN VERSALLES"),
    ("El transporte 0000365167 tiene un adicional de $25.000 por espera en obra", "transportes", ["0000365167"],
     "ESTE VIAJE TIENE ADICIONAL DE $25.000 POR ESPERA EN OBRA"),
    ("Agrega un adicional de 45 mil a los transportes 0000367477 y 0000368298 por doble descarga", "transportes",
     ["0000367477", "0000368298"], "ESTE VIAJE TIENE ADICIONAL DE $45.000 POR DOBLE DESCARGA"),
    ("Los viajes de las guías 483732 y 483934 llevan adicional de $12.500", "guias", ["483732", "483934"],
     "ESTE VIAJE TIENE ADICIONAL DE $12.500"),
    ("Registra un adicional de 7.500 pesos al viaje del transporte 0000365167 debido a peaje", "transportes",
     ["0000365167"], "ESTE VIAJE TIENE ADICIONAL DE $7.500 DEBIDO A PEAJE"),
])
def test_frases_reales_y_variantes(frase, clave, numeros, texto):
    intencion = interpretar_determinista(frase)
    assert intencion is not None and intencion.accion == "VIAJE_AGREGAR_OBSERVACION"
    assert intencion.parametros == {clave: numeros, "texto": texto}


@pytest.mark.parametrize("frase", ["¿Qué adicional tiene la guía 482634?", "cuántos viajes tienen adicional",
                                   "Muéstrame los viajes con adicional en Versalles"])
def test_preguntas_siguen_siendo_consultas(raiz, frase):
    assert operador(raiz).consultar(frase, derivar_operacionales=True)["estado"] == "NO_INTERPRETADA"


def test_adicional_nunca_es_material_ni_cae_a_consultas(raiz):
    frase = "La guía 482634 tiene adicional de 30.000 por retiro de materiales"
    assert interpretar_determinista(frase).accion == "VIAJE_AGREGAR_OBSERVACION"
    # Sin monto: no se adivina, pero tampoco se deja pasar a consulta/incidencias.
    sin_monto = "La guía 482634 tiene adicional por carga en Versalles"
    b = operador(raiz)
    assert b.consultar(sin_monto, derivar_operacionales=True)["estado"] == "REQUIERE_OPERADOR"
    assert b.consultar(sin_monto)["estado"] == "RECHAZADA"
    r = b.atender("c", sin_monto)
    assert r["estado"] == "ACLARACION_REQUERIDA" and "monto" in r["mensaje"]
    assert b.pendiente("c") is None


def test_una_vez_por_viaje_incluso_agrupado_y_conserva_observaciones(raiz):
    b = operador(raiz)
    r = b.atender("c", "Agrega un adicional de $20.000 por espera en obra a las guías 474597, 480603, 474598 y 482634")
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    viajes = {f[0]: f for f in r["tablas"][0]["filas"]}
    assert set(viajes) == {"0000360122", "0000365167"}, "dos viajes: el agrupado cuenta una vez"
    assert viajes["0000360122"][1] == "474597, 480603, 474598"
    assert "CARGA LISTA A LAS 9" in viajes["0000365167"][3]
    assert b.atender("c", "sí")["estado"] == "EJECUTADA"
    n = notas(raiz)
    assert n["0000360122"] == "ESTE VIAJE TIENE ADICIONAL DE $20.000 POR ESPERA EN OBRA"
    assert "0000360179" not in n, "nunca en el transporte secundario del mismo viaje"
    assert n["0000365167"] == "CARGA LISTA A LAS 9\nESTE VIAJE TIENE ADICIONAL DE $20.000 POR ESPERA EN OBRA"
    # Repetirlo, ahora por el transporte secundario, no duplica.
    r2 = b.atender("c", "El transporte 0000360179 tiene adicional de $20.000 por espera en obra")
    assert r2["estado"] == "SIN_CAMBIOS", r2
    assert r2["tablas"][0]["filas"][0][:3] == ["0000360122", "transporte 0000360179", "Ya la tiene (sin cambio)"]
    assert b.pendiente("c") is None


def test_transporte_sin_ceros_y_no_encontrados_explicitos(raiz):
    b = operador(raiz)
    r = b.atender("c", "Agrega un adicional de $10.000 por espera a los transportes 365167 y 0000999999")
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert [f[0] for f in r["tablas"][0]["filas"]] == ["0000365167"]
    assert r["tablas"][1]["filas"] == [["transporte 0000999999", "No existe en Atlas (no se aplica)"]]
    assert "No encontré: transporte 0000999999" in r["mensaje"]


def test_sin_acciones_validas_no_hay_confirmacion(raiz):
    b = operador(raiz)
    antes = notas(raiz)
    r = b.atender("c", "La guía 999999 tiene adicional de 30.000 por carga en Versalles")
    assert r["estado"] == "SIN_CAMBIOS" and "preview" in r and b.pendiente("c") is None
    assert "No encontré: guía 999999" in r["mensaje"]
    assert b.atender("c", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert notas(raiz) == antes


def test_mismo_monto_otro_motivo_corrige_la_linea_y_conserva_lo_demas(raiz):
    registrar_evento(raiz=raiz, tipo_evento="OBSERVACION_OPERACIONAL", numero_transporte="0000365167",
                     nota="CARGA LISTA A LAS 9\nESTE VIAJE TIENE ADICIONAL DE $30.000 POR RETIRO DE MATERIALES FUERA DE AZA",
                     origen="TEST")
    b = operador(raiz)
    r = b.atender("c", "La guía 482634 tiene adicional de 30.000 por carga en Versalles.")
    assert r["estado"] == "PREVIEW_PENDIENTE" and r["tablas"][0]["filas"][0][2].startswith("Se corrige el motivo")
    assert b.atender("c", "sí")["estado"] == "EJECUTADA"
    assert notas(raiz)["0000365167"] == "CARGA LISTA A LAS 9\nESTE VIAJE TIENE ADICIONAL DE $30.000 POR CARGA EN VERSALLES"
