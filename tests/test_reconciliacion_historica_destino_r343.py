"""R3.4.3: reconciliación histórica READ-ONLY de decisiones DESTINO_SIN_CONFIRMAR
que quedaron atrapadas porque su OBRA_DESCONOCIDA se REGISTRÓ antes de que
existiera el fix de R3.4.2 (el `contexto.destino_documental` nunca se
persistió para esas aplicaciones ya hechas, y ya no están en la bandeja
pendiente para que `regenerar_decisiones_persistidas` las reclasifique).

`detectar_decisiones_destino_historicas_sin_ocr` reconstruye, exclusivamente
a partir de identidad canónica ya persistida (obra_id/cliente_id del propio
ledger + fila del dataset correlacionada por el mismo numero_guia), la
decisión que R3.4.2 habría generado en su momento. No usa fuzzy matching,
no infiere nada por nombre, no ejecuta OCR."""
import csv
import json

from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_destinos import CatalogoDestinos
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, ResultadoEvidencia, TipoEvidencia
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    detectar_decisiones_destino_historicas_sin_ocr,
    reconciliar_decisiones_destino_historicas,
)

OBRA_TEXTO = "CONSULTORES EN ARQUITECTURA"
DESTINO_TEXTO = "RICARDO MORALES 3369 SAN MIGUEL SAN MIGUEL"


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "464718.jpeg", "estado_procesamiento": "OK", "numero_guia": "464718",
        "numero_transporte": "T-464718", "fecha": "12-08-2026", "chofer": "CHOFER TEST",
        "cliente": "EBEMA SA", "obra_destino": OBRA_TEXTO,
        "patente_tracto": "BDFG50", "patente_rampla": "No encontrado",
        "descripcion_material": "MATERIAL", "tipo_carga": "OTRO",
        "indicador_revision": "REVISAR",
        "motivos_revision_documento": "OBRA_DESTINO_SIN_CORROBORAR",
        "despachar_a_crudo": DESTINO_TEXTO, "estado_entrega": "RESUELTO",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _entorno(tmp_path):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"; actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True); catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []}, "empresas.json": {}, "vehiculos.json": {},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    return raiz, catalogos, actual


def _cliente(catalogos, nombre="EBEMA SA", rut="76.123.987-2"):
    return CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social=nombre, rut=rut, fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )


def _registrar_obra(catalogos, *, cliente, obra_texto, guia):
    """Simula lo que hacía `aplicar_decision_obra` (REGISTRAR) ANTES de
    R3.4.2: crea la obra pero nunca la relación."""
    obras = CatalogoObrasDestinos(ruta=catalogos/"obras_destinos.json", ruta_clientes=catalogos/"clientes.json", ruta_destinos=catalogos/"destinos_maestros.json")
    evidencia = Evidencia(
        tipo=TipoEvidencia.GUIA.value, identificador_fuente=guia, referencia_hash="a"*64,
        campos_observados={"obra": obra_texto}, fecha="2026-01-01T00:00:00+00:00",
        actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value,
    )
    return obras.registrar_observacion(cliente_id=cliente.cliente_id, nombre_obra=obra_texto, evidencia=evidencia).obra


def _ledger_registro_obra(*, guia, obra, cliente, obra_texto, transporte=None):
    """Reproduce EXACTAMENTE el shape de un `decisiones_aplicadas.json` real
    (mismos campos que escribe `aplicar_decision_obra` hoy)."""
    return {
        "decision_id": f"ID-{guia}", "tipo": "OBRA_DESCONOCIDA", "accion": "REGISTRAR",
        "actor": "JAVIER_DESKTOP", "fecha": "2026-08-17T16:03:50.634875+00:00",
        "documento": {"archivo": f"{guia}.jpeg", "numero_guia": guia, "numero_transporte": transporte or f"T-{guia}"},
        "valor_documental": obra_texto, "cliente_id": cliente.cliente_id, "obra_id": obra.obra_id,
        "dataset_sha256": "X", "catalogos_sha256_antes": {},
    }


def _escribir_ledger(actual, aplicaciones):
    (actual/"decisiones_aplicadas.json").write_text(
        json.dumps({"schema_version": 1, "aplicaciones": aplicaciones}), encoding="utf-8",
    )


# --- detectar_decisiones_destino_historicas_sin_ocr ---

def test_detecta_candidato_para_obra_registrada_con_destino(tmp_path):
    raiz, catalogos, actual = _entorno(tmp_path)
    cliente = _cliente(catalogos)
    obra = _registrar_obra(catalogos, cliente=cliente, obra_texto=OBRA_TEXTO, guia="464718")
    _escribir_csv(actual/"analisis_completo_guias.csv", [_fila_csv()])
    _escribir_ledger(actual, [_ledger_registro_obra(guia="464718", obra=obra, cliente=cliente, obra_texto=OBRA_TEXTO)])

    candidatas = detectar_decisiones_destino_historicas_sin_ocr(raiz_atlas=raiz)
    assert len(candidatas) == 1
    d = candidatas[0]
    assert d["tipo"] == "DESTINO_SIN_CONFIRMAR"
    assert d["valor_documental"] == DESTINO_TEXTO
    assert d["identidad_resuelta"]["entidad_id"] == obra.obra_id
    assert d["contexto"]["cliente_id"] == cliente.cliente_id
    assert d["documento"]["numero_guia"] == "464718"
    assert d["acciones_permitidas"] == ["CONFIRMAR", "NO_CONFIRMAR", "POSPONER"]


def test_caso_a_obra_ya_confirmada_no_genera_candidato(tmp_path):
    raiz, catalogos, actual = _entorno(tmp_path)
    cliente = _cliente(catalogos)
    obra = _registrar_obra(catalogos, cliente=cliente, obra_texto=OBRA_TEXTO, guia="464718")
    obras_cat = CatalogoObrasDestinos(ruta=catalogos/"obras_destinos.json", ruta_clientes=catalogos/"clientes.json", ruta_destinos=catalogos/"destinos_maestros.json")
    destino = CatalogoDestinos(catalogos/"destinos_maestros.json", ruta_clientes=catalogos/"clientes.json").crear_o_reutilizar_global(
        nombre_destino=DESTINO_TEXTO, direccion=DESTINO_TEXTO, fuente="TEST",
    )
    evidencia = Evidencia(tipo=TipoEvidencia.GUIA.value, identificador_fuente="otra", referencia_hash="b"*64, campos_observados={"obra": OBRA_TEXTO}, fecha="2026-01-01T00:00:00+00:00", actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value)
    pendiente = obras_cat.registrar_observacion(cliente_id=cliente.cliente_id, nombre_obra=OBRA_TEXTO, destino_id=destino.destino_id, evidencia=evidencia).relacion
    obras_cat.confirmar_relacion(pendiente.relacion_id, actor="test")

    _escribir_csv(actual/"analisis_completo_guias.csv", [_fila_csv()])
    _escribir_ledger(actual, [_ledger_registro_obra(guia="464718", obra=obra, cliente=cliente, obra_texto=OBRA_TEXTO)])
    assert detectar_decisiones_destino_historicas_sin_ocr(raiz_atlas=raiz) == []


def test_caso_c_sin_destino_documental_no_genera_candidato(tmp_path):
    raiz, catalogos, actual = _entorno(tmp_path)
    cliente = _cliente(catalogos)
    obra = _registrar_obra(catalogos, cliente=cliente, obra_texto=OBRA_TEXTO, guia="464718")
    _escribir_csv(actual/"analisis_completo_guias.csv", [_fila_csv(despachar_a_crudo="")])
    _escribir_ledger(actual, [_ledger_registro_obra(guia="464718", obra=obra, cliente=cliente, obra_texto=OBRA_TEXTO)])
    assert detectar_decisiones_destino_historicas_sin_ocr(raiz_atlas=raiz) == []


def test_fila_csv_ausente_no_genera_candidato(tmp_path):
    raiz, catalogos, actual = _entorno(tmp_path)
    cliente = _cliente(catalogos)
    obra = _registrar_obra(catalogos, cliente=cliente, obra_texto=OBRA_TEXTO, guia="464718")
    _escribir_csv(actual/"analisis_completo_guias.csv", [_fila_csv(numero_guia="999999")])
    _escribir_ledger(actual, [_ledger_registro_obra(guia="464718", obra=obra, cliente=cliente, obra_texto=OBRA_TEXTO)])
    assert detectar_decisiones_destino_historicas_sin_ocr(raiz_atlas=raiz) == []


def test_fila_csv_ambigua_no_genera_candidato(tmp_path):
    raiz, catalogos, actual = _entorno(tmp_path)
    cliente = _cliente(catalogos)
    obra = _registrar_obra(catalogos, cliente=cliente, obra_texto=OBRA_TEXTO, guia="464718")
    _escribir_csv(actual/"analisis_completo_guias.csv", [_fila_csv(), _fila_csv(archivo="464718_dup.jpeg")])
    _escribir_ledger(actual, [_ledger_registro_obra(guia="464718", obra=obra, cliente=cliente, obra_texto=OBRA_TEXTO)])
    assert detectar_decisiones_destino_historicas_sin_ocr(raiz_atlas=raiz) == []


def test_obra_destino_documental_no_coincide_no_genera_candidato(tmp_path):
    """La fila con ese numero_guia existe, pero su `obra_destino` documental
    NO es la misma obra que el ledger asoció -- correlación no confiable
    (p.ej. numero_guia reutilizado/otro caso), se descarta sin adivinar."""
    raiz, catalogos, actual = _entorno(tmp_path)
    cliente = _cliente(catalogos)
    obra = _registrar_obra(catalogos, cliente=cliente, obra_texto=OBRA_TEXTO, guia="464718")
    _escribir_csv(actual/"analisis_completo_guias.csv", [_fila_csv(obra_destino="OTRA OBRA DISTINTA")])
    _escribir_ledger(actual, [_ledger_registro_obra(guia="464718", obra=obra, cliente=cliente, obra_texto=OBRA_TEXTO)])
    assert detectar_decisiones_destino_historicas_sin_ocr(raiz_atlas=raiz) == []


def test_obra_inactiva_no_genera_candidato(tmp_path):
    raiz, catalogos, actual = _entorno(tmp_path)
    cliente = _cliente(catalogos)
    obra = _registrar_obra(catalogos, cliente=cliente, obra_texto=OBRA_TEXTO, guia="464718")
    contenido = json.loads((catalogos/"obras_destinos.json").read_text(encoding="utf-8"))
    for o in contenido["obras"]:
        if o["obra_id"] == obra.obra_id:
            o["estado_vigencia"] = "INACTIVO"
    (catalogos/"obras_destinos.json").write_text(json.dumps(contenido), encoding="utf-8")
    _escribir_csv(actual/"analisis_completo_guias.csv", [_fila_csv()])
    _escribir_ledger(actual, [_ledger_registro_obra(guia="464718", obra=obra, cliente=cliente, obra_texto=OBRA_TEXTO)])
    assert detectar_decisiones_destino_historicas_sin_ocr(raiz_atlas=raiz) == []


def test_cliente_inactivo_no_genera_candidato(tmp_path):
    raiz, catalogos, actual = _entorno(tmp_path)
    cliente = _cliente(catalogos)
    obra = _registrar_obra(catalogos, cliente=cliente, obra_texto=OBRA_TEXTO, guia="464718")
    contenido = json.loads((catalogos/"clientes.json").read_text(encoding="utf-8"))
    for c in contenido["clientes"]:
        if c["cliente_id"] == cliente.cliente_id:
            c["estado_vigencia"] = "INACTIVO"
    (catalogos/"clientes.json").write_text(json.dumps(contenido), encoding="utf-8")
    _escribir_csv(actual/"analisis_completo_guias.csv", [_fila_csv()])
    _escribir_ledger(actual, [_ledger_registro_obra(guia="464718", obra=obra, cliente=cliente, obra_texto=OBRA_TEXTO)])
    assert detectar_decisiones_destino_historicas_sin_ocr(raiz_atlas=raiz) == []


def test_otros_tipos_y_acciones_del_ledger_se_ignoran(tmp_path):
    raiz, catalogos, actual = _entorno(tmp_path)
    cliente = _cliente(catalogos)
    obra = _registrar_obra(catalogos, cliente=cliente, obra_texto=OBRA_TEXTO, guia="464718")
    _escribir_csv(actual/"analisis_completo_guias.csv", [_fila_csv()])
    otros = [
        {**_ledger_registro_obra(guia="464718", obra=obra, cliente=cliente, obra_texto=OBRA_TEXTO), "tipo": "VEHICULO_DESCONOCIDO"},
        {**_ledger_registro_obra(guia="464718", obra=obra, cliente=cliente, obra_texto=OBRA_TEXTO), "accion": "NO_REGISTRAR"},
    ]
    _escribir_ledger(actual, otros)
    assert detectar_decisiones_destino_historicas_sin_ocr(raiz_atlas=raiz) == []


def test_dos_casos_reales_generan_dos_candidatos_y_un_tercero_ya_confirmado_no(tmp_path):
    """Reproduce, de forma genérica (sin mencionar guías reales en el
    código), la forma exacta del caso real: 3 obras registradas -- una ya
    corroborada (no genera nada) y dos con destino documental pendiente
    (generan candidato cada una)."""
    raiz, catalogos, actual = _entorno(tmp_path)
    cliente_a = _cliente(catalogos, nombre="EBEMA SA", rut="76.123.987-2")
    cliente_b = _cliente(catalogos, nombre="EASY RETAIL SA", rut="50.234.350-5")
    cliente_c = _cliente(catalogos, nombre="CONSTRUMART SA", rut="96.543.210-8")

    obra_1 = _registrar_obra(catalogos, cliente=cliente_a, obra_texto="OBRA UNO", guia="G1")
    obra_2 = _registrar_obra(catalogos, cliente=cliente_b, obra_texto="OBRA DOS", guia="G2")
    obra_3 = _registrar_obra(catalogos, cliente=cliente_c, obra_texto="OBRA TRES YA CONFIRMADA", guia="G3")

    obras_cat = CatalogoObrasDestinos(ruta=catalogos/"obras_destinos.json", ruta_clientes=catalogos/"clientes.json", ruta_destinos=catalogos/"destinos_maestros.json")
    destino_3 = CatalogoDestinos(catalogos/"destinos_maestros.json", ruta_clientes=catalogos/"clientes.json").crear_o_reutilizar_global(nombre_destino="DESTINO TRES", direccion="DESTINO TRES", fuente="TEST")
    evidencia = Evidencia(tipo=TipoEvidencia.GUIA.value, identificador_fuente="otra", referencia_hash="c"*64, campos_observados={"obra": "OBRA TRES YA CONFIRMADA"}, fecha="2026-01-01T00:00:00+00:00", actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value)
    pend = obras_cat.registrar_observacion(cliente_id=cliente_c.cliente_id, nombre_obra="OBRA TRES YA CONFIRMADA", destino_id=destino_3.destino_id, evidencia=evidencia).relacion
    obras_cat.confirmar_relacion(pend.relacion_id, actor="test")

    filas = [
        _fila_csv(archivo="G1.jpeg", numero_guia="G1", numero_transporte="T1", cliente="EBEMA SA", obra_destino="OBRA UNO", despachar_a_crudo="DIRECCION UNO"),
        _fila_csv(archivo="G2.jpeg", numero_guia="G2", numero_transporte="T2", cliente="EASY RETAIL SA", obra_destino="OBRA DOS", despachar_a_crudo="DIRECCION DOS"),
        _fila_csv(archivo="G3.jpeg", numero_guia="G3", numero_transporte="T3", cliente="CONSTRUMART SA", obra_destino="OBRA TRES YA CONFIRMADA", despachar_a_crudo="DESTINO TRES"),
    ]
    _escribir_csv(actual/"analisis_completo_guias.csv", filas)
    _escribir_ledger(actual, [
        _ledger_registro_obra(guia="G1", obra=obra_1, cliente=cliente_a, obra_texto="OBRA UNO", transporte="T1"),
        _ledger_registro_obra(guia="G2", obra=obra_2, cliente=cliente_b, obra_texto="OBRA DOS", transporte="T2"),
        _ledger_registro_obra(guia="G3", obra=obra_3, cliente=cliente_c, obra_texto="OBRA TRES YA CONFIRMADA", transporte="T3"),
    ])

    candidatas = detectar_decisiones_destino_historicas_sin_ocr(raiz_atlas=raiz)
    guias = sorted(d["documento"]["numero_guia"] for d in candidatas)
    assert guias == ["G1", "G2"]  # G3 ya corroborada -- CASO A, sin candidato


# --- reconciliar_decisiones_destino_historicas ---

def test_reconciliar_publica_candidatas_sin_tocar_catalogos_csv_ni_ledger(tmp_path):
    raiz, catalogos, actual = _entorno(tmp_path)
    cliente = _cliente(catalogos)
    obra = _registrar_obra(catalogos, cliente=cliente, obra_texto=OBRA_TEXTO, guia="464718")
    dataset = actual/"analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila_csv()])
    ledger_ruta = actual/"decisiones_aplicadas.json"
    _escribir_ledger(actual, [_ledger_registro_obra(guia="464718", obra=obra, cliente=cliente, obra_texto=OBRA_TEXTO)])
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[], ruta_salida=actual/"decisiones_pendientes.json")

    antes = {
        "catalogos": {p.name: p.read_bytes() for p in catalogos.iterdir()},
        "csv": dataset.read_bytes(),
        "ledger": ledger_ruta.read_bytes(),
    }
    resultado = reconciliar_decisiones_destino_historicas(raiz_atlas=raiz)
    assert resultado["decisiones_candidatas"] == 1
    assert resultado["decisiones_publicadas"] == 1

    assert {p.name: p.read_bytes() for p in catalogos.iterdir()} == antes["catalogos"]
    assert dataset.read_bytes() == antes["csv"]
    assert ledger_ruta.read_bytes() == antes["ledger"]

    publicadas = json.loads((actual/"decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]
    assert len(publicadas) == 1 and publicadas[0]["tipo"] == "DESTINO_SIN_CONFIRMAR"
    assert publicadas[0]["documento"]["numero_guia"] == "464718"


def test_reconciliar_es_idempotente_no_duplica(tmp_path):
    raiz, catalogos, actual = _entorno(tmp_path)
    cliente = _cliente(catalogos)
    obra = _registrar_obra(catalogos, cliente=cliente, obra_texto=OBRA_TEXTO, guia="464718")
    dataset = actual/"analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila_csv()])
    _escribir_ledger(actual, [_ledger_registro_obra(guia="464718", obra=obra, cliente=cliente, obra_texto=OBRA_TEXTO)])
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[], ruta_salida=actual/"decisiones_pendientes.json")

    reconciliar_decisiones_destino_historicas(raiz_atlas=raiz)
    primera = json.loads((actual/"decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]
    resultado_2 = reconciliar_decisiones_destino_historicas(raiz_atlas=raiz)
    segunda = json.loads((actual/"decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]
    assert len(primera) == 1 and len(segunda) == 1
    assert primera[0]["decision_id"] == segunda[0]["decision_id"]
    assert resultado_2["decisiones_publicadas"] == 1


def test_reconciliar_no_resucita_decision_terminal(tmp_path):
    raiz, catalogos, actual = _entorno(tmp_path)
    cliente = _cliente(catalogos)
    obra = _registrar_obra(catalogos, cliente=cliente, obra_texto=OBRA_TEXTO, guia="464718")
    dataset = actual/"analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila_csv()])
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[], ruta_salida=actual/"decisiones_pendientes.json")

    # Averiguamos el decision_id determinístico que se sintetizaría...
    _escribir_ledger(actual, [_ledger_registro_obra(guia="464718", obra=obra, cliente=cliente, obra_texto=OBRA_TEXTO)])
    candidatas = detectar_decisiones_destino_historicas_sin_ocr(raiz_atlas=raiz)
    assert len(candidatas) == 1
    decision_id_sintetizada = candidatas[0]["decision_id"]

    # ...y simulamos que YA fue rechazada terminalmente antes de reconciliar.
    ledger_actual = json.loads((actual/"decisiones_aplicadas.json").read_text(encoding="utf-8"))
    ledger_actual["aplicaciones"].append({
        "decision_id": decision_id_sintetizada, "tipo": "DESTINO_SIN_CONFIRMAR", "accion": "NO_CONFIRMAR",
        "actor": "JAVIER_DESKTOP", "fecha": "2026-08-17T20:00:00+00:00",
        "documento": {"archivo": "464718.jpeg", "numero_guia": "464718", "numero_transporte": "T-464718"},
        "valor_documental": DESTINO_TEXTO, "cliente_id": cliente.cliente_id, "obra_id": obra.obra_id,
        "destino_id": None, "relacion_id": None, "dataset_sha256": "X", "catalogos_sha256_antes": {},
    })
    (actual/"decisiones_aplicadas.json").write_text(json.dumps(ledger_actual), encoding="utf-8")

    resultado = reconciliar_decisiones_destino_historicas(raiz_atlas=raiz)
    assert resultado["decisiones_candidatas"] == 1  # se sintetiza igual...
    assert resultado["decisiones_publicadas"] == 0  # ...pero el ledger la filtra: no resucita
    assert json.loads((actual/"decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"] == []


def test_reconciliar_preserva_decisiones_pendientes_existentes(tmp_path):
    raiz, catalogos, actual = _entorno(tmp_path)
    cliente = _cliente(catalogos)
    obra = _registrar_obra(catalogos, cliente=cliente, obra_texto=OBRA_TEXTO, guia="464718")
    otro_cliente = _cliente(catalogos, nombre="OTRO CLIENTE SPA", rut="11.111.111-1")
    dataset = actual/"analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila_csv()])
    _escribir_ledger(actual, [_ledger_registro_obra(guia="464718", obra=obra, cliente=cliente, obra_texto=OBRA_TEXTO)])

    decision_no_relacionada = crear_decision(
        tipo="OBRA_DESCONOCIDA", entidad="OBRA", archivo="otra.png", numero_guia="OTRA-GUIA",
        numero_transporte="T-X", campo="obra_destino", valor_documental="OBRA SIN RELACION",
        valor_normalizado="OBRA SIN RELACION", identidad_resuelta=None, candidatos=(),
        motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),
        evidencias=({"tipo": "CLIENTE_RESUELTO", "entidad_id": otro_cliente.cliente_id},),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        contexto={"cliente_id": otro_cliente.cliente_id, "cliente_canonico": otro_cliente.razon_social, "destino_documental": ""},
    )
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision_no_relacionada], ruta_salida=actual/"decisiones_pendientes.json")

    resultado = reconciliar_decisiones_destino_historicas(raiz_atlas=raiz)
    assert resultado["decisiones_publicadas"] == 2
    tipos = sorted(d["tipo"] for d in resultado["bandeja"]["decisiones"])
    assert tipos == ["DESTINO_SIN_CONFIRMAR", "OBRA_DESCONOCIDA"]
