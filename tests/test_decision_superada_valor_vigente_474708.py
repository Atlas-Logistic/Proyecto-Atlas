"""Caso real 474708 -- tras una reextracción la obra pasó de QUELICURA (valor
de COMUNA mal asignado) a CONSTRUMART SA CONCEDCION (método GEOMETRICO, sin
corroborar). El flujo dejaba dos inconsistencias:

1. el reparador retiraba OBRA_DESTINO_SIN_CORROBORAR aunque el valor nuevo
   sigue sin corroborar;
2. la bandeja conservaba la tarjeta OBRA_DESCONOCIDA = QUELICURA.

Regla general: los motivos de un campo reemplazado son los del valor NUEVO
(evaluados por las reglas de siempre en la reextracción), y una
OBRA_DESCONOCIDA cuyo valor ya no es el vigente se retira en la
reconciliación canónica de la bandeja, generando -- con el cliente ya
resuelto de la propia decisión -- sólo la pregunta que el valor nuevo
necesita. Datos sintéticos (sin 474708/QUELICURA/CONSTRUMART hardcodeados en
la lógica).
"""
from __future__ import annotations

import csv
import json

from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, ResultadoEvidencia, TipoEvidencia
from atlas_core.decisiones_pendientes import crear_decision, regenerar_decisiones_persistidas
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.reprocesamiento_reparador import CambioCampo, _aplicar_cambios_a_fila

SIN_CORROBORAR = "OBRA_DESTINO_SIN_CORROBORAR"


# ------------------------------------------------------------ utilidades


def _catalogos(tmp_path, *, estado_cliente=EstadoCalidadCliente.CONFIRMADO):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    (carpeta / "clientes.json").write_text(json.dumps({"version_formato": 1, "clientes": []}), encoding="utf-8")
    (carpeta / "destinos_maestros.json").write_text(json.dumps({"version_formato": 1, "destinos": []}), encoding="utf-8")
    (carpeta / "obras_destinos.json").write_text(
        json.dumps({"version_formato": 1, "obras": [], "relaciones": []}), encoding="utf-8",
    )
    for nombre, contenido in {"choferes.json": {}, "vehiculos.json": {}, "empresas.json": {},
                              "plantas.json": {"plantas": []}, "rutas.json": {"rutas": []}}.items():
        (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    cliente = CatalogoClientes(carpeta / "clientes.json").crear(
        razon_social="CLIENTE UNO SA", rut="76.111.111-6", fuente="TEST", estado_calidad=estado_cliente,
    )
    return carpeta, cliente


def _confirmar_obra(carpeta, cliente, nombre_obra):
    destino = CatalogoDestinos(carpeta / "destinos_maestros.json", ruta_clientes=carpeta / "clientes.json").crear(
        cliente_id="", nombre_destino="CALLE UNO 100 SANTIAGO", direccion="CALLE UNO 100 SANTIAGO",
        pais="CHILE", fuente="TEST", estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    obras = CatalogoObrasDestinos(
        ruta=carpeta / "obras_destinos.json", ruta_clientes=carpeta / "clientes.json",
        ruta_destinos=carpeta / "destinos_maestros.json",
    )
    observacion = obras.registrar_observacion(
        cliente_id=cliente.cliente_id, nombre_obra=nombre_obra, destino_id=destino.destino_id,
        evidencia=Evidencia(
            tipo=TipoEvidencia.GUIA.value, identificador_fuente="100001", referencia_hash="a" * 64,
            campos_observados={"obra": nombre_obra}, fecha="2026-01-01T00:00:00+00:00",
            actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value,
        ),
    )
    obras.confirmar_relacion(observacion.relacion.relacion_id, actor="TEST", identificador_fuente="test")


def _fila(guia="500001", **overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": f"{guia}.jpeg", "estado_procesamiento": "OK", "numero_guia": guia,
        "numero_transporte": "0000900001", "cliente": "CLIENTE UNO SA", "obra_destino": "",
        "despachar_a_crudo": "CALLE DOS 200 SANTIAGO", "motivos_revision_documento": SIN_CORROBORAR,
        "motivo_ruta": "MULTIPLES_UBICACIONES_DISPERSAS(3)", "estado_ruta": "REQUIERE_REVISION",
    })
    fila.update(overrides)
    return fila


def _dataset(tmp_path, filas, *, ledger=()):
    ruta = tmp_path / "actual" / "analisis_completo_guias.csv"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)
    (ruta.parent / "decisiones_aplicadas.json").write_text(
        json.dumps({"aplicaciones": list(ledger)}), encoding="utf-8",
    )
    return ruta


def _obra_desconocida(valor, cliente, guia="500001"):
    return crear_decision(
        tipo="OBRA_DESCONOCIDA", entidad="OBRA", archivo=f"{guia}.jpeg", numero_guia=guia,
        numero_transporte="0000900001", campo="obra_destino", valor_documental=valor, valor_normalizado=valor,
        identidad_resuelta=None, candidatos=(), motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),
        evidencias=({"tipo": "CLIENTE_RESUELTO", "entidad_id": cliente.cliente_id},),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        contexto={"cliente_id": cliente.cliente_id, "cliente_canonico": cliente.razon_social, "destino_documental": ""},
    )


def _destino_no_resuelto(guia="500001"):
    return crear_decision(
        tipo="DESTINO_NO_RESUELTO", entidad="DESTINO", archivo=f"{guia}.jpeg", numero_guia=guia,
        numero_transporte="0000900001", campo="despachar_a_crudo", valor_documental="CALLE DOS 200 SANTIAGO",
        valor_normalizado="", identidad_resuelta=None, candidatos=(), motivos=("MULTIPLES_UBICACIONES_DISPERSAS",),
        evidencias=({"tipo": "RUTA_BLOQUEADA", "motivo_ruta": "MULTIPLES_UBICACIONES_DISPERSAS(3)"},),
        acciones_permitidas=("REGISTRAR_DIRECCION", "NO_PUEDO_DETERMINAR", "POSPONER"),
    )


def _reconciliar(decisiones, carpeta, dataset):
    return regenerar_decisiones_persistidas(decisiones=decisiones, carpeta_catalogos=carpeta, ruta_dataset=dataset)


def _obras(decisiones):
    return [(d["tipo"], d["valor_documental"]) for d in decisiones if d.get("campo") == "obra_destino"]


# ------------------------------------------------ A. motivos del valor nuevo


def test_reextraccion_conserva_sin_corroborar_si_el_valor_nuevo_sigue_sin_corroborar():
    fila = _fila(obra_destino="COMUNA LEIDA", motivos_revision_documento=f"PATENTE_SIN_HOMOLOGAR | {SIN_CORROBORAR}")
    cambio = CambioCampo("500001.jpeg", "500001", "obra_destino", "COMUNA LEIDA", "OBRA NUEVA SA SUR")
    _aplicar_cambios_a_fila(fila, [cambio], motivos_reextraccion=f"{SIN_CORROBORAR} | MATERIAL_AUSENTE")
    assert fila["obra_destino"] == "OBRA NUEVA SA SUR"
    motivos = fila["motivos_revision_documento"].split(" | ")
    assert SIN_CORROBORAR in motivos
    assert "PATENTE_SIN_HOMOLOGAR" in motivos, "motivos de otros campos se conservan"
    assert "MATERIAL_AUSENTE" not in motivos, "la reextracción no agrega motivos de campos no reemplazados"


def test_reextraccion_retira_sin_corroborar_si_el_valor_nuevo_ya_esta_corroborado():
    fila = _fila(obra_destino="COMUNA LEIDA")
    cambio = CambioCampo("500001.jpeg", "500001", "obra_destino", "COMUNA LEIDA", "OBRA CONOCIDA")
    _aplicar_cambios_a_fila(fila, [cambio], motivos_reextraccion="")
    assert SIN_CORROBORAR not in fila["motivos_revision_documento"]


# ----------------------------------------- B. decisiones por valor vigente


def test_caso_real_decision_del_valor_anterior_se_reemplaza_por_una_del_valor_vigente(tmp_path):
    carpeta, cliente = _catalogos(tmp_path)
    dataset = _dataset(tmp_path, [_fila(obra_destino="OBRA NUEVA SA SUR", cliente="CLIENTE UN0 SA")])
    vieja = _obra_desconocida("COMUNA LEIDA", cliente)
    resultado = _reconciliar([vieja, _destino_no_resuelto()], carpeta, dataset)
    assert _obras(resultado) == [("OBRA_DESCONOCIDA", "OBRA NUEVA SA SUR")]
    nueva = next(d for d in resultado if d.get("campo") == "obra_destino")
    assert nueva["decision_id"] != vieja["decision_id"]
    assert nueva["contexto"]["cliente_id"] == cliente.cliente_id, "cliente ya resuelto, no re-resuelto del OCR"
    assert nueva["estado"] == "PENDIENTE"
    # Decisión de otro campo en la misma guía: intacta.
    assert any(d["tipo"] == "DESTINO_NO_RESUELTO" for d in resultado)


def test_valor_cambia_a_obra_ya_confirmada_retira_la_vieja_y_no_crea_nueva(tmp_path):
    carpeta, cliente = _catalogos(tmp_path)
    _confirmar_obra(carpeta, cliente, "OBRA CONFIRMADA NORTE")
    for motivos in ("", SIN_CORROBORAR):
        dataset = _dataset(tmp_path, [_fila(obra_destino="OBRA CONFIRMADA NORTE", motivos_revision_documento=motivos)])
        resultado = _reconciliar([_obra_desconocida("COMUNA LEIDA", cliente)], carpeta, dataset)
        assert _obras(resultado) == [], motivos


def test_valor_no_cambia_conserva_la_decision_sin_duplicarla(tmp_path):
    carpeta, cliente = _catalogos(tmp_path)
    dataset = _dataset(tmp_path, [_fila(obra_destino="OBRA NUEVA SA SUR")])
    decision = _obra_desconocida("OBRA NUEVA SA SUR", cliente)
    resultado = _reconciliar([decision], carpeta, dataset)
    assert [d["decision_id"] for d in resultado if d.get("campo") == "obra_destino"] == [decision["decision_id"]]


def test_valor_cambia_dos_veces_solo_queda_la_decision_del_ultimo_valor(tmp_path):
    carpeta, cliente = _catalogos(tmp_path)
    dataset = _dataset(tmp_path, [_fila(obra_destino="OBRA TERCERA")])
    resultado = _reconciliar(
        [_obra_desconocida("OBRA PRIMERA", cliente), _obra_desconocida("OBRA SEGUNDA", cliente)], carpeta, dataset,
    )
    assert _obras(resultado) == [("OBRA_DESCONOCIDA", "OBRA TERCERA")]


def test_segunda_reconciliacion_es_idempotente(tmp_path):
    carpeta, cliente = _catalogos(tmp_path)
    dataset = _dataset(tmp_path, [_fila(obra_destino="OBRA NUEVA SA SUR")])
    primera = _reconciliar([_obra_desconocida("COMUNA LEIDA", cliente), _destino_no_resuelto()], carpeta, dataset)
    segunda = _reconciliar(primera, carpeta, dataset)
    assert sorted(d["decision_id"] for d in segunda) == sorted(d["decision_id"] for d in primera)
    assert len({d["decision_id"] for d in segunda}) == len(segunda)


def test_decision_de_otra_guia_no_se_toca(tmp_path):
    carpeta, cliente = _catalogos(tmp_path)
    dataset = _dataset(tmp_path, [
        _fila(obra_destino="OBRA NUEVA SA SUR"),
        _fila(guia="500002", obra_destino="OBRA AJENA"),
    ])
    ajena = _obra_desconocida("OBRA AJENA", cliente, guia="500002")
    resultado = _reconciliar([_obra_desconocida("COMUNA LEIDA", cliente), ajena], carpeta, dataset)
    assert ajena["decision_id"] in {d["decision_id"] for d in resultado}


def test_obra_ya_decidida_por_un_humano_no_se_reabre(tmp_path):
    carpeta, cliente = _catalogos(tmp_path)
    ledger = [{"tipo": "OBRA_DESCONOCIDA", "accion": "REGISTRAR", "documento": {"numero_guia": "500001"}}]
    dataset = _dataset(tmp_path, [_fila(obra_destino="OBRA NUEVA SA SUR")], ledger=ledger)
    decision = _obra_desconocida("COMUNA LEIDA", cliente)
    resultado = _reconciliar([decision], carpeta, dataset)
    assert ("OBRA_DESCONOCIDA", "OBRA NUEVA SA SUR") not in _obras(resultado)


def test_valor_vigente_ausente_o_cliente_no_confirmado_no_reemplaza(tmp_path):
    carpeta, cliente = _catalogos(tmp_path)
    dataset = _dataset(tmp_path, [_fila(obra_destino="No encontrado")])
    decision = _obra_desconocida("COMUNA LEIDA", cliente)
    assert decision["decision_id"] in {d["decision_id"] for d in _reconciliar([decision], carpeta, dataset)}

    otra = tmp_path / "otro"
    otra.mkdir()
    carpeta_b, cliente_b = _catalogos(otra, estado_cliente=EstadoCalidadCliente.PENDIENTE)
    dataset_b = _dataset(otra, [_fila(obra_destino="OBRA NUEVA SA SUR")])
    decision_b = _obra_desconocida("COMUNA LEIDA", cliente_b)
    assert decision_b["decision_id"] in {d["decision_id"] for d in _reconciliar([decision_b], carpeta_b, dataset_b)}
