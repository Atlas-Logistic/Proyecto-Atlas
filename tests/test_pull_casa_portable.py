"""Sin red/OCR real ni registro de tareas: perfil y archivos temporales."""
import json
import os
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

from atlas_core.guardia_pull import proteger_escrituras
from atlas_core.escritor_operativo import LeaseEscritorOperativo, ErrorEscritorOperativo
from sincronizar_mobile_cloud import ejecutar_pull_con_escritor
from tests.test_sincronizar_mobile_cloud_escritor import EscritorFalso

RAIZ = Path(__file__).resolve().parents[1]


def test_perder_lease_bloquea_publicacion_y_escrituras(tmp_path):
    destino = tmp_path / 'dataset.csv'
    destino.write_text('antes')
    temporal = tmp_path / 'nuevo.tmp'
    temporal.write_text('nuevo')
    vivo = [True]
    with proteger_escrituras(tmp_path, lambda: vivo[0]):
        (tmp_path / 'recepcion.json').write_text('{}')
        vivo[0] = False
        for operacion in [lambda: destino.write_text('despues'), lambda: temporal.replace(destino),
                          lambda: destino.unlink(), lambda: (tmp_path / 'sub').mkdir()]:
            with pytest.raises(PermissionError, match='Lease PULL perdido'):
                operacion()
    assert destino.read_text() == 'antes'
    assert temporal.read_text() == 'nuevo'


def test_orquestador_aplica_guardia_durante_procesamiento(tmp_path):
    escritor = EscritorFalso(adquirido=True)
    repo = type('Repo', (), {'raiz_atlas': tmp_path})()
    def procesar(**kw):
        assert kw['proveedor_ocr_preferido'] == 'rapidocr'
        escritor.vigente = False
        assert not kw['puede_continuar']()
        (tmp_path / 'publicacion.json').write_text('{}')
    with patch('sincronizar_mobile_cloud.sincronizar_envios_cloud', side_effect=procesar):
        with pytest.raises(PermissionError):
            ejecutar_pull_con_escritor(base_url='https://cloud.test', token_motor='t', consumidor='casa',
                repositorio=repo, timeout=1, procesar=True, dataset=None, carpeta_catalogos=None,
                proveedor_ocr_preferido='rapidocr', fabrica_escritor=lambda **kw: escritor)
    assert escritor.cerrado
    assert not (tmp_path / 'publicacion.json').exists()


def test_dos_equipos_contienden_y_perdida_no_se_renueva():
    titular = [None]
    def api(base, ruta, token, **kw):
        body = kw.get('body') or {}
        if ruta.endswith('/estado'): return {'epoca': 0}
        if ruta.endswith('/adquirir'):
            if titular[0]: raise ErrorEscritorOperativo('ocupado')
            titular[0] = body['escritor_id']
            return {'estado': 'ADQUIRIDO', 'lease_token': titular[0], 'epoca': 1}
        if ruta.endswith('/renovar'):
            if body['lease_token'] != titular[0]: raise ErrorEscritorOperativo('perdido')
            return {'estado': 'RENOVADO'}
        if ruta.endswith('/liberar'):
            if titular[0] == body['lease_token']: titular[0] = None
            return {'estado': 'LIBERADO'}
        raise AssertionError(ruta)
    def lease(id):
        return LeaseEscritorOperativo(base_url='https://cloud.test', token_motor='t', escritor_id=id,
                                     heartbeat_segundos=0, margen_relevo_segundos=0)
    with patch('atlas_core.escritor_operativo._json', side_effect=api):
        casa, oficina = lease('casa'), lease('oficina')
        assert casa.adquirir()
        assert not oficina.adquirir()
        titular[0] = None  # vencimiento simulado
        assert oficina.adquirir()
        assert not casa.renovar() and not casa.vigente
        casa.cerrar()
        assert titular[0] == 'oficina'  # cierre viejo no libera al nuevo
        oficina.cerrar()


def _ps(script, *args):
    return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
                           str(RAIZ / 'scripts' / script), *map(str, args)],
                          capture_output=True, text=True, timeout=30)


@pytest.mark.skipif(os.name != 'nt', reason='PowerShell Windows')
def test_lanzador_configura_rapidocr_y_no_admite_equipo_unico(tmp_path, monkeypatch):
    proyecto = tmp_path / 'Motor con espacios'; proyecto.mkdir()
    (proyecto / '.venv/Scripts').mkdir(parents=True)
    (proyecto / '.venv/Scripts/python.exe').touch()
    (proyecto / 'sincronizar_mobile_cloud.py').touch()
    rapid = tmp_path / 'rapid.exe'; rapid.touch()
    monkeypatch.setenv('ATLAS_RAPIDOCR_PYTHON', str(rapid))
    monkeypatch.setenv('ATLAS_CLOUD_MOTOR_TOKEN', 'sintetico')
    c = tmp_path / 'config.json'; a = tmp_path / 'auth.json'
    politica = dict(proyecto=str(proyecto), raiz=str(tmp_path), autorizada=True, habilitada=True, modo_escritor='lease_cloud')
    c.write_text(json.dumps(politica))
    a.write_text(json.dumps(dict(autor='Javier',exclusividad_verificada=True,vence_utc='2099-01-01T00:00:00Z')))
    result = _ps('pull_pc_nuevo.ps1','-Config',c,'-Autorizacion',a,'-Validar')
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data['OCR'] == 'rapidocr' and data['RapidPython'] == str(rapid)
    politica['modo_escritor'] = 'equipo_unico'; c.write_text(json.dumps(politica))
    assert _ps('pull_pc_nuevo.ps1','-Config',c,'-Autorizacion',a,'-Validar').returncode != 0
    politica['modo_escritor'] = 'lease_cloud'; c.write_text(json.dumps(politica))
    a.write_text(json.dumps(dict(autor='Javier',exclusividad_verificada=True,vence_utc='2000-01-01T00:00:00Z')))
    assert _ps('pull_pc_nuevo.ps1','-Config',c,'-Autorizacion',a,'-Validar').returncode != 0


@pytest.mark.skipif(os.name != 'nt', reason='PowerShell Windows')
def test_instalador_plan_portable_deshabilitado(tmp_path):
    config = tmp_path / 'config.json'; auth = tmp_path / 'auth.json'
    config.write_text(json.dumps({'proyecto':str(RAIZ)})); auth.write_text('{}')
    result = _ps('instalar_tarea_pull.ps1','-Config',config,'-Autorizacion',auth,'-Plan')
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan['CadaMinutos'] == 5 and plan['AlIniciarSesion']
    assert not plan['Enabled'] and plan['MultipleInstances'] == 'IgnoreNew'
    assert str(RAIZ) in plan['Arguments'] and str(config) in plan['Arguments']


@pytest.mark.skipif(os.name != 'nt', reason='PowerShell Windows')
def test_instalador_repetible_con_registro_simulado(tmp_path):
    config = tmp_path / 'config.json'; auth = tmp_path / 'auth.json'
    config.write_text(json.dumps({'proyecto':str(RAIZ)})); auth.write_text('{}')
    wrapper = tmp_path / 'ensayo.ps1'
    script = r"""
param($Instalador,$Config,$Auth,$Backup)
Import-Module ScheduledTasks
$global:registros=0
$global:previa=$null
function global:Get-ScheduledTask { param($TaskName,$ErrorAction) if ($global:previa) { $global:previa } }
function global:Export-ScheduledTask { param($TaskName) '<Task/>' }
function global:Register-ScheduledTask {
 param($TaskName,$InputObject,[switch]$Force)
 if ($InputObject.Settings.Enabled) { throw 'Debe instalar deshabilitada' }
 if ($InputObject.Triggers.Count -ne 2) { throw 'Faltan triggers' }
 if ($InputObject.Settings.MultipleInstances -ne 2) { throw 'Falta IgnoreNew' }
 $global:registros++
 $global:previa=[pscustomobject]@{TaskName=$TaskName;State='Disabled';Actions=$InputObject.Actions}
}
& $Instalador -Config $Config -Autorizacion $Auth -BackupDir $Backup
& $Instalador -Config $Config -Autorizacion $Auth -BackupDir $Backup
if ($global:registros -ne 2) { throw 'No reinstalo' }
if (@(Get-ChildItem $Backup -Filter '*.xml').Count -ne 1) { throw 'No respaldo tarea anterior' }
'OK: dos registros simulados, una identidad, deshabilitada, dos triggers, respaldo'
"""
    wrapper.write_text(script)
    result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
        '-File',str(wrapper),str(RAIZ/'scripts/instalar_tarea_pull.ps1'),str(config),str(auth),str(tmp_path/'backup')],
        capture_output=True,text=True,timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'OK: dos registros' in result.stdout
