"""Bloque INCIDENCIAS OPERACIONALES V1.1 -- integración B1 + preview +
confirmación sobre la V1 ya aprobada. Cubre de punta a punta:

    texto libre -> interpretación determinística -> preview (nunca
    escribe) -> confirmación humana explícita -> aplicar_lote
    (idempotente) -> resumen; y el lado de consulta (estado de gestión,
    "no revisado por incidencias", delegación al motor genérico).

Nunca toca G: real -- todo corre sobre fixtures en `tmp_path`."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from atlas_core.gestion_incidencias_conversacional import (
    confirmar_lote_incidencias,
    proponer_lote_incidencias,
    responder_consulta_incidencias_conversacional,
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
    _fila(viaje_id="v3", numero_transporte="T3", numeros_guia="473010", fecha="12-08-2026", choferes="PATRICIO VILLAGRA"),
    _fila(viaje_id="v4", numero_transporte="T4", numeros_guia="473015", fecha="13-08-2026", choferes="LEANDRO TOLEDO"),
    _fila(viaje_id="v5", numero_transporte="T5", numeros_guia="473020", fecha="14-08-2026", choferes="LEANDRO TOLEDO"),
]


# ============================================================
# 1. Interpretación (item 1 del bloque) -- las 5 instrucciones de
#    referencia, sin ejecutar nada todavía.
# ============================================================


def test_interpreta_lote_lista_una_sola_incidencia_compartida():
    acciones = interpretar_instruccion_incidencias("Las guías 473001, 473004 y 473010 tienen estadía.")
    assert acciones == [
        {"accion": "REGISTRAR_INCIDENCIA", "guia": "473001", "tipo": "TIENE_ESTADIA"},
        {"accion": "REGISTRAR_INCIDENCIA", "guia": "473004", "tipo": "TIENE_ESTADIA"},
        {"accion": "REGISTRAR_INCIDENCIA", "guia": "473010", "tipo": "TIENE_ESTADIA"},
    ]


def test_interpreta_tipos_mezclados_por_guia():
    acciones = interpretar_instruccion_incidencias("473015 tuvo devolución parcial y 473020 doble vuelta.")
    assert acciones == [
        {"accion": "REGISTRAR_INCIDENCIA", "guia": "473015", "tipo": "DEVOLUCION_PARCIAL"},
        {"accion": "REGISTRAR_INCIDENCIA", "guia": "473020", "tipo": "DOBLE_VUELTA"},
    ]


def test_interpreta_actualizacion_gestion_lista_compartida():
    acciones = interpretar_instruccion_incidencias("Las estadías de 473001 y 473004 fueron aprobadas.")
    assert acciones == [
        {"accion": "ACTUALIZAR_GESTION", "guia": "473001", "estado_gestion": "APROBADA", "tipo": "TIENE_ESTADIA"},
        {"accion": "ACTUALIZAR_GESTION", "guia": "473004", "estado_gestion": "APROBADA", "tipo": "TIENE_ESTADIA"},
    ]


def test_interpreta_rechazo_singular():
    acciones = interpretar_instruccion_incidencias("Rechazaron la estadía de 473010.")
    assert acciones == [
        {"accion": "ACTUALIZAR_GESTION", "guia": "473010", "estado_gestion": "RECHAZADA", "tipo": "TIENE_ESTADIA"},
    ]


def test_interpreta_pendiente_sin_tipo_explicito():
    acciones = interpretar_instruccion_incidencias("473020 sigue pendiente de respuesta.")
    assert acciones == [
        {"accion": "ACTUALIZAR_GESTION", "guia": "473020", "estado_gestion": "PENDIENTE_RESPUESTA"},
    ]


# ============================================================
# 1b. Composición en UNA instrucción -- caso real Desktop: "tienen
#    estadía confirmada" generaba REGISTRAR_INCIDENCIA sin ESTADO
#    GESTIÓN porque "confirmada" no era sinónimo de ningún estado.
#    "confirmada"/"confirmadas" ahora es sinónimo de APROBADA (mismo
#    mecanismo genérico tipo+gestión ya usado por
#    `test_interpreta_actualizacion_gestion_lista_compartida`, nunca un
#    parche exclusivo de estadía).
# ============================================================


def test_composicion_estadia_confirmada_las_5_guias_reales_del_reporte():
    """Caso real reportado: 5 guías, "tienen estadía confirmada" ->
    TIENE_ESTADIA + APROBADA para cada una, en una sola instrucción."""
    texto = "Las guías 473056, 473220, 473081, 473280 y 473221 tienen estadía confirmada"
    acciones = interpretar_instruccion_incidencias(texto)
    assert acciones == [
        {"accion": "ACTUALIZAR_GESTION", "guia": guia, "estado_gestion": "APROBADA", "tipo": "TIENE_ESTADIA"}
        for guia in ("473056", "473220", "473081", "473280", "473221")
    ]


def test_composicion_generaliza_a_devolucion_y_doble_vuelta_confirmada():
    """No es un parche exclusivo de estadía -- "confirmada" compone
    igual con cualquier tipo ya soportado."""
    assert interpretar_instruccion_incidencias("473015 tuvo devolución total confirmada.") == [
        {"accion": "ACTUALIZAR_GESTION", "guia": "473015", "estado_gestion": "APROBADA", "tipo": "DEVOLUCION_TOTAL"},
    ]
    assert interpretar_instruccion_incidencias("473020 doble vuelta confirmada.") == [
        {"accion": "ACTUALIZAR_GESTION", "guia": "473020", "estado_gestion": "APROBADA", "tipo": "DOBLE_VUELTA"},
    ]
    assert interpretar_instruccion_incidencias("Fueron confirmadas las devoluciones parciales de 473001 y 473004.") == [
        {"accion": "ACTUALIZAR_GESTION", "guia": "473001", "estado_gestion": "APROBADA", "tipo": "DEVOLUCION_PARCIAL"},
        {"accion": "ACTUALIZAR_GESTION", "guia": "473004", "estado_gestion": "APROBADA", "tipo": "DEVOLUCION_PARCIAL"},
    ]


def test_composicion_no_rompe_las_frases_de_gestion_ya_soportadas():
    """Regresión explícita: "aprobada"/"rechazada"/"pendiente de
    respuesta" (vocabulario ya soportado antes de este bloque) siguen
    funcionando igual, incluso mezcladas con "confirmada" en la misma
    instrucción."""
    # "Y" separa dos hechos INDEPENDIENTES aquí (ya hay una palabra clave
    # -- "confirmada" -- entre la guía 473001 y la "Y"): la segunda
    # sub-cláusula nunca hereda el tipo de la primera, mismo criterio que
    # ya prueba `_sub_clausulas` para el resto del vocabulario -- por eso
    # 473004 queda sin "tipo" (candidata a backfill, igual que "473020
    # sigue pendiente de respuesta").
    acciones = interpretar_instruccion_incidencias(
        "473001 tiene estadía confirmada y 473004 fue rechazada."
    )
    assert acciones == [
        {"accion": "ACTUALIZAR_GESTION", "guia": "473001", "estado_gestion": "APROBADA", "tipo": "TIENE_ESTADIA"},
        {"accion": "ACTUALIZAR_GESTION", "guia": "473004", "estado_gestion": "RECHAZADA"},
    ]
    assert interpretar_instruccion_incidencias("Las estadías de 473001 y 473004 fueron aprobadas.") == [
        {"accion": "ACTUALIZAR_GESTION", "guia": "473001", "estado_gestion": "APROBADA", "tipo": "TIENE_ESTADIA"},
        {"accion": "ACTUALIZAR_GESTION", "guia": "473004", "estado_gestion": "APROBADA", "tipo": "TIENE_ESTADIA"},
    ]
    assert interpretar_instruccion_incidencias("473020 sigue pendiente de respuesta.") == [
        {"accion": "ACTUALIZAR_GESTION", "guia": "473020", "estado_gestion": "PENDIENTE_RESPUESTA"},
    ]


def test_fragmento_sin_tipo_ni_gestion_queda_marcado_no_reconocido():
    """Nunca se descarta en silencio -- una guía mencionada sin ninguna
    palabra clave reconocida queda con `accion=""`, visible después en el
    preview como error."""
    acciones = interpretar_instruccion_incidencias("473099 llegó tarde.")
    assert acciones == [{"accion": "", "guia": "473099"}]


# ============================================================
# 2/3. Preview obligatorio + confirmación (items 2 y 3) -- casos
#    "una incidencia", "guía inexistente", "lote parcialmente inválido",
#    "preview no escribe", "sin confirmación no escribe".
# ============================================================


def test_una_incidencia_preview_no_escribe_nada(tmp_path):
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    propuesta = proponer_lote_incidencias(
        texto="La guía 473001 tiene estadía.", raiz=raiz, ruta_viajes=ruta_viajes,
    )
    assert propuesta["interpretado"] is True
    assert propuesta["preview"]["aplicable"] is True
    assert propuesta["preview"]["acciones"][0]["estado"] == "RESUELTA"
    assert not _ruta_eventos(raiz).exists(), "el preview nunca debe escribir"


def test_texto_no_reconocible_no_produce_preview(tmp_path):
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    propuesta = proponer_lote_incidencias(texto="¿Cómo está el clima hoy?", raiz=raiz, ruta_viajes=ruta_viajes)
    assert propuesta["interpretado"] is False
    assert propuesta["preview"] is None
    assert not _ruta_eventos(raiz).exists()


def test_guia_inexistente_preview_marca_no_encontrada_sin_escribir(tmp_path):
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    propuesta = proponer_lote_incidencias(texto="La guía 999999 tiene estadía.", raiz=raiz, ruta_viajes=ruta_viajes)
    assert propuesta["preview"]["aplicable"] is False
    assert propuesta["preview"]["acciones"][0]["estado"] == "NO_ENCONTRADA"
    assert not _ruta_eventos(raiz).exists()
    # Ni siquiera confirmando se puede aplicar un preview no aplicable en
    # su totalidad -- pero cada acción se evalúa por su cuenta; una guía
    # NO_ENCONTRADA nunca produce un evento (ver aplicar_lote).
    resultado = confirmar_lote_incidencias(
        raiz=raiz, ruta_viajes=ruta_viajes, acciones=propuesta["acciones"], actor="TEST", confirmado=True,
    )
    assert resultado["resultados"][0]["ok"] is False
    assert resultado["resultados"][0]["estado"] == "NO_ENCONTRADA"
    assert not _ruta_eventos(raiz).exists()


def test_lote_parcialmente_invalido_muestra_cada_parte_explicitamente(tmp_path):
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    propuesta = proponer_lote_incidencias(
        texto="Las guías 473001 y 999999 tienen estadía.", raiz=raiz, ruta_viajes=ruta_viajes,
    )
    acciones_preview = propuesta["preview"]["acciones"]
    assert acciones_preview[0]["guia"] == "473001" and acciones_preview[0]["estado"] == "RESUELTA"
    assert acciones_preview[1]["guia"] == "999999" and acciones_preview[1]["estado"] == "NO_ENCONTRADA"
    assert propuesta["preview"]["aplicable"] is False


def test_sin_confirmacion_no_escribe(tmp_path):
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    propuesta = proponer_lote_incidencias(texto="La guía 473001 tiene estadía.", raiz=raiz, ruta_viajes=ruta_viajes)
    resultado = confirmar_lote_incidencias(
        raiz=raiz, ruta_viajes=ruta_viajes, acciones=propuesta["acciones"], actor="TEST", confirmado=False,
    )
    assert resultado["aplicado"] is False
    assert resultado["motivo"] == "CONFIRMACION_HUMANA_REQUERIDA"
    assert not _ruta_eventos(raiz).exists()


def test_confirmacion_aplica_y_lote_multiple_se_registra(tmp_path):
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    propuesta = proponer_lote_incidencias(
        texto="Las guías 473001, 473004 y 473010 tienen estadía.", raiz=raiz, ruta_viajes=ruta_viajes,
    )
    resultado = confirmar_lote_incidencias(
        raiz=raiz, ruta_viajes=ruta_viajes, acciones=propuesta["acciones"], actor="JAVIER", confirmado=True,
    )
    assert resultado["aplicado"] is True
    assert resultado["resumen"] == {"aplicados": 3, "ya_registrados": 0, "no_aplicados": 0, "errores": []}
    documento = json.loads(_ruta_eventos(raiz).read_text(encoding="utf-8"))
    assert len(documento["eventos"]) == 3
    assert {e["tipo_evento"] for e in documento["eventos"]} == {"TIENE_ESTADIA"}


def test_reintento_es_idempotente_no_duplica(tmp_path):
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    texto = "Las guías 473001, 473004 y 473010 tienen estadía."
    p1 = proponer_lote_incidencias(texto=texto, raiz=raiz, ruta_viajes=ruta_viajes)
    r1 = confirmar_lote_incidencias(raiz=raiz, ruta_viajes=ruta_viajes, acciones=p1["acciones"], actor="JAVIER", confirmado=True)
    assert r1["resumen"]["aplicados"] == 3

    # Mismo texto interpretado de nuevo (simula reenvío/refresco) y
    # confirmado otra vez -- nunca debe duplicar eventos.
    p2 = proponer_lote_incidencias(texto=texto, raiz=raiz, ruta_viajes=ruta_viajes)
    r2 = confirmar_lote_incidencias(raiz=raiz, ruta_viajes=ruta_viajes, acciones=p2["acciones"], actor="JAVIER", confirmado=True)
    assert r2["resumen"] == {"aplicados": 0, "ya_registrados": 3, "no_aplicados": 0, "errores": []}
    documento = json.loads(_ruta_eventos(raiz).read_text(encoding="utf-8"))
    assert len(documento["eventos"]) == 3  # nunca duplicó


def test_tipos_mezclados_registran_cada_incidencia_con_su_propio_tipo(tmp_path):
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    propuesta = proponer_lote_incidencias(
        texto="473015 tuvo devolución parcial y 473020 doble vuelta.", raiz=raiz, ruta_viajes=ruta_viajes,
    )
    resultado = confirmar_lote_incidencias(
        raiz=raiz, ruta_viajes=ruta_viajes, acciones=propuesta["acciones"], actor="JAVIER", confirmado=True,
    )
    assert resultado["resumen"]["aplicados"] == 2
    documento = json.loads(_ruta_eventos(raiz).read_text(encoding="utf-8"))
    tipos_por_guia = {e["numeros_guia"][0]: e["tipo_evento"] for e in documento["eventos"]}
    assert tipos_por_guia == {"473015": "DEVOLUCION_PARCIAL", "473020": "DOBLE_VUELTA"}


def test_actualizacion_gestion_backfill_de_tipo_desde_incidencia_existente(tmp_path):
    """Caso real de referencia (ejemplo 5): "473020 sigue pendiente de
    respuesta" no nombra el tipo -- si ya existe EXACTAMENTE una
    incidencia activa para esa guía, se completa desde ahí (nunca se
    adivina si hubiera más de una)."""
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    p0 = proponer_lote_incidencias(texto="473020 tiene doble vuelta.", raiz=raiz, ruta_viajes=ruta_viajes)
    confirmar_lote_incidencias(raiz=raiz, ruta_viajes=ruta_viajes, acciones=p0["acciones"], actor="JAVIER", confirmado=True)

    propuesta = proponer_lote_incidencias(texto="473020 sigue pendiente de respuesta.", raiz=raiz, ruta_viajes=ruta_viajes)
    assert propuesta["acciones"][0]["tipo"] == "DOBLE_VUELTA"
    assert propuesta["acciones"][0]["tipo_inferido_de_incidencia_existente"] is True
    assert propuesta["preview"]["aplicable"] is True

    resultado = confirmar_lote_incidencias(
        raiz=raiz, ruta_viajes=ruta_viajes, acciones=propuesta["acciones"], actor="JAVIER", confirmado=True,
    )
    assert resultado["resumen"]["aplicados"] == 1
    documento = json.loads(_ruta_eventos(raiz).read_text(encoding="utf-8"))
    evento = documento["eventos"][0]
    assert evento["tipo_evento"] == "DOBLE_VUELTA"
    assert evento["estado_gestion"] == "PENDIENTE_RESPUESTA"


def test_actualizacion_gestion_sin_incidencia_previa_queda_tipo_requerido(tmp_path):
    """Sin ninguna incidencia activa que inferir, nunca se adivina --
    `previsualizar_lote` marca TIPO_REQUERIDO, visible antes de aplicar."""
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    propuesta = proponer_lote_incidencias(texto="473001 sigue pendiente de respuesta.", raiz=raiz, ruta_viajes=ruta_viajes)
    assert "tipo" not in propuesta["acciones"][0]
    assert propuesta["preview"]["acciones"][0]["estado"] == "TIPO_REQUERIDO"
    assert propuesta["preview"]["aplicable"] is False


def test_rechazo_de_estadia_actualiza_gestion_sin_duplicar_el_hecho(tmp_path):
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    p0 = proponer_lote_incidencias(texto="La guía 473010 tiene estadía.", raiz=raiz, ruta_viajes=ruta_viajes)
    confirmar_lote_incidencias(raiz=raiz, ruta_viajes=ruta_viajes, acciones=p0["acciones"], actor="JAVIER", confirmado=True)

    p1 = proponer_lote_incidencias(texto="Rechazaron la estadía de 473010.", raiz=raiz, ruta_viajes=ruta_viajes)
    r1 = confirmar_lote_incidencias(raiz=raiz, ruta_viajes=ruta_viajes, acciones=p1["acciones"], actor="JAVIER", confirmado=True)
    assert r1["resumen"]["aplicados"] == 1  # cambio real: estado_gestion nuevo

    documento = json.loads(_ruta_eventos(raiz).read_text(encoding="utf-8"))
    assert len(documento["eventos"]) == 1  # nunca duplicó el hecho MARCA_VIAJE
    assert documento["eventos"][0]["estado_gestion"] == "RECHAZADA"


# ============================================================
# 5b. Composición en el preview real de Desktop (propuesta.acciones,
#    zipped por índice con propuesta.preview.acciones -- exactamente lo
#    que `atlas_viajes.html`/`renderPropuestaIncidencias` lee para pintar
#    las columnas "Tipo"/"Estado gestión") -- ANTES de cualquier
#    confirmación/escritura.
# ============================================================


def test_preview_estadia_confirmada_muestra_tipo_y_gestion_compuestos_antes_de_confirmar(tmp_path):
    """Criterio de aceptación: la frase compuesta debe mostrar, en el
    preview (antes de escribir nada), TIENE_ESTADIA + APROBADA para
    cada guía -- lo mismo que Desktop pinta en "Tipo"/"Estado gestión"."""
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    texto = "Las guías 473001, 473004, 473010, 473015 y 473020 tienen estadía confirmada."
    propuesta = proponer_lote_incidencias(texto=texto, raiz=raiz, ruta_viajes=ruta_viajes)

    assert propuesta["interpretado"] is True
    assert propuesta["preview"]["aplicable"] is True
    for accion, item in zip(propuesta["acciones"], propuesta["preview"]["acciones"]):
        assert accion["tipo"] == "TIENE_ESTADIA"
        assert accion["estado_gestion"] == "APROBADA"
        assert item["estado"] == "RESUELTA"  # lo que Desktop usa para la fila "ok"
    assert not _ruta_eventos(raiz).exists(), "el preview nunca debe escribir eventos_operacionales"


def test_confirmar_estadia_confirmada_aplica_tipo_y_gestion_en_una_sola_escritura_e_idempotente(tmp_path):
    """Aplicar la instrucción compuesta crea el hecho MARCA_VIAJE Y deja
    estado_gestion=APROBADA en la MISMA escritura (nunca dos pasos) --
    y repetir la misma instrucción nunca duplica ni reescribe de más
    (revalidación/idempotencia intactas)."""
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    texto = "Las guías 473001, 473004 y 473010 tienen estadía confirmada."
    p1 = proponer_lote_incidencias(texto=texto, raiz=raiz, ruta_viajes=ruta_viajes)
    r1 = confirmar_lote_incidencias(raiz=raiz, ruta_viajes=ruta_viajes, acciones=p1["acciones"], actor="JAVIER", confirmado=True)
    assert r1["resumen"] == {"aplicados": 3, "ya_registrados": 0, "no_aplicados": 0, "errores": []}

    documento = json.loads(_ruta_eventos(raiz).read_text(encoding="utf-8"))
    assert len(documento["eventos"]) == 3
    for evento in documento["eventos"]:
        assert evento["tipo_evento"] == "TIENE_ESTADIA"
        assert evento["estado_gestion"] == "APROBADA"
        assert evento["creado_en"] == evento["actualizado_en"]  # una sola escritura, no dos pasos

    # Reintento con la MISMA instrucción -- idempotente, nunca duplica.
    p2 = proponer_lote_incidencias(texto=texto, raiz=raiz, ruta_viajes=ruta_viajes)
    r2 = confirmar_lote_incidencias(raiz=raiz, ruta_viajes=ruta_viajes, acciones=p2["acciones"], actor="JAVIER", confirmado=True)
    assert r2["resumen"] == {"aplicados": 0, "ya_registrados": 3, "no_aplicados": 0, "errores": []}
    documento_final = json.loads(_ruta_eventos(raiz).read_text(encoding="utf-8"))
    assert len(documento_final["eventos"]) == 3  # nunca duplicó


# ============================================================
# 6. Seguridad -- B1 nunca escribe directamente.
# ============================================================


def test_interpretar_nunca_toca_disco(tmp_path):
    """La interpretación es una función pura -- ni siquiera necesita
    `raiz`/`ruta_viajes` para producir la lista de acciones."""
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    interpretar_instruccion_incidencias("Las guías 473001, 473004 y 473010 tienen estadía.")
    assert not _ruta_eventos(raiz).exists()
    assert not (raiz / "operacion" / "actual").exists() or list((raiz / "operacion" / "actual").iterdir()) == []


def test_accion_fuera_de_allowlist_nunca_se_aplica(tmp_path):
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    acciones = [{"accion": "BORRAR_TODO", "guia": "473001"}]
    from atlas_core.comandos_incidencias_operacionales import previsualizar_lote
    resultado_preview = previsualizar_lote(ruta_viajes=ruta_viajes, acciones=acciones)
    assert resultado_preview["acciones"][0]["estado"] == "ACCION_NO_PERMITIDA"
    resultado = confirmar_lote_incidencias(raiz=raiz, ruta_viajes=ruta_viajes, acciones=acciones, actor="JAVIER", confirmado=True)
    assert resultado["resultados"][0]["ok"] is False
    assert not _ruta_eventos(raiz).exists()


# ============================================================
# 5. Consultas históricas / no revisados (item 5 del bloque).
# ============================================================


def _confirmar(texto, raiz, ruta_viajes):
    p = proponer_lote_incidencias(texto=texto, raiz=raiz, ruta_viajes=ruta_viajes)
    return confirmar_lote_incidencias(raiz=raiz, ruta_viajes=ruta_viajes, acciones=p["acciones"], actor="JAVIER", confirmado=True)


def test_consulta_no_revisados_por_chofer(tmp_path):
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    # Sólo 473001 queda revisada (con incidencia); el resto de Toledo
    # (473004, 473015, 473020) sigue sin ningún hecho ni revisión.
    _confirmar("La guía 473001 tiene estadía.", raiz, ruta_viajes)

    respuesta = responder_consulta_incidencias_conversacional(
        "Muéstrame los viajes de Toledo que todavía no he revisado por incidencias.", raiz=raiz, ruta_viajes=ruta_viajes,
    )
    assert respuesta["origen"] == "INCIDENCIAS_NO_REVISADAS"
    transportes = {v["numero_transporte"] for v in respuesta["viajes"]}
    assert transportes == {"T2", "T4", "T5"}  # 473004, 473015, 473020 -- nunca T1 (ya tiene incidencia)


def test_consulta_gestion_aprobadas(tmp_path):
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    _confirmar("Las guías 473001 y 473004 tienen estadía.", raiz, ruta_viajes)
    _confirmar("Las estadías de 473001 y 473004 fueron aprobadas.", raiz, ruta_viajes)
    _confirmar("La guía 473010 tiene estadía.", raiz, ruta_viajes)
    _confirmar("Rechazaron la estadía de 473010.", raiz, ruta_viajes)

    respuesta = responder_consulta_incidencias_conversacional("Qué incidencias fueron aprobadas.", raiz=raiz, ruta_viajes=ruta_viajes)
    assert respuesta["origen"] == "INCIDENCIAS_GESTION"
    assert len(respuesta["incidencias"]) == 2
    assert {i["numero_transporte"] for i in respuesta["incidencias"]} == {"T1", "T2"}


def test_consulta_devoluciones_rechazadas_filtra_por_prefijo_sin_inventar_cual(tmp_path):
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    _confirmar("473015 tuvo devolución parcial.", raiz, ruta_viajes)
    _confirmar("Rechazaron la devolución parcial de 473015.", raiz, ruta_viajes)

    respuesta = responder_consulta_incidencias_conversacional("Qué devoluciones fueron rechazadas.", raiz=raiz, ruta_viajes=ruta_viajes)
    assert respuesta["origen"] == "INCIDENCIAS_GESTION"
    assert len(respuesta["incidencias"]) == 1
    assert respuesta["incidencias"][0]["tipo_evento"] == "DEVOLUCION_PARCIAL"


def test_consulta_estadias_pendientes_usa_pendientes_gestion(tmp_path):
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    _confirmar("473001 tiene estadía.", raiz, ruta_viajes)
    _confirmar("473001 sigue pendiente de respuesta.", raiz, ruta_viajes)
    _confirmar("473004 tiene estadía.", raiz, ruta_viajes)
    _confirmar("Las estadías de 473004 fueron aprobadas.", raiz, ruta_viajes)

    respuesta = responder_consulta_incidencias_conversacional("Qué estadías están pendientes.", raiz=raiz, ruta_viajes=ruta_viajes)
    assert respuesta["origen"] == "INCIDENCIAS_GESTION"
    assert len(respuesta["incidencias"]) == 1
    assert respuesta["incidencias"][0]["numero_transporte"] == "T1"


def test_consulta_viajes_por_chofer_y_mes_nombrado_se_delega_al_motor_generico(tmp_path):
    raiz, ruta_viajes = _entorno(tmp_path, FILAS_BASE)
    from datetime import date
    hoy = date(2026, 9, 15)
    from atlas_core.gestion_incidencias_conversacional import _reescribir_mes_nombrado
    texto_reescrito = _reescribir_mes_nombrado("Muéstrame los viajes de Leandro Toledo de agosto.", hoy=hoy)
    assert "01/08/2026" in texto_reescrito and "31/08/2026" in texto_reescrito

    respuesta = responder_consulta_incidencias_conversacional(
        "Muéstrame los viajes de Leandro Toledo de agosto.", raiz=raiz, ruta_viajes=ruta_viajes,
    )
    assert respuesta["origen"] == "DELEGADO_RESPONDER_CONSULTA_ATLAS"
    assert respuesta["estado"] == "OK"
    assert respuesta["resultado"].total_coincidencias == 4  # las 4 guías de Toledo, todas en agosto


def test_consulta_gestion_ambigua_por_chofer_no_adivina(tmp_path):
    filas = FILAS_BASE + [
        _fila(viaje_id="v6", numero_transporte="T6", numeros_guia="473099", fecha="15-08-2026", choferes="LEANDRO PEREZ"),
    ]
    raiz, ruta_viajes = _entorno(tmp_path, filas)
    respuesta = responder_consulta_incidencias_conversacional(
        "Muéstrame los viajes de Leandro que todavía no he revisado por incidencias.", raiz=raiz, ruta_viajes=ruta_viajes,
    )
    assert respuesta["estado"] == "AMBIGUA"
    assert set(respuesta["opciones_aclaracion"]) == {"LEANDRO TOLEDO", "LEANDRO PEREZ"}
