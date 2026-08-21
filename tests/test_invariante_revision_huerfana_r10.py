"""Bloque R10 -- invariante general: una decisión HUMANA aplicada que
resuelve el ÚNICO motivo documental de una fila NUNCA puede dejar esa fila
en REQUIERE_REVISION sin ninguna decisión pendiente ni causa técnica
explícita ("revisión huérfana").

Caso real que motiva este bloque: guía 472163 -- Javier aplicó REGISTRAR
sobre OBRA_DESCONOCIDA desde Desktop, la decisión desapareció correctamente
de Revisión de Atlas, pero el viaje siguió mostrando REVISAR en Viajes
porque `aplicar_decision_obra` nunca disparaba la revalidación documental
para ese tipo de decisión (ver `atlas_core/aplicacion_decisiones.py`, bloque
R10). El fix es general (una lista blanca cerrada de tipos se invirtió a
una lista negra de las 2 acciones sin efecto en el dataset y los 3 tipos
que ya regeneran directo) -- este archivo prueba el INVARIANTE resultante
contra dominios reales distintos (obra, vehículo, cliente), no el caso
puntual 472163, para que ningún tipo de decisión futuro pueda reintroducir
el mismo bug por omisión.

El dominio DESTINO (DESTINO_SIN_CONFIRMAR/CONFIRMAR) ya tiene cobertura
equivalente y explícita en `test_destinos_confirmacion_r34.py`
(`test_confirmar_integra_revalidacion_automaticamente_y_reporte_vigente_
cambia`); el dominio PLANTA (ORIGEN_NO_CONFIRMADO) y CLIENTE_AUSENTE ya
regeneran directo (ver `TIPOS_CON_REGENERACION_DIRECTA`) y tienen su propia
cobertura en `test_aplicacion_decisiones.py`/`test_cliente_ausente_r9.py`;
no se duplican aquí.
"""
import csv
import json
from datetime import datetime, timezone

from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_vehiculos import TipoVehiculo, confirmar_vehiculo
from atlas_core.decisiones_pendientes import (
    crear_decision, detectar_decisiones_documento, enriquecer_decisiones_vehiculo, generar_artefacto,
)
from atlas_core.procesamiento_masivo import COLUMNAS


def _catalogos_base(carpeta, *, vehiculos=None):
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "empresas.json": {},
        "vehiculos.json": vehiculos if vehiculos is not None else {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")


def _pendientes(actual):
    return json.loads((actual / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]


FECHA = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _fila_final(dataset, numero_guia):
    with dataset.open(encoding="utf-8-sig") as archivo:
        return next(f for f in csv.DictReader(archivo, delimiter=";") if f["numero_guia"] == numero_guia)


def _assert_sin_revision_huerfana(*, actual, dataset, numero_guia):
    """El invariante en sí, dominio-agnóstico: si la decisión recién
    aplicada era el único motivo de la fila, la fila queda OK y no debe
    quedar ninguna decisión pendiente asociada a esa guía."""
    fila = _fila_final(dataset, numero_guia)
    assert fila["motivos_revision_documento"] == ""
    assert fila["indicador_revision"] == "OK"
    assert not any(d["documento"]["numero_guia"] == numero_guia for d in _pendientes(actual))


# --- Dominio OBRA (caso real 472163) ---

def test_obra_desconocida_registrar_unico_motivo_no_deja_revision_huerfana(tmp_path):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"; actual = raiz / "operacion" / "actual"
    catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="CLIENTE CANONICO SA", rut="50.234.350-5", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    dataset = actual / "analisis_completo_guias.csv"
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "472163.png", "estado_procesamiento": "OK", "numero_guia": "472163",
        "numero_transporte": "T1", "fecha": "01-08-2026", "cliente": "CLIENTE CANONICO SA",
        "obra_destino": "OBRA NUEVA", "indicador_revision": "REVISAR",
        "motivos_revision_documento": "OBRA_DESTINO_SIN_CORROBORAR",
    })
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerow(fila)
    decision = crear_decision(
        tipo="OBRA_DESCONOCIDA", entidad="OBRA", archivo="472163.png", numero_guia="472163",
        numero_transporte="T1", campo="obra_destino", valor_documental="OBRA NUEVA",
        valor_normalizado="OBRA NUEVA", identidad_resuelta=None, candidatos=(),
        motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),
        evidencias=({"tipo": "CLIENTE_RESUELTO", "entidad_id": cliente.cliente_id},),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        contexto={"cliente_id": cliente.cliente_id, "cliente_canonico": cliente.razon_social},
    )
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision], ruta_salida=actual / "decisiones_pendientes.json")

    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR")
    assert resultado["ok"] is True
    assert "revalidacion" in resultado
    _assert_sin_revision_huerfana(actual=actual, dataset=dataset, numero_guia="472163")


def test_obra_desconocida_no_registrar_unico_motivo_no_deja_revision_huerfana(tmp_path):
    """Control simétrico: un rechazo humano también cierra la revisión --
    R4.9 trata REGISTRAR y NO_REGISTRAR como igualmente terminales (un
    humano ya revisó), así que tampoco debe quedar huérfana."""
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"; actual = raiz / "operacion" / "actual"
    catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="CLIENTE CANONICO SA", rut="50.234.350-5", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    dataset = actual / "analisis_completo_guias.csv"
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "472164.png", "estado_procesamiento": "OK", "numero_guia": "472164",
        "numero_transporte": "T2", "fecha": "01-08-2026", "cliente": "CLIENTE CANONICO SA",
        "obra_destino": "OBRA INVENTADA", "indicador_revision": "REVISAR",
        "motivos_revision_documento": "OBRA_DESTINO_SIN_CORROBORAR",
    })
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerow(fila)
    decision = crear_decision(
        tipo="OBRA_DESCONOCIDA", entidad="OBRA", archivo="472164.png", numero_guia="472164",
        numero_transporte="T2", campo="obra_destino", valor_documental="OBRA INVENTADA",
        valor_normalizado="OBRA INVENTADA", identidad_resuelta=None, candidatos=(),
        motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),
        evidencias=({"tipo": "CLIENTE_RESUELTO", "entidad_id": cliente.cliente_id},),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        contexto={"cliente_id": cliente.cliente_id, "cliente_canonico": cliente.razon_social},
    )
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision], ruta_salida=actual / "decisiones_pendientes.json")

    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="NO_REGISTRAR")
    assert resultado["ok"] is True
    _assert_sin_revision_huerfana(actual=actual, dataset=dataset, numero_guia="472164")


# --- Dominio VEHÍCULO ---

def test_vehiculo_desconocido_usar_patente_existente_unico_motivo_no_deja_revision_huerfana(tmp_path):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"; actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True); catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    dataset = actual / "analisis_completo_guias.csv"
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "900001.jpeg", "estado_procesamiento": "OK", "numero_guia": "900001",
        "numero_transporte": "T9", "fecha": "01/01/2026", "chofer": "TEST",
        "cliente": "CLIENTE CANONICO SA", "obra_destino": "OBRA EXISTENTE",
        "patente_tracto": "VP6521", "patente_rampla": "No encontrado",
        "descripcion_material": "MATERIAL", "tipo_carga": "OTRO",
        "indicador_revision": "REVISAR", "motivos_revision_documento": "PATENTE_SIN_HOMOLOGAR",
    })
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerow(fila)
    confirmar_vehiculo(catalogos / "vehiculos.json", patente="VP8521", tipo=TipoVehiculo.TRACTO.value, actor="TEST", fuente_decision="TEST", fecha=FECHA)

    from atlas_core.catalogo_vehiculos import cargar_catalogo_vehiculos
    vehiculos = cargar_catalogo_vehiculos(catalogos / "vehiculos.json").homologables()
    decision = {
        "decision_id": "d-900001", "estado": "PENDIENTE", "tipo": "VEHICULO_DESCONOCIDO",
        "entidad": "VEHICULO", "documento": {"archivo": "900001.jpeg", "numero_guia": "900001", "numero_transporte": "T9"},
        "campo": "patente_tracto", "valor_documental": "VP6521", "valor_normalizado": "VP6521",
        "identidad_resuelta": None, "contexto": None,
        "candidatos": [{"patente": "VP8521", "vehiculo_id": vehiculos[0].vehiculo_id, "tipo_vehiculo": "TRACTO"}],
        "motivos": ["SIN_VEHICULO_CONFIRMADO_COMPATIBLE"],
        "evidencias": [{"tipo": "OCR_DOCUMENTAL", "campo": "patente_tracto", "valor": "VP6521"}],
        "acciones_permitidas": ["REGISTRAR", "NO_REGISTRAR", "USAR_PATENTE_EXISTENTE", "SELECCIONAR_OTRA_PATENTE", "POSPONER"],
        "tipo_resolucion": "REQUIERE_CONFIRMACION_HUMANA", "tipo_vehiculo_propuesto": None,
    }
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision], ruta_salida=actual / "decisiones_pendientes.json")

    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="USAR_PATENTE_EXISTENTE")
    assert resultado["ok"] is True
    assert "revalidacion" in resultado
    _assert_sin_revision_huerfana(actual=actual, dataset=dataset, numero_guia="900001")


# --- Dominio CLIENTE ---

def test_cliente_candidato_confirmar_unico_motivo_no_deja_revision_huerfana(tmp_path):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"; actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True); catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="COMERCIAL A Y B LTDA", rut="78.634.910-9", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    # `obra_destino` documental es el propio cliente ("retiro en bodega
    # propia") -- R3.2 reconoce que es el mismo hecho dos veces, no una
    # obra nueva, así que CONFIRMAR no encadena ninguna pregunta de obra/
    # destino y CLIENTE_SIN_CORROBORAR queda como el ÚNICO motivo real de
    # la fila (a diferencia de una obra de terceros, dominio ya cubierto
    # arriba).
    dataset = actual / "analisis_completo_guias.csv"
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "800001.jpeg", "estado_procesamiento": "OK", "numero_guia": "800001",
        "numero_transporte": "T8", "fecha": "01-08-2026", "cliente": "COMERCIAL A Y B LTDA",
        "obra_destino": "COMERCIAL A Y B LTDA", "indicador_revision": "REVISAR",
        "motivos_revision_documento": "CLIENTE_SIN_CORROBORAR",
    })
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerow(fila)
    ds = detectar_decisiones_documento(
        archivo="800001.jpeg",
        datos={"número de guía": "800001", "número de transporte": "T8",
               "cliente": "COMERCIAL A Y B LTDA", "RUT del cliente": "No encontrado",
               "obra destino": "COMERCIAL A Y B LTDA"},
        carpeta_catalogos=catalogos, cliente_documental_original="CONERCIAL A Y B LTDA",
    )
    decision = next(d for d in ds if d["tipo"] == "CLIENTE_CANDIDATO")
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision], ruta_salida=actual / "decisiones_pendientes.json")

    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR")
    assert resultado["ok"] is True
    assert "revalidacion" in resultado
    _assert_sin_revision_huerfana(actual=actual, dataset=dataset, numero_guia="800001")


# --- Inverso: si queda OTRO motivo legítimo, el viaje debe seguir REVISAR
#     con una decisión pendiente accionable -- nunca "REQUIERE_REVISION sin
#     ninguna decisión y sin causa técnica" (el otro extremo inconsistente
#     descrito en la Parte C del bloque). ---

def test_vehiculo_usar_patente_existente_con_otro_motivo_conserva_revision_accionable(tmp_path):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"; actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True); catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    dataset = actual / "analisis_completo_guias.csv"
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "900002.jpeg", "estado_procesamiento": "OK", "numero_guia": "900002",
        "numero_transporte": "T7", "fecha": "01/01/2026", "chofer": "TEST",
        "cliente": "No encontrado", "obra_destino": "OBRA EXISTENTE",
        "patente_tracto": "VP6521", "patente_rampla": "No encontrado",
        "descripcion_material": "MATERIAL", "tipo_carga": "OTRO",
        "indicador_revision": "REVISAR",
        "motivos_revision_documento": "PATENTE_SIN_HOMOLOGAR | CLIENTE_AUSENTE",
    })
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerow(fila)
    confirmar_vehiculo(catalogos / "vehiculos.json", patente="VP8521", tipo=TipoVehiculo.TRACTO.value, actor="TEST", fuente_decision="TEST", fecha=FECHA)
    from atlas_core.catalogo_vehiculos import cargar_catalogo_vehiculos
    vehiculos = cargar_catalogo_vehiculos(catalogos / "vehiculos.json").homologables()
    decision = {
        "decision_id": "d-900002", "estado": "PENDIENTE", "tipo": "VEHICULO_DESCONOCIDO",
        "entidad": "VEHICULO", "documento": {"archivo": "900002.jpeg", "numero_guia": "900002", "numero_transporte": "T7"},
        "campo": "patente_tracto", "valor_documental": "VP6521", "valor_normalizado": "VP6521",
        "identidad_resuelta": None, "contexto": None,
        "candidatos": [{"patente": "VP8521", "vehiculo_id": vehiculos[0].vehiculo_id, "tipo_vehiculo": "TRACTO"}],
        "motivos": ["SIN_VEHICULO_CONFIRMADO_COMPATIBLE"],
        "evidencias": [{"tipo": "OCR_DOCUMENTAL", "campo": "patente_tracto", "valor": "VP6521"}],
        "acciones_permitidas": ["REGISTRAR", "NO_REGISTRAR", "USAR_PATENTE_EXISTENTE", "SELECCIONAR_OTRA_PATENTE", "POSPONER"],
        "tipo_resolucion": "REQUIERE_CONFIRMACION_HUMANA", "tipo_vehiculo_propuesto": None,
    }
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision], ruta_salida=actual / "decisiones_pendientes.json")

    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="USAR_PATENTE_EXISTENTE")
    assert resultado["ok"] is True

    fila_final = _fila_final(dataset, "900002")
    # PATENTE_SIN_HOMOLOGAR se retiró, pero CLIENTE_AUSENTE es un problema
    # legítimo distinto -- el viaje debe seguir REVISAR, nunca pasar a OK
    # silenciosamente, y debe existir una decisión CLIENTE_AUSENTE
    # accionable para ese mismo documento (nunca "REVISAR" sin ninguna
    # decisión ni causa explícita).
    assert "PATENTE_SIN_HOMOLOGAR" not in fila_final["motivos_revision_documento"]
    assert "CLIENTE_AUSENTE" in fila_final["motivos_revision_documento"]
    assert fila_final["indicador_revision"] == "REVISAR"
