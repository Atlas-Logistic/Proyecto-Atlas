"""Banco aislado para comparar PaddleOCR CPU y EasyOCR por campo.

Las fotos, manifiesto real y resultados viven bajo ``data/ocr_cpu_benchmark/``
(ignorado por Git). Este programa nunca lee ni escribe la raíz Atlas: recibe
copias locales ya preparadas. Antes de OCR rechaza ejecutar si la tarea PULL
de oficina está activa.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Mapping


CAMPOS_POR_DEFECTO = ("numero_guia", "numero_transporte", "fecha", "cliente", "obra_destino", "chofer")


def _normalizar(valor: object) -> str:
    return "".join(str(valor or "").upper().split())


def pull_activo() -> bool:
    """Consulta de sólo lectura del scheduler de Windows.

    Si no es posible consultar el scheduler, devuelve ``True``: el benchmark
    prefiere abstenerse a competir con PULL por CPU.
    """
    if sys.platform != "win32":
        return False
    comando = (
        "$t=Get-ScheduledTask -TaskName 'Atlas Mobile - PULL Cloud a Motor' "
        "-TaskPath '\\Atlas\\' -ErrorAction SilentlyContinue; "
        "if($null -eq $t){exit 1}; if([int]$t.State -eq 4){exit 0}; exit 1"
    )
    try:
        return subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", comando],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return True


def preparar_banco(manifiesto: Path, destino: Path) -> dict[str, object]:
    """Copia sólo los archivos declarados a un banco local y calcula SHA-256."""
    datos = json.loads(manifiesto.read_text(encoding="utf-8"))
    muestras = datos.get("muestras", [])
    if not isinstance(muestras, list) or not muestras:
        raise ValueError("El manifiesto debe contener una lista no vacía 'muestras'.")
    destino.mkdir(parents=True, exist_ok=True)
    preparadas = []
    for muestra in muestras:
        origen = Path(str(muestra["origen"])).resolve()
        nombre = Path(str(muestra.get("archivo") or origen.name)).name
        if not origen.is_file():
            raise FileNotFoundError(f"No existe la foto fuente: {origen}")
        copia = destino / nombre
        if copia.exists() and hashlib.sha256(copia.read_bytes()).digest() != hashlib.sha256(origen.read_bytes()).digest():
            raise ValueError(f"La copia existente no coincide con la fuente: {copia}")
        if not copia.exists():
            shutil.copy2(origen, copia)
        preparadas.append({"id": str(muestra.get("id", nombre)), "archivo": nombre,
                            "sha256": hashlib.sha256(copia.read_bytes()).hexdigest(), "bytes": copia.stat().st_size})
    return {"muestras": preparadas, "directorio": str(destino)}


def _proveedor(nombre: str):
    from atlas_core.ocr_provider import EasyOCRProvider, PaddleOCRProvider
    if nombre == "easyocr":
        return EasyOCRProvider()
    if nombre == "paddleocr_cpu":
        return PaddleOCRProvider(device="cpu")
    raise ValueError(f"Proveedor no admitido: {nombre}")


def _evaluar_campos(extraido: Mapping[str, object], esperado: Mapping[str, object]) -> dict[str, dict[str, object]]:
    campos = sorted(set(esperado) & set(CAMPOS_POR_DEFECTO))
    return {
        campo: {"esperado": esperado[campo], "obtenido": extraido.get(campo, ""),
                "correcto": _normalizar(extraido.get(campo, "")) == _normalizar(esperado[campo])}
        for campo in campos
    }


def comparar(manifiesto: Path, directorio: Path, fabrica: Callable[[str], object] = _proveedor) -> dict[str, object]:
    """Ejecuta ambos motores sobre copias locales, mide CPU/wall y extrae campos."""
    from atlas_core.extractor import extraer_datos

    datos = json.loads(manifiesto.read_text(encoding="utf-8"))
    resultados: dict[str, object] = {"motores": {}, "muestras": []}
    for nombre_motor in ("paddleocr_cpu", "easyocr"):
        proveedor = fabrica(nombre_motor)
        motor = []
        try:
            for muestra in datos["muestras"]:
                ruta = directorio / Path(str(muestra["archivo"])).name
                inicio_wall, inicio_cpu = time.perf_counter(), time.process_time()
                lineas = proveedor.leer_texto(ruta)
                extraido = extraer_datos(lineas)
                motor.append({"id": muestra.get("id", ruta.name), "archivo": ruta.name,
                              "wall_seg": round(time.perf_counter() - inicio_wall, 3),
                              "cpu_seg": round(time.process_time() - inicio_cpu, 3),
                              "campos": _evaluar_campos(extraido, muestra.get("esperado", {})),
                              "texto": lineas})
        finally:
            if hasattr(proveedor, "cerrar"):
                proveedor.cerrar()
        resultados["motores"][nombre_motor] = motor
    return resultados


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="accion", required=True)
    preparar = sub.add_parser("preparar")
    preparar.add_argument("--manifiesto", type=Path, required=True)
    preparar.add_argument("--destino", type=Path, required=True)
    correr = sub.add_parser("comparar")
    correr.add_argument("--manifiesto", type=Path, required=True)
    correr.add_argument("--directorio", type=Path, required=True)
    correr.add_argument("--salida", type=Path, required=True)
    correr.add_argument("--confirmar-ventana-segura", action="store_true")
    args = parser.parse_args(argv)

    if args.accion == "preparar":
        print(json.dumps(preparar_banco(args.manifiesto, args.destino), ensure_ascii=False, indent=2))
        return 0
    if not args.confirmar_ventana_segura:
        parser.error("comparar exige --confirmar-ventana-segura")
    if pull_activo():
        print("BLOQUEADO: PULL está activo o no fue posible verificarlo; no se inició OCR.", file=sys.stderr)
        return 2
    resultado = comparar(args.manifiesto, args.directorio)
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"salida": str(args.salida), "motores": list(resultado["motores"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
