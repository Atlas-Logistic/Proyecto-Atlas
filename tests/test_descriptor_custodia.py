"""Compatibilidad descriptor Motor <-> custodia de generaciones Cloud v1. Solo datos sintéticos."""
from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from atlas_core import descriptor_custodia as dc
from atlas_core import descriptor_generacion as dg
from atlas_core.descriptor_custodia import (
    MAX_OBJETOS_CUSTODIA, RUTA_DESCRIPTOR, proyectar_para_custodia, verificar_generacion_custodia,
)
from atlas_core.descriptor_generacion import (
    COMPLETITUD, TIPOS_V1, ErrorDescriptor, GeneracionSolicitada, Inventario, ObjetoFuente, Referencia,
    construir_descriptor, huella_contenido, leer_descriptor, serializar_descriptor,
)

EMP = "empresa-sintetica"
OTRA = "empresa-ajena"
MBT_CLOUD = "empresa-prueba-javier"
G1 = GeneracionSolicitada("gen-000001", 1)
G2 = GeneracionSolicitada("gen-000002", 2, "gen-000001")


def generacion(empresa=EMP, gen=G1, *, n_evidencia=2, variante="", con_marca=None):
    """Descriptor sintético y contenidos de sus objetos (identidad -> bytes)."""
    contenidos: dict[str, bytes] = {}
    objetos: list[ObjetoFuente] = []

    def agregar(ident, tipo, texto, *, obligatorio=None, referencias=(), metadatos=None):
        datos = texto.encode("utf-8")
        contenidos[ident] = datos
        o = ObjetoFuente(ident, tipo, huella_contenido(datos), empresa,
                         TIPOS_V1[tipo].obligatorio if obligatorio is None else obligatorio,
                         len(datos), metadatos or {}, tuple(referencias))
        objetos.append(o)
        return o

    evidencia = [agregar(f"evidencia/guia/{900000 + i}/original", "EVIDENCIA_DOCUMENTAL",
                         f"pdf-sintetico-{i}{variante}", obligatorio=True, metadatos={"documento": f"{900000 + i}"})
                 for i in range(n_evidencia)]
    refs = [Referencia(e.identidad, e.huella, empresa) for e in evidencia]
    if con_marca if con_marca is not None else empresa not in dg.EMPRESAS_SIN_MARCA:
        agregar("empresa/identidad", "IDENTIDAD_EMPRESA", json.dumps({"cloud_id": empresa}))
    agregar("operacion/dataset", "DATASET_OPERACIONAL", f"guia,fecha\n900000,2026-11-20{variante}\n", referencias=refs)
    agregar("operacion/ledger", "LEDGER_DECISIONES", "[]")
    agregar("operacion/decisiones-humanas", "DECISIONES_HUMANAS", "{}")
    agregar("operacion/bandeja", "BANDEJA_REVISION", "[]")
    agregar("operacion/agrupaciones", "AGRUPACIONES_CONFIRMADAS", "[]")
    agregar("operacion/investigacion", "REGISTRO_INVESTIGACION", '{"abiertos":[]}', referencias=refs[:1])
    agregar("catalogos/choferes", "CATALOGO", "rut,nombre\n")
    agregar("catalogos/asignaciones", "ASIGNACIONES", "patente,rut,desde\n")
    declaracion = {t: 0 for t in TIPOS_V1}
    for o in objetos:
        declaracion[o.tipo] += 1
    d = construir_descriptor(Inventario(1, empresa, gen, declaracion, tuple(objetos)))
    return d, contenidos


def respuesta_cloud(p: dc.ProyeccionCustodia):
    """Lo que devolvería GET .../actual para esta proyección (forma canónica)."""
    return p.descriptor(), p.descriptor_sha256


def rechazo(fn, *args, **kwargs) -> ErrorDescriptor:
    with pytest.raises(ErrorDescriptor) as exc:
        fn(*args, **kwargs)
    return exc.value


# ---------------------------------------------------------------- forma Cloud
_ID_SEGURO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")  # src/worker.js:4


def _ruta_estado_valida(ruta: str) -> bool:  # src/worker.js rutaEstadoValida
    if not isinstance(ruta, str) or not ruta or len(ruta) > 512 or re.search(r"[\x00-\x08\x0B-\x1F\x7F]", ruta):
        return False
    if ruta.startswith("/") or "\\" in ruta or ":" in ruta:
        return False
    return all(p and p not in (".", "..") for p in ruta.split("/"))


def test_proyeccion_cumple_la_forma_del_contrato_cloud():
    d, contenidos = generacion()
    p = proyectar_para_custodia(d, EMP)
    cuerpo = p.descriptor()
    assert list(cuerpo) == ["version", "empresa_id", "generacion_id", "objetos"]
    assert cuerpo["version"] == 1 and cuerpo["empresa_id"] == EMP and cuerpo["generacion_id"] == "gen-000001"
    assert _ID_SEGURO.fullmatch(cuerpo["generacion_id"])
    rutas = [o["ruta"] for o in cuerpo["objetos"]]
    assert rutas == sorted(rutas) and len(set(rutas)) == len(rutas) and 1 <= len(rutas) <= MAX_OBJETOS_CUSTODIA
    assert all(_ruta_estado_valida(r) for r in rutas)
    assert all(set(o) == {"ruta", "sha256"} and re.fullmatch(r"[0-9a-f]{64}", o["sha256"]) for o in cuerpo["objetos"])
    assert p.descriptor_sha256 == hashlib.sha256(p.descriptor_cloud).hexdigest()
    assert p.anterior_id is None
    # Fuentes = objetos con ruta = identidad; el descriptor Motor es un objeto más.
    assert set(rutas) == set(contenidos) | {RUTA_DESCRIPTOR}


def test_separacion_descriptor_preparado_y_publicacion():
    d, _ = generacion()
    p = proyectar_para_custodia(d, EMP)
    texto = p.descriptor_cloud.decode()
    for prohibido in ("lease", "version_base", "PENDIENTE\"", "PUBLICADA", "estado", "anterior_id"):
        assert prohibido not in texto
    motor = json.loads(p.objeto_descriptor)
    assert motor["completitud"] == COMPLETITUD and motor["clase"] == "DESCRIPTOR_PREPARADO"
    vuelto = verificar_generacion_custodia(*respuesta_cloud(p), p.objeto_descriptor, EMP)
    assert vuelto == d and vuelto.completitud == COMPLETITUD
    con_estado = {**p.descriptor(), "estado": "PUBLICADA"}
    assert rechazo(verificar_generacion_custodia, con_estado, p.descriptor_sha256, p.objeto_descriptor, EMP).codigos \
        == {"FORMATO_INVALIDO"}


# ---------------------------------------------------------------- empresa
def test_empresa_canonica_es_la_identidad_de_custodia():
    from atlas_core import aislamiento_empresas as ae
    assert dg.EMPRESAS_SIN_MARCA == {ae.CLOUD_MBT}
    assert dg.EMPRESAS_LOCALES_NO_CANONICAS == {ae.EMPRESA_MBT, ae.REGISTRO_MBT}
    for local in ("mbt", "oficina"):
        inv = Inventario(1, local, G1, {}, ())
        assert rechazo(construir_descriptor, inv).codigos == {"EMPRESA_INVALIDA"}
        d, _ = generacion()
        assert rechazo(proyectar_para_custodia, d, local).codigos == {"EMPRESA_INVALIDA"}


def test_mbt_opera_sin_marca_declarada_en_cero():
    d, contenidos = generacion(MBT_CLOUD)
    assert dict(d.declaracion)["IDENTIDAD_EMPRESA"] == 0 and "empresa/identidad" not in contenidos
    p = proyectar_para_custodia(d, MBT_CLOUD)
    assert verificar_generacion_custodia(*respuesta_cloud(p), p.objeto_descriptor, MBT_CLOUD) == d
    # Una marca en la custodia MBT indica empresa ajena.
    assert "EMPRESA_INCORRECTA" in rechazo(generacion, MBT_CLOUD, G1, con_marca=True).codigos
    # Las demás empresas siguen exigiendo su marca.
    assert "FUENTE_OBLIGATORIA_AUSENTE" in rechazo(generacion, EMP, G1, con_marca=False).codigos


def test_rechazo_de_empresas_cruzadas():
    d, _ = generacion()
    assert rechazo(proyectar_para_custodia, d, OTRA).codigos == {"EMPRESA_INCORRECTA"}
    p = proyectar_para_custodia(d, EMP)
    cuerpo, sha = respuesta_cloud(p)
    assert rechazo(verificar_generacion_custodia, cuerpo, sha, p.objeto_descriptor, OTRA).codigos == {"EMPRESA_INCORRECTA"}
    # Cuerpo Cloud reescrito a la otra empresa con el descriptor Motor original dentro.
    ajeno = {**cuerpo, "empresa_id": OTRA}
    assert rechazo(verificar_generacion_custodia, ajeno, sha, p.objeto_descriptor, OTRA).codigos == {"EMPRESA_INCORRECTA"}


# ---------------------------------------------------------------- huellas y determinismo
def test_huellas_equivalentes_y_verificables():
    d, contenidos = generacion()
    p = proyectar_para_custodia(d, EMP)
    cloud = {o["ruta"]: o["sha256"] for o in p.descriptor()["objetos"]}
    for f in d.fuentes:
        assert f.huella == "sha256:" + cloud[f.identidad]
        assert hashlib.sha256(contenidos[f.identidad]).hexdigest() == cloud[f.identidad]
    assert cloud[RUTA_DESCRIPTOR] == p.objeto_descriptor_sha256 == hashlib.sha256(p.objeto_descriptor).hexdigest()
    assert p.objeto_descriptor == serializar_descriptor(d)


def test_proyeccion_determinista_ante_orden_de_entrada():
    d, _ = generacion(n_evidencia=6)
    base = proyectar_para_custodia(d, EMP)
    rng = random.Random(1120)
    for _ in range(4):
        fuentes = list(d.fuentes)
        rng.shuffle(fuentes)
        decl = dict(reversed(d.declaracion))
        otra = construir_descriptor(Inventario(1, EMP, G1, decl, tuple(fuentes)))
        p = proyectar_para_custodia(otra, EMP)
        assert p.descriptor_cloud == base.descriptor_cloud and p.objeto_descriptor == base.objeto_descriptor


def test_descriptor_alterado_se_rechaza():
    d, _ = generacion()
    p = proyectar_para_custodia(d, EMP)
    cuerpo, sha = respuesta_cloud(p)
    alterado = p.objeto_descriptor.replace(b"gen-000001", b"gen-000009")
    assert rechazo(verificar_generacion_custodia, cuerpo, sha, alterado, EMP).codigos == {"DESCRIPTOR_ALTERADO"}
    assert rechazo(verificar_generacion_custodia, cuerpo, "0" * 64, p.objeto_descriptor, EMP).codigos \
        == {"DESCRIPTOR_ALTERADO"}
    # Un DescriptorPreparado fabricado con huella falsa no sale de la proyección.
    falso = replace(d, huella_descriptor="sha256:" + "0" * 64)
    assert rechazo(proyectar_para_custodia, falso, EMP).codigos == {"DESCRIPTOR_ALTERADO"}


def test_generacion_distinta_entre_cloud_y_motor():
    d, _ = generacion()
    p = proyectar_para_custodia(d, EMP)
    cuerpo, sha = respuesta_cloud(p)
    assert rechazo(verificar_generacion_custodia, {**cuerpo, "generacion_id": "gen-x"}, sha,
                   p.objeto_descriptor, EMP).codigos == {"GENERACION_INVALIDA"}


# ---------------------------------------------------------------- versiones
@pytest.mark.parametrize("version", [0, 2, "1", True, None])
def test_version_cloud_incompatible(version):
    d, _ = generacion()
    p = proyectar_para_custodia(d, EMP)
    cuerpo, sha = respuesta_cloud(p)
    assert rechazo(verificar_generacion_custodia, {**cuerpo, "version": version}, sha,
                   p.objeto_descriptor, EMP).codigos == {"VERSION_INCOMPATIBLE"}


def test_version_motor_incompatible_dentro_de_la_custodia():
    d, _ = generacion()
    p = proyectar_para_custodia(d, EMP)
    motor = json.loads(p.objeto_descriptor)
    motor["version_contrato"] = 3
    datos = json.dumps(motor, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    objetos = [o if o["ruta"] != RUTA_DESCRIPTOR else {"ruta": RUTA_DESCRIPTOR, "sha256": hashlib.sha256(datos).hexdigest()}
               for o in p.descriptor()["objetos"]]
    cuerpo = {**p.descriptor(), "objetos": objetos}
    assert rechazo(verificar_generacion_custodia, cuerpo, p.descriptor_sha256, datos, EMP).codigos \
        == {"VERSION_INCOMPATIBLE"}


# ---------------------------------------------------------------- inventario
def test_inventario_completo_y_exacto():
    d, _ = generacion()
    p = proyectar_para_custodia(d, EMP)
    cuerpo, sha = respuesta_cloud(p)
    assert verificar_generacion_custodia(cuerpo, sha, p.objeto_descriptor, EMP) == d
    sin_fuente = {**cuerpo, "objetos": [o for o in cuerpo["objetos"] if o["ruta"] != "operacion/ledger"]}
    assert rechazo(verificar_generacion_custodia, sin_fuente, sha, p.objeto_descriptor, EMP).codigos \
        == {"INVENTARIO_INCOMPLETO"}
    extra = {**cuerpo, "objetos": cuerpo["objetos"] + [{"ruta": "operacion/otro", "sha256": "a" * 64}]}
    assert rechazo(verificar_generacion_custodia, extra, sha, p.objeto_descriptor, EMP).codigos \
        == {"INVENTARIO_INCONSISTENTE"}
    sin_motor = {**cuerpo, "objetos": [o for o in cuerpo["objetos"] if o["ruta"] != RUTA_DESCRIPTOR]}
    assert rechazo(verificar_generacion_custodia, sin_motor, sha, p.objeto_descriptor, EMP).codigos \
        == {"FUENTE_OBLIGATORIA_AUSENTE"}
    duplicado = {**cuerpo, "objetos": cuerpo["objetos"] + [cuerpo["objetos"][0]]}
    assert rechazo(verificar_generacion_custodia, duplicado, sha, p.objeto_descriptor, EMP).codigos \
        == {"IDENTIDAD_DUPLICADA"}
    hex_malo = {**cuerpo, "objetos": [{**cuerpo["objetos"][0], "sha256": "sha256:" + "a" * 64}] + cuerpo["objetos"][1:]}
    assert rechazo(verificar_generacion_custodia, hex_malo, sha, p.objeto_descriptor, EMP).codigos \
        == {"CONTENIDO_NO_VERIFICABLE"}
    for basura in ([], {}, {**cuerpo, "objetos": []}, {**cuerpo, "objetos": [["r", "s"]]}):
        assert rechazo(verificar_generacion_custodia, basura, sha, p.objeto_descriptor, EMP).codigo in {
            "FORMATO_INVALIDO", "VERSION_INCOMPATIBLE"}


@pytest.mark.parametrize("tipo", sorted(t for t, r in TIPOS_V1.items() if r.obligatorio and t != "IDENTIDAD_EMPRESA"))
def test_fuente_obligatoria_ausente_no_llega_a_custodia(tipo):
    d, _ = generacion()
    sin = tuple(f for f in d.fuentes if f.tipo != tipo)
    decl = dict(d.declaracion)
    assert "FUENTE_OBLIGATORIA_AUSENTE" in rechazo(construir_descriptor, Inventario(1, EMP, G1, decl, sin)).codigos


def test_limite_de_objetos_de_la_custodia():
    def con_evidencia(n):
        d, _ = generacion(n_evidencia=0)
        extra = tuple(ObjetoFuente(f"evidencia/{i:04}", "EVIDENCIA_DOCUMENTAL", huella_contenido(b"%d" % i), EMP,
                                   False, len(b"%d" % i)) for i in range(n))
        decl = {**dict(d.declaracion), "EVIDENCIA_DOCUMENTAL": n}
        return construir_descriptor(Inventario(1, EMP, G1, decl, d.fuentes + extra))
    base = len(generacion(n_evidencia=0)[0].fuentes)
    justo = con_evidencia(MAX_OBJETOS_CUSTODIA - 1 - base)
    assert len(proyectar_para_custodia(justo, EMP).descriptor()["objetos"]) == MAX_OBJETOS_CUSTODIA
    assert rechazo(proyectar_para_custodia, con_evidencia(MAX_OBJETOS_CUSTODIA - base), EMP).codigos \
        == {"LIMITE_CUSTODIA"}


def test_ruta_del_descriptor_no_colisiona_con_identidades_motor():
    d, _ = generacion()
    intrusa = ObjetoFuente(RUTA_DESCRIPTOR, "CUARENTENA", huella_contenido(b"x"), EMP, False, 1)
    decl = {**dict(d.declaracion), "CUARENTENA": 1}
    assert "IDENTIDAD_INVALIDA" in rechazo(construir_descriptor, Inventario(1, EMP, G1, decl, d.fuentes + (intrusa,))).codigos


# ---------------------------------------------------------------- evidencia
def test_evidencia_y_vacio_explicito():
    d, contenidos = generacion(n_evidencia=3)
    p = proyectar_para_custodia(d, EMP)
    rutas = {o["ruta"] for o in p.descriptor()["objetos"]}
    assert {f"evidencia/guia/{900000 + i}/original" for i in range(3)} <= rutas
    vuelto = verificar_generacion_custodia(*respuesta_cloud(p), p.objeto_descriptor, EMP)
    assert [r.identidad for r in vuelto.fuente("operacion/dataset").referencias] == \
        [f"evidencia/guia/{900000 + i}/original" for i in range(3)]
    # Sin evidencia: Cloud no recibe objetos de evidencia; el 0 viaja declarado en el descriptor Motor.
    vacio, _ = generacion(n_evidencia=0)
    pv = proyectar_para_custodia(vacio, EMP)
    assert not any(o["ruta"].startswith("evidencia/") for o in pv.descriptor()["objetos"])
    leido = verificar_generacion_custodia(*respuesta_cloud(pv), pv.objeto_descriptor, EMP)
    assert dict(leido.declaracion)["EVIDENCIA_DOCUMENTAL"] == 0


def test_referencia_contradictoria_entre_cloud_y_motor():
    d, _ = generacion()
    p = proyectar_para_custodia(d, EMP)
    cuerpo, sha = respuesta_cloud(p)
    ev = "evidencia/guia/900000/original"
    cambiado = {**cuerpo, "objetos": [{**o, "sha256": "b" * 64} if o["ruta"] == ev else o for o in cuerpo["objetos"]]}
    assert rechazo(verificar_generacion_custodia, cambiado, sha, p.objeto_descriptor, EMP).codigos \
        == {"REFERENCIA_INCONSISTENTE"}
    # En el Motor, una referencia con huella distinta de la inventariada ya se rechaza al construir.
    fuentes = list(d.fuentes)
    i = next(k for k, f in enumerate(fuentes) if f.identidad == "operacion/investigacion")
    fuentes[i] = replace(fuentes[i], referencias=(Referencia(ev, "sha256:" + "b" * 64, EMP),))
    assert "REFERENCIA_INCONSISTENTE" in rechazo(
        construir_descriptor, Inventario(1, EMP, G1, dict(d.declaracion), tuple(fuentes))).codigos


# ---------------------------------------------------------------- sin escrituras
_vigilancia = {"activa": False, "eventos": []}
_PROHIBIDOS = {"open", "os.remove", "os.unlink", "os.rename", "os.replace", "os.mkdir", "os.rmdir", "os.truncate",
               "shutil.copyfile", "shutil.move", "socket.connect", "socket.getaddrinfo", "urllib.Request",
               "subprocess.Popen", "os.system", "sqlite3.connect"}


def _auditor(evento, args):
    if _vigilancia["activa"] and evento in _PROHIBIDOS:
        _vigilancia["eventos"].append((evento, repr(args)[:120]))


sys.addaudithook(_auditor)


def test_sin_escrituras_ni_lecturas_de_archivos():
    d, _ = generacion(n_evidencia=20)
    proyectar_para_custodia(d, EMP)  # calienta caches
    _vigilancia["eventos"].clear()
    _vigilancia["activa"] = True
    try:
        p = proyectar_para_custodia(d, EMP)
        verificar_generacion_custodia(*respuesta_cloud(p), p.objeto_descriptor, EMP)
        with pytest.raises(ErrorDescriptor):
            verificar_generacion_custodia(*respuesta_cloud(p), b"{}", EMP)
        with pytest.raises(ErrorDescriptor):
            proyectar_para_custodia(d, OTRA)
    finally:
        _vigilancia["activa"] = False
    assert _vigilancia["eventos"] == []


def test_modulo_sin_dependencias_de_e_s():
    arbol = ast.parse(Path(dc.__file__).read_text(encoding="utf-8"))
    importados = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            importados |= {a.name for a in nodo.names}
        elif isinstance(nodo, ast.ImportFrom):
            importados.add(nodo.module or "")
    assert importados <= {"__future__", "hashlib", "json", "re", "collections.abc", "dataclasses",
                          "atlas_core.descriptor_generacion"}
    llamadas = {n.func.id for n in ast.walk(arbol) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not {"open", "exec", "eval", "__import__", "print"} & llamadas


# ---------------------------------------------------------------- contrato cruzado
CLOUD_DIR = os.environ.get("DESCRIPTOR_CLOUD_CONTRATO_DIR", "")
NODE = shutil.which("node")
SCRIPT = Path(__file__).with_name("contrato_custodia") / "cruce_generaciones.mjs"


def _b64(datos: bytes) -> str:
    return base64.b64encode(datos).decode()


@pytest.mark.skipif(not (CLOUD_DIR and NODE and Path(CLOUD_DIR, "src", "worker.js").is_file()),
                    reason="definir DESCRIPTOR_CLOUD_CONTRATO_DIR con una copia del código Cloud y tener node")
def test_contrato_cruzado_con_worker_cloud(tmp_path):
    d1, c1 = generacion(EMP, G1)
    d2, c2 = generacion(EMP, G2, variante="-v2")
    p1, p2 = proyectar_para_custodia(d1, EMP), proyectar_para_custodia(d2, EMP)
    assert p2.anterior_id == "gen-000001"
    v2 = {**p1.descriptor(), "version": 2}
    nuevos_g2 = {k: v for k, v in c2.items() if c1.get(k) != v}
    pasos = [{"op": "adquirir", "empresa": EMP}, {"op": "adquirir", "empresa": OTRA}]
    pasos += [{"op": "subir", "empresa": EMP, "base64": _b64(b)} for b in [*c1.values(), p1.objeto_descriptor]]
    pasos += [
        {"op": "preparar", "empresa": EMP, "descriptor": p1.descriptor(), "anterior_id": p1.anterior_id, "etiqueta": "prep1"},
        {"op": "preparar", "empresa": EMP, "descriptor": p1.descriptor(), "anterior_id": None, "etiqueta": "prep1_rep"},
        {"op": "preparar", "empresa": OTRA, "descriptor": p1.descriptor(), "anterior_id": None, "etiqueta": "cruzada"},
        {"op": "preparar", "empresa": EMP, "descriptor": v2, "anterior_id": None, "etiqueta": "version2"},
        {"op": "publicar", "empresa": EMP, "generacion_id": "gen-000001", "etiqueta": "pub1"},
        {"op": "leer", "empresa": EMP, "etiqueta": "actual1"},
        {"op": "descargar", "empresa": EMP, "sha256": p1.objeto_descriptor_sha256, "etiqueta": "obj1"},
        {"op": "descargar", "empresa": OTRA, "sha256": p1.objeto_descriptor_sha256, "etiqueta": "obj1_ajena"},
        {"op": "leer", "empresa": OTRA, "etiqueta": "actual_ajena"},
        {"op": "publicar", "empresa": OTRA, "generacion_id": "gen-000001", "etiqueta": "pub_ajena"},
        # Generación 2 preparada antes de subir su evidencia nueva: no puede publicarse.
        {"op": "subir", "empresa": EMP, "base64": _b64(p2.objeto_descriptor)},
        {"op": "preparar", "empresa": EMP, "descriptor": p2.descriptor(), "anterior_id": p2.anterior_id, "etiqueta": "prep2"},
        {"op": "publicar", "empresa": EMP, "generacion_id": "gen-000002", "etiqueta": "pub2_incompleta"},
        {"op": "leer", "empresa": EMP, "etiqueta": "actual_sigue_1"},
    ]
    pasos += [{"op": "subir", "empresa": EMP, "base64": _b64(b)} for b in nuevos_g2.values()]
    pasos += [
        {"op": "publicar", "empresa": EMP, "generacion_id": "gen-000002", "etiqueta": "pub2"},
        {"op": "leer", "empresa": EMP, "etiqueta": "actual2"},
        {"op": "descargar", "empresa": EMP, "sha256": p2.objeto_descriptor_sha256, "etiqueta": "obj2"},
    ]
    archivo = tmp_path / "pasos.json"
    archivo.write_text(json.dumps({"empresas": [EMP, OTRA], "pasos": pasos}), encoding="utf-8")
    entorno = {k: v for k, v in os.environ.items() if not k.startswith(("ATLAS_", "CLOUD"))}
    salida = subprocess.run([NODE, str(SCRIPT), CLOUD_DIR, str(archivo)], capture_output=True, text=True,
                            encoding="utf-8", timeout=120, env=entorno, cwd=tmp_path)
    assert salida.returncode == 0, salida.stderr
    r = {x["etiqueta"]: x for x in json.loads(salida.stdout) if x["etiqueta"]}
    assert all(x["status"] == 200 for x in json.loads(salida.stdout) if x["op"] in ("adquirir", "subir"))

    # Cloud acepta el descriptor Motor y calcula el mismo hash canónico.
    assert r["prep1"]["status"] == 200 and r["prep1"]["body"]["estado"] == "PENDIENTE"
    assert r["prep1"]["body"]["descriptor_sha256"] == p1.descriptor_sha256
    assert r["prep1_rep"]["body"]["idempotente"] is True
    assert (r["cruzada"]["status"], r["cruzada"]["body"]["error"]) == (400, "GENERACION_INVALIDA")
    assert (r["version2"]["status"], r["version2"]["body"]["error"]) == (400, "GENERACION_INVALIDA")
    assert r["pub1"]["status"] == 200 and r["pub1"]["body"]["estado"] == "PUBLICADA"

    # Lectura: el descriptor Cloud y el objeto Motor verifican contra el contrato Motor.
    a1 = r["actual1"]["body"]
    assert a1["descriptor"] == p1.descriptor() and a1["descriptor_sha256"] == p1.descriptor_sha256
    obj1 = base64.b64decode(r["obj1"]["body"]["base64"])
    assert verificar_generacion_custodia(a1["descriptor"], a1["descriptor_sha256"], obj1, EMP) == d1

    # Aislamiento: la otra empresa no ve, no descarga ni publica.
    assert r["obj1_ajena"]["status"] == 404 and r["actual_ajena"]["status"] == 404
    assert r["pub_ajena"]["status"] in (404, 409)
    with pytest.raises(ErrorDescriptor) as exc:
        verificar_generacion_custodia(a1["descriptor"], a1["descriptor_sha256"], obj1, OTRA)
    assert exc.value.codigos == {"EMPRESA_INCORRECTA"}

    # Evidencia faltante en custodia: NO_CONFIABLE y sigue visible la generación anterior.
    assert r["prep2"]["status"] == 200 and r["prep2"]["body"]["descriptor_sha256"] == p2.descriptor_sha256
    assert r["pub2_incompleta"]["body"]["error"] == "NO_CONFIABLE"
    assert r["actual_sigue_1"]["body"]["descriptor"]["generacion_id"] == "gen-000001"
    assert r["pub2"]["status"] == 200
    a2 = r["actual2"]["body"]
    obj2 = base64.b64decode(r["obj2"]["body"]["base64"])
    vuelto = verificar_generacion_custodia(a2["descriptor"], a2["descriptor_sha256"], obj2, EMP)
    assert vuelto == d2 and vuelto.generacion.previa_id == "gen-000001" and vuelto.completitud == COMPLETITUD
