"""Bloque PROYECTO ATLAS -- DESTINOS INTERNOS V1: CatalogoObrasDestinos +
historial/confirmaciones humanas como evidencia PRIORITARIA para B1,
antes de Internet.

Causa raíz real (caso 472593): la obra "EMPRESA CONST SIGRO" (para
PRODALAM SA) YA tenía DOS relaciones CONFIRMADAS por Javier hacia el
mismo lugar real (Avda Irarrázaval 5497, Ñuñoa) -- confirmadas en dos
guías históricas distintas (464550 y 472227), cada una contra un
`Destino` de texto ligeramente distinto (mismo patrón ya conocido y
resuelto para AUSIN SAN BERNARDO en `decisiones_pendientes.py`, Bloque
REGENERACIÓN B1). `_corroborar_obra_destino_confirmada` usaba
`resolver_obra_destino_confirmada`, que exige EXACTAMENTE una relación
confirmada -- ante DOS (evidencia REDUNDANTE, nunca una contradicción)
devolvía `None` como si Javier nunca hubiera confirmado nada, y
472593 escalaba a B1/Internet por algo ya confirmado dos veces.

Confirmado con los catálogos REALES (G:\\Mi unidad\\Atlas\\catalogos_
privados, sólo lectura, nunca modificados): con el fix,
`_corroborar_obra_destino_confirmada` para 472593 devuelve el destino
confirmado (antes: `None`) -- cero llamadas a Groq, cero llamadas a
Internet."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from atlas_core import procesamiento_masivo
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_destinos import CatalogoDestinos
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, TipoEvidencia
from atlas_core.atlas_ia.contratos import ContextoRazonamiento, HipotesisIA, RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA, RESULTADO_HIPOTESIS_ABSTENCION, calcular_hipotesis_id
from atlas_core.atlas_ia.herramientas import herramienta_verificacion_externa
from atlas_core.atlas_ia.orquestador import (
    ABSTENCION_IA,
    CLASIFICACION_C,
    OrquestadorAtlasIA,
    ResultadoOrquestacion,
    RESUELTO_POR_IA,
)
from atlas_core.atlas_ia.buscador_web import RespuestaBusquedaWeb, Cita
from atlas_core.atlas_ia.registro_problemas import (
    recopilar_evidencia_catalogo_obras_destinos,
    recopilar_evidencia_obra_destino,
)
from atlas_core.procesamiento_masivo import (
    _corroborar_obra_destino_confirmada,
    escalar_resultado_ia_en_memoria,
    procesar_archivo,
)


class Reloj:
    def __init__(self):
        self.actual = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self):
        valor = self.actual
        self.actual += timedelta(seconds=1)
        return valor


class Ids:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return f"id-{self.n}"


def _evidencia(identificador="guia-1", resultado="SOPORTA"):
    return Evidencia(
        tipo=TipoEvidencia.GUIA.value, identificador_fuente=identificador,
        referencia_hash="a" * 64, campos_observados={"obra": "OBRA GENERICA"},
        fecha="2026-01-01T00:00:00+00:00", actor_proceso="test", resultado=resultado,
    )


def _crear_cliente(tmp_path, *, razon_social="CLIENTE EJEMPLO SPA", rut="50.234.350-5"):
    carpeta = tmp_path / "catalogos"
    clientes = carpeta / "clientes.json"
    reloj, ids = Reloj(), Ids()
    cliente = CatalogoClientes(clientes, reloj=reloj, generador_id=ids).crear(
        razon_social=razon_social, rut=rut, fuente="PRUEBA", estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    return carpeta, clientes, cliente, reloj, ids


def _crear_destino(carpeta, clientes, cliente, reloj, ids, *, nombre, direccion, comuna="", region="", fuente="PRUEBA"):
    return CatalogoDestinos(
        carpeta / "destinos_maestros.json", ruta_clientes=clientes, reloj=reloj, generador_id=ids,
    ).crear(
        cliente_id=cliente.cliente_id, nombre_destino=nombre, direccion=direccion,
        comuna=comuna, region=region, pais="CHILE", fuente=fuente,
    )


def _obras_destinos(carpeta, clientes):
    return CatalogoObrasDestinos(
        carpeta / "obras_destinos.json", ruta_clientes=clientes, ruta_destinos=carpeta / "destinos_maestros.json",
    )


def _resolver(carpeta, *, cliente_texto, rut_cliente, obra, direccion=""):
    return _corroborar_obra_destino_confirmada(
        carpeta, cliente_texto=cliente_texto, rut_cliente=rut_cliente,
        obra_documental=obra, identidad_cliente_corroborada=True, direccion_documental=direccion,
    )


def _hipotesis(contexto, resultado, *, valor="", herramienta="", evidencia_usada=()):
    return HipotesisIA(
        hipotesis_id=calcular_hipotesis_id(contexto, valor), campo=contexto.campo,
        valor_observado=contexto.valor_documental, valor_propuesto=valor, resultado=resultado,
        herramienta_faltante=herramienta, evidencia_usada=evidencia_usada,
    )


class _OrquestadorContador:
    """Doble de prueba real (nunca un Mock genérico): registra, campo por
    campo, cada `ContextoRazonamiento` con el que efectivamente se llamó
    -- permite afirmar "0 llamadas PARA obra_destino" sin exigir "0
    llamadas en absoluto" (un documento sintético puede tener otros
    motivos incidentales elegibles -- p. ej. chofer/patente -- ajenos a
    este bloque; lo que este bloque debe demostrar es que el dominio
    OBRA_DESTINO específicamente nunca llega a B1 cuando el catálogo ya
    resolvió)."""

    def __init__(self):
        self.campos_llamados: list[str] = []

    def resolver(self, contexto):
        self.campos_llamados.append(contexto.campo)
        return ResultadoOrquestacion(ABSTENCION_IA, CLASIFICACION_C, contexto, rondas=1)


# ============================================================
# 1. destino confirmado exacto -> determinístico; B1=0, web=0
# ============================================================


def test_1_destino_confirmado_exacto_resuelve_determinista_sin_b1(tmp_path, monkeypatch):
    carpeta, clientes, cliente, reloj, ids = _crear_cliente(tmp_path)
    destino = _crear_destino(carpeta, clientes, cliente, reloj, ids, nombre="OBRA UNO", direccion="CALLE UNO 100, SANTIAGO")
    catalogo = _obras_destinos(carpeta, clientes)
    resultado = catalogo.registrar_observacion(cliente_id=cliente.cliente_id, nombre_obra="OBRA GENERICA", destino_id=destino.destino_id, evidencia=_evidencia())
    catalogo.confirmar_relacion(resultado.relacion.relacion_id, actor="HUMANO")

    encontrado = _resolver(carpeta, cliente_texto=cliente.razon_social, rut_cliente="50.234.350-5", obra="OBRA GENERICA")
    assert encontrado is not None
    assert encontrado.destino.destino_id == destino.destino_id

    # Nivel pipeline: Core (`procesar_archivo`) resuelve solo -- el motivo
    # OBRA_DESTINO_SIN_CORROBORAR ni siquiera debe aparecer.
    salida = _procesar_con_mocks(
        tmp_path, carpeta, monkeypatch, cliente_texto=cliente.razon_social, rut_cliente="50.234.350-5",
        obra="OBRA GENERICA",
    )
    assert "OBRA_DESTINO_SIN_CORROBORAR" not in salida["motivos_revision_documento"]
    assert "CATALOGO_OBRA_DESTINO" in salida["metodos_recuperacion_documento"]

    # Nivel B1 (Sección 9/20): con el motivo ya ausente, la capa de
    # escalamiento (`escalar_resultado_ia_en_memoria`, misma entrada que
    # usa Mobile) NUNCA invoca al orquestador para el dominio OBRA_DESTINO
    # -- 0 llamadas reales para este campo, cero Groq, cero web.
    orquestador = _OrquestadorContador()
    escalar_resultado_ia_en_memoria(salida, [], orquestador_ia=orquestador, carpeta_catalogos=carpeta)
    assert "obra_destino" not in orquestador.campos_llamados


def _procesar_con_mocks(tmp_path, carpeta, monkeypatch, *, cliente_texto, rut_cliente, obra, direccion="CALLE UNO 100 SANTIAGO"):
    base = {
        "número de guía": "900001", "número de transporte": "0000900000",
        "cliente": cliente_texto, "obra destino": obra,
        "chofer": "JUAN PEREZ", "RUT del cliente": rut_cliente,
        "RUT del chofer": "50.234.350-5", "patente del tracto": "AB1234",
        "patente del carro": "CD5678",
    }
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[f"DESPACHAR A {direccion}"]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=base))
    return procesar_archivo(tmp_path / "guia.jpg", carpeta_catalogos=carpeta, proveedor_rutas=object())


# ============================================================
# 2. alias confirmado + misma dirección -> resolución automática
# ============================================================


def test_2_alias_confirmado_resuelve_automaticamente(tmp_path):
    carpeta, clientes, cliente, reloj, ids = _crear_cliente(tmp_path)
    destino = _crear_destino(carpeta, clientes, cliente, reloj, ids, nombre="OBRA DOS", direccion="CALLE DOS 200, SANTIAGO")
    catalogo = _obras_destinos(carpeta, clientes)
    resultado = catalogo.registrar_observacion(
        cliente_id=cliente.cliente_id, nombre_obra="EMPRESA EJEMPLO CONSTRUCTORA", destino_id=destino.destino_id,
        evidencia=_evidencia(), alias_documental="EMP EJEMPLO CONST",
    )
    catalogo.confirmar_relacion(resultado.relacion.relacion_id, actor="HUMANO")

    # El documento trae el ALIAS, no el nombre canónico -- debe seguir resolviendo.
    encontrado = _resolver(carpeta, cliente_texto=cliente.razon_social, rut_cliente="50.234.350-5", obra="EMP EJEMPLO CONST")
    assert encontrado is not None
    assert encontrado.destino.destino_id == destino.destino_id


# ============================================================
# 3. dirección normalizada equivalente (dos destinos redundantes)
#    -> resolución automática (caso real 472593/AUSIN SAN BERNARDO)
# ============================================================


def test_3_dos_confirmaciones_redundantes_para_la_misma_obra_igual_resuelve(tmp_path):
    """Caso real: la misma obra queda con DOS relaciones CONFIRMADAS
    hacia dos `Destino` de texto ligeramente distinto para el MISMO
    lugar real. Antes del fix, esto hacía que `_corroborar_obra_
    destino_confirmada` devolviera None (ambigüedad aparente).
    Universal: rubro y nombres genéricos, nunca SIGRO/PRODALAM."""
    carpeta, clientes, cliente, reloj, ids = _crear_cliente(tmp_path)
    destino_a = _crear_destino(
        carpeta, clientes, cliente, reloj, ids,
        nombre="AVENIDA CENTRAL 500 SANTIAGO NUNOA", direccion="AVENIDA CENTRAL 500 SANTIAGO NUNOA",
        fuente="DECISION_HUMANA_TEST_1",
    )
    destino_b = _crear_destino(
        carpeta, clientes, cliente, reloj, ids,
        nombre="Av. Central 500 Ñuñoa", direccion="Av. Central 500 Ñuñoa", comuna="Ñuñoa", region="Metropolitana",
        fuente="DECISION_HUMANA_TEST_2",
    )
    catalogo = _obras_destinos(carpeta, clientes)
    r1 = catalogo.registrar_observacion(cliente_id=cliente.cliente_id, nombre_obra="OBRA GENERICA", destino_id=destino_a.destino_id, evidencia=_evidencia("guia-a"))
    catalogo.confirmar_relacion(r1.relacion.relacion_id, actor="HUMANO")
    r2 = catalogo.registrar_observacion(cliente_id=cliente.cliente_id, nombre_obra="OBRA GENERICA", destino_id=destino_b.destino_id, evidencia=_evidencia("guia-b"))
    catalogo.confirmar_relacion(r2.relacion.relacion_id, actor="HUMANO")

    # La resolución estricta (una sola relación confirmada) falla -- es
    # justo lo que el bug reproducía.
    estricta = catalogo.resolver_obra_destino_confirmada_global(nombre_obra="OBRA GENERICA")
    assert estricta is None

    # Con el fix, la dirección documental (igual a AMBAS variantes
    # normalizadas) sí resuelve.
    encontrado = _resolver(
        carpeta, cliente_texto=cliente.razon_social, rut_cliente="50.234.350-5",
        obra="OBRA GENERICA", direccion="AVENIDA CENTRAL 500 SANTIAGO NUNOA",
    )
    assert encontrado is not None
    assert encontrado.destino_id in {destino_a.destino_id, destino_b.destino_id}


# ============================================================
# 4. candidato catálogo parcial -> evidencia para B1, no autoaplicar
# ============================================================


def test_4_candidato_parcial_se_pasa_como_evidencia_sin_autoaplicar(tmp_path):
    """Obra con DOS destinos confirmados (candidato fuerte, pero
    ambiguo -- exactamente el patrón redundante de la Sección 3/12) y
    una dirección documental que no coincide LITERALMENTE con ninguno:
    Core se abstiene (nunca "adivina" cuál de los dos), pero ambos
    quedan disponibles como evidencia estructurada para B1."""
    carpeta, clientes, cliente, reloj, ids = _crear_cliente(tmp_path)
    destino_x = _crear_destino(carpeta, clientes, cliente, reloj, ids, nombre="OBRA TRES SEDE X", direccion="CALLE TRES 300, SANTIAGO")
    destino_y = _crear_destino(carpeta, clientes, cliente, reloj, ids, nombre="OBRA TRES SEDE Y", direccion="CALLE CUATRO 400, SANTIAGO")
    catalogo = _obras_destinos(carpeta, clientes)
    r1 = catalogo.registrar_observacion(cliente_id=cliente.cliente_id, nombre_obra="OBRA GENERICA", destino_id=destino_x.destino_id, evidencia=_evidencia("guia-x"))
    catalogo.confirmar_relacion(r1.relacion.relacion_id, actor="HUMANO")
    r2 = catalogo.registrar_observacion(cliente_id=cliente.cliente_id, nombre_obra="OBRA GENERICA", destino_id=destino_y.destino_id, evidencia=_evidencia("guia-y"))
    catalogo.confirmar_relacion(r2.relacion.relacion_id, actor="HUMANO")

    # El documento trae una dirección que no coincide con NINGUNO de los dos.
    encontrado = _resolver(
        carpeta, cliente_texto=cliente.razon_social, rut_cliente="50.234.350-5",
        obra="OBRA GENERICA", direccion="CALLE COMPLETAMENTE DISTINTA 999",
    )
    assert encontrado is None  # nunca se autoaplica un candidato parcial/ambiguo

    fila = {"obra_destino": "OBRA GENERICA"}
    recolector = recopilar_evidencia_catalogo_obras_destinos("obra_destino")
    evidencias = recolector(fila, [], carpeta_catalogos=carpeta)
    assert len(evidencias) == 2
    valores = {e.valor for e in evidencias}
    assert valores == {"CALLE TRES 300, SANTIAGO", "CALLE CUATRO 400, SANTIAGO"}
    assert all(e.tipo_fuente == "CATALOGO" for e in evidencias)  # informativo, no una decisión ya tomada


# ============================================================
# 5. observación única no confirmada -> insuficiente
# ============================================================


def test_5_observacion_no_confirmada_es_insuficiente(tmp_path):
    carpeta, clientes, cliente, reloj, ids = _crear_cliente(tmp_path)
    destino = _crear_destino(carpeta, clientes, cliente, reloj, ids, nombre="OBRA CUATRO", direccion="CALLE CUATRO 400")
    catalogo = _obras_destinos(carpeta, clientes)
    catalogo.registrar_observacion(cliente_id=cliente.cliente_id, nombre_obra="OBRA GENERICA", destino_id=destino.destino_id, evidencia=_evidencia())
    # NUNCA se llama confirmar_relacion -- queda observada, no confirmada.

    encontrado = _resolver(
        carpeta, cliente_texto=cliente.razon_social, rut_cliente="50.234.350-5",
        obra="OBRA GENERICA", direccion="CALLE CUATRO 400",
    )
    assert encontrado is None

    recolector = recopilar_evidencia_catalogo_obras_destinos("obra_destino")
    evidencias = recolector({"obra_destino": "OBRA GENERICA"}, [], carpeta_catalogos=carpeta)
    assert evidencias == ()  # una observación sola no se convierte en evidencia reutilizable


# ============================================================
# 6. historial independiente repetido -> evidencia aumenta
# ============================================================


def test_6_historial_repetido_sigue_aportando_evidencia_en_el_recolector_combinado(tmp_path):
    fila_actual = {
        "archivo": "mobile/actual/original.jpg", "numero_guia": "900201", "numero_transporte": "0000900200",
        "fecha": "25-08-2026", "chofer": "JUAN PEREZ", "patente_tracto": "AB1234", "obra_destino": "OBRA GENERICA",
    }
    hermano_1 = dict(fila_actual, archivo="mobile/h1/original.jpg", numero_guia="900101", numero_transporte="0000900100")
    hermano_2 = dict(fila_actual, archivo="mobile/h2/original.jpg", numero_guia="900301", numero_transporte="0000900300")

    recolector = recopilar_evidencia_obra_destino("obra_destino")
    evidencias = recolector(fila_actual, [hermano_1, hermano_2], carpeta_catalogos=None)
    assert len(evidencias) == 2
    assert all(e.tipo_fuente == "HISTORICO" for e in evidencias)


# ============================================================
# 7. confirmación humana previa -> reutilizable (nivel CANONICO_CONFIRMADO)
# ============================================================


def test_7_confirmacion_humana_se_expone_como_evidencia_canonico_confirmado(tmp_path):
    carpeta, clientes, cliente, reloj, ids = _crear_cliente(tmp_path)
    destino = _crear_destino(
        carpeta, clientes, cliente, reloj, ids, nombre="OBRA CINCO", direccion="CALLE CINCO 500",
        fuente="CONFIRMACION_HUMANA_TEST",
    )
    catalogo = _obras_destinos(carpeta, clientes)
    resultado = catalogo.registrar_observacion(cliente_id=cliente.cliente_id, nombre_obra="OBRA SEIS", destino_id=destino.destino_id, evidencia=_evidencia())
    catalogo.confirmar_relacion(resultado.relacion.relacion_id, actor="HUMANO")

    recolector = recopilar_evidencia_catalogo_obras_destinos("obra_destino")
    evidencias = recolector({"obra_destino": "OBRA SEIS"}, [], carpeta_catalogos=carpeta)
    assert len(evidencias) == 1
    assert evidencias[0].tipo_fuente == "DECISION_HUMANA"
    assert evidencias[0].es_decision_humana is True
    assert evidencias[0].nivel == "CANONICO_CONFIRMADO"


# ============================================================
# 8. un documento nunca se corrobora consigo mismo (recolector combinado)
# ============================================================


def test_8_documento_no_se_corrobora_a_si_mismo_en_el_recolector_combinado():
    fila_actual = {
        "archivo": "mobile/actual/original.jpg", "numero_guia": "900201", "numero_transporte": "0000900200",
        "fecha": "25-08-2026", "chofer": "JUAN PEREZ", "patente_tracto": "AB1234", "obra_destino": "OBRA GENERICA",
    }
    fila_propia_anterior = dict(fila_actual)
    recolector = recopilar_evidencia_obra_destino("obra_destino")
    evidencias = recolector(fila_actual, [fila_propia_anterior], carpeta_catalogos=None)
    assert evidencias == ()


# ============================================================
# 9. contradicción catálogo vs documento -> no sobrescribir en silencio
# ============================================================


def test_9_contradiccion_catalogo_vs_documento_nunca_sobrescribe_en_silencio(tmp_path, monkeypatch):
    """Sección 15: catálogo confirmado dice Destino->Calle Siete, el
    documento trae una dirección de entrega DISTINTA (Calle Ocho). Con
    una única relación confirmada, el NOMBRE de obra sigue
    corroborándose por catálogo (comportamiento ya existente, no
    afectado por este bloque) -- pero eso NUNCA sustituye en silencio
    la dirección de entrega documental (`despachar_a_crudo`, la única
    fuente autoritativa de entrega, ver `atlas_core.rutas.destino_
    entrega`) por la dirección guardada en el catálogo: son campos
    distintos, y la del catálogo nunca pisa la del documento."""
    carpeta, clientes, cliente, reloj, ids = _crear_cliente(tmp_path)
    destino = _crear_destino(carpeta, clientes, cliente, reloj, ids, nombre="OBRA SIETE", direccion="CALLE SIETE 700")
    catalogo = _obras_destinos(carpeta, clientes)
    resultado = catalogo.registrar_observacion(cliente_id=cliente.cliente_id, nombre_obra="OBRA GENERICA", destino_id=destino.destino_id, evidencia=_evidencia())
    catalogo.confirmar_relacion(resultado.relacion.relacion_id, actor="HUMANO")

    salida = _procesar_con_mocks(
        tmp_path, carpeta, monkeypatch, cliente_texto=cliente.razon_social, rut_cliente="50.234.350-5",
        obra="OBRA GENERICA", direccion="CALLE OCHO CONTRADICTORIA 800",
    )
    assert salida["obra_destino"] == "OBRA GENERICA"
    assert "CALLE OCHO CONTRADICTORIA 800" in salida.get("despachar_a_crudo", "")
    assert "CALLE SIETE 700" not in salida.get("despachar_a_crudo", "")


# ============================================================
# 10. catálogo insuficiente -> B1 puede pedir web
# ============================================================


def test_10_catalogo_insuficiente_b1_puede_pedir_verificacion_externa(tmp_path):
    fila = {"obra_destino": "EMPRESA SIN CATALOGO SPA"}
    recolector = recopilar_evidencia_obra_destino("obra_destino")
    evidencias = recolector(fila, [], carpeta_catalogos=tmp_path / "catalogos")
    assert evidencias == ()  # nada interno -- catálogo insuficiente

    class _Buscador:
        def buscar(self, consulta):
            return RespuestaBusquedaWeb(
                consulta=consulta, respuesta_texto="Sin evidencia pública suficiente.",
                citas=(Cita("Fuente", "https://ejemplo.test"),), proveedor="openrouter_sonar",
                modelo="perplexity/sonar", fecha="2026-08-27T00:00:00+00:00",
            )

    herramienta = herramienta_verificacion_externa(_Buscador())

    class _ProveedorPideWeb:
        def __init__(self):
            self.ronda = 0

        def razonar(self, contexto):
            self.ronda += 1
            if self.ronda == 1:
                return _hipotesis(contexto, RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA, herramienta="VERIFICACION_EXTERNA")
            return _hipotesis(contexto, RESULTADO_HIPOTESIS_ABSTENCION)

    contexto = ContextoRazonamiento(
        campo="obra_destino", valor_documental="EMPRESA SIN CATALOGO SPA", rut_chofer="", numero_guia="900501",
        numero_transporte="0000900500", evidencias=evidencias, resultado_motor="REQUIERE_REVISION",
        identidad_operacional={"obra_destino": "EMPRESA SIN CATALOGO SPA", "cliente": "", "direccion_entrega": ""},
        herramientas_disponibles=("VERIFICACION_EXTERNA",),
    )
    resultado = OrquestadorAtlasIA(proveedor=_ProveedorPideWeb(), herramientas={"VERIFICACION_EXTERNA": herramienta}).resolver(contexto)
    assert resultado.herramientas_usadas == ("VERIFICACION_EXTERNA",)


# ============================================================
# 11. catálogo suficiente -> web/B1 nunca se llama
# ============================================================


def test_11_catalogo_suficiente_nunca_llama_a_b1(tmp_path, monkeypatch):
    carpeta, clientes, cliente, reloj, ids = _crear_cliente(tmp_path)
    destino = _crear_destino(carpeta, clientes, cliente, reloj, ids, nombre="OBRA OCHO", direccion="CALLE OCHO 800, SANTIAGO")
    catalogo = _obras_destinos(carpeta, clientes)
    resultado = catalogo.registrar_observacion(cliente_id=cliente.cliente_id, nombre_obra="OBRA GENERICA", destino_id=destino.destino_id, evidencia=_evidencia())
    catalogo.confirmar_relacion(resultado.relacion.relacion_id, actor="HUMANO")

    salida = _procesar_con_mocks(
        tmp_path, carpeta, monkeypatch, cliente_texto=cliente.razon_social, rut_cliente="50.234.350-5",
        obra="OBRA GENERICA", direccion="CALLE OCHO 800 SANTIAGO",
    )
    orquestador = _OrquestadorContador()
    escalar_resultado_ia_en_memoria(salida, [], orquestador_ia=orquestador, carpeta_catalogos=carpeta)
    assert "obra_destino" not in orquestador.campos_llamados


# ============================================================
# 12. fixture universal -- otro rubro, sucursal != casa matriz
# ============================================================


def test_12_fixture_universal_distribuidora_alimentos_sucursal_distinta_de_matriz(tmp_path):
    carpeta, clientes, cliente, reloj, ids = _crear_cliente(
        tmp_path, razon_social="DISTRIBUIDORA NORTE SPA", rut="76.083.093-3",
    )
    sucursal = _crear_destino(
        carpeta, clientes, cliente, reloj, ids, nombre="SUCURSAL SAN BERNARDO",
        direccion="CAMINO REAL 450, SAN BERNARDO", comuna="SAN BERNARDO", fuente="CONFIRMACION_HUMANA_TEST",
    )
    catalogo = _obras_destinos(carpeta, clientes)
    resultado = catalogo.registrar_observacion(
        cliente_id=cliente.cliente_id, nombre_obra="SUPERMERCADOS VALLE VERDE",
        destino_id=sucursal.destino_id, evidencia=_evidencia(),
    )
    catalogo.confirmar_relacion(resultado.relacion.relacion_id, actor="HUMANO")

    encontrado = _resolver(
        carpeta, cliente_texto="DISTRIBUIDORA NORTE SPA", rut_cliente="76.083.093-3",
        obra="SUPERMERCADOS VALLE VERDE", direccion="CAMINO REAL 450, SAN BERNARDO",
    )
    assert encontrado is not None
    assert encontrado.destino.destino_id == sucursal.destino_id
    # La sucursal (destino operacional) es DISTINTA de cualquier posible
    # "casa matriz" -- nunca se confunden porque ni siquiera se modela
    # una sede separada aquí: el catálogo sólo conoce la relación
    # obra<->destino real, nunca inventa una sede.
