"""Compatibilidad de RapidOCR con las etiquetas del ingreso manual.

No altera el proveedor de PULL ni corrige dígitos por nombre de archivo.
Conserva geometría y evidencia original; solo separa etiquetas conocidas.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import re
import unicodedata

from atlas_core.ocr_provider import RapidOCRProvider
from atlas_core.extractor import _normalizar_bloques_geometricos

_ETIQUETAS = (
    'GUIA DE DESPACHO', 'FECHA DE EMISION', 'FECHA SALIDA',
    'FECHA LLEGADA', 'HORA ENTRADA', 'HORA SALIDA',
)


def separar_etiqueta(texto: str) -> str:
    simple = ''.join(c for c in unicodedata.normalize('NFD', texto.upper()) if not unicodedata.combining(c))
    clave = re.sub(r'\s+', '', simple).strip(' :：')
    for etiqueta in _ETIQUETAS:
        if clave == etiqueta.replace(' ', ''):
            return etiqueta
    return texto


def fecha_completa(texto):
    if not re.fullmatch(r'\d{2}[-/]\d{2}[-/]\d{4}', texto.strip()):
        return None
    try:
        return datetime.strptime(texto.strip().replace('/', '-'), '%d-%m-%Y').strftime('%d-%m-%Y')
    except ValueError:
        return None


def localizar_fecha_emision(bloques):
    """Una única fecha a la derecha y en la misma fila de EMISIÓN.

    El buscador general admite candidatos de otras filas (por ejemplo RUT).
    Aquí solo se localiza una línea con sintaxis de fecha, incluso truncada.
    """
    items = _normalizar_bloques_geometricos(bloques)
    etiquetas = [i for i in items if i['simple'] == 'FECHA DE EMISION']
    candidatos = []
    for etiqueta in etiquetas:
        for i in items:
            h = max(i['h'], etiqueta['h'])
            if (re.fullmatch(r'\d{1,2}[-/]\d{1,2}[-/]\d{2,4}', i['texto'].strip())
                    and 0 <= i['x1'] - etiqueta['x2'] <= h * 12
                    and abs(i['cy'] - etiqueta['cy']) <= h * 0.7):
                candidatos.append(i)
    return candidatos[0] if len(etiquetas) == 1 and len(candidatos) == 1 else None


def consensuar_fecha(lecturas):
    votos = {}
    for lectura in lecturas:
        valor = fecha_completa(str(lectura.get('texto', '')))
        confianza = lectura.get('confianza')
        if valor and isinstance(confianza, (int, float)) and confianza >= 0.70:
            votos.setdefault(valor, set()).add(lectura.get('variante'))
    if len(votos) == 1:
        valor, variantes = next(iter(votos.items()))
        if len(variantes - {None}) >= 2:
            return valor
    return None


class RapidOCRManualProvider(RapidOCRProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._manual_ruta = None
        self._manual_bloques = []
        self.evidencia_manual = []

    def _bloques_adaptados(self, ruta_imagen):
        if self._manual_ruta == str(ruta_imagen):
            return list(self._manual_bloques)
        crudos = super()._bloques_adaptados(ruta_imagen)
        bloques = [replace(b, texto=separar_etiqueta(b.texto)) for b in crudos]
        fecha = localizar_fecha_emision([b.a_bloque_atlas() for b in bloques])
        if fecha and not fecha_completa(fecha['texto']):
            caja = [fecha[k] for k in ('x1','y1','x2','y2')]
            focal = self._comando(op='focal_linea', ruta=str(ruta_imagen), caja=caja)
            valor = consensuar_fecha(focal['lecturas'])
            self.evidencia_manual.append({'campo':'fecha_emision', 'original':fecha['texto'], 'valor':valor, **focal})
            if valor is None:
                raise ValueError('Fecha de emisión truncada sin consenso focal; requiere una captura más legible.')
            bloques = [replace(b, texto=valor) if b.texto == fecha['texto'] and
                       min(p[0] for p in b.bounding_box) == fecha['x1'] and
                       min(p[1] for p in b.bounding_box) == fecha['y1'] else b for b in bloques]
        self._manual_ruta, self._manual_bloques = str(ruta_imagen), bloques
        return list(bloques)

    def cerrar(self):
        super().cerrar()
        self._manual_ruta, self._manual_bloques = None, []
