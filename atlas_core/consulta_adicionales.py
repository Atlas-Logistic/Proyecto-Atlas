"""Consultas de adicionales monetarios basadas en observaciones de viaje."""
import json
import re
import unicodedata
from pathlib import Path

from atlas_core.consultas_atlas import ConsultaAtlas, ResultadoConsultaAtlas, METRICA_COUNT_VIAJES, METRICA_LISTAR_VIAJES


def _normalizar(texto):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(texto).upper()) if not unicodedata.combining(c))


_MONTO = r'\$?\s*(?:\d{1,3}(?:[.]\d{3})+|\d+)(?:\s*(?:MIL|LUCAS|PESOS))?'

def _monto(texto):
    t = re.sub(r'\s+', ' ', texto.strip())
    m = re.fullmatch(r'\$?\s*(\d{1,3}(?:[.]\d{3})+|\d+)(?:\s*(MIL|LUCAS|PESOS))?', t)
    if not m:
        return None
    valor = int(m.group(1).replace('.', ''))
    if m.group(2) in ('MIL', 'LUCAS'):
        valor *= 1000
    return valor


# Linea canonica que B1 escribe con motivo libre: "ESTE VIAJE TIENE ADICIONAL DE
# $15.000 POR SEGUNDA VUELTA DEL VIERNES 23/10/2026". Las cifras del motivo
# (fechas) no son importes; B1 nunca guarda un motivo con otro importe, otro
# adicional o un monto por guia, y si una nota los trae no se neutraliza.
_LINEA_CANONICA_CON_MOTIVO = re.compile(
    r'(ESTE VIAJE TIENE ADICIONAL DE \$\d{1,3}(?:[.]\d{3})*) (?P<motivo>(?:POR|DEBIDO A|CORRESPONDIENTE A) .+)')


def _sin_motivo_canonico(nota):
    """Nota normalizada sin el motivo de sus lineas canonicas de adicional."""
    lineas = []
    for linea in nota.split('\n'):
        m = _LINEA_CANONICA_CON_MOTIVO.fullmatch(linea.strip())
        motivo = m.group('motivo') if m else ''
        if m and not re.search(r'\$|\b(?:MIL|LUCAS|PESOS|ADICIONAL(?:ES)?)\b|\b(?:POR|CADA)\s+(?:GUIA|DOCUMENTO|FOTO)\b',
                               motivo):
            linea = m.group(1)
        lineas.append(linea)
    return '\n'.join(lineas)


def _consulta(pregunta):
    texto = _normalizar(pregunta).strip().strip('¿? ')
    if not re.search(r'\bADICIONAL(?:ES)?\b', texto):
        return None
    texto = re.sub(r'^(CUANTOS\s+VIAJES)\s+TIENEN\s+(?:UN\s+)?ADICIONAL', r'\1 CON ADICIONAL', texto)
    patron = (r'(?P<accion>CUANTOS\s+VIAJES(?:\s+HAY)?|'
              r'(?:LISTA|LISTAR|ENUMERA|ENUMERAR|MUESTRAME|MOSTRAR|CUALES SON)\s+(?:LOS\s+)?VIAJES)'
              r'\s+(?:CON|TIENEN|TIENE|QUE TIENEN)\s+(?:UN\s+)?ADICIONAL(?:ES)?'
              r'(?:\s+(?P<op>DE|IGUAL A|SUPERIOR A|MAYOR A|MAYOR QUE|MAS DE|INFERIOR A|MENOR A|MENOR QUE|'
              r'AL MENOS|COMO MINIMO|HASTA|COMO MAXIMO)\s*(?P<montos>' + _MONTO + r'(?:\s+O\s+' + _MONTO + r')*))?')
    m = re.fullmatch(patron, texto)
    if not m:
        return False
    op = m.group('op')
    valores = tuple(_monto(x) for x in re.split(r'\s+O\s+', m.group('montos') or '') if x)
    if any(v is None for v in valores) or (len(valores) > 1 and op not in ('DE', 'IGUAL A')):
        return False
    return m.group('accion').startswith('CUANTOS'), op, valores


def consultar_adicionales(pregunta, viajes, raiz_atlas):
    """None si no menciona adicionales; de otro modo resultado o limitacion."""
    c = _consulta(pregunta)
    filtro_extra = None
    filtros_base = {}
    if c is False:
        texto = _normalizar(pregunta).strip().strip('\u00bf? ')
        combinado = re.fullmatch(
            r'(?P<base>(?:CUANTOS VIAJES|(?:MUESTRAME|MUESTRA|LISTA|LISTAR) (?:LOS )?VIAJES)'
            r'(?: DE [A-Z\u00d1]+(?: [A-Z\u00d1]+){0,3})?'
            r'(?: EL \d{1,2}[-/]\d{1,2}[-/]\d{4})?'
            r'(?: SIN (?:MATERIAL|PESO|DIRECCION|CLIENTE|CHOFER))?)'
            r' (?P<adicional>CON (?:UN )?ADICIONAL(?:ES)?(?: (?:DE|IGUAL A) ' + _MONTO + r'(?:\s+O\s+' + _MONTO + r')*)?)', texto)
        if combinado:
            prefijo = 'CUANTOS VIAJES ' if texto.startswith('CUANTOS VIAJES') else 'LISTA LOS VIAJES '
            c = _consulta(prefijo + combinado.group('adicional'))
            from atlas_core.interpretador_consultas import construir_catalogos_consulta, interpretar_consulta_determinista
            from atlas_core.consultas_atlas import ejecutar_consulta_atlas
            consulta_base, avisos = interpretar_consulta_determinista(combinado.group('base'), catalogos=construir_catalogos_consulta(viajes))
            if consulta_base is None or avisos or consulta_base.agrupacion:
                return ('limitacion', 'No pude resolver los filtros adicionales de la consulta.')
            from atlas_core.consultas_atlas import _COLUMNA_PRESENCIA
            if any(_COLUMNA_PRESENCIA.get(c.strip()) not in v for c in consulta_base.filtros.get('ausente', '').split(',') if c.strip() for v in viajes):
                return ('limitacion', 'El reporte no contiene el campo solicitado; no puedo filtrar sus ausencias.')
            filtros_base = dict(consulta_base.filtros)
            filtro_extra = set(str(v.get('viaje_id') or '') for v in ejecutar_consulta_atlas(consulta_base, viajes).viajes_soporte)
    if c is None:
        return None
    if c is False:
        return ('limitacion', 'No pude interpretar todos los filtros de la consulta de adicionales. Indica un monto y si quieres contar o listar viajes.')
    if raiz_atlas is None or not (Path(raiz_atlas) / 'operacion/actual/eventos_operacionales.json').is_file():
        return ('limitacion', 'No puedo verificar los adicionales: no esta disponible el registro de observaciones operacionales.')
    try:
        documento = json.loads((Path(raiz_atlas) / 'operacion/actual/eventos_operacionales.json').read_text(encoding='utf-8-sig'))
        if not isinstance(documento, dict) or documento.get('schema_version') != 1 or not isinstance(documento.get('eventos'), list):
            raise ValueError('registro incompatible')
        eventos = documento['eventos']
        if not all(isinstance(e, dict) for e in eventos):
            raise ValueError('evento invalido')
    except (OSError, ValueError, KeyError, TypeError):
        return ('limitacion', 'No puedo verificar los adicionales: el registro de observaciones no esta disponible o es ilegible.')
    por_id = {}
    por_transporte = {}
    for v in viajes:
        vid = str(v.get('viaje_id') or '').strip()
        t = str(v.get('numero_transporte') or '').strip()
        if not vid:
            return ('limitacion', 'No puedo contar viajes unicos: el reporte tiene identidades ausentes.')
        if vid in por_id:
            if por_id[vid] != v:
                return ('limitacion', 'No puedo contar viajes unicos: el reporte tiene identidades contradictorias.')
            continue
        por_id[vid] = v
        por_transporte.setdefault(t, []).append(vid)
    cuenta, op, valores_consulta = c
    montos = {}
    for evento in eventos:
        if evento.get('estado') != 'ACTIVO' or evento.get('tipo_evento') != 'OBSERVACION_OPERACIONAL':
            continue
        nota = _sin_motivo_canonico(_normalizar(evento.get('nota') or ''))
        if not re.search(r'\bADICIONAL(?:ES)?\b', nota):
            continue
        # No convertir importes por guia, negados, o varios conceptos en un monto de viaje.
        if evento.get('naturaleza') != 'MARCA_VIAJE' or re.search(r'\b(?:POR|CADA)\s+(?:GUIA|DOCUMENTO|FOTO)\b|\b(?:SIN|NO(?:\s+\w+){0,4})\s+ADICIONAL', nota):
            return ('limitacion', 'Hay observaciones de adicionales que no identifican con certeza un monto por viaje; no puedo dar un conteo fiable.')
        hallados = re.findall(r'\bADICIONAL\s+(?:DE|POR|ES DE)\s*(' + _MONTO + r')', nota)
        if not hallados and not valores_consulta and len(re.findall(r'\bADICIONAL(?:ES)?\b', nota)) == 1 and not re.search(r'\d', nota):
            hallados = []
        elif len(hallados) != 1 or len(re.findall(r'\bADICIONAL(?:ES)?\b', nota)) != 1:
            return ('limitacion', 'Hay observaciones de adicionales con importes ambiguos; no puedo dar un conteo fiable.')
        resto = nota.replace(hallados[0], '', 1) if hallados else nota
        if re.search(r'\d', resto):
            return ('limitacion', 'Hay observaciones de adicionales con otras cifras que requieren revision; no puedo dar un conteo fiable.')
        importe = _monto(hallados[0]) if hallados else None
        vid = str(evento.get('viaje_id') or '').strip()
        transporte = str(evento.get('numero_transporte') or '').strip()
        if not vid:
            candidatos = por_transporte.get(transporte, [])
            vid = candidatos[0] if len(candidatos) == 1 else ''
        if (importe is None and valores_consulta) or vid not in por_id or transporte != str(por_id[vid].get('numero_transporte') or '').strip():
            return ('limitacion', 'Hay observaciones de adicionales sin un vinculo unico y verificable con el viaje; no puedo dar un conteo fiable.')
        montos.setdefault(vid, set()).add(importe)
    def coincide(importe):
        if not valores_consulta:
            return True
        valor = valores_consulta[0]
        if importe is None:
            return False
        if op in ('DE', 'IGUAL A'):
            return importe in valores_consulta
        return {'SUPERIOR A': importe > valor, 'MAYOR A': importe > valor, 'MAYOR QUE': importe > valor,
                'MAS DE': importe > valor, 'INFERIOR A': importe < valor, 'MENOR A': importe < valor,
                'MENOR QUE': importe < valor, 'AL MENOS': importe >= valor, 'COMO MINIMO': importe >= valor,
                'HASTA': importe <= valor, 'COMO MAXIMO': importe <= valor}[op]
    soporte = tuple(por_id[vid] for vid, importes in montos.items() if any(coincide(n) for n in importes) and (filtro_extra is None or vid in filtro_extra))
    descripcion = ' o '.join(f'${valor:,}'.replace(',', '.') for valor in valores_consulta)
    etiqueta = f'{op.lower()} {descripcion}' if op else ''
    consulta = ConsultaAtlas(metrica=METRICA_COUNT_VIAJES if cuenta else METRICA_LISTAR_VIAJES,
                             filtros={**filtros_base, 'adicional': etiqueta or 'CUALQUIERA'})
    resultado = ResultadoConsultaAtlas(consulta, len(soporte) if cuenta else soporte, 'viajes', len(soporte), soporte)
    mensaje = f'{len(soporte)} viaje(s) con adicional {etiqueta}.'.replace(' .', '.')
    if filtro_extra is not None:
        mensaje += ' Se aplicaron los filtros indicados de chofer, fecha o campos.'
    if not eventos:
        mensaje += ' El registro de observaciones esta vacio; no demuestra que no existan adicionales fuera de esta fuente.'
    return ('resultado', resultado, mensaje)
