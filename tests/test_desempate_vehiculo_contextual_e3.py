"""Bloque VEHÍCULO E3 -- DESEMPATE CONTEXTUAL de patente/vehículo.

Un error pequeño de OCR no puede convertir conocimiento fuertemente
establecido en desconocido; pero si hay DOS candidatos realmente
plausibles Atlas se abstiene y pregunta. La resolución sigue una
JERARQUÍA de evidencia (nunca una suma ciega de puntos):

  1. confirmación humana / decisión humana previa del mismo RUT y campo
  2. corroboración documental independiente (>= 1 transporte distinto)
  3. similitud OCR calibrada -- sólo señal secundaria, nunca domina sola

`convergencia_vehiculo` delega esa jerarquía en `evaluar_evidencia_
patente` (el Motor) y sólo añade guardarraíles: distancia OCR tolerada
por la fuerza del ganador, contradicción documental, y "si el Motor no
resolvió inequívocamente -> revisión".

Caso real congelado que motiva el bloque: guía 472477 / viaje
0000354870, chofer CARLOS SIMON (RUT 15.489.424-1), OCR rampla "JD8629";
candidatos JD8659 (confirmada por un humano PARA este RUT) y JE8659 (un
transporte independiente real, un tier por debajo) -> resuelve JD8659,
NO por la regla de caracteres "2↔5" (que sigue fuera de la tabla OCR).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from atlas_core.atlas_ia.contratos import (
    ContextoRazonamiento,
    HipotesisIA,
    MOTIVO_VALOR_NO_RESPALDADO,
    RESULTADO_HIPOTESIS_PROPUESTA,
    calcular_hipotesis_id,
)
from atlas_core.atlas_ia.convergencia import (
    CONTRADICCION_FUERTE,
    MANTENER_REVISION,
    METODO_ABSTENCION_AMBIGUA,
    METODO_CONTEXTO_DETERMINISTA,
    RESOLVER_SILENCIOSO,
)
from atlas_core.atlas_ia.evidencia_dominios import convergencia_vehiculo, evidencia_vehiculo_interna
from atlas_core.atlas_ia.validadores import validar_hipotesis_multicampo
from atlas_core.capacidades_reevaluacion import (
    DOMINIO_VEHICULO,
    REGISTRO_CAPACIDADES,
    capacidades_avanzadas,
)
from atlas_core.catalogo_vehiculos import TipoVehiculo, cargar_catalogo_vehiculos, confirmar_vehiculo
from atlas_core.decisiones_pendientes import (
    RESULTADO_ABSTENCION,
    RESULTADO_RESUELTO_AUTOMATICAMENTE,
    RESULTADO_SUGERENCIA_HUMANA,
    enriquecer_decisiones_vehiculo,
    evaluar_evidencia_patente,
)

RUT_CARLOS = "15.489.424-1"


# --------------------------------------------------------------------------
# Fixtures mínimas -- catálogos tmp reales, nunca G:\
# --------------------------------------------------------------------------


def _cat(tmp_path):
    c = tmp_path / "catalogos_privados"
    c.mkdir(parents=True, exist_ok=True)
    return c


def _confirmar(cat, patente, tipo=TipoVehiculo.CARRO, *, rut_chofer_asociado=""):
    ruta = cat / "vehiculos.json"
    if not ruta.exists():
        ruta.write_text(json.dumps({"version": 1, "vehiculos": []}), encoding="utf-8")
    return confirmar_vehiculo(
        ruta, patente=patente, tipo=tipo, actor="JAVIER_MBT", fuente_decision="TEST",
        fecha=datetime.now(timezone.utc), rut_chofer_asociado=rut_chofer_asociado,
    )


def _vehiculos(cat):
    return list(cargar_catalogo_vehiculos(cat / "vehiculos.json").homologables())


def _fila(*, patente_rampla, rut_chofer=RUT_CARLOS, numero_transporte, numero_guia,
          estado_procesamiento="OK", patente_tracto=""):
    return {
        "patente_rampla": patente_rampla, "patente_tracto": patente_tracto,
        "rut_chofer": rut_chofer, "numero_transporte": numero_transporte,
        "numero_guia": numero_guia, "estado_procesamiento": estado_procesamiento,
    }


def _ledger_seleccion(patente_canonica, *, rut_chofer=RUT_CARLOS, campo="patente_rampla"):
    return {
        "tipo": "VEHICULO_DESCONOCIDO", "accion": "SELECCIONAR_OTRA_PATENTE",
        "campo": campo, "rut_chofer": rut_chofer, "tipo_vehiculo": "CARRO",
        "patente_canonica": patente_canonica,
    }


# ==========================================================================
# 1. Candidato conocido único + error OCR pequeño + relación fuerte -> resuelve
# ==========================================================================


def test_1_candidato_unico_confirmado_mas_error_ocr_pequeno_resuelve(tmp_path):
    cat = _cat(tmp_path)
    _confirmar(cat, "JD8659", rut_chofer_asociado=RUT_CARLOS)
    r = convergencia_vehiculo(
        campo="patente_rampla", valor_documental="JD8629", rut_chofer=RUT_CARLOS,
        numero_transporte="0000354870", filas=[], carpeta_catalogos=cat,
    )
    assert r.decision == RESOLVER_SILENCIOSO
    assert r.valor_canonico == "JD8659"
    assert r.valor_ocr_original == "JD8629"  # OCR nunca se pierde
    assert r.confianza == "ALTA"
    assert r.desempate["metodo"] == METODO_CONTEXTO_DETERMINISTA
    assert r.desempate["valor_canonico_aplicado"] == "JD8659"


# ==========================================================================
# 2. Dos candidatos con historial, uno con evidencia contextual dominante
#    -> resuelve el dominante  (CASO REAL 472477)
# ==========================================================================


def test_2_dos_con_historial_pero_uno_dominante_resuelve_dominante(tmp_path):
    cat = _cat(tmp_path)
    _confirmar(cat, "JD8659", rut_chofer_asociado=RUT_CARLOS)   # tier 1: confirmación humana del RUT
    _confirmar(cat, "JE8659")                                   # confirmada, sin RUT asociado
    filas = [
        _fila(patente_rampla="JE8659", numero_transporte="0000352376", numero_guia="464698"),
        _fila(patente_rampla="JE8659", numero_transporte="0000352376", numero_guia="464700"),
        _fila(patente_rampla="JD8629", numero_transporte="0000354870", numero_guia="472477"),
    ]
    ev = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="JD8629", rut_chofer=RUT_CARLOS,
        tipo_esperado="CARRO", numero_transporte_actual="0000354870",
        filas=filas, vehiculos=_vehiculos(cat),
    )
    assert ev["resultado"] == RESULTADO_RESUELTO_AUTOMATICAMENTE
    assert ev["candidatos"][0]["patente"] == "JD8659"
    assert ev["candidatos"][0]["nivel"] == "CONFIRMACION_HUMANA"
    assert ev["candidatos"][1]["nivel"] == "DOCUMENTAL_INDEPENDIENTE"  # JE8659, un tier por debajo

    r = convergencia_vehiculo(
        campo="patente_rampla", valor_documental="JD8629", rut_chofer=RUT_CARLOS,
        numero_transporte="0000354870", filas=filas, carpeta_catalogos=cat,
    )
    assert r.decision == RESOLVER_SILENCIOSO and r.valor_canonico == "JD8659"
    patentes_traza = {c["patente"] for c in r.desempate["candidatos"]}
    assert patentes_traza == {"JD8659", "JE8659"}  # ambos quedan en la traza de observabilidad


# ==========================================================================
# 3. Dos candidatos realmente plausibles (empate de nivel) -> abstiene
# ==========================================================================


def test_3_dos_candidatos_plausibles_empatados_abstiene(tmp_path):
    cat = _cat(tmp_path)
    _confirmar(cat, "JD8659", rut_chofer_asociado=RUT_CARLOS)
    _confirmar(cat, "JD8658", rut_chofer_asociado=RUT_CARLOS)  # también confirmada PARA este RUT
    r = convergencia_vehiculo(
        campo="patente_rampla", valor_documental="JD8629", rut_chofer=RUT_CARLOS,
        numero_transporte="T", filas=[], carpeta_catalogos=cat,
    )
    assert r.decision == MANTENER_REVISION
    assert set(r.competidores) == {"JD8658", "JD8659"}
    assert r.desempate["metodo"] == METODO_ABSTENCION_AMBIGUA


# ==========================================================================
# 4. Variante radical (GFZW99) -> abstiene aunque el RUT tenga confirmación
# ==========================================================================


def test_4_variante_radical_abstiene(tmp_path):
    cat = _cat(tmp_path)
    _confirmar(cat, "JD8659", rut_chofer_asociado=RUT_CARLOS)
    r = convergencia_vehiculo(
        campo="patente_rampla", valor_documental="GFZW99", rut_chofer=RUT_CARLOS,
        numero_transporte="T", filas=[], carpeta_catalogos=cat,
    )
    assert r.decision == MANTENER_REVISION


# ==========================================================================
# 5. Parecido OCR pero el valor documental ES una patente canónica real
#    y distinta -> contradicción, nunca autocorrección
# ==========================================================================


def test_5_contradiccion_documental_fuerte_rechaza(tmp_path):
    cat = _cat(tmp_path)
    _confirmar(cat, "JD8659", rut_chofer_asociado=RUT_CARLOS)
    _confirmar(cat, "JE8659")  # patente real de OTRO vehículo -- el OCR leyó exactamente ésta
    r = convergencia_vehiculo(
        campo="patente_rampla", valor_documental="JE8659", rut_chofer=RUT_CARLOS,
        numero_transporte="T", filas=[], carpeta_catalogos=cat,
    )
    assert r.decision == CONTRADICCION_FUERTE
    assert r.desempate["contradicciones"]


# ==========================================================================
# 6. Un par tracto↔rampla histórico NUEVO del chofer aporta evidencia
#    (candidato con PAREJA_TRACTO_RAMPLA_HISTORICA) y frena la resolución
# ==========================================================================


def test_6_par_tracto_rampla_historico_aporta_evidencia(tmp_path):
    cat = _cat(tmp_path)
    _confirmar(cat, "JD8659", rut_chofer_asociado=RUT_CARLOS)
    _confirmar(cat, "VP8521", tipo=TipoVehiculo.TRACTO)
    _confirmar(cat, "JZ1000")  # rampla real vista SÓLO en una relación histórica
    decision = {
        "tipo": "VEHICULO_DESCONOCIDO", "campo": "patente_rampla",
        "documento": {"numero_guia": "472477", "numero_transporte": "0000354870"},
        "valor_documental": "JD8629", "tipo_vehiculo_propuesto": "CARRO",
        "acciones_permitidas": ["REGISTRAR", "NO_REGISTRAR", "POSPONER"],
    }
    filas = [_fila(patente_rampla="JD8629", numero_transporte="0000354870", numero_guia="472477")]
    rel = [{
        "rut_chofer": RUT_CARLOS, "numero_transporte": "0000350000", "numero_guia": "460001",
        "patente_tracto": "VP8521", "patente_rampla": "JZ1000",
    }]
    out = enriquecer_decisiones_vehiculo(
        decisiones=[decision], filas=filas, vehiculos=_vehiculos(cat), relaciones_historicas=rel,
    )[0]
    patentes = {c["patente"] for c in out["candidatos"]}
    assert "JZ1000" in patentes
    jz = next(c for c in out["candidatos"] if c["patente"] == "JZ1000")
    assert "PAREJA_TRACTO_RAMPLA_HISTORICA" in jz["evidencias"]
    # Introduce un competidor nuevo que el Motor no vio -> baja a revisión.
    assert out["evaluacion_evidencia"]["resultado"] == RESULTADO_SUGERENCIA_HUMANA


# ==========================================================================
# 7. Historial antiguo NO vence a la evidencia directa reciente
# ==========================================================================


def test_7_historial_antiguo_no_vence_confirmacion_directa(tmp_path):
    cat = _cat(tmp_path)
    _confirmar(cat, "JD8659", rut_chofer_asociado=RUT_CARLOS)  # directa
    _confirmar(cat, "JE8659")
    # JE8659 con MÁS guías (3) pero UN solo transporte -> sigue un tier abajo.
    filas = [
        _fila(patente_rampla="JE8659", numero_transporte="0000352376", numero_guia="464698"),
        _fila(patente_rampla="JE8659", numero_transporte="0000352376", numero_guia="464699"),
        _fila(patente_rampla="JE8659", numero_transporte="0000352376", numero_guia="464700"),
        _fila(patente_rampla="JD8629", numero_transporte="0000354870", numero_guia="472477"),
    ]
    ev = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="JD8629", rut_chofer=RUT_CARLOS,
        tipo_esperado="CARRO", numero_transporte_actual="0000354870",
        filas=filas, vehiculos=_vehiculos(cat),
    )
    assert ev["resultado"] == RESULTADO_RESUELTO_AUTOMATICAMENTE
    assert ev["candidatos"][0]["patente"] == "JD8659"
    je = next(c for c in ev["candidatos"] if c["patente"] == "JE8659")
    assert je["transportes_independientes"] == 1  # 3 guías, 1 evento -> no es "3 corroboraciones"


# ==========================================================================
# 8. La frecuencia SOLA (varias guías, un transporte) no basta para resolver
# ==========================================================================


def test_8_frecuencia_sola_no_basta(tmp_path):
    cat = _cat(tmp_path)
    _confirmar(cat, "JX4000")  # confirmada/activa pero SIN confirmación asociada al RUT
    filas = [
        _fila(patente_rampla="JX4000", numero_transporte="0000340000", numero_guia="450001"),
        _fila(patente_rampla="JX4000", numero_transporte="0000340000", numero_guia="450002"),
        _fila(patente_rampla="JX4000", numero_transporte="0000340000", numero_guia="450003"),
        _fila(patente_rampla="AB1200", numero_transporte="0000354870", numero_guia="472477"),
    ]
    ev = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="AB1200", rut_chofer=RUT_CARLOS,
        tipo_esperado="CARRO", numero_transporte_actual="0000354870",
        filas=filas, vehiculos=_vehiculos(cat),
    )
    # 3 guías pero 1 solo transporte independiente y sin similitud OCR con
    # "AB1200" -> nunca RESUELTO_AUTOMATICAMENTE.
    assert ev["resultado"] != RESULTADO_RESUELTO_AUTOMATICAMENTE
    r = convergencia_vehiculo(
        campo="patente_rampla", valor_documental="AB1200", rut_chofer=RUT_CARLOS,
        numero_transporte="0000354870", filas=filas, carpeta_catalogos=cat,
    )
    assert r.decision == MANTENER_REVISION


# ==========================================================================
# 9. Una decisión humana previa (ledger) del mismo RUT/campo pesa como
#    confirmación humana -- vence a un parecido OCR débil
# ==========================================================================


def test_9_decision_humana_previa_del_ledger_pesa(tmp_path):
    cat = _cat(tmp_path)
    _confirmar(cat, "JD8659")  # en catálogo, SIN rut_chofer_asociado
    ledger = [_ledger_seleccion("JD8659", rut_chofer=RUT_CARLOS)]
    ev = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="JD8629", rut_chofer=RUT_CARLOS,
        tipo_esperado="CARRO", numero_transporte_actual="0000354870",
        filas=[], vehiculos=_vehiculos(cat), decisiones_aplicadas=ledger,
    )
    assert ev["resultado"] == RESULTADO_RESUELTO_AUTOMATICAMENTE
    gan = ev["candidatos"][0]
    assert gan["patente"] == "JD8659" and gan["nivel"] == "CONFIRMACION_HUMANA"
    assert "DECISION_HUMANA_PREVIA_MISMO_RUT" in gan["evidencias"]

    # Sin la decisión previa (ledger vacío) y sin confirmación de RUT ni
    # historial: la misma patente NO alcanza a resolver sola.
    ev_sin = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="JD8629", rut_chofer=RUT_CARLOS,
        tipo_esperado="CARRO", numero_transporte_actual="0000354870",
        filas=[], vehiculos=_vehiculos(cat), decisiones_aplicadas=[],
    )
    assert ev_sin["resultado"] in (RESULTADO_SUGERENCIA_HUMANA, RESULTADO_ABSTENCION)


def test_9b_ledger_de_otro_rut_no_cuenta(tmp_path):
    cat = _cat(tmp_path)
    _confirmar(cat, "JD8659")
    ledger = [_ledger_seleccion("JD8659", rut_chofer="11.111.111-1")]  # otro chofer
    ev = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="JD8629", rut_chofer=RUT_CARLOS,
        tipo_esperado="CARRO", numero_transporte_actual="0000354870",
        filas=[], vehiculos=_vehiculos(cat), decisiones_aplicadas=ledger,
    )
    assert ev["resultado"] != RESULTADO_RESUELTO_AUTOMATICAMENTE


# ==========================================================================
# 10 / 11. B1 -- sólo puede aplicar una respuesta respaldada por evidencia
#          interna canónica; nunca "el más parecido" sin respaldo
# ==========================================================================


def _contexto(evs):
    return ContextoRazonamiento(
        campo="patente_rampla", valor_documental="JD8629", rut_chofer=RUT_CARLOS,
        numero_guia="472477", numero_transporte="0000354870", evidencias=tuple(evs),
        resultado_motor="REQUIERE_REVISION",
    )


def _propuesta(contexto, valor):
    return HipotesisIA(
        hipotesis_id=calcular_hipotesis_id(contexto, valor), campo=contexto.campo,
        valor_observado=contexto.valor_documental, valor_propuesto=valor,
        resultado=RESULTADO_HIPOTESIS_PROPUESTA,
    )


def test_10_b1_no_puede_aplicar_sin_evidencia_interna(tmp_path):
    cat = _cat(tmp_path)
    _confirmar(cat, "JD8659", rut_chofer_asociado=RUT_CARLOS)
    evs = evidencia_vehiculo_interna(
        campo="patente_rampla", valor_documental="JD8629", rut_chofer=RUT_CARLOS,
        numero_transporte="0000354870", filas=[], carpeta_catalogos=cat,
    )
    contexto = _contexto(evs)
    # "JX1234" no aparece en ninguna evidencia interna -> bloqueada.
    res = validar_hipotesis_multicampo(_propuesta(contexto, "JX1234"), contexto)
    assert not res.aceptada and res.motivo_rechazo == MOTIVO_VALOR_NO_RESPALDADO


def test_11_b1_puede_aplicar_cuando_evidencia_interna_canonica_converge(tmp_path):
    cat = _cat(tmp_path)
    _confirmar(cat, "JD8659", rut_chofer_asociado=RUT_CARLOS)
    evs = evidencia_vehiculo_interna(
        campo="patente_rampla", valor_documental="JD8629", rut_chofer=RUT_CARLOS,
        numero_transporte="0000354870", filas=[], carpeta_catalogos=cat,
    )
    assert any(e.valor == "JD8659" and e.es_decision_humana for e in evs)
    contexto = _contexto(evs)
    assert validar_hipotesis_multicampo(_propuesta(contexto, "JD8659"), contexto).aceptada


# ==========================================================================
# 12. Retroactividad -- subir la versión de VEHICULO la marca para reevaluar
# ==========================================================================


def test_12_bump_vehiculo_dispara_reevaluacion_retroactiva():
    assert REGISTRO_CAPACIDADES[DOMINIO_VEHICULO].version >= 3
    persistidas = {d: c.version for d, c in REGISTRO_CAPACIDADES.items()}
    persistidas[DOMINIO_VEHICULO] = 2  # una operación migrada antes de E3
    avanzadas = capacidades_avanzadas(persistidas)
    assert DOMINIO_VEHICULO in avanzadas
    assert avanzadas[DOMINIO_VEHICULO] == (2, REGISTRO_CAPACIDADES[DOMINIO_VEHICULO].version)
    # y VEHICULO_DESCONOCIDO / PATENTE_SIN_HOMOLOGAR quedan en su alcance
    cap = REGISTRO_CAPACIDADES[DOMINIO_VEHICULO]
    assert "VEHICULO_DESCONOCIDO" in cap.tipos_decision
    assert "PATENTE_SIN_HOMOLOGAR" in cap.motivos_documentales


def test_12b_sin_bump_no_hay_reevaluacion():
    persistidas = {d: c.version for d, c in REGISTRO_CAPACIDADES.items()}
    assert DOMINIO_VEHICULO not in capacidades_avanzadas(persistidas)


# ==========================================================================
# 13. Idempotencia -- volver a evaluar con los mismos datos da lo mismo
# ==========================================================================


def test_13_idempotente(tmp_path):
    cat = _cat(tmp_path)
    _confirmar(cat, "JD8659", rut_chofer_asociado=RUT_CARLOS)
    _confirmar(cat, "JE8659")
    filas = [
        _fila(patente_rampla="JE8659", numero_transporte="0000352376", numero_guia="464698"),
        _fila(patente_rampla="JD8629", numero_transporte="0000354870", numero_guia="472477"),
    ]
    kw = dict(campo="patente_rampla", valor_documental="JD8629", rut_chofer=RUT_CARLOS,
              numero_transporte="0000354870", filas=filas, carpeta_catalogos=cat)
    a = convergencia_vehiculo(**kw)
    b = convergencia_vehiculo(**kw)
    assert (a.decision, a.valor_canonico, a.confianza) == (b.decision, b.valor_canonico, b.confianza)
    assert a.decision == RESOLVER_SILENCIOSO and a.valor_canonico == "JD8659"


# ==========================================================================
# 14. Nunca toca un vehículo/valor ya correcto (el OCR ya es la canónica)
# ==========================================================================


def test_14_no_toca_patente_ya_correcta(tmp_path):
    cat = _cat(tmp_path)
    _confirmar(cat, "JD8659", rut_chofer_asociado=RUT_CARLOS)
    # El documento ya trae la canónica exacta -> no hay nada que "resolver".
    r = convergencia_vehiculo(
        campo="patente_rampla", valor_documental="JD8659", rut_chofer=RUT_CARLOS,
        numero_transporte="0000354870", filas=[], carpeta_catalogos=cat,
    )
    assert r.decision != RESOLVER_SILENCIOSO
    ev = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="JD8659", rut_chofer=RUT_CARLOS,
        tipo_esperado="CARRO", numero_transporte_actual="0000354870",
        filas=[], vehiculos=_vehiculos(cat),
    )
    assert "JD8659" not in {c["patente"] for c in ev["candidatos"]}  # nunca compite consigo misma


# ==========================================================================
# 15. La regla de caracteres "2↔5" sigue FUERA de la tabla OCR global
# ==========================================================================


def test_15_confusion_2_5_no_esta_en_la_tabla_ocr():
    from atlas_core.catalogo_vehiculos import _CONFUSIONES_OCR, _diferencia_ocr_segura

    assert frozenset({"2", "5"}) not in _CONFUSIONES_OCR
    assert _diferencia_ocr_segura("JD8629", "JD8659") is False
