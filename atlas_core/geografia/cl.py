"""Adaptador Chile sobre la división político-administrativa oficial CUT."""
from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType

from .modelos import ResultadoNormalizacion, UnidadAdministrativa
from .motor import MotorNormalizacion, texto_normalizado

NIVEL_REGION = 1
NIVEL_PROVINCIA = 2
NIVEL_COMUNA = 3
RUTA_DATASET = Path(__file__).resolve().parents[2] / "catalogos_privados" / "geografia_chile.json"

PALABRAS_ESTRUCTURALES_DIRECCION = frozenset({
    "CAMINO", "CALLE", "AVENIDA", "AVDA", "PASAJE", "PJE", "RUTA", "SECTOR",
    "PARCELA", "LOTE", "VILLA", "POBLACION", "CONDOMINIO", "DIAGONAL",
    "COSTANERA", "ALAMEDA", "PARQUE", "FUNDO", "ROTONDA", "MANZANA", "SITIO",
    "PARADERO", "INTERIOR", "LOCAL", "PISO", "OFICINA", "BODEGA", "GALPON",
    "NORTE", "SUR", "ORIENTE", "PONIENTE",
})

_ALIAS_REGIONES = {
    "08": ("Del Bio-Bio", "Del BioBío", "Bio Bio"),
    "13": ("Metropolitana", "Region Metropolitana", "RM", "Santiago Area Metropolitana"),
    "09": ("Araucania",),
    "14": ("Region de Los Rios",),
    "10": ("Region de Los Lagos",),
    "06": ("O'Higgins", "Libertador Bernardo O'Higgins"),
    "12": ("Magallanes",),
    "11": ("Aysen",),
}


def _nombre_presentacion(nombre: str) -> str:
    palabras_menores = {"DE", "DEL", "Y", "LA", "LAS", "LOS"}
    partes = []
    for posicion, palabra in enumerate(str(nombre).split()):
        if posicion and palabra in palabras_menores:
            partes.append(palabra.lower())
        else:
            titulo = palabra[:1].upper() + palabra[1:].lower()
            partes.append("'".join(parte[:1].upper() + parte[1:] for parte in titulo.split("'")))
    return " ".join(partes)


class GeografiaChile:
    codigo_pais = "CL"
    codigos_pais = ("CL", "CHL")
    niveles = ("región", "provincia", "comuna")
    nivel_geocodificable = NIVEL_COMUNA
    nivel_region_geocodificacion = NIVEL_REGION

    def __init__(self, ruta_dataset: str | Path = RUTA_DATASET) -> None:
        filas = json.loads(Path(ruta_dataset).read_text(encoding="utf-8"))
        if len(filas) != 346:
            raise ValueError(f"dataset geográfico CL inválido: se esperaban 346 comunas, hay {len(filas)}")
        unidades: list[UnidadAdministrativa] = []
        regiones: dict[str, UnidadAdministrativa] = {}
        provincias: dict[str, UnidadAdministrativa] = {}
        for fila in filas:
            codigo_region = str(fila["codigo_region"])
            codigo_provincia = str(fila["codigo_provincia"])
            if codigo_region not in regiones:
                nombre_oficial = str(fila["nombre_region"])
                nombre = "Metropolitana" if codigo_region == "13" else _nombre_presentacion(nombre_oficial)
                regiones[codigo_region] = UnidadAdministrativa(
                    "CL", NIVEL_REGION, codigo_region, None, nombre, texto_normalizado(nombre),
                    aliases=tuple({nombre_oficial, fila["abreviatura_region"], *_ALIAS_REGIONES.get(codigo_region, ())}),
                    metadata=MappingProxyType({
                        "nombre_oficial": nombre_oficial,
                        "abreviatura_region": fila["abreviatura_region"],
                        "fuente": "SUBDERE CUT_2018_v04",
                    }),
                )
            if codigo_provincia not in provincias:
                nombre_oficial = str(fila["nombre_provincia"])
                provincias[codigo_provincia] = UnidadAdministrativa(
                    "CL", NIVEL_PROVINCIA, codigo_provincia, codigo_region,
                    _nombre_presentacion(nombre_oficial), texto_normalizado(nombre_oficial),
                    metadata=MappingProxyType({"nombre_oficial": nombre_oficial, "fuente": "SUBDERE CUT_2018_v04"}),
                )
        unidades.extend(regiones.values())
        unidades.extend(provincias.values())
        for fila in filas:
            nombre_oficial = str(fila["nombre_comuna"])
            unidades.append(UnidadAdministrativa(
                "CL", NIVEL_COMUNA, str(fila["codigo_comuna"]), str(fila["codigo_provincia"]),
                _nombre_presentacion(nombre_oficial), texto_normalizado(nombre_oficial),
                metadata=MappingProxyType({"nombre_oficial": nombre_oficial, "fuente": "SUBDERE CUT_2018_v04"}),
            ))
        self.unidades = tuple(unidades)
        self.motor = MotorNormalizacion(self.unidades, palabras_estructurales=PALABRAS_ESTRUCTURALES_DIRECCION)

    def normalizar(self, texto: str, nivel: int | None = None) -> ResultadoNormalizacion:
        return self.motor.normalizar(texto, nivel)

    def normalizar_direccion(self, texto: str) -> str:
        return self.motor.normalizar_direccion(texto, nivel=self.nivel_geocodificable)

    def buscar_por_codigo(self, codigo: str) -> UnidadAdministrativa | None:
        return self.motor.por_codigo.get(str(codigo))

    def parametros_geocodificacion(self, unidad: UnidadAdministrativa) -> dict[str, str]:
        parametros = {"codigo_pais": self.codigo_pais, "unidad": unidad.nombre_canonico}
        region = self._ancestro(unidad, NIVEL_REGION)
        if region is not None:
            parametros["region"] = region.nombre_canonico
        return parametros

    def compatibilidad_territorial(self, a: UnidadAdministrativa, b: UnidadAdministrativa) -> bool:
        if a.codigo_pais != self.codigo_pais or b.codigo_pais != self.codigo_pais:
            return False
        if a.codigo == b.codigo:
            return True
        codigos_a = self._cadena_codigos(a)
        codigos_b = self._cadena_codigos(b)
        return a.codigo in codigos_b or b.codigo in codigos_a

    def _ancestro(self, unidad: UnidadAdministrativa, nivel: int) -> UnidadAdministrativa | None:
        actual = unidad
        while actual.nivel > nivel and actual.codigo_padre:
            padre = self.buscar_por_codigo(actual.codigo_padre)
            if padre is None:
                return None
            actual = padre
        return actual if actual.nivel == nivel else None

    def _cadena_codigos(self, unidad: UnidadAdministrativa) -> set[str]:
        codigos = {unidad.codigo}
        actual = unidad
        while actual.codigo_padre:
            codigos.add(actual.codigo_padre)
            padre = self.buscar_por_codigo(actual.codigo_padre)
            if padre is None:
                break
            actual = padre
        return codigos
