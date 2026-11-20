"""Validación cruzada del descriptor Motor v2 (a9b5649) contra el contrato Cloud v2 (79de408).

Tres grupos, distinguidos en el nombre de cada prueba:

* ``test_oficial_*``: bytes y resultados publicados por Codex en
  ``tests/contrato_cloud_v2/vectores_cloud_v2.json`` y el fixture Motor v2
  (copias verificadas contra los blobs de Atlas-Mobile-Cloud 79de408).
* ``test_cruzado_*``: el modelo Node original de Codex, evaluado sin modificar
  sobre una copia ``git archive`` (``DESCRIPTOR_CLOUD_V2_DIR``), comparado con
  el verificador de referencia Python sobre las mismas entradas.
* ``test_sintetico_*``: casos adicionales sin resultado publicado.

``conciliar_motor`` es una especificación ejecutable de las reglas mínimas que
el adaptador v2 de ``descriptor_custodia.py`` deberá cumplir. No es el
adaptador y no se importa desde ``atlas_core``. Sin E/S salvo leer los vectores.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

import test_descriptor_generacion_v2 as v2
from atlas_core import descriptor_custodia as dc
from atlas_core.descriptor_generacion import (
    DescriptorPreparado, ErrorDescriptor, GeneracionSolicitada, construir_descriptor, leer_descriptor,
    serializar_descriptor,
)
from contrato_cloud_v2 import referencia_cloud_v2 as ref
from contrato_cloud_v2.referencia_cloud_v2 import ErrorCloudV2, RUTA_DESCRIPTOR

DIR = Path(__file__).with_name("contrato_cloud_v2")
VECTORES = DIR / "vectores_cloud_v2.json"
FIXTURE_MOTOR = DIR / "fixture_motor_v2_sintetico.json"
# Blobs git en Atlas-Mobile-Cloud 79de40805cc746254ef09e9a80e8b5e2ab2944fc.
BLOB_VECTORES = "d1eede606da9128e357413ec1167fbf9089a59a9"
BLOB_FIXTURE = "e99aa4e2c25db8262e4a311e3a2607cbaa3e95b3"
SHA_FIXTURE = "e11f377991aa669048b0805be838233d452e961a3d04864bb483fd7e3d532932"
EMP = "empresa-sintetica"
TAMANOS = (1, 100, 101, 999, 1000, 1001, 2500, 5000)


def _blob(datos: bytes) -> str:
    return hashlib.sha1(b"blob %d\x00" % len(datos) + datos).hexdigest()


def _vectores() -> dict:
    return json.loads(VECTORES.read_text(encoding="utf-8"))


def _sha(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _codigo(fn, *args, **kwargs) -> str:
    with pytest.raises(ErrorCloudV2) as exc:
        fn(*args, **kwargs)
    return exc.value.codigo


# ------------------------------------------------- especificación del adaptador
def proyectar_motor(descriptor: DescriptorPreparado, empresa: str) -> tuple[ref.GeneracionV2, bytes]:
    """Motor v2 -> Cloud v2: fuentes exactas + descriptor como objeto reservado."""
    datos = serializar_descriptor(descriptor)
    motor = leer_descriptor(datos)
    assert motor.empresa_id == empresa
    objetos = [(f.identidad, f.huella.removeprefix("sha256:")) for f in motor.fuentes]
    objetos.append((RUTA_DESCRIPTOR, ref.sha256_hex(datos)))
    return ref.construir(empresa, motor.generacion.generacion_id, motor.generacion.previa_id, objetos), datos


def conciliar_motor(gen: ref.GeneracionV2, datos_descriptor: bytes, empresa: str) -> DescriptorPreparado:
    """Reglas mínimas tras ``ref.verificar``: bytes, semántica Motor, identidad y exactitud."""
    c = gen.cabecera
    if ref.sha256_hex(datos_descriptor) != c["sha_descriptor_motor"]:
        raise ErrorCloudV2("DESCRIPTOR_ALTERADO", RUTA_DESCRIPTOR)
    motor = leer_descriptor(datos_descriptor)          # ErrorDescriptor si el Motor es inválido
    if motor.empresa_id != empresa:
        raise ErrorCloudV2("EMPRESA_INCORRECTA", motor.empresa_id)
    if motor.generacion.generacion_id != c["generacion_id"]:
        raise ErrorCloudV2("GENERACION_INCORRECTA", motor.generacion.generacion_id)
    if motor.generacion.previa_id != c["anterior_id"]:   # regla nueva respecto de v1
        raise ErrorCloudV2("ANTERIOR_INCORRECTA", f"{motor.generacion.previa_id!r} != {c['anterior_id']!r}")
    esperados = {f.identidad: f.huella.removeprefix("sha256:") for f in motor.fuentes}
    recibidos = {r: s for r, s in gen.objetos if r != RUTA_DESCRIPTOR}
    if esperados.keys() - recibidos.keys():
        raise ErrorCloudV2("INVENTARIO_INCOMPLETO", sorted(esperados.keys() - recibidos.keys())[0])
    if recibidos.keys() - esperados.keys():
        raise ErrorCloudV2("INVENTARIO_INCONSISTENTE", sorted(recibidos.keys() - esperados.keys())[0])
    for ruta, sha in esperados.items():
        if recibidos[ruta] != sha:
            raise ErrorCloudV2("INVENTARIO_INCONSISTENTE", ruta)
    return motor


def descriptor_motor(n_objetos: int, empresa: str = EMP, gen: GeneracionSolicitada = v2.G1) -> DescriptorPreparado:
    """Descriptor Motor v2 válido cuya generación Cloud tiene exactamente ``n_objetos`` objetos."""
    base = v2.objetos_v2(empresa)
    extra = n_objetos - 1 - len(base)
    assert extra >= 0, f"un descriptor Motor v2 válido no cabe en {n_objetos} objetos"
    ev = [v2.evidencia(f"Guia {i:06d}.JPG", "original", f"foto-{i}", empresa) for i in range(extra)]
    return construir_descriptor(v2.inv(base + ev, empresa=empresa, gen=gen))


def generacion_sintetica(n: int, descriptor: bytes = b'{"version_contrato":2}', empresa: str = EMP,
                         gen: str = "g", anterior: str | None = None) -> ref.GeneracionV2:
    objetos = [(RUTA_DESCRIPTOR, ref.sha256_hex(descriptor))]
    objetos += [(f"fuente/{i:06d}", _sha(f"contenido-{i}")) for i in range(n - 1)]
    return ref.construir(empresa, gen, anterior, objetos)


# ============================================================ vectores oficiales
def test_oficial_copias_identicas_a_cloud_79de408():
    assert _blob(VECTORES.read_bytes().replace(b"\r\n", b"\n")) == BLOB_VECTORES
    datos = FIXTURE_MOTOR.read_bytes()
    assert _blob(datos) == BLOB_FIXTURE and ref.sha256_hex(datos) == SHA_FIXTURE


def test_oficial_vector_una_parte_bytes_hashes_y_huella():
    v = _vectores()
    parte, cabecera = bytes.fromhex(v["parte_utf8_hex"]), bytes.fromhex(v["cabecera_utf8_hex"])
    assert ref.sha256_hex(parte) == v["parte_sha256_bytes"]
    assert ref.hoja(parte).hex() == v["parte_sha256_dominio"]
    assert ref.sha256_hex(cabecera) == v["cabecera_sha256_bytes"]
    assert ref.hash_dominio("cabecera", cabecera).hex() == v["cabecera_sha256_dominio"]
    gen = ref.verificar(cabecera, [parte], EMP, huella_esperada=v["cabecera_sha256_dominio"])
    assert gen.cabecera["raiz_partes"] == v["parte_sha256_dominio"]          # una parte: raíz = hoja
    assert gen.cabecera["anterior_id"] == "gen-1" and gen.cabecera["generacion_id"] == "gen-2"
    # Reconstrucción independiente desde las entradas del modelo: mismos bytes publicados.
    otra = ref.construir(EMP, "gen-2", "gen-1", gen.objetos[::-1])
    assert otra.partes_bytes == (parte,) and otra.cabecera_bytes == cabecera
    # Serialización canónica: claves ordenadas, sin espacios, ASCII.
    assert ref.canonico(json.loads(parte)) == parte and b" " not in parte and parte.isascii()


def test_oficial_vector_tres_partes_raiz_impar_y_huella():
    v = _vectores()
    objetos = [(RUTA_DESCRIPTOR, _sha("m"))] + [(f"fuente/{i:04d}", _sha(f"valor-{i}")) for i in range(201)]
    gen = ref.construir(EMP, "g", None, objetos)
    assert [h.hex() for h in gen.hojas] == v["tres_partes_sha256"]
    assert gen.cabecera["raiz_partes"] == v["tres_partes_raiz"]
    assert gen.huella == v["tres_partes_cabecera_sha256"]
    h = [bytes.fromhex(x) for x in v["tres_partes_sha256"]]
    assert ref.hash_dominio("nodo", ref.hash_dominio("nodo", h[0] + h[1]) + h[2]).hex() == v["tres_partes_raiz"]
    assert ref.hash_dominio("nodo", ref.hash_dominio("nodo", h[0] + h[1])
                            + ref.hash_dominio("nodo", h[2] + h[2])).hex() != v["tres_partes_raiz"]  # no duplica
    assert [json.loads(p)["cantidad"] for p in gen.partes_bytes] == [100, 100, 2]
    ref.verificar(gen.cabecera_bytes, gen.partes_bytes, EMP, huella_esperada=v["tres_partes_cabecera_sha256"])


def test_oficial_vector_uno_no_es_descriptor_motor_valido():
    """El vector oficial es Cloud-válido pero su objeto Motor (`{"version_contrato":2}`) no lo es."""
    v = _vectores()
    gen = ref.verificar(bytes.fromhex(v["cabecera_utf8_hex"]), [bytes.fromhex(v["parte_utf8_hex"])], EMP)
    with pytest.raises(ErrorDescriptor) as exc:
        conciliar_motor(gen, b'{"version_contrato":2}', EMP)
    assert {p.codigo for p in exc.value.problemas} == {"FORMATO_INVALIDO"}


def test_oficial_fixture_motor_v2_autentico_y_representable():
    datos = FIXTURE_MOTOR.read_bytes()
    motor = leer_descriptor(datos)
    assert motor.version_contrato == 2 and datos.isascii() and not datos.endswith(b"\n")
    assert serializar_descriptor(construir_descriptor(v2.inv(v2.objetos_v2()))) == datos   # a9b5649 lo regenera
    gen, bytes_motor = proyectar_motor(motor, EMP)
    assert bytes_motor == datos                                       # se transporta sin reinterpretar
    assert gen.cabecera["sha_descriptor_motor"] == SHA_FIXTURE != motor.huella_descriptor.removeprefix("sha256:")
    assert gen.cabecera["numero_objetos"] == len(motor.fuentes) + 1 == 20
    assert gen.cabecera["anterior_id"] is None and gen.cabecera["generacion_id"] == "gen-000001"
    leido = conciliar_motor(ref.verificar(gen.cabecera_bytes, gen.partes_bytes, EMP, huella_esperada=gen.huella),
                            datos, EMP)
    assert leido == motor
    assert leido.derivaciones == motor.derivaciones and dict(leido.declaracion)["DECISIONES_HUMANAS"] == 2
    assert {f.rol for f in leido.fuentes if f.tipo == "EVIDENCIA_DOCUMENTAL"} >= {"original", "pdf-texto"}


# ===================================================== cruce con el modelo Node
CLOUD_DIR = os.environ.get("DESCRIPTOR_CLOUD_V2_DIR", "")
MODELO = Path(CLOUD_DIR, "test", "contrato_cloud_v2_modelo.test.js") if CLOUD_DIR else None
requiere_modelo = pytest.mark.skipif(not (MODELO and MODELO.is_file() and shutil.which("node")),
                                     reason="definir DESCRIPTOR_CLOUD_V2_DIR (git archive de Cloud 79de408) y node")


def _modelo(casos: list[dict]) -> list[dict]:
    r = subprocess.run(["node", str(DIR / "modelo_cloud_v2.mjs"), str(MODELO)], input=json.dumps(casos),
                       capture_output=True, text=True, encoding="utf-8", timeout=300, check=True)
    return json.loads(r.stdout)


def _caso_crear(gen: ref.GeneracionV2) -> dict:
    c = gen.cabecera
    return {"op": "crear", "empresa": c["empresa_id"], "generacion": c["generacion_id"],
            "anterior": c["anterior_id"], "entradas": [{"ruta": r, "sha256": s} for r, s in gen.objetos[::-1]]}


def _comparar(gen: ref.GeneracionV2, salida: dict) -> None:
    assert salida["ok"], salida
    assert bytes.fromhex(salida["cabecera_hex"]) == gen.cabecera_bytes
    assert salida["partes_sha256"] == [ref.sha256_hex(p) for p in gen.partes_bytes]
    assert salida["hojas"] == [h.hex() for h in gen.hojas] and salida["huella"] == gen.huella


@requiere_modelo
def test_cruzado_tamanos_sinteticos_identicos_en_python_y_node():
    gens = [generacion_sintetica(n) for n in TAMANOS]
    for gen, salida in zip(gens, _modelo([_caso_crear(g) for g in gens])):
        _comparar(gen, salida)


@requiere_modelo
def test_cruzado_descriptores_motor_reales_identicos_en_python_y_node():
    gens = [proyectar_motor(descriptor_motor(n), EMP)[0] for n in TAMANOS[1:]]
    gens.append(proyectar_motor(leer_descriptor(FIXTURE_MOTOR.read_bytes()), EMP)[0])
    for gen, salida in zip(gens, _modelo([_caso_crear(g) for g in gens])):
        _comparar(gen, salida)


@requiere_modelo
def test_cruzado_rechazos_coinciden_con_el_modelo():
    gen = generacion_sintetica(202)
    base = {"op": "verificar", "empresa": EMP, "cabecera": gen.cabecera, "huella": gen.huella}
    partes = [json.loads(p) for p in gen.partes_bytes]
    alterada = json.loads(json.dumps(partes)); alterada[0]["objetos"][1]["sha256"] = _sha("x")
    ajena = json.loads(json.dumps(partes)); ajena[1]["empresa_id"] = "empresa-ajena"
    version = json.loads(json.dumps(partes)); version[2]["version"] = 3
    desorden = [partes[1], partes[0], partes[2]]
    casos = [dict(base, partes=partes), dict(base, partes=alterada), dict(base, partes=partes[:2]),
             dict(base, partes=ajena), dict(base, partes=version), dict(base, partes=desorden),
             dict(base, partes=partes, huella="0" * 64)]
    assert [s["ok"] for s in _modelo(casos)] == [True] + [False] * 6
    for p in (alterada, partes[:2], ajena, version, desorden):
        with pytest.raises(ErrorCloudV2):
            ref.verificar(gen.cabecera_bytes, [ref.canonico(x) for x in p], EMP)
    assert _codigo(ref.verificar, gen.cabecera_bytes, gen.partes_bytes, EMP, huella_esperada="0" * 64) \
        == "HUELLA_INCORRECTA"


# ============================================================ casos sintéticos
@pytest.mark.parametrize("n", TAMANOS)
def test_sintetico_particion_y_verificacion_por_tamano(n):
    gen = generacion_sintetica(n)
    partes = [json.loads(p) for p in gen.partes_bytes]
    assert gen.cabecera["numero_objetos"] == n and gen.cabecera["numero_partes"] == -(-n // 100) == len(partes)
    assert [p["indice"] for p in partes] == list(range(len(partes)))
    assert all(p["cantidad"] == 100 for p in partes[:-1]) and partes[-1]["cantidad"] == n - 100 * (len(partes) - 1)
    assert sum(p["cantidad"] for p in partes) == n
    assert ref.verificar(gen.cabecera_bytes, gen.partes_bytes, EMP, huella_esperada=gen.huella).objetos == gen.objetos
    hojas = gen.hojas
    for i in range(len(hojas)):                     # cada página se prueba contra la raíz comprometida
        assert ref.verificar_prueba_merkle(hojas[i], i, len(hojas), ref.prueba_merkle(hojas, i),
                                           bytes.fromhex(gen.cabecera["raiz_partes"]))


def test_sintetico_partes_esperadas_por_tamano():
    assert {n: generacion_sintetica(n).cabecera["numero_partes"] for n in TAMANOS} == \
        {1: 1, 100: 1, 101: 2, 999: 10, 1000: 10, 1001: 11, 2500: 25, 5000: 50}


@pytest.mark.parametrize("n", TAMANOS[1:])
def test_sintetico_descriptor_motor_real_por_tamano(n):
    motor = descriptor_motor(n)
    gen, datos = proyectar_motor(motor, EMP)
    assert gen.cabecera["numero_objetos"] == n
    leido = conciliar_motor(ref.verificar(gen.cabecera_bytes, gen.partes_bytes, EMP, huella_esperada=gen.huella),
                            datos, EMP)
    assert leido == motor and leido.version_contrato == 2
    if n > 1000:    # v1 admite hasta 1000 objetos incluido el descriptor; v2 no impone ese máximo
        with pytest.raises(ErrorDescriptor) as exc:
            dc.proyectar_para_custodia(motor, EMP)
        assert {p.codigo for p in exc.value.problemas} == {"LIMITE_CUSTODIA"}


def test_sintetico_un_objeto_es_cloud_valido_pero_nunca_motor_valido():
    gen = generacion_sintetica(1, FIXTURE_MOTOR.read_bytes())
    assert ref.verificar(gen.cabecera_bytes, gen.partes_bytes, EMP).cabecera["numero_objetos"] == 1
    with pytest.raises(ErrorCloudV2) as exc:            # el fixture no coincide en generación ni fuentes
        conciliar_motor(gen, FIXTURE_MOTOR.read_bytes(), EMP)
    assert exc.value.codigo in {"GENERACION_INCORRECTA", "INVENTARIO_INCOMPLETO"}
    # Descriptor Motor v2 mínimo (sin evidencia ni catálogo global): 10 fuentes, 9 para la empresa sin marca.
    for empresa, esperado in ((EMP, 10), (v2.MBT, 9)):
        objs = [o for o in v2.objetos_v2(empresa, con_evidencia=False) if o.empresa_id is not None]
        assert len(construir_descriptor(v2.inv(objs, empresa=empresa)).fuentes) == esperado
        for quitar in objs:                              # ninguna fuente sobra: no hay v2 válido más chico
            with pytest.raises(ErrorDescriptor):
                construir_descriptor(v2.inv([o for o in objs if o is not quitar], empresa=empresa,
                                            declaracion=v2.declarar(objs)))


def test_sintetico_parte_alterada():
    gen = generacion_sintetica(250)
    p = json.loads(gen.partes_bytes[1]); p["objetos"][5]["sha256"] = _sha("alterado")
    assert _codigo(ref.verificar, gen.cabecera_bytes, [gen.partes_bytes[0], ref.canonico(p), gen.partes_bytes[2]],
                   EMP) == "RAIZ_INCORRECTA"
    no_canonica = gen.partes_bytes[1].replace(b'{"cantidad":', b'{ "cantidad":', 1)
    assert _codigo(ref.verificar, gen.cabecera_bytes, [gen.partes_bytes[0], no_canonica, gen.partes_bytes[2]],
                   EMP) == "NO_CANONICO"


def test_sintetico_objeto_duplicado():
    objetos = list(generacion_sintetica(5).objetos)
    assert _codigo(ref.construir, EMP, "g", None, objetos + [objetos[1]]) == "IDENTIDAD_DUPLICADA"
    assert _codigo(ref.construir, EMP, "g", None, objetos + [(objetos[1][0], _sha("otro"))]) == "IDENTIDAD_DUPLICADA"
    gen = generacion_sintetica(5)
    p = json.loads(gen.partes_bytes[0]); p["objetos"][2] = p["objetos"][1]
    assert _codigo(ref.verificar, gen.cabecera_bytes, [ref.canonico(p)], EMP) == "IDENTIDAD_DUPLICADA"
    # Contenidos idénticos en rutas distintas sí se admiten.
    ref.construir(EMP, "g", None, [(RUTA_DESCRIPTOR, _sha("m")), ("a/x", _sha("igual")), ("a/y", _sha("igual"))])


def test_sintetico_duplicado_entre_partes():
    gen = generacion_sintetica(150)
    p1 = json.loads(gen.partes_bytes[1]); p1["objetos"][0] = json.loads(gen.partes_bytes[0])["objetos"][-1]
    assert _codigo(ref.verificar, gen.cabecera_bytes, [gen.partes_bytes[0], ref.canonico(p1)], EMP) \
        == "IDENTIDAD_DUPLICADA"


def test_sintetico_empresa_cruzada():
    gen = generacion_sintetica(150)
    assert _codigo(ref.verificar, gen.cabecera_bytes, gen.partes_bytes, "empresa-ajena") == "EMPRESA_INCORRECTA"
    p = json.loads(gen.partes_bytes[1]); p["empresa_id"] = "empresa-ajena"
    assert _codigo(ref.verificar, gen.cabecera_bytes, [gen.partes_bytes[0], ref.canonico(p)], EMP) \
        == "EMPRESA_INCORRECTA"
    otra = generacion_sintetica(150, empresa="empresa-ajena")        # mismo ID e inventario, otra empresa
    assert otra.huella != gen.huella and otra.cabecera["raiz_partes"] != gen.cabecera["raiz_partes"]
    assert _codigo(ref.verificar, otra.cabecera_bytes, gen.partes_bytes, "empresa-ajena") == "EMPRESA_INCORRECTA"
    # Motor de otra empresa dentro de una generación Cloud propia.
    motor = descriptor_motor(30, empresa="empresa-ajena")
    gen_ajena, datos = proyectar_motor(motor, "empresa-ajena")
    propia = ref.construir(EMP, gen_ajena.cabecera["generacion_id"], None, gen_ajena.objetos)
    assert _codigo(conciliar_motor, propia, datos, EMP) == "EMPRESA_INCORRECTA"


@pytest.mark.parametrize("version", [1, 3, 0, True, "2", None])
def test_sintetico_version_desconocida(version):
    gen = generacion_sintetica(150)
    c = dict(gen.cabecera, version=version)
    assert _codigo(ref.verificar, ref.canonico(c), gen.partes_bytes, EMP) == "VERSION_INCOMPATIBLE"
    p = json.loads(gen.partes_bytes[1]); p["version"] = version
    assert _codigo(ref.verificar, gen.cabecera_bytes, [gen.partes_bytes[0], ref.canonico(p)], EMP) \
        == "VERSION_INCOMPATIBLE"


def test_sintetico_descriptor_motor_invalido():
    motor = descriptor_motor(40)
    gen, datos = proyectar_motor(motor, EMP)
    verificada = ref.verificar(gen.cabecera_bytes, gen.partes_bytes, EMP)
    assert _codigo(conciliar_motor, verificada, datos + b" ", EMP) == "DESCRIPTOR_ALTERADO"
    # Bytes alterados pero coherentes con su propio SHA: Cloud los acepta, Motor no.
    alterado = datos.replace(b'"secuencia":1', b'"secuencia":2', 1)
    objetos = [(r, s) for r, s in gen.objetos if r != RUTA_DESCRIPTOR] + [(RUTA_DESCRIPTOR, ref.sha256_hex(alterado))]
    falsa = ref.construir(EMP, gen.cabecera["generacion_id"], None, objetos)
    ref.verificar(falsa.cabecera_bytes, falsa.partes_bytes, EMP)
    with pytest.raises(ErrorDescriptor):
        conciliar_motor(falsa, alterado, EMP)
    # Motor autodeclarado completo.
    completo = datos.replace(b'"PENDIENTE_PROTOCOLO_OFICIAL"', b'"COMPLETA"', 1)
    with pytest.raises(ErrorDescriptor) as exc:
        leer_descriptor(completo)
    assert {p.codigo for p in exc.value.problemas} == {"DESCRIPTOR_AUTODECLARADO"}
    # Inventario Cloud con fuente sobrante o con otra huella.
    sobra = ref.construir(EMP, gen.cabecera["generacion_id"], None, list(gen.objetos) + [("extra/x", _sha("x"))])
    assert _codigo(conciliar_motor, sobra, datos, EMP) == "INVENTARIO_INCONSISTENTE"
    falta = ref.construir(EMP, gen.cabecera["generacion_id"], None,
                          [o for o in gen.objetos if o[0] != "operacion/ledger"])
    assert _codigo(conciliar_motor, falta, datos, EMP) == "INVENTARIO_INCOMPLETO"
    cambio = ref.construir(EMP, gen.cabecera["generacion_id"], None,
                           [(r, _sha("y") if r == "operacion/ledger" else s) for r, s in gen.objetos])
    assert _codigo(conciliar_motor, cambio, datos, EMP) == "INVENTARIO_INCONSISTENTE"


def test_sintetico_parte_ausente_y_sobrante():
    gen = generacion_sintetica(2500)
    assert _codigo(ref.verificar, gen.cabecera_bytes, gen.partes_bytes[:-1], EMP) == "PARTE_AUSENTE"
    assert _codigo(ref.verificar, gen.cabecera_bytes, gen.partes_bytes[:12] + gen.partes_bytes[13:], EMP) \
        in {"ORDEN_INCORRECTO", "PARTE_AUSENTE"}
    assert _codigo(ref.verificar, gen.cabecera_bytes, gen.partes_bytes + gen.partes_bytes[-1:], EMP) \
        == "PARTE_SOBRANTE"
    # Una hoja válida aislada no acredita el inventario: la cabecera exige todas.
    assert _codigo(ref.verificar, gen.cabecera_bytes, gen.partes_bytes[:1], EMP) == "PARTE_AUSENTE"


def test_sintetico_orden_incorrecto():
    gen = generacion_sintetica(300)
    p = gen.partes_bytes
    assert _codigo(ref.verificar, gen.cabecera_bytes, [p[1], p[0], p[2]], EMP) == "ORDEN_INCORRECTO"
    q = json.loads(p[0]); q["objetos"][3], q["objetos"][4] = q["objetos"][4], q["objetos"][3]
    assert _codigo(ref.verificar, gen.cabecera_bytes, [ref.canonico(q), p[1], p[2]], EMP) == "ORDEN_INCORRECTO"
    # Último incompleto en medio: [100, 99+1...] no es partición canónica.
    r0, r1 = json.loads(p[0]), json.loads(p[1])
    r1["objetos"].insert(0, r0["objetos"].pop()); r0["cantidad"] = 99; r1["cantidad"] = 101
    assert _codigo(ref.verificar, gen.cabecera_bytes, [ref.canonico(r0), ref.canonico(r1), p[2]], EMP) \
        == "CONTEO_INCORRECTO"


def test_sintetico_huella_y_raiz_incorrectas():
    gen = generacion_sintetica(1001)
    assert _codigo(ref.verificar, gen.cabecera_bytes, gen.partes_bytes, EMP, huella_esperada="f" * 64) \
        == "HUELLA_INCORRECTA"
    c = dict(gen.cabecera, raiz_partes="0" * 64)
    assert _codigo(ref.verificar, ref.canonico(c), gen.partes_bytes, EMP) == "RAIZ_INCORRECTA"
    c = dict(gen.cabecera, sha_descriptor_motor="0" * 64)
    assert _codigo(ref.verificar, ref.canonico(c), gen.partes_bytes, EMP) == "DESCRIPTOR_INCONSISTENTE"
    c = dict(gen.cabecera, numero_objetos=1000)
    assert _codigo(ref.verificar, ref.canonico(c), gen.partes_bytes, EMP) == "CONTEO_INCORRECTO"
    hojas = gen.hojas
    prueba = ref.prueba_merkle(hojas, 7)
    raiz = bytes.fromhex(gen.cabecera["raiz_partes"])
    assert not ref.verificar_prueba_merkle(hojas[7], 6, len(hojas), prueba, raiz)        # índice ajeno
    assert not ref.verificar_prueba_merkle(hojas[7], 7, len(hojas), prueba[:-1], raiz)   # truncada
    assert not ref.verificar_prueba_merkle(hojas[7], 7, len(hojas), prueba + prueba[:1], raiz)
    assert not ref.verificar_prueba_merkle(hojas[7], 7, 8, prueba, raiz)                 # total ajeno
    # Observación: con 11 partes, la prueba de la hoja 7 tiene la misma forma para totales 9..12.
    # Sólo la cabecera comprometida (numero_partes dentro de la huella) fija el total.
    assert all(ref.verificar_prueba_merkle(hojas[7], 7, t, prueba, raiz) for t in (9, 10, 11, 12))


def test_sintetico_cabecera_anterior_debe_coincidir_con_motor():
    """Cloud v1 no transporta anterior en el descriptor; v2 lo compromete en la cabecera."""
    motor = descriptor_motor(30, gen=v2.G2)
    gen, datos = proyectar_motor(motor, EMP)
    assert gen.cabecera["anterior_id"] == "gen-000001"
    conciliar_motor(gen, datos, EMP)
    for anterior in (None, "gen-otra"):
        falsa = ref.construir(EMP, gen.cabecera["generacion_id"], anterior, gen.objetos)
        ref.verificar(falsa.cabecera_bytes, falsa.partes_bytes, EMP)          # Cloud no lo detecta
        assert _codigo(conciliar_motor, falsa, datos, EMP) == "ANTERIOR_INCORRECTA"
    assert _codigo(ref.construir, EMP, "g", "g", gen.objetos) == "GENERACION_INVALIDA"


def test_sintetico_no_canonico_y_claves_duplicadas():
    gen = generacion_sintetica(3)
    texto = gen.cabecera_bytes.decode()
    assert _codigo(ref.verificar, texto.replace('"version":2}', '"version":2,"version":2}').encode(),
                   gen.partes_bytes, EMP) == "FORMATO_INVALIDO"
    escapada = gen.cabecera_bytes.replace(b'"generacion_id"', b'"\\u0067eneracion_id"', 1)
    assert json.loads(escapada) == gen.cabecera                     # mismo valor, otra serialización
    assert _codigo(ref.verificar, escapada, gen.partes_bytes, EMP) == "NO_CANONICO"
    assert _codigo(ref.verificar, gen.cabecera_bytes + b"\n", gen.partes_bytes, EMP) == "NO_CANONICO"
    invertida = json.dumps(dict(reversed(list(gen.cabecera.items()))), separators=(",", ":")).encode()
    assert _codigo(ref.verificar, invertida, gen.partes_bytes, EMP) == "NO_CANONICO"   # claves fuera de orden
    p = json.loads(gen.partes_bytes[0])
    p["objetos"] = [{"sha256": o["sha256"], "ruta": o["ruta"]} for o in p["objetos"]]
    assert _codigo(ref.verificar, gen.cabecera_bytes, [json.dumps(p, separators=(",", ":")).encode()], EMP) \
        == "NO_CANONICO"
    extra = dict(gen.cabecera, secuencia=1)
    assert _codigo(ref.verificar, ref.canonico(extra), gen.partes_bytes, EMP) == "FORMATO_INVALIDO"
    c = dict(gen.cabecera, numero_objetos=3.0)
    assert _codigo(ref.verificar, json.dumps(c, sort_keys=True, separators=(",", ":")).encode(),
                   gen.partes_bytes, EMP) == "CONTEO_INCORRECTO"


def test_sintetico_parte_maxima_cabe_en_65536_bytes():
    empresa, generacion = "e" + "a" * 38 + "z", "g" * 128
    objetos = [(RUTA_DESCRIPTOR, _sha("m"))]
    objetos += [(("r" + f"{i:03d}") + "/" + "x" * 251, _sha(str(i))) for i in range(99)]
    assert all(len(r) == 256 for r, _ in objetos[1:])
    gen = ref.construir(empresa, generacion, None, objetos)
    assert len(gen.partes_bytes) == 1 and len(gen.partes_bytes[0]) < 40000 < ref.MAX_BYTES_PARTE
    assert _codigo(ref.construir, empresa, generacion, None, objetos + [("r/" + "y" * 255, _sha("z"))]) \
        == "RUTA_INVALIDA"


def test_sintetico_identidades_motor_caben_en_rutas_cloud():
    from atlas_core import descriptor_generacion as dg
    assert dg._PATRON_EMPRESA.pattern == ref.PATRON_EMPRESA.pattern
    assert dg._PATRON_GENERACION.pattern == ref.PATRON_GENERACION.pattern
    assert dg._PATRON_IDENTIDAD.pattern == ref.PATRON_RUTA.pattern and dg._MAX_IDENTIDAD == ref.MAX_RUTA
    assert dc.RUTA_DESCRIPTOR == ref.RUTA_DESCRIPTOR and not ref.PATRON_RUTA.fullmatch(RUTA_DESCRIPTOR)
    motor = descriptor_motor(60)
    for f in motor.fuentes:
        assert ref.PATRON_RUTA.fullmatch(f.identidad) and f.identidad.isascii()
    globales = [f for f in motor.fuentes if f.empresa_id is None]
    assert globales and all(f.identidad in dict(proyectar_motor(motor, EMP)[0].objetos) for f in globales)


# ===================================================== compatibilidad v1 / v2
def test_compat_motor_v1_conserva_bytes_y_huella():
    casos = json.loads((Path(__file__).with_name("fixtures") / "descriptor_generacion_v1.json")
                       .read_text(encoding="utf-8"))["casos"]
    for caso in casos:
        datos = caso["serializado"].encode("utf-8")
        d = leer_descriptor(datos)
        assert d.version_contrato == 1 and d.huella_descriptor == caso["huella_descriptor"]
        assert serializar_descriptor(d) == datos


def test_compat_motor_v1_viaja_en_cloud_v2_sin_promoverse():
    caso = json.loads((Path(__file__).with_name("fixtures") / "descriptor_generacion_v1.json")
                      .read_text(encoding="utf-8"))["casos"][0]
    datos = caso["serializado"].encode("utf-8")
    d = leer_descriptor(datos)
    gen, bytes_motor = proyectar_motor(d, d.empresa_id)
    assert bytes_motor == datos
    leido = conciliar_motor(ref.verificar(gen.cabecera_bytes, gen.partes_bytes, d.empresa_id), datos, d.empresa_id)
    assert leido.version_contrato == 1 and leido == d


def test_compat_motor_v2_no_se_convierte_en_v1():
    motor = descriptor_motor(30)
    for datos in (proyectar_motor(motor, EMP)[1], dc.proyectar_para_custodia(motor, EMP).objeto_descriptor):
        assert json.loads(datos)["version_contrato"] == 2 and leer_descriptor(datos).version_contrato == 2
    with pytest.raises(ErrorDescriptor):            # el mismo inventario con reglas v1 no es válido
        construir_descriptor(replace(v2.inv(v2.objetos_v2()), version_contrato=1))


def test_compat_cloud_v1_sigue_legible_y_rechaza_v2():
    motor = descriptor_motor(30)
    p = dc.proyectar_para_custodia(motor, EMP)
    assert dc.verificar_generacion_custodia(p.descriptor(), p.descriptor_sha256, p.objeto_descriptor, EMP) == motor
    gen, datos = proyectar_motor(motor, EMP)
    with pytest.raises(ErrorDescriptor) as exc:     # una cabecera v2 nunca se lee como v1 parcial
        dc.verificar_generacion_custodia(gen.cabecera, ref.sha256_hex(gen.cabecera_bytes), datos, EMP)
    assert {x.codigo for x in exc.value.problemas} == {"VERSION_INCOMPATIBLE"}
    # Y el verificador v2 no acepta el cuerpo v1.
    assert _codigo(ref.verificar, p.descriptor_cloud, [], EMP) == "VERSION_INCOMPATIBLE"


def test_compat_camino_v1_sin_cambios_ni_dependencia_v2():
    assert dc.VERSION_CUSTODIA == 1 and dc.VERSIONES_CUSTODIA_COMPATIBLES == frozenset({1})
    assert dc.MAX_OBJETOS_CUSTODIA == 1000
    fuente = Path(dc.__file__).read_text(encoding="utf-8")
    assert "contrato_cloud_v2" not in fuente and "custodia/v2" not in fuente
    # Huella v1 fijada del fixture oficial: cualquier cambio del camino v1 la altera.
    p = dc.proyectar_para_custodia(leer_descriptor(FIXTURE_MOTOR.read_bytes()), EMP)
    assert p.descriptor_cloud.startswith(b'{"version":1,"empresa_id":"empresa-sintetica","generacion_id":')
    assert p.objeto_descriptor_sha256 == SHA_FIXTURE
    assert p.descriptor_sha256 == HUELLA_V1_FIXTURE


HUELLA_V1_FIXTURE = "7094e7c46da0774e7fae3053d0565d3e42bc905772294dfd90e7497352490d0e"
