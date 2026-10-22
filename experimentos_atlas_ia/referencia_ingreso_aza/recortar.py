"""Recorta y amplía una región de una imagen para inspección visual humana o del agente.

Sólo Pillow (rotar, recortar, redimensionar). No ejecuta OCR. La región va en
coordenadas normalizadas 0–1 sobre la imagen ya rotada, para que la misma
ubicación se pueda mostrar luego en la revisión sin depender de la resolución.

Uso:
  python -I recortar.py <imagen> <salida.png> [--caja x0,y0,x1,y1] [--rotar 0|90|180|270]
                        [--ancho 1600]
"""

import argparse

from PIL import Image, ImageOps


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("imagen")
    p.add_argument("salida")
    p.add_argument("--caja", default="0,0,1,1")
    p.add_argument("--rotar", type=int, default=0, choices=(0, 90, 180, 270))
    p.add_argument("--ancho", type=int, default=1600)
    a = p.parse_args()
    img = ImageOps.exif_transpose(Image.open(a.imagen))
    if a.rotar:
        img = img.rotate(-a.rotar, expand=True)  # sentido horario
    x0, y0, x1, y1 = (float(v) for v in a.caja.split(","))
    w, h = img.size
    region = img.crop((round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h)))
    escala = a.ancho / region.width
    region = region.resize((a.ancho, max(1, round(region.height * escala))), Image.LANCZOS)
    region.convert("RGB").save(a.salida)
    print(f"{a.salida} {region.width}x{region.height} desde {w}x{h}")


if __name__ == "__main__":
    main()
