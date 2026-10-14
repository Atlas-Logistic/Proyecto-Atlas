"""Worker aislado de RapidOCR/ONNX Runtime para ``RapidOCRProvider``.

Se ejecuta con el intérprete configurado en ``ATLAS_RAPIDOCR_PYTHON``. No
importa el Motor, no escribe archivos Atlas y devuelve sólo JSON por stdout.
Las imágenes se transponen por EXIF antes de OCR, por lo que las coordenadas
de salida ya corresponden a la referencia documental que usa Atlas.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _dependencias():
    import numpy as np
    from PIL import Image, ImageEnhance, ImageOps
    from rapidocr_onnxruntime import RapidOCR
    return np, Image, ImageEnhance, ImageOps, RapidOCR


def _filas(resultado: Any) -> list[object]:
    if isinstance(resultado, tuple) and len(resultado) == 2:
        resultado = resultado[0]
    return list(resultado or []) if isinstance(resultado, (list, tuple)) else []


def _bloques(engine: Any, ruta: str, Image, ImageOps, np) -> list[list[object]]:
    with Image.open(Path(ruta)) as imagen:
        orientada = ImageOps.exif_transpose(imagen).convert("RGB")
        resultado = engine(np.asarray(orientada))
    salida: list[list[object]] = []
    for fila in _filas(resultado):
        if not isinstance(fila, (list, tuple)) or len(fila) < 3:
            continue
        bbox, texto, confianza = fila[0], fila[1], fila[2]
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4 or not str(texto or "").strip():
            continue
        try:
            salida.append([
                [[float(p[0]), float(p[1])] for p in bbox], str(texto), float(confianza),
            ])
        except (TypeError, ValueError, IndexError):
            continue
    return salida


def _focal(engine: Any, ruta: str, caja: list[float], Image, ImageEnhance, ImageOps, np) -> dict[str, object]:
    with Image.open(Path(ruta)) as imagen:
        orientada = ImageOps.exif_transpose(imagen).convert("RGB")
        x1, y1, x2, y2 = (float(valor) for valor in caja)
        if not (x1 < x2 and y1 < y2):
            raise ValueError("La caja focal no tiene dimensiones válidas")
        ancho, alto = x2 - x1, y2 - y1
        margen_x, margen_y = max(4, round(ancho * 0.12)), max(4, round(alto * 0.35))
        recorte = (max(0, int(x1) - margen_x), max(0, int(y1) - margen_y),
                   min(orientada.width, int(x2 + 0.999) + margen_x), min(orientada.height, int(y2 + 0.999) + margen_y))
        if recorte[0] >= recorte[2] or recorte[1] >= recorte[3]:
            raise ValueError("El recorte focal quedó fuera de la imagen")
        original = orientada.crop(recorte)
        ampliada = original.resize((original.width * 2, original.height * 2), Image.Resampling.LANCZOS)
        variantes = (("original", original), ("grises", ImageOps.grayscale(original)),
                     ("ampliada_2x", ampliada),
                     ("ampliada_2x_contraste", ImageEnhance.Contrast(ImageOps.grayscale(ampliada)).enhance(1.35)))
    lecturas = []
    for nombre, variante in variantes:
        bloques = _filas(engine(np.asarray(variante.convert("RGB"))))
        textos = [str(fila[1]) for fila in bloques if isinstance(fila, (list, tuple)) and len(fila) >= 3]
        confianzas = [float(fila[2]) for fila in bloques if isinstance(fila, (list, tuple)) and len(fila) >= 3 and isinstance(fila[2], (int, float))]
        lecturas.append({"variante": nombre, "texto": " ".join(textos), "confianza": min(confianzas) if confianzas else None})
    return {"recorte": list(recorte), "lecturas": lecturas}


def main() -> int:
    try:
        np, Image, ImageEnhance, ImageOps, RapidOCR = _dependencias()
        engine = RapidOCR()
    except Exception as exc:  # import/modelo fallido: el padre mostrará un mensaje apto para operador
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), flush=True)
        return 1
    print(json.dumps({"ok": True, "listo": True, "engine": "rapidocr-onnxruntime", "device": "cpu"}), flush=True)
    for linea in sys.stdin:
        if not linea.strip():
            continue
        try:
            comando = json.loads(linea)
            op, ruta = comando["op"], str(comando["ruta"])
            if op == "bloques":
                resultado: object = _bloques(engine, ruta, Image, ImageOps, np)
            elif op == "texto":
                resultado = "\n".join(str(fila[1]) for fila in _bloques(engine, ruta, Image, ImageOps, np))
            elif op == "focal":
                resultado = _focal(engine, ruta, list(comando["caja"]), Image, ImageEnhance, ImageOps, np)
            else:
                raise ValueError(f"Operación desconocida: {op}")
            print(json.dumps({"ok": True, "resultado": resultado}), flush=True)
        except Exception as exc:
            print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
