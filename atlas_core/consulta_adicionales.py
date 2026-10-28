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


def _consulta(pregunta):
    texto = _normalizar(pregunta).strip().strip('¿? ')
    if not re.search(r'\bADICIONAL(?:ES)?\b', texto):
        return None
    patron = (r'(?P<accion>CUANTOS\s+VIAJES(?:\s+(?:TIENEN|HAY))?|'
              r'(?:LISTA|LISTAR|ENUMERA|ENUMERAR|MUESTRAME|MOSTRAR|CUALES SON)\s+(?:LOS\s+)?VIAJES)'
              r'\s+(?:CON|TIENEN|TIENE|QUE TIENEN)\s+(?:UN\s+)?ADICIONAL(?:ES)?\s+'
              r'(?P<op>DE|IGUAL A|SUPERIOR A|MAYOR A|MAYOR QUE|MAS DE|INFERIOR A|MENOR A|MENOR QUE|'
              r'AL MENOS|COMO MINIMO|HASTA|COMO MAXIMO)\s*(?P<monto>' + _MONTO + r')')
    # "cuantos viajes tienen adicional" already consumed TIENEN above.
    texto = re.sub(r'^(CUANTOS\s+VIAJES)\s+TIENEN\s+(?:UN\s+)?ADICIONAL', r'\1 CON ADICIONAL', texto)
    m = re.fullmatch(patron, texto)
    if not m:
        return False
    valor = _monto(m.group('monto'))
    if valor is None:
        return False
    return (m.group('accion').startswith('CUANTOS'), m.group('op'), valor)


def consultar_adicionales(pregunta, viajes, raiz_atlas):
    """None si no menciona adicionales; de otro modo resultado o limitacion."""
    c = _consulta(pregunta)
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
    montos = {}
    for evento in eventos:
        if evento.get('estado') != 'ACTIVO' or evento.get('tipo_evento') != 'OBSERVACION_OPERACIONAL':
            continue
        nota = _normalizar(evento.get('nota') or '')
        if not re.search(r'\bADICIONAL(?:ES)?\b', nota):
            continue
        # No convertir importes por guia, negados, o varios conceptos en un monto de viaje.
        if evento.get('naturaleza') != 'MARCA_VIAJE' or re.search(r'\b(?:POR|CADA)\s+(?:GUIA|DOCUMENTO|FOTO)\b|\b(?:SIN|NO(?:\s+\w+){0,4})\s+ADICIONAL', nota):
            return ('limitacion', 'Hay observaciones de adicionales que no identifican con certeza un monto por viaje; no puedo dar un conteo fiable.')
        hallados = re.findall(r'\bADICIONAL\s+(?:DE|POR|ES DE)\s*(' + _MONTO + r')', nota)
        if len(hallados) != 1 or len(re.findall(r'\bADICIONAL(?:ES)?\b', nota)) != 1:
            return ('limitacion', 'Hay observaciones de adicionales con importes ambiguos; no puedo dar un conteo fiable.')
        resto = nota.replace(hallados[0], '', 1)
        if re.search(r'\d', resto):
            return ('limitacion', 'Hay observaciones de adicionales con otras cifras que requieren revision; no puedo dar un conteo fiable.')
        importe = _monto(hallados[0])
        vid = str(evento.get('viaje_id') or '').strip()
        transporte = str(evento.get('numero_transporte') or '').strip()
        if not vid:
            candidatos = por_transporte.get(transporte, [])
            vid = candidatos[0] if len(candidatos) == 1 else ''
        if importe is None or vid not in por_id or transporte != str(por_id[vid].get('numero_transporte') or '').strip():
            return ('limitacion', 'Hay observaciones de adicionales sin un vinculo unico y verificable con el viaje; no puedo dar un conteo fiable.')
        montos.setdefault(vid, set()).add(importe)
    cuenta, op, valor = c
    comparadores = {'DE':lambda x:x==valor, 'IGUAL A':lambda x:x==valor, 'SUPERIOR A':lambda x:x>valor,
                    'MAYOR A':lambda x:x>valor, 'MAYOR QUE':lambda x:x>valor, 'MAS DE':lambda x:x>valor,
                    'INFERIOR A':lambda x:x<valor, 'MENOR A':lambda x:x<valor, 'MENOR QUE':lambda x:x<valor,
                    'AL MENOS':lambda x:x>=valor, 'COMO MINIMO':lambda x:x>=valor,
                    'HASTA':lambda x:x<=valor, 'COMO MAXIMO':lambda x:x<=valor}
    soporte = tuple(por_id[vid] for vid, valores in montos.items() if any(comparadores[op](n) for n in valores))
    consulta = ConsultaAtlas(metrica=METRICA_COUNT_VIAJES if cuenta else METRICA_LISTAR_VIAJES,
                             filtros={'adicional': f'{op} {valor}'})
    resultado = ResultadoConsultaAtlas(consulta, len(soporte) if cuenta else soporte, 'viajes', len(soporte), soporte)
    return ('resultado', resultado, f'{len(soporte)} viaje(s) con adicional {op.lower()} ${valor:,}.'.replace(',', '.'))
