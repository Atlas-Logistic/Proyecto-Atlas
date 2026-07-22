import sys
import types
from pathlib import Path

import pytest

# Permitir importar atlas.py desde la raíz del proyecto cuando se ejecute este script.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Stub mínimo para easyocr para poder importar atlas.py.
easyocr_stub = types.ModuleType("easyocr")


class Reader:
    def __init__(self, *args, **kwargs):
        pass

    def readtext(self, *args, **kwargs):
        return []


easyocr_stub.Reader = Reader
sys.modules.setdefault("easyocr", easyocr_stub)

from atlas import extraer_datos
from atlas_core.extractor import (
    _clasificar_evidencia_transporte,
    _consensuar_transporte_focal,
    _extraer_asociaciones_geometricas,
    _extraer_transporte_geometrico,
)
from atlas_core.ocr import BloqueOCR


def _bloque(texto, x, y, ancho=None, alto=18):
    ancho = ancho if ancho is not None else max(30, len(texto) * 8)
    return BloqueOCR(
        texto=texto,
        bounding_box=((x, y), (x + ancho, y), (x + ancho, y + alto), (x, y + alto)),
        confianza=0.9,
    )


def test_geometria_cliente_a_la_derecha_de_senores():
    bloques = [_bloque("SEÑOR(ES)", 20, 20, 80), _bloque("ACEROS DEL SUR", 180, 20)]

    assert _extraer_asociaciones_geometricas(bloques)["cliente"] == "ACEROS DEL SUR"


def test_geometria_cliente_debajo_de_senores():
    bloques = [_bloque("SEÑOR(ES)", 20, 20, 80), _bloque("METALURGICA ANDINA", 25, 55)]

    assert _extraer_asociaciones_geometricas(bloques)["cliente"] == "METALURGICA ANDINA"


def test_geometria_cliente_dividido_en_dos_bloques():
    bloques = [
        _bloque("SEÑOR(ES)", 20, 20, 80),
        _bloque("ACEROS", 150, 20, 55),
        _bloque("NUBLE", 212, 20, 48),
    ]

    assert _extraer_asociaciones_geometricas(bloques)["cliente"] == "ACEROS NUBLE"


def test_geometria_no_depende_del_orden_ocr():
    etiqueta = _bloque("SEÑOR(ES)", 20, 20, 80)
    valor = _bloque("INDUSTRIAS PACIFICO", 180, 20)

    directo = _extraer_asociaciones_geometricas([etiqueta, valor])
    invertido = _extraer_asociaciones_geometricas([valor, etiqueta])

    assert directo == invertido == {"cliente": "INDUSTRIAS PACIFICO"}


def test_geometria_obra_destino_a_la_izquierda_de_etiqueta():
    bloques = [_bloque("PLANTA CENTRAL", 20, 20, 110), _bloque("OBRA DESTINO", 170, 20, 105)]

    assert _extraer_asociaciones_geometricas(bloques)["obra destino"] == "PLANTA CENTRAL"


def test_geometria_obra_destino_sobre_etiqueta():
    bloques = [_bloque("PROYECTO CORDILLERA", 100, 10), _bloque("OBRA DESTINO", 110, 45, 105)]

    assert _extraer_asociaciones_geometricas(bloques)["obra destino"] == "PROYECTO CORDILLERA"


def test_geometria_obra_destino_compone_nombre_y_sa_solo_si_ambos_existen():
    bloques = [
        _bloque("OBRA DESTINO", 20, 20, 105),
        _bloque("CONSTRUCTORA NORTE", 170, 20, 150),
        _bloque("SA", 326, 20, 24),
    ]

    assert _extraer_asociaciones_geometricas(bloques)["obra destino"] == "CONSTRUCTORA NORTE SA"


def test_geometria_no_inventa_sa():
    bloques = [_bloque("OBRA DESTINO", 20, 20, 105), _bloque("CONSTRUCTORA NORTE", 170, 20)]

    assert _extraer_asociaciones_geometricas(bloques)["obra destino"] == "CONSTRUCTORA NORTE"


def test_geometria_excluye_rut_telefono_codigo_hora_y_direccion():
    excluidos = [
        _bloque("RUT 76.123.456-7", 145, 20),
        _bloque("TELEFONO 987654321", 145, 20),
        _bloque("0001001424", 145, 20),
        _bloque("08:45:00", 145, 20),
        _bloque("DIRECCION GALVARINO 8501", 145, 20),
    ]
    etiqueta = _bloque("SEÑOR(ES)", 20, 20, 80)

    for candidato in excluidos:
        assert _extraer_asociaciones_geometricas([etiqueta, candidato]) == {}


def test_geometria_se_abstiene_ante_dos_candidatos_equivalentes():
    bloques = [
        _bloque("SEÑOR(ES)", 100, 50, 80),
        _bloque("EMPRESA NORTE", 190, 40, 100),
        _bloque("EMPRESA SUR", 190, 60, 100),
    ]

    assert _extraer_asociaciones_geometricas(bloques) == {}


def test_geometria_sin_candidato_se_abstiene():
    assert _extraer_asociaciones_geometricas([_bloque("OBRA DESTINO", 20, 20)]) == {}


def test_geometria_resultado_determinista_en_repeticiones():
    bloques = [_bloque("OBRA DESTINO", 20, 20, 105), _bloque("PLANTA ORIENTE", 170, 20)]

    resultados = [_extraer_asociaciones_geometricas(list(reversed(bloques))) for _ in range(5)]

    assert resultados == [{"obra destino": "PLANTA ORIENTE"}] * 5


def test_geometria_no_usa_nombre_de_archivo():
    # La función recibe exclusivamente bloques OCR, no una ruta o nombre de guía.
    assert _extraer_asociaciones_geometricas([_bloque("SEÑOR(ES)", 20, 20)]) == {}


def test_geometria_prefiere_nominal_frente_a_numerico_cercano():
    bloques = [
        _bloque("SEÑOR(ES)", 20, 20, 80),
        _bloque("0001001424", 110, 20),
        _bloque("INDUSTRIAS ANDINAS", 210, 20),
    ]

    assert _extraer_asociaciones_geometricas(bloques)["cliente"] == "INDUSTRIAS ANDINAS"


def test_geometria_excluye_montos_y_pesos_alfanumericos():
    etiqueta = _bloque("OBRA DESTINO", 20, 20, 105)

    for texto in ("TOTAL 5.585.996", "PESO BRUTO 21.052 KG", "IVA 1.061.339"):
        assert _extraer_asociaciones_geometricas([etiqueta, _bloque(texto, 140, 20)]) == {}


def test_geometria_sa_lejano_no_se_une():
    bloques = [
        _bloque("OBRA DESTINO", 20, 20, 105),
        _bloque("CONSTRUCTORA NORTE", 170, 20, 150),
        _bloque("SA", 410, 20, 24),
    ]

    assert _extraer_asociaciones_geometricas(bloques)["obra destino"] == "CONSTRUCTORA NORTE"


def test_geometria_ignora_cajas_ausentes_o_malformadas_sin_perder_validas():
    class Incompleto:
        texto = "RUIDO"

    bloques = [
        Incompleto(),
        BloqueOCR("RUIDO", ((1, 1),), 0.5),
        _bloque("SEÑOR(ES)", 20, 20, 80),
        _bloque("EMPRESA VALIDA", 150, 20),
    ]

    assert _extraer_asociaciones_geometricas(bloques) == {"cliente": "EMPRESA VALIDA"}


def test_geometria_cliente_y_destino_simultaneos_no_se_mezclan():
    bloques = [
        _bloque("SEÑOR(ES)", 20, 20, 80),
        _bloque("EMPRESA ANDINA", 150, 20),
        _bloque("OBRA DESTINO", 20, 90, 105),
        _bloque("PLANTA COSTA", 170, 90),
    ]

    assert _extraer_asociaciones_geometricas(bloques) == {
        "cliente": "EMPRESA ANDINA",
        "obra destino": "PLANTA COSTA",
    }


def _transporte(candidato, etiqueta="NRO. TRANSPORTE"):
    return _extraer_transporte_geometrico(
        [_bloque(etiqueta, 20, 20, 120), _bloque(candidato, 180, 20, 100)]
    )


def test_transporte_acepta_diez_digitos_y_conserva_ceros_iniciales():
    assert _transporte("0000348808") == {"valor": "0000348808", "corregido": False}


@pytest.mark.parametrize(
    "etiqueta", ["NRO. TRANSPORTE", "Nro, TRANSPORTE", "NRO TRANSPORTE", "NÚMERO TRANSPORTE", "TRANSPORTE"]
)
def test_transporte_reconoce_variantes_de_etiqueta(etiqueta):
    assert _transporte("0000348808", etiqueta)["valor"] == "0000348808"


@pytest.mark.parametrize(
    ("ocr", "esperado"),
    [
        ("O000348808", "0000348808"),
        ("000o348808", "0000348808"),
        ("D000348808", "0000348808"),
        ("000d348808", "0000348808"),
        ("Q000348808", "0000348808"),
        ("I000348808", "1000348808"),
        ("l000348808", "1000348808"),
        ("|000348808", "1000348808"),
        ("00do348808", "0000348808"),
    ],
)
def test_transporte_aplica_solo_sustituciones_autorizadas(ocr, esperado):
    assert _transporte(ocr) == {"valor": esperado, "corregido": True}


@pytest.mark.parametrize("ocr", ["OQD0348808", "000X348808", "000348808", "00000348808"])
def test_transporte_rechaza_dudosos_no_autorizados_o_longitud_invalida(ocr):
    assert _transporte(ocr) == {}


def test_transporte_acepta_solo_espacio_punto_y_guion_como_separadores():
    assert _transporte("00 00.34-8808")["valor"] == "0000348808"
    assert _transporte("0000/348808") == {}


@pytest.mark.parametrize(
    ("otra_etiqueta", "valor"),
    [
        ("ORDEN DE COMPRA", "4500205692"),
        ("CODIGO CLIENTE", "0001001424"),
        ("TELEFONO", "9876543210"),
        ("HORA ENTRADA", "0000084500"),
    ],
)
def test_transporte_excluye_numeros_mas_cercanos_a_otras_etiquetas(otra_etiqueta, valor):
    bloques = [
        _bloque("NRO TRANSPORTE", 20, 20, 120),
        _bloque(otra_etiqueta, 170, 20, 120),
        _bloque(valor, 300, 20, 100),
    ]

    assert _extraer_transporte_geometrico(bloques) == {}


def test_transporte_rechaza_numero_cercano_fuera_de_la_zona_de_etiqueta():
    bloques = [_bloque("NRO TRANSPORTE", 20, 20, 120), _bloque("0000348808", 500, 200)]

    assert _extraer_transporte_geometrico(bloques) == {}


def test_transporte_se_abstiene_ante_dos_candidatos_equivalentes():
    bloques = [
        _bloque("NRO TRANSPORTE", 20, 50, 120),
        _bloque("0000348808", 180, 40, 100),
        _bloque("0000349909", 180, 60, 100),
    ]

    assert _extraer_transporte_geometrico(bloques) == {}


def test_transporte_etiqueta_sin_candidato_y_ausencia_de_etiqueta_se_abstienen():
    assert _extraer_transporte_geometrico([_bloque("NRO TRANSPORTE", 20, 20)]) == {}
    assert _extraer_transporte_geometrico([_bloque("0000348808", 180, 20)]) == {}


def test_transporte_ignora_cajas_malformadas():
    bloque_malo = BloqueOCR("0000348808", ((1, 1),), 0.5)

    assert _extraer_transporte_geometrico([_bloque("NRO TRANSPORTE", 20, 20), bloque_malo]) == {}


def test_transporte_es_independiente_del_orden_y_determinista():
    bloques = [_bloque("NUMERO TRANSPORTE", 20, 20, 140), _bloque("000o348808", 190, 20)]
    esperado = {"valor": "0000348808", "corregido": True}

    assert _extraer_transporte_geometrico(bloques) == esperado
    assert [_extraer_transporte_geometrico(list(reversed(bloques))) for _ in range(5)] == [esperado] * 5


def test_transporte_no_recibe_nombre_de_archivo():
    assert _extraer_transporte_geometrico([]) == {}


def test_consenso_focal_dos_lecturas_iguales():
    resultado = _consensuar_transporte_focal(["0000348808", "0000348808"])

    assert resultado["valor"] == "0000348808"


def test_consenso_focal_mayoria_dos_a_uno_por_posicion():
    resultado = _consensuar_transporte_focal(
        ["000o348808", "000o348808", "000o348608"]
    )

    assert resultado["valor"] == "0000348808"
    assert resultado["posiciones"][7] == {"8": 2, "6": 1}


def test_consenso_focal_empate_en_una_posicion_abstiene_completo():
    resultado = _consensuar_transporte_focal(["0000348808", "0000348608"])

    assert "valor" not in resultado
    assert resultado["motivo"] == "candidatos-exactos-conflictivos"


def test_consenso_focal_ruido_separado_con_un_unico_segmento_valido():
    resultado = _consensuar_transporte_focal(
        ["000o348608", "000o348608", "oo 00do348808", "oo 0000348808"]
    )

    assert resultado["normalizados"] == [
        "0000348608", "0000348608", "0000348808", "0000348808"
    ]
    assert resultado["valor"] == "0000348808"
    assert resultado["motivo"] == "evidencia-exacta-con-respaldo-independiente"


def test_consenso_focal_una_sola_lectura_valida_abstiene():
    resultado = _consensuar_transporte_focal(["0000348808"])

    assert "valor" not in resultado
    assert resultado["motivo"] == "evidencia-exacta-sin-respaldo"


def test_consenso_focal_longitudes_invalidas_no_completan_posiciones():
    resultado = _consensuar_transporte_focal(["000348808", "00000348808"])

    assert resultado["normalizados"] == []
    assert "valor" not in resultado


@pytest.mark.parametrize("global_ocr", ["0000348808", "00do348608"])
def test_consenso_focal_no_deja_que_global_prevalezca_sobre_dos_focales(global_ocr):
    resultado = _consensuar_transporte_focal(
        ["0000348808", "0000348808"], global_ocr
    )

    assert resultado["valor"] == "0000348808"
    assert resultado["global"][0] in {"0000348808", "0000348608"}


def test_consenso_no_contiene_sustitucion_general_seis_a_ocho():
    resultado = _consensuar_transporte_focal(["0000348608", "0000348608"])

    assert resultado["valor"] == "0000348608"


def test_jerarquia_exacta_mas_respaldo_normalizado_coincidente():
    resultado = _consensuar_transporte_focal(["oo 0000348808", "oo 00do348808"])

    assert resultado["valor"] == "0000348808"
    assert [e["categoria"] for e in resultado["evidencias"]] == ["EXACTA", "NORMALIZADA_2"]


def test_jerarquia_exacta_mas_respaldo_exacto():
    resultado = _consensuar_transporte_focal(["0000348808", "00 00 34 88 08"])

    assert resultado["valor"] == "0000348808"
    assert [e["categoria"] for e in resultado["evidencias"]] == ["EXACTA", "EXACTA"]


def test_jerarquia_exacta_unica_sin_respaldo_abstiene():
    resultado = _consensuar_transporte_focal(["0000348808", "000o348608"])

    assert "valor" not in resultado
    assert resultado["motivo"] == "evidencia-exacta-sin-respaldo"


def test_jerarquia_dos_exactas_conflictivas_abstiene():
    resultado = _consensuar_transporte_focal(["0000348808", "0000348608"])

    assert "valor" not in resultado
    assert resultado["motivo"] == "candidatos-exactos-conflictivos"


def test_jerarquia_exacta_respaldada_supera_dos_normalizadas_distintas():
    resultado = _consensuar_transporte_focal(
        ["oo 0000348808", "oo 00do348808", "000o348608", "000o348608"]
    )

    assert resultado["valor"] == "0000348808"


def test_jerarquia_dos_candidatos_solo_normalizados_empatados_abstiene():
    resultado = _consensuar_transporte_focal(["000o348808", "000o348608"])

    assert "valor" not in resultado
    assert resultado["motivo"] == "sin-mayoria-posicion-7"


def test_jerarquia_caso_sintetico_obligatorio():
    resultado = _consensuar_transporte_focal(
        ["oo 0000348808", "oo 00do348808", "000o348608"]
    )

    assert resultado["valor"] == "0000348808"
    assert resultado["motivo"] == "evidencia-exacta-con-respaldo-independiente"


@pytest.mark.parametrize("texto", ["oo 0000348808", "00 00 34 88 08", "0000.348-808"])
def test_clasificacion_detecta_exacta_con_ruido_o_separadores_permitidos(texto):
    evidencia = _clasificar_evidencia_transporte(texto, "variante", 0.8)

    assert evidencia["categoria"] == "EXACTA"
    assert evidencia["candidato"] == "0000348808"
    assert evidencia["sustituciones"] == 0
    assert evidencia["confianza"] == 0.8


def test_clasificacion_extrae_exacta_rodeada_por_letras_exteriores():
    evidencia = _clasificar_evidencia_transporte("A0000348808B")

    assert evidencia["categoria"] == "EXACTA"
    assert evidencia["candidato"] == "0000348808"


def test_clasificacion_once_digitos_no_contiene_exacta_de_diez():
    evidencia = _clasificar_evidencia_transporte("00000348808")

    assert evidencia["categoria"] == "INVALIDA"


def test_clasificacion_letra_interna_es_normalizada_no_exacta():
    evidencia = _clasificar_evidencia_transporte("000o348608")

    assert evidencia["categoria"] == "NORMALIZADA_1"
    assert evidencia["directa"] is False


def test_jerarquia_es_determinista_y_no_sustituye_seis_por_ocho():
    lecturas = ["oo 0000348808", "oo 00do348808", "000o348608"]

    assert [_consensuar_transporte_focal(lecturas)["valor"] for _ in range(5)] == ["0000348808"] * 5
    assert _clasificar_evidencia_transporte("0000348608")["candidato"] == "0000348608"


def test_jerarquia_independiente_del_orden_de_variantes():
    lecturas = [
        {"variante": "a", "texto": "oo 0000348808"},
        {"variante": "b", "texto": "oo 00do348808"},
        {"variante": "c", "texto": "000o348608"},
    ]

    assert _consensuar_transporte_focal(lecturas)["valor"] == "0000348808"
    assert _consensuar_transporte_focal(list(reversed(lecturas)))["valor"] == "0000348808"


def test_jerarquia_no_cuenta_dos_veces_la_misma_variante():
    lecturas = [
        {"variante": "original", "texto": "0000348808"},
        {"variante": "original", "texto": "0000348808"},
        {"variante": "grises", "texto": "000o348608"},
    ]

    resultado = _consensuar_transporte_focal(lecturas)

    assert "valor" not in resultado
    assert resultado["motivo"] == "evidencia-exacta-sin-respaldo"
    assert len(resultado["evidencias"]) == 2


def test_clasificacion_dos_secuencias_exactas_distintas_es_invalida():
    evidencia = _clasificar_evidencia_transporte("0000348808 0000348608")

    assert evidencia["categoria"] == "INVALIDA"
    assert evidencia["motivo"] == "secuencia-numerica-mayor"


@pytest.mark.parametrize("confianza", [None, "alta", float("nan"), float("inf")])
def test_confianza_invalida_se_conserva_sin_decidir(confianza):
    lecturas = [
        {"variante": "a", "texto": "0000348808", "confianza": confianza},
        {"variante": "b", "texto": "000o348808", "confianza": 0.1},
    ]

    resultado = _consensuar_transporte_focal(lecturas)

    assert resultado["valor"] == "0000348808"
    assert resultado["evidencias"][0]["confianza"] is confianza


def test_confianza_no_desplaza_jerarquia_de_evidencia():
    lecturas = [
        {"variante": "exacta", "texto": "0000348808", "confianza": 0.01},
        {"variante": "respaldo", "texto": "000o348808", "confianza": 0.02},
        {"variante": "conflicto", "texto": "000o348608", "confianza": 0.99},
    ]

    assert _consensuar_transporte_focal(lecturas)["valor"] == "0000348808"


def probar_guia1():
    textos = [
        "RUT. 92.176.000-0 GUIA DE DESPACHO ELECTRÓNICA N° 462429 SOLICITANTE EMPRESA CONST SIGRO SA TELEFONO OBRA DESTINO EMPRESA CONST SIGRO COD DESTINATARIO 0002012245 HORA ENTRADA 13,11:00 HORA SALIDA 13:55;54 Nro. TRANSPORTE 0000346311",
        "Código cliente 0001003518 FECHA DE EMISIÓN 02-07-2026 SEÑOR(ES) PRODALAK Rut. 93.772 000 GIRO VENTA POR MAYOR",
        "VALOR TOTAL 10.425.558 ENTREGA 03.07 PEDIDO 28 TORRE PESO KG 12.441 DESPACHAR A AVDA IRARRAZAVAL 5497 SANTIAGO ÑUÑOA RUT ChoFER 18611137-0 FECHA SALIDA 02-07-2026",
        "RETIRA PATENTE FECHA LLEGADA LEANDRO TOLEDO BKYX63",
    ]

    datos = extraer_datos(textos)

    assert datos["número de guía"] == "462429", datos
    assert datos["número de transporte"] == "0000346311", datos
    assert datos["cliente"] == "PRODALAM SA", datos
    assert datos["obra destino"] == "EMPRESA CONST SIGRO", datos
    assert datos["RUT del cliente"] == "93.772.000", datos
    assert datos["chofer"] == "LEANDRO TOLEDO", datos
    assert datos["RUT del chofer"] == "18611137-0", datos
    assert datos["patente del tracto"] == "BKYX63", datos
    assert datos["patente del carro"] == "No encontrado", datos
    assert datos["hora de entrada"] == "11:00", datos
    assert datos["hora de salida"] == "13:55", datos
    assert datos["peso"] == "12.441", datos


def probar_guia2():
    textos = [
        "RUT. 92.176.000-0 GUIA DE DESPACHO ELECTRÓNICA N° 462474 Código Cliente 0001000197 FECHA DE EMISIÓN 03-07-2026 SEÑOR(ES) AMERICAN SCREW CHILE SPA RUT 91.410 .000 GIRO FABRICACION DE CABL DIRECCION CAMINO MELIPILLA 10800",
        "ORDEN DE COMPRA SOLICITANTE TELEFONO OBRA DESTINO COD DESTINATARIO HORA ENTRADA HORA SALIDA Nro. TRANSPORTE",
        "1600052285 0030020250 AMERICAN SCREW CHILE SPA",
        "AMERICAN SCREW CHILE SPA 0001000197 06:59 00 09:30 : 10 0000346352",
        "VALOR TOTAL 26.000.702 03/07 HASTA LAS 15 JENNY 956058217 PESO KG- 27.398 00 DESPACHAR A CAMINO A MELIPILLA 10800 MAIPU RUT ChoFER 14293816-2 FECHA SALIDA 03 07-2026",
        "RETIRA PATENTE FECHA LLEGADA LUIS VARAS DD2494 CARRO : JB8529",
    ]

    datos = extraer_datos(textos)

    assert datos["número de guía"] == "462474", datos
    assert datos["número de transporte"] == "0000346352", datos
    assert datos["cliente"] == "AMERICAN SCREW CHILE SPA", datos
    assert datos["obra destino"] == "AMERICAN SCREW CHILE SPA", datos
    assert datos["RUT del cliente"] == "91.410.000", datos
    assert datos["chofer"] == "LUIS VARAS", datos
    assert datos["RUT del chofer"] == "14293816-2", datos
    assert datos["patente del tracto"] == "DD2494", datos
    assert datos["patente del carro"] == "JB8529", datos
    assert datos["hora de entrada"] == "06:59", datos
    assert datos["hora de salida"] == "09:30", datos
    assert datos["peso"] == "27.398", datos


def probar_guia3():
    textos = [
        "RUT. 92.176.000-0 GUIA DE DESPACHO ELECTRONICA N° 462654 SANTIAGO PONIENTE Numero SAP ORDEN DE COMPRA 4300000509 0030020353 SOLICITANTE COYSIRUCIORA POCURO S?4 TELEFONO 86228064 OBRA DESTINO CCNSIRUCIOAA PCCURO Spa COD DESTINATARIO 0002012926 HORA ENTRADA 1118:00 HORA SALIDA 12,02630 Nro. TRANSPORTE 0000347050",
        "Codigo Cliente 0001000047 FECHA DE EMISION SENOR(ES) Rut: Giro DIRECCION COMUNA CIUDAD INDICADOR TRASLADO empresa TRANSPORTE 07-07-2026 ACMA 92,190,000 INDUSTRIAS BASICAS MARURI 1942 RENCA SANTIAGO Operacion constituye Venta TRANSPORTES Yat SPA",
        "DESCRIPCION HORMIGON 10vN 12K A630-420 Coladas 2617697002 HORMIGON 12KX 12k a630-420k Coladas 2617717302",
        "250 000 Peso Bruto 14-270,00",
        "CAJA 07/07 15:00 SZRGIO 963063650 556.460 020400 EDUARDO FREI KONTALVA 16no MAI?U KAIPD PDTE 18098153 07-07-2026 VALOR TOTAL : PESOKG DESPACHAR A rut Chofer FECHA SALIDA",
        "retira PATENTE FECHA LLEGADA PAIRICIO VILLAGRA 2DRG50 07/07 2026",
    ]

    datos = extraer_datos(textos)

    assert datos["número de guía"] == "462654", datos
    assert datos["número de transporte"] == "0000347050", datos
    assert datos["cliente"] == "ACMA SA", datos
    assert datos["obra destino"] == "CONSTRUCTORA POCURO SPA", datos
    assert datos["RUT del cliente"] == "92.190.000-7", datos
    assert datos["chofer"] == "PATRICIO VILLAGRA", datos
    assert datos["RUT del chofer"] == "18098153-5", datos
    assert datos["patente del tracto"] == "BDFG50", datos
    assert datos["patente del carro"] == "No encontrado", datos
    assert datos["hora de entrada"] == "11:18", datos
    assert datos["hora de salida"] == "12:02", datos
    assert datos["peso"] == "14.270,000", datos



def probar_guia6():
    textos = [
        "RUT: 92.176.000-0 GUIA DE DESPACHO ELECTRONICA N? 462491",
        "Codigo Cliente 0001001 Fecha DE EMISION SENOR(ES) RUT Giro DIRECCION COMUNA Ciudad",
        "Numero Sap 0000577916 2026 FERROLUBAC 490 VEXia PoRKEVOR DustmiE 120 720 RUROA Santiago",
        "Operacion Consiliuye Venta Transportes VPI SPA",
        "Onofm De Compha solicitante Telefono opna destino Cod Destinataio Hoaa Entrada HOAA Salida Nro Taanspoate",
        "1e1an 0070020 14 ferrolujac Pedro 82 Gfa YESAOLUJAC Pedro D3 Oha 0002000ad 0000846170",
        "VALOR TOTAL 029.286 PesoKG 3282 DespachAR Pedro DE ON 19 RUROA NUÑOR Rut Chofer 17576134 FeCHA Salida 03-07-2026",
        "960 Doo 2030 Bruto 12+242,000",
        "Nombre Rut FECHA Recinto Firma Acube DE Precio",
    ]

    datos = extraer_datos(textos)

    assert datos["número de guía"] == "462491", datos
    assert datos["número de transporte"] == "0000346370", datos
    assert datos["cliente"] == "FERROLUSAC SA", datos
    assert datos["obra destino"] == "FERROLUSAC PEDRO DE OÑA", datos
    assert datos["RUT del cliente"] == "96.596.450-9", datos
    assert datos["chofer"] == "CRISTOPHER RETAMAL", datos
    assert datos["RUT del chofer"] == "17576134-9", datos
    assert datos["patente del tracto"] == "BPHR67", datos
    assert datos["patente del carro"] == "No encontrado", datos
    assert datos["hora de entrada"] == "10:15", datos
    assert datos["hora de salida"] == "10:36", datos
    assert datos["peso"] == "12.242,000", datos



def probar_guia7():
    textos = [
        "RUT.: 92.176.000-0 GUIA DE DESPACHO ELECTRONICA N? 462793",
        "SLL SANTIAGO PONIENTE CODIGO 0001001411 FECHA DE EMISION 02072026 SENOR(ES) DSI RUT UNDERGROUND CHILE SPA",
        "VENTA AL POR MAYOR DIRECCION AVDA CORDILLERA 482 COMUNA QUILICURA CIUDAD SANTIAGO",
        "Numero SAP 0000579034 ORDEN DE COMPRA P0013429 SOLICITANTE DSI UNDERGROUND CHILE Spa",
        "TELEFONO OBRA DESTINO Ds1 UNDERGROUND CHILE Spa COD DESTINATARIO 0002002906",
        "HORA ENTRADA 01:00 HORA SALIDA 02 : 2 Nro TRANSPORTE d00d3/7265",
        "VALOR TOTAL 26.926.530 PESO KG 26.846",
        "Victor Rodriguez A. Rut: 17.519.432-0 Fecha: 07/26",
        "DESPACHAR A RUT Chofer FECHA SALIDA",
        "Las VIOLETAS 55 SECTOR 10833150-K",
        "retira PATENTE FECHA LLEGADA JOSE LAZCASO RL1E79 CRARO: JK2501 09-07-2026",
        "09-07-2026 2 20.926 538 IVA 19 00%",
    ]

    datos = extraer_datos(textos)

    assert datos["número de guía"] == "462793", datos
    assert datos["número de transporte"] == "0000347265", datos
    assert datos["cliente"] == "DSI UNDERGROUND CHILE SPA", datos
    assert datos["obra destino"] == "DSI UNDERGROUND CHILE SPA", datos
    assert datos["RUT del cliente"] == "76083093-3", datos
    assert datos["chofer"] == "JOSE LAZCANO", datos
    assert datos["RUT del chofer"] == "10833150-K", datos
    assert datos["patente del tracto"] == "AL1879", datos
    assert datos["patente del carro"] == "JK2501", datos
    assert datos["hora de entrada"] == "07:01", datos
    assert datos["hora de salida"] == "09:02", datos
    assert datos["peso"] == "41.886,000", datos



def probar_guia8():
    textos = [
        "RUT.: 92.176.000-0 GUIA DE DESPACHO ELECTRONICA N? 462833",
        "Sui : SANTIAGO PONIENTE Numero SAP 0080589226 PED252644 0020020731 AGF ACEROS DE CHILE SPA",
        "AGF ACEROS DE CRILE Spa 0002001737 12216300 13851:5 0000347401",
        "Codigo Cliente 0001006226 FECHA DE EMISION 07-2026 SENOR(ES) MGF ACEROS DE CHILE Spa",
        "RUT. 4104131 GIRO Construccion PIOY DIRECCION APOQUINDO OI . 605 PISO 6410 COMUNA CONDES CIUDAD SANTIAGO",
        "EMPRESA TRANSPORTE IranSpORTES HaT",
        "ORDEN DE COMPRA SOLICITANTE TELEFONO OBRA DESTINO COD DESTINATARIO hora EnTRADA HORA SALIDA Nro. TAANSPORTE",
        "DESCRIPCION ROLLO HORMIGON 16x11 1gjo 20H Golagas 2616976102 2617620212",
        "UNIDAD PrECIo VaLOA 836, 00 12,881 .736",
        "14 . 770, 000 Pasg aruro 30.142 000",
        "VALOR TOTAL 12.881,736 PESOKG 150272, 00",
        "DESPACHAR rut Chofer FECHA SALIDA PANIERICANA NORTE 22650 SANTIAGO LAMPA 18091586",
        "retira PATENTE FECHA LLEGADA SALCKON PIZARRO 1G8925 CARRO: JF9565 10-07 2026",
        "09-07-2026 NETO $ 881.736 IVA 19.0096",
    ]

    datos = extraer_datos(textos)

    assert datos["número de guía"] == "462833", datos
    assert datos["número de transporte"] == "0000347401", datos
    assert datos["cliente"] == "AGF ACEROS DE CHILE SPA", datos
    assert datos["obra destino"] == "AGF ACEROS DE CHILE SPA", datos
    assert datos["RUT del cliente"] == "77410131-4", datos
    assert datos["chofer"] == "SALOMÓN PIZARRO", datos
    assert datos["RUT del chofer"] == "18091588-5", datos
    assert datos["patente del tracto"] == "TG8925", datos
    assert datos["patente del carro"] == "JF9565", datos
    assert datos["hora de entrada"] == "12:46", datos
    assert datos["hora de salida"] == "13:54", datos
    assert datos["peso"] == "30.142,000", datos



def probar_guia9():
    textos = [
        "RUT.: 92.176.000-0 GUIA DE DESPACHO ELECTRÓNICA N° 461878",
        "SLL SANTIAGO PONIENTE INVICTOPA TAF CPISloaalf Obra CASAALIDA 136",
        "Codigo Cliente 0061000Peo FECHA DE EMISION 24206-2026 SeNoR(ES) Alsix nos Ltda",
        "RUT 293.200 GIRO VEAL MESCA PINT Direccion VATECAA 25 COMUNA GAYtinGO",
        "DESTINO InvICTOPA Taf CPISloaalf Obra SALIDA 136",
        "Nro. TAANSPORTE 0000345062",
        "VALOR TOTAL PESOkg DESPACHA A RuT Chofea FECHA SALDA",
        "COLO COLO 341 QUILICURA 175/6134 247062026",
        "RETIRA PATENTE FECHA LLEGADA CRISIOPWER RIAAI 121A67 24-06-2026",
        "20,636,0U0",
        "TOTAL $ 124824.960",
    ]

    datos = extraer_datos(textos)

    assert datos["número de guía"] == "461878", datos
    assert datos["número de transporte"] == "0000345062", datos
    assert datos["cliente"] == "AUSIN HNOS LTDA", datos
    assert datos["obra destino"] == "CONSTRUCTORA SAN CRISTOBAL LTDA", datos
    assert datos["RUT del cliente"] == "81293200-4", datos
    assert datos["chofer"] == "CRISTOPHER RETAMAL", datos
    assert datos["RUT del chofer"] == "17576134-9", datos
    assert datos["patente del tracto"] == "BPHR67", datos
    assert datos["patente del carro"] == "No encontrado", datos
    assert datos["hora de entrada"] == "10:47", datos
    assert datos["hora de salida"] == "11:36", datos
    assert datos["peso"] == "20.636,000", datos



def probar_guia10():
    textos = [
        "RUT.: 92.176.000-0 GUIA DE DESPACHO ELECTRÓNICA N? 462544",
        "Codigo Cliente 0001001230 Numero SAP 0080538083",
        "FECHA DE EMISIÓN SEÑOR(ES) RUT GIRO DIRECCION COMUNA CIUDAD INDICADOR TRASLADO EMPRESA TRANSPORTE",
        "06-07-2026 FERRETERIA COVADONGA LTDA 707 000 VTA AL X MENOR MAI AVDA MATTA 067 SANTIAGO SANTIAGO",
        "Operacion constituye Venta TRANSPORTES MBT SPA",
        "ORDEN DE COMPRA SOLICITANTE TELEFONO OBRA DESTINO COD DESTINATARIO HORA ENTRADA HORA SALIDA Nro TRANSPORTE",
        "4268 0030020519 HG CONSTRUCTORA SPA 961251716 HG CONSTRUCTORA SPA 0002012885 08 : 46:00 09: 46:54 0000346760",
        "Tara 7.680,000 Peso Bruto 14 971,000",
        "VALOR TOTAL 6.729.593 Herman 9647 6583 PESO KG 7.291,00",
        "DESPACHAR A VITA MORADA 6480 VITACURA VITACURA RUT ChoFeR 18611137-0 FECHA SALIDA 06-07-2026",
        "RETIRA PATENTE FECHA LLEGADA LEANDRO TOLEDO BKYK63",
        "06-07-2026",
    ]

    datos = extraer_datos(textos)

    assert datos["número de guía"] == "462544", datos
    assert datos["número de transporte"] == "0000346760", datos
    assert datos["cliente"] == "FERRETERIA COVADONGA LTDA", datos
    assert datos["obra destino"] == "HG CONSTRUCTORA SPA", datos
    assert datos["RUT del cliente"] == "94707000-2", datos
    assert datos["chofer"] == "LEANDRO TOLEDO", datos
    assert datos["RUT del chofer"] == "18611137-0", datos
    assert datos["patente del tracto"] == "BKYK63", datos
    assert datos["patente del carro"] == "No encontrado", datos
    assert datos["hora de entrada"] == "08:46", datos
    assert datos["hora de salida"] == "09:46", datos
    assert datos["peso"] == "14.971,000", datos


def test_guia11():
    textos = [
        "ACEROS AZA S A AZA FUNDICION LAMINACION EXPORTACION GIRO; Casa IhiZ FlANIA RENCA Hae LA UNION 2070 RENCA SANIinGO CHILE COD FosTal 16 76 22 Fono (5612287 79100 Www a2rci Colle Heclty Gtvroz Cato 21 CCO su10; Nindo Uaw  Cuxey / lotnusta Sucwurse Antoco Calle Wnane 02875*Baito Indusi Mdci Tlko Fon 45 22 1d3 Guuiza] Suusf ukhano Ale Ruyrul J01 C Lnchennt PananojnVl Nona Ka, 6 CM 21871tu809 Fono 800) 72077 Sucursn] Corio",
        "RUT: 92.176.000-0 GUIA DE DESPACHO ELECTRONICA N? 462871",
        "511 < sahtiago Poniekte",
        "Mumero Sap",
        "0040539156",
        "Codigo Cllenle",
        "0001000aeo",
        "oadeM De Compra SOLICITANTE telefono obha Destino Coo Destinatario Hora EntradA Hora alida Nro TRANSPOATE",
        "Movozaiga 00j09207 -1 Cowst CEppo apoquinDo Cuat7o",
        "FECHA DE EMISION 0722026 SenoR(eS) AUSiX Hnos UIDA Rut 200 Giao i MENORPINT , DIRECCION Fatueana Cohuna Santingo CiuoaD EANTICO indicAdor TrasLAdo Operacion Conat Luvo Venga Evdaesa Taanspoate IRAKSPORTES Kat Spa descripciok Caandad cooigo Ioraigoy 16pM 12k A6jo 420h 711 00o? Capoon 2617710202 HORKIGOX !2h !2h 46do 420u 1220002*16 a 2617715402",
        "Crppo Roquinto Cuai7o 000z012506 0e ; 5 106 10400 Dooo)17469",
        "Unioad Paecio",
        "Valoa 24824 J0",
        "773,00",
        "dla",
        "en",
        "870,000 Yodo Brulo",
        "17.772,Odo",
        "IpoDE DOCUMENIO",
        "FOLIO",
        "FECHA",
        "MonvO",
        "8-216+346 Felpl O11varos 156 85005602 VAIOR IOTAL ; PESOKG 902400 VIStA PAFORIEICA 10901 Santiago Lo PaaneChEA retirA DespachaR A PATENTE RUT Chofer 17576134 FECHA 10-07 2026 Fecha Salida LLEGADA IVA 19.009 $ 1, 561 144 TOTAL EXENTO $ 8ez16 346 Neto $ F3uo pal KOMeRE Fecha Rut Qti L Abiek Firiaa REcinio 6Lo DispiestoEnuLeTAALI DEL Acuse 0ERECIBO Qe Eneste ACTOAOEEAEUERDC ^L EniheoA DE Heicadfa ^5 VIF DELNi Jacaedi Serv cios5) paestabois boohecib Dos)",
        "Cristopher REILAL BpHR6 /",
        "1J70772026",
        "IOTAL $",
        "447772090",
        "Ilmbre Elecuonlco SIl Res80 d0 2014 Venlique docur Cedible Con SU FACTURA",
        "JU 203s Soluclon 00 Fociurn Electronica w Snbmel€ 22",
    ]

    datos = extraer_datos(textos)

    assert datos["número de guía"] == "462871", datos
    assert datos["número de transporte"] == "0000347469", datos
    assert datos["cliente"] == "AUSIN HNOS LTDA", datos
    assert datos["obra destino"] == "CONST CERRO APOQUINDO CUATRO", datos
    assert datos["RUT del cliente"] == "81293200-4", datos
    assert datos["chofer"] == "CRISTOPHER RETAMAL", datos
    assert datos["RUT del chofer"] == "17576134-9", datos
    assert datos["patente del tracto"] == "BPHR67", datos
    assert datos["patente del carro"] == "No encontrado", datos
    assert datos["hora de entrada"] == "08:53", datos
    assert datos["hora de salida"] == "10:00", datos
    assert datos["peso"] == "17.772,000", datos



def probar_guia5():
    textos = [
        "RUT.: 92.176.000-0 GUIA DE DESPACHO ELECTRONICA N° 462395",
        "AMERICAN SCREW CHILE SPA SOLICITANTE TELEFONO OBRA DESTINO",
        "SENOR(ES) AMERICAN SCREW CHILE SPA RUT 91.410.000-3",
        "HORA ENTRADA 08:13:00 HORA SALIDA 09:34:10 NRO TRANSPORTE 0000346245",
        "RETIRA PATENTE FECHA LLEGADA RODRIGO NAHUELÑIR SB6486 CARRO JF4288",
        "RUT CHOFER 15454297",
        "PESO BRUTO 43.624,000",
    ]

    datos = extraer_datos(textos)

    assert datos["número de guía"] == "462395", datos
    assert datos["número de transporte"] == "0000346245", datos
    assert datos["cliente"] == "AMERICAN SCREW CHILE SPA", datos
    assert datos["obra destino"] == "AMERICAN SCREW CHILE SPA", datos
    assert datos["RUT del cliente"] == "91410000-3", datos
    assert datos["chofer"] == "RODRIGO NAHUELÑIR", datos
    assert datos["RUT del chofer"] == "15454297-3", datos
    assert datos["patente del tracto"] == "SB6486", datos
    assert datos["patente del carro"] == "JF4288", datos
    assert datos["hora de entrada"] == "08:13", datos
    assert datos["hora de salida"] == "09:34", datos
    assert datos["peso"] == "43.624,000", datos


def main():
    probar_guia1()
    probar_guia2()
    probar_guia3()
    print("Todas las pruebas de extracción pasaron correctamente.")


if __name__ == "__main__":
    main()
