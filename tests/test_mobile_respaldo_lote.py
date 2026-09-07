"""Bloque RESPALDO POR LOTE (Multiguía V2) -- preparación prueba real
"5 guías / 2 viajes".

Problema confirmado por auditoría previa (no implementado en ese momento,
por instrucción explícita): Mobile ya genera/transmite/persiste `lote_id`
para una tanda (varias fotos capturadas antes de "Enviar N guías"), pero
`asociar_documento` nunca lo usaba -- si el OCR no lograba leer
`numero_transporte` en una guía, ésta podía quedar huérfana aunque Mobile
ya supiera que pertenecía a la misma tanda física que otra guía cuyo
transporte SÍ se resolvió.

Este bloque agrega un respaldo genérico y conservador (ver `atlas_core.
mobile.asociar_documento`/`_transportes_resueltos_del_lote`):
`numero_transporte` sigue siendo la única identidad canónica del viaje;
`lote_id` nunca lo reemplaza, sólo aporta evidencia adicional cuando el
mecanismo normal (guía/transporte contra la operación vigente) no
encuentra NADA con qué asociar un documento que tampoco trae evidencia
propia utilizable.

Esta suite prueba, en orden, las pruebas A-J pedidas explícitamente:
A) lote 2, ambos OK; B) lote 2, uno falla y el otro resuelve; C) lote 3,
sólo uno resuelve; D) lote 5/N genérico + Desktop sigue agrupando por
numero_transporte; E) llegada fuera de orden da el mismo resultado; F)
revalidación posterior converge y se estabiliza; G) dos transportes
incompatibles en el mismo lote -- nunca se elige uno; H) idempotencia
(envío/lote/revalidación repetida); I) lote_id ausente -- comportamiento
histórico intacto; J) evidencia propia contradictoria -- nunca se pisa.
"""
from __future__ import annotations

import csv
import uuid
from pathlib import Path

from atlas_core.gestor_viajes import agrupar_viajes
from atlas_core.mobile import (
    RepositorioEnviosMobile, procesar_envio_mobile, revalidar_asociacion_mobile_sin_ocr,
)
from atlas_core.procesamiento_masivo import COLUMNAS


def _dataset_vacio(ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";").writeheader()


def _dataset_con_filas(ruta: Path, filas: list[dict[str, str]]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        for fila in filas:
            escritor.writerow({columna: fila.get(columna, "") for columna in COLUMNAS})


def _leer_filas(dataset: Path) -> list[dict[str, str]]:
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _recibir(repo: RepositorioEnviosMobile, *, lote_id: str = "", chofer_id: str = "c1") -> str:
    envio_id = str(uuid.uuid4())
    metadata: dict[str, object] = {
        "chofer_id": chofer_id, "tipo_novedad": "", "guia_firmada_correo": False,
        "planta_origen_informada": "AZA_COLINA",
    }
    if lote_id:
        metadata["lote_id"] = lote_id
    repo.recibir(envio_id=envio_id, imagen=b"foto", mime="image/jpeg", metadata=metadata)
    return envio_id


def _procesar(repo, envio_id, dataset, guia: str, transporte: str) -> dict:
    return procesar_envio_mobile(
        repo, envio_id, dataset=dataset,
        procesador=lambda ruta: {"numero_guia": guia, "numero_transporte": transporte},
    )


# ============================================================
# A. lote 2 documentos, ambos OCR transporte correcto
# ============================================================

def test_a_lote_dos_documentos_ambos_ok_no_necesitan_respaldo(tmp_path: Path) -> None:
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    repo = RepositorioEnviosMobile(tmp_path)
    lote = str(uuid.uuid4())
    e1 = _recibir(repo, lote_id=lote)
    e2 = _recibir(repo, lote_id=lote)

    r1 = _procesar(repo, e1, dataset, "A1", "0000700000")
    r2 = _procesar(repo, e2, dataset, "A2", "0000700000")
    revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)

    r1 = repo.cargar(e1)
    r2 = repo.cargar(e2)
    assert r1["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"
    assert r2["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"
    assert r1["resultado_asociacion"]["numero_transporte"] == "0000700000"
    assert r2["resultado_asociacion"]["numero_transporte"] == "0000700000"
    # Ninguno de los dos necesitó el respaldo por lote -- ambos se
    # resolvieron por el mecanismo normal (guía/transporte).
    assert "lote" not in r1["resultado_asociacion"]["motivo"].lower()
    assert "lote" not in r2["resultado_asociacion"]["motivo"].lower()


# ============================================================
# B. lote 2, primero falla transporte y segundo lo resuelve
# ============================================================

def test_b_lote_dos_primero_falla_segundo_resuelve_converge_por_respaldo(tmp_path: Path) -> None:
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    # Transporte ya conocido en la operación vigente (p. ej. otro
    # documento previo, no-Mobile) -- así el segundo documento de la
    # tanda se asocia por el mecanismo normal, sin depender de lote_id.
    _dataset_con_filas(dataset, [{"archivo": "desktop/otra.jpg", "numero_guia": "999", "numero_transporte": "0000800000"}])
    repo = RepositorioEnviosMobile(tmp_path)
    lote = str(uuid.uuid4())
    e_falla = _recibir(repo, lote_id=lote)
    e_resuelve = _recibir(repo, lote_id=lote)

    # Guía legible, transporte no ("TRANSPORTE_NO_LEIDO", nunca captura
    # ilegible -- ese bucket ni siquiera entra a revalidación).
    r_falla = _procesar(repo, e_falla, dataset, "B1", "No encontrado")
    assert r_falla["resultado_asociacion"]["estado"] == "SIN_ASOCIACION"

    r_resuelve = _procesar(repo, e_resuelve, dataset, "B2", "0000800000")
    assert r_resuelve["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"

    revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)
    r_falla = repo.cargar(e_falla)
    assert r_falla["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"
    assert r_falla["resultado_asociacion"]["numero_transporte"] == "0000800000"
    assert "lote" in r_falla["resultado_asociacion"]["motivo"].lower()
    assert r_falla["estado"] == "ASOCIADO"


# ============================================================
# C. lote 3, sólo uno logra resolver transporte
# ============================================================

def test_c_lote_tres_solo_uno_resuelve_los_otros_dos_convergen(tmp_path: Path) -> None:
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_con_filas(dataset, [{"archivo": "desktop/otra.jpg", "numero_guia": "999", "numero_transporte": "0000810000"}])
    repo = RepositorioEnviosMobile(tmp_path)
    lote = str(uuid.uuid4())
    e1 = _recibir(repo, lote_id=lote)
    e2 = _recibir(repo, lote_id=lote)
    e3 = _recibir(repo, lote_id=lote)

    _procesar(repo, e1, dataset, "C1", "No encontrado")
    _procesar(repo, e2, dataset, "C2", "No encontrado")
    r3 = _procesar(repo, e3, dataset, "C3", "0000810000")
    assert r3["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"

    revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)
    for envio_id in (e1, e2):
        registro = repo.cargar(envio_id)
        assert registro["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"
        assert registro["resultado_asociacion"]["numero_transporte"] == "0000810000"


# ============================================================
# D. lote 5/N documentos -- genérico, nunca 2+3 hardcodeado
# ============================================================

def test_d_lote_de_n_documentos_converge_y_desktop_agrupa_un_solo_viaje(tmp_path: Path) -> None:
    N = 5  # deliberadamente distinto de 2+3, para no hardcodear la prueba real futura
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_con_filas(dataset, [{"archivo": "desktop/otra.jpg", "numero_guia": "999", "numero_transporte": "0000820000"}])
    repo = RepositorioEnviosMobile(tmp_path)
    lote = str(uuid.uuid4())
    envios = [_recibir(repo, lote_id=lote) for _ in range(N)]

    # Sólo el último documento trae transporte legible; los N-1 restantes
    # llegan con guía legible pero transporte no (nunca captura ilegible).
    for indice, envio_id in enumerate(envios[:-1]):
        _procesar(repo, envio_id, dataset, f"D{indice}", "No encontrado")
    _procesar(repo, envios[-1], dataset, f"D{N}", "0000820000")
    revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)

    for envio_id in envios:
        registro = repo.cargar(envio_id)
        assert registro["resultado_asociacion"]["numero_transporte"] == "0000820000"
        assert registro["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"

    filas = _leer_filas(dataset)
    viajes, _ = agrupar_viajes(filas)
    # Desktop agrupa por numero_transporte normal -- nunca necesitó saber
    # qué es lote_id (ni la columna existe en el dataset).
    assert "lote_id" not in (filas[0].keys() if filas else [])
    viaje_820000 = next(v for v in viajes if v.numero_transporte == "0000820000")
    assert len(viaje_820000.numeros_guia) == N + 1  # las N de Mobile + la fila desktop preexistente


# ============================================================
# E. llegada fuera de orden -- el resultado final no depende del orden
# ============================================================

def test_e_orden_de_llegada_no_cambia_el_resultado_final(tmp_path: Path) -> None:
    fila_previa = {"archivo": "desktop/otra.jpg", "numero_guia": "999", "numero_transporte": "0000830000"}

    # Orden 1: el que resuelve llega PRIMERO -- el que falla converge en
    # su propio primer procesamiento, sin necesitar revalidación.
    dataset_1 = tmp_path / "orden1/analisis_completo_guias.csv"
    _dataset_con_filas(dataset_1, [fila_previa])
    repo_1 = RepositorioEnviosMobile(tmp_path / "orden1")
    lote_1 = str(uuid.uuid4())
    e_resuelve_1 = _recibir(repo_1, lote_id=lote_1)
    e_falla_1 = _recibir(repo_1, lote_id=lote_1)
    _procesar(repo_1, e_resuelve_1, dataset_1, "E1", "0000830000")
    r_falla_1 = _procesar(repo_1, e_falla_1, dataset_1, "E1f", "No encontrado")
    assert r_falla_1["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"
    assert r_falla_1["resultado_asociacion"]["numero_transporte"] == "0000830000"

    # Orden 2: el que falla llega PRIMERO -- converge recién con la
    # revalidación posterior.
    dataset_2 = tmp_path / "orden2/analisis_completo_guias.csv"
    _dataset_con_filas(dataset_2, [fila_previa])
    repo_2 = RepositorioEnviosMobile(tmp_path / "orden2")
    lote_2 = str(uuid.uuid4())
    e_falla_2 = _recibir(repo_2, lote_id=lote_2)
    e_resuelve_2 = _recibir(repo_2, lote_id=lote_2)
    r_falla_2 = _procesar(repo_2, e_falla_2, dataset_2, "E2f", "No encontrado")
    assert r_falla_2["resultado_asociacion"]["estado"] == "SIN_ASOCIACION"
    _procesar(repo_2, e_resuelve_2, dataset_2, "E2", "0000830000")
    revalidar_asociacion_mobile_sin_ocr(repo_2, dataset=dataset_2)
    r_falla_2 = repo_2.cargar(e_falla_2)

    # Mismo resultado final, sin importar el orden real de llegada.
    assert r_falla_2["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"
    assert r_falla_2["resultado_asociacion"]["numero_transporte"] == "0000830000"


# ============================================================
# F. revalidación posterior -- convergencia y estabilización
# ============================================================

def test_f_revalidacion_posterior_converge_y_luego_se_estabiliza(tmp_path: Path) -> None:
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_con_filas(dataset, [{"archivo": "desktop/otra.jpg", "numero_guia": "999", "numero_transporte": "0000840000"}])
    repo = RepositorioEnviosMobile(tmp_path)
    lote = str(uuid.uuid4())
    e_falla = _recibir(repo, lote_id=lote)
    e_resuelve = _recibir(repo, lote_id=lote)

    _procesar(repo, e_falla, dataset, "F1", "No encontrado")
    _procesar(repo, e_resuelve, dataset, "F2", "0000840000")

    resumen_1 = revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)
    assert e_falla in resumen_1["actualizados"]
    assert repo.cargar(e_falla)["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"

    # Segunda pasada: ya no hay nada reintentable -- ninguna asociación
    # ya resuelta se vuelve a tocar (nunca degrada, nunca oscila).
    resumen_2 = revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)
    assert e_falla not in resumen_2["actualizados"]
    assert repo.cargar(e_falla)["resultado_asociacion"]["numero_transporte"] == "0000840000"


# ============================================================
# G. lote con dos transportes incompatibles -- nunca se elige uno
# ============================================================

def test_g_lote_con_transportes_incompatibles_no_autoasocia(tmp_path: Path) -> None:
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_con_filas(dataset, [
        {"archivo": "desktop/t1.jpg", "numero_guia": "991", "numero_transporte": "0000850001"},
        {"archivo": "desktop/t2.jpg", "numero_guia": "992", "numero_transporte": "0000850002"},
    ])
    repo = RepositorioEnviosMobile(tmp_path)
    lote = str(uuid.uuid4())
    e_t1 = _recibir(repo, lote_id=lote)
    e_t2 = _recibir(repo, lote_id=lote)
    e_ambiguo = _recibir(repo, lote_id=lote)

    r_t1 = _procesar(repo, e_t1, dataset, "G1", "0000850001")
    r_t2 = _procesar(repo, e_t2, dataset, "G2", "0000850002")
    assert r_t1["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"
    assert r_t2["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"

    r_ambiguo = _procesar(repo, e_ambiguo, dataset, "G3", "No encontrado")
    revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)
    r_ambiguo = repo.cargar(e_ambiguo)

    assert r_ambiguo["resultado_asociacion"]["estado"] == "PROPUESTA_REQUIERE_REVISION"
    assert r_ambiguo["resultado_asociacion"]["numero_transporte"] == ""
    assert set(r_ambiguo["resultado_asociacion"]["candidatos"]) == {"0000850001", "0000850002"}
    assert r_ambiguo["estado"] == "REQUIERE_REVISION"


# ============================================================
# H. idempotencia -- reintento de envío, lote_id repetido, revalidación repetida
# ============================================================

def test_h_idempotencia_reintento_lote_y_revalidacion(tmp_path: Path) -> None:
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_con_filas(dataset, [{"archivo": "desktop/otra.jpg", "numero_guia": "999", "numero_transporte": "0000860000"}])
    repo = RepositorioEnviosMobile(tmp_path)
    lote = str(uuid.uuid4())
    envio_id = str(uuid.uuid4())
    metadata = {
        "chofer_id": "c1", "tipo_novedad": "", "guia_firmada_correo": False,
        "planta_origen_informada": "AZA_COLINA", "lote_id": lote,
    }
    registro_1, nuevo_1 = repo.recibir(envio_id=envio_id, imagen=b"foto", mime="image/jpeg", metadata=metadata)
    # Reintento de red: MISMO envio_id -- nunca crea un segundo documento.
    registro_2, nuevo_2 = repo.recibir(envio_id=envio_id, imagen=b"foto", mime="image/jpeg", metadata=metadata)
    assert nuevo_1 is True
    assert nuevo_2 is False
    assert registro_1["envio_id"] == registro_2["envio_id"]

    e_falla = _recibir(repo, lote_id=lote)
    _procesar(repo, envio_id, dataset, "H1", "0000860000")
    # El hermano ya estaba resuelto (ASOCIADO_AUTOMATICAMENTE) cuando
    # e_falla se procesó por primera vez -- converge de inmediato, sin
    # necesitar revalidación (mismo caso que la Prueba E, orden 1).
    r_falla = _procesar(repo, e_falla, dataset, "H2", "No encontrado")
    assert r_falla["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"
    assert r_falla["resultado_asociacion"]["numero_transporte"] == "0000860000"

    resumen_1 = revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)
    # Ya no queda nada reintentable -- esta primera revalidación tampoco
    # toca nada (idempotencia frente a una convergencia que ya ocurrió).
    assert e_falla not in resumen_1["actualizados"]
    filas_tras_1 = _leer_filas(dataset)

    # Revalidación repetida converge al MISMO resultado -- ni duplica
    # filas ni cambia el transporte ya asignado.
    resumen_2 = revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)
    assert e_falla not in resumen_2["actualizados"]
    filas_tras_2 = _leer_filas(dataset)
    assert len(filas_tras_1) == len(filas_tras_2)
    assert repo.cargar(e_falla)["resultado_asociacion"]["numero_transporte"] == "0000860000"


# ============================================================
# I. lote_id ausente -- comportamiento histórico intacto
# ============================================================

def test_i_lote_id_ausente_comportamiento_historico_intacto(tmp_path: Path) -> None:
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_con_filas(dataset, [{"archivo": "desktop/otra.jpg", "numero_guia": "999", "numero_transporte": "0000870000"}])
    repo = RepositorioEnviosMobile(tmp_path)
    # Ningún envío de este test trae lote_id -- Mobile V1 histórico
    # (una sola foto, sin tanda).
    e_resuelve = _recibir(repo)
    e_falla = _recibir(repo)

    _procesar(repo, e_resuelve, dataset, "I1", "0000870000")
    r_falla = _procesar(repo, e_falla, dataset, "I2", "No encontrado")
    assert r_falla["resultado_asociacion"]["estado"] == "SIN_ASOCIACION"

    revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)
    r_falla = repo.cargar(e_falla)
    # Sin lote_id que los conecte, nunca convergen entre sí -- exactamente
    # el comportamiento de antes de este bloque.
    assert r_falla["resultado_asociacion"]["estado"] == "SIN_ASOCIACION"
    assert r_falla["resultado_asociacion"]["numero_transporte"] == ""


# ============================================================
# J. numero_transporte explícito contradictorio con el lote -- no se pisa
# ============================================================

def test_j_transporte_propio_contradictorio_con_lote_no_se_sobrescribe(tmp_path: Path) -> None:
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_con_filas(dataset, [{"archivo": "desktop/otra.jpg", "numero_guia": "999", "numero_transporte": "0000880000"}])
    repo = RepositorioEnviosMobile(tmp_path)
    lote = str(uuid.uuid4())
    e_resuelto = _recibir(repo, lote_id=lote)
    e_propio = _recibir(repo, lote_id=lote)

    r_resuelto = _procesar(repo, e_resuelto, dataset, "J1", "0000880000")
    assert r_resuelto["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"

    # Este documento SÍ trae su propia lectura de transporte -- válida en
    # formato, pero un número distinto al que ya resolvió su tanda (nunca
    # matchea nada en la operación vigente todavía). Es evidencia propia,
    # aunque no confirmada -- nunca se pisa con la del lote.
    r_propio = _procesar(repo, e_propio, dataset, "J2", "0000880099")
    assert r_propio["resultado_asociacion"]["estado"] == "SIN_ASOCIACION"
    assert r_propio["resultado_asociacion"]["numero_transporte"] == ""
    assert "lote" not in r_propio["resultado_asociacion"]["motivo"].lower()

    revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)
    r_propio = repo.cargar(e_propio)
    # Sigue sin asociar -- nunca terminó silenciosamente en 0000880000
    # (el transporte del lote) pisando su propia lectura (0000880099).
    assert r_propio["resultado_asociacion"]["estado"] == "SIN_ASOCIACION"
    assert r_propio["resultado_asociacion"]["numero_transporte"] == ""
