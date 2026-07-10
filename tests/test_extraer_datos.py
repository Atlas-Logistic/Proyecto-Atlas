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


def main():
    probar_guia1()
    probar_guia2()
    probar_guia3()
    print("Todas las pruebas de extracción pasaron correctamente.")


if __name__ == "__main__":
    main()
