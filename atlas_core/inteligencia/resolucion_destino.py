"""Resolución conservadora de destino, territorio y planta de salida."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
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
from atlas_core.inteligencia.normalizacion_geografica import (
    comunas_equivalentes,
    regiones_equivalentes,
    separar_direccion,
)
from atlas_core.inteligencia.politica_confianza_destino import (
    POLITICA_CONFIANZA_DESTINO_V1,
    PoliticaConfianzaDestino,
    ViaDecisionDestino,
)
from atlas_core.inteligencia.snapshot_catalogo_destinos import (
    InstantaneaCatalogoDestinos,
    crear_snapshot_catalogo_destinos,
    normalizar_texto_destino,
)


UMBRAL_FUZZY_DESTINO = 0.88
MARGEN_FUZZY_DESTINO = 0.08
_GENERICAS = frozenset({
    "OBRA", "PLANTA", "BODEGA", "SUCURSAL", "DESTINO", "CLIENTE",
})


@dataclass(frozen=True)
class HallazgoCatalogoDestinos:
    codigo: str
    detalle: str
    identificadores: tuple[str, ...]


@dataclass(frozen=True)
class ResultadoResolucionDestino(ResultadoResolucion):
    destino_original: str = ""
    direccion_original: str = ""
    comuna_original: str = ""
    region_original: str = ""
    planta_original: str = ""
    id_destino_canonico: str | None = None
    destino_canonico: str | None = None
    direccion_canonica: str | None = None
    comuna_canonica: str | None = None
    region_canonica: str | None = None
    planta_salida_canonica: str | None = None

    @property
    def estado_resolucion(self) -> EstadoResolucion:
        return self.estado

    @property
    def requiere_revision(self) -> bool:
        return self.requiere_revision_humana


def _entidad_destino(
    identificador: str, registro: Mapping[str, Any]
) -> EntidadCanonica:
    return EntidadCanonica(
        identificador,
        str(registro["nombre_destino"]),
        "destino",
        str(registro["origen"]),
        str(registro["estado_vigencia"]) == "ACTIVO",
    )


def _observacion(campo: str, valor: object, fuente: str = "OCR") -> ValorObservado:
    original = "" if valor is None else str(valor)
    normalizado = normalizar_texto_destino(original)
    return ValorObservado(
        campo,
        original,
        normalizado,
        fuente,
        Disponibilidad.DISPONIBLE if normalizado else Disponibilidad.AUSENTE,
        CalidadObservacion.NO_EVALUADA,
        "Valor conservado; la normalización solo se usa para comparar.",
    )


def _variantes_nombre(registro: Mapping[str, Any]) -> tuple[str, ...]:
    return (
        str(registro["nombre_destino"]),
        *(str(a) for a in registro["aliases"]),
    )


def _similitud(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _nombre_generico(valor: str) -> bool:
    tokens = set(valor.split())
    return not valor or len(valor) < 5 or tokens <= _GENERICAS


def _direccion_tipo(observada: str, canonica: str) -> tuple[str, float]:
    if not observada or not canonica:
        return "AUSENTE", 0.0
    obs = separar_direccion(observada)
    can = separar_direccion(canonica)
    similitud_via = _similitud(obs.via, can.via)
    calle_exacta = bool(obs.via) and obs.via == can.via
    calle_fuzzy = similitud_via >= UMBRAL_FUZZY_DESTINO
    if (calle_exacta or calle_fuzzy) and obs.numero and can.numero:
        if obs.numero != can.numero:
            return "CONTRADICCION_NUMERO", similitud_via
        return (
            "DIRECCION_EXACTA" if calle_exacta else "DIRECCION_FUZZY",
            similitud_via,
        )
    if (calle_exacta or calle_fuzzy) and not obs.numero:
        return "DIRECCION_PARCIAL", similitud_via
    return "SIN_COINCIDENCIA", similitud_via


def _resolver_cliente_id(
    snapshot: InstantaneaCatalogoDestinos,
    id_cliente: object,
    cliente: object,
) -> str | None:
    id_texto = str(id_cliente or "").strip()
    if id_texto in snapshot.clientes:
        return id_texto
    nombre = normalizar_texto_destino(cliente)
    if not nombre:
        return None
    matches = [
        identificador
        for identificador, registro in snapshot.clientes.items()
        if nombre in {
            normalizar_texto_destino(registro["razon_social"]),
            normalizar_texto_destino(registro["nombre_comercial"]),
            *(normalizar_texto_destino(a) for a in registro["aliases"]),
        }
    ]
    return matches[0] if len(matches) == 1 else None


def auditar_catalogo_destinos(
    snapshot_o_destinos: InstantaneaCatalogoDestinos | Mapping[str, Any],
    catalogo_clientes: Mapping[str, Any] | None = None,
    catalogo_plantas: Mapping[str, Any] | None = None,
) -> tuple[HallazgoCatalogoDestinos, ...]:
    snapshot = (
        snapshot_o_destinos
        if isinstance(snapshot_o_destinos, InstantaneaCatalogoDestinos)
        else crear_snapshot_catalogo_destinos(
            snapshot_o_destinos,
            catalogo_clientes or {"clientes": []},
            catalogo_plantas or {"plantas": []},
        )
    )
    hallazgos: list[HallazgoCatalogoDestinos] = []
    identidades: dict[tuple[str, str, str], list[str]] = {}
    aliases: dict[str, list[str]] = {}
    for identificador, registro in snapshot.destinos.items():
        faltantes = [
            campo for campo in (
                "cliente_id", "nombre_destino", "direccion", "comuna", "region"
            ) if not str(registro[campo]).strip()
        ]
        if faltantes:
            hallazgos.append(HallazgoCatalogoDestinos(
                "DESTINO_INCOMPLETO",
                ",".join(faltantes),
                (identificador,),
            ))
        clave = (
            str(registro["cliente_id"]),
            normalizar_texto_destino(registro["nombre_destino"]),
            normalizar_texto_destino(registro["direccion"]),
        )
        identidades.setdefault(clave, []).append(identificador)
        for alias in registro["aliases"]:
            aliases.setdefault(
                normalizar_texto_destino(alias), []
            ).append(identificador)
    for clave, ids in identidades.items():
        if len(ids) > 1:
            hallazgos.append(HallazgoCatalogoDestinos(
                "DESTINO_DUPLICADO", "|".join(clave), tuple(sorted(ids))
            ))
    for alias, ids in aliases.items():
        if alias and len(set(ids)) > 1:
            hallazgos.append(HallazgoCatalogoDestinos(
                "ALIAS_AMBIGUO", alias, tuple(sorted(set(ids)))
            ))
    return tuple(sorted(
        hallazgos,
        key=lambda h: (h.codigo, h.detalle, h.identificadores),
    ))


def _resolver_planta(
    snapshot: InstantaneaCatalogoDestinos,
    observada: ValorObservado,
    documental: ValorObservado,
) -> tuple[str | None, list[ContradiccionResolucion], list[EvidenciaResolucion]]:
    evidencias: list[EvidenciaResolucion] = []
    contradicciones: list[ContradiccionResolucion] = []

    def matches(obs: ValorObservado) -> list[tuple[str, Mapping[str, Any]]]:
        if obs.disponibilidad is Disponibilidad.AUSENTE:
            return []
        return [
            (identificador, registro)
            for identificador, registro in snapshot.plantas.items()
            if obs.valor_normalizado in {
                normalizar_texto_destino(registro["nombre"]),
                normalizar_texto_destino(registro["direccion"]),
            }
        ]

    por_campo = {
        observada.campo: matches(observada),
        documental.campo: matches(documental),
    }
    nombres: dict[str, str] = {}
    for obs in (observada, documental):
        candidatos = por_campo[obs.campo]
        if len(candidatos) == 1:
            identificador, registro = candidatos[0]
            nombres[obs.campo] = str(registro["nombre"])
            entidad = EntidadCanonica(
                identificador,
                str(registro["nombre"]),
                "planta",
                str(registro["origen"]),
                str(registro["estado_vigencia"]) == "ACTIVA",
            )
            evidencias.append(EvidenciaResolucion(
                "PLANTA_EXACTA", "snapshot_plantas", obs, entidad, 1.0,
                "Planta explícita, única y canónica.", True,
            ))
        elif obs.disponibilidad is Disponibilidad.DISPONIBLE:
            evidencias.append(EvidenciaResolucion(
                "PLANTA_NO_RESUELTA", "snapshot_plantas", obs, None, 0.0,
                "La planta observada no identifica Colina o Renca.", False,
            ))
    if len(set(nombres.values())) > 1:
        enfrentadas = tuple(
            e for e in evidencias if e.tipo == "PLANTA_EXACTA"
        )
        contradicciones.append(ContradiccionResolucion(
            ("planta_salida", "planta_documental"),
            enfrentadas,
            tuple(e.candidato for e in enfrentadas if e.candidato),
            "OCR y evidencia documental apuntan a plantas distintas.",
            GravedadContradiccion.ALTA,
            "Exige revisión; nunca se elige Colina por defecto.",
        ))
        return None, contradicciones, evidencias
    return next(iter(nombres.values()), None), contradicciones, evidencias


def resolver_destino_ubicacion(
    obra_destino: object = "",
    direccion: object = "",
    comuna: object = "",
    region: object = "",
    planta_salida: object = "",
    catalogo_destinos: Mapping[str, Any] | InstantaneaCatalogoDestinos = (
        MappingProxyType({})
    ),
    catalogo_clientes: Mapping[str, Any] | None = None,
    catalogo_plantas: Mapping[str, Any] | None = None,
    *,
    id_cliente_canonico: object = "",
    cliente_canonico: object = "",
    codigo_destinatario: object = "",
    planta_documental: object = "",
    calidades: Mapping[str, float] | None = None,
    contexto: Mapping[str, Any] | None = None,
    campo_obligatorio: bool = True,
    politica_confianza: PoliticaConfianzaDestino = (
        POLITICA_CONFIANZA_DESTINO_V1
    ),
) -> ResultadoResolucionDestino:
    snapshot = (
        catalogo_destinos
        if isinstance(catalogo_destinos, InstantaneaCatalogoDestinos)
        else crear_snapshot_catalogo_destinos(
            catalogo_destinos,
            catalogo_clientes or {"clientes": []},
            catalogo_plantas or {"plantas": []},
        )
    )
    calidad_campos = {
        str(campo): float(valor)
        for campo, valor in (calidades or {}).items()
    }
    if any(not 0.0 <= valor <= 1.0 for valor in calidad_campos.values()):
        raise ValueError("la calidad de evidencia debe estar entre 0 y 1")

    def calidad(campo: str) -> float:
        return calidad_campos.get(campo, 1.0)

    obs_nombre = _observacion("obra_destino", obra_destino)
    obs_direccion = _observacion("direccion", direccion)
    obs_comuna = _observacion("comuna", comuna)
    obs_region = _observacion("region", region)
    obs_planta = _observacion("planta_salida", planta_salida)
    obs_planta_doc = _observacion(
        "planta_documental", planta_documental, "EVIDENCIA_DOCUMENTAL"
    )
    obs_codigo = _observacion(
        "codigo_destinatario", codigo_destinatario, "EVIDENCIA_DOCUMENTAL"
    )
    observaciones = (
        obs_nombre, obs_direccion, obs_comuna, obs_region,
        obs_planta, obs_planta_doc, obs_codigo,
    )
    codigo_buscado = str(codigo_destinatario or "").strip().upper()
    cliente_id = _resolver_cliente_id(
        snapshot, id_cliente_canonico, cliente_canonico
    )

    def clientes_destino(registro: Mapping[str, Any]) -> frozenset[str]:
        ids = registro.get("cliente_ids", ())
        if isinstance(ids, str):
            ids = (ids,)
        return frozenset(str(item).strip() for item in ids if str(item).strip())
    nombre_generico = _nombre_generico(obs_nombre.valor_normalizado)
    datos: dict[str, dict[str, Any]] = {}
    nombre_fuertes: set[str] = set()
    direccion_fuertes: set[str] = set()
    codigo_fuertes: set[str] = set()
    for identificador, registro in snapshot.destinos.items():
        variantes = _variantes_nombre(registro)
        variantes_norm = [normalizar_texto_destino(v) for v in variantes]
        exacto_canonico = (
            not nombre_generico
            and obs_nombre.valor_normalizado
            == normalizar_texto_destino(registro["nombre_destino"])
        )
        alias_exacto = (
            not nombre_generico
            and obs_nombre.valor_normalizado
            and obs_nombre.valor_normalizado in variantes_norm[1:]
        )
        fuzzy = max(
            (_similitud(obs_nombre.valor_normalizado, v) for v in variantes_norm),
            default=0.0,
        ) if not nombre_generico else 0.0
        tipo_direccion, similitud_direccion = _direccion_tipo(
            obs_direccion.valor_original, str(registro["direccion"])
        )
        # Coincidencia exacta y única de Código Destinatario contra el
        # código maestro del propio registro: evidencia determinista, sin
        # comparación difusa de texto. Se exige además calidad confirmada
        # más abajo, igual que cualquier otra vía. A diferencia del nombre
        # y la dirección, esta evidencia puede generar un candidato por sí
        # sola, incluso si el nombre OCR está demasiado degradado para
        # coincidir con nada.
        codigo_exacto = bool(
            codigo_buscado
            and str(registro.get("codigo_destino", "")).strip().upper()
            == codigo_buscado
        )
        if exacto_canonico or alias_exacto:
            nombre_fuertes.add(identificador)
        if tipo_direccion == "DIRECCION_EXACTA":
            direccion_fuertes.add(identificador)
        if codigo_exacto:
            codigo_fuertes.add(identificador)
        evidencia_score = (
            (55 if alias_exacto else 50 if exacto_canonico else 20 * fuzzy
             if fuzzy >= UMBRAL_FUZZY_DESTINO else 0)
            + (60 if tipo_direccion == "DIRECCION_EXACTA"
               else 35 if tipo_direccion == "DIRECCION_FUZZY"
               else 20 if tipo_direccion == "DIRECCION_PARCIAL" else 0)
        )
        score = evidencia_score + (
            20 if evidencia_score and cliente_id
            and cliente_id in clientes_destino(registro) else 0
        ) + (200 if codigo_exacto else 0)
        if score:
            datos[identificador] = {
                "registro": registro,
                "exacto": exacto_canonico,
                "alias": alias_exacto,
                "fuzzy": fuzzy,
                "direccion_tipo": tipo_direccion,
                "direccion_similitud": similitud_direccion,
                "codigo_exacto": codigo_exacto,
                "score": score,
            }

    evidencias: list[EvidenciaResolucion] = []
    contradicciones: list[ContradiccionResolucion] = []
    alternativas: list[AlternativaResolucion] = []
    if codigo_fuertes and (nombre_fuertes | direccion_fuertes) - codigo_fuertes:
        contradicciones.append(ContradiccionResolucion(
            ("obra_destino", "codigo_destinatario"),
            (),
            tuple(
                _entidad_destino(i, snapshot.destinos[i])
                for i in sorted(codigo_fuertes | nombre_fuertes | direccion_fuertes)
            ),
            "El código destinatario y el nombre o dirección observados "
            "apuntan a destinos distintos.",
            GravedadContradiccion.ALTA,
            "Exige revisión; el código nunca reemplaza silenciosamente al nombre.",
        ))
    if nombre_fuertes and direccion_fuertes and nombre_fuertes.isdisjoint(
        direccion_fuertes
    ):
        contradicciones.append(ContradiccionResolucion(
            ("obra_destino", "direccion"),
            (),
            tuple(
                _entidad_destino(i, snapshot.destinos[i])
                for i in sorted(nombre_fuertes | direccion_fuertes)
            ),
            "Nombre y dirección apuntan a destinos distintos.",
            GravedadContradiccion.ALTA,
            "Exige revisión y conserva ambos valores OCR.",
        ))

    if cliente_id:
        candidatos_con_evidencia = dict(datos)
        compatibles = {
            i: d for i, d in datos.items()
            if cliente_id in clientes_destino(d["registro"])
        }
        if candidatos_con_evidencia and not compatibles:
            sin_relacion = all(
                not clientes_destino(d["registro"])
                for d in candidatos_con_evidencia.values()
            )
            contradicciones.append(ContradiccionResolucion(
                ("cliente", "obra_destino"),
                (),
                tuple(
                    _entidad_destino(i, d["registro"])
                    for i, d in sorted(candidatos_con_evidencia.items())
                ),
                (
                    "El catálogo no declara relación entre el cliente y el destino."
                    if sin_relacion else
                    "El destino observado pertenece explícitamente a otro cliente canónico."
                ),
                GravedadContradiccion.ALTA,
                "El filtro cliente-destino es obligatorio y nunca falla abierto.",
            ))
        datos = compatibles
    ranking = sorted(
        datos.items(),
        key=lambda item: (-item[1]["score"], item[0]),
    )
    for identificador, dato in ranking:
        entidad = _entidad_destino(identificador, dato["registro"])
        alternativas.append(AlternativaResolucion(
            entidad,
            min(1.0, dato["score"] / 100.0),
            "Candidato por nombre, dirección y compatibilidad de cliente.",
        ))
    seleccionado: tuple[str, dict[str, Any]] | None = None
    ambiguo = False
    if ranking:
        mejor = ranking[0]
        segundo = ranking[1][1]["score"] if len(ranking) > 1 else -1
        if mejor[1]["score"] == segundo:
            ambiguo = True
        else:
            seleccionado = mejor

    entidad: EntidadCanonica | None = None
    registro: Mapping[str, Any] | None = None
    dato: dict[str, Any] | None = None
    if seleccionado:
        identificador, dato = seleccionado
        registro = dato["registro"]
        entidad = _entidad_destino(identificador, registro)
        if dato["exacto"]:
            evidencias.append(EvidenciaResolucion(
                "DESTINO_CANONICO_EXACTO", "snapshot_destinos", obs_nombre,
                entidad, calidad("obra_destino"), "Nombre canónico exacto.", True,
            ))
        if dato["alias"]:
            evidencias.append(EvidenciaResolucion(
                "ALIAS_DESTINO_EXACTO", "snapshot_destinos", obs_nombre,
                entidad, 0.98 * calidad("obra_destino"),
                "Alias explícito y único.", True,
            ))
        if dato["codigo_exacto"]:
            evidencias.append(EvidenciaResolucion(
                "CODIGO_DESTINATARIO_EXACTO", "snapshot_destinos", obs_codigo,
                entidad, calidad("codigo_destinatario"),
                "Código destinatario exacto y único contra el catálogo maestro.",
                True,
            ))
        if dato["fuzzy"] >= UMBRAL_FUZZY_DESTINO and not (
            dato["exacto"] or dato["alias"]
        ):
            evidencias.append(EvidenciaResolucion(
                "NOMBRE_DESTINO_FUZZY", "snapshot_destinos", obs_nombre,
                entidad, dato["fuzzy"] * calidad("obra_destino"),
                "Fuzzy aislado nunca confirma.", True,
            ))
        if dato["direccion_tipo"] != "SIN_COINCIDENCIA":
            apoya = dato["direccion_tipo"] != "CONTRADICCION_NUMERO"
            evidencias.append(EvidenciaResolucion(
                dato["direccion_tipo"], "snapshot_destinos", obs_direccion,
                entidad, dato["direccion_similitud"] * calidad("direccion"),
                "Comparación estructurada de calle y número.", apoya,
            ))
            if not apoya:
                contradicciones.append(ContradiccionResolucion(
                    ("direccion", "direccion_canonica"),
                    (evidencias[-1],),
                    (entidad,),
                    "La calle coincide, pero el número es distinto.",
                    GravedadContradiccion.ALTA,
                    "Exige revisión; los números nunca se aproximan.",
                ))
        elif obs_direccion.disponibilidad is Disponibilidad.DISPONIBLE:
            contradicciones.append(ContradiccionResolucion(
                ("direccion", "direccion_canonica"), (), (entidad,),
                "La dirección OCR no es compatible con el destino candidato.",
                GravedadContradiccion.ALTA,
                "Exige revisión antes de confirmar el destino.",
            ))
        if (
            obs_comuna.disponibilidad is Disponibilidad.DISPONIBLE
            and not comunas_equivalentes(obs_comuna.valor_original, registro["comuna"])
        ):
            contradicciones.append(ContradiccionResolucion(
                ("comuna", "comuna_canonica"), (), (entidad,),
                "La comuna OCR no corresponde al destino.",
                GravedadContradiccion.ALTA, "Exige revisión.",
            ))
        if (
            obs_region.disponibilidad is Disponibilidad.DISPONIBLE
            and not regiones_equivalentes(obs_region.valor_original, registro["region"])
        ):
            contradicciones.append(ContradiccionResolucion(
                ("region", "region_canonica"), (), (entidad,),
                "La región OCR no corresponde al destino.",
                GravedadContradiccion.ALTA, "Exige revisión.",
            ))

    planta_canonica, contra_planta, evidencia_planta = _resolver_planta(
        snapshot, obs_planta, obs_planta_doc
    )
    contradicciones.extend(contra_planta)
    evidencias.extend(evidencia_planta)
    planta_explicita_no_resuelta = any(
        e.tipo == "PLANTA_NO_RESUELTA" for e in evidencia_planta
    )
    if planta_explicita_no_resuelta:
        contradicciones.append(ContradiccionResolucion(
            ("planta_salida",), tuple(
                e for e in evidencia_planta if e.tipo == "PLANTA_NO_RESUELTA"
            ), (), "La planta explícita no es AZA Colina ni AZA Renca.",
            GravedadContradiccion.MEDIA,
            "La planta queda no resuelta; nunca se usa un origen por defecto.",
        ))
    planta_calidad_baja = bool(
        planta_canonica
        and min(calidad("planta_salida"), calidad("planta_documental")) < 0.8
        and (
            obs_planta.disponibilidad is Disponibilidad.DISPONIBLE
            or obs_planta_doc.disponibilidad is Disponibilidad.DISPONIBLE
        )
    )

    via = ViaDecisionDestino.NO_RESUELTO
    estado = EstadoResolucion.NO_RESUELTO
    candidato = entidad
    medicion = dato["fuzzy"] if dato else 0.0
    razones = [
        "Todos los valores OCR originales se conservaron.",
        "No se usaron rutas, distancias, red ni geocodificación.",
        "Cliente y destino permanecen como entidades diferentes.",
    ]
    if contradicciones:
        estado = EstadoResolucion.REQUIERE_REVISION
        via = ViaDecisionDestino.CONTRADICCION
    elif ambiguo:
        candidato = None
        estado = EstadoResolucion.REQUIERE_REVISION
        via = ViaDecisionDestino.DUPLICADO
    elif entidad and entidad.activa is False:
        estado = EstadoResolucion.REQUIERE_REVISION
        via = ViaDecisionDestino.INACTIVO
    elif planta_calidad_baja or (
        entidad and dato and (
            (
                obs_nombre.disponibilidad is Disponibilidad.DISPONIBLE
                and calidad("obra_destino") < 0.8
            )
            or (
                obs_direccion.disponibilidad is Disponibilidad.DISPONIBLE
                and calidad("direccion") < 0.8
            )
        )
    ):
        estado = EstadoResolucion.REQUIERE_REVISION
        via = ViaDecisionDestino.CALIDAD_INCOMPLETA
    elif registro and (
        registro["estado_calidad"] not in {"CONFIRMADO", "CONFIRMADO_DOCUMENTAL"}
        or any(not str(registro[c]).strip() for c in (
            "cliente_id", "nombre_destino", "direccion", "comuna", "region"
        ))
    ):
        estado = EstadoResolucion.REQUIERE_REVISION
        via = ViaDecisionDestino.CALIDAD_INCOMPLETA
    elif dato and dato["codigo_exacto"]:
        estado = EstadoResolucion.CONFIRMADO
        via = ViaDecisionDestino.CODIGO_DESTINATARIO_EXACTO
    elif dato and dato["direccion_tipo"] == "DIRECCION_EXACTA" and (
        dato["exacto"] or dato["alias"]
    ):
        estado = EstadoResolucion.CONFIRMADO
        via = ViaDecisionDestino.NOMBRE_MAS_DIRECCION
    elif dato and dato["direccion_tipo"] == "DIRECCION_EXACTA" and dato[
        "fuzzy"
    ] >= UMBRAL_FUZZY_DESTINO:
        estado = EstadoResolucion.CONFIRMADO
        via = ViaDecisionDestino.FUZZY_MAS_DIRECCION
    elif dato and dato["direccion_tipo"] == "DIRECCION_EXACTA":
        estado = EstadoResolucion.CONFIRMADO
        via = ViaDecisionDestino.DIRECCION_EXACTA_UNICA
    elif dato and dato["direccion_tipo"] == "DIRECCION_FUZZY" and dato["fuzzy"] >= (
        UMBRAL_FUZZY_DESTINO
    ):
        estado = EstadoResolucion.CONFIRMADO
        via = ViaDecisionDestino.FUZZY_MAS_DIRECCION
    elif dato and dato["exacto"]:
        estado = EstadoResolucion.CONFIRMADO
        via = ViaDecisionDestino.DESTINO_EXACTO_UNICO
    elif dato and dato["alias"]:
        estado = EstadoResolucion.CONFIRMADO
        via = ViaDecisionDestino.ALIAS_EXACTO_UNICO
    elif entidad:
        estado = EstadoResolucion.PROPUESTO
        via = ViaDecisionDestino.FUZZY_O_PARCIAL
    else:
        candidato = None

    if estado is EstadoResolucion.CONFIRMADO:
        relacion_valida = bool(
            not cliente_id
            or (registro and cliente_id in clientes_destino(registro))
        )
        direccion_valida = bool(
            dato and (
                obs_direccion.disponibilidad is Disponibilidad.AUSENTE
                or dato["direccion_tipo"] not in {
                    "SIN_COINCIDENCIA", "CONTRADICCION_NUMERO"
                }
            )
        )
        if not (
            entidad and entidad.activa and seleccionado and not ambiguo
            and registro and relacion_valida and direccion_valida
            and not contradicciones
        ):
            raise AssertionError(
                "invariante destino: CONFIRMADO exige candidato único, activo, "
                "dirección y cliente compatibles y cero contradicciones"
            )

    explicaciones = {
        ViaDecisionDestino.DESTINO_EXACTO_UNICO:
            "Nombre exacto, único y de calidad confirmada.",
        ViaDecisionDestino.ALIAS_EXACTO_UNICO:
            "Alias exacto, único y trazable.",
        ViaDecisionDestino.CODIGO_DESTINATARIO_EXACTO:
            "Código destinatario exacto, único y confirmado fijó el destino.",
        ViaDecisionDestino.DIRECCION_EXACTA_UNICA:
            "Dirección completa y única confirmó el destino.",
        ViaDecisionDestino.NOMBRE_MAS_DIRECCION:
            "Nombre y dirección convergen en la misma identidad.",
        ViaDecisionDestino.FUZZY_MAS_DIRECCION:
            "Nombre degradado y dirección compatible convergen.",
        ViaDecisionDestino.FUZZY_O_PARCIAL:
            "La evidencia fuzzy o parcial solo propone.",
        ViaDecisionDestino.CONTRADICCION:
            "Existe evidencia incompatible que exige revisión.",
        ViaDecisionDestino.DUPLICADO:
            "Más de un destino conserva la misma fuerza.",
        ViaDecisionDestino.INACTIVO:
            "El destino está inactivo.",
        ViaDecisionDestino.CALIDAD_INCOMPLETA:
            "El destino está pendiente o incompleto.",
        ViaDecisionDestino.NO_RESUELTO:
            "No existe evidencia suficiente para resolver destino.",
    }
    razones.append(explicaciones[via])
    return ResultadoResolucionDestino(
        "destino",
        observaciones,
        candidato,
        estado,
        politica_confianza.confianza(via, medicion=medicion),
        tuple(evidencias),
        tuple(contradicciones),
        tuple(razones),
        requiere_revision_por_estado(
            estado, campo_obligatorio=campo_obligatorio
        ),
        tuple(alternativas),
        dict(contexto or {}),
        politica_confianza.version,
        via.value,
        snapshot.version,
        obs_nombre.valor_original,
        obs_direccion.valor_original,
        obs_comuna.valor_original,
        obs_region.valor_original,
        obs_planta.valor_original,
        candidato.identificador if candidato else None,
        str(registro["nombre_destino"]) if candidato and registro else None,
        str(registro["direccion"]) if candidato and registro else None,
        str(registro["comuna"]) if candidato and registro else None,
        str(registro["region"]) if candidato and registro else None,
        planta_canonica,
    )
