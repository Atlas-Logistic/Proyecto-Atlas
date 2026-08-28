"""Bloque U1 -- UNIVERSALIDAD REAL DE B1.

Contexto real (fase 1/2 de este bloque, auditoría del código actual, no
suposiciones): Mobile y Desktop/lote ya comparten UN único dispatcher
(`atlas_core.procesamiento_masivo._ejecutar_ia_operacional`), UN único
registro de tipos de problema (`atlas_ia.registro_problemas.
REGISTRO_PROBLEMAS_IA`, vía `detectar_problemas_elegibles`) y UNA única
fábrica de herramientas (`_herramientas_b1_disponibles`, usada por
`_crear_orquestador_ia_configurado`, invocada tanto desde el camino en
memoria de Mobile -- `escalar_resultado_ia_en_memoria` -- como desde el
lote de Desktop). No existían dos registros divergentes ni un `if
llamar_b1()` disperso en veinte sitios -- la arquitectura universal ya
estaba mayormente construida.

La desconexión real encontrada (fase 2) es más angosta pero de mayor
radio de impacto que la de M2-C: `DOCUMENTOS_RELACIONADOS`
(`atlas_ia.herramientas.herramienta_documentos_relacionados`) estaba
declarada como herramienta disponible en `TipoProblemaIA.herramientas`
para ~9 tipos de problema (CHOFER_SIN_CORROBORAR/AUSENTE,
PATENTE_SIN_HOMOLOGAR/AMBIGUA en ambos campos, CLIENTE_SIN_CORROBORAR/
AUSENTE/NUEVA_ENTIDAD_NO_CATALOGADA, FECHA_SIN_CORROBORAR,
MATERIAL_AUSENTE, DESTINO) pero JAMÁS conectada en
`_herramientas_b1_disponibles` -- exactamente el mismo patrón de bug que
M2-C, con una superficie mucho mayor. Se corrige en
`procesamiento_masivo.py` y se cierra estructuralmente con la nueva
`atlas_ia.registro_problemas.nombres_herramientas_declaradas()` (fuente
única de "qué nombres existen"), verificada aquí contra la fábrica real.

Estas pruebas demuestran la PROPIEDAD arquitectónica pedida por el
bloque, no reglas puntuales por dominio."""
from __future__ import annotations

import inspect

from atlas_core import procesamiento_masivo as pm
from atlas_core.atlas_ia.contratos import (
    ContextoRazonamiento, HipotesisIA, RESULTADO_HIPOTESIS_ABSTENCION,
    RESULTADO_HIPOTESIS_PROPUESTA, calcular_hipotesis_id,
)
from atlas_core.atlas_ia.orquestador import (
    ABSTENCION_IA, NO_APLICA_IA, OrquestadorAtlasIA,
)
from atlas_core.atlas_ia.registro_problemas import (
    detectar_problemas_elegibles, nombres_herramientas_declaradas,
)
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.procesamiento_masivo import _herramientas_b1_disponibles


# ============================================================
# 1. Mobile y Desktop acceden al MISMO registro/capacidades B1 -- un
#    único dispatcher, nunca dos caminos que puedan divergir.
# ============================================================


def test_mobile_y_desktop_comparten_el_mismo_dispatcher_b1():
    """Prueba arquitectónica por inspección de código: tanto el camino
    Mobile (`escalar_resultado_ia_en_memoria`) como el camino Desktop/
    lote (`procesar_carpeta`) delegan en la MISMA función
    `_ejecutar_ia_operacional` -- nunca una copia paralela. Si algún día
    alguien "resuelve" un bug de B1 sólo en un camino y olvida el otro,
    esta prueba deja de tener sentido para expresarlo (el código fuente
    ya no compartiría la llamada) y falla."""
    fuente_mobile = inspect.getsource(pm.escalar_resultado_ia_en_memoria)
    fuente_lote = inspect.getsource(pm.procesar_carpeta)
    assert "_ejecutar_ia_operacional(" in fuente_mobile
    assert "_ejecutar_ia_operacional(" in fuente_lote

    # Ambos caminos construyen el orquestador, cuando no se les entrega
    # uno explícito, con la MISMA fábrica -- nunca una fábrica de
    # herramientas distinta por flujo.
    assert "_crear_orquestador_ia_configurado(" in fuente_mobile
    assert "_crear_orquestador_ia_configurado(" in fuente_lote


# ============================================================
# 2. Una herramienta declarada no puede quedar silenciosamente
#    inaccesible en ningún flujo -- regresión estructural general.
# ============================================================


def test_toda_herramienta_declarada_queda_realmente_registrada(tmp_path, monkeypatch):
    """Cierra estructuralmente la clase de bug real de M2-C/U1: con
    datos "máximos" disponibles (filas de historial, catálogo de
    plantas real, credencial de búsqueda externa), TODO nombre que
    `REGISTRO_PROBLEMAS_IA` declara vía `TipoProblemaIA.herramientas`
    debe terminar como clave real en `_herramientas_b1_disponibles`.

    Esta es la regresión que impide que un dominio nuevo, mañana,
    declare una herramienta y se le olvide conectarla -- sin necesidad
    de enumerar los nombres a mano (se derivan del registro real vía
    `nombres_herramientas_declaradas()`, nunca una lista duplicada
    aquí)."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "clave-de-prueba-u1")
    carpeta_catalogos = tmp_path / "catalogos"
    CatalogoPlantas(carpeta_catalogos / "plantas.json").crear(
        nombre="PLANTA DE PRUEBA U1", pais="CHILE", fuente="TEST",
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    filas = [{
        "numero_guia": "1", "numero_transporte": "1",
        "origen_determinado_por": "TELEMETRIA_GPS", "planta_origen_nombre": "PLANTA DE PRUEBA U1",
    }]

    declaradas = nombres_herramientas_declaradas()
    disponibles = _herramientas_b1_disponibles(filas=filas, carpeta_catalogos=carpeta_catalogos)

    faltantes = declaradas - set(disponibles)
    assert faltantes == set(), (
        f"Herramienta(s) declarada(s) en REGISTRO_PROBLEMAS_IA sin conexión real "
        f"en _herramientas_b1_disponibles: {sorted(faltantes)}"
    )
    # Control: la propiedad no es trivial -- de verdad hay herramientas
    # registradas (nunca ambos conjuntos vacíos por casualidad).
    assert disponibles


def test_documentos_relacionados_especificamente_ya_no_queda_inaccesible(tmp_path):
    """Caso concreto (antes de este bloque, con datos): la fábrica real
    nunca incluía `DOCUMENTOS_RELACIONADOS` pese a estar declarada para
    CHOFER/PATENTE/CLIENTE/FECHA/MATERIAL/DESTINO. Ahora sí."""
    filas = [{"numero_guia": "1", "numero_transporte": "1", "cliente": "EMPRESA X"}]
    disponibles = _herramientas_b1_disponibles(filas=filas)
    assert "DOCUMENTOS_RELACIONADOS" in disponibles


# ============================================================
# 3-7. Un problema no resuelto de ORIGEN/PATENTE/CLIENTE/OBRA-DESTINO/
#      MATERIAL puede llegar a B1 -- vía la MISMA puerta común
#      (`detectar_problemas_elegibles`), con herramientas realmente
#      conectadas.
# ============================================================


def _fila_documental(motivo: str, **extra: str) -> dict[str, str]:
    fila = {
        "numero_guia": "1", "numero_transporte": "1",
        "motivos_revision_documento": motivo, "motivo_ruta": "", "motivo_origen_gps": "",
    }
    fila.update(extra)
    return fila


def test_problema_no_resuelto_de_origen_llega_a_b1():
    fila = {
        "numero_guia": "1", "numero_transporte": "1",
        "motivos_revision_documento": "", "motivo_ruta": "CONTRADICCION_OPERACIONAL_ORIGEN[MOBILE=X:INCOMPATIBLE]",
        "motivo_origen_gps": "",
    }
    encontrados = detectar_problemas_elegibles(fila)
    dominios = {tipo.dominio for tipo, _ in encontrados}
    assert "PLANTA_ORIGEN" in dominios
    tipo_origen = next(tipo for tipo, _ in encontrados if tipo.dominio == "PLANTA_ORIGEN")
    assert set(tipo_origen.herramientas) <= nombres_herramientas_declaradas()


def test_problema_no_resuelto_de_patente_llega_a_b1():
    fila = _fila_documental("PATENTE_SIN_HOMOLOGAR")
    encontrados = detectar_problemas_elegibles(fila)
    dominios_y_campos = {(tipo.dominio, tipo.campo) for tipo, _ in encontrados}
    assert ("PATENTE", "patente_tracto") in dominios_y_campos
    assert ("PATENTE", "patente_rampla") in dominios_y_campos  # Bloque R12 -- ambos campos, nunca sólo tracto.


def test_problema_no_resuelto_de_cliente_llega_a_b1():
    fila = _fila_documental("CLIENTE_SIN_CORROBORAR")
    encontrados = detectar_problemas_elegibles(fila)
    assert any(tipo.dominio == "CLIENTE" for tipo, _ in encontrados)


def test_problema_no_resuelto_de_obra_destino_llega_a_b1():
    fila = _fila_documental("OBRA_DESTINO_SIN_CORROBORAR")
    encontrados = detectar_problemas_elegibles(fila)
    assert any(tipo.dominio == "OBRA_DESTINO" for tipo, _ in encontrados)


def test_problema_no_resuelto_de_material_llega_a_b1():
    fila = _fila_documental("MATERIAL_AUSENTE")
    encontrados = detectar_problemas_elegibles(fila)
    assert any(tipo.dominio == "MATERIAL" for tipo, _ in encontrados)


# ============================================================
# 8. Un problema nuevo/genérico soportado por el contrato puede
#    alcanzar la puerta B1 y abstenerse limpiamente, aunque todavía no
#    tenga herramienta especializada -- el contrato (`ContextoRazonamiento`/
#    `OrquestadorAtlasIA`) no tiene una lista cerrada de "campos
#    permitidos".
# ============================================================


class _ProveedorSeAbstiene:
    """Simula un proveedor real que, sin evidencia suficiente, se
    abstiene limpiamente -- comportamiento correcto para CUALQUIER
    dominio nuevo sin herramienta especializada todavía."""

    def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:
        return HipotesisIA(
            hipotesis_id=calcular_hipotesis_id(contexto, ""), campo=contexto.campo,
            valor_observado=contexto.valor_documental, valor_propuesto="",
            resultado=RESULTADO_HIPOTESIS_ABSTENCION,
            explicacion="Sin herramienta especializada ni evidencia suficiente para este dominio.",
        )


def test_dominio_nuevo_generico_alcanza_la_puerta_b1_y_se_abstiene_limpio():
    """`campo` es un string libre -- ni `ContextoRazonamiento` ni
    `OrquestadorAtlasIA` mantienen una lista cerrada de dominios
    permitidos. Un dominio operacional que ni siquiera existe hoy en
    `REGISTRO_PROBLEMAS_IA` puede construirse como contexto y pasar por
    el mismo orquestador -- sin herramientas (`herramientas_disponibles=
    ()`), B1 se abstiene, nunca queda estructuralmente incapaz de
    intervenir."""
    contexto = ContextoRazonamiento(
        campo="dominio_operacional_hipotetico_futuro_u1", valor_documental="ALGO",
        rut_chofer="", numero_guia="9", numero_transporte="9",
        evidencias=(), resultado_motor="REQUIERE_REVISION",
        herramientas_disponibles=(),
    )
    resultado = OrquestadorAtlasIA(proveedor=_ProveedorSeAbstiene(), herramientas={}).resolver(contexto)
    assert resultado.estado == ABSTENCION_IA
    assert resultado.hipotesis.resultado == RESULTADO_HIPOTESIS_ABSTENCION


# ============================================================
# 9. Evidencia determinista suficiente NO invoca B1 -- ni al proveedor
#    ni a la puerta de escalamiento.
# ============================================================


class _ProveedorNuncaDeberiaLlamarse:
    def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:  # pragma: no cover
        raise AssertionError("B1 no debía invocarse: el Motor ya resolvió con evidencia suficiente.")


def test_resultado_motor_ya_resuelto_nunca_invoca_al_proveedor():
    contexto = ContextoRazonamiento(
        campo="cliente", valor_documental="EMPRESA X", rut_chofer="", numero_guia="1",
        numero_transporte="1", evidencias=(), resultado_motor="RESUELTO_AUTOMATICAMENTE",
    )
    resultado = OrquestadorAtlasIA(proveedor=_ProveedorNuncaDeberiaLlamarse(), herramientas={}).resolver(contexto)
    assert resultado.estado == NO_APLICA_IA
    assert resultado.rondas == 0


def test_fila_sin_ningun_motivo_de_revision_nunca_produce_un_problema_elegible():
    """Sin ningún motivo (documental/ruta/origen GPS), la puerta común
    (`detectar_problemas_elegibles`) no encuentra nada que escalar --
    B1 nunca recibe una tarea para un documento ya resuelto."""
    fila = {
        "numero_guia": "1", "numero_transporte": "1",
        "motivos_revision_documento": "", "motivo_ruta": "", "motivo_origen_gps": "",
    }
    assert detectar_problemas_elegibles(fila) == []
