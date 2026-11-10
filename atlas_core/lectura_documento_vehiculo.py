"""Lectura de originales vehiculares mediante el OCR y rasterizador existentes."""
from pathlib import Path
from tempfile import TemporaryDirectory
import re
import unicodedata


def leer_texto_documento(ruta: Path, proveedor):
    """Lee todas las páginas; un PDF incompleto nunca produce una lectura parcial."""
    ruta = Path(ruta)
    if ruta.suffix.lower() != ".pdf":
        return list(proveedor().leer_texto(ruta))
    from atlas_core.ingesta_pdf import rasterizar_pdf
    with TemporaryDirectory(prefix=".ocr-vehiculo-", dir=ruta.parent) as temporal:
        resultado = rasterizar_pdf(ruta, temporal)
        if resultado.errores or not resultado.procesable or len(resultado.paginas) != resultado.paginas_declaradas:
            return None
        lineas = []
        for pagina in resultado.paginas:
            lineas.extend(proveedor().leer_texto(pagina.ruta_imagen))
        return lineas


def extraer_campos_adicionales(lineas):
    """Sólo acepta valores rotulados e inequívocos; conserva evidencia por campo."""
    from atlas_core.extraccion_vencimientos_vehiculos import _fechas

    normalizadas = []
    for linea in lineas:
        texto = unicodedata.normalize("NFKD", str(linea).upper())
        normalizadas.append(" ".join("".join(c for c in texto if not unicodedata.combining(c)).split()))

    def campo(candidatos):
        valores = {valor for valor, _ in candidatos}
        return {"valor": next(iter(valores)) if len(valores) == 1 else None,
                "estado": "EXTRAIDO" if len(valores) == 1 else "PENDIENTE_REVISION",
                "motivo": "" if len(valores) == 1 else "VARIOS_VALORES" if valores else "NO_ENCONTRADO",
                "evidencia": [linea for _, linea in candidatos][:10]}

    emision, aseguradora, poliza = [], [], []
    for linea in normalizadas:
        if re.search(r"\b(?:FECHA\s+DE\s+EMISION|EMITIDO\s+EL)\b", linea):
            fechas, malas = _fechas(linea)
            if not malas:
                emision.extend((f["valor"], linea) for f in fechas if not f["hora"])
        for patron, destino in (
            (r"^\s*(?:ASEGURADORA|COMPANIA DE SEGUROS)\s*:\s*([A-Z0-9][A-Z0-9 .&-]{2,79})\s*$", aseguradora),
            (r"^\s*(?:POLIZA|NUMERO DE POLIZA|NRO\.? DE POLIZA)\s*[:#]\s*([A-Z0-9][A-Z0-9/-]{2,39})\s*$", poliza),
        ):
            match = re.match(patron, linea)
            if match:
                destino.append((match.group(1).strip(), linea))
    # Una lista explícita y cerrada de coberturas, sin lenguaje de exclusión.
    # No se infieren coberturas desde títulos, cláusulas, límites o glosas libres.
    rotuladas = [linea for linea in normalizadas if re.match(r"^COBERTURAS?\s*:", linea)]
    cubiertas = set()
    for linea in rotuladas:
        contenido = linea.split(":", 1)[1].strip()
        partes = re.split(r"\s*(?:,|;|\bY\b)\s*", contenido)
        mapa = {"RESPONSABILIDAD CIVIL": "POLIZA_RESPONSABILIDAD_CIVIL", "ROBO": "POLIZA_ROBO",
                "ROBOS": "POLIZA_ROBO"}
        if not partes or any(p not in mapa for p in partes):
            cubiertas = set()
            break
        cubiertas.update(mapa[p] for p in partes)
    if any(re.search(r"\b(?:EXCLUSION|EXCLUID[OA]S?|NO CUBRE|SIN COBERTURA)\b", l) for l in normalizadas):
        cubiertas.clear()
    cobertura = {"valor": sorted(cubiertas) if cubiertas else None,
                 "estado": "EXTRAIDO" if cubiertas else "PENDIENTE_REVISION",
                 "motivo": "" if cubiertas else "NO_ENCONTRADO_O_AMBIGUO", "evidencia": rotuladas[:10]}
    return {"emision": campo(emision), "aseguradora": campo(aseguradora), "numero_poliza": campo(poliza),
            "coberturas": cobertura}
