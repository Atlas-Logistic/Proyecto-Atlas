"""Contrato de fuentes reales de generación: coherencia con el código y con el descriptor.

Solo datos sintéticos; las rutas se calculan con objetos Path sin tocar disco.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path, PurePosixPath

import pytest

from atlas_core import descriptor_generacion as dg
from atlas_core import fuentes_generacion as fg
from atlas_core.descriptor_custodia import RUTA_DESCRIPTOR
from atlas_core.descriptor_generacion import (
    ErrorDescriptor, GeneracionSolicitada, Inventario, ObjetoFuente, construir_descriptor, huella_contenido,
)

RAIZ = Path("R")  # raíz sintética: sólo se componen rutas, nunca se accede
ATLAS_CORE = Path(fg.__file__).parent
EMP = "empresa-sintetica"
MBT = "empresa-prueba-javier"
G1 = GeneracionSolicitada("gen-000001", 1)


def rel(ruta: Path) -> str:
    return PurePosixPath(*Path(ruta).relative_to(RAIZ).parts).as_posix()


def fuente(clave: str) -> fg.FuenteReal:
    return next(f for f in fg.FUENTES if f.clave == clave)


# ------------------------------------------------------------ coherencia interna
def test_contrato_coherente():
    assert fg.validar_contrato() == []


def test_cubre_todos_los_tipos_del_descriptor():
    """Cada tipo v2 y cada derivación v2 tiene fuente real en el contrato."""
    assert set(fg.fuentes_por_tipo()) == set(dg.TIPOS_V2) | set(dg.DERIVACIONES)


def test_tipos_obligatorios_bloqueados_son_explicitos():
    """Con v2 ningún tipo obligatorio queda bloqueado; sólo la evidencia, por custodia."""
    bloqueados = {t for t, fs in fg.fuentes_por_tipo().items()
                  if t in dg.TIPOS_V2 and dg.TIPOS_V2[t].obligatorio
                  and any(f.integracion == fg.BLOQUEADA for f in fs)}
    assert bloqueados == set()
    assert {f.clave for f in fg.FUENTES if f.integracion == fg.BLOQUEADA} == {
        "evidencia", "relecturas", "evidencias_adicionales_pdf"}
    assert {f.rol for f in fg.fuentes_por_tipo()["DECISIONES_HUMANAS"]} == dg.ROLES_DECISIONES_HUMANAS
    assert set(fg.RANURAS_ASIGNACIONES) == set(dg.DERIVACIONES["ASIGNACIONES"])
    assert fuente("asignaciones").integracion == fg.DEPENDENCIAS_DECLARADAS
    for f in fg.FUENTES:
        if f.integracion == fg.BLOQUEADA:
            assert f.bloqueo
        if f.mapeo in (fg.AMBIGUO, fg.NO_RESUELTO):
            assert f.integracion == fg.BLOQUEADA, f.clave


# ------------------------------------------------------------ rutas reales
def test_rutas_coinciden_con_el_codigo():
    from atlas_core import (acciones_operacionales, agrupacion_viajes, aislamiento_empresas, aplicacion_decisiones,
                            evidencia_documental, ingesta_pdf, investigacion_documental, operaciones_conversacionales)

    archivos = acciones_operacionales._Contexto(RAIZ, None, None, None).archivos
    esperado = {
        "dataset": archivos["dataset"], "bandeja": archivos["bandeja"], "ledger": archivos["ledger_decisiones"],
        "agrupaciones": archivos["agrupaciones_viaje"],
        "catalogo_choferes": archivos["choferes"], "catalogo_vehiculos": archivos["vehiculos"],
        "catalogo_clientes": archivos["clientes"], "catalogo_obras_destinos": archivos["obras_destinos"],
        "catalogo_destinos_maestros": archivos["destinos_maestros"],
        "catalogo_incidencias_documentales": archivos["incidencias"],
        "acciones_operacionales": RAIZ / "operacion" / "actual" / acciones_operacionales.NOMBRE_REGISTRO,
        "investigacion": investigacion_documental.ruta_registro(RAIZ),
        "relecturas": evidencia_documental.ruta_registro_relecturas(RAIZ),
        "operaciones_conversacionales": operaciones_conversacionales._ledger_ruta(RAIZ),
        "evidencias_adicionales_pdf": ingesta_pdf.directorio_evidencia_pdf_para_dataset(archivos["dataset"])
        / ingesta_pdf.NOMBRE_REGISTRO_EVIDENCIAS_ADICIONALES,
        "identidad_empresa": RAIZ.joinpath(*aislamiento_empresas.RUTA_MARCA.split("/")),
    }
    assert agrupacion_viajes.ruta_registro(archivos["agrupaciones_viaje"].parent) == archivos["agrupaciones_viaje"]
    assert archivos["ledger_decisiones"].name == aplicacion_decisiones.LEDGER
    for clave, ruta in esperado.items():
        assert fuente(clave).ruta == rel(ruta), clave


def test_catalogos_requeridos_estan_en_el_contrato():
    from atlas_core.fuente_catalogos import ARCHIVOS_REQUERIDOS
    rutas = {f.ruta for f in fg.fuentes_por_tipo()["CATALOGO"]}
    assert {f"catalogos_privados/{n}" for n in ARCHIVOS_REQUERIDOS} <= rutas


def test_custodia_declarada_coincide_con_la_semilla():
    from atlas_core.estado_confirmado import SEMILLA_CARPETAS, SEMILLA_ENVIOS, rastreable

    def en_semilla(ruta: str) -> bool:
        return any(ruta.startswith(c + "/") for c in SEMILLA_CARPETAS) or (
            ruta.startswith(SEMILLA_ENVIOS + "/") and ruta.endswith("/envio.json"))

    for f in fg.FUENTES:
        if f.ruta is None or "{" in f.ruta or "<" in f.ruta:
            continue
        if f.custodia == fg.EN_SEMILLA:
            assert en_semilla(f.ruta) and rastreable(f.ruta), f.clave
        elif f.custodia == fg.FUERA_DE_SEMILLA:
            assert not en_semilla(f.ruta) and rastreable(f.ruta), f.clave
    # Binarios de evidencia: ninguna de sus ubicaciones está en la semilla.
    for ejemplo in ("operacion/entradas/lote-1/guia.jpg", "operacion/mobile/envios/e1/original.jpg",
                    "operacion/evidencia_pdf/doc_p0001.png", "operacion/evidencia_orientada/x.png",
                    "operacion/evidencia_resuelta/e1/metadata.json"):
        assert not en_semilla(ejemplo) and rastreable(ejemplo)
    assert fuente("evidencia").custodia == fg.FUERA_DE_SEMILLA


# ------------------------------------------------------------ escritores y lectores
def _fuente_modulo(nombre: str) -> str:
    return (ATLAS_CORE / f"{nombre}.py").read_text(encoding="utf-8")


def _existe(referencia: str) -> bool:
    modulo, *atributos = referencia.split(".")
    ruta = ATLAS_CORE / f"{modulo}.py"
    if not ruta.is_file():
        return False
    texto = ruta.read_text(encoding="utf-8")
    return all(re.search(rf"^\s*(def|class)\s+{re.escape(a)}\b", texto, re.M) for a in atributos)


def test_escritores_y_lectores_existen_en_el_codigo():
    for f in fg.FUENTES:
        for ref in (*f.escritores, *f.lectores_tolerantes):
            if ref.startswith("externo:"):
                continue
            assert _existe(ref), f"{f.clave}: {ref}"


def test_locks_declarados_existen_en_el_codigo():
    todo = "\n".join(p.read_text(encoding="utf-8") for p in ATLAS_CORE.glob("*.py") if p.name != "fuentes_generacion.py")
    for f in fg.FUENTES:
        for lock in f.locks:
            assert f'"{lock}"' in todo, f"{f.clave}: lock {lock}"


def test_lectores_que_convierten_ausencia_en_vacio_estan_declarados():
    """El riesgo 'ausente = vacío' del código actual queda visible en el contrato."""
    for clave in ("dataset", "ledger", "bandeja", "agrupaciones", "investigacion", "acciones_operacionales",
                  "relecturas", "evidencias_adicionales_pdf", "asignaciones"):
        assert fuente(clave).lectores_tolerantes, clave
    # Comprobación del comportamiento citado, sobre su código fuente.
    assert "return []" in _fuente_modulo("acciones_operacionales").split("def _filas_sin_bloqueo", 1)[1][:200]
    assert 'except (OSError, ValueError):\n        return []' in _fuente_modulo("agrupacion_viajes")


# ------------------------------------------------------------ identidades
_IDENT = dg._PATRON_IDENTIDAD


def test_identidades_validas_sin_colision():
    fijas = [f.identidad for f in fg.FUENTES if "<" not in f.identidad]
    assert len(fijas) == len(set(fijas))
    for ident in fijas:
        assert _IDENT.fullmatch(ident), ident
        assert ident != RUTA_DESCRIPTOR and not ident.startswith("_")
    archivos = ["Guia 485190.JPG", "lote.pdf::pagina=0001", "lote.pdf::pagina=0002", "mobile/abc-1/original.jpg",
                "485190.jpg", "485190.JPG"]
    contenidos = [huella_contenido(b"foto-1"), huella_contenido(b"foto-2")]  # p. ej. original y relectura
    generadas = {fg.identidad_evidencia(a, r, h) for a in archivos for r in sorted(fg.ROLES_EVIDENCIA)
                 for h in contenidos}
    assert len(generadas) == len(archivos) * len(fg.ROLES_EVIDENCIA) * len(contenidos)
    assert all(_IDENT.fullmatch(i) and len(i) <= 256 for i in generadas)
    assert not set(fijas) & generadas
    # Las identidades fijas no caen en el espacio evidencia/<sha256>/<rol>/<sha256>.
    espacio = re.compile(r"^evidencia/[0-9a-f]{64}/[a-z-]+/[0-9a-f]{64}$")
    assert not any(espacio.fullmatch(i) for i in fijas)
    for malo in ("", "  "):
        with pytest.raises(ValueError):
            fg.identidad_evidencia(malo, "original", contenidos[0])
    with pytest.raises(ValueError):
        fg.identidad_evidencia("x.jpg", "activa-desktop", contenidos[0])  # rol de ubicación v1: ya no existe
    with pytest.raises(ValueError):
        fg.identidad_evidencia("x.jpg", "original", "sin-huella")


def test_archivo_real_no_es_identidad_valida():
    """Motivo de identidad_evidencia: 'archivo' real viola la gramática Motor y la ruta Cloud."""
    for archivo in ("lote.pdf::pagina=0001", "Guia 485190.JPG"):
        assert not _IDENT.fullmatch(archivo)


def test_evidencia_representada():
    from atlas_core import evidencia_documental as ed
    tipos = fg.fuentes_por_tipo()["EVIDENCIA_DOCUMENTAL"]
    assert {f.clave for f in tipos} == {"evidencia", "relecturas", "evidencias_adicionales_pdf"}
    # Roles documentales, no ubicaciones: Mobile, entradas y evidencia_resuelta contienen el mismo
    # "original" (mover un archivo no cambia su identidad); la página PDF es "pdf-pagina".
    assert fg.ROLES_EVIDENCIA == {"original", "orientada", "pdf", "pdf-pagina", "pdf-texto"}
    ubicaciones = {ed.UBICACION_ACTIVA_MOBILE: "original", ed.UBICACION_ACTIVA_DESKTOP: "original",
                   ed.UBICACION_EVIDENCIA_RESUELTA: "original", ed.UBICACION_DERIVADA_PDF: "pdf-pagina"}
    assert set(ubicaciones.values()) <= fg.ROLES_EVIDENCIA
    assert {f.rol for f in tipos if f.rol} == set(dg.ROLES_EVIDENCIA_INDICE)
    assert {f.identidad for f in tipos if f.rol} == set(dg.ROLES_EVIDENCIA_INDICE.values())
    assert set(fuente("evidencia").dependencias) >= {"dataset", "relecturas"}
    assert "investigacion" in {f.clave for f in fg.FUENTES if "evidencia" in f.dependencias}


# ------------------------------------------------------------ empresas
def test_empresas_no_se_mezclan():
    for f in fg.FUENTES:
        assert f.empresa in (fg.PROPIA, fg.GLOBAL)
        if f.empresa == fg.GLOBAL:
            assert f.tipo == "CATALOGO" and f.custodia == fg.VERSIONADA_EN_CODIGO
        assert not re.search(r"mbt|empresa-|oficina", f.identidad)  # la empresa nunca va en la identidad
    objs, decl = _inventario_sintetico(EMP)
    objs[0] = ObjetoFuente(objs[0].identidad, objs[0].tipo, objs[0].huella, "empresa-ajena", True, objs[0].tamano,
                           rol=objs[0].rol)
    with pytest.raises(ErrorDescriptor) as exc:
        construir_descriptor(Inventario(2, EMP, G1, decl, tuple(objs), DERIV))
    assert "EMPRESA_INCORRECTA" in exc.value.codigos


# ------------------------------------------------------------ inventario sintético
DERIV = {"ASIGNACIONES": {ranura: fuente(clave).identidad for ranura, clave in fg.RANURAS_ASIGNACIONES.items()}}


def _inventario_sintetico(empresa: str):
    """Objetos sintéticos v2 con las identidades y roles del contrato (sin leer nada real).

    Nunca fabrica objetos para plantillas ni para fuentes sin almacén propio.
    La evidencia se declara 0 aparte.
    """
    objetos: list[ObjetoFuente] = []
    for f in fg.FUENTES:
        if "<" in f.identidad or f.ruta is None or f.tipo == "EVIDENCIA_DOCUMENTAL":
            continue
        if f.tipo == "IDENTIDAD_EMPRESA" and empresa in dg.EMPRESAS_SIN_MARCA:
            continue
        datos = f"sintetico:{f.clave}".encode()
        objetos.append(ObjetoFuente(f.identidad, f.tipo, huella_contenido(datos),
                                    None if f.empresa == fg.GLOBAL else empresa, True, len(datos),
                                    relacion=dg.RELACION_GLOBAL if f.empresa == fg.GLOBAL else dg.RELACION_PROPIA,
                                    rol=f.rol))
    declaracion = {t: 0 for t in dg.TIPOS_V2}
    for o in objetos:
        declaracion[o.tipo] += 1
    return objetos, declaracion


@pytest.mark.parametrize("empresa", [EMP, MBT])
def test_contrato_v2_produce_inventario_completo(empresa):
    """Con v2, las fuentes del contrato forman un inventario completo sin objetos fabricados."""
    objs, decl = _inventario_sintetico(empresa)
    d = construir_descriptor(Inventario(2, empresa, G1, decl, tuple(objs), DERIV))
    assert d.version_contrato == 2
    assert {f.rol for f in d.fuentes if f.tipo == "DECISIONES_HUMANAS"} == dg.ROLES_DECISIONES_HUMANAS
    assert {r: o.identidad for r, o in d.derivacion("ASIGNACIONES").items()} == DERIV["ASIGNACIONES"]
    assert not any(f.tipo == "ASIGNACIONES" for f in d.fuentes)


@pytest.mark.parametrize("rol", sorted(dg.ROLES_DECISIONES_HUMANAS))
def test_falta_un_registro_humano(rol):
    objs, decl = _inventario_sintetico(EMP)
    sin = [o for o in objs if o.rol != rol or o.tipo != "DECISIONES_HUMANAS"]
    with pytest.raises(ErrorDescriptor) as exc:
        construir_descriptor(Inventario(2, EMP, G1, decl, tuple(sin), DERIV))
    assert ("FUENTE_OBLIGATORIA_AUSENTE", f"DECISIONES_HUMANAS:{rol}") in {(p.codigo, p.sujeto) for p in exc.value.problemas}


def test_ausente_no_es_vacio():
    objs, decl = _inventario_sintetico(EMP)
    sin_dataset = [o for o in objs if o.tipo != "DATASET_OPERACIONAL"]
    with pytest.raises(ErrorDescriptor) as exc:
        construir_descriptor(Inventario(2, EMP, G1, decl, tuple(sin_dataset), DERIV))
    assert ("FUENTE_OBLIGATORIA_AUSENTE", "DATASET_OPERACIONAL") in {(p.codigo, p.sujeto) for p in exc.value.problemas}
    with pytest.raises(ErrorDescriptor) as exc:
        construir_descriptor(Inventario(2, EMP, G1, decl, tuple(objs), {}))
    assert ("DEPENDENCIA_INCOMPLETA", "ASIGNACIONES") in {(p.codigo, p.sujeto) for p in exc.value.problemas}
    omitida = {k: v for k, v in decl.items() if k != "EVIDENCIA_DOCUMENTAL"}
    with pytest.raises(ErrorDescriptor) as exc:
        construir_descriptor(Inventario(2, EMP, G1, omitida, tuple(objs), DERIV))
    assert ("INVENTARIO_INCOMPLETO", "EVIDENCIA_DOCUMENTAL") in {(p.codigo, p.sujeto) for p in exc.value.problemas}
    # CUARENTENA sin almacén propio: se declara 0, nunca se omite.
    assert decl["CUARENTENA"] == 0 and fuente("cuarentena").integracion == fg.DECLARAR_CERO


# ------------------------------------------------------------ sin escrituras
_vigilancia = {"activa": False, "eventos": []}


def _auditor(evento, args):
    if _vigilancia["activa"] and evento in {"open", "os.remove", "os.rename", "os.replace", "os.mkdir",
                                            "os.unlink", "shutil.copyfile", "socket.connect", "subprocess.Popen"}:
        _vigilancia["eventos"].append((evento, repr(args)[:100]))


sys.addaudithook(_auditor)


def test_sin_escrituras_ni_lecturas():
    _vigilancia["eventos"].clear()
    _vigilancia["activa"] = True
    try:
        fg.validar_contrato()
        fg.fuentes_por_tipo()
        fg.identidad_evidencia("lote.pdf::pagina=0001", "pdf-pagina", huella_contenido(b"png"))
    finally:
        _vigilancia["activa"] = False
    assert _vigilancia["eventos"] == []


def test_modulo_declarativo_sin_e_s():
    arbol = ast.parse(Path(fg.__file__).read_text(encoding="utf-8"))
    importados = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            importados |= {a.name for a in nodo.names}
        elif isinstance(nodo, ast.ImportFrom):
            importados.add(nodo.module or "")
    assert importados <= {"__future__", "dataclasses", "atlas_core"}  # atlas_core: sólo descriptor_generacion (puro)
    assert all(a.name == "descriptor_generacion" for n in ast.walk(arbol)
               if isinstance(n, ast.ImportFrom) and n.module == "atlas_core" for a in n.names)
    llamadas = {n.func.id for n in ast.walk(arbol) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not {"open", "exec", "eval", "__import__", "print"} & llamadas
