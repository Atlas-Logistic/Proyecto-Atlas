"""Migraciones ligeras e idempotentes de artefactos operacionales derivados.

No ejecuta OCR, no lee imágenes y no recalcula rutas. El dataset documental y
los catálogos son las fuentes; ``viajes.csv`` y las clasificaciones de ficha
son proyecciones regenerables de esas fuentes.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from atlas_core.almacenamiento_portable import (
    bloqueo_sesion,
    escribir_json_atomico,
    escribir_estado_operacion,
    leer_estado_operacion,
)
from atlas_core.aplicacion_decisiones import LEDGER
from atlas_core.decisiones_pendientes import NOMBRE_ARTEFACTO
from atlas_core.mobile import RepositorioEnviosMobile, revalidar_asociacion_mobile_sin_ocr
from atlas_core.reporte_viajes import _sha256_archivo, generar_reporte_viajes
from atlas_core.revalidacion_documental import (
    reconciliar_bandeja_decisiones,
    reconciliar_incidencias_rut_chofer_documental,
    revalidar_indicadores_documentales_sin_ocr,
    revalidar_material_estampado_persistido_sin_ocr,
    revalidar_motivo_destino_ya_confirmado_sin_ocr,
    revalidar_origen_encabezado_no_confiable_sin_ocr,
    revalidar_ruta_sin_destino_calculado_sin_ocr,
)


# Bloque RECONCILIACIÓN POST-DECISIÓN -- causa raíz real (caso 472640,
# confirmada dos veces): la migración de versión es la ÚNICA señal que hace
# que `reconciliar_estado_derivado` vuelva a barrer una operación que YA
# alcanzó la versión vigente (ver `migracion = version_previa <
# RULESET_VERSION`, más abajo) -- un cambio de REGLAS dentro de una misma
# corrida (p. ej. corregir la corroboración que usa `revalidar_motivo_
# destino_ya_confirmado_sin_ocr`, commit efb2067) sin subir este número
# queda INVISIBLE para cualquier operación que ya migró: `migracion` da
# `False`, y si el dataset no cambió por ningún otro motivo (ninguna
# decisión nueva, ningún reintento de ruta vencido), la reconciliación
# entera se aborta temprano (`VERSION_VIGENTE_SIN_REINTENTO_PENDIENTE`) sin
# ejecutar NINGÚN revalidador -- el fix de reglas nunca llega a correr
# contra datos reales hasta que algo más (una decisión humana nueva)
# vuelva a mover el dataset. Éste es el nombre EXPLÍCITO del número que
# hay que subir cada vez que cambian las reglas de cualquier `revalidar_*_
# sin_ocr` invocado desde `reconciliar_estado_derivado` -- no sólo cuando
# cambia el ESQUEMA de los artefactos derivados (`pendientes_tecnicos.json`,
# etc., el motivo original de esta migración). `VERSION_ESTADO_DERIVADO`
# (persistido en `estado_operacion.json`, nombre de campo ya fijado, nunca
# se renombra) sigue siendo exactamente este mismo número -- RULESET_
# VERSION es sólo el nombre que dice qué dispara la migración: CUALQUIER
# cambio de reglas de reconciliación, no sólo un cambio de esquema.
#
# Subida de 3 a 4 -- causa raíz real: la migración a versión 3 ya había
# corrido (y quedado persistida en `estado_operacion.json`) usando la
# corroboración VIEJA de `revalidar_motivo_destino_ya_confirmado_sin_ocr`
# (sólo destino CONFIRMADO en catálogo) ANTES de que el commit efb2067
# agregara la corroboración por `estado_ruta` ya `RUTA_CALCULADA` -- para
# una obra sin ningún destino en catálogo (472640, DSI UNDERGROUND CHILE
# SPA), la reconciliación NUNCA volvió a intentarlo con la regla nueva,
# porque `version_previa` ya no era menor que 3. Subir a 4 dispara, en la
# PRÓXIMA carga natural de Desktop (nunca un reproceso manual de ninguna
# guía puntual), un barrido completo con TODAS las reglas vigentes.
#
# Subida de 4 a 5 -- causa raíz real (viaje 0000355433, guías 472623/
# 472624): la migración a versión 4 ya había corrido y quedado persistida
# ANTES de que este ticket agregara `revalidar_indicadores_documentales_
# sin_ocr` (convergencia única de `indicador_revision`/`estado_documental`/
# `estado_operacional`) y generalizara `revalidar_asociacion_mobile_sin_
# ocr` para resincronizar `estado` aun con la asociación ya resuelta --
# sin subir este número, ambas correcciones de reglas quedarían
# INVISIBLES para cualquier operación ya migrada a 4 (exactamente este
# caso real), tal como advierte el párrafo de arriba.
#
# Subida de 5 a 6 -- bloque previo al lote 2: se conectan aquí
# `revalidar_origen_encabezado_no_confiable_sin_ocr` (caso real 464367,
# AZA RENCA aceptado desde "CASA MATRIZ PLANTA RENCA") y
# `reconciliar_bandeja_decisiones` (Motor de Evidencia -- homologación de
# patente por similitud/historial, alias por RUT exacto, obra por
# evidencia externa) al flujo automático -- antes, ambas sólo corrían
# detrás de un camino de excepción manual (`aplicar_decision_pendiente.py`,
# sólo tras `DecisionObsoletaError`) o de sus propios tests. Una operación
# que ya migró a la versión 5 nunca volvería a barrerse con estas dos
# reglas nuevas sin subir este número, igual que advierte el párrafo de
# arriba.
RULESET_VERSION = 6
VERSION_ESTADO_DERIVADO = RULESET_VERSION
NOMBRE_PENDIENTES_TECNICOS = "pendientes_tecnicos.json"
INTERVALO_REINTENTO = timedelta(hours=24)
MAX_REINTENTOS_IGUALES_ARRANQUE = 3


def _leer_filas(ruta: Path) -> list[dict[str, str]]:
    with ruta.open("r", newline="", encoding="utf-8-sig") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _guias_humanas(decisiones: Path) -> set[str]:
    try:
        contenido = json.loads(decisiones.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {
        str((d.get("documento") or {}).get("numero_guia", "")).strip()
        for d in contenido.get("decisiones", []) if d.get("estado") == "PENDIENTE"
    }


def _huella_ruta(fila: dict[str, str]) -> str:
    campos = (
        "planta_origen_id", "despachar_a_crudo", "cliente", "obra_destino",
        "destino_id", "motivo_ruta", "resultado_atlas_ia_json",
    )
    return hashlib.sha256("\0".join(str(fila.get(c, "")) for c in campos).encode("utf-8")).hexdigest()


def _cargar_seguimiento(ruta: Path) -> dict[str, dict[str, object]]:
    try:
        contenido = json.loads(ruta.read_text(encoding="utf-8"))
        return {str(p["numero_guia"]): p for p in contenido.get("pendientes", [])}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _pendientes_ruta(dataset: Path, decisiones: Path) -> list[dict[str, str]]:
    humanas = _guias_humanas(decisiones)
    return [
        f for f in _leer_filas(dataset)
        if str(f.get("numero_guia", "")).strip() not in humanas
        and str(f.get("indicador_revision", "")).strip() == "OK"
        and str(f.get("estado_ruta", "")).strip() not in ("", "RUTA_CALCULADA")
        and str(f.get("planta_origen_id", "")).strip()
        and str(f.get("despachar_a_crudo", "")).strip()
    ]


def _registro_pendiente(fila: dict[str, str], previo: dict[str, object] | None) -> dict[str, object]:
    huella = _huella_ruta(fila)
    mismo = previo if previo and previo.get("huella_datos") == huella else None
    return {
        "numero_guia": str(fila.get("numero_guia", "")).strip(),
        "dependencia_fallida": "GEOCODIFICACION_ROUTING",
        "resultado_pendiente": "DIRECCION_ENTREGA_KM_TIEMPO",
        "motivo_actual": str(fila.get("motivo_ruta", "")).strip(),
        "reintentable": True,
        "datos_disponibles": {
            "planta_origen_id": str(fila.get("planta_origen_id", "")).strip(),
            "destino_documental": str(fila.get("despachar_a_crudo", "")).strip(),
            "cliente": str(fila.get("cliente", "")).strip(),
            "obra": str(fila.get("obra_destino", "")).strip(),
            "evidencia_b1_persistida": bool(str(fila.get("resultado_atlas_ia_json", "")).strip()),
        },
        "huella_datos": huella,
        "intentos_misma_evidencia": int((mismo or {}).get("intentos_misma_evidencia", 0)),
        "ultimo_intento": (mismo or {}).get("ultimo_intento"),
        "ultimo_resultado": (mismo or {}).get("ultimo_resultado"),
        "historial_resultados": list((mismo or {}).get("historial_resultados", [])),
        "proxima_oportunidad": "ARRANQUE_TRAS_24H_O_CAMBIO_DE_EVIDENCIA",
        "escalamiento": "PROXIMA_CORRIDA_GUIAS_REVALIDACION_GLOBAL_B1" if int((mismo or {}).get("intentos_misma_evidencia", 0)) >= MAX_REINTENTOS_IGUALES_ARRANQUE else "REINTENTO_DEPENDENCIA",
    }


def reconciliar_estado_derivado(
    *, raiz_atlas: str | Path, reloj=lambda: datetime.now(timezone.utc),
    proveedor_rutas=None, proveedor_rutas_fallback=None,
) -> dict[str, object]:
    """Actualiza una operación antigua una sola vez por RULESET_VERSION.

    `migracion` (más abajo) sólo se dispara si `version_previa <
    RULESET_VERSION` -- CUALQUIER cambio a las reglas de alguno de los
    `revalidar_*_sin_ocr` invocados aquí (no sólo un cambio de esquema de
    los artefactos derivados) exige subir `RULESET_VERSION`; de lo
    contrario, una operación que ya alcanzó la versión vigente nunca
    vuelve a ejecutar la regla corregida hasta que algo MÁS mueva el
    dataset (ver docstring de `RULESET_VERSION`, caso real 472640)."""
    raiz = Path(raiz_atlas)
    actual = raiz / "operacion" / "actual"
    dataset = actual / "analisis_completo_guias.csv"
    catalogos = raiz / "catalogos_privados"
    estado_previo = leer_estado_operacion(raiz=raiz) or {}
    version_previa = int(estado_previo.get("version_estado_derivado", 0) or 0)
    if not dataset.is_file():
        return {"reconciliado": False, "motivo": "SIN_DATASET", "version": version_previa}

    instante = reloj().astimezone(timezone.utc)
    sello = instante.strftime("%Y%m%d_%H%M%S_%f")
    respaldo = raiz / "respaldos" / f"reconciliacion_estado_derivado_v{VERSION_ESTADO_DERIVADO}_{sello}"
    reporte = raiz / "reportes" / f"reporte_desktop_reconciliado_v{VERSION_ESTADO_DERIVADO}_{sello}"
    estado_ruta = actual / "estado_operacion.json"
    decisiones = actual / NOMBRE_ARTEFACTO
    ruta_pendientes = actual / NOMBRE_PENDIENTES_TECNICOS
    seguimiento_previo = _cargar_seguimiento(ruta_pendientes)
    pendientes_antes = _pendientes_ruta(dataset, decisiones)
    registros = [_registro_pendiente(f, seguimiento_previo.get(str(f.get("numero_guia", "")))) for f in pendientes_antes]
    por_reintentar = []
    for registro in registros:
        ultimo = registro.get("ultimo_intento")
        vencido = True
        if ultimo:
            try:
                vencido = instante - datetime.fromisoformat(str(ultimo)) >= INTERVALO_REINTENTO
            except ValueError:
                pass
        if registro["intentos_misma_evidencia"] < MAX_REINTENTOS_IGUALES_ARRANQUE and vencido:
            por_reintentar.append(str(registro["numero_guia"]))
    migracion = version_previa < RULESET_VERSION
    # Bloque R2.5 -- PROYECCIÓN CANÓNICA -> OPERACIÓN: caso real 464264
    # (decisión humana aplicada; "Revisión de Atlas" ya reflejaba 0
    # decisiones, pero `viajes.csv` seguía siendo el snapshot generado
    # ANTES de la decisión -- Desktop mostraba "Destino operacional: No
    # disponible" y el km/tiempo del destino ANTERIOR indefinidamente,
    # porque nada volvía a llamar `generar_reporte_viajes` fuera de un
    # drop de imágenes nuevas). El dataset puede cambiar por muchas vías
    # que no son "migración" ni "reintento de ruta vencido" (cualquier
    # decisión humana vía `aplicar_decision_obra`, cualquier revalidación
    # `_sin_ocr`) -- comparar la huella del dataset contra la huella que
    # el ÚLTIMO `reporte_vigente` publicado registró es la señal general,
    # sin polling: se evalúa en la misma oportunidad de reconciliación
    # natural que ya dispara cada carga de Desktop.
    huella_dataset_actual = _sha256_archivo(dataset)
    reporte_desactualizado = huella_dataset_actual != estado_previo.get("dataset_sha256")
    if not migracion and not por_reintentar and not reporte_desactualizado:
        return {
            "reconciliado": False, "motivo": "VERSION_VIGENTE_SIN_REINTENTO_PENDIENTE",
            "version": version_previa, "pendientes_tecnicos": len(registros),
        }

    with bloqueo_sesion(actual, "reconciliacion_estado_derivado"):
        # Bloque CONSISTENCIA OPERACIONAL, Fase 2 -- este lock ya NO
        # protege el dataset (sus escritores reales son las
        # revalidaciones `_sin_ocr` de abajo, cada una atómica y
        # protegida por su PROPIO lock común, "revalidacion_dataset" --
        # ver más abajo). Sigue existiendo para que dos reconciliaciones
        # completas no corran en paralelo pisándose sus propios
        # artefactos (`pendientes_tecnicos.json`, la carpeta de reporte,
        # `estado_operacion.json`) -- una transacción de negocio, igual
        # que el lock exterior de `aplicar_decision_obra`.
        respaldo.mkdir(parents=True, exist_ok=False)
        # El respaldo se conserva como AUDITORÍA/histórico -- NUNCA como
        # fuente para restaurar el dataset a ciegas (ver la Regla
        # absoluta del bloque: nunca reponer una copia vieja del dataset
        # si otro escritor real pudo haberlo modificado desde el
        # snapshot). `estado_operacion.json` tampoco se restaura desde
        # acá -- ver por qué en el `except` de más abajo.
        shutil.copy2(dataset, respaldo / dataset.name)
        if estado_ruta.is_file():
            shutil.copy2(estado_ruta, respaldo / estado_ruta.name)
        if decisiones.is_file():
            shutil.copy2(decisiones, respaldo / decisiones.name)
        if ruta_pendientes.is_file():
            shutil.copy2(ruta_pendientes, respaldo / ruta_pendientes.name)
        (respaldo / "manifest.json").write_text(json.dumps({
            "version_origen": version_previa,
            "version_destino": VERSION_ESTADO_DERIVADO,
            "creado_en": instante.isoformat(),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        # Bloque RECONCILIACIÓN POST-DECISIÓN -- caso real 472640: estas
        # tres revalidaciones NUNCA leen OCR ni recalculan ruta -- sólo
        # reconcilian flags/estados derivados YA obsoletos contra reglas
        # ya vigentes (motivo documental de destino ya confirmado por una
        # decisión humana o por catálogo; material que en verdad fusiona
        # varios ítems reales o trae un sello pegado; asociación/estado de
        # un envío Mobile cuyo propio documento ya tiene fila fresca en el
        # dataset). Antes corrían SÓLO durante una migración de versión
        # (`if migracion:`) -- la primera vez que Javier confirmó una
        # dirección real (472640) y Atlas recalculó km/tiempo
        # correctamente, el viaje seguía mostrando "Pendiente técnico" y
        # el envío Mobile seguía "sin asociación" pidiendo "Confirmar
        # viaje", porque nada volvía a mirar estos tres flags en la MISMA
        # reconciliación que ya corre automáticamente en cada carga de
        # Desktop. Corren siempre que se entra a este bloque (migración,
        # reintento de ruta vencido, o simplemente el dataset avanzó por
        # cualquier decisión humana) -- nunca sólo una vez por versión.
        limpieza = revalidar_motivo_destino_ya_confirmado_sin_ocr(
            ruta_dataset=dataset, carpeta_catalogos=catalogos,
        )
        limpieza_material = revalidar_material_estampado_persistido_sin_ocr(ruta_dataset=dataset)
        # Bloque CORRECCIÓN ESTRUCTURAL DE ORIGEN DOCUMENTAL AZA -- causa
        # raíz real (464367): un origen que quedó determinado ÚNICAMENTE
        # por `evidencia_origen="ENCABEZADO_GUIA"` (membrete/casa matriz
        # societaria, nunca la planta real de despacho) nunca se
        # revertía sola -- esta función existía y estaba probada, pero
        # ningún flujo automático la invocaba. Corre ANTES del reintento
        # de ruta y de la convergencia de indicadores de abajo, para que
        # un origen recién invalidado (vuelve a `ORIGEN_NO_DETERMINADO`)
        # se refleje de inmediato en `estado_operacional`, nunca con un
        # ciclo de rezago.
        limpieza_origen = revalidar_origen_encabezado_no_confiable_sin_ocr(ruta_dataset=dataset)
        # Bloque FIX RUT AUSENTE -- caso real 464367 (CARLOS ÑANCUCHEO):
        # un chofer identificado por nombre pero sin RUT documental
        # (ausente o inválido) puede tener RUT canónico confiable en
        # catálogo o en el histórico del propio dataset -- función ya
        # existente y probada, sin flujo automático que la invocara.
        limpieza_rut_chofer = reconciliar_incidencias_rut_chofer_documental(raiz_atlas=raiz, reloj=lambda: instante)
        recuperacion = {"guias_actualizadas": []}
        if por_reintentar:
            recuperacion = revalidar_ruta_sin_destino_calculado_sin_ocr(
                ruta_dataset=dataset, carpeta_catalogos=catalogos,
                proveedor_rutas=proveedor_rutas,
                proveedor_rutas_fallback=proveedor_rutas_fallback,
                guias_objetivo=set(por_reintentar),
            )
        # Bloque CONVERGENCIA DE ESTADO -- causa raíz sistémica real (viaje
        # 0000355433, guías 472623/472624): esta reconciliación (y también
        # `revalidar_y_regenerar_reporte`, la otra vía por la que un motivo
        # puede retirarse, p. ej. patente ya homologada) puede dejar
        # `motivos_revision_documento`/`estado_ruta` ya al día pero
        # `indicador_revision`/`estado_documental`/`estado_operacional`
        # desincronizados -- cada revalidación de motivo (arriba, y las que
        # corren fuera de este archivo) reimplementaba ese cálculo por su
        # cuenta, algunas de forma incompleta. Corre AL FINAL, una sola vez,
        # sobre el estado YA definitivo de esta pasada (después del retiro
        # de motivos Y del reintento de ruta) -- nunca decide si un motivo
        # sigue vigente, sólo hace que los tres campos deriven siempre de
        # esa misma fuente ya canónica.
        limpieza_indicadores = revalidar_indicadores_documentales_sin_ocr(ruta_dataset=dataset)
        # Mobile debe leer el indicador YA convergido en esta misma
        # pasada. Si corriera antes, una fila con motivos canónicos
        # resueltos pero `indicador_revision` todavía obsoleto seguiría
        # dejando el envío en REQUIERE_REVISION; como el reporte publica
        # después la huella fresca, podría no existir una segunda pasada
        # natural que lo corrigiera.
        limpieza_mobile = revalidar_asociacion_mobile_sin_ocr(
            RepositorioEnviosMobile(raiz_atlas=raiz), dataset=dataset,
        )
        # Bloque MOTOR DE EVIDENCIA -- causa raíz real (T2MN86/J35478,
        # 464529 alias TORRES OCARANEA): `reconciliar_bandeja_decisiones`
        # (catálogo + similitud OCR calibrada + historial RUT/transporte
        # para patentes; RUT exacto para alias; evidencia externa
        # oficial/corporativa para obras) existía completo y probado,
        # pero sólo se invocaba detrás de un camino de excepción manual
        # (`aplicar_decision_pendiente.py`, sólo tras
        # `DecisionObsoletaError`). Corre AL FINAL de esta pasada, sobre
        # el dataset YA reconciliado arriba (motivos/ruta/origen/mobile),
        # para que la evidencia que usa (p. ej. `estado_ruta` ya
        # `RUTA_CALCULADA`) sea la vigente. Nunca inventa ni relaja sus
        # propios umbrales -- reutiliza exactamente el mismo mecanismo ya
        # probado (Fases 1-4), incluida su auto-resolución acotada
        # (`MAX_ITERACIONES_AUTO_RESOLUCION`) para los tipos de decisión
        # donde la evidencia YA alcanza el nivel más alto sin ambigüedad.
        evidencia_decisiones = reconciliar_bandeja_decisiones(raiz_atlas=raiz, reloj=lambda: instante)
        # A partir de acá el dataset YA tiene los cambios de las
        # revalidaciones de arriba -- cada una es atómica y ya quedó
        # protegida por su propio lock común del dataset al escribir; NO
        # se revierten pase lo que pase con lo que sigue (son
        # revalidaciones canónicas, siempre seguras de conservar, igual
        # que cualquier otra corrida de `revalidar_y_regenerar_reporte`).
        try:
            filas_despues = {str(f.get("numero_guia", "")): f for f in _leer_filas(dataset)}
            guias_recuperadas = [
                guia for guia in por_reintentar
                if str(filas_despues.get(guia, {}).get("estado_ruta", "")) == "RUTA_CALCULADA"
            ]
            pendientes_despues = _pendientes_ruta(dataset, decisiones)
            registros_despues = []
            for fila in pendientes_despues:
                guia = str(fila.get("numero_guia", ""))
                registro = _registro_pendiente(fila, seguimiento_previo.get(guia))
                if guia in por_reintentar:
                    registro["intentos_misma_evidencia"] = int(registro["intentos_misma_evidencia"]) + 1
                    registro["ultimo_intento"] = instante.isoformat()
                    registro["ultimo_resultado"] = str(filas_despues[guia].get("motivo_ruta", "")) or "SIN_CAMBIO"
                    historial = list(registro["historial_resultados"])[-9:]
                    historial.append({"fecha": instante.isoformat(), "resultado": registro["ultimo_resultado"]})
                    registro["historial_resultados"] = historial
                registros_despues.append(registro)
            escribir_json_atomico(ruta_pendientes, {
                "schema_version": 1, "actualizado_en": instante.isoformat(),
                "pendientes": registros_despues,
            })

            # Bloque CONSISTENCIA OPERACIONAL, Sección 3 -- publicación
            # VERSIONADA: se captura la huella del dataset YA
            # RECONCILIADO (fresca, después de las revalidaciones de
            # arriba) justo ANTES de generar el reporte, y se vuelve a
            # comprobar justo DESPUÉS -- si algo más (una decisión
            # humana, un reproceso, otra revalidación) cambió el dataset
            # mientras `generar_reporte_viajes` corría, este reporte YA
            # NO corresponde al dataset vigente: nunca se publica como
            # `reporte_vigente` -- se descarta la carpeta recién creada
            # (huérfana, nunca "vigente") y se retorna sin publicar. El
            # próximo ciclo natural de reconciliación (ya se dispara en
            # cada carga de Desktop, idempotente) converge con el
            # dataset ya estable.
            huella_para_publicar = _sha256_archivo(dataset)
            manifest = generar_reporte_viajes(
                dataset, reporte, carpeta_catalogos=catalogos,
                ruta_ledger=actual / LEDGER, reloj=lambda: instante,
            )
            if _sha256_archivo(dataset) != huella_para_publicar:
                shutil.rmtree(reporte, ignore_errors=True)
                return {
                    "reconciliado": False, "motivo": "DATASET_AVANZO_DURANTE_RECONCILIACION",
                    "version": version_previa,
                    "guias_actualizadas": limpieza["guias_actualizadas"],
                    "guias_recuperadas": guias_recuperadas,
                    "pendientes_tecnicos": len(registros_despues),
                }
            escribir_estado_operacion(
                reporte_vigente=reporte,
                dataset_operacional=dataset,
                decisiones_pendientes=(decisiones if decisiones.is_file() else None),
                raiz=raiz,
                reloj=lambda: instante,
                origen="RECONCILIACION_ESTADO_DERIVADO",
                version_estado_derivado=VERSION_ESTADO_DERIVADO,
                dataset_sha256=huella_para_publicar,
            )
        except Exception:
            # Bloque CONSISTENCIA OPERACIONAL -- el dataset NUNCA se
            # restaura acá (Regla absoluta: sus cambios, si los hubo,
            # vienen de revalidaciones ya atómicas y protegidas por su
            # propio lock -- siempre seguras de conservar, nunca "un
            # snapshot viejo" que reponer). `estado_operacion.json`
            # tampoco necesita restaurarse: con la publicación versionada
            # de arriba, `escribir_estado_operacion` corre COMPLETO
            # (atómico) sólo al final, o no corre en absoluto -- un
            # fallo acá jamás lo deja a medio escribir ni lo pisa con
            # datos viejos. Sólo se limpia la carpeta de reporte a medio
            # generar, si llegó a crearse -- nunca queda huérfana como
            # "vigente".
            if reporte.exists():
                shutil.rmtree(reporte, ignore_errors=True)
            raise

    return {
        "reconciliado": True,
        "version": VERSION_ESTADO_DERIVADO,
        "respaldo": str(respaldo),
        "reporte_vigente": str(reporte),
        "guias_actualizadas": sorted(
            set(limpieza["guias_actualizadas"])
            | set(limpieza_material["guias_actualizadas"])
            | set(limpieza_origen["guias_actualizadas"])
            | set(limpieza_rut_chofer["rut_corregido_en_dataset"])
            | set(limpieza_indicadores["guias_actualizadas"])
        ),
        "guias_recuperadas": guias_recuperadas,
        "envios_mobile_actualizados": limpieza_mobile["actualizados"],
        "decisiones_aplicadas_automaticamente": evidencia_decisiones["decisiones_aplicadas_automaticamente"],
        "pendientes_tecnicos": len(registros_despues),
        "totales": manifest["totales"],
        "ocr_ejecutado": False,
        "reporte_regenerado_por_dataset_desactualizado": reporte_desactualizado,
    }
