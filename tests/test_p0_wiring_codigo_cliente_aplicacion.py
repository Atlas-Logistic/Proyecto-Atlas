"""Bloque P0 -- CÓDIGO CLIENTE: wiring con el flujo humano existente.

Una confirmación humana de identidad de CLIENTE (CLIENTE_CANDIDATO/
CLIENTE_DESCONOCIDO/CLIENTE_AUSENTE/ALIAS_CANDIDATO -- las cuatro
convergen en el mismo punto dentro de `aplicar_decision_obra`, justo
después de escribir el ledger) aprende `codigo_cliente -> cliente_id`
SÓLO si el documento vigente trae `codigo_cliente` documental válido.
Nunca aprende de `cod_destinatario`, nunca sin confirmación humana real,
siempre idempotente. Tests puramente sintéticos, nunca tocan G:."""
import json

from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.codigo_cliente_destinatario import CatalogoCodigosCliente
from atlas_core.decisiones_pendientes import detectar_decisiones_documento, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS


def _catalogos(tmp_path):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "empresas.json": {},
        "vehiculos.json": {},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    return carpeta


def _cliente_confirmado(carpeta, nombre="PRODALAM SA", rut="93.772.000-9"):
    return CatalogoClientes(carpeta / "clientes.json").crear(
        razon_social=nombre, rut=rut, fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "472037.jpeg", "estado_procesamiento": "OK", "numero_guia": "472037",
        "numero_transporte": "T1", "fecha": "18/08/2026", "chofer": "CRISTOPHER RETAMAL",
        "cliente": "PRODALAM SA", "obra_destino": "EMPRESA CONST SIGRO",
        "patente_tracto": "BPHR67", "patente_rampla": "No encontrado",
        "descripcion_material": "HORMIGON", "tipo_carga": "OTRO",
        "indicador_revision": "REVISAR", "codigo_cliente": "No encontrado",
        "cod_destinatario": "No encontrado",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    import csv
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _entorno_cliente_candidato(tmp_path, *, codigo_cliente="No encontrado", cod_destinatario="No encontrado"):
    raiz = tmp_path / "atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True)
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []}, "empresas.json": {}, "vehiculos.json": {},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    cliente = _cliente_confirmado(catalogos)
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila_csv(codigo_cliente=codigo_cliente, cod_destinatario=cod_destinatario)])
    ds = detectar_decisiones_documento(
        archivo="472037.jpeg",
        datos={"número de guía": "472037", "número de transporte": "T1",
               "cliente": "PRODALAM SA", "RUT del cliente": "No encontrado",
               "obra destino": "EMPRESA CONST SIGRO"},
        carpeta_catalogos=catalogos, cliente_documental_original="PRODALAM SA",
    )
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=ds,
        ruta_salida=actual / "decisiones_pendientes.json",
    )
    decision = next(d for d in ds if d["tipo"] == "CLIENTE_CANDIDATO")
    return raiz, catalogos, actual, cliente, decision


def test_confirmar_con_codigo_cliente_valido_aprende_la_asociacion(tmp_path):
    raiz, catalogos, actual, cliente, decision = _entorno_cliente_candidato(
        tmp_path, codigo_cliente="0001003518",
    )
    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR")
    assert resultado["ok"] is True

    catalogo_codigos = CatalogoCodigosCliente(catalogos / "codigos_cliente.json")
    assert catalogo_codigos.buscar("0001003518") == cliente.cliente_id


def test_confirmar_sin_codigo_cliente_documental_no_aprende_nada(tmp_path):
    raiz, catalogos, actual, cliente, decision = _entorno_cliente_candidato(
        tmp_path, codigo_cliente="No encontrado",
    )
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR")
    assert not (catalogos / "codigos_cliente.json").exists()


def test_no_confirmar_nunca_aprende_aunque_haya_codigo(tmp_path):
    raiz, catalogos, actual, cliente, decision = _entorno_cliente_candidato(
        tmp_path, codigo_cliente="0001003518",
    )
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="NO_CONFIRMAR")
    assert not (catalogos / "codigos_cliente.json").exists()


def test_nunca_aprende_cod_destinatario_como_codigo_cliente(tmp_path):
    raiz, catalogos, actual, cliente, decision = _entorno_cliente_candidato(
        tmp_path, codigo_cliente="No encontrado", cod_destinatario="0002012245",
    )
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR")
    # Ni se creó el catálogo (sin codigo_cliente documental) ni, si
    # existiera, tendría el valor de cod_destinatario aprendido por error.
    catalogo_codigos = CatalogoCodigosCliente(catalogos / "codigos_cliente.json")
    assert catalogo_codigos.buscar("0002012245") is None


def test_aplicacion_es_idempotente(tmp_path):
    raiz, catalogos, actual, cliente, decision = _entorno_cliente_candidato(
        tmp_path, codigo_cliente="0001003518",
    )
    primero = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR")
    segundo = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR")
    assert primero.get("idempotente") is not True
    assert segundo.get("idempotente") is True

    catalogo_codigos = CatalogoCodigosCliente(catalogos / "codigos_cliente.json")
    assert catalogo_codigos.buscar("0001003518") == cliente.cliente_id
    contenido = json.loads((catalogos / "codigos_cliente.json").read_text(encoding="utf-8"))
    assert len(contenido["asociaciones"]) == 1  # nunca duplica la entrada


def test_trazabilidad_de_la_confirmacion_queda_registrada(tmp_path):
    raiz, catalogos, actual, cliente, decision = _entorno_cliente_candidato(
        tmp_path, codigo_cliente="0001003518",
    )
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR")
    contenido = json.loads((catalogos / "codigos_cliente.json").read_text(encoding="utf-8"))
    entrada = contenido["asociaciones"]["0001003518"]
    assert entrada["cliente_id"] == cliente.cliente_id
    assert entrada["actor"] == "JAVIER_DESKTOP"
    assert entrada["fuente"] == "CLIENTE_CANDIDATO:CONFIRMAR"
    assert entrada["fecha_confirmacion"]

    # El ledger sigue siendo la autoridad real -- esto es sólo una
    # proyección derivada, nunca al revés.
    ledger = json.loads((actual / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    aplicacion = ledger["aplicaciones"][0]
    assert aplicacion["tipo"] == "CLIENTE_CANDIDATO" and aplicacion["accion"] == "CONFIRMAR"
    assert aplicacion["cliente_id"] == cliente.cliente_id
