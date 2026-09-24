"""Bloque P0 -- CONVERGENCIA DE IDENTIDADES CONOCIDAS. Casos reales
473546 (CHOFER_CANDIDATO/SALOMÓN PIZARRO) y 473442 (CLIENTE_DESCONOCIDO/
TORRES OCARANZA LTDA). Tests puramente sintéticos, nunca tocan G:."""
from __future__ import annotations

import csv
import json

from atlas_core.catalogo_clientes import Cliente, normalizar_nombre_cliente
from atlas_core.convergencia_identidad_conocida import (
    RESULTADO_ABSTENCION,
    RESULTADO_RESUELTO,
    RESULTADO_SIN_EVIDENCIA,
    resolver_identidad_nominal_fuerte_chofer,
    resolver_identidad_nominal_fuerte_cliente,
)
from atlas_core.decisiones_pendientes import crear_decision, regenerar_decisiones_persistidas
from atlas_core.procesamiento_masivo import COLUMNAS

RUT_TORRES_CANONICO = "50234350-5"


def _cliente(cliente_id, razon_social, rut="", estado_calidad="CONFIRMADO", estado_vigencia="ACTIVO"):
    return Cliente(
        cliente_id=cliente_id, razon_social=razon_social,
        nombre_normalizado=normalizar_nombre_cliente(razon_social), nombre_comercial="",
        rut=rut, aliases=(), estado_calidad=estado_calidad, estado_vigencia=estado_vigencia,
        fuente="TEST", observacion="", fecha_creacion="2026-01-01T00:00:00+00:00",
        fecha_modificacion="2026-01-01T00:00:00+00:00",
    )


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "1.jpeg", "numero_guia": "1", "chofer": "No encontrado", "rut_chofer": "No encontrado",
        "cliente": "No encontrado", "rut_cliente": "No encontrado", "motivos_revision_documento": "",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _catalogos_vacios(tmp_path):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "choferes.json": {},
    }.items():
        (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    return carpeta


def _escribir_choferes(carpeta, choferes):
    (carpeta / "choferes.json").write_text(json.dumps(choferes), encoding="utf-8")


def _escribir_clientes(carpeta, clientes):
    contenido = {"version_formato": 1, "clientes": [c.a_dict() for c in clientes]}
    (carpeta / "clientes.json").write_text(json.dumps(contenido), encoding="utf-8")


def _decision_chofer_candidato(*, archivo, numero_guia, valor_documental):
    return crear_decision(
        tipo="CHOFER_CANDIDATO", entidad="CHOFER", archivo=archivo, numero_guia=numero_guia,
        numero_transporte="No encontrado", campo="chofer", valor_documental=valor_documental,
        valor_normalizado=valor_documental, identidad_resuelta=None, candidatos=[],
        motivos=("CHOFER_SIN_CORROBORAR_REQUIERE_CONFIRMACION",),
        evidencias=({"tipo": "RUT_DOCUMENTAL", "valor": ""},),
        acciones_permitidas=("CONFIRMAR", "NO_CONFIRMAR", "POSPONER"),
    )


def _decision_cliente_desconocido(*, archivo, numero_guia, valor_documental):
    return crear_decision(
        tipo="CLIENTE_DESCONOCIDO", entidad="CLIENTE", archivo=archivo, numero_guia=numero_guia,
        numero_transporte="No encontrado", campo="cliente", valor_documental=valor_documental,
        valor_normalizado=valor_documental, identidad_resuelta=None, candidatos=[],
        motivos=("CLIENTE_SIN_CORROBORAR_SIN_ESTRATEGIA_AUTOMATICA",), evidencias=(),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
    )


# ==================== CASO A -- CHOFER (473546) ====================

def test_caso_a_473546_nombre_unico_activo_resuelve_pese_a_rut_contradictorio():
    choferes = {
        "180915885": {"nombre": "SALOMÓN PIZARRO", "rut": None, "activo": True},
    }
    resultado = resolver_identidad_nominal_fuerte_chofer(
        nombre_documental="SALOMÓN PIZARRO", rut_documental="18091586-9",  # válido pero DISTINTO del canónico
        choferes=choferes,
    )
    assert resultado.resultado == RESULTADO_RESUELTO
    assert resultado.identificador == "180915885"
    assert resultado.rut_documental_conservado == "18091586-9"  # evidencia conservada, no descartada


def test_chofer_rut_ausente_no_impide_resolver():
    choferes = {"1": {"nombre": "JUAN PEREZ", "rut": "11111111-1", "activo": True}}
    resultado = resolver_identidad_nominal_fuerte_chofer(
        nombre_documental="JUAN PEREZ", rut_documental="No encontrado", choferes=choferes,
    )
    assert resultado.resultado == RESULTADO_RESUELTO


def test_chofer_inactivo_no_auto_resuelve():
    choferes = {"1": {"nombre": "JUAN PEREZ", "rut": "11111111-1", "activo": False}}
    resultado = resolver_identidad_nominal_fuerte_chofer(
        nombre_documental="JUAN PEREZ", rut_documental="No encontrado", choferes=choferes,
    )
    assert resultado.resultado != RESULTADO_RESUELTO


def test_chofer_dos_candidatos_nominales_se_abstiene():
    choferes = {
        "1": {"nombre": "JUAN PEREZ", "rut": "11111111-1", "activo": True},
        "2": {"nombre": "JUAN PEREZ", "rut": "22222222-2", "activo": True},
    }
    resultado = resolver_identidad_nominal_fuerte_chofer(
        nombre_documental="JUAN PEREZ", rut_documental="No encontrado", choferes=choferes,
    )
    assert resultado.resultado == RESULTADO_ABSTENCION
    assert resultado.identificador is None


def test_chofer_fuzzy_no_exacto_no_resuelve_por_este_mecanismo():
    """Una variante de OCR (no exacta) sigue sin resolverse aquí -- las
    reglas existentes (fuzzy/CHOFER_CANDIDATO por candidatos ambiguos)
    siguen intactas y son las que deben seguir aplicando."""
    choferes = {"1": {"nombre": "SALOMÓN PIZARRO", "rut": None, "activo": True}}
    resultado = resolver_identidad_nominal_fuerte_chofer(
        nombre_documental="SALOYOX PIZRRRO",  # variante real de OCR, no exacta
        rut_documental="No encontrado", choferes=choferes,
    )
    assert resultado.resultado != RESULTADO_RESUELTO


def test_bandeja_retira_chofer_candidato_convergente_y_conserva_lo_demas(tmp_path):
    carpeta = _catalogos_vacios(tmp_path)
    _escribir_choferes(carpeta, {"180915885": {"nombre": "SALOMÓN PIZARRO", "rut": None, "activo": True}})
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [
        _fila(archivo="473546.jpeg", numero_guia="473546", chofer="SALOMÓN PIZARRO", rut_chofer="18091586-9"),
        _fila(archivo="otro.jpeg", numero_guia="9", chofer="ALGUIEN DESCONOCIDO", rut_chofer="No encontrado"),
    ])
    convergente = _decision_chofer_candidato(archivo="473546.jpeg", numero_guia="473546", valor_documental="SALOMÓN PIZARRO")
    otra_decision_no_relacionada = _decision_chofer_candidato(archivo="otro.jpeg", numero_guia="9", valor_documental="ALGUIEN DESCONOCIDO")

    restantes = regenerar_decisiones_persistidas(
        decisiones=[convergente, otra_decision_no_relacionada], carpeta_catalogos=carpeta, ruta_dataset=dataset,
    )
    ids = {d["decision_id"] for d in restantes}
    assert convergente["decision_id"] not in ids
    assert otra_decision_no_relacionada["decision_id"] in ids  # nunca se toca una decisión no relacionada

    # Nunca se corrige/sobrescribe el RUT documental en el dataset.
    filas_tras = list(csv.DictReader(dataset.open(encoding="utf-8-sig", newline=""), delimiter=";"))
    assert filas_tras[0]["rut_chofer"] == "18091586-9"


# ==================== CASO B -- CLIENTE (473442) ====================

def test_caso_b_473442_rut_exacto_resuelve():
    torres = _cliente("cliente-torres", "TORRES OCARANZA LTDA", rut=RUT_TORRES_CANONICO)
    resultado = resolver_identidad_nominal_fuerte_cliente(
        nombre_documental="TORRES OCARANZA LTDA", rut_documental="50.234.350-5", clientes=[torres],
    )
    assert resultado.resultado == RESULTADO_RESUELTO
    assert resultado.cliente_id == "cliente-torres"
    assert resultado.via == "RUT"


def test_caso_b_473442_rut_persistido_contradictorio_se_abstiene():
    """Con el RUT documental REALMENTE persistido hoy (garbled por OCR,
    válido pero distinto), 473442 debe seguir pendiente -- nunca se
    fuerza la identidad sólo porque el nombre coincide."""
    torres = _cliente("cliente-torres", "TORRES OCARANZA LTDA", rut=RUT_TORRES_CANONICO)
    resultado = resolver_identidad_nominal_fuerte_cliente(
        nombre_documental="TORRES OCARANZA LTDA", rut_documental="5.023.415-0", clientes=[torres],
    )
    assert resultado.resultado == RESULTADO_ABSTENCION
    assert resultado.cliente_id is None


def test_cliente_nombre_exacto_unico_sin_rut_resuelve():
    torres = _cliente("cliente-torres", "TORRES OCARANZA LTDA", rut=RUT_TORRES_CANONICO)
    resultado = resolver_identidad_nominal_fuerte_cliente(
        nombre_documental="TORRES OCARANZA LTDA", rut_documental="No encontrado", clientes=[torres],
    )
    assert resultado.resultado == RESULTADO_RESUELTO
    assert resultado.via == "NOMBRE"


def test_cliente_dos_candidatos_nominales_se_abstiene():
    a = _cliente("a", "MISMO NOMBRE SA")
    b = _cliente("b", "MISMO NOMBRE SA")
    resultado = resolver_identidad_nominal_fuerte_cliente(
        nombre_documental="MISMO NOMBRE SA", rut_documental="No encontrado", clientes=[a, b],
    )
    assert resultado.resultado == RESULTADO_ABSTENCION


def test_cliente_inactivo_o_no_confirmado_no_auto_resuelve():
    pendiente = _cliente("p", "EMPRESA PENDIENTE SA", estado_calidad="PENDIENTE")
    inactivo = _cliente("i", "EMPRESA INACTIVA SA", estado_vigencia="INACTIVO")
    for candidato in (pendiente, inactivo):
        resultado = resolver_identidad_nominal_fuerte_cliente(
            nombre_documental=candidato.razon_social, rut_documental="No encontrado", clientes=[candidato],
        )
        assert resultado.resultado != RESULTADO_RESUELTO


def test_cliente_sin_coincidencia_ninguna_sin_evidencia():
    torres = _cliente("cliente-torres", "TORRES OCARANZA LTDA", rut=RUT_TORRES_CANONICO)
    resultado = resolver_identidad_nominal_fuerte_cliente(
        nombre_documental="EMPRESA TOTALMENTE DISTINTA SPA", rut_documental="No encontrado", clientes=[torres],
    )
    assert resultado.resultado == RESULTADO_SIN_EVIDENCIA


def test_bandeja_retira_cliente_desconocido_convergente_usando_rut_vigente(tmp_path):
    carpeta = _catalogos_vacios(tmp_path)
    torres = _cliente("cliente-torres", "TORRES OCARANZA LTDA", rut=RUT_TORRES_CANONICO)
    _escribir_clientes(carpeta, [torres])
    _escribir_choferes(carpeta, {})
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [
        # RUT vigente ya corregido (reextracción) -- coincide exacto.
        _fila(archivo="473442.jpeg", numero_guia="473442", cliente="TORRES OCARANZA LTDA", rut_cliente="50.234.350-5"),
    ])
    decision = _decision_cliente_desconocido(archivo="473442.jpeg", numero_guia="473442", valor_documental="TORRES OCARANZA LTDA")

    restantes = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=carpeta, ruta_dataset=dataset,
    )
    assert restantes == []
    # Nunca crea un cliente/alias nuevo -- el catálogo queda intacto.
    contenido = json.loads((carpeta / "clientes.json").read_text(encoding="utf-8"))
    assert len(contenido["clientes"]) == 1


def test_bandeja_conserva_cliente_desconocido_con_rut_contradictorio_persistido(tmp_path):
    """Caso real EXACTO de hoy: con el RUT tal cual está persistido en
    G: (contradictorio), la tarjeta debe SOBREVIVIR -- nunca se
    homologa a la fuerza."""
    carpeta = _catalogos_vacios(tmp_path)
    torres = _cliente("cliente-torres", "TORRES OCARANZA LTDA", rut=RUT_TORRES_CANONICO)
    _escribir_clientes(carpeta, [torres])
    _escribir_choferes(carpeta, {})
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [
        _fila(archivo="473442.jpeg", numero_guia="473442", cliente="TORRES OCARANZA LTDA", rut_cliente="5.023.415-0"),
    ])
    decision = _decision_cliente_desconocido(archivo="473442.jpeg", numero_guia="473442", valor_documental="TORRES OCARANZA LTDA")

    restantes = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=carpeta, ruta_dataset=dataset,
    )
    assert len(restantes) == 1
    assert restantes[0]["decision_id"] == decision["decision_id"]


def test_convergencia_nunca_toca_vehiculo_desconocido(tmp_path):
    """VEHICULO_DESCONOCIDO (y por extensión cualquier tipo que no sea
    CHOFER_CANDIDATO/CLIENTE_DESCONOCIDO) queda fuera del alcance de este
    bloque -- aislamiento de scope, incluso cuando el cliente vigente de
    ESA misma fila sí converge y el valor de patente sigue vigente
    (nada más lo retiraría tampoco)."""
    carpeta = _catalogos_vacios(tmp_path)
    torres = _cliente("cliente-torres", "TORRES OCARANZA LTDA", rut=RUT_TORRES_CANONICO)
    _escribir_clientes(carpeta, [torres])
    _escribir_choferes(carpeta, {})
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila(
        archivo="1.jpeg", numero_guia="1", cliente="TORRES OCARANZA LTDA", rut_cliente=RUT_TORRES_CANONICO,
        patente_tracto="BPHR67",
    )])
    decision_vehiculo = crear_decision(
        tipo="VEHICULO_DESCONOCIDO", entidad="VEHICULO", archivo="1.jpeg", numero_guia="1",
        numero_transporte="No encontrado", campo="patente_tracto", valor_documental="BPHR67",
        valor_normalizado="BPHR67", identidad_resuelta=None,
        candidatos=[], motivos=("SIN_VEHICULO_CONFIRMADO_COMPATIBLE",), evidencias=(),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        tipo_resolucion="REQUIERE_CONFIRMACION_HUMANA", tipo_vehiculo_propuesto=None,
    )
    restantes = regenerar_decisiones_persistidas(
        decisiones=[decision_vehiculo], carpeta_catalogos=carpeta, ruta_dataset=dataset,
    )
    assert len(restantes) == 1  # sobrevive -- este bloque no toca VEHICULO_DESCONOCIDO
