"""Auditoría de escritores fuera del turno (docs/AUDITORIA_ESCRITORES_FUERA_DEL_TURNO.md).

Cada prueba corre en un subproceso aislado: LOCALAPPDATA propio, política
sintética cuya raíz «parece» compartida (contiene "Google Drive", igual que la
regla `exclusion_local.compartida` reconoce G:/Drive), sin variables ATLAS_* ni
credenciales. No toca G:, CASA, OFICINA ni Cloud, ni modifica ningún mecanismo:
sólo ejercita el código existente.

Convención: ``PROTEGIDO`` = la escritura se rechaza; ``VULNERABLE`` = la
escritura ocurre sin la coordinación requerida (la prueba fija que HOY ocurre).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="turno local y CopyFile2 son de Windows")

ARBOL = Path(__file__).resolve().parents[1]
DESKTOP = Path(os.environ.get("AUDITORIA_DESKTOP_DIR", r"C:\Atlas\Atlas-Viajes-Desktop"))
FUENTE = "operacion/actual/agrupaciones_viaje.json"
CONTENIDO = '{"schema_version": 1, "agrupaciones": []}'


def _sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


@pytest.fixture
def mundo(tmp_path):
    raiz = tmp_path / "Google Drive" / "Atlas"          # compartida() la reconoce como Drive
    (raiz / "operacion" / "actual").mkdir(parents=True)
    (raiz / "catalogos_privados").mkdir(parents=True)
    (raiz / FUENTE).write_text(CONTENIDO, encoding="utf-8")
    (raiz / "operacion/actual/analisis_completo_guias.csv").write_text("archivo;numero_guia\n", encoding="utf-8")
    (raiz / "operacion/actual/decisiones_pendientes.json").write_text('{"decisiones": []}', encoding="utf-8")
    local = tmp_path / "local"
    (local / "Atlas").mkdir(parents=True)
    politica = local / "Atlas" / "desktop_operacion.json"
    politica.write_text(json.dumps({"raiz": str(raiz), "habilitada": True, "autorizada": True,
                                    "modo_escritor": "lease_cloud"}), encoding="utf-8")
    temporal = tmp_path / "tmp"
    temporal.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ATLAS_", "CLOUD", "PYTHON"))}
    env.update(LOCALAPPDATA=str(local), ATLAS_OPERACION_CONFIG=str(politica), PYTHONIOENCODING="utf-8",
               PYTHONDONTWRITEBYTECODE="1", TEMP=str(temporal), TMP=str(temporal))
    return SimpleNamespace(raiz=raiz, env=env, tmp=tmp_path, politica=politica)


def correr(mundo, codigo: str, *, env=None, entrada=None, timeout=60):
    preludio = f"import sys, json, os, shutil\nsys.path.insert(0, {str(ARBOL)!r})\nimport atlas_core\nfrom pathlib import Path\nRAIZ = Path({str(mundo.raiz)!r})\n"
    return subprocess.run([sys.executable, "-E", "-c", preludio + textwrap.dedent(codigo)], cwd=ARBOL,
                          env=env or mundo.env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          input=entrada, timeout=timeout)


ESCRIBIR = """
from atlas_core.almacenamiento_portable import escribir_json_atomico
escribir_json_atomico(RAIZ / {fuente!r}, {{"schema_version": 1, "agrupaciones": [{{"id": "X"}}]}})
print("ESCRITO")
"""


# ------------------------------------------------------------------ C. CLIs y escritores sin turno
def test_escritor_real_sin_turno_bloqueado_por_la_guardia(mundo):
    antes = _sha(mundo.raiz / FUENTE)
    r = correr(mundo, ESCRIBIR.format(fuente=FUENTE))
    assert r.returncode != 0 and "EscrituraSinTurno" in r.stderr
    assert _sha(mundo.raiz / FUENTE) == antes


@pytest.mark.parametrize("cli", [
    ["aplicar_decision_pendiente.py", "--raiz-atlas", "{raiz}", "--decision-id", "D-SINTETICA", "--accion", "CONFIRMAR"],
    ["migrar_relaciones_operacionales.py", "--raiz", "{raiz}", "--aplicar", "--sin-escritor"],
    ["reproceso_cuarentena.py", "promover", "--raiz-atlas", "{raiz}", "--workspace", "{ws}"],
])
def test_cli_manual_sin_turno_bloqueado(mundo, cli):
    ws = mundo.tmp / "workspace"
    ws.mkdir()
    (ws / "manifiesto_candidato.json").write_text(json.dumps({"estado": "APTO_PARA_PROMOCION", "documentos": []}),
                                                  encoding="utf-8")
    antes = {p: _sha(p) for p in mundo.raiz.rglob("*") if p.is_file()}
    args = [a.format(raiz=mundo.raiz, ws=ws) for a in cli]
    r = subprocess.run([sys.executable, "-E", str(ARBOL / args[0]), *args[1:]], cwd=ARBOL, env=mundo.env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert r.returncode != 0 and "EscrituraSinTurno" in r.stderr, r.stderr[-400:]
    despues = {p: _sha(p) for p in mundo.raiz.rglob("*") if p.is_file()}
    assert despues == antes   # ni lock, ni dataset, ni bandeja: nada parcial


def test_con_turno_la_escritura_procede(mundo):
    r = correr(mundo, "from atlas_core.exclusion_local import TurnoEscritura\nwith TurnoEscritura(RAIZ):\n"
               + textwrap.indent(ESCRIBIR.format(fuente=FUENTE), "    "))
    assert r.returncode == 0 and "ESCRITO" in r.stdout, r.stderr[-300:]


def test_competencia_con_turno_activo(mundo):
    poseedor = subprocess.Popen(
        [sys.executable, "-E", "-c",
         f"import sys; sys.path.insert(0, {str(ARBOL)!r}); import atlas_core\n"
         f"from atlas_core.exclusion_local import TurnoEscritura\n"
         f"t = TurnoEscritura({str(mundo.raiz)!r}); assert t.adquirir(); print('LISTO', flush=True); sys.stdin.read()"],
        cwd=ARBOL, env=mundo.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert poseedor.stdout.readline().strip() == "LISTO"
        r = correr(mundo, "from atlas_core.exclusion_local import TurnoEscritura\n"
                          "print('TURNO', TurnoEscritura(RAIZ).adquirir())\n" + ESCRIBIR.format(fuente=FUENTE))
        assert "TURNO False" in r.stdout and "EscrituraSinTurno" in r.stderr
    finally:
        poseedor.communicate("", timeout=30)


# ------------------------------------------------------------------ evasiones de la guardia
def test_vulnerable_proceso_sin_politica_ni_raiz_declarada(mundo):
    """Otro perfil, tarea de otro usuario o un LOCALAPPDATA sin política: la raíz no está protegida."""
    otro = dict(mundo.env)
    otro.pop("ATLAS_OPERACION_CONFIG")
    otro["LOCALAPPDATA"] = str(mundo.tmp / "otro_perfil")
    r = correr(mundo, ESCRIBIR.format(fuente=FUENTE), env=otro)
    assert r.returncode == 0 and "ESCRITO" in r.stdout
    assert json.loads((mundo.raiz / FUENTE).read_text(encoding="utf-8"))["agrupaciones"] == [{"id": "X"}]


def test_vulnerable_alias_por_junction(mundo):
    alias = mundo.tmp / "alias_atlas"
    hecho = subprocess.run(["cmd", "/c", "mklink", "/J", str(alias), str(mundo.raiz)], capture_output=True, text=True)
    if hecho.returncode != 0:
        pytest.skip("no se pudo crear el junction: " + hecho.stderr)
    try:
        r = correr(mundo, f"""
from atlas_core.almacenamiento_portable import escribir_json_atomico
escribir_json_atomico(Path({str(alias)!r}) / {FUENTE!r}, {{"schema_version": 1, "agrupaciones": [{{"id": "J"}}]}})
print("ESCRITO")
""")
        assert r.returncode == 0 and "ESCRITO" in r.stdout, r.stderr[-300:]
        assert json.loads((mundo.raiz / FUENTE).read_text(encoding="utf-8"))["agrupaciones"] == [{"id": "J"}]
    finally:
        os.rmdir(alias)   # quita sólo el junction, nunca el destino


# ------------------------------------------------------------------ pérdida de lease
def test_vulnerable_cli_con_escritor_sigue_escribiendo_tras_perder_el_lease(mundo):
    """migrar_relaciones_operacionales._con_escritor (mismo patrón que mantener_pendientes_tecnicos.pasada_programada):
    sólo comprueba ``vigente`` antes de la operación. El lease perdido no suelta el turno local, así que la guardia
    tampoco bloquea."""
    r = correr(mundo, f"""
sys.path.insert(0, {str(ARBOL)!r})
import migrar_relaciones_operacionales as m
from atlas_core.exclusion_local import TurnoEscritura
from atlas_core.almacenamiento_portable import escribir_json_atomico

class EscritorSintetico:   # turno local real + lease simulado que se pierde
    def __init__(self, raiz): self.turno, self.lease_vigente = TurnoEscritura(raiz), True
    def __enter__(self): return self
    def __exit__(self, *a): self.turno.soltar()
    def adquirir(self): return self.turno.adquirir()
    @property
    def vigente(self): return self.lease_vigente and self.turno.vigente

esc = {{}}
def fabrica(raiz):
    esc["e"] = EscritorSintetico(raiz)
    return esc["e"]

def operacion():
    esc["e"].lease_vigente = False                      # heartbeat perdido a mitad de operación
    escribir_json_atomico(RAIZ / {FUENTE!r}, {{"schema_version": 1, "agrupaciones": [{{"id": "TRAS_PERDIDA"}}]}})
    return {{"vigente_al_escribir": esc["e"].vigente}}

print(json.dumps(m._con_escritor(str(RAIZ), operacion, fabrica=fabrica, sin_escritor=False)))
""")
    assert r.returncode == 0, r.stderr[-400:]
    assert json.loads(r.stdout.strip().splitlines()[-1]) == {"vigente_al_escribir": False}
    assert json.loads((mundo.raiz / FUENTE).read_text(encoding="utf-8"))["agrupaciones"] == [{"id": "TRAS_PERDIDA"}]


SESION_O_PULL = """
from atlas_core.exclusion_local import TurnoEscritura
from atlas_core.almacenamiento_portable import escribir_json_atomico
import tempfile
estado = {{"vigente": True}}
origen = Path(tempfile.gettempdir()) / "copia_origen.json"
origen.write_text('{{"copiado": true}}', encoding="utf-8")
resultado = {{}}
with TurnoEscritura(RAIZ):
    {activar}
    escribir_json_atomico(RAIZ / "operacion/actual/primera.json", {{"n": 1}})
    resultado["primera"] = "ESCRITA"
    estado["vigente"] = False                            # lease perdido entre dos escrituras
    try:
        escribir_json_atomico(RAIZ / "operacion/actual/segunda.json", {{"n": 2}})
        resultado["segunda"] = "ESCRITA"
    except PermissionError as e:
        resultado["segunda"] = "BLOQUEADA"
    try:
        shutil.copy2(origen, RAIZ / "operacion/actual/copiada.json")   # _winapi.CopyFile2: sin evento open
        resultado["copia"] = "ESCRITA"
    except PermissionError:
        resultado["copia"] = "BLOQUEADA"
print(json.dumps(resultado))
"""


def test_sesion_desktop_tras_perdida_de_lease(mundo):
    activar = ("from atlas_core import desktop_operacion as d\n    "
               "d._auditoria.set(([RAIZ.resolve(), Path(tempfile.gettempdir()).resolve()], lambda: estado['vigente']))")
    r = correr(mundo, SESION_O_PULL.format(activar=activar))
    assert r.returncode == 0, r.stderr[-400:]
    resultado = json.loads(r.stdout.strip().splitlines()[-1])
    # PROTEGIDO para open/rename; escritura parcial demostrada; CopyFile2 no auditada: VULNERABLE.
    assert resultado == {"primera": "ESCRITA", "segunda": "BLOQUEADA", "copia": "ESCRITA"}
    assert not (mundo.raiz / "operacion/actual/segunda.json").exists()


def test_pull_tras_perdida_de_lease(mundo):
    activar = ("from atlas_core.guardia_pull import proteger_escrituras\n    "
               "ctx = proteger_escrituras(RAIZ, lambda: estado['vigente']); ctx.__enter__()")
    r = correr(mundo, SESION_O_PULL.format(activar=activar))
    assert r.returncode == 0, r.stderr[-400:]
    assert json.loads(r.stdout.strip().splitlines()[-1]) == {"primera": "ESCRITA", "segunda": "BLOQUEADA",
                                                             "copia": "ESCRITA"}


# ------------------------------------------------------------------ A/B. Desktop (código instalado = repo)
NODE = shutil.which("node")


@pytest.mark.skipif(not (NODE and (DESKTOP / "src" / "instalacion_consulta.js").is_file()),
                    reason="requiere node y el repositorio Desktop (AUDITORIA_DESKTOP_DIR)")
def test_ruta_legada_electron_bloqueada_por_modo_consulta(mundo):
    """procesarImagenesDesktop (rama no preparada) copia con fs.copyFileSync y crea carpetas en entradas;
    instalacion_consulta.js parchea fs y child_process en el proceso principal."""
    origen = mundo.tmp / "guia.jpg"
    origen.write_bytes(b"foto-sintetica")
    script = mundo.tmp / "legado.js"
    script.write_text(textwrap.dedent(f"""
        delete process.env.ATLAS_PRUEBA_ROOT;
        const path = require('node:path');
        const consulta = require({str(DESKTOP / 'src' / 'instalacion_consulta.js')!r});
        consulta.configurarRaices(() => [{str(mundo.raiz)!r}]);
        const fs = require('node:fs'); const cp = require('node:child_process');
        const r = {{}};
        const lote = path.join({str(mundo.raiz)!r}, 'operacion', 'entradas', 'lote-legado');
        try {{ fs.mkdirSync(lote, {{ recursive: true }}); r.mkdir = 'ESCRITA'; }} catch (e) {{ r.mkdir = 'BLOQUEADA'; }}
        try {{ fs.copyFileSync({str(origen)!r}, path.join(lote, 'guia.jpg')); r.copia = 'ESCRITA'; }} catch (e) {{ r.copia = 'BLOQUEADA'; }}
        try {{ fs.writeFileSync(path.join({str(mundo.raiz)!r}, 'operacion', 'actual', 'x.json'), '{{}}'); r.escritura = 'ESCRITA'; }} catch (e) {{ r.escritura = 'BLOQUEADA'; }}
        try {{ cp.spawn('python'); r.proceso = 'LANZADO'; }} catch (e) {{ r.proceso = 'BLOQUEADO'; }}
        console.log(JSON.stringify(r));
    """), encoding="utf-8")
    env = {k: v for k, v in mundo.env.items() if k != "ATLAS_PRUEBA_ROOT"}
    r = subprocess.run([NODE, str(script)], cwd=mundo.tmp, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-400:]
    assert json.loads(r.stdout.strip().splitlines()[-1]) == {"mkdir": "BLOQUEADA", "copia": "BLOQUEADA",
                                                             "escritura": "BLOQUEADA", "proceso": "BLOQUEADO"}
    assert not (mundo.raiz / "operacion" / "entradas").exists()


@pytest.mark.skipif(not (DESKTOP / "src" / "consulta_python.py").is_file(), reason="requiere el repositorio Desktop")
def test_envoltorio_solo_consulta_bloquea_escrituras_salvo_copias(mundo):
    """Lectores que Desktop lanza (consultar_atlas, b1_consulta, retomar --listar): consulta_python.py."""
    destino = mundo.tmp / "fuera_de_raiz"
    destino.mkdir()
    lector = mundo.tmp / "lector_sintetico.py"
    lector.write_text(textwrap.dedent(f"""
        import json, shutil
        from pathlib import Path
        d = Path({str(destino)!r}); r = {{}}
        (d / 'origen.txt').exists()
        try:
            open(d / 'escrito.txt', 'w').close(); r['open'] = 'ESCRITA'
        except PermissionError: r['open'] = 'BLOQUEADA'
        try:
            shutil.copy2({str(mundo.raiz / FUENTE)!r}, d / 'copiado.json'); r['copia'] = 'ESCRITA'
        except PermissionError: r['copia'] = 'BLOQUEADA'
        print(json.dumps(r))
    """), encoding="utf-8")
    r = subprocess.run([sys.executable, "-I", "-B", str(DESKTOP / "src" / "consulta_python.py"), str(lector)],
                       cwd=mundo.tmp, env=mundo.env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-400:]
    assert json.loads(r.stdout.strip().splitlines()[-1]) == {"open": "BLOQUEADA", "copia": "ESCRITA"}
