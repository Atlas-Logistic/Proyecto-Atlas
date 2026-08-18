"""R3.4.2: cierra el callejón sin salida OBRA_DESCONOCIDA -> REGISTRAR ->
OBRA_DESTINO_SIN_CORROBORAR sin siguiente paso.

Cuando `detectar_decisiones_documento` emite OBRA_DESCONOCIDA, la obra
todavía no existe -- por eso no puede, en ese mismo instante, generar
también la pregunta de destino (DESTINO_SIN_CONFIRMAR exige una obra ya
identificada). Estos tests verifican que, al REGISTRAR la obra,
`aplicar_decision_obra` genera esa siguiente pregunta accionable cuando
corresponde (CASO B), se abstiene cuando el destino ya es corroborable sin
intervención humana (CASO A) o cuando el documento no trajo destino
(CASO C) -- y que el mecanismo de regeneración general (no sólo el momento
de aplicar) hace lo mismo para decisiones ya persistidas."""
import csv
import json

import pytest

from atlas_core.aplicacion_decisiones import DecisionObsoletaError, aplicar_decision_obra
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_destinos import CatalogoDestinos
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, ResultadoEvidencia, TipoEvidencia
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto, regenerar_decisiones_persistidas
from atlas_core.procesamiento_masivo import COLUMNAS

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


def _entorno(tmp_path, *, destino_documental=DESTINO_TEXTO, filas_csv=None):
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
        razon_social="EBEMA SA", rut="76.123.987-2", fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, filas_csv if filas_csv is not None else [_fila_csv()])

    decision = crear_decision(
        tipo="OBRA_DESCONOCIDA", entidad="OBRA", archivo="464718.jpeg",
        numero_guia="464718", numero_transporte="T-464718", campo="obra_destino",
        valor_documental=OBRA_TEXTO, valor_normalizado=OBRA_TEXTO,
        identidad_resuelta=None, candidatos=(), motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),
        evidencias=({"tipo": "CLIENTE_RESUELTO", "entidad_id": cliente.cliente_id},),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        # Tal como lo deja `detectar_decisiones_documento` desde R3.4.2: la
        # dirección documental ya resuelta viaja en el contexto de la propia
        # OBRA_DESCONOCIDA, para cuando haga falta al REGISTRAR.
        contexto={
            "cliente_id": cliente.cliente_id, "cliente_canonico": "EBEMA SA",
            "destino_documental": destino_documental,
        },
    )
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision], ruta_salida=actual/"decisiones_pendientes.json")
    return raiz, catalogos, actual, cliente, decision


def _pendientes(actual):
    return json.loads((actual/"decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]


def _fila(dataset):
    return list(csv.DictReader(dataset.open(encoding="utf-8-sig"), delimiter=";"))[0]


# --- CASO B: destino documental presente -> siguiente pregunta accionable ---

def test_registrar_obra_con_destino_genera_destino_sin_confirmar_siguiente(tmp_path):
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR")
    assert resultado["ok"]

    pendientes = _pendientes(actual)
    assert len(pendientes) == 1
    siguiente = pendientes[0]
    assert siguiente["tipo"] == "DESTINO_SIN_CONFIRMAR"
    assert siguiente["valor_documental"] == DESTINO_TEXTO
    assert siguiente["identidad_resuelta"]["entidad_id"] == resultado["obra_id"]
    assert siguiente["contexto"]["obra_id"] == resultado["obra_id"]
    assert siguiente["contexto"]["destino_documental"] == DESTINO_TEXTO
    assert siguiente["contexto"]["cliente_id"] == cliente.cliente_id
    assert siguiente["acciones_permitidas"] == ["CONFIRMAR", "NO_CONFIRMAR", "POSPONER"]

    # La obra en sí quedó registrada (OBSERVADA) -- REGISTRAR no confirma
    # implícitamente ninguna relación.
    obras = CatalogoObrasDestinos(ruta=catalogos/"obras_destinos.json", ruta_clientes=catalogos/"clientes.json", ruta_destinos=catalogos/"destinos_maestros.json").listar_obras()
    assert len(obras) == 1 and obras[0].estado == "OBSERVADA"
    assert CatalogoObrasDestinos(ruta=catalogos/"obras_destinos.json", ruta_clientes=catalogos/"clientes.json", ruta_destinos=catalogos/"destinos_maestros.json").listar_relaciones() == []


# --- CASO C: sin destino documental -> no se inventa nada ---

def test_registrar_obra_sin_destino_no_inventa_decision(tmp_path):
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path, destino_documental="")
    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR")
    assert resultado["ok"]
    assert _pendientes(actual) == []
    obras = CatalogoObrasDestinos(ruta=catalogos/"obras_destinos.json", ruta_clientes=catalogos/"clientes.json", ruta_destinos=catalogos/"destinos_maestros.json").listar_obras()
    assert len(obras) == 1  # la obra sí se registra -- sólo se abstiene de inventar destino


def test_registrar_obra_con_destino_ausente_no_inventa_decision(tmp_path):
    """`despachar_a_documental` puede llegar como 'No encontrado' (mismo
    vocabulario de ausencia que usa el resto del módulo)."""
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path, destino_documental="No encontrado")
    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR")
    assert resultado["ok"]
    assert _pendientes(actual) == []


# --- CASO A: destino ya corroborable sin intervención humana -> sin pregunta redundante ---

def test_registrar_obra_ya_corroborable_no_genera_decision_redundante(tmp_path):
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    # Simula que, entre la detección original y el REGISTRAR, la MISMA obra
    # (mismo nombre normalizado) ya quedó CONFIRMADA con una relación única
    # -- p. ej. otro cliente/guía la resolvió primero por otra vía.
    obras_cat = CatalogoObrasDestinos(ruta=catalogos/"obras_destinos.json", ruta_clientes=catalogos/"clientes.json", ruta_destinos=catalogos/"destinos_maestros.json")
    evidencia = Evidencia(
        tipo=TipoEvidencia.GUIA.value, identificador_fuente="OTRA-GUIA", referencia_hash="c"*64,
        campos_observados={"obra": OBRA_TEXTO}, fecha="2026-01-01T00:00:00+00:00",
        actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value,
    )
    destino = CatalogoDestinos(catalogos/"destinos_maestros.json", ruta_clientes=catalogos/"clientes.json").crear_o_reutilizar_global(
        nombre_destino=DESTINO_TEXTO, direccion=DESTINO_TEXTO, fuente="TEST",
    )
    pendiente = obras_cat.registrar_observacion(cliente_id=cliente.cliente_id, nombre_obra=OBRA_TEXTO, destino_id=destino.destino_id, evidencia=evidencia).relacion
    obras_cat.confirmar_relacion(pendiente.relacion_id, actor="test")
    # Los catálogos cambiaron -- se regenera la bandeja para que
    # catalogos_sha256 refleje el estado vigente antes de aplicar.
    generar_artefacto(ruta_dataset=actual/"analisis_completo_guias.csv", carpeta_catalogos=catalogos, decisiones=[decision], ruta_salida=actual/"decisiones_pendientes.json")

    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR")
    assert resultado["ok"]
    assert _pendientes(actual) == []  # nada redundante que preguntar

    obras = obras_cat.listar_obras()
    assert len(obras) == 1  # reutilizó la obra existente, no duplicó
    relaciones = obras_cat.listar_relaciones()
    assert len(relaciones) == 1  # tampoco duplicó la relación


# --- decisión consecutiva: obra -> destino, sin obsolescencia ---

def test_decision_consecutiva_obra_luego_destino_sin_obsolescencia(tmp_path):
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    resultado_obra = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR")
    assert resultado_obra["ok"]
    siguiente = _pendientes(actual)[0]

    resultado_destino = aplicar_decision_obra(raiz_atlas=raiz, decision_id=siguiente["decision_id"], accion="CONFIRMAR")
    assert resultado_destino["ok"]
    assert resultado_destino["revalidacion"]["reporte_regenerado"] is True
    assert _pendientes(actual) == []

    obras_cat = CatalogoObrasDestinos(ruta=catalogos/"obras_destinos.json", ruta_clientes=catalogos/"clientes.json", ruta_destinos=catalogos/"destinos_maestros.json")
    obras = obras_cat.listar_obras()
    assert len(obras) == 1 and obras[0].estado == "CONFIRMADA"
    relaciones = obras_cat.listar_relaciones()
    assert len(relaciones) == 1 and relaciones[0].estado == "CONFIRMADA"

    ledger = json.loads((actual/"decisiones_aplicadas.json").read_text(encoding="utf-8"))
    assert [a["decision_id"] for a in ledger["aplicaciones"]] == [decision["decision_id"], siguiente["decision_id"]]

    fila = _fila(actual/"analisis_completo_guias.csv")
    assert "OBRA_DESTINO_SIN_CORROBORAR" not in fila["motivos_revision_documento"]
    assert fila["indicador_revision"] == "OK"


# --- decidir después: la nueva decisión permanece pendiente ---

def test_decidir_despues_en_la_nueva_decision_permanece_pendiente(tmp_path):
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR")
    siguiente = _pendientes(actual)[0]
    antes = {p: p.read_bytes() for p in [catalogos/"obras_destinos.json", catalogos/"destinos_maestros.json", actual/"decisiones_pendientes.json"]}

    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=siguiente["decision_id"], accion="POSPONER")
    assert resultado["accion"] == "POSPONER"
    assert len(_pendientes(actual)) == 1
    assert antes == {p: p.read_bytes() for p in antes}


# --- rechazo terminal: no resucita al regenerar ---

def test_rechazo_terminal_de_la_nueva_decision_no_resucita_al_regenerar(tmp_path):
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR")
    siguiente = _pendientes(actual)[0]
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=siguiente["decision_id"], accion="NO_CONFIRMAR")
    assert _pendientes(actual) == []

    # Simula una bandeja desincronizada que todavía trae la OBRA_DESCONOCIDA
    # original -- la obra ya existe, así que `regenerar_decisiones_persistidas`
    # vuelve a sintetizar la MISMA pregunta de destino (mismo decision_id)...
    restantes = regenerar_decisiones_persistidas(decisiones=[decision], carpeta_catalogos=catalogos)
    assert any(d["decision_id"] == siguiente["decision_id"] for d in restantes)
    # ...pero `generar_artefacto` la filtra contra el ledger: nunca resucita
    # una decisión ya rechazada terminalmente.
    bandeja = generar_artefacto(ruta_dataset=actual/"analisis_completo_guias.csv", carpeta_catalogos=catalogos, decisiones=restantes, ruta_salida=actual/"decisiones_pendientes.json")
    assert bandeja["decisiones"] == []


# --- idempotencia: repetir la regeneración no duplica ---

def test_idempotencia_repetir_regeneracion_no_duplica(tmp_path):
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR")
    pendientes_1 = _pendientes(actual)
    assert len(pendientes_1) == 1

    # Regenerar de nuevo sobre la bandeja ya publicada (que ya sólo trae la
    # decisión sintetizada, no la OBRA_DESCONOCIDA original) no debe crear
    # una segunda.
    restantes = regenerar_decisiones_persistidas(decisiones=pendientes_1, carpeta_catalogos=catalogos)
    bandeja = generar_artefacto(ruta_dataset=actual/"analisis_completo_guias.csv", carpeta_catalogos=catalogos, decisiones=restantes, ruta_salida=actual/"decisiones_pendientes.json")
    assert len(bandeja["decisiones"]) == 1
    assert bandeja["decisiones"][0]["decision_id"] == pendientes_1[0]["decision_id"]


def test_idempotencia_reaplicar_registrar_no_duplica_siguiente(tmp_path):
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR")
    primera = _pendientes(actual)
    segunda_aplicacion = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR")
    assert segunda_aplicacion["idempotente"] is True
    assert _pendientes(actual) == primera  # nada cambió, no se duplicó nada


# --- motivos independientes: no se eliminan otros motivos del documento ---

def test_motivos_independientes_no_se_eliminan(tmp_path):
    fila = _fila_csv(motivos_revision_documento="CLIENTE_SIN_CORROBORAR | OBRA_DESTINO_SIN_CORROBORAR")
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path, filas_csv=[fila])
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR")
    siguiente = _pendientes(actual)[0]
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=siguiente["decision_id"], accion="CONFIRMAR")

    fila_final = _fila(actual/"analisis_completo_guias.csv")
    assert "OBRA_DESTINO_SIN_CORROBORAR" not in fila_final["motivos_revision_documento"]
    assert "CLIENTE_SIN_CORROBORAR" in fila_final["motivos_revision_documento"]
    assert fila_final["indicador_revision"] == "REVISAR"  # sigue habiendo un motivo bloqueante


# --- regeneración general (no sólo al aplicar): Path 2 ---

def test_regenerar_sintetiza_destino_para_otra_decision_persistida_con_misma_obra(tmp_path):
    """Si la obra ya quedó registrada (p. ej. porque otra decisión para OTRA
    guía la registró primero), una OBRA_DESCONOCIDA todavía persistida para
    ESTA guía debe reemplazarse por su propia pregunta de destino al
    regenerar -- no simplemente desaparecer sin dejar rastro."""
    raiz, catalogos, actual, cliente, decision_original = _entorno(tmp_path)
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision_original["decision_id"], accion="REGISTRAR")
    # decision_original ya se aplicó (la obra existe); construimos una
    # SEGUNDA OBRA_DESCONOCIDA persistida para otra guía, con la misma obra
    # documental y su propio destino -- tal como habría quedado atrapada en
    # una bandeja generada antes de que la primera guía registrara la obra.
    otra_destino = "CAM. EL NOVICIADO LAMPA LAMPA"
    decision_otra_guia = crear_decision(
        tipo="OBRA_DESCONOCIDA", entidad="OBRA", archivo="999.jpeg",
        numero_guia="999", numero_transporte="T-999", campo="obra_destino",
        valor_documental=OBRA_TEXTO, valor_normalizado=OBRA_TEXTO,
        identidad_resuelta=None, candidatos=(), motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),
        evidencias=({"tipo": "CLIENTE_RESUELTO", "entidad_id": cliente.cliente_id},),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        contexto={
            "cliente_id": cliente.cliente_id, "cliente_canonico": "EBEMA SA",
            "destino_documental": otra_destino,
        },
    )
    restantes = regenerar_decisiones_persistidas(decisiones=[decision_otra_guia], carpeta_catalogos=catalogos)
    assert len(restantes) == 1
    sintetizada = restantes[0]
    assert sintetizada["tipo"] == "DESTINO_SIN_CONFIRMAR"
    assert sintetizada["valor_documental"] == otra_destino
    assert sintetizada["documento"]["numero_guia"] == "999"
    assert not any(d["tipo"] == "OBRA_DESCONOCIDA" for d in restantes)


def test_regenerar_sin_destino_documental_abstiene_sin_inventar(tmp_path):
    """Una OBRA_DESCONOCIDA persistida ANTES de este cambio no trae
    `destino_documental` en su contexto -- se conserva el comportamiento
    previo (la pregunta desaparece sin reemplazo) en vez de inventar algo
    que el artefacto legado no dice."""
    raiz, catalogos, actual, cliente, decision_original = _entorno(tmp_path)
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision_original["decision_id"], accion="REGISTRAR")
    decision_legado = crear_decision(
        tipo="OBRA_DESCONOCIDA", entidad="OBRA", archivo="998.jpeg",
        numero_guia="998", numero_transporte="T-998", campo="obra_destino",
        valor_documental=OBRA_TEXTO, valor_normalizado=OBRA_TEXTO,
        identidad_resuelta=None, candidatos=(), motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),
        evidencias=({"tipo": "CLIENTE_RESUELTO", "entidad_id": cliente.cliente_id},),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        contexto={"cliente_id": cliente.cliente_id, "cliente_canonico": "EBEMA SA"},
    )
    restantes = regenerar_decisiones_persistidas(decisiones=[decision_legado], carpeta_catalogos=catalogos)
    assert restantes == []


# --- obsolescencia normal se preserva para la nueva decisión también ---

def test_confirmar_nueva_decision_obsoleta_por_catalogo_se_abstiene(tmp_path):
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR")
    siguiente = _pendientes(actual)[0]
    CatalogoClientes(catalogos/"clientes.json").crear(razon_social="OTRO SPA", fuente="TEST")
    antes_obras = (catalogos/"obras_destinos.json").read_bytes()
    with pytest.raises(DecisionObsoletaError):
        aplicar_decision_obra(raiz_atlas=raiz, decision_id=siguiente["decision_id"], accion="CONFIRMAR")
    assert (catalogos/"obras_destinos.json").read_bytes() == antes_obras
