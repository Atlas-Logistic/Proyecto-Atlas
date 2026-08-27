"""Bloque PROYECTO ATLAS -- OBRA/DESTINO V2: identidad operacional
EMPRESA <-> OBRA <-> DESTINO OPERACIONAL <-> DIRECCIÓN DE ENTREGA <->
DIRECCIÓN CORPORATIVA.

Causa raíz real (caso 472593, OBRA_DESTINO_SIN_CORROBORAR): la
herramienta VERIFICACION_EXTERNA (conectada en el bloque anterior)
recibía `contexto.valor_documental` = "EMPRESA CONST SIGRO" -- un
NOMBRE de empresa/obra, nunca una dirección -- y `_construir_consultas_
investigacion` preguntaba, literalmente, "¿es 'EMPRESA CONST SIGRO' una
dirección real?". Esa pregunta no tiene sentido: sólo podía traer la
SEDE CORPORATIVA general de la empresa (identidad), nunca evidencia de
una obra/proyecto/entrega puntual. Además, `identidad_operacional`
nunca incluía la dirección de entrega documental
(`despachar_a_crudo`/`direccion_entrega`) -- sin ella, no había forma
de preguntar por la RELACIÓN entre el nombre y esa dirección. El
modelo de catálogos (`atlas_core.catalogo_destinos.Destino`, con
`cliente_id` + `direccion` PROPIA, distinta de la sede del cliente) ya
distinguía empresa de obra/destino correctamente -- el bug vivía
enteramente en la capa de razonamiento B1/verificación externa, no en
el modelo de datos.

Confirmado con la llamada real: la primera ejecución en shadow de
472593 (bloque anterior) preguntó por "EMPRESA CONST SIGRO" como si
fuera una dirección y por "PRODALAM SA" como cliente -- ambas
respuestas trajeron sólo domicilios corporativos genéricos (sede de
SIGRO, sede de PRODALAM), nunca nada sobre Avda Irarrázaval 5497 -- y
B1, razonablemente dado ESE contexto mal formado, concluyó una
"contradicción" que en realidad comparaba dos sedes corporativas entre
sí, ninguna de las dos con la dirección de entrega real del documento."""
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
from atlas_core.atlas_ia.herramientas import _construir_consultas_investigacion, herramienta_verificacion_externa
from atlas_core.atlas_ia.orquestador import (
    ABSTENCION_IA,
    CLASIFICACION_B,
    CLASIFICACION_C,
    REQUIERE_HERRAMIENTA,
    RESUELTO_POR_IA,
    OrquestadorAtlasIA,
)
from atlas_core.atlas_ia.registro_problemas import recopilar_evidencia_documentos_relacionados


# ---------------------------------------------------------------------
# Fakes reutilizables (mismo patrón que test_verificacion_externa_b1_v1.py)
# ---------------------------------------------------------------------


class _BuscadorFake:
    def __init__(self, respuestas=None, excepcion=None):
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


def _contexto(**cambios):
    datos = {
        "campo": "obra_destino", "valor_documental": "EMPRESA EJEMPLO CONSTRUCTORA",
        "rut_chofer": "10190440-7", "numero_guia": "900001", "numero_transporte": "0000900000",
        "evidencias": (), "resultado_motor": "REQUIERE_REVISION",
        "explicacion_motor": "OBRA_DESTINO_SIN_CORROBORAR",
        "identidad_operacional": {
            "obra_destino": "EMPRESA EJEMPLO CONSTRUCTORA", "cliente": "CLIENTE EJEMPLO SPA",
            "direccion_entrega": "CALLE FICTICIA 123 SANTIAGO NUNOA",
        },
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
# 0. la construcción de la consulta ya no confunde nombre con dirección
# ---------------------------------------------------------------------


def test_0a_campo_direccion_conserva_la_pregunta_original():
    """`despachar_a_crudo`/`direccion_entrega` SÍ son direcciones -- la
    pregunta "¿es una dirección real?" sigue siendo correcta ahí, sin
    cambios de comportamiento."""
    contexto = _contexto(
        campo="despachar_a_crudo", valor_documental="CALLE FICTICIA 123 SANTIAGO NUNOA",
        identidad_operacional={"obra_destino": "EMPRESA EJEMPLO CONSTRUCTORA", "cliente": "CLIENTE EJEMPLO SPA"},
    )
    consultas = _construir_consultas_investigacion(contexto)
    assert consultas
    assert "es una dirección real" in consultas[0]
    assert "CALLE FICTICIA 123 SANTIAGO NUNOA" in consultas[0]


def test_0b_campo_nombre_pregunta_por_la_relacion_no_por_si_es_direccion():
    """Caso real 472593: `obra_destino` es un NOMBRE -- la pregunta debe
    ser sobre la relación empresa/obra <-> dirección de entrega YA
    conocida, nunca "¿es [nombre] una dirección real?"."""
    contexto = _contexto(
        campo="obra_destino", valor_documental="EMPRESA EJEMPLO CONSTRUCTORA",
        identidad_operacional={"cliente": "", "direccion_entrega": "CALLE FICTICIA 123 SANTIAGO NUNOA"},
    )
    consultas = _construir_consultas_investigacion(contexto)
    assert consultas
    consulta = consultas[0]
    assert "¿es" not in consulta or "una dirección real" not in consulta  # nunca la pregunta vieja
    assert "EMPRESA EJEMPLO CONSTRUCTORA" in consulta
    assert "CALLE FICTICIA 123 SANTIAGO NUNOA" in consulta
    assert "relacionad" in consulta.lower()  # pregunta explícitamente por la relación


def test_0c_campo_nombre_sin_direccion_usa_cliente_como_relacion():
    contexto = _contexto(
        campo="obra_destino", valor_documental="EMPRESA EJEMPLO CONSTRUCTORA",
        identidad_operacional={"cliente": "CLIENTE EJEMPLO SPA", "direccion_entrega": ""},
    )
    consultas = _construir_consultas_investigacion(contexto)
    assert consultas
    assert "EMPRESA EJEMPLO CONSTRUCTORA" in consultas[0]
    assert "CLIENTE EJEMPLO SPA" in consultas[0]


def test_0d_campo_nombre_sin_nada_usa_identidad_general_como_ultimo_recurso():
    contexto = _contexto(
        campo="obra_destino", valor_documental="EMPRESA EJEMPLO CONSTRUCTORA",
        identidad_operacional={"cliente": "", "direccion_entrega": ""},
    )
    consultas = _construir_consultas_investigacion(contexto)
    assert consultas
    assert "EMPRESA EJEMPLO CONSTRUCTORA" in consultas[0]


# ---------------------------------------------------------------------
# 1. dirección corporativa != dirección de obra -> NO contradicción
# ---------------------------------------------------------------------


def test_1_sede_corporativa_distinta_de_direccion_documental_no_es_contradiccion():
    evidencia_sede = EvidenciaIA(
        identificador="externo:sede", campo="obra_destino",
        valor="La sede corporativa de Empresa Ejemplo Constructora está en Avenida Providencia 1000, Santiago.",
        tipo_fuente="EXTERNO", nivel="EXTERNO_WEB", independencia=3,
    )

    class _ProveedorQueDistingueRoles:
        def razonar(self, contexto):
            # Comportamiento correcto (política v3, regla 15): la sede
            # corporativa NO contradice la dirección de entrega -- son
            # datos de rol distinto. Sin evidencia de OBRA puntual, se
            # abstiene (no "confirma" ni "contradice").
            return _hipotesis(contexto, RESULTADO_HIPOTESIS_ABSTENCION)

    resultado = OrquestadorAtlasIA(proveedor=_ProveedorQueDistingueRoles()).resolver(
        _contexto(evidencias=(evidencia_sede,))
    )
    assert resultado.estado == ABSTENCION_IA  # nunca BLOQUEADO_POR_VALIDACION/"contradicción"
    assert resultado.hipotesis.evidencia_en_contra == ()  # la sede no se registró como evidencia EN CONTRA


# ---------------------------------------------------------------------
# 2. dos direcciones de OBRA incompatibles, misma entidad/período -> ambiguo
# ---------------------------------------------------------------------


def test_2_dos_direcciones_de_obra_para_la_misma_entidad_es_ambiguo():
    evidencias = (
        EvidenciaIA(
            identificador="externo:obra-1", campo="obra_destino",
            valor="Empresa Ejemplo Constructora tiene una obra activa en Calle Norte 200, Santiago.",
            tipo_fuente="EXTERNO", nivel="EXTERNO_WEB", independencia=1,
        ),
        EvidenciaIA(
            identificador="externo:obra-2", campo="obra_destino",
            valor="Empresa Ejemplo Constructora tiene una obra activa en Calle Sur 900, Santiago.",
            tipo_fuente="EXTERNO", nivel="EXTERNO_WEB", independencia=1,
        ),
    )

    class _ProveedorAnteAmbiguedadDeObra:
        def razonar(self, contexto):
            return _hipotesis(contexto, RESULTADO_HIPOTESIS_ABSTENCION)

    resultado = OrquestadorAtlasIA(proveedor=_ProveedorAnteAmbiguedadDeObra()).resolver(
        _contexto(evidencias=evidencias)
    )
    assert resultado.estado == ABSTENCION_IA
    assert resultado.clasificacion == CLASIFICACION_C


# ---------------------------------------------------------------------
# 3. empresa con múltiples obras -> permitido (no es un error por sí solo)
# ---------------------------------------------------------------------


def test_3_empresa_con_multiples_obras_conocidas_no_es_un_error():
    """Tener DOS obras conocidas de la misma empresa no rompe nada -- si
    una evidencia adicional (aquí, la propia dirección documental)
    coincide exactamente con UNA de ellas, esa sigue siendo
    corroborable (mismo criterio de test 4/7), la otra simplemente no
    aplica a este documento."""
    evidencia_obra_a = EvidenciaIA(
        identificador="externo:obra-norte", campo="obra_destino",
        valor="CALLE FICTICIA 123 SANTIAGO NUNOA",  # coincide EXACTO con la entrega documental
        tipo_fuente="EXTERNO", nivel="EXTERNO_WEB", independencia=2,
    )
    evidencia_obra_b = EvidenciaIA(
        identificador="externo:obra-sur", campo="obra_destino",
        valor="Empresa Ejemplo Constructora también tiene una obra en Rancagua, sin relación con este documento.",
        tipo_fuente="EXTERNO", nivel="EXTERNO_WEB", independencia=1,
    )

    class _ProveedorQueEligeLaObraRelevante:
        def razonar(self, contexto):
            return _hipotesis(
                contexto, RESULTADO_HIPOTESIS_PROPUESTA, valor="CALLE FICTICIA 123 SANTIAGO NUNOA",
                evidencia_usada=("externo:obra-norte",),
            )

    resultado = OrquestadorAtlasIA(proveedor=_ProveedorQueEligeLaObraRelevante()).resolver(
        _contexto(evidencias=(evidencia_obra_a, evidencia_obra_b))
    )
    assert resultado.estado == RESUELTO_POR_IA
    assert resultado.validacion.aceptada


# ---------------------------------------------------------------------
# 4. misma obra/dirección corroborada por evidencia fuerte -> relación válida
# ---------------------------------------------------------------------


def test_4_evidencia_de_obra_puntual_coincide_con_entrega_documental_corrobora():
    evidencia_obra = EvidenciaIA(
        identificador="externo:obra", campo="obra_destino", valor="CALLE FICTICIA 123 SANTIAGO NUNOA",
        tipo_fuente="EXTERNO", nivel="EXTERNO_WEB", independencia=4,
    )

    class _ProveedorConfirmaRelacion:
        def razonar(self, contexto):
            return _hipotesis(
                contexto, RESULTADO_HIPOTESIS_PROPUESTA, valor="CALLE FICTICIA 123 SANTIAGO NUNOA",
                evidencia_usada=("externo:obra",),
            )

    resultado = OrquestadorAtlasIA(proveedor=_ProveedorConfirmaRelacion()).resolver(
        _contexto(evidencias=(evidencia_obra,))
    )
    assert resultado.estado == RESUELTO_POR_IA
    assert resultado.validacion.aceptada
    assert resultado.clasificacion == CLASIFICACION_B  # sigue sin ser autonomía A (EXTERNO_WEB, ver bloque anterior)


# ---------------------------------------------------------------------
# 5. coincidencia sólo nominal -> insuficiente
# ---------------------------------------------------------------------


def test_5_coincidencia_nominal_sin_direccion_es_insuficiente():
    evidencia_solo_nombre = EvidenciaIA(
        identificador="externo:nombre", campo="obra_destino",
        valor="Existe una empresa constructora con ese nombre en Chile, sin más información pública.",
        tipo_fuente="EXTERNO", nivel="EXTERNO_WEB", independencia=1,
    )

    class _ProveedorCauteloso:
        def razonar(self, contexto):
            return _hipotesis(contexto, RESULTADO_HIPOTESIS_ABSTENCION)

    resultado = OrquestadorAtlasIA(proveedor=_ProveedorCauteloso()).resolver(
        _contexto(evidencias=(evidencia_solo_nombre,))
    )
    assert resultado.estado == ABSTENCION_IA


# ---------------------------------------------------------------------
# 6. sede corporativa encontrada, sin evidencia de obra -> SIN_EVIDENCIA
# ---------------------------------------------------------------------


def test_6_sede_corporativa_sin_evidencia_de_obra_es_sin_evidencia_no_contradiccion():
    """Igual que test 1, pero foco explícito en el estado conceptual:
    SIN_EVIDENCIA (abstención), nunca 'contradicción' ni bloqueo."""
    evidencia_sede = EvidenciaIA(
        identificador="externo:solo-sede", campo="obra_destino",
        valor="Empresa Ejemplo Constructora, casa matriz en Avenida Providencia 1000, Santiago.",
        tipo_fuente="EXTERNO", nivel="EXTERNO_WEB", independencia=5,
    )

    class _ProveedorHonesto:
        def razonar(self, contexto):
            return _hipotesis(contexto, RESULTADO_HIPOTESIS_ABSTENCION)

    resultado = OrquestadorAtlasIA(proveedor=_ProveedorHonesto()).resolver(
        _contexto(evidencias=(evidencia_sede,))
    )
    assert resultado.estado == ABSTENCION_IA
    assert resultado.estado != "BLOQUEADO_POR_VALIDACION"


# ---------------------------------------------------------------------
# 7. evidencia externa específica empresa<->obra<->dirección -> corroborable
#    (de punta a punta, con la herramienta real -- sin red)
# ---------------------------------------------------------------------


def test_7_verificacion_externa_end_to_end_pregunta_por_la_relacion_y_corrobora():
    buscador = _BuscadorFake([_respuesta_web(
        "Sí, Empresa Ejemplo Constructora tiene un proyecto/obra activo en Calle Ficticia 123, Ñuñoa."
    )])
    herramienta = herramienta_verificacion_externa(buscador)

    class _ProveedorSecuencial:
        def __init__(self):
            self.ronda = 0

        def razonar(self, contexto):
            self.ronda += 1
            if self.ronda == 1:
                return _hipotesis(contexto, RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA, herramienta="VERIFICACION_EXTERNA")
            return _hipotesis(
                contexto, RESULTADO_HIPOTESIS_PROPUESTA,
                valor=contexto.evidencias[0].valor, evidencia_usada=(contexto.evidencias[0].identificador,),
            )

    resultado = OrquestadorAtlasIA(
        proveedor=_ProveedorSecuencial(), herramientas={"VERIFICACION_EXTERNA": herramienta},
    ).resolver(_contexto())

    # La consulta real que salió preguntó por la RELACIÓN, no por "es
    # una dirección real" -- verificación end-to-end del fix.
    assert buscador.consultas
    assert "relacionad" in buscador.consultas[0].lower()
    assert "EMPRESA EJEMPLO CONSTRUCTORA" in buscador.consultas[0]
    assert "CALLE FICTICIA 123 SANTIAGO NUNOA" in buscador.consultas[0]
    assert resultado.estado == RESUELTO_POR_IA
    assert resultado.validacion.aceptada


# ---------------------------------------------------------------------
# 8. historial interno repetido, independiente -> evidencia reutilizable
# ---------------------------------------------------------------------


def test_8_historial_interno_repetido_e_independiente_es_evidencia_reutilizable():
    fila_actual = {
        "archivo": "mobile/actual/original.jpg", "numero_guia": "900201",
        "numero_transporte": "0000900200", "fecha": "25-08-2026", "chofer": "JUAN PEREZ",
        "patente_tracto": "BKYK63", "obra_destino": "EMPRESA EJEMPLO CONSTRUCTORA",
    }
    # Dos documentos HERMANOS reales (guías/transportes distintos, nunca
    # la fila propia) que ya trajeron el mismo obra_destino.
    hermano_1 = dict(fila_actual, archivo="mobile/h1/original.jpg", numero_guia="900101", numero_transporte="0000900100")
    hermano_2 = dict(fila_actual, archivo="mobile/h2/original.jpg", numero_guia="900301", numero_transporte="0000900300")

    recolector = recopilar_evidencia_documentos_relacionados("obra_destino")
    evidencias = recolector(fila_actual, [hermano_1, hermano_2])

    assert len(evidencias) == 2  # dos fuentes independientes reales, reutilizables como evidencia
    assert all(e.valor == "EMPRESA EJEMPLO CONSTRUCTORA" for e in evidencias)
    assert all(e.tipo_fuente == "HISTORICO" for e in evidencias)


# ---------------------------------------------------------------------
# 9. un documento nunca se corrobora consigo mismo (fix ya publicado)
# ---------------------------------------------------------------------


def test_9_documento_no_se_corrobora_a_si_mismo_para_obra_destino():
    fila_actual = {
        "archivo": "mobile/actual/original.jpg", "numero_guia": "900201",
        "numero_transporte": "0000900200", "fecha": "25-08-2026", "chofer": "JUAN PEREZ",
        "patente_tracto": "BKYK63", "obra_destino": "EMPRESA EJEMPLO CONSTRUCTORA",
    }
    fila_propia_anterior = dict(fila_actual)  # mismo numero_guia -- el propio historial de este documento
    recolector = recopilar_evidencia_documentos_relacionados("obra_destino")
    evidencias = recolector(fila_actual, [fila_propia_anterior])
    assert evidencias == ()


# ---------------------------------------------------------------------
# 10. fixture universal -- otro rubro, sin SIGRO/PRODALAM/AZA/construcción
# ---------------------------------------------------------------------


def test_10_fixture_universal_sucursal_distinta_de_casa_matriz():
    """Distribuidora de alimentos: la sucursal/local de entrega es
    DISTINTA de la casa matriz -- misma semántica que el caso real, otro
    rubro por completo."""
    buscador = _BuscadorFake([_respuesta_web(
        "Sí, Supermercados Valle Verde tiene un local/sucursal en Camino Real 450, San Bernardo -- "
        "distinto de su casa matriz en Providencia."
    )])
    herramienta = herramienta_verificacion_externa(buscador)

    class _ProveedorSecuencial:
        def __init__(self):
            self.ronda = 0

        def razonar(self, contexto):
            self.ronda += 1
            if self.ronda == 1:
                return _hipotesis(contexto, RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA, herramienta="VERIFICACION_EXTERNA")
            return _hipotesis(contexto, RESULTADO_HIPOTESIS_ABSTENCION)

    contexto = _contexto(
        valor_documental="SUPERMERCADOS VALLE VERDE",
        identidad_operacional={
            "obra_destino": "SUPERMERCADOS VALLE VERDE", "cliente": "DISTRIBUIDORA NORTE SPA",
            "direccion_entrega": "CAMINO REAL 450 SAN BERNARDO",
        },
        numero_guia="900401", numero_transporte="0000900400",
    )
    resultado = OrquestadorAtlasIA(
        proveedor=_ProveedorSecuencial(), herramientas={"VERIFICACION_EXTERNA": herramienta},
    ).resolver(contexto)

    assert resultado.herramientas_usadas == ("VERIFICACION_EXTERNA",)
    consulta = buscador.consultas[0]
    assert "SUPERMERCADOS VALLE VERDE" in consulta
    assert "CAMINO REAL 450 SAN BERNARDO" in consulta
    assert "SIGRO" not in consulta and "PRODALAM" not in consulta and "AZA" not in consulta


# ---------------------------------------------------------------------
# 11. error de herramienta -> degradación segura
# ---------------------------------------------------------------------


def test_11_error_de_red_en_verificacion_externa_degrada_seguro():
    buscador = _BuscadorFake(excepcion=BuscadorWebNoDisponible("Sin conexión."))
    herramienta = herramienta_verificacion_externa(buscador)

    class _ProveedorInsiste:
        def razonar(self, contexto):
            return _hipotesis(contexto, RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA, herramienta="VERIFICACION_EXTERNA")

    resultado = OrquestadorAtlasIA(
        proveedor=_ProveedorInsiste(), herramientas={"VERIFICACION_EXTERNA": herramienta},
    ).resolver(_contexto())

    assert resultado.estado == REQUIERE_HERRAMIENTA
    assert resultado.clasificacion == CLASIFICACION_C
    assert resultado.contexto_final.evidencias == ()
