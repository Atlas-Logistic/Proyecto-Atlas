"""Agrupación trazable y conservadora de documentos en viajes.

La agrupación usa ``numero_transporte`` como clave, pero nunca resuelve en
silencio contradicciones entre documentos. Los valores originales quedan en
``evidencias_documentos`` para permitir auditorías posteriores.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Callable, Iterable, Mapping
from uuid import NAMESPACE_URL, uuid5

from atlas_core.catalogos import normalizar_rut


_AUSENTES = {"", "no encontrado", "revisar", "ilegible"}
_PATRON_TRANSPORTE = re.compile(r"^\d+$")


def _valor_presente(valor: object) -> bool:
    texto = str(valor or "").strip()
    return bool(texto) and texto.casefold() not in _AUSENTES


def _clave_normalizada(valor: object) -> str:
    texto = " ".join(str(valor or "").strip().casefold().split())
    sin_acentos = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sin_acentos if not unicodedata.combining(c))


def _transporte_valido(valor: object) -> bool:
    texto = str(valor or "").strip()
    return _valor_presente(texto) and _PATRON_TRANSPORTE.fullmatch(texto) is not None


def _fecha_para_desktop(valor: object) -> str | None:
    texto = str(valor or "").strip()
    if not _valor_presente(texto):
        return None
    dmy = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", texto)
    iso = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", texto)
    if dmy:
        dia, mes, anio = map(int, dmy.groups())
    elif iso:
        anio, mes, dia = map(int, iso.groups())
    else:
        return None
    try:
        fecha = date(anio, mes, dia)
    except ValueError:
        return None
    return fecha.strftime("%d-%m-%Y")


def _valores_unicos(valores: Iterable[str]) -> list[str]:
    unicos: dict[str, str] = {}
    for valor in valores:
        if _valor_presente(valor):
            unicos.setdefault(_clave_normalizada(valor), str(valor).strip())
    return sorted(unicos.values(), key=_clave_normalizada)


def _valores_compatibles(valores: Iterable[str]) -> bool:
    return len({_clave_normalizada(v) for v in valores if _valor_presente(v)}) <= 1


def _valores_compatibles_rut(valores: Iterable[str]) -> bool:
    """Como `_valores_compatibles`, pero tolerante al formato de RUT
    (puntos, guion, mayúscula/minúscula del dígito verificador) mediante la
    misma normalización canónica que Atlas ya usa para corroborar RUT de
    chofer contra catálogo (`atlas_core.catalogos.normalizar_rut`). Sólo se
    usa para `rut_chofer` -- ningún otro campo de conflicto cambia.

    Si un valor no contiene ningún dígito ni "K" tras normalizar (no tiene
    forma de RUT -- p. ej. texto libre, un error de OCR sin dígitos), se
    compara por su forma literal (`_clave_normalizada`) en vez de por RUT
    normalizado, para no fusionar dos textos distintos que no son RUT en
    una igualdad artificial. Esto conserva exactamente el comportamiento
    previo para valores ausentes/inválidos/no parseables como RUT."""
    return len({
        normalizar_rut(v) or _clave_normalizada(v)
        for v in valores if _valor_presente(v)
    }) <= 1


def _documento_marca_revision(fila: Mapping[str, object]) -> bool:
    """True si el documento de origen ya viene marcado REVISAR
    (`indicador_revision`) por el pipeline de extracción/homologación —
    independiente de si contradice o no a otros documentos del viaje."""
    return str(fila.get("indicador_revision", "")).strip().casefold() == "revisar"


def _calcular_permanencia_minutos(hora_entrada: str, hora_salida: str) -> str:
    """Igual semántica que `procesamiento_masivo._calcular_permanencia_minutos`
    (duplicada a propósito para no acoplar este módulo a uno de nivel más
    bajo): permanencia en minutos entre dos horas "HH:MM", o "No
    determinada" si la salida es anterior a la entrada sin evidencia de
    cruce de medianoche."""
    try:
        hora_e, minuto_e = (int(x) for x in hora_entrada.split(":"))
        hora_s, minuto_s = (int(x) for x in hora_salida.split(":"))
    except (ValueError, AttributeError):
        return ""
    minutos_entrada = hora_e * 60 + minuto_e
    minutos_salida = hora_s * 60 + minuto_s
    if minutos_salida < minutos_entrada:
        return "No determinada"
    return str(minutos_salida - minutos_entrada)


def _peso_kg_numerico(valor: str) -> int | None:
    texto = str(valor or "").strip()
    return int(texto) if texto.isdigit() else None


class EstadoViaje(str, Enum):
    CONFIRMADO = "CONFIRMADO"
    REQUIERE_REVISION = "REQUIERE_REVISION"


class MotivoRevision(str, Enum):
    FECHA_NO_COMPATIBLE_DESKTOP = "FECHA_NO_COMPATIBLE_DESKTOP"
    CONFLICTO_FECHA = "CONFLICTO_FECHA"
    CONFLICTO_CHOFER = "CONFLICTO_CHOFER"
    CONFLICTO_RUT_CHOFER = "CONFLICTO_RUT_CHOFER"
    CONFLICTO_CLIENTE = "CONFLICTO_CLIENTE"
    CONFLICTO_OBRA_DESTINO = "CONFLICTO_OBRA_DESTINO"
    CONFLICTO_ORIGEN = "CONFLICTO_ORIGEN"
    CONFLICTO_PATENTE_TRACTO = "CONFLICTO_PATENTE_TRACTO"
    CONFLICTO_PATENTE_RAMPLA = "CONFLICTO_PATENTE_RAMPLA"
    DOCUMENTO_REQUIERE_REVISION = "DOCUMENTO_REQUIERE_REVISION"
    # Bloque O1: horas de planta que deberían referirse al mismo
    # ingreso/salida del camión cuando varias guías comparten transporte
    # -- si las horas válidas presentes difieren entre documentos, nunca
    # se elige una arbitrariamente.
    CONFLICTO_HORA_ENTRADA = "CONFLICTO_HORA_ENTRADA"
    CONFLICTO_HORA_SALIDA = "CONFLICTO_HORA_SALIDA"


@dataclass(frozen=True)
class DocumentoViaje:
    archivo: str
    numero_guia: str
    cliente: str
    obra_destino: str
    origen: str
    chofer: str
    chofer_original: str
    rut_chofer: str
    patente_tracto: str
    patente_rampla: str
    descripcion_material: str
    tipo_carga: str
    peso_kg: str
    hora_entrada_aza: str
    hora_salida_aza: str
    permanencia_minutos: str
    # Bloque E2E R1: enriquecimiento logístico por documento (planta origen
    # + DESPACHAR A + ORS). Igual criterio que peso/horas de Bloque O1: la
    # ausencia nunca invalida el documento ni el viaje.
    despachar_a_crudo: str
    direccion_entrega: str
    localidad_entrega: str
    region_entrega: str
    estado_entrega: str
    planta_origen_id: str
    planta_origen_nombre: str
    origen_determinado_por: str
    evidencia_origen: str
    distancia_km: str
    duracion_min: str
    proveedor_ruta: str
    estado_ruta: str
    motivo_ruta: str
    # Bloque TELEMETRÍA T2: enriquecimiento GPS opcional por documento.
    # Igual criterio -- la ausencia nunca invalida el documento ni el viaje.
    proveedor_telemetria: str
    estado_telemetria: str
    origen_gps: str
    planta_gps_id: str
    planta_gps_nombre: str
    hora_entrada_gps: str
    hora_salida_gps: str
    distancia_gps_km: str
    evidencia_telemetria: str
    # Bloque TELEMETRÍA T3: detención GPS real (Fase C) -- poblados solo
    # cuando `origen_gps == ORIGEN_GPS_ESTADIA_SIN_PLANTA`.
    motivo_origen_gps: str
    latitud_estadia_gps: str
    longitud_estadia_gps: str
    duracion_estadia_gps_min: str
    evidencia: dict[str, str]


@dataclass
class Viaje:
    viaje_id: str
    numero_transporte: str
    fecha: str
    documentos: list[DocumentoViaje] = field(default_factory=list)
    estado: EstadoViaje = EstadoViaje.CONFIRMADO
    motivos_revision: list[MotivoRevision] = field(default_factory=list)
    fecha_creacion: str = ""

    @property
    def numeros_guia(self) -> list[str]:
        return _valores_unicos(d.numero_guia for d in self.documentos)

    @property
    def clientes(self) -> list[str]:
        return _valores_unicos(d.cliente for d in self.documentos)

    @property
    def obras_destino(self) -> list[str]:
        return _valores_unicos(d.obra_destino for d in self.documentos)

    @property
    def origenes(self) -> list[str]:
        return _valores_unicos(d.origen for d in self.documentos)

    @property
    def choferes(self) -> list[str]:
        return _valores_unicos(d.chofer for d in self.documentos)

    @property
    def ruts_chofer(self) -> list[str]:
        return _valores_unicos(d.rut_chofer for d in self.documentos)

    @property
    def patentes_tracto(self) -> list[str]:
        return _valores_unicos(d.patente_tracto for d in self.documentos)

    @property
    def patentes_rampla(self) -> list[str]:
        return _valores_unicos(d.patente_rampla for d in self.documentos)

    @property
    def materiales(self) -> list[str]:
        return _valores_unicos(d.descripcion_material for d in self.documentos)

    @property
    def tipos_carga(self) -> list[str]:
        return _valores_unicos(d.tipo_carga for d in self.documentos)

    @property
    def peso_total_viaje_kg(self) -> str:
        """Bloque O1 -- suma de `peso_kg` de todos los documentos del
        viaje. Evidencia real (2 transportes multi-guía verificados
        contra la guía impresa): cada documento trae el peso PARCIAL de
        su propia línea de carga (materiales/códigos distintos, nunca el
        mismo peso repetido) -- sumarlos no duplica. Solo se calcula si
        TODOS los documentos del viaje tienen un `peso_kg` numérico
        válido; si falta en alguno, no puede demostrarse que la suma esté
        completa, así que se deja vacío en vez de sumar un subconjunto."""
        pesos = [_peso_kg_numerico(d.peso_kg) for d in self.documentos]
        if not pesos or any(peso is None for peso in pesos):
            return ""
        return str(sum(pesos))

    @property
    def hora_entrada_aza(self) -> str:
        """Consolidada solo si todas las horas de entrada válidas
        presentes coinciden (documentos sin dato no impiden consolidar) —
        nunca se elige una arbitrariamente ante conflicto."""
        valores = _valores_unicos(d.hora_entrada_aza for d in self.documentos)
        return valores[0] if len(valores) == 1 else ""

    @property
    def hora_salida_aza(self) -> str:
        valores = _valores_unicos(d.hora_salida_aza for d in self.documentos)
        return valores[0] if len(valores) == 1 else ""

    @property
    def permanencia_minutos(self) -> str:
        """Derivada de las horas ya consolidadas a nivel de viaje --
        nunca promedia las permanencias de los documentos individuales."""
        entrada, salida = self.hora_entrada_aza, self.hora_salida_aza
        if not entrada or not salida:
            return ""
        return _calcular_permanencia_minutos(entrada, salida)

    def _campo_ruta_consolidado(self, campo: str) -> str:
        """Bloque E2E R1 -- mismo criterio conservador que hora_entrada_aza/
        hora_salida_aza: un campo de enriquecimiento logístico (calculado
        por documento, no por viaje) solo se consolida al nivel de viaje si
        todos los documentos que lo informan coinciden. Documentos sin dato
        no impiden consolidar; ante conflicto real, nunca se elige uno
        arbitrariamente -- se deja vacío."""
        valores = _valores_unicos(getattr(d, campo) for d in self.documentos)
        return valores[0] if len(valores) == 1 else ""

    @property
    def despachar_a(self) -> str:
        return self._campo_ruta_consolidado("despachar_a_crudo")

    @property
    def direccion_entrega(self) -> str:
        return self._campo_ruta_consolidado("direccion_entrega")

    @property
    def localidad_entrega(self) -> str:
        return self._campo_ruta_consolidado("localidad_entrega")

    @property
    def region_entrega(self) -> str:
        return self._campo_ruta_consolidado("region_entrega")

    @property
    def estado_entrega(self) -> str:
        return self._campo_ruta_consolidado("estado_entrega")

    @property
    def planta_origen_id(self) -> str:
        return self._campo_ruta_consolidado("planta_origen_id")

    @property
    def planta_origen_nombre(self) -> str:
        return self._campo_ruta_consolidado("planta_origen_nombre")

    @property
    def origen_determinado_por(self) -> str:
        return self._campo_ruta_consolidado("origen_determinado_por")

    @property
    def evidencia_origen(self) -> str:
        return self._campo_ruta_consolidado("evidencia_origen")

    @property
    def distancia_km(self) -> str:
        return self._campo_ruta_consolidado("distancia_km")

    @property
    def duracion_min(self) -> str:
        return self._campo_ruta_consolidado("duracion_min")

    @property
    def proveedor_ruta(self) -> str:
        return self._campo_ruta_consolidado("proveedor_ruta")

    @property
    def estado_ruta(self) -> str:
        return self._campo_ruta_consolidado("estado_ruta")

    @property
    def motivo_ruta(self) -> str:
        return self._campo_ruta_consolidado("motivo_ruta")

    @property
    def proveedor_telemetria(self) -> str:
        return self._campo_ruta_consolidado("proveedor_telemetria")

    @property
    def estado_telemetria(self) -> str:
        return self._campo_ruta_consolidado("estado_telemetria")

    @property
    def origen_gps(self) -> str:
        return self._campo_ruta_consolidado("origen_gps")

    @property
    def planta_gps_id(self) -> str:
        return self._campo_ruta_consolidado("planta_gps_id")

    @property
    def planta_gps_nombre(self) -> str:
        return self._campo_ruta_consolidado("planta_gps_nombre")

    @property
    def hora_entrada_gps(self) -> str:
        return self._campo_ruta_consolidado("hora_entrada_gps")

    @property
    def hora_salida_gps(self) -> str:
        return self._campo_ruta_consolidado("hora_salida_gps")

    @property
    def distancia_gps_km(self) -> str:
        return self._campo_ruta_consolidado("distancia_gps_km")

    @property
    def evidencia_telemetria(self) -> str:
        return self._campo_ruta_consolidado("evidencia_telemetria")

    @property
    def motivo_origen_gps(self) -> str:
        return self._campo_ruta_consolidado("motivo_origen_gps")

    @property
    def latitud_estadia_gps(self) -> str:
        return self._campo_ruta_consolidado("latitud_estadia_gps")

    @property
    def longitud_estadia_gps(self) -> str:
        return self._campo_ruta_consolidado("longitud_estadia_gps")

    @property
    def duracion_estadia_gps_min(self) -> str:
        return self._campo_ruta_consolidado("duracion_estadia_gps_min")

    def a_dict(self) -> dict[str, object]:
        return {
            "viaje_id": self.viaje_id,
            "numero_transporte": self.numero_transporte,
            "fecha": self.fecha,
            "estado": self.estado.value,
            "motivos_revision": [m.value for m in self.motivos_revision],
            "documentos": [d.archivo for d in self.documentos],
            "numeros_guia": self.numeros_guia,
            "clientes": self.clientes,
            "obras_destino": self.obras_destino,
            "origenes": self.origenes,
            "choferes": self.choferes,
            "ruts_chofer": self.ruts_chofer,
            "patentes_tracto": self.patentes_tracto,
            "patentes_rampla": self.patentes_rampla,
            "materiales": self.materiales,
            "tipos_carga": self.tipos_carga,
            "peso_total_viaje_kg": self.peso_total_viaje_kg,
            "hora_entrada_aza": self.hora_entrada_aza,
            "hora_salida_aza": self.hora_salida_aza,
            "permanencia_minutos": self.permanencia_minutos,
            "despachar_a": self.despachar_a,
            "direccion_entrega": self.direccion_entrega,
            "localidad_entrega": self.localidad_entrega,
            "region_entrega": self.region_entrega,
            "estado_entrega": self.estado_entrega,
            "planta_origen_id": self.planta_origen_id,
            "planta_origen_nombre": self.planta_origen_nombre,
            "origen_determinado_por": self.origen_determinado_por,
            "evidencia_origen": self.evidencia_origen,
            "distancia_km": self.distancia_km,
            "duracion_min": self.duracion_min,
            "proveedor_ruta": self.proveedor_ruta,
            "estado_ruta": self.estado_ruta,
            "motivo_ruta": self.motivo_ruta,
            "proveedor_telemetria": self.proveedor_telemetria,
            "estado_telemetria": self.estado_telemetria,
            "origen_gps": self.origen_gps,
            "planta_gps_id": self.planta_gps_id,
            "planta_gps_nombre": self.planta_gps_nombre,
            "hora_entrada_gps": self.hora_entrada_gps,
            "hora_salida_gps": self.hora_salida_gps,
            "distancia_gps_km": self.distancia_gps_km,
            "evidencia_telemetria": self.evidencia_telemetria,
            "motivo_origen_gps": self.motivo_origen_gps,
            "latitud_estadia_gps": self.latitud_estadia_gps,
            "longitud_estadia_gps": self.longitud_estadia_gps,
            "duracion_estadia_gps_min": self.duracion_estadia_gps_min,
            "evidencias_documentos": [d.evidencia for d in self.documentos],
            "fecha_creacion": self.fecha_creacion,
        }


def _documento_desde_fila(
    fila: Mapping[str, object],
    *,
    normalizador_chofer: Callable[[str], str] | None,
) -> DocumentoViaje:
    evidencia = {str(clave): str(valor or "") for clave, valor in fila.items()}
    chofer_original = str(fila.get("chofer", "")).strip()
    chofer = (
        normalizador_chofer(chofer_original)
        if normalizador_chofer and _valor_presente(chofer_original)
        else chofer_original
    )
    origen = str(fila.get("origen", fila.get("planta_origen", "")))
    return DocumentoViaje(
        archivo=str(fila.get("archivo", "")).strip(),
        numero_guia=str(fila.get("numero_guia", "")).strip(),
        cliente=str(fila.get("cliente", "")).strip(),
        obra_destino=str(fila.get("obra_destino", "")).strip(),
        origen=origen.strip(),
        chofer=str(chofer).strip(),
        chofer_original=chofer_original,
        rut_chofer=str(fila.get("rut_chofer", "")).strip(),
        patente_tracto=str(fila.get("patente_tracto", "")).strip(),
        patente_rampla=str(fila.get("patente_rampla", "")).strip(),
        descripcion_material=str(fila.get("descripcion_material", "")).strip(),
        tipo_carga=str(fila.get("tipo_carga", "")).strip(),
        peso_kg=str(fila.get("peso_kg", "")).strip(),
        hora_entrada_aza=str(fila.get("hora_entrada_aza", "")).strip(),
        hora_salida_aza=str(fila.get("hora_salida_aza", "")).strip(),
        permanencia_minutos=str(fila.get("permanencia_minutos", "")).strip(),
        despachar_a_crudo=str(fila.get("despachar_a_crudo", "")).strip(),
        direccion_entrega=str(fila.get("direccion_entrega", "")).strip(),
        localidad_entrega=str(fila.get("localidad_entrega", "")).strip(),
        region_entrega=str(fila.get("region_entrega", "")).strip(),
        estado_entrega=str(fila.get("estado_entrega", "")).strip(),
        planta_origen_id=str(fila.get("planta_origen_id", "")).strip(),
        planta_origen_nombre=str(fila.get("planta_origen_nombre", "")).strip(),
        origen_determinado_por=str(fila.get("origen_determinado_por", "")).strip(),
        evidencia_origen=str(fila.get("evidencia_origen", "")).strip(),
        distancia_km=str(fila.get("distancia_km", "")).strip(),
        duracion_min=str(fila.get("duracion_min", "")).strip(),
        proveedor_ruta=str(fila.get("proveedor_ruta", "")).strip(),
        estado_ruta=str(fila.get("estado_ruta", "")).strip(),
        motivo_ruta=str(fila.get("motivo_ruta", "")).strip(),
        proveedor_telemetria=str(fila.get("proveedor_telemetria", "")).strip(),
        estado_telemetria=str(fila.get("estado_telemetria", "")).strip(),
        origen_gps=str(fila.get("origen_gps", "")).strip(),
        planta_gps_id=str(fila.get("planta_gps_id", "")).strip(),
        planta_gps_nombre=str(fila.get("planta_gps_nombre", "")).strip(),
        hora_entrada_gps=str(fila.get("hora_entrada_gps", "")).strip(),
        hora_salida_gps=str(fila.get("hora_salida_gps", "")).strip(),
        distancia_gps_km=str(fila.get("distancia_gps_km", "")).strip(),
        evidencia_telemetria=str(fila.get("evidencia_telemetria", "")).strip(),
        motivo_origen_gps=str(fila.get("motivo_origen_gps", "")).strip(),
        latitud_estadia_gps=str(fila.get("latitud_estadia_gps", "")).strip(),
        longitud_estadia_gps=str(fila.get("longitud_estadia_gps", "")).strip(),
        duracion_estadia_gps_min=str(fila.get("duracion_estadia_gps_min", "")).strip(),
        evidencia=evidencia,
    )


def _deduplicar_filas(
    filas: Iterable[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    """Evita duplicados exactos y fija un orden independiente de la entrada."""
    unicas: dict[tuple[tuple[str, str], ...], Mapping[str, object]] = {}
    for fila in filas:
        huella = tuple(
            sorted((str(k), str(v or "")) for k, v in fila.items())
        )
        unicas.setdefault(huella, fila)
    return [unicas[huella] for huella in sorted(unicas)]


def agrupar_viajes(
    filas: Iterable[Mapping[str, object]],
    *,
    normalizador_chofer: Callable[[str], str] | None = None,
    reloj: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    generador_id: Callable[[], str] | None = None,
) -> tuple[list[Viaje], list[dict[str, object]]]:
    """Agrupa por transporte y conserva toda contradicción como revisión."""
    grupos: dict[str, list[Mapping[str, object]]] = {}
    sin_transporte: list[dict[str, object]] = []

    for fila in _deduplicar_filas(filas):
        transporte = str(fila.get("numero_transporte", "")).strip()
        if not _transporte_valido(transporte):
            sin_transporte.append(dict(fila))
            continue
        grupos.setdefault(_clave_normalizada(transporte), []).append(fila)

    viajes: list[Viaje] = []
    ahora = reloj().isoformat()
    for clave_transporte, filas_grupo in grupos.items():
        documentos = [
            _documento_desde_fila(
                fila, normalizador_chofer=normalizador_chofer
            )
            for fila in filas_grupo
        ]
        fechas_originales = [str(f.get("fecha", "")).strip() for f in filas_grupo]
        fechas_desktop = [_fecha_para_desktop(valor) for valor in fechas_originales]
        campos_conflicto = (
            (MotivoRevision.CONFLICTO_FECHA, [valor or "" for valor in fechas_desktop], _valores_compatibles),
            (MotivoRevision.CONFLICTO_CHOFER, [d.chofer for d in documentos], _valores_compatibles),
            (MotivoRevision.CONFLICTO_RUT_CHOFER, [d.rut_chofer for d in documentos], _valores_compatibles_rut),
            (MotivoRevision.CONFLICTO_CLIENTE, [d.cliente for d in documentos], _valores_compatibles),
            (MotivoRevision.CONFLICTO_OBRA_DESTINO, [d.obra_destino for d in documentos], _valores_compatibles),
            (MotivoRevision.CONFLICTO_ORIGEN, [d.origen for d in documentos], _valores_compatibles),
            (MotivoRevision.CONFLICTO_PATENTE_TRACTO, [d.patente_tracto for d in documentos], _valores_compatibles),
            (MotivoRevision.CONFLICTO_PATENTE_RAMPLA, [d.patente_rampla for d in documentos], _valores_compatibles),
            (MotivoRevision.CONFLICTO_HORA_ENTRADA, [d.hora_entrada_aza for d in documentos], _valores_compatibles),
            (MotivoRevision.CONFLICTO_HORA_SALIDA, [d.hora_salida_aza for d in documentos], _valores_compatibles),
        )
        motivos = [
            motivo for motivo, valores, comparador in campos_conflicto
            if not comparador(valores)
        ]
        if any(
            _valor_presente(original) and normalizada is None
            for original, normalizada in zip(fechas_originales, fechas_desktop)
        ):
            motivos.append(MotivoRevision.FECHA_NO_COMPATIBLE_DESKTOP)
        # Un documento marcado REVISAR por el pipeline (campos ausentes,
        # recuperación geométrica, chofer no homologado, etc.) nunca puede
        # quedar CONFIRMADO en silencio a nivel de viaje, tenga o no
        # contradicciones con otros documentos del mismo transporte. Esto es
        # independiente y se suma a los conflictos ya detectados arriba.
        if any(_documento_marca_revision(fila) for fila in filas_grupo):
            motivos.append(MotivoRevision.DOCUMENTO_REQUIERE_REVISION)
        fecha = next((valor for valor in fechas_desktop if valor), "")
        identificador = (
            generador_id()
            if generador_id
            else str(uuid5(NAMESPACE_URL, f"atlas:viaje:{clave_transporte}"))
        )
        viajes.append(
            Viaje(
                viaje_id=identificador,
                numero_transporte=str(filas_grupo[0]["numero_transporte"]).strip(),
                fecha=fecha,
                documentos=documentos,
                estado=(
                    EstadoViaje.REQUIERE_REVISION
                    if motivos
                    else EstadoViaje.CONFIRMADO
                ),
                motivos_revision=motivos,
                fecha_creacion=ahora,
            )
        )
    return viajes, sin_transporte
