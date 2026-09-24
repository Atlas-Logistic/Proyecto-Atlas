"""Bloque P0 -- CÓDIGO CLIENTE + DESTINATARIO OPERACIONAL.

Dos identidades documentales DISTINTAS, nunca fusionadas (semántica
confirmada documentalmente, casos reales AGF/PRODALAM/EASY/TORRES/
ACEROS COX):

- `codigo_cliente` ("Código Cliente"): cuenta interna del
  CLIENTE_COMPRADOR (mismo campo que SEÑOR(ES)/RUT cliente). Se
  comporta 1:1 con el comprador en la muestra observada, pero es
  evidencia COMPLEMENTARIA -- nunca reemplaza RUT/nombre ya resueltos.
- `cod_destinatario` ("COD DESTINATARIO"): ficha operacional AZA/SAP.
  Relación observada comprador -> cod_destinatario es 1:N (un mismo
  comprador puede traer varios COD DESTINATARIO, uno por obra/entrega).
  NUNCA equivale a cliente, a un receptor jurídico ni a una dirección
  física; se asocia documentalmente con OBRA_DESTINO, JAMÁS con
  DESPACHAR_A (un mismo COD DESTINATARIO puede traer distintos
  DESPACHAR_A históricamente -- ver `evidencia_destinatario_compatible_
  con_obra`, que nunca examina `despachar_a_crudo`).

Puramente aditivo y complementario:
- Nunca crea entidades de catálogo nuevas por sí mismo -- eso sigue
  viviendo exclusivamente en `aplicacion_decisiones.py`, gatillado por
  una decisión humana.
- `CatalogoCodigosCliente.confirmar()` sólo debe invocarse desde ese
  mismo mecanismo de aplicación de decisiones YA existente, tras una
  confirmación/registro humano que traía `codigo_cliente` -- nunca desde
  la ingesta ni desde una sola guía sin corroboración.
- `evidencia_destinatario_compatible_con_obra` nunca aprende de un
  catálogo mutable propio: lee directamente las filas YA persistidas del
  dataset documental (la fuente de verdad es la evidencia real ya
  guardada, nunca una inferencia nueva).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico
from atlas_core.catalogo_clientes import Cliente, normalizar_nombre_cliente, normalizar_rut_cliente
from atlas_core.decisiones_pendientes import rut_documental_de_decision_cliente

VERSION_FORMATO = 1
NOMBRE_LOCK_CODIGOS_CLIENTE = "codigos_cliente"

_AUSENTES = {"", "No encontrado", "REVISAR", "Ilegible"}

RESULTADO_SUGERENCIA_HUMANA = "SUGERENCIA_HUMANA"
RESULTADO_ABSTENCION = "ABSTENCION"
RESULTADO_SIN_EVIDENCIA = "SIN_EVIDENCIA"


class ErrorCatalogoCodigosCliente(ValueError):
    """Error base del catálogo de asociaciones código_cliente -> cliente_id."""


class CatalogoCodigosClienteCorruptoError(ErrorCatalogoCodigosCliente):
    """El archivo existe pero no cumple el formato esperado."""


def _normalizar_codigo(valor: str | None) -> str:
    """Un código administrativo se conserva TAL CUAL (ceros a la
    izquierda incluidos, alfanumérico permitido -- caso real ACEROS COX
    "CL12") -- nunca se interpreta como número; sólo se recorta espacio
    en blanco sobrante y se uniforma mayúscula para comparar."""
    if valor is None or str(valor).strip() in _AUSENTES:
        return ""
    return re.sub(r"\s+", "", str(valor)).upper()


class CatalogoCodigosCliente:
    """Mapeo `codigo_cliente -> cliente_id`, persistencia JSON local
    (`catalogos_privados/codigos_cliente.json`). Nunca se escribe desde
    la ingesta ni desde `procesar_archivo` -- sólo `confirmar()`,
    invocado por `aplicacion_decisiones.py` tras una confirmación/
    registro humano de CLIENTE_CANDIDATO/CLIENTE_DESCONOCIDO que traía
    `codigo_cliente`."""

    def __init__(self, ruta: str | Path) -> None:
        self.ruta = Path(ruta)

    def _leer(self) -> dict[str, dict[str, object]]:
        if not self.ruta.is_file():
            return {}
        try:
            contenido = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CatalogoCodigosClienteCorruptoError(str(error)) from error
        if not isinstance(contenido, dict) or not isinstance(contenido.get("asociaciones"), dict):
            raise CatalogoCodigosClienteCorruptoError("formato de codigos_cliente.json inválido")
        return contenido["asociaciones"]

    def buscar(self, codigo: str) -> str | None:
        """`cliente_id` asociado a `codigo`, o `None` si no hay ninguna
        asociación CONFIRMADA todavía -- nunca inventa una ni infiere de
        una coincidencia parcial."""
        codigo_normalizado = _normalizar_codigo(codigo)
        if not codigo_normalizado:
            return None
        try:
            asociaciones = self._leer()
        except CatalogoCodigosClienteCorruptoError:
            return None
        entrada = asociaciones.get(codigo_normalizado)
        return str(entrada["cliente_id"]) if entrada else None

    def confirmar(
        self, *, codigo: str, cliente_id: str, actor: str, fuente: str,
        reloj=lambda: datetime.now(timezone.utc),
    ) -> None:
        """Registra la asociación -- SIEMPRE gatillada por una decisión
        humana ya aplicada (ver docstring del módulo); sobrescribe una
        asociación previa del mismo código sólo porque un humano nuevo
        acaba de confirmarla explícitamente, nunca por inferencia."""
        codigo_normalizado = _normalizar_codigo(codigo)
        if not codigo_normalizado:
            raise ErrorCatalogoCodigosCliente("código vacío")
        if not str(cliente_id or "").strip():
            raise ErrorCatalogoCodigosCliente("cliente_id vacío")
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with bloqueo_sesion(self.ruta.parent, NOMBRE_LOCK_CODIGOS_CLIENTE):
            try:
                asociaciones = dict(self._leer())
            except CatalogoCodigosClienteCorruptoError:
                asociaciones = {}
            asociaciones[codigo_normalizado] = {
                "cliente_id": str(cliente_id), "actor": str(actor), "fuente": str(fuente),
                "fecha_confirmacion": reloj().isoformat(),
            }
            escribir_json_atomico(
                self.ruta, {"version_formato": VERSION_FORMATO, "asociaciones": asociaciones},
            )


@dataclass(frozen=True)
class IdentidadClienteReforzada:
    resultado: str
    cliente_id: str | None
    razon_social: str | None
    via: str
    explicacion: str


def _nombre_compatible(nombre_documental: str, cliente: Cliente) -> bool:
    """Compatibilidad conservadora: el nombre documental normalizado
    coincide con, o está contenido en, la razón social/nombre comercial/
    algún alias del cliente ya catalogado -- nunca fuzzy/aproximado
    (mismo criterio de igualdad textual que ya usa `_claves_cliente`,
    sin tolerancia nueva)."""
    if nombre_documental in _AUSENTES:
        return False
    clave_doc = normalizar_nombre_cliente(nombre_documental)
    if not clave_doc:
        return False
    claves_cliente = {
        normalizar_nombre_cliente(valor)
        for valor in (cliente.razon_social, cliente.nombre_comercial, *cliente.aliases)
        if valor
    }
    return any(clave_doc == clave or clave_doc in clave or clave in clave_doc for clave in claves_cliente if clave)


def _cliente_por_rut(clientes: Iterable[Cliente], rut_normalizado: str) -> Cliente | None:
    if not rut_normalizado:
        return None
    for cliente in clientes:
        if cliente.rut and cliente.rut == rut_normalizado:
            return cliente
    return None


def resolver_identidad_cliente_reforzada(
    *, rut_documental: str, nombre_documental: str, codigo_cliente: str,
    clientes: Iterable[Cliente], catalogo_codigos: CatalogoCodigosCliente,
) -> IdentidadClienteReforzada:
    """Prioridad de identidad (contrato P0, punto B):

    1. RUT documental válido y coincide con un cliente catalogado --
       gana siempre, `codigo_cliente` es irrelevante.
    2. `codigo_cliente` conocido (ya confirmado alguna vez por un humano,
       ver `CatalogoCodigosCliente.confirmar`) + identidad compatible
       (sin RUT documental contradictorio, y con nombre documental
       compatible) -- refuerza como sugerencia, nunca automática.
    3. `codigo_cliente` conocido pero el RUT documental de ESTA guía
       pertenece a un cliente DISTINTO del que el código señala --
       ABSTENCIÓN explícita: nunca se reemplaza una identidad por RUT
       con la que sugiere el código.
    4. Sin código conocido, o sin evidencia de nombre compatible -- sin
       evidencia: el resto del pipeline sigue exactamente igual que hoy.
    """
    clientes = list(clientes)
    rut_normalizado = normalizar_rut_cliente(rut_documental) if rut_documental not in _AUSENTES else ""
    cliente_por_rut = _cliente_por_rut(clientes, rut_normalizado) if rut_normalizado else None
    if cliente_por_rut is not None:
        return IdentidadClienteReforzada(
            resultado=RESULTADO_SUGERENCIA_HUMANA, cliente_id=cliente_por_rut.cliente_id,
            razon_social=cliente_por_rut.razon_social, via="RUT",
            explicacion="RUT documental coincide con un cliente catalogado -- máxima prioridad, código no interviene.",
        )

    codigo_normalizado = _normalizar_codigo(codigo_cliente)
    if not codigo_normalizado:
        return IdentidadClienteReforzada(RESULTADO_SIN_EVIDENCIA, None, None, "", "Sin código cliente documental.")

    cliente_id_conocido = catalogo_codigos.buscar(codigo_normalizado)
    if cliente_id_conocido is None:
        return IdentidadClienteReforzada(
            RESULTADO_SIN_EVIDENCIA, None, None, "",
            "Código cliente sin asociación confirmada todavía -- no se aprende de esta guía sola.",
        )

    cliente_candidato = next((c for c in clientes if c.cliente_id == cliente_id_conocido), None)
    if cliente_candidato is None:
        return IdentidadClienteReforzada(
            RESULTADO_SIN_EVIDENCIA, None, None, "",
            "Código cliente conocido pero el cliente asociado ya no existe en el catálogo vigente.",
        )

    if rut_normalizado and cliente_candidato.rut and rut_normalizado != cliente_candidato.rut:
        return IdentidadClienteReforzada(
            resultado=RESULTADO_ABSTENCION, cliente_id=None, razon_social=None, via="CODIGO_CLIENTE",
            explicacion=(
                f"Código cliente {codigo_normalizado} está asociado a {cliente_candidato.razon_social}, "
                "pero el RUT documental de esta guía pertenece a otra entidad -- abstención, "
                "no se reemplaza la identidad."
            ),
        )

    if not _nombre_compatible(nombre_documental, cliente_candidato):
        return IdentidadClienteReforzada(
            RESULTADO_SIN_EVIDENCIA, None, None, "",
            "Código cliente conocido pero el nombre documental no es compatible -- se requiere evidencia adicional.",
        )

    return IdentidadClienteReforzada(
        resultado=RESULTADO_SUGERENCIA_HUMANA, cliente_id=cliente_candidato.cliente_id,
        razon_social=cliente_candidato.razon_social, via="CODIGO_CLIENTE",
        explicacion=(
            f"Código cliente {codigo_normalizado} conocido y nombre documental compatible con "
            f"{cliente_candidato.razon_social}."
        ),
    )


def evidencia_destinatario_compatible_con_obra(
    *, cliente_comprador: str, cod_destinatario: str, obra_candidata: str,
    filas_historicas: Iterable[Mapping[str, str]],
) -> bool:
    """Relación observada cliente_comprador -> cod_destinatario ->
    obra_destino_literal, leída DIRECTAMENTE de filas ya persistidas --
    nunca un catálogo nuevo que aprenda solo, la fuente de verdad es el
    propio dataset documental. `True` sólo si `obra_candidata` aparece,
    normalizada, entre los `obra_destino` históricos de filas del MISMO
    cliente_comprador + MISMO cod_destinatario -- nunca se infiere nada
    si no hay al menos una fila histórica exactamente así. Deliberadamente
    nunca examina `despachar_a_crudo`: un mismo COD DESTINATARIO puede
    traer distintos DESPACHAR_A históricamente (contrato P0, punto C)."""
    if cliente_comprador in _AUSENTES or cod_destinatario in _AUSENTES or obra_candidata in _AUSENTES:
        return False
    cod_normalizado = _normalizar_codigo(cod_destinatario)
    clave_cliente = normalizar_nombre_cliente(cliente_comprador)
    clave_obra = normalizar_nombre_cliente(obra_candidata)
    for fila in filas_historicas:
        if normalizar_nombre_cliente(str(fila.get("cliente", ""))) != clave_cliente:
            continue
        if _normalizar_codigo(str(fila.get("cod_destinatario", ""))) != cod_normalizado:
            continue
        if normalizar_nombre_cliente(str(fila.get("obra_destino", ""))) == clave_obra:
            return True
    return False


def enriquecer_decisiones_cliente_por_codigo(
    *, decisiones: Iterable[Mapping[str, object]], filas: Iterable[Mapping[str, str]],
    clientes: Iterable[Cliente], catalogo_codigos: CatalogoCodigosCliente,
) -> list[dict[str, object]]:
    """Enriquece CLIENTE_AUSENTE/CLIENTE_DESCONOCIDO/CLIENTE_CANDIDATO YA
    generadas (nunca las crea) con `evaluacion_evidencia_codigo` -- campo
    APARTE de `evaluacion_evidencia` (que sigue reflejando sólo RUT/
    nombre, sin tocar) -- puramente informativo/complementario. Nunca
    sube el nivel de auto-resolución por código solo (contrato P0, punto
    1: "inicialmente evidencia complementaria")."""
    clientes = list(clientes)
    filas_por_archivo = {str(f.get("archivo", "")): f for f in filas}
    salida: list[dict[str, object]] = []
    for decision_original in decisiones:
        decision = dict(decision_original)
        if decision.get("entidad") == "CLIENTE" and decision.get("tipo") in (
            "CLIENTE_AUSENTE", "CLIENTE_DESCONOCIDO", "CLIENTE_CANDIDATO",
        ):
            archivo = str((decision.get("documento") or {}).get("archivo", ""))
            fila = filas_por_archivo.get(archivo) or {}
            codigo_cliente = str(fila.get("codigo_cliente", ""))
            rut_documental = rut_documental_de_decision_cliente(decision) or str(fila.get("rut_cliente", ""))
            nombre_documental = str(decision.get("valor_documental", "")) or str(fila.get("cliente", ""))
            identidad = resolver_identidad_cliente_reforzada(
                rut_documental=rut_documental, nombre_documental=nombre_documental,
                codigo_cliente=codigo_cliente, clientes=clientes, catalogo_codigos=catalogo_codigos,
            )
            decision["evaluacion_evidencia_codigo"] = {
                "resultado": identidad.resultado, "via": identidad.via,
                "cliente_id": identidad.cliente_id, "razon_social": identidad.razon_social,
                "explicacion": identidad.explicacion,
            }
        salida.append(decision)
    return salida


def enriquecer_decisiones_obra_por_destinatario(
    *, decisiones: Iterable[Mapping[str, object]], filas: Iterable[Mapping[str, str]],
) -> list[dict[str, object]]:
    """Enriquece OBRA_DESCONOCIDA con `evaluacion_evidencia_destinatario`
    (contrato P0, punto C: refuerza obra sólo si cliente comprador ya
    resuelto + cod_destinatario tiene historial compatible + sin
    contradicción) y agrega `cod_destinatario`/`codigo_cliente`
    documentales como CONTEXTO puramente informativo a DESTINO_NO_
    RESUELTO -- nunca infiere ni fija `despachar_a_crudo`/direccion desde
    ahí (contrato P0, punto E)."""
    filas = list(filas)
    filas_por_archivo = {str(f.get("archivo", "")): f for f in filas}
    salida: list[dict[str, object]] = []
    for decision_original in decisiones:
        decision = dict(decision_original)
        archivo = str((decision.get("documento") or {}).get("archivo", ""))
        fila = filas_por_archivo.get(archivo) or {}
        if decision.get("tipo") == "OBRA_DESCONOCIDA":
            contexto = decision.get("contexto") or {}
            cliente_comprador = str(contexto.get("cliente_canonico", "")) or str(fila.get("cliente", ""))
            cod_destinatario = str(fila.get("cod_destinatario", ""))
            obra_candidata = str(decision.get("valor_documental", ""))
            compatible = evidencia_destinatario_compatible_con_obra(
                cliente_comprador=cliente_comprador, cod_destinatario=cod_destinatario,
                obra_candidata=obra_candidata, filas_historicas=filas,
            )
            decision["evaluacion_evidencia_destinatario"] = {
                "resultado": RESULTADO_SUGERENCIA_HUMANA if compatible else RESULTADO_SIN_EVIDENCIA,
                "cod_destinatario": cod_destinatario if cod_destinatario not in _AUSENTES else None,
                "explicacion": (
                    f"Historial de cliente+COD DESTINATARIO {cod_destinatario} ya registró esta obra."
                    if compatible else
                    "Sin historial compatible de cliente+COD DESTINATARIO que corrobore esta obra."
                ),
            }
        elif decision.get("tipo") == "DESTINO_NO_RESUELTO":
            cod_destinatario = str(fila.get("cod_destinatario", ""))
            codigo_cliente = str(fila.get("codigo_cliente", ""))
            if cod_destinatario not in _AUSENTES or codigo_cliente not in _AUSENTES:
                contexto = dict(decision.get("contexto") or {})
                contexto["cod_destinatario_documental"] = cod_destinatario if cod_destinatario not in _AUSENTES else None
                contexto["codigo_cliente_documental"] = codigo_cliente if codigo_cliente not in _AUSENTES else None
                decision["contexto"] = contexto
        salida.append(decision)
    return salida
