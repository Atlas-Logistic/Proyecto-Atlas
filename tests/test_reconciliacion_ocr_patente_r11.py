"""Bloque R11 -- reconciliación OCR de patente contra el catálogo completo,
general (nunca hardcodeada por guía/chofer/patente).

Caso real que motiva este bloque: guía 472247 (Rodrigo Nahuelñir),
patente_rampla OCR "JE4288" -- ningún documento hermano de este RUT existe
(ni en el dataset ni en el ledger), así que el historial de chofer
(`_transportes_por_patente_de_chofer`/`_vehiculos_confirmados_para_rut`)
nunca podía surgir ninguna candidata, aunque "JF4288" ya estuviera
CONFIRMADO/ACTIVO como CARRO en el catálogo -- una única confusión OCR
calibrada (E/F) de distancia. Antes de este bloque, Atlas generaba
VEHICULO_DESCONOCIDO liso, sin ninguna sugerencia -- exactamente lo que el
caso real pedía evitar (nunca registrar la entidad falsa JE4288)."""
from __future__ import annotations

from datetime import datetime, timezone

from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.catalogo_vehiculos import TipoVehiculo, cargar_catalogo_vehiculos, confirmar_vehiculo
from atlas_core.decisiones_pendientes import (
    RESULTADO_ABSTENCION, RESULTADO_SUGERENCIA_HUMANA, evaluar_evidencia_patente, generar_artefacto,
)

FECHA = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _confirmar(ruta_catalogo, *, patente, tipo, referencia="TEST"):
    import json
    if not ruta_catalogo.exists():
        ruta_catalogo.write_text(json.dumps({"version": 1, "vehiculos": []}), encoding="utf-8")
    confirmar_vehiculo(ruta_catalogo, patente=patente, tipo=tipo, actor="TEST", fuente_decision=referencia, fecha=FECHA)


def _homologables(ruta_catalogo):
    return cargar_catalogo_vehiculos(ruta_catalogo).homologables()


# --- 1. Caso real: sin historial de RUT, único candidato OCR-seguro ---

def test_je4288_sin_historial_rut_reconcilia_con_jf4288_via_catalogo(tmp_path):
    catalogo = tmp_path / "vehiculos.json"
    _confirmar(catalogo, patente="JF4288", tipo=TipoVehiculo.CARRO.value)

    resultado = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="JE4288", rut_chofer="15.454.297-3",
        tipo_esperado="CARRO", numero_transporte_actual="0000354576",
        filas=[], vehiculos=_homologables(catalogo),
    )
    assert resultado["resultado"] == RESULTADO_SUGERENCIA_HUMANA
    assert [c["patente"] for c in resultado["candidatos"]] == ["JF4288"]
    candidato = resultado["candidatos"][0]
    # Nunca "RUT_CHOFER_COINCIDE" -- ningún documento de este chofer lo
    # corrobora, sólo la similitud OCR calibrada contra el catálogo.
    assert "RUT_CHOFER_COINCIDE" not in candidato["evidencias"]
    assert "SIMILITUD_OCR_CALIBRADA" in candidato["evidencias"]
    assert "SIN_HISTORIAL_PARA_ESTE_RUT" in candidato["conflictos"]
    # Nunca RESUELTO_AUTOMATICAMENTE -- exige confirmación humana siempre.
    assert resultado["resultado"] != "RESUELTO_AUTOMATICAMENTE"


def test_je4288_sin_tipo_esperado_no_amplia_el_universo(tmp_path):
    """Control -- sin tipo INEQUIVOCO, nunca se amplía al catálogo
    completo (demasiado riesgo de ambigüedad); sigue abstención."""
    catalogo = tmp_path / "vehiculos.json"
    _confirmar(catalogo, patente="JF4288", tipo=TipoVehiculo.CARRO.value)

    resultado = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="JE4288", rut_chofer="15.454.297-3",
        tipo_esperado=None, numero_transporte_actual="0000354576",
        filas=[], vehiculos=_homologables(catalogo),
    )
    assert resultado["resultado"] == RESULTADO_ABSTENCION
    assert resultado["candidatos"] == []


def test_je4288_tipo_incompatible_no_reconcilia(tmp_path):
    """Control -- JF4288 existe pero como TRACTO, no CARRO: nunca gana
    aunque la patente sea idéntica."""
    catalogo = tmp_path / "vehiculos.json"
    _confirmar(catalogo, patente="JF4288", tipo=TipoVehiculo.TRACTO.value)

    resultado = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="JE4288", rut_chofer="15.454.297-3",
        tipo_esperado="CARRO", numero_transporte_actual="0000354576",
        filas=[], vehiculos=_homologables(catalogo),
    )
    assert resultado["resultado"] == RESULTADO_ABSTENCION
    assert resultado["candidatos"] == []


def test_patente_realmente_desconocida_sigue_sin_candidatos(tmp_path):
    """Control -- ninguna patente del catálogo está a una confusión OCR
    calibrada de distancia: Atlas se abstiene tal como antes, nunca
    inventa una sustitución sin evidencia (patente realmente desconocida
    sigue funcionando)."""
    catalogo = tmp_path / "vehiculos.json"
    _confirmar(catalogo, patente="AB1234", tipo=TipoVehiculo.CARRO.value)

    resultado = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="ZZ9999", rut_chofer="15.454.297-3",
        tipo_esperado="CARRO", numero_transporte_actual="0000000001",
        filas=[], vehiculos=_homologables(catalogo),
    )
    assert resultado["resultado"] == RESULTADO_ABSTENCION
    assert resultado["candidatos"] == []


def test_dos_candidatos_catalogo_empatados_nunca_elige_uno_solo(tmp_path):
    """Dos patentes del catálogo, ambas CARRO, ambas a una única
    confusión OCR calibrada del valor documental -- Atlas nunca elige
    entre ellas, quedan ambas como sugerencia, ninguna gana sola."""
    catalogo = tmp_path / "vehiculos.json"
    # "JE4288" documental: "JF4288" (E/F, posición 2) y "JE428B" (8/B,
    # última posición) compiten -- las dos son un único carácter de
    # distancia, mismo nivel.
    _confirmar(catalogo, patente="JF4288", tipo=TipoVehiculo.CARRO.value, referencia="A")
    _confirmar(catalogo, patente="JE428B", tipo=TipoVehiculo.CARRO.value, referencia="B")

    resultado = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="JE4288", rut_chofer="15.454.297-3",
        tipo_esperado="CARRO", numero_transporte_actual="0000354576",
        filas=[], vehiculos=_homologables(catalogo),
    )
    assert resultado["resultado"] == RESULTADO_SUGERENCIA_HUMANA
    assert sorted(c["patente"] for c in resultado["candidatos"]) == ["JE428B", "JF4288"]
    assert "candidatas con evidencia comparable" in resultado["explicacion"]


# --- 2. E2E: aplicar la decisión real no duplica catálogo ni "aprende"
#     una regla universal E->F ---

def _entorno_472247(tmp_path):
    import csv
    import json
    from atlas_core.decisiones_pendientes import crear_decision
    from atlas_core.procesamiento_masivo import COLUMNAS

    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"; actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True); catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []}, "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    _confirmar(catalogos / "vehiculos.json", patente="JF4288", tipo=TipoVehiculo.CARRO.value)
    _confirmar(catalogos / "vehiculos.json", patente="SB6486", tipo=TipoVehiculo.TRACTO.value)

    dataset = actual / "analisis_completo_guias.csv"
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "472247.jpeg", "estado_procesamiento": "OK", "numero_guia": "472247",
        "numero_transporte": "0000354576", "fecha": "01/01/2026", "chofer": "RODRIGO NAHUELÑIR",
        "rut_chofer": "15.454.297-3", "cliente": "No encontrado", "obra_destino": "OBRA X",
        "patente_tracto": "SB6486", "patente_rampla": "JE4288",
        "descripcion_material": "MATERIAL", "tipo_carga": "OTRO",
        "indicador_revision": "REVISAR", "motivos_revision_documento": "PATENTE_SIN_HOMOLOGAR",
    })
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerow(fila)

    decision = crear_decision(
        tipo="VEHICULO_DESCONOCIDO", entidad="VEHICULO", archivo="472247.jpeg",
        numero_guia="472247", numero_transporte="0000354576", campo="patente_rampla",
        valor_documental="JE4288", valor_normalizado="JE4288", identidad_resuelta=None,
        candidatos=(), motivos=("SIN_VEHICULO_CONFIRMADO_COMPATIBLE",),
        evidencias=({"tipo": "OCR_DOCUMENTAL", "campo": "patente_rampla", "valor": "JE4288"},),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        tipo_resolucion="INEQUIVOCO", tipo_vehiculo_propuesto="CARRO",
    )
    from atlas_core.decisiones_pendientes import enriquecer_decisiones_vehiculo
    enriquecidas = enriquecer_decisiones_vehiculo(
        decisiones=[decision], filas=[fila], vehiculos=_homologables(catalogos / "vehiculos.json"),
    )
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=enriquecidas,
        ruta_salida=actual / "decisiones_pendientes.json",
    )
    return raiz, catalogos, actual, enriquecidas[0]


def test_472247_e2e_reconciliacion_propone_jf4288_y_usar_patente_existente_no_duplica_catalogo(tmp_path):
    raiz, catalogos, actual, decision = _entorno_472247(tmp_path)
    assert [c["patente"] for c in decision["candidatos"]] == ["JF4288"]
    assert "USAR_PATENTE_EXISTENTE" in decision["acciones_permitidas"]

    import json
    resultado = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="USAR_PATENTE_EXISTENTE",
        patente_elegida="JF4288",
    )
    assert resultado["ok"] is True
    assert resultado["patente_canonica"] == "JF4288"

    catalogo = json.loads((catalogos / "vehiculos.json").read_text(encoding="utf-8"))
    patentes = [v["patente_canonica"] for v in catalogo["vehiculos"]]
    # Nunca se registra "JE4288" como entidad nueva -- ni se duplica JF4288.
    assert "JE4288" not in patentes
    assert patentes.count("JF4288") == 1

    # El aprendizaje queda scoped a ESTE documento/campo/valor -- nunca una
    # regla universal "JE siempre significa JF" (ver
    # `resolver_patentes_confirmadas_por_ledger`, indexado por
    # (numero_guia, campo, valor_documental)).
    from atlas_core.aplicacion_decisiones import resolver_patentes_confirmadas_por_ledger
    indice = resolver_patentes_confirmadas_por_ledger(actual / "decisiones_aplicadas.json")
    assert indice == {("472247", "patente_rampla", "JE4288"): "JF4288"}

    # El valor documental original nunca se toca en el dataset.
    import csv
    with (actual / "analisis_completo_guias.csv").open(encoding="utf-8-sig") as archivo:
        fila_final = next(csv.DictReader(archivo, delimiter=";"))
    assert fila_final["patente_rampla"] == "JE4288"
    assert "PATENTE_SIN_HOMOLOGAR" not in fila_final["motivos_revision_documento"]
