"""Retoma entradas Desktop recibidas cuyo procesamiento nunca comenzó
(ver `atlas_core.entradas_desktop`, caso real 475193).

  --listar             JSON con los lotes NUNCA_INICIADA (sólo lectura).
  --lote L --salida CSV --catalogos DIR
                       procesa ESA entrada existente con el mismo
                       `analizar_guias_masivo` (+ --reconciliar-focal) que
                       usa Desktop al soltar imágenes; nunca copia nada ni
                       crea otro lote. Última línea: JSON del resultado.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from atlas_core.entradas_desktop import clasificar_entradas_desktop, NUNCA_INICIADA, retomar_entrada_desktop


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raiz-atlas", type=Path, required=True)
    parser.add_argument("--listar", action="store_true")
    parser.add_argument("--lote")
    parser.add_argument("--salida", type=Path)
    parser.add_argument("--catalogos", type=Path)
    argumentos = parser.parse_args(argv)

    if argumentos.listar:
        lotes = [
            c for c in clasificar_entradas_desktop(argumentos.raiz_atlas) if c["estado"] == NUNCA_INICIADA
        ]
        print(json.dumps({"pendientes": lotes}, ensure_ascii=False))
        return
    if not (argumentos.lote and argumentos.salida and argumentos.catalogos):
        parser.error("--lote requiere --salida y --catalogos")

    def ejecutar(carpeta: Path) -> None:
        import analizar_guias_masivo

        analizar_guias_masivo.main([
            str(carpeta), "--salida", str(argumentos.salida),
            "--catalogos", str(argumentos.catalogos), "--reconciliar-focal",
        ])

    resultado = retomar_entrada_desktop(argumentos.raiz_atlas, argumentos.lote, ejecutar=ejecutar)
    print(json.dumps(resultado, ensure_ascii=False))


if __name__ == "__main__":
    main()
