"""Viaje físico multitransporte confirmado por humano
(`atlas_core.agrupacion_viajes` + `gestor_viajes.agrupar_viajes` +
VIAJE_AGRUPAR_GUIAS + B1). Datos sintéticos; el caso real (dos cargas AZA
del mismo chofer/camión/día, un solo reparto) se reproduce como
comportamiento, sin que sus números sean lógica de producción."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.agrupacion_viajes import (
    evaluar_agrupacion, mapa_transporte_a_grupo, registrar_agrupacion,
)
from atlas_core.b1_operador import OperadorB1
from atlas_core.gestor_viajes import EstadoViaje, MotivoRevision, agrupar_viajes
from atlas_core.procesamiento_masivo import COLUMNAS

T1, T2, T3 = "0000900469", "0000900569", "0000900777"


def _fila(guia, transporte, **extra):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": f"{guia}.jpeg", "estado_procesamiento": "OK", "numero_guia": guia, "numero_transporte": transporte,
        "fecha": "26-09-2026", "chofer": "LUIS REYES", "rut_chofer": "12.345.678-5", "patente_tracto": "KN5439",
        "patente_rampla": "JF6468", "cliente": "CLIENTE UNO SA", "obra_destino": "CLIENTE UNO SA",
        "despachar_a_crudo": "LA ESTERA 525", "direccion_entrega": "LA ESTERA 525", "planta_origen_id": "p-colina",
        "planta_origen_nombre": "AZA COLINA", "hora_entrada_aza": "07:18", "hora_salida_aza": "08:27",
        "peso_kg": "12000", "estado_ruta": "RUTA_CALCULADA", "distancia_km": "7.0038", "duracion_min": "15",
        "indicador_revision": "OK", "estado_documental": "OK", "estado_operacional": "OK",
    })
    fila.update(extra)
    return fila


def _dos_cargas(**extra_segunda):
    return [_fila("600694", T1),
            _fila("600733", T2, hora_entrada_aza="09:38", hora_salida_aza="10:55", peso_kg="16119", **extra_segunda),
            _fila("600900", T3, chofer="OTRO CHOFER", rut_chofer="15.432.876-9", patente_tracto="ZZ1111")]


# ------------------------------------------------------------ gestor_viajes


def test_sin_agrupaciones_el_agrupamiento_por_transporte_no_cambia():
    viajes, _ = agrupar_viajes(_dos_cargas(), guias_revision_humana=())
    assert sorted(v.numero_transporte for v in viajes) == [T1, T2, T3]
    assert all(v.a_dict()["transportes_aza"] == [v.numero_transporte] for v in viajes)


def test_transportes_agrupados_son_un_viaje_con_id_y_transporte_del_principal():
    viajes, _ = agrupar_viajes(_dos_cargas(), guias_revision_humana=(), agrupaciones_transporte={T1: T1, T2: T1})
    por_transporte = {v.numero_transporte: v for v in viajes}
    assert sorted(por_transporte) == [T1, T3]
    unico = por_transporte[T1]
    assert unico.viaje_id == str(uuid5(NAMESPACE_URL, f"atlas:viaje:{T1}"))  # mismo id que tenía el principal
    assert unico.transportes_aza == [T1, T2]
    assert unico.numeros_guia == ["600694", "600733"]
    # cada transporte es su propia visita a planta: horas distintas NO son conflicto
    assert unico.estado == EstadoViaje.CONFIRMADO, unico.motivos_revision
    assert unico.peso_total_viaje_kg == "28119"
    assert {d.evidencia["numero_transporte"] for d in unico.documentos} == {T1, T2}  # datos AZA intactos por guía
    assert unico.hora_entrada_aza == "" and unico.permanencia_minutos == ""  # dos visitas: no se inventa una


def test_agrupado_sigue_exigiendo_mismo_chofer_y_detecta_horas_contradictorias_dentro_de_un_transporte():
    filas = _dos_cargas(rut_chofer="15.432.876-9", chofer="OTRO")
    viajes, _ = agrupar_viajes(filas, guias_revision_humana=(), agrupaciones_transporte={T1: T1, T2: T1})
    unico = next(v for v in viajes if v.numero_transporte == T1)
    assert MotivoRevision.CONFLICTO_RUT_CHOFER in unico.motivos_revision

    filas = _dos_cargas() + [_fila("600695", T1, hora_entrada_aza="11:00", hora_salida_aza="12:00")]
    viajes, _ = agrupar_viajes(filas, guias_revision_humana=(), agrupaciones_transporte={T1: T1, T2: T1})
    unico = next(v for v in viajes if v.numero_transporte == T1)
    assert MotivoRevision.CONFLICTO_HORA_ENTRADA in unico.motivos_revision


# ------------------------------------------------------------ evaluación / registro


def test_evaluacion_rechaza_condiciones_estructurales_inseguras():
    base = _dos_cargas()
    assert evaluar_agrupacion(guias=["600694", "600733"], filas=base, agrupaciones=()).motivo_rechazo == ""
    casos = {
        "fecha": _dos_cargas(fecha="27-09-2026"),
        "chofer": _dos_cargas(rut_chofer="15.432.876-9"),
        "tracto": _dos_cargas(patente_tracto="AB1234"),
        "rampla": _dos_cargas(patente_rampla="AB1234"),
    }
    for etiqueta, filas in casos.items():
        motivo = evaluar_agrupacion(guias=["600694", "600733"], filas=filas, agrupaciones=()).motivo_rechazo
        assert etiqueta in motivo, (etiqueta, motivo)
    assert "no existe" in evaluar_agrupacion(guias=["600694", "999999"], filas=base, agrupaciones=()).motivo_rechazo
    otra = [{"estado": "ACTIVA", "transportes": [T2, T3]}]
    assert "otra agrupación" in evaluar_agrupacion(guias=["600694", "600733"], filas=base, agrupaciones=otra).motivo_rechazo
    eventos = [{"numero_transporte": T2, "estado": "ACTIVO", "tipo_evento": "TIENE_ESTADIA"}]
    assert "eventos" in evaluar_agrupacion(guias=["600694", "600733"], filas=base, agrupaciones=(),
                                           eventos=eventos).motivo_rechazo
    # eventos del transporte PRINCIPAL no se pierden (sigue siendo la clave del viaje)
    eventos_principal = [{"numero_transporte": T1, "estado": "ACTIVO"}]
    assert evaluar_agrupacion(guias=["600694", "600733"], filas=base, agrupaciones=(),
                              eventos=eventos_principal).motivo_rechazo == ""


def test_misma_guia_o_mismo_transporte_ya_es_el_mismo_viaje():
    filas = _dos_cargas() + [_fila("600695", T1)]
    evaluacion = evaluar_agrupacion(guias=["600694", "600695"], filas=filas, agrupaciones=())
    assert evaluacion.ya_agrupadas and not evaluacion.motivo_rechazo


def test_registro_idempotente_y_mapa_ignora_agrupaciones_contradictorias(tmp_path):
    a, creada = registrar_agrupacion(tmp_path, transportes=[T2, T1], guias=["600733", "600694"],
                                     actor="B1", confirmado_por="JAVIER", fuente="TEST")
    b, creada_otra = registrar_agrupacion(tmp_path, transportes=[T1, T2], guias=["600694"],
                                          actor="B1", confirmado_por="JAVIER", fuente="TEST")
    assert creada and not creada_otra and a["agrupacion_id"] == b["agrupacion_id"]
    assert len(json.loads((tmp_path / "agrupaciones_viaje.json").read_text(encoding="utf-8"))["agrupaciones"]) == 1
    with pytest.raises(ValueError):
        registrar_agrupacion(tmp_path, transportes=[T2, T3], guias=[], actor="B1", confirmado_por="J", fuente="T")
    assert mapa_transporte_a_grupo([{"transportes": [T1, T2]}]) == {T1: T1, T2: T1}
    assert mapa_transporte_a_grupo([{"transportes": [T1, T2]}, {"transportes": [T2, T3]}]) == {}


# ------------------------------------------------------------ B1 / capa (caso real como comportamiento)


@pytest.fixture
def raiz(tmp_path):
    raiz = tmp_path / "AtlasCopia"
    cat, actual = raiz / "catalogos_privados", raiz / "operacion" / "actual"
    cat.mkdir(parents=True)
    actual.mkdir(parents=True)
    (cat / "choferes.json").write_text(json.dumps(
        {"123456785": {"nombre": "LUIS REYES", "rut": "12.345.678-5", "aliases": [], "activo": True}}), encoding="utf-8")
    for nombre, contenido in {"vehiculos.json": {"version": 1, "vehiculos": []}, "empresas.json": {},
                              "clientes.json": {"version_formato": 1, "clientes": []},
                              "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
                              "destinos_maestros.json": {"version_formato": 1, "destinos": []},
                              "plantas.json": {"plantas": []}}.items():
        (cat / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    with (actual / "analisis_completo_guias.csv").open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(_dos_cargas())
    return raiz


def _viajes_del_ultimo_reporte(raiz: Path):
    estado = json.loads((raiz / "operacion" / "actual" / "estado_operacion.json").read_text(encoding="utf-8"))
    ruta = Path(estado["reporte_vigente"])
    ruta = ruta if ruta.is_absolute() else raiz / ruta
    return list(csv.DictReader((ruta / "viajes.csv").open(encoding="utf-8-sig", newline=""), delimiter=";"))


def test_b1_mismo_viaje_preview_confirmacion_aplicacion_e_idempotencia(raiz):
    actual = raiz / "operacion" / "actual"
    dataset_antes = hashlib.sha256((actual / "analisis_completo_guias.csv").read_bytes()).hexdigest()
    b1 = OperadorB1(raiz)

    r = b1.atender("c", "Las guías 600694 y 600733 pertenecen al mismo viaje")
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert r["accion"] == "VIAJE_AGRUPAR_GUIAS"
    assert f"transporte {T1} (guía 600694)" in r["mensaje"] and f"transporte {T2} (guía 600733)" in r["mensaje"]
    assert r["preview"]["valor_propuesto"]["viaje_unico"]["transportes_aza"] == [T1, T2]
    assert not (actual / "agrupaciones_viaje.json").exists()  # nada escrito antes del "sí"

    e = b1.atender("c", "sí")
    assert e["estado"] == "EJECUTADA", e
    registro = json.loads((actual / "agrupaciones_viaje.json").read_text(encoding="utf-8"))["agrupaciones"]
    assert len(registro) == 1 and registro[0]["transportes"] == [T1, T2]
    assert registro[0]["confirmado_por"] == "JAVIER" and registro[0]["actor"] == "B1"
    assert e["resultado"]["revalidacion"]["reporte"]["regenerado"] is True
    viajes = {v["numero_transporte"]: v for v in _viajes_del_ultimo_reporte(raiz)}
    assert sorted(viajes) == [T1, T3]
    assert viajes[T1]["transportes_aza"] == f"{T1} | {T2}"
    assert viajes[T1]["numeros_guia"] == "600694 | 600733"
    assert viajes[T1]["estado"] == "CONFIRMADO"
    # dataset documental intacto: cada guía conserva su transporte AZA
    assert hashlib.sha256((actual / "analisis_completo_guias.csv").read_bytes()).hexdigest() == dataset_antes
    auditoria = b1.capa.auditoria()
    assert [a["accion"] for a in auditoria] == ["VIAJE_AGRUPAR_GUIAS"]

    # repetir la instrucción: ya pertenecen al mismo viaje, sin tocar nada
    r = b1.atender("c", "Las guías 600733 y 600694 son del mismo viaje")
    assert r["estado"] == "SIN_CAMBIOS"
    assert "ya pertenecen al mismo viaje" in r["mensaje"]
    assert len(json.loads((actual / "agrupaciones_viaje.json").read_text(encoding="utf-8"))["agrupaciones"]) == 1
    assert len(b1.capa.auditoria()) == 1


def test_b1_agrupacion_insegura_muestra_el_motivo_y_no_escribe(raiz):
    b1 = OperadorB1(raiz)
    r = b1.atender("c", "Las guías 600694 y 600900 pertenecen al mismo viaje")
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "PRECONDICION_FALLIDA"
    assert "No es seguro agruparlas" in r["mensaje"]
    assert not (raiz / "operacion" / "actual" / "agrupaciones_viaje.json").exists()
    assert b1.atender("c", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"


def test_capa_catalogo_expone_la_accion_como_reversible():
    from atlas_core.acciones_operacionales import catalogo_acciones
    accion = {a["accion"]: a for a in catalogo_acciones()}["VIAJE_AGRUPAR_GUIAS"]
    assert accion["riesgo"] == "OPERACIONAL_REVERSIBLE" and accion["parametros"]["guias"]["obligatorio"]
    assert isinstance(CapaAccionesOperacionales, type)


# ------------------------------------------------------------ multiplanta / multidestino
# Forma del caso real (sin sus números): 2 transportes AZA cargados en 2
# plantas distintas, 4 guías, 3 entregas (dos guías comparten una).
TA, TB = "0000800122", "0000800179"


def _multiplanta():
    def f(guia, transporte, planta_id, planta, horas, peso, destino, localidad, unidad, km):
        return _fila(guia, transporte, planta_origen_id=planta_id, planta_origen_nombre=planta,
                     origen_determinado_por="CATEGORIA_DESTINO_EXTERNO", hora_entrada_aza=horas[0],
                     hora_salida_aza=horas[1], peso_kg=peso, despachar_a_crudo=destino, direccion_entrega=destino,
                     localidad_entrega=localidad, codigo_unidad=unidad, distancia_km=km, fecha="24-09-2026",
                     chofer="CHOFER MULTI", rut_chofer="16.789.012-1", patente_tracto="AB1234", patente_rampla="CD5678")
    return [
        f("700597", TA, "p-norte", "PLANTA NORTE", ("14:02", "14:49"), "11973", "LAS HORTENSIAS 3800", "Talcahuano", "08110", "522.3"),
        f("700598", TA, "p-norte", "PLANTA NORTE", ("14:02", "14:49"), "3008", "AV CUATRO NORTE 1565", "Concepcion", "08101", "518.1"),
        f("700603", TB, "p-sur", "PLANTA SUR", ("16:47", "16:47"), "1002", "CALLE D LOTE 27 CORONEL", "Coronel", "08102", "535.9"),
        f("700604", TB, "p-sur", "PLANTA SUR", ("16:47", "16:47"), "11938", "CALLE D LOTE 27 CORONEL", "Coronel", "08102", "535.9"),
    ]


def test_multiplanta_un_viaje_con_3_entregas_pesos_propios_y_sin_conflicto_de_origen_falso():
    sueltos, _ = agrupar_viajes(_multiplanta(), guias_revision_humana=())
    assert len(sueltos) == 2 and all(v.estado == EstadoViaje.CONFIRMADO for v in sueltos)
    viajes, _ = agrupar_viajes(_multiplanta(), guias_revision_humana=(), agrupaciones_transporte={TA: TA, TB: TA})
    assert len(viajes) == 1
    viaje = viajes[0]
    assert viaje.transportes_aza == [TA, TB] and viaje.numeros_guia == ["700597", "700598", "700603", "700604"]
    # dos plantas = dos cargas, no una contradicción del viaje
    assert MotivoRevision.CONFLICTO_ORIGEN not in viaje.motivos_revision
    assert viaje.estado == EstadoViaje.CONFIRMADO, viaje.motivos_revision
    assert viaje.planta_origen_nombre == ""  # nunca se elige una planta única
    # cada guía conserva SU transporte, planta y peso documental
    propios = {d.numero_guia: (d.evidencia["numero_transporte"], d.planta_origen_nombre, d.peso_kg) for d in viaje.documentos}
    assert propios == {"700597": (TA, "PLANTA NORTE", "11973"), "700598": (TA, "PLANTA NORTE", "3008"),
                       "700603": (TB, "PLANTA SUR", "1002"), "700604": (TB, "PLANTA SUR", "11938")}
    assert viaje.peso_total_viaje_kg == "27921"
    # 3 entregas, dos guías compartiendo la misma, cada una con SU ruta
    entregas = {tuple(e["numeros_guia"]): e for e in viaje.entregas}
    assert set(entregas) == {("700597",), ("700598",), ("700603", "700604")}
    assert entregas[("700597",)]["distancia_km"] == "522.3"
    assert entregas[("700598",)]["distancia_km"] == "518.1"
    assert entregas[("700603", "700604")]["distancia_km"] == "535.9"  # nunca la del transporte principal
    assert viaje.distancia_km == ""  # sin ruta única inventada a nivel de viaje


def test_multiplanta_sigue_detectando_plantas_contradictorias_dentro_de_un_mismo_transporte():
    filas = _multiplanta()
    filas[1].update(planta_origen_id="p-sur", planta_origen_nombre="PLANTA SUR")
    viajes, _ = agrupar_viajes(filas, guias_revision_humana=(), agrupaciones_transporte={TA: TA, TB: TA})
    assert MotivoRevision.CONFLICTO_ORIGEN in viajes[0].motivos_revision


@pytest.fixture
def raiz_multiplanta(raiz):
    with (raiz / "operacion" / "actual" / "analisis_completo_guias.csv").open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(_multiplanta())
    return raiz


def test_b1_preview_multiplanta_explicito_aplicacion_e_idempotencia(raiz_multiplanta):
    raiz = raiz_multiplanta
    actual = raiz / "operacion" / "actual"
    b1 = OperadorB1(raiz)
    r = b1.atender("c", "Las guías 700597, 700598, 700603 y 700604 pertenecen al mismo viaje")
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    mensaje = r["mensaje"]
    assert f"transporte {TA} en PLANTA NORTE (14:02-14:49): guía 700597 11.973 kg, guía 700598 3.008 kg" in mensaje
    assert f"transporte {TB} en PLANTA SUR (16:47-16:47): guía 700603 1.002 kg, guía 700604 11.938 kg" in mensaje
    assert "3 ENTREGA(S)" in mensaje
    assert "guía 700597 -> LAS HORTENSIAS 3800 (Talcahuano), 522 km" in mensaje
    assert "guía 700598 -> AV CUATRO NORTE 1565 (Concepcion), 518 km" in mensaje
    assert "guía 700603, 700604 -> CALLE D LOTE 27 CORONEL (Coronel), 536 km" in mensaje
    assert "Peso total 27.921 kg" in mensaje and "Estado resultante: CONFIRMADO" in mensaje
    entregas = r["preview"]["valor_propuesto"]["viaje_unico"]["entregas"]
    assert [e["guias"] for e in entregas] == [["700597"], ["700598"], ["700603", "700604"]]
    assert not (actual / "agrupaciones_viaje.json").exists()

    assert b1.atender("c", "sí")["estado"] == "EJECUTADA"
    viajes = [v for v in _viajes_del_ultimo_reporte(raiz) if TA in v["transportes_aza"]]
    assert len(viajes) == 1 and viajes[0]["estado"] == "CONFIRMADO"
    publicadas = json.loads(viajes[0]["entregas"])
    assert sorted(tuple(e["numeros_guia"]) for e in publicadas) == [("700597",), ("700598",), ("700603", "700604")]

    r = b1.atender("c", "Las guías 700604, 700597, 700598 y 700603 pertenecen al mismo viaje")
    assert r["estado"] == "SIN_CAMBIOS" and "ya pertenecen al mismo viaje" in r["mensaje"]
    assert len(json.loads((actual / "agrupaciones_viaje.json").read_text(encoding="utf-8"))["agrupaciones"]) == 1
