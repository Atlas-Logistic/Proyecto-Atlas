"""Consultas acotadas de la bandeja vigente y sus viajes, sin escrituras."""
import csv
import json
import re
import unicodedata

from atlas_core.almacenamiento_portable import leer_estado_operacion


def _normalizar(texto):
    texto = unicodedata.normalize('NFD', str(texto or '').upper())
    return ' '.join(''.join(c for c in texto if not unicodedata.combining(c)).strip(' ¿?¡!').split())


def _modo(texto):
    t = _normalizar(texto)
    # Formas completas: no absorber consultas con filtros u otras capacidades.
    if re.fullmatch(r'CUANTAS (?:REVISIONES|DECISIONES) PENDIENTES(?: HAY| TENEMOS)?', t):
        return 'revisiones'
    if re.fullmatch(r'CUANTOS VIAJES (?:TIENEN|REQUIEREN|CON|EN) REVISION(?: PENDIENTE)?(?: HAY| TENEMOS)?', t):
        return 'viajes'
    if re.fullmatch(r'(?:MUESTRAME|MUESTRA|LISTA|LISTAME|LISTAR|CUALES SON) (?:LOS )?VIAJES (?:CON|EN|QUE TIENEN|QUE REQUIEREN) REVISION(?: PENDIENTE)?', t):
        return 'lista'
    return None


def _ruta_viajes(ctx):
    # El reporte vigente lo publica el manifiesto de operación (misma fuente
    # que Desktop y Mobile); operacion/actual no contiene viajes.csv.
    estado = leer_estado_operacion(raiz=ctx.raiz) or {}
    reporte = str(estado.get('reporte_vigente') or '').strip()
    return ctx.raiz / reporte / 'viajes.csv' if reporte else ctx.actual / 'viajes.csv'


def consultar_revisiones(ctx, texto):
    modo = _modo(texto)
    if not modo:
        return None
    ruta = ctx.archivos['bandeja']
    try:
        with ruta.open(encoding='utf-8-sig') as f:
            contenido = json.load(f)
        decisiones = contenido.get('decisiones', contenido.get('decisions'))
        if not isinstance(decisiones, list):
            raise ValueError('bandeja inválida')
        pendientes = [d for d in decisiones if isinstance(d, dict) and str(d.get('estado', 'PENDIENTE')).upper() == 'PENDIENTE']
        if modo == 'revisiones':
            n = len(pendientes)
            return {'estado': 'RESULTADO_LECTURA', 'accion': 'REVISIONES_PENDIENTES',
                    'resultado': {'total_revisiones': n},
                    'mensaje': f"{n} {'revisión pendiente' if n == 1 else 'revisiones pendientes'}."}
        with _ruta_viajes(ctx).open(encoding='utf-8-sig', newline='') as f:
            lector = csv.DictReader(f, delimiter=';')
            if not {'viaje_id', 'numeros_guia', 'documentos'}.issubset(lector.fieldnames or []):
                raise ValueError('reporte inválido')
            viajes = list(lector)
    except (OSError, ValueError, TypeError, AttributeError):
        return {'estado': 'RECHAZADA', 'mensaje': 'No se pudo leer la bandeja de revisiones o el reporte de viajes.'}
    def valores(valor):
        return {v.strip() for v in str(valor or '').split('|') if v.strip()}
    # Una gu?a repetida en m?s de un viaje no identifica un viaje de forma
    # un?voca. El archivo, cuando existe, tiene prioridad sobre el folio.
    encontrados_indices = set()
    asociadas = set()
    for i, decision in enumerate(pendientes):
        documento = decision.get('documento') or {}
        if not isinstance(documento, dict):
            continue
        archivo = str(documento.get('archivo') or '').strip()
        guia = str(documento.get('numero_guia') or '').strip()
        candidatos = [j for j, viaje in enumerate(viajes) if
                      (archivo in valores(viaje.get('documentos')) if archivo else
                       bool(guia) and guia in valores(viaje.get('numeros_guia')))]
        if len(candidatos) == 1:
            encontrados_indices.add(candidatos[0])
            asociadas.add(i)
    encontrados = [v for j, v in enumerate(viajes) if j in encontrados_indices]
    n = len(encontrados)
    sin_viaje = len(pendientes) - len(asociadas)
    # Se separan viajes afectados, revisiones pendientes y total del reporte.
    mensaje = (f"{n} {'viaje' if n == 1 else 'viajes'} con revisiones pendientes "
               f"({len(pendientes)} {'revisión pendiente' if len(pendientes) == 1 else 'revisiones pendientes'}; "
               f"{len(viajes)} {'viaje' if len(viajes) == 1 else 'viajes'} en el reporte vigente).")
    if sin_viaje:
        mensaje += f' {sin_viaje} revisiones pendientes no se pudieron asociar a un viaje del reporte.'
    respuesta = {'estado': 'RESULTADO_LECTURA', 'accion': 'VIAJES_CON_REVISION',
                 'resultado': {'total_viajes': n, 'total_revisiones': len(pendientes),
                               'viajes_reporte': len(viajes), 'revisiones_sin_viaje': sin_viaje}, 'mensaje': mensaje}
    if modo == 'lista':
        respuesta['tablas'] = [{'tipo': 'viajes_revision', 'resumen': 'Viajes con revisiones pendientes',
            'columnas': ['Transporte', 'Guías', 'Fecha'], 'filas': [[v.get('numero_transporte', ''), v.get('numeros_guia', ''), v.get('fecha', '')] for v in encontrados]}]
    return respuesta
