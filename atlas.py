"""Proyecto Atlas: lectura de texto desde imágenes con EasyOCR."""

import re
from pathlib import Path
from typing import Dict, List, Optional

from atlas_core.extractor import extraer_datos
from atlas_core.ocr import leer_texto_imagen
from atlas_core.storage import guardar_ficha_viaje, guardar_viaje_csv


def solicitar_ruta_imagen() -> Optional[Path]:
    """Solicita la ruta de la imagen al usuario desde la terminal."""
    ruta_ingresada = input("Ingresa la ruta completa de la imagen: ").strip()
    ruta_ingresada = re.sub(r"^\s*&\s*['\"]?(.*?)['\"]?$", r"\1", ruta_ingresada)
    ruta_ingresada = ruta_ingresada.strip('"').strip("'")

    if not ruta_ingresada:
        print("No se ingresó ninguna ruta.")
        return None

    ruta = Path(ruta_ingresada).expanduser()
    if not ruta.exists():
        origen_proyecto = Path(__file__).resolve().parent
        ruta_relativa = origen_proyecto / ruta_ingresada
        if ruta_relativa.exists():
            ruta = ruta_relativa
        else:
            ruta_absoluta = (Path.cwd() / ruta_ingresada).resolve()
            if ruta_absoluta.exists():
                ruta = ruta_absoluta

    if not ruta.exists():
        print("La ruta ingresada no existe.")
        return None

    if not ruta.is_file():
        print("La ruta ingresada no corresponde a un archivo.")
        return None

    return ruta


def _limpiar_valor(valor: str) -> str:
    """Limpia espacios y puntuación innecesaria de un valor extraído."""
    return re.sub(r"\s+", " ", valor).strip(" :;.-")



def mostrar_texto(textos: List[str]) -> None:
    """Muestra en pantalla el texto detectado."""
    if not textos:
        print("No se detectó texto en la imagen.")
        return

    print("\nTexto detectado:\n")
    for texto in textos:
        print(texto)


def mostrar_datos_extraidos(datos: Dict[str, str]) -> None:
    """Muestra los datos estructurados extraídos de la guía."""
    print("\nDatos extraídos:\n")
    for campo, valor in datos.items():
        print(f"{campo}: {valor}")




def procesar_imagen(ruta_imagen):
    print(f"\nProcesando imagen: {ruta_imagen}")

    textos = leer_texto_imagen(ruta_imagen)
    mostrar_texto(textos)

    datos = extraer_datos(textos)
    mostrar_datos_extraidos(datos)

    ruta_ficha = guardar_ficha_viaje(datos)
    print(f"\nFicha de viaje guardada en: {ruta_ficha}")

    ruta_csv = guardar_viaje_csv(datos)
    print(f"Viaje agregado al CSV en: {ruta_csv}")

    return datos


def procesar_carpeta(ruta_carpeta):
    extensiones_validas = {".jpg", ".jpeg", ".png", ".webp"}

    imagenes = sorted(
        archivo
        for archivo in ruta_carpeta.iterdir()
        if archivo.is_file() and archivo.suffix.lower() in extensiones_validas
    )

    if not imagenes:
        print("No se encontraron imágenes en la carpeta.")
        return

    print(f"Se encontraron {len(imagenes)} imágenes para procesar.")

    for indice, imagen in enumerate(imagenes, start=1):
        print("\n" + "=" * 60)
        print(f"Procesando {indice} de {len(imagenes)}: {imagen.name}")
        print("=" * 60)

        try:
            procesar_imagen(imagen)
        except Exception as error:
            print(f"Error procesando {imagen.name}: {error}")

    print("\nProceso de carpeta terminado.")


def main() -> None:
    """Función principal del programa."""
    print("Proyecto Atlas")
    print("")
    print("Elige una opción:")
    print("1 - Procesar una sola guía")
    print("2 - Procesar todas las guías de una carpeta")
    print("")

    opcion = input("Opción: ").strip()

    if opcion == "2":
        ruta_ingresada = input("Ingresa la ruta de la carpeta: ").strip().strip("'").strip('"')

        if not ruta_ingresada:
            print("No se ingresó ninguna ruta.")
            return

        ruta_carpeta = Path(ruta_ingresada).expanduser()

        if not ruta_carpeta.exists():
            origen_proyecto = Path(__file__).resolve().parent
            ruta_carpeta = origen_proyecto / ruta_ingresada

        if not ruta_carpeta.exists():
            print("La carpeta ingresada no existe.")
            return

        if not ruta_carpeta.is_dir():
            print("La ruta ingresada no corresponde a una carpeta.")
            return

        procesar_carpeta(ruta_carpeta)
        return

    ruta_imagen = solicitar_ruta_imagen()
    if ruta_imagen is None:
        return

    procesar_imagen(ruta_imagen)

if __name__ == "__main__":
    main()
