"""Bloque CIERRE GENERAL DE LOS 9 INCOMPLETO_TECNICO (Codex, segunda
pasada aceptada como diagnóstico base) -- tests de CAPACIDAD permanentes,
uno por cada capacidad general nueva/corregida en este bloque. Ninguno
depende de los archivos vivos de G: (todos construyen su propio
dataset/ledger/catálogo mínimo en `tmp_path` o bloques OCR sintéticos con
`BloqueOCR`), pero cada fixture reproduce la geometría/datos REALES que
motivaron la capacidad -- nunca un literal por número de guía en el
código de producción, sólo en el comentario que documenta el caso.

Casos reales que motivan cada capacidad (ver PLAN MÍNIMO GENERAL, segunda
pasada): 472623/472624 (obra ausente bloquea ruteo), 472037 (destino
humano confirmado, dependencia previa resuelta), 472211 (captura
recortada severa + corroboración documental), 472437 (contaminación
GIRO/SEÑOR + unión multibloque), 464453 (GUIA_AUSENTE recuperable),
464170/464746 (dirección confirmada por humano vs geocodificación
imprecisa), 472477/472541 (bug de huella_ruta / AGOTABLE)."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

from atlas_core.decisiones_pendientes import (
    detectar_decision_destino_no_resuelto,
)
from atlas_core.extractor import (
    _extraer_asociaciones_geometricas,
    _extraer_despachar_a_geometrico,
    _extraer_numero_guia_geometrico,
)
from atlas_core.ocr import BloqueOCR
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.reconciliacion_estado_derivado import (
    ESTADO_ESPERA_ACCION_HUMANA,
    ESTADO_ESPERA_EVIDENCIA,
    _ciclo_vida_pendiente,
    _huella_ruta,
    _registro_pendiente,
)
from atlas_core.revalidacion_documental import (
    revalidar_destino_vacio_confirmado_por_documento_sin_ocr,
)


def _bloque(texto, x, y, ancho=None, alto=18):
    ancho = ancho if ancho is not None else max(30, len(texto) * 8)
    return BloqueOCR(
        texto=texto,
        bounding_box=((x, y), (x + ancho, y), (x + ancho, y + alto), (x, y + alto)),
        confianza=0.9,
    )


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "9999999.jpeg", "estado_procesamiento": "OK",
        "indicador_revision": "REVISAR", "estado_documental": "OK",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _leer_csv(ruta):
    with ruta.open("r", newline="", encoding="utf-8-sig") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


# =====================================================================
# Item 1 -- obra ausente bloquea el ruteo (caso real 472623/472624):
# motivo_ruta/estado_ruta vacíos NO son automáticamente "nada que
# preguntar" cuando la obra nunca se extrajo Y ya hay una dirección
# documental real que preguntar junto.
# =====================================================================

def test_obra_ausente_con_direccion_conocida_genera_accion_util():
    fila = {
        "numero_guia": "OBRA-AUSENTE-1", "numero_transporte": "T-OA-1",
        "planta_origen_id": "planta-1", "estado_ruta": "", "motivo_ruta": "",
        "obra_destino": "No encontrado", "despachar_a_crudo": "AV SIEMPRE VIVA 123 COMUNA X",
    }
    decision = detectar_decision_destino_no_resuelto(archivo="9999999.jpeg", fila=fila)

    assert decision is not None
    assert "OBRA_AUSENTE_BLOQUEA_RUTEO" in decision["motivos"]


def test_obra_ausente_sin_direccion_documental_no_pregunta_todavia():
    """Sin una dirección documental real que preguntar junto, no hay
    acción humana útil NUEVA -- Atlas nunca inventa una pregunta sin
    evidencia que ofrecerle a Javier."""
    fila = {
        "numero_guia": "OBRA-AUSENTE-2", "numero_transporte": "T-OA-2",
        "planta_origen_id": "planta-1", "estado_ruta": "", "motivo_ruta": "",
        "obra_destino": "No encontrado", "despachar_a_crudo": "",
    }

    assert detectar_decision_destino_no_resuelto(archivo="9999999.jpeg", fila=fila) is None


def test_obra_ausente_bloquea_ruteo_tambien_en_ciclo_de_vida_pendiente():
    """Misma capacidad, reflejada en la explicación de
    `pendientes_tecnicos.json` (`_ciclo_vida_pendiente`) -- no sólo en la
    generación de la tarjeta."""
    fila = {
        "numero_guia": "OBRA-AUSENTE-3", "planta_origen_id": "planta-1",
        "despachar_a_crudo": "AV SIEMPRE VIVA 123", "cliente": "CLIENTE X",
        "obra_destino": "", "destino_id": "", "motivo_ruta": "",
    }
    registro = _registro_pendiente(fila, previo=None)
    resultado = _ciclo_vida_pendiente(
        registro, instante=datetime.now(timezone.utc),
        direccion_confirmada_por_humano=False, destino_terminado_por_humano=False,
    )

    assert resultado["estado_espera"] == ESTADO_ESPERA_ACCION_HUMANA
    assert resultado["causa_siguiente_accion"] == "OBRA_AUSENTE_BLOQUEA_RUTEO"


# =====================================================================
# Item 2 -- destino humano ya confirmado, dependencia previa resuelta
# (caso real 472037): reaplica automáticamente sin volver a preguntar.
# =====================================================================

def test_destino_confirmado_por_ledger_se_reaplica_al_resolver_origen(tmp_path):
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [
        _fila_csv(
            numero_guia="472037-SIM", numero_transporte="T-472037",
            planta_origen_id="planta-1", despachar_a_crudo="",
            estado_ruta="", motivo_ruta="", obra_destino="OBRA CONOCIDA",
        ),
    ])
    ledger = tmp_path / "decisiones_aplicadas.json"
    ledger.write_text(json.dumps({
        "schema_version": 1,
        "aplicaciones": [{
            "decision_id": "d-472037", "tipo": "DESTINO_NO_RESUELTO",
            "accion": "REGISTRAR_DIRECCION", "actor": "JAVIER_DESKTOP",
            "documento": {
                "archivo": "472037.jpeg", "numero_guia": "472037-SIM",
                "numero_transporte": "T-472037",
            },
            "direccion_manual": "VICUÑA MACKENNA 655",
        }],
    }), encoding="utf-8")

    resultado = revalidar_destino_vacio_confirmado_por_documento_sin_ocr(
        ruta_dataset=dataset, ruta_ledger=ledger,
    )

    assert resultado["guias_actualizadas"] == ["472037-SIM"]
    fila_final = _leer_csv(dataset)[0]
    assert fila_final["despachar_a_crudo"] == "VICUÑA MACKENNA 655"


def test_destino_confirmado_por_ledger_nunca_se_reaplica_a_otra_guia(tmp_path):
    """Seguridad de identidad: la clave es (numero_guia, numero_transporte)
    -- una confirmación del ledger nunca se aplica a una fila de OTRO
    documento aunque comparta cualquier otro dato."""
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [
        _fila_csv(
            numero_guia="OTRA-GUIA", numero_transporte="T-OTRA",
            planta_origen_id="planta-1", despachar_a_crudo="",
            estado_ruta="", motivo_ruta="",
        ),
    ])
    ledger = tmp_path / "decisiones_aplicadas.json"
    ledger.write_text(json.dumps({
        "schema_version": 1,
        "aplicaciones": [{
            "tipo": "DESTINO_NO_RESUELTO", "accion": "REGISTRAR_DIRECCION",
            "documento": {"numero_guia": "472037-SIM", "numero_transporte": "T-472037"},
            "direccion_manual": "VICUÑA MACKENNA 655",
        }],
    }), encoding="utf-8")

    resultado = revalidar_destino_vacio_confirmado_por_documento_sin_ocr(
        ruta_dataset=dataset, ruta_ledger=ledger,
    )

    assert resultado["guias_actualizadas"] == []
    assert _leer_csv(dataset)[0]["despachar_a_crudo"] == ""


def test_destino_confirmado_por_ledger_nunca_pisa_ruta_ya_calculada(tmp_path):
    """Sin dependencia bloqueada que resolver (la ruta ya convergió),
    nunca hay nada que reaplicar -- evita pisar un resultado ya bueno."""
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [
        _fila_csv(
            numero_guia="472037-SIM", numero_transporte="T-472037",
            planta_origen_id="planta-1", despachar_a_crudo="OTRA DIRECCION YA CALCULADA",
            estado_ruta="RUTA_CALCULADA", motivo_ruta="",
        ),
    ])
    ledger = tmp_path / "decisiones_aplicadas.json"
    ledger.write_text(json.dumps({
        "schema_version": 1,
        "aplicaciones": [{
            "tipo": "DESTINO_NO_RESUELTO", "accion": "REGISTRAR_DIRECCION",
            "documento": {"numero_guia": "472037-SIM", "numero_transporte": "T-472037"},
            "direccion_manual": "VICUÑA MACKENNA 655",
        }],
    }), encoding="utf-8")

    resultado = revalidar_destino_vacio_confirmado_por_documento_sin_ocr(
        ruta_dataset=dataset, ruta_ledger=ledger,
    )

    assert resultado["guias_actualizadas"] == []
    assert _leer_csv(dataset)[0]["despachar_a_crudo"] == "OTRA DIRECCION YA CALCULADA"


# =====================================================================
# Item 3 -- captura recortada SEVERA + corroboración documental (caso
# real 472211: ancla "AR A", falta "DESPACH" completo).
# =====================================================================

def _bloques_472211(*, con_duplicado: bool):
    bloques = [
        _bloque("AR A", 0, 1175, 35, 14),
        _bloque("RETIRA", 511, 1167, 54, 16),
        _bloque("PATENTE", 509, 1179, 70, 20),
        _bloque("ESTERA", 129, 1173, 54, 16),
        _bloque("634", 189, 1173, 26, 14),
        _bloque("LANPA", 221, 1173, 46, 14),
    ]
    if con_duplicado:
        bloques += [
            _bloque("ESTERA", 191, 613, 52, 14),
            _bloque("634", 249, 611, 26, 14),
            _bloque("LAMPA", 167, 631, 44, 14),
        ]
    return bloques


def test_ancla_severamente_recortada_se_acepta_con_duplicado_documental():
    resultado = _extraer_despachar_a_geometrico(_bloques_472211(con_duplicado=True))

    assert resultado.get("valor") == "ESTERA 634 LANPA"
    assert resultado.get("senal_calidad_captura") == "CAPTURA_RECORTADA_POSIBLE"


def test_ancla_severamente_recortada_sin_duplicado_se_abstiene():
    """Sin un segundo valor independiente en el documento que corrobore
    el candidato, la tolerancia MUY corta ("AR A") nunca se acepta sola
    -- nunca se relaja el umbral de longitud del ancla."""
    resultado = _extraer_despachar_a_geometrico(_bloques_472211(con_duplicado=False))

    assert resultado == {}


# =====================================================================
# Item 4 -- contaminación GIRO/SEÑOR + unión multibloque (caso real
# 472437): el valor real de SEÑOR(ES) no debe perderse contra GIRO
# cuando GIRO no tiene ningún candidato mejor, y un nombre partido en 3+
# cajas OCR debe unirse completo.
# =====================================================================

def _bloques_472437():
    # Geometría simplificada (no pixel-exacta) del layout real de 472437:
    # SEÑOR(ES) es una etiqueta más ALTA que una línea normal (bloque OCR
    # real de 45px de alto vs ~18px del resto) y GIRO queda justo debajo,
    # en la misma columna -- el valor real de SEÑOR(ES) ("AGF ACEROS DE
    # CHILE SPA") cae geométricamente entre ambas etiquetas, más cerca de
    # SEÑOR(ES) que de GIRO, pero dentro del alcance de las dos. La
    # reproducción exacta a nivel de píxel depende de la mediana de
    # altura de los ~260 bloques de la imagen completa (no práctica en un
    # fixture) -- aquí se preserva el mismo patrón estructural con un
    # margen robusto, no un empate al límite de precisión de punto
    # flotante.
    return [
        _bloque("SEÑOR(ES)", 114, 348, 102, 45),
        _bloque("GIRO", 116, 390, 54, 32),
        _bloque("AGF ACEROS", 260, 375, 92, 18),
        _bloque("DE", 356, 381, 22, 14),
        _bloque("CHILE", 384, 381, 46, 16),
        _bloque("SPA", 436, 385, 28, 14),
        _bloque("SOLICITANTE", 645, 401, 103, 25),
        _bloque("OBRA DESTINO", 648, 438, 114, 24),
        _bloque("CONSTRUCTORA", 829, 436, 111, 24),
        _bloque("IGNACIO", 947, 439, 64, 14),
        _bloque("HURTADO", 1017, 439, 66, 16),
        # Etiqueta administrativa "Código Cliente" -- nunca el campo
        # SEÑOR(ES)/nombre real, aunque su texto sea exactamente "CLIENTE".
        _bloque("CODIGO", 121, 295, 70, 40),
        _bloque("CLIENTE", 180, 309, 65, 40),
    ]


def test_giro_no_absorbe_el_valor_real_de_senor_por_falta_de_candidato_propio():
    resultado = _extraer_asociaciones_geometricas(_bloques_472437())

    assert resultado.get("cliente") == "AGF ACEROS DE CHILE SPA"


def test_union_multibloque_recupera_nombre_de_obra_completo():
    resultado = _extraer_asociaciones_geometricas(_bloques_472437())

    assert resultado.get("obra destino") == "CONSTRUCTORA IGNACIO HURTADO"


def test_etiqueta_codigo_cliente_nunca_se_confunde_con_senores():
    """Un bloque "CLIENTE" precedido de "CODIGO"/"COD" en la misma fila es
    un número de cuenta interno, nunca el campo de nombre real -- si se
    tratara como SEÑOR(ES) equivalente, competiría por el mismo valor y
    podría ganar por ruido geométrico cercano (letterhead)."""
    bloques = _bloques_472437() + [_bloque("0001006226", 270, 336, 90, 20)]

    resultado = _extraer_asociaciones_geometricas(bloques)

    assert resultado.get("cliente") == "AGF ACEROS DE CHILE SPA"


def test_giro_real_sigue_protegido_cuando_es_mejor_candidato_464170():
    """No regresión (caso real 464170, ya cubierto en
    `test_extraer_datos.py::test_geometria_obra_destino_no_confunde_giro_con_destino_real`)
    -- se repite aquí como parte del contrato de capacidad de este
    bloque: cuando GIRO SÍ tiene su propio valor real cercano, ese valor
    nunca se devuelve como obra_destino."""
    bloques = [
        _bloque("SEÑOR(ES)", 46, 550, 72, 15),
        _bloque(": EBEMA SA", 217, 550, 71, 15),
        _bloque("SOLICITANTE", 482, 554, 84, 14),
        _bloque(": SUPERMERCADO SEÑOR DE LOS MI", 623, 550, 225, 17),
        _bloque("GIRO", 46, 585, 37, 18),
        _bloque(": VENTA AL POR MAYOR D", 216, 589, 160, 13),
        _bloque("OBRA DESTINO", 482, 587, 95, 14),
        _bloque(": SUPERMERCADO SEÑOR DE LOS MI", 622, 583, 226, 17),
    ]

    resultado = _extraer_asociaciones_geometricas(bloques)

    assert resultado["obra destino"] == "SUPERMERCADO SEÑOR DE LOS MI"


# =====================================================================
# Item 5 -- GUIA_AUSENTE recuperable desde imagen (caso real 464453):
# ancla "GUIA DE DESPACHO" truncada por OCR + marcador "N?" (confusión
# de "N°").
# =====================================================================

def test_numero_guia_geometrico_tolera_ancla_truncada_y_marcador_interrogacion():
    bloques = [
        _bloque("GUIA DE DESPAC", 570, 272, 169, 30),
        _bloque("N? 464453", 622, 334, 98, 26),
    ]

    resultado = _extraer_numero_guia_geometrico(bloques)

    assert resultado.get("valor") == "464453"


def test_numero_guia_geometrico_nunca_usa_nombre_de_archivo():
    """Sin ancla real en el documento, se abstiene -- nunca inventa un
    número a partir de metadata externa (nombre de archivo)."""
    bloques = [_bloque("ALGUN OTRO TEXTO", 100, 100, 120, 20)]

    assert _extraer_numero_guia_geometrico(bloques) == {}


# =====================================================================
# Item 6 -- dirección confirmada por humano vs. geocodificación
# imprecisa (caso real 464170/464746): un humano ya resolvió la
# IDENTIDAD del destino; que el proveedor externo no logre una
# coordenada precisa es una LIMITACION_PROVEEDOR, nunca una acción
# humana pendiente de nuevo.
# =====================================================================

def test_direccion_confirmada_por_humano_nunca_vuelve_a_preguntar():
    fila = {
        "numero_guia": "464170-SIM", "planta_origen_id": "planta-1",
        "despachar_a_crudo": "AV ALMTE LATORRE 843", "motivo_ruta": "COORDENADA_NO_CONFIRMADA(2)",
    }
    registro = _registro_pendiente(fila, previo=None)

    resultado = _ciclo_vida_pendiente(
        registro, instante=datetime.now(timezone.utc),
        direccion_confirmada_por_humano=True, destino_terminado_por_humano=False,
    )

    assert resultado["estado_espera"] == ESTADO_ESPERA_EVIDENCIA
    assert resultado["causa_siguiente_accion"] == "DIRECCION_CONFIRMADA_POR_HUMANO__GEOCODER_NO_RESUELVE"


def test_sin_confirmacion_humana_el_mismo_motivo_no_se_trata_igual():
    """Control: la MISMA `fila`/`motivo_ruta`, sin la confirmación humana
    (`direccion_confirmada_por_humano=False`), sigue el camino normal de
    reintentos técnicos -- la distinción depende exclusivamente de la
    confirmación, nunca del motivo por sí solo."""
    fila = {
        "numero_guia": "464170-CTRL", "planta_origen_id": "planta-1",
        "despachar_a_crudo": "AV ALMTE LATORRE 843", "motivo_ruta": "COORDENADA_NO_CONFIRMADA(2)",
    }
    registro = _registro_pendiente(fila, previo=None)

    resultado = _ciclo_vida_pendiente(
        registro, instante=datetime.now(timezone.utc),
        direccion_confirmada_por_humano=False, destino_terminado_por_humano=False,
    )

    assert resultado["causa_siguiente_accion"] != "DIRECCION_CONFIRMADA_POR_HUMANO__GEOCODER_NO_RESUELVE"


# =====================================================================
# Item 7 -- bug real de `intentos_misma_evidencia` (caso real
# 472477/472541): la huella de "misma evidencia" no debe incluir
# `resultado_atlas_ia_json` (traza diagnóstica, no evidencia de ruteo) --
# de lo contrario un reintento determinista se resetea sin motivo y
# nunca converge.
# =====================================================================

def test_huella_ruta_estable_aunque_cambie_la_traza_diagnostica():
    base = {
        "planta_origen_id": "planta-1", "despachar_a_crudo": "AV X 123",
        "cliente": "CLIENTE X", "obra_destino": "OBRA X",
        "destino_id": "", "motivo_ruta": "COORDENADA_NO_CONFIRMADA(1)",
    }
    fila_a = dict(base, resultado_atlas_ia_json='{"traza": "corrida-1"}')
    fila_b = dict(base, resultado_atlas_ia_json='{"traza": "corrida-2-totalmente-distinta"}')

    assert _huella_ruta(fila_a) == _huella_ruta(fila_b)


def test_huella_ruta_cambia_si_cambia_evidencia_real_de_ruteo():
    """Control: la huella SÍ debe cambiar ante un cambio real de
    evidencia de ruteo -- la estabilidad de arriba es selectiva, nunca
    una huella constante que nunca detecte nada."""
    base = {
        "planta_origen_id": "planta-1", "despachar_a_crudo": "AV X 123",
        "cliente": "CLIENTE X", "obra_destino": "OBRA X",
        "destino_id": "", "motivo_ruta": "COORDENADA_NO_CONFIRMADA(1)",
    }
    otra = dict(base, despachar_a_crudo="AV Y 456 -- DIRECCION DISTINTA")

    assert _huella_ruta(base) != _huella_ruta(otra)


def test_reintentos_se_acumulan_entre_pasadas_con_misma_evidencia_real():
    """El bug real: con la traza diagnóstica cambiando en cada pasada
    (comportamiento normal de B1), `intentos_misma_evidencia` debía
    acumular igual porque la evidencia de RUTEO no cambió."""
    fila = {
        "numero_guia": "472477-SIM", "planta_origen_id": "planta-1",
        "despachar_a_crudo": "AV X 123", "cliente": "CLIENTE X", "obra_destino": "OBRA X",
        "destino_id": "", "motivo_ruta": "COORDENADA_NO_CONFIRMADA(1)",
        "resultado_atlas_ia_json": '{"traza": "corrida-1"}',
    }
    primero = _registro_pendiente(fila, previo=None)
    primero["intentos_misma_evidencia"] = 1
    primero["ultimo_intento"] = datetime.now(timezone.utc).isoformat()

    fila_siguiente_pasada = dict(fila, resultado_atlas_ia_json='{"traza": "corrida-2-distinta"}')
    segundo = _registro_pendiente(fila_siguiente_pasada, previo=primero)

    assert segundo["intentos_misma_evidencia"] == 1


# =====================================================================
# Contrato general -- dos guías del mismo transporte/destino no implican
# dos interacciones humanas (caso real 472491/472492): el Motor debe
# publicar el `contexto` (obra_canonica/cliente_canonico/comuna_sugerida)
# que la deduplicación de Desktop (`TIPOS_DEDUPLICABLES_POR_CONTEXTO`,
# `decisiones_pendientes_ui.js`) usa para fusionar ambas tarjetas en una
# sola revisión -- este test fija el contrato del lado Motor; la fusión
# en sí ya está cubierta en Desktop
# (`test/revision_paginador_deduplicacion.test.js`).
# =====================================================================

def test_contexto_identico_para_guias_hermanas_mismo_transporte_destino():
    fila_472491 = {
        "numero_guia": "472491-SIM", "planta_origen_id": "planta-1",
        "cliente": "CONST COLBUN SPA", "obra_destino": "OBRA COLBUN",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "DESTINO_REVISAR",
        "despachar_a_crudo": "AV PEHUENCHE 1177 TALCA",
    }
    fila_472492 = dict(fila_472491, numero_guia="472492-SIM")

    decision_1 = detectar_decision_destino_no_resuelto(archivo="472491.jpeg", fila=fila_472491)
    decision_2 = detectar_decision_destino_no_resuelto(archivo="472492.jpeg", fila=fila_472492)

    assert decision_1 is not None and decision_2 is not None
    assert decision_1["contexto"]["obra_canonica"] == decision_2["contexto"]["obra_canonica"]
    assert decision_1["contexto"]["cliente_canonico"] == decision_2["contexto"]["cliente_canonico"]
    assert decision_1["documento"]["numero_guia"] != decision_2["documento"]["numero_guia"]


def test_contexto_distinto_para_guias_del_mismo_viaje_obra_diferente():
    """Control (caso real 472490): mismo viaje, obra/cliente distintos --
    el contexto debe diferir, así que Desktop nunca las fusiona."""
    fila_472490 = {
        "numero_guia": "472490-SIM", "planta_origen_id": "planta-1",
        "cliente": "OTRO CLIENTE SPA", "obra_destino": "OTRA OBRA DISTINTA",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "DESTINO_REVISAR",
        "despachar_a_crudo": "AV PEHUENCHE 1177 TALCA",
    }
    fila_472491 = {
        "numero_guia": "472491-SIM2", "planta_origen_id": "planta-1",
        "cliente": "CONST COLBUN SPA", "obra_destino": "OBRA COLBUN",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "DESTINO_REVISAR",
        "despachar_a_crudo": "AV PEHUENCHE 1177 TALCA",
    }

    decision_1 = detectar_decision_destino_no_resuelto(archivo="472490.jpeg", fila=fila_472490)
    decision_2 = detectar_decision_destino_no_resuelto(archivo="472491.jpeg", fila=fila_472491)

    assert decision_1 is not None and decision_2 is not None
    assert decision_1["contexto"]["obra_canonica"] != decision_2["contexto"]["obra_canonica"]
