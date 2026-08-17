import csv
import json

import pytest

import atlas_core.aplicacion_decisiones as modulo
from atlas_core.aplicacion_decisiones import DecisionObsoletaError, ErrorAplicacionDecision, aplicar_decision_obra
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_destinos import CatalogoDestinos
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, ResultadoEvidencia, TipoEvidencia
from atlas_core.decisiones_pendientes import crear_decision, detectar_decisiones_documento, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_obra_destino_sin_ocr, revalidar_y_regenerar_reporte

OBRA_TEXTO = "CONSTRUCTORA INMOBILIARIA E"
DESTINO_TEXTO = "AV. VICUNA MACKENNA 3451 SAN JOAQUIN"


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "464715.jpeg", "estado_procesamiento": "OK", "numero_guia": "464715",
        "numero_transporte": "T1", "fecha": "01/01/2026", "chofer": "CHOFER TEST",
        "cliente": "CONSTRUMART SA", "obra_destino": OBRA_TEXTO,
        "patente_tracto": "AB1234", "patente_rampla": "No encontrado",
        "descripcion_material": "MATERIAL", "tipo_carga": "OTRO",
        "indicador_revision": "REVISAR",
        "motivos_revision_documento": "OBRA_DESTINO_SIN_CORROBORAR",
        "despachar_a_crudo": DESTINO_TEXTO, "estado_entrega": "REVISAR",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _entorno(tmp_path, *, filas_csv=None):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"; actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True); catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []}, "empresas.json": {}, "vehiculos.json": {},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="CONSTRUMART SA", rut="76.123.987-2", fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    obras = CatalogoObrasDestinos(ruta=catalogos/"obras_destinos.json", ruta_clientes=catalogos/"clientes.json", ruta_destinos=catalogos/"destinos_maestros.json")
    evidencia_obra = Evidencia(
        tipo=TipoEvidencia.GUIA.value, identificador_fuente="464715", referencia_hash="a"*64,
        campos_observados={"obra": OBRA_TEXTO}, fecha="2026-01-01T00:00:00+00:00",
        actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value,
    )
    obra = obras.registrar_observacion(cliente_id=cliente.cliente_id, nombre_obra=OBRA_TEXTO, evidencia=evidencia_obra).obra

    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, filas_csv if filas_csv is not None else [_fila_csv()])

    decision = crear_decision(
        tipo="DESTINO_SIN_CONFIRMAR", entidad="RELACION_OBRA_DESTINO", archivo="464715.jpeg",
        numero_guia="464715", numero_transporte="T1", campo="destino_entrega",
        valor_documental=DESTINO_TEXTO, valor_normalizado=DESTINO_TEXTO,
        identidad_resuelta={"entidad_id": obra.obra_id, "valor_canonico": OBRA_TEXTO},
        candidatos=(), motivos=("OBRA_SIN_RELACION_CONFIRMADA_UNICA",),
        evidencias=({"tipo": "OBRA_IDENTIFICADA", "entidad_id": obra.obra_id},),
        acciones_permitidas=("CONFIRMAR", "NO_CONFIRMAR", "POSPONER"),
        contexto={
            "cliente_id": cliente.cliente_id, "cliente_canonico": "CONSTRUMART SA",
            "obra_id": obra.obra_id, "obra_canonica": OBRA_TEXTO, "destino_documental": DESTINO_TEXTO,
        },
    )
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision], ruta_salida=actual/"decisiones_pendientes.json")
    return raiz, catalogos, actual, cliente, obra, decision


def _pendientes(actual):
    return json.loads((actual/"decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]


def _confirmar_relacion_directamente(catalogos, cliente, obra, *, destino_texto=DESTINO_TEXTO):
    """Crea la relación obra<->destino CONFIRMADA llamando directamente a la
    API de catálogo (sin pasar por aplicar_decision_obra) -- para probar
    `revalidar_obra_destino_sin_ocr` en aislamiento, sin que la
    revalidación automática de aplicar_decision_obra ya haya limpiado el
    dataset de antemano."""
    destino = CatalogoDestinos(catalogos/"destinos_maestros.json", ruta_clientes=catalogos/"clientes.json").crear_o_reutilizar_global(
        nombre_destino=destino_texto, direccion=destino_texto, fuente="PRUEBA_DIRECTA",
    )
    obras_cat = CatalogoObrasDestinos(ruta=catalogos/"obras_destinos.json", ruta_clientes=catalogos/"clientes.json", ruta_destinos=catalogos/"destinos_maestros.json")
    evidencia = Evidencia(
        tipo=TipoEvidencia.GUIA.value, identificador_fuente="464715-directa", referencia_hash="b"*64,
        campos_observados={"obra": obra.nombre_canonico}, fecha="2026-01-01T00:00:00+00:00",
        actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value,
    )
    pendiente = obras_cat.registrar_observacion(cliente_id=cliente.cliente_id, nombre_obra=obra.nombre_canonico, destino_id=destino.destino_id, evidencia=evidencia).relacion
    obras_cat.confirmar_relacion(pendiente.relacion_id, actor="test")
    return destino


# --- CONFIRMAR: destino nuevo, relación confirmada, obra reutilizada ---

def test_confirmar_crea_destino_relacion_confirmada_y_promueve_obra(tmp_path):
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path)
    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR")
    assert resultado["ok"]

    destinos = CatalogoDestinos(catalogos/"destinos_maestros.json", ruta_clientes=catalogos/"clientes.json").listar()
    assert len(destinos) == 1 and destinos[0].direccion == DESTINO_TEXTO
    assert resultado["destino_id"] == destinos[0].destino_id

    obras_cat = CatalogoObrasDestinos(ruta=catalogos/"obras_destinos.json", ruta_clientes=catalogos/"clientes.json", ruta_destinos=catalogos/"destinos_maestros.json")
    obras_todas = obras_cat.listar_obras()
    assert len(obras_todas) == 1  # no se duplicó la obra
    assert obras_todas[0].obra_id == obra.obra_id
    assert obras_todas[0].estado == "CONFIRMADA"

    relaciones = obras_cat.listar_relaciones()
    assert len(relaciones) == 1 and relaciones[0].estado == "CONFIRMADA"
    assert relaciones[0].obra_id == obra.obra_id and relaciones[0].destino_id == destinos[0].destino_id

    assert _pendientes(actual) == []


def test_confirmar_reutiliza_destino_existente_sin_duplicar(tmp_path):
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path)
    # El destino ya existe globalmente (p.ej. otra guía lo trajo primero).
    destino_previo = CatalogoDestinos(catalogos/"destinos_maestros.json", ruta_clientes=catalogos/"clientes.json").crear(
        cliente_id="", nombre_destino=DESTINO_TEXTO, direccion=DESTINO_TEXTO, pais="CHILE", fuente="PRUEBA",
    )
    # La creación cambió destinos_maestros.json -- se regenera el artefacto
    # para que catalogos_sha256 refleje el estado vigente antes de aplicar.
    generar_artefacto(ruta_dataset=actual/"analisis_completo_guias.csv", carpeta_catalogos=catalogos, decisiones=[decision], ruta_salida=actual/"decisiones_pendientes.json")
    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR")
    assert resultado["destino_id"] == destino_previo.destino_id
    destinos = CatalogoDestinos(catalogos/"destinos_maestros.json", ruta_clientes=catalogos/"clientes.json").listar()
    assert len(destinos) == 1  # no se creó un segundo


def test_otro_cliente_misma_obra_destino_reutiliza_sin_preguntar(tmp_path):
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path)
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR")

    easy = CatalogoClientes(catalogos/"clientes.json").crear(
        razon_social="EASY RETAIL SA", rut="50.234.350-5", fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    nuevas = detectar_decisiones_documento(
        archivo="200.png",
        datos={"número de guía": "200", "cliente": "EASY RETAIL SA", "RUT del cliente": "50.234.350-5", "obra destino": OBRA_TEXTO},
        carpeta_catalogos=catalogos, despachar_a_documental=DESTINO_TEXTO,
    )
    assert not any(d["tipo"] in {"OBRA_DESCONOCIDA", "DESTINO_SIN_CONFIRMAR"} for d in nuevas)


def test_segunda_guia_misma_obra_destino_no_pregunta(tmp_path):
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path)
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR")
    nuevas = detectar_decisiones_documento(
        archivo="201.png",
        datos={"número de guía": "201", "cliente": "CONSTRUMART SA", "RUT del cliente": "76.123.987-2", "obra destino": OBRA_TEXTO},
        carpeta_catalogos=catalogos, despachar_a_documental=DESTINO_TEXTO,
    )
    assert not any(d["tipo"] in {"OBRA_DESCONOCIDA", "DESTINO_SIN_CONFIRMAR"} for d in nuevas)


def test_repetir_confirmar_no_duplica(tmp_path):
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path)
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR")
    segunda = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR")
    assert segunda["idempotente"] is True
    destinos = CatalogoDestinos(catalogos/"destinos_maestros.json", ruta_clientes=catalogos/"clientes.json").listar()
    assert len(destinos) == 1


# --- NO CONFIRMAR ---

def test_no_confirmar_no_crea_destino_ni_relacion_y_queda_auditado(tmp_path):
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path)
    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="NO_CONFIRMAR")
    assert resultado["ok"]
    assert CatalogoDestinos(catalogos/"destinos_maestros.json", ruta_clientes=catalogos/"clientes.json").listar() == []
    assert CatalogoObrasDestinos(ruta=catalogos/"obras_destinos.json", ruta_clientes=catalogos/"clientes.json", ruta_destinos=catalogos/"destinos_maestros.json").listar_relaciones() == []
    ledger = json.loads((actual/"decisiones_aplicadas.json").read_text(encoding="utf-8"))
    assert ledger["aplicaciones"][0]["accion"] == "NO_CONFIRMAR"
    assert _pendientes(actual) == []


def test_no_confirmar_misma_evidencia_no_reaparece_pero_guia_nueva_si(tmp_path):
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path)
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="NO_CONFIRMAR")
    # La misma decisión no vuelve a aparecer si se regenera con la misma evidencia.
    generar_artefacto(ruta_dataset=actual/"analisis_completo_guias.csv", carpeta_catalogos=catalogos, decisiones=[decision], ruta_salida=actual/"decisiones_pendientes.json")
    assert _pendientes(actual) == []
    # Una guía nueva con evidencia distinta SÍ puede volver a preguntar.
    nuevas = detectar_decisiones_documento(
        archivo="202.png",
        datos={"número de guía": "202", "cliente": "CONSTRUMART SA", "RUT del cliente": "76.123.987-2", "obra destino": OBRA_TEXTO},
        carpeta_catalogos=catalogos, despachar_a_documental=DESTINO_TEXTO,
    )
    assert any(d["tipo"] == "DESTINO_SIN_CONFIRMAR" for d in nuevas)


# --- POSPONER ---

def test_posponer_no_escribe_y_conserva_pendiente(tmp_path):
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path)
    antes = {p: p.read_bytes() for p in [catalogos/"obras_destinos.json", catalogos/"destinos_maestros.json", actual/"decisiones_pendientes.json"]}
    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="POSPONER")
    assert resultado["accion"] == "POSPONER" and not (actual/"decisiones_aplicadas.json").exists()
    assert len(_pendientes(actual)) == 1
    assert antes == {p: p.read_bytes() for p in antes}


# --- obsolescencia / rollback ---

def test_estado_obsoleto_por_catalogo_se_abstiene_sin_escribir(tmp_path):
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path)
    otro = CatalogoClientes(catalogos/"clientes.json").crear(razon_social="OTRO SPA", fuente="TEST")
    antes_destinos = (catalogos/"destinos_maestros.json").read_bytes()
    antes_obras = (catalogos/"obras_destinos.json").read_bytes()
    with pytest.raises(DecisionObsoletaError):
        aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR")
    assert (catalogos/"destinos_maestros.json").read_bytes() == antes_destinos
    assert (catalogos/"obras_destinos.json").read_bytes() == antes_obras


def test_fallo_posterior_revierte_destinos_obras_ledger_y_artefacto(tmp_path, monkeypatch):
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path)
    rutas = [catalogos/"obras_destinos.json", catalogos/"destinos_maestros.json", actual/"decisiones_pendientes.json"]
    antes = {p: p.read_bytes() for p in rutas}
    monkeypatch.setattr(modulo, "generar_artefacto", lambda **k: (_ for _ in ()).throw(OSError("fallo sintético")))
    with pytest.raises(OSError):
        aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR")
    assert antes == {p: p.read_bytes() for p in rutas}
    assert not (actual/"decisiones_aplicadas.json").exists()


def test_accion_de_otro_tipo_es_rechazada(tmp_path):
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path)
    with pytest.raises(ErrorAplicacionDecision):
        aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR")


# --- revalidación sin OCR ---

def test_revalidar_retira_motivo_cuando_ya_resuelto_y_preserva_lo_demas(tmp_path):
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path)
    _confirmar_relacion_directamente(catalogos, cliente, obra)
    dataset = actual / "analisis_completo_guias.csv"
    fila_antes = list(csv.DictReader(dataset.open(encoding="utf-8-sig"), delimiter=";"))[0]

    resultado = revalidar_obra_destino_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=catalogos)
    assert resultado["guias_actualizadas"] == ["464715"]

    filas = list(csv.DictReader(dataset.open(encoding="utf-8-sig"), delimiter=";"))
    assert len(filas) == 1
    fila = filas[0]
    assert "OBRA_DESTINO_SIN_CORROBORAR" not in fila["motivos_revision_documento"]
    assert fila["indicador_revision"] == "OK"
    # Todo dato documental permanece igual.
    for campo in ("numero_guia", "numero_transporte", "fecha", "cliente", "obra_destino", "chofer",
                  "patente_tracto", "patente_rampla", "descripcion_material", "peso_kg",
                  "hora_entrada_aza", "hora_salida_aza", "despachar_a_crudo"):
        assert fila[campo] == fila_antes[campo]


def test_revalidar_no_afecta_filas_no_relacionadas(tmp_path):
    otra_fila = _fila_csv(numero_guia="999", obra_destino="OTRA OBRA", motivos_revision_documento="CLIENTE_AUSENTE")
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path, filas_csv=[_fila_csv(), otra_fila])
    _confirmar_relacion_directamente(catalogos, cliente, obra)
    dataset = actual / "analisis_completo_guias.csv"
    resultado = revalidar_obra_destino_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=catalogos)
    assert resultado["guias_actualizadas"] == ["464715"]
    filas = {f["numero_guia"]: f for f in csv.DictReader(dataset.open(encoding="utf-8-sig"), delimiter=";")}
    assert filas["999"]["motivos_revision_documento"] == "CLIENTE_AUSENTE"  # intacta


def test_revalidar_preserva_otros_motivos_bloqueantes_e_indicador_sigue_revisar(tmp_path):
    fila = _fila_csv(motivos_revision_documento="PATENTE_SIN_HOMOLOGAR | OBRA_DESTINO_SIN_CORROBORAR")
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path, filas_csv=[fila])
    _confirmar_relacion_directamente(catalogos, cliente, obra)
    dataset = actual / "analisis_completo_guias.csv"
    revalidar_obra_destino_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=catalogos)
    fila_final = list(csv.DictReader(dataset.open(encoding="utf-8-sig"), delimiter=";"))[0]
    assert fila_final["motivos_revision_documento"] == "PATENTE_SIN_HOMOLOGAR"
    assert fila_final["indicador_revision"] == "REVISAR"  # sigue habiendo un motivo bloqueante


def test_revalidar_ignora_fila_con_cliente_ausente_si_obra_destino_resuelve(tmp_path):
    """Caso real 464740: cliente documental ausente, pero la obra+destino
    global ya resueltos deben limpiar el motivo igual -- no depende del
    cliente de ESTA fila."""
    fila = _fila_csv(numero_guia="464740", cliente="No encontrado")
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path, filas_csv=[fila])
    _confirmar_relacion_directamente(catalogos, cliente, obra)
    dataset = actual / "analisis_completo_guias.csv"
    resultado = revalidar_obra_destino_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=catalogos)
    assert resultado["guias_actualizadas"] == ["464740"]


def test_revalidar_no_modifica_catalogos(tmp_path):
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path)
    _confirmar_relacion_directamente(catalogos, cliente, obra)
    antes = {p.name: p.read_bytes() for p in catalogos.iterdir()}
    revalidar_obra_destino_sin_ocr(ruta_dataset=actual/"analisis_completo_guias.csv", carpeta_catalogos=catalogos)
    assert antes == {p.name: p.read_bytes() for p in catalogos.iterdir()}


def test_revalidar_y_regenerar_reporte_publica_nuevo_reporte_vigente(tmp_path):
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path)
    _confirmar_relacion_directamente(catalogos, cliente, obra)
    resultado = revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_prueba_r34")
    assert resultado["reporte_regenerado"] is True
    estado = json.loads((actual/"estado_operacion.json").read_text(encoding="utf-8"))
    assert estado["reporte_vigente"] == "reportes/reporte_prueba_r34"
    assert (raiz/"reportes"/"reporte_prueba_r34"/"viajes.csv").exists()


def test_revalidar_y_regenerar_reporte_no_hace_nada_si_no_cambio_nada(tmp_path):
    fila = _fila_csv(motivos_revision_documento="CLIENTE_AUSENTE")  # nada que revalidar
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path, filas_csv=[fila])
    resultado = revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_no_deberia_existir")
    assert resultado["reporte_regenerado"] is False
    assert not (raiz/"reportes"/"reporte_no_deberia_existir").exists()


def test_confirmar_integra_revalidacion_automaticamente_y_reporte_vigente_cambia(tmp_path):
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path)
    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR")
    assert resultado["revalidacion"]["reporte_regenerado"] is True
    dataset = actual / "analisis_completo_guias.csv"
    fila = list(csv.DictReader(dataset.open(encoding="utf-8-sig"), delimiter=";"))[0]
    assert "OBRA_DESTINO_SIN_CORROBORAR" not in fila["motivos_revision_documento"]
    assert fila["indicador_revision"] == "OK"


# --- R3.5: regeneración automática encadenada sin OCR ---

def _agregar_caso_destino(catalogos, cliente, *, guia, obra_texto, destino_texto):
    obras = CatalogoObrasDestinos(
        ruta=catalogos/"obras_destinos.json", ruta_clientes=catalogos/"clientes.json",
        ruta_destinos=catalogos/"destinos_maestros.json",
    )
    evidencia = Evidencia(
        tipo=TipoEvidencia.GUIA.value, identificador_fuente=guia,
        referencia_hash=(guia * 64)[:64], campos_observados={"obra": obra_texto},
        fecha="2026-01-01T00:00:00+00:00", actor_proceso="TEST",
        resultado=ResultadoEvidencia.SOPORTA.value,
    )
    obra = obras.registrar_observacion(
        cliente_id=cliente.cliente_id, nombre_obra=obra_texto, evidencia=evidencia,
    ).obra
    return crear_decision(
        tipo="DESTINO_SIN_CONFIRMAR", entidad="RELACION_OBRA_DESTINO",
        archivo=f"{guia}.jpeg", numero_guia=guia, numero_transporte=f"T-{guia}",
        campo="destino_entrega", valor_documental=destino_texto,
        valor_normalizado=destino_texto, identidad_resuelta={
            "entidad_id": obra.obra_id, "valor_canonico": obra_texto,
        }, candidatos=(), motivos=("OBRA_SIN_RELACION_CONFIRMADA_UNICA",),
        evidencias=({"tipo": "OBRA_IDENTIFICADA", "entidad_id": obra.obra_id},),
        acciones_permitidas=("CONFIRMAR", "NO_CONFIRMAR", "POSPONER"),
        contexto={
            "cliente_id": cliente.cliente_id, "cliente_canonico": "CONSTRUMART SA",
            "obra_id": obra.obra_id, "obra_canonica": obra_texto,
            "destino_documental": destino_texto,
        },
    )


def test_r35_e2e_aplica_a_regenera_y_aplica_b_inmediatamente_sin_ocr(tmp_path):
    fila_b = _fila_csv(
        numero_guia="464716", numero_transporte="T-464716", obra_destino="OBRA B",
        despachar_a_crudo="CALLE B 200", motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR",
    )
    raiz, catalogos, actual, cliente, obra, decision_a = _entorno(
        tmp_path, filas_csv=[_fila_csv(), fila_b],
    )
    decision_b = _agregar_caso_destino(
        catalogos, cliente, guia="464716", obra_texto="OBRA B", destino_texto="CALLE B 200",
    )
    decision_b["contexto"]["cliente_canonico"] = "CONTEXTO ANTIGUO"
    generar_artefacto(
        ruta_dataset=actual/"analisis_completo_guias.csv", carpeta_catalogos=catalogos,
        decisiones=[decision_a, decision_b], ruta_salida=actual/"decisiones_pendientes.json",
    )

    resultado_a = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision_a["decision_id"], accion="CONFIRMAR",
    )
    artefacto_tras_a = json.loads((actual/"decisiones_pendientes.json").read_text(encoding="utf-8"))
    assert resultado_a["ok"] and resultado_a["revalidacion"]["guias_actualizadas"] == ["464715"]
    assert [d["decision_id"] for d in artefacto_tras_a["decisiones"]] == [decision_b["decision_id"]]
    assert artefacto_tras_a["decisiones"][0]["contexto"]["cliente_canonico"] == "CONSTRUMART SA"
    assert artefacto_tras_a["dataset_sha256"] == modulo._sha(actual/"analisis_completo_guias.csv")

    resultado_b = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision_b["decision_id"], accion="CONFIRMAR",
    )
    assert resultado_b["ok"] and _pendientes(actual) == []
    ledger = json.loads((actual/"decisiones_aplicadas.json").read_text(encoding="utf-8"))
    assert [a["decision_id"] for a in ledger["aplicaciones"]] == [
        decision_a["decision_id"], decision_b["decision_id"],
    ]


def test_r35_si_a_resuelve_indirectamente_b_b_desaparece(tmp_path):
    raiz, catalogos, actual, cliente, obra, decision_a = _entorno(
        tmp_path, filas_csv=[_fila_csv(), _fila_csv(numero_guia="464740")],
    )
    decision_b = crear_decision(
        tipo="DESTINO_SIN_CONFIRMAR", entidad="RELACION_OBRA_DESTINO",
        archivo="464740.jpeg", numero_guia="464740", numero_transporte="T2",
        campo="destino_entrega", valor_documental=DESTINO_TEXTO,
        valor_normalizado=DESTINO_TEXTO,
        identidad_resuelta={"entidad_id": obra.obra_id, "valor_canonico": OBRA_TEXTO},
        candidatos=(), motivos=("OBRA_SIN_RELACION_CONFIRMADA_UNICA",),
        evidencias=({"tipo": "OBRA_IDENTIFICADA", "entidad_id": obra.obra_id},),
        acciones_permitidas=("CONFIRMAR", "NO_CONFIRMAR", "POSPONER"),
        contexto={"cliente_id": cliente.cliente_id, "cliente_canonico": "CONSTRUMART SA",
                  "obra_id": obra.obra_id, "obra_canonica": OBRA_TEXTO,
                  "destino_documental": DESTINO_TEXTO},
    )
    generar_artefacto(
        ruta_dataset=actual/"analisis_completo_guias.csv", carpeta_catalogos=catalogos,
        decisiones=[decision_a, decision_b], ruta_salida=actual/"decisiones_pendientes.json",
    )
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision_a["decision_id"], accion="CONFIRMAR")
    assert _pendientes(actual) == []


def test_r35_fallo_al_publicar_bandeja_revierte_dataset_estado_reporte_y_ledger(tmp_path, monkeypatch):
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path)
    rutas = [
        catalogos/"obras_destinos.json", catalogos/"destinos_maestros.json",
        actual/"analisis_completo_guias.csv", actual/"decisiones_pendientes.json",
    ]
    antes = {p: p.read_bytes() for p in rutas}
    monkeypatch.setattr(modulo, "generar_artefacto", lambda **k: (_ for _ in ()).throw(OSError("fallo R3.5")))
    with pytest.raises(OSError, match="fallo R3.5"):
        aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR")
    assert antes == {p: p.read_bytes() for p in rutas}
    assert not (actual/"decisiones_aplicadas.json").exists()
    assert not (actual/"estado_operacion.json").exists()
    assert list((raiz/"reportes").iterdir()) == []


def _entorno_dos_destinos(tmp_path):
    fila_b = _fila_csv(
        numero_guia="464716", numero_transporte="T-464716", obra_destino="OBRA B",
        despachar_a_crudo="CALLE B 200", motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR",
    )
    raiz, catalogos, actual, cliente, obra, decision_a = _entorno(
        tmp_path, filas_csv=[_fila_csv(), fila_b],
    )
    decision_b = _agregar_caso_destino(
        catalogos, cliente, guia="464716", obra_texto="OBRA B", destino_texto="CALLE B 200",
    )
    generar_artefacto(
        ruta_dataset=actual/"analisis_completo_guias.csv", carpeta_catalogos=catalogos,
        decisiones=[decision_a, decision_b], ruta_salida=actual/"decisiones_pendientes.json",
    )
    return raiz, catalogos, actual, decision_a, decision_b


def _crear_ventana_legacy_r34(raiz, actual, decision_a, monkeypatch):
    import atlas_core.revalidacion_documental as revalidacion
    real = revalidacion.revalidar_y_regenerar_reporte
    monkeypatch.setattr(
        revalidacion, "revalidar_y_regenerar_reporte",
        lambda **k: {"guias_actualizadas": [], "reporte_regenerado": False},
    )
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision_a["decision_id"], accion="CONFIRMAR")
    monkeypatch.setattr(revalidacion, "revalidar_y_regenerar_reporte", real)
    # Secuencia exacta R3.4 real: bandeja ya publicada; después cambia el CSV
    # y se publica reporte/estado, pero la bandeja conserva el hash anterior.
    real(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_revalidacion_legacy")
    artefacto = json.loads((actual/"decisiones_pendientes.json").read_text(encoding="utf-8"))
    assert artefacto["dataset_sha256"] != modulo._sha(actual/"analisis_completo_guias.csv")


def test_r351_reproduce_bandeja_real_legacy_y_aplica_siguiente_decision(tmp_path, monkeypatch):
    raiz, catalogos, actual, decision_a, decision_b = _entorno_dos_destinos(tmp_path)
    _crear_ventana_legacy_r34(raiz, actual, decision_a, monkeypatch)

    # Antes de R3.5.1 esta llamada fallaba por hash stale, igual que SIGRO.
    resultado_b = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision_b["decision_id"], accion="CONFIRMAR",
    )
    assert resultado_b["ok"] and _pendientes(actual) == []
    ledger = json.loads((actual/"decisiones_aplicadas.json").read_text(encoding="utf-8"))
    assert [a["decision_id"] for a in ledger["aplicaciones"]] == [
        decision_a["decision_id"], decision_b["decision_id"],
    ]


def test_r351_cambio_externo_despues_del_reporte_publicado_sigue_obsoleto(tmp_path, monkeypatch):
    raiz, catalogos, actual, decision_a, decision_b = _entorno_dos_destinos(tmp_path)
    _crear_ventana_legacy_r34(raiz, actual, decision_a, monkeypatch)
    dataset = actual/"analisis_completo_guias.csv"
    dataset.write_bytes(dataset.read_bytes() + b"\n")
    with pytest.raises(DecisionObsoletaError):
        aplicar_decision_obra(
            raiz_atlas=raiz, decision_id=decision_b["decision_id"], accion="CONFIRMAR",
        )
