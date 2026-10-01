"""Tavily como buscador externo de la investigación adaptativa B1.

Tavily devuelve resultados web (title/url/content/raw_content/score), no una
respuesta generativa. La conversión a `CandidatoExterno` es determinista: sólo
se extrae un nombre que la fuente publica literalmente, que empieza por el
prefijo documental y termina en una forma societaria explícita; nunca se
completan palabras. La verificación y la convergencia reutilizan
`candidatos_externos` (`_verificar`, `evaluar_nombre_obra`).

La credencial (`TAVILY_API_KEY`) nunca se incluye en errores, trazas ni caché.
"""
from __future__ import annotations

import json
import re
import socket
import unicodedata
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request

from atlas_core.almacenamiento_portable import ruta_cache
from atlas_core.atlas_ia.buscador_web import (
    BuscadorWebNoDisponible, Cita, CredencialBuscadorWebAusente, RepositorioCacheBusquedaWeb,
    RespuestaBusquedaWeb, TransporteHTTP, _transporte_urllib,
)
from atlas_core.atlas_ia.candidatos_externos import (
    CandidatoExterno, ResultadoBusquedaAdaptativa, _verificar, clave_nombre_societario, normalizar,
)
from atlas_core.atlas_ia.credenciales import resolver_tavily_api_key

PROVEEDOR_TAVILY = "tavily"
NOMBRE_ARCHIVO_CACHE_TAVILY = "busqueda_web_tavily_cache.json"
_URL_BUSQUEDA = "https://api.tavily.com/search"
_MAX_RAW_CONTENT = 4000
_VENTANA = 300
# Formas societarias que cierran un nombre publicado. Sólo LIMITADA/LTDA son
# equivalentes entre sí (ver `clave_nombre_societario`).
_FORMA_SOCIETARIA = r"(?:LIMITADA|LTDA\.?|SPA|S\.\s?A\.|EIRL|E\.I\.R\.L\.)"
_RUT = re.compile(r"(?<![\d.])(\d{1,2})\.?(\d{3})\.?(\d{3})\s*-\s*([\dK])(?![0-9A-Z])")


def repositorio_cache_tavily() -> RepositorioCacheBusquedaWeb:
    # Archivo propio: una consulta Tavily nunca se confunde con una respuesta Sonar.
    return RepositorioCacheBusquedaWeb(ruta_cache("busqueda_web") / NOMBRE_ARCHIVO_CACHE_TAVILY)


class BuscadorWebTavily:
    """Ejecuta UNA búsqueda Tavily (search_depth=basic). Nunca decide nada."""

    nombre = PROVEEDOR_TAVILY

    def __init__(self, *, api_key: str | None = None, timeout: float = 30.0,
                 transporte: TransporteHTTP = _transporte_urllib, max_resultados: int = 10) -> None:
        self._api_key = resolver_tavily_api_key(api_key)
        self._timeout = timeout
        self._transporte = transporte
        self._max_resultados = max_resultados

    def buscar(self, consulta: str) -> RespuestaBusquedaWeb:
        if not self._api_key:
            raise CredencialBuscadorWebAusente("No hay TAVILY_API_KEY configurada en este entorno.")
        cuerpo = json.dumps({
            "query": str(consulta), "search_depth": "basic", "max_results": self._max_resultados,
            "include_raw_content": "text", "include_answer": False, "include_usage": True,
        }, ensure_ascii=False).encode("utf-8")
        solicitud = Request(_URL_BUSQUEDA, data=cuerpo, method="POST")
        solicitud.add_header("authorization", f"Bearer {self._api_key}")
        solicitud.add_header("content-type", "application/json")
        try:
            respuesta = self._transporte(solicitud, self._timeout)
        except HTTPError as error:
            raise BuscadorWebNoDisponible(f"Tavily devolvió HTTP {error.code}.") from None
        except (TimeoutError, socket.timeout):
            raise BuscadorWebNoDisponible("Tiempo de espera agotado en la búsqueda Tavily.") from None
        except (URLError, OSError):
            raise BuscadorWebNoDisponible("Sin conexión para la búsqueda Tavily.") from None
        if not 200 <= respuesta.estado < 300:
            raise BuscadorWebNoDisponible(f"Tavily devolvió HTTP {respuesta.estado}.")
        try:
            datos = json.loads(respuesta.cuerpo)
            brutos = datos["results"]
            if not isinstance(brutos, list):
                raise TypeError
        except (KeyError, TypeError, json.JSONDecodeError):
            raise BuscadorWebNoDisponible("Respuesta Tavily sin resultados válidos.") from None
        resultados = [{
            "title": str(r.get("title") or ""), "url": str(r.get("url") or ""),
            "content": str(r.get("content") or ""),
            "raw_content": str(r.get("raw_content") or "")[:_MAX_RAW_CONTENT],
            "score": r.get("score"),
        } for r in brutos if isinstance(r, dict) and r.get("url")]
        uso = datos.get("usage") if isinstance(datos.get("usage"), dict) else {}
        return RespuestaBusquedaWeb(
            consulta=str(consulta),
            respuesta_texto=json.dumps({"proveedor": PROVEEDOR_TAVILY, "resultados": resultados,
                                        "creditos": uso.get("credits")}, ensure_ascii=False, sort_keys=True),
            citas=tuple(Cita(r["title"], r["url"]) for r in resultados),
            proveedor=self.nombre, modelo="tavily-search-basic",
            fecha=datetime.now(timezone.utc).isoformat(),
        )


def construir_consulta_tavily(entidad: str, direccion: str, localidad: str) -> str:
    """Consulta corta sólo con datos documentales; nunca agrega palabras."""
    partes = [str(entidad or "").strip(), str(direccion or "").strip()]
    if localidad and normalizar(localidad) not in normalizar(direccion):
        partes.append(str(localidad).strip())
    return " ".join(" ".join(p for p in partes if p).split())[:400]


def _plegar(texto: str) -> str:
    """Mayúsculas sin tildes, con la MISMA longitud que el original (índices alineados)."""
    salida = []
    for c in texto:
        base = unicodedata.normalize("NFKD", c)[:1] or c
        mayuscula = base.upper()
        salida.append(mayuscula if len(mayuscula) == 1 else base)
    return "".join(salida)


def _rut_valido(cuerpo: str, dv: str) -> bool:
    suma, factor = 0, 2
    for digito in reversed(cuerpo):
        suma += int(digito) * factor
        factor = 2 if factor == 7 else factor + 1
    esperado = 11 - suma % 11
    return dv == {10: "K", 11: "0"}.get(esperado, str(esperado))


def _ruts(texto: str) -> set[str]:
    encontrados = set()
    for m in _RUT.finditer(_plegar(texto)):
        cuerpo = m.group(1) + m.group(2) + m.group(3)
        if _rut_valido(cuerpo, m.group(4)):
            encontrados.add(f"{m.group(1)}.{m.group(2)}.{m.group(3)}-{m.group(4)}")
    return encontrados


def _nombres_publicados(texto: str, prefijo: list[str]) -> list[tuple[str, int, int]]:
    """(nombre original, inicio, fin) que empiezan por el prefijo y cierran en forma societaria."""
    patron = re.compile(
        r"(?<![A-Z0-9])" + r"\s+".join(re.escape(t) for t in prefijo)
        + r"(?:\s+[A-Z][A-Z&]*){0,4}?\s+" + _FORMA_SOCIETARIA + r"(?![A-Z0-9])")
    plegado = _plegar(texto)
    nombres = []
    for m in patron.finditer(plegado):
        siguiente = texto[m.end():].lstrip()  # original: NFKD convierte "…" en "."
        # Un nombre seguido de "…" puede estar cortado: no se usa.
        if siguiente.startswith(("…", "..")):
            continue
        nombres.append((" ".join(texto[m.start():m.end()].split()), m.start(), m.end()))
    return nombres


def candidatos_desde_tavily(respuesta: RespuestaBusquedaWeb, entidad_documental: str) -> list[CandidatoExterno]:
    """Convierte resultados Tavily en candidatos verificados, sin inferencia."""
    prefijo = normalizar(entidad_documental).split()
    if len(prefijo) < 2:
        return []
    try:
        resultados = json.loads(respuesta.respuesta_texto).get("resultados") or []
    except (ValueError, AttributeError):
        return []
    candidatos: list[CandidatoExterno] = []
    for resultado in resultados:
        if not isinstance(resultado, dict) or not resultado.get("url"):
            continue
        por_clave: dict[str, list[tuple[str, str, set[str]]]] = {}
        for campo in ("title", "content", "raw_content"):
            texto = str(resultado.get(campo) or "")
            for nombre, inicio, fin in _nombres_publicados(texto, prefijo):
                ventana = texto[max(0, inicio - _VENTANA):fin + _VENTANA]
                por_clave.setdefault(clave_nombre_societario(nombre), []).append((nombre, ventana, _ruts(ventana)))
        for ocurrencias in por_clave.values():
            # Preferir la forma completa LIMITADA; si no, la primera publicada.
            nombre, ventana, _ = next((o for o in ocurrencias if normalizar(o[0]).endswith(" LIMITADA")),
                                      ocurrencias[0])
            ruts = set().union(*(o[2] for o in ocurrencias))
            rut = next(iter(ruts)) if len(ruts) == 1 else ""
            if rut and rut not in _ruts(ventana):
                ventana = next(o[1] for o in ocurrencias if rut in o[2])
            verificado = _verificar(CandidatoExterno(
                nombre=nombre, rut=rut, url=str(resultado["url"]), fragmento=ventana[:600],
                tipo_fuente="WEB_TAVILY", consulta=respuesta.consulta, consultado_en=respuesta.fecha,
            ), ventana)
            if verificado.verificacion == "VERIFICADA":
                candidatos.append(verificado)
    return candidatos


def buscar_adaptativamente_tavily(*, buscador, entidad: str, direccion: str,
                                  localidad: str) -> ResultadoBusquedaAdaptativa:
    """Una consulta documental; los candidatos salen sólo de texto publicado."""
    resultado = ResultadoBusquedaAdaptativa()
    consulta = construir_consulta_tavily(entidad, direccion, localidad)
    try:
        nuevos = candidatos_desde_tavily(buscador.buscar(consulta), entidad)
        error = ""
    except Exception as exc:  # noqa: BLE001 -- mismo contrato que buscar_adaptativamente
        nuevos, error = [], f"{type(exc).__name__}: {str(exc)[:160]}"
    resultado.candidatos.extend(nuevos)
    resultado.traza.append({"incertidumbre": "IDENTIDAD_NOMBRE", "proveedor": PROVEEDOR_TAVILY,
                            "consulta": consulta, "candidatos": [c.a_dict() for c in nuevos], "error": error})
    return resultado
