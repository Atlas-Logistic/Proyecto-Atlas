"""Bloque P0 -- CONVERGENCIA DE IDENTIDADES CONOCIDAS.

Casos reales: 473546 (CHOFER_CANDIDATO sobre "SALOMÓN PIZARRO", único
chofer activo de ese nombre en catálogo) y 473442 (CLIENTE_DESCONOCIDO
sobre "TORRES OCARANZA LTDA", cliente ya confirmado/activo en catálogo).
Atlas no debe mantener una decisión humana cuando la identidad vigente
ya puede resolverse de forma única y fuerte contra una entidad conocida.

Regla transversal de CHOFER: nombre normalizado EXACTO + candidato
ÚNICO + registro ACTIVO => resuelve, sin que un RUT documental
ausente/incompleto/inválido/contradictorio lo impida -- nunca corrige
ni sobrescribe el RUT canónico, nunca aprende nada del catálogo, el RUT
documental se conserva como evidencia aparte. Deliberadamente MÁS
permisiva que `catalogos.corroborar_chofer_por_nombre_y_rut_documental`
(que sigue intacta, sin tocar, para el resto del pipeline): esa función
sirve a la corroboración AUTOMÁTICA durante ingesta, donde una
contradicción de RUT debe seguir bloqueando en silencio; ésta sirve
específicamente para decidir si una tarjeta YA PENDIENTE sigue
teniendo una pregunta real que hacer, y el nombre único+activo ya
responde esa pregunta sin ambigüedad -- el RUT nunca se usa para nada
más que evidencia conservada.

Regla transversal de CLIENTE: RUT documental exacto contra un cliente
conocido, O nombre normalizado exacto + candidato único, homologa al
cliente existente -- nunca fusiona por nombre difuso, nunca crea una
entidad/alias nueva. A diferencia de CHOFER, un RUT documental válido
mas CONTRADICTORIO (distinto del único candidato nominal) SÍ fuerza
abstención -- asimetría deliberada del contrato: la identidad de
cliente exige más certeza que la de chofer."""
from __future__ import annotations

import difflib
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Mapping

from atlas_core.catalogo_clientes import Cliente, normalizar_nombre_cliente, normalizar_rut_cliente
from atlas_core.catalogos import buscar_chofer_por_nombre_exacto, normalizar_rut
from atlas_core.validadores import EstadoValidacion, validar_rut_chileno

_AUSENTES = {"", "No encontrado", "REVISAR", "Ilegible"}

RESULTADO_RESUELTO = "RESUELTO"
RESULTADO_ABSTENCION = "ABSTENCION"
RESULTADO_SIN_EVIDENCIA = "SIN_EVIDENCIA"
# Chofer identificado, pero configurado explícitamente como asignación
# variable en `choferes.json` -- la regla de asignación canónica nunca
# aplica aquí; el llamador debe seguir usando los mecanismos existentes
# (evidencia documental/histórica), nunca imponer una patente fija.
RESULTADO_NO_APLICA_VARIABLE = "NO_APLICA_VARIABLE"


@dataclass(frozen=True)
class IdentidadChoferResuelta:
    resultado: str
    identificador: str | None
    nombre_canonico: str | None
    rut_documental_conservado: str | None
    explicacion: str
    candidatos: tuple[str, ...] = ()


def _normalizar_referencia_humana(texto: str) -> tuple[str, ...]:
    """Normaliza tildes y separa tokens, sin hacer fuzzy global."""
    descompuesto = unicodedata.normalize("NFKD", str(texto or "").upper())
    plano = "".join(c for c in descompuesto if not unicodedata.combining(c))
    return tuple(token for token in "".join(c if c.isalnum() else " " for c in plano).split() if token)


def _token_coincide_fuerte(referencia: str, candidato: str) -> bool:
    if referencia == candidato:
        return True
    # Error OCR/ortográfico leve: nunca para tokens cortos ni más de un
    # carácter de diferencia. No puntúa ni elige candidatos.
    if min(len(referencia), len(candidato)) < 5 or abs(len(referencia) - len(candidato)) > 1:
        return False
    return difflib.SequenceMatcher(None, referencia, candidato).ratio() >= 0.8


def _candidatos_contextuales_chofer(
    choferes: Mapping[str, object], referencia: str,
) -> list[tuple[str, dict[str, object]]]:
    """Todo token debe explicar el nombre/alias de un chofer activo."""
    tokens = _normalizar_referencia_humana(referencia)
    if not tokens:
        return []
    encontrados: list[tuple[str, dict[str, object]]] = []
    for identificador, registro in choferes.items():
        if not isinstance(registro, dict) or registro.get("activo", True) is not True:
            continue
        aliases = registro.get("aliases")
        nombres = [registro.get("nombre", ""), *(aliases if isinstance(aliases, list) else [])]
        if any(
            (tokens_nombre := _normalizar_referencia_humana(str(nombre)))
            and all(any(_token_coincide_fuerte(token, posible) for posible in tokens_nombre) for token in tokens)
            for nombre in nombres
        ):
            encontrados.append((str(identificador), registro))
    return encontrados


def resolver_identidad_nominal_fuerte_chofer(
    *, nombre_documental: str, rut_documental: str, choferes: Mapping[str, object],
) -> IdentidadChoferResuelta:
    """`choferes` es el catálogo crudo (mismo formato que
    `cargar_catalogo_json`). Nunca corrige/sobrescribe el RUT canónico
    del registro -- sólo conserva el documental como evidencia aparte."""
    if nombre_documental in _AUSENTES:
        return IdentidadChoferResuelta(RESULTADO_SIN_EVIDENCIA, None, None, None, "Sin nombre documental de chofer.")

    coincidencia = buscar_chofer_por_nombre_exacto(choferes, nombre_documental)
    if coincidencia is None:
        contextuales = _candidatos_contextuales_chofer(choferes, nombre_documental)
        if len(contextuales) == 1:
            identificador, registro = contextuales[0]
            nombre_canonico = str(registro.get("nombre", nombre_documental)).strip() or nombre_documental
            rut_doc = str(rut_documental or "").strip()
            return IdentidadChoferResuelta(
                resultado=RESULTADO_RESUELTO, identificador=identificador,
                nombre_canonico=nombre_canonico,
                rut_documental_conservado=rut_doc if rut_doc not in _AUSENTES else None,
                explicacion=(
                    f"Referencia contextual identifica de forma única al chofer activo ({nombre_canonico}); "
                    "todos los tokens disponibles coinciden, sin usar historial como autoridad."
                ),
            )
        if len(contextuales) > 1:
            nombres = tuple(sorted(
                str(registro.get("nombre", identificador)).strip() or identificador
                for identificador, registro in contextuales
            ))
            return IdentidadChoferResuelta(
                RESULTADO_ABSTENCION, None, None, None,
                "Referencia humana coincide con varios choferes activos; requiere elección.", nombres,
            )
        # 0 candidatos activos (desconocido) o 2+ (ambigüedad) -- en
        # ambos casos las reglas existentes (fuzzy/CHOFER_CANDIDATO/
        # CHOFER_DESCONOCIDO) siguen aplicando sin cambios.
        return IdentidadChoferResuelta(
            RESULTADO_ABSTENCION, None, None, None,
            "Sin candidato único activo por nombre exacto -- ambigüedad o desconocido.",
        )
    identificador, registro = coincidencia
    nombre_canonico = str(registro.get("nombre", nombre_documental)).strip() or nombre_documental
    rut_doc = str(rut_documental or "").strip()
    return IdentidadChoferResuelta(
        resultado=RESULTADO_RESUELTO, identificador=str(identificador), nombre_canonico=nombre_canonico,
        rut_documental_conservado=rut_doc if rut_doc not in _AUSENTES else None,
        explicacion=(
            f"Nombre documental coincide EXACTO con el único chofer activo ({nombre_canonico}) -- "
            "RUT documental conservado como evidencia, nunca usado para corregir el canónico."
        ),
    )


@dataclass(frozen=True)
class IdentidadClienteResuelta:
    resultado: str
    cliente_id: str | None
    razon_social: str | None
    via: str
    explicacion: str


def _nombre_exacto_cliente(nombre_documental: str, cliente: Cliente) -> bool:
    """Igualdad EXACTA tras normalizar -- nunca substring/fuzzy (eso ya
    lo cubren otros mecanismos existentes; este bloque exige certeza)."""
    clave_doc = normalizar_nombre_cliente(nombre_documental)
    if not clave_doc:
        return False
    claves_cliente = {
        normalizar_nombre_cliente(valor)
        for valor in (cliente.razon_social, cliente.nombre_comercial, *cliente.aliases)
        if valor
    }
    return clave_doc in claves_cliente


def resolver_identidad_nominal_fuerte_cliente(
    *, nombre_documental: str, rut_documental: str, clientes: Iterable[Cliente],
) -> IdentidadClienteResuelta:
    """`clientes` debe venir ya filtrado a CONFIRMADO/ACTIVO por el
    llamador (mismo criterio que el resto del pipeline de decisiones) --
    esta función además re-filtra por seguridad, nunca confía en que el
    llamador lo haya hecho correctamente."""
    clientes_vigentes = [
        c for c in clientes if c.estado_calidad == "CONFIRMADO" and c.estado_vigencia == "ACTIVO"
    ]

    rut_normalizado = ""
    if rut_documental not in _AUSENTES:
        validado = validar_rut_chileno(rut_documental)
        if validado.estado == EstadoValidacion.VALIDO:
            rut_normalizado = normalizar_rut_cliente(str(validado.valor))

    if rut_normalizado:
        cliente_por_rut = next((c for c in clientes_vigentes if c.rut and c.rut == rut_normalizado), None)
        if cliente_por_rut is not None:
            return IdentidadClienteResuelta(
                resultado=RESULTADO_RESUELTO, cliente_id=cliente_por_rut.cliente_id,
                razon_social=cliente_por_rut.razon_social, via="RUT",
                explicacion="RUT documental coincide EXACTO con un cliente catalogado -- máxima certeza.",
            )

    candidatos_nombre = [c for c in clientes_vigentes if nombre_documental not in _AUSENTES and _nombre_exacto_cliente(nombre_documental, c)]
    if len(candidatos_nombre) > 1:
        return IdentidadClienteResuelta(
            RESULTADO_ABSTENCION, None, None, "",
            "Múltiples clientes catalogados coinciden por nombre exacto -- ambigüedad, no se resuelve.",
        )
    if len(candidatos_nombre) == 1:
        candidato = candidatos_nombre[0]
        if rut_normalizado and candidato.rut and rut_normalizado != candidato.rut:
            return IdentidadClienteResuelta(
                resultado=RESULTADO_ABSTENCION, cliente_id=None, razon_social=None, via="",
                explicacion=(
                    f"RUT documental contradice al único cliente ({candidato.razon_social}) que coincide "
                    "por nombre exacto -- abstención, nunca se fuerza la identidad."
                ),
            )
        return IdentidadClienteResuelta(
            resultado=RESULTADO_RESUELTO, cliente_id=candidato.cliente_id, razon_social=candidato.razon_social,
            via="NOMBRE",
            explicacion=f"Nombre documental coincide EXACTO con único cliente confirmado/activo ({candidato.razon_social}).",
        )
    return IdentidadClienteResuelta(RESULTADO_SIN_EVIDENCIA, None, None, "", "Sin coincidencia exacta de RUT ni de nombre.")


# ============================================================
# Bloque P0 FINAL -- ASIGNACIÓN OPERACIONAL CHOFER -> VEHÍCULO
# ============================================================
#
# Regla operacional definida por Javier: la asignación chofer->vehículo
# YA CONFIRMADA en catálogo (`confirmar_vehiculo(..., rut_chofer_
# asociado=...)`, el mismo mecanismo ya existente que usa
# `_vehiculos_confirmados_para_rut`) es conocimiento operacional
# canónico, NUNCA una inferencia probabilística por historial. Si (1) el
# chofer se identifica de forma inequívoca (reutiliza
# `resolver_identidad_nominal_fuerte_chofer`, arriba -- nunca una
# segunda resolución de identidad), (2) el catálogo tiene EXACTAMENTE
# una patente CONFIRMADA/ACTIVA con `rut_chofer_asociado` igual al RUT
# canónico de ese chofer, y (3) ese chofer no está marcado como
# asignación variable -- esa patente es la determinada del viaje. Una
# lectura OCR distinta NUNCA la sobrescribe ni se pierde: sólo deja de
# generar/mantener la pregunta `VEHICULO_DESCONOCIDO`; el valor
# documental sigue intacto en el dataset como evidencia.
#
# Historial NUNCA es la fuente de esta regla (deliberado, a pedido
# explícito): esta función NUNCA lee `filas`/transportes/frecuencia de
# uso -- sólo lee `choferes.json` (identidad + variabilidad) y
# `vehiculos.json` (asignación ya confirmada). Si el catálogo todavía
# no tiene esa asignación explícita, se reporta el hueco -- nunca se
# infiere de "el chofer usó esta patente en 19 de 20 viajes".

FLAG_ASIGNACION_VARIABLE = "asignacion_variable"


@dataclass(frozen=True)
class AsignacionVehiculoResuelta:
    resultado: str
    patente: str | None
    vehiculo_id: str | None
    explicacion: str


def _chofer_es_asignacion_variable(choferes: Mapping[str, object], identificador: str) -> bool:
    """Default conservador: ausencia de la marca == asignación FIJA
    (comportamiento ya vigente hoy, sin cambio, para cualquier chofer
    que nunca declaró variabilidad). Sólo `True` explícito en
    `choferes.json` desactiva la regla para ese chofer."""
    registro = choferes.get(identificador)
    if not isinstance(registro, dict):
        return False
    return bool(registro.get(FLAG_ASIGNACION_VARIABLE, False))


def resolver_patente_operacional_canonica_por_chofer(
    *, nombre_documental: str, rut_documental: str, choferes: Mapping[str, object],
    vehiculos: Iterable[object], tipo_esperado: str = "TRACTO",
) -> AsignacionVehiculoResuelta:
    """`choferes` es el catálogo crudo (`cargar_catalogo_json`).
    `vehiculos` son objetos `Vehiculo` (mismo contrato que usa
    `_vehiculos_confirmados_para_rut`). `tipo_esperado` acota a
    `patente_tracto` por defecto -- la regla, tal como se pidió, es
    sobre "la patente"/el camión, no sobre la rampla."""
    identidad = resolver_identidad_nominal_fuerte_chofer(
        nombre_documental=nombre_documental, rut_documental=rut_documental, choferes=choferes,
    )
    if identidad.resultado != RESULTADO_RESUELTO or not identidad.identificador:
        return AsignacionVehiculoResuelta(
            RESULTADO_ABSTENCION, None, None,
            "Chofer no identificado de forma inequívoca (ambiguo o desconocido) -- la regla de "
            "asignación canónica no puede aplicarse sin identidad cierta.",
        )
    if _chofer_es_asignacion_variable(choferes, identidad.identificador):
        return AsignacionVehiculoResuelta(
            RESULTADO_NO_APLICA_VARIABLE, None, None,
            f"{identidad.nombre_canonico} está configurado como asignación variable en catálogo -- "
            "la regla de patente canónica no aplica; siguen vigentes los mecanismos existentes.",
        )

    # Import diferido: `_vehiculos_confirmados_para_rut` vive en
    # `decisiones_pendientes.py`, que YA importa este módulo a nivel de
    # módulo (para el wiring de retiro de decisiones) -- el import
    # inverso a nivel de módulo crearía un ciclo (mismo patrón ya usado
    # en `aplicacion_decisiones.py` para `_leer_filas`).
    from atlas_core.decisiones_pendientes import _vehiculos_confirmados_para_rut

    rut_canonico = normalizar_rut(identidad.identificador)
    patentes_asociadas = sorted(_vehiculos_confirmados_para_rut(
        rut_normalizado=rut_canonico, tipo_esperado=tipo_esperado, vehiculos=vehiculos,
    ))
    if not patentes_asociadas:
        return AsignacionVehiculoResuelta(
            RESULTADO_SIN_EVIDENCIA, None, None,
            f"Catálogo sin ninguna patente CONFIRMADA/ACTIVA con rut_chofer_asociado={rut_canonico} "
            f"({identidad.nombre_canonico}) -- falta registrar esa asociación explícita "
            "(confirmar_vehiculo con rut_chofer_asociado), nunca se infiere del historial.",
        )
    if len(patentes_asociadas) > 1:
        return AsignacionVehiculoResuelta(
            RESULTADO_ABSTENCION, None, None,
            f"Catálogo tiene {len(patentes_asociadas)} patentes distintas asociadas a "
            f"{identidad.nombre_canonico} ({', '.join(patentes_asociadas)}) -- múltiples asignaciones "
            "vigentes, ambigüedad real, no se elige ninguna.",
        )
    patente = patentes_asociadas[0]
    vehiculo = next((v for v in vehiculos if v.patente_canonica == patente), None)
    return AsignacionVehiculoResuelta(
        resultado=RESULTADO_RESUELTO, patente=patente,
        vehiculo_id=vehiculo.vehiculo_id if vehiculo is not None else None,
        explicacion=(
            f"{identidad.nombre_canonico} tiene exactamente una patente confirmada en catálogo "
            f"({patente}) -- asignación operacional canónica, la lectura OCR documental se conserva "
            "como evidencia aparte."
        ),
    )
