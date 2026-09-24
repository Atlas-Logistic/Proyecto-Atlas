"""Bloque P0 CONFIABILIDAD "PREGÚNTALE A ATLAS" -- CASO A. Caso real:
después de registrar estadías TIENE_ESTADIA/APROBADA, la misma acción
podía reaparecer como "Lista para aplicar". Causa raíz (investigada,
reproducida en vivo antes de tocar código):

  Bug 1 -- `interpretador_incidencias_operacionales._procesar_subclausula`
  descartaba en silencio una sub-cláusula sin guía propia ("... Y fue
  aprobada", tras partir en la "Y"). Con la frase compuesta en una sola
  oración ("473001 tiene estadía Y fue aprobada."), el ACTUALIZAR_GESTION
  desaparecía por completo -- nunca se escribía `estado_gestion`.

  Bug 2 -- `gestion_incidencias_conversacional._backfill_tipo_pendiente`
  sólo consultaba el ledger YA ESCRITO para inferir el `tipo` faltante de
  un ACTUALIZAR_GESTION. Con la frase en dos oraciones ("473001 tiene
  estadía. 473001 fue aprobada."), ambas acciones SÍ se generaban, pero
  la segunda (misma guía, mismo lote) no veía la primera -- que todavía
  no se había escrito -- y quedaba TIPO_REQUERIDO, sin aplicarse.

  En ambos casos, el evento MARCA_VIAJE terminaba persistido con
  `estado_gestion=None` -- un estado NO terminal que vuelve a calificar
  como "aplicable" (RESUELTA) en cualquier preview posterior, exactamente
  el síntoma reportado.

Este archivo prueba, en `tmp_path` (nunca G, nunca red, nunca B1 real),
que el ciclo de vida PENDIENTE -> PREVIEW -> CONFIRMACIÓN HUMANA ->
APLICADA -> YA_REGISTRADA/HISTÓRICA se sostiene, incluida la frase
compuesta real. No hardcodea 473001 como caso especial -- es sólo el
número de guía de fixture, cualquier otro produciría el mismo resultado."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from atlas_core.gestion_incidencias_conversacional import (
    confirmar_lote_incidencias,
    proponer_lote_incidencias,
)
from atlas_core.interpretador_incidencias_operacionales import interpretar_instruccion_incidencias

COLUMNAS = [
    "viaje_id", "numero_transporte", "numeros_guia", "fecha", "choferes", "ruts_chofer",
    "clientes", "obras_destino", "patentes_tracto", "patentes_rampla", "materiales",
    "tipos_carga", "peso_total_viaje_kg", "distancia_km", "duracion_min",
    "direccion_entrega", "localidad_entrega", "estado_ruta", "estado",
]


def _fila(**kw):
    base = {c: "" for c in COLUMNAS}
    base.update(kw)
    return base


def _entorno(tmp_path: Path, filas: list[dict]):
    raiz = tmp_path / "Atlas"
    (raiz / "operacion" / "actual").mkdir(parents=True)
    ruta_viajes = tmp_path / "viajes.csv"
    with ruta_viajes.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        w.writerows(filas)
    return raiz, ruta_viajes


def _ruta_eventos(raiz: Path) -> Path:
    return raiz / "operacion" / "actual" / "eventos_operacionales.json"


FILAS_BASE = [
    _fila(viaje_id="v1", numero_transporte="T1", numeros_guia="473001", fecha="10-08-2026", choferes="LEANDRO TOLEDO"),
    _fila(viaje_id="v2", numero_transporte="T2", numeros_guia="473004", fecha="11-08-2026", choferes="LEANDRO TOLEDO"),
]


# ==========================================================================
# A1 -- acción nueva -> aplicable
# ==========================================================================


def test_a1_accion_nueva_es_aplicable(tmp_path):
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    propuesta = proponer_lote_incidencias(texto="473001 tiene estadía.", raiz=raiz, ruta_viajes=ruta_viajes)
    assert propuesta["preview"]["aplicable"] is True
    assert propuesta["preview"]["resumen"] == {"aplicables": 1, "ya_registradas": 0, "no_resueltas": 0}
    assert propuesta["preview"]["acciones"][0]["estado"] == "RESUELTA"


# ==========================================================================
# A2/A3 -- aplicar deja de ser accionable; repetir consulta -> YA_REGISTRADA
#          (frase COMPUESTA "X tiene estadía Y fue aprobada" -- Bug 1)
# ==========================================================================


def test_a2_a3_frase_compuesta_aplica_tipo_y_gestion_y_no_reaparece(tmp_path):
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    texto = "473001 tiene estadía y fue aprobada."

    # Antes del fix, el ACTUALIZAR_GESTION desaparecía en silencio aquí.
    acciones = interpretar_instruccion_incidencias(texto)
    assert acciones == [
        {"accion": "REGISTRAR_INCIDENCIA", "guia": "473001", "tipo": "TIENE_ESTADIA"},
        {"accion": "ACTUALIZAR_GESTION", "guia": "473001", "estado_gestion": "APROBADA"},
    ]

    propuesta = proponer_lote_incidencias(texto=texto, raiz=raiz, ruta_viajes=ruta_viajes)
    assert propuesta["preview"]["aplicable"] is True
    assert propuesta["preview"]["resumen"]["no_resueltas"] == 0  # nunca TIPO_REQUERIDO

    resultado = confirmar_lote_incidencias(
        raiz=raiz, ruta_viajes=ruta_viajes, acciones=propuesta["acciones"], actor="JAVIER", confirmado=True,
    )
    assert resultado["resumen"]["aplicados"] == 2
    assert resultado["resumen"]["no_aplicados"] == 0

    documento = json.loads(_ruta_eventos(raiz).read_text(encoding="utf-8"))
    assert len(documento["eventos"]) == 1  # un solo hecho MARCA_VIAJE, no duplicado
    evento = documento["eventos"][0]
    assert evento["tipo_evento"] == "TIENE_ESTADIA"
    assert evento["estado_gestion"] == "APROBADA"  # NUNCA None

    # A2/A3: repetir exactamente la misma instrucción -- ya no es
    # accionable, nunca "Lista para aplicar" de nuevo.
    propuesta2 = proponer_lote_incidencias(texto=texto, raiz=raiz, ruta_viajes=ruta_viajes)
    assert propuesta2["preview"]["aplicable"] is False
    assert propuesta2["preview"]["resumen"] == {"aplicables": 0, "ya_registradas": 2, "no_resueltas": 0}
    for item in propuesta2["preview"]["acciones"]:
        assert item["estado"] == "YA_REGISTRADA"


def test_a2_a3_frase_en_dos_oraciones_misma_guia_no_reaparece(tmp_path):
    """Misma garantía, pero para la otra forma real (Bug 2): dos
    oraciones separadas sobre la misma guía en un solo lote."""
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    texto = "473001 tiene estadía. 473001 fue aprobada."

    propuesta = proponer_lote_incidencias(texto=texto, raiz=raiz, ruta_viajes=ruta_viajes)
    assert propuesta["acciones"][1]["accion"] == "ACTUALIZAR_GESTION"
    assert propuesta["acciones"][1].get("tipo") == "TIENE_ESTADIA"  # backfill DENTRO del lote
    assert propuesta["acciones"][1]["tipo_inferido_de_incidencia_existente"] is True
    assert propuesta["preview"]["aplicable"] is True
    assert propuesta["preview"]["resumen"]["no_resueltas"] == 0

    resultado = confirmar_lote_incidencias(
        raiz=raiz, ruta_viajes=ruta_viajes, acciones=propuesta["acciones"], actor="JAVIER", confirmado=True,
    )
    assert resultado["resumen"]["no_aplicados"] == 0
    documento = json.loads(_ruta_eventos(raiz).read_text(encoding="utf-8"))
    assert documento["eventos"][0]["estado_gestion"] == "APROBADA"  # NUNCA None

    propuesta2 = proponer_lote_incidencias(texto=texto, raiz=raiz, ruta_viajes=ruta_viajes)
    assert propuesta2["preview"]["aplicable"] is False
    for item in propuesta2["preview"]["acciones"]:
        assert item["estado"] == "YA_REGISTRADA"


# ==========================================================================
# A4 -- lote nueva + registrada + inexistente -> sólo nueva aplicable
# ==========================================================================


def test_a4_lote_mixto_solo_la_nueva_es_aplicable(tmp_path):
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    # 473001 ya queda registrada de antemano.
    p0 = proponer_lote_incidencias(texto="473001 tiene estadía.", raiz=raiz, ruta_viajes=ruta_viajes)
    confirmar_lote_incidencias(raiz=raiz, ruta_viajes=ruta_viajes, acciones=p0["acciones"], actor="JAVIER", confirmado=True)

    # Lote: 473001 (ya registrada) + 473004 (nueva) + 999999 (no existe).
    texto = "473001, 473004 y 999999 tienen estadía."
    propuesta = proponer_lote_incidencias(texto=texto, raiz=raiz, ruta_viajes=ruta_viajes)
    resumen = propuesta["preview"]["resumen"]
    assert resumen == {"aplicables": 1, "ya_registradas": 1, "no_resueltas": 1}
    por_guia = {item["guia"]: item["estado"] for item in propuesta["preview"]["acciones"]}
    assert por_guia["473001"] == "YA_REGISTRADA"
    assert por_guia["473004"] == "RESUELTA"
    assert por_guia["999999"] == "NO_ENCONTRADA"

    # Confirmar el lote completo: sólo la nueva se aplica de verdad; las
    # otras se informan, nunca bloquean ni se aplican.
    resultado = confirmar_lote_incidencias(
        raiz=raiz, ruta_viajes=ruta_viajes, acciones=propuesta["acciones"], actor="JAVIER", confirmado=True,
    )
    assert resultado["resumen"]["aplicados"] == 1
    assert resultado["resumen"]["ya_registrados"] == 1
    assert resultado["resumen"]["no_aplicados"] == 1
    documento = json.loads(_ruta_eventos(raiz).read_text(encoding="utf-8"))
    assert len(documento["eventos"]) == 2  # 473001 (previo) + 473004 (nuevo) -- nunca 999999


# ==========================================================================
# A5 -- reutilizar un preview ya consumido no duplica ni rompe
# ==========================================================================


def test_a5_reutilizar_preview_consumido_no_duplica(tmp_path):
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    propuesta = proponer_lote_incidencias(texto="473001 tiene estadía.", raiz=raiz, ruta_viajes=ruta_viajes)
    acciones_congeladas = propuesta["acciones"]  # simula el token/preview que la ventana guardó

    r1 = confirmar_lote_incidencias(
        raiz=raiz, ruta_viajes=ruta_viajes, acciones=acciones_congeladas, actor="JAVIER", confirmado=True,
    )
    assert r1["resumen"]["aplicados"] == 1

    # La misma lista de acciones (el preview "viejo") se reenvía otra vez
    # -- nunca vuelve a aplicar el mismo hecho.
    r2 = confirmar_lote_incidencias(
        raiz=raiz, ruta_viajes=ruta_viajes, acciones=acciones_congeladas, actor="JAVIER", confirmado=True,
    )
    assert r2["aplicado"] is False
    assert r2["motivo"] == "SIN_ACCIONES_APLICABLES"
    documento = json.loads(_ruta_eventos(raiz).read_text(encoding="utf-8"))
    assert len(documento["eventos"]) == 1  # nunca duplicó


# ==========================================================================
# A6 -- recargar/reabrir estado: la aplicada no reaparece como pendiente
# ==========================================================================


def test_a6_reapertura_no_muestra_la_aplicada_como_pendiente(tmp_path):
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    texto = "473001 tiene estadía y fue aprobada."
    propuesta = proponer_lote_incidencias(texto=texto, raiz=raiz, ruta_viajes=ruta_viajes)
    confirmar_lote_incidencias(raiz=raiz, ruta_viajes=ruta_viajes, acciones=propuesta["acciones"], actor="JAVIER", confirmado=True)

    # "Reabrir" = una llamada COMPLETAMENTE independiente (sin ningún
    # estado en memoria de la sesión anterior, ni un token/preview
    # reutilizado) que vuelve a interpretar el MISMO texto desde cero y
    # a previsualizar contra el ledger persistido -- el mismo punto de
    # entrada público que usaría una ventana recién abierta.
    propuesta_reabierta = proponer_lote_incidencias(texto=texto, raiz=raiz, ruta_viajes=ruta_viajes)
    assert propuesta_reabierta["preview"]["aplicable"] is False
    assert propuesta_reabierta["preview"]["resumen"]["aplicables"] == 0
    for item in propuesta_reabierta["preview"]["acciones"]:
        assert item["estado"] == "YA_REGISTRADA"
