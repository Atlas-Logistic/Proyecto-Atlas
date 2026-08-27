"""Bloque ASOCIACIÓN MOBILE V2 -- documento Mobile -> operación/viaje
vigente + reevaluación.

Causa raíz real (caso 472593, envio_id 36e7aa53-214e-48b0-a96c-14989b60e9aa,
preservado en G:\\Mi unidad\\Atlas\\operacion\\mobile\\envios\\, NUNCA
modificado por este bloque): el OCR leyó un `numero_transporte` limpio
(0000355419) pero, en el momento en que este documento se procesó, era
el ÚNICO documento conocido con ese transporte en toda la operación
vigente (`analisis_completo_guias.csv`) -- cero coincidencias, no
ambigüedad. El código anterior ya devolvía SIN_ASOCIACION en ese caso
(comportamiento correcto según Sección 13.2 del bloque: "ninguna
coincidencia -> no inventar asociación"), pero el `motivo` decía "Sin
coincidencia INEQUÍVOCA" -- literalmente lo contrario de lo que había
pasado (no hubo NINGUNA coincidencia, ni ambigua ni clara) -- y no
existía ningún mecanismo para que ese veredicto se revisara solo si más
adelante aparecía un segundo documento con el mismo transporte (el caso
típico de Multiguía: Doc A se procesa antes que Doc B, y Doc A no tiene
con qué asociarse todavía).

Esta suite prueba: (1) el motivo ahora es preciso, (2-3) los tres casos
de asociar_documento, (4) identidad del transporte con ceros iniciales
nunca se corrompe, (5-7) semántica de Multiguía, (8) multiorigen
preservado, (9) reevaluación real, y (10) un fixture fiel del caso
472593.
"""
from __future__ import annotations

import csv
import uuid
from pathlib import Path

from atlas_core.gestor_viajes import agrupar_viajes
from atlas_core.mobile import (
    RepositorioEnviosMobile, asociar_documento, procesar_envio_mobile,
    revalidar_asociacion_mobile_sin_ocr,
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


def _recibir(tmp_path: Path, chofer_id: str = "c1") -> tuple[RepositorioEnviosMobile, str]:
    repo = RepositorioEnviosMobile(tmp_path)
    envio_id = str(uuid.uuid4())
    repo.recibir(
        envio_id=envio_id, imagen=b"foto", mime="image/jpeg",
        metadata={"chofer_id": chofer_id, "tipo_novedad": "", "guia_firmada_correo": False, "planta_origen_informada": "AZA_COLINA"},
    )
    return repo, envio_id


# ============================================================
# 1-3. Los tres casos de asociar_documento (Sección 13.1-13.3)
# ============================================================

def test_transporte_con_coincidencia_existente_se_asocia_automaticamente() -> None:
    datos = {"numero_guia": "999999", "numero_transporte": "0000355419"}
    filas = [{"archivo": "desktop/otra.jpg", "numero_guia": "111111", "numero_transporte": "0000355419"}]
    resultado = asociar_documento(datos, filas)
    assert resultado["estado"] == "ASOCIADO_AUTOMATICAMENTE"
    assert resultado["numero_transporte"] == "0000355419"


def test_transporte_leido_sin_ninguna_coincidencia_no_inventa_asociacion() -> None:
    """Caso 472593: transporte limpio, cero coincidencias -- nunca se
    inventa una asociación sólo porque el texto se leyó bien (Sección 3:
    "mismo texto -> asociación ciega" está prohibido; Sección 13.2)."""
    datos = {"numero_guia": "472593", "numero_transporte": "0000355419"}
    resultado = asociar_documento(datos, filas=[])
    assert resultado["estado"] == "SIN_ASOCIACION"
    assert resultado["numero_transporte"] == ""
    assert resultado["candidatos"] == []
    # El motivo debe ser preciso: "ninguna" coincidencia, nunca "sin
    # coincidencia inequívoca" (esa frase describía ambigüedad, que es
    # justo lo que NO pasó acá).
    assert "ninguna" in resultado["motivo"].lower()
    assert "inequívoca" not in resultado["motivo"].lower()


def test_transporte_con_multiples_candidatos_no_asocia_ciegamente() -> None:
    """La misma guía ya aparece en el dataset con DOS transportes
    distintos (dato contradictorio) -- ambigüedad real, nunca se
    resuelve adivinando uno de los dos."""
    datos = {"numero_guia": "472593", "numero_transporte": "0000355419"}
    filas = [
        {"archivo": "a.jpg", "numero_guia": "472593", "numero_transporte": "0000355419"},
        {"archivo": "b.jpg", "numero_guia": "472593", "numero_transporte": "0000355420"},
    ]
    resultado = asociar_documento(datos, filas)
    assert resultado["estado"] == "PROPUESTA_REQUIERE_REVISION"
    assert resultado["numero_transporte"] == ""
    assert set(resultado["candidatos"]) == {"0000355419", "0000355420"}


# ============================================================
# 4. Ceros iniciales -- identidad exacta, nunca se corrompe/colapsa
# ============================================================

def test_transporte_con_ceros_iniciales_conserva_su_identidad_exacta() -> None:
    """`asociar_documento` nunca reinterpreta el transporte como número
    (nunca `int()`) -- el valor devuelto es carácter por carácter el
    mismo que llegó, ceros incluidos, igual que en el envío real 472593
    (0000355419, 10 dígitos)."""
    datos = {"numero_guia": "999998", "numero_transporte": "0000355419"}
    filas = [{"archivo": "a.jpg", "numero_guia": "111112", "numero_transporte": "0000355419"}]
    resultado = asociar_documento(datos, filas)
    assert resultado["numero_transporte"] == "0000355419"  # nunca "355419"


def test_transportes_con_distinta_cantidad_de_ceros_nunca_se_confunden() -> None:
    """"0000355419" (10 dígitos) y "000355419" (9 dígitos) son STRINGS
    distintos -- si Atlas los tratara como el mismo número (p. ej.
    casteando a int) perdería la capacidad de distinguir dos transportes
    reales que sólo COINCIDEN en valor numérico tras perder el padding
    real que trae la guía impresa. La comparación es exacta, nunca
    numérica."""
    datos = {"numero_guia": "999997", "numero_transporte": "000355419"}
    filas = [{"archivo": "a.jpg", "numero_guia": "111113", "numero_transporte": "0000355419"}]
    resultado = asociar_documento(datos, filas)
    assert resultado["estado"] == "SIN_ASOCIACION"  # no matchea con el de 10 dígitos


# ============================================================
# 5-7. Multiguía: mismo transporte asocia, distinto no, sin transporte no
# ============================================================

def test_multiguia_dos_documentos_mismo_transporte_terminan_asociados_al_mismo_viaje(tmp_path: Path) -> None:
    """Sección 4 del bloque, ejemplo textual: Doc A -> transporte X, Doc
    B -> transporte X. Doc A se procesa primero (sin nada con qué
    asociarse todavía -- SIN_ASOCIACION legítimo); Doc B llega después,
    ve la fila de Doc A ya persistida y se asocia solo; y la
    reevaluación (Sección 7) pone a Doc A al día -- ambos terminan
    ASOCIADO_AUTOMATICAMENTE con el MISMO numero_transporte, sin
    usar lote_id para decidirlo."""
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    repo, envio_a = _recibir(tmp_path)
    _, envio_b = _recibir(tmp_path)
    lote = str(uuid.uuid4())
    repo.guardar(envio_a, {**repo.cargar(envio_a), "lote_id": lote})
    repo.guardar(envio_b, {**repo.cargar(envio_b), "lote_id": lote})

    registro_a = procesar_envio_mobile(
        repo, envio_a, dataset=dataset,
        procesador=lambda ruta: {"numero_guia": "700001", "numero_transporte": "0000700000"},
    )
    assert registro_a["resultado_asociacion"]["estado"] == "SIN_ASOCIACION"  # primero, sin nada con qué asociarse todavía

    registro_b = procesar_envio_mobile(
        repo, envio_b, dataset=dataset,
        procesador=lambda ruta: {"numero_guia": "700002", "numero_transporte": "0000700000"},
    )
    assert registro_b["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"
    assert registro_b["resultado_asociacion"]["numero_transporte"] == "0000700000"

    # Reevaluación: Doc A se pone al día SIN volver a correr OCR, SIN
    # recrear el envío, SIN duplicar su fila en el dataset.
    resumen = revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)
    assert envio_a in resumen["actualizados"]
    registro_a_revisado = repo.cargar(envio_a)
    assert registro_a_revisado["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"
    assert registro_a_revisado["resultado_asociacion"]["numero_transporte"] == "0000700000"
    assert registro_a_revisado["estado"] == "ASOCIADO"

    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    assert len(filas) == 2  # una fila por documento, nunca fusionadas ni duplicadas

    viajes, _ = agrupar_viajes(filas)
    assert len(viajes) == 1
    assert sorted(viajes[0].numeros_guia) == ["700001", "700002"]


def test_multiguia_dos_documentos_transportes_distintos_asociaciones_independientes(tmp_path: Path) -> None:
    """Sección 4: Doc A -> transporte X, Doc C -> transporte Y (misma
    tanda) -- nunca se fusionan, cada uno se asocia (o no) por su propio
    mérito."""
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    repo, envio_a = _recibir(tmp_path)
    _, envio_c = _recibir(tmp_path)

    procesar_envio_mobile(repo, envio_a, dataset=dataset, procesador=lambda r: {"numero_guia": "800001", "numero_transporte": "0000800000"})
    procesar_envio_mobile(repo, envio_c, dataset=dataset, procesador=lambda r: {"numero_guia": "800101", "numero_transporte": "0000800100"})
    revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)

    registro_a = repo.cargar(envio_a)
    registro_c = repo.cargar(envio_c)
    # Ninguno de los dos tiene con qué asociarse (transportes distintos,
    # cada uno único) -- ambos siguen SIN_ASOCIACION, cada uno por su
    # cuenta, nunca agrupados entre sí.
    assert registro_a["resultado_asociacion"]["estado"] == "SIN_ASOCIACION"
    assert registro_c["resultado_asociacion"]["estado"] == "SIN_ASOCIACION"

    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    viajes, _ = agrupar_viajes(filas)
    assert len(viajes) == 2  # dos viajes independientes, nunca uno solo


def test_documento_sin_transporte_no_se_asocia_por_pertenecer_a_la_misma_tanda(tmp_path: Path) -> None:
    """Sección 4/7: un documento sin transporte legible nunca se asocia
    por cercanía/lote_id con otro documento de la misma tanda, aunque
    ese otro sí tenga un transporte inequívoco."""
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    repo, envio_con = _recibir(tmp_path)
    _, envio_sin = _recibir(tmp_path)
    lote = str(uuid.uuid4())
    repo.guardar(envio_con, {**repo.cargar(envio_con), "lote_id": lote})
    repo.guardar(envio_sin, {**repo.cargar(envio_sin), "lote_id": lote})

    procesar_envio_mobile(repo, envio_con, dataset=dataset, procesador=lambda r: {"numero_guia": "900001", "numero_transporte": "0000900000"})
    registro_sin = procesar_envio_mobile(
        repo, envio_sin, dataset=dataset,
        procesador=lambda r: {"numero_guia": "No encontrado", "numero_transporte": "No encontrado"},
    )
    revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)
    registro_sin = repo.cargar(envio_sin)
    assert registro_sin["resultado_asociacion"]["estado"] == "SIN_ASOCIACION"
    assert registro_sin["resultado_asociacion"]["numero_transporte"] == ""


# ============================================================
# 8. Multiorigen: asociar no destruye evidencia de origen por documento
# ============================================================

def test_mismo_transporte_dos_origenes_asociados_conservan_ambas_evidencias(tmp_path: Path) -> None:
    """Sección 6: un mismo viaje puede cargar en dos plantas (reparto,
    regiones). Asociar dos documentos al mismo viaje NO debe promediar
    ni descartar el origen de ninguno de los dos -- ambos quedan
    representados y, si de verdad discrepan, el viaje lo marca como
    conflicto (mecanismo YA existente, no se toca)."""
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    repo, envio_a = _recibir(tmp_path)
    _, envio_b = _recibir(tmp_path)

    procesar_envio_mobile(
        repo, envio_a, dataset=dataset,
        procesador=lambda r: {
            "numero_guia": "910001", "numero_transporte": "0000910000",
            "planta_origen_nombre": "AZA COLINA", "planta_origen_id": "colina-id",
            "origen_determinado_por": "DOCUMENTO", "evidencia_origen": "ENCABEZADO_GUIA",
        },
    )
    procesar_envio_mobile(
        repo, envio_b, dataset=dataset,
        procesador=lambda r: {
            "numero_guia": "910002", "numero_transporte": "0000910000",
            "planta_origen_nombre": "AZA RENCA", "planta_origen_id": "renca-id",
            "origen_determinado_por": "DOCUMENTO", "evidencia_origen": "ENCABEZADO_GUIA",
        },
    )
    revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)
    assert repo.cargar(envio_a)["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"
    assert repo.cargar(envio_b)["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"

    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    viajes, _ = agrupar_viajes(filas)
    assert len(viajes) == 1
    viaje = viajes[0]
    # Ambas evidencias de origen siguen vivas, una por documento -- nunca
    # colapsadas en una sola.
    origenes_por_documento = sorted(d.planta_origen_nombre for d in viaje.documentos)
    assert origenes_por_documento == ["AZA COLINA", "AZA RENCA"]


# ============================================================
# 9. Reevaluación: nunca degrada, nunca reprocesa lo ilegible/pendiente
# ============================================================

def test_revalidar_nunca_degrada_un_envio_ya_asociado(tmp_path: Path) -> None:
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_con_filas(dataset, [{"archivo": "a.jpg", "numero_guia": "920001", "numero_transporte": "0000920000"}])
    repo, envio_id = _recibir(tmp_path)
    registro = procesar_envio_mobile(repo, envio_id, dataset=dataset, procesador=lambda r: {"numero_guia": "920002", "numero_transporte": "0000920000"})
    assert registro["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"

    # El dataset queda vaciado -- si revalidar volviera a evaluar un
    # envío ya asociado, esto lo "desasociaría" en falso.
    _dataset_vacio(dataset)
    resumen = revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)
    assert envio_id not in resumen["actualizados"]
    assert repo.cargar(envio_id)["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"


def test_revalidar_no_toca_envios_con_captura_ilegible(tmp_path: Path) -> None:
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    repo, envio_id = _recibir(tmp_path)
    procesar_envio_mobile(repo, envio_id, dataset=dataset, procesador=lambda r: {"numero_guia": "No encontrado", "numero_transporte": "No encontrado"})
    resumen = revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)
    assert resumen["revisados"] == 0
    assert envio_id not in resumen["actualizados"]


def test_revalidar_no_toca_envios_todavia_sin_procesar() -> None:
    """Un envío recién recibido (sin `datos_ocr` todavía) no debe
    contarse ni tocarse -- nada que reevaluar."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        repo = RepositorioEnviosMobile(Path(tmp))
        envio_id = str(uuid.uuid4())
        repo.recibir(
            envio_id=envio_id, imagen=b"foto", mime="image/jpeg",
            metadata={"tipo_novedad": "", "guia_firmada_correo": False, "planta_origen_informada": "AZA_COLINA"},
        )
        dataset = Path(tmp) / "operacion/actual/analisis_completo_guias.csv"
        _dataset_vacio(dataset)
        resumen = revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)
        assert resumen["revisados"] == 0


# ============================================================
# 10. Regresión 472593 -- fixture fiel del envío real preservado
# ============================================================

def test_regresion_472593_fixture_fiel(tmp_path: Path) -> None:
    """Fixture con los MISMOS datos_ocr del envío real 36e7aa53-214e-
    48b0-a96c-14989b60e9aa (guía 472593, transporte 0000355419) -- el
    envío real en G:\\Mi unidad\\Atlas NUNCA se toca ni se confirma
    (Sección 12 del bloque); esto reproduce su comportamiento contra un
    dataset de prueba aislado.

    Solo, el documento queda SIN_ASOCIACION con un motivo preciso (no
    hay ningún otro documento con ese transporte en la operación
    vigente) -- comportamiento correcto, no un bug. Si más adelante
    aparece un segundo documento real del mismo transporte (p. ej. la
    segunda guía física que Javier tiene reservada -- Sección 12, NO se
    usa en este bloque), la reevaluación lo asocia solo."""
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    repo, envio_id = _recibir(tmp_path, chofer_id="JAVIER_PRUEBA")

    datos_ocr_472593 = {
        "numero_guia": "472593", "numero_transporte": "0000355419",
        "chofer": "LEANDRO TOLEDO", "rut_chofer": "18611137-0", "cliente": "PRODALAM SA",
        "obra_destino": "EMPRESA CONST SIGRO", "patente_tracto": "BKYK63",
        "tipo_carga": "BARRAS", "peso_kg": "12434",
        "motivos_revision_documento": "OBRA_DESTINO_SIN_CORROBORAR",
        "indicador_revision": "REVISAR", "estado_documental": "REQUIERE_REVISION",
    }
    registro = procesar_envio_mobile(repo, envio_id, dataset=dataset, procesador=lambda r: dict(datos_ocr_472593))

    # SIN_ASOCIACION es correcto acá -- es el único documento conocido de
    # este transporte. El estado del ENVÍO es REQUIERE_REVISION por
    # OBRA_DESTINO_SIN_CORROBORAR (indicador_revision=REVISAR), la MISMA
    # razón que en el envío real -- nunca por culpa de la asociación.
    assert registro["resultado_asociacion"]["estado"] == "SIN_ASOCIACION"
    assert registro["resultado_asociacion"]["numero_transporte"] == ""
    assert registro["estado"] == "REQUIERE_REVISION"

    # La fila SÍ quedó persistida en la operación vigente con el
    # transporte leído intacto -- disponible para que agrupar_viajes ya
    # la use, y para que un segundo documento futuro la encuentre.
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    assert len(filas) == 1
    assert filas[0]["numero_transporte"] == "0000355419"

    # Simulación de la 2da guía física de Javier (fixture, nunca la real
    # -- Sección 12: "NO procesarlas en este bloque"): mismo transporte,
    # otra guía.
    repo2, envio_id_2 = _recibir(tmp_path, chofer_id="JAVIER_PRUEBA")
    procesar_envio_mobile(
        repo2, envio_id_2, dataset=dataset,
        procesador=lambda r: {"numero_guia": "472594", "numero_transporte": "0000355419"},
    )
    revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)
    registro_revisado = repo.cargar(envio_id)
    assert registro_revisado["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"
    assert registro_revisado["resultado_asociacion"]["numero_transporte"] == "0000355419"
