"""Bloque REVISIÓN DE ATLAS: COHERENCIA (casos reales 472623/472624).

Tres clases de problema, cada una con su causa raíz propia en la capa de
extracción/corroboración documental de Mobile (Desktop comparte el mismo
Core, así que las tres corrigen ambos caminos):

1. RUT cliente (`_extraer_rut_cliente_geometrico`) no se recuperaba
   siempre que debía -- no porque el extractor esté roto (ya localiza
   correctamente la zona SEÑOR(ES)/R.U.T., ver `test_rut_cliente_v1.py`),
   sino porque los ~6 intentos de recuperación geométrica de
   `procesar_archivo` (cliente/obra destino, RUT cliente, chofer, RUT
   chofer, transporte, patentes) compartían un solo try/except -- una
   excepción en CUALQUIERA de ellos abortaba el bloque completo y
   silenciaba a los demás, aunque cada uno sea independiente y ya se
   abstenga solo ante ambigüedad. Ver `atlas_core.procesamiento_masivo`.

2. "AZA RENCA" (membrete/casa matriz societaria) se colaba como
   evidencia de origen documental pese a que `_tokens_encabezado_origen`
   ya excluye ese tramo -- la exigencia de que "MATRIZ" apareciera
   INMEDIATAMENTE después de "CASA" en el texto de página completa era
   frágil ante un bloque de ruido OCR intercalado entre ambos tokens.
   Ver `atlas_core.rutas.origen_documental`.

3. La decisión ORIGEN_NO_CONFIRMADO aparecía duplicada (dos decision_id
   distintos para la misma guía/evidencia) y la "guía original" quedaba
   irresoluble -- ambos por la misma causa: `escalar_resultado_ia_en_
   memoria` (compartida por Mobile) dejaba escapar en su valor de
   retorno el placeholder interno `"__mobile_actual__"` (necesario sólo
   para que el orquestador B1 identifique la fila actual en su CSV
   temporal), que terminaba tanto en `envio.json` como en
   `documento.archivo` de la decisión detectada en vivo -- distinto del
   `archivo` real que la reconciliación por lote usa más tarde para la
   MISMA decisión. Ver `atlas_core.procesamiento_masivo.
   escalar_resultado_ia_en_memoria` y `atlas_core.mobile.
   procesar_envio_mobile`.
"""
from __future__ import annotations

from unittest.mock import Mock

import atlas_core.procesamiento_masivo as procesamiento_masivo
from atlas_core.ocr import BloqueOCR
from atlas_core.procesamiento_masivo import escalar_resultado_ia_en_memoria, procesar_archivo
from atlas_core.rutas.origen_documental import resolver_origen_documental


# ============================================================
# 1. Aislamiento de fallbacks geométricos independientes (RUT cliente)
# ============================================================


def test_fallo_en_asociacion_geometrica_cliente_no_impide_recuperar_rut_cliente(tmp_path, monkeypatch):
    """Caso real 472624: la foto es nítida y el RUT está impreso en la
    zona SEÑOR(ES)/R.U.T. -- si el paso de asociación geométrica de
    cliente/obra destino falla (por cualquier motivo real: catálogo
    corrupto, imagen atípica), el RUT del cliente debe seguir
    recuperándose igual -- son dos extractores independientes que antes
    compartían un solo try/except."""
    etiqueta_senor = BloqueOCR("SEÑOR(ES)", ((10, 100), (100, 100), (100, 130), (10, 130)), 0.9)
    etiqueta_rut = BloqueOCR("R.U.T.", ((10, 132), (70, 132), (70, 162), (10, 162)), 0.9)
    valor_rut = BloqueOCR("76.083.093-3", ((150, 130), (280, 130), (280, 160), (150, 160)), 0.9)

    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo, "leer_bloques_imagen",
        Mock(return_value=[etiqueta_senor, etiqueta_rut, valor_rut]),
    )
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value={
            "número de guía": "472624", "cliente": "No encontrado", "obra destino": "No encontrado",
            "RUT del cliente": "No encontrado",
        }),
    )

    def _asociacion_rota(_bloques):
        raise RuntimeError("catálogo de asociación geométrica corrupto (simulado)")

    monkeypatch.setattr(procesamiento_masivo, "_extraer_asociaciones_geometricas", _asociacion_rota)

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    # El paso que falló no recuperó nada (correcto -- no se inventa).
    assert resultado["cliente"] == "No encontrado"
    # ...pero el RUT del cliente, extractor totalmente independiente, se
    # recupera igual -- antes de este fix, la excepción de arriba lo
    # silenciaba también.
    assert resultado["rut_cliente"] == "76.083.093-3"


def test_fallo_en_rut_cliente_geometrico_no_impide_recuperar_chofer_geometrico(tmp_path, monkeypatch):
    """Misma clase, dirección inversa: un fallo en la recuperación
    geométrica de RUT cliente nunca debe impedir que la del chofer (otro
    extractor independiente) se intente."""
    etiqueta_retira = BloqueOCR("RETIRA", ((10, 300), (90, 300), (90, 330), (10, 330)), 0.9)
    valor_chofer = BloqueOCR("JAVIER PEREZ", ((150, 300), (300, 300), (300, 330), (150, 330)), 0.9)

    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo, "leer_bloques_imagen",
        Mock(return_value=[etiqueta_retira, valor_chofer]),
    )
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value={
            "número de guía": "472624", "cliente": "SODIMAC SA", "obra destino": "OBRA",
            "RUT del cliente": "No encontrado", "chofer": "No encontrado",
        }),
    )

    def _rut_cliente_roto(_bloques):
        raise RuntimeError("lectura geométrica de RUT cliente rota (simulado)")

    monkeypatch.setattr(procesamiento_masivo, "_extraer_rut_cliente_geometrico", _rut_cliente_roto)

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["rut_cliente"] == "No encontrado"
    assert resultado["chofer"] == "JAVIER PEREZ"


def test_asociaciones_geometricas_validas_se_conservan_aunque_identidad_recortada_falle_despues(tmp_path, monkeypatch):
    """Hallazgo Codex (2da ronda): el aislamiento anterior seguía
    incompleto -- `_extraer_asociaciones_geometricas` (que SÍ tuvo éxito)
    y `_extraer_identidad_cliente_recortada_geometrica` (que corre
    DESPUÉS, sólo como recuperación opcional adicional) compartían un
    mismo try/except. Si la segunda fallaba, la excepción cortaba antes
    de aplicar las asociaciones YA obtenidas por la primera -- un
    resultado válido se descartaba por el fallo de un paso opcional
    posterior, no relacionado. cliente/obra destino deben conservarse."""
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value={
            "número de guía": "472624", "cliente": "No encontrado", "obra destino": "No encontrado",
        }),
    )
    monkeypatch.setattr(
        procesamiento_masivo, "_extraer_asociaciones_geometricas",
        Mock(return_value={"cliente": "ACEROS SUR", "obra destino": "PLANTA CENTRAL"}),
    )

    def _identidad_recortada_rota(_bloques):
        raise RuntimeError("identidad de cliente recortada geométrica rota (simulado)")

    monkeypatch.setattr(
        procesamiento_masivo, "_extraer_identidad_cliente_recortada_geometrica", _identidad_recortada_rota,
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    # Las asociaciones ya válidas se aplican igual -- el fallo posterior
    # (paso opcional, independiente) no las descarta.
    assert resultado["cliente"] == "ACEROS SUR"
    assert resultado["obra_destino"] == "PLANTA CENTRAL"


# ============================================================
# 2. Membrete/casa matriz societaria -- ventana tolerante a bloques OCR
#    intercalados (nunca evidencia de origen, bajo ningún contexto)
# ============================================================


class _PlantaFalsa:
    def __init__(self, nombre, estado_calidad="CONFIRMADA", estado_vigencia="ACTIVA"):
        self.nombre = nombre
        self.estado_calidad = estado_calidad
        self.estado_vigencia = estado_vigencia


def test_membrete_casa_matriz_con_bloque_intercalado_sigue_excluyendo_la_planta():
    """Caso real 472624: "CASA MATRIZ PLANTA RENCA" impreso en el
    membrete -- si el proveedor OCR devuelve "CASA MATRIZ" y "PLANTA
    RENCA" como bloques SEPARADOS con un bloque de ruido intercalado
    entre ambos (logo/leyenda superpuesta en esa misma zona -- el orden
    de `textos` es el del proveedor OCR, no necesariamente el de lectura
    visual estricta), la adyacencia exacta token-a-token ya no detecta
    "CASA MATRIZ" -- "RENCA" se colaba como si fuera encabezado
    evaluable. La ventana tolerante sigue excluyéndolo."""
    textos = [
        "ACEROS AZA S.A",
        "CASA",
        "Acero Sostenible",  # ruido intercalado -- mismo patrón real observado en 472624
        "MATRIZ PLANTA RENCA, LA UNION 3070, RENCA SANTIAGO",
        "Sucursal Colina: Panamericana Norte KM. 18",
    ]
    plantas = [_PlantaFalsa("AZA COLINA"), _PlantaFalsa("AZA RENCA")]
    assert resolver_origen_documental(textos, plantas) is None


def test_membrete_casa_matriz_adyacente_sigue_funcionando_sin_cambios():
    """Control -- el caso original (472647/472648, sin ruido intercalado)
    sigue funcionando exactamente igual."""
    textos = ["ACEROS AZA S.A", "CASA MATRIZ PLANTA RENCA, LA UNION 3070, RENCA SANTIAGO"]
    plantas = [_PlantaFalsa("AZA COLINA"), _PlantaFalsa("AZA RENCA")]
    assert resolver_origen_documental(textos, plantas) is None


def test_encabezado_real_sin_membrete_sigue_resolviendo_la_planta():
    """Control -- una planta impresa ANTES de cualquier "CASA MATRIZ"/
    "SUCURSAL" (evidencia real de origen) sigue resolviendo con
    normalidad; la ventana más tolerante nunca excluye de más."""
    textos = ["GUIA DE DESPACHO", "PLANTA COLINA", "CASA MATRIZ PLANTA RENCA, LA UNION 3070"]
    plantas = [_PlantaFalsa("PLANTA COLINA"), _PlantaFalsa("AZA RENCA")]
    assert resolver_origen_documental(textos, plantas).nombre == "PLANTA COLINA"


# ============================================================
# 3. El placeholder interno de Mobile nunca escapa como si fuera un
#    `archivo` real (decisión duplicada + "guía original no disponible")
# ============================================================


class _OrquestadorInerte:
    """Nunca debería ni siquiera consultarse en estos tests (sin motivo
    B1-elegible) -- si lo fuera, abstiene limpio, sin red."""

    def resolver(self, contexto):
        from atlas_core.atlas_ia.orquestador import ABSTENCION_IA, CLASIFICACION_C, ResultadoOrquestacion
        return ResultadoOrquestacion(ABSTENCION_IA, CLASIFICACION_C, contexto, rondas=1)


def test_escalar_resultado_ia_en_memoria_nunca_filtra_el_placeholder_de_archivo():
    """Cuando Mobile todavía no conoce el `archivo` final del documento
    (normal -- se asigna recién al persistir la fila), el placeholder
    interno `"__mobile_actual__"` (necesario sólo para que el
    orquestador B1 identifique la fila actual en su CSV temporal) nunca
    debe aparecer en el valor de retorno."""
    datos = {"cliente": "SODIMAC SA", "motivos_revision_documento": ""}
    salida, _resumen = escalar_resultado_ia_en_memoria(datos, [], orquestador_ia=_OrquestadorInerte())
    assert salida.get("archivo", "") == ""


def test_escalar_resultado_ia_en_memoria_preserva_un_archivo_real_ya_conocido():
    """Control -- si el `archivo` YA viene poblado (caso del lote de
    Desktop, que siempre conoce el nombre real antes de escalar a B1),
    nunca se pisa ni se toca."""
    datos = {"archivo": "guia_real.jpg", "cliente": "SODIMAC SA", "motivos_revision_documento": ""}
    salida, _resumen = escalar_resultado_ia_en_memoria(datos, [], orquestador_ia=_OrquestadorInerte())
    assert salida.get("archivo") == "guia_real.jpg"


def test_fallback_de_archivo_en_mobile_resuelve_al_identificador_real_tras_el_fix():
    """Ejercita el mismo fallback exacto que usa
    `mobile.procesar_envio_mobile` al detectar `ORIGEN_NO_CONFIRMADO`
    (`archivo=str(datos.get("archivo") or identificador)`) -- con el
    placeholder ya no filtrándose, este fallback vuelve a resolver al
    identificador REAL del envío (el mismo que usará después la
    reconciliación por lote para la misma guía), en vez de quedar
    atascado en `"__mobile_actual__"`."""
    envio_id = "286f5007-f9eb-4ac1-99a5-148184a52aec"
    identificador = f"mobile/{envio_id}/original.jpg"
    datos, _resumen = escalar_resultado_ia_en_memoria(
        {"cliente": "SODIMAC SA", "motivos_revision_documento": ""}, [], orquestador_ia=_OrquestadorInerte(),
    )
    archivo_resuelto = str(datos.get("archivo") or identificador)
    assert archivo_resuelto == identificador
