"""Pasos del alta integral de una empresa, cada uno en un proceso de ESA empresa.

Los lanza ``alta_empresa.py`` (raíz del Motor), que no importa ``atlas_core``:
así ningún paso corre con la guarda de MBT ni con la de otra empresa. Cada paso
es idempotente (comprueba el estado real antes de escribir), nunca sobrescribe
lo existente e imprime una sola línea JSON::

    {"paso": ..., "estado": "HECHO" | "YA_ESTABA" | "SE_HARIA" | "PENDIENTE" | "ERROR", ...}

    python -m atlas_core.alta_empresa <paso> '<parámetros JSON>' [--revisar]

Pasos: ``registro`` (proceso de alta, ``ATLAS_EMPRESA_ALTA``), ``estructura``,
``cloud``, ``custodia``, ``mobile-estado``, ``verificar``. Las escrituras en la
raíz se hacen con el turno local (raíz compartida: Drive) y, desde que existe
custodia, con el escritor oficial (lease + custodia).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from atlas_core import almacenamiento_portable as ap
from atlas_core import aislamiento_empresas as ae

# Catálogos base: el mismo formato que crean el Motor y Desktop al operar.
CATALOGOS_BASE: dict[str, object] = {
    "choferes.json": {},
    "usuarios_mobile.json": {"schema_version": 1, "usuarios": {}},
    "vehiculos.json": {"version": 1, "vehiculos": []},
    "clientes.json": {"version_formato": 1, "clientes": []},
    "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
    "empresas.json": {},
    "plantas.json": {"plantas": []},
    "rutas.json": {"rutas": []},
}
CARPETAS_BASE = ("catalogos_privados", "operacion/actual", "reportes")


class ErrorPaso(Exception):
    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(detalle or codigo)
        self.codigo, self.detalle = codigo, detalle


def _contexto(params: dict, *, alta: bool = False) -> ae.ContextoEmpresa:
    contexto = ae.contexto_desde_entorno()
    if contexto.es_mbt or contexto.empresa_id != params["empresa_id"]:
        raise ErrorPaso("PROCESO_DE_OTRA_EMPRESA", contexto.empresa_id)
    if not alta and contexto.cloud_id != params["cloud_id"]:
        raise ErrorPaso("CLOUD_ID_DISTINTO", f"{contexto.cloud_id!r} != {params['cloud_id']!r}")
    return contexto


def _turno(raiz: Path):
    from atlas_core.exclusion_local import TurnoEscritura
    turno = TurnoEscritura(raiz, espera_segundos=30)
    if not turno.adquirir():
        raise ErrorPaso("TURNO_OCUPADO", "otro escritor del Motor tiene el turno de esta raíz")
    return turno


# ------------------------------------------------------------------ registro
def registro(params: dict, revisar: bool) -> dict:
    """Marca de la empresa (``inicializar_empresa``). Proceso de alta: la raíz aún sin marca."""
    contexto = _contexto(params, alta=True)
    if contexto.cloud_id is not None:
        if contexto.cloud_id != params["cloud_id"]:
            raise ErrorPaso("EMPRESA_YA_DEFINIDA", f"cloud_id registrado {contexto.cloud_id!r}")
        return {"estado": "YA_ESTABA", "raiz": str(contexto.raiz)}
    # Las mismas comprobaciones que inicializar_empresa, sin escribir.
    for otra in ae.listar_empresas(contexto.raiz_mbt)[1:]:
        if otra != contexto.empresa_id and ae.abrir_empresa(contexto.raiz_mbt, otra).cloud_id == params["cloud_id"]:
            raise ErrorPaso("CLOUD_ID_EN_USO", params["cloud_id"])
    if params["cloud_id"] == ae.CLOUD_MBT:
        raise ErrorPaso("CLOUD_ID_EN_USO", params["cloud_id"])
    if revisar:
        return {"estado": "SE_HARIA", "raiz": str(contexto.raiz)}
    with _turno(contexto.raiz):
        nuevo = ae.inicializar_empresa(contexto.raiz_mbt, contexto.empresa_id, nombre=params["nombre"],
                                       cloud_id=params["cloud_id"])
    return {"estado": "HECHO", "raiz": str(nuevo.raiz), "empresas": ae.listar_empresas(contexto.raiz_mbt)}


# ---------------------------------------------------------------- estructura
def _iniciales(carpeta: str | None) -> dict[str, object]:
    """Catálogos iniciales aportados: sólo nombres conocidos y JSON del mismo tipo que la base."""
    if not carpeta:
        return {}
    salida = {}
    for ruta in sorted(Path(carpeta).glob("*.json")):
        if ruta.name not in CATALOGOS_BASE or ruta.name == "usuarios_mobile.json":
            raise ErrorPaso("CATALOGO_INICIAL_NO_ADMITIDO", ruta.name)
        try:
            contenido = json.loads(ruta.read_text(encoding="utf-8-sig"))
        except ValueError as error:
            raise ErrorPaso("CATALOGO_INICIAL_ILEGIBLE", f"{ruta.name}: {error}") from error
        if type(contenido) is not type(CATALOGOS_BASE[ruta.name]):
            raise ErrorPaso("CATALOGO_INICIAL_INVALIDO", ruta.name)
        salida[ruta.name] = contenido
    return salida


def estructura(params: dict, revisar: bool) -> dict:
    """Carpetas y catálogos que falten. Nunca reemplaza un archivo existente.
    Tras sembrar la custodia ya no se crea nada fuera del escritor oficial."""
    contexto = _contexto(params)
    iniciales = _iniciales(params.get("catalogos_iniciales"))
    catalogos = contexto.catalogos()
    faltan = [n for n in CATALOGOS_BASE if not (catalogos / n).is_file()]
    carpetas = [c for c in CARPETAS_BASE if not contexto.ruta(c).is_dir()]
    if not faltan and not carpetas:
        return {"estado": "YA_ESTABA", "catalogos": len(CATALOGOS_BASE)}
    if params.get("custodia_sembrada") and faltan:
        raise ErrorPaso("ESTRUCTURA_INCOMPLETA_CON_CUSTODIA",
                        f"faltan {faltan} con la custodia ya sembrada; crearlos con el escritor oficial")
    if revisar:
        return {"estado": "SE_HARIA", "crear": faltan, "carpetas": carpetas, "iniciales": sorted(iniciales)}
    with _turno(contexto.raiz):
        for carpeta in carpetas:
            contexto.ruta(carpeta).mkdir(parents=True, exist_ok=True)
        for nombre in faltan:
            ap.escribir_json_atomico(catalogos / nombre, iniciales.get(nombre, CATALOGOS_BASE[nombre]))
    return {"estado": "HECHO", "creados": faltan, "desde_iniciales": sorted(set(faltan) & set(iniciales))}


# ------------------------------------------------------------- cloud/custodia
def _lease(contexto: ae.ContextoEmpresa):
    from atlas_core.escritor_operativo import lease_desde_entorno
    lease = lease_desde_entorno(raiz=contexto.raiz)
    if lease is None:
        raise ErrorPaso("SIN_CREDENCIAL_MOTOR", f"falta {ae.VARIABLE_TOKEN}__{contexto.empresa_id.upper().replace('-', '_')}")
    return lease


def cloud(params: dict, revisar: bool) -> dict:
    """¿Reconoce Cloud la credencial Motor de esta empresa? Sólo lectura."""
    contexto = _contexto(params)
    lease = _lease(contexto)
    try:
        datos = lease.custodia.cliente.manifiesto()
    except Exception as error:  # noqa: BLE001 - se informa el motivo, nunca el token
        texto = str(error)
        if "401" in texto or "403" in texto:
            return {"estado": "PENDIENTE", "codigo": "CLOUD_NO_RECONOCE_TOKEN",
                    "detalle": "Agregar la entrada de esta empresa a CLOUD_MOTOR_TOKENS_JSON del Worker"}
        raise ErrorPaso("CLOUD_NO_DISPONIBLE", texto[:300]) from error
    return {"estado": "YA_ESTABA", "archivos_custodia": len(datos.get("archivos", []))}


def custodia(params: dict, revisar: bool) -> dict:
    """Línea base de la custodia Cloud (``estado_confirmado --sembrar``) si está vacía.
    Si ya existe, debe ser de ESTA empresa (su marca) y coincidir con la copia local."""
    from atlas_core.estado_confirmado import verificar_sin_escribir
    contexto = _contexto(params)
    lease = _lease(contexto)
    cliente = lease.custodia.cliente
    estado = ae.verificar_custodia_cloud(contexto, cliente)  # CUSTODIA_AJENA si es de otra empresa
    if estado["estado"] == "COINCIDE":
        verificacion = verificar_sin_escribir(contexto.raiz, cliente, carpeta_local=contexto.carpeta_custodia())
        if verificacion["distintos"]:
            raise ErrorPaso("CUSTODIA_DIFIERE", json.dumps(verificacion, ensure_ascii=False))
        return {"estado": "YA_ESTABA", "version": verificacion["version"], "archivos": verificacion["archivos"]}
    if revisar:
        return {"estado": "SE_HARIA", "archivos": len(lease.custodia.rutas_semilla())}
    with lease:
        if not lease.adquirir():
            raise ErrorPaso(lease.motivo or "ESCRITOR_OCUPADO", "no se obtuvo el escritor; nada se sembró")
        resultado = lease.custodia.sembrar(lease)
    final = ae.verificar_custodia_cloud(contexto, cliente)
    if final["estado"] != "COINCIDE":
        raise ErrorPaso("CUSTODIA_SIN_MARCA", json.dumps(final))
    return {"estado": "HECHO", **resultado}


# -------------------------------------------------------------------- mobile
def mobile_estado(params: dict, revisar: bool) -> dict:
    """Estado local de un chofer/usuario Mobile, para decidir qué falta (sólo lectura)."""
    from alta_chofer_mobile import ErrorAlta, normalizar_datos
    from atlas_core.catalogos import normalizar_rut
    contexto = _contexto(params)
    try:
        datos = normalizar_datos(usuario=params["usuario"], rut=params["rut"], nombre=params["nombre"])
    except ErrorAlta as error:
        raise ErrorPaso(error.codigo, error.detalle) from error
    choferes = json.loads((contexto.catalogos() / "choferes.json").read_text(encoding="utf-8-sig"))
    usuarios = json.loads((contexto.catalogos() / "usuarios_mobile.json").read_text(encoding="utf-8-sig"))["usuarios"]
    cuenta = usuarios.get(datos["usuario"])
    propios = [c for c in choferes if normalizar_rut(c) == datos["rut"]]
    return {"estado": "YA_ESTABA", "usuario": datos["usuario"], "rut": datos["rut"],
            "chofer_en_catalogo": bool(propios),
            "usuario_local": None if cuenta is None else
            ("PROPIO" if normalizar_rut(str(cuenta.get("chofer_id", ""))) == datos["rut"] else "DE_OTRO_CHOFER")}


# ------------------------------------------------------------------ verificar
def verificar(params: dict, revisar: bool) -> dict:
    """Comprobación final, sólo lectura, desde el proceso de la empresa."""
    from atlas_core.estado_confirmado import verificar_sin_escribir
    contexto = _contexto(params)
    faltan = [n for n in CATALOGOS_BASE if not (contexto.catalogos() / n).is_file()]
    resultado = {"raiz": str(contexto.raiz), "cloud_id": contexto.cloud_id, "catalogos_faltantes": faltan,
                 "entorno_local": str(ae.base_local(contexto.empresa_id))}
    lease = _lease(contexto)
    resultado["custodia"] = verificar_sin_escribir(contexto.raiz, lease.custodia.cliente,
                                                   carpeta_local=contexto.carpeta_custodia())
    ae.verificar_custodia_cloud(contexto, lease.custodia.cliente)
    ok = not faltan and resultado["custodia"]["distintos"] == 0 and resultado["custodia"]["archivos"] > 0
    return {"estado": "YA_ESTABA" if ok else "ERROR", **resultado}


PASOS = {"registro": registro, "estructura": estructura, "cloud": cloud, "custodia": custodia,
         "mobile-estado": mobile_estado, "verificar": verificar}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    revisar = "--revisar" in argv
    argv = [a for a in argv if a != "--revisar"]
    paso, params = argv[0], json.loads(argv[1])
    try:
        salida = {"paso": paso, **PASOS[paso](params, revisar)}
        codigo = 1 if salida["estado"] == "ERROR" else 0
    except (ErrorPaso, ae.ErrorAislamiento) as error:
        salida = {"paso": paso, "estado": "ERROR", "codigo": error.codigo,
                  "detalle": getattr(error, "detalle", "") or str(error)}
        codigo = 1
    except Exception as error:  # noqa: BLE001 - tipo y mensaje, nunca secretos (no se manejan aquí)
        salida = {"paso": paso, "estado": "ERROR", "codigo": "ERROR_INESPERADO", "detalle": f"{type(error).__name__}: {error}"[:600]}
        codigo = 1
    print(json.dumps(salida, ensure_ascii=False), flush=True)
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
