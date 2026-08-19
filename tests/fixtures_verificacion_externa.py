"""Evidencia externa REAL, capturada por el agente el 2026-08-19 usando
sus propias herramientas de búsqueda (fuera del proceso Python -- el
código de producción no tiene hoy ningún proveedor de búsqueda
configurado, ver `atlas_core.verificacion_externa`). Se guarda aquí, tal
cual se obtuvo, para poder auditarla y para validar el caso SIGRO de este
bloque contra una consulta genuina -- nunca inventada ni simulada.

Fuentes originales (consultadas 2026-08-19):
- https://www.mercantil.com/empresa/empresa-constructora-sigro-sa/las-condes/300070828/eng/
- https://web.sigro.cl/en/home/
- búsqueda "Supermercado Señor de los Milagros" Mejillones -- sin resultados
  directos; hallazgo colateral: dos supermercados reales confirmados en la
  misma calle (Av. Almirante Latorre), Mejillones."""
from __future__ import annotations

from atlas_core.verificacion_externa import TIPO_FUENTE_CORPORATIVO, TIPO_FUENTE_DIRECTORIO, EvidenciaExterna

FECHA_CONSULTA_REAL = "2026-08-19T21:00:00+00:00"

EVIDENCIA_SIGRO_DIRECTORIO = EvidenciaExterna(
    fuente="mercantil.com", tipo_fuente=TIPO_FUENTE_DIRECTORIO,
    url="https://www.mercantil.com/empresa/empresa-constructora-sigro-sa/las-condes/300070828/eng/",
    fecha_consulta=FECHA_CONSULTA_REAL,
    razon_social="Empresa Constructora Sigro S.A.", rut="89.037.500-6",
    direccion="Avenida Isidora Goyenechea 3477 Piso 3", comuna="Las Condes",
    campos_corroborados=("razon_social", "rut", "direccion", "comuna"),
)

EVIDENCIA_SIGRO_CORPORATIVA = EvidenciaExterna(
    fuente="web.sigro.cl", tipo_fuente=TIPO_FUENTE_CORPORATIVO, url="https://web.sigro.cl/en/home/",
    fecha_consulta=FECHA_CONSULTA_REAL,
    razon_social="SIGRO S.A.", direccion="Narciso Goycolea 4040 Piso 1", comuna="Vitacura",
    campos_corroborados=("razon_social", "direccion"),
)

# Búsqueda real para "Supermercado Señor de los Milagros" en Mejillones no
# encontró NINGUNA coincidencia -- se representa como tupla vacía, nunca
# como un resultado fabricado. El hallazgo colateral real (dos
# supermercados confirmados en la misma calle, con nombre distinto) se
# documenta en la bitácora técnica, no como `EvidenciaExterna` (no
# corrobora NADA sobre "Señor de los Milagros" -- sería forzar una
# conclusión que la evidencia no sostiene).
EVIDENCIA_SUPERMERCADO_MILAGROS: tuple[EvidenciaExterna, ...] = ()
