"""Resolución aislada, conservadora y trazable de cliente + RUT."""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

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
from atlas_core.inteligencia.politica_confianza_cliente import (
    POLITICA_CONFIANZA_CLIENTE_V1,
    PoliticaConfianzaCliente,
    ViaDecisionCliente,
)
from atlas_core.inteligencia.snapshot_catalogo_clientes import (
    InstantaneaCatalogoClientes,
    crear_snapshot_catalogo_clientes,
)
from atlas_core.modelos import EstadoValidacion
from atlas_core.validadores import validar_rut_chileno


UMBRAL_FUZZY_CLIENTE = 0.88
MARGEN_MINIMO_FUZZY_CLIENTE = 0.08
MINIMO_CARACTERES_FUZZY_CLIENTE = 5

_SUFIJOS: tuple[tuple[str, ...], ...] = (
    ("EMPRESA", "INDIVIDUAL", "DE", "RESPONSABILIDAD", "LIMITADA"),
    ("SOCIEDAD", "POR", "ACCIONES"),
    ("SOCIEDAD", "ANONIMA"),
    ("LIMITADA",),
    ("E", "I", "R", "L"),
    ("EIRL",),
    ("L", "T", "D", "A"),
    ("LTDA",),
    ("S", "P", "A"),
    ("SPA",),
    ("S", "A"),
    ("SA",),
)


@dataclass(frozen=True)
class HallazgoCatalogoClientes:
    tipo: str
    clave: str
    identificadores: tuple[str, ...]


@dataclass(frozen=True)
class ResultadoResolucionCliente(ResultadoResolucion):
    rut_cliente_canonico: str | None = None

    @property
    def cliente_original(self) -> str:
        return self.ultimos_valores_ocr_originales.get("cliente", "")

    @property
    def rut_cliente_original(self) -> str:
        return self.ultimos_valores_ocr_originales.get("rut_cliente", "")

    @property
    def cliente_canonico(self) -> str | None:
        return self.valor_canonico

    @property
    def id_cliente_canonico(self) -> str | None:
        return self.identificador_canonico

    @property
    def requiere_revision(self) -> bool:
        return self.requiere_revision_humana


def normalizar_nombre_cliente_multicampo(valor: object) -> str:
    """Normaliza variantes empresariales sin usar subcadenas ni perder Ñ."""
    texto = unicodedata.normalize(
        "NFC", " ".join(str(valor or "").strip().upper().split())
    )
    sin_diacriticos: list[str] = []
    for caracter in texto:
        if caracter == "Ñ":
            sin_diacriticos.append(caracter)
            continue
        descompuesto = unicodedata.normalize("NFD", caracter)
        sin_diacriticos.extend(
            item for item in descompuesto if not unicodedata.combining(item)
        )
    tokens = re.findall(r"[A-Z0-9Ñ]+", "".join(sin_diacriticos))
    cambio = True
    while tokens and cambio:
        cambio = False
        for sufijo in _SUFIJOS:
            if tuple(tokens[-len(sufijo):]) == sufijo:
                tokens = tokens[:-len(sufijo)]
                cambio = True
                break
    return " ".join(tokens)


def _rut_limpio(valor: object) -> str:
    return re.sub(r"[^0-9Kk]", "", str(valor or "")).upper()


def _rut_canonico(valor: object) -> str | None:
    limpio = _rut_limpio(valor)
    if len(limpio) < 2:
        return None
    validado = validar_rut_chileno(f"{limpio[:-1]}-{limpio[-1]}")
    if validado.estado is not EstadoValidacion.VALIDO:
        return None
    return _rut_limpio(validado.valor)


def _entidad(
    identificador: str, registro: Mapping[str, Any]
) -> EntidadCanonica:
    activa = str(registro.get("estado_vigencia", "ACTIVO")).upper() == "ACTIVO"
    return EntidadCanonica(
        identificador=f"cliente:{identificador}",
        valor=str(registro.get("razon_social", "")).strip(),
        tipo_entidad="cliente",
        origen=f"{registro.get('origen', 'catalogo_clientes')}:cliente_id",
        activa=activa,
    )


def _variantes_nombre(registro: Mapping[str, Any]) -> tuple[str, ...]:
    valores: list[str] = [
        str(registro.get("razon_social", "")),
        str(registro.get("nombre_comercial", "")),
    ]
    aliases = registro.get("aliases", ())
    if isinstance(aliases, (tuple, list)):
        valores.extend(str(alias) for alias in aliases)
    return tuple(valor for valor in valores if valor.strip())


def _calidad_confirmada(registro: Mapping[str, Any]) -> bool:
    return str(registro.get("estado_calidad", "")).upper() == "CONFIRMADO"


def auditar_catalogo_clientes(
    catalogo: (
        Mapping[str, Any]
        | Iterable[Mapping[str, Any]]
        | InstantaneaCatalogoClientes
    ),
) -> tuple[HallazgoCatalogoClientes, ...]:
    snapshot = (
        catalogo
        if isinstance(catalogo, InstantaneaCatalogoClientes)
        else crear_snapshot_catalogo_clientes(catalogo)
    )
    indices: dict[str, dict[str, list[str]]] = {
        "RUT_DUPLICADO": {},
        "NOMBRE_DUPLICADO": {},
        "ALIAS_COMPARTIDO": {},
    }
    for identificador, registro in snapshot.registros.items():
        rut = _rut_canonico(registro.get("rut"))
        if rut:
            indices["RUT_DUPLICADO"].setdefault(rut, []).append(identificador)
        razon = normalizar_nombre_cliente_multicampo(
            registro.get("razon_social")
        )
        if razon:
            indices["NOMBRE_DUPLICADO"].setdefault(razon, []).append(
                identificador
            )
        aliases = registro.get("aliases", ())
        if isinstance(aliases, (tuple, list)):
            for alias in aliases:
                clave = normalizar_nombre_cliente_multicampo(alias)
                if clave:
                    indices["ALIAS_COMPARTIDO"].setdefault(
                        clave, []
                    ).append(identificador)
    hallazgos: list[HallazgoCatalogoClientes] = []
    for tipo, claves in indices.items():
        for clave, identificadores in sorted(claves.items()):
            unicos = tuple(sorted(set(identificadores)))
            if len(unicos) > 1:
                hallazgos.append(
                    HallazgoCatalogoClientes(tipo, clave, unicos)
                )
    return tuple(hallazgos)


def _observacion_nombre(valor: object) -> ValorObservado:
    original = str(valor or "")
    normalizado = normalizar_nombre_cliente_multicampo(original)
    return ValorObservado(
        "cliente",
        original,
        normalizado,
        "OCR",
        Disponibilidad.DISPONIBLE if normalizado else Disponibilidad.AUSENTE,
        CalidadObservacion.NO_EVALUADA,
    )


def _observacion_rut(valor: object) -> tuple[ValorObservado, str]:
    original = str(valor or "")
    limpio = _rut_limpio(original)
    if not limpio:
        return (
            ValorObservado(
                "rut_cliente",
                original,
                "",
                "OCR",
                Disponibilidad.AUSENTE,
                CalidadObservacion.NO_EVALUADA,
            ),
            "AUSENTE",
        )
    canonico = _rut_canonico(original)
    if canonico:
        return (
            ValorObservado(
                "rut_cliente",
                original,
                canonico,
                "OCR",
                Disponibilidad.DISPONIBLE,
                CalidadObservacion.VALIDA,
                "RUT chileno válido; normalizado sin puntos ni guion.",
            ),
            "VALIDO",
        )
    return (
        ValorObservado(
            "rut_cliente",
            original,
            limpio,
            "OCR",
            Disponibilidad.DISPONIBLE,
            CalidadObservacion.INVALIDA,
            "RUT chileno inválido por formato o módulo 11.",
        ),
        "INVALIDO",
    )


def _similitud(izquierda: str, derecha: str) -> float:
    if not izquierda or not derecha:
        return 0.0
    return difflib.SequenceMatcher(None, izquierda, derecha).ratio()


def resolver_cliente_rut(
    cliente_ocr: object,
    rut_cliente_ocr: object,
    catalogo_clientes: (
        Mapping[str, Any]
        | Iterable[Mapping[str, Any]]
        | InstantaneaCatalogoClientes
    ),
    contexto: Mapping[str, Any] | None = None,
    *,
    catalogo_empresas: Mapping[str, Mapping[str, Any]] | None = None,
    campo_obligatorio: bool = True,
    politica_confianza: PoliticaConfianzaCliente = (
        POLITICA_CONFIANZA_CLIENTE_V1
    ),
) -> ResultadoResolucionCliente:
    """Resuelve solo cliente + RUT; destino/obra/contexto nunca deciden."""
    snapshot = (
        catalogo_clientes
        if isinstance(catalogo_clientes, InstantaneaCatalogoClientes)
        else crear_snapshot_catalogo_clientes(
            catalogo_clientes, catalogo_empresas
        )
    )
    nombre_obs = _observacion_nombre(cliente_ocr)
    rut_obs, clase_rut = _observacion_rut(rut_cliente_ocr)
    registros = [
        (identificador, registro, _entidad(identificador, registro))
        for identificador, registro in snapshot.registros.items()
        if str(registro.get("razon_social", "")).strip()
    ]
    evidencias: list[EvidenciaResolucion] = []
    alternativas: list[AlternativaResolucion] = []

    rut_matches = []
    if clase_rut == "VALIDO":
        rut_matches = [
            item
            for item in registros
            if _rut_canonico(item[1].get("rut")) == rut_obs.valor_normalizado
        ]
        for _, _, entidad in rut_matches:
            evidencias.append(EvidenciaResolucion(
                "RUT_EXACTO_VALIDO",
                "snapshot_clientes",
                rut_obs,
                entidad,
                1.0,
                "El RUT válido coincide exactamente con la identidad.",
                True,
            ))
    elif clase_rut == "INVALIDO":
        evidencias.append(EvidenciaResolucion(
            "RUT_INVALIDO",
            "validador_rut_chileno",
            rut_obs,
            None,
            0.0,
            rut_obs.detalle_calidad,
            False,
        ))

    nombre_matches = []
    if nombre_obs.valor_normalizado:
        for identificador, registro, entidad in registros:
            variantes = _variantes_nombre(registro)
            coincidencias = [
                variante
                for variante in variantes
                if normalizar_nombre_cliente_multicampo(variante)
                == nombre_obs.valor_normalizado
            ]
            if not coincidencias:
                continue
            tipo = (
                "NOMBRE_CANONICO_EXACTO"
                if normalizar_nombre_cliente_multicampo(
                    registro.get("razon_social")
                ) == nombre_obs.valor_normalizado
                else "ALIAS_EMPRESARIAL_EXACTO"
            )
            nombre_matches.append(
                (identificador, registro, entidad, tipo)
            )
            evidencias.append(EvidenciaResolucion(
                tipo,
                "snapshot_clientes",
                nombre_obs,
                entidad,
                1.0 if tipo == "NOMBRE_CANONICO_EXACTO" else 0.98,
                (
                    "Coincidencia exacta tras normalizar el sufijo societario."
                    if tipo == "NOMBRE_CANONICO_EXACTO"
                    else "Coincidencia exacta con nombre comercial o alias."
                ),
                True,
            ))

    ranking = []
    if (
        nombre_obs.valor_normalizado
        and not nombre_matches
        and len(nombre_obs.valor_normalizado) >= MINIMO_CARACTERES_FUZZY_CLIENTE
    ):
        for identificador, registro, entidad in registros:
            puntaje = max(
                (
                    _similitud(
                        nombre_obs.valor_normalizado,
                        normalizar_nombre_cliente_multicampo(variante),
                    )
                    for variante in _variantes_nombre(registro)
                ),
                default=0.0,
            )
            ranking.append((puntaje, identificador, registro, entidad))
        ranking.sort(key=lambda item: (-item[0], item[3].valor, item[1]))
        for puntaje, _, _, entidad in ranking[:3]:
            alternativas.append(AlternativaResolucion(
                entidad, puntaje, "Candidato por similitud global, no subcadena."
            ))

    nombre_fuerte = None
    nombre_ambiguo = len(nombre_matches) > 1
    if len(nombre_matches) == 1:
        nombre_fuerte = nombre_matches[0]
    elif not nombre_matches and ranking:
        mejor = ranking[0]
        segundo = ranking[1][0] if len(ranking) > 1 else 0.0
        margen = mejor[0] - segundo
        if (
            mejor[0] >= UMBRAL_FUZZY_CLIENTE
            and margen >= MARGEN_MINIMO_FUZZY_CLIENTE
        ):
            nombre_fuerte = (mejor[1], mejor[2], mejor[3], "NOMBRE_FUZZY")
            evidencias.append(EvidenciaResolucion(
                "NOMBRE_FUZZY",
                "comparacion_determinista",
                nombre_obs,
                mejor[3],
                mejor[0],
                f"Similitud global {mejor[0]:.3f}; margen {margen:.3f}.",
                True,
            ))
        elif mejor[0] >= UMBRAL_FUZZY_CLIENTE:
            nombre_ambiguo = True

    rut_entidad = rut_matches[0][2] if len(rut_matches) == 1 else None
    nombre_entidad = nombre_fuerte[2] if nombre_fuerte else None
    contradicciones: list[ContradiccionResolucion] = []
    if (
        rut_entidad
        and nombre_entidad
        and rut_entidad.identificador != nombre_entidad.identificador
    ):
        enfrentadas = tuple(
            evidencia
            for evidencia in evidencias
            if evidencia.candidato
            and evidencia.candidato.identificador in {
                rut_entidad.identificador,
                nombre_entidad.identificador,
            }
        )
        contradicciones.append(ContradiccionResolucion(
            ("cliente", "rut_cliente"),
            enfrentadas,
            (rut_entidad, nombre_entidad),
            "El nombre y el RUT apuntan a clientes distintos.",
            GravedadContradiccion.ALTA,
            "Impide reasignar el RUT o corregir silenciosamente el cliente.",
        ))
        evidencias = [
            EvidenciaResolucion(
                evidencia.tipo,
                evidencia.fuente,
                evidencia.observado,
                evidencia.candidato,
                evidencia.fuerza,
                evidencia.detalle,
                (
                    False
                    if evidencia.candidato
                    and evidencia.candidato.identificador
                    == nombre_entidad.identificador
                    else evidencia.apoya
                ),
            )
            for evidencia in evidencias
        ]

    candidato = rut_entidad or nombre_entidad
    via = ViaDecisionCliente.NO_RESUELTO
    razones = [
        "Los valores OCR originales se conservaron sin sobrescritura.",
        "Solo cliente y RUT participaron en la decisión.",
        "No hubo aprendizaje ni escritura de catálogos.",
    ]
    if len(rut_matches) > 1:
        estado = EstadoResolucion.REQUIERE_REVISION
        via = ViaDecisionCliente.DUPLICADO
        candidato = None
        razones.append("Más de una identidad comparte el RUT válido.")
    elif contradicciones:
        estado = EstadoResolucion.REQUIERE_REVISION
        via = ViaDecisionCliente.CONTRADICCION
        razones.append("Existe una contradicción fuerte entre nombre y RUT.")
    elif nombre_ambiguo:
        estado = EstadoResolucion.REQUIERE_REVISION
        via = ViaDecisionCliente.DUPLICADO
        candidato = None
        razones.append("El nombre tiene candidatos ambiguos.")
    elif candidato and candidato.activa is not True:
        estado = EstadoResolucion.REQUIERE_REVISION
        via = ViaDecisionCliente.INACTIVO
        razones.append("La identidad candidata está inactiva.")
    elif candidato and not _calidad_confirmada(
        next(
            registro
            for _, registro, entidad in registros
            if entidad.identificador == candidato.identificador
        )
    ):
        estado = EstadoResolucion.REQUIERE_REVISION
        via = ViaDecisionCliente.CALIDAD_NO_CONFIRMADA
        razones.append("La identidad no tiene calidad canónica confirmada.")
    elif clase_rut == "INVALIDO" and candidato:
        estado = EstadoResolucion.REQUIERE_REVISION
        via = ViaDecisionCliente.CONTRADICCION
        razones.append("El RUT observado es inválido por módulo 11 o formato.")
    elif rut_entidad:
        estado = EstadoResolucion.CONFIRMADO
        if nombre_entidad == rut_entidad:
            if nombre_fuerte and nombre_fuerte[3] == "NOMBRE_FUZZY":
                via = ViaDecisionCliente.FUZZY_MAS_RUT
            else:
                via = ViaDecisionCliente.RUT_EXACTO_MAS_NOMBRE_COMPATIBLE
        else:
            via = ViaDecisionCliente.RUT_EXACTO_UNICO
        razones.append("Un RUT chileno válido, único y confirmado fija la identidad.")
    elif nombre_fuerte and nombre_fuerte[3] in {
        "NOMBRE_CANONICO_EXACTO",
        "ALIAS_EMPRESARIAL_EXACTO",
    }:
        estado = EstadoResolucion.CONFIRMADO
        via = (
            ViaDecisionCliente.CANONICO_EXACTO_UNICO
            if nombre_fuerte[3] == "NOMBRE_CANONICO_EXACTO"
            else ViaDecisionCliente.ALIAS_HUMANO_UNICO
        )
        razones.append("Nombre empresarial exacto, único y confirmado.")
    elif nombre_fuerte and nombre_fuerte[3] == "NOMBRE_FUZZY":
        estado = EstadoResolucion.PROPUESTO
        via = ViaDecisionCliente.FUZZY_UNICO
        razones.append("El fuzzy aislado solo propone; nunca confirma por sí solo.")
    else:
        candidato = None
        estado = EstadoResolucion.NO_RESUELTO
        via = ViaDecisionCliente.NO_RESUELTO
        razones.append("No existe evidencia suficiente para resolver.")

    medicion_fuzzy = next(
        (
            evidencia.fuerza
            for evidencia in evidencias
            if evidencia.tipo == "NOMBRE_FUZZY"
        ),
        None,
    )
    confianza = politica_confianza.confianza(
        via,
        medicion_fuzzy=(
            medicion_fuzzy
            if via is ViaDecisionCliente.FUZZY_UNICO
            else None
        ),
    )
    if candidato and not any(
        alternativa.entidad.identificador == candidato.identificador
        for alternativa in alternativas
    ):
        alternativas.insert(
            0, AlternativaResolucion(candidato, None, "Candidato principal.")
        )
    registro_candidato = next(
        (
            registro
            for _, registro, entidad in registros
            if candidato
            and entidad.identificador == candidato.identificador
        ),
        None,
    )
    rut_canonico_candidato = (
        _rut_canonico(registro_candidato.get("rut"))
        if registro_candidato
        else None
    )
    return ResultadoResolucionCliente(
        tipo_entidad="cliente",
        observaciones=(nombre_obs, rut_obs),
        entidad=candidato,
        estado=estado,
        confianza=confianza,
        evidencias=tuple(evidencias),
        contradicciones=tuple(contradicciones),
        razones=tuple(razones),
        requiere_revision_humana=requiere_revision_por_estado(
            estado, campo_obligatorio=campo_obligatorio
        ),
        alternativas=tuple(alternativas[:3]),
        contexto=contexto,
        version_politica=politica_confianza.version,
        via_decision=via.value,
        version_catalogo=snapshot.version,
        rut_cliente_canonico=rut_canonico_candidato,
    )
