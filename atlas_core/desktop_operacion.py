"""Escrituras manuales de Desktop bajo exclusividad explícita.

No recibe envíos Mobile ni inicia PULL. Las raíces locales no comparten
archivos; Drive/UNC requieren lease global o política de equipo único.
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
import re
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
        from atlas_core.exclusividad_equipo import politica_equipo_unico, EscritorEquipoUnico, recuperar_bloqueos_huerfanos
        politica = politica_equipo_unico(raiz)
        if politica:
            escritor = EscritorEquipoUnico(raiz)
        elif compartida(raiz):
            escritor = fabrica()
            if escritor is None:
                raise PermissionError('Modo compartido sin lease: configure una política autorizada de equipo único o la credencial legítima del árbitro Cloud.')
        if escritor is not None:
            stack.enter_context(escritor)
            if not escritor.adquirir():
                raise PermissionError('Escritor ocupado o exclusividad no verificable. No se inició ninguna escritura.')
            # Mutex local o lease Cloud: con exclusividad vigente, un lock de
            # este PC cuyo PID terminó es huérfano (caída a mitad de ingreso).
            recuperar_bloqueos_huerfanos(raiz, escritor=escritor)
        def comprobar():
            if escritor is not None and (not escritor.vigente or not escritor.renovar()):
                raise PermissionError('Se perdió la exclusividad del escritor; operación detenida.')
        comprobar()
        # El lease se adquiere ANTES de crear incluso el lock local en Drive.
        stack.enter_context(bloqueo_sesion(raiz/'operacion'/'actual', 'desktop_manual'))
        raices = [raiz, Path(tempfile.gettempdir()).resolve()]
        # Cache derivado local: siempre se contrasta con las huellas de Drive.
        # Se permite sólo este directorio, sin ampliar el permiso a AppData.
        cache = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir()))/'Atlas'/'cache'
        cache.mkdir(parents=True, exist_ok=True)
        raices.append(cache.resolve())
        if os.environ.get('EASYOCR_MODULE_PATH'): raices.append(Path(os.environ['EASYOCR_MODULE_PATH']).resolve())
        token = _auditoria.set((raices, lambda: escritor is None or escritor.vigente))
        try: yield comprobar
        finally: _auditoria.reset(token)

def ejecutar_script(argumentos, entrada=None):
    script = Path(argumentos[0])
    if script.name not in ESCRITORES or (script.is_absolute() and script.parent.resolve() != RAIZ_CODIGO):
        raise PermissionError('Acción Desktop no admitida.')
    return _cli([script.name, *argumentos[1:]], entrada)

class _SalidaCLI(io.StringIO):
    """Captura la respuesta interna y entrega el progreso sin esperar al CLI."""

    def __init__(self, stderr):
        super().__init__()
        self._stderr = stderr
        self._pendiente = ''

    def _linea(self, linea):
        if re.fullmatch(r'\[\d+/\d+\]\s+[^\r\n]+', linea.rstrip('\r\n')):
            self._stderr.write(linea if linea.endswith('\n') else linea + '\n')
            self._stderr.flush()
        else:
            super().write(linea)

    def write(self, texto):
        self._pendiente += texto
        while '\n' in self._pendiente:
            linea, self._pendiente = self._pendiente.split('\n', 1)
            self._linea(linea + '\n')
        return len(texto)

    def finalizar(self):
        if self._pendiente:
            self._linea(self._pendiente)
            self._pendiente = ''


def _cli(argumentos, entrada=None):
    anteriores = sys.argv
    stdin_anterior = sys.stdin
    salida = _SalidaCLI(sys.stderr)
    try:
        sys.argv = [str(RAIZ_CODIGO/argumentos[0]), *map(str, argumentos[1:])]
        if entrada is not None: sys.stdin = io.StringIO(entrada)
        with contextlib.redirect_stdout(salida):
            try:
                runpy.run_path(sys.argv[0], run_name='__main__')
            except SystemExit as e:
                if e.code not in (None, 0): raise RuntimeError('Motor terminó con error: '+str(e.code)) from e
    finally:
        try:
            salida.finalizar()
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
    dataset = raiz/'operacion'/'actual'/'analisis_completo_guias.csv'
    csv.field_size_limit(2147483647)
    existentes = []
    if dataset.is_file():
        with dataset.open(encoding='utf-8-sig',newline='') as f: vigentes=list(csv.DictReader(f,delimiter=';'))
        numeros={r.get('numero_guia','').strip():r for r in vigentes}
        nuevos=[]
        for p in originales:
            if re.fullmatch(r'\d{3,12}',p.stem) and p.stem in numeros:
                r=numeros[p.stem]
                existentes.append({'archivo':p.name,'numero_guia':p.stem,'numero_transporte':r.get('numero_transporte',''),'encontrado':True,'ya_existia':True})
            else: nuevos.append(p)
        originales=nuevos
    if not originales:
        estado=leer_estado_operacion(raiz=raiz) or {}
        return {'ok':True,'cantidad':0,'existentes':existentes,'resumen':existentes,'carpetaReportes':str(raiz/estado.get('reporte_vigente',''))}
    marca = datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
    entrada = raiz/'operacion'/'entradas'/marca
    entrada.mkdir(parents=True, exist_ok=False)
    for p in originales:
        comprobar()
        with p.open('rb') as fuente, (entrada/p.name).open('xb') as destino:
            shutil.copyfileobj(fuente, destino)
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
    return {'ok':True,'cantidad':len(originales),'resumen':resumen+existentes,'existentes':existentes,'carpetaReportes':str(vigente),'lote':marca}

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
