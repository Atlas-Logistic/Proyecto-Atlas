"""R4.8 -- Bloque CLIENTE_CANDIDATO: sin RUT documental corroborable, el
nombre documental puede seguir siendo evidencia real de identidad (difuso o
por alias) contra un cliente YA CONFIRMADO/ACTIVO -- caso real 472037/464981
(motivo `CLIENTE_SIN_CORROBORAR` sin ninguna decisión accionable antes de
este bloque)."""
import csv
import json

from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.decisiones_pendientes import detectar_decisiones_documento, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    detectar_decisiones_cliente_candidato_sin_ocr,
    reconciliar_decisiones_cliente_candidato_historico,
    revalidar_cliente_sin_corroborar_sin_ocr,
)


def _catalogos(tmp_path):
    carpeta = tmp_path / "catalogos"; carpeta.mkdir()
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "empresas.json": {},
        "vehiculos.json": {},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    return carpeta


def _cliente_confirmado(carpeta, nombre="COMERCIAL A Y B LTDA", rut="78.634.910-9"):
    return CatalogoClientes(carpeta / "clientes.json").crear(
        razon_social=nombre, rut=rut, fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )


def test_cliente_sin_rut_con_nombre_difuso_genera_cliente_candidato(tmp_path):
    carpeta = _catalogos(tmp_path)
    _cliente_confirmado(carpeta)
    ds = detectar_decisiones_documento(
        archivo="472037.jpeg",
        datos={"número de guía": "472037", "cliente": "COMERCIAL A Y B LTDA",
               "RUT del cliente": "No encontrado", "obra destino": "ING Y CONST FUNDAMENTA SPA"},
        carpeta_catalogos=carpeta,
        cliente_documental_original="CONERCIAL A Y B LTDA",  # typo real de OCR
    )
    candidatas = [d for d in ds if d["tipo"] == "CLIENTE_CANDIDATO"]
    assert len(candidatas) == 1
    assert candidatas[0]["identidad_resuelta"]["valor_canonico"] == "COMERCIAL A Y B LTDA"
    assert candidatas[0]["acciones_permitidas"] == ["CONFIRMAR", "NO_CONFIRMAR", "POSPONER"]
    # La obra no se pregunta todavía -- la identidad de cliente sigue sin
    # confirmar humanamente, sólo es una candidata.
    assert not any(d["tipo"] in ("OBRA_DESCONOCIDA", "DESTINO_SIN_CONFIRMAR") for d in ds)


def test_cliente_sin_rut_realmente_desconocido_no_genera_decision(tmp_path):
    """Control -- sin RUT y sin ningún nombre parecido en catálogo, Atlas
    se abstiene (nunca inventa una sugerencia sin evidencia)."""
    carpeta = _catalogos(tmp_path)
    _cliente_confirmado(carpeta)
    ds = detectar_decisiones_documento(
        archivo="x.jpeg",
        datos={"número de guía": "1", "cliente": "EMPRESA TOTALMENTE DISTINTA SPA",
               "RUT del cliente": "No encontrado"},
        carpeta_catalogos=carpeta,
    )
    assert not any(d["tipo"] == "CLIENTE_CANDIDATO" for d in ds)


def test_cliente_documental_ausente_no_genera_decision(tmp_path):
    carpeta = _catalogos(tmp_path)
    _cliente_confirmado(carpeta)
    ds = detectar_decisiones_documento(
        archivo="x.jpeg", datos={"número de guía": "1", "RUT del cliente": "No encontrado"},
        carpeta_catalogos=carpeta,
    )
    assert not any(d["tipo"] == "CLIENTE_CANDIDATO" for d in ds)


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "472037.jpeg", "estado_procesamiento": "OK", "numero_guia": "472037",
        "numero_transporte": "T1", "fecha": "18/08/2026", "chofer": "CRISTOPHER RETAMAL",
        "cliente": "COMERCIAL A Y B LTDA", "obra_destino": "ING Y CONST FUNDAMENTA SPA",
        "patente_tracto": "BPHR67", "patente_rampla": "No encontrado",
        "descripcion_material": "HORMIGON", "tipo_carga": "OTRO",
        "indicador_revision": "REVISAR",
        "motivos_revision_documento": "CLIENTE_SIN_CORROBORAR | OBRA_DESTINO_SIN_CORROBORAR",
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
    cliente = _cliente_confirmado(catalogos)
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila_csv()])
    ds = detectar_decisiones_documento(
        archivo="472037.jpeg",
        datos={"número de guía": "472037", "número de transporte": "T1",
               "cliente": "COMERCIAL A Y B LTDA", "RUT del cliente": "No encontrado",
               "obra destino": "ING Y CONST FUNDAMENTA SPA"},
        carpeta_catalogos=catalogos, cliente_documental_original="CONERCIAL A Y B LTDA",
    )
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=ds, ruta_salida=actual / "decisiones_pendientes.json")
    decision = next(d for d in ds if d["tipo"] == "CLIENTE_CANDIDATO")
    return raiz, catalogos, actual, cliente, decision


def _pendientes(actual):
    return json.loads((actual / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]


def test_confirmar_cliente_candidato_no_escribe_catalogo_y_encadena_obra(tmp_path):
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    antes = (catalogos / "clientes.json").read_bytes()

    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR")
    assert resultado["ok"] is True
    assert resultado["cliente_id"] == cliente.cliente_id
    # Nunca escribe el catálogo de clientes -- nada que registrar, la
    # entidad ya existía tal cual.
    assert (catalogos / "clientes.json").read_bytes() == antes

    pendientes = _pendientes(actual)
    assert not any(d["decision_id"] == decision["decision_id"] for d in pendientes)
    # La obra encadenada SÍ debe aparecer ahora -- ya hay una identidad de
    # cliente confirmada para preguntar por ella (mismo patrón R3.4.2).
    obra_pendiente = [d for d in pendientes if d["tipo"] == "OBRA_DESCONOCIDA"]
    assert len(obra_pendiente) == 1
    assert obra_pendiente[0]["valor_documental"] == "ING Y CONST FUNDAMENTA SPA"

    ledger = json.loads((actual / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    aplicacion = ledger["aplicaciones"][0]
    assert aplicacion["tipo"] == "CLIENTE_CANDIDATO" and aplicacion["accion"] == "CONFIRMAR"
    assert aplicacion["valor_canonico"] == "COMERCIAL A Y B LTDA"


def test_flujo_completo_472037_termina_sin_estado_intermedio_no_accionable(tmp_path):
    """R4.9, caso real 472037 de punta a punta: CONFIRMAR el cliente
    candidato encadena la obra; REGISTRAR la obra (sin destino documental,
    CASO C -- no genera una decisión siguiente) no debe dejar el viaje en
    un limbo "REVISAR pero nadie puede hacer nada" -- `revalidar_y_
    regenerar_reporte` retira OBRA_DESTINO_SIN_CORROBORAR usando la señal
    del ledger (ver `resolver_obras_resueltas_por_ledger`), y no queda
    ninguna decisión pendiente."""
    from atlas_core.revalidacion_documental import revalidar_y_regenerar_reporte

    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR")
    obra_pendiente = next(d for d in _pendientes(actual) if d["tipo"] == "OBRA_DESCONOCIDA")

    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=obra_pendiente["decision_id"], accion="REGISTRAR")
    assert resultado["ok"] is True
    # REGISTRAR sin destino documental -- CASO C, ninguna decisión siguiente.
    assert not any(d["tipo"] == "DESTINO_SIN_CONFIRMAR" for d in _pendientes(actual))

    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open(encoding="utf-8-sig") as archivo:
        fila = next(csv.DictReader(archivo, delimiter=";"))
    assert "OBRA_DESTINO_SIN_CORROBORAR" in fila["motivos_revision_documento"]  # todavía no revalidado

    revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_r49")

    with dataset.open(encoding="utf-8-sig") as archivo:
        fila_final = next(csv.DictReader(archivo, delimiter=";"))
    assert fila_final["motivos_revision_documento"] == ""
    assert fila_final["indicador_revision"] == "OK"
    assert _pendientes(actual) == []


def test_confirmar_cliente_candidato_limpia_motivo_csv(tmp_path):
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR")

    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open(encoding="utf-8-sig") as archivo:
        fila = next(csv.DictReader(archivo, delimiter=";"))
    assert "CLIENTE_SIN_CORROBORAR" not in fila["motivos_revision_documento"]
    # OBRA_DESTINO_SIN_CORROBORAR sigue -- todavía requiere una decisión
    # separada (la obra recién encadenada), nunca se retira sin evidencia.
    assert "OBRA_DESTINO_SIN_CORROBORAR" in fila["motivos_revision_documento"]


def test_no_confirmar_cliente_candidato_no_encadena_obra(tmp_path):
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="NO_CONFIRMAR")
    assert resultado["ok"] is True
    pendientes = _pendientes(actual)
    assert not any(d["tipo"] == "OBRA_DESCONOCIDA" for d in pendientes)
    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open(encoding="utf-8-sig") as archivo:
        fila = next(csv.DictReader(archivo, delimiter=";"))
    assert "CLIENTE_SIN_CORROBORAR" in fila["motivos_revision_documento"]


def test_revalidar_cliente_sin_corroborar_no_toca_fila_sin_confirmacion_ledger(tmp_path):
    """Control -- sin ninguna confirmación en el ledger, la revalidación
    nunca retira el motivo por sí sola (nunca decide por coincidencia de
    texto suelto)."""
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    dataset = actual / "analisis_completo_guias.csv"
    resultado = revalidar_cliente_sin_corroborar_sin_ocr(
        ruta_dataset=dataset, ruta_ledger=actual / "decisiones_aplicadas.json",
    )
    assert resultado["guias_actualizadas"] == []


def _entorno_historico(tmp_path):
    """Simula el caso real (472037/464981): el documento ya se procesó
    ANTES de que CLIENTE_CANDIDATO existiera -- el CSV ya trae
    `CLIENTE_SIN_CORROBORAR`, pero la bandeja de decisiones está vacía
    (nunca se generó nada, no hay nada que reconciliar)."""
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"; actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True); catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []}, "empresas.json": {}, "vehiculos.json": {},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    cliente = _cliente_confirmado(catalogos)
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila_csv()])
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[], ruta_salida=actual / "decisiones_pendientes.json")
    (actual / "decisiones_aplicadas.json").write_text(json.dumps({"schema_version": 1, "aplicaciones": []}), encoding="utf-8")
    return raiz, catalogos, actual, cliente


def test_detectar_cliente_candidato_sin_ocr_reconstruye_la_decision_desde_el_csv(tmp_path):
    raiz, catalogos, actual, cliente = _entorno_historico(tmp_path)
    candidatas = detectar_decisiones_cliente_candidato_sin_ocr(raiz_atlas=raiz)
    assert len(candidatas) == 1
    assert candidatas[0]["tipo"] == "CLIENTE_CANDIDATO"
    assert candidatas[0]["identidad_resuelta"]["valor_canonico"] == "COMERCIAL A Y B LTDA"
    assert candidatas[0]["documento"]["numero_guia"] == "472037"


def test_reconciliar_cliente_candidato_historico_publica_sin_tocar_catalogo_ni_csv(tmp_path):
    raiz, catalogos, actual, cliente = _entorno_historico(tmp_path)
    antes_catalogo = (catalogos / "clientes.json").read_bytes()
    antes_csv = (actual / "analisis_completo_guias.csv").read_bytes()

    resultado = reconciliar_decisiones_cliente_candidato_historico(raiz_atlas=raiz)
    assert resultado["decisiones_candidatas"] == 1
    assert resultado["decisiones_publicadas"] == 1

    assert (catalogos / "clientes.json").read_bytes() == antes_catalogo
    assert (actual / "analisis_completo_guias.csv").read_bytes() == antes_csv

    pendientes = _pendientes(actual)
    assert len(pendientes) == 1 and pendientes[0]["tipo"] == "CLIENTE_CANDIDATO"

    # Ahora sí es accionable de punta a punta: aplicar_decision_obra puede
    # confirmarla igual que si la detección la hubiera generado en su
    # momento original.
    decision_id = pendientes[0]["decision_id"]
    resultado_aplicacion = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision_id, accion="CONFIRMAR")
    assert resultado_aplicacion["ok"] is True
    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open(encoding="utf-8-sig") as archivo:
        fila = next(csv.DictReader(archivo, delimiter=";"))
    assert "CLIENTE_SIN_CORROBORAR" not in fila["motivos_revision_documento"]


def test_reconciliar_cliente_candidato_historico_es_idempotente(tmp_path):
    """Ejecutar la reconciliación histórica dos veces seguidas (p. ej. el
    bloque se corre más de una vez por error operacional) no duplica la
    decisión -- mismo `decision_id` ambas veces, `generar_artefacto` la
    deduplica igual que a cualquier otra."""
    raiz, catalogos, actual, cliente = _entorno_historico(tmp_path)
    primero = reconciliar_decisiones_cliente_candidato_historico(raiz_atlas=raiz)
    segundo = reconciliar_decisiones_cliente_candidato_historico(raiz_atlas=raiz)
    assert primero["decisiones_publicadas"] == 1
    assert segundo["decisiones_publicadas"] == 1
    pendientes = _pendientes(actual)
    assert len(pendientes) == 1
