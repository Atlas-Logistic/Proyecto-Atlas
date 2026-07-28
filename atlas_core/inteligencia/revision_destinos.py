"""Integración de destinos con el motor inteligente, sólo para revisión humana."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol

from atlas_core.inteligencia.modelos import Evidencia, TipoFuente
from atlas_core.inteligencia.motor import normalizar
from atlas_core.inteligencia.verificacion_destinos import (
    EstadoVerificacionDestino,
    RespuestaHTTPDestino,
    ResultadoVerificacionDestino,
    SolicitudVerificacionDestino,
    VerificadorDestinosOpenRouteService,
    resolver_destino_con_verificacion,
)


CAMPOS_AUTORIZABLES = frozenset({
    "direccion_original", "comuna_esperada", "region_esperada", "pais"
})
ACCIONES_PERMITIDAS = frozenset({
    "MANTENER", "REVISAR_DIRECCION", "REVISAR_NUMERACION", "REVISAR_COMUNA",
    "REVISAR_REGION", "EVALUAR_COORDENADAS",
    "REPETIR_CONSULTA_MANUALMENTE", "SIN_ACCION_AUTOMATICA",
})


class ErrorEntradaDestinos(ValueError):
    """Entrada ausente, vacía o con esquema incompatible."""


class ErrorConfiguracionRevision(ValueError):
    """Combinación insegura o incompleta de parámetros."""


class EstadoRevisionDestino(str, Enum):
    SIN_CAMBIOS = "SIN_CAMBIOS"
    CONFIRMACION_PROPUESTA = "CONFIRMACION_PROPUESTA"
    COORDENADAS_PROPUESTAS = "COORDENADAS_PROPUESTAS"
    COINCIDENCIA_PARCIAL = "COINCIDENCIA_PARCIAL"
    CONTRADICCION_DIRECCION = "CONTRADICCION_DIRECCION"
    CONTRADICCION_NUMERO = "CONTRADICCION_NUMERO"
    CONTRADICCION_COMUNA = "CONTRADICCION_COMUNA"
    CONTRADICCION_REGION = "CONTRADICCION_REGION"
    RESPUESTA_AMBIGUA = "RESPUESTA_AMBIGUA"
    SIN_RESULTADOS = "SIN_RESULTADOS"
    CONSULTA_NO_AUTORIZADA = "CONSULTA_NO_AUTORIZADA"
    ERROR_PROVEEDOR = "ERROR_PROVEEDOR"
    REQUIERE_REVISION = "REQUIERE_REVISION"


class DecisionHumanaDestino(str, Enum):
    CONFIRMAR_PROPUESTA = "CONFIRMAR_PROPUESTA"
    RECHAZAR_PROPUESTA = "RECHAZAR_PROPUESTA"
    CORREGIR_MANUALMENTE = "CORREGIR_MANUALMENTE"
    POSPONER = "POSPONER"
    MARCAR_NO_RECONOCIDO = "MARCAR_NO_RECONOCIDO"


@dataclass(frozen=True)
class DestinoEntrada:
    destino_id: str
    cliente_id: str
    direccion: str
    comuna: str
    region: str
    pais: str
    latitud: float | None
    longitud: float | None
    estado_actual: str
    autorizacion_consulta_externa: bool
    campos_autorizados: frozenset[str]
    registro_original: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "registro_original", MappingProxyType(dict(self.registro_original))
        )


@dataclass(frozen=True)
class RegistroRevisionDestino:
    destino_id: str
    cliente_id: str
    direccion_original: str
    comuna_original: str
    region_original: str
    coordenadas_originales: tuple[float, float] | None
    estado_original: str
    estado_revision: EstadoRevisionDestino
    direccion_externa: str
    comuna_externa: str
    region_externa: str
    coordenadas_externas: tuple[float, float] | None
    clasificacion_geografica: str
    propuesta: str
    confianza: str
    evidencias_favorables: tuple[str, ...]
    evidencias_contrarias: tuple[str, ...]
    contradicciones: tuple[str, ...]
    explicacion: tuple[str, ...]
    accion_recomendada: str
    fecha_evaluacion: datetime
    proveedor: str
    consulta_realizada: bool
    consulta_desde_cache: bool
    requiere_decision_humana: bool
    huella_del_registro_original: str

    def __post_init__(self) -> None:
        if self.accion_recomendada not in ACCIONES_PERMITIDAS:
            raise ValueError("Acción recomendada no permitida")


@dataclass(frozen=True)
class ConfiguracionRevisionDestinos:
    permitir_consultas: bool = False
    max_consultas: int = 0
    usar_cache: bool = True
    solo_cache: bool = False
    timeout: float = 8.0
    proveedor: str = "ninguno"

    def __post_init__(self) -> None:
        if self.max_consultas < 0 or self.timeout <= 0:
            raise ErrorConfiguracionRevision("Máximo y timeout deben ser válidos")
        if self.solo_cache and not self.usar_cache:
            raise ErrorConfiguracionRevision("--solo-cache requiere --usar-cache")
        if not self.permitir_consultas and self.max_consultas != 0:
            raise ErrorConfiguracionRevision(
                "Sin --permitir-consultas, --max-consultas debe ser 0"
            )


@dataclass(frozen=True)
class ResultadoLoteRevision:
    revisiones: tuple[RegistroRevisionDestino, ...]
    resumen: Mapping[str, Any]
    manifiesto: Mapping[str, Any]


class ProveedorRevision(Protocol):
    nombre: str
    consultas_externas: int

    def verificar(
        self, solicitud: SolicitudVerificacionDestino
    ) -> ResultadoVerificacionDestino: ...


class ProveedorRespuestasCongeladas:
    """Proveedor offline indexado por la consulta registrada por Pelias."""

    nombre = "openrouteservice-pelias-congelado"

    def __init__(self, ruta: str | Path) -> None:
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
        self._respuestas: dict[str, tuple[int, Mapping[str, Any]]] = {}
        for item in datos:
            cuerpo = item["cuerpo"]
            consulta = cuerpo.get("geocoding", {}).get("query", {}).get("text", "")
            if not consulta:
                raise ErrorEntradaDestinos("Respuesta congelada sin consulta original")
            self._respuestas[normalizar(consulta)] = (int(item["codigo_http"]), cuerpo)
        self.consultas_externas = 0

    def verificar(
        self, solicitud: SolicitudVerificacionDestino
    ) -> ResultadoVerificacionDestino:
        consulta = _consulta_de_solicitud(solicitud)
        congelada = self._respuestas.get(normalizar(consulta))
        if congelada is None:
            return _resultado_local(
                solicitud, EstadoVerificacionDestino.SIN_RESULTADOS,
                "CONSULTA_NO_EXISTE_EN_CACHE_CONGELADO", "SIN_RESULTADO",
            )
        codigo, cuerpo = congelada
        proveedor = VerificadorDestinosOpenRouteService(
            api_key="CREDENCIAL_LOCAL_NO_REAL",
            limite_consultas=1,
            usar_cache=False,
            transporte=lambda *_: RespuestaHTTPDestino(
                codigo, json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
            ),
        )
        resultado = proveedor.verificar(solicitud)
        return replace(
            resultado, desde_cache=True, proveedor=self.nombre, duracion_ms=0.0
        )


def cargar_destinos(ruta: str | Path) -> tuple[DestinoEntrada, ...]:
    origen = Path(ruta)
    if not origen.exists():
        raise FileNotFoundError(f"Entrada inexistente: {origen}")
    if not origen.is_file():
        raise ErrorEntradaDestinos("La entrada debe ser un archivo")
    if origen.stat().st_size == 0:
        raise ErrorEntradaDestinos("El archivo de entrada está vacío")
    sufijo = origen.suffix.lower()
    if sufijo == ".json":
        datos = json.loads(origen.read_text(encoding="utf-8-sig"))
        filas = datos.get("destinos") if isinstance(datos, dict) else datos
        if not isinstance(filas, list):
            raise ErrorEntradaDestinos("JSON debe ser lista o contener 'destinos'")
    elif sufijo == ".csv":
        with origen.open("r", encoding="utf-8-sig", newline="") as archivo:
            muestra = archivo.read(4096)
            archivo.seek(0)
            try:
                dialecto = csv.Sniffer().sniff(muestra, delimiters=";,")
            except csv.Error:
                dialecto = csv.excel
            filas = list(csv.DictReader(archivo, dialect=dialecto))
    else:
        raise ErrorEntradaDestinos("Formato permitido: JSON o CSV")
    if not filas:
        raise ErrorEntradaDestinos("La entrada no contiene registros")
    destinos = tuple(_validar_registro(fila, i) for i, fila in enumerate(filas, 1))
    ids = [d.destino_id for d in destinos]
    if len(ids) != len(set(ids)):
        raise ErrorEntradaDestinos("Existen destino_id duplicados")
    return destinos


def procesar_destinos(
    destinos: Iterable[DestinoEntrada],
    *,
    configuracion: ConfiguracionRevisionDestinos = ConfiguracionRevisionDestinos(),
    proveedor: ProveedorRevision | None = None,
    fecha_evaluacion: datetime | None = None,
) -> ResultadoLoteRevision:
    destinos = tuple(sorted(destinos, key=lambda d: d.destino_id.casefold()))
    if configuracion.solo_cache and proveedor is None:
        raise ErrorConfiguracionRevision("No existe caché/proveedor congelado")
    fecha = fecha_evaluacion or datetime.now(timezone.utc)
    revisiones = []
    consultas_iniciales = _consultas_proveedor(proveedor)
    for destino in destinos:
        try:
            revisiones.append(_evaluar_destino(
                destino, configuracion, proveedor, fecha
            ))
        except Exception as error:  # una falla individual no detiene el lote
            revisiones.append(_revision_error(destino, fecha, error))
    consultas_finales = _consultas_proveedor(proveedor)
    resumen = _crear_resumen(
        revisiones, len(destinos), consultas_finales - consultas_iniciales
    )
    manifiesto = {
        "modo": "REVISION_HUMANA_SIN_ESCRITURA",
        "fecha_evaluacion": fecha.isoformat(),
        "destinos_leidos": len(destinos),
        "orden_destinos": [d.destino_id for d in destinos],
        "consultas_reales_habilitadas": (
            configuracion.permitir_consultas
            and configuracion.max_consultas > 0
            and not configuracion.solo_cache
            and configuracion.proveedor == "ors"
        ),
        "max_consultas": configuracion.max_consultas,
        "usar_cache": configuracion.usar_cache,
        "solo_cache": configuracion.solo_cache,
        "timeout": configuracion.timeout,
        "proveedor": configuracion.proveedor,
        "acciones_permitidas": sorted(ACCIONES_PERMITIDAS),
        "escritura_catalogo": False,
        "decision_humana_separada": True,
    }
    return ResultadoLoteRevision(
        tuple(revisiones), MappingProxyType(resumen), MappingProxyType(manifiesto)
    )


def guardar_bandeja(
    resultado: ResultadoLoteRevision,
    salida: str | Path,
    *,
    hash_entrada_antes: str,
    hash_entrada_despues: str,
) -> tuple[Path, ...]:
    destino = Path(salida)
    destino.mkdir(parents=True, exist_ok=True)
    filas = [_revision_serializable(r) for r in resultado.revisiones]
    ruta_csv = destino / "revisiones_destinos.csv"
    with ruta_csv.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(
            archivo, fieldnames=list(filas[0]), delimiter=";",
            lineterminator="\n",
        )
        escritor.writeheader()
        escritor.writerows(filas)
    ruta_json = destino / "revisiones_destinos.json"
    _escribir_json(ruta_json, filas)
    resumen = dict(resultado.resumen)
    resumen["hash_entrada_antes"] = hash_entrada_antes
    resumen["hash_entrada_despues"] = hash_entrada_despues
    resumen["entrada_intacta"] = hash_entrada_antes == hash_entrada_despues
    ruta_resumen = destino / "resumen_revision_destinos.json"
    _escribir_json(ruta_resumen, resumen)
    ruta_manifest = destino / "manifiesto_ejecucion.json"
    _escribir_json(ruta_manifest, dict(resultado.manifiesto))
    return ruta_csv, ruta_json, ruta_resumen, ruta_manifest


def ejecutar_archivo(
    entrada: str | Path,
    salida: str | Path,
    *,
    configuracion: ConfiguracionRevisionDestinos = ConfiguracionRevisionDestinos(),
    proveedor: ProveedorRevision | None = None,
    fecha_evaluacion: datetime | None = None,
) -> ResultadoLoteRevision:
    ruta = Path(entrada)
    hash_antes = sha256_archivo(ruta)
    destinos = cargar_destinos(ruta)
    resultado = procesar_destinos(
        destinos, configuracion=configuracion, proveedor=proveedor,
        fecha_evaluacion=fecha_evaluacion,
    )
    hash_despues = sha256_archivo(ruta)
    if hash_antes != hash_despues:
        raise RuntimeError("La fuente fue modificada durante la evaluación")
    guardar_bandeja(
        resultado, salida, hash_entrada_antes=hash_antes,
        hash_entrada_despues=hash_despues,
    )
    return resultado


def sha256_archivo(ruta: str | Path) -> str:
    return hashlib.sha256(Path(ruta).read_bytes()).hexdigest()


def _validar_registro(fila: Mapping[str, Any], numero_fila: int) -> DestinoEntrada:
    if not isinstance(fila, Mapping):
        raise ErrorEntradaDestinos(f"Fila {numero_fila}: registro no es objeto")
    original = dict(fila)
    direccion = _obtener(fila, "direccion", "dirección")
    region = _obtener(fila, "region", "región")
    autorizacion = _booleano(
        _obtener(fila, "autorizacion_consulta_externa", "autorización_consulta_externa"),
        numero_fila,
    )
    campos = _campos_autorizados(_obtener(fila, "campos_autorizados"))
    latitud = _coordenada_opcional(_obtener(fila, "latitud", requerido=False), "latitud")
    longitud = _coordenada_opcional(
        _obtener(fila, "longitud", requerido=False), "longitud"
    )
    if (latitud is None) != (longitud is None):
        raise ErrorEntradaDestinos(
            f"Fila {numero_fila}: latitud y longitud deben coexistir"
        )
    if latitud is not None and not (-90 <= latitud <= 90 and -180 <= longitud <= 180):
        raise ErrorEntradaDestinos(f"Fila {numero_fila}: coordenadas inválidas")
    datos = {
        "destino_id": _texto(_obtener(fila, "destino_id"), "destino_id", numero_fila),
        "cliente_id": str(_obtener(fila, "cliente_id", requerido=False) or "").strip(),
        "direccion": _texto(direccion, "direccion", numero_fila),
        "comuna": _texto(_obtener(fila, "comuna"), "comuna", numero_fila),
        "region": _texto(region, "region", numero_fila),
        "pais": _texto(_obtener(fila, "pais"), "pais", numero_fila),
        "latitud": latitud,
        "longitud": longitud,
        "estado_actual": _texto(
            _obtener(fila, "estado_actual", "estado"), "estado_actual", numero_fila
        ),
        "autorizacion_consulta_externa": autorizacion,
        "campos_autorizados": campos,
        "registro_original": original,
    }
    return DestinoEntrada(**datos)


def _evaluar_destino(destino, configuracion, proveedor, fecha):
    huella = _huella_registro(destino.registro_original)
    if not configuracion.permitir_consultas:
        return _revision_sin_resultado(
            destino, fecha, EstadoRevisionDestino.CONSULTA_NO_AUTORIZADA,
            "SIN_ACCION_AUTOMATICA", "Consultas externas desactivadas globalmente.",
            huella,
        )
    if not destino.autorizacion_consulta_externa:
        return _revision_sin_resultado(
            destino, fecha, EstadoRevisionDestino.CONSULTA_NO_AUTORIZADA,
            "SIN_ACCION_AUTOMATICA", "El registro no autoriza consulta externa.",
            huella,
        )
    if proveedor is None:
        return _revision_sin_resultado(
            destino, fecha, EstadoRevisionDestino.ERROR_PROVEEDOR,
            "REPETIR_CONSULTA_MANUALMENTE", "Proveedor no disponible.", huella,
        )
    if (
        not configuracion.solo_cache
        and _consultas_proveedor(proveedor) >= configuracion.max_consultas
    ):
        return _revision_sin_resultado(
            destino, fecha, EstadoRevisionDestino.ERROR_PROVEEDOR,
            "REPETIR_CONSULTA_MANUALMENTE",
            "Límite local de consultas alcanzado.", huella,
        )
    solicitud = SolicitudVerificacionDestino(
        direccion_original=destino.direccion,
        comuna_esperada=destino.comuna,
        region_esperada=destino.region,
        pais=destino.pais,
        identificador_interno=destino.destino_id,
        autorizacion_externa=True,
        campos_autorizados=destino.campos_autorizados & CAMPOS_AUTORIZABLES,
        contiene_datos_sensibles=False,
    )
    resultado = proveedor.verificar(solicitud)
    internas = _evidencias_internas(destino, fecha)
    propuesta = resolver_destino_con_verificacion(
        destino.direccion, internas, resultado
    )
    estado_revision, accion = _mapear_revision(resultado)
    coords_ext = (
        (resultado.latitud, resultado.longitud)
        if resultado.latitud is not None and resultado.longitud is not None
        else None
    )
    if resultado.estado == EstadoVerificacionDestino.VERIFICADA and coords_ext:
        if _coords_originales(destino) is not None:
            if _coordenadas_equivalentes(_coords_originales(destino), coords_ext):
                estado_revision, accion = EstadoRevisionDestino.SIN_CAMBIOS, "MANTENER"
            else:
                estado_revision, accion = (
                    EstadoRevisionDestino.COORDENADAS_PROPUESTAS,
                    "EVALUAR_COORDENADAS",
                )
    contradicciones = tuple(
        c.motivo for c in propuesta.contradicciones
    )
    explicacion = tuple(propuesta.explicacion) + tuple(
        resultado.detalle_comparacion.get("explicacion", ())
    )
    return RegistroRevisionDestino(
        destino.destino_id, destino.cliente_id, destino.direccion, destino.comuna,
        destino.region, _coords_originales(destino), destino.estado_actual,
        estado_revision, resultado.direccion_devuelta,
        resultado.comuna_encontrada, resultado.region_encontrada, coords_ext,
        resultado.tipo_coincidencia, propuesta.valor_propuesto,
        propuesta.confianza.value,
        tuple(e.referencia for e in propuesta.evidencias_favorables),
        tuple(e.referencia for e in propuesta.evidencias_contrarias),
        contradicciones, explicacion, accion, fecha, resultado.proveedor,
        not resultado.desde_cache, resultado.desde_cache, True, huella,
    )


def _mapear_revision(resultado):
    estado = resultado.estado
    if estado == EstadoVerificacionDestino.VERIFICADA:
        return EstadoRevisionDestino.CONFIRMACION_PROPUESTA, "EVALUAR_COORDENADAS"
    if estado == EstadoVerificacionDestino.COINCIDENCIA_PARCIAL:
        return EstadoRevisionDestino.COINCIDENCIA_PARCIAL, "REVISAR_DIRECCION"
    if estado == EstadoVerificacionDestino.CONTRADICCION_NUMERO:
        return EstadoRevisionDestino.CONTRADICCION_NUMERO, "REVISAR_NUMERACION"
    if estado == EstadoVerificacionDestino.CONTRADICCION_COMUNA:
        return EstadoRevisionDestino.CONTRADICCION_COMUNA, "REVISAR_COMUNA"
    if estado == EstadoVerificacionDestino.CONTRADICCION_REGION:
        return EstadoRevisionDestino.CONTRADICCION_REGION, "REVISAR_REGION"
    if estado == EstadoVerificacionDestino.REVISAR:
        if resultado.tipo_coincidencia == "AMBIGUA":
            return EstadoRevisionDestino.RESPUESTA_AMBIGUA, "REVISAR_DIRECCION"
        return EstadoRevisionDestino.REQUIERE_REVISION, "REVISAR_DIRECCION"
    if estado == EstadoVerificacionDestino.SIN_RESULTADOS:
        return EstadoRevisionDestino.SIN_RESULTADOS, "REPETIR_CONSULTA_MANUALMENTE"
    if estado == EstadoVerificacionDestino.CONSULTA_NO_AUTORIZADA:
        return EstadoRevisionDestino.CONSULTA_NO_AUTORIZADA, "SIN_ACCION_AUTOMATICA"
    return EstadoRevisionDestino.ERROR_PROVEEDOR, "REPETIR_CONSULTA_MANUALMENTE"


def _revision_sin_resultado(destino, fecha, estado, accion, motivo, huella):
    return RegistroRevisionDestino(
        destino.destino_id, destino.cliente_id, destino.direccion, destino.comuna,
        destino.region, _coords_originales(destino), destino.estado_actual, estado,
        "", "", "", None, "", destino.direccion, "NULA", (), (), (), (motivo,),
        accion, fecha, "ninguno", False, False, True, huella,
    )


def _revision_error(destino, fecha, error):
    return _revision_sin_resultado(
        destino, fecha, EstadoRevisionDestino.ERROR_PROVEEDOR,
        "REPETIR_CONSULTA_MANUALMENTE",
        f"Error aislado: {type(error).__name__}: {error}",
        _huella_registro(destino.registro_original),
    )


def _crear_resumen(revisiones, leidos, consultas):
    conteos = {estado.value: 0 for estado in EstadoRevisionDestino}
    for revision in revisiones:
        conteos[revision.estado_revision.value] += 1
    contradicciones = sum(
        conteos[e.value] for e in (
            EstadoRevisionDestino.CONTRADICCION_DIRECCION,
            EstadoRevisionDestino.CONTRADICCION_NUMERO,
            EstadoRevisionDestino.CONTRADICCION_COMUNA,
            EstadoRevisionDestino.CONTRADICCION_REGION,
        )
    )
    return {
        "destinos_leidos": leidos,
        "destinos_evaluados": len(revisiones),
        "sin_cambios": conteos["SIN_CAMBIOS"],
        "confirmaciones_propuestas": conteos["CONFIRMACION_PROPUESTA"],
        "coordenadas_propuestas": conteos["COORDENADAS_PROPUESTAS"],
        "contradicciones": contradicciones,
        "ambiguos": conteos["RESPUESTA_AMBIGUA"],
        "sin_resultados": conteos["SIN_RESULTADOS"],
        "consultas_no_autorizadas": conteos["CONSULTA_NO_AUTORIZADA"],
        "errores": conteos["ERROR_PROVEEDOR"],
        "consultas_externas_consumidas": consultas,
        "resultados_desde_cache": sum(r.consulta_desde_cache for r in revisiones),
        "casos_requieren_decision_humana": sum(
            r.requiere_decision_humana for r in revisiones
        ),
        "estados": conteos,
    }


def _revision_serializable(revision):
    datos = asdict(revision)
    datos["estado_revision"] = revision.estado_revision.value
    datos["coordenadas_originales"] = _json_compacto(revision.coordenadas_originales)
    datos["coordenadas_externas"] = _json_compacto(revision.coordenadas_externas)
    for campo in (
        "evidencias_favorables", "evidencias_contrarias", "contradicciones",
        "explicacion",
    ):
        datos[campo] = _json_compacto(datos[campo])
    datos["fecha_evaluacion"] = revision.fecha_evaluacion.isoformat()
    return datos


def _evidencias_internas(destino, fecha):
    return (
        Evidencia(
            "destino", destino.direccion, normalizar(destino.direccion),
            "fuente_entrada_modo_revision", TipoFuente.CATALOGO, 1.0, fecha,
            referencia=f"ORIGINAL-{destino.destino_id}",
        ),
    )


def _resultado_local(solicitud, estado, error, tipo):
    ahora = datetime.now(timezone.utc)
    consulta = _consulta_de_solicitud(solicitud)
    identificador = hashlib.sha256(normalizar(consulta).encode()).hexdigest()
    return ResultadoVerificacionDestino(
        estado, consulta, "", "", "", "", None, None, tipo, None, None,
        "cache-congelado", ahora, 0.0, error, True, solicitud, identificador,
        ahora, True,
    )


def _consulta_de_solicitud(solicitud):
    return ", ".join(
        str(getattr(solicitud, campo)).strip()
        for campo in (
            "direccion_original", "comuna_esperada", "region_esperada", "pais"
        )
        if campo in solicitud.campos_autorizados
        and str(getattr(solicitud, campo)).strip()
    )


def _obtener(fila, *nombres, requerido=True):
    for nombre in nombres:
        if nombre in fila:
            return fila[nombre]
    if requerido:
        raise ErrorEntradaDestinos(f"Falta columna obligatoria: {nombres[0]}")
    return None


def _texto(valor, campo, fila):
    texto = str(valor or "").strip()
    if not texto:
        raise ErrorEntradaDestinos(f"Fila {fila}: {campo} vacío")
    return texto


def _booleano(valor, fila):
    if isinstance(valor, bool):
        return valor
    texto = normalizar(valor)
    if texto in {"TRUE", "SI", "1"}:
        return True
    if texto in {"FALSE", "NO", "0"}:
        return False
    raise ErrorEntradaDestinos(f"Fila {fila}: autorización inválida")


def _campos_autorizados(valor):
    if isinstance(valor, (list, tuple, set, frozenset)):
        campos = frozenset(str(v).strip() for v in valor if str(v).strip())
    else:
        texto = str(valor or "").replace(",", "|").replace(";", "|")
        campos = frozenset(v.strip() for v in texto.split("|") if v.strip())
    if not campos <= CAMPOS_AUTORIZABLES:
        desconocidos = sorted(campos - CAMPOS_AUTORIZABLES)
        raise ErrorEntradaDestinos(f"Campos no autorizables: {desconocidos}")
    return campos


def _coordenada_opcional(valor, nombre):
    if valor is None or str(valor).strip() == "":
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError) as error:
        raise ErrorEntradaDestinos(f"{nombre} inválida") from error
    if not math.isfinite(numero):
        raise ErrorEntradaDestinos(f"{nombre} inválida")
    return numero


def _coords_originales(destino):
    if destino.latitud is None:
        return None
    return destino.latitud, destino.longitud


def _coordenadas_equivalentes(a, b, tolerancia=0.000001):
    return abs(a[0] - b[0]) <= tolerancia and abs(a[1] - b[1]) <= tolerancia


def _consultas_proveedor(proveedor):
    if proveedor is None:
        return 0
    return int(getattr(
        proveedor, "consultas_externas",
        getattr(proveedor, "consultas_realizadas", 0),
    ))


def _huella_registro(registro):
    serializado = json.dumps(
        dict(registro), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serializado.encode("utf-8")).hexdigest()


def _json_compacto(valor):
    return json.dumps(valor, ensure_ascii=False, separators=(",", ":"), default=str)


def _escribir_json(ruta, valor):
    ruta.write_text(
        json.dumps(valor, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )
