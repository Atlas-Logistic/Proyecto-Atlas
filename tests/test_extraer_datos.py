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
    _chofer_lineal_contaminado,
    _clasificar_evidencia_transporte,
    _consensuar_transporte_focal,
    _extraer_asociaciones_geometricas,
    _extraer_chofer_geometrico,
    _extraer_fecha_geometrico,
    _extraer_identidad_cliente_recortada_geometrica,
    _extraer_patentes_geometrico,
    _extraer_rut_cliente_geometrico,
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


def test_asociacion_cliente_es_equivalente_a_distintas_resoluciones():
    def escena(escala):
        return [
            _bloque("SEÑOR(ES)", 20 * escala, 20 * escala, 80 * escala, 18 * escala),
            _bloque("DSI UNDERGROUND CHILE SPA", 180 * escala, 20 * escala, 210 * escala, 18 * escala),
        ]

    assert _extraer_asociaciones_geometricas(escena(1))["cliente"] == "DSI UNDERGROUND CHILE SPA"
    assert _extraer_asociaciones_geometricas(escena(4))["cliente"] == "DSI UNDERGROUND CHILE SPA"


def test_rut_multibloque_sin_guion_se_reconstruye_solo_con_dv_valido():
    base = [
        _bloque("SEÑOR(ES)", 20, 100, 80),
        _bloque("R.U.T.", 20, 121, 50),
    ]
    valido = base + [
        _bloque("76", 90, 121, 20), _bloque("083", 112, 121, 28),
        _bloque("093", 142, 121, 28), _bloque("3", 172, 121, 12),
    ]
    invalido = base + [
        _bloque("76", 90, 121, 20), _bloque("083", 112, 121, 28),
        _bloque("093", 142, 121, 28), _bloque("4", 172, 121, 12),
    ]

    # `validar_rut_chileno` siempre devuelve el formato canónico (con
    # puntos), sin importar si el candidato de entrada los traía -- mismo
    # formato que ya usa el resto de esta función (ver caso real 472593).
    assert _extraer_rut_cliente_geometrico(valido) == {"valor": "76.083.093-3"}
    assert _extraer_rut_cliente_geometrico(invalido) == {}


def test_identidad_cliente_recortada_exige_nombre_y_rut_valido_en_borde():
    bloques = [
        _bloque("S)", 0, 100, 13, 15),
        _bloque("EMPRESA SEGURA SA", 90, 98, 120, 12),
        _bloque("90.970.000-0", 90, 111, 93, 15),
    ]

    assert _extraer_identidad_cliente_recortada_geometrica(bloques) == {
        "cliente": "EMPRESA SEGURA SA",
        "rut": "90.970.000-0",
    }


def test_identidad_cliente_recortada_se_abstiene_sin_rut_valido_o_fuera_del_borde():
    sin_rut_valido = [
        _bloque("S)", 0, 100, 13, 15),
        _bloque("EMPRESA SEGURA SA", 90, 98, 120, 12),
        _bloque("90.970.000-1", 90, 111, 93, 15),
    ]
    fuera_borde = [
        _bloque("S)", 20, 100, 13, 15),
        _bloque("EMPRESA SEGURA SA", 90, 98, 120, 12),
        _bloque("90.970.000-0", 90, 111, 93, 15),
    ]

    assert _extraer_identidad_cliente_recortada_geometrica(sin_rut_valido) == {}
    assert _extraer_identidad_cliente_recortada_geometrica(fuera_borde) == {}


def test_identidad_cliente_recortada_se_abstiene_ante_dos_parejas_validas():
    bloques = [
        _bloque("S)", 0, 100, 13, 15),
        _bloque("EMPRESA UNO SA", 90, 98, 110, 12),
        _bloque("90.970.000-0", 90, 111, 93, 15),
        _bloque("EMPRESA DOS SA", 215, 98, 110, 12),
        _bloque("12.345.678-5", 215, 111, 93, 15),
    ]

    assert _extraer_identidad_cliente_recortada_geometrica(bloques) == {}


def test_identidad_cliente_recortada_rechaza_campo_estructural_como_nombre():
    bloques = [
        _bloque("S)", 0, 100, 13, 15),
        _bloque("DIRECCION CLIENTE", 90, 98, 130, 12),
        _bloque("90.970.000-0", 90, 111, 93, 15),
    ]

    assert _extraer_identidad_cliente_recortada_geometrica(bloques) == {}


def test_geometria_cliente_tolera_s_inicial_recortada_de_senores():
    """Una foto puede recortar solo la S inicial de SEÑOR(ES), sin volver
    permisivo el reconocimiento de etiquetas por subcadena."""
    bloques = [_bloque("EÑORIES)", 0, 20, 65), _bloque("ARMACERO MATCO", 180, 20)]

    assert _extraer_asociaciones_geometricas(bloques)["cliente"] == "ARMACERO MATCO"


def test_geometria_cliente_descarta_rut_con_r_inicial_recortada():
    bloques = [
        _bloque("EÑORIES)", 0, 20, 65),
        _bloque("ARMACERO MATCO", 180, 20),
        _bloque("UT", 0, 42, 27),
    ]

    assert _extraer_asociaciones_geometricas(bloques)["cliente"] == "ARMACERO MATCO"


def test_geometria_cliente_no_confunde_emision_recortada_con_empresa():
    bloques = [
        _bloque("CHA DE EMISIÓN", 0, 0, 118),
        _bloque("EÑORIES)", 0, 24, 65),
        _bloque("ARMACERO MATCO", 180, 24),
    ]

    assert _extraer_asociaciones_geometricas(bloques)["cliente"] == "ARMACERO MATCO"


def test_geometria_cliente_no_confunde_valor_de_giro_recortado():
    bloques = [
        _bloque("EÑORIES)", 0, 20, 65),
        _bloque("ARMACERO MATCO", 180, 20),
        _bloque("IRO", 0, 42, 27),
        _bloque("FCA OTROS PDR METAL", 180, 42),
    ]

    assert _extraer_asociaciones_geometricas(bloques)["cliente"] == "ARMACERO MATCO"


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


def test_geometria_giro_no_se_apropia_del_nombre_de_fila_anterior():
    """Una fila GIRO sin valor alineado no debe reservar el nombre legítimo
    de SEÑOR(ES) situado arriba; un valor real de GIRO situado a su derecha
    sigue siendo estructural y no puede publicarse como cliente."""
    bloques = [
        _bloque("SEÑOR(ES)", 20, 20, 80),
        _bloque("COMERCIAL DEL PACIFICO SA", 150, 24, 190),
        _bloque("GIRO", 20, 45, 45),
        _bloque("VENTA AL POR MENOR", 150, 48, 150),
    ]

    assert _extraer_asociaciones_geometricas(bloques) == {
        "cliente": "COMERCIAL DEL PACIFICO SA"
    }


# --- Bloque C1: caso real guía 464170 (EBEMA SA / IVAN ROA) ---


def test_buscar_cliente_reconoce_senor_es_con_ene_real():
    """Regresión Parte B: SEÑOR(ES) con eñe real (no 'SENOR' sin tilde) debe
    resolver el cliente por el camino lineal; antes del fix, la falta de
    normalización Ñ→N en `texto_busqueda` dejaba esto en 'No encontrado'."""
    textos = [
        "GUIA DE DESPACHO N 464170 FECHA DE EMISION 04-08-2026 "
        "SEÑOR(ES) EBEMA SA RUT 83.585.400-0 GIRO VENTA AL POR MAYOR"
    ]

    datos = extraer_datos(textos)

    assert datos["cliente"] == "EBEMA SA", datos


def test_geometria_supermercado_senor_no_se_interpreta_como_etiqueta():
    """Regresión Parte C (caso real guía 464170): 'SEÑOR' dentro del nombre
    de un destino (SUPERMERCADO SEÑOR DE LOS MI) no debe confundirse con la
    etiqueta real SEÑOR(ES). Antes del fix, el matcher por subcadena
    generaba una etiqueta falsa que competía con la real y producía
    ambigüedad -> abstención, aunque el candidato correcto ya fuera el
    mejor puntuado."""
    bloques = [
        _bloque("SEÑOR(ES)", 20, 20, 80),
        _bloque(": EBEMA SA", 110, 20, 80),
        _bloque("SOLICITANTE", 400, 20, 90),
        _bloque(": SUPERMERCADO SEÑOR DE LOS MI", 500, 20, 220),
        _bloque("ORDEN DE COMPRA", 400, 60, 110),
    ]

    assert _extraer_asociaciones_geometricas(bloques)["cliente"] == "EBEMA SA"


def test_geometria_rut_cliente_generico_recupera_ebema():
    """Regresión Parte D (caso real guía 464170): el RUT del cliente se
    recupera de forma genérica (no hardcodeada) desde la zona
    SEÑOR(ES)/R.U.T., validando que sea un RUT chileno real (dígito
    verificador correcto)."""
    bloques = [
        _bloque("SEÑOR(ES)", 46, 550, 72, 15),
        _bloque(": EBEMA SA", 217, 550, 71, 15),
        _bloque("R.U.T.", 47, 568, 40, 15),
        _bloque(":83.585.400-0", 216, 568, 103, 15),
    ]

    assert _extraer_rut_cliente_geometrico(bloques) == {"valor": "83.585.400-0"}


def test_buscar_rut_chofer_tolera_dos_puntos_pegados_al_valor():
    """Corolario necesario para la validación real de la guía 464170:
    PaddleOCR real entrega 'RUT CHOFER' y ':10190440-7' como líneas
    separadas; el regex solo toleraba espacios/saltos de línea entre la
    etiqueta y el valor, no los dos puntos literales que preceden al RUT."""
    textos = ["RUT CHOFER", ":10190440-7", ": IVAN ROA"]

    datos = extraer_datos(textos)

    assert datos["RUT del chofer"] == "10190440-7", datos


def test_geometria_rut_cliente_ambiguo_se_abstiene():
    """Ante dos candidatos igualmente válidos (dos RUT chilenos reales) en
    la misma zona, la extracción de RUT cliente debe abstenerse en vez de
    adivinar."""
    bloques = [
        _bloque("SEÑOR(ES)", 46, 550, 72, 15),
        _bloque(": EBEMA SA", 217, 550, 71, 15),
        _bloque("R.U.T.", 47, 568, 40, 15),
        _bloque(":83.585.400-0", 216, 568, 103, 15),
        _bloque(":76.083.093-3", 216, 568, 103, 15),
    ]

    assert _extraer_rut_cliente_geometrico(bloques) == {}


@pytest.mark.parametrize("solapamiento", [-7, -8])
def test_rut_cliente_geometrico_acepta_solapamiento_relativo_realista(solapamiento):
    alto_senor = 24
    y_rut = 100 + alto_senor + solapamiento
    bloques = [
        _bloque("SENOR(ES)", 50, 100, 80, alto_senor),
        _bloque("R.U.T.", 51, y_rut, 45, 20),
        _bloque(":76.083.093-3", 220, y_rut + 2, 105, 18),
    ]
    assert _extraer_rut_cliente_geometrico(bloques) == {"valor": "76.083.093-3"}


def test_rut_cliente_geometrico_escala_cajas_y_solapamiento():
    bloques = [
        _bloque("SENOR(ES)", 100, 200, 160, 48),
        _bloque("R.U.T.", 102, 232, 90, 40),
        _bloque(":76.083.093-3", 440, 236, 210, 36),
    ]
    assert _extraer_rut_cliente_geometrico(bloques) == {"valor": "76.083.093-3"}


@pytest.mark.parametrize(
    "bloques",
    [
        [_bloque("SENOR(ES)", 50, 100, 80, 24), _bloque("R.U.T.", 51, 94, 45, 20), _bloque(":76.083.093-3", 220, 96, 105, 18)],
        [_bloque("SENOR(ES)", 50, 100, 80, 20), _bloque("R.U.T.", 51, 155, 45, 20), _bloque(":76.083.093-3", 220, 157, 105, 18)],
        [_bloque("SENOR(ES)", 50, 100, 80, 20), _bloque("R.U.T.", 100, 116, 45, 20), _bloque(":76.083.093-3", 220, 118, 105, 18)],
        [_bloque("SENOR(ES)", 50, 100, 80, 20), _bloque("R.U.T.", 51, 116, 45, 20), _bloque(":76.083.093-3", 220, 150, 105, 18)],
        [_bloque("SENOR(ES)", 50, 100, 80, 20), _bloque("R.U.T.", 51, 116, 45, 20), _bloque(":76.083.093-4", 220, 118, 105, 18)],
    ],
)
def test_rut_cliente_geometrico_se_abstiene_ante_geometria_o_dv_inseguro(bloques):
    assert _extraer_rut_cliente_geometrico(bloques) == {}


@pytest.mark.parametrize("solapamiento", [-3, -5])
def test_rut_cliente_geometrico_conserva_controles_historicos(solapamiento):
    bloques = [
        _bloque("SENOR(ES)", 50, 100, 80, 20),
        _bloque("R.U.T.", 51, 120 + solapamiento, 45, 18),
        _bloque(":76.083.093-3", 220, 122 + solapamiento, 105, 16),
    ]
    assert _extraer_rut_cliente_geometrico(bloques) == {"valor": "76.083.093-3"}


# --- Bloque D1: separar GIRO de obra_destino (caso real guía 464170) ---


def test_geometria_obra_destino_no_confunde_giro_con_destino_real():
    """Caso real obligatorio guía 464170: SEÑOR(ES): EBEMA SA / GIRO: VENTA
    AL POR MAYOR D... / OBRA DESTINO: SUPERMERCADO SEÑOR DE LOS MI. Antes
    del fix, el candidato real de obra_destino quedaba excluido por
    contener la palabra "SEÑOR" (misma clase de colisión que motivó C1,
    pero del lado del candidato en vez de la etiqueta), y el valor de GIRO
    -en la columna vecina, misma fila- terminaba ganando por ser el único
    candidato restante."""
    bloques = [
        _bloque("SEÑOR(ES)", 46, 550, 72, 15),
        _bloque(": EBEMA SA", 217, 550, 71, 15),
        _bloque("SOLICITANTE", 482, 554, 84, 14),
        _bloque(": SUPERMERCADO SEÑOR DE LOS MI", 623, 550, 225, 17),
        _bloque("GIRO", 46, 585, 37, 18),
        _bloque(": VENTA AL POR MAYOR D", 216, 589, 160, 13),
        _bloque("OBRA DESTINO", 482, 587, 95, 14),
        _bloque(": SUPERMERCADO SEÑOR DE LOS MI", 622, 583, 226, 17),
    ]

    resultado = _extraer_asociaciones_geometricas(bloques)

    assert resultado["obra destino"] == "SUPERMERCADO SEÑOR DE LOS MI"


def test_geometria_giro_nunca_se_devuelve_como_obra_destino():
    """GIRO es un campo distinto y nunca es elegible como obra/destino,
    aunque sea el único bloque cercano a la etiqueta OBRA DESTINO."""
    bloques = [
        _bloque("GIRO", 46, 585, 40, 18),
        _bloque(": VENTA AL POR MAYOR D", 216, 589, 165, 14),
        _bloque("OBRA DESTINO", 482, 587, 95, 15),
    ]

    assert _extraer_asociaciones_geometricas(bloques).get("obra destino") is None


def test_geometria_solo_giro_sin_obra_destino_no_inventa_nada():
    """Si el documento solo aporta GIRO, sin ninguna etiqueta de
    OBRA/DESTINO, no debe inventarse un valor de obra_destino a partir de
    GIRO ni de ningún otro campo."""
    bloques = [
        _bloque("GIRO", 46, 585, 40, 18),
        _bloque(": VENTA AL POR MAYOR D", 216, 589, 165, 14),
    ]

    assert "obra destino" not in _extraer_asociaciones_geometricas(bloques)


def test_geometria_obra_con_palabra_senor_no_crea_etiqueta_falsa_de_cliente():
    """Un nombre de obra/destino real que contiene la palabra SEÑOR
    (SUPERMERCADO SEÑOR DE LOS MI) no debe generar una etiqueta de cliente
    falsa que interfiera con la resolución correcta de cliente (fix C1,
    preservado aquí junto con la resolución de obra_destino)."""
    bloques = [
        _bloque("SEÑOR(ES)", 46, 550, 72, 15),
        _bloque(": EBEMA SA", 217, 550, 71, 15),
        _bloque("OBRA DESTINO", 482, 587, 95, 14),
        _bloque(": SUPERMERCADO SEÑOR DE LOS MI", 622, 583, 226, 17),
    ]

    resultado = _extraer_asociaciones_geometricas(bloques)

    assert resultado["cliente"] == "EBEMA SA"
    assert resultado["obra destino"] == "SUPERMERCADO SEÑOR DE LOS MI"


def test_geometria_obra_destino_ambiguo_se_abstiene():
    """Ante dos candidatos igualmente plausibles de obra_destino, la
    geometría debe abstenerse en vez de elegir por orden OCR."""
    bloques = [
        _bloque("OBRA DESTINO", 100, 50, 105, 18),
        _bloque("DESTINO NORTE", 220, 40, 110, 18),
        _bloque("DESTINO SUR", 220, 60, 100, 18),
    ]

    assert _extraer_asociaciones_geometricas(bloques).get("obra destino") is None


def test_geometria_no_regresion_cliente_chofer_rut_cliente_junto_a_obra_destino():
    """No regresión (Bloque D1): resolver obra_destino correctamente no
    altera las resoluciones de cliente/chofer/RUT cliente ya corregidas en
    C1, usando la geometría real (bounding boxes reales) de la guía 464170."""
    bloques = [
        _bloque("SEÑOR(ES)", 46, 553, 72, 17),
        _bloque(": EBEMA SA", 217, 557, 71, 11),
        _bloque("R.U.T.", 47, 570, 39, 15),
        _bloque(":83.585.400-0", 216, 573, 103, 13),
        _bloque("SOLICITANTE", 482, 554, 84, 14),
        _bloque(": SUPERMERCADO SEÑOR DE LOS MI", 623, 550, 225, 17),
        _bloque("GIRO", 46, 585, 37, 18),
        _bloque(": VENTA AL POR MAYOR D", 216, 589, 160, 13),
        _bloque("OBRA DESTINO", 482, 587, 95, 14),
        _bloque(": SUPERMERCADO SEÑOR DE LOS MI", 622, 583, 226, 17),
        _bloque("RETIRA", 549, 1101, 49, 15),
        _bloque("RUT CHOFER", 26, 1113, 87, 14),
        _bloque(":10190440-7", 173, 1114, 91, 15),
        _bloque(": IVAN ROA", 623, 1107, 74, 11),
        _bloque("PATENTE", 550, 1118, 61, 14),
    ]

    asociaciones = _extraer_asociaciones_geometricas(bloques)
    chofer = _extraer_chofer_geometrico(bloques)
    rut_cliente = _extraer_rut_cliente_geometrico(bloques)

    assert asociaciones["cliente"] == "EBEMA SA"
    assert asociaciones["obra destino"] == "SUPERMERCADO SEÑOR DE LOS MI"
    assert chofer["valor"] == "IVAN ROA"
    assert rut_cliente["valor"] == "83.585.400-0"


def test_geometria_obra_destino_identico_al_cliente_se_resuelve_de_forma_independiente():
    """Diagnóstico real 472640 (DSI UNDERGROUND CHILE SPA): investigación
    contra la imagen/OCR real confirmó que el documento imprime el MISMO
    nombre de cliente en DOS lugares físicos distintos -- junto a
    SEÑOR(ES) (la respuesta de cliente) y, por separado, junto a OBRA
    DESTINO (un cliente sin obra/proyecto propio: el destino ES el propio
    cliente) -- más un tercer bloque idéntico, más arriba en la imagen,
    que no está pegado a ninguna etiqueta (letra de cabecera/repetición
    de imprenta). Geometría real (bounding boxes reales del OCR de
    472640, sin reescalar): la coincidencia de texto entre cliente y
    obra_destino NUNCA viene de que el código copie uno al otro -- cada
    campo se resuelve por su PROPIA etiqueta y posición, ignorando el
    bloque suelto sin etiqueta. Ver también `probar_guia7` (462793,
    mismo cliente real) para el mismo patrón por la vía lineal."""
    bloques = [
        _bloque("DSI UNDERGROUND CHILE SPA", 2233, 938, 650, 62),  # suelto, sin etiqueta -- nunca debe ganar
        _bloque("SEÑOR(ES)", 120, 991, 229, 51),
        _bloque("DSI UNDERGROUND CHILE SPA", 790, 967, 615, 62),  # junto a SEÑOR(ES)
        _bloque("OBRA DESTINO", 1646, 1068, 323, 46),
        _bloque("DSI UNDERGROUND CHILE SPA", 2235, 1049, 652, 60),  # junto a OBRA DESTINO
    ]

    asociaciones = _extraer_asociaciones_geometricas(bloques)

    assert asociaciones["cliente"] == "DSI UNDERGROUND CHILE SPA"
    assert asociaciones["obra destino"] == "DSI UNDERGROUND CHILE SPA"


def test_buscar_obra_destino_lineal_no_captura_etiqueta_vecina_comuna():
    """Reproducción real guía 464264: en el orden de lectura del OCR, la
    etiqueta "COMUNA" (columna izquierda) queda intercalada entre "OBRA
    DESTINO" y "COD DESTINATARIO" (columna derecha, misma franja Y) como
    línea OCR propia -- y como el regex de `buscar_obra_destino` no puede
    cruzar líneas completas (usa `.` sin DOTALL), termina capturando esa
    etiqueta vecina en vez de valor real, que en el orden de lectura
    apareció recién DESPUÉS de "COD DESTINATARIO". Antes del fix, esto
    devolvía "COMUNA"; ahora se descarta y el valor real se recupera por
    geometría en `procesar_archivo` (ver `test_procesamiento_masivo.py`)."""
    textos = [
        "FECHA DE EMISIÓN :05-08-2026",
        "SEÑOR(ES) : SODIMAC SA",
        "ORDEN DE COMPRA :17402312 / 0030020999",
        "R.U.T. 96.792.430-K",
        "SOLICITANTE : SODIMAC SA CORONEL",
        "GIRO : VTA AL X MENOR MAT C",
        "OBRA DESTINO",
        "COMUNA",
        "COD DESTINATARIO",
        ": SODIMAC SA CORONEL",
        "DIRECCION : AV PDTE EDUARDO FREI 3092",
        "HORA ENTRADA 09:32:00",
        "CIUDAD : RENCA",
    ]

    datos = extraer_datos(textos)

    assert datos["obra destino"] != "COMUNA", datos
    # `buscar_obra_destino` se abstiene (no captura la etiqueta vecina); el
    # valor real sólo llega por geometría, que `extraer_datos` (fase
    # puramente lineal, sin bounding boxes) no ejecuta -- por eso aquí el
    # resultado esperado es la abstención, no el valor real.
    assert datos["obra destino"] == "No encontrado", datos


@pytest.mark.parametrize(
    "etiqueta_vecina",
    ["COMUNA", "CIUDAD", "DIRECCION", "GIRO", "TOTAL", "RUT"],
)
def test_buscar_obra_destino_lineal_descarta_cualquier_etiqueta_estructural_conocida(etiqueta_vecina):
    """Generalización: cualquier etiqueta de la lista canónica ya usada por
    la asociación geométrica (`_EXCLUSIONES_CANDIDATO_NOMINAL_GEOMETRICO`)
    debe descartarse igual si queda intercalada sola entre "OBRA DESTINO" y
    "COD DESTINATARIO" -- no es un caso especial de "COMUNA"."""
    textos = [
        "OBRA DESTINO",
        etiqueta_vecina,
        "COD DESTINATARIO",
        ": CONSTRUCTORA REAL SPA",
    ]

    datos = extraer_datos(textos)

    assert datos["obra destino"] != etiqueta_vecina, datos


def test_buscar_obra_destino_lineal_sigue_capturando_valor_real_sin_etiqueta_intercalada():
    """No regresión: cuando el valor real está directamente entre "OBRA
    DESTINO" y "COD DESTINATARIO" (sin ninguna etiqueta intercalada), sigue
    capturándose normalmente -- el fix no afecta el camino que ya
    funcionaba (mismo patrón que `probar_guia1`/`probar_guia2`)."""
    textos = [
        "TELEFONO OBRA DESTINO EMPRESA CONST SIGRO COD DESTINATARIO 0002012245",
    ]

    datos = extraer_datos(textos)

    assert datos["obra destino"] == "EMPRESA CONST SIGRO", datos


def test_buscar_obra_destino_lineal_no_descarta_valor_real_que_contiene_palabra_de_la_lista():
    """Negativo: un valor real y legítimo de obra_destino que sólo
    CONTIENE una de las palabras de la lista canónica (no que ES esa
    palabra exacta) no debe descartarse -- la comparación es de igualdad
    exacta tras normalizar, nunca de subcadena, para no perder nombres
    reales de obra/destino (p. ej. "TOTAL" dentro de un nombre comercial)."""
    textos = [
        "OBRA DESTINO CONSTRUCTORA TOTAL SPA COD DESTINATARIO 0002000001",
    ]

    datos = extraer_datos(textos)

    assert datos["obra destino"] == "CONSTRUCTORA TOTAL SPA", datos


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


def test_fecha_geometrica_candidato_a_la_derecha_de_la_etiqueta():
    bloques = [
        _bloque("FECHA DE EMISION", 20, 20, 150),
        _bloque("23-06-2025", 190, 20, 90),
    ]

    resultado = _extraer_fecha_geometrico(bloques)

    assert resultado["valor"] == "23-06-2025"
    assert resultado["caja"] == (190.0, 20.0, 280.0, 38.0)


def test_fecha_geometrica_candidato_debajo_de_la_etiqueta():
    bloques = [
        _bloque("FECHA DE EMISION", 20, 20, 150),
        _bloque("23-06-2025", 25, 55, 90),
    ]

    assert _extraer_fecha_geometrico(bloques)["valor"] == "23-06-2025"


def test_fecha_geometrica_etiqueta_ausente_se_abstiene():
    assert _extraer_fecha_geometrico([_bloque("23-06-2025", 190, 20, 90)]) == {}


def test_fecha_geometrica_sin_candidato_se_abstiene():
    assert _extraer_fecha_geometrico([_bloque("FECHA DE EMISION", 20, 20, 150)]) == {}


def test_fecha_geometrica_se_abstiene_ante_dos_candidatos_equivalentes():
    bloques = [
        _bloque("FECHA DE EMISION", 20, 50, 150),
        _bloque("23-06-2025", 190, 40, 90),
        _bloque("24-06-2025", 190, 60, 90),
    ]

    assert _extraer_fecha_geometrico(bloques) == {}


def test_fecha_geometrica_prioriza_emision_sobre_salida_cercana():
    bloques = [
        _bloque("FECHA SALIDA", 20, 20, 120),
        _bloque("FECHA DE EMISION", 20, 60, 150),
        _bloque("23-06-2025", 190, 60, 90),
    ]

    resultado = _extraer_fecha_geometrico(bloques)

    assert resultado["valor"] == "23-06-2025"


def test_fecha_geometrica_no_toma_candidato_mas_cercano_a_salida_que_a_emision():
    bloques = [
        _bloque("FECHA DE EMISION", 20, 20, 150),
        _bloque("FECHA SALIDA", 20, 60, 120),
        _bloque("25-06-2025", 190, 60, 90),
    ]

    assert _extraer_fecha_geometrico(bloques) == {}


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


def _chofer(*candidatos):
    return _extraer_chofer_geometrico(
        [_bloque("RETIRA", 20, 20, 60), _bloque("PATENTE", 20, 50, 70), *candidatos]
    )


def test_chofer_a_la_derecha_de_retira():
    assert _chofer(_bloque("MARIO SOTO", 120, 20))["valor"] == "MARIO SOTO"


def test_chofer_debajo_de_retira():
    assert _chofer(_bloque("ELENA ROJAS", 25, 42))["valor"] == "ELENA ROJAS"


def test_chofer_compone_nombre_dividido_y_apellido_compuesto():
    bloques = [
        _bloque("RETIRA", 20, 20, 60), _bloque("PATENTE", 20, 50, 70),
        _bloque("ANA", 120, 20, 35), _bloque("MARIA", 160, 20, 45),
        _bloque("DEL RIO", 210, 20, 65),
    ]

    assert _extraer_chofer_geometrico(bloques)["valor"] == "ANA MARIA DEL RIO"


def test_chofer_independiente_del_orden_ocr():
    bloques = [_bloque("RETIRA", 20, 20, 60), _bloque("PATENTE", 20, 50, 70), _bloque("LUIS PEREZ", 120, 20)]

    assert _extraer_chofer_geometrico(bloques) == _extraer_chofer_geometrico(list(reversed(bloques)))


@pytest.mark.parametrize(
    "texto",
    ["TOTAL EXENTO", "NETO IVA TOTAL", "PATENTE CARRO", "RUT 12345678", "FECHA 21-07-2026", "DIRECCION AVENIDA CENTRAL", "AB1234"],
)
def test_chofer_excluye_finanzas_etiquetas_rut_fecha_direccion_y_patente(texto):
    assert _chofer(_bloque(texto, 120, 20)) == {}


def test_chofer_rechaza_numero_interno():
    assert _chofer(_bloque("MARI0 SOTO", 120, 20)) == {}


@pytest.mark.parametrize("nombre", ["ANA PEREZ-GOMEZ", "LUIS O'NEILL"])
def test_chofer_admite_guion_y_apostrofe_entre_letras(nombre):
    assert _chofer(_bloque(nombre, 120, 20))["valor"] == nombre


def test_chofer_se_abstiene_ante_dos_candidatos_equivalentes():
    bloques = [
        _bloque("RETIRA", 20, 50, 60), _bloque("PATENTE", 20, 80, 70),
        _bloque("MARIO NORTE", 120, 40, 100), _bloque("MARIO SUR", 120, 60, 100),
    ]

    assert _extraer_chofer_geometrico(bloques) == {}


def test_chofer_etiqueta_sin_candidato_y_cajas_invalidas():
    malo = BloqueOCR("NOMBRE APELLIDO", ((1, 1),), 0.5)
    assert _extraer_chofer_geometrico([_bloque("RETIRA", 20, 20), malo]) == {}


def test_chofer_resultado_determinista():
    bloques = [_bloque("RETIRA", 20, 20, 60), _bloque("PATENTE", 20, 50, 70), _bloque("PEDRO LUNA", 120, 20)]

    assert [_extraer_chofer_geometrico(bloques) for _ in range(5)] == [{"valor": "PEDRO LUNA"}] * 5


def test_chofer_no_recibe_nombre_de_archivo():
    assert _extraer_chofer_geometrico([]) == {}


@pytest.mark.parametrize(
    ("valor", "contaminado"),
    [
        ("TOTAL EXENTO JUAN PEREZ", True),
        ("NETO JUAN PEREZ", True),
        ("JUAN PEREZ PATENTE", True),
        ("JUAN PEREZ", False),
        ("TOTALINO PEREZ", False),
    ],
)
def test_chofer_contaminacion_lineal_usa_palabras_completas(valor, contaminado):
    assert _chofer_lineal_contaminado(valor) is contaminado


def test_chofer_no_excluye_apellido_que_contiene_parcialmente_iva():
    assert _chofer(_bloque("PEDRO OLIVARES", 120, 20))["valor"] == "PEDRO OLIVARES"


def test_chofer_compone_cuatro_bloques_nominales():
    bloques = [
        _bloque("RETIRA", 20, 20, 60), _bloque("PATENTE", 20, 55, 70),
        _bloque("JUAN", 110, 20, 38), _bloque("CARLOS", 154, 21, 48),
        _bloque("DE", 208, 20, 22), _bloque("LA", 236, 21, 22),
    ]

    assert _extraer_chofer_geometrico(bloques)["valor"] == "JUAN CARLOS DE LA"


def test_chofer_no_une_bloques_atravesando_patente():
    bloques = [
        _bloque("RETIRA", 20, 20, 60), _bloque("RUT CHOFER", 20, 55, 90),
        _bloque("JUAN", 110, 20, 38), _bloque("PATENTE", 152, 20, 70),
        _bloque("PEREZ", 226, 20, 45),
    ]

    assert _extraer_chofer_geometrico(bloques) == {}


def test_chofer_no_cuenta_bloque_duplicado_como_nombre_compuesto():
    nombre = _bloque("MARIO", 120, 20, 50)

    assert _chofer(nombre, nombre) == {}


def test_chofer_orden_mezclado_repetido_es_determinista():
    import random

    bloques = [_bloque("RETIRA", 20, 20, 60), _bloque("PATENTE", 20, 55, 70), _bloque("ANA MARIA", 120, 20)]
    resultados = []
    for semilla in range(5):
        mezcla = list(bloques)
        random.Random(semilla).shuffle(mezcla)
        resultados.append(_extraer_chofer_geometrico(mezcla))

    assert resultados == [{"valor": "ANA MARIA"}] * 5


@pytest.mark.parametrize("confianza", ["alta", float("nan"), float("inf")])
def test_chofer_confianza_invalida_no_decide(confianza):
    bloque = BloqueOCR("ANA MARIA", ((120, 20), (200, 20), (200, 38), (120, 38)), confianza)

    assert _chofer(bloque)["valor"] == "ANA MARIA"


def test_chofer_caja_con_puntos_invertidos_se_normaliza():
    bloque = BloqueOCR("ANA MARIA", ((200, 38), (120, 38), (120, 20), (200, 20)), 0.8)

    assert _chofer(bloque)["valor"] == "ANA MARIA"


def test_chofer_candidato_junto_a_cliente_no_desplaza_zona_retira():
    bloques = [
        _bloque("RETIRA", 20, 20, 60), _bloque("PATENTE", 20, 55, 70),
        _bloque("MARIO SOTO", 130, 20, 90),
        _bloque("CLIENTE", 300, 20, 70), _bloque("EMPRESA NORTE", 378, 20, 110),
    ]

    assert _extraer_chofer_geometrico(bloques)["valor"] == "MARIO SOTO"


# --- P1: patentes tolerantes al orden de bloques que produce PaddleOCR ---


def test_patentes_secuencia_real_paddle_valor_y_carro_en_un_solo_bloque():
    bloques = [
        _bloque("RETIRA", 20, 20, 60),
        _bloque("PATENTE", 20, 50, 70),
        _bloque(":SD6486 CARRO:JF4288", 20, 80, 220),
        _bloque("FECHA LLEGADA", 20, 110, 120),
    ]

    assert _extraer_patentes_geometrico(bloques) == {"tracto": "SD6486", "carro": "JF4288"}


def test_patentes_etiquetas_y_valores_separados_por_bloques():
    bloques = [
        _bloque("RETIRA", 20, 20, 60),
        _bloque("PATENTE", 20, 50, 70),
        _bloque("SD6486", 120, 50, 70),
        _bloque("CARRO", 20, 80, 60),
        _bloque("JF4288", 120, 80, 70),
        _bloque("FECHA LLEGADA", 20, 110, 120),
    ]

    assert _extraer_patentes_geometrico(bloques) == {"tracto": "SD6486", "carro": "JF4288"}


def test_patentes_dos_columnas_no_asigna_al_carro_el_valor_izquierdo_del_tracto():
    """Caso real 464522: el valor de PATENTE está entre ambas etiquetas."""
    bloques = [
        _bloque("RETIRA", 545, 999, 50),
        _bloque("PATENTE", 545, 1013, 64),
        _bloque("AL1e79", 633, 1015, 50),
        _bloque("CARRO", 697, 1013, 42),
        _bloque("JR2501", 743, 1013, 50),
        _bloque("FECHA LLEGADA", 545, 1043, 100),
    ]

    assert _extraer_patentes_geometrico(bloques) == {"tracto": "AL1E79", "carro": "JR2501"}


def test_patentes_candidato_fuera_de_zona_retira_llegada_se_rechaza():
    bloques = [
        _bloque("RETIRA", 20, 20, 60),
        _bloque("PATENTE", 20, 50, 70),
        _bloque("FECHA LLEGADA", 20, 80, 120),
        _bloque("ZZ9999", 20, 400, 70),  # muy por debajo de la zona RETIRA-LLEGADA
    ]

    assert _extraer_patentes_geometrico(bloques) == {}


def test_patentes_candidato_lejano_ya_no_bloquea_al_mas_cercano():
    """Bloque PATENTES P4 -- reescribe la expectativa anterior. El
    algoritmo previo concatenaba toda la zona RETIRA-FECHA LLEGADA en un
    solo texto y trataba CUALQUIER segundo token de 6 caracteres como
    ambigüedad, sin importar su distancia real a la etiqueta -- por eso
    esta prueba antes esperaba abstención. El algoritmo geométrico actual
    asocia cada etiqueta a su candidato más cercano: AB1234 está pegado a
    PATENTE, CD5678 está mucho más lejos en el mismo renglón -- ya no hay
    ambigüedad real, y CD5678 lejano no debe bloquear el hallazgo (ver
    `test_patentes_dos_etiquetas_con_valores_igual_de_cercanos_se_abstiene`
    en tests/test_patentes_p4.py para el caso de ambigüedad genuina)."""
    bloques = [
        _bloque("RETIRA", 20, 20, 60),
        _bloque("PATENTE", 20, 50, 70),
        _bloque("AB1234", 120, 50, 70),
        _bloque("CD5678", 220, 50, 70),
        _bloque("FECHA LLEGADA", 20, 80, 120),
    ]

    assert _extraer_patentes_geometrico(bloques) == {"tracto": "AB1234"}


def test_patentes_solo_tracto_disponible():
    bloques = [
        _bloque("RETIRA", 20, 20, 60),
        _bloque("PATENTE", 20, 50, 70),
        _bloque("AB1234", 120, 50, 70),
        _bloque("FECHA LLEGADA", 20, 80, 120),
    ]

    assert _extraer_patentes_geometrico(bloques) == {"tracto": "AB1234"}


def test_patentes_solo_carro_disponible():
    bloques = [
        _bloque("RETIRA", 20, 20, 60),
        _bloque("PATENTE", 20, 50, 70),
        _bloque("CARRO:JF4288", 120, 50, 110),
        _bloque("FECHA LLEGADA", 20, 80, 120),
    ]

    assert _extraer_patentes_geometrico(bloques) == {"carro": "JF4288"}


def test_patentes_sin_ancla_retira_se_abstiene():
    bloques = [_bloque("PATENTE", 20, 50, 70), _bloque("AB1234", 120, 50, 70)]

    assert _extraer_patentes_geometrico(bloques) == {}


def test_patentes_no_afecta_extraccion_de_chofer():
    bloques = [
        _bloque("RETIRA", 20, 20, 60),
        _bloque("MARIO SOTO", 120, 20, 90),
        _bloque("PATENTE", 20, 50, 70),
        _bloque("SD6486", 120, 50, 70),
        _bloque("CARRO", 20, 80, 60),
        _bloque("JF4288", 120, 80, 70),
        _bloque("FECHA LLEGADA", 20, 110, 120),
    ]

    assert _extraer_chofer_geometrico(bloques)["valor"] == "MARIO SOTO"
    assert _extraer_patentes_geometrico(bloques) == {"tracto": "SD6486", "carro": "JF4288"}


def test_guia5_formato_historico_easyocr_continuo_sigue_funcionando():
    """Regresión: la fase textual (`buscar_chofer_y_patentes`) no se tocó en
    P1; la guía real con RODRIGO NAHUELÑIR / SB6486 / JF4288 sigue
    resolviéndose por el camino lineal cuando el OCR entrega la frase
    contigua "RETIRA PATENTE FECHA LLEGADA" (formato histórico EasyOCR)."""
    probar_guia5()


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
    # Bloque O1: corregido de "12.242,000" (Peso Bruto) a "3.282,00"
    # (PESO KG, el peso operacional real -- ver semántica de PESO).
    assert datos["peso"] == "3.282,00", datos



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
