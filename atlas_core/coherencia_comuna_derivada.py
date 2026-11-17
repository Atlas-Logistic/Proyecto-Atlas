"""Proyecta la comuna acreditada sin modificar la evidencia ni la ruta."""
from __future__ import annotations

import json
from pathlib import Path


def revalidar_comunas_confirmadas(*, ruta_dataset, carpeta_catalogos, guias_objetivo=None, aplicar=True):
    from atlas_core.almacenamiento_portable import bloqueo_sesion
    from atlas_core.alcance_revalidacion import guias_en_alcance
    from atlas_core.convergencia_destino_confirmado import _partes_direccion, resolver_destino_confirmado
    from atlas_core.geografia import EstadoNormalizacion, cargar_geografia
    from atlas_core.decisiones_pendientes import _actor_es_humano
    from atlas_core.rutas.destino_entrega import _comunas_explicitas
    from atlas_core.revalidacion_documental import _leer_filas, _escribir_filas_completas

    ruta = Path(ruta_dataset)
    try:
        ledger = json.loads((ruta.parent / "decisiones_aplicadas.json").read_text(encoding="utf-8-sig"))
        aplicaciones = ledger["aplicaciones"]
        if not isinstance(aplicaciones, list) or not all(isinstance(e, dict) for e in aplicaciones):
            raise ValueError("ledger invalido")
    except (OSError, ValueError, KeyError, TypeError):
        return {"guias_actualizadas": [], "abstencion": "LEDGER_ILEGIBLE"}
    alcance = guias_en_alcance(ruta)
    if alcance is not None:
        guias_objetivo = set(alcance) if guias_objetivo is None else set(guias_objetivo) & set(alcance)
    geo = cargar_geografia("CL")
    cache = {}
    actualizadas = []
    with bloqueo_sesion(ruta.parent, "revalidacion_dataset"):
        filas = _leer_filas(ruta)
        for fila in filas:
            guia = str(fila.get("numero_guia") or "").strip()
            archivo = str(fila.get("archivo") or "").strip()
            transporte = str(fila.get("numero_transporte") or "").strip()
            if not all((guia, archivo, transporte)) or (guias_objetivo is not None and guia not in guias_objetivo):
                continue
            direccion = str(fila.get("direccion_entrega") or "").strip()
            crudo = str(fila.get("despachar_a_crudo") or "").strip()
            comunas = _comunas_explicitas(direccion)
            if len(comunas) != 1 or not _partes_direccion(direccion) or _partes_direccion(direccion) != _partes_direccion(crudo):
                continue
            comuna = comunas[0]
            resultado = geo.normalizar(comuna, nivel=3)
            if resultado.estado != EstadoNormalizacion.EXACTA or resultado.unidad is None:
                continue
            if fila.get("localidad_entrega") == comuna and (not fila.get("codigo_unidad") or fila.get("codigo_unidad") == resultado.unidad.codigo):
                continue
            decision = None
            for e in reversed(aplicaciones):
                doc = e.get("documento")
                if not isinstance(doc, dict):
                    continue
                tipo, accion, campo = str(e.get("tipo") or ""), str(e.get("accion") or ""), str(e.get("campo") or "")
                if not (tipo.startswith("DESTINO_") or campo in {"direccion_entrega", "despachar_a_crudo", "localidad_entrega", "obra_destino"} or "DESTINO" in accion or "OBRA" in accion):
                    continue
                archivo_decision = str(doc.get("archivo") or "").strip()
                guia_decision = str(doc.get("numero_guia") or "").strip()
                if archivo_decision != archivo and guia_decision != guia:
                    continue
                # Una identidad parcial o contradictoria exige abstenerse.
                if (archivo_decision, guia_decision, str(doc.get("numero_transporte") or "").strip()) != (archivo, guia, transporte):
                    decision = False
                    break
                decision = e
                break
            respaldada = False
            if isinstance(decision, dict):
                if decision.get("tipo") == "DESTINO_NO_RESUELTO" and decision.get("accion") == "REGISTRAR_DIRECCION":
                    manual = str(decision.get("direccion_manual") or "").strip()
                    comuna_manual = str(decision.get("comuna_manual") or "").strip()
                    explicitas = _comunas_explicitas(manual)
                    manual_normalizada = geo.normalizar(comuna_manual, nivel=3) if comuna_manual else None
                    autor = str(decision.get("actor") or "").strip()
                    confirmante = str(decision.get("confirmado_por") or "").strip()
                    es_humana = bool(autor and _actor_es_humano(autor)) or bool(confirmante and _actor_es_humano(confirmante))
                    coincide = (manual.casefold() == crudo.casefold() and explicitas == (comuna,)
                        and (not comuna_manual or (manual_normalizada.estado == EstadoNormalizacion.EXACTA
                             and manual_normalizada.unidad and manual_normalizada.unidad.nombre_canonico == comuna)))
                    respaldada = es_humana and coincide
                    anteriores_humanas = any(
                        isinstance(e, dict) and isinstance(e.get("documento"), dict)
                        and (str(e["documento"].get("archivo") or "").strip() == archivo
                             or str(e["documento"].get("numero_guia") or "").strip() == guia)
                        and (str(e.get("tipo") or "").startswith("DESTINO_")
                             or str(e.get("campo") or "") in {"direccion_entrega", "despachar_a_crudo", "localidad_entrega", "obra_destino"})
                        and ((str(e.get("actor") or "").strip() and _actor_es_humano(e.get("actor")))
                             or (str(e.get("confirmado_por") or "").strip() and _actor_es_humano(e.get("confirmado_por"))))
                        for e in aplicaciones if e is not decision
                    )
                    if coincide and not es_humana and not anteriores_humanas:
                        # Un actor B1 no prueba por si solo confirmacion humana.
                        # El catalogo confirmado puede corroborar el destino sin
                        # atribuir esa decision automatica a una persona.
                        try:
                            resuelto = resolver_destino_confirmado(fila, carpeta_catalogos=carpeta_catalogos, _cache=cache)
                            territorial = geo.normalizar(resuelto[1].comuna, nivel=3) if resuelto else None
                            respaldada = bool(resuelto and _comunas_explicitas(resuelto[1].direccion) == (comuna,)
                                and territorial.estado == EstadoNormalizacion.EXACTA and territorial.unidad
                                and territorial.unidad.nombre_canonico == comuna)
                        except (OSError, ValueError, TypeError, AttributeError):
                            respaldada = False
            elif decision is None:
                try:
                    evidencia = json.loads(fila.get("metricas_procesamiento_json") or "{}").get("convergencia_destino_confirmado")
                    if isinstance(evidencia, dict) and evidencia.get("fuente") == "CLIENTE_RUT_OBRA_DIRECCION_CATALOGO_CONFIRMADO":
                        resuelto = resolver_destino_confirmado(fila, carpeta_catalogos=carpeta_catalogos, _cache=cache)
                        territorial = geo.normalizar(resuelto[1].comuna, nivel=3) if resuelto else None
                        respaldada = bool(resuelto and resuelto[1].destino_id == evidencia.get("destino_id")
                            and resuelto[0].obra_id == evidencia.get("obra_id")
                            and _comunas_explicitas(resuelto[1].direccion) == (comuna,)
                            and territorial.estado == EstadoNormalizacion.EXACTA and territorial.unidad is not None
                            and territorial.unidad.nombre_canonico == comuna)
                except (OSError, ValueError, TypeError, AttributeError):
                    continue
            if not respaldada:
                continue
            contexto = geo.parametros_geocodificacion(resultado.unidad)
            if str(fila.get("codigo_pais") or "").strip() not in ("", "CL") or str(fila.get("codigo_contexto") or "").strip() not in ("", contexto.codigo_contexto):
                continue
            fila["localidad_entrega"] = comuna
            if fila.get("codigo_unidad"):
                fila["codigo_unidad"] = resultado.unidad.codigo
            actualizadas.append(guia)
        if actualizadas and aplicar:
            _escribir_filas_completas(ruta, filas)
    return {"guias_actualizadas": actualizadas}
