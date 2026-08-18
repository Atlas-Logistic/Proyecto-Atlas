"""Worker de PaddleOCR para ejecución en proceso/entorno aislado.

Este módulo se ejecuta con el intérprete del venv aislado de PaddleOCR
(fuera del entorno principal de Atlas), nunca se importa directamente desde
el proceso principal. Por eso NO importa nada de atlas_core ni depende de
easyocr — solo de la librería estándar, PaddleOCR y Pillow/numpy (ya
dependencias de paddleocr).

Protocolo: línea de inicialización JSON por stdin con {"device": "gpu"|"cpu"},
luego una línea JSON por comando: {"op": "texto"|"bloques"|"focal", ...}.
Responde una línea JSON por comando: {"ok": true, "resultado": ...} o
{"ok": false, "error": "..."}. Termina al cerrarse stdin.

Si se modifica el recorte/margen/variantes de _leer_region_focal en
atlas_core/ocr.py, esta copia debe actualizarse a mano — la aislación de
proceso impide compartir el código directamente.
"""
import json
import sys


def _cargar_dependencias():
    from paddleocr import PaddleOCR
    from PIL import Image, ImageEnhance, ImageOps
    import numpy as np

    return PaddleOCR, Image, ImageEnhance, ImageOps, np


def _crear_ocr(PaddleOCR, device):
    kwargs = dict(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        device=device,
    )
    if device == "cpu":
        # Workaround estable (Fase 0 de OCR-EVAL): sin esto, la inferencia
        # falla en Windows con NotImplementedError de oneDNN/PIR.
        kwargs["enable_mkldnn"] = False
    return PaddleOCR(**kwargs)


def _paginas_a_bloques(paginas):
    bloques = []
    for pagina in paginas:
        textos = pagina.get("rec_texts", []) or []
        scores = pagina.get("rec_scores", []) or []
        polys = pagina.get("rec_polys", pagina.get("dt_polys", [])) or []
        for idx, texto in enumerate(textos):
            score = float(scores[idx]) if idx < len(scores) else None
            bbox = polys[idx].tolist() if idx < len(polys) and hasattr(polys[idx], "tolist") else None
            bloques.append({"texto": texto, "bbox": bbox, "confianza": score})
    return bloques


def _recortar_variantes(Image, ImageEnhance, ImageOps, ruta, caja):
    """Replica el recorte/margen/variantes de atlas_core.ocr._leer_region_focal."""
    with Image.open(ruta) as imagen:
        orientada = ImageOps.exif_transpose(imagen).convert("RGB")
        x1, y1, x2, y2 = (float(v) for v in caja)
        if not (x1 < x2 and y1 < y2):
            raise ValueError("La caja focal no tiene dimensiones válidas")
        ancho, alto = x2 - x1, y2 - y1
        margen_x = max(4, round(ancho * 0.12))
        margen_y = max(4, round(alto * 0.35))
        recorte = (
            max(0, int(x1) - margen_x),
            max(0, int(y1) - margen_y),
            min(orientada.width, int(x2 + 0.999) + margen_x),
            min(orientada.height, int(y2 + 0.999) + margen_y),
        )
        if recorte[0] >= recorte[2] or recorte[1] >= recorte[3]:
            raise ValueError("El recorte focal quedó fuera de la imagen")
        original = orientada.crop(recorte)
        gris = ImageOps.grayscale(original)
        ampliada = original.resize((original.width * 2, original.height * 2), Image.Resampling.LANCZOS)
        ampliada_contraste = ImageEnhance.Contrast(ImageOps.grayscale(ampliada)).enhance(1.35)
        return recorte, (
            ("original", original),
            ("grises", gris),
            ("ampliada_2x", ampliada),
            ("ampliada_2x_contraste", ampliada_contraste),
        )


def _a_array_rgb(variante, np):
    """Normaliza una variante PIL a un array (H, W, 3) antes de pasarla a
    PaddleOCR.predict() -- exige canal de color; un array 2D (H, W), que
    resulta de convertir directamente una imagen en modo "L"/escala de
    grises, se rechaza siempre con "ValueError: not enough values to
    unpack (expected 3, got 2)". `.convert("RGB")` sólo normaliza el
    formato de canales (un gris ya es R=G=B replicado) -- nunca altera el
    contenido visual, y es no-op para variantes ya en RGB."""
    return np.asarray(variante.convert("RGB"))


def _ejecutar_focal(ocr, ruta, caja, Image, ImageEnhance, ImageOps, np):
    """Ejecuta las 4 variantes focales contra un `ocr` ya inicializado
    (con `.predict()`) -- extraído de la rama "focal" de `main()` para
    poder probarlo con un doble de OCR, sin depender de PaddleOCR real."""
    recorte, variantes = _recortar_variantes(Image, ImageEnhance, ImageOps, ruta, caja)
    lecturas = []
    for nombre, variante in variantes:
        arreglo = _a_array_rgb(variante, np)
        paginas = list(ocr.predict(arreglo))
        bloques = _paginas_a_bloques(paginas)
        texto = " ".join(b["texto"] for b in bloques)
        confianzas = [b["confianza"] for b in bloques if isinstance(b["confianza"], (int, float))]
        lecturas.append({
            "variante": nombre,
            "texto": texto,
            "confianza": min(confianzas) if confianzas else None,
        })
    return {"recorte": list(recorte), "lecturas": lecturas}


def main():
    PaddleOCR, Image, ImageEnhance, ImageOps, np = _cargar_dependencias()

    linea_init = sys.stdin.readline()
    init = json.loads(linea_init) if linea_init.strip() else {}
    device = init.get("device", "cpu")
    ocr = _crear_ocr(PaddleOCR, device)

    print(json.dumps({"ok": True, "listo": True, "device": device}), flush=True)

    for linea in sys.stdin:
        linea = linea.strip()
        if not linea:
            continue
        try:
            comando = json.loads(linea)
            op = comando["op"]
            ruta = comando["ruta"]
            if op in ("texto", "bloques"):
                paginas = list(ocr.predict(ruta))
                bloques = _paginas_a_bloques(paginas)
                if op == "texto":
                    resultado = "\n".join(b["texto"] for b in bloques)
                else:
                    resultado = bloques
            elif op == "focal":
                caja = comando["caja"]
                resultado = _ejecutar_focal(ocr, ruta, caja, Image, ImageEnhance, ImageOps, np)
            else:
                raise ValueError(f"Operación desconocida: {op}")
            print(json.dumps({"ok": True, "resultado": resultado}), flush=True)
        except Exception as exc:  # el worker nunca debe morir por un error de una imagen
            print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), flush=True)


if __name__ == "__main__":
    main()
