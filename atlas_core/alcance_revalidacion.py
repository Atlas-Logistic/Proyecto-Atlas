"""Alcance causal de una decisión, compartido por dataset y bandeja.

None es mantenimiento global explícito; un conjunto vacío nunca significa
global. El ContextVar limita la batería existente sin duplicar sus reglas.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import csv
import json
from pathlib import Path
import unicodedata

_alcance = ContextVar('alcance_revalidacion_operacional', default=None)


def guias_en_alcance(ruta_dataset):
    actual = _alcance.get()
    return actual[1] if actual and Path(ruta_dataset).resolve() == actual[0] else None


@contextmanager
def alcance_guias(ruta_dataset, guias):
    if guias is None:
        yield
        return
    ruta = Path(ruta_dataset).resolve()
    previo = guias_en_alcance(ruta)
    conjunto = frozenset(str(g).strip() for g in guias if str(g).strip())
    if previo is not None:
        conjunto &= previo  # una llamada anidada nunca amplía su operación
    token = _alcance.set((ruta, conjunto))
    try:
        yield conjunto
    finally:
        _alcance.reset(token)


def _clave(texto):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFD',str(texto or '').upper())
                            if not unicodedata.combining(c)).split())


def calcular_guias_afectadas(raiz, decision, *, nombres_adicionales=(), accion=None):
    """Documento, entidad cambiada y viajes de esos documentos; nunca placeholders."""
    raiz = Path(raiz)
    doc = decision.get('documento') or {}
    numero = str(doc.get('numero_guia') or '').strip()
    dataset = raiz/'operacion/actual/analisis_completo_guias.csv'
    from atlas_core.registro_obra_destino import _asegurar_limite_campo_csv
    _asegurar_limite_campo_csv()
    with dataset.open(encoding='utf-8-sig',newline='') as f:
        filas = list(csv.DictReader(f,delimiter=';'))
    tipo = decision.get('tipo')
    campo = {'OBRA_DESCONOCIDA':'obra_destino','DESTINO_SIN_CONFIRMAR':'obra_destino',
             'DESTINO_NO_RESUELTO':'obra_destino','CLIENTE_DESCONOCIDO':'cliente',
             'CLIENTE_CANDIDATO':'cliente','CHOFER_DESCONOCIDO':'chofer','CHOFER_CANDIDATO':'chofer',
             'VEHICULO_DESCONOCIDO':{'patente_tracto':'patente_tracto','patente_rampla':'patente_rampla',
                  'patente del tracto':'patente_tracto','patente del carro':'patente_rampla'}.get(decision.get('campo')),
             'ALIAS_CANDIDATO':'cliente'}.get(tipo)
    if accion in {'POSPONER','NO_REGISTRAR','NO_CONFIRMAR','RECHAZAR','NO_PUEDO_DETERMINAR'}:
        campo = None  # no cambió una entidad compartida
    contexto = decision.get('contexto') or {}
    identidad = decision.get('identidad_resuelta') or {}
    objetivos = {numero} - {''}
    origen = [f for f in filas if str(f.get('numero_guia','')).strip() == numero]
    claves = {_clave(f.get(campo)) for f in origen} if campo else set()
    if campo:
        adicionales = (nombres_adicionales.get(campo),) if isinstance(nombres_adicionales,dict) else nombres_adicionales
        claves |= {_clave(n) for n in adicionales}
        claves.add(_clave(identidad.get('valor_canonico')))
        if campo == 'obra_destino':
            claves.add(_clave(contexto.get('obra_canonica')))
            if tipo == 'OBRA_DESCONOCIDA': claves.add(_clave(decision.get('valor_documental')))
            ruta = raiz/'catalogos_privados/obras_destinos.json'
            if ruta.is_file():
                obras = json.loads(ruta.read_text(encoding='utf-8')).get('obras',[])
                for obra in obras:
                    nombres = {_clave(obra.get('nombre_canonico')), *map(_clave,obra.get('aliases_documentales') or [])}
                    if claves & nombres and (not contexto.get('cliente_id') or obra.get('cliente_id') == contexto['cliente_id']):
                        claves |= nombres
        claves -= {'','NO ENCONTRADO','NO DETERMINADO','SIN DATO','N/A'}
        clientes = {_clave(f.get('cliente')) for f in origen} - {'','NO ENCONTRADO'}
        for f in filas:
            valores = [f.get(campo)]
            if tipo == 'VEHICULO_DESCONOCIDO': valores.append(f.get('patente_rampla'))
            if any(_clave(v) in claves for v in valores) and (
                campo != 'obra_destino' or (clientes and _clave(f.get('cliente')) in clientes)
            ):
                objetivos.add(str(f.get('numero_guia','')).strip())
    transportes = {str(f.get('numero_transporte','')).strip() for f in filas
                   if str(f.get('numero_guia','')).strip() in objetivos}
    transportes.add(str(doc.get('numero_transporte') or '').strip())
    transportes = {t for t in transportes if _clave(t) not in {'','NO ENCONTRADO','NO DETERMINADO','N/A','SIN DATO'}}
    objetivos |= {str(f.get('numero_guia','')).strip() for f in filas
                  if str(f.get('numero_transporte','')).strip() in transportes}
    return objetivos - {''}


@contextmanager
def alcance_decision_persistida(raiz, decision_id, *, nombres_adicionales=(), accion=None):
    # El caller ya sostiene aplicar_decision_obra: no se calcula con una
    # tarjeta leída antes de adquirir el lock.
    raiz = Path(raiz)
    ruta = raiz/'operacion/actual/decisiones_pendientes.json'
    bandeja = json.loads(ruta.read_text(encoding='utf-8')) if ruta.is_file() else {}
    decision = next((d for d in bandeja.get('decisiones',[]) if d.get('decision_id') == decision_id),{})
    guias = calcular_guias_afectadas(raiz,decision,nombres_adicionales=nombres_adicionales,accion=accion) if decision else set()
    with alcance_guias(raiz/'operacion/actual/analisis_completo_guias.csv',guias):
        yield


def conservar_decisiones_ajenas(ruta_dataset, ruta_salida, decisiones):
    guias = guias_en_alcance(ruta_dataset)
    if guias is None: return list(decisiones)
    ruta = Path(ruta_salida)
    previas = json.loads(ruta.read_text(encoding='utf-8')).get('decisiones',[]) if ruta.is_file() else []
    def dentro(d): return str((d.get('documento') or {}).get('numero_guia','')).strip() in guias
    return [d for d in previas if not dentro(d)] + [d for d in decisiones if dentro(d)]
