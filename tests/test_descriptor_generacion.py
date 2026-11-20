"""Descriptor preparado de generación operacional: solo datos sintéticos, sin E/S."""
from __future__ import annotations

import ast
import json
import os
import random
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from atlas_core import descriptor_generacion as dg
from atlas_core.descriptor_generacion import (
    COMPLETITUD, TIPOS_V1, ErrorDescriptor, GeneracionSolicitada, Inventario, ObjetoFuente, Referencia,
    construir_descriptor, huella_contenido, leer_descriptor, serializar_descriptor, verificar_contenido,
)

EMP = "empresa-sintetica"
OTRA = "empresa-ajena"
GEN = GeneracionSolicitada("gen-000002", 2, "gen-000001")


def obj(ident, tipo, contenido, *, empresa=EMP, obligatorio=None, referencias=(), metadatos=None, **kw):
    datos = contenido.encode("utf-8")
    return ObjetoFuente(
        identidad=ident, tipo=tipo, huella=huella_contenido(datos), empresa_id=empresa,
        obligatorio=TIPOS_V1[tipo].obligatorio if obligatorio is None else obligatorio,
        tamano=len(datos), metadatos=metadatos or {}, referencias=tuple(referencias), **kw)


def ref(o, empresa=EMP):
    return Referencia(o.identidad, o.huella, empresa)


def declarar(objetos):
    conteo = {t: 0 for t in TIPOS_V1}
    for o in objetos:
        conteo[o.tipo] = conteo.get(o.tipo, 0) + 1
    return conteo


def inventario(objetos, declaracion=None, *, empresa=EMP, generacion=GEN, version=1):
    objetos = tuple(objetos)
    return Inventario(version, empresa, generacion, declarar(objetos) if declaracion is None else declaracion, objetos)


def objetos_base(n_evidencia=1, n_cuarentena=0):
    """Generación sintética: 10 fuentes base + evidencia + cuarentena."""
    evidencia = [obj(f"evidencia/guia/{900000 + i}/original", "EVIDENCIA_DOCUMENTAL", f"pdf-sintetico-{i}",
                     obligatorio=(i == 0), metadatos={"documento": f"{900000 + i}", "formato": "pdf"})
                 for i in range(n_evidencia)]
    cuarentena = [obj(f"cuarentena/{i:04}", "CUARENTENA", f"cuarentena-{i}") for i in range(n_cuarentena)]
    dataset = obj("operacion/dataset", "DATASET_OPERACIONAL", "guia,fecha\n900000,2026-11-20\n",
                  referencias=[ref(evidencia[0])] if evidencia else [], metadatos={"filas": 1, "formato": "csv"})
    investigacion = obj("operacion/investigacion", "REGISTRO_INVESTIGACION", '{"abiertos":[]}',
                        referencias=[ref(evidencia[0])] if evidencia else [])
    base = [
        obj("empresa/identidad", "IDENTIDAD_EMPRESA", '{"empresa_id":"empresa-sintetica"}'),
        dataset,
        obj("operacion/ledger", "LEDGER_DECISIONES", "[]"),
        obj("operacion/decisiones-humanas", "DECISIONES_HUMANAS", "{}"),
        obj("operacion/bandeja", "BANDEJA_REVISION", "[]"),
        obj("operacion/agrupaciones", "AGRUPACIONES_CONFIRMADAS", "[]"),
        investigacion,
        obj("catalogos/choferes", "CATALOGO", "rut,nombre\n"),
        obj("catalogos/vehiculos", "CATALOGO", "patente,tipo\nAA0000,TRACTO\n", metadatos={"marca": "SINTETICA"}),
        obj("catalogos/asignaciones", "ASIGNACIONES", "patente,rut,desde\n"),
    ]
    return base + evidencia + cuarentena


def con_n_objetos(n):
    """Inventario completo de exactamente n objetos (n >= 10)."""
    assert n >= 10
    extra = n - 10
    return objetos_base(n_evidencia=extra - extra // 4, n_cuarentena=extra // 4)


def rechazo(inv) -> ErrorDescriptor:
    with pytest.raises(ErrorDescriptor) as exc:
        construir_descriptor(inv)
    return exc.value


# 1 -----------------------------------------------------------------------
def test_descriptor_completo_valido():
    d = construir_descriptor(inventario(objetos_base(n_evidencia=3, n_cuarentena=1)))
    assert d.empresa_id == EMP and d.generacion == GEN and d.completitud == COMPLETITUD
    assert d.huella_descriptor.startswith("sha256:") and len(d.huella_descriptor) == 71
    assert [f.identidad for f in d.fuentes] == sorted(f.identidad for f in d.fuentes)
    assert dict(d.declaracion) == {**{t: 0 for t in TIPOS_V1}, **declarar(d.fuentes)}
    cuerpo = d.como_dict()
    assert cuerpo["clase"] == "DESCRIPTOR_PREPARADO" and cuerpo["completitud"] == "PENDIENTE_PROTOCOLO_OFICIAL"
    assert cuerpo["resumen"]["objetos"] == 14 and cuerpo["resumen"]["tamanos_desconocidos"] == 0
    for f in cuerpo["fuentes"]:
        assert set(f) == {"identidad", "tipo", "huella", "tamano", "empresa_id", "relacion", "obligatorio",
                          "metadatos", "referencias"}
        assert f["empresa_id"] == EMP and f["relacion"] == "PROPIA"
    assert d.fuente("operacion/investigacion").referencias[0].identidad == "evidencia/guia/900000/original"
    assert not {"estado", "custodia", "lease", "publicacion", "version_custodia"} & set(cuerpo)


def test_catalogo_global_compartido_admitido_sin_empresa():
    objs = objetos_base() + [obj("global/geografia", "CATALOGO", "comunas", empresa=None,
                                 relacion=dg.RELACION_GLOBAL)]
    d = construir_descriptor(inventario(objs))
    assert d.fuente("global/geografia").empresa_id is None


def test_tamano_desconocido_admitido_y_contado():
    objs = objetos_base()
    objs[-1] = replace(objs[-1], tamano=None)
    d = construir_descriptor(inventario(objs))
    assert d.como_dict()["resumen"]["tamanos_desconocidos"] == 1


# 2 -----------------------------------------------------------------------
def test_orden_de_entrada_distinto_misma_huella_y_bytes():
    objs = objetos_base(n_evidencia=6, n_cuarentena=3)
    objs[1] = replace(objs[1], referencias=tuple(ref(o) for o in objs if o.tipo == "EVIDENCIA_DOCUMENTAL"
                                                 and o.obligatorio), metadatos={"z": 1, "a": "x", "m": True})
    referencia = construir_descriptor(inventario(objs))
    rng = random.Random(20261120)
    for _ in range(5):
        mezcla = [replace(o, referencias=tuple(reversed(o.referencias)),
                          metadatos=dict(reversed(list(o.metadatos.items())))) for o in objs]
        rng.shuffle(mezcla)
        decl = dict(reversed(list(declarar(objs).items())))
        d = construir_descriptor(inventario(mezcla, decl))
        assert d.huella_descriptor == referencia.huella_descriptor
        assert serializar_descriptor(d) == serializar_descriptor(referencia)


# 3 -----------------------------------------------------------------------
def test_cambio_de_contenido_cambia_huella():
    objs = objetos_base(n_evidencia=2)
    base = construir_descriptor(inventario(objs)).huella_descriptor
    cambiado = list(objs)
    cambiado[-1] = obj(objs[-1].identidad, "EVIDENCIA_DOCUMENTAL", "pdf-sintetico-modificado",
                       obligatorio=objs[-1].obligatorio, metadatos=dict(objs[-1].metadatos))
    assert construir_descriptor(inventario(cambiado)).huella_descriptor != base
    meta = list(objs)
    meta[2] = replace(objs[2], metadatos={"filas": 0})
    assert construir_descriptor(inventario(meta)).huella_descriptor != base
    otra_gen = GeneracionSolicitada("gen-000003", 3, "gen-000002")
    assert construir_descriptor(inventario(objs, generacion=otra_gen)).huella_descriptor != base


# 4 -----------------------------------------------------------------------
OBLIGATORIOS = sorted(t for t, r in TIPOS_V1.items() if r.obligatorio)


@pytest.mark.parametrize("tipo", OBLIGATORIOS)
def test_fuente_obligatoria_faltante(tipo):
    sin = [o for o in objetos_base(n_evidencia=0) if o.tipo != tipo]
    # Declarada en 0, omitida de la declaración, o declarada pero sin objeto: siempre rechazo.
    decl_cero = declarar(sin)
    decl_cero[tipo] = 0
    assert "FUENTE_OBLIGATORIA_AUSENTE" in rechazo(inventario(sin, decl_cero)).codigos
    decl_omitida = declarar(sin)
    decl_omitida.pop(tipo, None)
    assert "FUENTE_OBLIGATORIA_AUSENTE" in rechazo(inventario(sin, decl_omitida)).codigos
    decl_original = declarar(objetos_base(n_evidencia=0))
    assert "FUENTE_OBLIGATORIA_AUSENTE" in rechazo(inventario(sin, decl_original)).codigos


def test_tipo_de_archivo_unico_no_admite_dos_objetos():
    objs = objetos_base() + [obj("operacion/dataset-2", "DATASET_OPERACIONAL", "x")]
    assert "INVENTARIO_INCONSISTENTE" in rechazo(inventario(objs)).codigos


def test_objeto_de_tipo_obligatorio_marcado_opcional():
    objs = objetos_base()
    objs[2] = replace(objs[2], obligatorio=False)
    assert "OBLIGATORIEDAD_INCONSISTENTE" in rechazo(inventario(objs)).codigos


# 5 -----------------------------------------------------------------------
def test_identidad_duplicada_y_contradictoria():
    objs = objetos_base()
    dup = objs + [objs[3]]
    assert rechazo(inventario(dup, declarar(objs))).codigos == {"IDENTIDAD_DUPLICADA"}
    contra = objs + [replace(objs[3], huella=huella_contenido(b"otro"), tamano=4)]
    assert "IDENTIDAD_CONTRADICTORIA" in rechazo(inventario(contra, declarar(objs))).codigos
    otro_tipo = objs + [replace(objs[-1], tipo="CUARENTENA", obligatorio=False)]
    assert "IDENTIDAD_CONTRADICTORIA" in rechazo(inventario(otro_tipo, declarar(objs))).codigos


# 6 -----------------------------------------------------------------------
@pytest.mark.parametrize("huella", [None, "", "   "])
def test_objeto_sin_huella(huella):
    objs = objetos_base()
    objs[4] = replace(objs[4], huella=huella)
    assert "OBJETO_SIN_HUELLA" in rechazo(inventario(objs)).codigos


@pytest.mark.parametrize("cambio", [
    {"huella": "md5:" + "0" * 32}, {"huella": "sha256:" + "Z" * 64}, {"huella": "sha256:" + "A" * 64},
    {"huella": "0" * 64}, {"tamano": -1}, {"tamano": 1.5}, {"tamano": True},
    {"huella": dg.HUELLA_VACIA, "tamano": 10},
])
def test_contenido_no_verificable(cambio):
    objs = objetos_base()
    objs[4] = replace(objs[4], **cambio)
    assert "CONTENIDO_NO_VERIFICABLE" in rechazo(inventario(objs)).codigos


def test_verificar_contenido_en_memoria():
    o = obj("operacion/ledger", "LEDGER_DECISIONES", "[]")
    verificar_contenido(o, b"[]")
    with pytest.raises(ErrorDescriptor) as exc:
        verificar_contenido(o, b"[1]")
    assert exc.value.codigos == {"CONTENIDO_NO_VERIFICABLE"}
    with pytest.raises(ErrorDescriptor):
        verificar_contenido(replace(o, tamano=5), b"[]")


# 7 -----------------------------------------------------------------------
def test_empresa_incorrecta_o_ausente():
    objs = objetos_base()
    objs[5] = replace(objs[5], empresa_id=OTRA)
    assert "EMPRESA_INCORRECTA" in rechazo(inventario(objs)).codigos
    objs = objetos_base()
    objs[5] = replace(objs[5], empresa_id=None)
    assert "EMPRESA_AUSENTE" in rechazo(inventario(objs)).codigos
    for vacia in (None, "", "  "):
        assert rechazo(inventario(objetos_base(), empresa=vacia)).codigos == {"EMPRESA_AUSENTE"}
    for invalida in ("Empresa", "a", "empresa_con_guion_bajo", "../x"):
        assert rechazo(inventario(objetos_base(), empresa=invalida)).codigos == {"EMPRESA_INVALIDA"}
    objs = objetos_base()
    objs[1] = replace(objs[1], empresa_id=None, relacion=dg.RELACION_GLOBAL)
    assert "EMPRESA_INCORRECTA" in rechazo(inventario(objs)).codigos


def test_referencia_entre_empresas():
    objs = objetos_base()
    objs[1] = replace(objs[1], referencias=(ref(objs[-1], empresa=OTRA),))
    assert "REFERENCIA_ENTRE_EMPRESAS" in rechazo(inventario(objs)).codigos


# 8 -----------------------------------------------------------------------
def test_inventario_incompleto():
    objs = objetos_base(n_evidencia=5)
    menos = objs[:-1]
    assert rechazo(inventario(menos, declarar(objs))).codigos == {"INVENTARIO_INCOMPLETO"}
    omitida = declarar(objs)
    del omitida["CUARENTENA"]
    assert rechazo(inventario(objs, omitida)).codigos == {"INVENTARIO_INCOMPLETO"}
    assert "INVENTARIO_INCONSISTENTE" in rechazo(inventario(objs, declarar(menos))).codigos
    desconocido = {**declarar(objs), "OTRA_FUENTE": 1}
    assert "TIPO_DESCONOCIDO" in rechazo(inventario(objs, desconocido)).codigos
    assert "TIPO_DESCONOCIDO" in rechazo(inventario(objs + [replace(objs[-1], identidad="x/y", tipo="RARO")])).codigos
    assert "INVENTARIO_INCOMPLETO" in rechazo(inventario(objs, {})).codigos


def test_vacio_solo_como_declaracion_explicita():
    # 0 declarado en tipos que admiten vacío es válido; la omisión no.
    objs = objetos_base(n_evidencia=0)
    decl = declarar(objs)
    assert decl["EVIDENCIA_DOCUMENTAL"] == 0 and decl["CUARENTENA"] == 0
    construir_descriptor(inventario(objs, decl))


# 9 -----------------------------------------------------------------------
def test_referencia_documental_inconsistente():
    objs = objetos_base(n_evidencia=2)
    ev = objs[-1]
    casos = {
        "fuera": Referencia("evidencia/guia/999999/original", ev.huella, EMP),
        "huella": Referencia(ev.identidad, huella_contenido(b"otra version"), EMP),
        "auto": Referencia("operacion/investigacion", objs[6].huella, EMP),
    }
    for nombre, r in casos.items():
        mod = list(objs)
        mod[6] = replace(objs[6], referencias=(r,))
        assert "REFERENCIA_INCONSISTENTE" in rechazo(inventario(mod)).codigos, nombre
    mod = list(objs)
    mod[6] = replace(objs[6], referencias=(ref(ev), Referencia(ev.identidad, huella_contenido(b"z"), EMP)))
    assert "REFERENCIA_INCONSISTENTE" in rechazo(inventario(mod)).codigos
    # Una fuente obligatoria no puede depender de evidencia opcional.
    mod = list(objs)
    mod[6] = replace(objs[6], referencias=(ref(ev),))
    assert not ev.obligatorio
    assert "OBLIGATORIEDAD_INCONSISTENTE" in rechazo(inventario(mod)).codigos
    mod = list(objs)
    mod[6] = replace(objs[6], referencias=(Referencia(ev.identidad, None, EMP),))
    assert "OBJETO_SIN_HUELLA" in rechazo(inventario(mod)).codigos


# 10 ----------------------------------------------------------------------
def test_serializacion_y_lectura():
    d = construir_descriptor(inventario(objetos_base(n_evidencia=3, n_cuarentena=2)))
    datos = serializar_descriptor(d)
    leido = leer_descriptor(datos)
    assert leido == d and serializar_descriptor(leido) == datos
    texto = datos.decode("utf-8")
    assert "\\\\" not in texto and ":/" not in texto.replace("sha256:", "") and "C:" not in texto
    assert json.loads(texto)["huella_descriptor"] == d.huella_descriptor


def _reescribir(datos: bytes, cambio, recalcular=True) -> bytes:
    bruto = json.loads(datos)
    cambio(bruto)
    if recalcular:
        cuerpo = {k: v for k, v in bruto.items() if k != "huella_descriptor"}
        bruto["huella_descriptor"] = dg._huella(dg._canonico(cuerpo))
    return dg._canonico(bruto)


def test_lectura_rechaza_alteraciones_y_autodeclaracion():
    datos = serializar_descriptor(construir_descriptor(inventario(objetos_base(n_evidencia=2))))

    def alterar_huella(b):
        b["fuentes"][0]["huella"] = huella_contenido(b"alterado")
    with pytest.raises(ErrorDescriptor) as exc:
        leer_descriptor(_reescribir(datos, alterar_huella, recalcular=False))
    assert exc.value.codigos == {"DESCRIPTOR_ALTERADO"}

    for cambio in (lambda b: b.__setitem__("completitud", "COMPLETA"),
                   lambda b: b.__setitem__("estado", "COMPLETA"),
                   lambda b: b.__setitem__("custodia", {"version": 9}),
                   lambda b: b.__setitem__("clase", "GENERACION_PUBLICADA")):
        with pytest.raises(ErrorDescriptor) as exc:
            leer_descriptor(_reescribir(datos, cambio))
        assert exc.value.codigos == {"DESCRIPTOR_AUTODECLARADO"}

    no_canonico = json.dumps(json.loads(datos), indent=2, ensure_ascii=False).encode("utf-8")
    with pytest.raises(ErrorDescriptor) as exc:
        leer_descriptor(no_canonico)
    assert exc.value.codigos == {"DESCRIPTOR_ALTERADO"}
    for basura in (b"{", b"[]", "\xff".encode("latin-1"), b'{"esquema":"otro"}'):
        with pytest.raises(ErrorDescriptor) as exc:
            leer_descriptor(basura)
        assert exc.value.codigos == {"FORMATO_INVALIDO"}
    with pytest.raises(ErrorDescriptor) as exc:
        leer_descriptor(_reescribir(datos, lambda b: b.pop("resumen")))
    assert exc.value.codigos == {"FORMATO_INVALIDO"}


@pytest.mark.parametrize("meta,codigo", [
    ({"origen": "C:\\Atlas\\Proyecto-Atlas\\x.csv"}, "CAMPO_PROHIBIDO"),
    ({"origen": "G:/Mi unidad/x"}, "CAMPO_PROHIBIDO"),
    ({"origen": "/home/x"}, "CAMPO_PROHIBIDO"),
    ({"origen": "\\\\servidor\\x"}, "CAMPO_PROHIBIDO"),
    ({"origen": "https://worker.example/x"}, "CAMPO_PROHIBIDO"),
    ({"lease_token": "x"}, "CAMPO_PROHIBIDO"),
    ({"api_key": "x"}, "CAMPO_PROHIBIDO"),
    ({"completa": True}, "CAMPO_PROHIBIDO"),
    ({"estado": "COMPLETA"}, "CAMPO_PROHIBIDO"),
    ({"Mayus": 1}, "FORMATO_INVALIDO"),
    ({"lista": [1]}, "FORMATO_INVALIDO"),
])
def test_metadatos_sin_rutas_credenciales_ni_estado(meta, codigo):
    objs = objetos_base()
    objs[3] = replace(objs[3], metadatos=meta)
    assert codigo in rechazo(inventario(objs)).codigos


@pytest.mark.parametrize("ident", ["C:/Atlas/x", "/abs/x", "../x", "a//b", "Operacion/X", "a\\b", "", "a/"])
def test_identidad_no_admite_rutas_locales(ident):
    objs = objetos_base()
    objs[3] = replace(objs[3], identidad=ident)
    assert "IDENTIDAD_INVALIDA" in rechazo(inventario(objs)).codigos


@pytest.mark.parametrize("gen", [
    GeneracionSolicitada("", 1), GeneracionSolicitada("Gen", 1), GeneracionSolicitada("g", 0),
    GeneracionSolicitada("g", 2), GeneracionSolicitada("g", 1, "f"), GeneracionSolicitada("g", 2, "g"),
    GeneracionSolicitada("g", True),
])
def test_generacion_invalida(gen):
    assert "GENERACION_INVALIDA" in rechazo(inventario(objetos_base(), generacion=gen)).codigos


# 11 ----------------------------------------------------------------------
@pytest.mark.parametrize("version", [0, 3, 99, True, "1", None])
def test_version_de_inventario_incompatible(version):
    assert rechazo(inventario(objetos_base(), version=version)).codigos == {"VERSION_INCOMPATIBLE"}


@pytest.mark.parametrize("version", [0, 3, "1", None])
def test_version_de_descriptor_incompatible(version):
    datos = serializar_descriptor(construir_descriptor(inventario(objetos_base())))
    with pytest.raises(ErrorDescriptor) as exc:
        leer_descriptor(_reescribir(datos, lambda b: b.__setitem__("version_contrato", version)))
    assert exc.value.codigos == {"VERSION_INCOMPATIBLE"}


# 12 ----------------------------------------------------------------------
_vigilancia = {"activa": False, "eventos": []}
_EVENTOS_PROHIBIDOS = {
    "open", "os.remove", "os.unlink", "os.rename", "os.replace", "os.mkdir", "os.rmdir", "os.truncate",
    "os.chmod", "os.link", "os.symlink", "shutil.copyfile", "shutil.move", "shutil.rmtree",
    "socket.connect", "socket.getaddrinfo", "urllib.Request", "subprocess.Popen", "os.system",
    "os.startfile", "sqlite3.connect",
}


def _auditor(evento, args):
    if _vigilancia["activa"] and evento in _EVENTOS_PROHIBIDOS:
        _vigilancia["eventos"].append((evento, repr(args)[:120]))


sys.addaudithook(_auditor)


def test_ausencia_total_de_escrituras_y_lecturas_de_archivos():
    objs = objetos_base(n_evidencia=20, n_cuarentena=5)
    datos_previos = serializar_descriptor(construir_descriptor(inventario(objs)))  # calienta caches
    _vigilancia["eventos"].clear()
    _vigilancia["activa"] = True
    try:
        d = construir_descriptor(inventario(objs))
        datos = serializar_descriptor(d)
        leer_descriptor(datos)
        verificar_contenido(objs[2], b"[]")
        with pytest.raises(ErrorDescriptor):
            construir_descriptor(inventario(objs[:-1], declarar(objs)))
        with pytest.raises(ErrorDescriptor):
            leer_descriptor(b"{")
    finally:
        _vigilancia["activa"] = False
    assert _vigilancia["eventos"] == []
    assert datos == datos_previos


def test_modulo_sin_dependencias_de_e_s():
    fuente = Path(dg.__file__).read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    importados = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            importados |= {a.name.split(".")[0] for a in nodo.names}
        elif isinstance(nodo, ast.ImportFrom):
            importados.add((nodo.module or "").split(".")[0])
    assert importados <= {"__future__", "hashlib", "json", "re", "collections", "dataclasses", "typing"}
    llamadas = {n.func.id for n in ast.walk(arbol) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not {"open", "exec", "eval", "__import__", "print"} & llamadas


# 13 ----------------------------------------------------------------------
@pytest.mark.parametrize("n", [2, 10, 51, 100])
def test_inventarios_de_distinto_tamano(n):
    if n < 10:
        # 2 objetos no cubren las fuentes obligatorias: rechazo determinista, nunca descriptor parcial.
        objs = objetos_base(n_evidencia=0)[:n]
        error = rechazo(inventario(objs))
        assert error.codigos == {"FUENTE_OBLIGATORIA_AUSENTE"}
        faltantes = {p.sujeto for p in error.problemas}
        assert faltantes == {t for t in OBLIGATORIOS if t not in {o.tipo for o in objs}}
        assert rechazo(inventario(list(reversed(objs)))).problemas == error.problemas
        return
    objs = con_n_objetos(n)
    assert len(objs) == n
    d = construir_descriptor(inventario(objs))
    assert len(d.fuentes) == n and d.como_dict()["resumen"]["objetos"] == n
    # Un solo descriptor, sin fragmentar en lotes de custodia (50 rutas).
    datos = serializar_descriptor(d)
    assert leer_descriptor(datos) == d
    mezcla = list(objs)
    random.Random(n).shuffle(mezcla)
    assert serializar_descriptor(construir_descriptor(inventario(mezcla))) == datos
    # Quitar uno cualquiera con la declaración original siempre se rechaza.
    for i in (0, n // 2, n - 1):
        with pytest.raises(ErrorDescriptor):
            construir_descriptor(inventario(objs[:i] + objs[i + 1:], declarar(objs)))
