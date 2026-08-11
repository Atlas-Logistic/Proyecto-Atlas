from dataclasses import dataclass

from atlas_core.rutas.origen_documental import resolver_origen_documental


@dataclass(frozen=True)
class _PlantaFicticia:
    nombre: str
    estado_calidad: str = "CONFIRMADA"
    estado_vigencia: str = "ACTIVA"


PLANTAS = [_PlantaFicticia("AZA RENCA"), _PlantaFicticia("AZA COLINA")]


def test_documental_renca_resuelve():
    textos = ["ACEROS AZA S A CASA MATRIZ PLANTA RENCA LA UNION 3070 RENCA SANTIAGO CHILE"]
    resultado = resolver_origen_documental(textos, PLANTAS)
    assert resultado is not None
    assert resultado.nombre == "AZA RENCA"


def test_documental_colina_resuelve():
    textos = ["ACEROS AZA S A CASA MATRIZ PLANTA COLINA PANAMERICANA NORTE 18500 COLINA SANTIAGO CHILE"]
    resultado = resolver_origen_documental(textos, PLANTAS)
    assert resultado is not None
    assert resultado.nombre == "AZA COLINA"


def test_documental_ignora_directorio_de_sucursales():
    """Caso real que motivó el fix histórico (2c5c764): el directorio de
    sucursales impreso en toda guía AZA menciona "Sucursal Colina", que sin
    el corte generaría una segunda coincidencia y anularía el voto real de
    RENCA."""
    textos = [
        "ACEROS AZA S A CASA MATRIZ PLANTA RENCA LA UNION 3070 RENCA SANTIAGO "
        "CHILE Sucursal Antofagasta Calle Hector Gomez Cobo Sucursal Temuco "
        "Calle Milano Sucursal Talcahuano Jaime Repullo Sucursal Colina "
        "Panamericana Norte KM 18 Colina Santiago"
    ]
    resultado = resolver_origen_documental(textos, PLANTAS)
    assert resultado is not None
    assert resultado.nombre == "AZA RENCA"


def test_documental_sin_evidencia_abstiene():
    textos = ["GUIA DE DESPACHO SEÑOR(ES) EBEMA SA RUT 83.585.400-0"]
    assert resolver_origen_documental(textos, PLANTAS) is None


def test_documental_ambiguo_abstiene():
    """Si el encabezado (antes del corte por SUCURSAL) menciona ambas
    plantas de forma completa, no puede haber una única planta -> se
    abstiene, no elige por orden ni por cercanía."""
    textos = ["ACEROS AZA CASA MATRIZ PLANTA RENCA Y PLANTA COLINA AMBAS ACTIVAS"]
    assert resolver_origen_documental(textos, PLANTAS) is None


def test_documental_ignora_plantas_no_confirmadas():
    plantas_pendiente = [_PlantaFicticia("AZA RENCA", estado_calidad="PENDIENTE")]
    textos = ["ACEROS AZA CASA MATRIZ PLANTA RENCA LA UNION 3070 RENCA"]
    assert resolver_origen_documental(textos, plantas_pendiente) is None


def test_documental_ignora_plantas_inactivas():
    plantas_inactiva = [_PlantaFicticia("AZA RENCA", estado_vigencia="INACTIVA")]
    textos = ["ACEROS AZA CASA MATRIZ PLANTA RENCA LA UNION 3070 RENCA"]
    assert resolver_origen_documental(textos, plantas_inactiva) is None
