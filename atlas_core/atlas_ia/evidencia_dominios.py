"""Bloque B1 AUTORIDAD / EVIDENCIA INTERNA -- construye evidencia
`EvidenciaIA` para B1 a partir del CONOCIMIENTO INTERNO CANÓNICO que
Atlas ya posee (catálogos, aliases, RUT, confirmaciones humanas de
identidad, relaciones chofer↔vehículo, obras↔destino confirmados),
consumiendo los Motores de Evidencia deterministas que ya viven en
producción -- nunca reimplementa su lógica:

- CLIENTE  -> `atlas_core.motor_evidencia_clientes.evaluar_evidencia_cliente`
- OBRA     -> `atlas_core.motor_evidencia_obras` (+ resolución por variación
              ortográfica menor / prefijo confirmado) y
              `CatalogoObrasDestinos.listar_destinos_confirmados_para_obra`
- VEHÍCULO -> `atlas_core.decisiones_pendientes.evaluar_evidencia_patente`

Causa raíz que este módulo corrige (Bloque "AUTORIDAD OPERACIONAL"):
los recolectores de `registro_problemas` sólo miraban documentos del
mismo lote, así que B1 recibía `evidencias: []` aunque Atlas tuviera la
respuesta en un catálogo/ledger -- y la barrera anti-alucinación
(`validadores.validar_hipotesis_multicampo`) bloqueaba cualquier
conclusión correcta por "VALOR_NO_RESPALDADO_POR_EVIDENCIA". Aquí NO se
resuelve nada ni se escribe nada: sólo se EMPAQUETA lo que los Motores
deterministas ya saben, como `EvidenciaIA` de sólo lectura, para que B1
pueda razonar con contexto real y el validador reconozca ese valor como
respaldado.

Nunca lanza: cualquier catálogo ausente/corrupto o dato faltante produce
`()` -- exactamente el mismo criterio que el resto de los recolectores
`sin_ocr` de Atlas.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping

from atlas_core.atlas_ia.adaptadores import evidencias_ia_desde_candidatos_vehiculo
from atlas_core.atlas_ia.contratos import EvidenciaIA
from atlas_core.atlas_ia.convergencia import (
    CONTRADICCION_FUERTE,
    MANTENER_REVISION,
    RESOLVER_SILENCIOSO,
    CandidatoConvergencia,
    ResultadoConvergencia,
    SEÑAL_ALIAS_CONOCIDO,
    SEÑAL_CATALOGO_CANONICO,
    SEÑAL_CONFIRMACION_HUMANA,
    SEÑAL_DIRECCION_COMUNA_COINCIDE,
    SEÑAL_HISTORIAL_CONSISTENTE,
    SEÑAL_RELACION_CHOFER_VEHICULO,
    SEÑAL_RELACION_CLIENTE_OBRA,
    SEÑAL_RELACION_OBRA_DESTINO,
    SEÑAL_RUT_COINCIDE,
    evaluar_convergencia,
)
from atlas_core.motor_evidencia import (
    NIVEL_CONFIRMACION_HUMANA,
    NIVEL_DOCUMENTAL_INDEPENDIENTE,
    NIVEL_EXTERNO_CORPORATIVO,
    NIVEL_EXTERNO_OFICIAL,
    CandidatoEvidencia,
    ResultadoEvidencia,
)

_AUSENTES = {"", "NO ENCONTRADO", "No encontrado"}

# Traducción nivel de Motor determinista -> `tipo_fuente` de `EvidenciaIA`
# (contrato `TIPOS_FUENTE_IA`). Nunca inventa una categoría nueva -- mapea
# la jerarquía ya publicada de `atlas_core.motor_evidencia`.
_TIPO_FUENTE_POR_NIVEL = {
    NIVEL_CONFIRMACION_HUMANA: "DECISION_HUMANA",
    NIVEL_EXTERNO_OFICIAL: "EXTERNO",
    NIVEL_EXTERNO_CORPORATIVO: "EXTERNO",
    NIVEL_DOCUMENTAL_INDEPENDIENTE: "HISTORICO",
}


def _tipo_esperado_por_campo(campo: str) -> str | None:
    return {"patente_tracto": "TRACTO", "patente_rampla": "CARRO"}.get(campo.lower())


def _evidencias_desde_resultado_generico(
    resultado: ResultadoEvidencia, *, campo: str, procedencia: str,
) -> tuple[EvidenciaIA, ...]:
    """Convierte los `CandidatoEvidencia` de un `ResultadoEvidencia`
    (Motor de clientes/obras) en `EvidenciaIA` -- uno por candidato, sin
    descartar ninguno (el Motor determinista nunca oculta al que perdió,
    este adaptador tampoco)."""
    evidencias: list[EvidenciaIA] = []
    for candidato in resultado.candidatos:
        if not str(candidato.valor_canonico or "").strip():
            continue
        tipo_fuente = _TIPO_FUENTE_POR_NIVEL.get(candidato.nivel, "CATALOGO")
        es_humana = candidato.nivel == NIVEL_CONFIRMACION_HUMANA
        evidencias.append(EvidenciaIA(
            identificador=str(candidato.identificador or candidato.valor_canonico),
            campo=campo,
            valor=str(candidato.valor_canonico),
            tipo_fuente=tipo_fuente,
            nivel=candidato.nivel,
            a_favor=tuple(candidato.evidencias),
            en_contra=tuple(candidato.conflictos),
            independencia=int(candidato.metadatos.get("transportes_independientes", 0) or 0),
            es_decision_humana=es_humana,
            procedencia=procedencia,
            referencias_fuente=tuple(
                str(v) for v in candidato.metadatos.get("guias", ())
            ) or (str(resultado.resultado),),
        ))
    return tuple(evidencias)


# ---------------------------------------------------------------------
# CLIENTE
# ---------------------------------------------------------------------


def evidencia_cliente_interna(
    *, nombre_documental: str, rut_documental: str, numero_guia: str,
    numero_transporte: str, carpeta_catalogos: str | Path | None,
) -> tuple[EvidenciaIA, ...]:
    """Empaqueta lo que el Motor de Evidencia de Clientes ya sabe:
    coincidencia por RUT canónico, coincidencia difusa/alias contra
    clientes CONFIRMADO/ACTIVO, y confirmaciones humanas de identidad
    independientes acumuladas para ese RUT (`evidencia_entidades.json`)."""
    if not carpeta_catalogos:
        return ()
    carpeta = Path(carpeta_catalogos)
    nombre = str(nombre_documental or "").strip()
    if nombre in _AUSENTES and str(rut_documental or "").strip() in _AUSENTES:
        return ()
    try:
        from atlas_core.catalogo_clientes import CatalogoClientes
        from atlas_core.evidencia_entidades import AlmacenEvidenciaEntidades
        from atlas_core.motor_evidencia_clientes import evaluar_evidencia_cliente

        clientes = CatalogoClientes(carpeta / "clientes.json").listar()
    except (OSError, ValueError):
        return ()
    confirmaciones: tuple = ()
    try:
        from atlas_core.catalogo_clientes import normalizar_rut_cliente

        rut_norm = normalizar_rut_cliente(rut_documental)
        confirmaciones = tuple(
            AlmacenEvidenciaEntidades(carpeta / "evidencia_entidades.json").confirmaciones_para(
                dominio="CLIENTE", contexto_clave=rut_norm,
            )
        )
    except (OSError, ValueError):
        confirmaciones = ()
    try:
        resultado = evaluar_evidencia_cliente(
            razon_social_documental=nombre if nombre not in _AUSENTES else "",
            rut_documental=str(rut_documental or ""),
            numero_guia=numero_guia, numero_transporte=numero_transporte,
            clientes=clientes, confirmaciones=confirmaciones,
        )
        evidencias = list(_evidencias_desde_resultado_generico(
            resultado, campo="cliente",
            procedencia="atlas_ia.evidencia_dominios.evidencia_cliente_interna",
        ))
    except (OSError, ValueError):
        evidencias = []

    # Identidad canónica exacta/única + confirmada como evidencia real
    # (Bloque A, ítem 5): `evaluar_evidencia_cliente` sólo resuelve por RUT
    # canónico o confirmaciones humanas acumuladas -- nunca por nombre. Si
    # el RUT no se pudo extraer pero el nombre documental resuelve, difuso
    # o por alias, contra UN único cliente CONFIRMADO/ACTIVO, esa identidad
    # canónica también es evidencia (nunca "cualquier nombre parecido":
    # `resolver_nombre_cliente_difuso` ya exige único candidato sobre el
    # umbral y con margen sobre el segundo).
    if nombre not in _AUSENTES:
        try:
            from atlas_core.catalogo_clientes import (
                EstadoCalidadCliente, EstadoVigenciaCliente,
            )
            from atlas_core.catalogos import resolver_nombre_cliente_difuso

            confirmados = [
                c for c in clientes
                if c.estado_calidad == EstadoCalidadCliente.CONFIRMADO.value
                and c.estado_vigencia == EstadoVigenciaCliente.ACTIVO.value
            ]
            coincidencia = resolver_nombre_cliente_difuso(confirmados, nombre)
            if coincidencia.estado in {"SIN_CAMBIO", "ALIAS", "COINCIDENCIA_SEGURA"}:
                # `SIN_CAMBIO` devuelve el propio texto de entrada como
                # `valor_resultado` -- el cliente canónico se identifica por
                # igualdad de nombre NORMALIZADO (razón social o alias),
                # nunca porque el texto documental esté en el conjunto (eso
                # calzaría con cualquier cliente).
                canonico = next(
                    (
                        c for c in confirmados
                        if _mismo_nombre_cliente(c.razon_social, coincidencia.valor_resultado)
                        or _mismo_nombre_cliente(c.razon_social, nombre)
                        or any(_mismo_nombre_cliente(a, coincidencia.valor_resultado) for a in c.aliases)
                    ),
                    None,
                )
                if canonico is not None and not any(
                    e.valor == canonico.razon_social for e in evidencias
                ):
                    exacta = coincidencia.estado in {"SIN_CAMBIO", "ALIAS"}
                    evidencias.append(EvidenciaIA(
                        identificador=f"cliente:{canonico.cliente_id}", campo="cliente",
                        valor=canonico.razon_social, tipo_fuente="CATALOGO",
                        nivel="CATALOGO_CONFIRMADO",
                        a_favor=(
                            ("IDENTIDAD_CANONICA_EXACTA_UNICA",) if exacta
                            else ("NOMBRE_" + coincidencia.estado,)
                        ),
                        independencia=1,
                        procedencia="atlas_ia.evidencia_dominios.evidencia_cliente_interna",
                        referencias_fuente=(
                            f"cliente_id={canonico.cliente_id}", f"rut={canonico.rut}",
                            f"estado={coincidencia.estado}",
                        ),
                    ))
        except (OSError, ValueError):
            pass
    return tuple(evidencias)


def _mismo_nombre_cliente(a: str, b: str) -> bool:
    try:
        from atlas_core.catalogo_clientes import normalizar_nombre_cliente

        return bool(a) and normalizar_nombre_cliente(a) == normalizar_nombre_cliente(b)
    except (ImportError, ValueError):
        return False


# ---------------------------------------------------------------------
# OBRA
# ---------------------------------------------------------------------


def _direccion_coincide(a: str, b: str) -> bool:
    try:
        from atlas_core.motor_evidencia_obras import _direccion_obra_coincide

        return _direccion_obra_coincide(a, b)
    except (ImportError, ValueError):
        return False


def evidencia_obra_interna(
    *, nombre_documental: str, cliente_documental: str, rut_cliente_documental: str,
    despachar_a_documental: str, carpeta_catalogos: str | Path | None,
) -> tuple[EvidenciaIA, ...]:
    """Empaqueta la obra conocida que corresponde a una variante OCR del
    nombre documental, CORROBORADA por contexto (cliente coincide + la
    dirección de entrega documental calza con un destino confirmado de esa
    obra) -- la conjunción es lo que hace segura la relación, nunca un
    fuzzy global. Reutiliza `resolver_obra_por_variacion_ortografica_menor`
    / `resolver_obra_por_prefijo_documental_confirmado` (ya en producción)
    y `listar_destinos_confirmados_para_obra`."""
    if not carpeta_catalogos:
        return ()
    carpeta = Path(carpeta_catalogos)
    nombre = str(nombre_documental or "").strip()
    if nombre in _AUSENTES:
        return ()
    try:
        from atlas_core.catalogo_obras_destinos import (
            CatalogoObrasDestinos, EstadoObra, EstadoVigencia, normalizar_nombre_obra,
        )
        from atlas_core.decisiones_pendientes import _identidad_cliente_por_rut
        from atlas_core.motor_evidencia_obras import (
            resolver_obra_por_prefijo_documental_confirmado,
            resolver_obra_por_variacion_ortografica_menor,
        )

        catalogo = CatalogoObrasDestinos(
            ruta=carpeta / "obras_destinos.json",
            ruta_clientes=carpeta / "clientes.json",
            ruta_destinos=carpeta / "destinos_maestros.json",
        )
        obras = catalogo.listar_obras()
    except (OSError, ValueError):
        return ()

    cliente = _identidad_cliente_por_rut(carpeta, rut_cliente_documental)
    cliente_id = cliente.cliente_id if cliente is not None else ""

    activas = tuple(
        o for o in obras
        if o.estado == EstadoObra.CONFIRMADA.value
        and o.estado_vigencia == EstadoVigencia.ACTIVO.value
    )
    del_cliente = tuple(o for o in activas if cliente_id and o.cliente_id == cliente_id)
    universo = del_cliente or activas

    clave = normalizar_nombre_obra(nombre)
    exacta = tuple(
        o for o in universo
        if clave in {
            normalizar_nombre_obra(o.nombre_canonico),
            *(normalizar_nombre_obra(a) for a in o.aliases_documentales),
        }
    )
    obra = (
        (exacta[0] if len(exacta) == 1 else None)
        or resolver_obra_por_variacion_ortografica_menor(
            nombre_documental=nombre, obras_confirmadas_mismo_cliente=universo,
        )
        or resolver_obra_por_prefijo_documental_confirmado(
            nombre_documental=nombre, obras_confirmadas_mismo_cliente=universo,
        )
    )
    if obra is None:
        return ()

    try:
        destinos = catalogo.listar_destinos_confirmados_para_obra(nombre_obra=obra.nombre_canonico)
    except (OSError, ValueError):
        destinos = []
    despachar_a = str(despachar_a_documental or "").strip()
    destino_corrobora = any(
        _direccion_coincide(str(getattr(d, "direccion", "") or ""), despachar_a)
        for d in destinos
    ) if despachar_a else False

    # El cliente sólo se considera corroborado cuando el RUT documental
    # resolvió, exacto, contra un cliente CONFIRMADO/ACTIVO -- nunca por
    # nombre suelto (ese camino es el que crea CLIENTE_CANDIDATO, no una
    # corroboración).
    cliente_corrobora = cliente is not None

    a_favor = ["OBRA_CONFIRMADA_VARIANTE_OCR"]
    nivel = "CATALOGO_CONFIRMADO"
    if cliente_corrobora:
        a_favor.append("CLIENTE_CANONICO_COINCIDE")
    if destino_corrobora:
        a_favor.append("DESTINO_CONFIRMADO_COINCIDE")
    if cliente_corrobora and destino_corrobora:
        # Conjunción: identidad altamente compatible + destino confirmado
        # coincide + sin competidor plausible -> evidencia interna fuerte
        # (equivalente estructural a una confirmación previa de esta
        # misma relación).
        nivel = NIVEL_CONFIRMACION_HUMANA
    referencias = (
        f"obra_id={obra.obra_id}",
        f"cliente_id={obra.cliente_id}",
        f"aliases={'|'.join(obra.aliases_documentales)}",
        f"destinos_confirmados={len(destinos)}",
    )
    tipo_fuente = "DECISION_HUMANA" if nivel == NIVEL_CONFIRMACION_HUMANA else "CATALOGO"
    return (
        EvidenciaIA(
            identificador=f"obra:{obra.obra_id}", campo="obra_destino",
            valor=obra.nombre_canonico, tipo_fuente=tipo_fuente, nivel=nivel,
            a_favor=tuple(a_favor),
            es_decision_humana=(nivel == NIVEL_CONFIRMACION_HUMANA),
            independencia=1,
            procedencia="atlas_ia.evidencia_dominios.evidencia_obra_interna",
            referencias_fuente=referencias,
        ),
    )


# ---------------------------------------------------------------------
# VEHÍCULO
# ---------------------------------------------------------------------


def evidencia_vehiculo_interna(
    *, campo: str, valor_documental: str, rut_chofer: str, numero_transporte: str,
    filas: Iterable[Mapping[str, object]], carpeta_catalogos: str | Path | None,
) -> tuple[EvidenciaIA, ...]:
    """Empaqueta lo que `evaluar_evidencia_patente` (Motor de Vehículos,
    Bloque VEHÍCULO E1/E2/R11) ya sabe: patentes CONFIRMADAS asociadas por
    un humano a este RUT, variantes históricas del mismo chofer en
    transportes independientes, y confusiones OCR calibradas del catálogo
    -- cada candidato como `EvidenciaIA`, con su nivel intacto. La
    diferencia 2↔5 de "JD8629" no está en la tabla de confusiones OCR
    globales (nunca se amplía a ciegas): lo que hace resoluble el caso es
    la CONFIRMACIÓN HUMANA de que JD8659 es la rampla de este chofer/RUT
    -- evidencia contextual, no una regla nueva."""
    if not carpeta_catalogos:
        return ()
    carpeta = Path(carpeta_catalogos)
    if str(valor_documental or "").strip() in _AUSENTES or not str(rut_chofer or "").strip():
        return ()
    try:
        from atlas_core.catalogo_vehiculos import cargar_catalogo_vehiculos
        from atlas_core.decisiones_pendientes import evaluar_evidencia_patente

        vehiculos = cargar_catalogo_vehiculos(carpeta / "vehiculos.json").homologables()
    except (OSError, ValueError):
        return ()
    try:
        resultado = evaluar_evidencia_patente(
            campo=campo, valor_documental=str(valor_documental),
            rut_chofer=str(rut_chofer), tipo_esperado=_tipo_esperado_por_campo(campo),
            numero_transporte_actual=str(numero_transporte or ""),
            filas=list(filas), vehiculos=vehiculos,
        )
    except (OSError, ValueError):
        return ()
    return evidencias_ia_desde_candidatos_vehiculo(
        resultado.get("candidatos") or (), campo=campo,
    )


# ---------------------------------------------------------------------
# CONVERGENCIA -- ¿el conocimiento acumulado absorbe la variación OCR y
# resuelve silenciosamente al canónico? (Bloque A, criterio general)
# ---------------------------------------------------------------------


def _distancia_edicion(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return len(a) + len(b)
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        actual = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            actual[j] = min(anterior[j] + 1, actual[j - 1] + 1, anterior[j - 1] + (0 if ca == cb else 1))
        anterior = actual
    return anterior[-1]


def _distancia_token_unico(a: str, b: str) -> int | None:
    """Distancia de edición del ÚNICO token que difiere entre dos nombres
    normalizados con el mismo número de tokens -- `None` si difieren en
    cero o en más de un token (no es una "variación pequeña", es otra
    identidad)."""
    ta, tb = a.upper().split(), b.upper().split()
    if len(ta) != len(tb):
        return None
    difs = [(x, y) for x, y in zip(ta, tb) if x != y]
    if len(difs) != 1:
        return 0 if not difs else None
    return _distancia_edicion(*difs[0])


def convergencia_vehiculo(
    *, campo: str, valor_documental: str, rut_chofer: str, numero_transporte: str,
    filas: Iterable[Mapping[str, object]], carpeta_catalogos: str | Path | None,
) -> ResultadoConvergencia:
    """¿Una confirmación humana / historial fuerte del chofer permite
    resolver esta patente al canónico sin pasar por revisión? Nunca
    inventa: sólo evalúa los candidatos que `evaluar_evidencia_patente`
    ya reunió, más una comprobación de contradicción (el propio valor OCR
    es una patente canónica real y distinta -> no es un error OCR)."""
    valor = str(valor_documental or "").strip()
    if not carpeta_catalogos or valor in _AUSENTES or not str(rut_chofer or "").strip():
        return ResultadoConvergencia(decision=MANTENER_REVISION, valor_ocr_original=valor, metodo="CONVERGENCIA_VEHICULO")
    carpeta = Path(carpeta_catalogos)
    try:
        from atlas_core.catalogo_vehiculos import (
            cargar_catalogo_vehiculos, normalizar_patente_vehiculo, resolver_patente,
        )
        from atlas_core.decisiones_pendientes import evaluar_evidencia_patente

        vehiculos = list(cargar_catalogo_vehiculos(carpeta / "vehiculos.json").homologables())
    except (OSError, ValueError):
        return ResultadoConvergencia(decision=MANTENER_REVISION, valor_ocr_original=valor, metodo="CONVERGENCIA_VEHICULO")

    contradicciones: list[str] = []
    exacto = resolver_patente(carpeta / "vehiculos.json", valor)
    if exacto.estado == "COINCIDENCIA_EXACTA":
        contradicciones.append(
            f'"{valor}" ya es una patente canónica real -- no es una lectura OCR a corregir'
        )

    try:
        resultado = evaluar_evidencia_patente(
            campo=campo, valor_documental=valor, rut_chofer=str(rut_chofer),
            tipo_esperado=_tipo_esperado_por_campo(campo),
            numero_transporte_actual=str(numero_transporte or ""),
            filas=list(filas), vehiculos=vehiculos,
        )
    except (OSError, ValueError):
        return ResultadoConvergencia(decision=MANTENER_REVISION, valor_ocr_original=valor, metodo="CONVERGENCIA_VEHICULO")

    valor_norm = normalizar_patente_vehiculo(valor)
    candidatos: list[CandidatoConvergencia] = []
    for c in resultado.get("candidatos") or ():
        codigos = tuple(c.get("evidencias") or ())
        señales: set[str] = {SEÑAL_CATALOGO_CANONICO}
        if "CONFIRMACION_HUMANA_ASOCIADA_AL_CHOFER" in codigos:
            señales.add(SEÑAL_CONFIRMACION_HUMANA)
            señales.add(SEÑAL_RELACION_CHOFER_VEHICULO)
        if "RUT_CHOFER_COINCIDE" in codigos:
            señales.add(SEÑAL_RUT_COINCIDE)
        if int(c.get("transportes_independientes", 0) or 0) >= 2:
            señales.add(SEÑAL_HISTORIAL_CONSISTENTE)
        if "SIMILITUD_OCR_CALIBRADA" in codigos:
            señales.add(SEÑAL_ALIAS_CONOCIDO)
        candidatos.append(CandidatoConvergencia(
            valor_canonico=str(c.get("patente", "")),
            distancia_ocr=_distancia_edicion(valor_norm, normalizar_patente_vehiculo(str(c.get("patente", "")))),
            señales=frozenset(señales),
        ))
    return evaluar_convergencia(
        dominio="VEHICULO", valor_ocr=valor, candidatos=tuple(candidatos),
        metodo="CONVERGENCIA_VEHICULO", contradicciones_fuertes=tuple(contradicciones),
    )


def _cliente_confirmado_por_humano(cliente) -> bool:
    fuente = str(getattr(cliente, "fuente", "") or "").upper()
    obs = str(getattr(cliente, "observacion", "") or "").upper()
    return (
        "CONFIRMA" in fuente or fuente == "INGRESO_MANUAL"
        or "CONFIRMAD" in obs or "CONFIRMO" in obs or "CONFIRMÓ" in obs
    )


def convergencia_cliente(
    *, nombre_documental: str, rut_documental: str, carpeta_catalogos: str | Path | None,
) -> ResultadoConvergencia:
    """¿La identidad canónica/única/confirmada del cliente absorbe la
    ausencia o una pequeña corrupción OCR del RUT? Si el documento trae un
    RUT VÁLIDO atribuible sin ambigüedad a OTRA empresa confirmada, eso es
    CONTRADICCION_FUERTE -- nunca se oculta ni se resuelve."""
    nombre = str(nombre_documental or "").strip()
    if not carpeta_catalogos or nombre in _AUSENTES:
        return ResultadoConvergencia(decision=MANTENER_REVISION, valor_ocr_original=nombre, metodo="CONVERGENCIA_CLIENTE")
    carpeta = Path(carpeta_catalogos)
    try:
        from atlas_core.catalogo_clientes import (
            CatalogoClientes, EstadoCalidadCliente, EstadoVigenciaCliente,
            normalizar_nombre_cliente, normalizar_rut_cliente,
        )
        from atlas_core.catalogos import resolver_nombre_cliente_difuso

        clientes = CatalogoClientes(carpeta / "clientes.json").listar()
    except (OSError, ValueError):
        return ResultadoConvergencia(decision=MANTENER_REVISION, valor_ocr_original=nombre, metodo="CONVERGENCIA_CLIENTE")

    confirmados = [
        c for c in clientes
        if c.estado_calidad == EstadoCalidadCliente.CONFIRMADO.value
        and c.estado_vigencia == EstadoVigenciaCliente.ACTIVO.value
    ]
    # Contradicción documental real: RUT válido -> otra empresa confirmada
    # cuyo nombre NO coincide con el documental.
    try:
        rut_norm = normalizar_rut_cliente(rut_documental)
    except ValueError:
        rut_norm = ""
    if rut_norm:
        por_rut = [c for c in confirmados if c.rut == rut_norm]
        if len(por_rut) == 1:
            otro = por_rut[0]
            claves = {normalizar_nombre_cliente(otro.razon_social), *(normalizar_nombre_cliente(a) for a in otro.aliases)}
            if normalizar_nombre_cliente(nombre) not in claves:
                return ResultadoConvergencia(
                    decision=CONTRADICCION_FUERTE, valor_ocr_original=nombre, metodo="CONVERGENCIA_CLIENTE",
                    contradiccion=(
                        f'El RUT documental {rut_documental} corresponde inequívocamente a '
                        f'"{otro.razon_social}", no a "{nombre}".'
                    ),
                )

    coincidencia = resolver_nombre_cliente_difuso(confirmados, nombre)
    if coincidencia.estado not in {"SIN_CAMBIO", "ALIAS", "COINCIDENCIA_SEGURA"}:
        return ResultadoConvergencia(decision=MANTENER_REVISION, valor_ocr_original=nombre, metodo="CONVERGENCIA_CLIENTE")
    canonico = next(
        (
            c for c in confirmados
            if _mismo_nombre_cliente(c.razon_social, coincidencia.valor_resultado)
            or _mismo_nombre_cliente(c.razon_social, nombre)
            or any(_mismo_nombre_cliente(a, coincidencia.valor_resultado) for a in c.aliases)
        ),
        None,
    )
    if canonico is None:
        return ResultadoConvergencia(decision=MANTENER_REVISION, valor_ocr_original=nombre, metodo="CONVERGENCIA_CLIENTE")

    exacto = coincidencia.estado in {"SIN_CAMBIO", "ALIAS"}
    distancia = 0 if exacto else _distancia_token_unico(
        normalizar_nombre_cliente(nombre), normalizar_nombre_cliente(canonico.razon_social),
    )
    señales: set[str] = {SEÑAL_CATALOGO_CANONICO}
    if coincidencia.estado == "ALIAS":
        señales.add(SEÑAL_ALIAS_CONOCIDO)
    if _cliente_confirmado_por_humano(canonico):
        señales.add(SEÑAL_CONFIRMACION_HUMANA)
    if canonico.rut:
        señales.add(SEÑAL_RUT_COINCIDE) if rut_norm == canonico.rut else None
    candidato = CandidatoConvergencia(
        valor_canonico=canonico.razon_social,
        distancia_ocr=None if exacto else distancia,
        señales=frozenset(señales),
    )
    return evaluar_convergencia(
        dominio="CLIENTE", valor_ocr=nombre, candidatos=(candidato,), metodo="CONVERGENCIA_CLIENTE",
        exigir_diferencia=False,
    )


def convergencia_obra(
    *, nombre_documental: str, cliente_documental: str, rut_cliente_documental: str,
    despachar_a_documental: str, carpeta_catalogos: str | Path | None,
) -> ResultadoConvergencia:
    """¿Cliente correcto (por RUT canónico) + destino confirmado que calza
    con la dirección de entrega documental convergen en UNA única obra
    conocida, de modo que una variante OCR del nombre no la vuelve
    "desconocida"? Sólo entra en juego bajo esa conjunción (nunca por el
    nombre solo); expone TODAS las obras confirmadas del cliente dentro
    de una variación de nombre pequeña como candidatos -- si hay dos
    igualmente plausibles, `evaluar_convergencia` mantiene la revisión."""
    nombre = str(nombre_documental or "").strip()
    fallo = ResultadoConvergencia(decision=MANTENER_REVISION, valor_ocr_original=nombre, metodo="CONVERGENCIA_OBRA")
    if not carpeta_catalogos or nombre in _AUSENTES:
        return fallo
    carpeta = Path(carpeta_catalogos)
    despachar_a = str(despachar_a_documental or "").strip()
    if not despachar_a:
        return fallo
    try:
        from atlas_core.catalogo_obras_destinos import (
            CatalogoObrasDestinos, EstadoObra, EstadoVigencia, normalizar_nombre_obra,
        )
        from atlas_core.decisiones_pendientes import _identidad_cliente_por_rut

        cliente = _identidad_cliente_por_rut(carpeta, rut_cliente_documental)
        if cliente is None:  # sin cliente canónico por RUT no hay conjunción posible
            return fallo
        catalogo = CatalogoObrasDestinos(
            ruta=carpeta / "obras_destinos.json", ruta_clientes=carpeta / "clientes.json",
            ruta_destinos=carpeta / "destinos_maestros.json",
        )
        obras = [
            o for o in catalogo.listar_obras()
            if o.cliente_id == cliente.cliente_id
            and o.estado == EstadoObra.CONFIRMADA.value
            and o.estado_vigencia == EstadoVigencia.ACTIVO.value
        ]
    except (OSError, ValueError):
        return fallo

    n_ocr = normalizar_nombre_obra(nombre)
    candidatos: list[CandidatoConvergencia] = []
    for obra in obras:
        claves = [obra.nombre_canonico, *obra.aliases_documentales]
        distancias = [
            d for d in (_distancia_token_unico(n_ocr, normalizar_nombre_obra(k)) for k in claves)
            if d is not None
        ]
        exacto = any(n_ocr == normalizar_nombre_obra(k) for k in claves)
        if not exacto and not distancias:
            continue  # ninguna clave es una "variación pequeña" del OCR
        try:
            destinos = catalogo.listar_destinos_confirmados_para_obra(nombre_obra=obra.nombre_canonico)
        except (OSError, ValueError):
            destinos = []
        destino_ok = any(
            _direccion_coincide(str(getattr(d, "direccion", "") or ""), despachar_a) for d in destinos
        )
        if not destino_ok:
            continue  # sin destino confirmado que calce, no hay conjunción
        señales = {
            SEÑAL_CATALOGO_CANONICO, SEÑAL_RELACION_CLIENTE_OBRA,
            SEÑAL_RELACION_OBRA_DESTINO, SEÑAL_DIRECCION_COMUNA_COINCIDE,
        }
        candidatos.append(CandidatoConvergencia(
            valor_canonico=obra.nombre_canonico,
            distancia_ocr=None if exacto else min(distancias),
            señales=frozenset(señales),
        ))
    return evaluar_convergencia(
        dominio="OBRA", valor_ocr=nombre, candidatos=tuple(candidatos), metodo="CONVERGENCIA_OBRA",
    )
