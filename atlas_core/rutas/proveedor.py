"""Puerto de proveedor y doble simulado sin acceso a red."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion,
    Coordenadas,
    EstadoRuta,
    ResultadoGeocodificacion,
    ResultadoRuta,
)


class ProveedorRutas(Protocol):
    nombre: str
    version: str

    def geocodificar(self, direccion: str) -> ResultadoGeocodificacion: ...

    def calcular_ruta(
        self, origen: Coordenadas, destino: Coordenadas, perfil: str
    ) -> ResultadoRuta: ...


@dataclass
class ProveedorRutasSimulado:
    """Proveedor determinista cuyos resultados son inyectados por prueba o CLI."""

    geocodificaciones: dict[str, ResultadoGeocodificacion] = field(default_factory=dict)
    resultado_ruta: ResultadoRuta = field(default_factory=lambda: ResultadoRuta(
        EstadoRuta.RUTA_CALCULADA, 12.5, 24.0, "RESULTADO_SINTETICO"
    ))
    nombre: str = "simulado"
    version: str = "1"
    llamadas_geocodificacion: int = 0
    llamadas_ruta: int = 0

    def geocodificar(self, direccion: str) -> ResultadoGeocodificacion:
        self.llamadas_geocodificacion += 1
        return self.geocodificaciones.get(
            direccion,
            ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(Coordenadas(-20.0, -10.0), "UBICACION DEMO"),),
                "CANDIDATO_SINTETICO",
            ),
        )

    def calcular_ruta(
        self, origen: Coordenadas, destino: Coordenadas, perfil: str
    ) -> ResultadoRuta:
        self.llamadas_ruta += 1
        return self.resultado_ruta
