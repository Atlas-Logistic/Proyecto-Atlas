import ast
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from uuid import uuid4

import pytest

from atlas_core.catalogo_transportistas import (
    AliasTransportista,
    CatalogoTransportistas,
    ErrorCatalogoTransportistas,
    ErrorCatalogoTransportistasCorrupto,
    ErrorRutTransportista,
    ErrorValidacionTransportista,
    EstadoBusquedaTransportista,
    EstadoCalidadTransportista,
    EstadoVigenciaAliasTransportista,
    EstadoVigenciaTransportista,
    MotivoRevisionBusquedaTransportista,
    ResultadoBusquedaTransportista,
    TipoAliasTransportista,
    TipoOrigenCoincidenciaTransportista,
    Transportista,
    VERSION_FORMATO_TRANSPORTISTAS,
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


FECHA_ANTERIOR = "2026-01-01T00:00:00+00:00"
FECHA_CREACION = "2026-01-02T00:00:00+00:00"
FECHA_MODIFICACION = "2026-01-03T00:00:00+00:00"


def _crear_alias(**cambios):
    datos = {
        "alias_id": str(uuid4()),
        "valor": "TRANSPORTES DEMO ANTERIOR SPA",
        "tipo": TipoAliasTransportista.RAZON_SOCIAL_ANTERIOR,
        "estado_vigencia": EstadoVigenciaAliasTransportista.ACTIVO,
        "fuente": "FUENTE SINTETICA",
        "observacion": "",
        "fecha_confirmacion_valor": FECHA_ANTERIOR,
        "fecha_creacion": FECHA_CREACION,
        "fecha_modificacion": FECHA_MODIFICACION,
    }
    datos.update(cambios)
    return AliasTransportista(**datos)


def _crear_transportista(**cambios):
    datos = {
        "transportista_id": str(uuid4()),
        "razon_social": "TRANSPORTES DEMO NORTE SPA",
        "fuente_razon_social": "FUENTE SINTETICA",
        "fecha_confirmacion_razon_social": "",
        "nombre_normalizado": "TRANSPORTES DEMO NORTE SPA",
        "nombre_comercial": "DEMO LOGISTICA",
        "rut": "",
        "aliases": (),
        "pais": "CL",
        "estado_calidad": EstadoCalidadTransportista.PENDIENTE,
        "estado_vigencia": EstadoVigenciaTransportista.ACTIVO,
        "fuente": "FUENTE SINTETICA",
        "observacion": "",
        "fecha_creacion": FECHA_CREACION,
        "fecha_modificacion": FECHA_MODIFICACION,
    }
    datos.update(cambios)
    return Transportista(**datos)


def _datos_alias(alias=None):
    return (alias or _crear_alias()).a_dict()


def _datos_transportista(transportista=None):
    return (transportista or _crear_transportista()).a_dict()


def test_alias_valido_inmutable_y_serializable():
    alias = _crear_alias()
    with pytest.raises(FrozenInstanceError):
        alias.valor = "OTRO"
    datos = alias.a_dict()
    assert tuple(datos) == AliasTransportista._CAMPOS
    assert datos["tipo"] == "RAZON_SOCIAL_ANTERIOR"
    assert datos["estado_vigencia"] == "ACTIVO"
    assert AliasTransportista.desde_dict(datos) == alias
    assert AliasTransportista.desde_dict(alias.a_dict()).a_dict() == datos


@pytest.mark.parametrize(
    ("campo", "valor"),
    (
        ("alias_id", "uuid-invalido"),
        ("valor", ""),
        ("fuente", " "),
        ("tipo", "ALIAS"),
        ("estado_vigencia", "ACTIVO"),
        ("observacion", None),
        ("fecha_confirmacion_valor", ""),
        ("fecha_creacion", "2026-01-02T00:00:00"),
        ("fecha_modificacion", "fecha-invalida"),
    ),
)
def test_alias_rechaza_campos_invalidos(campo, valor):
    with pytest.raises(ErrorValidacionTransportista):
        _crear_alias(**{campo: valor})


@pytest.mark.parametrize(
    "cambios",
    (
        {"fecha_confirmacion_valor": "2026-01-03T00:00:00+00:00"},
        {"fecha_creacion": "2026-01-04T00:00:00+00:00"},
    ),
)
def test_alias_rechaza_orden_temporal_invalido(cambios):
    with pytest.raises(ErrorValidacionTransportista):
        _crear_alias(**cambios)


@pytest.mark.parametrize("alteracion", ("faltante", "extra", "raiz", "enum", "enum_tipado"))
def test_alias_desde_dict_es_estricto_y_no_muta(alteracion):
    datos = _datos_alias()
    original = {**datos}
    entrada = datos
    if alteracion == "faltante":
        entrada = {clave: valor for clave, valor in datos.items() if clave != "fuente"}
    elif alteracion == "extra":
        entrada = {**datos, "extra": True}
    elif alteracion == "raiz":
        entrada = list(datos.values())
    elif alteracion == "enum":
        entrada = {**datos, "tipo": "DESCONOCIDO"}
    elif alteracion == "enum_tipado":
        entrada = {**datos, "tipo": TipoAliasTransportista.ALIAS}
    with pytest.raises(ErrorValidacionTransportista):
        AliasTransportista.desde_dict(entrada)
    assert datos == original


def test_transportistas_validos_por_estado_de_calidad():
    pendiente = _crear_transportista()
    confirmado = _crear_transportista(
        estado_calidad=EstadoCalidadTransportista.CONFIRMADO,
        fecha_confirmacion_razon_social=FECHA_CREACION,
    )
    revision_nueva = _crear_transportista(
        estado_calidad=EstadoCalidadTransportista.REQUIERE_REVISION
    )
    revision_historica = _crear_transportista(
        estado_calidad=EstadoCalidadTransportista.REQUIERE_REVISION,
        fecha_confirmacion_razon_social=FECHA_ANTERIOR,
    )
    assert pendiente.fecha_confirmacion_razon_social == ""
    assert confirmado.fecha_confirmacion_razon_social == FECHA_CREACION
    assert revision_nueva.fecha_confirmacion_razon_social == ""
    assert revision_historica.fecha_confirmacion_razon_social == FECHA_ANTERIOR


def test_transportista_es_inmutable():
    transportista = _crear_transportista()
    with pytest.raises(FrozenInstanceError):
        transportista.razon_social = "OTRA"


@pytest.mark.parametrize(
    ("campo", "valor"),
    (
        ("transportista_id", "uuid-invalido"),
        ("razon_social", ""),
        ("fuente_razon_social", ""),
        ("nombre_normalizado", "NOMBRE INCORRECTO"),
        ("nombre_comercial", None),
        ("pais", "AR"),
        ("estado_calidad", "PENDIENTE"),
        ("estado_vigencia", "ACTIVO"),
        ("fuente", ""),
        ("observacion", None),
        ("fecha_creacion", "2026-01-02T00:00:00"),
        ("fecha_modificacion", "fecha-invalida"),
    ),
)
def test_transportista_rechaza_campos_invalidos(campo, valor):
    with pytest.raises(ErrorValidacionTransportista):
        _crear_transportista(**{campo: valor})


def test_transportista_rechaza_orden_y_reglas_de_confirmacion_invalidos():
    casos = (
        {"fecha_creacion": "2026-01-04T00:00:00+00:00"},
        {"fecha_confirmacion_razon_social": FECHA_ANTERIOR},
        {"estado_calidad": EstadoCalidadTransportista.CONFIRMADO},
        {
            "estado_calidad": EstadoCalidadTransportista.CONFIRMADO,
            "fecha_confirmacion_razon_social": "2026-01-04T00:00:00+00:00",
        },
    )
    for cambios in casos:
        with pytest.raises(ErrorValidacionTransportista):
            _crear_transportista(**cambios)


def test_transportista_admite_rut_vacio_y_canonico():
    cuerpo, digito = _rut_sintetico()
    assert _crear_transportista().rut == ""
    rut = f"{cuerpo}-{digito}"
    assert _crear_transportista(rut=rut).rut == rut


def test_transportista_rechaza_rut_no_canonico_o_invalido_sin_exponerlo():
    cuerpo, digito = _rut_sintetico()
    entradas = (f"{cuerpo[:2]}.{cuerpo[2:5]}.{cuerpo[5:]}-{digito}", f"{cuerpo}-X")
    for recibido in entradas:
        with pytest.raises(ErrorValidacionTransportista) as capturado:
            _crear_transportista(rut=recibido)
        mensaje = str(capturado.value)
        assert recibido not in mensaje
        assert cuerpo not in mensaje
        assert mensaje == "RUT del transportista inválido o no canónico"


@pytest.mark.parametrize("aliases", ([], (_crear_alias(), "no-alias")))
def test_transportista_exige_tupla_de_aliases_tipados(aliases):
    with pytest.raises(ErrorValidacionTransportista):
        _crear_transportista(aliases=aliases)


def test_transportista_rechaza_colisiones_internas_de_aliases():
    alias = _crear_alias()
    repetido_id = _crear_alias(alias_id=alias.alias_id, valor="OTRO NOMBRE")
    repetido_valor = _crear_alias(valor="Transportes Démo Anterior, S.P.A.")
    igual_razon = _crear_alias(valor="Transportes Demo Norte S.P.A.")
    igual_comercial = _crear_alias(valor="Demo Logística")
    for aliases in (
        (alias, repetido_id),
        (alias, repetido_valor),
        (igual_razon,),
        (igual_comercial,),
    ):
        with pytest.raises(ErrorValidacionTransportista):
            _crear_transportista(aliases=aliases)


def test_aliases_activos_e_inactivos_permanecen_representables():
    activo = _crear_alias(valor="ALIAS DEMO UNO")
    inactivo = _crear_alias(
        valor="ALIAS DEMO DOS",
        estado_vigencia=EstadoVigenciaAliasTransportista.INACTIVO,
    )
    transportista = _crear_transportista(aliases=(activo, inactivo))
    assert tuple(alias.estado_vigencia for alias in transportista.aliases) == (
        EstadoVigenciaAliasTransportista.ACTIVO,
        EstadoVigenciaAliasTransportista.INACTIVO,
    )


def test_transportista_round_trip_estable_con_aliases_y_enums():
    transportista = _crear_transportista(
        aliases=(_crear_alias(valor="ALIAS DEMO UNO"),),
        estado_calidad=EstadoCalidadTransportista.CONFIRMADO,
        fecha_confirmacion_razon_social=FECHA_ANTERIOR,
    )
    datos = transportista.a_dict()
    assert tuple(datos) == Transportista._CAMPOS
    assert isinstance(datos["aliases"], list)
    assert datos["estado_calidad"] == "CONFIRMADO"
    assert datos["estado_vigencia"] == "ACTIVO"
    reconstruido = Transportista.desde_dict(datos)
    assert reconstruido == transportista
    assert reconstruido.a_dict() == datos


@pytest.mark.parametrize("alteracion", ("faltante", "extra", "raiz", "aliases", "enum", "enum_tipado"))
def test_transportista_desde_dict_es_estricto_y_no_muta(alteracion):
    datos = _datos_transportista()
    original = {**datos, "aliases": list(datos["aliases"])}
    entrada = datos
    if alteracion == "faltante":
        entrada = {clave: valor for clave, valor in datos.items() if clave != "fuente"}
    elif alteracion == "extra":
        entrada = {**datos, "extra": True}
    elif alteracion == "raiz":
        entrada = list(datos.values())
    elif alteracion == "aliases":
        entrada = {**datos, "aliases": ()}
    elif alteracion == "enum":
        entrada = {**datos, "estado_calidad": "DESCONOCIDO"}
    elif alteracion == "enum_tipado":
        entrada = {**datos, "estado_calidad": EstadoCalidadTransportista.PENDIENTE}
    with pytest.raises(ErrorValidacionTransportista):
        Transportista.desde_dict(entrada)
    assert datos == original


_NO_INDICADO = object()


def _resultado(estado, transportista=_NO_INDICADO, **cambios):
    requiere = estado in {
        EstadoBusquedaTransportista.COINCIDENCIA,
        EstadoBusquedaTransportista.REQUIERE_REACTIVACION,
        EstadoBusquedaTransportista.PROPUESTA_EXISTENTE,
        EstadoBusquedaTransportista.EN_REVISION,
    }
    elegido = (_crear_transportista() if requiere else None) if transportista is _NO_INDICADO else transportista
    datos = {
        "estado": estado,
        "motivo_revision": (
            MotivoRevisionBusquedaTransportista.ESTADO_CALIDAD
            if estado is EstadoBusquedaTransportista.EN_REVISION else None
        ),
        "transportista": elegido,
        "cantidad_candidatos": 1 if requiere else 0,
        "transportista_ids": (
            (elegido.transportista_id,)
            if requiere and isinstance(elegido, Transportista)
            else ()
        ),
        "origenes_coincidencia": (
            (TipoOrigenCoincidenciaTransportista.RAZON_SOCIAL,) if requiere else ()
        ),
    }
    datos.update(cambios)
    return ResultadoBusquedaTransportista(**datos)


@pytest.mark.parametrize(
    "estado",
    (
        EstadoBusquedaTransportista.COINCIDENCIA,
        EstadoBusquedaTransportista.REQUIERE_REACTIVACION,
        EstadoBusquedaTransportista.PROPUESTA_EXISTENTE,
        EstadoBusquedaTransportista.EN_REVISION,
        EstadoBusquedaTransportista.SIN_COINCIDENCIA,
    ),
)
def test_resultados_validos_por_estado(estado):
    assert _resultado(estado).estado is estado


@pytest.mark.parametrize(
    "motivo",
    tuple(MotivoRevisionBusquedaTransportista),
)
def test_en_revision_admite_ambos_motivos(motivo):
    origen = (
        TipoOrigenCoincidenciaTransportista.ALIAS_INACTIVO
        if motivo is MotivoRevisionBusquedaTransportista.ALIAS_INACTIVO
        else TipoOrigenCoincidenciaTransportista.RAZON_SOCIAL
    )
    assert _resultado(
        EstadoBusquedaTransportista.EN_REVISION,
        motivo_revision=motivo,
        origenes_coincidencia=(origen,),
    ).motivo_revision is motivo


def test_resultado_ambiguo_valido_con_ids_ordenados():
    ids = tuple(sorted((str(uuid4()), str(uuid4()))))
    resultado = _resultado(
        EstadoBusquedaTransportista.AMBIGUA,
        cantidad_candidatos=2,
        transportista_ids=ids,
        origenes_coincidencia=(TipoOrigenCoincidenciaTransportista.ALIAS_INACTIVO,),
    )
    assert resultado.transportista is None


@pytest.mark.parametrize(
    "cambios",
    (
        {"motivo_revision": MotivoRevisionBusquedaTransportista.ESTADO_CALIDAD},
        {"transportista": None},
        {"cantidad_candidatos": -1},
        {"cantidad_candidatos": True},
        {"transportista_ids": ()},
    ),
)
def test_resultado_individual_rechaza_inconsistencias(cambios):
    with pytest.raises(ErrorValidacionTransportista):
        _resultado(EstadoBusquedaTransportista.COINCIDENCIA, **cambios)


def test_resultado_en_revision_exige_motivo():
    with pytest.raises(ErrorValidacionTransportista):
        _resultado(EstadoBusquedaTransportista.EN_REVISION, motivo_revision=None)


def test_resultado_rechaza_uuid_distinto_repetido_no_canonico_o_desordenado():
    transportista = _crear_transportista()
    otro = str(uuid4())
    casos = (
        (otro,),
        (otro, otro),
        (otro.upper(),),
        tuple(reversed(sorted((otro, str(uuid4()))))),
    )
    for ids in casos:
        with pytest.raises(ErrorValidacionTransportista):
            _resultado(
                EstadoBusquedaTransportista.COINCIDENCIA,
                transportista=transportista,
                transportista_ids=ids,
                cantidad_candidatos=len(ids),
            )


def test_resultado_ambiguo_rechaza_transportista_o_cantidad_inconsistente():
    ids = tuple(sorted((str(uuid4()), str(uuid4()))))
    with pytest.raises(ErrorValidacionTransportista):
        _resultado(
            EstadoBusquedaTransportista.AMBIGUA,
            transportista=_crear_transportista(),
            cantidad_candidatos=2,
            transportista_ids=ids,
        )
    with pytest.raises(ErrorValidacionTransportista):
        _resultado(
            EstadoBusquedaTransportista.AMBIGUA,
            cantidad_candidatos=3,
            transportista_ids=ids,
        )


def test_sin_coincidencia_rechaza_origenes():
    with pytest.raises(ErrorValidacionTransportista):
        _resultado(
            EstadoBusquedaTransportista.SIN_COINCIDENCIA,
            origenes_coincidencia=(TipoOrigenCoincidenciaTransportista.ALIAS_ACTIVO,),
        )


@pytest.mark.parametrize(
    "origenes",
    (
        (TipoOrigenCoincidenciaTransportista.ALIAS_ACTIVO,) * 2,
        ("ALIAS_ACTIVO",),
        [TipoOrigenCoincidenciaTransportista.ALIAS_ACTIVO],
    ),
)
def test_resultado_rechaza_origenes_repetidos_o_mal_tipados(origenes):
    with pytest.raises(ErrorValidacionTransportista):
        _resultado(EstadoBusquedaTransportista.COINCIDENCIA, origenes_coincidencia=origenes)


def test_resultado_es_inmutable_y_no_tiene_serializacion_persistente():
    resultado = _resultado(EstadoBusquedaTransportista.COINCIDENCIA)
    with pytest.raises(FrozenInstanceError):
        resultado.cantidad_candidatos = 2
    assert not hasattr(resultado, "a_dict")
    assert not hasattr(ResultadoBusquedaTransportista, "desde_dict")


@pytest.mark.parametrize(
    "estado",
    (
        EstadoBusquedaTransportista.COINCIDENCIA,
        EstadoBusquedaTransportista.REQUIERE_REACTIVACION,
        EstadoBusquedaTransportista.PROPUESTA_EXISTENTE,
        EstadoBusquedaTransportista.EN_REVISION,
    ),
)
def test_resultados_con_candidato_rechazan_origenes_vacios(estado):
    with pytest.raises(ErrorValidacionTransportista):
        _resultado(estado, origenes_coincidencia=())


def test_en_revision_por_alias_inactivo_exige_origen_correspondiente():
    with pytest.raises(ErrorValidacionTransportista):
        _resultado(
            EstadoBusquedaTransportista.EN_REVISION,
            motivo_revision=MotivoRevisionBusquedaTransportista.ALIAS_INACTIVO,
            origenes_coincidencia=(),
        )
    with pytest.raises(ErrorValidacionTransportista):
        _resultado(
            EstadoBusquedaTransportista.EN_REVISION,
            motivo_revision=MotivoRevisionBusquedaTransportista.ALIAS_INACTIVO,
            origenes_coincidencia=(TipoOrigenCoincidenciaTransportista.RAZON_SOCIAL,),
        )
    resultado = _resultado(
        EstadoBusquedaTransportista.EN_REVISION,
        motivo_revision=MotivoRevisionBusquedaTransportista.ALIAS_INACTIVO,
        origenes_coincidencia=(
            TipoOrigenCoincidenciaTransportista.RAZON_SOCIAL,
            TipoOrigenCoincidenciaTransportista.ALIAS_INACTIVO,
        ),
    )
    assert TipoOrigenCoincidenciaTransportista.ALIAS_INACTIVO in resultado.origenes_coincidencia


def test_resultado_ambiguo_rechaza_origenes_vacios():
    ids = tuple(sorted((str(uuid4()), str(uuid4()))))
    with pytest.raises(ErrorValidacionTransportista):
        _resultado(
            EstadoBusquedaTransportista.AMBIGUA,
            cantidad_candidatos=2,
            transportista_ids=ids,
            origenes_coincidencia=(),
        )


def test_sin_coincidencia_exige_origenes_vacios():
    assert _resultado(EstadoBusquedaTransportista.SIN_COINCIDENCIA).origenes_coincidencia == ()
    with pytest.raises(ErrorValidacionTransportista):
        _resultado(
            EstadoBusquedaTransportista.SIN_COINCIDENCIA,
            origenes_coincidencia=(TipoOrigenCoincidenciaTransportista.RAZON_SOCIAL,),
        )


class _TextoDerivado(str):
    pass


class _DictDerivado(dict):
    pass


class _TuplaDerivada(tuple):
    pass


class _ListaDerivada(list):
    pass


class _EnteroDerivado(int):
    pass


def test_modelos_rechazan_subclases_de_texto():
    with pytest.raises(ErrorValidacionTransportista):
        _crear_alias(valor=_TextoDerivado("ALIAS DEMO"))
    with pytest.raises(ErrorValidacionTransportista):
        _crear_transportista(razon_social=_TextoDerivado("TRANSPORTES DEMO NORTE SPA"))
    with pytest.raises(ErrorValidacionTransportista):
        _crear_alias(alias_id=_TextoDerivado(str(uuid4())))
    with pytest.raises(ErrorValidacionTransportista):
        _crear_alias(fecha_creacion=_TextoDerivado(FECHA_CREACION))


def test_deserializacion_rechaza_subclase_de_dict():
    with pytest.raises(ErrorValidacionTransportista):
        AliasTransportista.desde_dict(_DictDerivado(_datos_alias()))
    with pytest.raises(ErrorValidacionTransportista):
        Transportista.desde_dict(_DictDerivado(_datos_transportista()))


def test_deserializacion_rechaza_subclase_de_lista_para_aliases():
    datos = _datos_transportista()
    datos["aliases"] = _ListaDerivada(datos["aliases"])
    with pytest.raises(ErrorValidacionTransportista):
        Transportista.desde_dict(datos)


def test_modelos_rechazan_subclases_de_tupla_y_entero():
    with pytest.raises(ErrorValidacionTransportista):
        _crear_transportista(aliases=_TuplaDerivada())
    with pytest.raises(ErrorValidacionTransportista):
        _resultado(
            EstadoBusquedaTransportista.COINCIDENCIA,
            cantidad_candidatos=_EnteroDerivado(1),
        )
    with pytest.raises(ErrorValidacionTransportista):
        _resultado(
            EstadoBusquedaTransportista.COINCIDENCIA,
            transportista_ids=_TuplaDerivada((_crear_transportista().transportista_id,)),
        )
    with pytest.raises(ErrorValidacionTransportista):
        _resultado(
            EstadoBusquedaTransportista.COINCIDENCIA,
            origenes_coincidencia=_TuplaDerivada(
                (TipoOrigenCoincidenciaTransportista.RAZON_SOCIAL,)
            ),
        )


def _contenido_catalogo(*transportistas):
    return {
        "version_formato": VERSION_FORMATO_TRANSPORTISTAS,
        "transportistas": [transportista.a_dict() for transportista in transportistas],
    }


def _escribir_catalogo(ruta, contenido):
    ruta.write_text(json.dumps(contenido, ensure_ascii=False), encoding="utf-8")


def test_catalogo_inexistente_es_vacio_y_no_crea_rutas(tmp_path):
    ruta = tmp_path / "padre-inexistente" / "transportistas.json"
    catalogo = CatalogoTransportistas(ruta)
    assert catalogo.ruta == ruta
    assert not ruta.parent.exists()
    assert catalogo.listar() == ()
    assert not ruta.exists()
    assert not ruta.parent.exists()


def test_constructor_no_lee_el_archivo(monkeypatch, tmp_path):
    def fallar(*args, **kwargs):
        raise AssertionError("el constructor intentó leer")

    monkeypatch.setattr(Path, "open", fallar)
    CatalogoTransportistas(tmp_path / "transportistas.json")


class _RutaConvertibleArbitraria:
    def __fspath__(self):
        return "transportistas.json"


@pytest.mark.parametrize("ruta", (_RutaConvertibleArbitraria(), 123, None))
def test_constructor_rechaza_objetos_convertibles_arbitrarios(ruta):
    with pytest.raises(ErrorValidacionTransportista):
        CatalogoTransportistas(ruta)


def test_catalogo_valido_vacio(tmp_path):
    ruta = tmp_path / "transportistas.json"
    _escribir_catalogo(ruta, _contenido_catalogo())
    resultado = CatalogoTransportistas(str(ruta)).listar()
    assert resultado == ()
    assert type(resultado) is tuple


def test_catalogo_conserva_orden_aliases_y_relee_cada_llamada(tmp_path):
    ruta = tmp_path / "transportistas.json"
    alias_activo = _crear_alias(valor="ALIAS SINTETICO UNO")
    alias_inactivo = _crear_alias(
        valor="ALIAS SINTETICO DOS",
        estado_vigencia=EstadoVigenciaAliasTransportista.INACTIVO,
    )
    primero = _crear_transportista(
        razon_social="TRANSPORTES SINTETICOS UNO SPA",
        nombre_normalizado="TRANSPORTES SINTETICOS UNO SPA",
        aliases=(alias_activo, alias_inactivo),
    )
    segundo = _crear_transportista(
        razon_social="TRANSPORTES SINTETICOS DOS LTDA",
        nombre_normalizado="TRANSPORTES SINTETICOS DOS LTDA",
    )
    _escribir_catalogo(ruta, _contenido_catalogo(primero))
    catalogo = CatalogoTransportistas(ruta)
    inicial = catalogo.listar()
    assert inicial == (primero,)
    assert tuple(alias.estado_vigencia for alias in inicial[0].aliases) == (
        EstadoVigenciaAliasTransportista.ACTIVO,
        EstadoVigenciaAliasTransportista.INACTIVO,
    )
    _escribir_catalogo(ruta, _contenido_catalogo(segundo, primero))
    assert catalogo.listar() == (segundo, primero)
    assert catalogo.listar() is not catalogo.listar()


@pytest.mark.parametrize(
    "contenido",
    (
        [],
        {"version_formato": 1},
        {"transportistas": []},
        {"version_formato": 1, "transportistas": [], "extra": True},
        {"version_formato": True, "transportistas": []},
        {"version_formato": "1", "transportistas": []},
        {"version_formato": 2, "transportistas": []},
        {"version_formato": 1, "transportistas": {}},
        {"version_formato": 1, "transportistas": ["registro"]},
    ),
)
def test_catalogo_rechaza_raiz_version_coleccion_o_registro_invalidos(tmp_path, contenido):
    ruta = tmp_path / "transportistas.json"
    _escribir_catalogo(ruta, contenido)
    with pytest.raises(ErrorCatalogoTransportistasCorrupto):
        CatalogoTransportistas(ruta).listar()


@pytest.mark.parametrize("estructura", ("raiz", "lista", "registro"))
def test_catalogo_rechaza_subclases_estructurales(monkeypatch, tmp_path, estructura):
    ruta = tmp_path / "transportistas.json"
    ruta.write_text("{}", encoding="utf-8")
    contenido = _contenido_catalogo()
    if estructura == "raiz":
        contenido = _DictDerivado(contenido)
    elif estructura == "lista":
        contenido["transportistas"] = _ListaDerivada()
    else:
        contenido["transportistas"] = [_DictDerivado(_datos_transportista())]
    monkeypatch.setattr(json, "load", lambda archivo, **kwargs: contenido)
    with pytest.raises(ErrorCatalogoTransportistasCorrupto):
        CatalogoTransportistas(ruta).listar()


@pytest.mark.parametrize("texto", ("", "no es json", "{"))
def test_catalogo_rechaza_json_invalido_sin_exponer_contenido(tmp_path, texto):
    ruta = tmp_path / "transportistas.json"
    ruta.write_text(texto, encoding="utf-8")
    with pytest.raises(ErrorCatalogoTransportistasCorrupto) as capturado:
        CatalogoTransportistas(ruta).listar()
    assert str(capturado.value) == "JSON del catálogo inválido"
    assert texto not in str(capturado.value) or not texto


def _assert_clave_json_duplicada(ruta, texto):
    ruta.write_text(texto, encoding="utf-8")
    with pytest.raises(ErrorCatalogoTransportistasCorrupto) as capturado:
        CatalogoTransportistas(ruta).listar()
    assert str(capturado.value) == "el catálogo contiene una clave JSON duplicada"


def test_catalogo_rechaza_clave_json_duplicada_en_raiz(tmp_path):
    _assert_clave_json_duplicada(
        tmp_path / "transportistas.json",
        '{"version_formato":1,"version_formato":1,"transportistas":[]}',
    )


def test_catalogo_rechaza_clave_json_duplicada_en_transportista(tmp_path):
    texto = json.dumps(_contenido_catalogo(_crear_transportista()), ensure_ascii=False)
    texto = texto.replace('"rut": ""', '"rut": "", "rut": ""', 1)
    _assert_clave_json_duplicada(tmp_path / "transportistas.json", texto)


def test_catalogo_rechaza_clave_json_duplicada_en_alias(tmp_path):
    transportista = _crear_transportista(aliases=(_crear_alias(valor="ALIAS DEMO UNICO"),))
    texto = json.dumps(_contenido_catalogo(transportista), ensure_ascii=False)
    texto = texto.replace(
        '"valor": "ALIAS DEMO UNICO"',
        '"valor": "ALIAS DEMO UNICO", "valor": "ALIAS DEMO UNICO"',
        1,
    )
    _assert_clave_json_duplicada(tmp_path / "transportistas.json", texto)


def test_catalogo_convierte_error_de_lectura(monkeypatch, tmp_path):
    ruta = tmp_path / "transportistas.json"
    ruta.write_text("{}", encoding="utf-8")

    def denegar(*args, **kwargs):
        raise PermissionError("detalle privado")

    monkeypatch.setattr(Path, "open", denegar)
    with pytest.raises(ErrorCatalogoTransportistasCorrupto) as capturado:
        CatalogoTransportistas(ruta).listar()
    assert str(capturado.value) == "no se pudo leer el catálogo"
    assert "detalle privado" not in str(capturado.value)


@pytest.mark.parametrize("error", (IsADirectoryError("privado"), OSError("privado")))
def test_catalogo_convierte_otros_errores_de_sistema(monkeypatch, tmp_path, error):
    ruta = tmp_path / "transportistas.json"

    def fallar(*args, **kwargs):
        raise error

    monkeypatch.setattr(Path, "open", fallar)
    with pytest.raises(ErrorCatalogoTransportistasCorrupto) as capturado:
        CatalogoTransportistas(ruta).listar()
    assert str(capturado.value) == "no se pudo leer el catálogo"
    assert "privado" not in str(capturado.value)


def test_catalogo_trata_file_not_found_durante_apertura_como_inexistente(monkeypatch, tmp_path):
    ruta = tmp_path / "transportistas.json"

    def desaparecer(*args, **kwargs):
        raise FileNotFoundError("ruta privada")

    monkeypatch.setattr(Path, "open", desaparecer)
    assert CatalogoTransportistas(ruta).listar() == ()


def test_catalogo_rechaza_bom_como_los_catalogos_existentes(tmp_path):
    ruta = tmp_path / "transportistas.json"
    texto = json.dumps(_contenido_catalogo())
    ruta.write_bytes(b"\xef\xbb\xbf" + texto.encode("utf-8"))
    with pytest.raises(ErrorCatalogoTransportistasCorrupto) as capturado:
        CatalogoTransportistas(ruta).listar()
    assert str(capturado.value) == "JSON del catálogo inválido"


def test_catalogo_rechaza_codificacion_utf8_invalida(tmp_path):
    ruta = tmp_path / "transportistas.json"
    ruta.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ErrorCatalogoTransportistasCorrupto) as capturado:
        CatalogoTransportistas(ruta).listar()
    assert str(capturado.value) == "codificación UTF-8 inválida"


@pytest.mark.parametrize(
    ("campo", "valor"),
    (
        ("razon_social", ""),
        ("estado_calidad", "DESCONOCIDO"),
        ("fecha_creacion", "fecha-invalida"),
    ),
)
def test_catalogo_convierte_registro_invalido_con_indice_seguro(tmp_path, campo, valor):
    ruta = tmp_path / "transportistas.json"
    datos = _datos_transportista()
    datos[campo] = valor
    _escribir_catalogo(ruta, {"version_formato": 1, "transportistas": [datos]})
    with pytest.raises(ErrorCatalogoTransportistasCorrupto) as capturado:
        CatalogoTransportistas(ruta).listar()
    assert str(capturado.value) == "registro de transportista inválido en índice 0"


def test_catalogo_convierte_alias_invalido_con_indice_seguro(tmp_path):
    ruta = tmp_path / "transportistas.json"
    datos = _datos_transportista(_crear_transportista(aliases=(_crear_alias(),)))
    datos["aliases"][0]["fecha_creacion"] = "sin-zona"
    _escribir_catalogo(ruta, {"version_formato": 1, "transportistas": [datos]})
    with pytest.raises(ErrorCatalogoTransportistasCorrupto) as capturado:
        CatalogoTransportistas(ruta).listar()
    assert str(capturado.value) == "registro de transportista inválido en índice 0"


def test_catalogo_no_expone_rut_invalido(tmp_path):
    ruta = tmp_path / "transportistas.json"
    cuerpo, digito = _rut_sintetico()
    rut_privado = f"{cuerpo}-X"
    datos = _datos_transportista()
    datos["rut"] = rut_privado
    _escribir_catalogo(ruta, {"version_formato": 1, "transportistas": [datos]})
    with pytest.raises(ErrorCatalogoTransportistasCorrupto) as capturado:
        CatalogoTransportistas(ruta).listar()
    mensaje = str(capturado.value)
    assert mensaje == "registro de transportista inválido en índice 0"
    assert rut_privado not in mensaje
    assert cuerpo not in mensaje


def test_catalogo_rechaza_transportista_id_global_repetido(tmp_path):
    ruta = tmp_path / "transportistas.json"
    primero = _crear_transportista()
    segundo = _crear_transportista(
        transportista_id=primero.transportista_id,
        razon_social="OTRO TRANSPORTISTA SPA",
        nombre_normalizado="OTRO TRANSPORTISTA SPA",
    )
    _escribir_catalogo(ruta, _contenido_catalogo(primero, segundo))
    with pytest.raises(ErrorCatalogoTransportistasCorrupto, match="transportista_id duplicado"):
        CatalogoTransportistas(ruta).listar()


def test_catalogo_rechaza_alias_id_global_repetido(tmp_path):
    ruta = tmp_path / "transportistas.json"
    alias = _crear_alias(valor="ALIAS GLOBAL UNO")
    primero = _crear_transportista(aliases=(alias,))
    segundo = _crear_transportista(
        razon_social="OTRO TRANSPORTISTA SPA",
        nombre_normalizado="OTRO TRANSPORTISTA SPA",
        aliases=(_crear_alias(alias_id=alias.alias_id, valor="ALIAS GLOBAL DOS"),),
    )
    _escribir_catalogo(ruta, _contenido_catalogo(primero, segundo))
    with pytest.raises(ErrorCatalogoTransportistasCorrupto, match="alias_id duplicado"):
        CatalogoTransportistas(ruta).listar()


@pytest.mark.parametrize(
    ("estado_primero", "estado_segundo", "vigencia_segundo"),
    (
        (EstadoCalidadTransportista.PENDIENTE, EstadoCalidadTransportista.PENDIENTE, EstadoVigenciaTransportista.ACTIVO),
        (EstadoCalidadTransportista.PENDIENTE, EstadoCalidadTransportista.PENDIENTE, EstadoVigenciaTransportista.INACTIVO),
        (EstadoCalidadTransportista.PENDIENTE, EstadoCalidadTransportista.CONFIRMADO, EstadoVigenciaTransportista.ACTIVO),
        (EstadoCalidadTransportista.PENDIENTE, EstadoCalidadTransportista.REQUIERE_REVISION, EstadoVigenciaTransportista.ACTIVO),
    ),
)
def test_catalogo_rechaza_rut_global_repetido_en_todos_los_estados(
    tmp_path, estado_primero, estado_segundo, vigencia_segundo
):
    ruta = tmp_path / "transportistas.json"
    cuerpo, digito = _rut_sintetico()
    rut = f"{cuerpo}-{digito}"
    def fecha_confirmacion(estado):
        return FECHA_ANTERIOR if estado is EstadoCalidadTransportista.CONFIRMADO else ""
    primero = _crear_transportista(
        rut=rut,
        estado_calidad=estado_primero,
        fecha_confirmacion_razon_social=fecha_confirmacion(estado_primero),
    )
    segundo = _crear_transportista(
        razon_social="OTRO TRANSPORTISTA SPA",
        nombre_normalizado="OTRO TRANSPORTISTA SPA",
        rut=rut,
        estado_calidad=estado_segundo,
        estado_vigencia=vigencia_segundo,
        fecha_confirmacion_razon_social=fecha_confirmacion(estado_segundo),
    )
    _escribir_catalogo(ruta, _contenido_catalogo(primero, segundo))
    with pytest.raises(ErrorCatalogoTransportistasCorrupto) as capturado:
        CatalogoTransportistas(ruta).listar()
    assert str(capturado.value) == "el catálogo contiene RUT duplicado"
    assert rut not in str(capturado.value)


def test_catalogo_permite_rut_vacio_repetido(tmp_path):
    ruta = tmp_path / "transportistas.json"
    primero = _crear_transportista()
    segundo = _crear_transportista(
        razon_social="OTRO TRANSPORTISTA SPA",
        nombre_normalizado="OTRO TRANSPORTISTA SPA",
    )
    _escribir_catalogo(ruta, _contenido_catalogo(primero, segundo))
    assert CatalogoTransportistas(ruta).listar() == (primero, segundo)


def test_catalogo_permite_colisiones_nominales_entre_transportistas(tmp_path):
    ruta = tmp_path / "transportistas.json"
    primero = _crear_transportista(
        razon_social="NOMBRE NOMINAL COMPARTIDO SPA",
        nombre_normalizado="NOMBRE NOMINAL COMPARTIDO SPA",
        nombre_comercial="COMERCIAL COMPARTIDO",
        aliases=(
            _crear_alias(valor="ALIAS COMPARTIDO", estado_vigencia=EstadoVigenciaAliasTransportista.ACTIVO),
            _crear_alias(valor="ALIAS CRUZADO"),
        ),
    )
    segundo = _crear_transportista(
        razon_social="NOMBRE NOMINAL COMPARTIDO SPA",
        nombre_normalizado="NOMBRE NOMINAL COMPARTIDO SPA",
        nombre_comercial="COMERCIAL COMPARTIDO",
        aliases=(
            _crear_alias(valor="ALIAS COMPARTIDO", estado_vigencia=EstadoVigenciaAliasTransportista.INACTIVO),
            _crear_alias(valor="OTRO ALIAS"),
        ),
        estado_vigencia=EstadoVigenciaTransportista.INACTIVO,
    )
    tercero = _crear_transportista(
        razon_social="ALIAS CRUZADO",
        nombre_normalizado="ALIAS CRUZADO",
    )
    _escribir_catalogo(ruta, _contenido_catalogo(primero, segundo, tercero))
    assert CatalogoTransportistas(ruta).listar() == (primero, segundo, tercero)


def test_catalogo_solo_implementa_listar_y_no_escribe(tmp_path):
    catalogo = CatalogoTransportistas(tmp_path / "transportistas.json")
    for nombre in ("obtener", "buscar", "agregar", "editar", "guardar", "escribir", "activar", "desactivar", "confirmar"):
        assert not hasattr(catalogo, nombre)
    modulo = Path(__file__).parents[1] / "atlas_core" / "catalogo_transportistas.py"
    texto = modulo.read_text(encoding="utf-8")
    assert "os.replace" not in texto
    assert "NamedTemporaryFile" not in texto
    assert not (Path(__file__).parents[1] / "catalogos" / "transportistas.json").exists()
