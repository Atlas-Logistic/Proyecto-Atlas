import ast
from pathlib import Path
from uuid import uuid4

import pytest

from atlas_core.catalogo_transportistas import (
    ErrorCatalogoTransportistas,
    ErrorRutTransportista,
    ErrorValidacionTransportista,
    EstadoBusquedaTransportista,
    EstadoCalidadTransportista,
    EstadoVigenciaAliasTransportista,
    EstadoVigenciaTransportista,
    MotivoRevisionBusquedaTransportista,
    TipoAliasTransportista,
    TipoOrigenCoincidenciaTransportista,
    normalizar_nombre_transportista,
    normalizar_rut_transportista,
    validar_fecha_iso8601_transportista,
    validar_uuid_transportista,
)


ENUMERACIONES = (
    (EstadoCalidadTransportista, ("PENDIENTE", "CONFIRMADO", "REQUIERE_REVISION")),
    (EstadoVigenciaTransportista, ("ACTIVO", "INACTIVO")),
    (EstadoVigenciaAliasTransportista, ("ACTIVO", "INACTIVO")),
    (TipoAliasTransportista, ("ALIAS", "RAZON_SOCIAL_ANTERIOR", "NOMBRE_COMERCIAL_ANTERIOR")),
    (EstadoBusquedaTransportista, ("COINCIDENCIA", "REQUIERE_REACTIVACION", "PROPUESTA_EXISTENTE", "EN_REVISION", "AMBIGUA", "SIN_COINCIDENCIA")),
    (MotivoRevisionBusquedaTransportista, ("ESTADO_CALIDAD", "ALIAS_INACTIVO")),
    (TipoOrigenCoincidenciaTransportista, ("RAZON_SOCIAL", "NOMBRE_COMERCIAL", "ALIAS_ACTIVO", "ALIAS_INACTIVO")),
)


@pytest.mark.parametrize(("enumeracion", "valores"), ENUMERACIONES)
def test_enumeraciones_tienen_valores_exactos(enumeracion, valores):
    assert tuple(item.value for item in enumeracion) == valores
    assert all(isinstance(item.value, str) for item in enumeracion)
    with pytest.raises(ValueError):
        enumeracion("DESCONOCIDO")


def test_jerarquia_de_excepciones_es_especifica():
    assert issubclass(ErrorValidacionTransportista, ErrorCatalogoTransportistas)
    assert issubclass(ErrorRutTransportista, ErrorValidacionTransportista)


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    (
        ("  empresa\t demo\n sur  ", "EMPRESA DEMO SUR"),
        ("empresa\u00a0demo\u2003sur", "EMPRESA DEMO SUR"),
        ("Transportes Ñandú", "TRANSPORTES NANDU"),
        ("RUTA—NORTE O’HIGGINS", "RUTA-NORTE O'HIGGINS"),
        ("DEMO & + / # @ - ' FINAL", "DEMO & + / # @ - ' FINAL"),
    ),
)
def test_normalizacion_general_conservadora(entrada, esperado):
    assert normalizar_nombre_transportista(entrada) == esperado


@pytest.mark.parametrize("variante", ("S.P.A.", "S P A", "SPA"))
def test_normaliza_variantes_terminales_spa(variante):
    assert normalizar_nombre_transportista(f"Empresa Demo {variante}") == "EMPRESA DEMO SPA"


@pytest.mark.parametrize("variante", ("L.T.D.A.", "L T D A", "LTDA"))
def test_normaliza_variantes_terminales_ltda(variante):
    assert normalizar_nombre_transportista(f"Empresa Demo {variante}") == "EMPRESA DEMO LTDA"


@pytest.mark.parametrize("variante", ("S.A.", "S A", "SA"))
def test_normaliza_variantes_terminales_sa(variante):
    assert normalizar_nombre_transportista(f"Empresa Demo {variante}") == "EMPRESA DEMO SA"


@pytest.mark.parametrize("separador", (", ", ",", ". "))
def test_normaliza_separador_antes_del_sufijo(separador):
    assert normalizar_nombre_transportista(f"Empresa Demo{separador}S.P.A.") == "EMPRESA DEMO SPA"


def test_no_equipara_sufijos_societarios():
    resultados = {normalizar_nombre_transportista(f"Empresa Demo {sufijo}") for sufijo in ("SPA", "SA", "LTDA")}
    assert resultados == {"EMPRESA DEMO SPA", "EMPRESA DEMO SA", "EMPRESA DEMO LTDA"}


@pytest.mark.parametrize(
    "entrada",
    (
        "SPA NORTE TRANSPORTES",
        "CASA SPAZIO",
        "RUTA S A CENTRAL",
        "LTDA SERVICIOS",
        "EMPRESA DEMO SPA NORTE",
        "EMPRESA DEMO S.A. SERVICIOS",
        "EMPRESA DEMO SPAZIO",
        "EMPRESA DEMO S A1",
        "EMPRESA DEMO S.P.A.X",
    ),
)
def test_no_canoniza_secuencias_no_terminales(entrada):
    assert normalizar_nombre_transportista(entrada) == entrada


@pytest.mark.parametrize("entrada", (None, "", " \t\n "))
def test_normalizacion_rechaza_vacio(entrada):
    with pytest.raises(ErrorValidacionTransportista):
        normalizar_nombre_transportista(entrada)


@pytest.mark.parametrize("entrada", ("  Empresa Démo, S.P.A. ", "RUTA–NORTE", "Demo & Asociados"))
def test_normalizacion_es_determinista_e_idempotente(entrada):
    primera = normalizar_nombre_transportista(entrada)
    assert normalizar_nombre_transportista(entrada) == primera
    assert normalizar_nombre_transportista(primera) == primera


def _digito_verificador(cuerpo: str) -> str:
    suma = 0
    factor = 2
    for digito in reversed(cuerpo):
        suma += int(digito) * factor
        factor = factor + 1 if factor < 7 else 2
    resultado = 11 - suma % 11
    return "0" if resultado == 11 else "K" if resultado == 10 else str(resultado)


def _rut_sintetico(*, requiere_k: bool = False) -> tuple[str, str]:
    for numero in range(10_000_001, 10_001_000):
        cuerpo = str(numero)
        digito = _digito_verificador(cuerpo)
        if not requiere_k or digito == "K":
            return cuerpo, digito
    raise AssertionError("no se pudo generar un RUT sintético")


def test_rut_vacio_se_conserva():
    assert normalizar_rut_transportista("") == ""
    assert normalizar_rut_transportista(None) == ""


def test_rut_acepta_puntos_guion_y_espacios():
    cuerpo, digito = _rut_sintetico()
    con_puntos = f" {cuerpo[:2]}.{cuerpo[2:5]}.{cuerpo[5:]} - {digito} "
    assert normalizar_rut_transportista(con_puntos) == f"{cuerpo}-{digito}"


def test_rut_acepta_k_minuscula_y_forma_canonica():
    cuerpo, digito = _rut_sintetico(requiere_k=True)
    assert digito == "K"
    assert normalizar_rut_transportista(f"{cuerpo}-k") == f"{cuerpo}-K"
    assert normalizar_rut_transportista(f"{cuerpo}-K") == f"{cuerpo}-K"


@pytest.mark.parametrize("tipo", ("digito", "estructura", "caracteres"))
def test_rut_rechaza_valores_invalidos_sin_exponerlos(tipo):
    cuerpo, digito = _rut_sintetico()
    entradas = {
        "digito": f"{cuerpo}-{'0' if digito != '0' else '1'}",
        "estructura": f"--{cuerpo}--{digito}",
        "caracteres": f"PRIVADO{cuerpo}-{digito}",
    }
    recibido = entradas[tipo]
    with pytest.raises(ErrorRutTransportista) as capturado:
        normalizar_rut_transportista(recibido)
    assert recibido not in str(capturado.value)
    assert cuerpo not in str(capturado.value)


def test_uuid_valido_se_canoniza_y_recorta():
    valor = str(uuid4())
    assert validar_uuid_transportista(f"  {valor.upper()}  ") == valor


@pytest.mark.parametrize("entrada", ("", "no-es-uuid", None, 123))
def test_uuid_rechaza_texto_invalido_o_vacio(entrada):
    with pytest.raises(ErrorValidacionTransportista):
        validar_uuid_transportista(entrada)


def test_fecha_utc_y_offset_validos_se_canonizan():
    assert validar_fecha_iso8601_transportista("2026-01-01T00:00:00+00:00") == "2026-01-01T00:00:00+00:00"
    assert validar_fecha_iso8601_transportista(" 2026-01-01T03:04:05-03:00 ") == "2026-01-01T03:04:05-03:00"


def test_fecha_con_z_se_acepta_y_canoniza_como_offset_utc():
    assert validar_fecha_iso8601_transportista("2026-01-01T00:00:00Z") == "2026-01-01T00:00:00+00:00"


@pytest.mark.parametrize("entrada", ("no-es-fecha", "2026-02-30T00:00:00+00:00", "2026-01-01T00:00:00", None))
def test_fecha_rechaza_invalida_o_sin_zona(entrada):
    with pytest.raises(ErrorValidacionTransportista):
        validar_fecha_iso8601_transportista(entrada)


def test_fecha_vacia_solo_se_acepta_explicita():
    assert validar_fecha_iso8601_transportista("  ", permitir_vacia=True) == ""
    with pytest.raises(ErrorValidacionTransportista):
        validar_fecha_iso8601_transportista("")


def test_modulo_permanece_aislado_y_sin_efectos_de_archivo():
    modulo = Path(__file__).parents[1] / "atlas_core" / "catalogo_transportistas.py"
    arbol = ast.parse(modulo.read_text(encoding="utf-8"))
    importados = {
        nodo.module
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.ImportFrom) and nodo.module
    }
    importados.update(
        alias.name
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Import)
        for alias in nodo.names
    )
    prohibidos = ("ocr", "extractor", "rutas", "catalogo_clientes")
    assert not any(fragmento in nombre for nombre in importados for fragmento in prohibidos)
    assert not (Path(__file__).parents[1] / "catalogos" / "transportistas.json").exists()
