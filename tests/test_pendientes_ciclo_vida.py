"""Ciclo de vida de pendientes técnicos y tarjetas (26/10/2026): motivo vacío
con reintentos acotados (483138, 482771, 482772, 483017), motivo técnico
obsoleto con prefijo (482909, 483208, 483223), identidad documental de
tarjetas Mobile (482816) y guías recuperadas (483169), publicación focal y
pasada programada que no compite con PULL ni B1. Sólo fixtures sintéticas."""
from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from atlas_core.decisiones_pendientes import (
    clasificar_pendiente_tecnico, crear_decision, normalizar_identidad_documental,
)
from atlas_core.politica_pendientes_tecnicos import elegibilidad
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.reconciliacion_estado_derivado import _ciclo_vida_pendiente
from atlas_core.revalidacion_documental import revalidar_ruta_sin_destino_calculado_sin_ocr
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from tests.test_revalidar_ruta_sin_destino_r410 import _catalogos, _escribir_csv, _fila_csv, _leer

AHORA = datetime(2026, 10, 26, 20, 0, tzinfo=timezone.utc)


def _registro(motivo, intentos=0, obra="COMERCIAL A Y B LTDA", destino="LA ESTERA 525", ultimo=None):
    return {"numero_guia": "483138", "motivo_actual": motivo, "intentos_misma_evidencia": intentos,
            "ultimo_intento": ultimo, "datos_disponibles": {"obra": obra, "destino_documental": destino}}


# ------------------------------------------------------------ motivo vacío


def test_motivo_vacio_es_reintentable_y_acotado():
    assert clasificar_pendiente_tecnico("") == "AGOTABLE"
    assert elegibilidad(_registro(""), huella_actual="h", instante=AHORA) == (True, "PRIMERA_OPORTUNIDAD")
    reciente = (AHORA - timedelta(minutes=5)).isoformat()
    assert elegibilidad(_registro("", 1, ultimo=reciente), huella_actual="h", instante=AHORA) == (
        False, "ESPERANDO_COOLDOWN")
    assert elegibilidad(_registro("", 3), huella_actual="h", instante=AHORA) == (False, "AGOTADO")


def test_motivo_vacio_por_obra_ausente_sigue_esperando_al_humano():
    registro = _registro("", obra="No encontrado", destino="LA ESTERA 525")
    assert clasificar_pendiente_tecnico("", obra="No encontrado", destino_documental="LA ESTERA 525") == "DETERMINISTA"
    estado = _ciclo_vida_pendiente(registro, instante=AHORA, direccion_confirmada_por_humano=False,
                                   destino_terminado_por_humano=False)
    assert estado["causa_siguiente_accion"] == "OBRA_AUSENTE_BLOQUEA_RUTEO"


def test_motivo_vacio_agotado_no_anuncia_accion_humana_sin_tarjeta():
    estado = _ciclo_vida_pendiente(_registro("", 3), instante=AHORA, direccion_confirmada_por_humano=False,
                                   destino_terminado_por_humano=False)
    assert estado["estado_espera"] == "ESPERANDO_EVIDENCIA_NUEVA"
    assert estado["causa_siguiente_accion"] == "RUTEO_SIN_RESULTADO_TRAS_MAX_INTENTOS"
    pendiente = _ciclo_vida_pendiente(_registro("", 1, ultimo=AHORA.isoformat()), instante=AHORA,
                                      direccion_confirmada_por_humano=False, destino_terminado_por_humano=False)
    assert pendiente["estado_espera"] == "ESPERANDO_COOLDOWN" and pendiente["clase_fallo"] == "AGOTABLE"


def test_motivos_con_causa_conservan_su_clase():
    assert clasificar_pendiente_tecnico("GEOCODIFICACION_SIN_CREDENCIAL") == "TRANSITORIO"
    assert clasificar_pendiente_tecnico("GEOCODIFICACION_DIRECCION_NO_ENCONTRADA") == "DETERMINISTA"
    assert clasificar_pendiente_tecnico("COORDENADA_NO_CONFIRMADA(2)") == "AGOTABLE"


# ------------------------------------------------------------ motivo técnico obsoleto


def test_sin_credencial_con_prefijo_se_reemplaza_por_la_causa_vigente(tmp_path):
    carpeta, planta = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_csv(
        planta, numero_guia="483208", despachar_a_crudo="CAMINOLO RUI2901 SEIAGO RA",
        direccion_entrega="", estado_ruta="REQUIERE_REVISION", motivo_ruta="GEOCODIFICACION_SIN_CREDENCIAL",
    )])
    proveedor = ProveedorRutasSimulado(
        geocodificaciones={"CAMINOLO RUI2901 SEIAGO RA, Chile": ResultadoGeocodificacion(
            EstadoRuta.DIRECCION_NO_ENCONTRADA, (), "")},
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 10.0, 15.0, "SINTETICO"),
    )
    revalidar_ruta_sin_destino_calculado_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta,
                                                 proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor)
    fila = _leer(dataset)[0]
    assert "SIN_CREDENCIAL" not in fila["motivo_ruta"] and fila["motivo_ruta"]
    assert fila["distancia_km"] == ""  # nunca inventa una ruta


# ------------------------------------------------------------ identidad documental

MOBILE = "mobile/8323e2e1-3e76-4c6e-90b5-2efdeaf571ee/original.jpg"


def _dataset(tmp_path, filas):
    actual = tmp_path / "operacion" / "actual"
    actual.mkdir(parents=True, exist_ok=True)
    ruta = actual / "analisis_completo_guias.csv"
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        for archivo_, guia, transporte in filas:
            fila = {c: "" for c in COLUMNAS}
            fila.update(archivo=archivo_, numero_guia=guia, numero_transporte=transporte)
            escritor.writerow(fila)
    return ruta


def _tarjeta(tipo, campo, valor, archivo, guia, transporte="0000365506"):
    return crear_decision(tipo=tipo, entidad="X", archivo=archivo, numero_guia=guia, numero_transporte=transporte,
                          campo=campo, valor_documental=valor, valor_normalizado=valor, identidad_resuelta=None,
                          candidatos=(), motivos=("P",), evidencias=(), acciones_permitidas=("POSPONER",))


def test_tarjeta_original_jpg_se_reidentifica_y_su_duplicado_se_retira(tmp_path):
    ruta = _dataset(tmp_path, [(MOBILE, "482816", "0000365506"), ("482740.jpeg", "482740", "0000365294")])
    chofer = _tarjeta("CHOFER_CANDIDATO", "chofer", "LUIS VARAS", "original.jpg", "482816")
    rampla_vieja = _tarjeta("VEHICULO_DESCONOCIDO", "patente_rampla", "JC4173", "original.jpg", "482816")
    rampla = _tarjeta("VEHICULO_DESCONOCIDO", "patente_rampla", "JC4173", MOBILE, "482816")
    desktop = _tarjeta("VEHICULO_DESCONOCIDO", "patente_tracto", "JC4173", "482740.jpeg", "482740", "0000365294")
    salida = normalizar_identidad_documental([chofer, rampla_vieja, rampla, desktop], ruta_dataset=ruta)
    assert [(d["tipo"], d["documento"]["archivo"]) for d in salida] == [
        ("CHOFER_CANDIDATO", MOBILE), ("VEHICULO_DESCONOCIDO", MOBILE), ("VEHICULO_DESCONOCIDO", "482740.jpeg")]
    assert salida[0]["decision_id"] != chofer["decision_id"]
    assert salida[1] == rampla and salida[2] == desktop
    # Idempotente.
    assert normalizar_identidad_documental(salida, ruta_dataset=ruta) == salida


def test_guia_recuperada_actualiza_la_tarjeta_y_respeta_lo_resuelto(tmp_path):
    archivo = "mobile/5eb978b8/original.jpg"
    ruta = _dataset(tmp_path, [(archivo, "483169", "0000366176"), (MOBILE, "482816", "0000365506")])
    peso = _tarjeta("PESO_VIAJE_IMPLAUSIBLE", "peso_kg", "30218", archivo, "No encontrado", "0000366176")
    chofer = _tarjeta("CHOFER_CANDIDATO", "chofer", "LUIS VARAS", "original.jpg", "482816")
    (ruta.parent / "decisiones_aplicadas.json").write_text(json.dumps({"aplicaciones": [{
        "tipo": "CHOFER_CANDIDATO", "campo": "chofer", "valor_documental": "LUIS VARAS",
        "accion": "CONFIRMAR", "documento": {"archivo": MOBILE, "numero_guia": "482816"}}]}), encoding="utf-8")
    salida = normalizar_identidad_documental([peso, chofer], ruta_dataset=ruta)
    assert [d["documento"]["numero_guia"] for d in salida] == ["483169"]  # la ya respondida no reaparece


def test_ambiguedad_o_transporte_distinto_no_se_adivina(tmp_path):
    ruta = _dataset(tmp_path, [("mobile/a/original.jpg", "482816", "0000365506"),
                               ("mobile/b/original.jpg", "482816", "0000365506"),
                               ("mobile/c/original.jpg", "483169", "0000366176")])
    dos_filas = _tarjeta("CHOFER_CANDIDATO", "chofer", "X", "original.jpg", "482816")
    otro_transporte = _tarjeta("PESO_VIAJE_IMPLAUSIBLE", "peso_kg", "1", "mobile/c/original.jpg", "No encontrado",
                               "0000999999")
    assert normalizar_identidad_documental([dos_filas, otro_transporte], ruta_dataset=ruta) == [
        dos_filas, otro_transporte]


def test_mobile_publica_con_el_identificador_canonico():
    from pathlib import Path
    from atlas_core.mobile import _identidad_canonica_mobile
    decisiones = [_tarjeta("CHOFER_CANDIDATO", "chofer", "X", "original.jpg", "482816")]
    _identidad_canonica_mobile(decisiones, Path("C:/x/envios/8323/original.jpg"), MOBILE)
    assert decisiones[0]["documento"]["archivo"] == MOBILE


# ------------------------------------------------------------ pasada programada


class _EscritorFalso:
    def __init__(self, libre=True):
        self.libre, self.vigente, self.cerrado = libre, False, False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cerrado = True

    def adquirir(self):
        self.vigente = self.libre
        return self.libre


def test_pasada_programada_sin_trabajo_no_toma_escritor(tmp_path, monkeypatch):
    import mantener_pendientes_tecnicos as cli
    monkeypatch.setattr(cli, "mantener_pendientes_tecnicos", lambda **k: {"elegibles": []})
    creados = []
    assert cli.pasada_programada(tmp_path, fabrica_escritor=lambda r: creados.append(1))["motivo"] == "SIN_ELEGIBLES"
    assert creados == []


def test_pasada_programada_omite_con_b1_en_curso_o_escritor_ocupado(tmp_path, monkeypatch):
    import mantener_pendientes_tecnicos as cli
    llamadas = []
    monkeypatch.setattr(cli, "mantener_pendientes_tecnicos",
                        lambda **k: llamadas.append(k) or {"elegibles": [{"numero_guia": "483138"}]})
    actual = tmp_path / "operacion" / "actual"
    actual.mkdir(parents=True)
    lock = actual / ".atlas_lock_acciones_operacionales"
    lock.write_text("{}", encoding="utf-8")
    assert cli.pasada_programada(tmp_path, fabrica_escritor=lambda r: _EscritorFalso())["motivo"] == \
        "OPERACION_HUMANA_EN_CURSO"
    viejo = time.time() - 7 * 3600
    os.utime(lock, (viejo, viejo))  # huérfano: ya no bloquea
    ocupado = _EscritorFalso(libre=False)
    assert cli.pasada_programada(tmp_path, fabrica_escritor=lambda r: ocupado)["motivo"] == "ESCRITOR_OCUPADO"
    assert ocupado.cerrado and all(k.get("solo_plan") for k in llamadas)
    libre = _EscritorFalso()
    cli.pasada_programada(tmp_path, fabrica_escritor=lambda r: libre)
    assert not llamadas[-1].get("solo_plan") and libre.cerrado


# ------------------------------------------------------------ capacidad declarada


def test_geografia_declara_la_convergencia_de_destinos():
    from atlas_core.capacidades_reevaluacion import REGISTRO_CAPACIDADES
    assert REGISTRO_CAPACIDADES["GEOGRAFIA"].version == 5


# ------------------------------------------------------------ mantenimiento


def test_cambio_de_conocimiento_no_atendido_sigue_pendiente(tmp_path, monkeypatch):
    from atlas_core import mantenimiento_pendientes_tecnicos as mantenimiento
    from tests.test_mantenimiento_pendientes_tecnicos import RELOJ, _entorno, _parches_sin_red, _pendiente
    raiz, _ = _entorno(tmp_path, minutos=10)  # en cooldown: sólo el cambio la reactiva
    huella_previa = _pendiente(raiz)[0]["huella_conocimiento"]
    catalogo = raiz / "catalogos_privados" / "destinos_maestros.json"
    contenido = json.loads(catalogo.read_text(encoding="utf-8"))
    contenido["destinos"][0].update(latitud=-33.5, longitud=-70.6)
    catalogo.write_text(json.dumps(contenido), encoding="utf-8")
    _parches_sin_red(monkeypatch)
    monkeypatch.setattr(mantenimiento, "MAX_GUIAS_POR_PASADA", 0)  # pasada llena: no la alcanza
    mantenimiento.mantener_pendientes_tecnicos(raiz_atlas=raiz, reloj=RELOJ)
    assert _pendiente(raiz)[0]["huella_conocimiento"] == huella_previa
    monkeypatch.setattr(mantenimiento, "MAX_GUIAS_POR_PASADA", 10)
    plan = mantenimiento.mantener_pendientes_tecnicos(raiz_atlas=raiz, reloj=RELOJ, solo_plan=True)
    assert [(e["numero_guia"], e["causa"]) for e in plan["elegibles"]] == [("474597", "CONOCIMIENTO_CAMBIO")]


def test_motivo_vacio_consulta_al_proveedor_en_su_primer_intento(tmp_path, monkeypatch):
    from atlas_core import mantenimiento_pendientes_tecnicos as mantenimiento
    from tests.test_mantenimiento_pendientes_tecnicos import RELOJ, _entorno, _parches_sin_red, _pendiente
    raiz, _ = _entorno(tmp_path, "", intentos=0)
    llamadas = _parches_sin_red(monkeypatch)
    mantenimiento.mantener_pendientes_tecnicos(raiz_atlas=raiz, reloj=RELOJ)
    assert llamadas["externo"] == [{"474597"}]
    registro = _pendiente(raiz)[0]
    assert registro["intentos_misma_evidencia"] == 1 and registro["clase_fallo"] == "AGOTABLE"
