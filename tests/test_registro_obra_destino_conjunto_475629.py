"""Registro completo de obra nueva -- caso real 475629 (PRODALAM SA SAN
MIGUEL), con datos sintéticos.

Antes: REGISTRAR la obra encadenaba de inmediato una segunda tarjeta
`DESTINO_SIN_CONFIRMAR` para la dirección que el mismo documento ya traía.
Ahora la vista previa muestra obra + cliente + dirección + comuna + región
+ ubicación propuesta, y una sola acción confirma ambas cosas -- con las
validaciones de obra y de geografía separadas, auditoría en el ledger,
idempotencia y revalidación sólo de los documentos/viajes afectados."""
import csv
import hashlib
import json

import pytest

from atlas_core.aplicacion_decisiones import ErrorAplicacionDecision, aplicar_decision_obra
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, ResultadoEvidencia, TipoEvidencia
from atlas_core.decisiones_pendientes import crear_decision, decision_destino_para_obra_registrada, generar_artefacto
from atlas_core.geografia.base_local import BaseGeograficaLocalSQLite
from atlas_core.geografia.importador_ine import importar_a_sqlite
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.registro_obra_destino import (
    MOTIVO_COORDENADA_CONTRADICHA, MOTIVO_DESTINO_CONTAMINADO, MOTIVO_SIN_VALIDACION_GEOGRAFICA,
    calle_y_numero, motivo_destino_documental_no_confiable, previsualizar_registro_obra_destino,
)

GUIA = "475629"
TRANSPORTE = "0000363001"
OBRA = "PRODALAM SA SAN MIGUEL"
DESTINO = "CARLOS VALDOVINOS 1553 SAN MIGUEL SAN MIGUEL"
LAT_INE, LON_INE = -33.478633, -70.65477
OTRA_OBRA = "CONSTRUCTORA AJENA SPA"


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "original.jpg", "estado_procesamiento": "OK", "numero_guia": GUIA,
        "numero_transporte": TRANSPORTE, "fecha": "08-10-2026", "chofer": "CHOFER SINTETICO",
        "cliente": "PRODALAM SA", "obra_destino": OBRA, "patente_tracto": "BKYK63",
        "patente_rampla": "No encontrado", "descripcion_material": "B HORMIGON 12MM 6M A630-420H (N)",
        "tipo_carga": "BARRAS", "peso_kg": "2107", "indicador_revision": "REVISAR",
        "motivos_revision_documento": "OBRA_DESTINO_SIN_CORROBORAR",
        "estado_documental": "REQUIERE_REVISION", "estado_operacional": "REQUIERE_REVISION",
        "despachar_a_crudo": DESTINO, "direccion_entrega": "Avenida Alcalde Carlos Valdovinos 1553",
        "localidad_entrega": "San Miguel", "region_entrega": "Metropolitana", "estado_entrega": "RESUELTO",
        "planta_origen_nombre": "AZA COLINA", "distancia_km": "25.2857", "estado_ruta": "RUTA_CALCULADA",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _leer_csv(ruta):
    return {f["numero_guia"]: f for f in csv.DictReader(ruta.open(encoding="utf-8-sig"), delimiter=";")}


def _sha(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest() if ruta.exists() else None


def _obras(catalogos):
    return CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    )


@pytest.fixture
def base_ine(tmp_path):
    csv_ine = tmp_path / "ine_sintetico.csv"
    csv_ine.write_text(
        "gid,via,hnum,alias,error,region,clase_urbana,nombre_comuna,longitude,latitude\n"
        f"1,CARLOS VALDOVINOS,1553,,,METROPOLITANA DE SANTIAGO,AVENIDA,SAN MIGUEL,{LON_INE},{LAT_INE}\n"
        "2,CARLOS VALDOVINOS,1555,,,METROPOLITANA DE SANTIAGO,AVENIDA,SAN MIGUEL,-70.6549,-33.4787\n",
        encoding="utf-8",
    )
    ruta = tmp_path / "base_local_rm_ine.sqlite"
    importar_a_sqlite(csv_ine, ruta, reemplazar=True)
    return BaseGeograficaLocalSQLite(ruta)


def _entorno(tmp_path, *, destino_previo=None):
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
        razon_social="PRODALAM SA", rut="93.772.000-9", fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    # Guía AJENA cuya obra ya tiene relación confirmada: una revalidación
    # global le retiraría el motivo -- la focal nunca la toca.
    destino_ajeno = CatalogoDestinos(catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json").crear_o_reutilizar_global(
        nombre_destino="CALLE AJENA 100", direccion="CALLE AJENA 100", comuna="Renca", region="Metropolitana", fuente="TEST",
    )
    evidencia = Evidencia(
        tipo=TipoEvidencia.GUIA.value, identificador_fuente="900001", referencia_hash="a" * 64,
        campos_observados={"obra": OTRA_OBRA}, fecha="2026-01-01T00:00:00+00:00",
        actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value,
    )
    relacion = _obras(catalogos).registrar_observacion(
        cliente_id=cliente.cliente_id, nombre_obra=OTRA_OBRA, destino_id=destino_ajeno.destino_id, evidencia=evidencia,
    ).relacion
    _obras(catalogos).confirmar_relacion(relacion.relacion_id, actor="test")
    if destino_previo is not None:
        CatalogoDestinos(catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json").crear_o_reutilizar_global(
            fuente="TEST", **destino_previo,
        )

    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [
        _fila(),
        # misma guía-viaje: otra guía del MISMO transporte
        _fila(numero_guia="475630", archivo="475630.jpeg", obra_destino="PRODALAM SA SAN MIGUEL"),
        _fila(numero_guia="900001", archivo="900001.jpeg", numero_transporte="0000999999",
              obra_destino=OTRA_OBRA, despachar_a_crudo="CALLE AJENA 100 RENCA", localidad_entrega="Renca"),
    ])
    decision = crear_decision(
        tipo="OBRA_DESCONOCIDA", entidad="OBRA", archivo="original.jpg",
        numero_guia=GUIA, numero_transporte=TRANSPORTE, campo="obra_destino",
        valor_documental=OBRA, valor_normalizado=OBRA,
        identidad_resuelta=None, candidatos=(), motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),
        evidencias=({"tipo": "CLIENTE_RESUELTO", "entidad_id": cliente.cliente_id},),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        contexto={"cliente_id": cliente.cliente_id, "cliente_canonico": "PRODALAM SA", "destino_documental": DESTINO},
    )
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision], ruta_salida=actual / "decisiones_pendientes.json")
    return raiz, catalogos, actual, cliente, decision


def _pendientes(actual):
    return json.loads((actual / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]


def _ledger(actual):
    ruta = actual / "decisiones_aplicadas.json"
    return json.loads(ruta.read_text(encoding="utf-8"))["aplicaciones"] if ruta.exists() else []


def test_calle_y_numero_corta_la_cola_de_comuna_repetida():
    assert calle_y_numero(DESTINO) == "CARLOS VALDOVINOS 1553"
    assert calle_y_numero("CAMINO SIN NUMERO LAMPA") == ""


def test_475629_vista_previa_presenta_obra_destino_y_ubicacion_sin_escribir(tmp_path, base_ine):
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    archivos = [catalogos / "obras_destinos.json", catalogos / "destinos_maestros.json",
                actual / "decisiones_pendientes.json", actual / "analisis_completo_guias.csv"]
    antes = {a: _sha(a) for a in archivos}

    vista = previsualizar_registro_obra_destino(
        raiz_atlas=raiz, decision_id=decision["decision_id"], base_geografica_local=base_ine,
    )

    assert vista["ok"] is True
    assert vista["obra"]["nombre"] == OBRA and vista["obra"]["es_nueva"] is True
    assert vista["cliente"] == {"cliente_id": cliente.cliente_id, "razon_social": "PRODALAM SA"}
    assert vista["destino"]["requiere_confirmacion"] is True
    assert vista["destino"]["direccion"] == DESTINO
    assert vista["destino"]["comuna"] == "San Miguel"
    assert vista["destino"]["region"]
    assert vista["destino"]["destino_existente"] is None
    assert vista["ubicacion"]["fuente"] == "BASE_TERRITORIAL_INE"
    assert vista["ubicacion"]["precision"] == "DIRECCION_EXACTA"
    assert (vista["ubicacion"]["latitud"], vista["ubicacion"]["longitud"]) == (LAT_INE, LON_INE)
    assert vista["validaciones"]["geografia"]["estado"] == "OK"
    assert vista["confirmacion_conjunta_disponible"] is True
    assert len(vista["huella"]) == 64
    assert {a: _sha(a) for a in archivos} == antes  # sólo lectura
    assert not (actual / "decisiones_aplicadas.json").exists()


def test_475629_confirmacion_conjunta_no_crea_segunda_tarjeta(tmp_path, base_ine):
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    vista = previsualizar_registro_obra_destino(
        raiz_atlas=raiz, decision_id=decision["decision_id"], base_geografica_local=base_ine,
    )

    resultado = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR",
        confirmar_destino_conjunto=True, huella_vista_previa=vista["huella"], base_geografica_local=base_ine,
    )

    assert resultado["ok"] is True and resultado["destino_confirmado_conjunto"] is True
    # Ninguna tarjeta nueva: ni DESTINO_SIN_CONFIRMAR ni ninguna otra.
    assert _pendientes(actual) == []

    # Identidad de obra + relación confirmadas.
    obras_cat = _obras(catalogos)
    obra = next(o for o in obras_cat.listar_obras() if o.nombre_canonico == OBRA)
    assert obra.estado == "CONFIRMADA" and obra.obra_id == resultado["obra_id"]
    relacion = next(r for r in obras_cat.listar_relaciones() if r.obra_id == obra.obra_id)
    assert relacion.estado == "CONFIRMADA" and relacion.relacion_id == resultado["relacion_id"]
    assert obras_cat.resolver_obra_destino_confirmada_global(nombre_obra=OBRA) is not None

    # Geografía: destino global CONFIRMADO con comuna/región y la ubicación INE.
    destino = CatalogoDestinos(catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json").obtener(resultado["destino_id"])
    assert destino.estado_calidad == EstadoCalidadDestino.CONFIRMADO.value
    assert destino.direccion == DESTINO and destino.comuna == "San Miguel" and destino.region
    assert (destino.latitud, destino.longitud) == (LAT_INE, LON_INE)

    # Auditoría: dos entradas en el ledger, la de destino con el MISMO id que
    # habría tenido la tarjeta encadenada y la traza del registro conjunto.
    tarjeta_que_no_aparecio = decision_destino_para_obra_registrada(
        obra=obra, cliente_id=cliente.cliente_id, cliente_canonico="PRODALAM SA",
        destino_documental=DESTINO, documento=decision["documento"],
        catalogo_obras=_Abstencion(),
    )
    ledger = _ledger(actual)
    assert [(a["tipo"], a["accion"]) for a in ledger] == [
        ("OBRA_DESCONOCIDA", "REGISTRAR"), ("DESTINO_SIN_CONFIRMAR", "CONFIRMAR"),
    ]
    obra_ap, destino_ap = ledger
    assert destino_ap["decision_id"] == tarjeta_que_no_aparecio["decision_id"]
    assert destino_ap["origen"] == "REGISTRO_CONJUNTO_OBRA_DESTINO"
    assert destino_ap["decision_origen_id"] == decision["decision_id"]
    assert destino_ap["huella_vista_previa"] == vista["huella"]
    assert destino_ap["ubicacion"]["fuente"] == "BASE_TERRITORIAL_INE"
    assert obra_ap["registro_conjunto"] == {
        "decision_destino_id": destino_ap["decision_id"],
        "destino_id": resultado["destino_id"], "relacion_id": resultado["relacion_id"],
    }

    # Revalidación FOCAL: sólo la guía, su obra y su viaje.
    focal = resultado["revalidacion_focal"]
    assert focal["alcance"] == "FOCAL"
    assert focal["guias"] == ["475629", "475630"] and focal["transportes"] == [TRANSPORTE]
    assert "revalidacion" not in resultado  # la batería global no corrió
    filas = _leer_csv(actual / "analisis_completo_guias.csv")
    assert "OBRA_DESTINO_SIN_CORROBORAR" not in filas[GUIA]["motivos_revision_documento"]
    assert "OBRA_DESTINO_SIN_CORROBORAR" not in filas["475630"]["motivos_revision_documento"]
    # La guía ajena (ya corroborable) quedó intacta: no estaba en el alcance.
    assert "OBRA_DESTINO_SIN_CORROBORAR" in filas["900001"]["motivos_revision_documento"]

    # Una tarjeta equivalente regenerada después se filtra por el ledger.
    generar_artefacto(
        ruta_dataset=actual / "analisis_completo_guias.csv", carpeta_catalogos=catalogos,
        decisiones=[tarjeta_que_no_aparecio], ruta_salida=actual / "decisiones_pendientes.json",
    )
    assert _pendientes(actual) == []


class _Abstencion:
    """Catálogo mínimo para reconstruir la tarjeta R3.4.2 tal como habría
    nacido (antes de confirmar la relación)."""

    def resolver_obra_destino_confirmada_global(self, *, nombre_obra):
        return None


def test_475629_reaplicar_es_idempotente(tmp_path, base_ine):
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    vista = previsualizar_registro_obra_destino(raiz_atlas=raiz, decision_id=decision["decision_id"], base_geografica_local=base_ine)
    argumentos = dict(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR",
        confirmar_destino_conjunto=True, huella_vista_previa=vista["huella"], base_geografica_local=base_ine,
    )
    aplicar_decision_obra(**argumentos)
    catalogos_tras_primera = {n: _sha(catalogos / n) for n in ("obras_destinos.json", "destinos_maestros.json")}

    segunda = aplicar_decision_obra(**argumentos)

    assert segunda["ok"] is True and segunda["idempotente"] is True
    assert len(_ledger(actual)) == 2
    assert {n: _sha(catalogos / n) for n in catalogos_tras_primera} == catalogos_tras_primera
    assert len(_obras(catalogos).listar_relaciones()) == 2  # la ajena + la de 475629, sin duplicar


def test_huella_vencida_no_aplica_nada(tmp_path, base_ine):
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    antes = {n: _sha(catalogos / n) for n in ("obras_destinos.json", "destinos_maestros.json")}

    with pytest.raises(ErrorAplicacionDecision, match="vista previa"):
        aplicar_decision_obra(
            raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR",
            confirmar_destino_conjunto=True, huella_vista_previa="0" * 64, base_geografica_local=base_ine,
        )

    assert {n: _sha(catalogos / n) for n in antes} == antes
    assert _ledger(actual) == []
    assert [d["decision_id"] for d in _pendientes(actual)] == [decision["decision_id"]]


def test_confirmacion_conjunta_exige_vista_previa(tmp_path, base_ine):
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    with pytest.raises(ErrorAplicacionDecision, match="vista previa"):
        aplicar_decision_obra(
            raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR",
            confirmar_destino_conjunto=True, base_geografica_local=base_ine,
        )
    assert _ledger(actual) == []


def test_coordenada_existente_contradicha_bloquea_confirmacion_conjunta(tmp_path, base_ine):
    # Mismo destino global ya guardado con una coordenada a cientos de km
    # (caso real del maestro de Valdovinos en -30.81): confirmarlo junto con
    # la obra la confirmaría tal cual -- la base territorial la desmiente.
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path, destino_previo={
        "nombre_destino": DESTINO, "direccion": DESTINO, "comuna": "San Miguel",
        "region": "Metropolitana", "latitud": -30.81432, "longitud": -70.60342,
    })
    vista = previsualizar_registro_obra_destino(raiz_atlas=raiz, decision_id=decision["decision_id"], base_geografica_local=base_ine)

    assert vista["destino"]["requiere_confirmacion"] is True
    assert vista["destino"]["destino_existente"]["latitud"] == -30.81432
    assert vista["validaciones"]["geografia"]["estado"] == "CONFLICTO"
    assert vista["confirmacion_conjunta_disponible"] is False
    assert vista["motivo_no_disponible"] == MOTIVO_COORDENADA_CONTRADICHA

    with pytest.raises(ErrorAplicacionDecision, match=MOTIVO_COORDENADA_CONTRADICHA):
        aplicar_decision_obra(
            raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR",
            confirmar_destino_conjunto=True, huella_vista_previa=vista["huella"], base_geografica_local=base_ine,
        )
    assert _ledger(actual) == []


def test_sin_destino_documental_no_ofrece_confirmacion_conjunta(tmp_path, base_ine):
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    bandeja = json.loads((actual / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    bandeja["decisiones"][0]["contexto"]["destino_documental"] = "No encontrado"
    (actual / "decisiones_pendientes.json").write_text(json.dumps(bandeja), encoding="utf-8")

    vista = previsualizar_registro_obra_destino(raiz_atlas=raiz, decision_id=decision["decision_id"], base_geografica_local=base_ine)

    assert vista["destino"]["requiere_confirmacion"] is False
    assert vista["destino"]["motivo_no_requiere"] == "SIN_DESTINO_DOCUMENTAL"
    assert vista["confirmacion_conjunta_disponible"] is False


def test_confirmacion_conjunta_solo_para_registrar_obra(tmp_path, base_ine):
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    with pytest.raises(ErrorAplicacionDecision, match="obra nueva"):
        aplicar_decision_obra(
            raiz_atlas=raiz, decision_id=decision["decision_id"], accion="NO_REGISTRAR",
            confirmar_destino_conjunto=True, huella_vista_previa="x", base_geografica_local=base_ine,
        )


def test_registrar_sin_confirmacion_conjunta_conserva_el_flujo_anterior(tmp_path, base_ine):
    """El registro de sólo la obra sigue disponible y encadena la tarjeta de
    destino exactamente como antes (R3.4.2)."""
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR")
    assert resultado["ok"] is True
    pendientes = _pendientes(actual)
    assert [d["tipo"] for d in pendientes] == ["DESTINO_SIN_CONFIRMAR"]
    assert pendientes[0]["valor_documental"] == DESTINO


def test_475629_confirmacion_individual_es_focal_publica_y_es_idempotente(tmp_path, base_ine, monkeypatch):
    """La tarjeta encadenada no debe pagar una batería global.

    Controla el alcance real (guía, viaje y obra), la publicación visible
    para Desktop y que una guía ajena no sea modificada por esta decisión.
    """
    import atlas_core.revalidacion_documental as revalidacion

    raiz, catalogos, actual, _cliente, decision_obra = _entorno(tmp_path)
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision_obra["decision_id"], accion="REGISTRAR")
    decision_destino = _pendientes(actual)[0]
    ajena_antes = _leer_csv(actual / "analisis_completo_guias.csv")["900001"].copy()

    def global_prohibida(**_kwargs):
        raise AssertionError("DESTINO_SIN_CONFIRMAR/CONFIRMAR no debe usar revalidación global")

    monkeypatch.setattr(revalidacion, "revalidar_y_regenerar_reporte", global_prohibida)
    primero = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision_destino["decision_id"], accion="CONFIRMAR",
    )

    assert primero["ok"] is True and primero["reporte_regenerado"] is True
    assert "revalidacion" not in primero
    assert primero["revalidacion_focal"]["alcance"] == "FOCAL"
    assert primero["revalidacion_focal"]["guias"] == ["475629", "475630"]
    assert primero["revalidacion_focal"]["transportes"] == [TRANSPORTE]
    assert _pendientes(actual) == []
    assert _leer_csv(actual / "analisis_completo_guias.csv")["900001"] == ajena_antes
    estado = json.loads((actual / "estado_operacion.json").read_text(encoding="utf-8"))
    assert (raiz / estado["reporte_vigente"] / "viajes.csv").is_file()

    segunda = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision_destino["decision_id"], accion="CONFIRMAR",
    )
    assert segunda["ok"] is True and segunda["idempotente"] is True
    assert len([a for a in _ledger(actual) if a["decision_id"] == decision_destino["decision_id"]]) == 1


def test_confirmacion_individual_falla_antes_del_ledger_si_no_puede_confirmar(tmp_path, base_ine):
    """Un fallo de validación intermedio no altera catálogo, ledger ni bandeja."""
    raiz, catalogos, actual, _cliente, decision_obra = _entorno(tmp_path)
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision_obra["decision_id"], accion="REGISTRAR")
    decision_destino = _pendientes(actual)[0]
    antes = {n: _sha(catalogos / n) for n in ("obras_destinos.json", "destinos_maestros.json")}
    pendientes_antes = _sha(actual / "decisiones_pendientes.json")
    ledger_antes = _sha(actual / "decisiones_aplicadas.json")

    # Una tarjeta malformada se rechaza durante la confirmación, antes de
    # publicar ledger o artefactos focales.
    bandeja = json.loads((actual / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    bandeja["decisiones"][0]["identidad_resuelta"] = {}
    bandeja["decisiones"][0]["contexto"]["obra_id"] = ""
    bandeja["decisiones"][0]["contexto"]["cliente_id"] = ""
    (actual / "decisiones_pendientes.json").write_text(json.dumps(bandeja), encoding="utf-8")
    pendientes_antes = _sha(actual / "decisiones_pendientes.json")
    with pytest.raises(ErrorAplicacionDecision):
        aplicar_decision_obra(
            raiz_atlas=raiz, decision_id=decision_destino["decision_id"], accion="CONFIRMAR",
        )

    assert {n: _sha(catalogos / n) for n in antes} == antes
    assert _sha(actual / "decisiones_pendientes.json") == pendientes_antes
    assert _sha(actual / "decisiones_aplicadas.json") == ledger_antes


def test_475629_dataset_real_con_campos_mayores_al_limite_csv(tmp_path, base_ine):
    """Prueba aislada con el dataset real (09-10): `resultado_atlas_ia_json`
    supera los 131072 caracteres por defecto de ``csv`` y la vista previa se
    caía con `_csv.Error: field larger than field limit`. Ahora la vista
    previa y la confirmación conjunta funcionan con filas así de grandes."""
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    dataset = actual / "analisis_completo_guias.csv"
    filas = list(_leer_csv(dataset).values())
    for fila in filas:
        fila["resultado_atlas_ia_json"] = json.dumps([{"evidencia": "x" * 200_000}])
    _escribir_csv(dataset, filas)
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision], ruta_salida=actual / "decisiones_pendientes.json")
    limite_previo = csv.field_size_limit(131072)  # límite por defecto de un proceso nuevo
    try:
        vista = previsualizar_registro_obra_destino(raiz_atlas=raiz, decision_id=decision["decision_id"], base_geografica_local=base_ine)
        assert vista["confirmacion_conjunta_disponible"] is True
        assert vista["destino"]["comuna"] == "San Miguel"
        csv.field_size_limit(131072)
        resultado = aplicar_decision_obra(
            raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR",
            confirmar_destino_conjunto=True, huella_vista_previa=vista["huella"], base_geografica_local=base_ine,
        )
    finally:
        csv.field_size_limit(max(limite_previo, csv.field_size_limit()))
    assert resultado["ok"] is True and resultado["destino_confirmado_conjunto"] is True
    assert resultado["revalidacion_focal"]["guias"] == ["475629", "475630"]
    assert _pendientes(actual) == []


def _sin_ruta(dataset, destino):
    filas = list(_leer_csv(dataset).values())
    for fila in filas:
        if fila["numero_guia"] == GUIA:
            fila.update({
                "despachar_a_crudo": destino, "direccion_entrega": "", "localidad_entrega": "",
                "region_entrega": "", "estado_entrega": "REVISAR", "estado_ruta": "REQUIERE_REVISION",
                "motivo_ruta": "GEOCODIFICACION_DIRECCION_NO_ENCONTRADA", "distancia_km": "",
            })
    _escribir_csv(dataset, filas)


def test_475603_destino_sin_validacion_geografica_no_se_confirma_con_la_obra(tmp_path, base_ine):
    """Caso real 475603: DESPACHAR A mal extraído ("12-10-2026 :17576134-9
    LLEGADA"), sin comuna, ubicación ni ruta. Confirmarlo con la obra lo
    dejaría CONFIRMADO; la vista previa no lo ofrece y Motor lo rechaza."""
    basura = "12-10-2026 :17576134-9 LLEGADA"
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    _sin_ruta(actual / "analisis_completo_guias.csv", basura)
    decision["contexto"]["destino_documental"] = basura
    generar_artefacto(ruta_dataset=actual / "analisis_completo_guias.csv", carpeta_catalogos=catalogos, decisiones=[decision], ruta_salida=actual / "decisiones_pendientes.json")

    vista = previsualizar_registro_obra_destino(raiz_atlas=raiz, decision_id=decision["decision_id"], base_geografica_local=base_ine)

    assert vista["destino"]["requiere_confirmacion"] is True
    assert vista["destino"]["comuna"] == "" and vista["ubicacion"] is None
    assert vista["confirmacion_conjunta_disponible"] is False
    assert vista["motivo_no_disponible"] == MOTIVO_DESTINO_CONTAMINADO
    assert vista["validaciones"]["geografia"]["estado"] == "CONFLICTO"
    with pytest.raises(ErrorAplicacionDecision, match=MOTIVO_DESTINO_CONTAMINADO):
        aplicar_decision_obra(
            raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR",
            confirmar_destino_conjunto=True, huella_vista_previa=vista["huella"], base_geografica_local=base_ine,
        )
    assert _ledger(actual) == []
    # "Registrar sólo la obra" sigue disponible y la dirección queda en su tarjeta.
    assert aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR")["ok"]
    assert [d["tipo"] for d in _pendientes(actual)] == ["DESTINO_SIN_CONFIRMAR"]


def test_sin_ruta_calculada_no_se_ofrece_aunque_la_calle_exista(tmp_path, base_ine):
    """La comuna verificada sólo viene de una ruta calculada sobre esta
    dirección -- sin ruta, la confirmación conjunta no se ofrece aunque la
    calle exista en la base territorial."""
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    _sin_ruta(actual / "analisis_completo_guias.csv", DESTINO)
    generar_artefacto(ruta_dataset=actual / "analisis_completo_guias.csv", carpeta_catalogos=catalogos, decisiones=[decision], ruta_salida=actual / "decisiones_pendientes.json")
    vista = previsualizar_registro_obra_destino(raiz_atlas=raiz, decision_id=decision["decision_id"], base_geografica_local=base_ine)
    assert vista["confirmacion_conjunta_disponible"] is False
    assert vista["motivo_no_disponible"] == MOTIVO_SIN_VALIDACION_GEOGRAFICA


@pytest.mark.parametrize("texto", [
    "12-10-2026 :17576134-9 LLEGADA",          # 475603: fecha + RUT + etiqueta
    "10833150-K FECHA",                        # 460486: RUT + etiqueta
    "SANTA ISABEL 585 SANTIAGO LAMPA :15454297-3",  # RUT pegado al final
    "PATENTE : BDFG50",                        # etiqueta de otro campo
    "3.812,00",                                # peso sin letras
    "HELSINSKI 5810 FECHA LLEGADA",            # etiqueta en cualquier posición
])
def test_destino_contaminado_por_ocr_se_rechaza(texto):
    assert motivo_destino_documental_no_confiable(texto) == MOTIVO_DESTINO_CONTAMINADO


@pytest.mark.parametrize("texto", [
    DESTINO, "PANAMERICANA NORTE 22650 SANTIAGO LAMPA", "HELSINSKI 5810 LA REINA SANTIAGO",
    "CAMINO A MELIPILLA 10800 SANTIAGO MAIPU", "CALLE D LOTE 27 Y 28 PANQUE INDRUST CORONEL",
    "CAM. EL NOVICIADO LAMPA LAMPA", "PARCELA 12-3 LAMPA",
])
def test_direcciones_reales_no_se_marcan_contaminadas(texto):
    assert motivo_destino_documental_no_confiable(texto) == ""


def test_destino_contaminado_no_se_ofrece_aunque_la_fila_tenga_ruta(tmp_path, base_ine):
    """El rechazo por contaminación es propio: no depende de que falte
    geografía. Aunque la fila tuviera ruta calculada, un destino con fecha/
    RUT/etiqueta nunca se confirma junto con la obra."""
    basura = "12-10-2026 :17576134-9 LLEGADA"
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    dataset = actual / "analisis_completo_guias.csv"
    filas = list(_leer_csv(dataset).values())
    for fila in filas:
        if fila["numero_guia"] == GUIA:
            fila["despachar_a_crudo"] = basura
    _escribir_csv(dataset, filas)
    decision["contexto"]["destino_documental"] = basura
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision], ruta_salida=actual / "decisiones_pendientes.json")
    vista = previsualizar_registro_obra_destino(raiz_atlas=raiz, decision_id=decision["decision_id"], base_geografica_local=base_ine)
    assert vista["confirmacion_conjunta_disponible"] is False
    assert vista["motivo_no_disponible"] == MOTIVO_DESTINO_CONTAMINADO


def test_ruta_calculada_sobre_otra_direccion_no_valida_el_destino(tmp_path, base_ine):
    """La ruta de la fila sólo cuenta si se calculó sobre ESTA misma
    dirección documental."""
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    decision["contexto"]["destino_documental"] = "OTRA CALLE 100 SAN MIGUEL"
    generar_artefacto(ruta_dataset=actual / "analisis_completo_guias.csv", carpeta_catalogos=catalogos, decisiones=[decision], ruta_salida=actual / "decisiones_pendientes.json")
    vista = previsualizar_registro_obra_destino(raiz_atlas=raiz, decision_id=decision["decision_id"], base_geografica_local=base_ine)
    assert vista["destino"]["comuna"] == ""
    assert vista["confirmacion_conjunta_disponible"] is False
    assert vista["motivo_no_disponible"] == MOTIVO_SIN_VALIDACION_GEOGRAFICA
