"""Bloque REGISTRO_DIRECCION CONTEXTO -- caso real 472640 (LAS VIOLETAS 55,
DSI UNDERGROUND CHILE SPA, guía 472640, transporte 0000355509): Javier
confirmó "LAS VIOLETAS 55" (Bloque R6 A/B/E, campo Dirección) -- exactamente
calle+número, lo que se le pide -- y Atlas Desktop respondió "Dirección
registrada, pero sigue sin poder calcularse una ruta confiable con ella".

Auditoría real (ver diagnóstico): el documento (`envio.json`) sólo trajo
"LAS VIOLETAS" en `despachar_a_crudo` (OCR truncado, B1 se abstuvo:
`DESTINO_CONTAMINADO_POR_OTRA_SECCION`, sin evidencia utilizable); no había
ninguna obra previa confirmada para "DSI UNDERGROUND CHILE SPA" (primer
documento de ese cliente/obra en el sistema). El geocodificador SÍ devolvió
un candidato real para "LAS VIOLETAS 55, Chile", pero con confianza por
debajo del umbral (`CONFIANZA_INSUFICIENTE`) -- un nombre de calle real,
ambiguo a nivel país sin comuna que lo acote. La comuna real ("Padre
Hurtado") sólo era legible en la foto del documento -- nunca capturada en
ningún campo/decisión persistido -- así que ninguna fuente automática podía
tenerla para ESTE caso concreto.

Estas pruebas cubren la CLASE de fallo, no sólo 472640: cuando Atlas SÍ
tiene una comuna/localidad confiable por otra vía (destino ya CONFIRMADO
para la misma obra, o mención inequívoca en el nombre de obra --
`resolver_comuna_territorial_conocida`), debe usarla sola, sin pedirle nada
extra al humano ni obligarlo a incrustarla dentro del campo Dirección; sólo
cuando NINGUNA fuente confiable existe (como en 472640) se permite pedirla
aparte (campo "Comuna/localidad" en Desktop) -- nunca inventar, nunca
fabricar una ruta sin evidencia real."""
from __future__ import annotations

import csv
import json

from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.decisiones_pendientes import (
    detectar_decision_destino_contaminado_documental, generar_artefacto,
)
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

COORD_AZA_COLINA = Coordenadas(-70.665977, -33.137558)
FECHA = "31-08-2026"
OBRA_DSI = "DSI UNDERGROUND CHILE SPA"


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "472640.jpeg", "estado_procesamiento": "OK", "numero_guia": "472640",
        "numero_transporte": "0000355509", "fecha": FECHA, "chofer": "LUIS REYES",
        "cliente": OBRA_DSI, "obra_destino": OBRA_DSI,
        "patente_tracto": "KN5439", "indicador_revision": "REVISAR",
        "planta_origen_id": "planta-colina", "planta_origen_nombre": "AZA COLINA",
        "origen_determinado_por": "MOBILE", "evidencia_origen": "MOBILE_INFORMADO",
        "despachar_a_crudo": "LAS VIOLETAS", "direccion_entrega": "", "estado_entrega": "",
        "distancia_km": "", "duracion_min": "", "proveedor_ruta": "",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "CONFIANZA_INSUFICIENTE",
        # Motivo REAL de 472640 (ver auditoría): el OCR truncó el destino y
        # B1 se abstuvo -- `detectar_decision_destino_contaminado_
        # documental` es el detector que realmente generó la decisión
        # pendiente para este caso (no `detectar_decision_destino_no_
        # resuelto`, que no reconoce `CONFIANZA_INSUFICIENTE` como motivo
        # de ruta -- ese es un rechazo de GEOCODIFICACIÓN, no de destino
        # documental ausente/contradictorio).
        "motivos_revision_documento": "DESTINO_CONTAMINADO_POR_OTRA_SECCION",
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


def _entorno(tmp_path, *, filas_csv, clientes=None, obras=None):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": clientes or []},
        "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": obras or [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    plantas = CatalogoPlantas(catalogos / "plantas.json")
    planta_colina = plantas.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="AV EJEMPLO 1", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    for fila in filas_csv:
        if fila.get("planta_origen_id") == "planta-colina":
            fila["planta_origen_id"] = planta_colina.planta_id
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, filas_csv)
    return {"raiz": raiz, "catalogos": catalogos, "actual": actual, "dataset": dataset}


def _cliente_dict(cliente_id="cliente-dsi"):
    return {
        "cliente_id": cliente_id, "razon_social": OBRA_DSI,
        "nombre_normalizado": OBRA_DSI, "nombre_comercial": "", "rut": "76086428-5",
        "aliases": [], "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO", "fuente": "TEST",
        "observacion": "", "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00",
    }


def _obra_dict(obra_id="obra-dsi", cliente_id="cliente-dsi", nombre=OBRA_DSI):
    return {
        "obra_id": obra_id, "cliente_id": cliente_id, "nombre_canonico": nombre,
        "nombre_normalizado": nombre, "aliases_documentales": [],
        "estado": "OBSERVADA", "estado_vigencia": "ACTIVO", "evidencias": [],
        "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00",
    }


def _publicar(entorno, *decisiones):
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=list(decisiones), ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )


def _proveedor(mapa_consulta_a_candidato, *, ruta_km=25.4, ruta_min=38.2):
    """`mapa_consulta_a_candidato`: {consulta_exacta: CandidatoGeocodificacion}.
    Cualquier consulta NO listada cae al candidato por defecto del
    simulador (confianza `None` -- exactamente "insuficiente", el mismo
    comportamiento real de un proveedor que no pudo ubicarla con
    seguridad) -- nunca se define explícitamente un candidato malo, el
    valor por defecto YA lo es."""
    geocodificaciones = {
        consulta: ResultadoGeocodificacion(EstadoRuta.REQUIERE_REVISION, (candidato,), "")
        for consulta, candidato in mapa_consulta_a_candidato.items()
    }
    return ProveedorRutasSimulado(
        geocodificaciones=geocodificaciones,
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, ruta_km, ruta_min, "SINTETICO"),
    )


# ============================================================
# 1/3. Regresión exacta 472640 -- sin ninguna fuente confiable de comuna,
# Atlas nunca fabrica una ruta; la decisión permite pedirle la comuna al
# humano (campo separado, ver Desktop) en vez de fallar en silencio.
# ============================================================


def test_472640_sin_contexto_disponible_no_fabrica_ruta_y_permite_pedir_comuna(tmp_path):
    fila = _fila_csv()
    entorno = _entorno(tmp_path, filas_csv=[fila], clientes=[_cliente_dict()])
    decision = detectar_decision_destino_contaminado_documental(
        archivo="472640.jpeg", fila=fila, carpeta_catalogos=entorno["catalogos"],
    )
    assert decision is not None
    # Sin destino confirmado previo ni mención de comuna en el nombre de
    # obra: nada confiable que sugerir -- Desktop debe mostrar el campo
    # separado "Comuna/localidad" (contrato: sólo si NO hay nada confiable).
    assert "comuna_sugerida" not in decision["contexto"]
    _publicar(entorno, decision)

    direccion = "LAS VIOLETAS 55"
    proveedor = _proveedor({
        f"{direccion}, Chile": CandidatoGeocodificacion(
            Coordenadas(-70.75, -33.57), direccion + ", RM, Chile", 0.3,
        ),
    })
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion,
        proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
    )
    assert resultado["ok"] is True
    assert resultado["ruta_resuelta"] is False

    fila_final = _leer_csv(entorno["dataset"])[0]
    assert fila_final["despachar_a_crudo"] == direccion
    assert fila_final["estado_ruta"] == "REQUIERE_REVISION"
    assert fila_final["motivo_ruta"].split(":", 1)[0] == "CONFIANZA_INSUFICIENTE"
    assert fila_final["distancia_km"] == ""
    assert fila_final["duracion_min"] == ""


# ============================================================
# 2/5/8. Destino ya CONFIRMADO para la misma obra -> la comuna se reutiliza
# sola; el humano NUNCA vuelve a escribirla. km/tiempo/proveedor quedan
# persistidos tras la decisión, sin reproceso manual.
# ============================================================


def test_comuna_de_destino_confirmado_previo_se_reutiliza_sin_preguntar(tmp_path):
    fila_1 = _fila_csv(numero_guia="472037", despachar_a_crudo="")
    fila_2 = _fila_csv(numero_guia="472640", numero_transporte="0000355509")
    entorno = _entorno(
        tmp_path, filas_csv=[fila_1, fila_2],
        clientes=[_cliente_dict()], obras=[_obra_dict()],
    )
    # Paso A -- una guía anterior de la MISMA obra ya confirmó una
    # dirección real que geocodificó con éxito a "Padre Hurtado".
    decision_1 = detectar_decision_destino_contaminado_documental(
        archivo="472037.jpeg", fila=fila_1, carpeta_catalogos=entorno["catalogos"],
    )
    _publicar(entorno, decision_1)
    direccion_1 = "CAMINO LA ESTRELLA 100"
    proveedor_1 = _proveedor({
        f"{direccion_1}, Chile": CandidatoGeocodificacion(
            Coordenadas(-70.75, -33.57), direccion_1 + ", Padre Hurtado, RM, Chile", 1.0,
            "Padre Hurtado", "Metropolitana",
        ),
    })
    resultado_1 = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision_1["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion_1, proveedor_rutas=proveedor_1,
    )
    assert resultado_1["ruta_resuelta"] is True

    # Paso B -- guía 472640: misma obra, dirección nueva SIN comuna
    # propia ("LAS VIOLETAS 55") -- Atlas ya conoce "Padre Hurtado" por
    # el destino recién CONFIRMADO; la decisión debe traerlo sugerido.
    decision_2 = detectar_decision_destino_contaminado_documental(
        archivo="472640.jpeg", fila=fila_2, carpeta_catalogos=entorno["catalogos"],
    )
    assert decision_2["contexto"]["comuna_sugerida"] == "Padre Hurtado"
    _publicar(entorno, decision_1, decision_2)

    direccion_2 = "LAS VIOLETAS 55"
    # Sólo la consulta YA AMPLIADA con la comuna auto-resuelta geocodifica
    # con confianza suficiente -- la consulta desnuda (sin comuna) caería
    # al candidato por defecto (confianza None), exactamente como en
    # 472640 real -- así se prueba que la comuna SÍ viajó, no que el
    # proveedor "adivinó" solo.
    proveedor_2 = _proveedor({
        f"{direccion_2} Padre Hurtado, Chile": CandidatoGeocodificacion(
            Coordenadas(-70.76, -33.58), direccion_2 + ", Padre Hurtado, RM, Chile", 0.95,
            "Padre Hurtado", "Metropolitana",
            # Bloque G1-B -- identidad territorial por código, como
            # devolvería un proveedor real ya resuelto contra el catálogo
            # territorial cerrado (ver `resolver_comuna_territorial_
            # conocida`/`_contexto_geografico_desde_texto`: "Padre
            # Hurtado" -> CL/13604/13).
            codigo_pais="CL", codigo_unidad="13604", codigo_contexto="13",
        ),
    }, ruta_km=18.2, ruta_min=27.0)
    resultado_2 = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision_2["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion_2,
        proveedor_rutas=proveedor_2, proveedor_rutas_fallback=proveedor_2,
    )
    assert resultado_2["ok"] is True
    assert resultado_2["ruta_resuelta"] is True  # nunca pidió la comuna de nuevo

    fila_final = _leer_csv(entorno["dataset"])[1]
    assert fila_final["numero_guia"] == "472640"
    # Bloque C (corrección Codex) -- aserciones completas del éxito, no
    # sólo "ruta_resuelta": estado/motivo coherentes, derivados numéricos
    # Y códigos territoriales G1-C, todos persistidos en la MISMA
    # operación (nunca requiere un segundo reproceso manual).
    assert fila_final["estado_ruta"] == "RUTA_CALCULADA"
    # Un éxito real nunca deja arrastrando un motivo de rechazo viejo.
    assert fila_final["motivo_ruta"] == ""
    assert fila_final["distancia_km"] == "18.2"
    assert fila_final["duracion_min"] == "27.0"
    assert fila_final["proveedor_ruta"] == "simulado"
    assert fila_final["localidad_entrega"] == "Padre Hurtado"
    assert fila_final["region_entrega"] == "Metropolitana"
    # Bloque G1-C -- identidad territorial por CÓDIGO, no sólo el texto
    # de localidad/región: sólo se publican en un destino RESUELTO real
    # (nunca en uno rechazado, ver `resolver_destino_entrega_validado`).
    assert fila_final["codigo_pais"] == "CL"
    assert fila_final["codigo_unidad"] == "13604"  # Padre Hurtado, catálogo territorial cerrado
    assert fila_final["codigo_contexto"] == "13"  # Región Metropolitana
    # La dirección persistida es EXACTAMENTE la que escribió Javier --
    # nunca la comuna agregada para geocodificar (Bloque 7, más abajo).
    assert fila_final["despachar_a_crudo"] == direccion_2


# ============================================================
# 6. Comuna mencionada de forma inequívoca en el nombre de obra (mismo
# patrón operacional "CLIENTE OBRA COMUNA", ya usado en R2.5/464264) --
# se reutiliza sola, sin destino confirmado previo.
# ============================================================


def test_comuna_mencionada_en_nombre_de_obra_se_reutiliza_sin_preguntar(tmp_path):
    obra_con_comuna = "CONSTRUCTORA EJEMPLO PADRE HURTADO"
    fila = _fila_csv(obra_destino=obra_con_comuna)
    entorno = _entorno(
        tmp_path, filas_csv=[fila],
        clientes=[_cliente_dict()], obras=[_obra_dict(nombre=obra_con_comuna)],
    )
    decision = detectar_decision_destino_contaminado_documental(
        archivo="472640.jpeg", fila=fila, carpeta_catalogos=entorno["catalogos"],
    )
    assert decision["contexto"]["comuna_sugerida"] == "Padre Hurtado"
    _publicar(entorno, decision)

    direccion = "LAS VIOLETAS 55"
    proveedor = _proveedor({
        f"{direccion} Padre Hurtado, Chile": CandidatoGeocodificacion(
            Coordenadas(-70.76, -33.58), direccion + ", Padre Hurtado, RM, Chile", 0.9,
            "Padre Hurtado", "Metropolitana",
            codigo_pais="CL", codigo_unidad="13604", codigo_contexto="13",
        ),
    })
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion,
        proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
    )
    assert resultado["ruta_resuelta"] is True

    # Bloque C (corrección Codex) -- mismas aserciones completas de éxito.
    fila_final = _leer_csv(entorno["dataset"])[0]
    assert fila_final["estado_ruta"] == "RUTA_CALCULADA"
    assert fila_final["motivo_ruta"] == ""
    assert fila_final["distancia_km"] == "25.4"  # ruta_km por defecto de _proveedor
    assert fila_final["duracion_min"] == "38.2"
    assert fila_final["proveedor_ruta"] == "simulado"
    assert fila_final["localidad_entrega"] == "Padre Hurtado"
    assert fila_final["region_entrega"] == "Metropolitana"
    assert fila_final["codigo_pais"] == "CL"
    assert fila_final["codigo_unidad"] == "13604"
    assert fila_final["codigo_contexto"] == "13"
    assert fila_final["despachar_a_crudo"] == direccion


# ============================================================
# 4. Sin ninguna fuente automática, el humano la aporta manualmente (campo
# separado "Comuna/localidad") -> Atlas la usa y calcula la ruta.
# ============================================================


def test_comuna_aportada_manualmente_calcula_ruta(tmp_path):
    fila = _fila_csv()
    entorno = _entorno(tmp_path, filas_csv=[fila], clientes=[_cliente_dict()])
    decision = detectar_decision_destino_contaminado_documental(
        archivo="472640.jpeg", fila=fila, carpeta_catalogos=entorno["catalogos"],
    )
    assert "comuna_sugerida" not in decision["contexto"]
    _publicar(entorno, decision)

    direccion = "LAS VIOLETAS 55"
    proveedor = _proveedor({
        f"{direccion} Padre Hurtado, Chile": CandidatoGeocodificacion(
            Coordenadas(-70.76, -33.58), direccion + ", Padre Hurtado, RM, Chile", 0.92,
            "Padre Hurtado", "Metropolitana",
            codigo_pais="CL", codigo_unidad="13604", codigo_contexto="13",
        ),
    })
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion, comuna_manual="Padre Hurtado",
        proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
    )
    assert resultado["ok"] is True
    assert resultado["ruta_resuelta"] is True

    # Bloque C (corrección Codex) -- aserciones completas de éxito.
    fila_final = _leer_csv(entorno["dataset"])[0]
    assert fila_final["estado_ruta"] == "RUTA_CALCULADA"
    assert fila_final["motivo_ruta"] == ""
    assert fila_final["distancia_km"] == "25.4"
    assert fila_final["duracion_min"] == "38.2"
    assert fila_final["proveedor_ruta"] == "simulado"
    assert fila_final["localidad_entrega"] == "Padre Hurtado"
    assert fila_final["region_entrega"] == "Metropolitana"
    assert fila_final["codigo_pais"] == "CL"
    assert fila_final["codigo_unidad"] == "13604"
    assert fila_final["codigo_contexto"] == "13"
    # Nunca incrustada en el campo Dirección -- viajó aparte.
    assert fila_final["despachar_a_crudo"] == direccion


# ============================================================
# 7. "SECTOR LA ESPERANZA" es referencia/sector, nunca calle -- y la
# comuna usada para geocodificar NUNCA se incrusta en `despachar_a_crudo`
# persistido, agregada manual o automáticamente.
# ============================================================


def test_comuna_nunca_se_incrusta_en_despachar_a_crudo_persistido(tmp_path):
    fila = _fila_csv()
    entorno = _entorno(tmp_path, filas_csv=[fila], clientes=[_cliente_dict()])
    decision = detectar_decision_destino_contaminado_documental(
        archivo="472640.jpeg", fila=fila, carpeta_catalogos=entorno["catalogos"],
    )
    _publicar(entorno, decision)

    # Javier escribe SÓLO calle+número -- "SECTOR LA ESPERANZA" (una
    # referencia visible en la foto, no parte de la calle) nunca se
    # escribe aquí, y la comuna manual viaja en su propio campo.
    direccion = "LAS VIOLETAS 55"
    proveedor = _proveedor({
        f"{direccion} Padre Hurtado, Chile": CandidatoGeocodificacion(
            Coordenadas(-70.76, -33.58), direccion + ", Padre Hurtado, RM, Chile", 0.9,
            "Padre Hurtado", "Metropolitana",
        ),
    })
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion, comuna_manual="Padre Hurtado",
        proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
    )
    assert resultado["ruta_resuelta"] is True
    fila_final = _leer_csv(entorno["dataset"])[0]
    assert fila_final["despachar_a_crudo"] == "LAS VIOLETAS 55"
    assert "PADRE HURTADO" not in fila_final["despachar_a_crudo"].upper()
    assert "SECTOR LA ESPERANZA" not in fila_final["despachar_a_crudo"].upper()


# ============================================================
# 9. Regresión G1/R2.5 -- la invalidación de derivados (incluidos los
# códigos territoriales G1-C) sigue corriendo ANTES de la resolución
# automática de comuna; nada de un intento viejo sobrevive si el nuevo
# intento (aunque auto-resuelva comuna) apunta a otro lugar.
# ============================================================


def test_r2_5_invalida_derivados_viejos_antes_de_reintentar_con_comuna_auto_resuelta(tmp_path):
    fila_vieja = _fila_csv(
        despachar_a_crudo="DIRECCION VIEJA 1", direccion_entrega="Otra Comuna, RM, Chile",
        localidad_entrega="Otra Comuna", region_entrega="Metropolitana",
        codigo_pais="CL", codigo_unidad="99999", codigo_contexto="13",
        distancia_km="999.9", duracion_min="999", proveedor_ruta="viejo",
        estado_ruta="REQUIERE_REVISION", motivo_ruta="CONFIANZA_INSUFICIENTE",
    )
    entorno = _entorno(
        tmp_path, filas_csv=[fila_vieja],
        clientes=[_cliente_dict()], obras=[_obra_dict()],
    )
    decision = detectar_decision_destino_contaminado_documental(
        archivo="472640.jpeg", fila=fila_vieja, carpeta_catalogos=entorno["catalogos"],
    )
    _publicar(entorno, decision)

    direccion = "LAS VIOLETAS 55"
    proveedor = _proveedor({
        f"{direccion}, Chile": CandidatoGeocodificacion(
            Coordenadas(-70.75, -33.57), direccion + ", RM, Chile", 0.3,
        ),
    })
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion,
        proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
    )
    assert resultado["ruta_resuelta"] is False
    fila_final = _leer_csv(entorno["dataset"])[0]
    # Nada del intento ANTERIOR sobrevive -- ni siquiera para volver a
    # fallar; se recalcula desde cero y el resultado fresco (aquí,
    # también sin ruta) es el único que queda persistido.
    for campo in (
        "direccion_entrega", "localidad_entrega", "region_entrega",
        "codigo_pais", "codigo_unidad", "codigo_contexto",
        "distancia_km", "duracion_min",
    ):
        assert fila_final[campo] == "", campo
    assert fila_final["proveedor_ruta"] != "viejo"
    assert fila_final["despachar_a_crudo"] == direccion
