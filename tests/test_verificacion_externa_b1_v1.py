"""Bloque VERIFICACIÓN EXTERNA B1 V1 -- evidencia externa controlada
para obra/destino.

`VERIFICACION_EXTERNA` (búsqueda web real, Perplexity Sonar vía
OpenRouter -- ver `atlas_core.atlas_ia.buscador_web`/`herramientas.py`)
ya estaba implementada, credenciada y registrada en el diccionario de
herramientas del orquestador (`_herramientas_b1_disponibles`), pero
ningún `TipoProblemaIA` la listaba en `herramientas` -- el orquestador
exige `nombre in contexto.herramientas_disponibles` antes de dejar
usarla aunque exista (ver `orquestador.py`). Sin esa conexión, B1 nunca
podía pedirla para OBRA_DESTINO_SIN_CORROBORAR (caso real: guía 472593).
Se conecta sólo para ese dominio (mínimo necesario).

Sin red real: `_evidencia_externa`/`_BuscadorFake` reemplazan la
llamada HTTP (mismo patrón que `test_atlas_ia_orquestador_b1.py`), y
los proveedores son fakes deterministas -- nunca se paga ni se depende
de una respuesta real de un LLM para que estos tests pasen siempre
igual. El único caso con red real (deliberado, único, documentado) es
la validación manual en shadow de 472593 -- fuera de esta suite."""
from __future__ import annotations

from atlas_core.atlas_ia.contratos import (
    ContextoRazonamiento,
    EvidenciaIA,
    HipotesisIA,
    RESULTADO_HIPOTESIS_ABSTENCION,
    RESULTADO_HIPOTESIS_PROPUESTA,
    RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA,
    calcular_hipotesis_id,
)
from atlas_core.atlas_ia.buscador_web import BuscadorWebNoDisponible, Cita, RespuestaBusquedaWeb
from atlas_core.atlas_ia.herramientas import herramienta_verificacion_externa
from atlas_core.atlas_ia.orquestador import (
    ABSTENCION_IA,
    BLOQUEADO_POR_VALIDACION,
    CLASIFICACION_A,
    CLASIFICACION_B,
    CLASIFICACION_C,
    REQUIERE_HERRAMIENTA,
    RESUELTO_POR_IA,
    OrquestadorAtlasIA,
)
from atlas_core.atlas_ia.registro_problemas import _ENTRADAS


# ---------------------------------------------------------------------
# 0. la conexión en sí: OBRA_DESTINO_SIN_CORROBORAR lista la herramienta
# ---------------------------------------------------------------------


def test_obra_destino_sin_corroborar_ahora_lista_verificacion_externa():
    entradas_obra = [e for e in _ENTRADAS if "OBRA_DESTINO_SIN_CORROBORAR" in e.codigos]
    assert entradas_obra, "debe existir la entrada de OBRA_DESTINO_SIN_CORROBORAR"
    assert "VERIFICACION_EXTERNA" in entradas_obra[0].herramientas
    # "DOCUMENTOS_RELACIONADOS" se retira de la lista de herramientas
    # INVOCABLES (nunca fue una de verdad -- ver comentario junto a la
    # entrada) -- la evidencia de documentos relacionados se sigue
    # recolectando igual, siempre, antes de llamar a B1.
    assert "DOCUMENTOS_RELACIONADOS" not in entradas_obra[0].herramientas
    assert entradas_obra[0].recopilar_evidencia is not None


# ---------------------------------------------------------------------
# Fakes reutilizables
# ---------------------------------------------------------------------


class _BuscadorFake:
    """Reemplaza `BuscadorWebOpenRouter`/`BuscadorWebConCache` -- sin
    red. `respuestas` es una cola (una por consulta esperada);
    `excepcion`, si se entrega, se lanza en la PRIMERA llamada."""

    def __init__(self, respuestas: list[RespuestaBusquedaWeb] | None = None, excepcion: Exception | None = None):
        self._respuestas = list(respuestas or [])
        self._excepcion = excepcion
        self.consultas: list[str] = []

    def buscar(self, consulta: str) -> RespuestaBusquedaWeb:
        self.consultas.append(consulta)
        if self._excepcion is not None:
            raise self._excepcion
        return self._respuestas.pop(0)


def _respuesta_web(texto: str, *, citas: int = 2) -> RespuestaBusquedaWeb:
    return RespuestaBusquedaWeb(
        consulta="c", respuesta_texto=texto,
        citas=tuple(Cita(f"Fuente {i}", f"https://ejemplo.test/{i}") for i in range(citas)),
        proveedor="openrouter_sonar", modelo="perplexity/sonar", fecha="2026-08-27T00:00:00+00:00",
    )


def _contexto(**cambios: object) -> ContextoRazonamiento:
    datos: dict[str, object] = {
        "campo": "obra_destino", "valor_documental": "EMPRESA EJEMPLO CONSTRUCTORA",
        "rut_chofer": "10190440-7", "numero_guia": "900001", "numero_transporte": "0000900000",
        "evidencias": (), "resultado_motor": "REQUIERE_REVISION",
        "explicacion_motor": "OBRA_DESTINO_SIN_CORROBORAR",
        "identidad_operacional": {"obra_destino": "EMPRESA EJEMPLO CONSTRUCTORA", "cliente": "CLIENTE EJEMPLO SPA"},
        # Mismo contrato real que arma `_ejecutar_ia_operacional` para
        # OBRA_DESTINO_SIN_CORROBORAR (ver registro_problemas.py) --
        # "DOCUMENTOS_RELACIONADOS" nunca es una herramienta invocable,
        # sólo un recolector previo (ver Sección 0 de este bloque).
        "herramientas_disponibles": ("VERIFICACION_EXTERNA",),
        "restricciones_dominio": ("NO_INVENTAR_DATOS", "NO_ESCRIBIR_CATALOGOS", "MAXIMO_RONDAS_B1"),
    }
    datos.update(cambios)
    return ContextoRazonamiento(**datos)


def _hipotesis(contexto, resultado, *, valor="", herramienta="", evidencia_usada=(), evidencia_en_contra=()):
    return HipotesisIA(
        hipotesis_id=calcular_hipotesis_id(contexto, valor), campo=contexto.campo,
        valor_observado=contexto.valor_documental, valor_propuesto=valor, resultado=resultado,
        herramienta_faltante=herramienta, evidencia_usada=evidencia_usada, evidencia_en_contra=evidencia_en_contra,
    )


# ---------------------------------------------------------------------
# 1. sin necesidad de herramienta -> 0 llamadas externas
# ---------------------------------------------------------------------


def test_1_sin_necesidad_de_herramienta_cero_llamadas_externas():
    """Ya hay evidencia interna suficiente (documento hermano real) --
    B1 nunca necesita pedir VERIFICACION_EXTERNA."""
    buscador = _BuscadorFake()
    herramienta = herramienta_verificacion_externa(buscador)

    class _ProveedorDirecto:
        def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:
            return _hipotesis(contexto, RESULTADO_HIPOTESIS_PROPUESTA, valor="EMPRESA EJEMPLO CONSTRUCTORA")

    contexto = _contexto(evidencias=(
        EvidenciaIA(
            identificador="documento:900002", campo="obra_destino", valor="EMPRESA EJEMPLO CONSTRUCTORA",
            tipo_fuente="HISTORICO", nivel="DOCUMENTO_RELACIONADO", independencia=1,
        ),
    ))
    resultado = OrquestadorAtlasIA(
        proveedor=_ProveedorDirecto(), herramientas={"VERIFICACION_EXTERNA": herramienta},
    ).resolver(contexto)

    assert resultado.estado == RESUELTO_POR_IA
    assert buscador.consultas == []  # nunca se llamó a la búsqueda externa


# ---------------------------------------------------------------------
# 2. REQUIERE_HERRAMIENTA -> la herramienta se ejecuta de verdad
# ---------------------------------------------------------------------


def test_2_requiere_herramienta_ejecuta_verificacion_externa():
    buscador = _BuscadorFake([_respuesta_web("La dirección corresponde a Empresa Ejemplo Constructora, Ñuñoa.")])
    herramienta = herramienta_verificacion_externa(buscador)

    class _ProveedorSecuencial:
        def __init__(self):
            self.ronda = 0

        def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:
            self.ronda += 1
            if self.ronda == 1:
                return _hipotesis(contexto, RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA, herramienta="VERIFICACION_EXTERNA")
            return _hipotesis(contexto, RESULTADO_HIPOTESIS_ABSTENCION)

    proveedor = _ProveedorSecuencial()
    resultado = OrquestadorAtlasIA(
        proveedor=proveedor, herramientas={"VERIFICACION_EXTERNA": herramienta},
    ).resolver(_contexto(identidad_operacional={"obra_destino": "EMPRESA EJEMPLO CONSTRUCTORA", "cliente": ""}))

    assert resultado.rondas == 2
    assert resultado.herramientas_usadas == ("VERIFICACION_EXTERNA",)
    assert len(buscador.consultas) >= 1  # la herramienta ejecutó al menos una búsqueda real
    assert len(resultado.contexto_final.evidencias) == 1
    evidencia = resultado.contexto_final.evidencias[0]
    assert evidencia.tipo_fuente == "EXTERNO"
    assert evidencia.nivel == "EXTERNO_WEB"


def test_2b_trazabilidad_conserva_fuente_consulta_url_y_fecha():
    """Sección 5 del bloque: toda evidencia externa usada debe conservar
    fuente/proveedor, consulta, fragmento estructurado, URL/referencia y
    fecha/hora de la consulta."""
    buscador = _BuscadorFake([_respuesta_web("Confirmado: dirección real en Ñuñoa.", citas=2)])
    herramienta = herramienta_verificacion_externa(buscador)

    contexto = _contexto(
        identidad_operacional={"obra_destino": "EMPRESA EJEMPLO CONSTRUCTORA", "cliente": ""},
    )
    evidencias = herramienta.consultar(contexto)

    assert len(evidencias) == 1
    evidencia = evidencias[0]
    assert evidencia.tipo_fuente == "EXTERNO"  # fuente/proveedor (tipo)
    assert evidencia.valor == "Confirmado: dirección real en Ñuñoa."  # fragmento estructurado
    assert evidencia.independencia == 2  # cuántas citas independientes la respaldan
    assert any("https://ejemplo.test/" in u for u in evidencia.referencias_fuente)  # URL/referencia
    assert any(r.startswith("consultado_en=") for r in evidencia.referencias_fuente)  # fecha/hora de la consulta


# ---------------------------------------------------------------------
# 3. evidencia externa fuerte y coherente -> corroboración válida
#    (pero SIEMPRE clase B, nunca A -- ver 0/comentario del bloque)
# ---------------------------------------------------------------------


def test_3_evidencia_externa_fuerte_corrobora_pero_nunca_autonomia_a():
    """Evidencia EXTERNO_WEB con varias citas independientes, coherente
    con el valor documental -- el validador la acepta (VÁLIDA), pero la
    clasificación se limita a B_ASISTENCIA: `_clasificar_propuesta` sólo
    otorga A a nivel CONFIRMACION_HUMANA/EXTERNO_OFICIAL, nunca a
    EXTERNO_WEB (búsqueda genérica) -- "una sola coincidencia [o varias]
    en Internet no basta" para autonomía plena, por diseño."""
    evidencia_externa = EvidenciaIA(
        identificador="externo:abc123", campo="obra_destino", valor="EMPRESA EJEMPLO CONSTRUCTORA",
        tipo_fuente="EXTERNO", nivel="EXTERNO_WEB", independencia=3,
        referencias_fuente=("Fuente 1 <https://ejemplo.test/1>", "Fuente 2 <https://ejemplo.test/2>"),
    )

    class _ProveedorConfirma:
        def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:
            return _hipotesis(
                contexto, RESULTADO_HIPOTESIS_PROPUESTA, valor="EMPRESA EJEMPLO CONSTRUCTORA",
                evidencia_usada=("externo:abc123",),
            )

    resultado = OrquestadorAtlasIA(proveedor=_ProveedorConfirma()).resolver(
        _contexto(evidencias=(evidencia_externa,))
    )
    assert resultado.estado == RESUELTO_POR_IA
    assert resultado.validacion and resultado.validacion.aceptada
    assert resultado.clasificacion == CLASIFICACION_B  # nunca CLASIFICACION_A


# ---------------------------------------------------------------------
# 4. coincidencia sólo nominal -> no corrobora
# ---------------------------------------------------------------------


def test_4_coincidencia_solo_nominal_no_corrobora():
    """El buscador confirma que 'EMPRESA EJEMPLO' existe (nombre), pero
    la evidencia no dice nada de la dirección/relación con el cliente --
    B1 correcto se abstiene en vez de proponer con una sola coincidencia
    de nombre (Sección 2 del bloque)."""
    evidencia_debil = EvidenciaIA(
        identificador="externo:solo-nombre", campo="obra_destino",
        valor="Existe una empresa llamada Empresa Ejemplo en Chile, sin más detalles de dirección u obra.",
        tipo_fuente="EXTERNO", nivel="EXTERNO_WEB", independencia=1,
    )

    class _ProveedorCauteloso:
        def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:
            # Comportamiento correcto esperado de B1: una coincidencia de
            # nombre aislada, sin dirección/obra confirmada, no basta.
            return _hipotesis(contexto, RESULTADO_HIPOTESIS_ABSTENCION)

    resultado = OrquestadorAtlasIA(proveedor=_ProveedorCauteloso()).resolver(
        _contexto(evidencias=(evidencia_debil,))
    )
    assert resultado.estado == ABSTENCION_IA
    assert resultado.clasificacion == CLASIFICACION_C


def test_4b_si_b1_de_todos_modos_propone_un_valor_no_respaldado_el_validador_lo_bloquea():
    """Red de seguridad: aunque B1 propusiera igual un valor a partir de
    sólo una coincidencia nominal, el validador determinista lo bloquea
    -- nunca depende sólo del buen juicio del LLM."""
    evidencia_debil = EvidenciaIA(
        identificador="externo:solo-nombre", campo="obra_destino",
        valor="Existe una empresa llamada Empresa Ejemplo, sin dirección confirmada.",
        tipo_fuente="EXTERNO", nivel="EXTERNO_WEB", independencia=1,
    )

    class _ProveedorSobreconfiado:
        def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:
            return _hipotesis(contexto, RESULTADO_HIPOTESIS_PROPUESTA, valor="EMPRESA EJEMPLO CONSTRUCTORA")

    resultado = OrquestadorAtlasIA(proveedor=_ProveedorSobreconfiado()).resolver(
        _contexto(evidencias=(evidencia_debil,))
    )
    assert resultado.estado == BLOQUEADO_POR_VALIDACION
    assert resultado.validacion.motivo_rechazo == "VALOR_NO_RESPALDADO_POR_EVIDENCIA"


# ---------------------------------------------------------------------
# 5. dos candidatos plausibles -> ambiguo
# ---------------------------------------------------------------------


def test_5_dos_candidatos_externos_plausibles_es_ambiguo():
    evidencias = (
        EvidenciaIA(
            identificador="externo:candidato-1", campo="obra_destino", valor="EMPRESA EJEMPLO CONSTRUCTORA SUCURSAL A",
            tipo_fuente="EXTERNO", nivel="EXTERNO_WEB", independencia=1,
        ),
        EvidenciaIA(
            identificador="externo:candidato-2", campo="obra_destino", valor="EMPRESA EJEMPLO CONSTRUCTORA SUCURSAL B",
            tipo_fuente="EXTERNO", nivel="EXTERNO_WEB", independencia=1,
        ),
    )

    class _ProveedorAnteAmbiguedad:
        def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:
            # Con dos candidatos igualmente plausibles y sin forma de
            # desempatar, la respuesta correcta es abstenerse -- nunca
            # elegir uno a ciegas.
            return _hipotesis(contexto, RESULTADO_HIPOTESIS_ABSTENCION)

    resultado = OrquestadorAtlasIA(proveedor=_ProveedorAnteAmbiguedad()).resolver(
        _contexto(evidencias=evidencias)
    )
    assert resultado.estado == ABSTENCION_IA
    assert resultado.clasificacion == CLASIFICACION_C


# ---------------------------------------------------------------------
# 6. fuente débil única -> no corrobora
# ---------------------------------------------------------------------


def test_6_fuente_debil_unica_sin_citas_no_corrobora():
    evidencia_sin_citas = EvidenciaIA(
        identificador="externo:sin-citas", campo="obra_destino",
        valor="Posible mención de la empresa, sin fuente verificable clara.",
        tipo_fuente="EXTERNO", nivel="EXTERNO_WEB", independencia=0,  # 0 citas -- fuente débil
    )

    class _ProveedorConCautela:
        def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:
            return _hipotesis(contexto, RESULTADO_HIPOTESIS_ABSTENCION)

    resultado = OrquestadorAtlasIA(proveedor=_ProveedorConCautela()).resolver(
        _contexto(evidencias=(evidencia_sin_citas,))
    )
    assert resultado.estado == ABSTENCION_IA


# ---------------------------------------------------------------------
# 7. contradicción entre dirección y nombre -> no aplicar
# ---------------------------------------------------------------------


def test_7_contradiccion_direccion_nombre_no_aplica():
    """La evidencia externa trae `en_contra` (la dirección buscada NO
    corresponde a la empresa documental) -- incluso si B1 la usara como
    'evidencia_usada' con un valor que técnicamente calza, el conflicto
    declarado no debe traducirse en autonomía; el resultado correcto es
    abstenerse."""
    evidencia_contradictoria = EvidenciaIA(
        identificador="externo:contradice", campo="obra_destino", valor="EMPRESA EJEMPLO CONSTRUCTORA",
        tipo_fuente="EXTERNO", nivel="EXTERNO_WEB", independencia=1,
        en_contra=("DIRECCION_NO_COINCIDE",),
    )

    class _ProveedorQueRespetaContradiccion:
        def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:
            hay_contradiccion = any(e.en_contra for e in contexto.evidencias)
            if hay_contradiccion:
                return _hipotesis(contexto, RESULTADO_HIPOTESIS_ABSTENCION)
            return _hipotesis(contexto, RESULTADO_HIPOTESIS_PROPUESTA, valor="EMPRESA EJEMPLO CONSTRUCTORA")

    resultado = OrquestadorAtlasIA(proveedor=_ProveedorQueRespetaContradiccion()).resolver(
        _contexto(evidencias=(evidencia_contradictoria,))
    )
    assert resultado.estado == ABSTENCION_IA


# ---------------------------------------------------------------------
# 8. error de red/proveedor -> degradación segura
# ---------------------------------------------------------------------


def test_8_error_de_red_en_busqueda_externa_degrada_seguro():
    """La búsqueda externa falla (sin red/HTTP) -- `herramienta_
    verificacion_externa` nunca deja pasar la excepción (la captura y
    devuelve evidencia vacía), y el orquestador se detiene sin producir
    ninguna evidencia inventada ni reventar el procesamiento."""
    buscador = _BuscadorFake(excepcion=BuscadorWebNoDisponible("Sin conexión para la búsqueda web."))
    herramienta = herramienta_verificacion_externa(buscador)

    class _ProveedorInsiste:
        def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:
            return _hipotesis(contexto, RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA, herramienta="VERIFICACION_EXTERNA")

    resultado = OrquestadorAtlasIA(
        proveedor=_ProveedorInsiste(), herramientas={"VERIFICACION_EXTERNA": herramienta},
    ).resolver(_contexto())

    assert resultado.estado == REQUIERE_HERRAMIENTA
    assert resultado.clasificacion == CLASIFICACION_C
    assert resultado.contexto_final.evidencias == ()  # nunca se inventó evidencia por el fallo


# ---------------------------------------------------------------------
# 9. fixture universal -- otro rubro, sin PRODALAM/SIGRO/AZA
# ---------------------------------------------------------------------


def test_9_fixture_universal_otro_rubro_mismo_pipeline():
    """Alimentos, no construcción -- mismo pipeline, ninguna regla
    hardcodeada al caso 472593."""
    buscador = _BuscadorFake([_respuesta_web(
        "Planta Nutrialimentos del Maule SA, ubicada en Camino Longitudinal Sur km 12, Talca, Región del Maule."
    )])
    herramienta = herramienta_verificacion_externa(buscador)

    class _ProveedorSecuencial:
        def __init__(self):
            self.ronda = 0

        def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:
            self.ronda += 1
            if self.ronda == 1:
                return _hipotesis(contexto, RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA, herramienta="VERIFICACION_EXTERNA")
            return _hipotesis(contexto, RESULTADO_HIPOTESIS_ABSTENCION)

    contexto = _contexto(
        valor_documental="NUTRIALIMENTOS DEL MAULE SA",
        identidad_operacional={"obra_destino": "NUTRIALIMENTOS DEL MAULE SA", "cliente": "DISTRIBUIDORA VALLE VERDE SPA"},
        numero_guia="900101", numero_transporte="0000900100",
    )
    resultado = OrquestadorAtlasIA(
        proveedor=_ProveedorSecuencial(), herramientas={"VERIFICACION_EXTERNA": herramienta},
    ).resolver(contexto)

    assert resultado.rondas == 2
    assert resultado.herramientas_usadas == ("VERIFICACION_EXTERNA",)
    assert len(resultado.contexto_final.evidencias) == 1
    consulta_enviada = buscador.consultas[0]
    assert "NUTRIALIMENTOS DEL MAULE SA" in consulta_enviada
    # Nunca aparece nada del caso 472593 en este flujo.
    assert "SIGRO" not in consulta_enviada and "PRODALAM" not in consulta_enviada
