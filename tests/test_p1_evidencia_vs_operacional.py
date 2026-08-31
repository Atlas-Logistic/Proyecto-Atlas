"""Bloque P1, Parte A -- SEPARACIÓN ESTRICTA entre evidencia OCR y dato
operacional publicado.

Causa raíz real (C1 detectaba pero seguía publicando): C1 (bloque
anterior) sólo agregaba un motivo trazable a `motivos_revision_
documento` -- el valor DUDOSO/INVÁLIDO seguía siendo exactamente el
mismo que Viajes/reportes terminaban mostrando. `atlas_core.
credibilidad_campos.valor_publicable` (nuevo, P1) es el único punto que
decide qué se PUBLICA; `atlas_core.gestor_viajes.Viaje` lo aplica a
cliente/obra_destino/material/despachar_a -- el valor documental crudo
nunca se borra, sigue disponible íntegro en `evidencia`/
`evidencias_documentos` (ya existía desde antes de P1, ver Bloque
VEHÍCULO D1)."""
from __future__ import annotations

import csv

from atlas_core.credibilidad_campos import (
    VALOR_NO_DETERMINADO,
    NivelCredibilidad,
    evaluar_credibilidad_entidad_nombre,
    evaluar_credibilidad_material,
    valor_publicable,
)
from atlas_core.gestor_viajes import agrupar_viajes
from atlas_core.procesamiento_masivo import COLUMNAS

_MATERIAL_CONTAMINADO_472624 = (
    "Codigo Cliente 0001004274 FECHA DE EMISION 26-08-2026 SODIMAC SA "
    "SENOR(ES) 96.792.430-K RUT VIA AL X MENOR MAI C GIRO AV PDIE "
    "EDUARDO FREI 3092 DIRECCION COMUNA RENCA CIUDAD SANTIAGO "
    "Operacion constituye Venta INDICADOR TRASLADO TRANSPORTE "
    "TRANSPORTES MBI SPA EMPRESA DESCRIPCION CANTIDAD Codigo "
    "HORMIGON 8MM 12M A630-420H (N) 3.025/110002847 B Coladas: 2617677302"
)


# ============================================================
# 1/2/3. valor_publicable: CONFIABLE se publica; DUDOSO/INVÁLIDO
#        conservan evidencia pero no se publican limpios.
# ============================================================


def test_campo_confiable_se_publica_tal_cual():
    assert valor_publicable("HORMIGON 8MM", evaluar_credibilidad_material) == "HORMIGON 8MM"


def test_campo_dudoso_no_se_publica_limpio_conserva_evidencia_intacta():
    """Caso real 472624: obra_destino = "TRANSPORTES" (DUDOSO, etiqueta
    genérica) -- nunca se publica como obra limpia; sin evidencia
    independiente, el resultado es VALOR_NO_DETERMINADO. El texto
    original nunca se muta (esto es una función pura -- el llamador es
    responsable de conservarlo aparte, como ya hace `DocumentoViaje.
    evidencia`)."""
    assert evaluar_credibilidad_entidad_nombre("TRANSPORTES").nivel == NivelCredibilidad.DUDOSO
    publicado = valor_publicable("TRANSPORTES", evaluar_credibilidad_entidad_nombre)
    assert publicado == VALOR_NO_DETERMINADO
    assert publicado != "TRANSPORTES"


def test_campo_invalido_no_se_publica_limpio():
    """Caso real 472624: material contaminado por un bloque documental
    completo -- INVÁLIDO, nunca publicado como párrafo operacional."""
    resultado = evaluar_credibilidad_material(_MATERIAL_CONTAMINADO_472624)
    assert resultado.nivel == NivelCredibilidad.INVALIDO
    assert valor_publicable(_MATERIAL_CONTAMINADO_472624, evaluar_credibilidad_material) == VALOR_NO_DETERMINADO


# ============================================================
# 4. Campo dudoso puede rehabilitarse con evidencia INDEPENDIENTE real
#    (nunca inventada).
# ============================================================


def test_campo_dudoso_se_rehabilita_con_candidato_confiable_real():
    """Caso real: 472624 cliente = "96 .792.430-K" (RUT crudo
    desalineado por OCR); el documento hermano 472623 del mismo
    transporte trae "SODIMAC SA" -- evidencia independiente real de que
    es el mismo cliente. Se recupera, nunca se publica el RUT crudo."""
    assert evaluar_credibilidad_entidad_nombre("96 .792.430-K").nivel != NivelCredibilidad.CONFIABLE
    publicado = valor_publicable(
        "96 .792.430-K", evaluar_credibilidad_entidad_nombre, candidatos_recuperacion=["SODIMAC SA"],
    )
    assert publicado == "SODIMAC SA"


def test_candidato_de_recuperacion_tambien_dudoso_no_rehabilita_nada():
    """Control: si NINGÚN candidato de recuperación es realmente
    confiable, nunca se "recupera" hacia otro valor igual de dudoso --
    se abstiene (VALOR_NO_DETERMINADO), nunca inventa una salida."""
    publicado = valor_publicable(
        "TRANSPORTES", evaluar_credibilidad_entidad_nombre, candidatos_recuperacion=["TRANSPORTE", ""],
    )
    assert publicado == VALOR_NO_DETERMINADO


# ============================================================
# 5. B1 insuficiente -> abstención limpia (reconstruido a nivel de
#    orquestador -- mismo criterio general ya probado en M3/U1/C1,
#    reafirmado aquí porque P1 depende de que esa barrera siga intacta:
#    si B1 alguna vez pudiera "limpiar" un dato sólo porque parece raro,
#    la separación evidencia/operacional de este bloque perdería sentido).
# ============================================================


def test_b1_insuficiente_nunca_fuerza_una_recuperacion_sin_evidencia():
    from atlas_core.atlas_ia.contratos import (
        ContextoRazonamiento, HipotesisIA, RESULTADO_HIPOTESIS_ABSTENCION, calcular_hipotesis_id,
    )
    from atlas_core.atlas_ia.orquestador import ABSTENCION_IA, OrquestadorAtlasIA

    class _ProveedorSeAbstiene:
        def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:
            return HipotesisIA(
                hipotesis_id=calcular_hipotesis_id(contexto, ""), campo=contexto.campo,
                valor_observado=contexto.valor_documental, valor_propuesto="",
                resultado=RESULTADO_HIPOTESIS_ABSTENCION,
            )

    contexto = ContextoRazonamiento(
        campo="obra_destino", valor_documental="TRANSPORTES", rut_chofer="",
        numero_guia="472624", numero_transporte="0000355433", evidencias=(),
        resultado_motor="REQUIERE_REVISION",
    )
    resultado = OrquestadorAtlasIA(proveedor=_ProveedorSeAbstiene(), herramientas={}).resolver(contexto)
    assert resultado.estado == ABSTENCION_IA
    # Sin propuesta de B1, el valor sigue dudoso -- `valor_publicable`
    # (llamado más tarde, a nivel de reporte) seguirá abstiéndose igual.
    assert valor_publicable("TRANSPORTES", evaluar_credibilidad_entidad_nombre) == VALOR_NO_DETERMINADO


# ============================================================
# 6/10. UI/viaje (Viajes) nunca recibe OCR contaminado como dato
#       operacional -- reconstrucción real end-to-end 472623/472624,
#       vía el mecanismo GENERAL (`agrupar_viajes`), nunca un parche por
#       guía. Mobile y Desktop/lote comparten el mismo dataset y el
#       mismo `agrupar_viajes` -- nunca dos caminos de agregación.
# ============================================================


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "1.jpeg", "estado_procesamiento": "OK", "fecha": "26-08-2026",
        "indicador_revision": "OK", "estado_ruta": "RUTA_CALCULADA",
        "planta_origen_nombre": "AZA COLINA",
    })
    fila.update(overrides)
    return fila


def test_viaje_472623_472624_nunca_publica_ocr_contaminado_como_dato_limpio():
    fila_472624 = _fila(
        archivo="472624.jpeg",
        numero_guia="472624", numero_transporte="0000355433",
        cliente="96 .792.430-K", obra_destino="TRANSPORTES",
        descripcion_material=_MATERIAL_CONTAMINADO_472624,
        despachar_a_crudo="SAN", direccion_entrega="", peso_kg="3025",
        patente_tracto="ND6443", patente_rampla="J36878",
    )
    fila_472623 = _fila(
        archivo="472623.jpeg",
        numero_guia="472623", numero_transporte="0000355433",
        cliente="SODIMAC SA", obra_destino="TRANSPORTES",
        descripcion_material="B HORMIGON 1 OMM 12M A630-42OH (N) Coladas : 2616301102,2616301202",
        despachar_a_crudo="SAN LUIS 1201 QUILICURA", direccion_entrega="SAN LUIS 1201 QUILICURA",
        peso_kg="87", patente_tracto="ND6443", patente_rampla="JB6878",
    )
    viajes, sin_transporte = agrupar_viajes([fila_472624, fila_472623])
    assert sin_transporte == []
    assert len(viajes) == 1
    viaje = viajes[0]

    # Nunca el bloque completo cliente/fecha/RUT/dirección/transportista
    # como "material" operacional -- ni el RUT crudo como cliente, ni la
    # etiqueta genérica como obra, ni el fragmento truncado como destino.
    assert _MATERIAL_CONTAMINADO_472624 not in viaje.materiales
    assert "96 .792.430-K" not in viaje.clientes
    assert "SAN" != viaje.despachar_a

    # Rehabilitado con evidencia real (documento hermano del mismo viaje):
    assert viaje.clientes == ["SODIMAC SA"]
    # obra_destino: ambos documentos comparten la MISMA etiqueta genérica
    # -- sin evidencia independiente real, ninguno se rehabilita.
    assert viaje.obras_destino == [VALOR_NO_DETERMINADO]
    # Material: nunca se recupera de un hermano (carga distinta por
    # documento) -- 472624 queda NO DETERMINADO, 472623 sigue visible.
    assert VALOR_NO_DETERMINADO in viaje.materiales
    assert "B HORMIGON 1 OMM 12M A630-42OH (N) Coladas : 2616301102,2616301202" in viaje.materiales
    # despachar_a: el fragmento truncado se excluye de la consolidación
    # -- gana la dirección real y completa del documento hermano.
    assert viaje.despachar_a == "SAN LUIS 1201 QUILICURA"

    # Preservado intacto -- P1 nunca toca origen/transporte/patentes/peso.
    assert viaje.origenes == ["AZA COLINA"]
    assert set(viaje.patentes_rampla) == {"J36878", "JB6878"}
    assert viaje.peso_total_viaje_kg == "3112"

    # El OCR contaminado NUNCA se pierde -- sigue íntegro como evidencia.
    materiales_evidencia = [d.evidencia.get("descripcion_material") for d in viaje.documentos]
    assert _MATERIAL_CONTAMINADO_472624 in materiales_evidencia


def test_mobile_y_lote_comparten_el_mismo_mecanismo_de_publicacion():
    """P1 -- `agrupar_viajes` es la única función de agregación; ni
    Mobile ni Desktop/lote construyen su propia versión de `Viaje`."""
    import inspect

    from atlas_core import reporte_viajes

    fuente = inspect.getsource(reporte_viajes)
    assert "agrupar_viajes(" in fuente
