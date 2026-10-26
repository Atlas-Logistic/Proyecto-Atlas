"""Corrobora obra y dirección juntas, sin OCR, red ni altas de catálogo.

Un nombre parecido nunca basta. Se exige cliente confirmado por nombre y
RUT, obra documental compatible y dirección con número compatible; todo
debe converger en una única relación confirmada y activa del catálogo.
"""
from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from atlas_core.catalogo_clientes import CatalogoClientes, normalizar_rut_cliente
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos
from atlas_core.catalogo_destinos import direccion_confirmada_coincide


def _clave(texto):
    texto = unicodedata.normalize('NFKD', str(texto or '')).encode('ascii', 'ignore').decode().upper()
    return re.sub(r'[^A-Z0-9]', '', texto)


def _nombre_compatible(documental, canonico):
    a, b = _clave(documental), _clave(canonico)
    return bool(a and b and (a == b or (min(len(a), len(b)) >= 15 and SequenceMatcher(None, a, b).ratio() >= .88)))


def _rut(texto):
    try:
        return normalizar_rut_cliente(texto)
    except ValueError:
        return ''


def _partes_direccion(texto):
    # Letras OCR sólo dentro de un número ya iniciado por dígito.
    texto = str(texto or '').upper()
    if re.search(r'\d{7,8}\s*-\s*[\dK]', texto):
        return None
    m = re.search(r'(?<![\dA-Z])(\d[\dIO]*)(?![\dA-Z])', texto)
    if not m:
        # OCR sin espacios: CAMINO...1080OSTIGO. Se toma únicamente el
        # tramo numérico; O final puede ser el cero perdido por OCR.
        m = re.search(r'\d[\dIO]*', texto)
    if not m:
        return None
    numero = m.group().translate(str.maketrans({'I': '1', 'O': '0'}))
    calle = _clave(texto[:m.start()])
    return (calle, numero) if len(calle) >= 7 else None


def _direccion_compatible(documental, destino, *, degradada=False, comunas_documentales=()):
    from atlas_core.territorio_chile import ESTADO_COMUNA_EXACTA, normalizar_comuna
    # El sufijo territorial explícito no puede desaparecer por una
    # coincidencia de calle. Las excepciones impresas deben estar ya
    # documentadas en una confirmación humana del catálogo.
    sufijo = re.split(r'\d[\dIO]*', str(documental).upper())[-1].strip().split()
    for n in range(min(4, len(sufijo)), 0, -1):
        comuna = normalizar_comuna(' '.join(sufijo[-n:]))
        if comuna.estado == ESTADO_COMUNA_EXACTA:
            if _clave(comuna.comuna) not in {_clave(destino.comuna), *map(_clave, comunas_documentales)}:
                return False
            break
    calle = destino.direccion.split(',', 1)[0]
    a, b = _partes_direccion(documental), _partes_direccion(calle)
    if not a or not b or a[1] != b[1]:
        return False
    if direccion_confirmada_coincide(calle, documental, comuna_confirmada=destino.comuna):
        return True
    corregido = re.sub(r'\d[\dIO]*', lambda m: m.group().translate(str.maketrans({'I': '1', 'O': '0'})), str(documental).upper())
    if corregido != str(documental).upper() and direccion_confirmada_coincide(
        calle, corregido, comuna_confirmada=destino.comuna,
    ):
        return True
    # La tolerancia amplia sólo sirve para texto degradado y requiere
    # además la obra en otra sección y el cliente corroborado por RUT.
    return bool(degradada and SequenceMatcher(None, a[0], b[0]).ratio() >= .70)


def resolver_destino_confirmado(fila, *, carpeta_catalogos, lineas=(), filas=(), _cache=None):
    carpeta = Path(carpeta_catalogos)
    cache = {} if _cache is None else _cache
    if 'clientes' not in cache:
        cache['clientes'] = CatalogoClientes(carpeta / 'clientes.json').listar()
    clientes = [c for c in cache['clientes']
                if c.estado_calidad == 'CONFIRMADO' and c.estado_vigencia == 'ACTIVO'
                and _clave(fila.get('cliente')) in {_clave(c.razon_social), *map(_clave, c.aliases)}
                and _rut(fila.get('rut_cliente')) == _rut(c.rut)
                and c.rut]
    if len(clientes) != 1:
        return None
    cliente = clientes[0]
    if 'catalogo' not in cache:
        cache['catalogo'] = CatalogoObrasDestinos(ruta=carpeta / 'obras_destinos.json',
                                                ruta_clientes=carpeta / 'clientes.json',
                                                ruta_destinos=carpeta / 'destinos_maestros.json')
        cache['obras'] = cache['catalogo'].listar_obras()
    catalogo = cache['catalogo']
    raw = str(fila.get('despachar_a_crudo', ''))
    obra_raw = str(fila.get('obra_destino', ''))
    ausente = _clave(obra_raw) in {'', 'NOENCONTRADO', 'NODETERMINADO'}
    # Dos identificadores propios legibles y un número pegado a palabras,
    # con confusión I/O interna, permiten corroborar una calle degradada.
    # Un nombre o un número aislado nunca habilitan esta tolerancia.
    candidatos = {}
    for obra in cache['obras']:
        if obra.estado != 'CONFIRMADA' or obra.estado_vigencia != 'ACTIVO' or obra.cliente_id != cliente.cliente_id:
            continue
        nombres = (obra.nombre_canonico, *obra.aliases_documentales)
        if not ausente and not any(_nombre_compatible(obra_raw, n) for n in nombres):
            continue
        if ausente and not any(_nombre_compatible(l, n) for l in lineas for n in nombres):
            continue
        if obra.obra_id not in cache:
            cache[obra.obra_id] = catalogo.listar_destinos_confirmados_para_obra(nombre_obra=obra.nombre_canonico)
        for destino in cache[obra.obra_id]:
            comunas_documentales = [e.campos_observados.get('comuna_documental', '')
                for e in getattr(obra, 'evidencias', ()) if e.resultado == 'SOPORTA'
                and _clave(e.campos_observados.get('comuna_operacional_confirmada')) == _clave(destino.comuna)]
            def compatible(texto, **kwargs):
                return _direccion_compatible(texto, destino, comunas_documentales=comunas_documentales, **kwargs)
            testigos = [fila, *filas]
            degradada = bool(ausente and re.search(r'[A-Z]{4}\d{3,}[IO][A-Z]{3}', raw.upper()) and any(
                _clave(t.get('cliente')) == _clave(cliente.razon_social)
                and _rut(t.get('rut_cliente')) == _rut(cliente.rut)
                and _clave(t.get('obra_destino')) == _clave(obra.nombre_canonico)
                and compatible(t.get('despachar_a_crudo', ''))
                and all(str(t.get(c, '')).isdigit() and any(re.search(r'(?<!\d)' + re.escape(str(t[c])) + r'(?!\d)', l) for l in lineas)
                        for c in ('codigo_cliente', 'cod_destinatario'))
                for t in testigos))
            # Una dirección propia válida distinta tiene precedencia sobre
            # cualquier coincidencia de otra sección (domicilio de factura).
            partes = _partes_direccion(raw)
            directo = compatible(raw)
            if partes and not directo:
                from atlas_core.rutas.destino_entrega import texto_destino_degradado
                if not texto_destino_degradado(raw) and not degradada:
                    continue
            fuentes = [raw, *lineas]
            compatibles = [l for l in fuentes if compatible(l, degradada=degradada)]
            if not compatibles:
                continue
            candidatos[(obra.obra_id, destino.destino_id)] = (obra, destino, compatibles[0])
    return next(iter(candidatos.values())) if len(candidatos) == 1 else None


def revalidar_destinos_confirmados_convergentes(*, ruta_dataset, carpeta_catalogos,
                                              guias_objetivo=None, directorio_trazas=None):
    """Sólo modifica campos de obra/destino y su evidencia; respeta ledger y alcance."""
    from atlas_core.almacenamiento_portable import bloqueo_sesion
    from atlas_core.alcance_revalidacion import guias_en_alcance
    from atlas_core.revalidacion_documental import (
        _leer_filas, _escribir_filas_completas, _hay_decision_humana_para_campo,
        _trazas_atlas_ia, _valor_destino_rechazado_por_b1,
    )
    from atlas_core.trazabilidad_ocr import ruta_traza_ocr
    ruta = Path(ruta_dataset)
    alcance = guias_en_alcance(ruta)
    if alcance is not None:
        guias_objetivo = alcance if guias_objetivo is None else alcance & set(guias_objetivo)
    try:
        aplicaciones = json.loads((ruta.parent / 'decisiones_aplicadas.json').read_text(encoding='utf-8')).get('aplicaciones', [])
    except FileNotFoundError:
        aplicaciones = []
    except (OSError, ValueError):
        return {'guias_actualizadas': [], 'abstencion': 'LEDGER_ILEGIBLE'}
    actualizadas = []
    cache = {}
    from atlas_core.investigacion_documental import archivos_en_investigacion
    cuarentena = archivos_en_investigacion(Path(carpeta_catalogos).parent)
    with bloqueo_sesion(ruta.parent, 'revalidacion_dataset'):
        filas = _leer_filas(ruta)
        testigos = [f for f in _leer_filas(ruta, completas=True) if f.get('archivo') not in cuarentena]
        for fila in filas:
            guia = str(fila.get('numero_guia', ''))
            if guias_objetivo is not None and guia not in guias_objetivo:
                continue
            if fila.get('estado_ruta') == 'RUTA_CALCULADA':
                continue
            if fila.get('archivo') in cuarentena:
                continue
            if any(_valor_destino_rechazado_por_b1(t) for t in _trazas_atlas_ia(fila)):
                continue
            if any(_hay_decision_humana_para_campo(aplicaciones, fila=fila, campo=c)
                   for c in ('obra_destino', 'despachar_a_crudo')):
                continue
            lineas = []
            if directorio_trazas is not None:
                traza_ruta = ruta_traza_ocr(Path(directorio_trazas), fila.get('archivo', ''))
                try:
                    traza = json.loads(traza_ruta.read_text(encoding='utf-8'))
                    if traza.get('imagen', {}).get('referencia') == fila.get('archivo'):
                        lineas = traza.get('ocr', {}).get('lineas', [])
                        if not isinstance(lineas, list) or not all(isinstance(l, str) for l in lineas):
                            lineas = []
                except (OSError, ValueError):
                    pass
            try:
                resuelto = resolver_destino_confirmado(fila, carpeta_catalogos=carpeta_catalogos, lineas=lineas, filas=testigos, _cache=cache)
            except (OSError, ValueError):
                continue
            if resuelto is None:
                continue
            obra, destino, documental = resuelto
            try:
                metricas = json.loads(fila.get('metricas_procesamiento_json') or '{}')
            except ValueError:
                continue
            if not isinstance(metricas, dict):
                continue
            previa = metricas.get('convergencia_destino_confirmado')
            if isinstance(previa, dict) and previa.get('destino_id') == destino.destino_id:
                continue
            metricas['convergencia_destino_confirmado'] = {
                'version': 1, 'obra_id': obra.obra_id, 'destino_id': destino.destino_id,
                'obra_documental_original': fila.get('obra_destino', ''),
                'direccion_documental_original': fila.get('despachar_a_crudo', ''),
                'evidencia_direccion': documental, 'fuente': 'CLIENTE_RUT_OBRA_DIRECCION_CATALOGO_CONFIRMADO',
            }
            fila['obra_destino'] = obra.nombre_canonico
            fila['despachar_a_crudo'] = destino.direccion
            fila['direccion_entrega'] = destino.direccion
            fila['localidad_entrega'] = destino.comuna
            fila['region_entrega'] = destino.region
            motivos = [m.strip() for m in fila.get('motivos_revision_documento', '').split('|') if m.strip()]
            motivos = [m for m in motivos if m not in {
                'OBRA_DESTINO_SIN_CORROBORAR', 'OBRA_DESTINO_AUSENTE',
                'DESTINO_CONTAMINADO_POR_OTRA_SECCION', 'DESTINO_FRAGMENTO_TRUNCADO',
            }]
            fila['motivos_revision_documento'] = ' | '.join(motivos)
            # Identidad resuelta, pero no se declara una ruta calculada.
            # La cola técnica y los proveedores habituales conservan ese trabajo.
            if fila.get('motivo_ruta') in {'DESTINO_CONTRADICE_CATALOGO_CONFIRMADO',
                                          'GEOCODIFICACION_DIRECCION_NO_ENCONTRADA',
                                          'GEOCODIFICACION_SIN_CREDENCIAL'}:
                fila['motivo_ruta'] = ''
                fila['estado_ruta'] = ''
            from atlas_core.procesamiento_masivo import _reflejar_estados_fila
            _reflejar_estados_fila(fila, motivos)
            fila['metricas_procesamiento_json'] = json.dumps(metricas, ensure_ascii=False, sort_keys=True)
            actualizadas.append(guia)
        if actualizadas:
            _escribir_filas_completas(ruta, filas)
    return {'guias_actualizadas': actualizadas}


def retirar_decisiones_destino_convergente(decisiones, *, ruta_dataset, carpeta_catalogos):
    """Revalida la evidencia contra catálogos vivos antes de retirar preguntas.

    Nunca afecta decisiones de otros dominios ni una corrección manual.
    """
    from atlas_core.revalidacion_documental import _leer_filas
    filas = {f.get('numero_guia'): f for f in _leer_filas(Path(ruta_dataset))}
    confirmadas = set()
    cache = {}
    for guia, fila in filas.items():
        try:
            evidencia = json.loads(fila.get('metricas_procesamiento_json') or '{}').get('convergencia_destino_confirmado', {})
            if not evidencia:
                continue
            resuelto = resolver_destino_confirmado(fila, carpeta_catalogos=carpeta_catalogos, _cache=cache)
            if resuelto and (resuelto[0].obra_id, resuelto[1].destino_id) == (evidencia.get('obra_id'), evidencia.get('destino_id')):
                confirmadas.add(guia)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return [d for d in decisiones if not (
        d.get('tipo') in {'OBRA_DESCONOCIDA', 'DESTINO_NO_RESUELTO'}
        and (d.get('documento') or {}).get('numero_guia') in confirmadas
        and not any(e.get('origen_pregunta') == 'CORRECCION_MANUAL_LOGISTICA' for e in d.get('evidencias', []))
    )]
