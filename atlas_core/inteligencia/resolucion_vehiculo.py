"""Resolución conservadora y aislada de vehículo, patente y rol."""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from atlas_core.inteligencia.contrato_multicampo import (
    AlternativaResolucion,
    CalidadObservacion,
    ContradiccionResolucion,
    Disponibilidad,
    EntidadCanonica,
    EstadoResolucion,
    EvidenciaResolucion,
    GravedadContradiccion,
    ResultadoResolucion,
    ValorObservado,
    requiere_revision_por_estado,
)
from atlas_core.inteligencia.politica_confianza_vehiculo import (
    POLITICA_CONFIANZA_VEHICULO_V1,
    PoliticaConfianzaVehiculo,
    ViaDecisionVehiculo,
)
from atlas_core.inteligencia.snapshot_catalogo_vehiculos import (
    InstantaneaCatalogoVehiculos,
    crear_snapshot_catalogo_vehiculos,
    normalizar_patente,
    normalizar_rol_vehiculo,
)


_CONFUSIONES = {
    "B": "8", "8": "B", "O": "0", "0": "O", "I": "1T",
    "1": "I", "T": "I", "S": "5", "5": "S", "Z": "2",
    "2": "Z", "G": "6", "6": "G",
}


def patente_chilena_valida(valor: object) -> bool:
    patente = normalizar_patente(valor)
    return bool(
        re.fullmatch(r"[A-Z]{2}[0-9]{4}", patente)
        or re.fullmatch(r"[A-Z]{4}[0-9]{2}", patente)
    )


@dataclass(frozen=True)
class HallazgoCatalogoVehiculos:
    codigo: str
    detalle: str
    identificadores: tuple[str, ...]


@dataclass(frozen=True)
class ResultadoResolucionVehiculo(ResultadoResolucion):
    patente_original: str = ""
    patente_tracto_original: str = ""
    patente_rampla_original: str = ""
    patente_canonica: str | None = None
    patente_tracto_canonica: str | None = None
    patente_rampla_canonica: str | None = None
    id_vehiculo_canonico: str | None = None
    tipo_vehiculo_canonico: str | None = None
    rol_patente: str | None = None

    @property
    def estado_resolucion(self) -> EstadoResolucion:
        return self.estado

    @property
    def requiere_revision(self) -> bool:
        return self.requiere_revision_humana


def auditar_catalogo_vehiculos(
    catalogo: Mapping[str, Any] | InstantaneaCatalogoVehiculos,
) -> tuple[HallazgoCatalogoVehiculos, ...]:
    snapshot = (
        catalogo
        if isinstance(catalogo, InstantaneaCatalogoVehiculos)
        else crear_snapshot_catalogo_vehiculos(catalogo)
    )
    por_patente: dict[str, list[str]] = {}
    por_alias: dict[str, list[str]] = {}
    hallazgos: list[HallazgoCatalogoVehiculos] = []
    for identificador, registro in snapshot.registros.items():
        patente = str(registro["patente"])
        por_patente.setdefault(patente, []).append(identificador)
        for alias in registro["aliases"]:
            por_alias.setdefault(str(alias), []).append(identificador)
        if not patente_chilena_valida(patente):
            hallazgos.append(HallazgoCatalogoVehiculos(
                "PATENTE_INVALIDA", patente, (identificador,)
            ))
        if registro["tipo"] not in {"TRACTO", "RAMPLA", "CAMION_CAJITA"}:
            hallazgos.append(HallazgoCatalogoVehiculos(
                "ROL_DESCONOCIDO", str(registro["tipo"]), (identificador,)
            ))
    for patente, ids in por_patente.items():
        if patente and len(ids) > 1:
            hallazgos.append(HallazgoCatalogoVehiculos(
                "PATENTE_DUPLICADA", patente, tuple(sorted(ids))
            ))
    for alias, ids in por_alias.items():
        destinos = set(ids) | set(por_patente.get(alias, ()))
        if alias and len(destinos) > 1:
            hallazgos.append(HallazgoCatalogoVehiculos(
                "ALIAS_PATENTE_AMBIGUO", alias, tuple(sorted(destinos))
            ))
    return tuple(sorted(
        hallazgos,
        key=lambda item: (item.codigo, item.detalle, item.identificadores),
    ))


def _observacion_patente(campo: str, valor: object) -> ValorObservado:
    original = "" if valor is None else str(valor)
    normalizado = normalizar_patente(original)
    if not normalizado:
        return ValorObservado(
            campo, original, "", "OCR", Disponibilidad.AUSENTE,
            CalidadObservacion.NO_EVALUADA, "Patente ausente.",
        )
    if len(normalizado) < 6:
        return ValorObservado(
            campo, original, normalizado, "OCR", Disponibilidad.PARCIAL,
            CalidadObservacion.NO_EVALUADA,
            "Fragmento insuficiente; nunca identifica un vehículo.",
        )
    valida = patente_chilena_valida(normalizado)
    return ValorObservado(
        campo, original, normalizado, "OCR", Disponibilidad.DISPONIBLE,
        CalidadObservacion.VALIDA if valida else CalidadObservacion.INVALIDA,
        (
            "Formato chileno antiguo o nuevo válido."
            if valida else "La lectura no tiene estructura de patente chilena."
        ),
    )


def _entidad(identificador: str, registro: Mapping[str, Any]) -> EntidadCanonica:
    return EntidadCanonica(
        identificador,
        str(registro["patente"]),
        "vehiculo",
        str(registro["origen"]),
        str(registro["estado_vigencia"]) == "ACTIVO",
    )


def _variantes_visuales(valor: str) -> set[str]:
    variantes: set[str] = set()
    for indice, caracter in enumerate(valor):
        for reemplazo in _CONFUSIONES.get(caracter, ""):
            variante = valor[:indice] + reemplazo + valor[indice + 1:]
            if patente_chilena_valida(variante):
                variantes.add(variante)
    return variantes


def _calidad(calidades: Mapping[str, float], campo: str) -> float:
    valor = float(calidades.get(campo, 1.0))
    if not 0.0 <= valor <= 1.0:
        raise ValueError("la calidad de evidencia debe estar entre 0 y 1")
    return valor


def resolver_vehiculo_patente(
    patente_tracto: object = "",
    patente_rampla: object = "",
    patente: object = "",
    tipo_vehiculo: object = "",
    catalogo: Mapping[str, Any] | InstantaneaCatalogoVehiculos = MappingProxyType({}),
    *,
    vehiculo: object = "",
    calidades: Mapping[str, float] | None = None,
    contexto: Mapping[str, Any] | None = None,
    campo_obligatorio: bool = True,
    politica_confianza: PoliticaConfianzaVehiculo = POLITICA_CONFIANZA_VEHICULO_V1,
) -> ResultadoResolucionVehiculo:
    snapshot = (
        catalogo
        if isinstance(catalogo, InstantaneaCatalogoVehiculos)
        else crear_snapshot_catalogo_vehiculos(catalogo)
    )
    calidad_campos = calidades or {}
    observaciones = (
        _observacion_patente("patente_tracto", patente_tracto),
        _observacion_patente("patente_rampla", patente_rampla),
        _observacion_patente("patente", patente),
    )
    tipo_original = "" if tipo_vehiculo is None else str(tipo_vehiculo)
    tipo_normalizado = normalizar_rol_vehiculo(tipo_original)
    tipo_disponible = bool(tipo_original.strip())
    observacion_tipo = ValorObservado(
        "tipo_vehiculo", tipo_original,
        tipo_normalizado if tipo_disponible else "",
        "OCR_O_ESTRUCTURA",
        Disponibilidad.DISPONIBLE if tipo_disponible else Disponibilidad.AUSENTE,
        CalidadObservacion.NO_EVALUADA,
        "Tipo usado solo como evidencia de rol compatible.",
    )
    nombre_original = "" if vehiculo is None else str(vehiculo)
    observacion_nombre = ValorObservado(
        "vehiculo", nombre_original, nombre_original.strip().upper(),
        "OCR", Disponibilidad.DISPONIBLE if nombre_original.strip()
        else Disponibilidad.AUSENTE,
        CalidadObservacion.NO_EVALUADA,
        "Nombre o alias nunca confirma sin patente.",
    )
    todas_observaciones = (*observaciones, observacion_tipo, observacion_nombre)
    registros = [
        (identificador, registro, _entidad(identificador, registro))
        for identificador, registro in snapshot.registros.items()
    ]
    evidencias: list[EvidenciaResolucion] = []
    contradicciones: list[ContradiccionResolucion] = []
    alternativas: list[AlternativaResolucion] = []
    resueltos: dict[str, tuple[EntidadCanonica, Mapping[str, Any], str]] = {}
    ambiguos = False

    roles_esperados = {
        "patente_tracto": "TRACTO",
        "patente_rampla": "RAMPLA",
        "patente": (
            tipo_normalizado if tipo_disponible else "DESCONOCIDO"
        ),
    }

    for observado in observaciones:
        if observado.disponibilidad is Disponibilidad.AUSENTE:
            continue
        if observado.disponibilidad is Disponibilidad.PARCIAL:
            evidencias.append(EvidenciaResolucion(
                "PATENTE_PARCIAL_INSUFICIENTE", "politica_vehiculo",
                observado, None, 0.0, observado.detalle_calidad, False,
            ))
            continue
        if observado.calidad is CalidadObservacion.INVALIDA:
            evidencias.append(EvidenciaResolucion(
                "PATENTE_FORMATO_INVALIDO", "validador_patente_chilena",
                observado, None, 0.0, observado.detalle_calidad, False,
            ))
        exactos = [
            (identificador, registro, entidad)
            for identificador, registro, entidad in registros
            if registro["patente"] == observado.valor_normalizado
        ]
        aliases = [
            (identificador, registro, entidad)
            for identificador, registro, entidad in registros
            if observado.valor_normalizado in registro["aliases"]
        ]
        candidatos_por_id = {
            identificador: (identificador, registro, entidad)
            for identificador, registro, entidad in (*exactos, *aliases)
        }
        candidatos = list(candidatos_por_id.values())
        tipo_evidencia = (
            "PATENTE_EXACTA"
            if exactos and len(candidatos) == 1
            else "ALIAS_PATENTE_HISTORICO"
        )
        if not candidatos:
            variantes = _variantes_visuales(observado.valor_normalizado)
            candidatos = [
                (identificador, registro, entidad)
                for identificador, registro, entidad in registros
                if registro["patente"] in variantes
            ]
            tipo_evidencia = "CORRECCION_VISUAL_UN_CARACTER"
        if not candidatos:
            evidencias.append(EvidenciaResolucion(
                "PATENTE_NO_EXISTE_EN_CATALOGO", "snapshot_vehiculos",
                observado, None, 0.0,
                "Lectura válida sin identidad canónica; se conserva.", False,
            ))
            continue
        for _, registro, entidad in candidatos:
            alternativas.append(AlternativaResolucion(
                entidad,
                1.0 if tipo_evidencia in {
                    "PATENTE_EXACTA", "ALIAS_PATENTE_HISTORICO"
                } else None,
                (
                    "Coincidencia exacta."
                    if tipo_evidencia == "PATENTE_EXACTA"
                    else (
                        "Corrección histórica trazable del catálogo."
                        if tipo_evidencia == "ALIAS_PATENTE_HISTORICO"
                        else "Una sustitución OCR confundible; requiere revisión."
                    )
                ),
            ))
        if len(candidatos) != 1:
            ambiguos = True
            for _, _, entidad in candidatos:
                evidencias.append(EvidenciaResolucion(
                    tipo_evidencia, "snapshot_vehiculos", observado, entidad,
                    1.0 if tipo_evidencia in {
                        "PATENTE_EXACTA", "ALIAS_PATENTE_HISTORICO"
                    } else 0.6,
                    "Más de una identidad compatible.", False,
                ))
            continue
        _, registro, entidad = candidatos[0]
        rol_esperado = roles_esperados[observado.campo]
        rol_real = str(registro["tipo"])
        compatible = rol_esperado == "DESCONOCIDO" or rol_esperado == rol_real
        evidencia = EvidenciaResolucion(
            tipo_evidencia, "snapshot_vehiculos", observado, entidad,
            _calidad(calidad_campos, observado.campo) * (
                1.0 if tipo_evidencia in {
                    "PATENTE_EXACTA", "ALIAS_PATENTE_HISTORICO"
                } else 0.7
            ),
            (
                "Patente exacta y única en catálogo."
                if tipo_evidencia == "PATENTE_EXACTA"
                else (
                    "Alias histórico explícito y único en el catálogo."
                    if tipo_evidencia == "ALIAS_PATENTE_HISTORICO"
                    else "Un carácter confundible conduce a un único candidato."
                )
            ),
            compatible,
        )
        evidencias.append(evidencia)
        resueltos[observado.campo] = (entidad, registro, tipo_evidencia)
        if not compatible:
            contradicciones.append(ContradiccionResolucion(
                (observado.campo, "tipo_vehiculo"),
                (evidencia,),
                (entidad,),
                f"Rol esperado {rol_esperado}, catálogo indica {rol_real}.",
                GravedadContradiccion.ALTA,
                "Exige revisión y no reasigna la patente.",
            ))

    if nombre_original.strip() and not resueltos:
        nombre_normalizado = nombre_original.strip().upper()
        candidatos_nombre = [
            (registro, entidad)
            for _, registro, entidad in registros
            if nombre_normalizado == str(registro["nombre"]).upper()
            or nombre_normalizado in {
                str(alias).upper() for alias in registro["aliases_nombre"]
            }
        ]
        if len(candidatos_nombre) == 1:
            registro, entidad = candidatos_nombre[0]
            evidencias.append(EvidenciaResolucion(
                "ALIAS_VEHICULO_SIN_PATENTE", "snapshot_vehiculos",
                observacion_nombre, entidad, 0.4,
                "El nombre solo propone; no confirma vehículo.", True,
            ))
            alternativas.append(AlternativaResolucion(
                entidad, None, "Nombre o alias sin patente verificable."
            ))

    tracto = resueltos.get("patente_tracto")
    rampla = resueltos.get("patente_rampla")
    generica = resueltos.get("patente")
    generica_observada = observaciones[2]
    intercambiados = bool(
        tracto and rampla
        and tracto[1]["tipo"] == "RAMPLA"
        and rampla[1]["tipo"] == "TRACTO"
    )
    if intercambiados:
        evidencias_par = tuple(
            evidencia for evidencia in evidencias
            if evidencia.observado.campo in {"patente_tracto", "patente_rampla"}
            and evidencia.candidato is not None
        )
        contradicciones.append(ContradiccionResolucion(
            ("patente_tracto", "patente_rampla"),
            evidencias_par,
            tuple(item[0] for item in (tracto, rampla)),
            "Las patentes de tracto y rampla están intercambiadas.",
            GravedadContradiccion.ALTA,
            "Exige revisión; no corrige silenciosamente los campos.",
        ))

    if tracto and rampla and generica_observada.disponibilidad is not (
        Disponibilidad.AUSENTE
    ):
        ids_par = {tracto[0].identificador, rampla[0].identificador}
        generica_compatible = bool(
            generica and generica[0].identificador in ids_par
        )
        if not generica_compatible:
            evidencias_generica = tuple(
                evidencia for evidencia in evidencias
                if evidencia.observado.campo == "patente"
            )
            candidatos_generica = tuple(dict.fromkeys(
                evidencia.candidato for evidencia in evidencias_generica
                if evidencia.candidato is not None
            ))
            contradicciones.append(ContradiccionResolucion(
                ("patente", "patente_tracto", "patente_rampla"),
                evidencias_generica,
                (tracto[0], rampla[0], *candidatos_generica),
                "La patente genérica no corresponde al par tracto/rampla.",
                GravedadContradiccion.ALTA,
                "Exige revisión; la patente genérica no reemplaza la identidad principal.",
            ))

    principal = tracto or generica or rampla
    es_cajita = bool(
        principal and principal[1]["tipo"] == "CAMION_CAJITA"
        and tipo_normalizado == "CAMION_CAJITA"
    )
    falsa_rampla = es_cajita and observaciones[1].disponibilidad is not (
        Disponibilidad.AUSENTE
    )
    if falsa_rampla:
        contradicciones.append(ContradiccionResolucion(
            ("tipo_vehiculo", "patente_rampla"),
            tuple(
                evidencia for evidencia in evidencias
                if evidencia.observado.campo == "patente_rampla"
            ),
            tuple(
                evidencia.candidato for evidencia in evidencias
                if evidencia.observado.campo == "patente_rampla"
                and evidencia.candidato is not None
            ),
            "Un camión cajita no debe tener rampla.",
            GravedadContradiccion.ALTA,
            "Exige revisión por posible falso OCR de rampla.",
        ))

    via = ViaDecisionVehiculo.NO_RESUELTO
    estado = EstadoResolucion.NO_RESUELTO
    candidato = principal[0] if principal else None
    razones = [
        "Los OCR originales se conservaron sin sobrescritura.",
        "No hubo aprendizaje ni escritura de catálogos.",
    ]
    if contradicciones:
        estado = EstadoResolucion.REQUIERE_REVISION
        via = (
            ViaDecisionVehiculo.TRACTO_RAMPLA_INTERCAMBIADOS
            if intercambiados
            else ViaDecisionVehiculo.CONTRADICCION_ROL
        )
    elif ambiguos:
        candidato = None
        estado = EstadoResolucion.REQUIERE_REVISION
        via = ViaDecisionVehiculo.DUPLICADO
    elif principal and principal[0].activa is False:
        estado = EstadoResolucion.REQUIERE_REVISION
        via = ViaDecisionVehiculo.INACTIVO
    elif principal and str(principal[1]["estado_calidad"]) != "CONFIRMADO":
        estado = EstadoResolucion.REQUIERE_REVISION
        via = ViaDecisionVehiculo.EVIDENCIA_BAJA
    elif principal and str(principal[1]["tipo"]) not in {
        "TRACTO", "RAMPLA", "CAMION_CAJITA",
    }:
        estado = EstadoResolucion.REQUIERE_REVISION
        via = ViaDecisionVehiculo.EVIDENCIA_BAJA
    elif principal and any(
        item[2] == "CORRECCION_VISUAL_UN_CARACTER"
        for item in resueltos.values()
    ):
        estado = EstadoResolucion.PROPUESTO
        via = ViaDecisionVehiculo.CORRECCION_VISUAL_UNICA
    elif principal and any(
        evidencia.tipo == "PATENTE_FORMATO_INVALIDO"
        for evidencia in evidencias
    ):
        estado = EstadoResolucion.REQUIERE_REVISION
        via = ViaDecisionVehiculo.EVIDENCIA_BAJA
    elif principal and any(
        evidencia.candidato == principal[0] and evidencia.fuerza < 0.8
        for evidencia in evidencias
    ):
        estado = EstadoResolucion.REQUIERE_REVISION
        via = ViaDecisionVehiculo.EVIDENCIA_BAJA
    elif principal:
        estado = EstadoResolucion.CONFIRMADO
        via = (
            ViaDecisionVehiculo.PAR_TRACTO_RAMPLA_EXACTO
            if tracto and rampla
            else ViaDecisionVehiculo.PATENTE_EXACTA_UNICA
        )
    elif any(e.tipo == "ALIAS_VEHICULO_SIN_PATENTE" for e in evidencias):
        estado = EstadoResolucion.PROPUESTO
        via = ViaDecisionVehiculo.ALIAS_SIN_PATENTE
        candidato = next(
            e.candidato for e in evidencias
            if e.tipo == "ALIAS_VEHICULO_SIN_PATENTE"
        )

    explicaciones = {
        ViaDecisionVehiculo.PATENTE_EXACTA_UNICA:
            "Una patente exacta, válida, activa y única confirmó identidad.",
        ViaDecisionVehiculo.PAR_TRACTO_RAMPLA_EXACTO:
            "Tracto y rampla exactos confirmaron un par de roles compatible.",
        ViaDecisionVehiculo.CORRECCION_VISUAL_UNICA:
            "La corrección visual única solo propone y exige revisión.",
        ViaDecisionVehiculo.ALIAS_SIN_PATENTE:
            "Un nombre o alias sin patente solo propone identidad.",
        ViaDecisionVehiculo.CONTRADICCION_ROL:
            "La patente y el rol esperado se contradicen.",
        ViaDecisionVehiculo.TRACTO_RAMPLA_INTERCAMBIADOS:
            "Los roles de tracto y rampla aparecen intercambiados.",
        ViaDecisionVehiculo.DUPLICADO:
            "Más de una identidad del catálogo es compatible.",
        ViaDecisionVehiculo.INACTIVO:
            "La identidad está inactiva y requiere revisión.",
        ViaDecisionVehiculo.EVIDENCIA_BAJA:
            "La calidad, estructura o clasificación no permite confirmar.",
        ViaDecisionVehiculo.NO_RESUELTO:
            "No existe evidencia canónica suficiente para resolver.",
    }
    razones.append(explicaciones[via])

    tracto_canonico = tracto[0].valor if tracto else None
    rampla_canonica = rampla[0].valor if rampla else None
    patente_canonica = principal[0].valor if principal else None
    rol = str(principal[1]["tipo"]) if principal else None
    if candidato and principal and (
        patente_canonica != candidato.valor
        or rol != str(principal[1]["tipo"])
    ):
        raise AssertionError(
            "invariante vehículo: ID, patente y rol canónicos deben describir "
            "la misma identidad"
        )
    if estado is EstadoResolucion.CONFIRMADO and contradicciones:
        raise AssertionError(
            "invariante vehículo: un resultado confirmado no admite contradicciones"
        )
    rampla_salida = "NO_APLICA" if es_cajita else rampla_canonica
    contexto_salida = dict(contexto or {})
    contexto_salida["rampla_disponibilidad"] = (
        "NO_APLICA" if es_cajita
        else (
            "AUSENTE"
            if observaciones[1].disponibilidad is Disponibilidad.AUSENTE
            else observaciones[1].disponibilidad.value
        )
    )
    return ResultadoResolucionVehiculo(
        "vehiculo",
        todas_observaciones,
        candidato,
        estado,
        politica_confianza.confianza(via),
        tuple(evidencias),
        tuple(contradicciones),
        tuple(razones),
        requiere_revision_por_estado(
            estado, campo_obligatorio=campo_obligatorio
        ),
        tuple(sorted(
            alternativas,
            key=lambda item: (item.entidad.valor, item.entidad.identificador),
        )),
        contexto_salida,
        politica_confianza.version,
        via.value,
        snapshot.version,
        "" if patente is None else str(patente),
        "" if patente_tracto is None else str(patente_tracto),
        "" if patente_rampla is None else str(patente_rampla),
        patente_canonica,
        tracto_canonico,
        rampla_salida,
        candidato.identificador if candidato else None,
        rol,
        rol,
    )
