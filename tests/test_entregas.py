"""Bloque VIAJE MULTIENTREGA V1 -- derivación genérica de entregas/paradas.

Cubre el invariante: VIAJE -> 1..N ENTREGAS -> 1..N GUÍAS por entrega, con
N arbitrario (1, 2, 5, ...). Nunca se agrupa por `numero_transporte`; sólo
con evidencia operacional positiva de mismo destino. Ante ambigüedad real,
cada documento forma su propia entrega.
"""

import csv
import json
from datetime import datetime, timezone

from atlas_core.entregas import derivar_entregas
from atlas_core.gestor_viajes import EstadoViaje, agrupar_viajes
from atlas_core.reporte_viajes import COLUMNAS_OFICIALES, generar_reporte_viajes


def _fila(**cambios):
    fila = {
        "archivo": f"{cambios.get('numero_guia', '000101')}.jpg",
        "numero_guia": "000101",
        "numero_transporte": "0000352376",
        "fecha": "2026-07-28",
        "chofer": "JOSÉ PÉREZ",
        "rut_chofer": "12.345.678-5",
        "cliente": "CLIENTE ÑUBLE",
        "obra_destino": "OBRA ÁGUILA",
        "patente_tracto": "ABCD12",
        "patente_rampla": "EFGH34",
        "descripcion_material": "BARRAS",
        "tipo_carga": "BARRAS",
        "peso_kg": "1000",
        "hora_entrada_aza": "07:00",
        "hora_salida_aza": "18:00",
        "despachar_a_crudo": "",
        "direccion_entrega": "",
        "localidad_entrega": "",
        "region_entrega": "",
        "estado_entrega": "",
        "distancia_km": "",
        "duracion_min": "",
        "proveedor_ruta": "",
        "estado_ruta": "",
        "motivo_ruta": "",
    }
    fila.update(cambios)
    fila.setdefault("archivo", f"{fila['numero_guia']}.jpg")
    return fila


def _entregas_de(filas):
    viajes, _ = agrupar_viajes(filas)
    assert len(viajes) == 1
    return viajes[0], viajes[0].entregas


def _parada(numero_guia, direccion, localidad, **extra):
    return _fila(
        numero_guia=numero_guia,
        archivo=f"{numero_guia}.jpg",
        despachar_a_crudo=direccion,
        direccion_entrega=direccion,
        localidad_entrega=localidad,
        region_entrega="Región X",
        estado_entrega="RESUELTO",
        distancia_km="100.0",
        duracion_min="120.0",
        proveedor_ruta="openrouteservice",
        estado_ruta="RUTA_CALCULADA",
        motivo_ruta="",
        **extra,
    )


# ---------------------------------------------------------------------------
# 1. viaje 1 guía / 1 destino
# ---------------------------------------------------------------------------
def test_una_guia_un_destino_es_una_sola_entrega():
    _, entregas = _entregas_de([_parada("464700", "COLON 123", "Concepción")])
    assert len(entregas) == 1
    assert entregas[0]["numeros_guia"] == ["464700"]
    assert entregas[0]["destino_operacional"] == "COLON 123"
    assert entregas[0]["localidad_entrega"] == "Concepción"
    assert entregas[0]["distancia_km"] == "100.0"
    assert entregas[0]["estado_ruta"] == "RUTA_CALCULADA"


# ---------------------------------------------------------------------------
# 2. viaje multiguía / 1 entrega (mismas señales de destino)
# ---------------------------------------------------------------------------
def test_multiguia_mismo_destino_es_una_entrega_con_varias_guias():
    _, entregas = _entregas_de([
        _parada("464698", "AV CAUQUENES 500", "Cauquenes"),
        _parada("464699", "AV CAUQUENES 500", "Cauquenes"),
    ])
    assert len(entregas) == 1
    assert entregas[0]["numeros_guia"] == ["464698", "464699"]


# ---------------------------------------------------------------------------
# 3. viaje con 2 entregas -- forma del caso real 0000352376
# ---------------------------------------------------------------------------
def test_dos_entregas_agrupa_las_hermanas_y_separa_la_otra():
    viaje, entregas = _entregas_de([
        _parada("464698", "AV CAUQUENES 500", "Cauquenes"),
        _parada("464699", "AV CAUQUENES 500", "Cauquenes"),
        _parada("464700", "COLON 123", "Concepción"),
    ])
    assert viaje.estado == EstadoViaje.CONFIRMADO
    assert len(entregas) == 2
    guias = sorted(e["numeros_guia"] for e in entregas)
    assert guias == [["464698", "464699"], ["464700"]]
    por_localidad = {e["localidad_entrega"]: e for e in entregas}
    assert set(por_localidad) == {"Cauquenes", "Concepción"}
    assert por_localidad["Cauquenes"]["numeros_guia"] == ["464698", "464699"]
    assert por_localidad["Concepción"]["numeros_guia"] == ["464700"]
    # cada entrega conserva su propia ruta ya calculada
    for entrega in entregas:
        assert entrega["distancia_km"] == "100.0"
        assert entrega["estado_ruta"] == "RUTA_CALCULADA"


# ---------------------------------------------------------------------------
# 4. viaje con 5 entregas -- N genérico
# ---------------------------------------------------------------------------
def test_cinco_entregas_se_generan_dinamicamente():
    filas = [
        _parada(f"47000{i}", f"CALLE {i} 100", f"Comuna {i}")
        for i in range(1, 6)
    ]
    _, entregas = _entregas_de(filas)
    assert len(entregas) == 5
    assert sorted(e["localidad_entrega"] for e in entregas) == [
        "Comuna 1", "Comuna 2", "Comuna 3", "Comuna 4", "Comuna 5",
    ]


# ---------------------------------------------------------------------------
# 5. varias guías agrupadas dentro de una entrega + otra suelta (3+1)
# ---------------------------------------------------------------------------
def test_grupo_de_tres_guias_en_una_entrega_y_una_cuarta_aparte():
    _, entregas = _entregas_de([
        _parada("1", "RUTA 5 KM 300", "Chillán"),
        _parada("2", "RUTA 5 KM 300", "Chillán"),
        _parada("3", "RUTA 5 KM 300", "Chillán"),
        _parada("4", "OHIGGINS 40", "Los Ángeles"),
    ])
    assert len(entregas) == 2
    grande = max(entregas, key=lambda e: len(e["numeros_guia"]))
    assert grande["numeros_guia"] == ["1", "2", "3"]


# ---------------------------------------------------------------------------
# 6. destinos realmente diferentes no se fusionan (aunque compartan cliente)
# ---------------------------------------------------------------------------
def test_destinos_distintos_no_se_fusionan_ni_con_mismo_cliente_y_transporte():
    _, entregas = _entregas_de([
        _parada("A", "DIRECCION UNO 1", "Talca", cliente="SODIMAC SA", rut_cliente="96.792.430-K"),
        _parada("B", "DIRECCION DOS 2", "Curicó", cliente="SODIMAC SA", rut_cliente="96.792.430-K"),
    ])
    assert len(entregas) == 2


def test_no_agrupa_solo_por_numero_de_transporte_sin_senal_de_destino():
    # Dos documentos del mismo transporte, ninguno con dirección/despachar
    # ni código territorial -> ambigüedad real: una entrega por documento.
    _, entregas = _entregas_de([
        _fila(numero_guia="X1", archivo="x1.jpg"),
        _fila(numero_guia="X2", archivo="x2.jpg"),
    ])
    assert len(entregas) == 2


def test_agrupa_por_despachar_a_cuando_no_hay_direccion_resuelta():
    _, entregas = _entregas_de([
        _fila(numero_guia="D1", archivo="d1.jpg", despachar_a_crudo="BODEGA CENTRAL S/N"),
        _fila(numero_guia="D2", archivo="d2.jpg", despachar_a_crudo="bodega central s/n"),
    ])
    assert len(entregas) == 1
    assert entregas[0]["numeros_guia"] == ["D1", "D2"]


def test_agrupa_por_codigo_territorial_opaco():
    comun = {"codigo_pais": "CL", "codigo_unidad": "08", "codigo_contexto": "8401"}
    _, entregas = _entregas_de([
        _fila(numero_guia="T1", archivo="t1.jpg", **comun),
        _fila(numero_guia="T2", archivo="t2.jpg", **comun),
        _fila(numero_guia="T3", archivo="t3.jpg",
              codigo_pais="CL", codigo_unidad="08", codigo_contexto="8101"),
    ])
    assert len(entregas) == 2
    assert sorted(e["numeros_guia"] for e in entregas) == [["T1", "T2"], ["T3"]]


def test_cliente_contradictorio_impide_fusion_aunque_destino_coincida():
    _, entregas = _entregas_de([
        _parada("C1", "MISMA DIRECCION 9", "Rancagua", cliente="CLIENTE A", rut_cliente="11.111.111-1"),
        _parada("C2", "MISMA DIRECCION 9", "Rancagua", cliente="CLIENTE B", rut_cliente="22.222.222-2"),
    ])
    assert len(entregas) == 2


# ---------------------------------------------------------------------------
# 7. MATERIAL_AUSENTE no bloqueante no altera la derivación ni el estado
# ---------------------------------------------------------------------------
def test_material_ausente_no_bloqueante_no_impide_confirmar_ni_derivar_entregas():
    viaje, entregas = _entregas_de([
        _parada("464698", "AV CAUQUENES 500", "Cauquenes", descripcion_material=""),
        _parada("464699", "AV CAUQUENES 500", "Cauquenes",
                descripcion_material="", motivos_revision_documento="MATERIAL_AUSENTE"),
        _parada("464700", "COLON 123", "Concepción"),
    ])
    assert viaje.estado == EstadoViaje.CONFIRMADO
    assert len(entregas) == 2


# ---------------------------------------------------------------------------
# 8. no regresión de viajes técnicos / revisión real
# ---------------------------------------------------------------------------
def test_entrega_unica_conserva_el_diagnostico_de_ruta_pendiente():
    _, entregas = _entregas_de([
        _fila(
            numero_guia="464170", archivo="464170.jpg",
            despachar_a_crudo="DIRECCION SIN GEOCODIFICAR 1",
            estado_ruta="REQUIERE_REVISION",
            motivo_ruta="GEOCODIFICACION_DIRECCION_NO_ENCONTRADA",
        ),
    ])
    assert len(entregas) == 1
    assert entregas[0]["estado_ruta"] == "REQUIERE_REVISION"
    assert entregas[0]["motivo_ruta"] == "GEOCODIFICACION_DIRECCION_NO_ENCONTRADA"
    assert entregas[0]["distancia_km"] == ""


def test_multientrega_una_resuelta_y_otra_pendiente_no_contaminan_entre_si():
    _, entregas = _entregas_de([
        _parada("464698", "AV CAUQUENES 500", "Cauquenes"),
        _fila(
            numero_guia="464700", archivo="464700.jpg",
            despachar_a_crudo="OTRA DIRECCION 2",
            estado_ruta="REQUIERE_REVISION",
            motivo_ruta="MULTIPLES_UBICACIONES_DISPERSAS",
        ),
    ])
    assert len(entregas) == 2
    por_guia = {tuple(e["numeros_guia"]): e for e in entregas}
    assert por_guia[("464698",)]["estado_ruta"] == "RUTA_CALCULADA"
    assert por_guia[("464698",)]["distancia_km"] == "100.0"
    assert por_guia[("464700",)]["estado_ruta"] == "REQUIERE_REVISION"
    assert por_guia[("464700",)]["motivo_ruta"] == "MULTIPLES_UBICACIONES_DISPERSAS"


def test_viaje_sin_documentos_no_tiene_entregas():
    assert derivar_entregas([]) == []


def test_a_dict_expone_entregas():
    viaje, _ = _entregas_de([
        _parada("464698", "AV CAUQUENES 500", "Cauquenes"),
        _parada("464700", "COLON 123", "Concepción"),
    ])
    datos = viaje.a_dict()
    assert "entregas" in datos
    assert len(datos["entregas"]) == 2


# ---------------------------------------------------------------------------
# E2E -- la columna `entregas` viaja en viajes.csv (lo que consume Desktop)
# ---------------------------------------------------------------------------
_RELOJ = lambda: datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def _fila_oficial(**cambios):
    fila = {columna: "" for columna in COLUMNAS_OFICIALES}
    fila.update(
        estado_procesamiento="OK",
        fecha="2026-07-28",
        chofer="JOSÉ PÉREZ",
        rut_chofer="12.345.678-5",
        patente_tracto="ABCD12",
        patente_rampla="EFGH34",
        tipo_carga="BARRAS",
        descripcion_material="BARRAS",
        indicador_revision="OK",
    )
    fila.update(cambios)
    return fila


def _parada_oficial(numero_guia, transporte, direccion, localidad, **extra):
    return _fila_oficial(
        archivo=f"{numero_guia}.jpg",
        numero_guia=numero_guia,
        numero_transporte=transporte,
        cliente=extra.pop("cliente", "SODIMAC SA"),
        obra_destino=extra.pop("obra_destino", f"OBRA {localidad.upper()}"),
        despachar_a_crudo=direccion,
        direccion_entrega=direccion,
        localidad_entrega=localidad,
        region_entrega="Región X",
        estado_entrega="RESUELTO",
        distancia_km="150.0",
        duracion_min="180.0",
        proveedor_ruta="openrouteservice",
        estado_ruta="RUTA_CALCULADA",
        **extra,
    )


def _reporte(tmp_path, filas):
    origen = tmp_path / "entrada.csv"
    salida = tmp_path / "reporte"
    with origen.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(
            archivo, fieldnames=list(COLUMNAS_OFICIALES), delimiter=";", extrasaction="ignore"
        )
        escritor.writeheader()
        escritor.writerows(filas)
    generar_reporte_viajes(
        origen, salida, carpeta_catalogos=tmp_path / "catalogos", reloj=_RELOJ
    )
    with (salida / "viajes.csv").open(newline="", encoding="utf-8-sig") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def test_e2e_multientrega_y_entrega_unica_en_viajes_csv(tmp_path):
    filas = [
        # Transporte multientrega -- forma del caso real 0000352376.
        _parada_oficial("464698", "0000352376", "AV CAUQUENES 500", "Cauquenes"),
        _parada_oficial("464699", "0000352376", "AV CAUQUENES 500", "Cauquenes"),
        _parada_oficial("464700", "0000352376", "OHIGGINS 1200", "Concepción"),
        # Transporte normal de una sola entrega -- no debe degradarse.
        _parada_oficial("470001", "0000352377", "MANUEL RODRIGUEZ 45", "Chillán"),
    ]
    viajes = {fila["numero_transporte"]: fila for fila in _reporte(tmp_path, filas)}

    multi = json.loads(viajes["0000352376"]["entregas"])
    assert len(multi) == 2
    por_localidad = {e["localidad_entrega"]: e for e in multi}
    assert set(por_localidad) == {"Cauquenes", "Concepción"}
    assert por_localidad["Cauquenes"]["numeros_guia"] == ["464698", "464699"]
    assert por_localidad["Concepción"]["numeros_guia"] == ["464700"]
    for entrega in multi:
        assert entrega["distancia_km"] == "150.0"
        assert entrega["estado_ruta"] == "RUTA_CALCULADA"
    # El viaje sigue CONFIRMADO (diversidad de destino no es conflicto).
    assert viajes["0000352376"]["estado"] == "CONFIRMADO"

    unica = json.loads(viajes["0000352377"]["entregas"])
    assert len(unica) == 1
    assert unica[0]["numeros_guia"] == ["470001"]
    assert unica[0]["destino_operacional"] == "MANUEL RODRIGUEZ 45"
    assert unica[0]["localidad_entrega"] == "Chillán"
