import sys
import types
import unittest

# Proveer un stub mínimo para easyocr para poder importar atlas.py en el entorno de prueba.
easyocr_stub = types.ModuleType("easyocr")


class Reader:
    def __init__(self, *args, **kwargs):
        pass

    def readtext(self, *args, **kwargs):
        return []


easyocr_stub.Reader = Reader
sys.modules.setdefault("easyocr", easyocr_stub)

from atlas import extraer_datos


class ExtraerDatosTests(unittest.TestCase):
    def test_rut_cliente_con_espacios_raros(self):
        textos = [
            "SEÑOR(ES) AMERICAN SCREW CHILE SPA RUT 91.410 .000 GIRO FABRICACION DE CABL DIRECCION CAMINO MELIPILLA 10800 COMUNA MIPU CIUDAD SANTIAGO"
        ]

        datos = extraer_datos(textos)

        self.assertEqual(datos["cliente"], "AMERICAN SCREW CHILE SPA")
        self.assertEqual(datos["RUT del cliente"], "91.410.000")

    def test_formato_primera_guia(self):
        textos = [
            "RUT. 92.176.000-0 GUIA DE DESPACHO ELECTRÓNICA N° 462429",
            "SOLICITANTE EMPRESA CONST SIGRO SA TELEFONO OBRA DESTINO EMPRESA CONST SIGRO COD DESTINATARIO 0002012245 HORA ENTRADA 13,11:00 HORA SALIDA 13:55;54 Nro. TRANSPORTE 0000346311 Código cliente 0001003518 FECHA DE EMISIÓN 02-07-2026 SEÑOR(ES) PRODALAK Rut. 93.772 000 GIRO",
            "VALOR TOTAL 10.425.558 ENTREGA 03.07 PEDIDO 28 TORRE PESO KG 12.441 DESPACHAR A AVDA IRARRAZAVAL 5497 SANTIAGO ÑUÑOA RUT ChoFER 18611137-0 FECHA SALIDA 02-07-2026 RETIRA PATENTE FECHA LLEGADA LEANDRO TOLEDO BKYX63",
        ]

        datos = extraer_datos(textos)

        self.assertEqual(datos["obra destino"], "EMPRESA CONST SIGRO")
        self.assertEqual(datos["RUT del cliente"], "93.772.000")
        self.assertEqual(datos["chofer"], "LEANDRO TOLEDO")
        self.assertEqual(datos["RUT del chofer"], "18611137-0")
        self.assertEqual(datos["patente del tracto"], "BKYX63")
        self.assertEqual(datos["hora de entrada"], "11:00")
        self.assertEqual(datos["hora de salida"], "13:55")
        self.assertEqual(datos["peso"], "12.441")

    def test_formato_segunda_guia(self):
        textos = [
            "RUT. 92.176.000-0 GUIA DE DESPACHO ELECTRÓNICA N° 462474",
            "Código Cliente 0001000197 FECHA DE EMISIÓN 03-07-2026 SEÑOR(ES) AMERICAN SCREW CHILE SPA RUT 91.410.000 GIRO FABRICACION DE CABL DIRECCION CAMINO MELIPILLA 10800 COMUNA MIPU CIUDAD SANTIAGO",
            "Numero SAP",
            "0080537846",
            "ORDEN DE COMPRA SOLICITANTE TELEFONO OBRA DESTINO COD DESTINATARIO HORA ENTRADA HORA SALIDA Nro. TRANSPORTE",
            "1600052285 0030020250 AMERICAN SCREW CHILE SPA",
            "AMERICAN SCREW CHILE SPA 0001000197 06:59 00 09:30 : 10 0000346352",
            "...",
            "VALOR TOTAL 26.000.702 03/07 HASTA LAS 15 JENNY 956058217 PESO KG- 27.398 00 DESPACHAR A CAMINO A MELIPILLA 10800 MAIPU RUT ChoFER 14293816-2 FECHA SALIDA 03 07-2026",
            "RETIRA PATENTE FECHA LLEGADA",
            "LUIS VARAS DD2494 CARRO : JB8529",
        ]

        datos = extraer_datos(textos)

        self.assertEqual(datos["obra destino"], "AMERICAN SCREW CHILE SPA")
        self.assertEqual(datos["RUT del cliente"], "91.410.000")
        self.assertEqual(datos["chofer"], "LUIS VARAS")
        self.assertEqual(datos["patente del tracto"], "DD2494")
        self.assertEqual(datos["patente del carro"], "JB8529")
        self.assertEqual(datos["hora de entrada"], "06:59")
        self.assertEqual(datos["hora de salida"], "09:30")
        self.assertEqual(datos["peso"], "27.398")
        self.assertEqual(datos["número de transporte"], "0000346352")


if __name__ == "__main__":
    unittest.main()
