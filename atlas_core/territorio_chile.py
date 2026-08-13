"""Catálogo territorial determinista de Chile (Bloque INTELIGENCIA N1).

Atlas opera en Chile. Este módulo es la fuente de verdad LOCAL de qué
comunas/regiones existen -- nunca consulta una fuente externa en tiempo
de ejecución (ni siquiera para normalizar un typo obvio). El snapshot de
`_COMUNAS_POR_REGION` está adaptado de un dataset público estable
(https://github.com/jromerof/regiones-chile, consultado 2026-08-12),
corrigiendo a mano los errores tipográficos evidentes de esa fuente
(p. ej. "Quilcura"->"Quilicura", "Vitcarua"->"Vitacura",
"Couhaique"->"Coyhaique", "Vicotira"->"Victoria", "Guateicas"->"Guaitecas")
contra los nombres oficiales de comuna. 16 regiones, 345 comunas.

Principio de diseño (ver docstring de `normalizar_comuna`): un valor OCR
nunca se trata como verdad literal, pero tampoco se "corrige" sin
evidencia -- EXACTA/NORMALIZADA_SEGURA/AMBIGUA/NO_RECONOCIDA son estados
explícitos y trazables, nunca una sustitución silenciosa.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

# --- Fase B: snapshot territorial ------------------------------------

_COMUNAS_POR_REGION: dict[str, tuple[str, ...]] = {
    "Arica y Parinacota": ("Arica", "Camarones", "Putre", "General Lagos"),
    "Tarapacá": ("Iquique", "Alto Hospicio", "Pozo Almonte", "Camiña", "Colchane", "Huara", "Pica"),
    "Antofagasta": (
        "Antofagasta", "Mejillones", "Sierra Gorda", "Taltal", "Calama", "Ollagüe",
        "San Pedro de Atacama", "Tocopilla", "María Elena",
    ),
    "Atacama": (
        "Copiapó", "Caldera", "Tierra Amarilla", "Chañaral", "Diego de Almagro",
        "Vallenar", "Alto del Carmen", "Freirina", "Huasco",
    ),
    "Coquimbo": (
        "La Serena", "Coquimbo", "Andacollo", "La Higuera", "Paihuano", "Vicuña",
        "Illapel", "Canela", "Los Vilos", "Salamanca", "Ovalle", "Combarbalá",
        "Monte Patria", "Punitaqui", "Río Hurtado",
    ),
    "Valparaíso": (
        "Valparaíso", "Casablanca", "Concón", "Juan Fernández", "Puchuncaví",
        "Quintero", "Viña del Mar", "Isla de Pascua", "Los Andes", "Calle Larga",
        "Rinconada", "San Esteban", "La Ligua", "Cabildo", "Papudo", "Petorca",
        "Zapallar", "Quillota", "La Calera", "Hijuelas", "La Cruz", "Nogales",
        "San Antonio", "Algarrobo", "Cartagena", "El Quisco", "El Tabo",
        "Santo Domingo", "San Felipe", "Catemu", "Llaillay", "Panquehue",
        "Putaendo", "Santa María", "Quilpué", "Limache", "Olmué", "Villa Alemana",
    ),
    "Metropolitana": (
        "Santiago", "Cerrillos", "Cerro Navia", "Conchalí", "El Bosque",
        "Estación Central", "Huechuraba", "Independencia", "La Cisterna",
        "La Florida", "La Granja", "La Pintana", "La Reina", "Las Condes",
        "Lo Barnechea", "Lo Espejo", "Lo Prado", "Macul", "Maipú", "Ñuñoa",
        "Pedro Aguirre Cerda", "Peñalolén", "Providencia", "Pudahuel", "Quilicura",
        "Quinta Normal", "Recoleta", "Renca", "San Joaquín", "San Miguel",
        "San Ramón", "Vitacura", "Puente Alto", "Pirque", "San José de Maipo",
        "Colina", "Lampa", "Til Til", "San Bernardo", "Buin", "Calera de Tango",
        "Paine", "Melipilla", "Alhué", "Curacaví", "María Pinto", "San Pedro",
        "Talagante", "El Monte", "Isla de Maipo", "Padre Hurtado", "Peñaflor",
    ),
    "Libertador General Bernardo O'Higgins": (
        "Rancagua", "Codegua", "Coinco", "Coltauco", "Doñihue", "Graneros",
        "Las Cabras", "Machalí", "Malloa", "Mostazal", "Olivar", "Peumo",
        "Pichidegua", "Quinta de Tilcoco", "Rengo", "Requínoa", "San Vicente",
        "Pichilemu", "La Estrella", "Litueche", "Marchihue", "Navidad",
        "Paredones", "San Fernando", "Chépica", "Chimbarongo", "Lolol",
        "Nancagua", "Palmilla", "Peralillo", "Placilla", "Pumanque", "Santa Cruz",
    ),
    "Maule": (
        "Talca", "Constitución", "Curepto", "Empedrado", "Maule", "Pelarco",
        "Pencahue", "Río Claro", "San Clemente", "San Rafael", "Cauquenes",
        "Chanco", "Pelluhue", "Curicó", "Hualañé", "Licantén", "Molina",
        "Rauco", "Romeral", "Sagrada Familia", "Teno", "Vichuquén", "Linares",
        "Colbún", "Longaví", "Parral", "Retiro", "San Javier", "Villa Alegre",
        "Yerbas Buenas",
    ),
    "Ñuble": (
        "San Carlos", "San Fabián", "Coihueco", "Ñiquén", "San Nicolás",
        "Bulnes", "Chillán", "Chillán Viejo", "El Carmen", "Pemuco", "Pinto",
        "Quillón", "San Ignacio", "Yungay", "Quirihue", "Cobquecura", "Coelemu",
        "Ninhue", "Portezuelo", "Ránquil", "Treguaco",
    ),
    "Biobío": (
        "Concepción", "Coronel", "Chiguayante", "Florida", "Hualqui", "Lota",
        "Penco", "San Pedro de la Paz", "Santa Juana", "Talcahuano", "Tomé",
        "Hualpén", "Lebu", "Arauco", "Cañete", "Contulmo", "Curanilahue",
        "Los Álamos", "Tirúa", "Los Ángeles", "Antuco", "Cabrero", "Laja",
        "Mulchén", "Nacimiento", "Negrete", "Quilaco", "Quilleco", "San Rosendo",
        "Santa Bárbara", "Tucapel", "Yumbel", "Alto Biobío",
    ),
    "La Araucanía": (
        "Temuco", "Carahue", "Cunco", "Curarrehue", "Freire", "Galvarino",
        "Gorbea", "Lautaro", "Loncoche", "Melipeuco", "Nueva Imperial",
        "Padre Las Casas", "Perquenco", "Pitrufquén", "Pucón", "Saavedra",
        "Teodoro Schmidt", "Toltén", "Vilcún", "Villarrica", "Cholchol",
        "Angol", "Collipulli", "Curacautín", "Ercilla", "Lonquimay",
        "Los Sauces", "Lumaco", "Purén", "Renaico", "Traiguén", "Victoria",
    ),
    "Los Ríos": (
        "Valdivia", "Corral", "Lanco", "Los Lagos", "Máfil", "Mariquina",
        "Paillaco", "Panguipulli", "La Unión", "Futrono", "Lago Ranco", "Río Bueno",
    ),
    "Los Lagos": (
        "Puerto Montt", "Calbuco", "Cochamó", "Fresia", "Frutillar",
        "Los Muermos", "Llanquihue", "Maullín", "Puerto Varas", "Castro",
        "Ancud", "Chonchi", "Curaco de Vélez", "Dalcahue", "Puqueldón",
        "Queilén", "Quellón", "Quemchi", "Quinchao", "Osorno", "Puerto Octay",
        "Purranque", "Puyehue", "Río Negro", "San Juan de la Costa",
        "San Pablo", "Chaitén", "Futaleufú", "Hualaihué", "Palena",
    ),
    "Aysén del General Carlos Ibáñez del Campo": (
        "Coyhaique", "Lago Verde", "Aysén", "Cisnes", "Guaitecas", "Cochrane",
        "O'Higgins", "Tortel", "Chile Chico", "Río Ibáñez",
    ),
    "Magallanes y de la Antártica Chilena": (
        "Punta Arenas", "Laguna Blanca", "Río Verde", "San Gregorio",
        "Cabo de Hornos", "Antártica", "Porvenir", "Primavera", "Timaukel",
        "Natales", "Torres del Paine",
    ),
}


def _texto_simple_territorio(texto: str) -> str:
    """Mayúsculas, sin acentos, espacios colapsados -- normalización
    ortográfica básica compartida por comuna/región (Fase C.1)."""
    normalizado = unicodedata.normalize("NFD", str(texto or "").strip().upper())
    sin_acentos = "".join(c for c in normalizado if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[.,;:]", " ", sin_acentos)).strip()


# clave simple -> (comuna canónica, región canónica)
_INDICE_COMUNAS: dict[str, tuple[str, str]] = {
    _texto_simple_territorio(comuna): (comuna, region)
    for region, comunas in _COMUNAS_POR_REGION.items()
    for comuna in comunas
}
_NOMBRES_SIMPLES_COMUNAS: tuple[str, ...] = tuple(_INDICE_COMUNAS.keys())

# Regiones: comparación exacta tolerante (mayúsculas/acentos) -- sin
# fuzzy propio, las variantes reales observadas (p. ej. "Del Bio-Bio" vs
# "Biobío") se cubren con un pequeño mapa de alias documentados, no con
# adivinación.
_ALIAS_REGION: dict[str, str] = {
    _texto_simple_territorio(alias): region
    for region, alias in (
        ("Biobío", "Del Bio-Bio"), ("Biobío", "Del BioBío"), ("Biobío", "Bio Bio"),
        ("Metropolitana", "Region Metropolitana"), ("Metropolitana", "RM"),
        ("La Araucanía", "Araucania"),
        ("Los Ríos", "Region de Los Rios"),
        ("Los Lagos", "Region de Los Lagos"),
        ("Libertador General Bernardo O'Higgins", "O'Higgins"),
        ("Libertador General Bernardo O'Higgins", "Libertador Bernardo O'Higgins"),
        ("Magallanes y de la Antártica Chilena", "Magallanes"),
        ("Aysén del General Carlos Ibáñez del Campo", "Aysen"),
    )
}
for _region_valida in _COMUNAS_POR_REGION:
    _ALIAS_REGION[_texto_simple_territorio(_region_valida)] = _region_valida


def region_valida(texto: str) -> str | None:
    """Nombre canónico de región si `texto` (con alias conocidos) la
    identifica sin ambigüedad; None si no se reconoce."""
    return _ALIAS_REGION.get(_texto_simple_territorio(texto))


# --- Fase C: normalización de comunas ---------------------------------

ESTADO_COMUNA_EXACTA = "EXACTA"
ESTADO_COMUNA_NORMALIZADA_SEGURA = "NORMALIZADA_SEGURA"
ESTADO_COMUNA_AMBIGUA = "AMBIGUA"
ESTADO_COMUNA_NO_RECONOCIDA = "NO_RECONOCIDA"

# Calibrado sobre los dos casos reales del bloque (CAUQUBNES/CADQUENES vs
# CAUQUENES, ambos ~0.889 de similitud, una sola posición distinta) CON
# evidencia negativa real: un umbral de 0.82 dejaba pasar "CAMINO"
# (palabra de dirección común, "camino Los Pinos") como corrupción de la
# comuna real "Camiña" (0.833), y "PARQUE" como corrupción de "Pirque"
# (0.833) -- ambos falsos positivos reales encontrados al validar este
# mismo bloque contra la tanda operacional. 0.87 mantiene los dos casos
# reales del bloque (0.889/0.923) y rechaza ambos falsos positivos.
UMBRAL_COMUNA_DIFUSA = 0.87
MARGEN_AMBIGUEDAD_COMUNA = 0.06
LONGITUD_MINIMA_COMUNA_DIFUSA = 4

# Vocabulario estructural de direcciones chilenas -- nunca es candidato a
# comuna, sin importar la similitud (defensa adicional, no solo el
# umbral): son palabras genéricas que aparecen en casi cualquier
# dirección real y, con 345 comunas en el universo, alguna terminará
# pareciéndose a una por azar. Lista acotada a la evidencia real de este
# bloque (palabras de estructura de dirección, nunca nombres propios).
_PALABRAS_ESTRUCTURALES_DIRECCION = frozenset({
    "CAMINO", "CALLE", "AVENIDA", "AVDA", "PASAJE", "PJE", "RUTA", "SECTOR",
    "PARCELA", "LOTE", "VILLA", "POBLACION", "CONDOMINIO", "DIAGONAL",
    "COSTANERA", "ALAMEDA", "PARQUE", "FUNDO", "ROTONDA", "MANZANA", "SITIO",
    "PARADERO", "INTERIOR", "LOCAL", "PISO", "OFICINA", "BODEGA", "GALPON",
    "NORTE", "SUR", "ORIENTE", "PONIENTE",
})


@dataclass(frozen=True)
class ResultadoNormalizacionComuna:
    """Decisión trazable y sin efectos laterales -- nunca sustituye en
    silencio. `valor_original` siempre se conserva."""

    estado: str
    valor_original: str
    comuna: str | None = None
    region: str | None = None
    similitud: float | None = None


def normalizar_comuna(texto: str) -> ResultadoNormalizacionComuna:
    """Normaliza un token/frase contra el universo cerrado de comunas de
    Chile (Fase C).

    1. Normalización ortográfica básica (mayúsculas/acentos/espacios).
    2. Coincidencia EXACTA con una comuna válida -> EXACTA.
    3. Si no, fuzzy conservador contra el universo cerrado -- acepta
       SOLO si hay un candidato único, con similitud >= umbral y margen
       claro sobre el segundo candidato (nunca por cercanía relativa
       sola) -> NORMALIZADA_SEGURA.
    4. Dos o más candidatos casi empatados -> AMBIGUA (nunca elige por
       orden ni por ser "el primero").
    5. Nada suficientemente parecido -> NO_RECONOCIDA (nunca inventa).

    Un token corto (< `LONGITUD_MINIMA_COMUNA_DIFUSA`) nunca se
    normaliza por fuzzy -- demasiado alto el riesgo de coincidencia
    espuria con un fragmento de otra palabra.
    """
    original = str(texto or "").strip()
    simple = _texto_simple_territorio(original)
    if not simple:
        return ResultadoNormalizacionComuna(ESTADO_COMUNA_NO_RECONOCIDA, original)

    exacta = _INDICE_COMUNAS.get(simple)
    if exacta:
        comuna, region = exacta
        return ResultadoNormalizacionComuna(ESTADO_COMUNA_EXACTA, original, comuna, region, 1.0)

    if len(simple) < LONGITUD_MINIMA_COMUNA_DIFUSA:
        return ResultadoNormalizacionComuna(ESTADO_COMUNA_NO_RECONOCIDA, original)

    if simple in _PALABRAS_ESTRUCTURALES_DIRECCION:
        # Nunca por fuzzy, sin importar la similitud -- ver bug real
        # documentado junto a `UMBRAL_COMUNA_DIFUSA`.
        return ResultadoNormalizacionComuna(ESTADO_COMUNA_NO_RECONOCIDA, original)

    candidatos = sorted(
        (
            (difflib.SequenceMatcher(None, simple, clave).ratio(), clave)
            for clave in _NOMBRES_SIMPLES_COMUNAS
        ),
        key=lambda par: (-par[0], par[1]),
    )
    mejor_similitud, mejor_clave = candidatos[0]
    if mejor_similitud < UMBRAL_COMUNA_DIFUSA:
        return ResultadoNormalizacionComuna(ESTADO_COMUNA_NO_RECONOCIDA, original, similitud=mejor_similitud)

    if len(candidatos) > 1 and mejor_similitud - candidatos[1][0] < MARGEN_AMBIGUEDAD_COMUNA:
        return ResultadoNormalizacionComuna(ESTADO_COMUNA_AMBIGUA, original, similitud=mejor_similitud)

    comuna, region = _INDICE_COMUNAS[mejor_clave]
    return ResultadoNormalizacionComuna(
        ESTADO_COMUNA_NORMALIZADA_SEGURA, original, comuna, region, mejor_similitud
    )


# --- Fase D/M: contexto territorial dentro de una dirección completa ---


def normalizar_direccion_con_comunas(texto: str) -> str:
    """Limpia, palabra por palabra, los tokens de una dirección completa
    (p. ej. `despachar_a_crudo`) que sean una corrupción OCR segura de
    una comuna real -- para desbloquear geocodificación sin tocar la
    calle/número (Fase D/M).

    Caso real (guías 464698/464699): el documento imprime la comuna DOS
    veces (campo COMUNA + campo CIUDAD, frecuente en guías chilenas); el
    OCR corrompió una de las dos ("CADQUENES"/"CAUQUBNES") mientras la
    otra quedó legible ("CAUQUENES"). Nunca produce un duplicado: si la
    forma canónica YA aparece como palabra exacta en otra parte del
    texto, el token corrupto se DESCARTA (era redundante); si no
    aparece, se REEMPLAZA por la forma correcta. Tokens ambiguos o no
    reconocidos se dejan intactos -- nunca se fuerza una corrección sin
    evidencia suficiente.
    """
    texto_original = str(texto or "")
    palabras = texto_original.split()
    if not palabras:
        return texto_original

    palabras_simples = [_texto_simple_territorio(p) for p in palabras]
    resultado: list[str] = []
    for indice, palabra in enumerate(palabras):
        decision = normalizar_comuna(palabra)
        if decision.estado != ESTADO_COMUNA_NORMALIZADA_SEGURA:
            resultado.append(palabra)
            continue
        forma_canonica_simple = _texto_simple_territorio(decision.comuna or "")
        ya_presente = any(
            otra == forma_canonica_simple
            for otro_indice, otra in enumerate(palabras_simples)
            if otro_indice != indice
        )
        if ya_presente:
            continue  # token redundante/corrupto -- se descarta, no se duplica
        resultado.append(decision.comuna or palabra)

    limpio = " ".join(resultado)
    return limpio if limpio else texto_original
