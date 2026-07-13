"""Guardado de fichas de viaje y registros CSV."""

import csv
from pathlib import Path


def guardar_ficha_viaje(datos):
    carpeta = Path("output") / "fichas"
    carpeta.mkdir(parents=True, exist_ok=True)

    numero_guia = datos.get("número de guía", "sin_numero")
    if not numero_guia or numero_guia == "No encontrado":
        numero_guia = "sin_numero"

    ruta_ficha = carpeta / f"guia_{numero_guia}.txt"

    lineas = [
        "FICHA DE VIAJE",
        "",
        f"NRO GUIA: {datos.get('número de guía', 'No encontrado')}",
        f"NRO TRANSPORTE: {datos.get('número de transporte', 'No encontrado')}",
        f"CLIENTE: {datos.get('cliente', 'No encontrado')}",
        f"RUT CLIENTE: {datos.get('RUT del cliente', 'No encontrado')}",
        f"OBRA DESTINO: {datos.get('obra destino', 'No encontrado')}",
        f"CHOFER: {datos.get('chofer', 'No encontrado')}",
        f"RUT CHOFER: {datos.get('RUT del chofer', 'No encontrado')}",
        f"PATENTE TRACTO: {datos.get('patente del tracto', 'No encontrado')}",
        f"PATENTE CARRO: {datos.get('patente del carro', 'No encontrado')}",
        f"HORA ENTRADA: {datos.get('hora de entrada', 'No encontrado')}",
        f"HORA SALIDA: {datos.get('hora de salida', 'No encontrado')}",
        f"PESO: {datos.get('peso', 'No encontrado')}",
    ]

    ruta_ficha.write_text("\n".join(lineas), encoding="utf-8")

    return ruta_ficha



def guardar_viaje_csv(datos):
    carpeta = Path("output")
    carpeta.mkdir(parents=True, exist_ok=True)

    ruta_csv = carpeta / "viajes.csv"

    columnas = [
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

    fila = {
        "numero_guia": datos.get("número de guía", "No encontrado"),
        "numero_transporte": datos.get("número de transporte", "No encontrado"),
        "cliente": datos.get("cliente", "No encontrado"),
        "rut_cliente": datos.get("RUT del cliente", "No encontrado"),
        "obra_destino": datos.get("obra destino", "No encontrado"),
        "chofer": datos.get("chofer", "No encontrado"),
        "rut_chofer": datos.get("RUT del chofer", "No encontrado"),
        "patente_tracto": datos.get("patente del tracto", "No encontrado"),
        "patente_carro": datos.get("patente del carro", "No encontrado"),
        "hora_entrada": datos.get("hora de entrada", "No encontrado"),
        "hora_salida": datos.get("hora de salida", "No encontrado"),
        "peso": datos.get("peso", "No encontrado"),
    }

    numero_guia = fila["numero_guia"]

    if ruta_csv.exists():
        with ruta_csv.open("r", newline="", encoding="utf-8-sig") as archivo:
            lector = csv.DictReader(archivo, delimiter=";")
            for fila_existente in lector:
                if fila_existente.get("numero_guia") == numero_guia:
                    print(f"Guía {numero_guia} ya existe en el CSV. No se agregó duplicado.")
                    return ruta_csv

    archivo_existe = ruta_csv.exists()

    with ruta_csv.open("a", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas, delimiter=";")

        if not archivo_existe:
            escritor.writeheader()

        escritor.writerow(fila)

    return ruta_csv


