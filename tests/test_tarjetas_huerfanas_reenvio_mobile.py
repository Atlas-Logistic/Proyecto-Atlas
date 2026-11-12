"""Caso real 484396 / transporte 0000369573 (11/11/2026): el envío Mobile
5de6b068 (10/11) es la fila canónica; el reenvío 5dd077a0 (11/11) no fue
promovido (SIN_MEJORA) y no tiene fila propia, pero publicó una tarjeta
VEHICULO_DESCONOCIDO rampla JF5595 bajo su propio archivo. Javier corrigió la
fila canónica (rampla JF9575) y la tarjeta seguía en Revisión de Atlas: ninguna
corrección ni reconciliación podía alcanzarla.

1. Un reenvío sin fila propia ya no publica tarjetas independientes.
2. La reconciliación oficial (`regenerar_decisiones_persistidas`) retira las
   tarjetas huérfanas SÓLO con prueba inequívoca en `envio.json` + dataset.
3. Toda otra tarjeta y el ledger de decisiones humanas quedan intactos."""
from __future__ import annotations

import copy
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import atlas_core.mobile as mobile
from atlas_core.catalogo_vehiculos import TipoVehiculo, confirmar_vehiculo
from atlas_core.decisiones_pendientes import (
    crear_decision, regenerar_decisiones_persistidas, retirar_decisiones_reenvio_mobile_huerfanas,
)
from atlas_core.mobile import RepositorioEnviosMobile, _reenvio_sin_fila_propia, procesar_envio_mobile
from atlas_core.procesamiento_masivo import COLUMNAS

GUIA, TRANSPORTE = "484396", "0000369573"
CANONICO_ID = "5de6b068-d394-4a9a-a479-61002f310597"
REENVIO_ID = "5dd077a0-a68d-49c5-b540-5ff1b29abb07"
CANONICO = f"mobile/{CANONICO_ID}/original.jpg"
REENVIO = f"mobile/{REENVIO_ID}/original.jpg"


def _fila(**valores: str) -> dict[str, str]:
    fila = {c: "" for c in COLUMNAS}
    fila.update(estado_procesamiento="OK")
    fila.update(valores)
    return fila


def _fila_canonica(**extra: str) -> dict[str, str]:
    # Estado real tras las correcciones de Javier (peso 27287, rampla JF9575).
    fila = _fila(
        archivo=CANONICO, numero_guia=GUIA, numero_transporte=TRANSPORTE, fecha="No encontrado",
        chofer="No encontrado", rut_chofer="No encontrado", cliente="DIREOCION", obra_destino="BBEM2.SA",
        patente_tracto="No encontrado", patente_rampla="JF9575", peso_kg="27287", tipo_carga="NO DETERMINADO",
        indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION", estado_operacional="REQUIERE_REVISION",
        motivos_revision_documento="CHOFER_AUSENTE | CLIENTE_SIN_CORROBORAR | MATERIAL_AUSENTE | OBRA_DESTINO_SIN_CORROBORAR",
    )
    fila.update(extra)
    return fila


def _fila_otra() -> dict[str, str]:
    return _fila(
        archivo="484293.jpeg", numero_guia="484293", numero_transporte="0000369273", chofer="LUIS REYES",
        rut_chofer="7814310-K", cliente="EBEMA SA", obra_destino="EBEMA SA", patente_tracto="KN5439",
        patente_rampla="JF6468", indicador_revision="OK", estado_documental="OK", estado_operacional="OK",
    )


def _lectura_reenvio() -> dict[str, object]:
    datos: dict[str, object] = {c: "" for c in COLUMNAS}
    datos.update(
        numero_guia=GUIA, numero_transporte=TRANSPORTE, fecha="10-11-2026", chofer="SALOMÓN PIZARRO",
        rut_chofer="18091588-5", cliente="EBEMA SA", obra_destino="EBEMA SA", patente_tracto="TG8925",
        patente_rampla="JF5595", descripcion_material="B HORMIGON 12MM12M A630-420H(N)", tipo_carga="BARRAS",
        peso_kg="27287", hora_entrada_aza="No encontrado", hora_salida_aza="No encontrado",
        permanencia_minutos="No encontrado", indicador_revision="REVISAR",
        motivos_revision_documento="PATENTE_SIN_HOMOLOGAR", estado_documental="REQUIERE_REVISION",
        estado_operacional="REQUIERE_REVISION", estado_procesamiento="OK",
    )
    return datos


def _tarjeta(archivo: str, *, guia: str = GUIA, transporte: str = TRANSPORTE, campo: str = "patente_rampla",
             valor: str = "JF5595") -> dict[str, object]:
    return crear_decision(
        tipo="VEHICULO_DESCONOCIDO", entidad="VEHICULO", archivo=archivo, numero_guia=guia,
        numero_transporte=transporte, campo=campo, valor_documental=valor, valor_normalizado=valor,
        identidad_resuelta=None, candidatos=(), motivos=("SIN_VEHICULO_CONFIRMADO_COMPATIBLE",),
        evidencias=({"tipo": "OCR_DOCUMENTAL", "campo": campo, "valor": valor},),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        tipo_resolucion="INEQUIVOCO", tipo_vehiculo_propuesto="CARRO",
    )


LEDGER = {"schema_version": 1, "aplicaciones": [{
    "decision_id": "ACCION_OPERACIONAL:b4bc9f0742f04dff9b536fa47ded71f4",
    "tipo": "CORRECCION_DOCUMENTAL_OPERADOR", "accion": "CORREGIR_CAMPO", "actor": "B1",
    "confirmado_por": "JAVIER_DESKTOP", "fecha": "2026-11-11T19:04:37.026138+00:00",
    "documento": {"archivo": CANONICO, "numero_guia": GUIA, "numero_transporte": TRANSPORTE},
    "campo": "patente_rampla", "valor_documental": "TG8925", "valor_corregido": "JF9575",
}]}


def _registro_reenvio(**cambios: object) -> dict[str, object]:
    """`envio.json` real del reenvío 5dd077a0 (campos relevantes)."""
    registro: dict[str, object] = {
        "schema_version": 1, "envio_id": REENVIO_ID, "estado": "REQUIERE_REVISION",
        "foto_original": "original.jpg", "archivo_dataset": "",
        "resultado_asociacion": {"estado": "ASOCIADO_AUTOMATICAMENTE", "numero_transporte": TRANSPORTE,
                                 "numero_guia": GUIA, "candidatos": [TRANSPORTE], "documento_ya_existe": True},
        "datos_ocr": _lectura_reenvio(),
        "relectura_documento": {"archivo_canonico": CANONICO, "promovida": False, "motivo": "SIN_MEJORA"},
    }
    registro.update(cambios)
    return registro


def _entorno(tmp_path: Path, *, filas: list[dict[str, str]] | None = None):
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
    fecha = datetime(2026, 9, 21, tzinfo=timezone.utc)
    for patente, tipo in (("TG8925", TipoVehiculo.TRACTO), ("JF9575", TipoVehiculo.CARRO),
                          ("KN5439", TipoVehiculo.TRACTO), ("JF6468", TipoVehiculo.CARRO)):
        confirmar_vehiculo(catalogos / "vehiculos.json", patente=patente, tipo=tipo.value,
                           actor="TEST", fuente_decision="TEST", fecha=fecha)
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    dataset.parent.mkdir(parents=True)
    _escribir(dataset, filas if filas is not None else [_fila_otra(), _fila_canonica()])
    (dataset.parent / "decisiones_aplicadas.json").write_text(json.dumps(LEDGER), encoding="utf-8")
    return raiz, catalogos, dataset


def _escribir(dataset: Path, filas: list[dict[str, str]]) -> None:
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerows(filas)


def _guardar_envio(raiz: Path, registro: dict[str, object], envio_id: str = REENVIO_ID) -> None:
    carpeta = raiz / "operacion" / "mobile" / "envios" / envio_id
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "envio.json").write_text(json.dumps(registro, ensure_ascii=False), encoding="utf-8")


def _ids(decisiones) -> list[str]:
    return [str(d["decision_id"]) for d in decisiones]


# ---------------------------------------------------------------- 1. prevención


def test_484396_reenvio_no_promovido_no_publica_tarjetas(tmp_path, monkeypatch):
    raiz, catalogos, dataset = _entorno(tmp_path)
    valida = _tarjeta("484293.jpeg", guia="484293", transporte="0000369273", campo="patente_tracto", valor="KN5A39")
    (dataset.parent / "decisiones_pendientes.json").write_text(
        json.dumps({"schema_version": 1, "decisiones": [valida]}), encoding="utf-8")
    filas_antes = dataset.read_bytes()
    ledger_antes = (dataset.parent / "decisiones_aplicadas.json").read_bytes()

    repo = RepositorioEnviosMobile(raiz)
    repo.recibir(envio_id=REENVIO_ID, imagen=b"foto-reenvio", mime="image/jpeg",
                 metadata={"chofer_id": "chofer-prueba-javier", "planta_origen_informada": "AZA_COLINA"})

    def procesar_archivo_falso(_imagen, **kw):
        # El detector real identifica por nombre de archivo ("original.jpg").
        kw["recolector_decisiones"]([_tarjeta("original.jpg")])
        return dict(_lectura_reenvio())

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(mobile, "procesar_archivo", procesar_archivo_falso)
    registro = procesar_envio_mobile(repo, REENVIO_ID, dataset=dataset, carpeta_catalogos=catalogos)

    assert registro["resultado_asociacion"]["documento_ya_existe"] is True
    assert registro["archivo_dataset"] == ""
    assert registro["relectura_documento"]["promovida"] is False
    bandeja = json.loads((dataset.parent / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]
    assert not [d for d in bandeja if d["documento"]["archivo"] == REENVIO]
    assert valida["decision_id"] in _ids(bandeja)
    assert dataset.read_bytes() == filas_antes
    assert (dataset.parent / "decisiones_aplicadas.json").read_bytes() == ledger_antes


def test_reintento_con_fila_propia_conserva_sus_tarjetas(tmp_path):
    _, _, dataset = _entorno(tmp_path, filas=[_fila_canonica(archivo=REENVIO)])
    # Un intento previo ya escribió la fila de ESTE envío: no es huérfano.
    assert _reenvio_sin_fila_propia({"documento_ya_existe": True}, identificador=REENVIO, dataset=dataset) is False
    assert _reenvio_sin_fila_propia({"documento_ya_existe": False}, identificador=REENVIO, dataset=dataset) is False
    assert _reenvio_sin_fila_propia({"documento_ya_existe": True}, identificador=CANONICO, dataset=dataset) is True
    assert _reenvio_sin_fila_propia({"documento_ya_existe": True}, identificador=CANONICO,
                                    dataset=dataset.parent / "inexistente.csv") is False


# ---------------------------------------------------------------- 2. retiro


def test_484396_reconciliacion_oficial_retira_tarjeta_huerfana(tmp_path):
    raiz, catalogos, dataset = _entorno(tmp_path)
    _guardar_envio(raiz, _registro_reenvio())
    huerfana = _tarjeta(REENVIO)
    otra = _tarjeta("484293.jpeg", guia="484293", transporte="0000369273", campo="patente_tracto", valor="KN5A39")
    ledger_antes = (dataset.parent / "decisiones_aplicadas.json").read_bytes()

    con = regenerar_decisiones_persistidas(decisiones=[otra, huerfana], carpeta_catalogos=catalogos,
                                           ruta_dataset=dataset)
    sin = regenerar_decisiones_persistidas(decisiones=[otra], carpeta_catalogos=catalogos, ruta_dataset=dataset)

    assert huerfana["decision_id"] not in _ids(con)
    assert con == sin  # el resto de la bandeja no cambia en nada
    assert (dataset.parent / "decisiones_aplicadas.json").read_bytes() == ledger_antes


def test_tarjetas_de_la_fila_canonica_se_conservan(tmp_path):
    raiz, _, dataset = _entorno(tmp_path)
    _guardar_envio(raiz, _registro_reenvio())
    canonica = _tarjeta(CANONICO, campo="patente_tracto", valor="TG8925")
    otra = _tarjeta("484293.jpeg", guia="484293", transporte="0000369273")
    salida = retirar_decisiones_reenvio_mobile_huerfanas(
        [canonica, _tarjeta(REENVIO), otra], ruta_dataset=dataset)
    assert _ids(salida) == [canonica["decision_id"], otra["decision_id"]]


def _sin(clave: str) -> dict[str, object]:
    registro = _registro_reenvio()
    registro.pop(clave)
    return registro


def _con(ruta: tuple[str, ...], valor: object) -> dict[str, object]:
    registro = copy.deepcopy(_registro_reenvio())
    destino = registro
    for clave in ruta[:-1]:
        destino = destino[clave]
    destino[ruta[-1]] = valor
    return registro


@pytest.mark.parametrize("registro", [
    _con(("relectura_documento", "promovida"), True),
    _con(("relectura_documento", "archivo_canonico"), ""),
    _con(("relectura_documento", "archivo_canonico"), REENVIO),
    _con(("relectura_documento", "archivo_canonico"), "mobile/otro/original.jpg"),
    _con(("resultado_asociacion", "documento_ya_existe"), False),
    _con(("archivo_dataset",), REENVIO),
    _con(("foto_original",), "otra.jpg"),
    _con(("envio_id",), CANONICO_ID),
    _con(("datos_ocr", "numero_transporte"), "0000369999"),
    _con(("datos_ocr", "numero_guia"), "484397"),
    _sin("relectura_documento"),
    _sin("resultado_asociacion"),
    None,  # sin envio.json
], ids=["promovida", "canonico-vacio", "canonico-propio", "canonico-inexistente", "no-ya-existe",
        "con-fila-propia", "foto-distinta", "envio-distinto", "transporte-leido-distinto",
        "guia-leida-distinta", "sin-relectura", "sin-asociacion", "sin-envio"])
def test_ante_duda_se_abstiene(tmp_path, registro):
    raiz, _, dataset = _entorno(tmp_path)
    if registro is not None:
        _guardar_envio(raiz, registro)
    tarjeta = _tarjeta(REENVIO)
    assert _ids(retirar_decisiones_reenvio_mobile_huerfanas([tarjeta], ruta_dataset=dataset)) == [tarjeta["decision_id"]]


@pytest.mark.parametrize("filas", [
    [_fila_otra()],  # sin fila canónica
    [_fila_otra(), _fila_canonica(), _fila_canonica()],  # canónica ambigua
    [_fila_otra(), _fila_canonica(numero_transporte="0000369999")],  # canónica de otro transporte
    [_fila_otra(), _fila_canonica(), _fila_canonica(archivo=REENVIO)],  # el reenvío tiene fila propia
], ids=["sin-canonica", "canonica-duplicada", "canonica-otro-transporte", "reenvio-con-fila"])
def test_dataset_no_concluyente_se_abstiene(tmp_path, filas):
    raiz, _, dataset = _entorno(tmp_path, filas=filas)
    _guardar_envio(raiz, _registro_reenvio())
    tarjeta = _tarjeta(REENVIO)
    assert _ids(retirar_decisiones_reenvio_mobile_huerfanas([tarjeta], ruta_dataset=dataset)) == [tarjeta["decision_id"]]


@pytest.mark.parametrize("guia,transporte", [("484397", TRANSPORTE), (GUIA, "0000369999"), ("No encontrado", TRANSPORTE)])
def test_tarjeta_de_otra_identidad_se_abstiene(tmp_path, guia, transporte):
    raiz, _, dataset = _entorno(tmp_path)
    _guardar_envio(raiz, _registro_reenvio())
    tarjeta = _tarjeta(REENVIO, guia=guia, transporte=transporte)
    assert _ids(retirar_decisiones_reenvio_mobile_huerfanas([tarjeta], ruta_dataset=dataset)) == [tarjeta["decision_id"]]


def test_fuera_de_raiz_atlas_no_retira(tmp_path):
    raiz, _, dataset = _entorno(tmp_path)
    _guardar_envio(raiz, _registro_reenvio())
    otro = tmp_path / "suelto.csv"
    otro.write_bytes(dataset.read_bytes())
    tarjeta = _tarjeta(REENVIO)
    assert _ids(retirar_decisiones_reenvio_mobile_huerfanas([tarjeta], ruta_dataset=otro)) == [tarjeta["decision_id"]]
