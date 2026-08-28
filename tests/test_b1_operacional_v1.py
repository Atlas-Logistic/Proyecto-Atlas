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


# ============================================================
# Bloque M3 -- caso real 472623/472624 (transporte 0000355433, rampla
# JB6878 vs J36878): la evidencia de documento relacionado, para campos
# de patente, expone además el hecho general y determinista de si el
# valor calza con una forma real de patente chilena -- nunca decide
# sola, sólo informa a B1 (que no puede usar "conocimiento general del
# mundo" por política de sistema).
# ============================================================


def test_documento_relacionado_patente_agrega_evidencia_de_formato_estandar():
    fila_actual = _fila(numero_guia="472624", patente_rampla="J36878")
    fila_hermana = _fila(
        archivo="mobile/envio-hermano/original.jpg", numero_guia="472623", patente_rampla="JB6878",
    )
    recolector = recopilar_evidencia_documentos_relacionados("patente_rampla")
    evidencias = recolector(fila_actual, [fila_hermana])

    assert len(evidencias) == 1
    assert evidencias[0].valor == "JB6878"
    assert evidencias[0].a_favor == ("FORMATO_PATENTE_CHILENA_ESTANDAR",)


def test_documento_relacionado_patente_sin_formato_estandar_no_agrega_el_codigo():
    """Control -- si el valor del documento hermano TAMPOCO calza con una
    forma real de patente chilena, nunca se le agrega el código a_favor
    (nunca se inventa una señal positiva que no corresponde)."""
    fila_actual = _fila(numero_guia="472623", patente_rampla="JB6878")
    fila_hermana = _fila(
        archivo="mobile/envio-hermano/original.jpg", numero_guia="472624", patente_rampla="J36878",
    )
    recolector = recopilar_evidencia_documentos_relacionados("patente_rampla")
    evidencias = recolector(fila_actual, [fila_hermana])

    assert len(evidencias) == 1
    assert evidencias[0].valor == "J36878"
    assert evidencias[0].a_favor == ()


def test_documento_relacionado_campo_no_patente_nunca_agrega_el_codigo_de_formato():
    """El código de formato es específico de patente_tracto/patente_rampla
    -- nunca se cuela para otros campos (obra_destino, cliente, etc.)."""
    fila_actual = _fila(numero_guia="472624")
    fila_hermana = _fila(archivo="mobile/envio-hermano/original.jpg", numero_guia="472623")
    recolector = recopilar_evidencia_documentos_relacionados("obra_destino")
    evidencias = recolector(fila_actual, [fila_hermana])

    assert len(evidencias) == 1
    assert evidencias[0].a_favor == ()


def test_regresion_ambiguedad_patente_no_se_resuelve_sola_aunque_haya_evidencia_de_formato():
    """REGRESIÓN obligatoria del bloque M3 -- reconstruye el caso real
    472623/472624 a nivel de `ContextoRazonamiento`/`HipotesisIA` para
    probar que la nueva evidencia de formato NUNCA es, por sí sola,
    evidencia "suficiente" para que B1 se autoconfirme.

    Escenario B/3 real: el documento 472624 leyó "J36878"; su hermano
    472623 (mismo transporte 0000355433) leyó "JB6878", que SÍ calza con
    un formato real de patente chilena (evidencia nueva de este bloque).
    Aun así, si el proveedor propusiera reconfirmar el propio valor no
    corroborado del documento ("J36878"), el validador V2 universal
    (`valor_propuesto not in contexto.valores_evidencia()`) debe
    rechazarlo -- "J36878" no vive en ninguna evidencia reunida, sólo en
    la lectura propia sin corroborar. Ni la evidencia de formato ni
    ninguna otra señal nueva de este bloque debilitan esa barrera."""
    from atlas_core.atlas_ia.contratos import (
        ContextoRazonamiento, EvidenciaIA, HipotesisIA, RESULTADO_HIPOTESIS_PROPUESTA,
        MOTIVO_VALOR_NO_RESPALDADO, calcular_hipotesis_id,
    )
    from atlas_core.atlas_ia.validadores import validar_hipotesis_vehiculo

    evidencia_hermana = EvidenciaIA(
        identificador="documento:mobile/9fb768e4-b385-4beb-a1ca-e8baa306cefe/original.jpg",
        campo="patente_rampla", valor="JB6878", tipo_fuente="HISTORICO",
        nivel="DOCUMENTO_RELACIONADO", a_favor=("FORMATO_PATENTE_CHILENA_ESTANDAR",),
    )
    contexto = ContextoRazonamiento(
        campo="patente_rampla", valor_documental="J36878", rut_chofer="",
        numero_guia="472624", numero_transporte="0000355433", evidencias=(evidencia_hermana,),
    )

    # El proveedor intenta reconfirmar su propia lectura no corroborada.
    hipotesis_autoconfirmacion = HipotesisIA(
        hipotesis_id=calcular_hipotesis_id(contexto, "J36878"), campo="patente_rampla",
        valor_observado="J36878", valor_propuesto="J36878", resultado=RESULTADO_HIPOTESIS_PROPUESTA,
    )
    resultado = validar_hipotesis_vehiculo(hipotesis_autoconfirmacion, contexto)

    assert resultado.aceptada is False
    assert resultado.motivo_rechazo == MOTIVO_VALOR_NO_RESPALDADO

    # Control positivo: proponer el valor que SÍ tiene evidencia (la del
    # hermano, ahora con el código de formato estándar) pasa la barrera
    # estructural -- pero "aceptada=True" nunca implica autonomía ni
    # aplicación automática (ver contratos.py); sigue siendo sólo una
    # hipótesis auditable a favor de una decisión humana/incidencia.
    hipotesis_valor_con_evidencia = HipotesisIA(
        hipotesis_id=calcular_hipotesis_id(contexto, "JB6878"), campo="patente_rampla",
        valor_observado="J36878", valor_propuesto="JB6878", resultado=RESULTADO_HIPOTESIS_PROPUESTA,
    )
    resultado_con_evidencia = validar_hipotesis_vehiculo(hipotesis_valor_con_evidencia, contexto)

    assert resultado_con_evidencia.aceptada is True
