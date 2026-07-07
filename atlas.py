"""Proyecto Atlas: lectura de texto desde imágenes con EasyOCR."""

import re
from pathlib import Path
from typing import Dict, List, Optional

try:
    import easyocr
except ImportError as exc:  # pragma: no cover - depende del entorno
    raise SystemExit(
        "EasyOCR no está instalado. Ejecute: pip install -r requirements.txt"
    ) from exc


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


def leer_texto_imagen(ruta_imagen: Path) -> List[str]:
    """Lee el texto contenido en una imagen usando EasyOCR."""
    # Se crea el lector de OCR con soporte para español e inglés.
    lector = easyocr.Reader(["es", "en"], gpu=False)

    # Se extrae el texto de la imagen y se filtran los resultados vacíos.
    resultados = lector.readtext(str(ruta_imagen), detail=0, paragraph=True)
    return [texto for texto in resultados if texto.strip()]


def _limpiar_valor(valor: str) -> str:
    """Limpia espacios y puntuación innecesaria de un valor extraído."""
    return re.sub(r"\s+", " ", valor).strip(" :;.-")


def extraer_datos(textos: List[str]) -> Dict[str, str]:
    """Intenta extraer campos relevantes a partir del texto detectado por OCR."""
    texto_completo = "\n".join(textos)
    texto_mayus = texto_completo.upper()
    lineas = [linea.strip() for linea in texto_mayus.splitlines() if linea.strip()]

    datos = {
        "número de guía": "No encontrado",
        "número de transporte": "No encontrado",
        "cliente": "No encontrado",
        "obra destino": "No encontrado",
        "RUT del cliente": "No encontrado",
        "chofer": "No encontrado",
        "RUT del chofer": "No encontrado",
        "patente del tracto": "No encontrado",
        "patente del carro": "No encontrado",
        "hora de entrada": "No encontrado",
        "hora de salida": "No encontrado",
        "peso": "No encontrado",
    }

    def limpiar_valor(valor: str) -> str:
        return re.sub(r"\s+", " ", valor).strip(" :;.-")

    def buscar_patrones(patrones: List[re.Pattern], texto: str = texto_mayus) -> Optional[str]:
        for patron in patrones:
            coincidencia = patron.search(texto)
            if coincidencia and coincidencia.group(1):
                return limpiar_valor(coincidencia.group(1))
        return None

    def buscar_rut(texto: str, limite: Optional[int] = None) -> Optional[str]:
        if limite is not None:
            texto = texto[:limite]

        texto = texto.strip()
        if not texto:
            return None

        coincidencia = re.search(r"RUT\.?\s*([0-9][0-9.\s-]{2,20})", texto, re.I)
        if not coincidencia:
            coincidencia = re.match(r"^\s*([0-9][0-9.\s-]{2,20})", texto)
        if not coincidencia:
            return None

        valor = coincidencia.group(1)
        valor_sin_separadores = re.sub(r"[^0-9]", "", valor)
        if not valor_sin_separadores:
            return None

        if len(valor_sin_separadores) == 8:
            return f"{valor_sin_separadores[:2]}.{valor_sin_separadores[2:5]}.{valor_sin_separadores[5:]}"
        if len(valor_sin_separadores) == 7:
            return f"{valor_sin_separadores[:3]}.{valor_sin_separadores[3:6]}.{valor_sin_separadores[6:]}"
        return None

    def extraer_cliente_y_rut_cliente() -> tuple[Optional[str], Optional[str]]:
        patron = re.compile(
            r"\bS(?:E[ÑN]OR|ENOR)(?:\(ES\)|ES)?\s*([A-ZÁÉÍÓÚÑ0-9 &/\.\-\*]+?)\s*RUT\.?\b",
            re.I,
        )
        coincidencia = patron.search(texto_mayus)
        if not coincidencia:
            return None, None
        cliente = normalizar_cliente(limpiar_valor(coincidencia.group(1)))

        segmento = texto_mayus[coincidencia.end() : coincidencia.end() + 80]
        rut_cliente = buscar_rut(segmento)
        if not rut_cliente:
            segmento = texto_mayus[coincidencia.start() : coincidencia.end() + 80]
            rut_cliente = buscar_rut(segmento)
        return cliente, rut_cliente

    def normalizar_cliente(cliente: str) -> str:
        cliente_normalizado = cliente.strip().upper()
        if re.search(r"\bPRODALA(?:M|K)?(?:[^A-Z0-9]|$)", cliente_normalizado):
            return "PRODALAM SA"
        return cliente.strip()

    def buscar_obra_destino() -> Optional[str]:
        patron = re.compile(r"OBRA\s+DESTINO\s*([A-ZÁÉÍÓÚÑ0-9 &/\.\-]+?)\s+COD\s+DESTINATARIO", re.I)
        coincidencia = patron.search(texto_mayus)
        if coincidencia:
            valor = limpiar_valor(coincidencia.group(1))
            if valor and "COD DESTINATARIO" not in valor.upper():
                return valor

        for indice, linea in enumerate(lineas):
            if "OBRA DESTINO" in linea:
                for linea_siguiente in lineas[indice + 1 : indice + 4]:
                    if any(palabra in linea_siguiente for palabra in ["COD DESTINATARIO", "HORA ENTRADA", "HORA SALIDA", "NRO. TRANSPORTE", "TRANSPORTE"]):
                        continue
                    valor = re.sub(r"\b\d[\d.\s-]*\b", " ", linea_siguiente)
                    valor = re.sub(r"\s+", " ", valor).strip(" :;.-")
                    if len(valor.split()) >= 2 and re.search(r"[A-ZÁÉÍÓÚÑ]", valor):
                        return limpiar_valor(valor)
                break

        return None

    def buscar_horas_y_transporte() -> tuple[Optional[str], Optional[str], Optional[str]]:
        entrada = None
        salida = None
        transporte = None

        posicion_entrada = texto_mayus.find("HORA ENTRADA")
        posicion_salida = texto_mayus.find("HORA SALIDA")
        if posicion_entrada != -1 and posicion_salida != -1:
            segmento_entrada = texto_mayus[posicion_entrada + len("HORA ENTRADA"):posicion_salida]
            coincidencia_entrada = re.search(r"(\d{1,2}:\d{2})", segmento_entrada)
            if coincidencia_entrada:
                entrada = coincidencia_entrada.group(1)

            segmento_salida = texto_mayus[posicion_salida + len("HORA SALIDA"):]
            coincidencias_horas = re.findall(r"\d{1,2}:\d{2}", segmento_salida)
            if len(coincidencias_horas) >= 2:
                salida = coincidencias_horas[1]
            elif coincidencias_horas:
                salida = coincidencias_horas[0]
            coincidencia_transporte = re.search(r"\d{1,2}:\d{2}\s*[:;.]?\s*\d{1,2}\s*[:;.]?\s*(\d{4,})", segmento_salida)
            if not coincidencia_transporte:
                coincidencia_transporte = re.search(r"\d{1,2}:\d{2}\s*(\d{4,})", segmento_salida)
            if not coincidencia_transporte:
                coincidencia_transporte = re.search(r"(\d{4,})", segmento_salida)
            if coincidencia_transporte:
                transporte = coincidencia_transporte.group(1)

        if entrada is None:
            for linea in lineas:
                tiempos = re.findall(r"\d{1,2}:\d{2}", linea)
                if tiempos:
                    entrada = tiempos[0]
                    break

        if salida is None:
            for linea in lineas:
                coincidencia_salida = re.search(r"(\d{1,2}:\d{2})", linea)
                if coincidencia_salida:
                    salida = coincidencia_salida.group(1)
                    break

        if transporte is None:
            for linea in lineas:
                coincidencia_transporte = re.search(r"(\d{4,})", linea)
                if coincidencia_transporte and not re.search(r"\d{1,2}:\d{2}", linea):
                    transporte = coincidencia_transporte.group(1)
                    break

        return entrada, salida, transporte

    def buscar_rut_chofer() -> Optional[str]:
        patron = re.compile(r"\bRUT\.?\s*CHOFER\b[\s\S]{0,40}?([0-9]{1,2}(?:[.\s]?\d{3}){1,2}-?[0-9K]?)", re.I)
        coincidencia = patron.search(texto_mayus)
        if coincidencia:
            return re.sub(r"\s+", "", coincidencia.group(1))
        return None

    def buscar_nombre_chofer() -> Optional[str]:
        for linea in lineas:
            if "CHOFER" in linea and "RUT" not in linea:
                coincidencia = re.search(r"\bCHOFER\b[:\s]*([A-ZÁÉÍÓÚÑ0-9 &/\.\-]+?)$", linea, re.I)
                if coincidencia:
                    nombre = limpiar_valor(coincidencia.group(1))
                    if nombre and not re.match(r"^[0-9]{5,}-?[0-9K]?$", nombre):
                        return nombre

        posicion = texto_mayus.find("RETIRA PATENTE FECHA LLEGADA")
        if posicion != -1:
            bloque = texto_mayus[posicion : posicion + 220]
            patente = buscar_patente_chilena(bloque)
            if patente:
                prefijo = bloque[: bloque.find(patente)]
                prefijo = re.sub(r"\b(?:RETIRA|PATENTE|FECHA|LLEGADA|CARRO)\b", "", prefijo, flags=re.I)
                prefijo = re.sub(r"[^A-ZÁÉÍÓÚÑ0-9\s]", " ", prefijo)
                prefijo = re.sub(r"\s+", " ", prefijo).strip(" :;.-")
                if len(prefijo.split()) >= 2 and "$" not in prefijo and "#" not in prefijo:
                    return prefijo

        for linea in lineas:
            if "$" in linea or "#" in linea:
                continue
            if re.search(r"\b(?:LUIS|JUAN|CARLOS|PEDRO|MIGUEL|JORGE|ANDRES|ROBERTO|ALEJANDRO|MANUEL|LEANDRO)\b", linea):
                if re.search(r"\b[A-ZÁÉÍÓÚÑ]{2,}\b", linea):
                    candidato = limpiar_valor(linea)
                    candidato = re.sub(r"\b(?:RETIRA|PATENTE|FECHA|LLEGADA|CARRO)\b", "", candidato, flags=re.I)
                    candidato = re.sub(r"\b(?:DD|JB|[A-Z]{2,3}\d{3,4}|[A-Z0-9]{6})\b", "", candidato, flags=re.I)
                    candidato = re.sub(r"\s+", " ", candidato).strip(" :;.-")
                    if len(candidato.split()) >= 2:
                        return candidato

        return None

    def buscar_patente_chilena(texto: str) -> Optional[str]:
        patrones = [
            re.compile(r"\b([A-Z]{2}\d{4})\b"),
            re.compile(r"\b([A-Z]{3}\d{3})\b"),
            re.compile(r"\b([A-Z0-9]{6})\b"),
        ]
        for patron in patrones:
            for coincidencia in patron.finditer(texto):
                placa = coincidencia.group(1)
                if re.search(r"[A-Z]", placa) and re.search(r"\d", placa):
                    return placa
        return None

    def buscar_patente_cerca() -> tuple[Optional[str], Optional[str]]:
        pat_tracto: Optional[str] = None
        pat_carro: Optional[str] = None

        patron_chofer = re.compile(r"RETIRA\s+PATENTE\s+FECHA\s+LLEGADA(?:\s|[\r\n])+(.*?)\b([A-Z]{2,3}\d{3,4})\b", re.I)
        coincidencia_chofer = patron_chofer.search(texto_mayus)
        if coincidencia_chofer:
            pat_tracto = coincidencia_chofer.group(2)

        coincidencia_carro = re.search(r"\bCARRO\b[^\n]*?\b([A-Z]{2,3}\d{3,4})\b", texto_mayus, re.I)
        if coincidencia_carro:
            pat_carro = coincidencia_carro.group(1)

        if not pat_tracto:
            for palabra in ["PATENTE DEL TRACTO", "RETIRA PATENTE", "PATENTE", "TRACTO"]:
                posicion = texto_mayus.find(palabra)
                if posicion == -1:
                    continue
                segmento = texto_mayus[posicion : posicion + 120]
                patente = buscar_patente_chilena(segmento)
                if patente:
                    pat_tracto = patente
                    break

        if not pat_carro:
            for palabra in ["PATENTE DEL CARRO", "CARRO"]:
                posicion = texto_mayus.find(palabra)
                if posicion == -1:
                    continue
                segmento = texto_mayus[posicion : posicion + 120]
                patente = buscar_patente_chilena(segmento)
                if patente:
                    pat_carro = patente
                    break

        if not pat_tracto and not pat_carro:
            patente = buscar_patente_chilena(texto_mayus)
            if patente:
                pat_tracto = patente

        return pat_tracto, pat_carro

    cliente, rut_cliente = extraer_cliente_y_rut_cliente()
    if cliente:
        datos["cliente"] = cliente
    if rut_cliente:
        datos["RUT del cliente"] = rut_cliente

    obra_destino = buscar_obra_destino()
    if obra_destino:
        datos["obra destino"] = obra_destino

    datos["número de guía"] = (
        buscar_patrones([
            re.compile(
                r"GU[ÍI]A\s+DE\s+DESPACHO\s+ELECTR(?:O|Ó)NICA[\s\S]{0,40}?\bN[°º\?\s]*O?\s*[:\-]?\s*(\d{5,8})",
                re.I,
            ),
            re.compile(
                r"GU[ÍI]A[\s\S]{0,40}?DESPACHO[\s\S]{0,40}?ELECTR(?:O|Ó)NICA[\s\S]{0,40}?\bN[°º\?\s]*O?\s*[:\-]?\s*(\d{5,8})",
                re.I,
            ),
        ])
        or datos["número de guía"]
    )

    datos["chofer"] = buscar_nombre_chofer() or datos["chofer"]
    datos["RUT del chofer"] = buscar_rut_chofer() or datos["RUT del chofer"]

    patente_tracto, patente_carro = buscar_patente_cerca()
    if patente_tracto:
        datos["patente del tracto"] = patente_tracto
    if patente_carro:
        datos["patente del carro"] = patente_carro

    if (
        datos["patente del tracto"] != "No encontrado"
        and datos["patente del tracto"] == datos["patente del carro"]
    ):
        datos["patente del carro"] = "No encontrado"

    hora_entrada, hora_salida, transporte = buscar_horas_y_transporte()
    if hora_entrada:
        datos["hora de entrada"] = hora_entrada
    if hora_salida:
        datos["hora de salida"] = hora_salida
    if transporte:
        datos["número de transporte"] = transporte

    datos["peso"] = (
        buscar_patrones([
            re.compile(r"PESO\s*KG[-:\s]*([0-9]{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?)", re.I),
        ])
        or datos["peso"]
    )

    if datos["número de transporte"] == "No encontrado":
        datos["número de transporte"] = (
            buscar_patrones([
                re.compile(r"N\.?R\.?O\.?\s*TRANSPORTE[\s\S]{0,40}?\b(\d{4,})", re.I),
                re.compile(r"NRO\s*TRANSPORTE[\s\S]{0,40}?\b(\d{4,})", re.I),
            ])
            or datos["número de transporte"]
        )

    return datos


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


def main() -> None:
    """Función principal del programa."""
    print("Proyecto Atlas")

    ruta_imagen = solicitar_ruta_imagen()
    if ruta_imagen is None:
        return

    print(f"Procesando imagen: {ruta_imagen}")
    textos = leer_texto_imagen(ruta_imagen)
    mostrar_texto(textos)

    datos = extraer_datos(textos)
    mostrar_datos_extraidos(datos)


if __name__ == "__main__":
    main()
