"""Worker aislado para EasyOCR usado sólo por el fallback acotado de PULL.

Protocolo JSONL: al estar listo emite ``{"ok": true}``; después recibe una
operación ``texto``, ``bloques`` o ``focal`` y responde un único JSON. No lee
ni escribe datos operativos de Atlas: sus únicas entradas son rutas de imagen
y sus únicas salidas son resultados OCR por stdout.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from atlas_core.ocr import _leer_region_focal, crear_lector_ocr, leer_bloques_imagen, leer_texto_imagen


def _bloques_json(ruta: str, lector: Any) -> list[dict[str, object]]:
    return [
        {"texto": bloque.texto, "bbox": [list(punto) for punto in bloque.bounding_box], "confianza": bloque.confianza}
        for bloque in leer_bloques_imagen(ruta, lector=lector)
    ]


def main() -> None:
    lector = crear_lector_ocr()
    print(json.dumps({"ok": True, "listo": True}), flush=True)
    for linea in sys.stdin:
        try:
            comando = json.loads(linea)
            ruta = str(comando["ruta"])
            operacion = comando["op"]
            if operacion == "texto":
                resultado: object = leer_texto_imagen(ruta, lector=lector)
            elif operacion == "bloques":
                resultado = _bloques_json(ruta, lector)
            elif operacion == "focal":
                resultado = _leer_region_focal(
                    ruta, tuple(float(v) for v in comando["caja"]), lector=lector,
                    allowlist=str(comando.get("allowlist", "")),
                )
            else:
                raise ValueError(f"Operación desconocida: {operacion}")
            print(json.dumps({"ok": True, "resultado": resultado}), flush=True)
        except Exception as error:
            print(json.dumps({"ok": False, "error": f"{type(error).__name__}: {error}"}), flush=True)


if __name__ == "__main__":
    main()
