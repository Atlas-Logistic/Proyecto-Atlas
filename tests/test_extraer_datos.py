import sys
import types
from pathlib import Path

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


def main():
    probar_guia1()
    probar_guia2()
    print("Todas las pruebas de extracción pasaron correctamente.")


if __name__ == "__main__":
    main()
