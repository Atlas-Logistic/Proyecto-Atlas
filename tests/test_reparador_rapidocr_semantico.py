"""Reparador con RapidOCR: procedencia documental, no sólo formato.

Bloques OCR tomados de la relectura RapidOCR real de laboratorio (23/10)
sobre guías leídas originalmente con EasyOCR de respaldo. Regresiones
obligatorias: nunca una hora de entrada como salida (482580), un monto como
peso (482580), un carro como tracto (482661, 482634). Sin evidencia el
reparador se abstiene y conserva el valor actual.
"""
from __future__ import annotations

import json

from atlas_core import reprocesamiento_reparador as m
from atlas_core.ocr import BloqueOCR
from atlas_core.ocr_manual import RapidOCRManualProvider
from atlas_core.ocr_provider import EasyOCRProvider, RapidOCRProvider
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.reprocesamiento_reparador import BloqueEvidencia, EvidenciaOCR, _reparar_campos_documento
from atlas_core.revalidacion_documental import _escribir_filas_completas, _leer_filas
from atlas_core.trazabilidad_ocr import persistir_traza_ocr
from tests.lectura_ocr_reparador import persistir_lectura


def _evidencia(*bloques: tuple[str, float, float, float, float]) -> EvidenciaOCR:
    return EvidenciaOCR(lineas=tuple(b[0] for b in bloques), bloques=tuple(BloqueEvidencia(*b) for b in bloques))


def _fila(**campos) -> dict[str, str]:
    fila = {columna: "No encontrado" for columna in COLUMNAS}
    fila.update({"archivo": "G.jpeg", "numero_guia": "482580", "motivos_revision_documento": "",
                 "despachar_a_crudo": "", "descripcion_material": "", "metricas_procesamiento_json": ""})
    fila.update(campos)
    return fila


def _cambios(fila, extraido, evidencia, *, degradado=True) -> dict[str, str]:
    cambios = _reparar_campos_documento(fila, extraido, [], documento_degradado=degradado, evidencia_ocr=evidencia)
    return {c.campo: c.valor_nuevo for c in cambios}


# --- 482580: hora de entrada como salida, monto como peso ----------------
LECTURA_482580 = _evidencia(
    ("HORAENTRADA", 396, 465, 355, 369), ("07:10:00", 500, 551, 354, 368),
    ("HORA SALIDA", 395, 457, 366, 379), ("Nro. TRANSPORTE", 395, 470, 380, 392),
    ("0000365023", 500, 560, 380, 392), ("afa15.070,000Pes0nruto", 241, 382, 585, 601),
    ("PESOKG.", 103, 148, 641, 655), ("27:974,00", 166, 212, 641, 658),
    ("NETO $", 103, 140, 700, 714), ("17:624", 163, 196, 700, 714),
)
REEXTRACCION_482580 = {
    "numero_transporte": "0000365023", "cliente": "ACRDMATCOSA", "hora_salida_aza": "07:10",
    "peso_kg": "12624",
    "motivos_revision_documento": "FECHA_SIN_CORROBORAR | CLIENTE_SIN_CORROBORAR | CHOFER_AUSENTE | DOCUMENTO_DEGRADADO",
}


def test_482580_hora_de_entrada_nunca_se_promueve_como_salida():
    assert "hora_salida_aza" not in _cambios(_fila(), REEXTRACCION_482580, LECTURA_482580)


def test_482580_peso_sin_respaldo_documental_se_abstiene():
    assert "peso_kg" not in _cambios(_fila(), REEXTRACCION_482580, LECTURA_482580)


def test_482580_monto_monetario_impreso_no_es_peso():
    cambios = _cambios(_fila(), {**REEXTRACCION_482580, "peso_kg": "17624"}, LECTURA_482580)
    assert "peso_kg" not in cambios


def test_482580_peso_impreso_junto_a_peso_kg_si_se_promueve():
    cambios = _cambios(_fila(), {**REEXTRACCION_482580, "peso_kg": "27974"}, LECTURA_482580)
    assert cambios["peso_kg"] == "27974"


def test_482580_monto_de_la_fila_superior_que_roza_peso_kg_no_es_peso():
    """Segunda lectura real: VALOR TOTAL "13.624" leído "12.624" en y 632-646."""
    lectura = _evidencia(
        ("afa15.070,000Pes0nruto", 241, 382, 585, 601), ("12.624", 164, 201, 632, 646),
        ("PESOKG.", 103, 148, 641, 655), ("27:974,00", 166, 212, 641, 658),
    )
    assert "peso_kg" not in _cambios(_fila(), REEXTRACCION_482580, lectura)
    assert _cambios(_fila(), {**REEXTRACCION_482580, "peso_kg": "27974"}, lectura)["peso_kg"] == "27974"


def test_482580_cliente_que_la_reextraccion_no_corrobora_se_abstiene():
    assert "cliente" not in _cambios(_fila(), REEXTRACCION_482580, LECTURA_482580)


def test_482580_transporte_impreso_se_recupera():
    assert _cambios(_fila(), REEXTRACCION_482580, LECTURA_482580)["numero_transporte"] == "0000365023"


# --- 482661 / 482634: carro como tracto ---------------------------------
LECTURA_482661 = _evidencia(
    ("PATENTE", 543, 607, 986, 1003), ("KN5439CARRO:JF6468", 604, 784, 984, 1003),
    ("R.U.T.", 30, 80, 455, 470), ("78.170.790-2", 240, 330, 455, 470),
)


def test_482661_carro_nunca_se_promueve_como_tracto():
    fila = _fila(numero_guia="482661", patente_rampla="J56468", motivos_revision_documento="PATENTE_SIN_HOMOLOGAR")
    extraido = {"patente_tracto": "JF6468", "patente_rampla": "No encontrado", "cliente": "ARMACERO MATCO SA",
                "rut_cliente": "78.170.790-2", "motivos_revision_documento": "PATENTE_SIN_HOMOLOGAR"}
    cambios = _cambios(fila, extraido, LECTURA_482661)
    assert "patente_tracto" not in cambios
    assert "patente_rampla" not in cambios  # "No encontrado" nunca reemplaza un valor
    assert (cambios["cliente"], cambios["rut_cliente"]) == ("ARMACERO MATCO SA", "78.170.790-2")


def test_482661_tracto_y_carro_en_su_posicion_si_se_promueven():
    fila = _fila(numero_guia="482661", motivos_revision_documento="PATENTE_SIN_HOMOLOGAR")
    cambios = _cambios(fila, {"patente_tracto": "KN5439", "patente_rampla": "JF6468"}, LECTURA_482661)
    assert (cambios["patente_tracto"], cambios["patente_rampla"]) == ("KN5439", "JF6468")


def test_482634_carro_jk2501_no_es_tracto_y_salida_en_su_fila_si():
    lectura = _evidencia(
        ("HORAENTRADA", 393, 476, 340, 359), ("10:19:00", 524, 580, 340, 356),
        ("HORA SALIDA", 395, 464, 356, 370), ("11:48:08", 522, 579, 352, 369),
        ("PATENTE", 423, 471, 702, 719), ("AL1879CARRO:JK2501", 479, 592, 704, 720),
    )
    cambios = _cambios(_fila(numero_guia="482634"), {"patente_tracto": "JK2501", "hora_salida_aza": "11:48"}, lectura)
    assert "patente_tracto" not in cambios
    assert cambios["hora_salida_aza"] == "11:48"
    assert "permanencia_minutos" not in cambios  # sin entrada no hay permanencia


# --- 473325: horas cruzadas; peso por PESO BRUTO - TARA -----------------
LECTURA_473325 = _evidencia(
    ("HORA ENTRADA", 518, 624, 489, 509), ("06:52:00", 691, 758, 492, 512),
    ("HORA SALIDA", 517, 611, 504, 526), ("0:20:19", 688, 759, 509, 529),
    ("Tara:8.920,000 PesoBruto:19.466,000", 274, 580, 861, 881), ("PESOKG.", 34, 102, 962, 982),
)


def test_473325_horas_cruzadas_no_se_promueven_y_peso_bruto_menos_tara_si():
    cambios = _cambios(
        _fila(numero_guia="473325", peso_kg="10246"),
        {"hora_entrada_aza": "00:20", "hora_salida_aza": "06:52", "permanencia_minutos": "392", "peso_kg": "10546"},
        LECTURA_473325,
    )
    assert not {"hora_entrada_aza", "hora_salida_aza", "permanencia_minutos"} & set(cambios)
    assert cambios["peso_kg"] == "10546"


def test_horas_en_su_fila_completan_permanencia_desde_las_horas_finales():
    cambios = _cambios(
        _fila(), {"hora_entrada_aza": "06:52", "hora_salida_aza": "08:20", "permanencia_minutos": "999"},
        _evidencia(("HORA ENTRADA", 0, 100, 0, 10), ("06:52:00", 120, 180, 0, 10),
                   ("HORA SALIDA", 0, 100, 15, 25), ("08:20:19", 120, 180, 15, 25)),
    )
    assert (cambios["hora_entrada_aza"], cambios["hora_salida_aza"], cambios["permanencia_minutos"]) == (
        "06:52", "08:20", "88")


def test_482661_permanencia_no_mezcla_hora_nueva_con_hora_persistida_sin_respaldo():
    lectura = _evidencia(("HORA ENTRADA", 491, 593, 499, 515), ("12:41:00", 647, 723, 499, 516),
                         ("HORASALIDA", 491, 579, 514, 531))
    cambios = _cambios(_fila(hora_entrada_aza="19:55", hora_salida_aza="19:55", permanencia_minutos="0"),
                       {"hora_entrada_aza": "12:41", "permanencia_minutos": "434"}, lectura)
    assert cambios["hora_entrada_aza"] == "12:41"
    assert "permanencia_minutos" not in cambios


def test_destinos_ilegibles_se_abstienen_y_una_direccion_plausible_si_se_completa():
    for ilegible in ("SANTA ISHEEL SSSSANTIAGOLNPA", "LABSTERA 525HANTIAGO", "GALVARINO BSOI QUILICURA",
                     "AV PEDRO AGUIRRE CERDA 13I3 VALDIVIA VALDIVI"):
        assert "despachar_a_crudo" not in _cambios(_fila(), {"despachar_a_crudo": ilegible}, None), ilegible
    cambios = _cambios(_fila(), {"despachar_a_crudo": "VARGAS BUSTOS 899 SAN MIGUEL SAN MIGUEL"}, None)
    assert cambios["despachar_a_crudo"] == "VARGAS BUSTOS 899 SAN MIGUEL SAN MIGUEL"


def test_salida_no_posterior_a_la_entrada_respaldada_no_se_promueve():
    cambios = _cambios(
        _fila(hora_entrada_aza="09:00"), {"hora_salida_aza": "08:20"},
        _evidencia(("HORA ENTRADA", 0, 100, 0, 10), ("09:00:00", 120, 180, 0, 10),
                   ("HORA SALIDA", 0, 100, 15, 25), ("08:20:19", 120, 180, 15, 25)),
    )
    assert "hora_salida_aza" not in cambios


def test_473616_hora_persistida_sin_respaldo_no_bloquea_la_entrada_nueva():
    lectura = _evidencia(("HORA ENTRADA", 478, 565, 496, 510), ("07:15:00", 608, 677, 492, 512),
                         ("HORASALIDA", 477, 553, 508, 525))
    cambios = _cambios(_fila(numero_guia="473616", hora_entrada_aza="00:11", hora_salida_aza="00:11",
                             permanencia_minutos="0"), {"hora_entrada_aza": "07:15"}, lectura)
    assert cambios["hora_entrada_aza"] == "07:15"
    assert "permanencia_minutos" not in cambios


# --- 482553 / 482726: RUT no impreso, destino de otra sección -----------
def test_482553_rut_chofer_no_impreso_no_viaja_con_el_chofer():
    lectura = _evidencia(("RUTCHOFER-", 115, 194, 991, 1008), ("17338559-5", 240, 320, 991, 1008))
    cambios = _cambios(_fila(numero_guia="482553"), {"chofer": "LUIS VARAS", "rut_chofer": "14.293.816-2"}, lectura)
    assert cambios["chofer"] == "LUIS VARAS"
    assert "rut_chofer" not in cambios


def test_482726_destino_con_etiqueta_de_otra_seccion_se_abstiene():
    cambios = _cambios(
        _fila(numero_guia="482726"), {"despachar_a_crudo": "RUTCHOFER VIBTA CIARA Z3ST CELLLOS 9708275-1"},
        _evidencia(("RUTCHOFER", 0, 60, 0, 10)),
    )
    assert "despachar_a_crudo" not in cambios


# --- Sin evidencia: abstención -------------------------------------------
def test_sin_lectura_de_la_relectura_los_literales_se_abstienen():
    extraido = {"peso_kg": "27974", "hora_salida_aza": "08:21", "patente_tracto": "AL1879",
                "rut_chofer": "9708225-1", "numero_transporte": "0000365023", "chofer": "RENE GARCIA"}
    cambios = _cambios(_fila(), extraido, None)
    assert set(cambios) == {"chofer"}


def test_mismo_vehiculo_como_tracto_y_carro_no_se_promueve():
    lectura = _evidencia(("PATENTE", 0, 60, 0, 10), ("AB1234", 120, 180, 0, 10))
    cambios = _cambios(_fila(), {"patente_tracto": "AB1234", "patente_rampla": "AB1234"}, lectura)
    assert not {"patente_tracto", "patente_rampla"} & set(cambios)


# --- RapidOCR reconocido como relectura del OCR principal ----------------
def test_rapidocr_y_su_variante_manual_cuentan_como_ocr_principal():
    assert m._backend_reextraccion(RapidOCRProvider()) == "RapidOCRProvider"
    assert m._backend_reextraccion(RapidOCRManualProvider()) == "RapidOCRProvider"
    assert "RapidOCRProvider" in m._BACKENDS_OCR_PRINCIPALES


def test_relectura_rapidocr_de_lectura_easyocr_repara_solo_lo_respaldado(tmp_path, monkeypatch):
    """Extremo a extremo: lectura previa EasyOCR, relectura RapidOCR (482661)."""
    raiz = tmp_path / "atlas"
    actual = raiz / "operacion" / "actual"
    (actual / "manifiestos_ingesta").mkdir(parents=True)
    (raiz / "operacion" / "entradas" / "L1").mkdir(parents=True)
    (raiz / "catalogos_privados").mkdir(parents=True)
    (actual / "manifiestos_ingesta" / "L1.json").write_text(json.dumps({"schema_version": 1, "lote": "L1", "seleccion": [
        {"nombre_archivo": "482661.jpeg", "ruta_origen": "C:/o/482661.jpeg",
         "ingresado_en_utc": "2026-10-21T13:46:33Z", "sha256": "x"}]}), encoding="utf-8")
    (raiz / "operacion" / "entradas" / "L1" / "482661.jpeg").write_bytes(b"img")
    fila = _fila(archivo="482661.jpeg", numero_guia="482661", numero_transporte="0000363214",
                 patente_rampla="J56468", cliente="No encontrado",
                 motivos_revision_documento="PATENTE_SIN_HOMOLOGAR | CLIENTE_AUSENTE",
                 estado_procesamiento="OK", estado_ruta="")
    _escribir_filas_completas(actual / "analisis_completo_guias.csv", [fila])
    (actual / "decisiones_aplicadas.json").write_text(json.dumps({"aplicaciones": []}), encoding="utf-8")
    persistir_traza_ocr(
        directorio=raiz / "operacion" / "trazas_ocr", referencia_imagen="482661.jpeg", textos=["basura"],
        bloques=None, proveedor=EasyOCRProvider(lector=object()),
    )
    bloques = [BloqueOCR(b.texto, ((b.x0, b.y0), (b.x1, b.y0), (b.x1, b.y1), (b.x0, b.y1)), 0.9)
               for b in LECTURA_482661.bloques]

    def procesar(ruta, **kw):
        valores = {"patente_tracto": "JF6468", "patente_rampla": "No encontrado", "cliente": "ARMACERO MATCO SA",
                   "rut_cliente": "78.170.790-2", "motivos_revision_documento": "PATENTE_SIN_HOMOLOGAR"}
        persistir_lectura(kw, valores, bloques)
        return valores

    monkeypatch.setattr(m, "procesar_archivo", procesar)
    resultado = m.reprocesar_lote_reparador(raiz_atlas=raiz, nombre_lote="L1", dry_run=False,
                                            proveedor=RapidOCRProvider())
    cambios = {c["campo"]: c["despues"] for c in resultado["documentos"][0]["cambios"]}
    assert cambios == {"cliente": "ARMACERO MATCO SA", "rut_cliente": "78.170.790-2"}
    tras = _leer_filas(actual / "analisis_completo_guias.csv")[0]
    assert (tras["patente_tracto"], tras["patente_rampla"]) == ("No encontrado", "J56468")
    assert json.loads(tras["metricas_procesamiento_json"])["recuperacion_p0"]["relectura_ocr_principal"][
        "backend_relectura"] == "RapidOCRProvider"
