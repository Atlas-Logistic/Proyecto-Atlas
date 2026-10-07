"""Caso real 475498 (envío e79c617e, transporte 0000362665): un reenvío
Mobile con una foto mucho mejor de una guía ya registrada desde una foto
mala se asociaba a "No encontrado" (transporte de la fila vieja) y su
lectura nueva se descartaba. Ahora mejora la MISMA fila con la política de
relectura existente, sin duplicar el documento ni pisar evidencia válida."""
from __future__ import annotations

import csv
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

import atlas_core.mobile as mobile
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_vehiculos import TipoVehiculo, confirmar_vehiculo
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
from atlas_core.gestor_viajes import agrupar_viajes
from atlas_core.mobile import (
    RepositorioEnviosMobile, asociar_documento, procesar_envio_mobile,
    recuperar_relectura_reenvio_mobile, revalidar_asociacion_mobile_sin_ocr,
)
from atlas_core.procesamiento_masivo import COLUMNAS

TRANSPORTE = "0000362665"


def _fila(**valores: str) -> dict[str, str]:
    fila = {c: "" for c in COLUMNAS}
    fila.update(estado_procesamiento="OK", fecha="06-10-2026")
    fila.update(valores)
    return fila


def _hermana(guia: str, peso: str, material: str) -> dict[str, str]:
    return _fila(
        archivo=f"{guia}.jpeg", numero_guia=guia, numero_transporte=TRANSPORTE, chofer="RENÉ GARCÍA",
        rut_chofer="9708225-1", cliente="EBEMA SA", rut_cliente="83.585.400-0", obra_destino="EBEMA SA",
        patente_tracto="AL1879", patente_rampla="JK2501", peso_kg=peso, descripcion_material=material,
        despachar_a_crudo="GALVARINO 8501 QUILICURA", direccion_entrega="GALVARINO 8501 QUILICURA",
        estado_ruta="RUTA_CALCULADA", indicador_revision="OK", estado_documental="OK", estado_operacional="OK",
    )


def _vieja_475498(**extra: str) -> dict[str, str]:
    fila = _fila(
        archivo="475498.jpeg", numero_guia="475498", numero_transporte="No encontrado",
        chofer="No encontrado", rut_chofer="No encontrado", cliente="No encontrado", rut_cliente="No encontrado",
        obra_destino="No encontrado", patente_tracto="GARC1A", patente_rampla="No encontrado",
        peso_kg="No encontrado", codigo_cliente="0001001424", despachar_a_crudo="1 CALVARINO 8501 QUSLIC9A",
        indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION",
        estado_operacional="REQUIERE_REVISION", fecha_ingesta_utc="2026-10-07T13:24:36+00:00",
        motivos_revision_documento=(
            "PATENTE_SIN_HOMOLOGAR | TRANSPORTE_AUSENTE | CHOFER_AUSENTE | CLIENTE_AUSENTE"
            " | MATERIAL_AUSENTE | DOCUMENTO_DEGRADADO"
        ),
    )
    fila.update(extra)
    return fila


def _lectura_mobile(**extra: object) -> dict[str, object]:
    datos: dict[str, object] = {c: "" for c in COLUMNAS}
    datos.update(
        numero_guia="475498", numero_transporte=TRANSPORTE, fecha="06-10-2026", chofer="RENÉ GARCÍA",
        rut_chofer="9.708.225-1", cliente="EBEMA SA", rut_cliente="83.585.400-0", obra_destino="EBEMA SA",
        patente_tracto="AL1879", patente_rampla="JK2501", peso_kg="12233",
        descripcion_material="B HORMIGON 12MM 12M A630-420H (N)", tipo_carga="BARRAS",
        despachar_a_crudo="GALVARINO 8501 QUILICURA", direccion_entrega="GALVARINO 8501 QUILICURA",
        estado_ruta="RUTA_CALCULADA", estado_entrega="RESUELTO", indicador_revision="OK",
        estado_documental="OK", estado_operacional="OK", motivos_revision_documento="",
        estado_procesamiento="OK",
    )
    datos.update(extra)
    return datos


def _entorno(tmp_path: Path, *, vieja: dict[str, str] | None = None, ledger: list | None = None):
    raiz = tmp_path
    catalogos = raiz / "catalogos_privados"; catalogos.mkdir()
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []}, "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
        "plantas.json": {"version_formato": 1, "plantas": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="EBEMA SA", rut="83.585.400-0", fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    fecha = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for patente, tipo in (("AL1879", TipoVehiculo.TRACTO), ("JK2501", TipoVehiculo.CARRO)):
        confirmar_vehiculo(catalogos / "vehiculos.json", patente=patente, tipo=tipo.value,
                           actor="TEST", fuente_decision="TEST", fecha=fecha)
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    dataset.parent.mkdir(parents=True)
    filas = [
        _hermana("475497", "4202", "ROLLO HORMIGON 16MM A630-420H (N)"),
        vieja or _vieja_475498(),
        _hermana("475499", "3059", "B HORMIGON 8MM 12M A630-420H (N)"),
    ]
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";"); escritor.writeheader(); escritor.writerows(filas)
    espurias = [
        crear_decision(
            tipo="VEHICULO_DESCONOCIDO", entidad="VEHICULO", archivo="475498.jpeg", numero_guia="475498",
            numero_transporte="No encontrado", campo="patente_tracto", valor_documental="GARC1A",
            valor_normalizado="GARC1A", identidad_resuelta=None, candidatos=(),
            motivos=("SIN_VEHICULO_CONFIRMADO_COMPATIBLE",),
            evidencias=({"tipo": "OCR_DOCUMENTAL", "campo": "patente_tracto", "valor": "GARC1A"},),
            acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        ),
        crear_decision(
            tipo="CLIENTE_AUSENTE", entidad="CLIENTE", archivo="475498.jpeg", numero_guia="475498",
            numero_transporte="No encontrado", campo="cliente", valor_documental="", valor_normalizado="",
            identidad_resuelta=None, candidatos=(), motivos=("CLIENTE_AUSENTE",),
            evidencias=({"tipo": "CAMPO_VACIO", "campo": "cliente"},),
            acciones_permitidas=("REGISTRAR_CLIENTE_MANUAL", "NO_PUEDO_DETERMINAR", "POSPONER"),
        ),
        crear_decision(
            tipo="DESTINO_NO_RESUELTO", entidad="DESTINO", archivo="475498.jpeg", numero_guia="475498",
            numero_transporte="No encontrado", campo="despachar_a_crudo",
            valor_documental="1 CALVARINO 8501 QUSLIC9A", valor_normalizado="", identidad_resuelta=None,
            candidatos=(), motivos=("OBRA_AUSENTE_BLOQUEA_RUTEO",),
            evidencias=({"tipo": "RUTA_BLOQUEADA", "despachar_a_crudo": "1 CALVARINO 8501 QUSLIC9A"},),
            acciones_permitidas=("REGISTRAR_DIRECCION", "NO_PUEDO_DETERMINAR", "POSPONER"),
        ),
    ]
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=espurias,
                      ruta_salida=dataset.parent / "decisiones_pendientes.json")
    if ledger is not None:
        (dataset.parent / "decisiones_aplicadas.json").write_text(json.dumps({"aplicaciones": ledger}), encoding="utf-8")
    repo = RepositorioEnviosMobile(raiz)
    envio_id = str(uuid.uuid4())
    repo.recibir(envio_id=envio_id, imagen=b"foto-mejor", mime="image/jpeg",
                 metadata={"chofer_id": "chofer-prueba-javier", "planta_origen_informada": "AZA_COLINA"})
    return raiz, catalogos, dataset, repo, envio_id


def _procesar(monkeypatch, dataset, catalogos, repo, envio_id, datos):
    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(mobile, "procesar_archivo", lambda _imagen, **_kw: dict(datos))
    return procesar_envio_mobile(repo, envio_id, dataset=dataset, carpeta_catalogos=catalogos)


def _filas(dataset):
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _tarjetas(dataset, guia="475498"):
    decisiones = json.loads((dataset.parent / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]
    return [(d["tipo"], d.get("valor_documental")) for d in decisiones if d["documento"].get("numero_guia") == guia]


def test_475498_reenvio_mejor_promueve_la_misma_fila(tmp_path, monkeypatch):
    raiz, catalogos, dataset, repo, envio_id = _entorno(tmp_path)
    assert len(_tarjetas(dataset)) == 3
    registro = _procesar(monkeypatch, dataset, catalogos, repo, envio_id, _lectura_mobile())

    filas = _filas(dataset)
    propias = [f for f in filas if f["numero_guia"] == "475498"]
    # A/F: una sola fila 475498, ninguna fila propia del envío.
    assert len(propias) == 1 and len(filas) == 3
    fila = propias[0]
    assert fila["archivo"] == "475498.jpeg"
    assert fila["fecha_ingesta_utc"] == "2026-10-07T13:24:36+00:00"
    assert registro["archivo_dataset"] == ""
    # B/C: mejorada por relectura y asociada a 0000362665.
    assert (fila["numero_transporte"], fila["chofer"], fila["cliente"]) == (TRANSPORTE, "RENÉ GARCÍA", "EBEMA SA")
    assert (fila["patente_tracto"], fila["patente_rampla"]) == ("AL1879", "JK2501")
    assert fila["despachar_a_crudo"] == "GALVARINO 8501 QUILICURA"
    assert fila["motivos_revision_documento"] == ""
    assert registro["resultado_asociacion"]["numero_transporte"] == TRANSPORTE
    assert registro["resultado_asociacion"]["documento_ya_existe"] is True
    assert registro["relectura_documento"]["promovida"] is True
    # E: un valor válido que la lectura nueva no trae se conserva.
    assert fila["codigo_cliente"] == "0001001424"
    # I: peso/material propios de 475498; las hermanas intactas.
    assert (fila["peso_kg"], fila["descripcion_material"]) == ("12233", "B HORMIGON 12MM 12M A630-420H (N)")
    por_guia = {f["numero_guia"]: f for f in filas}
    assert (por_guia["475497"]["peso_kg"], por_guia["475499"]["peso_kg"]) == ("4202", "3059")
    # G: las tres revisiones espurias ya no corresponden.
    tarjetas = _tarjetas(dataset)
    assert not {"VEHICULO_DESCONOCIDO", "CLIENTE_AUSENTE", "DESTINO_NO_RESUELTO"} & {t for t, _ in tarjetas}
    # H: un único viaje 0000362665 con las tres guías.
    viajes, _ = agrupar_viajes(filas)
    assert [(v.numero_transporte, sorted(d.numero_guia for d in v.documentos)) for v in viajes] == [
        (TRANSPORTE, ["475497", "475498", "475499"]),
    ]
    # Trazabilidad: el reenvío Mobile quedó como la evidencia que promovió.
    relecturas = json.loads((raiz / "operacion" / "relecturas_documentales.json").read_text(encoding="utf-8"))
    entrada = relecturas["documentos"]["475498.jpeg"]["historial"][-1]
    assert (entrada["resultado"], entrada["origen"], entrada["envio_id"]) == ("PROMOVIDA", "MOBILE", envio_id)
    assert entrada["evidencia"] == f"mobile/{envio_id}/original.jpg"
    assert (repo.raiz / envio_id / "original.jpg").read_bytes() == b"foto-mejor"


def test_lectura_nueva_peor_no_promueve(tmp_path, monkeypatch):
    _, catalogos, dataset, repo, envio_id = _entorno(tmp_path)
    antes = _filas(dataset)
    peor = _lectura_mobile(motivos_revision_documento="DOCUMENTO_DEGRADADO", indicador_revision="REVISAR")
    registro = _procesar(monkeypatch, dataset, catalogos, repo, envio_id, peor)
    assert _filas(dataset) == antes
    assert registro["relectura_documento"]["promovida"] is False


def test_identidad_conflictiva_no_promueve(tmp_path, monkeypatch):
    vieja = _vieja_475498(numero_transporte="0000370001")
    _, catalogos, dataset, repo, envio_id = _entorno(tmp_path, vieja=vieja)
    antes = _filas(dataset)
    registro = _procesar(monkeypatch, dataset, catalogos, repo, envio_id, _lectura_mobile())
    assert _filas(dataset) == antes
    assert registro["relectura_documento"]["motivo"] == "IDENTIDAD_DISTINTA"


def test_decision_humana_protegida_no_se_sobrescribe(tmp_path, monkeypatch):
    vieja = _vieja_475498(peso_kg="12000")
    ledger = [{"documento": {"archivo": "475498.jpeg", "numero_guia": "475498"}, "campo": "peso_kg",
               "tipo": "PESO_VIAJE_IMPLAUSIBLE", "accion": "CORREGIR_PESO"}]
    _, catalogos, dataset, repo, envio_id = _entorno(tmp_path, vieja=vieja, ledger=ledger)
    registro = _procesar(monkeypatch, dataset, catalogos, repo, envio_id, _lectura_mobile())
    fila = next(f for f in _filas(dataset) if f["numero_guia"] == "475498")
    assert registro["relectura_documento"]["promovida"] is True
    assert fila["peso_kg"] == "12000"  # la corrección humana gana
    assert fila["numero_transporte"] == TRANSPORTE


def test_transporte_ocr_invalido_no_inventa_asociacion():
    filas = [_vieja_475498(), _hermana("475497", "4202", "X")]
    asociacion = asociar_documento(_lectura_mobile(numero_transporte="No encontrado"), filas)
    assert asociacion["estado"] == "SIN_ASOCIACION"
    assert asociacion["numero_transporte"] == ""
    assert asociacion["documento_ya_existe"] is True


def test_asociacion_por_guia_prefiere_transporte_valido_de_la_fila():
    filas = [_vieja_475498(numero_transporte="0000362999")]
    asociacion = asociar_documento(_lectura_mobile(), filas)
    assert asociacion["numero_transporte"] == "0000362999"  # comportamiento de siempre


def test_revalidacion_reevalua_asociado_a_transporte_invalido(tmp_path, monkeypatch):
    _, catalogos, dataset, repo, envio_id = _entorno(tmp_path)
    registro = repo.cargar(envio_id)
    registro.update(estado="ASOCIADO", datos_ocr=_lectura_mobile(), problema_captura=False, resultado_asociacion={
        "estado": "ASOCIADO_AUTOMATICAMENTE", "numero_transporte": "No encontrado", "numero_guia": "475498",
        "candidatos": ["No encontrado"], "motivo": "x", "documento_ya_existe": True,
    })
    repo.guardar(envio_id, registro)
    resumen = revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)
    assert envio_id in resumen["actualizados"]
    assert repo.cargar(envio_id)["resultado_asociacion"]["numero_transporte"] == TRANSPORTE


def test_recuperacion_sin_ocr_de_reenvio_almacenado_es_idempotente(tmp_path, monkeypatch):
    _, catalogos, dataset, repo, envio_id = _entorno(tmp_path)
    registro = repo.cargar(envio_id)
    registro.update(estado="ASOCIADO", datos_ocr=_lectura_mobile(), problema_captura=False,
                    imagen_sha256="9be2", resultado_asociacion={"estado": "ASOCIADO_AUTOMATICAMENTE",
                    "numero_transporte": "No encontrado", "numero_guia": "475498", "documento_ya_existe": True})
    repo.guardar(envio_id, registro)
    reportes = []
    monkeypatch.setattr(mobile, "_regenerar_reporte_tras_envio_mobile", lambda _r, e: reportes.append(e) or True)
    monkeypatch.setattr(mobile, "procesar_archivo", lambda *_a, **_k: pytest.fail("no debe correr OCR"))

    primero = recuperar_relectura_reenvio_mobile(repo, envio_id, dataset=dataset, carpeta_catalogos=catalogos)
    assert primero["promovida"] is True and reportes == [envio_id]
    fila = next(f for f in _filas(dataset) if f["numero_guia"] == "475498")
    assert fila["numero_transporte"] == TRANSPORTE
    assert repo.cargar(envio_id)["resultado_asociacion"]["numero_transporte"] == TRANSPORTE

    segundo = recuperar_relectura_reenvio_mobile(repo, envio_id, dataset=dataset, carpeta_catalogos=catalogos)
    assert segundo["promovida"] is False and segundo["motivo"] == "SIN_MEJORA"
    assert len(_filas(dataset)) == 3
