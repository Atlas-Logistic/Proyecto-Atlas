"""Bloque B1 OPERACIONAL V1 -- configuración local + prueba real
controlada de razonamiento.

Bug real encontrado durante la validación con el caso real 472593: al
REPROCESAR/REVALIDAR un documento ya persistido (mismo mecanismo que
`atlas_core.mobile.procesar_envio_mobile` reutiliza para correcciones
focales -- ver bloques RUT CLIENTE V1 / ASOCIACIÓN MOBILE V2), la propia
fila anterior de ESE documento ya vive en el `historial` (dataset real)
que arma `escalar_resultado_ia_en_memoria`. Como es un dict RECONSTRUIDO
a partir del CSV (nunca el mismo objeto que la fila actual), la
comparación por identidad (`is`) de
`recopilar_evidencia_documentos_relacionados` nunca lo detectaba -- el
documento terminaba "corroborándose" con su propia lectura anterior,
contada como evidencia HISTÓRICA independiente (`independencia=1`).
Confirmado con datos reales: la llamada real a B1 sobre 472593
(OBRA_DESTINO_SIN_CORROBORAR) trajo como única evidencia
`documento:mobile/36e7aa53-214e-48b0-a96c-14989b60e9aa/original.jpg` --
el archivo de la PROPIA guía 472593."""
from __future__ import annotations

from atlas_core.atlas_ia.registro_problemas import recopilar_evidencia_documentos_relacionados


def _fila(**overrides):
    base = {
        "archivo": "mobile/envio-1/original.jpg", "numero_guia": "472593",
        "numero_transporte": "0000355419", "fecha": "25-08-2026",
        "chofer": "LEANDRO TOLEDO", "patente_tracto": "BKYK63",
        "obra_destino": "EMPRESA CONST SIGRO",
    }
    base.update(overrides)
    return base


def test_reprocesar_un_documento_no_lo_corrobora_con_su_propia_fila_anterior():
    """Caso real 472593: el historial (dataset) ya trae la fila anterior
    de ESTE mismo documento (mismo numero_guia) -- nunca debe contarse
    como 'documento relacionado' de sí mismo."""
    fila_actual = _fila()
    fila_propia_anterior = _fila()  # dict DISTINTO, mismos datos -- el propio historial de este documento
    historial = [fila_propia_anterior]

    recolector = recopilar_evidencia_documentos_relacionados("obra_destino")
    evidencias = recolector(fila_actual, historial)

    assert evidencias == ()


def test_otro_documento_real_con_las_mismas_señales_si_corrobora():
    """Control: un documento REALMENTE distinto (otra guía) que comparte
    suficientes señales de vecindad sigue aportando evidencia -- el fix
    no rompe la corroboración real entre documentos hermanos."""
    fila_actual = _fila()
    fila_hermana = _fila(archivo="mobile/envio-2/original.jpg", numero_guia="472594")
    historial = [fila_hermana]

    recolector = recopilar_evidencia_documentos_relacionados("obra_destino")
    evidencias = recolector(fila_actual, historial)

    assert len(evidencias) == 1
    assert evidencias[0].identificador == "documento:mobile/envio-2/original.jpg"
    assert evidencias[0].valor == "EMPRESA CONST SIGRO"
    assert evidencias[0].tipo_fuente == "HISTORICO"


def test_sin_numero_de_guia_sigue_usando_identidad_de_objeto_como_antes():
    """Si `numero_guia` no está presente (nunca debería faltar en
    producción, pero el recolector no debe reventar), el chequeo nuevo
    simplemente no aplica -- se mantiene el comportamiento previo
    (identidad de objeto)."""
    fila_actual = {"archivo": "x.jpg", "obra_destino": "EMPRESA CONST SIGRO", "fecha": "25-08-2026", "numero_transporte": "1", "chofer": "A", "patente_tracto": "AB1234"}
    otra_sin_guia = dict(fila_actual)  # mismas señales, sin numero_guia en ninguno de los dos
    historial = [otra_sin_guia]

    recolector = recopilar_evidencia_documentos_relacionados("obra_destino")
    evidencias = recolector(fila_actual, historial)

    # Coincide en todas las señales de vecindad -- sin numero_guia con el
    # que distinguir "mismo documento" de "documento hermano idéntico",
    # se conserva el criterio histórico (señales), nunca se rompe.
    assert len(evidencias) == 1
