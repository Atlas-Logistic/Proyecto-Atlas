import csv
import sys
import types


# Proveer un stub mínimo para importar atlas sin depender de EasyOCR.
easyocr_stub = types.ModuleType("easyocr")


class Reader:
    def __init__(self, *args, **kwargs):
        pass

    def readtext(self, *args, **kwargs):
        return []


easyocr_stub.Reader = Reader
sys.modules.setdefault("easyocr", easyocr_stub)

from atlas import guardar_ficha_viaje, guardar_viaje_csv


DATOS_VIAJE = {
    "número de guía": "462429",
    "número de transporte": "0000346311",
    "cliente": "CONSTRUCTORA EJEMPLO SPA",
    "RUT del cliente": "76.123.456-7",
    "obra destino": "EDIFICIO ATLAS",
    "chofer": "JUAN PÉREZ",
    "RUT del chofer": "18.611.137-0",
    "patente del tracto": "BKYX63",
    "patente del carro": "JB8529",
    "hora de entrada": "11:00",
    "hora de salida": "13:55",
    "peso": "12.441",
}


def test_guardar_ficha_viaje_crea_ficha_con_datos(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    ruta_ficha = guardar_ficha_viaje(DATOS_VIAJE)

    ruta_esperada = tmp_path / "output" / "fichas" / "guia_462429.txt"
    assert ruta_ficha.resolve() == ruta_esperada
    assert ruta_esperada.is_file()

    contenido = ruta_esperada.read_text(encoding="utf-8")
    lineas_esperadas = [
        "NRO GUIA: 462429",
        "NRO TRANSPORTE: 0000346311",
        "CLIENTE: CONSTRUCTORA EJEMPLO SPA",
        "RUT CLIENTE: 76.123.456-7",
        "OBRA DESTINO: EDIFICIO ATLAS",
        "CHOFER: JUAN PÉREZ",
        "RUT CHOFER: 18.611.137-0",
        "PATENTE TRACTO: BKYX63",
        "PATENTE CARRO: JB8529",
        "HORA ENTRADA: 11:00",
        "HORA SALIDA: 13:55",
        "PESO: 12.441",
    ]
    for linea in lineas_esperadas:
        assert linea in contenido


def test_guardar_viaje_csv_usa_punto_y_coma_y_evitar_duplicados(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    guardar_viaje_csv(DATOS_VIAJE)
    ruta_csv = guardar_viaje_csv(DATOS_VIAJE)

    ruta_esperada = tmp_path / "output" / "viajes.csv"
    assert ruta_csv.resolve() == ruta_esperada
    assert ruta_esperada.is_file()

    contenido = ruta_esperada.read_text(encoding="utf-8-sig")
    lineas = contenido.splitlines()
    assert len(lineas) == 2
    assert lineas[0].count(";") == 11
    assert lineas[1].count(";") == 11

    columnas_esperadas = [
        "numero_guia",
        "numero_transporte",
        "cliente",
        "rut_cliente",
        "obra_destino",
        "chofer",
        "rut_chofer",
        "patente_tracto",
        "patente_carro",
        "hora_entrada",
        "hora_salida",
        "peso",
    ]
    fila_esperada = {
        "numero_guia": "462429",
        "numero_transporte": "0000346311",
        "cliente": "CONSTRUCTORA EJEMPLO SPA",
        "rut_cliente": "76.123.456-7",
        "obra_destino": "EDIFICIO ATLAS",
        "chofer": "JUAN PÉREZ",
        "rut_chofer": "18.611.137-0",
        "patente_tracto": "BKYX63",
        "patente_carro": "JB8529",
        "hora_entrada": "11:00",
        "hora_salida": "13:55",
        "peso": "12.441",
    }

    with ruta_esperada.open("r", newline="", encoding="utf-8-sig") as archivo:
        lector = csv.DictReader(archivo, delimiter=";")
        filas = list(lector)

    assert lector.fieldnames == columnas_esperadas
    assert filas == [fila_esperada]
