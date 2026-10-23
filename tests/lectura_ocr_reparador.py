"""Lecturas OCR sintéticas para dobles de `procesar_archivo` del reparador.

El reparador sólo promueve horas, peso, patentes, RUT y transporte cuando la
lectura de la relectura los muestra junto a la etiqueta de su campo (ver
`_valor_con_procedencia`). `procesar_archivo` real persiste esa lectura en
`directorio_trazas_ocr`; estos dobles hacen lo mismo con una guía AZA mínima
coherente con los valores que devuelven.
"""
from __future__ import annotations

from atlas_core.ocr import BloqueOCR
from atlas_core.trazabilidad_ocr import persistir_traza_ocr

_ALTO = 10
_X_ETIQUETA = 0
_X_VALOR = 120


def _bloque(texto: str, x: float, y: float, ancho: float = 100) -> BloqueOCR:
    return BloqueOCR(texto, ((x, y), (x + ancho, y), (x + ancho, y + _ALTO), (x, y + _ALTO)), 0.95)


def _kilos(valor: str) -> str:
    return f"{int(valor):,}".replace(",", ".") + ",00"


def bloques_guia(valores: dict) -> list[BloqueOCR]:
    """Cada campo literal en su fila, con la etiqueta AZA a la izquierda."""
    filas: list[tuple[str, str]] = []
    if valores.get("numero_transporte"):
        filas.append(("Nro. TRANSPORTE", str(valores["numero_transporte"])))
    if valores.get("rut_cliente"):
        filas.append(("R.U.T.", str(valores["rut_cliente"])))
    if valores.get("hora_entrada_aza"):
        filas.append(("HORA ENTRADA", f"{valores['hora_entrada_aza']}:00"))
    if valores.get("hora_salida_aza"):
        filas.append(("HORA SALIDA", f"{valores['hora_salida_aza']}:00"))
    if str(valores.get("peso_kg", "")).isdigit():
        filas.append(("PESO KG.", _kilos(str(valores["peso_kg"]))))
    if valores.get("rut_chofer"):
        filas.append(("RUT CHOFER", str(valores["rut_chofer"])))
    tracto, rampla = valores.get("patente_tracto"), valores.get("patente_rampla")
    if tracto or rampla:
        filas.append(("PATENTE", f"{tracto or ''} CARRO:{rampla or ''}".strip()))
    return [
        bloque
        for i, (etiqueta, valor) in enumerate(filas)
        for bloque in (_bloque(etiqueta, _X_ETIQUETA, 40 * i), _bloque(valor, _X_VALOR, 40 * i))
    ]


def persistir_lectura(kw: dict, valores: dict, bloques: list[BloqueOCR] | None = None) -> None:
    """Persiste la lectura donde el reparador la pide (si la pide)."""
    directorio = kw.get("directorio_trazas_ocr")
    if directorio is None:
        return
    bloques = bloques_guia(valores) if bloques is None else bloques
    persistir_traza_ocr(
        directorio=directorio, referencia_imagen=kw["referencia_imagen_traza"],
        textos=[b.texto for b in bloques],
        bloques=bloques, proveedor=kw.get("proveedor"),
    )


def con_lectura(doble):
    """Envuelve un doble de `procesar_archivo`: devuelve lo mismo y deja la
    lectura OCR coherente con esos valores."""
    def procesar(*args, **kw):
        valores = doble(*args, **kw)
        persistir_lectura(kw, dict(valores or {}))
        return valores
    return procesar
