"""Candidatos externos verificables para la investigación B1 de revisiones.

Usa el buscador web ya configurado por Atlas. Sonar descubre candidatos;
esta capa exige URL citada y comprueba los anclajes en el texto de esa URL.
Ni una respuesta del buscador ni una semejanza nominal se vuelven hechos.
"""
from __future__ import annotations

import html
import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


def normalizar(texto: object) -> str:
    base = unicodedata.normalize("NFKD", str(texto or "").upper())
    base = "".join(c for c in base if not unicodedata.combining(c))
    return " ".join(re.findall(r"[A-Z0-9]+", base))


def _tokens_via(texto: str) -> tuple[str, ...]:
    omitidos = {"AV", "AVENIDA", "CALLE", "CAM", "CAMINO", "DE", "DEL", "LOS", "LAS", "EL", "LA"}
    return tuple(t for t in normalizar(texto).split() if t not in omitidos and len(t) >= 3)


def _distancia(a: str, b: str) -> int:
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        nueva = [i]
        for j, cb in enumerate(b, 1):
            nueva.append(min(nueva[-1] + 1, anterior[j] + 1, anterior[j - 1] + (ca != cb)))
        anterior = nueva
    return anterior[-1]


def comparar_texto(a: str, b: str) -> str:
    na, nb = normalizar(a), normalizar(b)
    if not na or not nb:
        return "NO_APORTA"
    if na == nb:
        return "COINCIDE"
    ta, tb = na.split(), nb.split()
    if any(x == y or (len(x) >= 5 and len(y) >= 5 and _distancia(x, y) <= 2)
           for x in ta for y in tb):
        return "COMPATIBLE"
    return "CONTRADICE"


def comparar_localidad(a: str, b: str) -> str:
    na, nb = normalizar(a), normalizar(b)
    if not na or not nb:
        return "NO_APORTA"
    if na == nb:
        return "COINCIDE"
    if min(len(na), len(nb)) >= 7 and _distancia(na, nb) <= 2:
        return "COMPATIBLE"
    return "CONTRADICE"


def comparar_calle(a: str, b: str) -> str:
    ta, tb = _tokens_via(a), _tokens_via(b)
    if not ta or not tb:
        return "NO_APORTA"
    if ta == tb:
        return "COINCIDE"
    if all(any(x == y or (len(x) >= 4 and len(y) >= 4 and
                           _distancia(x, y) <= (1 if min(len(x), len(y)) < 5 else 2))
               for y in tb) for x in ta):
        return "COMPATIBLE"
    return "CONTRADICE"


def comparar_entidad(a: str, b: str) -> str:
    ignorar = {"SA", "SPA", "LTDA", "LIMITADA", "EMPRESA", "SOCIEDAD", "CONSTRUCTORA", "CENTRO"}
    ta = [t for t in normalizar(a).split() if t not in ignorar and len(t) >= 4]
    tb = [t for t in normalizar(b).split() if t not in ignorar and len(t) >= 4]
    if not ta or not tb:
        return "NO_APORTA"
    iguales = [x for x in ta if any(x == y or (len(x) >= 6 and len(y) >= 6 and
                                           _distancia(x, y) <= 2) for y in tb)]
    if ta == tb:
        return "COINCIDE"
    return "COMPATIBLE" if len(iguales) >= 2 or any(len(x) >= 8 for x in iguales) else "CONTRADICE"


def comparar_numero(ocr: str, candidato: str) -> str:
    a, b = normalizar(ocr).replace(" ", ""), normalizar(candidato).replace(" ", "")
    if not a or not b:
        return "NO_APORTA"
    if a == b:
        return "COINCIDE"
    if len(a) == len(b) and any(c.isalpha() for c in a) and all(c.isdigit() for c in b):
        if sum(x != y for x, y in zip(a, b)) == 1:
            return "COMPATIBLE"
    return "CONTRADICE"


class _TextoHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.partes: list[str] = []
        self.oculto = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.oculto += 1
        if tag == "meta":
            datos = dict(attrs)
            if datos.get("content"):
                self.partes.append(datos["content"])

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.oculto:
            self.oculto -= 1

    def handle_data(self, data):
        if not self.oculto:
            self.partes.append(data)


@lru_cache(maxsize=128)
def obtener_texto_fuente(url: str) -> str:
    """Lectura acotada de páginas públicas; nunca consulta redes internas."""
    def validar_url(destino: str) -> None:
        partes = urlsplit(destino)
        host = (partes.hostname or "").lower()
        if partes.scheme != "https" or not host or "." not in host or host in {"localhost", "127.0.0.1"}:
            raise ValueError("URL pública HTTPS requerida")
        if re.fullmatch(r"\d+(?:\.\d+){3}", host):
            raise ValueError("IP literal no permitida")

    validar_url(url)
    solicitud = Request(url, headers={"User-Agent": "Mozilla/5.0 (Atlas research)"})
    class SinRedireccion(HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            validar_url(newurl)
            return super().redirect_request(request, fp, code, msg, headers, newurl)

    with build_opener(SinRedireccion).open(solicitud, timeout=12) as respuesta:
        if "text/html" not in respuesta.headers.get("Content-Type", "text/html"):
            raise ValueError("Fuente no HTML")
        cuerpo = respuesta.read(1_000_001)
    if len(cuerpo) > 1_000_000:
        raise ValueError("Fuente demasiado grande")
    analizador = _TextoHTML()
    analizador.feed(cuerpo.decode("utf-8", "replace"))
    return " ".join(html.unescape(" ".join(analizador.partes)).split())


@dataclass(frozen=True)
class CandidatoExterno:
    nombre: str = ""
    razon_social: str = ""
    direccion: str = ""
    numero: str = ""
    comuna: str = ""
    ciudad: str = ""
    region: str = ""
    rut: str = ""
    codigo: str = ""
    tipo_entidad: str = ""
    tipo_fuente: str = ""
    url: str = ""
    fragmento: str = ""
    fecha: str = ""
    consultado_en: str = ""
    consulta: str = ""
    verificacion: str = "NO_VERIFICABLE"
    fragmento_fuente: str = ""
    anclajes_verificados: tuple[str, ...] = ()

    def a_dict(self) -> dict:
        return {**self.__dict__, "anclajes_verificados": list(self.anclajes_verificados)}


def _nombre_publicado(candidato: CandidatoExterno) -> str:
    """Nombre usable para una obra: el nombre comercial o la razón social publicada."""
    return str(candidato.nombre or candidato.razon_social or "").strip()


def _parsear_candidatos(texto: str) -> list[dict]:
    limpio = texto.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        datos = json.loads(limpio)
    except (ValueError, TypeError):
        return []
    lista = datos.get("candidatos", []) if isinstance(datos, dict) else []
    return [x for x in lista[:8] if isinstance(x, dict)]


def _verificar(candidato: CandidatoExterno, texto: str) -> CandidatoExterno:
    from dataclasses import replace

    fuente = normalizar(texto)
    via = _tokens_via(candidato.direccion)
    comuna = normalizar(candidato.comuna)
    numero = normalizar(candidato.numero)
    nombre_publicado = _nombre_publicado(candidato)
    nombre = normalizar(nombre_publicado)
    rut = normalizar(candidato.rut).replace(" ", "")
    # Se exige coocurrencia local de dirección, número y comuna. Una
    # página con varias sucursales no puede mezclar valores de filas lejanas.
    fragmento = ""
    anclajes: list[str] = []
    if via and numero:
        for hallazgo in re.finditer(rf"\b{re.escape(numero)}\b", texto, re.IGNORECASE):
            ventana_original = texto[max(0, hallazgo.start() - 220):hallazgo.end() + 220]
            ventana = normalizar(ventana_original)
            if all(t in ventana for t in via) and (not comuna or comuna in ventana):
                fragmento = ventana_original
                anclajes.extend(["DIRECCION", "NUMERO"])
                if comuna:
                    anclajes.append("COMUNA")
                break
    elif nombre and rut and nombre.split()[0] in fuente and rut in fuente.replace(" ", ""):
        fragmento = texto[:440]
        anclajes.extend(["ENTIDAD", "RUT"])
    elif nombre:
        # Un nombre completo publicado por una fuente citada también es
        # evidencia útil para NOMBRAR una obra. No prueba propiedad del
        # predio, contratación ni titularidad: sólo que esa denominación
        # existe en esa fuente. La convergencia entre fuentes se exige más
        # abajo, antes de proponerla a una persona.
        nombre_tokens = [t for t in nombre.split() if len(t) >= 4]
        if nombre_tokens and all(t in fuente for t in nombre_tokens):
            fragmento = texto[:440]
            anclajes.extend(["ENTIDAD", "NOMBRE_COMPLETO"])
    if not fragmento:
        return candidato
    # Si la fuente enlaza además el nombre en la misma vecindad, se marca.
    nombre_tokens = [t for t in nombre.split() if len(t) >= 5]
    fragmento_normalizado = normalizar(fragmento)
    if nombre_tokens and any(t in fragmento_normalizado for t in nombre_tokens):
        anclajes.append("ENTIDAD")
    if nombre_tokens and all(t in fragmento_normalizado for t in nombre_tokens):
        anclajes.append("NOMBRE_COMPLETO")
    if rut and "ENTIDAD" in anclajes and rut in fuente.replace(" ", ""):
        anclajes.append("RUT")
    fecha_verificada = candidato.fecha if candidato.fecha and candidato.fecha in texto else ""
    return replace(candidato, nombre=nombre_publicado, verificacion="VERIFICADA", fragmento_fuente=fragmento,
                   fecha=fecha_verificada,
                   anclajes_verificados=tuple(dict.fromkeys(anclajes)))


def extraer_candidatos_respuesta(respuesta, *, leer_fuente: Callable[[str], str] = obtener_texto_fuente) -> list[CandidatoExterno]:
    citadas = tuple(dict.fromkeys(c.url for c in respuesta.citas if c.url))[:12]
    resultado = []
    cache_paginas: dict[str, str | None] = {}
    for bruto in _parsear_candidatos(respuesta.respuesta_texto):
        url = str(bruto.get("url") or "").strip()
        candidato = CandidatoExterno(**{
            k: str(bruto.get(k) or "").strip() for k in CandidatoExterno.__dataclass_fields__
            if k in bruto and k not in {"consulta", "fecha", "consultado_en", "verificacion", "fragmento_fuente", "anclajes_verificados"}
        }, consulta=respuesta.consulta, fecha=str(bruto.get("fecha") or ""), consultado_en=respuesta.fecha)
        urls = (url,) if url in citadas else citadas if not url else ()
        for url_citada in urls:
            if url_citada not in cache_paginas:
                try:
                    cache_paginas[url_citada] = leer_fuente(url_citada)
                except (OSError, ValueError, TimeoutError):
                    cache_paginas[url_citada] = None
            if cache_paginas[url_citada]:
                from dataclasses import replace
                localizado = _verificar(replace(candidato, url=url_citada), cache_paginas[url_citada])
                if localizado.verificacion == "VERIFICADA":
                    resultado.append(localizado)
        if not any(c is candidato or (c.consulta == candidato.consulta and
                   c.nombre == candidato.nombre and c.numero == candidato.numero and
                   c.direccion == candidato.direccion) for c in resultado):
            resultado.append(candidato)
    return resultado


def _numero_documental(direccion: str) -> str:
    # Sólo un token corto en la línea de dirección. Un RUT/código largo no
    # es número de calle; una letra inicial OCR conserva la incertidumbre.
    for token in re.findall(r"\b[A-Z]?\d{1,5}\b", normalizar(direccion)):
        if len(token) <= 5:
            return token
    return ""


def _calle_documental(direccion: str, localidad: str) -> str:
    texto = normalizar(direccion)
    comuna = normalizar(localidad)
    if comuna and comuna in texto:
        texto = texto.split(comuna, 1)[0]
    return re.split(r"\b[A-Z]?\d{1,5}\b", texto, maxsplit=1)[0].strip()


def _dominio(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def localidad_documental(direccion: str) -> str:
    """Comuna mencionada literalmente, según el catálogo geográfico Atlas."""
    from atlas_core.geografia.cl import RUTA_DATASET

    try:
        comunas = json.loads(RUTA_DATASET.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    texto = f" {normalizar(direccion)} "
    halladas = [str(f["nombre_comuna"]) for f in comunas
                if f" {normalizar(f['nombre_comuna'])} " in texto]
    return max(halladas, key=len, default="")


def evaluar_candidatos(*, candidatos: list[CandidatoExterno], obra: str,
                       cliente: str, rut_cliente: str, direccion_documental: str,
                       localidad: str, historial: list[dict] | None = None) -> dict:
    """Reglas estructurales, sin puntuación acumulada de similitudes.

    Una dirección resoluble exige dos dominios independientes verificados,
    calle y comuna compatibles con el original, número no contradictorio y
    relación de la misma entidad/establecimiento con la dirección.
    """
    numero_doc = _numero_documental(direccion_documental)
    grupos: list[list[CandidatoExterno]] = []
    for candidato in candidatos:
        if not candidato.direccion or not candidato.numero or not candidato.comuna:
            continue
        grupo = next((g for g in grupos if
                      normalizar(g[0].numero) == normalizar(candidato.numero) and
                      normalizar(g[0].comuna) == normalizar(candidato.comuna) and
                      comparar_calle(g[0].direccion, candidato.direccion) in {"COINCIDE", "COMPATIBLE"}), None)
        if grupo is None:
            grupos.append([candidato])
        else:
            grupo.append(candidato)
    evaluados = []
    for grupo in grupos:
        patron = grupo[0]
        calle = comparar_calle(_calle_documental(direccion_documental, localidad), patron.direccion)
        comuna = comparar_localidad(localidad, patron.comuna)
        numero = comparar_numero(numero_doc, patron.numero)
        verificados = [c for c in grupo if c.verificacion == "VERIFICADA"]
        vinculados = [c for c in verificados if "ENTIDAD" in c.anclajes_verificados and (
            comparar_entidad(obra, c.nombre) in {"COINCIDE", "COMPATIBLE"} or
            comparar_entidad(cliente, c.nombre) in {"COINCIDE", "COMPATIBLE"})]
        dominios = sorted({_dominio(c.url) for c in vinculados})
        entidad = "COMPATIBLE" if vinculados else "NO_VERIFICABLE" if verificados else "NO_APORTA"
        ruts = [c.rut for c in vinculados if "RUT" in c.anclajes_verificados and c.rut]
        rut_doc = normalizar(rut_cliente).replace(" ", "")
        rut = ("COINCIDE" if all(normalizar(x).replace(" ", "") == rut_doc for x in ruts)
               else "CONTRADICE") if ruts and rut_cliente else "NO_APORTA"
        campos = {"CALLE": calle, "NUMERO": numero, "COMUNA": comuna,
                  "ENTIDAD": entidad, "RUT": rut}
        conflicto = any(v == "CONTRADICE" for v in campos.values())
        # Si el documento no trae número, dos fuentes independientes que
        # sí lo publican pueden proponerlo para confirmación humana. No se
        # infiere ni se completa un número: el propuesto debe venir literal
        # en cada fuente verificada. Un número documental distinto siempre
        # bloquea la propuesta.
        numero_compatible = numero in {"COINCIDE", "COMPATIBLE", "NO_APORTA"}
        resoluble = (not conflicto and calle in {"COINCIDE", "COMPATIBLE"}
                     and comuna in {"COINCIDE", "COMPATIBLE"}
                     and numero_compatible
                     and entidad == "COMPATIBLE" and len(dominios) >= 2)
        nombres_completos = [c.nombre for c in vinculados if "NOMBRE_COMPLETO" in c.anclajes_verificados]
        evaluados.append({"direccion": f"{patron.direccion} {patron.numero}, {patron.comuna}",
                          "nombre_candidato": max(nombres_completos, key=lambda n: len(normalizar(n)), default=""),
                          "comparaciones": campos, "fuentes_independientes": dominios,
                          "fuentes": [c.a_dict() for c in grupo], "resoluble": resoluble,
                          "historial": list(historial or [])})
    plausibles = [e for e in evaluados if e["resoluble"]]
    # Dos destinos distintos con todos los anclajes suficientes: no elegir.
    if len(plausibles) == 1:
        estado, ganador = "PROPUESTA_RESOLUBLE", plausibles[0]
        razon = "Dos fuentes independientes verificadas y anclajes documentales compatibles"
    elif len(plausibles) > 1:
        estado, ganador = "ABSTENCION", None
        razon = "Dos candidatos plausibles con evidencia convergente"
    else:
        estado, ganador = "ABSTENCION", None
        razon = "Falta corroboración independiente de dirección y entidad, o hay contradicción estructural"
    return {"estado": estado, "propuesta": ganador, "razon": razon,
            "candidatos_evaluados": evaluados, "numero_documental": numero_doc}


def evaluar_nombre_obra(*, candidatos: list[CandidatoExterno], obra_documental: str) -> dict:
    """Evalúa una ampliación de nombre operacional, nunca una relación legal.

    El nombre abreviado del documento debe ser compatible con el nombre
    completo publicado. Se requieren dos dominios web independientes que
    muestren ese mismo nombre completo; no se exige que la fuente pruebe
    propiedad, mandato, contrato ni vínculo jurídico con el cliente.
    """
    documental = normalizar(obra_documental)

    def compatible(nombre: str) -> bool:
        # Una ampliación debe conservar literalmente el prefijo documental;
        # no basta compartir una palabra distintiva. Así no se inventan
        # términos ni se confunden dos razones sociales parecidas.
        base, completo = documental.split(), normalizar(nombre).split()
        return len(base) >= 2 and len(completo) > len(base) and completo[:len(base)] == base

    grupos: dict[str, list[CandidatoExterno]] = {}
    for candidato in candidatos:
        if candidato.verificacion != "VERIFICADA" or "NOMBRE_COMPLETO" not in candidato.anclajes_verificados:
            continue
        nombre = _nombre_publicado(candidato)
        if not compatible(nombre):
            continue
        clave = normalizar(nombre)
        if clave:
            grupos.setdefault(clave, []).append(candidato)

    evaluados = []
    for grupo in grupos.values():
        dominios = sorted({_dominio(c.url) for c in grupo if _dominio(c.url)})
        evaluados.append({
            "nombre_candidato": max((_nombre_publicado(c) for c in grupo), key=lambda n: len(normalizar(n))),
            "fuentes_independientes": dominios,
            "fuentes": [c.a_dict() for c in grupo],
            "resoluble": len(dominios) >= 2,
        })
    if not evaluados and any(normalizar(_nombre_publicado(c)) == documental for c in candidatos
           if c.verificacion == "VERIFICADA"):
        return {"estado": "SIN_CAMBIOS", "propuesta": None,
                "razon": "El nombre documental ya está completo en la evidencia pública",
                "candidatos_evaluados": evaluados}
    plausibles = [e for e in evaluados if e["resoluble"]]
    # Una fuente publicada que muestra otra ampliación compatible ya es una
    # contradicción nominal relevante: no se escoge entre dos razones sociales.
    if len(evaluados) > 1:
        return {"estado": "ABSTENCION", "propuesta": None,
                "razon": "Fuentes públicas presentan nombres completos contradictorios",
                "candidatos_evaluados": evaluados}
    if len(plausibles) == 1:
        return {"estado": "PROPUESTA_RESOLUBLE", "propuesta": plausibles[0],
                "razon": "Dos fuentes independientes publican el mismo nombre operacional completo",
                "candidatos_evaluados": evaluados}
    if len(plausibles) > 1:
        return {"estado": "ABSTENCION", "propuesta": None,
                "razon": "Dos nombres completos plausibles requieren aclaración humana",
                "candidatos_evaluados": evaluados}
    return {"estado": "ABSTENCION", "propuesta": None,
            "razon": "Falta corroboración independiente del nombre operacional completo",
            "candidatos_evaluados": evaluados}


@dataclass
class ResultadoBusquedaAdaptativa:
    candidatos: list[CandidatoExterno] = field(default_factory=list)
    traza: list[dict] = field(default_factory=list)


def _consulta(objetivo: str, entidad: str, direccion: str, localidad: str, excluir: str = "") -> str:
    return (
        f"Investiga {objetivo} de {entidad!r} en {localidad!r}. Dirección documental OCR: {direccion!r}. "
        f"{('Busca una fuente independiente de ' + excluir + '. ') if excluir else ''}"
        "Devuelve SOLO JSON válido {\"candidatos\":[{\"nombre\":\"\",\"razon_social\":\"\","
        "\"direccion\":\"\",\"numero\":\"\",\"comuna\":\"\",\"ciudad\":\"\",\"region\":\"\","
        "\"rut\":\"\",\"codigo\":\"\",\"tipo_entidad\":\"\",\"tipo_fuente\":\"\","
        "\"url\":\"\",\"fragmento\":\"\",\"fecha\":\"\"}]}. "
        "Usa sólo páginas citadas. No completes datos ausentes ni copies el OCR como hecho verificado. "
        "Distingue establecimientos distintos de una misma empresa. Máximo 3 candidatos."
    )


def buscar_adaptativamente(*, buscador, entidad: str, direccion: str, localidad: str,
                           leer_fuente: Callable[[str], str] = obtener_texto_fuente,
                           max_consultas: int = 3) -> ResultadoBusquedaAdaptativa:
    """Descubre y contrasta candidatos, con consulta siguiente ligada a hallazgos."""
    resultado = ResultadoBusquedaAdaptativa()
    pendientes = [("IDENTIDAD_Y_DIRECCION", _consulta("identidad y dirección", entidad, direccion, localidad))]
    hechas: set[str] = set()
    while pendientes and len(hechas) < max_consultas:
        objetivo, consulta = pendientes.pop(0)
        if consulta in hechas:
            continue
        hechas.add(consulta)
        try:
            respuesta = buscador.buscar(consulta)
            nuevos = extraer_candidatos_respuesta(respuesta, leer_fuente=leer_fuente)
            error = ""
        except Exception as exc:
            nuevos, error = [], f"{type(exc).__name__}: {str(exc)[:160]}"
        resultado.candidatos.extend(nuevos)
        resultado.traza.append({"incertidumbre": objetivo, "consulta": consulta,
                                "candidatos": [c.a_dict() for c in nuevos], "error": error})
        if objetivo == "IDENTIDAD_Y_DIRECCION":
            # La corroboración de nombre no depende de que una razón social
            # tenga publicada la dirección de la entrega. Se consulta una
            # fuente de otro dominio para validar la expansión nominal.
            corroborar_nombre = None
            nombres_vistos: set[str] = set()
            for candidato in nuevos:
                nombre = _nombre_publicado(candidato)
                clave_nombre = normalizar(nombre)
                if not clave_nombre or clave_nombre in nombres_vistos:
                    continue
                nombres_vistos.add(clave_nombre)
                corroborar_nombre = (f"CORROBORAR_NOMBRE:{clave_nombre}",
                    _consulta("corroboración independiente del nombre operacional completo", nombre,
                              "", "", urlsplit(candidato.url).hostname or ""))
                break
            # El segundo paso depende de direcciones realmente encontradas.
            # Se investiga tanto la coincidente como la rival, hasta el tope.
            vistos: set[tuple[str, str]] = set()
            for candidato in nuevos:
                clave = (normalizar(candidato.direccion), normalizar(candidato.numero))
                if not all(clave) or clave in vistos:
                    continue
                vistos.add(clave)
                destino = f"{candidato.direccion} {candidato.numero}"
                pendientes.append((f"CORROBORAR:{destino}",
                    _consulta("corroboración de establecimiento y dirección", candidato.nombre or entidad,
                              destino, candidato.comuna or localidad, urlsplit(candidato.url).hostname or "")))
                if len(pendientes) >= max_consultas - 1:
                    break
            if corroborar_nombre is not None:
                pendientes.append(corroborar_nombre)
    return resultado
