"""Bloque R8 -- evidencia GPS REAL (OneLogis, ya almacenada en
`cache/telemetria/telemetria_cache.json` de la operación real), extraída
tal cual para reutilizarla en tests -- nunca coordenadas fabricadas.

Patente SB6486, 2026-08-06: la secuencia real muestra al vehículo
permaneciendo primero en la zona de AZA COLINA (09:59:42-10:14:30, con
detenciones reales de velocidad 0 dentro de esa geocerca), viajando
después hacia el sur (10:14:30-10:29:29, velocidades 25-88 km/h), y
permaneciendo luego en la zona de AZA RENCA en 3 tramos con motor
apagándose/encendiéndose entre medio (10:30:30-10:35:39 ENGINE_OFF;
10:40:13-10:47:02 ENGINE_OFF; 12:09:55-12:22:04 ENGINE_OFF, separados por
huecos de ~4,5 y ~83 min, ambos dentro de GAP_MAXIMO_MIN_PREDETERMINADO
-- se encadenan como una sola detención real), antes de partir
definitivamente a las 13:48:46 (30543835, 13,97 km). Corresponde
exactamente al patrón que Javier describió (permanencia con estados
detenido/apagado/encendido, luego salida) para AZA RENCA -- confirmado
por Javier, Bloque R8."""
from __future__ import annotations

VIAJES_SB6486_20260806 = [
    {"proveedor_trip_id": "30539854", "patente": "SB6486", "inicio": "2026-08-06 09:59:42", "fin": "2026-08-06 10:35:39", "distancia_km": 15.28},
    {"proveedor_trip_id": "30540537", "patente": "SB6486", "inicio": "2026-08-06 10:40:13", "fin": "2026-08-06 10:47:02", "distancia_km": 0.02},
    {"proveedor_trip_id": "30542187", "patente": "SB6486", "inicio": "2026-08-06 12:09:55", "fin": "2026-08-06 12:22:04", "distancia_km": 0.2},
    {"proveedor_trip_id": "30543835", "patente": "SB6486", "inicio": "2026-08-06 13:48:46", "fin": "2026-08-06 14:19:00", "distancia_km": 13.97},
]

# Primeros ~15 min del trip 30539854: permanencia real dentro de la
# geocerca de AZA COLINA (mismo polígono real ya confirmado en
# catalogos_privados/plantas.json, Bloque PLANTAS P3) -- velocidad 0 en
# 10:00:42-10:02:42 y 10:05:00-10:06:31, luego sale.
BREADCRUMBS_30539854_ZONA_COLINA = [
    {"latitud": -33.295107, "longitud": -70.72907, "timestamp": "2026-08-06 09:59:42", "velocidad": 9.0, "evento": "ENGINE_ON"},
    {"latitud": -33.295347, "longitud": -70.729398, "timestamp": "2026-08-06 09:59:57", "velocidad": 9.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.295432, "longitud": -70.729333, "timestamp": "2026-08-06 10:00:42", "velocidad": 0.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.295447, "longitud": -70.729328, "timestamp": "2026-08-06 10:01:42", "velocidad": 0.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.295687, "longitud": -70.729138, "timestamp": "2026-08-06 10:02:42", "velocidad": 0.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.29601, "longitud": -70.728835, "timestamp": "2026-08-06 10:03:27", "velocidad": 7.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.294892, "longitud": -70.730072, "timestamp": "2026-08-06 10:05:00", "velocidad": 0.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.294893, "longitud": -70.730085, "timestamp": "2026-08-06 10:06:26", "velocidad": 0.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.294892, "longitud": -70.730083, "timestamp": "2026-08-06 10:06:31", "velocidad": 0.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.294593, "longitud": -70.730357, "timestamp": "2026-08-06 10:07:22", "velocidad": 8.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.294738, "longitud": -70.732478, "timestamp": "2026-08-06 10:14:30", "velocidad": 62.0, "evento": "PERIODIC_ON"},
]

# Tramo final del trip 30539854 (llegada a la zona de AZA RENCA) + los 2
# trips siguientes completos -- la permanencia real que motivó este
# bloque.
BREADCRUMBS_30539854_ZONA_RENCA = [
    {"latitud": -33.387907, "longitud": -70.690772, "timestamp": "2026-08-06 10:26:30", "velocidad": 44.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.39083, "longitud": -70.689457, "timestamp": "2026-08-06 10:27:30", "velocidad": 28.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.393117, "longitud": -70.69029, "timestamp": "2026-08-06 10:28:22", "velocidad": 7.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.397913, "longitud": -70.68843, "timestamp": "2026-08-06 10:29:29", "velocidad": 37.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.399448, "longitud": -70.687848, "timestamp": "2026-08-06 10:30:02", "velocidad": 6.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.399675, "longitud": -70.687773, "timestamp": "2026-08-06 10:30:30", "velocidad": 0.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.399675, "longitud": -70.687773, "timestamp": "2026-08-06 10:31:30", "velocidad": 0.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.399673, "longitud": -70.687775, "timestamp": "2026-08-06 10:32:20", "velocidad": 0.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.399673, "longitud": -70.687768, "timestamp": "2026-08-06 10:33:39", "velocidad": 0.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.399672, "longitud": -70.68777, "timestamp": "2026-08-06 10:34:39", "velocidad": 0.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.399675, "longitud": -70.687767, "timestamp": "2026-08-06 10:35:39", "velocidad": 0.0, "evento": "ENGINE_OFF"},
]

BREADCRUMBS_30540537 = [
    {"latitud": -33.400407, "longitud": -70.687493, "timestamp": "2026-08-06 10:40:13", "velocidad": 4.0, "evento": "ENGINE_ON"},
    {"latitud": -33.400365, "longitud": -70.687477, "timestamp": "2026-08-06 10:41:05", "velocidad": 0.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.40036, "longitud": -70.687477, "timestamp": "2026-08-06 10:41:13", "velocidad": 0.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.40037, "longitud": -70.687455, "timestamp": "2026-08-06 10:44:02", "velocidad": 0.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.400372, "longitud": -70.687455, "timestamp": "2026-08-06 10:45:02", "velocidad": 0.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.40037, "longitud": -70.687452, "timestamp": "2026-08-06 10:46:02", "velocidad": 0.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.40037, "longitud": -70.687447, "timestamp": "2026-08-06 10:47:02", "velocidad": 0.0, "evento": "ENGINE_OFF"},
]

BREADCRUMBS_30542187 = [
    {"latitud": -33.400395, "longitud": -70.687447, "timestamp": "2026-08-06 12:09:55", "velocidad": 5.0, "evento": "ENGINE_ON"},
    {"latitud": -33.400503, "longitud": -70.687343, "timestamp": "2026-08-06 12:10:06", "velocidad": 4.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.400602, "longitud": -70.687337, "timestamp": "2026-08-06 12:10:14", "velocidad": 5.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.400625, "longitud": -70.687527, "timestamp": "2026-08-06 12:11:06", "velocidad": 0.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.400317, "longitud": -70.68937, "timestamp": "2026-08-06 12:16:26", "velocidad": 0.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.40031, "longitud": -70.689362, "timestamp": "2026-08-06 12:17:26", "velocidad": 0.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.400312, "longitud": -70.689348, "timestamp": "2026-08-06 12:20:04", "velocidad": 0.0, "evento": "PERIODIC_ON"},
    {"latitud": -33.400322, "longitud": -70.68935, "timestamp": "2026-08-06 12:22:04", "velocidad": 0.0, "evento": "ENGINE_OFF"},
]

# Centroide real de los puntos con velocidad 0 dentro de la geocerca de
# AZA RENCA (los 2 tramos con más puntos, 30539854-final + 30540537) --
# usado para `punto_ruteo_latitud/longitud`, mismo criterio que ya usa
# AZA COLINA (breadcrumb real más cercano/representativo, nunca una
# coordenada fabricada).
PUNTO_RUTEO_RENCA_REAL = (-33.399989, -70.687632)
