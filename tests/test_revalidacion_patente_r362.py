"""R3.6.2: revalidación conservadora de PATENTE_SIN_HOMOLOGAR contra el
estado canónico VIGENTE del catálogo de vehículos -- sin OCR, sin
reprocesar imágenes, sin relajar la regla final de clasificación ya
validada en R3.6.1 (ver `atlas_core/decisiones_pendientes.py`):
  - patente_rampla válida -> INEQUIVOCO / CARRO
  - patente_tracto con rampla válida -> INEQUIVOCO / TRACTO
  - patente_tracto aislada -> TRACTO o CAMION_RIGIDO (confirmación humana)

Caso real que motiva este bloque: guía 464740, patente_tracto=XF3629,
patente_rampla="No encontrado" -- Javier confirmó XF3629 como
CAMION_RIGIDO desde Desktop, pero el dataset conservaba
PATENTE_SIN_HOMOLOGAR porque nada disparaba la revalidación para
decisiones VEHICULO_DESCONOCIDO/REGISTRAR (sólo se disparaba para
DESTINO_SIN_CONFIRMAR/CONFIRMAR, ver R3.4/R3.5).
"""
import csv
import json
from datetime import datetime, timezone

import pytest

from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.catalogo_vehiculos import TipoVehiculo, confirmar_vehiculo
from atlas_core.decisiones_pendientes import detectar_decisiones_documento, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    revalidar_patente_sin_homologar_sin_ocr,
    revalidar_y_regenerar_reporte,
)

FECHA = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "464740.jpeg", "estado_procesamiento": "OK", "numero_guia": "464740",
        "numero_transporte": "T1", "fecha": "01/01/2026", "chofer": "PATRICK ORTIZ",
        "cliente": "No encontrado", "obra_destino": "CONSTRUCTORA INMOBILIARIA E",
        "patente_tracto": "XF3629", "patente_rampla": "No encontrado",
        "descripcion_material": "MATERIAL", "tipo_carga": "OTRO",
        "indicador_revision": "REVISAR",
        "motivos_revision_documento": "PATENTE_SIN_HOMOLOGAR | CLIENTE_AUSENTE",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _entorno(tmp_path, *, filas_csv=None, vehiculos=None):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True)
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "empresas.json": {},
        "vehiculos.json": vehiculos if vehiculos is not None else {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, filas_csv if filas_csv is not None else [_fila_csv()])
    return raiz, catalogos, actual, dataset


def _leer_filas(dataset):
    return {f["numero_guia"]: f for f in csv.DictReader(dataset.open(encoding="utf-8-sig"), delimiter=";")}


def _confirmar(catalogos, *, patente, tipo, referencia="TEST"):
    confirmar_vehiculo(
        catalogos / "vehiculos.json", patente=patente, tipo=tipo, actor="TEST",
        fuente_decision=referencia, fecha=FECHA,
    )


def _vehiculo_v1_manual(*, patente, tipo, estado_calidad, estado_vigencia, confirmado=False):
    entrada = {
        "vehiculo_id": f"manual:{patente}", "patente_canonica": patente, "tipo": tipo,
        "estado_calidad": estado_calidad, "estado_vigencia": estado_vigencia,
        "aliases": [], "evidencias": [],
        "procedencia": "OBSERVACION_OCR", "confirmado_por": "", "fecha_confirmacion": "",
        "observaciones": "", "fecha_creacion": "2026-01-01T00:00:00+00:00",
        "fecha_modificacion": "2026-01-01T00:00:00+00:00",
    }
    if confirmado:
        entrada.update({
            "confirmado_por": "TEST", "fecha_confirmacion": "2026-01-01T00:00:00+00:00",
        })
    return entrada


# --- 1. Vehículo resuelto (tracto + rampla, ambos confirmados y tipados) ---

def test_vehiculo_resuelto_retira_el_motivo(tmp_path):
    fila = _fila_csv(
        numero_guia="464726", patente_tracto="KN5439", patente_rampla="JF6468",
        cliente="CONSTRUMART SA", motivos_revision_documento="PATENTE_SIN_HOMOLOGAR",
    )
    raiz, catalogos, actual, dataset = _entorno(tmp_path, filas_csv=[fila])
    _confirmar(catalogos, patente="KN5439", tipo=TipoVehiculo.TRACTO)
    _confirmar(catalogos, patente="JF6468", tipo=TipoVehiculo.CARRO)

    resultado = revalidar_patente_sin_homologar_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=catalogos)
    assert resultado["guias_actualizadas"] == ["464726"]

    fila_final = _leer_filas(dataset)["464726"]
    assert "PATENTE_SIN_HOMOLOGAR" not in fila_final["motivos_revision_documento"]
    assert fila_final["indicador_revision"] == "OK"
    assert fila_final["patente_tracto"] == "KN5439"  # dato documental intacto
    assert fila_final["patente_rampla"] == "JF6468"


# --- 2. Vehículo parcialmente resuelto (sólo una de las dos patentes) ---

def test_vehiculo_parcialmente_resuelto_conserva_el_motivo(tmp_path):
    fila = _fila_csv(
        numero_guia="464726", patente_tracto="KN5439", patente_rampla="JF6468",
        motivos_revision_documento="PATENTE_SIN_HOMOLOGAR",
    )
    raiz, catalogos, actual, dataset = _entorno(tmp_path, filas_csv=[fila])
    _confirmar(catalogos, patente="KN5439", tipo=TipoVehiculo.TRACTO)
    # JF6468 (rampla) nunca se confirma -> permanece sin homologar.

    resultado = revalidar_patente_sin_homologar_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=catalogos)
    assert resultado["guias_actualizadas"] == []
    fila_final = _leer_filas(dataset)["464726"]
    assert fila_final["motivos_revision_documento"] == "PATENTE_SIN_HOMOLOGAR"


# --- 3. Tipo incompatible (la patente existe pero con un tipo que contradice el rol documental) ---

def test_tipo_incompatible_conserva_el_motivo(tmp_path):
    fila = _fila_csv(
        numero_guia="464740", patente_tracto="XF3629", patente_rampla="No encontrado",
        motivos_revision_documento="PATENTE_SIN_HOMOLOGAR",
    )
    raiz, catalogos, actual, dataset = _entorno(tmp_path, filas_csv=[fila])
    # XF3629 confirmada como CARRO -- una patente aislada de "patente_tracto"
    # sólo admite TRACTO o CAMION_RIGIDO (R3.6.1); CARRO es incompatible.
    _confirmar(catalogos, patente="XF3629", tipo=TipoVehiculo.CARRO)

    resultado = revalidar_patente_sin_homologar_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=catalogos)
    assert resultado["guias_actualizadas"] == []
    fila_final = _leer_filas(dataset)["464740"]
    assert "PATENTE_SIN_HOMOLOGAR" in fila_final["motivos_revision_documento"]


def test_rampla_con_tracto_camion_rigido_es_incompatible(tmp_path):
    """patente_tracto + patente_rampla exige TRACTO para el tracto -- un
    CAMION_RIGIDO no es compatible con un par tracto+rampla articulado."""
    fila = _fila_csv(
        numero_guia="464726", patente_tracto="KN5439", patente_rampla="JF6468",
        motivos_revision_documento="PATENTE_SIN_HOMOLOGAR",
    )
    raiz, catalogos, actual, dataset = _entorno(tmp_path, filas_csv=[fila])
    _confirmar(catalogos, patente="KN5439", tipo=TipoVehiculo.CAMION_RIGIDO)
    _confirmar(catalogos, patente="JF6468", tipo=TipoVehiculo.CARRO)

    resultado = revalidar_patente_sin_homologar_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=catalogos)
    assert resultado["guias_actualizadas"] == []


# --- 4. Patente inactiva / no confirmada ---

def test_patente_no_confirmada_conserva_el_motivo(tmp_path):
    fila = _fila_csv(
        numero_guia="464740", patente_tracto="XF3629", patente_rampla="No encontrado",
        motivos_revision_documento="PATENTE_SIN_HOMOLOGAR",
    )
    vehiculos = {"version": 1, "vehiculos": [
        _vehiculo_v1_manual(patente="XF3629", tipo="CAMION_RIGIDO", estado_calidad="CANDIDATO", estado_vigencia="ACTIVO"),
    ]}
    raiz, catalogos, actual, dataset = _entorno(tmp_path, filas_csv=[fila], vehiculos=vehiculos)

    resultado = revalidar_patente_sin_homologar_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=catalogos)
    assert resultado["guias_actualizadas"] == []


def test_patente_inactiva_conserva_el_motivo(tmp_path):
    fila = _fila_csv(
        numero_guia="464740", patente_tracto="XF3629", patente_rampla="No encontrado",
        motivos_revision_documento="PATENTE_SIN_HOMOLOGAR",
    )
    vehiculos = {"version": 1, "vehiculos": [
        _vehiculo_v1_manual(
            patente="XF3629", tipo="CAMION_RIGIDO", estado_calidad="CONFIRMADO",
            estado_vigencia="INACTIVO", confirmado=True,
        ),
    ]}
    raiz, catalogos, actual, dataset = _entorno(tmp_path, filas_csv=[fila], vehiculos=vehiculos)

    resultado = revalidar_patente_sin_homologar_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=catalogos)
    assert resultado["guias_actualizadas"] == []


# --- 5. Camión rígido: tracto aislado confirmado como CAMION_RIGIDO resuelve ---

def test_tracto_aislado_camion_rigido_resuelve_el_motivo(tmp_path):
    """Caso real 464740: XF3629 confirmada CAMION_RIGIDO -- patente_tracto
    aislada (sin rampla documental) admite TRACTO o CAMION_RIGIDO."""
    fila = _fila_csv(numero_guia="464740", patente_tracto="XF3629", patente_rampla="No encontrado")
    raiz, catalogos, actual, dataset = _entorno(tmp_path, filas_csv=[fila])
    _confirmar(catalogos, patente="XF3629", tipo=TipoVehiculo.CAMION_RIGIDO)

    resultado = revalidar_patente_sin_homologar_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=catalogos)
    assert resultado["guias_actualizadas"] == ["464740"]
    fila_final = _leer_filas(dataset)["464740"]
    assert fila_final["motivos_revision_documento"] == "CLIENTE_AUSENTE"
    assert fila_final["indicador_revision"] == "REVISAR"  # CLIENTE_AUSENTE sigue bloqueando


def test_tracto_aislado_tracto_tambien_resuelve_el_motivo(tmp_path):
    fila = _fila_csv(
        numero_guia="464740", patente_tracto="XF3629", patente_rampla="No encontrado",
        motivos_revision_documento="PATENTE_SIN_HOMOLOGAR",
    )
    raiz, catalogos, actual, dataset = _entorno(tmp_path, filas_csv=[fila])
    _confirmar(catalogos, patente="XF3629", tipo=TipoVehiculo.TRACTO)

    resultado = revalidar_patente_sin_homologar_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=catalogos)
    assert resultado["guias_actualizadas"] == ["464740"]


# --- 6. Idempotencia ---

def test_revalidar_dos_veces_es_idempotente(tmp_path):
    fila = _fila_csv(numero_guia="464740", patente_tracto="XF3629", patente_rampla="No encontrado")
    raiz, catalogos, actual, dataset = _entorno(tmp_path, filas_csv=[fila])
    _confirmar(catalogos, patente="XF3629", tipo=TipoVehiculo.CAMION_RIGIDO)

    primera = revalidar_patente_sin_homologar_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=catalogos)
    assert primera["guias_actualizadas"] == ["464740"]
    contenido_tras_primera = dataset.read_bytes()

    segunda = revalidar_patente_sin_homologar_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=catalogos)
    assert segunda["guias_actualizadas"] == []
    assert dataset.read_bytes() == contenido_tras_primera


# --- 7. Motivos independientes: resolver una patente no toca otros motivos ---

def test_no_afecta_motivos_independientes_de_otras_filas_ni_de_la_misma_fila(tmp_path):
    fila_resuelta = _fila_csv(
        numero_guia="464740", patente_tracto="XF3629", patente_rampla="No encontrado",
        motivos_revision_documento="PATENTE_SIN_HOMOLOGAR | CLIENTE_AUSENTE | OBRA_DESTINO_SIN_CORROBORAR",
    )
    otra_fila = _fila_csv(
        numero_guia="999", patente_tracto="ZZ0000", patente_rampla="No encontrado",
        motivos_revision_documento="PATENTE_SIN_HOMOLOGAR",
    )
    raiz, catalogos, actual, dataset = _entorno(tmp_path, filas_csv=[fila_resuelta, otra_fila])
    _confirmar(catalogos, patente="XF3629", tipo=TipoVehiculo.CAMION_RIGIDO)

    resultado = revalidar_patente_sin_homologar_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=catalogos)
    assert resultado["guias_actualizadas"] == ["464740"]

    filas = _leer_filas(dataset)
    assert filas["464740"]["motivos_revision_documento"] == "CLIENTE_AUSENTE | OBRA_DESTINO_SIN_CORROBORAR"
    assert filas["999"]["motivos_revision_documento"] == "PATENTE_SIN_HOMOLOGAR"  # ZZ0000 no registrada -> intacta


def test_catalogo_ausente_o_vacio_conserva_todo(tmp_path):
    fila = _fila_csv()
    raiz, catalogos, actual, dataset = _entorno(tmp_path, filas_csv=[fila])
    (catalogos / "vehiculos.json").unlink()  # catálogo ausente

    resultado = revalidar_patente_sin_homologar_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=catalogos)
    assert resultado["guias_actualizadas"] == []
    filas = _leer_filas(dataset)
    assert filas["464740"]["motivos_revision_documento"] == "PATENTE_SIN_HOMOLOGAR | CLIENTE_AUSENTE"


# --- 9. Aplicación de decisión: REGISTRAR dispara la revalidación ---

def test_aplicar_decision_registrar_vehiculo_dispara_revalidacion_y_limpia_otra_fila(tmp_path):
    """Reproduce el caso real 464740: una decisión VEHICULO_DESCONOCIDO
    REGISTRAR (de OTRA guía, o de la misma) confirma canónicamente una
    patente que ya estaba presente -sin homologar- en el dataset, y la
    aplicación de esa decisión debe disparar la revalidación -- sin
    intervención manual y sin OCR."""
    fila = _fila_csv(numero_guia="464740", patente_tracto="XF3629", patente_rampla="No encontrado")
    raiz, catalogos, actual, dataset = _entorno(tmp_path, filas_csv=[fila])

    datos = {
        "número de guía": "464740", "número de transporte": "T1",
        "patente del tracto": "XF3629", "patente del carro": "No encontrado",
    }
    decisiones = detectar_decisiones_documento(archivo="464740.jpeg", datos=datos, carpeta_catalogos=catalogos)
    decision = next(d for d in decisiones if d["tipo"] == "VEHICULO_DESCONOCIDO")
    assert decision["tipo_resolucion"] == "REQUIERE_CONFIRMACION_HUMANA"
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision],
        ruta_salida=actual / "decisiones_pendientes.json",
    )

    resultado = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR", tipo_vehiculo="CAMION_RIGIDO",
    )
    assert resultado["ok"] is True
    assert "revalidacion" in resultado
    assert resultado["revalidacion"]["guias_actualizadas"] == ["464740"]
    assert resultado["revalidacion"]["reporte_regenerado"] is True

    fila_final = _leer_filas(dataset)["464740"]
    assert "PATENTE_SIN_HOMOLOGAR" not in fila_final["motivos_revision_documento"]
    assert fila_final["motivos_revision_documento"] == "CLIENTE_AUSENTE"


def test_no_registrar_no_dispara_revalidacion(tmp_path):
    fila = _fila_csv(numero_guia="464740", patente_tracto="XF3629", patente_rampla="No encontrado")
    raiz, catalogos, actual, dataset = _entorno(tmp_path, filas_csv=[fila])
    datos = {
        "número de guía": "464740", "número de transporte": "T1",
        "patente del tracto": "XF3629", "patente del carro": "No encontrado",
    }
    decisiones = detectar_decisiones_documento(archivo="464740.jpeg", datos=datos, carpeta_catalogos=catalogos)
    decision = next(d for d in decisiones if d["tipo"] == "VEHICULO_DESCONOCIDO")
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision],
        ruta_salida=actual / "decisiones_pendientes.json",
    )

    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="NO_REGISTRAR")
    # Bloque R10: la revalidación ahora corre siempre (fix de la revisión
    # huérfana) -- pero NO_REGISTRAR nunca queda en el índice del ledger
    # que usa `revalidar_patente_sin_homologar_sin_ocr`
    # (`resolver_patentes_confirmadas_por_ledger`, sólo USAR_PATENTE_
    # EXISTENTE/SELECCIONAR_OTRA_PATENTE), así que corre sin encontrar
    # nada que retirar -- nunca resuelve falsamente la patente.
    assert "revalidacion" in resultado
    assert resultado["revalidacion"]["guias_actualizadas"] == []
    fila_final = _leer_filas(dataset)["464740"]
    assert "PATENTE_SIN_HOMOLOGAR" in fila_final["motivos_revision_documento"]


# --- Bloque CIERRE OPERACIONAL D1: USAR_PATENTE_EXISTENTE/SELECCIONAR_OTRA_PATENTE ---
# Caso real que motiva este bloque: guía 464265 (Carlos Simón), patente_tracto
# documental "VP6521" -- Javier confirmó USAR_PATENTE_EXISTENTE (canónica
# VP8521, ya en catálogo) desde Desktop, pero el dataset seguía mostrando
# PATENTE_SIN_HOMOLOGAR: el valor documental "VP6521" JAMÁS iba a
# homologar por sí solo (no es la canónica, sólo una lectura OCR distinta)
# y nada disparaba la revalidación para estas dos acciones.


def test_usar_patente_existente_dispara_revalidacion_via_ledger(tmp_path):
    fila = _fila_csv(
        numero_guia="464265", patente_tracto="VP6521", patente_rampla="No encontrado",
        motivos_revision_documento="PATENTE_SIN_HOMOLOGAR | CLIENTE_AUSENTE",
    )
    raiz, catalogos, actual, dataset = _entorno(tmp_path, filas_csv=[fila])
    _confirmar(catalogos, patente="VP8521", tipo=TipoVehiculo.TRACTO.value)

    from atlas_core.decisiones_pendientes import enriquecer_decisiones_vehiculo

    decision = {
        "decision_id": "d-vp6521", "estado": "PENDIENTE", "tipo": "VEHICULO_DESCONOCIDO",
        "entidad": "VEHICULO", "documento": {"archivo": "464265.jpeg", "numero_guia": "464265", "numero_transporte": "T1"},
        "campo": "patente_tracto", "valor_documental": "VP6521", "valor_normalizado": "VP6521",
        "identidad_resuelta": None, "contexto": None, "candidatos": [],
        "motivos": ["SIN_VEHICULO_CONFIRMADO_COMPATIBLE"],
        "evidencias": [{"tipo": "OCR_DOCUMENTAL", "campo": "patente_tracto", "valor": "VP6521"}],
        "acciones_permitidas": ["REGISTRAR", "NO_REGISTRAR", "POSPONER"],
        "tipo_resolucion": "REQUIERE_CONFIRMACION_HUMANA", "tipo_vehiculo_propuesto": None,
    }
    filas_csv = list(csv.DictReader(dataset.open(encoding="utf-8-sig"), delimiter=";"))
    from atlas_core.catalogo_vehiculos import cargar_catalogo_vehiculos
    vehiculos = cargar_catalogo_vehiculos(catalogos / "vehiculos.json").homologables()
    # numero_transporte real de 464265 comparte transporte con 464264 --
    # aquí basta con que exista al menos un vehiculo homologable para que
    # USAR_PATENTE_EXISTENTE tenga sentido; el candidato exacto no importa
    # para este test (se fuerza directamente abajo).
    enriquecidas = enriquecer_decisiones_vehiculo(decisiones=[decision], filas=filas_csv, vehiculos=vehiculos)
    decision_final = enriquecidas[0]
    if not decision_final.get("candidatos"):
        # Sin historial de otro documento del mismo RUT, el motor de
        # evidencia no propone nada por su cuenta (correcto, nunca
        # autocorrige) -- se simula aquí la sugerencia ya publicada tal
        # como quedó realmente en la bandeja real antes de que Javier la
        # confirmara, para poder ejercitar USAR_PATENTE_EXISTENTE.
        decision_final["candidatos"] = [{"patente": "VP8521", "vehiculo_id": vehiculos[0].vehiculo_id, "tipo_vehiculo": "TRACTO"}]
        decision_final["acciones_permitidas"] = ["REGISTRAR", "NO_REGISTRAR", "USAR_PATENTE_EXISTENTE", "SELECCIONAR_OTRA_PATENTE", "POSPONER"]
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision_final],
        ruta_salida=actual / "decisiones_pendientes.json",
    )

    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision_final["decision_id"], accion="USAR_PATENTE_EXISTENTE")
    assert resultado["ok"] is True
    assert resultado["patente_canonica"] == "VP8521"
    assert "revalidacion" in resultado
    assert resultado["revalidacion"]["guias_actualizadas"] == ["464265"]

    fila_final = _leer_filas(dataset)["464265"]
    assert "PATENTE_SIN_HOMOLOGAR" not in fila_final["motivos_revision_documento"]
    assert fila_final["motivos_revision_documento"] == "CLIENTE_AUSENTE"
    # El valor documental original nunca se toca.
    assert fila_final["patente_tracto"] == "VP6521"


def test_no_registrar_sigue_sin_disparar_revalidacion_ni_falsamente_resolver_patente(tmp_path):
    """Control negativo del mismo bloque: NO_REGISTRAR (caso real 464036,
    error documental sin canónica) NUNCA debe entrar al índice del
    ledger que usa la revalidación -- un rechazo explícito no es una
    confirmación. Bloque R10: la revalidación en sí corre siempre (fix de
    la revisión huérfana), pero al no estar en ese índice nunca retira
    PATENTE_SIN_HOMOLOGAR."""
    fila = _fila_csv(numero_guia="464036", patente_tracto="XF3662", patente_rampla="No encontrado")
    raiz, catalogos, actual, dataset = _entorno(tmp_path, filas_csv=[fila])
    datos = {
        "número de guía": "464036", "número de transporte": "T1",
        "patente del tracto": "XF3662", "patente del carro": "No encontrado",
    }
    decisiones = detectar_decisiones_documento(archivo="464036.jpeg", datos=datos, carpeta_catalogos=catalogos)
    decision = next(d for d in decisiones if d["tipo"] == "VEHICULO_DESCONOCIDO")
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision],
        ruta_salida=actual / "decisiones_pendientes.json",
    )
    resultado = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="NO_REGISTRAR", motivo_rechazo="ERROR_DOCUMENTAL_MANDANTE",
    )
    # Bloque R10: la revalidación corre siempre ahora -- el control real es
    # que nunca resuelva falsamente la patente, no que se abstenga de correr.
    assert "revalidacion" in resultado
    assert resultado["revalidacion"]["guias_actualizadas"] == []
    fila_final = _leer_filas(dataset)["464036"]
    assert "PATENTE_SIN_HOMOLOGAR" in fila_final["motivos_revision_documento"]


# --- Orquestador combinado (obra/destino + patente en la misma pasada) ---

def test_revalidar_y_regenerar_reporte_combina_ambas_revalidaciones(tmp_path):
    fila = _fila_csv(numero_guia="464740", patente_tracto="XF3629", patente_rampla="No encontrado")
    raiz, catalogos, actual, dataset = _entorno(tmp_path, filas_csv=[fila])
    _confirmar(catalogos, patente="XF3629", tipo=TipoVehiculo.CAMION_RIGIDO)

    resultado = revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_prueba_r362")
    assert resultado["reporte_regenerado"] is True
    assert resultado["guias_actualizadas"] == ["464740"]
    assert resultado["patente"]["guias_actualizadas"] == ["464740"]
    assert resultado["obra_destino"]["guias_actualizadas"] == []


def test_revalidar_y_regenerar_reporte_no_hace_nada_si_ninguna_revalidacion_cambio(tmp_path):
    fila = _fila_csv(motivos_revision_documento="CLIENTE_AUSENTE")
    raiz, catalogos, actual, dataset = _entorno(tmp_path, filas_csv=[fila])
    resultado = revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_no_deberia_existir")
    assert resultado["reporte_regenerado"] is False
    assert not (raiz / "reportes" / "reporte_no_deberia_existir").exists()
