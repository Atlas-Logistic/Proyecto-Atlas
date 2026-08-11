"""Puerto de posición de vehículo por GPS (Bloque RUTAS R1).

Contrato agnóstico de proveedor para resolver "dónde estaba la patente X
cerca del instante Y" -- pensado para un proveedor histórico de GPS
(Onelogis u otro). La integración GPS real hoy disponible en Atlas
(`Atlas-Viajes-Desktop-Restaurado/src/gps_logic.js`, vía un endpoint propio
`.../gps/ultimas-posiciones`) solo expone la ÚLTIMA posición conocida de
cada patente, no un histórico consultable por timestamp -- por eso no hay
todavía un adaptador real aquí, solo el contrato y un doble determinista
para pruebas. Ver docs/BITACORA_TECNICA_CRONOLOGICA.md (bloque RUTAS R1)
para el detalle de la auditoría.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol

from atlas_core.rutas.modelos import Coordenadas


class EstadoPosicionVehiculo(str, Enum):
    POSICION_ENCONTRADA = "POSICION_ENCONTRADA"
    SIN_DATOS = "SIN_DATOS"
    PROVEEDOR_NO_DISPONIBLE = "PROVEEDOR_NO_DISPONIBLE"


@dataclass(frozen=True)
class ResultadoPosicionVehiculo:
    estado: EstadoPosicionVehiculo
    coordenadas: Coordenadas | None = None
    timestamp_gps: str = ""
    proveedor: str = ""
    motivo: str = ""


class ProveedorPosicionVehiculo(Protocol):
    nombre: str

    def obtener_posicion(
        self, patente: str, instante: datetime
    ) -> ResultadoPosicionVehiculo: ...


@dataclass
class ProveedorPosicionVehiculoSimulado:
    """Doble determinista: posiciones inyectadas por prueba/CLI, sin red.

    Mismo patrón que `ProveedorRutasSimulado` (atlas_core/rutas/proveedor.py).
    """

    posiciones: dict[str, ResultadoPosicionVehiculo] = field(default_factory=dict)
    nombre: str = "simulado"
    llamadas: int = 0

    def obtener_posicion(
        self, patente: str, instante: datetime
    ) -> ResultadoPosicionVehiculo:
        self.llamadas += 1
        return self.posiciones.get(
            str(patente or "").strip().upper(),
            ResultadoPosicionVehiculo(
                EstadoPosicionVehiculo.SIN_DATOS,
                proveedor=self.nombre,
                motivo="SIN_DATOS_INYECTADOS",
            ),
        )
