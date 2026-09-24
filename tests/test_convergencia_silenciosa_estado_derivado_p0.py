"""Bloque P0 CONVERGENCIA SILENCIOSA -- ESTADO DERIVADO HUÉRFANO. Caso
real medido (guía 474252, Cristopher Retamal): `_segunda_pasada_
universal` resolvía silenciosamente un campo (vía `convergencia_
vehiculo`/`convergencia_cliente`/`convergencia_obra`) y corregía el
valor operacional, pero nunca limpiaba el motivo de revisión que ese
valor documental había disparado -- el viaje quedaba REQUIERE_REVISION/
INCOMPLETO_TECNICO con una tarjeta huérfana (PATENTE_SIN_HOMOLOGAR) aun
con el valor ya canónico.

Estos tests son GENÉRICOS -- ninguno usa 474252, BPHR67 ni Cristopher
Retamal; reutilizan el fixture ya auditado de
`test_segunda_pasada_universal_f3.py`. Todo en `tmp_path`, sin red, sin
proveedores, sin G."""
from __future__ import annotations

import csv

from atlas_core.catalogo_vehiculos import TipoVehiculo
from atlas_core.procesamiento_masivo import _segunda_pasada_universal
from tests.test_segunda_pasada_universal_f3 import (
    _carpeta, _cliente, _confirmar_vehiculo, _csv, _decision_vehiculo, _dos_ramplas,
    _fila, _fila_vehiculo, _obra_confirmada,
)


def _leer_fila(ruta_csv):
    with ruta_csv.open(encoding="utf-8-sig", newline="") as f:
        return next(csv.DictReader(f, delimiter=";"))


# ==========================================================================
# A -- patente OCR muy degradada + evidencia canónica única fuerte
#      -> valor canónico + motivo stale eliminado
# ==========================================================================


def test_a_patente_degradada_con_evidencia_unica_limpia_motivo_stale(tmp_path):
    carpeta = _carpeta(tmp_path)
    _confirmar_vehiculo(carpeta, "JD8659", TipoVehiculo.TRACTO, rut_chofer_asociado="15489424-1")

    # 2 posiciones distintas de "JD8659" -- fuera de la tolerancia
    # documental de 1 carácter, pero dentro del techo calibrado para una
    # asociación humana única (`_DISTANCIA_MAXIMA_ANCLA_HUMANA = 2`,
    # Bloque P0 CONVERGENCIA VEHÍCULO: ese techo nunca es ilimitado, pero
    # sí más generoso que el documental).
    fila = _fila(
        rut_chofer="15489424-1", chofer="CARLOS SIMON", patente_tracto="JD8611",
        motivos_revision_documento="PATENTE_SIN_HOMOLOGAR",
        indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION",
        estado_operacional="REQUIERE_REVISION", estado_ruta="RUTA_CALCULADA",
    )
    ruta_csv = _csv(tmp_path, [fila])
    dec = _decision_vehiculo(valor="JD8611", campo="patente_tracto")

    m = _segunda_pasada_universal(ruta_csv, {"g1.jpeg"}, [dec], None, carpeta)
    assert m["resueltas_determinista"] == 1

    fila_final = _leer_fila(ruta_csv)
    assert fila_final["patente_tracto"] == "JD8659"
    assert "PATENTE_SIN_HOMOLOGAR" not in fila_final["motivos_revision_documento"]
    assert fila_final["indicador_revision"] == "OK"
    assert fila_final["estado_documental"] == "OK"
    # Sin otro motivo pendiente y con ruta ya calculada -> converge a OK.
    assert fila_final["estado_operacional"] == "OK"


# ==========================================================================
# B -- misma situación, pero existe OTRO motivo técnico independiente
#      -> se elimina SÓLO el motivo de patente; el otro permanece
# ==========================================================================


def test_b_motivo_independiente_sobrevive_a_la_limpieza_de_patente(tmp_path):
    carpeta = _carpeta(tmp_path)
    _confirmar_vehiculo(carpeta, "JD8659", TipoVehiculo.TRACTO, rut_chofer_asociado="15489424-1")

    fila = _fila(
        rut_chofer="15489424-1", chofer="CARLOS SIMON", patente_tracto="JD8611",
        motivos_revision_documento="PATENTE_SIN_HOMOLOGAR | MATERIAL_AUSENTE",
        indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION",
        estado_operacional="REQUIERE_REVISION", estado_ruta="RUTA_CALCULADA",
    )
    ruta_csv = _csv(tmp_path, [fila])
    dec = _decision_vehiculo(valor="JD8611", campo="patente_tracto")

    m = _segunda_pasada_universal(ruta_csv, {"g1.jpeg"}, [dec], None, carpeta)
    assert m["resueltas_determinista"] == 1

    fila_final = _leer_fila(ruta_csv)
    assert fila_final["patente_tracto"] == "JD8659"
    motivos = {x.strip() for x in fila_final["motivos_revision_documento"].split("|") if x.strip()}
    assert "PATENTE_SIN_HOMOLOGAR" not in motivos
    assert "MATERIAL_AUSENTE" in motivos
    # MATERIAL_AUSENTE es informativo (MOTIVOS_NO_BLOQUEANTES) -- el
    # indicador puede volver a OK igual; lo que importa es que el motivo
    # independiente NUNCA se borró por la limpieza de patente.


def test_b2_motivo_independiente_bloqueante_mantiene_revision(tmp_path):
    """Variante con un motivo independiente que SÍ bloquea (no está en
    MOTIVOS_NO_BLOQUEANTES) -- el viaje debe seguir en revisión por ESE
    motivo, aunque la patente ya converja."""
    carpeta = _carpeta(tmp_path)
    _confirmar_vehiculo(carpeta, "JD8659", TipoVehiculo.TRACTO, rut_chofer_asociado="15489424-1")

    fila = _fila(
        rut_chofer="15489424-1", chofer="CARLOS SIMON", patente_tracto="JD8611",
        motivos_revision_documento="PATENTE_SIN_HOMOLOGAR | CLIENTE_AUSENTE",
        indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION",
        estado_operacional="REQUIERE_REVISION", estado_ruta="RUTA_CALCULADA",
    )
    ruta_csv = _csv(tmp_path, [fila])
    dec = _decision_vehiculo(valor="JD8611", campo="patente_tracto")

    _segunda_pasada_universal(ruta_csv, {"g1.jpeg"}, [dec], None, carpeta)

    fila_final = _leer_fila(ruta_csv)
    motivos = {x.strip() for x in fila_final["motivos_revision_documento"].split("|") if x.strip()}
    assert "PATENTE_SIN_HOMOLOGAR" not in motivos
    assert "CLIENTE_AUSENTE" in motivos
    assert fila_final["indicador_revision"] == "REVISAR"
    assert fila_final["estado_documental"] == "REQUIERE_REVISION"
    assert fila_final["estado_operacional"] == "REQUIERE_REVISION"


# ==========================================================================
# C -- convergencia ambigua / no silenciosa -> NO limpiar el motivo
# ==========================================================================


def test_c_convergencia_ambigua_no_limpia_motivo(tmp_path):
    carpeta = _carpeta(tmp_path)
    _dos_ramplas(carpeta)  # dos candidatos confirmados para el mismo RUT -> ambigüedad, ABSTENCION

    fila = _fila_vehiculo(
        indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION",
        estado_operacional="REQUIERE_REVISION",
    )
    ruta_csv = _csv(tmp_path, [fila])

    from tests.test_segunda_pasada_universal_f3 import _OrquestadorFalso
    orq = _OrquestadorFalso(modo="ABSTENCION")
    m = _segunda_pasada_universal(ruta_csv, {"g1.jpeg"}, [_decision_vehiculo()], orq, carpeta)
    assert m["resueltas_determinista"] == 0

    fila_final = _leer_fila(ruta_csv)
    # Valor documental intacto -- la convergencia no resolvió nada.
    assert fila_final["patente_rampla"] == "JD8629"
    assert "PATENTE_SIN_HOMOLOGAR" in fila_final["motivos_revision_documento"]
    assert fila_final["indicador_revision"] == "REVISAR"
    assert fila_final["estado_documental"] == "REQUIERE_REVISION"
    assert fila_final["estado_operacional"] == "REQUIERE_REVISION"


# ==========================================================================
# D -- cliente resuelto silenciosamente -> limpia SÓLO el motivo de cliente
# ==========================================================================


def test_d_cliente_resuelto_limpia_solo_motivo_de_cliente(tmp_path):
    carpeta = _carpeta(tmp_path)
    _cliente(carpeta, razon_social="PRODALAM SA", rut="93.772.000-9")

    fila = _fila(
        cliente="PRODALAM SA", rut_cliente="",
        motivos_revision_documento="CLIENTE_SIN_CORROBORAR | MATERIAL_AUSENTE",
        indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION",
        estado_operacional="REQUIERE_REVISION", estado_ruta="RUTA_CALCULADA",
    )
    ruta_csv = _csv(tmp_path, [fila])

    from atlas_core.decisiones_pendientes import detectar_decisiones_documento
    decisiones = list(detectar_decisiones_documento(
        archivo="g1.jpeg",
        datos={"número de guía": "900001", "número de transporte": "T-1",
               "cliente": "PRODALAM SA", "RUT del cliente": ""},
        carpeta_catalogos=carpeta,
    ))

    m = _segunda_pasada_universal(ruta_csv, {"g1.jpeg"}, decisiones, None, carpeta)
    assert m["resueltas_determinista"] >= 1

    fila_final = _leer_fila(ruta_csv)
    assert fila_final["cliente"] == "PRODALAM SA"
    motivos = {x.strip() for x in fila_final["motivos_revision_documento"].split("|") if x.strip()}
    assert "CLIENTE_SIN_CORROBORAR" not in motivos
    assert "MATERIAL_AUSENTE" in motivos  # motivo independiente, conservado


# ==========================================================================
# E -- obra resuelta silenciosamente -> limpia SÓLO el motivo de obra
# ==========================================================================


def test_e_obra_resuelta_limpia_solo_motivo_de_obra(tmp_path):
    carpeta = _carpeta(tmp_path)
    cliente = _cliente(carpeta, razon_social="YOLITO BALART HNOS LTDA", rut="80.565.900-9")
    _obra_confirmada(
        carpeta, cliente, nombre_obra="CASA HELSINSKI",
        direccion="HELSINSKI 5810 LA REINA SANTIAGO", aliases=("INMOB CASA RELSINSKI SPA",),
    )
    ocr = "INMOB CASA VELINSKI SPA"
    fila = _fila(
        cliente="YOLITO BALART HNOS LTDA", rut_cliente="80565900-9",
        obra_destino=ocr, despachar_a_crudo="HELSINSKI 5810 LA REINA SANTIAGO",
        motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR | MATERIAL_AUSENTE",
        indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION",
        estado_operacional="REQUIERE_REVISION", estado_ruta="RUTA_CALCULADA",
    )
    ruta_csv = _csv(tmp_path, [fila])

    from atlas_core.decisiones_pendientes import detectar_decisiones_documento
    decisiones = list(detectar_decisiones_documento(
        archivo="g1.jpeg",
        datos={"número de guía": "900001", "número de transporte": "T-1",
               "cliente": "YOLITO BALART HNOS LTDA", "RUT del cliente": "80565900-9",
               "obra destino": ocr},
        carpeta_catalogos=carpeta,
    ))

    m = _segunda_pasada_universal(ruta_csv, {"g1.jpeg"}, decisiones, None, carpeta)
    assert m["resueltas_determinista"] >= 1

    fila_final = _leer_fila(ruta_csv)
    assert fila_final["obra_destino"] == "CASA HELSINSKI"
    motivos = {x.strip() for x in fila_final["motivos_revision_documento"].split("|") if x.strip()}
    assert "OBRA_DESTINO_SIN_CORROBORAR" not in motivos
    assert "MATERIAL_AUSENTE" in motivos


# ==========================================================================
# F -- el OCR/raw original permanece intacto (auditoría), sólo cambia lo
#      operacional/canónico
# ==========================================================================


def test_f_raw_ocr_permanece_intacto_en_la_auditoria(tmp_path):
    carpeta = _carpeta(tmp_path)
    _confirmar_vehiculo(carpeta, "JD8659", TipoVehiculo.TRACTO, rut_chofer_asociado="15489424-1")

    fila = _fila(
        rut_chofer="15489424-1", chofer="CARLOS SIMON", patente_tracto="JD8611",
        motivos_revision_documento="PATENTE_SIN_HOMOLOGAR",
        indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION",
        estado_operacional="REQUIERE_REVISION", estado_ruta="RUTA_CALCULADA",
    )
    ruta_csv = _csv(tmp_path, [fila])
    dec = _decision_vehiculo(valor="JD8611", campo="patente_tracto")

    m = _segunda_pasada_universal(ruta_csv, {"g1.jpeg"}, [dec], None, carpeta)

    # El valor operacional cambió...
    fila_final = _leer_fila(ruta_csv)
    assert fila_final["patente_tracto"] == "JD8659"
    # ...pero el OCR crudo original queda preservado en la auditoría de
    # la resolución determinista -- nunca se pierde ni se sobrescribe.
    assert len(m["resoluciones_deterministas"]) == 1
    resolucion = m["resoluciones_deterministas"][0]
    assert resolucion["valor_ocr"] == "JD8611"
    assert resolucion["valor_canonico"] == "JD8659"
