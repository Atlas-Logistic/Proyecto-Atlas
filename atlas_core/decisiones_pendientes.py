"""Contrato R3.1 de decisiones pendientes, separado del resultado documental.

El módulo sólo observa resultados y catálogos. Nunca aplica decisiones ni
modifica catálogos; la única escritura permitida es el artefacto versionado.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from atlas_core.almacenamiento_portable import escribir_json_atomico
from atlas_core.catalogo_clientes import (
    CatalogoClientes,
    EstadoCalidadCliente,
    EstadoVigenciaCliente,
    normalizar_nombre_cliente,
    normalizar_rut_cliente,
)
from atlas_core.catalogo_obras_destinos import (
    CatalogoObrasDestinos,
    EstadoVigencia,
    normalizar_nombre_obra,
)
from atlas_core.catalogo_vehiculos import resolver_patente
from atlas_core.catalogos import buscar_empresa_por_rut, cargar_catalogo_json
from atlas_core.validadores import EstadoValidacion, validar_rut_chileno


SCHEMA_VERSION = 1
NOMBRE_ARTEFACTO = "decisiones_pendientes.json"
TIPOS_SOPORTADOS = frozenset({
    "VEHICULO_DESCONOCIDO", "CLIENTE_DESCONOCIDO", "CLIENTE_CANDIDATO",
    "OBRA_DESCONOCIDA", "DESTINO_SIN_CONFIRMAR", "ALIAS_CANDIDATO",
})
_AUSENTES = {"", "No encontrado", "REVISAR", "Ilegible"}


def _sha256(ruta: Path) -> str:
    digest = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest().upper()


def _decision_id(*, tipo: str, documento: Mapping[str, str], campo: str,
                 valor_documental: str, evidencias: list[dict[str, object]]) -> str:
    identidad = {
        "schema_version": SCHEMA_VERSION,
        "tipo": tipo,
        "documento": dict(documento),
        "campo": campo,
        "valor_documental": valor_documental,
        "evidencias": evidencias,
    }
    serializado = json.dumps(
        identidad, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(serializado).hexdigest()


def crear_decision(
    *, tipo: str, entidad: str, archivo: str, numero_guia: str,
    numero_transporte: str, campo: str, valor_documental: str,
    valor_normalizado: str, identidad_resuelta: dict[str, object] | None,
    candidatos: Iterable[Mapping[str, object]], motivos: Iterable[str],
    evidencias: Iterable[Mapping[str, object]], acciones_permitidas: Iterable[str],
) -> dict[str, object]:
    if tipo not in TIPOS_SOPORTADOS:
        raise ValueError(f"tipo de decisión no soportado: {tipo}")
    documento = {
        "archivo": str(archivo),
        "numero_guia": str(numero_guia),
        "numero_transporte": str(numero_transporte),
    }
    evidencias_lista = [dict(evidencia) for evidencia in evidencias]
    decision = {
        "decision_id": _decision_id(
            tipo=tipo, documento=documento, campo=campo,
            valor_documental=str(valor_documental), evidencias=evidencias_lista,
        ),
        "estado": "PENDIENTE",
        "tipo": tipo,
        "entidad": entidad,
        "documento": documento,
        "campo": campo,
        "valor_documental": str(valor_documental),
        "valor_normalizado": str(valor_normalizado),
        "identidad_resuelta": identidad_resuelta,
        "candidatos": [dict(candidato) for candidato in candidatos],
        "motivos": [str(motivo) for motivo in motivos],
        "evidencias": evidencias_lista,
        "acciones_permitidas": [str(accion) for accion in acciones_permitidas],
    }
    return decision


def _identidad_cliente_por_rut(carpeta: Path, rut: str):
    try:
        normalizado = normalizar_rut_cliente(rut)
        coincidencias = [
            cliente for cliente in CatalogoClientes(carpeta / "clientes.json").listar()
            if cliente.rut == normalizado
            and cliente.estado_calidad == EstadoCalidadCliente.CONFIRMADO.value
            and cliente.estado_vigencia == EstadoVigenciaCliente.ACTIVO.value
        ]
        return coincidencias[0] if len(coincidencias) == 1 else None
    except (OSError, ValueError):
        return None


def detectar_decisiones_documento(
    *, archivo: str, datos: Mapping[str, object], carpeta_catalogos: str | Path,
    cliente_documental_original: str = "",
) -> list[dict[str, object]]:
    """Detecta incertidumbres por el estado final, no por la ruta OCR usada."""
    carpeta = Path(carpeta_catalogos)
    guia = str(datos.get("número de guía", ""))
    transporte = str(datos.get("número de transporte", ""))
    comunes = {"archivo": archivo, "numero_guia": guia, "numero_transporte": transporte}
    decisiones: list[dict[str, object]] = []

    for campo, clave_dato, tipo_esperado in (
        ("patente_tracto", "patente del tracto", "TRACTO"),
        ("patente_rampla", "patente del carro", "CARRO"),
    ):
        valor = str(datos.get(clave_dato, "")).strip()
        if valor in _AUSENTES:
            continue
        resultado = resolver_patente(
            carpeta / "vehiculos.json", valor, tipo_esperado=tipo_esperado
        )
        if resultado.estado in {"SIN_CANDIDATO", "CATALOGO_VACIO"}:
            decisiones.append(crear_decision(
                tipo="VEHICULO_DESCONOCIDO", entidad="VEHICULO", campo=campo,
                valor_documental=valor, valor_normalizado=resultado.valor_resultado,
                identidad_resuelta=None, candidatos=(),
                motivos=("SIN_VEHICULO_CONFIRMADO_COMPATIBLE",),
                evidencias=({"tipo": "OCR_DOCUMENTAL", "campo": campo, "valor": valor},),
                acciones_permitidas=("CONFIRMAR_NUEVO", "ASOCIAR_EXISTENTE", "POSPONER"),
                **comunes,
            ))

    cliente_final = str(datos.get("cliente", "")).strip()
    cliente_documental = str(cliente_documental_original or cliente_final).strip()
    rut_cliente = str(datos.get("RUT del cliente", "")).strip()
    cliente = _identidad_cliente_por_rut(carpeta, rut_cliente)
    rut_valido = validar_rut_chileno(rut_cliente).estado == EstadoValidacion.VALIDO
    identidad_cliente = None
    if cliente is not None:
        identidad_cliente = {
            "entidad_id": cliente.cliente_id,
            "valor_canonico": cliente.razon_social,
            "rut": cliente.rut,
        }
        claves_confirmadas = {
            normalizar_nombre_cliente(cliente.razon_social),
            *(normalizar_nombre_cliente(alias) for alias in cliente.aliases),
        }
        if (
            cliente_documental not in _AUSENTES
            and normalizar_nombre_cliente(cliente_documental) not in claves_confirmadas
        ):
            decisiones.append(crear_decision(
                tipo="ALIAS_CANDIDATO", entidad="CLIENTE", campo="cliente",
                valor_documental=cliente_documental,
                valor_normalizado=normalizar_nombre_cliente(cliente_documental),
                identidad_resuelta=identidad_cliente,
                candidatos=(identidad_cliente,), motivos=("RUT_EXACTO_ALIAS_NO_CONFIRMADO",),
                evidencias=({"tipo": "RUT_EXACTO", "campo": "rut_cliente", "valor": rut_cliente},),
                acciones_permitidas=("CONFIRMAR_ALIAS", "RECHAZAR", "POSPONER"),
                **comunes,
            ))
    elif rut_valido and cliente_documental not in _AUSENTES:
        empresas = cargar_catalogo_json(carpeta / "empresas.json")
        empresa = buscar_empresa_por_rut(empresas, rut_cliente)
        if empresa is not None:
            canonico = str(empresa.get("nombre", "")).strip()
            alias_confirmados = [str(x) for x in empresa.get("aliases", [])]
            claves = {normalizar_nombre_cliente(canonico), *(
                normalizar_nombre_cliente(alias) for alias in alias_confirmados
            )}
            if normalizar_nombre_cliente(cliente_documental) not in claves:
                identidad = {
                    "entidad_id": normalizar_rut_cliente(rut_cliente),
                    "valor_canonico": canonico,
                    "rut": normalizar_rut_cliente(rut_cliente),
                    "catalogo": "empresas.json",
                }
                decisiones.append(crear_decision(
                    tipo="ALIAS_CANDIDATO", entidad="CLIENTE", campo="cliente",
                    valor_documental=cliente_documental,
                    valor_normalizado=normalizar_nombre_cliente(cliente_documental),
                    identidad_resuelta=identidad, candidatos=(identidad,),
                    motivos=("RUT_EXACTO_ALIAS_NO_CONFIRMADO",),
                    evidencias=({"tipo": "RUT_EXACTO", "campo": "rut_cliente", "valor": rut_cliente},),
                    acciones_permitidas=("CONFIRMAR_ALIAS", "RECHAZAR", "POSPONER"),
                    **comunes,
                ))
        else:
            decisiones.append(crear_decision(
                tipo="CLIENTE_DESCONOCIDO", entidad="CLIENTE", campo="cliente",
                valor_documental=cliente_documental,
                valor_normalizado=normalizar_nombre_cliente(cliente_documental),
                identidad_resuelta=None, candidatos=(),
                motivos=("RUT_VALIDO_NO_EXISTE_EN_CATALOGO_MAESTRO",),
                evidencias=({"tipo": "RUT_VALIDO", "campo": "rut_cliente", "valor": rut_cliente},),
                acciones_permitidas=("CONFIRMAR_NUEVO", "ASOCIAR_EXISTENTE", "POSPONER"),
                **comunes,
            ))

    obra_texto = str(datos.get("obra destino", "")).strip()
    if identidad_cliente is not None and obra_texto not in _AUSENTES:
        try:
            catalogo_obras = CatalogoObrasDestinos(
                ruta=carpeta / "obras_destinos.json",
                ruta_clientes=carpeta / "clientes.json",
                ruta_destinos=carpeta / "destinos_maestros.json",
            )
            clave = normalizar_nombre_obra(obra_texto)
            obras = [
                obra for obra in catalogo_obras.listar_obras()
                if obra.cliente_id == cliente.cliente_id
                and obra.estado_vigencia == EstadoVigencia.ACTIVO.value
                and clave in {
                    normalizar_nombre_obra(obra.nombre_canonico),
                    *(normalizar_nombre_obra(alias) for alias in obra.aliases_documentales),
                }
            ]
            if not obras:
                decisiones.append(crear_decision(
                    tipo="OBRA_DESCONOCIDA", entidad="OBRA", campo="obra_destino",
                    valor_documental=obra_texto, valor_normalizado=clave,
                    identidad_resuelta=None, candidatos=(),
                    motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),
                    evidencias=({"tipo": "CLIENTE_RESUELTO", "entidad_id": cliente.cliente_id},),
                    acciones_permitidas=("REGISTRAR_OBSERVACION", "ASOCIAR_EXISTENTE", "POSPONER"),
                    **comunes,
                ))
            elif len(obras) == 1 and catalogo_obras.resolver_obra_destino_confirmada(
                cliente_id=cliente.cliente_id, nombre_obra=obra_texto
            ) is None:
                obra = obras[0]
                decisiones.append(crear_decision(
                    tipo="DESTINO_SIN_CONFIRMAR", entidad="RELACION_OBRA_DESTINO",
                    campo="obra_destino", valor_documental=obra_texto,
                    valor_normalizado=clave,
                    identidad_resuelta={
                        "entidad_id": obra.obra_id,
                        "valor_canonico": obra.nombre_canonico,
                    },
                    candidatos=(), motivos=("OBRA_SIN_RELACION_CONFIRMADA_UNICA",),
                    evidencias=({"tipo": "OBRA_IDENTIFICADA", "entidad_id": obra.obra_id},),
                    acciones_permitidas=("CONFIRMAR_RELACION", "RECHAZAR", "POSPONER"),
                    **comunes,
                ))
        except (OSError, ValueError):
            pass
    return decisiones


def generar_artefacto(
    *, ruta_dataset: str | Path, carpeta_catalogos: str | Path,
    decisiones: Iterable[Mapping[str, object]], ruta_salida: str | Path | None = None,
    reloj=lambda: datetime.now(timezone.utc),
) -> dict[str, object]:
    dataset = Path(ruta_dataset)
    catalogos = Path(carpeta_catalogos)
    salida = Path(ruta_salida) if ruta_salida is not None else dataset.parent / NOMBRE_ARTEFACTO
    hashes = {}
    for clave, nombre in {
        "clientes": "clientes.json", "vehiculos": "vehiculos.json",
        "obras_destinos": "obras_destinos.json",
        "destinos_maestros": "destinos_maestros.json",
    }.items():
        ruta = catalogos / nombre
        hashes[clave] = _sha256(ruta) if ruta.is_file() else None
    decisiones_unicas: list[dict[str, object]] = []
    ids_vistos: set[str] = set()
    for decision_original in decisiones:
        decision = dict(decision_original)
        decision_id = str(decision.get("decision_id", ""))
        if decision_id and decision_id in ids_vistos:
            continue
        if decision_id:
            ids_vistos.add(decision_id)
        decisiones_unicas.append(decision)
    artefacto = {
        "schema_version": SCHEMA_VERSION,
        "generado_en": reloj().astimezone(timezone.utc).isoformat(),
        "dataset_sha256": _sha256(dataset),
        "catalogos_sha256": hashes,
        "decisiones": decisiones_unicas,
    }
    escribir_json_atomico(salida, artefacto)
    return artefacto
