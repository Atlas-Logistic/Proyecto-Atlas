"""P0 RECUPERACIÓN INCREMENTAL DE CAMPOS AUSENTES.

Completa, en guías ya procesadas, SÓLO los campos núcleo que quedaron
ausentes ("No encontrado"): chofer/RUT, tracto, rampla y material, usando el
extractor vigente sobre el MISMO original (traza OCR persistida si trae
bloques; si no, OCR con presupuesto).

Reglas (diagnóstico 16/11/2026, casos 480973, 481180, 484096, 484002, 484396):

* Nunca escribe un campo con valor, ni uno tocado por una acción humana, ni
  filas con decisión pendiente o en investigación.
* Cada valor escrito debe aparecer impreso en el documento (líneas OCR del
  mismo original). Una patente sólo por asignación chofer->vehículo, actual o
  histórica, nunca se escribe: el extractor vigente la deduce cuando el papel
  no trae carro (480973), así que su salida se re-verifica contra el texto.
* Rampla: camión rígido de catálogo (NO_APLICA_RIGIDO), papel sin carro o
  "CARRO: LOCAL" (SIN_CARRO_DOCUMENTAL) y carro ilegible (NO_ENCONTRADO) son
  estados distintos; la columna conserva "No encontrado" por compatibilidad.
* No toca motivos, estados, rutas, transporte, guía ni agrupaciones. Un tracto
  nuevo en una fila sin planta de origen se abstiene (los vecinos GPS del
  mismo vehículo podrían inferir origen y recalcular ruta).
* Un intento por campo y por versión de las capacidades que lo gobiernan: una
  mejora futura (subir la versión del dominio) habilita UN reintento.
* Auditoría en `operacion/actual/recuperaciones_incrementales.json` (custodiado)
  y en `metricas_procesamiento_json.recuperacion_p0.campos_ausentes`; actor
  `MOTOR_RECUPERACION_INCREMENTAL`, nunca un humano. Reversible por lote.
"""
from __future__ import annotations

import csv
import difflib
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping

logger = logging.getLogger(__name__)

VERSION_RECUPERACION_INCREMENTAL = 1
ACTOR = "MOTOR_RECUPERACION_INCREMENTAL"
CLAVE_METRICAS = "campos_ausentes"
NOMBRE_REGISTRO = "recuperaciones_incrementales.json"
MARCA_COPIA = "COPIA_PREVIA_RECUPERACION"
VARIABLE_DESACTIVAR = "ATLAS_RECUPERACION_INCREMENTAL"
LIMITE_OCR_POR_CICLO = 2
LIMITE_TRAZA_POR_CICLO = 10
_AUSENTES = {"", "NO ENCONTRADO"}

GRUPOS: dict[str, tuple[str, ...]] = {
    "chofer": ("chofer", "rut_chofer"),
    "patente_tracto": ("patente_tracto",),
    "patente_rampla": ("patente_rampla",),
    "descripcion_material": ("descripcion_material",),
}

# Estados finales de un campo (además de los resultados de un intento).
VALIDO = "VALIDO"
CONFIRMADO_HUMANO = "CONFIRMADO_HUMANO"
NO_ENCONTRADO = "NO_ENCONTRADO"
NO_APLICA_RIGIDO = "NO_APLICA_RIGIDO"
SIN_CARRO_DOCUMENTAL = "SIN_CARRO_DOCUMENTAL"
# Resultados de intento.
RECUPERADO = "RECUPERADO"
SIN_MEJORA = "SIN_MEJORA"
SIN_EVIDENCIA_DOCUMENTAL = "SIN_EVIDENCIA_DOCUMENTAL"
CONFLICTO_TRANSPORTE = "CONFLICTO_TRANSPORTE"
EFECTO_ORIGEN = "EFECTO_ORIGEN"
DISCREPANCIA_IDENTIDAD = "DISCREPANCIA_IDENTIDAD"
INTEGRIDAD = "INTEGRIDAD"
REVERTIDO = "REVERTIDO"

_ACCIONES_POR_GRUPO = {
    "chofer": {"DOCUMENTO_CORREGIR_CHOFER_OPERACIONAL", "DOCUMENTO_CORREGIR_IDENTIDAD_CHOFER"},
    "patente_tracto": {"CHOFER_ASIGNAR_VEHICULO"},
    "patente_rampla": {"CHOFER_ASIGNAR_VEHICULO"},
    "descripcion_material": {"DOCUMENTO_RECUPERAR_MATERIAL"},
}
_CAMPOS_ACCION_POR_GRUPO = {
    "chofer": {"CHOFER", "RUT_CHOFER", "CHOFER_OPERACIONAL", "IDENTIDAD_CHOFER"},
    "patente_tracto": {"PATENTE_TRACTO", "TRACTO", "PATENTE"},
    "patente_rampla": {"PATENTE_RAMPLA", "RAMPLA", "CARRO", "PATENTE_CARRO"},
    "descripcion_material": {"DESCRIPCION_MATERIAL", "MATERIAL"},
}
# Acciones humanas que vuelven intocable la fila completa.
_ACCIONES_FILA = {"DOCUMENTO_CONFIRMAR_ERROR_DOCUMENTAL_AZA"}


def ausente(valor: object) -> bool:
    return str(valor or "").strip().upper() in _AUSENTES


def _normalizar(texto: object) -> str:
    plano = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Z0-9]", "", plano.upper())


def _rut_normalizado(texto: object) -> str:
    return re.sub(r"[^0-9K]", "", str(texto or "").upper())


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def dominios_por_grupo() -> dict[str, tuple[str, ...]]:
    from atlas_core.capacidades_reevaluacion import (
        DOMINIO_CHOFER, DOMINIO_EXTRACCION, DOMINIO_MATERIAL, DOMINIO_VEHICULO,
    )
    return {
        "chofer": (DOMINIO_CHOFER, DOMINIO_EXTRACCION),
        "patente_tracto": (DOMINIO_VEHICULO, DOMINIO_EXTRACCION),
        "patente_rampla": (DOMINIO_VEHICULO, DOMINIO_EXTRACCION),
        "descripcion_material": (DOMINIO_MATERIAL, DOMINIO_EXTRACCION),
    }


def clave_capacidad(grupo: str, versiones: Mapping[str, int] | None = None) -> dict[str, object]:
    """Lo que identifica un intento: versión propia + dominios del campo."""
    from atlas_core.capacidades_reevaluacion import versiones_actuales
    versiones = dict(versiones or versiones_actuales())
    return {
        "version": VERSION_RECUPERACION_INCREMENTAL,
        "capacidades": {d: int(versiones.get(d, 0)) for d in dominios_por_grupo()[grupo]},
    }


# --- métricas por fila ------------------------------------------------------

def _metricas(fila: Mapping[str, object]) -> dict:
    try:
        valor = json.loads(str(fila.get("metricas_procesamiento_json") or "") or "{}")
    except (TypeError, ValueError):
        return {}
    return valor if isinstance(valor, dict) else {}


def intentos_de_fila(fila: Mapping[str, object]) -> dict[str, dict]:
    p0 = _metricas(fila).get("recuperacion_p0")
    registro = p0.get(CLAVE_METRICAS) if isinstance(p0, dict) else None
    return registro if isinstance(registro, dict) else {}


def _anotar_intento(fila: dict, grupo: str, registro: Mapping[str, object]) -> None:
    metricas = _metricas(fila)
    p0 = metricas.get("recuperacion_p0") if isinstance(metricas.get("recuperacion_p0"), dict) else {}
    campos = p0.get(CLAVE_METRICAS) if isinstance(p0.get(CLAVE_METRICAS), dict) else {}
    campos[grupo] = dict(registro)
    p0[CLAVE_METRICAS] = campos
    metricas["recuperacion_p0"] = p0
    fila["metricas_procesamiento_json"] = json.dumps(metricas, ensure_ascii=False, sort_keys=True)


def _intento_vigente(fila: Mapping[str, object], grupo: str, clave: Mapping[str, object]) -> bool:
    previo = intentos_de_fila(fila).get(grupo)
    return bool(
        isinstance(previo, dict)
        and previo.get("version") == clave["version"]
        and previo.get("capacidades") == clave["capacidades"]
    )


# --- protecciones humanas ---------------------------------------------------

@dataclass(frozen=True)
class Protecciones:
    por_archivo: Mapping[str, frozenset[str]]  # archivo -> grupos protegidos
    filas_bloqueadas: frozenset[str]           # archivos intocables


def cargar_protecciones(actual: Path) -> Protecciones:
    """Lee el registro de acciones humanas, pendientes e investigaciones.

    Si un archivo existe pero no se puede leer, se lanza: sin saber qué tocó
    un humano no se escribe nada (nunca se asume "sin protección")."""
    por_archivo: dict[str, set[str]] = {}
    bloqueadas: set[str] = set()

    acciones = actual / "acciones_operacionales.json"
    if acciones.is_file():
        datos = json.loads(acciones.read_text(encoding="utf-8"))
        for entrada in (datos.get("auditoria") or []) if isinstance(datos, dict) else []:
            if not isinstance(entrada, dict) or not str(entrada.get("confirmado_por") or "").strip():
                continue
            entidad = entrada.get("entidad") if isinstance(entrada.get("entidad"), dict) else {}
            parametros = entrada.get("parametros") if isinstance(entrada.get("parametros"), dict) else {}
            archivo = str(entidad.get("id") or parametros.get("archivo") or "").strip()
            if not archivo:
                continue
            accion = str(entrada.get("accion") or "")
            if accion in _ACCIONES_FILA:
                bloqueadas.add(archivo)
            campo = _normalizar(entidad.get("campo") or parametros.get("campo") or "")
            for grupo in GRUPOS:
                campos = {_normalizar(c) for c in _CAMPOS_ACCION_POR_GRUPO[grupo]}
                if accion in _ACCIONES_POR_GRUPO[grupo] or (accion == "DOCUMENTO_CORREGIR_CAMPO" and campo in campos):
                    por_archivo.setdefault(archivo, set()).add(grupo)
            if accion == "DECISION_APLICAR":
                # Una decisión humana aplicada sobre el documento: se protege
                # el documento completo (no se sabe qué campo tocó).
                bloqueadas.add(archivo)

    pendientes = actual / "decisiones_pendientes.json"
    if pendientes.is_file():
        bloqueadas |= _archivos_mencionados(json.loads(pendientes.read_text(encoding="utf-8")))
    investigacion = actual / "documentos_en_investigacion.json"
    if investigacion.is_file():
        bloqueadas |= _archivos_mencionados(json.loads(investigacion.read_text(encoding="utf-8")))
    return Protecciones(
        {k: frozenset(v) for k, v in por_archivo.items()}, frozenset(bloqueadas),
    )


def _archivos_mencionados(datos: object) -> set[str]:
    """Todo valor `archivo` (o `documento.archivo`) de un JSON de pendientes."""
    encontrados: set[str] = set()

    def visitar(nodo: object) -> None:
        if isinstance(nodo, dict):
            for clave, valor in nodo.items():
                if clave in {"archivo", "archivo_documento"} and isinstance(valor, str) and valor.strip():
                    encontrados.add(valor.strip())
                else:
                    visitar(valor)
        elif isinstance(nodo, list):
            for elemento in nodo:
                visitar(elemento)

    visitar(datos)
    return encontrados


# --- lectura del documento --------------------------------------------------

@dataclass
class Lectura:
    datos: Mapping[str, object]
    lineas: list[str]
    fuente: str               # TRAZA_OCR | OCR_COPIA
    sha256_original: str


class ProveedorDesdeTraza:
    """Proveedor OCR que reproduce la lectura persistida (sin OCR nuevo)."""

    def __init__(self, traza: Mapping[str, object], referencia: str) -> None:
        from atlas_core.replay_traza_ocr import reconstruir_bloques_desde_traza
        self._bloques = list(reconstruir_bloques_desde_traza(traza, referencia_esperada=referencia))
        ocr = traza.get("ocr") if isinstance(traza.get("ocr"), dict) else {}
        self._lineas = [str(x) for x in (ocr.get("lineas") or [])]

    def leer_texto(self, ruta_imagen) -> list[str]:
        return list(self._lineas)

    def leer_bloques(self, ruta_imagen) -> list:
        return list(self._bloques)

    def leer_focal(self, ruta_imagen, caja, allowlist: str = "") -> dict:
        return {"lecturas": []}

    def cerrar(self) -> None:
        pass


class _ProveedorRegistrado:
    """Envoltorio que conserva las líneas/bloques leídos como evidencia."""

    def __init__(self, base) -> None:
        self._base = base
        self.lineas: list[str] = []

    def leer_texto(self, ruta_imagen) -> list[str]:
        lineas = list(self._base.leer_texto(ruta_imagen))
        self.lineas.extend(str(x) for x in lineas)
        return lineas

    def leer_bloques(self, ruta_imagen) -> list:
        bloques = list(self._base.leer_bloques(ruta_imagen))
        self.lineas.extend(str(getattr(b, "texto", "")) for b in bloques)
        return bloques

    def leer_focal(self, ruta_imagen, caja, allowlist: str = "") -> dict:
        return self._base.leer_focal(ruta_imagen, caja, allowlist=allowlist)


class _ProveedorRutasSinRed:
    """Nunca consulta red: la recuperación sólo usa los cinco campos."""

    nombre = "sin_red_recuperacion"
    version = "1"

    def geocodificar(self, direccion):
        from atlas_core.rutas.modelos import EstadoRuta, ResultadoGeocodificacion
        return ResultadoGeocodificacion(EstadoRuta.PROVEEDOR_NO_DISPONIBLE, (), "RECUPERACION_INCREMENTAL_SIN_RED")

    def geocodificar_estructurado(self, direccion, contexto):
        return self.geocodificar(direccion)

    def calcular_ruta(self, origen, destino, perfil):
        from atlas_core.rutas.modelos import EstadoRuta, ResultadoRuta
        return ResultadoRuta(EstadoRuta.PROVEEDOR_NO_DISPONIBLE, None, None, "RECUPERACION_INCREMENTAL_SIN_RED")


def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def sha_referencia(raiz: Path, fila: Mapping[str, object]) -> str:
    """Huella registrada del original (Mobile: envio.json; si no, métricas)."""
    archivo = str(fila.get("archivo") or "")
    partes = archivo.split("/")
    if len(partes) == 3 and partes[0] == "mobile":
        envio = raiz / "operacion" / "mobile" / "envios" / partes[1] / "envio.json"
        if envio.is_file():
            try:
                registro = json.loads(envio.read_text(encoding="utf-8"))
                if registro.get("foto_original") == partes[2] and registro.get("imagen_sha256"):
                    return str(registro["imagen_sha256"]).lower()
            except (OSError, ValueError):
                pass
    orientacion = _metricas(fila).get("orientacion_documental")
    if isinstance(orientacion, dict) and orientacion.get("sha256_original"):
        return str(orientacion["sha256_original"]).lower()
    return ""


def traza_con_bloques(raiz: Path, archivo: str) -> dict | None:
    from atlas_core.trazabilidad_ocr import ESTADO_BLOQUES_DISPONIBLES, ruta_traza_ocr
    ruta = ruta_traza_ocr(raiz / "operacion" / "trazas_ocr", archivo)
    if not ruta.is_file():
        return None
    try:
        traza = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    imagen = traza.get("imagen") if isinstance(traza.get("imagen"), dict) else {}
    ocr = traza.get("ocr") if isinstance(traza.get("ocr"), dict) else {}
    if str(imagen.get("referencia") or "").replace("\\", "/") != archivo.replace("\\", "/"):
        return None
    if ocr.get("estado_bloques") != ESTADO_BLOQUES_DISPONIBLES:
        return None
    return traza


class LectorDocumental:
    """Corre el extractor vigente sobre una COPIA del original, con catálogos
    copiados y sin red: ningún efecto fuera de un directorio temporal."""

    def __init__(self, raiz: Path, fabrica_ocr: Callable[[], object] | None) -> None:
        self.raiz = raiz
        self.fabrica_ocr = fabrica_ocr
        self._ocr = None
        self._temporal = Path(tempfile.mkdtemp(prefix="atlas_recuperacion_"))
        destino = self._temporal / "Atlas" / "catalogos_privados"
        destino.mkdir(parents=True)
        origen = raiz / "catalogos_privados"
        for archivo in origen.glob("*.json"):
            shutil.copy2(archivo, destino / archivo.name)
        self.catalogos = destino

    def cerrar(self) -> None:
        if self._ocr is not None and hasattr(self._ocr, "cerrar"):
            try:
                self._ocr.cerrar()
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(self._temporal, ignore_errors=True)

    def leer(self, ruta_original: Path, archivo: str, traza: dict | None) -> Lectura:
        from atlas_core.procesamiento_masivo import procesar_archivo
        sha = _sha256(ruta_original)
        copia_dir = self._temporal / "img" / hashlib.sha256(archivo.encode()).hexdigest()[:16]
        copia_dir.mkdir(parents=True, exist_ok=True)
        copia = copia_dir / ruta_original.name
        shutil.copy2(ruta_original, copia)
        if traza is not None:
            base, fuente = ProveedorDesdeTraza(traza, archivo), "TRAZA_OCR"
        else:
            if self._ocr is None:
                if self.fabrica_ocr is None:
                    raise RuntimeError("Sin proveedor OCR para relectura.")
                self._ocr = self.fabrica_ocr()
            base, fuente = self._ocr, "OCR_COPIA"
        proveedor = _ProveedorRegistrado(base)
        sin_red = _ProveedorRutasSinRed()
        datos = procesar_archivo(
            copia, proveedor=proveedor, carpeta_catalogos=self.catalogos,
            proveedor_rutas=sin_red, proveedor_geocodificacion_fallback=sin_red,
            directorio_orientacion=self._temporal / "orientacion",
        )
        if _sha256(ruta_original) != sha:
            raise RuntimeError("El original cambió durante la relectura.")
        return Lectura(dict(datos), proveedor.lineas, fuente, sha)


# --- evaluación por campo ---------------------------------------------------

@dataclass
class Resultado:
    grupo: str
    resultado: str
    valores: dict[str, str] = field(default_factory=dict)
    evidencia: str = ""
    detalle: str = ""


# Etiqueta CARRO con las deformaciones OCR vistas en guías reales
# (CARRD1JX2501, CARR01JB8529, "Carao; J5o108").
_ETIQUETA_CARRO = re.compile(r"C[A4]R[RA][O0DQ]")


def _segmentos(lineas: Iterable[str]) -> tuple[list[str], list[str]]:
    """(texto de tracto, texto tras la etiqueta CARRO) normalizados por línea."""
    tracto, carro = [], []
    for linea in lineas:
        n = _normalizar(linea)
        marca = _ETIQUETA_CARRO.search(n)
        if marca:
            tracto.append(n[:marca.start()])
            carro.append(n[marca.end():])
        else:
            tracto.append(n)
    return tracto, carro


def _alguna_patente_cercana(textos: Iterable[str], patentes: Iterable[str]) -> bool:
    """¿Aparece alguna patente (a lo más 1 carácter distinto) en el texto?"""
    objetivos = [p for p in (_normalizar(x) for x in patentes) if len(p) == 6]
    for texto in textos:
        for i in range(0, max(0, len(texto) - 5)):
            ventana = texto[i:i + 6]
            if any(sum(a != b for a, b in zip(ventana, p)) <= 1 for p in objetivos):
                return True
    return False


def _patente_en_texto(patente: str, textos: Iterable[str], catalogo: Path, tipo: str) -> str:
    """Devuelve el fragmento que, homologado, da exactamente `patente`."""
    from atlas_core.catalogos import resolver_patente_canonica
    objetivo = _normalizar(patente)
    if len(objetivo) != 6:
        return ""
    for texto in textos:
        if objetivo in texto:
            return objetivo
        for i in range(0, max(0, len(texto) - 5)):
            ventana = texto[i:i + 6]
            if sum(a != b for a, b in zip(ventana, objetivo)) != 1:
                continue
            decision = resolver_patente_canonica(catalogo, ventana, tipo_esperado=tipo)
            if decision.estado in {"COINCIDENCIA_EXACTA", "ALIAS", "CORRECCION_OCR_SEGURA"} and \
                    _normalizar(decision.valor_resultado) == objetivo:
                return ventana
    return ""


def _tipo_vehiculo(catalogo_vehiculos, patente: str) -> str:
    objetivo = _normalizar(patente)
    for vehiculo in catalogo_vehiculos.homologables():
        if _normalizar(vehiculo.patente_canonica) == objetivo:
            return str(vehiculo.tipo)
    return ""


def _conflicto_transporte(fila, columna: str, valor: str, filas: list[dict]) -> bool:
    transporte = str(fila.get("numero_transporte") or "").strip()
    if ausente(transporte):
        return False
    normal = _rut_normalizado if columna == "rut_chofer" else _normalizar
    for otra in filas:
        if otra is fila or otra.get("archivo") == fila.get("archivo"):
            continue
        if str(otra.get("numero_transporte") or "").strip() != transporte:
            continue
        existente = otra.get(columna)
        if not ausente(existente) and normal(existente) != normal(valor):
            return True
    return False


def _identidad_discrepa(fila, datos) -> bool:
    for columna in ("numero_guia", "numero_transporte"):
        a, b = fila.get(columna), datos.get(columna)
        if not ausente(a) and not ausente(b) and re.sub(r"\D", "", str(a)) != re.sub(r"\D", "", str(b)):
            return True
    return False


def evaluar_grupo(
    grupo: str, fila: Mapping[str, object], lectura: Lectura, *, filas: list[dict],
    catalogo_vehiculos, ruta_vehiculos: Path, choferes: Mapping[str, object],
) -> Resultado:
    datos, lineas = lectura.datos, lectura.lineas
    texto = [_normalizar(x) for x in lineas]
    unido = "".join(texto)

    if grupo == "chofer":
        from atlas_core.convergencia_identidad_conocida import resolver_identidad_nominal_fuerte_chofer
        from atlas_core.validadores import EstadoValidacion, validar_rut_chileno
        nombre, rut = str(datos.get("chofer") or ""), str(datos.get("rut_chofer") or "")
        if ausente(nombre) or ausente(rut):
            return Resultado(grupo, SIN_MEJORA, detalle="El extractor vigente no obtiene chofer y RUT.")
        if validar_rut_chileno(rut).estado != EstadoValidacion.VALIDO:
            return Resultado(grupo, SIN_MEJORA, detalle="RUT leído inválido.")
        identidad = resolver_identidad_nominal_fuerte_chofer(
            nombre_documental=nombre, rut_documental=rut, choferes=choferes,
        )
        if identidad.resultado != "RESUELTO":
            return Resultado(grupo, SIN_EVIDENCIA_DOCUMENTAL, detalle=f"Chofer no identificado: {identidad.explicacion}")
        if _rut_normalizado(rut) not in unido:
            return Resultado(grupo, SIN_EVIDENCIA_DOCUMENTAL, detalle="El RUT no aparece impreso en la lectura.")
        tokens = [t for t in re.split(r"\s+", _sin_tildes(identidad.nombre_canonico or nombre)) if len(t) >= 4]
        if not any(_normalizar(t) in unido for t in tokens):
            return Resultado(grupo, SIN_EVIDENCIA_DOCUMENTAL, detalle="El nombre no aparece impreso en la lectura.")
        valores = {}
        for columna, nuevo in (("chofer", nombre), ("rut_chofer", rut)):
            actual = fila.get(columna)
            if ausente(actual):
                valores[columna] = nuevo
            elif (_rut_normalizado(actual) if columna == "rut_chofer" else _normalizar(actual)) != \
                    (_rut_normalizado(nuevo) if columna == "rut_chofer" else _normalizar(nuevo)):
                return Resultado(grupo, DISCREPANCIA_IDENTIDAD, detalle=f"{columna} existente difiere de la lectura.")
        if any(_conflicto_transporte(fila, c, v, filas) for c, v in valores.items()):
            return Resultado(grupo, CONFLICTO_TRANSPORTE, detalle="Otra guía del transporte informa otro chofer.")
        return Resultado(grupo, RECUPERADO, valores, evidencia=f"RUT {rut} / {nombre}")

    if grupo == "patente_tracto":
        valor = str(datos.get("patente_tracto") or "")
        if ausente(valor):
            return Resultado(grupo, SIN_MEJORA, detalle="El extractor vigente no obtiene tracto.")
        tipo = _tipo_vehiculo(catalogo_vehiculos, valor)
        if tipo not in {"TRACTO", "CAMION_RIGIDO"}:
            return Resultado(grupo, SIN_EVIDENCIA_DOCUMENTAL, detalle=f"{valor} no es tracto confirmado ({tipo or 'sin catálogo'}).")
        segmentos_tracto, _ = _segmentos(lineas)
        fragmento = _patente_en_texto(valor, segmentos_tracto, ruta_vehiculos, tipo)
        if not fragmento:
            return Resultado(grupo, SIN_EVIDENCIA_DOCUMENTAL, detalle=f"{valor} no aparece impreso como patente.")
        if ausente(fila.get("planta_origen_id")):
            return Resultado(grupo, EFECTO_ORIGEN, detalle="Sin planta de origen: un tracto nuevo podría inferir origen GPS.")
        if _conflicto_transporte(fila, "patente_tracto", valor, filas):
            return Resultado(grupo, CONFLICTO_TRANSPORTE, detalle="Otra guía del transporte informa otro tracto.")
        return Resultado(grupo, RECUPERADO, {"patente_tracto": valor}, evidencia=fragmento)

    if grupo == "patente_rampla":
        tracto = str(fila.get("patente_tracto") or "")
        if ausente(tracto):
            tracto = str(datos.get("patente_tracto") or "")
        if not ausente(tracto) and _tipo_vehiculo(catalogo_vehiculos, tracto) == "CAMION_RIGIDO":
            return Resultado(grupo, NO_APLICA_RIGIDO, detalle=f"{tracto} es camión rígido.")
        _, segmentos_carro = _segmentos(lineas)
        valor = str(datos.get("patente_rampla") or "")
        if not ausente(valor):
            if _tipo_vehiculo(catalogo_vehiculos, valor) != "CARRO":
                return Resultado(grupo, SIN_EVIDENCIA_DOCUMENTAL, detalle=f"{valor} no es carro confirmado.")
            fragmento = _patente_en_texto(valor, segmentos_carro, ruta_vehiculos, "CARRO")
            if fragmento:
                if _conflicto_transporte(fila, "patente_rampla", valor, filas):
                    return Resultado(grupo, CONFLICTO_TRANSPORTE, detalle="Otra guía del transporte informa otra rampla.")
                return Resultado(grupo, RECUPERADO, {"patente_rampla": valor}, evidencia=f"CARRO {fragmento}")
        if any(s.startswith("LOCAL") for s in segmentos_carro):
            return Resultado(grupo, SIN_CARRO_DOCUMENTAL, detalle="El documento declara CARRO: LOCAL.")
        carros = [v.patente_canonica for v in catalogo_vehiculos.homologables() if str(v.tipo) == "CARRO"]
        if not segmentos_carro and "PATENTE" in unido and not ausente(tracto) and \
                _patente_en_texto(tracto, _segmentos(lineas)[0], ruta_vehiculos, "TRACTO") and \
                not _alguna_patente_cercana(texto, carros):
            return Resultado(grupo, SIN_CARRO_DOCUMENTAL,
                             detalle="El bloque PATENTE es legible, sin etiqueta CARRO ni patente de carro.")
        if not ausente(valor):
            return Resultado(grupo, SIN_EVIDENCIA_DOCUMENTAL,
                             detalle=f"{valor} sólo deducido (no impreso tras CARRO); no se completa.")
        return Resultado(grupo, SIN_MEJORA, detalle="Carro no identificado en la lectura.")

    if grupo == "descripcion_material":
        from atlas_core.credibilidad_campos import NivelCredibilidad, evaluar_credibilidad_material
        valor = str(datos.get("descripcion_material") or "").strip()
        if ausente(valor):
            return Resultado(grupo, SIN_MEJORA, detalle="El extractor vigente no obtiene material.")
        if evaluar_credibilidad_material(valor).nivel == NivelCredibilidad.INVALIDO:
            return Resultado(grupo, SIN_EVIDENCIA_DOCUMENTAL, detalle="Material leído no creíble.")
        for item in [x.strip() for x in valor.split("|") if x.strip()]:
            objetivo = _normalizar(item)
            mejor = max((difflib.SequenceMatcher(None, objetivo, t).ratio() for t in texto if t), default=0.0)
            if mejor < 0.8 and not any(objetivo in t for t in texto):
                return Resultado(grupo, SIN_EVIDENCIA_DOCUMENTAL, detalle=f"'{item}' no coincide con ninguna línea impresa.")
        return Resultado(grupo, RECUPERADO, {"descripcion_material": valor}, evidencia=valor[:120])

    raise ValueError(grupo)


def _sin_tildes(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii").upper()


# --- selección --------------------------------------------------------------

def estado_grupo(fila: Mapping[str, object], grupo: str, protecciones: Protecciones) -> str:
    archivo = str(fila.get("archivo") or "")
    if grupo in protecciones.por_archivo.get(archivo, ()):
        return CONFIRMADO_HUMANO
    if not any(ausente(fila.get(c)) for c in GRUPOS[grupo]):
        return VALIDO
    previo = intentos_de_fila(fila).get(grupo)
    if isinstance(previo, dict) and previo.get("resultado") in {NO_APLICA_RIGIDO, SIN_CARRO_DOCUMENTAL}:
        return str(previo["resultado"])
    return NO_ENCONTRADO


def grupos_candidatos(fila, protecciones: Protecciones, versiones=None) -> list[str]:
    if str(fila.get("archivo") or "") in protecciones.filas_bloqueadas:
        return []
    candidatos = []
    for grupo in GRUPOS:
        if estado_grupo(fila, grupo, protecciones) != NO_ENCONTRADO:
            continue
        if _intento_vigente(fila, grupo, clave_capacidad(grupo, versiones)):
            continue
        candidatos.append(grupo)
    return candidatos


# --- ciclo ------------------------------------------------------------------

def _leer_dataset(ruta: Path) -> tuple[list[str], list[dict[str, str]]]:
    from atlas_core.revalidacion_documental import _leer_filas
    filas = _leer_filas(ruta, completas=True)
    with ruta.open("r", newline="", encoding="utf-8-sig") as archivo:
        encabezado = next(csv.reader(archivo, delimiter=";"))
    return encabezado, filas


def _escribir_dataset(ruta: Path, filas: list[dict[str, str]]) -> None:
    from atlas_core.revalidacion_documental import _escribir_filas_completas
    _escribir_filas_completas(ruta, filas)


def _respaldar_dataset(dataset: Path, directorio: Path, lote: str) -> Path:
    directorio.mkdir(parents=True, exist_ok=True)
    destino = directorio / f"{lote}.csv"
    shutil.copy2(dataset, destino)
    for viejo in sorted(directorio.glob("*.csv"), key=lambda p: p.stat().st_mtime)[:-30]:
        viejo.unlink(missing_ok=True)
    return destino


def _directorio_respaldo_local() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "Atlas" / "respaldos" / "recuperacion_incremental"


def _registrar_lote(actual: Path, lote: Mapping[str, object]) -> None:
    from atlas_core.almacenamiento_portable import escribir_json_atomico
    ruta = actual / NOMBRE_REGISTRO
    registro = {"schema_version": 1, "lotes": []}
    if ruta.is_file():
        registro = json.loads(ruta.read_text(encoding="utf-8"))
    registro.setdefault("lotes", []).append(dict(lote))
    escribir_json_atomico(ruta, registro)


def recuperar_campos_ausentes(
    *, raiz_atlas: str | Path, fabrica_ocr: Callable[[], object] | None = None,
    comprobar: Callable[[], None] | None = None,
    limite_ocr: int = LIMITE_OCR_POR_CICLO, limite_traza: int = LIMITE_TRAZA_POR_CICLO,
    reconciliar: bool = True, lector: LectorDocumental | None = None,
    directorio_respaldo: Path | None = None, reloj: Callable[[], datetime] = _ahora,
) -> dict[str, object]:
    """Una pasada con presupuesto. Devuelve el resumen del lote."""
    from atlas_core.almacenamiento_portable import bloqueo_sesion
    from atlas_core.capacidades_reevaluacion import versiones_actuales
    from atlas_core.catalogos import cargar_catalogo_json
    from atlas_core.catalogo_vehiculos import cargar_catalogo_vehiculos
    from atlas_core.evidencia_documental import resolver_ruta_evidencia

    raiz = Path(raiz_atlas)
    actual = raiz / "operacion" / "actual"
    dataset = actual / "analisis_completo_guias.csv"
    resumen: dict[str, object] = {"lote": "", "intentados": 0, "recuperados": [], "resultados": [], "guias_actualizadas": []}
    if os.environ.get(VARIABLE_DESACTIVAR, "").strip() == "0" or not dataset.is_file():
        resumen["omitido"] = "DESACTIVADO" if dataset.is_file() else "SIN_DATASET"
        return resumen
    versiones = versiones_actuales()
    protecciones = cargar_protecciones(actual)
    _, filas = _leer_dataset(dataset)

    # Candidatas: más recientes primero (las que Desktop muestra hoy).
    orden = sorted(filas, key=lambda f: str(f.get("fecha_ingesta_utc") or ""), reverse=True)
    plan: list[tuple[dict, list[str], dict | None]] = []
    gasto_ocr = gasto_traza = 0
    rigidos: list[tuple[dict, str]] = []
    vehiculos_ruta = raiz / "catalogos_privados" / "vehiculos.json"
    catalogo_vehiculos = cargar_catalogo_vehiculos(vehiculos_ruta)
    choferes = cargar_catalogo_json(raiz / "catalogos_privados" / "choferes.json")
    for fila in orden:
        grupos = grupos_candidatos(fila, protecciones, versiones)
        if not grupos:
            continue
        archivo = str(fila["archivo"])
        if grupos == ["patente_rampla"] and _tipo_vehiculo(catalogo_vehiculos, fila.get("patente_tracto")) == "CAMION_RIGIDO":
            rigidos.append((fila, "patente_rampla"))  # sin lectura
            continue
        if resolver_ruta_evidencia(raiz, archivo).ruta is None:
            continue  # el original puede llegar después; no consume intento
        traza = traza_con_bloques(raiz, archivo)
        if traza is not None:
            if gasto_traza >= limite_traza:
                continue
            gasto_traza += 1
        else:
            if gasto_ocr >= limite_ocr:
                continue
            gasto_ocr += 1
        plan.append((fila, grupos, traza))
        if gasto_ocr >= limite_ocr and gasto_traza >= limite_traza:
            break

    instante = reloj()
    lote = f"{instante.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    resumen["lote"] = lote
    propuestas: dict[str, list[tuple[Resultado, dict]]] = {}
    for fila, grupo in rigidos:
        propuestas.setdefault(fila["archivo"], []).append((
            Resultado(grupo, NO_APLICA_RIGIDO, detalle="Camión rígido de catálogo."), {"fuente": "CATALOGO"},
        ))

    propio = lector is None and bool(plan)
    if propio:
        lector = LectorDocumental(raiz, fabrica_ocr)
    try:
        for fila, grupos, traza in plan:
            if comprobar is not None:
                comprobar()
            archivo = str(fila["archivo"])
            ruta = resolver_ruta_evidencia(raiz, archivo).ruta
            referencia = sha_referencia(raiz, fila)
            meta = {"fuente": "TRAZA_OCR" if traza is not None else "OCR_COPIA"}
            if referencia and _sha256(ruta) != referencia:
                for grupo in grupos:
                    propuestas.setdefault(archivo, []).append((
                        Resultado(grupo, INTEGRIDAD, detalle="El original no coincide con su huella registrada."), meta))
                continue
            try:
                lectura = lector.leer(ruta, archivo, traza)
            except Exception as error:  # noqa: BLE001
                from atlas_core.ocr_provider import ProveedorOCRNoDisponible
                if isinstance(error, (ProveedorOCRNoDisponible, PermissionError)):
                    raise
                logger.warning("Relectura de %s fallida: %s", archivo, error)
                continue  # transitorio: no consume intento
            meta = {"fuente": lectura.fuente, "sha256_original": lectura.sha256_original}
            discrepa = _identidad_discrepa(fila, lectura.datos)
            for grupo in grupos:
                if discrepa:
                    resultado = Resultado(grupo, DISCREPANCIA_IDENTIDAD, detalle="Guía/transporte leídos no coinciden con la fila.")
                else:
                    resultado = evaluar_grupo(
                        grupo, fila, lectura, filas=filas, catalogo_vehiculos=catalogo_vehiculos,
                        ruta_vehiculos=vehiculos_ruta, choferes=choferes,
                    )
                propuestas.setdefault(archivo, []).append((resultado, meta))
    finally:
        if propio and lector is not None:
            lector.cerrar()

    resumen["intentados"] = len(plan)
    if not propuestas:
        return resumen

    cambios: list[dict[str, object]] = []
    escrito = False
    with bloqueo_sesion(actual, "revalidacion_dataset"):
        _, vigentes = _leer_dataset(dataset)
        por_archivo = {f.get("archivo"): f for f in vigentes}
        respaldo = None
        for archivo, resultados in propuestas.items():
            fila = por_archivo.get(archivo)
            if fila is None or archivo in protecciones.filas_bloqueadas:
                continue
            for resultado, meta in resultados:
                grupo = resultado.grupo
                clave = clave_capacidad(grupo, versiones)
                if estado_grupo(fila, grupo, protecciones) != NO_ENCONTRADO or _intento_vigente(fila, grupo, clave):
                    continue  # cambió mientras se leía: no se pisa nada
                registro = {**clave, "resultado": resultado.resultado, "en": instante.isoformat(),
                            "lote": lote, "actor": ACTOR, "detalle": resultado.detalle, **meta}
                if resultado.resultado == RECUPERADO:
                    anteriores = {c: fila.get(c, "") for c in resultado.valores}
                    if not all(ausente(v) for v in anteriores.values()):
                        continue
                    if respaldo is None:
                        respaldo = _respaldar_dataset(dataset, directorio_respaldo or _directorio_respaldo_local(), lote)
                    fila.update(resultado.valores)
                    registro.update({"valor_anterior": anteriores, "valor": dict(resultado.valores),
                                     "evidencia": resultado.evidencia})
                    cambios.append({"archivo": archivo, "numero_guia": fila.get("numero_guia", ""),
                                    "grupo": grupo, "anterior": anteriores, "nuevo": dict(resultado.valores),
                                    "evidencia": resultado.evidencia, **meta})
                _anotar_intento(fila, grupo, registro)
                escrito = True
                resumen["resultados"].append({"archivo": archivo, "numero_guia": fila.get("numero_guia", ""),
                                              "grupo": grupo, "resultado": resultado.resultado,
                                              "detalle": resultado.detalle, "valor": resultado.valores})
        if escrito:
            _escribir_dataset(dataset, vigentes)
        if cambios:
            _registrar_lote(actual, {"lote": lote, "en": instante.isoformat(), "actor": ACTOR,
                                     "version": VERSION_RECUPERACION_INCREMENTAL, "capacidades": versiones,
                                     "respaldo_local": str(respaldo) if respaldo else "", "cambios": cambios})
    guias = sorted({str(c["numero_guia"]).strip() for c in cambios if not ausente(c["numero_guia"])})
    resumen["recuperados"] = cambios
    resumen["guias_actualizadas"] = guias
    resumen["dataset_escrito"] = escrito
    if escrito and reconciliar:
        # Focal sobre las guías cambiadas (vacío = sólo republica estado y
        # reporte con la huella nueva); nunca reintenta su ruta.
        from atlas_core.reconciliacion_estado_derivado import reconciliar_estado_derivado
        objetivo = set(guias)
        resumen["reconciliacion"] = {
            k: v for k, v in reconciliar_estado_derivado(
                raiz_atlas=raiz, guias_objetivo=objetivo, guias_excluir_reintento_ruta=objetivo,
            ).items() if k in {"reconciliado", "motivo", "version"}
        }
    return resumen


def revertir_lote(*, raiz_atlas: str | Path, lote: str, reconciliar: bool = True) -> dict[str, object]:
    """Restaura el valor anterior de cada cambio del lote cuyo valor actual
    siga siendo el recuperado (nunca pisa algo que cambió después)."""
    from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico
    raiz = Path(raiz_atlas)
    actual = raiz / "operacion" / "actual"
    dataset = actual / "analisis_completo_guias.csv"
    registro_ruta = actual / NOMBRE_REGISTRO
    registro = json.loads(registro_ruta.read_text(encoding="utf-8"))
    entrada = next((l for l in registro.get("lotes", []) if l.get("lote") == lote), None)
    if entrada is None:
        raise ValueError(f"Lote {lote} no registrado.")
    revertidos, conservados = [], []
    with bloqueo_sesion(actual, "revalidacion_dataset"):
        _, filas = _leer_dataset(dataset)
        por_archivo = {f.get("archivo"): f for f in filas}
        for cambio in entrada.get("cambios", []):
            fila = por_archivo.get(cambio["archivo"])
            if fila is None or any(fila.get(c) != v for c, v in cambio["nuevo"].items()):
                conservados.append(cambio["archivo"])
                continue
            fila.update(cambio["anterior"])
            previo = intentos_de_fila(fila).get(cambio["grupo"], {})
            _anotar_intento(fila, cambio["grupo"], {**previo, "resultado": REVERTIDO})
            revertidos.append(str(fila.get("numero_guia") or ""))
        _escribir_dataset(dataset, filas)
        entrada["revertido_en"] = _ahora().isoformat()
        entrada["revertidos"] = revertidos
        escribir_json_atomico(registro_ruta, registro)
    if revertidos and reconciliar:
        from atlas_core.reconciliacion_estado_derivado import reconciliar_estado_derivado
        objetivo = {g for g in revertidos if not ausente(g)}
        reconciliar_estado_derivado(raiz_atlas=raiz, guias_objetivo=objetivo, guias_excluir_reintento_ruta=objetivo)
    return {"lote": lote, "revertidos": revertidos, "conservados": conservados}


def main(argv: list[str] | None = None) -> int:
    """Vista previa sobre una COPIA (exige el archivo marcador) o reversión."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raiz-atlas", required=True)
    sub = parser.add_subparsers(dest="orden", required=True)
    previa = sub.add_parser("previsualizar")
    previa.add_argument("--limite-ocr", type=int, default=10_000)
    previa.add_argument("--limite-traza", type=int, default=10_000)
    previa.add_argument("--salida", required=True)
    previa.add_argument("--sin-reconciliar", action="store_true")
    revertir = sub.add_parser("revertir")
    revertir.add_argument("--lote", required=True)
    args = parser.parse_args(argv)
    raiz = Path(args.raiz_atlas)
    if args.orden == "previsualizar":
        if not (raiz / MARCA_COPIA).is_file():
            parser.error(f"La vista previa sólo corre sobre una copia con el marcador {MARCA_COPIA}.")
        from atlas_core.ocr_provider import crear_proveedor_ocr, resolver_preferencia_ocr_desde_entorno
        resumen = recuperar_campos_ausentes(
            raiz_atlas=raiz, fabrica_ocr=lambda: crear_proveedor_ocr(resolver_preferencia_ocr_desde_entorno()),
            limite_ocr=args.limite_ocr, limite_traza=args.limite_traza,
            reconciliar=not args.sin_reconciliar, directorio_respaldo=raiz / "_respaldos_recuperacion",
        )
        Path(args.salida).write_text(json.dumps(resumen, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in resumen.items()}, ensure_ascii=False))
        return 0
    print(json.dumps(revertir_lote(raiz_atlas=raiz, lote=args.lote), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
