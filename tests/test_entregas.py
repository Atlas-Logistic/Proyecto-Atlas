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


# ---------------------------------------------------------------------------
# 6b. Bloque VIAJE MULTIENTREGA V1.1 -- un typo de OCR de un solo carácter
# en la dirección no debe dividir una entrega real (caso real 0000359510)
# ---------------------------------------------------------------------------
def test_typo_ocr_de_un_caracter_en_direccion_no_divide_la_entrega():
    # Caso real 0000359510 (chofer SALOMÓN PIZARRO): 474285 imprime "SANTA
    # ISADEL 585 SANTIAGO LAMPA" (OCR confundió B/D, visualmente
    # parecidas); 474286 y 474287 imprimen correctamente "SANTA ISABEL 585
    # SANTIAGO LAMPA". Las tres son el mismo destino operacional -- antes
    # de este bloque, ese único carácter dividía el viaje en 2 entregas
    # (DIRECTO real presentado como REPARTO falso).
    _, entregas = _entregas_de([
        _parada("474285", "SANTA ISADEL 585 SANTIAGO LAMPA", "Lampa"),
        _parada("474286", "SANTA ISABEL 585 SANTIAGO LAMPA", "Lampa"),
        _parada("474287", "SANTA ISABEL 585 SANTIAGO LAMPA", "Lampa"),
    ])
    assert len(entregas) == 1
    assert entregas[0]["numeros_guia"] == ["474285", "474286", "474287"]


def test_dos_typos_ocr_en_direccion_larga_siguen_tolerados():
    # Misma tolerancia ya usada y aprobada para reutilizar un destino
    # confirmado (`catalogo_destinos._limite_tolerancia_ocr_direccion`):
    # direcciones de más de 25 caracteres toleran hasta 2 sustituciones.
    _, entregas = _entregas_de([
        _parada("1", "AVENIDA LAS INDUSTRIAS 4850", "Renca"),
        _parada("2", "AVENIDA LAS IN0USTRIA5 4850", "Renca"),
    ])
    assert len(entregas) == 1


def test_direcciones_con_mas_diferencias_que_un_typo_no_se_fusionan():
    # Salvaguarda del bloque anterior: no se convierte en fuzzy matching
    # abierto -- una dirección genuinamente distinta (o con más de 1-2
    # caracteres distintos) sigue separando la entrega.
    _, entregas = _entregas_de([
        _parada("1", "SANTA ISABEL 585 SANTIAGO LAMPA", "Lampa"),
        _parada("2", "SANTA MONICA 585 SANTIAGO LAMPA", "Lampa"),
    ])
    assert len(entregas) == 2


def test_direcciones_de_distinta_longitud_no_reciben_tolerancia():
    # Longitudes distintas podrían ser una calle real más corta/larga, no
    # un typo de un solo carácter en la misma posición -- sin tolerancia.
    _, entregas = _entregas_de([
        _parada("1", "SANTA ISABEL 585", "Lampa"),
        _parada("2", "SANTA ISABEL 5850", "Lampa"),
    ])
    assert len(entregas) == 2


# ---------------------------------------------------------------------------
# 6c. Bloque VIAJE MULTIENTREGA V1.1 -- ruta consolidada de una entrega
# fusionada por tolerancia OCR: varios documentos calcularon RUTA EXITOSA
# antes de reconocerse como la misma entrega, con resultados numéricos
# distintos -- reutilizar la ruta de la mayoría (nunca promediar/inventar)
# ---------------------------------------------------------------------------
def _parada_con_ruta(numero_guia, direccion, localidad, **cambios_ruta):
    """Como `_parada`, pero permite sobreescribir cualquier campo de ruta
    (incluidos los que `_parada` ya fija por defecto) sin chocar por
    keyword duplicado."""
    fila = _parada(numero_guia, direccion, localidad)
    fila.update(cambios_ruta)
    return fila


def test_ruta_de_la_mayoria_se_reutiliza_cuando_hay_typo_ocr_en_un_documento():
    # Caso real 0000359510: 474285 calculó ruta a "SANTA ISADEL" (typo),
    # 474286/474287 calcularon la MISMA ruta real a "SANTA ISABEL". Los
    # tres ya se fusionan en una entrega (tolerancia OCR); la ruta debe
    # ser la de la mayoría (474286/474287), nunca un promedio ni vacío.
    _, entregas = _entregas_de([
        _parada_con_ruta("474285", "SANTA ISADEL 585 SANTIAGO LAMPA", "Lampa", distancia_km="8.5231", duracion_min="14.44"),
        _parada_con_ruta("474286", "SANTA ISABEL 585 SANTIAGO LAMPA", "Lampa", distancia_km="6.5048", duracion_min="10.85"),
        _parada_con_ruta("474287", "SANTA ISABEL 585 SANTIAGO LAMPA", "Lampa", distancia_km="6.5048", duracion_min="10.85"),
    ])
    assert len(entregas) == 1
    assert entregas[0]["numeros_guia"] == ["474285", "474286", "474287"]
    assert entregas[0]["distancia_km"] == "6.5048"
    assert entregas[0]["duracion_min"] == "10.85"
    assert entregas[0]["estado_ruta"] == "RUTA_CALCULADA"
    # El destino operacional PUBLICADO de la parada también debe ser el de
    # la mayoría -- nunca "el primer documento que llegó" (474285, el del
    # typo). Antes de este bloque `destino_operacional` usaba
    # `_primer_presente`, ciego a cuál dirección es la real.
    assert entregas[0]["destino_operacional"] == "SANTA ISABEL 585 SANTIAGO LAMPA"


def test_destino_operacional_de_la_mayoria_no_depende_del_orden_de_los_documentos():
    # Mismo caso real, pero con el documento del typo llegando AL FINAL en
    # vez de primero -- `_primer_presente` habría acertado por casualidad
    # en ese orden; la mayoría debe dar el mismo resultado sin importar el
    # orden de llegada de los documentos.
    _, entregas = _entregas_de([
        _parada_con_ruta("474286", "SANTA ISABEL 585 SANTIAGO LAMPA", "Lampa", distancia_km="6.5048", duracion_min="10.85"),
        _parada_con_ruta("474287", "SANTA ISABEL 585 SANTIAGO LAMPA", "Lampa", distancia_km="6.5048", duracion_min="10.85"),
        _parada_con_ruta("474285", "SANTA ISADEL 585 SANTIAGO LAMPA", "Lampa", distancia_km="8.5231", duracion_min="14.44"),
    ])
    assert len(entregas) == 1
    assert entregas[0]["destino_operacional"] == "SANTA ISABEL 585 SANTIAGO LAMPA"


def test_destino_operacional_sin_mayoria_estricta_usa_el_primer_documento_como_antes():
    # Empate real (1 contra 1): sin mayoría estricta, se conserva el
    # comportamiento previo a este bloque (primer valor presente) -- nunca
    # deja de mostrar un destino que sí existe sólo por el empate.
    _, entregas = _entregas_de([
        _parada_con_ruta("1", "SANTA ISADEL 585 SANTIAGO LAMPA", "Lampa", distancia_km="8.5231", duracion_min="14.44"),
        _parada_con_ruta("2", "SANTA ISABEL 585 SANTIAGO LAMPA", "Lampa", distancia_km="6.5048", duracion_min="10.85"),
    ])
    assert len(entregas) == 1
    assert entregas[0]["destino_operacional"] == "SANTA ISADEL 585 SANTIAGO LAMPA"


def test_ruta_sin_mayoria_estricta_se_abstiene_nunca_promedia():
    # 2 documentos, 2 rutas exitosas distintas -- empate real, ninguna
    # mayoría. Atlas se abstiene (NUNCA centroide/promedio).
    _, entregas = _entregas_de([
        _parada_con_ruta("1", "SANTA ISADEL 585 SANTIAGO LAMPA", "Lampa", distancia_km="8.5231", duracion_min="14.44"),
        _parada_con_ruta("2", "SANTA ISABEL 585 SANTIAGO LAMPA", "Lampa", distancia_km="6.5048", duracion_min="10.85"),
    ])
    assert len(entregas) == 1  # misma entrega (tolerancia OCR), pero...
    assert entregas[0]["distancia_km"] == ""  # ...sin mayoría, se abstiene
    assert entregas[0]["duracion_min"] == ""
    assert entregas[0]["estado_ruta"] == ""


def test_ruta_de_la_mayoria_no_aplica_si_alguna_ruta_fallo():
    # Mezcla de éxito + fallo real -- no es el caso que cubre este bloque
    # (todas exitosas pero distintas); debe seguir abstiniéndose como
    # antes, nunca "ganarle" al fallo con una mayoría de éxitos.
    _, entregas = _entregas_de([
        _parada_con_ruta("1", "SANTA ISADEL 585 SANTIAGO LAMPA", "Lampa", distancia_km="8.5231", duracion_min="14.44"),
        _parada_con_ruta(
            "2", "SANTA ISABEL 585 SANTIAGO LAMPA", "Lampa",
            distancia_km="", duracion_min="", proveedor_ruta="",
            estado_ruta="SIN_CANDIDATO", motivo_ruta="GEOCODIFICACION_AMBIGUA",
        ),
        _parada_con_ruta(
            "3", "SANTA ISABEL 585 SANTIAGO LAMPA", "Lampa",
            distancia_km="", duracion_min="", proveedor_ruta="",
            estado_ruta="SIN_CANDIDATO", motivo_ruta="GEOCODIFICACION_AMBIGUA",
        ),
    ])
    assert len(entregas) == 1
    # 2 fallos iguales + 1 éxito: sigue la regla YA existente de "un solo
    # modo de fallo coherente" -- conserva el diagnóstico, nunca la ruta.
    assert entregas[0]["distancia_km"] == ""
    assert entregas[0]["estado_ruta"] == "SIN_CANDIDATO"


# ---------------------------------------------------------------------------
# 6d. P0 D2 -- un candidato de destino rechazado/de baja confianza nunca
# puede ganar la mayoría e imponerse como destino operacional.
# ---------------------------------------------------------------------------
def test_destino_operacional_nunca_es_un_valor_contaminado_aunque_gane_por_mayoria():
    # 3 documentos comparten el mismo código territorial opaco (evidencia
    # operacional POSITIVA que ya agrupa la entrega independientemente de
    # `direccion_entrega`, ver `_destino_compatible`). 2 de las 3 traen un
    # `direccion_entrega` contaminado por una etiqueta de otra sección
    # ("PATENTE BDFG50" -- INVÁLIDO según
    # `credibilidad_campos.evaluar_credibilidad_direccion`); la tercera sí
    # trae la dirección real. Antes del fix, la mayoría (2 contra 1)
    # imponía el valor contaminado como destino operacional -- exactamente
    # el candidato rechazado/de baja confianza reapareciendo por
    # consolidación que el invariante P0 D2 prohíbe.
    codigo = dict(codigo_pais="CL", codigo_unidad="RENCA", codigo_contexto="0001")
    _, entregas = _entregas_de([
        _parada("1", "PATENTE BDFG50", "Quilicura", **codigo),
        _parada("2", "PATENTE BDFG50", "Quilicura", **codigo),
        _parada("3", "SAN LUIS 1201 QUILICURA", "Quilicura", **codigo),
    ])
    assert len(entregas) == 1
    assert entregas[0]["destino_operacional"] == "SAN LUIS 1201 QUILICURA"


def test_destino_operacional_sin_ningun_valor_confiable_no_inventa_uno():
    # Si TODOS los `direccion_entrega` de la entrega son dudosos/inválidos,
    # nunca se elige el "menos malo" por mayoría -- se cae al mismo
    # respaldo documental ya usado cuando no hay `direccion_entrega` en
    # absoluto (`despachar_a_crudo`).
    codigo = dict(codigo_pais="CL", codigo_unidad="RENCA", codigo_contexto="0002")
    _, entregas = _entregas_de([
        _parada_con_ruta("1", "PATENTE BDFG50", "Quilicura", despachar_a_crudo="", **codigo),
        _parada_con_ruta(
            "2", "PATENTE BDFG50", "Quilicura",
            despachar_a_crudo="SAN LUIS 1201 QUILICURA", **codigo,
        ),
    ])
    assert len(entregas) == 1
    assert entregas[0]["destino_operacional"] == "SAN LUIS 1201 QUILICURA"


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
