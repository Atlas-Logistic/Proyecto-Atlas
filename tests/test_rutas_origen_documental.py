from dataclasses import dataclass

from atlas_core.rutas.origen_documental import resolver_origen_documental


@dataclass(frozen=True)
class _PlantaFicticia:
    nombre: str
    estado_calidad: str = "CONFIRMADA"
    estado_vigencia: str = "ACTIVA"


PLANTAS = [_PlantaFicticia("AZA RENCA"), _PlantaFicticia("AZA COLINA")]


# ---------------------------------------------------------------------
# Bloque CORRECCIÓN ESTRUCTURAL DE ORIGEN DOCUMENTAL AZA -- caso real
# 472647/472648, transporte 0000355231: "CASA MATRIZ PLANTA RENCA" es el
# domicilio legal/societario (terminología SII estándar, impresa en TODA
# guía de la empresa, sin importar la planta real de despacho) -- Javier
# confirma que el membrete/encabezado corporativo NUNCA debe tratarse
# como evidencia de origen, bajo ningún contexto. Antes de este bloque,
# estos mismos textos SÍ resolvían (comportamiento ahora corregido).
# ---------------------------------------------------------------------


def test_membrete_casa_matriz_nunca_resuelve_origen():
    textos = ["ACEROS AZA S A CASA MATRIZ PLANTA RENCA LA UNION 3070 RENCA SANTIAGO CHILE"]
    assert resolver_origen_documental(textos, PLANTAS) is None


def test_membrete_casa_matriz_otra_planta_tampoco_resuelve():
    textos = ["ACEROS AZA S A CASA MATRIZ PLANTA COLINA PANAMERICANA NORTE 18500 COLINA SANTIAGO CHILE"]
    assert resolver_origen_documental(textos, PLANTAS) is None


def test_membrete_con_directorio_de_sucursales_tampoco_resuelve():
    """Caso real 472648: ni la casa matriz ni el listado de sucursales de
    contacto (impreso a continuación) identifican la planta real de
    despacho."""
    textos = [
        "ACEROS AZA S A CASA MATRIZ PLANTA RENCA LA UNION 3070 RENCA SANTIAGO "
        "CHILE Sucursal Antofagasta Calle Hector Gomez Cobo Sucursal Temuco "
        "Calle Milano Sucursal Talcahuano Jaime Repullo Sucursal Colina "
        "Panamericana Norte KM 18 Colina Santiago"
    ]
    assert resolver_origen_documental(textos, PLANTAS) is None


def test_solo_directorio_de_sucursales_sin_casa_matriz_tampoco_resuelve():
    """Un listado de sucursales de contacto tampoco es planta de origen,
    exista o no, además, una declaración de casa matriz."""
    textos = ["EMPRESA GENERICA SPA Sucursal Colina Panamericana Norte KM 18 Colina Santiago"]
    assert resolver_origen_documental(textos, PLANTAS) is None


def test_campo_explicito_de_origen_si_resuelve():
    """Evidencia REAL y contextual (un campo que declara la planta de
    despacho, no el domicilio legal de la empresa) sigue resolviendo --
    la corrección elimina el membrete/sucursales, nunca toda posibilidad
    de evidencia documental."""
    textos = ["GUIA DE DESPACHO PLANTA ORIGEN AZA COLINA RUT 12.345.678-9"]
    resultado = resolver_origen_documental(textos, PLANTAS)
    assert resultado is not None
    assert resultado.nombre == "AZA COLINA"


def test_documental_sin_evidencia_abstiene():
    textos = ["GUIA DE DESPACHO SEÑOR(ES) EBEMA SA RUT 83.585.400-0"]
    assert resolver_origen_documental(textos, PLANTAS) is None


def test_documental_ambiguo_abstiene():
    """Si la zona utilizable del encabezado (antes de CASA MATRIZ/SUCURSAL)
    menciona ambas plantas de forma completa, no puede haber una única
    planta -> se abstiene, no elige por orden ni por cercanía."""
    textos = ["ACEROS AZA PLANTA RENCA Y PLANTA COLINA AMBAS ACTIVAS CASA MATRIZ LA UNION 3070"]
    assert resolver_origen_documental(textos, PLANTAS) is None


def test_documental_ignora_plantas_no_confirmadas():
    plantas_pendiente = [_PlantaFicticia("AZA RENCA", estado_calidad="PENDIENTE")]
    textos = ["GUIA DE DESPACHO PLANTA ORIGEN AZA RENCA LA UNION 3070"]
    assert resolver_origen_documental(textos, plantas_pendiente) is None


def test_documental_ignora_plantas_inactivas():
    plantas_inactiva = [_PlantaFicticia("AZA RENCA", estado_vigencia="INACTIVA")]
    textos = ["GUIA DE DESPACHO PLANTA ORIGEN AZA RENCA LA UNION 3070"]
    assert resolver_origen_documental(textos, plantas_inactiva) is None


# ---------------------------------------------------------------------
# Fixture universal -- otro rubro, nada relacionado con AZA/acero/RENCA
# ---------------------------------------------------------------------


def test_fixture_universal_casa_matriz_otro_rubro_no_resuelve():
    plantas_distribuidora = [_PlantaFicticia("PLANTA NORTE"), _PlantaFicticia("PLANTA SUR")]
    textos = [
        "DISTRIBUIDORA GENERICA SPA GIRO DISTRIBUCION DE ALIMENTOS CASA MATRIZ "
        "PLANTA NORTE AVENIDA SIEMPREVIVA 742 SANTIAGO CHILE"
    ]
    assert resolver_origen_documental(textos, plantas_distribuidora) is None


def test_fixture_universal_campo_explicito_otro_rubro_si_resuelve():
    plantas_distribuidora = [_PlantaFicticia("PLANTA NORTE"), _PlantaFicticia("PLANTA SUR")]
    textos = ["GUIA DE DESPACHO PLANTA ORIGEN PLANTA SUR AVENIDA SIEMPREVIVA 742"]
    resultado = resolver_origen_documental(textos, plantas_distribuidora)
    assert resultado is not None
    assert resultado.nombre == "PLANTA SUR"
