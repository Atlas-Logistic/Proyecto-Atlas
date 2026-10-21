"""Escrituras manuales de Desktop bajo el mismo árbitro del PULL.

No recibe envíos Mobile ni inicia PULL. Las raíces locales no comparten
archivos con oficina; las raíces Drive/UNC requieren lease global.
"""
from __future__ import annotations
import contextlib
import csv
import io
import json
import os
import runpy
import shutil
import sys
import uuid
import tempfile
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from atlas_core.almacenamiento_portable import bloqueo_sesion, leer_estado_operacion
from atlas_core.escritor_operativo import lease_desde_entorno

RAIZ_CODIGO = Path(__file__).resolve().parent.parent
ESCRITORES = frozenset({
    'aplicar_decision_pendiente.py', 'aplicar_decisiones_multiples.py',
    'forzar_correccion_destino.py', 'previsualizar_registro_obra.py',
    'acciones_operacionales_cli.py', 'eventos_operacionales_cli.py',
    'confirmar_incidencias_operacionales.py', 'proponer_incidencias_operacionales.py',
    'asociar_evidencia_mobile.py', 'resolver_envio_mobile.py',
    'gestionar_catalogos.py', 'reconciliar_estado_derivado.py',
    'retomar_entradas_desktop.py', 'generar_reporte_viajes.py', 'resumen_procesamiento_desktop.py',
})
_auditoria = ContextVar('desktop_escrituras', default=None)
def _auditar(evento, args):
    sesion_actual = _auditoria.get()
    if sesion_actual is None: return
    raices, vigente = sesion_actual
    destinos = []
    if evento == 'open':
        ruta, modo, flags = args
        if not ((modo and any(c in modo for c in 'wax+')) or (flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))): return
        destinos = [ruta]
    elif evento in {'os.mkdir','os.remove','os.rmdir','os.chmod','os.utime','os.truncate'}: destinos = [args[0]]
    elif evento in {'os.rename','os.link','os.symlink'}: destinos = args[:2]
    elif evento in {'subprocess.Popen','os.system','os.startfile','os.exec','os.posix_spawn'}:
        raise PermissionError('Desktop no permite procesos operacionales ajenos al Motor.')
    else: return
    if not vigente(): raise PermissionError('Escritor global perdido: escritura detenida.')
    for destino in destinos:
        if isinstance(destino,int): continue  # Handle abierto por el propio Motor.
        real = Path(os.fsdecode(destino)).resolve()
        if not any(real.is_relative_to(r) for r in raices):
            raise PermissionError('Destino fuera de la raíz operacional y temporales aprobados: '+str(real))
sys.addaudithook(_auditar)

def compartida(raiz):
    texto = str(raiz).replace('/', '\\').lower()
    return texto.startswith('\\\\') or (len(texto) > 1 and texto[1] == ':' and texto[0] != 'c') or 'onedrive' in texto or 'google drive' in texto

@contextlib.contextmanager
def sesion(raiz, *, fabrica=lease_desde_entorno):
    raiz = Path(raiz).resolve()
    with contextlib.ExitStack() as stack:
        escritor = None
        if compartida(raiz):
            escritor = fabrica()
            if escritor is None:
                raise PermissionError('Falta ATLAS_CLOUD_MOTOR_TOKEN: necesario sólo para arbitrar el dataset compartido con oficina; PULL no debe estar activo en JAVO.')
            stack.enter_context(escritor)
            if not escritor.adquirir():
                raise PermissionError('Dataset compartido ocupado o árbitro inaccesible. No se inició ninguna escritura.')
        def comprobar():
            if escritor is not None and (not escritor.vigente or not escritor.renovar()):
                raise PermissionError('Se perdió la exclusividad del escritor; operación detenida.')
        comprobar()
        # El lease se adquiere ANTES de crear incluso el lock local en Drive.
        stack.enter_context(bloqueo_sesion(raiz/'operacion'/'actual', 'desktop_manual'))
        raices = [raiz, Path(tempfile.gettempdir()).resolve()]
        if os.environ.get('EASYOCR_MODULE_PATH'): raices.append(Path(os.environ['EASYOCR_MODULE_PATH']).resolve())
        token = _auditoria.set((raices, lambda: escritor is None or escritor.vigente))
        try: yield comprobar
        finally: _auditoria.reset(token)

def ejecutar_script(argumentos, entrada=None):
    script = Path(argumentos[0])
    if script.name not in ESCRITORES or (script.is_absolute() and script.parent.resolve() != RAIZ_CODIGO):
        raise PermissionError('Acción Desktop no admitida.')
    return _cli([script.name, *argumentos[1:]], entrada)

def _cli(argumentos, entrada=None):
    anteriores = sys.argv
    stdin_anterior = sys.stdin
    salida = io.StringIO()
    try:
        sys.argv = [str(RAIZ_CODIGO/argumentos[0]), *map(str, argumentos[1:])]
        if entrada is not None: sys.stdin = io.StringIO(entrada)
        with contextlib.redirect_stdout(salida):
            try:
                runpy.run_path(sys.argv[0], run_name='__main__')
            except SystemExit as e:
                if e.code not in (None, 0): raise RuntimeError('Motor terminó con error: '+str(e.code)) from e
    finally:
        sys.argv = anteriores
        sys.stdin = stdin_anterior
    return salida.getvalue()

def ingresar(raiz, archivos, comprobar):
    raiz = Path(raiz).resolve()
    originales = [Path(p).resolve(strict=True) for p in archivos]
    if not originales or any(not p.is_file() or p.suffix.lower() not in {'.png','.jpg','.jpeg','.pdf'} for p in originales):
        raise ValueError('Seleccione guías JPG, PNG o PDF válidas.')
    nombres = [p.name.casefold() for p in originales]
    if len(set(nombres)) != len(nombres):
        raise ValueError('Hay archivos con el mismo nombre en el lote; no se sobrescribió ninguno.')
    from atlas_core.fuente_catalogos import validar_fuente_catalogos
    catalogos = raiz/'catalogos_privados'
    validar_fuente_catalogos(catalogos)
    comprobar()
    marca = datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
    entrada = raiz/'operacion'/'entradas'/marca
    entrada.mkdir(parents=True, exist_ok=False)
    for p in originales:
        comprobar()
        with p.open('rb') as fuente, (entrada/p.name).open('xb') as destino:
            shutil.copyfileobj(fuente, destino)
    dataset = raiz/'operacion'/'actual'/'analisis_completo_guias.csv'
    snapshot = entrada/'_snapshot_antes.json'
    _cli(['resumen_procesamiento_desktop.py','snapshot','--csv-masivo',dataset,'--salida',snapshot])
    comprobar()
    _cli(['analizar_guias_masivo.py',entrada,'--salida',dataset,'--catalogos',catalogos,'--reconciliar-focal','--sin-telemetria'])
    comprobar()
    reporte = raiz/'reportes'/('reporte_desktop_'+marca)
    _cli(['generar_reporte_viajes.py',dataset,reporte,'--catalogos',catalogos])
    estado = leer_estado_operacion(raiz=raiz) or {}
    vigente = raiz/estado.get('reporte_vigente','')
    if not (vigente/'viajes.csv').is_file():
        raise RuntimeError('Motor no publicó un reporte vigente; no se declara ingreso completo.')
    args = ['resumen_procesamiento_desktop.py','resumen','--csv-masivo',dataset,'--reporte',vigente,'--snapshot',snapshot]
    for p in originales: args += ['--archivo',p.name]
    resumen = json.loads(_cli(args))
    with dataset.open(encoding='utf-8-sig',newline='') as f:
        filas = list(csv.DictReader(f,delimiter=';'))
    errores = [f.get('error','Error de procesamiento') for f in filas if any(f.get('archivo','') == p.name or f.get('archivo','').startswith(p.name+'::') for p in originales) and f.get('estado_procesamiento') == 'ERROR']
    if errores: raise RuntimeError('Guía guardada para revisión técnica, sin éxito de procesamiento: '+'; '.join(errores))
    return {'ok':True,'cantidad':len(originales),'resumen':resumen,'carpetaReportes':str(vigente),'lote':marca}

def ejecutar(solicitud):
    raiz = Path(solicitud['raiz']).resolve(strict=True)
    os.environ['ATLAS_DATA_DIR'] = str(raiz)
    os.environ['ATLAS_CATALOGOS_DIR'] = str(raiz/'catalogos_privados')
    os.environ.setdefault('ATLAS_OCR_PROVIDER','easyocr')
    accion = solicitud.get('accion')
    if accion not in {'ingresar','script'}: raise ValueError('Acción Desktop inválida.')
    if accion == 'script' and Path(solicitud['argumentos'][0]).name not in ESCRITORES:
        raise PermissionError('Acción Desktop no admitida.')
    with sesion(raiz) as comprobar:
        if accion == 'ingresar': return ingresar(raiz, solicitud.get('archivos',[]), comprobar)
        comprobar()
        return {'ok':True,'salida':ejecutar_script(solicitud['argumentos'],solicitud.get('entrada'))}
