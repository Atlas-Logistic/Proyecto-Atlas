"""Raíz de trabajo local y raíz publicada (P0.3.1), visto por cualquier proceso.

Con ``raiz_publicada.json`` en la carpeta local de la empresa, Drive es la
raíz PUBLICADA (sólo recibe lo que Cloud confirmó) y el Motor escribe en la
raíz de TRABAJO local. Desktop muestra la publicada y entrega esa ruta a los
scripts del Motor (``--raiz-atlas``, ``ATLAS_DATA_DIR``, solicitud de
``desktop_operacion``): al importar ``atlas_core`` se redirige a la de
trabajo, de modo que toda acción de Desktop/B1 escribe bajo lease en la raíz
de trabajo y su resultado llega a Drive al confirmar (P0.6).

Sólo biblioteca estándar y lectura: se ejecuta en el arranque de cada
proceso del Motor. Sin configuración no cambia nada.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ARCHIVO = "raiz_publicada.json"
VARIABLE_DATOS = "ATLAS_DATA_DIR"


def ruta_configuracion() -> Path:
    from atlas_core.aislamiento_empresas import base_local
    return base_local() / ARCHIVO


def configuracion(ruta: Path | None = None) -> dict | None:
    try:
        with open(ruta or ruta_configuracion(), encoding="utf-8") as archivo:  # lectura: la guardia no la ve
            datos = json.load(archivo)
    except (OSError, ValueError):
        return None
    if not isinstance(datos, dict):
        return None
    trabajo, publicada = datos.get("raiz_trabajo"), datos.get("raiz_publicada")
    if not (isinstance(trabajo, str) and isinstance(publicada, str) and trabajo and publicada):
        return None
    return {"raiz_trabajo": trabajo, "raiz_publicada": publicada}


def misma_ruta(a, b) -> bool:
    try:
        return (os.path.normcase(os.path.abspath(os.fspath(a))).rstrip("\\/")
                == os.path.normcase(os.path.abspath(os.fspath(b))).rstrip("\\/"))
    except (TypeError, ValueError):
        return False


def es_raiz_de_trabajo(raiz) -> bool:
    c = configuracion()
    return bool(c) and misma_ruta(c["raiz_trabajo"], raiz)


def operativa(raiz):
    """La raíz sobre la que el Motor opera: la de trabajo si se recibe la publicada."""
    c = configuracion()
    if c and misma_ruta(c["raiz_publicada"], raiz):
        return type(raiz)(c["raiz_trabajo"]) if isinstance(raiz, Path) else c["raiz_trabajo"]
    return raiz


def redirigir_proceso() -> bool:
    """En el arranque: ``ATLAS_DATA_DIR`` y los argumentos que nombran la raíz
    publicada pasan a la de trabajo. Devuelve True si cambió algo."""
    c = configuracion()
    if not c:
        return False
    publicada, trabajo = c["raiz_publicada"], c["raiz_trabajo"]
    cambio = False
    if os.environ.get(VARIABLE_DATOS) and misma_ruta(os.environ[VARIABLE_DATOS], publicada):
        os.environ[VARIABLE_DATOS] = trabajo
        cambio = True
    for i, argumento in enumerate(sys.argv[1:], start=1):
        if not isinstance(argumento, str) or not argumento:
            continue
        if argumento.startswith("--") and "=" in argumento:
            opcion, valor = argumento.split("=", 1)
            if valor and misma_ruta(valor, publicada):
                sys.argv[i] = f"{opcion}={trabajo}"
                cambio = True
        elif not argumento.startswith("-") and misma_ruta(argumento, publicada):
            sys.argv[i] = trabajo
            cambio = True
    return cambio
