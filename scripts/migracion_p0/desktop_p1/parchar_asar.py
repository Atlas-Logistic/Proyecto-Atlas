"""Parche determinista de app.asar para Desktop P1.1+P1.2 (ficha B1).

    python parchar_asar.py --entrada <app.asar instalado> --salida <candidato.asar> [--verificar-solo]

Toma el app.asar instalado (SHA-256 esperado en manifiesto.json), reemplaza
o agrega sólo los archivos de `archivos/` (finales de línea CRLF, igual que el
instalado) y escribe el candidato. El resultado se comprueba contra el SHA-256
esperado: CASA y OFICINA obtienen exactamente los mismos bytes. Nunca modifica
la entrada; app.asar.unpacked no cambia (consulta_python.py no se toca).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
BLOQUE = 4 * 1024 * 1024


def sha256(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def integridad(datos: bytes) -> dict:
    bloques = [sha256(datos[i:i + BLOQUE]) for i in range(0, max(len(datos), 1), BLOQUE)]
    return {"algorithm": "SHA256", "hash": sha256(datos), "blockSize": BLOQUE, "blocks": bloques}


def leer_asar(ruta: Path) -> tuple[dict, bytes]:
    datos = ruta.read_bytes()
    _, tam_pickle, _, largo = struct.unpack("<4I", datos[:16])
    cabecera = json.loads(datos[16:16 + largo].decode("utf-8"))
    return cabecera, datos[8 + tam_pickle:]


def archivos(nodo: dict, prefijo: str = ""):
    for nombre, entrada in nodo.get("files", {}).items():
        ruta = f"{prefijo}{nombre}"
        if "files" in entrada:
            yield from archivos(entrada, ruta + "/")
        else:
            yield ruta, entrada


def contenido(entrada: dict, cuerpo: bytes) -> bytes:
    inicio = int(entrada["offset"])
    return cuerpo[inicio:inicio + entrada["size"]]


def escribir_asar(cabecera: dict, cuerpo: bytes) -> bytes:
    texto = json.dumps(cabecera, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    relleno = (4 - len(texto) % 4) % 4
    carga = struct.pack("<I", len(texto)) + texto + b"\0" * relleno
    pickle = struct.pack("<I", len(carga)) + carga
    return struct.pack("<2I", 4, len(pickle)) + pickle + cuerpo


def parchar(entrada: Path, reemplazos: dict[str, bytes]) -> bytes:
    cabecera, cuerpo = leer_asar(entrada)
    empaquetados = sorted(((r, e) for r, e in archivos(cabecera) if not e.get("unpacked")),
                          key=lambda par: int(par[1]["offset"]))
    existentes = {r for r, _ in archivos(cabecera)}
    nuevo_cuerpo = bytearray()
    for ruta, e in empaquetados:
        datos = reemplazos.get(ruta, contenido(e, cuerpo))
        e["offset"] = str(len(nuevo_cuerpo))
        e["size"] = len(datos)
        e["integrity"] = integridad(datos)
        nuevo_cuerpo += datos
    for ruta in sorted(set(reemplazos) - existentes):
        partes = ruta.split("/")
        nodo = cabecera
        for carpeta in partes[:-1]:
            nodo = nodo["files"][carpeta]  # sólo archivos nuevos en carpetas existentes
        datos = reemplazos[ruta]
        nueva = {"size": len(datos), "offset": str(len(nuevo_cuerpo)), "integrity": integridad(datos)}
        # Se conserva el orden del índice instalado: la entrada nueva va
        # antes de la primera que la sigue alfabéticamente.
        hijos, puesta = {}, False
        for nombre, existente in nodo["files"].items():
            if not puesta and nombre > partes[-1]:
                hijos[partes[-1]], puesta = nueva, True
            hijos[nombre] = existente
        if not puesta:
            hijos[partes[-1]] = nueva
        nodo["files"] = hijos
        nuevo_cuerpo += datos
    return escribir_asar(cabecera, bytes(nuevo_cuerpo))


def verificar(entrada: Path, salida_bytes: bytes, reemplazos: dict[str, bytes]) -> list[str]:
    """Todo archivo del candidato es el reemplazo pedido o idéntico al instalado."""
    errores = []
    tmp = Path(str(entrada) + ".verificacion.tmp")
    tmp.write_bytes(salida_bytes)
    try:
        cab_in, cuerpo_in = leer_asar(entrada)
        cab_out, cuerpo_out = leer_asar(tmp)
    finally:
        tmp.unlink()
    antes = dict(archivos(cab_in))
    despues = dict(archivos(cab_out))
    if set(despues) != set(antes) | set(reemplazos):
        errores.append(f"lista de archivos inesperada: {sorted(set(despues) ^ (set(antes) | set(reemplazos)))[:10]}")
    for ruta, e in despues.items():
        if e.get("unpacked"):
            if e != antes.get(ruta):
                errores.append(f"entrada desempaquetada cambiada: {ruta}")
            continue
        datos = contenido(e, cuerpo_out)
        esperado = reemplazos.get(ruta, contenido(antes[ruta], cuerpo_in) if ruta in antes else None)
        if datos != esperado:
            errores.append(f"contenido distinto: {ruta}")
        if e["integrity"]["hash"] != sha256(datos):
            errores.append(f"integridad incorrecta: {ruta}")
    return errores


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entrada", required=True, type=Path)
    parser.add_argument("--salida", required=True, type=Path)
    args = parser.parse_args()
    manifiesto = json.loads((AQUI / "manifiesto.json").read_text(encoding="utf-8"))
    if sha256(args.entrada.read_bytes()) != manifiesto["asar_entrada_sha256"]:
        print(f"ERROR: app.asar de entrada no es el esperado ({manifiesto['asar_entrada_sha256'][:8]}); no se parcha.")
        return 2
    reemplazos = {}
    for ruta, huella in manifiesto["archivos"].items():
        datos = (AQUI / "archivos" / ruta).read_bytes()
        if sha256(datos) != huella:
            print(f"ERROR: archivo del kit alterado: {ruta}")
            return 2
        reemplazos[ruta] = datos
    salida = parchar(args.entrada, reemplazos)
    errores = verificar(args.entrada, salida, reemplazos)
    if errores:
        print("ERROR: " + "; ".join(errores))
        return 2
    if manifiesto.get("asar_salida_sha256") and sha256(salida) != manifiesto["asar_salida_sha256"]:
        print(f"ERROR: candidato con SHA-256 inesperado {sha256(salida)}")
        return 2
    if args.salida.exists():
        print("ERROR: la salida ya existe; no se sobrescribe.")
        return 2
    args.salida.write_bytes(salida)
    print(json.dumps({"candidato": str(args.salida), "sha256": sha256(salida), "archivos": sorted(reemplazos)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
