"""Recálculo explícito y acotado de rutas hacia una planta confirmada.

Casos reales 477043, 477449, 477355.jpeg y 488100 (AZA COLINA). Sus rutas se
derivaron antes de que el Motor reconociera la planta como destino:
- tres quedaron con RUTA_CALCULADA hacia el centro de Colina (28,3 km);
- 488100 tiene un destino operacional confirmado por Javier, con la ruta
  pendiente congelada en esa decisión.

La reconciliación ordinaria nunca vuelve a tocar una ruta ya calculada ni la
ruta de un destino humano. Este módulo lo permite sólo para los documentos
pedidos explícitamente, identificados por `archivo` (nunca sólo por número),
y sólo cuando:
- el documento es único en el dataset;
- su planta de origen sigue en el catálogo;
- las únicas decisiones humanas sobre él son su destino operacional vigente
  (sin "conservar estado") o correcciones de peso/material, que no afectan
  la ruta (cualquier otra decisión: abstención);
- el destino vigente (documental o el confirmado por el humano) es
  inequívocamente una planta confirmada (`planta_conocida_como_destino`),
  o bien -- sólo para el destino confirmado por el humano -- un destino
  CONFIRMADO del catálogo con coordenadas coherentes
  (`destino_operacional.ubicacion_destino_catalogo`; casos reales
  492111/483526 VISTA CLARA 2351, CERRILLOS, cuya ruta quedó pendiente
  porque se geocodificó el texto en vez de usar el destino conocido);
- el proveedor real calcula la ruta hasta el punto de ruteo de esa planta
  o hasta esas coordenadas (nunca se geocodifica en este módulo).

Nunca modifica el ledger ni crea decisiones. En un documento con destino
humano, la ruta queda en `metricas_procesamiento_json` ligada al
`decision_id`, la dirección y la comuna de esa decisión, y la proyección
(`destino_operacional.proyectar_destino`) la publica sólo mientras esa
decisión siga vigente. Toda escritura deja la ruta anterior en la auditoría.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

CLAVE_AUDITORIA = "recalculo_ruta_planta_conocida"
METODO_COMPROBACION_CONFIRMACION = "COMPROBACION_DESTINO_CONSERVADO"
CLAVE_RUTA_OPERACIONAL = "ruta_operacional_recalculada"
_CAMPOS_HUMANOS_SIN_EFECTO_EN_RUTA = frozenset({"peso_kg", "descripcion_material"})
_CAMPOS_RUTA_FILA = (
    "direccion_entrega", "localidad_entrega", "region_entrega", "estado_entrega",
    "codigo_pais", "codigo_unidad", "codigo_contexto",
    "distancia_km", "duracion_min", "proveedor_ruta", "estado_ruta", "motivo_ruta", "estado_operacional",
)


def _metricas(fila: Mapping[str, object]) -> dict:
    try:
        valor = json.loads(str(fila.get("metricas_procesamiento_json") or "") or "{}")
    except ValueError:
        return {}
    return valor if isinstance(valor, dict) else {}


def ruta_operacional_recalculada(fila: Mapping[str, object], *, decision_id: str, direccion: str,
                                 comuna: str) -> dict | None:
    """Ruta recalculada para EXACTAMENTE esta decisión humana de destino, o
    `None` (otra decisión, otra dirección/comuna, o sin recálculo)."""
    registro = _metricas(fila).get(CLAVE_RUTA_OPERACIONAL)
    if not isinstance(registro, Mapping) or not decision_id:
        return None
    if (registro.get("decision_id"), registro.get("direccion"), registro.get("comuna")) != (
            decision_id, direccion, comuna):
        return None
    ruta = registro.get("ruta")
    return dict(ruta) if isinstance(ruta, Mapping) else None


def _entradas_del_documento(aplicaciones: list, fila: Mapping[str, object]) -> list[dict]:
    """Decisiones del ledger que identifican a ESTE documento: por archivo, o
    por número de guía + transporte cuando el número es un folio real."""
    archivo = str(fila.get("archivo") or "").strip()
    guia = str(fila.get("numero_guia") or "").strip()
    transporte = str(fila.get("numero_transporte") or "").strip()
    salida = []
    for entrada in aplicaciones:
        if not isinstance(entrada, Mapping):
            continue
        doc = entrada.get("documento") if isinstance(entrada.get("documento"), Mapping) else {}
        mismo_archivo = bool(archivo) and str(doc.get("archivo") or "").strip() == archivo
        mismo_folio = (guia.isdigit() and str(doc.get("numero_guia") or "").strip() == guia
                       and str(doc.get("numero_transporte") or "").strip() == transporte)
        if mismo_archivo or mismo_folio:
            salida.append(dict(entrada))
    return salida


# Con el destino fijado por un humano, la ruta sólo depende de la planta de
# origen del documento (se lee la vigente) y de ese destino. Corregir
# cliente, patentes, chofer, folio u otros campos documentales no la cambia
# (casos reales 492059/485469/484396). Las decisiones sobre origen u otro
# destino sí: el recálculo se abstiene.
_CAMPOS_ORIGEN_O_DESTINO = frozenset({
    "planta_origen_id", "planta_origen_nombre", "despachar_a_crudo", "direccion_entrega", "localidad_entrega",
})
_TIPOS_SIN_EFECTO_EN_RUTA_DE_DESTINO_HUMANO = frozenset({"CHOFER_OPERACIONAL_DOCUMENTO"})


def _sin_efecto_en_ruta_de_destino_humano(entrada: Mapping[str, object]) -> bool:
    tipo = str(entrada.get("tipo") or "")
    if tipo in _TIPOS_SIN_EFECTO_EN_RUTA_DE_DESTINO_HUMANO:
        return True
    if tipo != "CORRECCION_DOCUMENTAL_OPERADOR":
        return False
    if entrada.get("accion") == "CORREGIR_NUMERO_GUIA":
        return True
    return (entrada.get("accion") == "CORREGIR_CAMPO"
            and str(entrada.get("campo") or "").strip() not in _CAMPOS_ORIGEN_O_DESTINO
            and bool(str(entrada.get("campo") or "").strip()))


def _destino_vigente(fila: Mapping[str, object], entradas: list[dict]) -> tuple[dict | None, str]:
    """(decisión de destino vigente o None, motivo de abstención o '')."""
    from atlas_core.destino_operacional import TIPO
    destinos = [e for e in entradas if str(e.get("tipo") or "") == TIPO]
    destino = destinos[-1] if destinos else None  # el ledger es cronológico: gana la última
    for entrada in entradas:
        tipo = str(entrada.get("tipo") or "")
        if tipo == TIPO:
            continue
        if (tipo == "CORRECCION_DOCUMENTAL_OPERADOR" and entrada.get("accion") == "CORREGIR_CAMPO"
                and str(entrada.get("campo") or "") in _CAMPOS_HUMANOS_SIN_EFECTO_EN_RUTA):
            continue
        if destino is not None and _sin_efecto_en_ruta_de_destino_humano(entrada):
            continue
        return None, f"DECISION_HUMANA_AFECTA_RUTA:{tipo or 'DESCONOCIDA'}"
    if destino is not None:
        valor = destino.get("destino_operacional") or {}
        if not (str(valor.get("direccion") or "").strip() and str(valor.get("comuna") or "").strip()
                and str(destino.get("decision_id") or "").strip()):
            return None, "DESTINO_HUMANO_INCOMPLETO"
    return destino, ""


def _huella_ruta(fila: Mapping[str, object]) -> tuple:
    return tuple(str(fila.get(c) or "") for c in (*_CAMPOS_RUTA_FILA, "planta_origen_id", "despachar_a_crudo"))


def recalcular_rutas_hacia_planta_conocida(
    *, raiz_atlas: str | Path, archivos: Iterable[str], proveedor_rutas=None,
    reloj=lambda: datetime.now(timezone.utc),
) -> dict[str, object]:
    """Recalcula, con el proveedor real, la ruta de cada documento pedido
    que cumpla las condiciones del módulo. Devuelve recalculadas (con ruta
    anterior y nueva), abstenciones (con motivo) y guías actualizadas."""
    from atlas_core.almacenamiento_portable import bloqueo_sesion
    from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
    from atlas_core.catalogo_plantas import CatalogoPlantas
    from atlas_core.destino_operacional import (
        calcular_ruta_operacional, ruta_hacia_ubicacion, ruta_valida,
        ubicacion_destino_catalogo,
    )
    from atlas_core.revalidacion_documental import (
        _escribir_filas_completas, _leer_filas, _proveedor_rutas_ors_predeterminado,
    )
    from atlas_core.rutas.destino_entrega import (
        METODO_PLANTA_CONOCIDA_CATALOGO, calcular_ruta_con_planta_conocida, planta_conocida_como_destino,
    )

    raiz = Path(raiz_atlas)
    actual = raiz / "operacion" / "actual"
    dataset = actual / "analisis_completo_guias.csv"
    carpeta = raiz / "catalogos_privados"
    pedidos = list(dict.fromkeys(str(a).strip() for a in archivos if str(a).strip()))
    resultado: dict[str, object] = {"recalculadas": [], "abstenciones": [], "guias_actualizadas": []}
    if not pedidos:
        return resultado
    plantas = CatalogoPlantas(carpeta / "plantas.json").listar()
    plantas_por_id = {p.planta_id: p for p in plantas}
    from atlas_core.identidad_destino import IndiceIdentidadDestinos
    indice_destinos = IndiceIdentidadDestinos.desde_carpeta(carpeta)
    try:
        confirmados = [d for d in CatalogoDestinos(carpeta / "destinos_maestros.json",
                                                   ruta_clientes=carpeta / "clientes.json").listar()
                       if d.estado_calidad == EstadoCalidadDestino.CONFIRMADO.value]
    except (OSError, ValueError):
        confirmados = []

    def leer_ledger() -> list:
        ruta = actual / "decisiones_aplicadas.json"
        if not ruta.is_file():
            return []
        aplicaciones = json.loads(ruta.read_text(encoding="utf-8")).get("aplicaciones", [])
        if not isinstance(aplicaciones, list):
            raise ValueError("Ledger de decisiones sin aplicaciones validas")
        return aplicaciones

    def abstener(archivo: str, motivo: str) -> None:
        resultado["abstenciones"].append({"archivo": archivo, "motivo": motivo})

    def preparar(filas: list[dict], aplicaciones: list, archivo: str):
        coincidentes = [f for f in filas if str(f.get("archivo") or "").strip() == archivo]
        if len(coincidentes) != 1:
            return None, f"DOCUMENTO_NO_UNICO:{len(coincidentes)}"
        fila = coincidentes[0]
        if not str(fila.get("numero_guia") or "").strip():
            return None, "DOCUMENTO_SIN_NUMERO"
        origen = plantas_por_id.get(str(fila.get("planta_origen_id") or "").strip())
        if origen is None:
            return None, "PLANTA_ORIGEN_DESCONOCIDA"
        decision, motivo = _destino_vigente(fila, _entradas_del_documento(aplicaciones, fila))
        if motivo:
            return None, motivo
        if decision is not None:
            valor = decision["destino_operacional"]
            texto, comuna = str(valor["direccion"]).strip(), str(valor["comuna"]).strip()
        else:
            texto, comuna = str(fila.get("despachar_a_crudo") or "").strip(), ""
        planta = planta_conocida_como_destino(texto, plantas, comuna_confirmada_humano=comuna,
                                              planta_origen_id=origen.planta_id)
        ubicacion = None
        if planta is None and decision is not None:
            puntos = indice_destinos.puntos_confirmados(texto, comuna)
            if puntos is not None and len(puntos) > 1:
                # Caso real 485242 (SANTA ISABEL 585, LAMPA): el catálogo
                # confirma dos puntos distintos para la misma dirección.
                # Nunca se elige uno ni se geocodifica para desempatar.
                return None, "DESTINO_CATALOGO_AMBIGUO"
            ubicacion = ubicacion_destino_catalogo(texto, comuna, carpeta_catalogos=carpeta)
            if ubicacion is None and decision.get("conservar_estado_operacional"):
                # "Conservar estado": la ruta de la dirección confirmada
                # nunca se calculó (quedó "requiere comprobación"). Se hace
                # aquí el MISMO cálculo de la confirmación, con la comuna
                # confirmada como control (casos reales 492036/492059).
                ubicacion = {"metodo_ubicacion": METODO_COMPROBACION_CONFIRMACION}
        if planta is None and ubicacion is None:
            return None, "DESTINO_NO_ES_PLANTA_CONOCIDA_INEQUIVOCA"
        return (fila, origen, decision, texto, comuna, planta, ubicacion), ""

    def destino_de(planta, ubicacion) -> str:
        if planta is not None:
            return planta.planta_id
        return str(ubicacion.get("destino_id") or ubicacion["metodo_ubicacion"])

    try:
        filas = _leer_filas(dataset, completas=True)
        aplicaciones = leer_ledger()
    except (OSError, ValueError) as error:
        resultado["abstenciones"] = [{"archivo": a, "motivo": f"LECTURA_FALLIDA:{type(error).__name__}"}
                                     for a in pedidos]
        return resultado
    proveedor_pedido = proveedor_rutas
    if proveedor_rutas is None:
        proveedor_rutas = _proveedor_rutas_ors_predeterminado(raiz_atlas=raiz)

    # 1) Cálculo con el proveedor real, fuera del lock del dataset.
    calculadas: dict[str, dict] = {}
    for archivo in pedidos:
        preparado, motivo = preparar(filas, aplicaciones, archivo)
        if motivo:
            abstener(archivo, motivo)
            continue
        fila, origen, decision, texto, comuna, planta, ubicacion = preparado
        if planta is None:
            if ubicacion.get("metodo_ubicacion") == METODO_COMPROBACION_CONFIRMACION:
                ruta_humana = calcular_ruta_operacional(
                    fila, texto, comuna, carpeta_catalogos=carpeta, proveedor_rutas=proveedor_pedido,
                    proveedor_rutas_fallback=proveedor_pedido)
                ruta_humana = {**ruta_humana, "metodo_ubicacion": ruta_humana.get(
                    "metodo_ubicacion") or METODO_COMPROBACION_CONFIRMACION}
            else:
                # Destino humano conocido en el catálogo: sólo el recorrido
                # desde la planta del documento hasta sus coordenadas.
                ruta_humana = ruta_hacia_ubicacion(origen.planta_id, comuna, ubicacion, carpeta_catalogos=carpeta,
                                                   proveedor_rutas=proveedor_rutas)
            if not ruta_valida(ruta_humana, comuna):
                abstener(archivo, f"RUTA_NO_CALCULADA:{ruta_humana.get('motivo') or ruta_humana.get('estado_ruta')}")
                continue
            calculadas[archivo] = {"ruta_humana": ruta_humana, "planta": None, "ubicacion": ubicacion,
                                   "destino": destino_de(None, ubicacion), "huella": _huella_ruta(fila),
                                   "decision_id": str(decision.get("decision_id") or ""),
                                   "texto": texto, "comuna": comuna}
            continue
        ruta = calcular_ruta_con_planta_conocida(
            planta=origen, despachar_a_crudo=texto, proveedor_rutas=proveedor_rutas,
            origen_determinado_por=str(fila.get("origen_determinado_por") or ""),
            evidencia_origen=str(fila.get("evidencia_origen") or ""),
            destinos_confirmados=confirmados, comuna_territorial_conocida=comuna,
            comuna_confirmada_humano=comuna, plantas_conocidas=plantas,
        )
        if ruta.metodo_confirmacion_destino != METODO_PLANTA_CONOCIDA_CATALOGO:
            abstener(archivo, f"DESTINO_RESUELTO_POR_OTRA_VIA:{ruta.metodo_confirmacion_destino or 'NINGUNA'}")
            continue
        if ruta.estado_ruta != "RUTA_CALCULADA" or not str(ruta.distancia_km or "").strip():
            abstener(archivo, f"RUTA_NO_CALCULADA:{ruta.motivo_ruta or ruta.estado_ruta}")
            continue
        calculadas[archivo] = {"ruta": ruta, "planta": planta, "destino": destino_de(planta, None),
                               "huella": _huella_ruta(fila),
                               "decision_id": str((decision or {}).get("decision_id") or ""),
                               "texto": texto, "comuna": comuna}

    if not calculadas:
        return resultado
    instante = reloj().astimezone(timezone.utc).isoformat()
    # 2) Escritura bajo el lock común del dataset, re-verificando todo.
    with bloqueo_sesion(actual, "revalidacion_dataset"):
        filas = _leer_filas(dataset, completas=True)
        aplicaciones = leer_ledger()
        cambios = False
        for archivo, calculo in calculadas.items():
            preparado, motivo = preparar(filas, aplicaciones, archivo)
            if motivo:
                abstener(archivo, f"CAMBIO_DURANTE_CALCULO:{motivo}")
                continue
            fila, origen, decision, texto, comuna, planta, ubicacion = preparado
            if (_huella_ruta(fila) != calculo["huella"] or destino_de(planta, ubicacion) != calculo["destino"]
                    or str((decision or {}).get("decision_id") or "") != calculo["decision_id"]):
                abstener(archivo, "CAMBIO_DURANTE_CALCULO")
                continue
            anterior = {c: str(fila.get(c) or "") for c in _CAMPOS_RUTA_FILA}
            metricas = _metricas(fila)
            if planta is None:
                ruta_humana = calculo["ruta_humana"]
            else:
                ruta = calculo["ruta"]
                nueva = {
                    "direccion_entrega": ruta.direccion_entrega_geocodificada,
                    "localidad_entrega": ruta.localidad_entrega, "region_entrega": ruta.region_entrega,
                    "codigo_pais": ruta.codigo_pais, "codigo_unidad": ruta.codigo_unidad,
                    "codigo_contexto": ruta.codigo_contexto,
                    "latitud_entrega": ruta.latitud_entrega, "longitud_entrega": ruta.longitud_entrega,
                    "distancia_km": ruta.distancia_km, "duracion_min": ruta.duracion_min,
                    "proveedor_ruta": ruta.proveedor_ruta, "estado_ruta": ruta.estado_ruta,
                }
                ruta_humana = {**{c: nueva[c] for c in (
                    "latitud_entrega", "longitud_entrega", "distancia_km", "duracion_min", "proveedor_ruta",
                    "estado_ruta", "region_entrega", "codigo_pais", "codigo_unidad", "codigo_contexto")},
                    "comuna": comuna, "planta_origen_id": origen.planta_id}
            if decision is not None:
                if not ruta_valida(ruta_humana, comuna):
                    abstener(archivo, "RUTA_NO_VALIDA_PARA_COMUNA_CONFIRMADA")
                    continue
                previa = ruta_operacional_recalculada(fila, decision_id=calculo["decision_id"],
                                                      direccion=texto, comuna=comuna)
                if previa == ruta_humana:
                    abstener(archivo, "SIN_CAMBIO")
                    continue
                metricas[CLAVE_RUTA_OPERACIONAL] = {
                    "decision_id": calculo["decision_id"], "direccion": texto, "comuna": comuna,
                    "ruta": ruta_humana, "calculado_en": instante,
                    **({"planta_destino_id": planta.planta_id} if planta is not None
                       else {"destino_id": ubicacion.get("destino_id", ""), "metodo": ubicacion["metodo_ubicacion"]}),
                }
                despues = ruta_humana
            else:
                if all(str(fila.get(c) or "") == str(nueva[c] or "") for c in (
                        "direccion_entrega", "distancia_km", "duracion_min", "estado_ruta")):
                    abstener(archivo, "SIN_CAMBIO")
                    continue
                for campo in ("direccion_entrega", "localidad_entrega", "region_entrega", "codigo_pais",
                              "codigo_unidad", "codigo_contexto", "distancia_km", "duracion_min",
                              "proveedor_ruta", "estado_ruta"):
                    fila[campo] = str(nueva[campo] or "")
                fila["motivo_ruta"] = ""
                fila["estado_entrega"] = "RESUELTO"
                # Misma regla que el reintento oficial de ruta: sólo un
                # documento sano sale de revisión; nunca se oculta otra causa.
                if (str(fila.get("indicador_revision", "")).strip() == "OK"
                        and str(fila.get("estado_documental", "")).strip() in ("", "OK")):
                    fila["estado_operacional"] = "OK"
                despues = {c: str(fila.get(c) or "") for c in _CAMPOS_RUTA_FILA}
            auditoria = metricas.get(CLAVE_AUDITORIA)
            auditoria = list(auditoria) if isinstance(auditoria, list) else []
            auditoria.append({
                "fecha": instante,
                **({"planta_destino_id": planta.planta_id, "planta_destino": planta.nombre,
                    "metodo": METODO_PLANTA_CONOCIDA_CATALOGO} if planta is not None
                   else {"destino_id": ubicacion.get("destino_id", ""), "metodo": ubicacion["metodo_ubicacion"]}),
                "decision_destino_id": calculo["decision_id"] or None,
                "ruta_anterior": anterior, "ruta_nueva": despues,
            })
            metricas[CLAVE_AUDITORIA] = auditoria
            fila["metricas_procesamiento_json"] = json.dumps(metricas, ensure_ascii=False)
            cambios = True
            guia = str(fila.get("numero_guia") or "").strip()
            resultado["guias_actualizadas"].append(guia)
            resultado["recalculadas"].append({"archivo": archivo, "numero_guia": guia,
                                              **({"planta_destino": planta.nombre} if planta is not None
                                                 else {"destino_id": ubicacion.get("destino_id", ""), "metodo": ubicacion["metodo_ubicacion"]}),
                                              "anterior": anterior,
                                              "nueva": despues,
                                              "decision_destino_id": calculo["decision_id"] or None})
        if cambios:
            _escribir_filas_completas(dataset, filas)
    return resultado
