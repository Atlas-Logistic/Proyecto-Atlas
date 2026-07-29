"""Resolución aislada y determinista de chofer por nombre y RUT."""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass
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
)
from atlas_core.modelos import EstadoValidacion
from atlas_core.validadores import validar_rut_chileno


UMBRAL_FUZZY_CHOFER = 0.85
MARGEN_MINIMO_FUZZY_CHOFER = 0.05
MINIMO_RUT_PARCIAL = 4


@dataclass(frozen=True)
class HallazgoCatalogoChoferes:
    tipo: str
    clave: str
    identificadores: tuple[str, ...]


def normalizar_nombre_identidad(valor: object) -> str:
    """Normaliza búsqueda sin fusionar Ñ con N."""
    texto = " ".join(str(valor or "").strip().upper().split())
    salida: list[str] = []
    for caracter in texto:
        if caracter == "Ñ":
            salida.append(caracter)
            continue
        descompuesto = unicodedata.normalize("NFD", caracter)
        salida.extend(c for c in descompuesto if not unicodedata.combining(c))
    return "".join(salida)


def _rut_limpio(valor: object) -> str:
    return re.sub(r"[^0-9Kk]", "", str(valor or "")).upper()


def _rut_canonico_sin_formato(valor: object) -> str | None:
    limpio = _rut_limpio(valor)
    if len(limpio) < 2:
        return None
    candidato = f"{limpio[:-1]}-{limpio[-1]}"
    validado = validar_rut_chileno(candidato)
    if validado.estado is not EstadoValidacion.VALIDO:
        return None
    return _rut_limpio(validado.valor)


def _entidad(identificador_catalogo: str, registro: Mapping[str, Any]) -> EntidadCanonica:
    return EntidadCanonica(
        identificador=f"chofer:{identificador_catalogo}",
        valor=str(registro.get("nombre", "")).strip(),
        tipo_entidad="chofer",
        origen="catalogo_choferes:clave",
        activa=registro.get("activo", True) is True,
    )


def auditar_catalogo_choferes(
    catalogo: Mapping[str, Mapping[str, Any]],
) -> tuple[HallazgoCatalogoChoferes, ...]:
    indices: dict[str, dict[str, list[str]]] = {
        "RUT_DUPLICADO": {}, "NOMBRE_DUPLICADO": {},
        "ALIAS_COMPARTIDO": {}, "COLISION_NORMALIZACION": {},
    }
    identidades_rut: dict[str, list[str]] = {}
    formas_conservadoras: dict[str, dict[str, list[str]]] = {}
    for identificador, registro in sorted(catalogo.items()):
        if not isinstance(registro, Mapping):
            continue
        rut = _rut_canonico_sin_formato(identificador)
        if rut:
            identidades_rut.setdefault(rut, []).append(identificador)
        nombre = str(registro.get("nombre", "")).strip()
        nombre_norm = normalizar_nombre_identidad(nombre)
        indices["NOMBRE_DUPLICADO"].setdefault(nombre_norm, []).append(identificador)
        tolerante = nombre_norm.replace("Ñ", "N")
        formas_conservadoras.setdefault(tolerante, {}).setdefault(
            nombre_norm, []
        ).append(identificador)
        aliases = registro.get("aliases", ())
        if isinstance(aliases, (list, tuple)):
            for alias in aliases:
                clave = normalizar_nombre_identidad(alias)
                if clave:
                    indices["ALIAS_COMPARTIDO"].setdefault(clave, []).append(
                        identificador
                    )
    indices["RUT_DUPLICADO"] = identidades_rut
    hallazgos: list[HallazgoCatalogoChoferes] = []
    for tipo in ("RUT_DUPLICADO", "NOMBRE_DUPLICADO", "ALIAS_COMPARTIDO"):
        for clave, ids in sorted(indices[tipo].items()):
            if len(set(ids)) > 1:
                hallazgos.append(HallazgoCatalogoChoferes(tipo, clave, tuple(sorted(set(ids)))))
    for clave, variantes in sorted(formas_conservadoras.items()):
        ids = sorted({i for grupo in variantes.values() for i in grupo})
        if len(variantes) > 1:
            hallazgos.append(
                HallazgoCatalogoChoferes("COLISION_NORMALIZACION", clave, tuple(ids))
            )
    for rut, ids in sorted(identidades_rut.items()):
        estados = {
            catalogo[i].get("activo", True) is True
            for i in ids if isinstance(catalogo[i], Mapping)
        }
        if len(ids) > 1 and len(estados) > 1:
            hallazgos.append(
                HallazgoCatalogoChoferes("IDENTIDAD_ACTIVA_E_INACTIVA", rut, tuple(sorted(ids)))
            )
    return tuple(hallazgos)


def _observacion_nombre(nombre: object) -> ValorObservado:
    original = str(nombre or "")
    normalizado = normalizar_nombre_identidad(original)
    return ValorObservado(
        "nombre_chofer", original, normalizado, "OCR",
        Disponibilidad.DISPONIBLE if normalizado else Disponibilidad.AUSENTE,
        CalidadObservacion.NO_EVALUADA,
    )


def _observacion_rut(rut: object) -> tuple[ValorObservado, str]:
    original = str(rut or "")
    limpio = _rut_limpio(original)
    if not limpio:
        return ValorObservado(
            "rut_chofer", original, "", "OCR", Disponibilidad.AUSENTE,
            CalidadObservacion.NO_EVALUADA,
        ), "AUSENTE"
    tiene_separador_dv = "-" in original
    if (
        re.fullmatch(r"[0-9]+K?", limpio) is not None
        and MINIMO_RUT_PARCIAL <= len(limpio) < 8
        and not tiene_separador_dv
    ):
        return ValorObservado(
            "rut_chofer", original, limpio, "OCR", Disponibilidad.PARCIAL,
            CalidadObservacion.NO_EVALUADA,
            "Fragmento de RUT: no se usa como coincidencia exacta.",
        ), "PARCIAL"
    canonico = _rut_canonico_sin_formato(original)
    if canonico:
        return ValorObservado(
            "rut_chofer", original, canonico, "OCR", Disponibilidad.DISPONIBLE,
            CalidadObservacion.VALIDA,
            "RUT chileno válido; se normalizó sin puntos ni guion.",
        ), "VALIDO"
    if (
        re.fullmatch(r"[0-9]+K?", limpio) is not None
        and MINIMO_RUT_PARCIAL <= len(limpio) <= 8
    ):
        return ValorObservado(
            "rut_chofer", original, limpio, "OCR", Disponibilidad.PARCIAL,
            CalidadObservacion.NO_EVALUADA,
            "Fragmento de RUT: no se usa como coincidencia exacta.",
        ), "PARCIAL"
    return ValorObservado(
        "rut_chofer", original, limpio, "OCR", Disponibilidad.DISPONIBLE,
        CalidadObservacion.INVALIDA, "RUT chileno inválido.",
    ), "INVALIDO"


def _similitud(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def resolver_chofer_rut(
    nombre_ocr: object,
    rut_ocr: object,
    catalogo: Mapping[str, Mapping[str, Any]],
    contexto: Mapping[str, Any] | None = None,
) -> ResultadoResolucion:
    """Aplica una tabla de decisión explícita; nunca modifica ``catalogo``."""
    nombre_obs = _observacion_nombre(nombre_ocr)
    rut_obs, clase_rut = _observacion_rut(rut_ocr)
    registros = [
        (str(i), r, _entidad(str(i), r))
        for i, r in sorted(catalogo.items(), key=lambda item: str(item[0]))
        if isinstance(r, Mapping) and str(r.get("nombre", "")).strip()
    ]
    evidencias: list[EvidenciaResolucion] = []
    alternativas: list[AlternativaResolucion] = []

    rut_coincidentes: list[tuple[str, Mapping[str, Any], EntidadCanonica]] = []
    if clase_rut == "VALIDO":
        rut_coincidentes = [item for item in registros if _rut_canonico_sin_formato(item[0]) == rut_obs.valor_normalizado]
        for _, _, entidad in rut_coincidentes:
            evidencias.append(EvidenciaResolucion(
                "RUT_EXACTO_VALIDO", "catalogo_choferes", rut_obs, entidad, 1.0,
                "El RUT válido coincide exactamente con la clave del catálogo.", True,
            ))

    nombre_matches: list[tuple[str, Mapping[str, Any], EntidadCanonica, str]] = []
    if nombre_obs.valor_normalizado:
        for identificador, registro, entidad in registros:
            if normalizar_nombre_identidad(registro.get("nombre")) == nombre_obs.valor_normalizado:
                nombre_matches.append((identificador, registro, entidad, "NOMBRE_CANONICO_EXACTO"))
                continue
            aliases = registro.get("aliases", ())
            if isinstance(aliases, (list, tuple)) and any(
                normalizar_nombre_identidad(alias) == nombre_obs.valor_normalizado
                for alias in aliases
            ):
                nombre_matches.append((identificador, registro, entidad, "ALIAS_CONFIRMADO_EXACTO"))
        for _, _, entidad, tipo in nombre_matches:
            evidencias.append(EvidenciaResolucion(
                tipo, "catalogo_choferes", nombre_obs, entidad,
                1.0 if tipo == "NOMBRE_CANONICO_EXACTO" else 0.98,
                "Coincidencia única por nombre canónico." if tipo == "NOMBRE_CANONICO_EXACTO"
                else "Coincidencia con alias confirmado por una persona.",
                True,
            ))

    ranking: list[tuple[float, str, Mapping[str, Any], EntidadCanonica]] = []
    if nombre_obs.valor_normalizado and not nombre_matches:
        for identificador, registro, entidad in registros:
            variantes = [registro.get("nombre", "")]
            aliases = registro.get("aliases", ())
            if isinstance(aliases, (list, tuple)):
                variantes.extend(aliases)
            puntaje = max(
                (_similitud(nombre_obs.valor_normalizado, normalizar_nombre_identidad(v)) for v in variantes),
                default=0.0,
            )
            ranking.append((puntaje, identificador, registro, entidad))
        ranking.sort(key=lambda item: (-item[0], item[3].valor, item[1]))
        for puntaje, _, _, entidad in ranking[:2]:
            alternativas.append(AlternativaResolucion(entidad, puntaje, "Candidato por similitud difusa."))

    nombre_fuerte: tuple[str, Mapping[str, Any], EntidadCanonica, str] | None = None
    nombre_ambiguo = False
    if len(nombre_matches) == 1:
        nombre_fuerte = nombre_matches[0]
    elif len(nombre_matches) > 1:
        nombre_ambiguo = True
    elif ranking:
        mejor = ranking[0]
        segunda = ranking[1][0] if len(ranking) > 1 else 0.0
        margen = mejor[0] - segunda
        if mejor[0] >= UMBRAL_FUZZY_CHOFER and margen >= MARGEN_MINIMO_FUZZY_CHOFER:
            nombre_fuerte = (mejor[1], mejor[2], mejor[3], "NOMBRE_FUZZY")
            evidencias.append(EvidenciaResolucion(
                "NOMBRE_FUZZY", "comparacion_determinista", nombre_obs, mejor[3],
                mejor[0], f"Similitud {mejor[0]:.3f}; margen {margen:.3f}.", True,
            ))
        elif mejor[0] >= UMBRAL_FUZZY_CHOFER:
            nombre_ambiguo = True

    parcial_coincidentes: list[tuple[str, Mapping[str, Any], EntidadCanonica]] = []
    if clase_rut == "PARCIAL":
        parcial = rut_obs.valor_normalizado
        parcial_coincidentes = [
            item for item in registros
            if (canon := _rut_canonico_sin_formato(item[0]))
            and (canon.startswith(parcial) or canon.endswith(parcial))
        ]
        for _, _, entidad in parcial_coincidentes:
            evidencias.append(EvidenciaResolucion(
                "RUT_PARCIAL_COMPATIBLE", "catalogo_choferes", rut_obs, entidad,
                0.55, "El fragmento coincide, pero no prueba un RUT exacto.", True,
            ))

    contradicciones: list[ContradiccionResolucion] = []
    rut_entidad = rut_coincidentes[0][2] if len(rut_coincidentes) == 1 else None
    nombre_entidad = nombre_fuerte[2] if nombre_fuerte else None
    if rut_entidad and nombre_entidad and rut_entidad.identificador != nombre_entidad.identificador:
        enfrentadas = tuple(
            e for e in evidencias
            if e.candidato and e.candidato.identificador in {
                rut_entidad.identificador, nombre_entidad.identificador
            }
        )
        contradicciones.append(ContradiccionResolucion(
            ("nombre_chofer", "rut_chofer"), enfrentadas,
            (rut_entidad, nombre_entidad),
            "El nombre y el RUT apuntan claramente a personas distintas.",
            GravedadContradiccion.ALTA, "Impide confirmar o corregir silenciosamente.",
        ))
    if nombre_entidad and clase_rut == "PARCIAL" and (
        not parcial_coincidentes
        or all(item[2].identificador != nombre_entidad.identificador for item in parcial_coincidentes)
    ):
        relacionadas = tuple(e for e in evidencias if e.candidato == nombre_entidad)
        contradicciones.append(ContradiccionResolucion(
            ("nombre_chofer", "rut_chofer"), relacionadas, (nombre_entidad,),
            "El fragmento de RUT es incompatible con la identidad indicada por el nombre.",
            GravedadContradiccion.ALTA, "Obliga a revisión humana.",
        ))

    candidato = rut_entidad or nombre_entidad
    razones: list[str] = [
        "Los valores OCR originales se conservaron sin sobrescritura.",
        "La decisión se obtuvo mediante una tabla de evidencias, no por aprendizaje automático.",
    ]
    if len(rut_coincidentes) > 1:
        estado, confianza = EstadoResolucion.REQUIERE_REVISION, 0.0
        candidato = None
        razones.append("Más de una entidad comparte el mismo RUT válido.")
    elif contradicciones:
        estado, confianza = EstadoResolucion.REQUIERE_REVISION, 0.0
        razones.append("Existe una contradicción explícita entre campos.")
    elif nombre_ambiguo:
        estado, confianza = EstadoResolucion.REQUIERE_REVISION, 0.0
        candidato = None
        razones.append("El nombre tiene candidatos ambiguos o una clave exacta compartida.")
    elif candidato and candidato.activa is not True:
        estado, confianza = EstadoResolucion.REQUIERE_REVISION, 0.0
        razones.append("La identidad candidata está inactiva.")
    elif clase_rut == "INVALIDO" and candidato:
        estado, confianza = EstadoResolucion.REQUIERE_REVISION, 0.0
        razones.append("El RUT observado es inválido y debe revisarse.")
    elif rut_entidad:
        estado = EstadoResolucion.CONFIRMADO
        confianza = 1.0 if nombre_entidad == rut_entidad else 0.95
        razones.append("Un RUT chileno válido y único fija la identidad canónica.")
    elif nombre_fuerte and nombre_fuerte[3] in {"NOMBRE_CANONICO_EXACTO", "ALIAS_CONFIRMADO_EXACTO"}:
        if clase_rut == "PARCIAL" and parcial_coincidentes and all(
            item[2].identificador != nombre_entidad.identificador for item in parcial_coincidentes
        ):
            estado, confianza = EstadoResolucion.REQUIERE_REVISION, 0.0
        else:
            estado, confianza = EstadoResolucion.CONFIRMADO, 0.90
            razones.append("Nombre canónico o alias humano confirmado, exacto y único.")
    elif nombre_fuerte and nombre_fuerte[3] == "NOMBRE_FUZZY":
        estado, confianza = EstadoResolucion.PROPUESTO, next(
            e.fuerza for e in evidencias if e.tipo == "NOMBRE_FUZZY"
        )
        razones.append("El fuzzy aislado solo puede proponer; nunca confirma por 0,85.")
    elif clase_rut == "PARCIAL" and len(parcial_coincidentes) == 1:
        candidato = parcial_coincidentes[0][2]
        estado, confianza = EstadoResolucion.PROPUESTO, 0.55
        razones.append("Un RUT parcial único solo permite proponer.")
    else:
        candidato = None
        estado, confianza = EstadoResolucion.NO_RESUELTO, 0.0
        razones.append("No existe evidencia suficiente para resolver.")

    if candidato and not any(a.entidad.identificador == candidato.identificador for a in alternativas):
        alternativas.insert(0, AlternativaResolucion(candidato, None, "Candidato principal."))
    return ResultadoResolucion(
        "chofer", (nombre_obs, rut_obs), candidato, estado, confianza,
        tuple(evidencias), tuple(contradicciones), tuple(razones),
        estado in {EstadoResolucion.REQUIERE_REVISION, EstadoResolucion.PROPUESTO},
        tuple(alternativas[:3]), contexto,
    )
