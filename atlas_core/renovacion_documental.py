"""Decisión única de renovación de documentos vehiculares (Mobile y Desktop).

Se evalúa sólo para un documento nuevo cuya lectura ya es confiable: tipo,
patente y vencimiento acreditados por OCR del mismo original y, si es póliza,
coberturas leídas con evidencia. Decide frente a los documentos operativos del
mismo vehículo (con vencimiento, no reemplazados ni pendientes):

- ACTIVAR: no hay anterior que acredite lo mismo.
- REEMPLAZAR: sustitución inequívoca (vínculo explícito verificable, o un único
  anterior relacionado), con cobertura igual o mayor y vencimiento posterior.
- PROGRAMAR: igual que REEMPLAZAR, pero la vigencia acreditada del nuevo aún no
  comienza: el anterior se conserva hasta esa fecha.
- PENDIENTE: ambigüedad; se conservan ambos y el nuevo nunca se activa solo,
  ni siquiera cuando el anterior vence.

Pura: no lee ni escribe almacenes.
"""
from __future__ import annotations

from datetime import date

TIPOS_POLIZA = frozenset({"POLIZA_RESPONSABILIDAD_CIVIL", "POLIZA_ROBO"})
ACTIVAR, REEMPLAZAR, PROGRAMAR, PENDIENTE = "ACTIVAR", "REEMPLAZAR", "PROGRAMAR", "PENDIENTE"


def _fecha(valor) -> date | None:
    try:
        return date.fromisoformat(str(valor or ""))
    except ValueError:
        return None


def tipos_acreditados(documento: dict) -> frozenset[str]:
    """Requisitos que acredita: una póliza por sus coberturas leídas; sin ellas, por su propio tipo."""
    tipo = documento.get("tipo")
    coberturas = [c for c in documento.get("coberturas") or [] if c in TIPOS_POLIZA]
    return frozenset(coberturas) if tipo in TIPOS_POLIZA and coberturas else frozenset({tipo})


def inicio_acreditado(campo_vencimiento: dict | None) -> str:
    """Comienzo de vigencia leído junto al vencimiento (par «desde/hasta» del mismo original)."""
    campo = (campo_vencimiento or {}).get("inicio_vigencia")
    if campo is not None:
        return campo.get("valor") or "" if campo.get("estado") == "EXTRAIDO" else ""
    for evidencia in (campo_vencimiento or {}).get("evidencia") or []:
        if isinstance(evidencia, dict) and _fecha(evidencia.get("par_desde")):
            return evidencia["par_desde"]
    return ""


def decidir_renovacion(nuevo: dict, anteriores: list[dict], hoy: date) -> dict:
    """`nuevo`: tipo, tipo_informado, vencimiento, inicio, coberturas, reemplaza (origen explícito o "").
    `anteriores`: documento_id, tipo, vencimiento, coberturas, origenes."""
    tipos = tipos_acreditados(nuevo)
    relacionados = [a for a in anteriores if tipos & tipos_acreditados(a)]

    def resultado(accion, motivo="", documentos=(), fecha=""):
        return {"accion": accion, "motivo": motivo, "documentos": [d["documento_id"] for d in documentos], "fecha": fecha}

    inicio = _fecha(nuevo.get("inicio"))
    estado_inicio = nuevo.get("estado_inicio") or {}
    if estado_inicio.get("motivo") not in (None, "", "NO_ENCONTRADO"):
        return resultado(PENDIENTE, "INICIO_AMBIGUO", relacionados)
    if inicio and _fecha(nuevo.get("vencimiento")) and inicio >= _fecha(nuevo.get("vencimiento")):
        return resultado(PENDIENTE, "FECHAS_CONTRADICTORIAS", relacionados)
    if not relacionados and not nuevo.get("reemplaza") and inicio and inicio > hoy:
        return resultado(PROGRAMAR, "VIGENCIA_FUTURA", fecha=inicio.isoformat())

    if nuevo.get("reemplaza"):
        # Vínculo explícito: debe resolver exactamente un documento operativo relacionado del mismo vehículo.
        elegidos = [a for a in anteriores if nuevo["reemplaza"] in (a.get("origenes") or [])]
        if len(elegidos) != 1 or elegidos[0] not in relacionados:
            return resultado(PENDIENTE, "VINCULO_NO_VERIFICABLE", elegidos or relacionados)
        objetivo = elegidos[0]
    else:
        informado = nuevo.get("tipo_informado")
        vigentes = [a for a in relacionados if (_fecha(a.get("vencimiento")) or date.min) >= hoy]
        if informado and informado != nuevo.get("tipo") and vigentes:
            return resultado(PENDIENTE, "TIPO_LEIDO_CON_VIGENTE", vigentes)
        if not relacionados:
            return resultado(ACTIVAR)
        if len(relacionados) > 1:
            return resultado(PENDIENTE, "VARIOS_ANTERIORES", relacionados)
        objetivo = relacionados[0]
    if objetivo.get("tipo") in TIPOS_POLIZA and not objetivo.get("coberturas"):
        return resultado(PENDIENTE, "COBERTURAS_ANTERIORES_NO_ACREDITADAS", [objetivo])
    if not tipos_acreditados(objetivo) <= tipos:
        # Nunca se retira una cobertura (RC o robo) que el nuevo no acredita.
        return resultado(PENDIENTE, "COBERTURAS_REDUCIDAS", [objetivo])
    nuevo_vence, anterior_vence = _fecha(nuevo.get("vencimiento")), _fecha(objetivo.get("vencimiento"))
    if not nuevo_vence or not anterior_vence or nuevo_vence <= anterior_vence:
        return resultado(PENDIENTE, "VENCIMIENTO_NO_POSTERIOR", [objetivo])
    inicio = _fecha(nuevo.get("inicio"))
    if inicio and inicio > hoy:
        return resultado(PROGRAMAR, "VIGENCIA_FUTURA", [objetivo], inicio.isoformat())
    return resultado(REEMPLAZAR, "", [objetivo])
