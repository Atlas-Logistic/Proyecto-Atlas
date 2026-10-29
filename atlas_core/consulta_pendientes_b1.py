"""Consulta de pendientes tecnicos registrada, sin inferirlos del estado del viaje."""
import json
import re
from pathlib import Path
from atlas_core.consultas_atlas import ConsultaAtlas, ResultadoConsultaAtlas, METRICA_COUNT_VIAJES, METRICA_LISTAR_VIAJES, normalizar_texto_atlas


def consultar_pendientes_tecnicos(pregunta, viajes, raiz):
    texto = normalizar_texto_atlas(pregunta).strip(' ?\u00bf!\u00a1')
    if not re.search(r'\bPENDIENTES? TECNICOS?\b', texto):
        return None
    contar = re.fullmatch(r'CUANTOS VIAJES (?:TIENEN|CON|TIENEN UN) PENDIENTES? TECNICOS?(?: HAY)?', texto)
    listar = re.fullmatch(r'(?:MUESTRAME|MUESTRA|LISTA|LISTAR|CUALES SON) (?:LOS )?VIAJES (?:CON|QUE TIENEN) PENDIENTES? TECNICOS?', texto)
    if not contar and not listar:
        # Otras formas ("cuantos pendientes tecnicos hay") siguen respondiendo
        # por el estado del viaje en el interprete general.
        return None
    try:
        if raiz is None:
            raise ValueError()
        ruta = Path(raiz) / 'operacion/actual/pendientes_tecnicos.json'
        datos = json.loads(ruta.read_text(encoding='utf-8-sig'))
        pendientes = datos['pendientes']
        if not isinstance(pendientes, list) or not all(isinstance(p, dict) for p in pendientes):
            raise ValueError()
        por_guia = {}
        por_id = {}
        for viaje in viajes:
            vid = str(viaje.get('viaje_id') or '').strip()
            if not vid or (vid in por_id and por_id[vid] != viaje):
                raise ValueError()
            por_id[vid] = viaje
            for guia in str(viaje.get('numeros_guia') or '').split('|'):
                if guia.strip():
                    por_guia.setdefault(guia.strip(), set()).add(vid)
        encontrados = set()
        sin_vinculo = 0
        for pendiente in pendientes:
            guia = str(pendiente.get('numero_guia') or '').strip()
            candidatos = por_guia.get(guia, set())
            if len(candidatos) != 1:
                sin_vinculo += 1
            else:
                encontrados.update(candidatos)
        soporte = tuple(v for vid, v in por_id.items() if vid in encontrados)
    except (OSError, ValueError, KeyError, TypeError):
        return ('limitacion', 'No puedo verificar los pendientes tecnicos: fuente o reporte no disponible o invalido.')
    consulta = ConsultaAtlas(metrica=METRICA_COUNT_VIAJES if contar else METRICA_LISTAR_VIAJES)
    resultado = ResultadoConsultaAtlas(consulta, len(soporte) if contar else soporte, 'viajes', len(soporte), soporte)
    mensaje = f'{len(soporte)} viajes con pendientes tecnicos registrados en el reporte vigente.'
    if sin_vinculo:
        mensaje += f' {sin_vinculo} pendientes no se pudieron asociar de forma unica a un viaje.'
    if not pendientes:
        mensaje += ' La fuente esta vacia; esto no demuestra que no existan otros problemas.'
    return ('resultado', resultado, mensaje)
