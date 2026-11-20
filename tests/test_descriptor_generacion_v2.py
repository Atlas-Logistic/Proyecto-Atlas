"""Descriptor de generación v2: decisiones humanas, derivación de asignaciones y evidencia.

Solo datos sintéticos; sin E/S salvo la lectura del fixture v1 y, opcionalmente,
la prueba cruzada contra una copia local del Worker Cloud.
"""
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

from atlas_core import descriptor_generacion as dg
from atlas_core.descriptor_custodia import RUTA_DESCRIPTOR, proyectar_para_custodia, verificar_generacion_custodia
from atlas_core.descriptor_generacion import (
    COMPLETITUD, ErrorDescriptor, GeneracionSolicitada, Inventario, ObjetoFuente, Referencia, construir_descriptor,
    huella_contenido, identidad_evidencia, leer_descriptor, serializar_descriptor,
)

EMP = "empresa-sintetica"
OTRA = "empresa-ajena"
MBT = "empresa-prueba-javier"
G1 = GeneracionSolicitada("gen-000001", 1)
G2 = GeneracionSolicitada("gen-000002", 2, "gen-000001")
FIXTURE_V1 = Path(__file__).with_name("fixtures") / "descriptor_generacion_v1.json"


def _obj(ident, tipo, texto, empresa=EMP, *, rol=None, documento=None, obligatorio=True, refs=(), meta=None,
         global_=False):
    datos = texto.encode("utf-8")
    return ObjetoFuente(ident, tipo, huella_contenido(datos), None if global_ else empresa, obligatorio, len(datos),
                        meta or {}, tuple(refs), dg.RELACION_GLOBAL if global_ else dg.RELACION_PROPIA,
                        rol=rol, documento=documento)


def evidencia(documento, rol, texto, empresa=EMP, *, obligatorio=False, meta=None):
    huella = huella_contenido(texto.encode("utf-8"))
    return replace(_obj("x", "EVIDENCIA_DOCUMENTAL", texto, empresa, rol=rol, documento=documento,
                        obligatorio=obligatorio, meta=meta),
                   identidad=identidad_evidencia(documento, rol, huella))


def objetos_v2(empresa=EMP, *, con_evidencia=True):
    """Generación v2 sintética: todas las fuentes reales y evidencia con todos los roles."""
    ev = []
    if con_evidencia:
        ev = [
            evidencia("Guia 485190.JPG", "original", "foto-original", empresa, obligatorio=True,
                      meta={"numero_guia": "485190"}),
            evidencia("Guia 485190.JPG", "original", "foto-relectura", empresa),   # segunda foto del mismo documento
            evidencia("Guia 485190.JPG", "orientada", "foto-orientada", empresa),
            evidencia("lote.pdf", "pdf", "%PDF-sintetico", empresa),
            evidencia("lote.pdf::pagina=0001", "pdf-pagina", "png-pagina-1", empresa),
            evidencia("lote.pdf::pagina=0001", "pdf-texto", "texto-pagina-1", empresa),
            _obj("evidencia/registro-relecturas", "EVIDENCIA_DOCUMENTAL", '{"relecturas":[]}', empresa,
                 rol="registro-relecturas", obligatorio=False),
            _obj("evidencia/pdf/evidencias-adicionales", "EVIDENCIA_DOCUMENTAL", '{"asociaciones":[]}', empresa,
                 rol="registro-evidencias-adicionales", obligatorio=False),
        ]
    refs = [Referencia(ev[0].identidad, ev[0].huella, empresa)] if ev else []
    base = [
        _obj("operacion/dataset", "DATASET_OPERACIONAL", "archivo;numero_guia\nGuia 485190.JPG;485190\n", empresa,
             refs=refs),
        _obj("operacion/ledger", "LEDGER_DECISIONES", '{"aplicaciones":[]}', empresa),
        _obj("operacion/acciones-operacionales", "DECISIONES_HUMANAS", '{"previews":{}}', empresa,
             rol="acciones_operacionales"),
        _obj("operacion/operaciones-conversacionales", "DECISIONES_HUMANAS", '{"operaciones":[]}', empresa,
             rol="operaciones_conversacionales"),
        _obj("operacion/bandeja", "BANDEJA_REVISION", '{"decisiones":[]}', empresa),
        _obj("operacion/agrupaciones", "AGRUPACIONES_CONFIRMADAS", '{"agrupaciones":[]}', empresa),
        _obj("operacion/investigacion", "REGISTRO_INVESTIGACION", '{"registros":[]}', empresa),
        _obj("catalogos/choferes", "CATALOGO", "{}", empresa, rol="choferes"),
        _obj("catalogos/vehiculos", "CATALOGO", '{"vehiculos":[]}', empresa, rol="vehiculos"),
        _obj("global/geografia-chile", "CATALOGO", "{}", rol="geografia_chile", global_=True),
    ]
    if empresa not in dg.EMPRESAS_SIN_MARCA:
        base.append(_obj("empresa/identidad", "IDENTIDAD_EMPRESA", json.dumps({"cloud_id": empresa}), empresa))
    return base + ev


DERIV = {"ASIGNACIONES": {"vehiculos": "catalogos/vehiculos", "choferes": "catalogos/choferes",
                          "ledger": "operacion/ledger"}}


def declarar(objetos):
    conteo = {t: 0 for t in dg.TIPOS_V2}
    for o in objetos:
        conteo[o.tipo] = conteo.get(o.tipo, 0) + 1
    return conteo


def inv(objetos, *, empresa=EMP, gen=G1, derivaciones=None, declaracion=None, version=2):
    objetos = tuple(objetos)
    return Inventario(version, empresa, gen, declarar(objetos) if declaracion is None else declaracion, objetos,
                      DERIV if derivaciones is None else derivaciones)


def rechazo(inventario) -> ErrorDescriptor:
    with pytest.raises(ErrorDescriptor) as exc:
        construir_descriptor(inventario)
    return exc.value


def pares(error):
    return {(p.codigo, p.sujeto) for p in error.problemas}


# 1-2 --------------------------------------------------------- decisiones humanas
def test_descriptor_v2_completo_con_dos_registros_humanos():
    d = construir_descriptor(inv(objetos_v2()))
    assert d.version_contrato == dg.VERSION_CONTRATO == 2 and d.completitud == COMPLETITUD
    humanos = [f for f in d.fuentes if f.tipo == "DECISIONES_HUMANAS"]
    assert {f.rol for f in humanos} == dg.ROLES_DECISIONES_HUMANAS
    assert len({f.identidad for f in humanos}) == 2 and len({f.huella for f in humanos}) == 2
    assert dict(d.declaracion)["DECISIONES_HUMANAS"] == 2
    assert leer_descriptor(serializar_descriptor(d)) == d


@pytest.mark.parametrize("rol", sorted(dg.ROLES_DECISIONES_HUMANAS))
def test_falta_cualquier_registro_humano(rol):
    objs = [o for o in objetos_v2() if o.rol != rol]
    error = rechazo(inv(objs))                         # declaración real: 1
    assert ("FUENTE_OBLIGATORIA_AUSENTE", f"DECISIONES_HUMANAS:{rol}") in pares(error)
    assert ("FUENTE_OBLIGATORIA_AUSENTE", "DECISIONES_HUMANAS") in pares(error)
    error = rechazo(inv(objs, declaracion=declarar(objetos_v2())))  # declarados 2, presente 1
    assert ("FUENTE_OBLIGATORIA_AUSENTE", f"DECISIONES_HUMANAS:{rol}") in pares(error)


def test_registros_humanos_no_se_fusionan_ni_se_inventan():
    objs = objetos_v2()
    i = next(k for k, o in enumerate(objs) if o.rol == "operaciones_conversacionales")
    mismo_rol = list(objs)
    mismo_rol[i] = replace(objs[i], rol="acciones_operacionales")
    error = rechazo(inv(mismo_rol))
    assert "IDENTIDAD_CONTRADICTORIA" in error.codigos
    assert ("FUENTE_OBLIGATORIA_AUSENTE", "DECISIONES_HUMANAS:operaciones_conversacionales") in pares(error)
    # Un tercer registro (p. ej. una "asignación confirmada" artificial) no cabe.
    tercero = objs + [_obj("operacion/asignaciones-confirmadas", "DECISIONES_HUMANAS", "{}", rol="asignaciones")]
    error = rechazo(inv(tercero))
    assert {"ROL_INVALIDO", "INVENTARIO_INCONSISTENTE"} <= error.codigos
    sin_rol = list(objs)
    sin_rol[i] = replace(objs[i], rol=None)
    assert "ROL_INVALIDO" in rechazo(inv(sin_rol)).codigos


# 3-4 --------------------------------------------------------- asignaciones
def test_derivacion_de_asignaciones_completa_sin_objeto_propio():
    d = construir_descriptor(inv(objetos_v2()))
    fuentes = d.derivacion("ASIGNACIONES")
    assert {r: o.identidad for r, o in fuentes.items()} == DERIV["ASIGNACIONES"]
    assert fuentes["vehiculos"].rol == "vehiculos" and fuentes["ledger"].tipo == "LEDGER_DECISIONES"
    assert not any("asignac" in f.identidad or f.tipo == "ASIGNACIONES" for f in d.fuentes)
    cuerpo = json.loads(serializar_descriptor(d))
    assert cuerpo["derivaciones"] == DERIV
    assert "ASIGNACIONES" not in cuerpo["declaracion"]


@pytest.mark.parametrize("derivaciones,codigo,sujeto", [
    ({}, "DEPENDENCIA_INCOMPLETA", "ASIGNACIONES"),
    ({"ASIGNACIONES": {"vehiculos": "catalogos/vehiculos", "choferes": "catalogos/choferes"}},
     "DEPENDENCIA_INCOMPLETA", "ASIGNACIONES.ledger"),
    ({"ASIGNACIONES": {**DERIV["ASIGNACIONES"], "vehiculos": "catalogos/no-existe"}},
     "DEPENDENCIA_INCOMPLETA", "ASIGNACIONES.vehiculos"),
    ({"ASIGNACIONES": {**DERIV["ASIGNACIONES"], "vehiculos": "catalogos/choferes"}},
     "DEPENDENCIA_INCOMPLETA", "ASIGNACIONES.vehiculos"),
    # Una asignación nunca se apoya en un registro de confirmaciones humanas.
    ({"ASIGNACIONES": {**DERIV["ASIGNACIONES"], "ledger": "operacion/acciones-operacionales"}},
     "DEPENDENCIA_INCOMPLETA", "ASIGNACIONES.ledger"),
    ({"ASIGNACIONES": {**DERIV["ASIGNACIONES"], "extra": "operacion/dataset"}},
     "FORMATO_INVALIDO", "ASIGNACIONES.extra"),
    ({**DERIV, "OTRA": {}}, "TIPO_DESCONOCIDO", "OTRA"),
])
def test_dependencias_incompletas(derivaciones, codigo, sujeto):
    assert (codigo, sujeto) in pares(rechazo(inv(objetos_v2(), derivaciones=derivaciones)))


def test_dependencias_de_otra_empresa_o_globales():
    objs = objetos_v2()
    global_vehiculos = [o for o in objs if o.identidad != "catalogos/vehiculos"] + [
        _obj("global/vehiculos", "CATALOGO", "{}", rol="vehiculos", global_=True)]
    deriv = {"ASIGNACIONES": {**DERIV["ASIGNACIONES"], "vehiculos": "global/vehiculos"}}
    assert ("EMPRESA_INCORRECTA", "ASIGNACIONES.vehiculos") in pares(rechazo(inv(global_vehiculos, derivaciones=deriv)))


def test_asignaciones_no_es_tipo_en_v2():
    objs = objetos_v2() + [_obj("catalogos/asignaciones", "ASIGNACIONES", "patente,rut\n")]
    error = rechazo(inv(objs, declaracion={**declarar(objetos_v2()), "ASIGNACIONES": 1}))
    assert ("TIPO_DESCONOCIDO", "catalogos/asignaciones") in pares(error)
    assert ("TIPO_DESCONOCIDO", "ASIGNACIONES") in pares(error)


# 5-6 --------------------------------------------------------- evidencia e identidades
def test_evidencias_multiples_con_roles_distintos():
    d = construir_descriptor(inv(objetos_v2()))
    ev = [f for f in d.fuentes if f.tipo == "EVIDENCIA_DOCUMENTAL"]
    assert {f.rol for f in ev} == dg.ROLES_EVIDENCIA_DOCUMENTO | set(dg.ROLES_EVIDENCIA_INDICE)
    originales = [f for f in ev if f.rol == "original"]
    assert len(originales) == 2 and len({f.identidad for f in originales}) == 2  # relectura sin colisión
    for f in ev:
        if f.rol in dg.ROLES_EVIDENCIA_DOCUMENTO:
            assert f.identidad == identidad_evidencia(f.documento, f.rol, f.huella)
            assert f.identidad.split("/")[1] == hashlib.sha256(f.documento.encode()).hexdigest()
            assert f.identidad.endswith(f.huella.removeprefix("sha256:"))
        else:
            assert f.documento is None and f.identidad == dg.ROLES_EVIDENCIA_INDICE[f.rol]
    assert any(f.documento == "lote.pdf::pagina=0001" for f in ev)  # el archivo real se conserva


def test_evidencia_sin_identidad_verificable():
    objs = objetos_v2()
    k = next(i for i, o in enumerate(objs) if o.rol == "orientada")
    casos = {
        "contenido_cambiado": replace(objs[k], huella=huella_contenido(b"otra"), tamano=4),
        "documento_cambiado": replace(objs[k], documento="Otra guia.JPG"),
        "rol_cambiado": replace(objs[k], rol="original"),
        "identidad_por_nombre": replace(objs[k], identidad="evidencia/guia-485190/orientada"),
        "sin_documento": replace(objs[k], documento=None),
        "documento_ruta_absoluta": replace(objs[k], documento="C:\\Atlas\\entradas\\g.jpg"),
        "documento_con_control": replace(objs[k], documento="g\n.jpg"),
    }
    for nombre, malo in casos.items():
        mod = list(objs)
        mod[k] = malo
        assert "EVIDENCIA_NO_VERIFICABLE" in rechazo(inv(mod)).codigos, nombre
    mod = list(objs)
    mod[k] = replace(objs[k], rol=None)
    assert "ROL_INVALIDO" in rechazo(inv(mod)).codigos
    idx = next(i for i, o in enumerate(objs) if o.rol == "registro-relecturas")
    for malo, codigo in ((replace(objs[idx], documento="x.jpg"), "FORMATO_INVALIDO"),
                         (replace(objs[idx], identidad="evidencia/otro-registro"), "EVIDENCIA_NO_VERIFICABLE")):
        mod = list(objs)
        mod[idx] = malo
        assert codigo in rechazo(inv(mod)).codigos


def test_identidades_repetidas_o_contradictorias():
    objs = objetos_v2()
    ev = next(o for o in objs if o.rol == "pdf")
    assert ("IDENTIDAD_DUPLICADA", ev.identidad) in pares(rechazo(inv(objs + [ev], declaracion=declarar(objs))))
    otro = replace(ev, metadatos={"nota": "distinta"})
    assert ("IDENTIDAD_CONTRADICTORIA", ev.identidad) in pares(rechazo(inv(objs + [otro], declaracion=declarar(objs))))
    dos_vehiculos = objs + [_obj("catalogos/vehiculos-2", "CATALOGO", "{}", rol="vehiculos")]
    assert ("IDENTIDAD_CONTRADICTORIA", "CATALOGO:vehiculos") in pares(rechazo(inv(dos_vehiculos)))
    i = next(k for k, o in enumerate(objs) if o.identidad == "catalogos/choferes")
    sin_rol = list(objs)
    sin_rol[i] = replace(objs[i], rol=None)
    assert "ROL_INVALIDO" in rechazo(inv(sin_rol)).codigos
    j = next(k for k, o in enumerate(objs) if o.tipo == "DATASET_OPERACIONAL")
    for malo, codigo in ((replace(objs[j], rol="dataset"), "ROL_INVALIDO"),
                         (replace(objs[j], documento="x.jpg"), "FORMATO_INVALIDO")):
        mod = list(objs)
        mod[j] = malo
        assert codigo in rechazo(inv(mod)).codigos


# 7 ----------------------------------------------------------- empresas
def test_empresas_cruzadas():
    objs = objetos_v2()
    for pred in (lambda o: o.rol == "pdf-pagina", lambda o: o.rol == "operaciones_conversacionales"):
        k = next(i for i, o in enumerate(objs) if pred(o))
        mod = list(objs)
        mod[k] = replace(objs[k], empresa_id=OTRA)
        assert ("EMPRESA_INCORRECTA", objs[k].identidad) in pares(rechazo(inv(mod)))
    ajenos = objetos_v2(OTRA)
    assert "EMPRESA_INCORRECTA" in rechazo(inv(ajenos)).codigos


def test_mbt_identidad_canonica():
    d = construir_descriptor(inv(objetos_v2(MBT), empresa=MBT))
    assert dict(d.declaracion)["IDENTIDAD_EMPRESA"] == 0
    assert rechazo(inv(objetos_v2(MBT), empresa="mbt")).codigos == {"EMPRESA_INVALIDA"}
    con_marca = objetos_v2(MBT) + [_obj("empresa/identidad", "IDENTIDAD_EMPRESA", "{}", MBT)]
    assert "EMPRESA_INCORRECTA" in rechazo(inv(con_marca, empresa=MBT)).codigos


# 8 ----------------------------------------------------------- determinismo
def test_determinismo_v2():
    base = construir_descriptor(inv(objetos_v2(), gen=G2))
    datos = serializar_descriptor(base)
    rng = random.Random(1120)
    for _ in range(5):
        objs = objetos_v2()
        rng.shuffle(objs)
        deriv = {"ASIGNACIONES": dict(reversed(list(DERIV["ASIGNACIONES"].items())))}
        decl = dict(reversed(list(declarar(objs).items())))
        d = construir_descriptor(inv(objs, gen=G2, derivaciones=deriv, declaracion=decl))
        assert serializar_descriptor(d) == datos and d.huella_descriptor == base.huella_descriptor
    otra = objetos_v2()
    k = next(i for i, o in enumerate(otra) if o.rol == "pdf-texto")
    otra[k] = evidencia("lote.pdf::pagina=0002", "pdf-texto", "texto-pagina-1")
    assert construir_descriptor(inv(otra, gen=G2)).huella_descriptor != base.huella_descriptor


# 9-10 -------------------------------------------------------- versiones
def _casos_v1():
    return json.loads(FIXTURE_V1.read_text(encoding="utf-8"))["casos"]


def test_lectura_compatible_de_descriptores_v1():
    for caso in _casos_v1():
        datos = caso["serializado"].encode("utf-8")
        d = leer_descriptor(datos)
        assert d.version_contrato == 1 and d.huella_descriptor == caso["huella_descriptor"]
        assert serializar_descriptor(d) == datos      # mismos bytes: nada se reinterpreta
        assert d.derivaciones == () and d.empresa_id == caso["empresa_id"]
        assert dict(d.declaracion)["DECISIONES_HUMANAS"] == 1 and "ASIGNACIONES" in dict(d.declaracion)
        assert all(f.rol is None and f.documento is None for f in d.fuentes)
        # El mismo inventario no cumple v2: no se promueve en silencio.
        with pytest.raises(ErrorDescriptor):
            construir_descriptor(Inventario(2, d.empresa_id, d.generacion, dict(d.declaracion), d.fuentes, DERIV))


def _reescribir(datos: bytes, cambio) -> bytes:
    bruto = json.loads(datos)
    cambio(bruto)
    cuerpo = {k: v for k, v in bruto.items() if k != "huella_descriptor"}
    bruto["huella_descriptor"] = dg._huella(dg._canonico(cuerpo))
    return dg._canonico(bruto)


def test_v1_no_se_convierte_en_v2():
    datos = _casos_v1()[0]["serializado"].encode("utf-8")
    for cambio in (lambda b: b.__setitem__("version_contrato", 2),
                   lambda b: b.__setitem__("derivaciones", DERIV)):
        with pytest.raises(ErrorDescriptor) as exc:
            leer_descriptor(_reescribir(datos, cambio))
        assert exc.value.codigos == {"FORMATO_INVALIDO"}
    v1_con_rol = [replace(o, rol="vehiculos") if o.identidad == "catalogos/vehiculos" else o
                  for o in leer_descriptor(datos).fuentes]
    d = leer_descriptor(datos)
    assert "FORMATO_INVALIDO" in rechazo(Inventario(1, d.empresa_id, d.generacion, dict(d.declaracion),
                                                    tuple(v1_con_rol))).codigos
    assert "FORMATO_INVALIDO" in rechazo(Inventario(1, d.empresa_id, d.generacion, dict(d.declaracion),
                                                    d.fuentes, DERIV)).codigos


@pytest.mark.parametrize("version", [0, 3, 99, True, "2", None])
def test_versiones_desconocidas(version):
    assert rechazo(inv(objetos_v2(), version=version)).codigos == {"VERSION_INCOMPATIBLE"}
    datos = serializar_descriptor(construir_descriptor(inv(objetos_v2())))
    with pytest.raises(ErrorDescriptor) as exc:
        leer_descriptor(_reescribir(datos, lambda b: b.__setitem__("version_contrato", version)))
    assert exc.value.codigos == {"VERSION_INCOMPATIBLE"}


def test_v2_conserva_alteracion_y_autodeclaracion():
    datos = serializar_descriptor(construir_descriptor(inv(objetos_v2())))
    for cambio, codigo in ((lambda b: b.__setitem__("completitud", "COMPLETA"), "DESCRIPTOR_AUTODECLARADO"),
                           (lambda b: b.__setitem__("estado", "PUBLICADA"), "DESCRIPTOR_AUTODECLARADO")):
        with pytest.raises(ErrorDescriptor) as exc:
            leer_descriptor(_reescribir(datos, cambio))
        assert exc.value.codigos == {codigo}
    bruto = json.loads(datos)
    bruto["derivaciones"]["ASIGNACIONES"]["ledger"] = "operacion/dataset"   # sin recalcular huella
    with pytest.raises(ErrorDescriptor) as exc:
        leer_descriptor(dg._canonico(bruto))
    assert exc.value.codigos == {"DEPENDENCIA_INCOMPLETA"}


# 11 ---------------------------------------------------------- adaptador Cloud
_ID_SEGURO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _ruta_estado_valida(ruta: str) -> bool:  # src/worker.js rutaEstadoValida (61c2872)
    if not ruta or len(ruta) > 512 or re.search(r"[\x00-\x08\x0B-\x1F\x7F]", ruta):
        return False
    if ruta.startswith("/") or "\\" in ruta or ":" in ruta:
        return False
    return all(p and p not in (".", "..") for p in ruta.split("/"))


@pytest.mark.parametrize("empresa", [EMP, MBT])
def test_adaptacion_al_contrato_cloud_vigente(empresa):
    d = construir_descriptor(inv(objetos_v2(empresa), empresa=empresa, gen=G2))
    p = proyectar_para_custodia(d, empresa)
    cuerpo = p.descriptor()
    assert list(cuerpo) == ["version", "empresa_id", "generacion_id", "objetos"] and cuerpo["version"] == 1
    rutas = {o["ruta"]: o["sha256"] for o in cuerpo["objetos"]}
    assert set(rutas) == {f.identidad for f in d.fuentes} | {RUTA_DESCRIPTOR}
    assert all(_ruta_estado_valida(r) for r in rutas) and _ID_SEGURO.fullmatch(cuerpo["generacion_id"])
    assert all(rutas[f.identidad] == f.huella.removeprefix("sha256:") for f in d.fuentes)
    assert p.anterior_id == "gen-000001"
    vuelto = verificar_generacion_custodia(cuerpo, p.descriptor_sha256, p.objeto_descriptor, empresa)
    assert vuelto == d and vuelto.version_contrato == 2


CLOUD_DIR = os.environ.get("DESCRIPTOR_CLOUD_CONTRATO_DIR", "")
NODE = shutil.which("node")
SCRIPT = Path(__file__).with_name("contrato_custodia") / "cruce_generaciones.mjs"


@pytest.mark.skipif(not (CLOUD_DIR and NODE and Path(CLOUD_DIR, "src", "worker.js").is_file()),
                    reason="definir DESCRIPTOR_CLOUD_CONTRATO_DIR con una copia del código Cloud y tener node")
def test_contrato_cruzado_v2_con_worker_cloud(tmp_path):
    objs = objetos_v2()
    d = construir_descriptor(inv(objs))
    p = proyectar_para_custodia(d, EMP)
    # Bytes sintéticos de objetos_v2, indexados por huella para subirlos a la custodia en memoria.
    universo = [b"foto-original", b"foto-relectura", b"foto-orientada", b"%PDF-sintetico", b"png-pagina-1",
                b"texto-pagina-1", b'{"relecturas":[]}', b'{"asociaciones":[]}',
                b"archivo;numero_guia\nGuia 485190.JPG;485190\n", b'{"aplicaciones":[]}', b'{"previews":{}}',
                b'{"operaciones":[]}', b'{"decisiones":[]}', b'{"agrupaciones":[]}', b'{"registros":[]}', b"{}",
                b'{"vehiculos":[]}', json.dumps({"cloud_id": EMP}).encode()]
    por_huella = {huella_contenido(b): b for b in universo}
    assert all(o.huella in por_huella for o in objs)
    pasos = [{"op": "adquirir", "empresa": EMP}]
    pasos += [{"op": "subir", "empresa": EMP, "base64": base64.b64encode(b).decode()}
              for b in [*por_huella.values(), p.objeto_descriptor]]
    pasos += [
        {"op": "preparar", "empresa": EMP, "descriptor": p.descriptor(), "anterior_id": None, "etiqueta": "prep"},
        {"op": "publicar", "empresa": EMP, "generacion_id": d.generacion.generacion_id, "etiqueta": "pub"},
        {"op": "leer", "empresa": EMP, "etiqueta": "actual"},
        {"op": "descargar", "empresa": EMP, "sha256": p.objeto_descriptor_sha256, "etiqueta": "obj"},
    ]
    archivo = tmp_path / "pasos.json"
    archivo.write_text(json.dumps({"empresas": [EMP], "pasos": pasos}), encoding="utf-8")
    entorno = {k: v for k, v in os.environ.items() if not k.startswith(("ATLAS_", "CLOUD"))}
    salida = subprocess.run([NODE, str(SCRIPT), CLOUD_DIR, str(archivo)], capture_output=True, text=True,
                            encoding="utf-8", timeout=120, env=entorno, cwd=tmp_path)
    assert salida.returncode == 0, salida.stderr
    r = {x["etiqueta"]: x for x in json.loads(salida.stdout) if x["etiqueta"]}
    assert r["prep"]["status"] == 200 and r["prep"]["body"]["descriptor_sha256"] == p.descriptor_sha256
    assert r["pub"]["status"] == 200
    actual = r["actual"]["body"]
    obj = base64.b64decode(r["obj"]["body"]["base64"])
    vuelto = verificar_generacion_custodia(actual["descriptor"], actual["descriptor_sha256"], obj, EMP)
    assert vuelto == d and vuelto.version_contrato == 2


# 12 ---------------------------------------------------------- sin E/S
_vigilancia = {"activa": False, "eventos": []}
_PROHIBIDOS = {"open", "os.remove", "os.unlink", "os.rename", "os.replace", "os.mkdir", "os.rmdir", "os.truncate",
               "shutil.copyfile", "shutil.move", "socket.connect", "socket.getaddrinfo", "urllib.Request",
               "subprocess.Popen", "os.system", "sqlite3.connect"}


def _auditor(evento, args):
    if _vigilancia["activa"] and evento in _PROHIBIDOS:
        _vigilancia["eventos"].append((evento, repr(args)[:120]))


sys.addaudithook(_auditor)


def test_sin_escrituras_ni_conexiones():
    objs = objetos_v2()
    v1 = _casos_v1()[0]["serializado"].encode("utf-8")
    construir_descriptor(inv(objs))  # calienta caches
    _vigilancia["eventos"].clear()
    _vigilancia["activa"] = True
    try:
        d = construir_descriptor(inv(objs))
        datos = serializar_descriptor(d)
        leer_descriptor(datos)
        leer_descriptor(v1)
        p = proyectar_para_custodia(d, EMP)
        verificar_generacion_custodia(p.descriptor(), p.descriptor_sha256, p.objeto_descriptor, EMP)
        with pytest.raises(ErrorDescriptor):
            construir_descriptor(inv(objs, derivaciones={}))
    finally:
        _vigilancia["activa"] = False
    assert _vigilancia["eventos"] == []


def test_modulo_sin_dependencias_de_e_s():
    arbol = ast.parse(Path(dg.__file__).read_text(encoding="utf-8"))
    importados = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            importados |= {a.name.split(".")[0] for a in nodo.names}
        elif isinstance(nodo, ast.ImportFrom):
            importados.add((nodo.module or "").split(".")[0])
    assert importados <= {"__future__", "hashlib", "json", "re", "collections", "dataclasses", "typing"}
    llamadas = {n.func.id for n in ast.walk(arbol) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not {"open", "exec", "eval", "__import__", "print"} & llamadas
