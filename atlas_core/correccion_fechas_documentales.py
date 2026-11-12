"""Corrección manual de las fechas de emisión y vencimiento de un documento ya
registrado en la ficha de un chofer o de un vehículo.

Reutiliza los dos almacenes del expediente digital, sin crear otro:
- `fichas_documentales.json` (licencias y documentos vehiculares de las fichas;
  las fechas son `emision` y `vencimiento`);
- `expediente_documentos.json` (documentos registrados en el expediente;
  `fecha_emision` y `fecha_vencimiento`).

Reglas:
- Sólo documentos vigentes en la ficha (no reemplazados, rechazados, anulados
  ni pendientes de extracción o de revisión: esos se completan en su propia
  revisión). El original, su huella y la lectura automática no cambian.
- Sólo se escriben las fechas que la persona cambió; las demás quedan igual.
- La vista previa (`previsualizar_correccion_fechas`, sólo lee) muestra los
  valores actuales, de dónde vienen, lo propuesto y la vigencia resultante, y
  entrega una `clave`. Guardar (`corregir_fechas_documento`) exige esa misma
  clave (nada cambió desde la vista previa), `confirmacion_humana=True` y autor.
- Cada corrección queda en el documento (`correcciones_fechas`, con antes y
  después), en el historial de la ficha o del expediente y, en las fichas,
  con respaldo del almacén. `fechas_confirmadas` guarda, por campo, el valor
  confirmado por una persona y la huella del original revisado.
- Un vencimiento leído por OCR y corregido por una persona deja de figurar
  como automático. Una corrección nunca se registra como lectura automática ni
  una lectura automática como confirmación humana. La lectura automática sólo
  actúa sobre documentos pendientes de extracción, que aquí no se corrigen:
  una fecha corregida no vuelve a ser sobrescrita por el OCR.
- La vigencia y las alertas se derivan siempre de las fechas guardadas.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico

CAMPOS = ("fecha_emision", "fecha_vencimiento")
# Nombre de cada campo en el almacén de fichas.
CAMPO_FICHA = {"fecha_emision": "emision", "fecha_vencimiento": "vencimiento"}
EXPEDIENTE, FICHA_CHOFER, FICHA_VEHICULO = "EXPEDIENTE", "FICHA_CHOFER", "FICHA_VEHICULO"
ESTADO_OCR_AUTOMATICO = "VENCIMIENTO_OCR_AUTOMATICO"
# Vencimiento leído por OCR y luego corregido por una persona (no vuelve a ser automático).
ESTADO_VENCIMIENTO_CORREGIDO = "VENCIMIENTO_CORREGIDO_HUMANO"
OPERACION = "FECHAS_DOCUMENTO_CORREGIDAS"
ORIGEN_OCR, ORIGEN_PERSONA, ORIGEN_REGISTRO, SIN_DATO = "OCR_AUTOMATICO", "CORRECCION_MANUAL", "REGISTRADO", "SIN_DATO"
_ANIO_MINIMO_EMISION, _ANIO_MINIMO_VENCIMIENTO, _ANIOS_FUTURO = 1950, 2000, 20
_Reloj = Callable[[], datetime]


class ErrorCorreccionFechas(ValueError):
    pass


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _autor(valor: object) -> str:
    texto = " ".join(str(valor or "").split())
    if not 2 <= len(texto) <= 80 or re.search(r"[\x00-\x1f\x7f]", texto):
        raise ErrorCorreccionFechas("Indique quién revisó el documento (2 a 80 caracteres)")
    return texto


def _motivo(valor: object) -> str:
    texto = " ".join(str(valor or "").split())
    if len(texto) > 300 or re.search(r"[\x00-\x1f\x7f]", texto):
        raise ErrorCorreccionFechas("El motivo admite hasta 300 caracteres")
    return texto


def _fecha(valor: object, nombre: str) -> str:
    texto = str(valor or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto):
        try:
            return date.fromisoformat(texto).isoformat()
        except ValueError:
            pass
    raise ErrorCorreccionFechas(f"La fecha de {nombre} no es válida (use AAAA-MM-DD)")


def _propuesta(propuesta: object) -> dict:
    """Sólo los campos indicados; una fecha vacía no borra la registrada."""
    if not isinstance(propuesta, dict):
        raise ErrorCorreccionFechas("Propuesta de fechas ilegible")
    desconocidos = set(propuesta) - set(CAMPOS)
    if desconocidos:
        raise ErrorCorreccionFechas("Sólo se corrigen la fecha de emisión y la de vencimiento")
    salida = {}
    for campo, nombre in (("fecha_emision", "emisión"), ("fecha_vencimiento", "vencimiento")):
        if str(propuesta.get(campo) or "").strip():
            salida[campo] = _fecha(propuesta[campo], nombre)
    return salida


# ------------------------------------------------------------------ ubicación del documento


def _empresa_fichas(raiz, empresa):
    from atlas_core.fichas_choferes import leer_almacen
    try:
        return leer_almacen(raiz, empresa=empresa)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ErrorCorreccionFechas(f"Fichas ilegibles: {error}") from error


def _en_fichas(raiz, fichas: dict | None, entidad: str, clave: str, equivalentes: list[str], documento_id: str,
               carpeta_catalogos) -> tuple[dict, dict] | None:
    """(contenedor con `historial`, documento) en el almacén de fichas, o None."""
    from atlas_core.expediente_digital import _carpeta, _indice_patentes
    if not fichas or fichas.get("version") != 2:
        return None
    if entidad == "CHOFER":
        for ficha in fichas.get("choferes", []):
            for doc in ficha.get("documentos", []):
                if doc.get("documento_id") == documento_id:
                    if not set(ficha.get("referencias_catalogo") or []) & set(equivalentes):
                        raise ErrorCorreccionFechas("El documento no pertenece a esta ficha")
                    return ficha, doc
        return None
    patentes = _indice_patentes(_carpeta(raiz, carpeta_catalogos))
    for ficha in fichas.get("vehiculos", []):
        for doc in ficha.get("documentos", []):
            if doc.get("documento_id") == documento_id:
                patente = str(ficha.get("patente", ""))
                if patentes.get(patente, patente) != clave:
                    raise ErrorCorreccionFechas("El documento no pertenece a esta ficha")
                return ficha, doc
    for doc in fichas.get("documentos_vehiculo_pendientes", []):
        if doc.get("documento_id") == documento_id:
            raise ErrorCorreccionFechas("El documento aún no está asignado a un vehículo; clasifíquelo primero en su revisión")
    return None


def _en_expediente(datos: dict, entidad: str, equivalentes: list[str], documento_id: str) -> dict | None:
    from atlas_core.expediente_digital import _buscar_expediente
    documento = next((d for d in datos["documentos"] if d.get("documento_id") == documento_id), None)
    if documento is None:
        return None
    expediente = _buscar_expediente(datos, entidad, equivalentes)
    if documento.get("entidad") != entidad or expediente is None or documento["expediente_id"] != expediente["expediente_id"]:
        raise ErrorCorreccionFechas("El documento no pertenece a esta ficha")
    return documento


def _corregible(fuente: str, documento: dict) -> None:
    from atlas_core.expediente_digital import ACTIVO
    if fuente == EXPEDIENTE:
        if documento.get("estado") != ACTIVO:
            raise ErrorCorreccionFechas("El documento ya no está vigente en la ficha (reemplazado o anulado)")
        if documento.get("pendiente_revision") or documento.get("transicion_programada"):
            raise ErrorCorreccionFechas("El documento está pendiente de revisión: complete sus datos en «Revisar»")
        return
    if documento.get("reemplazado_por"):
        raise ErrorCorreccionFechas("El documento fue reemplazado por otro; corrija el vigente")
    if documento.get("rechazo") or documento.get("estado_revision") == "RECHAZADO_EN_REVISION":
        raise ErrorCorreccionFechas("El documento fue rechazado en revisión")
    if documento.get("estado_revision") == "PENDIENTE_EXTRACCION" or documento.get("transicion_programada") \
            or documento.get("posible_reemplazo") or not documento.get("vencimiento"):
        raise ErrorCorreccionFechas("El documento está pendiente de extracción o de revisión: complete sus datos en su revisión")
    if documento.get("tipo") == "DOCUMENTO_VEHICULO_PENDIENTE":
        raise ErrorCorreccionFechas("El tipo del documento aún no está identificado; resuélvalo en su revisión")


def _valores(fuente: str, documento: dict) -> dict:
    if fuente == EXPEDIENTE:
        return {c: str(documento.get(c) or "") for c in CAMPOS}
    return {c: str(documento.get(CAMPO_FICHA[c]) or "") for c in CAMPOS}


def _confirmado(documento: dict, campo: str, valor: str) -> dict | None:
    """Confirmación humana vigente de ese campo: mismo valor y mismo original."""
    registro = (documento.get("fechas_confirmadas") or {}).get(campo) or {}
    if registro.get("valor") == valor and registro.get("sha256") == documento.get("sha256"):
        return registro
    return None


def _origenes(fuente: str, documento: dict, actuales: dict) -> dict:
    origen = {}
    for campo in CAMPOS:
        if not actuales[campo]:
            origen[campo] = SIN_DATO
        elif _confirmado(documento, campo, actuales[campo]):
            origen[campo] = ORIGEN_PERSONA
        elif campo == "fecha_vencimiento" and (
                documento.get("estado_revision") == ESTADO_OCR_AUTOMATICO
                or (fuente == EXPEDIENTE and documento.get("confirmado_por_humano") is False)):
            origen[campo] = ORIGEN_OCR
        else:
            origen[campo] = ORIGEN_REGISTRO
    return origen


def _leido_ocr(documento: dict) -> dict:
    """Lo que leyó la lectura automática del mismo original (sólo referencia)."""
    extraccion = documento.get("extraccion_automatica") or {}
    if extraccion.get("sha256") and extraccion.get("sha256") != documento.get("sha256"):
        return {}
    campos = extraccion.get("campos") or {}
    salida = {}
    for campo, nombre in (("fecha_emision", "emision"), ("fecha_vencimiento", "vencimiento")):
        leido = campos.get(nombre) or {}
        valor = leido.get("valor")
        if leido.get("estado") == "EXTRAIDO" and isinstance(valor, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor):
            salida[campo] = valor
    return salida


def _requiere_vencimiento(fuente: str, documento: dict, datos_expediente: dict | None) -> bool:
    if fuente != EXPEDIENTE:
        return True
    from atlas_core.expediente_digital import tipos_documento
    return tipos_documento(datos_expediente).get(documento.get("tipo"), {}).get("requiere_vencimiento", True)


def _evaluar(fuente: str, documento: dict, propuesta: dict, hoy: date, requiere_vencimiento: bool) -> dict:
    from atlas_core.expediente_digital import DIAS_POR_VENCER, _dias_para_vencer, estado_vencimiento
    actuales = _valores(fuente, documento)
    finales = {**actuales, **propuesta}
    cambios = {c: {"antes": actuales[c], "despues": finales[c]} for c in CAMPOS if finales[c] != actuales[c]}
    error = ""
    emision, vencimiento = finales["fecha_emision"], finales["fecha_vencimiento"]
    if "fecha_emision" in cambios and emision > hoy.isoformat():
        error = "La fecha de emisión no puede ser futura"
    elif "fecha_emision" in cambios and int(emision[:4]) < _ANIO_MINIMO_EMISION:
        error = "La fecha de emisión no es plausible; revise el año"
    elif "fecha_vencimiento" in cambios and not _ANIO_MINIMO_VENCIMIENTO <= int(vencimiento[:4]) <= hoy.year + _ANIOS_FUTURO:
        error = "La fecha de vencimiento no es plausible; revise el año"
    elif emision and vencimiento and emision > vencimiento:
        error = "La fecha de emisión es posterior al vencimiento"
    elif requiere_vencimiento and not vencimiento:
        error = "Indique la fecha de vencimiento"
    elif not cambios:
        error = "Sin cambios: las fechas indicadas son las registradas"
    vigencia = {momento: {"estado": estado_vencimiento(valor, hoy=hoy, dias_por_vencer=DIAS_POR_VENCER),
                          "dias_para_vencer": _dias_para_vencer(valor, hoy)}
                for momento, valor in (("antes", actuales["fecha_vencimiento"]), ("despues", vencimiento))}
    return {"actuales": actuales, "finales": finales, "cambios": cambios, "error": error, "vigencia": vigencia}


def _clave(fuente: str, documento: dict, propuesta: dict) -> str:
    contenido = {"fuente": fuente, "documento": documento, "propuesta": propuesta}
    return hashlib.sha256(json.dumps(contenido, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:32]


def _localizar(raiz, empresa, entidad, referencia, documento_id, carpeta_catalogos, fichas, datos_expediente):
    from atlas_core.expediente_digital import ErrorExpedienteDigital, _identidad
    entidad = str(entidad or "").upper()
    if entidad not in ("CHOFER", "VEHICULO"):
        raise ErrorCorreccionFechas("Entidad no válida")
    documento_id = str(documento_id or "")
    if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", documento_id):
        raise ErrorCorreccionFechas("Documento no válido")
    try:
        clave, equivalentes, _ = _identidad(raiz, empresa, entidad, referencia, carpeta_catalogos)
    except ErrorExpedienteDigital as error:
        raise ErrorCorreccionFechas(str(error)) from error
    hallado = _en_fichas(raiz, fichas, entidad, clave, equivalentes, documento_id, carpeta_catalogos)
    if hallado is not None:
        return (FICHA_CHOFER if entidad == "CHOFER" else FICHA_VEHICULO), hallado[0], hallado[1], entidad
    documento = _en_expediente(datos_expediente, entidad, equivalentes, documento_id)
    if documento is not None:
        return EXPEDIENTE, None, documento, entidad
    raise ErrorCorreccionFechas("El documento no existe en esta ficha; recargue la ficha")


# ------------------------------------------------------------------ vista previa (sólo lectura)


def previsualizar_correccion_fechas(raiz: str | Path, *, empresa: str, entidad: str, referencia: str, documento_id: str,
                                    propuesta: dict | None = None, reloj: _Reloj = _ahora,
                                    carpeta_catalogos: str | Path | None = None) -> dict:
    """Valores actuales, su origen, lo propuesto y la vigencia resultante. No escribe."""
    from atlas_core.expediente_digital import NOMBRE_ALMACEN, leer_expediente, tipos_documento
    hoy = reloj().astimezone(timezone.utc).date()
    propuesta = _propuesta(propuesta or {})
    fichas = _empresa_fichas(raiz, empresa)
    datos = leer_expediente(raiz, empresa=empresa)
    fuente, _, documento, entidad = _localizar(raiz, empresa, entidad, referencia, documento_id, carpeta_catalogos,
                                               fichas, datos)
    _corregible(fuente, documento)
    evaluacion = _evaluar(fuente, documento, propuesta, hoy, _requiere_vencimiento(fuente, documento, datos))
    nombres = tipos_documento(datos)
    return {
        "empresa": empresa, "almacen": NOMBRE_ALMACEN if fuente == EXPEDIENTE else "fichas_documentales.json",
        "documento": {"documento_id": documento["documento_id"], "tipo": documento.get("tipo", ""),
                      "nombre": nombres.get(documento.get("tipo"), {}).get("nombre", documento.get("tipo", "")),
                      "fuente": fuente, "entidad": entidad, "sha256": documento.get("sha256", ""),
                      "archivo": documento.get("archivo", "")},
        "actuales": evaluacion["actuales"], "origen": _origenes(fuente, documento, evaluacion["actuales"]),
        "leido_ocr": _leido_ocr(documento), "propuesta": propuesta, "cambios": evaluacion["cambios"],
        "vigencia": evaluacion["vigencia"], "correcciones_anteriores": len(documento.get("correcciones_fechas") or []),
        "error": evaluacion["error"], "puede_guardar": not evaluacion["error"],
        "clave": _clave(fuente, documento, propuesta),
    }


# ------------------------------------------------------------------ escritura


def _registro(documento: dict, cambios: dict, autor: str, motivo: str, actor: str, instante: str) -> dict:
    return {"autor": autor, "actor": actor, "fecha": instante, "sha256": documento.get("sha256", ""),
            "cambios": cambios, "motivo": motivo, "confirmacion_humana": True,
            "estado_revision_anterior": documento.get("estado_revision")}


def _marcar_confirmadas(documento: dict, cambios: dict, autor: str, actor: str, instante: str) -> None:
    confirmadas = dict(documento.get("fechas_confirmadas") or {})
    for campo, cambio in cambios.items():
        confirmadas[campo] = {"valor": cambio["despues"], "autor": autor, "actor": actor, "fecha": instante,
                              "sha256": documento.get("sha256", "")}
    documento["fechas_confirmadas"] = confirmadas


def _resultado(fuente: str, documento: dict, cambios: dict, revision: int, vigencia: dict, respaldo: str = "") -> dict:
    return {"ok": True, "modificado": True, "fuente": fuente, "documento_id": documento["documento_id"],
            "tipo": documento.get("tipo", ""), "cambios": cambios, "revision": revision,
            "fecha_emision": _valores(fuente, documento)["fecha_emision"],
            "fecha_vencimiento": _valores(fuente, documento)["fecha_vencimiento"],
            "vigencia": vigencia["despues"], **({"respaldo": respaldo} if respaldo else {})}


def corregir_fechas_documento(
    raiz: str | Path, *, empresa: str, entidad: str, referencia: str, documento_id: str, sha256: str,
    propuesta: dict, autor: str, confirmacion_humana: bool, clave: str, motivo: str = "", actor: str = "DESKTOP",
    reloj: _Reloj = _ahora, carpeta_catalogos: str | Path | None = None,
) -> dict:
    """Guarda las fechas que la persona revisó en la vista previa (misma `clave`)."""
    from atlas_core.desktop_operacion import sesion
    from atlas_core.expediente_digital import _actor
    if confirmacion_humana is not True:
        raise ErrorCorreccionFechas("Falta la confirmación de que una persona revisó el original")
    autor, motivo, actor = _autor(autor), _motivo(motivo), _actor(actor)
    propuesta = _propuesta(propuesta)
    if not re.fullmatch(r"[0-9a-f]{32}", str(clave or "")):
        raise ErrorCorreccionFechas("Revise la vista previa antes de guardar")
    with sesion(raiz, reutilizar=True) as comprobar:
        with bloqueo_sesion(Path(raiz) / "operacion" / "actual", "fichas_choferes_" + empresa):
            return _corregir_bajo_bloqueo(raiz, empresa, entidad, referencia, documento_id, sha256, propuesta, autor,
                                          motivo, actor, clave, reloj, carpeta_catalogos, comprobar)


def _corregir_bajo_bloqueo(raiz, empresa, entidad, referencia, documento_id, sha256, propuesta, autor, motivo, actor,
                           clave, reloj, carpeta_catalogos, comprobar):
    from atlas_core.expediente_digital import _mutacion, leer_expediente
    from atlas_core.fichas_choferes import _validar_v2, ruta_almacen
    from atlas_core.fichas_vehiculos import _validar_vehiculos
    hoy = reloj().astimezone(timezone.utc).date()
    instante = reloj().astimezone(timezone.utc).isoformat()
    anterior = _empresa_fichas(raiz, empresa)
    fuente, _, documento, entidad = _localizar(raiz, empresa, entidad, referencia, documento_id, carpeta_catalogos,
                                               anterior, leer_expediente(raiz, empresa=empresa))
    if fuente == EXPEDIENTE:
        with _mutacion(raiz, empresa) as datos:
            documento = _en_expediente(datos, entidad, _equivalentes(raiz, empresa, entidad, referencia, carpeta_catalogos),
                                       documento_id)
            _verificar(fuente, documento, sha256, propuesta, clave)
            evaluacion = _evaluar(fuente, documento, propuesta, hoy, _requiere_vencimiento(fuente, documento, datos))
            if evaluacion["error"]:
                raise ErrorCorreccionFechas(evaluacion["error"])
            cambios = evaluacion["cambios"]
            documento.setdefault("correcciones_fechas", []).append(
                _registro(documento, cambios, autor, motivo, actor, instante))
            _marcar_confirmadas(documento, cambios, autor, actor, instante)
            documento.update({c: v["despues"] for c, v in cambios.items()})
            if "fecha_vencimiento" in cambios and documento.get("confirmado_por_humano") is False:
                documento["confirmado_por_humano"] = True
            from atlas_core.expediente_digital import _evento
            _evento(datos, OPERACION, actor, instante, expediente_id=documento["expediente_id"],
                    documento_id=documento["documento_id"], tipo=documento.get("tipo", ""), autor=autor,
                    cambios=cambios, motivo=motivo)
            comprobar()
            revision = int(datos.get("revision", 0)) + 1
            resultado = dict(documento)
        return _resultado(fuente, resultado, cambios, revision, evaluacion["vigencia"])
    # Almacén de fichas: misma secuencia que las demás escrituras de fichas (respaldo + escritura atómica).
    propuesta_almacen = copy.deepcopy(anterior)
    _, contenedor, documento, _ = _localizar(raiz, empresa, entidad, referencia, documento_id, carpeta_catalogos,
                                             propuesta_almacen, {"documentos": [], "expedientes": []})
    _verificar(fuente, documento, sha256, propuesta, clave)
    evaluacion = _evaluar(fuente, documento, propuesta, hoy, True)
    if evaluacion["error"]:
        raise ErrorCorreccionFechas(evaluacion["error"])
    cambios = evaluacion["cambios"]
    estado_anterior = documento.get("estado_revision")
    documento.setdefault("correcciones_fechas", []).append(_registro(documento, cambios, autor, motivo, actor, instante))
    _marcar_confirmadas(documento, cambios, autor, actor, instante)
    documento.update({CAMPO_FICHA[c]: v["despues"] for c, v in cambios.items()})
    if "fecha_vencimiento" in cambios and estado_anterior == ESTADO_OCR_AUTOMATICO:
        documento["estado_revision"] = ESTADO_VENCIMIENTO_CORREGIDO
    contenedor.setdefault("historial", []).append({
        "accion": OPERACION, "actor": actor, "autor": autor, "fecha": instante, "documento_id": documento_id,
        "tipo": documento.get("tipo", ""), "cambios": cambios, "motivo": motivo,
        **({"estado_revision_anterior": estado_anterior, "estado_revision": documento["estado_revision"]}
           if documento.get("estado_revision") != estado_anterior else {}),
    })
    propuesta_almacen["revision"] = int(anterior["revision"]) + 1
    _validar_v2(propuesta_almacen)
    _validar_vehiculos(propuesta_almacen)
    ruta = ruta_almacen(raiz, empresa)
    respaldo = Path(raiz) / "respaldos" / "fichas_choferes" / uuid.uuid4().hex
    respaldo.mkdir(parents=True)
    shutil.copy2(ruta, respaldo / ruta.name)
    escribir_json_atomico(respaldo / "manifest.json", {
        "empresa": empresa, "actor": actor, "autor": autor, "operacion": OPERACION, "fuente": fuente,
        "documento_id": documento_id, "cambios": cambios, "revision_anterior": anterior["revision"],
        "ruta_relativa": str(ruta.relative_to(raiz)),
    })
    comprobar()
    escribir_json_atomico(ruta, propuesta_almacen)
    return _resultado(fuente, documento, cambios, propuesta_almacen["revision"], evaluacion["vigencia"], str(respaldo))


def _equivalentes(raiz, empresa, entidad, referencia, carpeta_catalogos) -> list[str]:
    from atlas_core.expediente_digital import _identidad
    return _identidad(raiz, empresa, str(entidad).upper(), referencia, carpeta_catalogos)[1]


def _verificar(fuente: str, documento: dict | None, sha256: str, propuesta: dict, clave: str) -> None:
    if documento is None:
        raise ErrorCorreccionFechas("El documento cambió desde la vista previa; vuelva a abrirla")
    _corregible(fuente, documento)
    if str(documento.get("sha256") or "") != str(sha256 or ""):
        raise ErrorCorreccionFechas("El documento cambió desde la vista previa; vuelva a abrirla")
    if _clave(fuente, documento, propuesta) != clave:
        raise ErrorCorreccionFechas("Las fechas registradas cambiaron desde la vista previa; vuelva a revisarlas")
