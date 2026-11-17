"""Identidad de entrega acreditada por una decisi?n documental vigente.

S?lo lectura: no altera campos, ruta ni evidencia de la gu?a.
"""
from __future__ import annotations

from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, normalizar_nombre_obra
from atlas_core.catalogo_destinos import CatalogoDestinos


def identidades_confirmadas(filas, ledger, carpeta_catalogos):
    """Relaciona identidad documental exacta con una relaci?n humana activa.

    Ante decisiones posteriores de obra/destino, identidades duplicadas o
    cat?logos incompletos se abstiene. La correcci?n operacional propia se
    proyecta por su mecanismo habitual, que tiene precedencia.
    """
    from pathlib import Path
    raiz = Path(carpeta_catalogos)
    try:
        catalogo = CatalogoObrasDestinos(ruta=raiz / "obras_destinos.json",
            ruta_clientes=raiz / "clientes.json", ruta_destinos=raiz / "destinos_maestros.json")
        obras = {o.obra_id: o for o in catalogo.listar_obras()}
        relaciones = {r.relacion_id: r for r in catalogo.listar_relaciones()}
        destinos = CatalogoDestinos(raiz / "destinos_maestros.json")
    except (OSError, ValueError):
        return {}
    def identidad(doc):
        return tuple(str(doc.get(c) or "").strip() for c in ("archivo", "numero_guia", "numero_transporte"))
    conteos = {}
    for fila in filas:
        key = identidad(fila)
        conteos[key] = conteos.get(key, 0) + 1
    aplicaciones = ledger.get("aplicaciones", [])
    if not isinstance(aplicaciones, list):
        return {}
    resultado = {}
    for fila in filas:
        key = identidad(fila)
        if not all(key) or conteos[key] != 1:
            continue
        for e in reversed(aplicaciones):
            if not isinstance(e, dict) or not isinstance(e.get("documento"), dict) or identidad(e["documento"]) != key:
                continue
            tipo, accion = e.get("tipo"), e.get("accion")
            campo = str(e.get("campo") or "").lower()
            if tipo == "DESTINO_SIN_CONFIRMAR" and accion == "CONFIRMAR":
                obra = obras.get(e.get("obra_id"))
                relacion = relaciones.get(e.get("relacion_id"))
                try:
                    destino = destinos.obtener(e.get("destino_id"))
                except (OSError, ValueError, TypeError):
                    break
                decision_id = str(e.get("decision_id") or "")
                evidencia = bool(relacion and any(x.tipo == "GUIA" and x.identificador_fuente == key[1]
                    and x.referencia_hash == decision_id and x.resultado == "SOPORTA" for x in relacion.evidencias))
                if (obra and obra.estado == "CONFIRMADA" and obra.estado_vigencia == "ACTIVO"
                    and relacion and relacion.estado == "CONFIRMADA" and relacion.fuente_confirmacion == "CONFIRMACION_HUMANA"
                    and relacion.obra_id == obra.obra_id and relacion.destino_id == destino.destino_id
                    and obra.cliente_id == e.get("cliente_id") and evidencia and decision_id
                    and normalizar_nombre_obra(str(fila.get("obra_destino") or "")) in
                        {normalizar_nombre_obra(n) for n in (obra.nombre_canonico, *obra.aliases_documentales)}
                    and destino.estado_calidad == "CONFIRMADO" and destino.estado_vigencia == "ACTIVO"
                    and destino.direccion and destino.comuna
                    and str(e.get("valor_documental") or "").strip() == str(fila.get("despachar_a_crudo") or "").strip()):
                    resultado[key] = (destino.direccion, destino.comuna, obra.nombre_canonico)
                break
            if (tipo in {"DESTINO_OPERACIONAL_DOCUMENTO", "DESTINO_SIN_CONFIRMAR", "OBRA_DESCONOCIDA"}
                or campo in {"obra_destino", "despachar_a_crudo", "direccion_entrega", "localidad_entrega"}
                or "OBRA" in str(accion or "") or "DESTINO" in str(accion or "")):
                break
    return resultado
