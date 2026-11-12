"""Expediente digital, base funcional -- sólo fixtures sintéticas.

Las dos empresas comparten deliberadamente RUT, clave de chofer, `vehiculo_id`
y patente: lo único que las separa es su almacén y sus catálogos.
"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import date, datetime, timezone

import pytest

from atlas_core.almacenamiento_portable import SesionOcupadaError
from atlas_core.expediente_digital import (
    ALTERADO, ANULADO, ARCHIVO_AUSENTE, FECHA_INVALIDA, INTEGRO, PENDIENTE_REVISION, POR_VENCER, REEMPLAZADO,
    SIN_HUELLA, SIN_VENCIMIENTO, VENCIDO, VIGENTE, ErrorExpedienteDigital, actualizar_documento, anular_documento,
    configurar_tipo_documento, consultar_expediente, consultar_vencimientos, crear_expediente, documentos_ausentes,
    estado_expediente, leer_expediente, preparar_alertas_vencimiento, registrar_documento, ruta_almacen_expediente,
    verificar_originales,
)
from tests.test_acciones_operacionales import _vehiculo

HOY = date(2026, 11, 9)
RELOJ = lambda: datetime(2026, 11, 9, 12, tzinfo=timezone.utc)  # noqa: E731
RUT, CLAVE, PATENTE = "12.345.678-5", "123456785", "KN5439"
PDF = b"%PDF-1.4 original sintetico"
PNG = b"\x89PNG\r\n\x1a\n" + b"foto sintetica"
NORTE, SUR = "NORTE", "SUR"


def _catalogos(carpeta, nombre, *, vehiculos=(PATENTE,)):
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "choferes.json").write_text(json.dumps({
        CLAVE: {"nombre": nombre, "rut": RUT, "aliases": [], "activo": True}}), encoding="utf-8")
    (carpeta / "vehiculos.json").write_text(json.dumps({
        "version": 1, "vehiculos": [_vehiculo(p) for p in vehiculos]}), encoding="utf-8")
    return carpeta


@pytest.fixture
def dos(tmp_path):
    """Dos empresas en una raíz, cada una con su catálogo e iguales identificadores."""
    raiz = tmp_path / "Atlas"
    return {"raiz": raiz, NORTE: _catalogos(tmp_path / "cat_norte", "ANA NORTE"),
            SUR: _catalogos(tmp_path / "cat_sur", "ANA SUR")}


def _chofer(dos, empresa=NORTE, **extra):
    datos = {"entidad": "CHOFER", "referencia": RUT, "tipo": "LICENCIA_CONDUCIR", "fecha_vencimiento": "2027-06-01",
             "actor": "TEST", "reloj": RELOJ, **extra}
    return registrar_documento(dos["raiz"], empresa=empresa, carpeta_catalogos=dos[empresa], **datos)


def _veh(dos, empresa=NORTE, **extra):
    datos = {"entidad": "VEHICULO", "referencia": PATENTE, "tipo": "SOAP", "fecha_vencimiento": "2027-03-31",
             "actor": "TEST", "reloj": RELOJ, **extra}
    return registrar_documento(dos["raiz"], empresa=empresa, carpeta_catalogos=dos[empresa], **datos)


def _consulta(dos, empresa=NORTE, entidad="VEHICULO", referencia=PATENTE):
    return consultar_expediente(dos["raiz"], empresa=empresa, entidad=entidad, referencia=referencia, hoy=HOY,
                                carpeta_catalogos=dos[empresa])


def _sha(contenido):
    return hashlib.sha256(contenido).hexdigest()


def _almacen(dos, empresa=NORTE):
    return ruta_almacen_expediente(dos["raiz"], empresa)


def _ficha(raiz, empresa, *, choferes=(), vehiculos=()):
    ruta = raiz / "fichas_digitales" / empresa / "fichas_documentales.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({"version": 2, "empresa": empresa, "revision": 1, "choferes": list(choferes),
                                "vehiculos": list(vehiculos)}), encoding="utf-8")
    return ruta


def _ficha_chofer(referencias, documentos=()):
    return {"ficha_id": str(uuid.uuid4()), "referencias_catalogo": list(referencias), "complementarios": {},
            "historial": [], "documentos": list(documentos)}


# ------------------------------------------------------------- alta e identidad


def test_alta_crea_un_solo_expediente_por_identidad(dos):
    primero = crear_expediente(dos["raiz"], empresa=NORTE, entidad="CHOFER", referencia=RUT, actor="TEST",
                               carpeta_catalogos=dos[NORTE], reloj=RELOJ)
    repetido = crear_expediente(dos["raiz"], empresa=NORTE, entidad="CHOFER", referencia=CLAVE, actor="TEST",
                                carpeta_catalogos=dos[NORTE], reloj=RELOJ)
    assert primero["creado"] and not repetido["creado"]
    assert primero["expediente_id"] == repetido["expediente_id"]
    datos = leer_expediente(dos["raiz"], empresa=NORTE)
    assert len(datos["expedientes"]) == 1 and datos["revision"] == 1  # repetir no escribe
    documento = _chofer(dos)
    assert documento["expediente_id"] == primero["expediente_id"]


def test_expediente_no_copia_datos_descriptivos(dos):
    _chofer(dos)
    texto = _almacen(dos).read_text(encoding="utf-8")
    assert "ANA NORTE" not in texto and RUT not in texto


def test_cambio_descriptivo_no_duplica_expediente(dos):
    antes = _chofer(dos)
    _catalogos(dos[NORTE], "ANA MARIA NORTE DE PEREZ")  # cambia el nombre, misma identidad
    despues = _chofer(dos, tipo="LICENCIA_CONDUCIR")
    assert antes["expediente_id"] == despues["expediente_id"]
    assert len(leer_expediente(dos["raiz"], empresa=NORTE)["expedientes"]) == 1


def test_correccion_de_patente_conserva_expediente(dos):
    antes = _veh(dos)
    catalogo = json.loads((dos[NORTE] / "vehiculos.json").read_text(encoding="utf-8"))
    catalogo["vehiculos"][0].update(patente_canonica="KN5440", aliases=[PATENTE])  # vehiculo_id estable
    catalogo["vehiculos"][0]["evidencias"][0]["campos_observados"]["alias"] = PATENTE
    (dos[NORTE] / "vehiculos.json").write_text(json.dumps(catalogo), encoding="utf-8")
    assert _veh(dos, referencia="KN5440")["expediente_id"] == antes["expediente_id"]
    assert _veh(dos, referencia=PATENTE)["expediente_id"] == antes["expediente_id"]  # por alias
    assert len(leer_expediente(dos["raiz"], empresa=NORTE)["expedientes"]) == 1


def test_consulta_por_patente_anterior_con_identificador_propio(dos):
    catalogo = json.loads((dos[NORTE] / "vehiculos.json").read_text(encoding="utf-8"))
    catalogo["vehiculos"][0].update(vehiculo_id="veh-estable-1", patente_canonica="KN5440", aliases=[PATENTE])
    catalogo["vehiculos"][0]["evidencias"][0]["campos_observados"]["alias"] = PATENTE
    (dos[NORTE] / "vehiculos.json").write_text(json.dumps(catalogo), encoding="utf-8")
    documento = _veh(dos, referencia=PATENTE)
    assert documento["referencia_catalogo"] == "veh-estable-1"
    assert _consulta(dos, referencia="KN5440")["expediente_id"] == documento["expediente_id"]


def test_cambio_de_clave_con_vinculo_de_ficha_conserva_expediente(dos):
    antes = _chofer(dos)
    (dos[NORTE] / "choferes.json").write_text(json.dumps({
        "NUEVA1": {"nombre": "ANA NORTE", "rut": RUT, "aliases": [], "activo": True}}), encoding="utf-8")
    _ficha(dos["raiz"], NORTE, choferes=[_ficha_chofer([CLAVE, "NUEVA1"])])
    despues = _chofer(dos, referencia="NUEVA1")
    assert despues["expediente_id"] == antes["expediente_id"]
    datos = leer_expediente(dos["raiz"], empresa=NORTE)
    assert len(datos["expedientes"]) == 1 and datos["expedientes"][0]["referencias"] == [CLAVE, "NUEVA1"]
    assert "EXPEDIENTE_REFERENCIA_VINCULADA" in [e["operacion"] for e in datos["historial"]]


def test_cambio_de_clave_sin_vinculo_no_se_adivina(dos):
    antes = _chofer(dos)
    (dos[NORTE] / "choferes.json").write_text(json.dumps({
        "NUEVA1": {"nombre": "ANA NORTE", "rut": RUT, "aliases": [], "activo": True}}), encoding="utf-8")
    assert _chofer(dos, referencia="NUEVA1")["expediente_id"] != antes["expediente_id"]


def test_alta_concurrente_no_duplica(dos):
    errores, ids = [], []
    inicio = threading.Barrier(8)

    def alta():
        inicio.wait()
        try:
            ids.append(crear_expediente(dos["raiz"], empresa=NORTE, entidad="VEHICULO", referencia=PATENTE, actor="T",
                                        carpeta_catalogos=dos[NORTE], reloj=RELOJ)["expediente_id"])
        except SesionOcupadaError:  # el bloqueo rechaza al competidor en vez de esperar
            pass
        except Exception as error:  # noqa: BLE001 -- la prueba las inspecciona
            errores.append(error)

    hilos = [threading.Thread(target=alta) for _ in range(8)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()
    assert not errores and len(set(ids)) == 1
    assert len(leer_expediente(dos["raiz"], empresa=NORTE)["expedientes"]) == 1


# ------------------------------------------------------------- consulta y vencimiento


def test_campos_del_documento(dos):
    documento = _veh(dos, fecha_emision="2026-03-31", archivo="archivos/v/soap.pdf", sha256=_sha(b"x"))
    assert (documento["tipo"], documento["fecha_emision"], documento["fecha_vencimiento"], documento["estado"],
            documento["archivo"]) == ("SOAP", "2026-03-31", "2027-03-31", "ACTIVO", "archivos/v/soap.pdf")


@pytest.mark.parametrize("vencimiento, estado, dias", [
    ("2026-11-08", VENCIDO, -1), ("2026-11-09", POR_VENCER, 0), ("2026-12-09", POR_VENCER, 30),
    ("2026-12-10", VIGENTE, 31),
])
def test_limites_de_vencimiento(dos, vencimiento, estado, dias):
    _veh(dos, fecha_vencimiento=vencimiento)
    documento = _consulta(dos)["documentos"][0]
    assert (documento["estado_vencimiento"], documento["dias_para_vencer"]) == (estado, dias)


def test_vencimiento_cambia_solo_con_la_fecha_consultada(dos):
    _veh(dos, fecha_vencimiento="2026-11-20")
    antes = _almacen(dos).read_bytes()
    estados = [estado_expediente(dos["raiz"], empresa=NORTE, hoy=h, carpeta_catalogos=dos[NORTE])[0]["estado_vencimiento"]
               for h in (date(2026, 10, 1), date(2026, 11, 20), date(2026, 11, 21))]
    assert estados == [VIGENTE, POR_VENCER, VENCIDO]
    assert _almacen(dos).read_bytes() == antes
    assert "estado_vencimiento" not in antes.decode("utf-8")


def test_consultar_vencimientos_agrupa_y_filtra(dos):
    _veh(dos, tipo="SOAP", fecha_vencimiento="2026-01-01")
    _veh(dos, tipo="REVISION_TECNICA", fecha_vencimiento="2026-11-20")
    _veh(dos, tipo="PERMISO_CIRCULACION", fecha_vencimiento="2028-01-01")
    _chofer(dos, fecha_vencimiento="2028-01-01")
    grupos = consultar_vencimientos(dos["raiz"], empresa=NORTE, hoy=HOY, carpeta_catalogos=dos[NORTE])
    assert ([d["tipo"] for d in grupos[VENCIDO]], [d["tipo"] for d in grupos[POR_VENCER]], len(grupos[VIGENTE])) == (
        ["SOAP"], ["REVISION_TECNICA"], 2)
    solo = consultar_vencimientos(dos["raiz"], empresa=NORTE, hoy=HOY, entidad="CHOFER", carpeta_catalogos=dos[NORTE])
    assert [d["tipo"] for d in solo[VIGENTE]] == ["LICENCIA_CONDUCIR"] and not solo[VENCIDO]


def test_consulta_de_identidad_sin_expediente_no_escribe(dos):
    consulta = _consulta(dos)
    assert not consulta["existe"] and consulta["documentos"] == []
    assert {a["tipo"] for a in consulta["ausentes"]} == {"SOAP", "REVISION_TECNICA", "PERMISO_CIRCULACION", "CERTIFICADO_EMISION_GASES", "POLIZA_RESPONSABILIDAD_CIVIL"}
    assert not _almacen(dos).exists()


def test_alertas_se_preparan_sin_notificar_ni_escribir(dos, monkeypatch):
    _veh(dos, tipo="SOAP", fecha_vencimiento="2026-11-01")
    _veh(dos, tipo="REVISION_TECNICA", fecha_vencimiento="2026-11-20")
    _veh(dos, tipo="PERMISO_CIRCULACION", fecha_vencimiento="2029-01-01")
    antes = _almacen(dos).read_bytes()
    archivos = {p for p in dos["raiz"].rglob("*")}

    def prohibido(*_a, **_k):
        raise AssertionError("preparar alertas no debe abrir red")
    monkeypatch.setattr("socket.socket.connect", prohibido)
    alertas = preparar_alertas_vencimiento(dos["raiz"], empresa=NORTE, hoy=HOY, carpeta_catalogos=dos[NORTE])
    assert [(a["tipo"], a["nivel"]) for a in alertas] == [("SOAP", VENCIDO), ("REVISION_TECNICA", POR_VENCER)]
    assert alertas == preparar_alertas_vencimiento(dos["raiz"], empresa=NORTE, hoy=HOY, carpeta_catalogos=dos[NORTE])
    assert _almacen(dos).read_bytes() == antes and {p for p in dos["raiz"].rglob("*")} == archivos


def test_alerta_cambia_de_identidad_al_cambiar_de_nivel(dos):
    _veh(dos, fecha_vencimiento="2026-11-20")
    antes = preparar_alertas_vencimiento(dos["raiz"], empresa=NORTE, hoy=HOY, carpeta_catalogos=dos[NORTE])[0]
    vencida = preparar_alertas_vencimiento(dos["raiz"], empresa=NORTE, hoy=date(2026, 12, 1), carpeta_catalogos=dos[NORTE])[0]
    assert antes["alerta_id"] != vencida["alerta_id"]


# ------------------------------------------------------------- actualización y trazabilidad


def test_actualizacion_conserva_antes_despues_y_original(dos):
    documento = _veh(dos, contenido=PDF, mime_type="application/pdf", fecha_emision="2026-01-01")
    corregido = actualizar_documento(dos["raiz"], empresa=NORTE, documento_id=documento["documento_id"], actor="OPE",
                                     motivo="error de digitación", fecha_vencimiento="2027-04-30", reloj=RELOJ)
    assert corregido["fecha_vencimiento"] == "2027-04-30" and corregido["fecha_emision"] == "2026-01-01"
    assert (corregido["archivo"], corregido["sha256"]) == (documento["archivo"], documento["sha256"])
    evento = _consulta(dos)["trazabilidad"][-1]
    assert (evento["operacion"], evento["actor"], evento["motivo"]) == ("DOCUMENTO_ACTUALIZADO", "OPE", "error de digitación")
    assert evento["cambios"] == {"fecha_vencimiento": {"antes": "2027-03-31", "despues": "2027-04-30"}}


def test_actualizar_sin_cambios_no_escribe(dos):
    documento = _veh(dos)
    antes = _almacen(dos).read_bytes()
    actualizar_documento(dos["raiz"], empresa=NORTE, documento_id=documento["documento_id"], actor="OPE", motivo="x",
                         fecha_vencimiento="2027-03-31", reloj=RELOJ)
    assert _almacen(dos).read_bytes() == antes


def test_reemplazo_conserva_historico_y_original(dos):
    primero = _veh(dos, contenido=PDF, mime_type="application/pdf")
    segundo = _veh(dos, contenido=PNG, mime_type="image/png", fecha_vencimiento="2028-03-31")
    consulta = _consulta(dos)
    assert [d["documento_id"] for d in consulta["documentos"]] == [segundo["documento_id"]]
    historico = consulta["historico"][0]
    assert (historico["documento_id"], historico["estado"], historico["reemplazado_por"]) == (
        primero["documento_id"], REEMPLAZADO, segundo["documento_id"])
    carpeta = _almacen(dos).parent
    assert (carpeta / primero["archivo"]).read_bytes() == PDF and (carpeta / segundo["archivo"]).read_bytes() == PNG
    assert consulta["trazabilidad"][-1]["reemplaza"] == [primero["documento_id"]]


def test_anular_conserva_registro_y_original_y_reabre_ausencia(dos):
    documento = _veh(dos, contenido=PDF, mime_type="application/pdf")
    anular_documento(dos["raiz"], empresa=NORTE, documento_id=documento["documento_id"], actor="OPE", motivo="otro vehículo",
                     reloj=RELOJ)
    consulta = _consulta(dos)
    assert consulta["documentos"] == [] and "SOAP" in {a["tipo"] for a in consulta["ausentes"]}
    assert consulta["historico"][0]["estado"] == ANULADO
    assert (_almacen(dos).parent / documento["archivo"]).read_bytes() == PDF
    assert verificar_originales(dos["raiz"], empresa=NORTE)[0]["estado"] == INTEGRO


@pytest.mark.parametrize("operacion", ["actualizar", "anular"])
def test_no_activo_no_se_modifica(dos, operacion):
    primero = _veh(dos)
    _veh(dos)
    antes = _almacen(dos).read_bytes()
    with pytest.raises(ErrorExpedienteDigital, match="REEMPLAZADO"):
        if operacion == "actualizar":
            actualizar_documento(dos["raiz"], empresa=NORTE, documento_id=primero["documento_id"], actor="OPE", motivo="x",
                                 fecha_vencimiento="2030-01-01", reloj=RELOJ)
        else:
            anular_documento(dos["raiz"], empresa=NORTE, documento_id=primero["documento_id"], actor="OPE", motivo="x", reloj=RELOJ)
    assert _almacen(dos).read_bytes() == antes


@pytest.mark.parametrize("extra, mensaje", [
    ({"motivo": ""}, "motivo"), ({"motivo": "m", "actor": ""}, "actor"), ({"motivo": "m", "fecha_vencimiento": ""}, "AAAA-MM-DD"),
    ({"motivo": "m", "fecha_vencimiento": "2027-13-01"}, "AAAA-MM-DD"),
    ({"motivo": "m", "fecha_emision": "2027-04-01"}, "futura|posterior"),
])
def test_actualizacion_invalida_no_escribe(dos, extra, mensaje):
    documento = _veh(dos)
    antes = _almacen(dos).read_bytes()
    with pytest.raises(ErrorExpedienteDigital, match=mensaje):
        actualizar_documento(dos["raiz"], empresa=NORTE, documento_id=documento["documento_id"],
                             **{"actor": "OPE", "reloj": RELOJ, **extra})
    assert _almacen(dos).read_bytes() == antes


# ------------------------------------------------------------- fechas inválidas y ausentes


@pytest.mark.parametrize("extra, mensaje", [
    ({"fecha_vencimiento": ""}, "vencimiento debe ser AAAA-MM-DD"),
    ({"fecha_vencimiento": "31-03-2027"}, "vencimiento debe ser AAAA-MM-DD"),
    ({"fecha_vencimiento": "2027-02-30"}, "vencimiento debe ser AAAA-MM-DD"),
    ({"fecha_emision": "2026/01/01"}, "emisión debe ser AAAA-MM-DD"),
    ({"fecha_emision": "2026-02-31"}, "emisión debe ser AAAA-MM-DD"),
    ({"fecha_emision": "2026-11-10"}, "futura"),
    ({"fecha_emision": "2026-11-01", "fecha_vencimiento": "2026-10-01"}, "posterior"),
])
def test_fechas_invalidas_no_escriben(dos, extra, mensaje):
    with pytest.raises(ErrorExpedienteDigital, match=mensaje):
        _veh(dos, **extra)
    assert not _almacen(dos).exists()


def test_emision_de_hoy_es_valida(dos):
    assert _veh(dos, fecha_emision="2026-11-09")["fecha_emision"] == "2026-11-09"


def test_ausentes_por_identidad_activa(dos):
    _catalogos(dos[NORTE], "ANA", vehiculos=(PATENTE, "ZZ1234"))
    _veh(dos, tipo="SOAP")
    _chofer(dos)
    ausentes = {(a["referencia_catalogo"], a["tipo"]) for a in documentos_ausentes(
        dos["raiz"], empresa=NORTE, carpeta_catalogos=dos[NORTE])}
    assert ausentes == {(PATENTE, "REVISION_TECNICA"), (PATENTE, "PERMISO_CIRCULACION"), ("ZZ1234", "SOAP"),
                        ("ZZ1234", "REVISION_TECNICA"), ("ZZ1234", "PERMISO_CIRCULACION")} | {(p, t) for p in (PATENTE, "ZZ1234") for t in ("CERTIFICADO_EMISION_GASES", "POLIZA_RESPONSABILIDAD_CIVIL")}


def test_ausentes_ignora_identidades_inactivas(dos):
    catalogo = dos[NORTE] / "choferes.json"
    catalogo.write_text(json.dumps({CLAVE: {"nombre": "A", "rut": RUT, "aliases": [], "activo": False}}), encoding="utf-8")
    assert all(a["entidad"] != "CHOFER" for a in documentos_ausentes(dos["raiz"], empresa=NORTE, carpeta_catalogos=dos[NORTE]))


def test_ausentes_sin_catalogo_es_error_no_lista_vacia(dos, tmp_path):
    with pytest.raises(ErrorExpedienteDigital, match="no disponible"):
        documentos_ausentes(dos["raiz"], empresa=NORTE, carpeta_catalogos=tmp_path / "no_existe")
    (dos[NORTE] / "choferes.json").unlink()  # el de vehículos sigue disponible
    with pytest.raises(ErrorExpedienteDigital, match="choferes no disponible"):
        documentos_ausentes(dos["raiz"], empresa=NORTE, carpeta_catalogos=dos[NORTE])


# ------------------------------------------------------------- tipos configurables


def test_tipo_configurable_obligatorio_y_sin_vencimiento(dos):
    configurar_tipo_documento(dos["raiz"], empresa=NORTE, entidad="CHOFER", tipo="certificado_antecedentes",
                              nombre="Certificado de antecedentes", requiere_vencimiento=False, obligatorio=True,
                              actor="ADM", reloj=RELOJ)
    assert "CERTIFICADO_ANTECEDENTES" in {a["tipo"] for a in _consulta(dos, entidad="CHOFER", referencia=RUT)["ausentes"]}
    _chofer(dos, tipo="CERTIFICADO_ANTECEDENTES", fecha_vencimiento="")
    consulta = _consulta(dos, entidad="CHOFER", referencia=RUT)
    assert "CERTIFICADO_ANTECEDENTES" not in {a["tipo"] for a in consulta["ausentes"]}
    assert [d["estado_vencimiento"] for d in consulta["documentos"]] == [SIN_VENCIMIENTO]


def test_tipo_de_una_empresa_no_existe_en_otra(dos):
    configurar_tipo_documento(dos["raiz"], empresa=NORTE, entidad="VEHICULO", tipo="GPS", nombre="GPS", actor="ADM", reloj=RELOJ)
    assert _veh(dos, tipo="GPS")["tipo"] == "GPS"
    with pytest.raises(ErrorExpedienteDigital, match="no admitido"):
        _veh(dos, empresa=SUR, tipo="GPS")


def test_tipo_desactivado_conserva_documentos_y_no_admite_nuevos(dos):
    def configurar(activo):
        configurar_tipo_documento(dos["raiz"], empresa=NORTE, entidad="VEHICULO", tipo="GPS", nombre="GPS", obligatorio=True,
                                  activo=activo, actor="ADM", reloj=RELOJ)
    configurar(True)
    documento = _veh(dos, tipo="GPS")
    configurar(False)
    with pytest.raises(ErrorExpedienteDigital, match="no admitido"):
        _veh(dos, tipo="GPS")
    consulta = _consulta(dos)
    assert [d["documento_id"] for d in consulta["documentos"]] == [documento["documento_id"]]
    assert "GPS" not in {a["tipo"] for a in consulta["ausentes"]}


@pytest.mark.parametrize("extra, mensaje", [
    ({"tipo": "SOAP"}, "no configurable"), ({"tipo": "con espacio"}, "no configurable"), ({"nombre": " "}, "nombre"),
    ({"entidad": "OTRA"}, "no admitida"), ({"actor": ""}, "actor"),
])
def test_configuracion_invalida_no_escribe(dos, extra, mensaje):
    datos = {"empresa": NORTE, "entidad": "VEHICULO", "tipo": "GPS", "nombre": "GPS", "actor": "ADM", "reloj": RELOJ, **extra}
    with pytest.raises(ErrorExpedienteDigital, match=mensaje):
        configurar_tipo_documento(dos["raiz"], **datos)
    assert not _almacen(dos).exists()


def test_entidad_de_tipo_configurado_no_cambia(dos):
    configurar_tipo_documento(dos["raiz"], empresa=NORTE, entidad="VEHICULO", tipo="GPS", nombre="GPS", actor="ADM", reloj=RELOJ)
    with pytest.raises(ErrorExpedienteDigital, match="no cambia"):
        configurar_tipo_documento(dos["raiz"], empresa=NORTE, entidad="CHOFER", tipo="GPS", nombre="GPS", actor="ADM", reloj=RELOJ)


# ------------------------------------------------------------- originales


def test_original_se_custodia_con_huella(dos):
    documento = _veh(dos, contenido=PDF, mime_type="application/pdf")
    assert documento["sha256"] == _sha(PDF) and documento["archivo"].startswith(
        f"archivos/expediente/{documento['expediente_id']}/")
    assert (_almacen(dos).parent / documento["archivo"]).read_bytes() == PDF
    assert verificar_originales(dos["raiz"], empresa=NORTE)[0]["estado"] == INTEGRO


def test_mismo_contenido_dos_veces_no_comparte_archivo(dos):
    uno, dos_doc = _veh(dos, contenido=PDF, mime_type="application/pdf"), _veh(dos, contenido=PDF, mime_type="application/pdf")
    assert uno["archivo"] != dos_doc["archivo"]
    assert all(v["estado"] == INTEGRO for v in verificar_originales(dos["raiz"], empresa=NORTE))


@pytest.mark.parametrize("extra, mensaje", [
    ({"contenido": b"no es pdf", "mime_type": "application/pdf"}, "no corresponde"),
    ({"contenido": PDF, "mime_type": "text/plain"}, "no corresponde"),
    ({"contenido": PDF, "mime_type": "application/pdf", "sha256": "0" * 64}, "huella"),
    ({"contenido": PDF, "mime_type": "application/pdf", "archivo": "archivos/x.pdf"}, "no ambos"),
])
def test_original_invalido_no_deja_rastro(dos, extra, mensaje):
    with pytest.raises(ErrorExpedienteDigital, match=mensaje):
        _veh(dos, **extra)
    assert not _almacen(dos).exists()
    assert not list(dos["raiz"].rglob("*.pdf"))


def test_fallo_al_publicar_retira_el_original_nuevo_y_conserva_el_anterior(dos, monkeypatch):
    previo = _veh(dos, contenido=PDF, mime_type="application/pdf")
    antes = _almacen(dos).read_bytes()

    def falla(*_a, **_k):
        raise OSError("disco lleno")
    monkeypatch.setattr("atlas_core.expediente_digital.escribir_json_atomico", falla)
    with pytest.raises(OSError):
        _veh(dos, contenido=PNG, mime_type="image/png")
    monkeypatch.undo()
    assert _almacen(dos).read_bytes() == antes
    assert not list(dos["raiz"].rglob("*.png"))
    assert (_almacen(dos).parent / previo["archivo"]).read_bytes() == PDF


def test_verificacion_detecta_alterado_ausente_y_sin_huella(dos):
    alterado = _veh(dos, tipo="SOAP", contenido=PDF, mime_type="application/pdf")
    ausente = _veh(dos, tipo="REVISION_TECNICA", contenido=PDF, mime_type="application/pdf")
    carpeta = _almacen(dos).parent
    (carpeta / "archivos" / "ref.pdf").write_bytes(PDF)
    sin_huella = _veh(dos, tipo="PERMISO_CIRCULACION", archivo="archivos/ref.pdf")
    (carpeta / alterado["archivo"]).write_bytes(PDF + b"x")
    (carpeta / ausente["archivo"]).unlink()
    estados = {v["documento_id"]: v["estado"] for v in verificar_originales(dos["raiz"], empresa=NORTE)}
    assert estados == {alterado["documento_id"]: ALTERADO, ausente["documento_id"]: ARCHIVO_AUSENTE,
                       sin_huella["documento_id"]: SIN_HUELLA}


# ------------------------------------------------------------- aislamiento entre empresas


def test_mismos_identificadores_expedientes_separados(dos):
    norte_chofer, sur_chofer = _chofer(dos, NORTE), _chofer(dos, SUR, fecha_vencimiento="2026-01-01")
    norte_veh, sur_veh = _veh(dos, NORTE), _veh(dos, SUR, fecha_vencimiento="2026-11-20")
    assert norte_chofer["expediente_id"] != sur_chofer["expediente_id"]
    assert norte_veh["expediente_id"] != sur_veh["expediente_id"]
    assert (norte_chofer["referencia_catalogo"], sur_chofer["referencia_catalogo"]) == (CLAVE, CLAVE)
    assert [d["documento_id"] for d in _consulta(dos, NORTE)["documentos"]] == [norte_veh["documento_id"]]
    assert [d["documento_id"] for d in _consulta(dos, SUR)["documentos"]] == [sur_veh["documento_id"]]
    assert _consulta(dos, NORTE, "CHOFER", RUT)["documentos"][0]["estado_vencimiento"] == VIGENTE
    assert _consulta(dos, SUR, "CHOFER", RUT)["documentos"][0]["estado_vencimiento"] == VENCIDO


def test_alta_en_una_empresa_no_cubre_ausentes_de_la_otra(dos):
    _veh(dos, NORTE, tipo="SOAP")
    assert "SOAP" not in {a["tipo"] for a in _consulta(dos, NORTE)["ausentes"]}
    assert "SOAP" in {a["tipo"] for a in _consulta(dos, SUR)["ausentes"]}


@pytest.mark.parametrize("operacion", ["actualizar", "anular"])
def test_documento_de_otra_empresa_es_inexistente(dos, operacion):
    documento = _veh(dos, SUR)
    _veh(dos, NORTE)
    antes = _almacen(dos, SUR).read_bytes()
    with pytest.raises(ErrorExpedienteDigital, match="no existe en esta empresa"):
        if operacion == "actualizar":
            actualizar_documento(dos["raiz"], empresa=NORTE, documento_id=documento["documento_id"], actor="OPE", motivo="x",
                                 fecha_vencimiento="2030-01-01", reloj=RELOJ)
        else:
            anular_documento(dos["raiz"], empresa=NORTE, documento_id=documento["documento_id"], actor="OPE", motivo="x", reloj=RELOJ)
    assert _almacen(dos, SUR).read_bytes() == antes


def test_identidad_solo_en_el_catalogo_de_otra_empresa_se_rechaza(dos):
    _catalogos(dos[SUR], "ANA SUR", vehiculos=("SUR999",))
    with pytest.raises(ErrorExpedienteDigital, match="no existe"):
        _veh(dos, NORTE, referencia="SUR999")
    assert not _almacen(dos, NORTE).exists()


def test_originales_quedan_bajo_su_empresa(dos):
    norte, sur = _veh(dos, NORTE, contenido=PDF, mime_type="application/pdf"), _veh(dos, SUR, contenido=PNG, mime_type="image/png")
    base = dos["raiz"] / "fichas_digitales"
    assert (base / NORTE / norte["archivo"]).read_bytes() == PDF and (base / SUR / sur["archivo"]).read_bytes() == PNG
    assert not (base / SUR / norte["archivo"]).exists() and not (base / NORTE / sur["archivo"]).exists()
    assert [v["estado"] for v in verificar_originales(dos["raiz"], empresa=SUR)] == [INTEGRO]


def test_fichas_de_una_empresa_no_aparecen_en_otra(dos):
    _ficha(dos["raiz"], SUR, vehiculos=[{"patente": PATENTE, "historial": [], "documentos": [
        {"documento_id": "sur-soap", "tipo": "SOAP", "vencimiento": "2027-01-01", "archivo": "archivos/v/s.pdf"}]}])
    assert _consulta(dos, NORTE)["documentos"] == []
    assert [d["documento_id"] for d in _consulta(dos, SUR)["documentos"]] == ["sur-soap"]


def test_raices_separadas_por_empresa(tmp_path):
    base = {"raiz": tmp_path / "A"}
    otra = {"raiz": tmp_path / "B"}
    for entorno_, empresa, nombre in ((base, NORTE, "A"), (otra, SUR, "B")):
        entorno_[empresa] = _catalogos(entorno_["raiz"] / "catalogos_privados", nombre)
    uno = registrar_documento(base["raiz"], empresa=NORTE, entidad="VEHICULO", referencia=PATENTE, tipo="SOAP",
                              fecha_vencimiento="2027-01-01", actor="T", reloj=RELOJ)
    assert leer_expediente(otra["raiz"], empresa=SUR)["documentos"] == []
    assert leer_expediente(base["raiz"], empresa=NORTE)["documentos"][0]["documento_id"] == uno["documento_id"]


def test_almacen_de_otra_empresa_copiado_se_rechaza(dos):
    _veh(dos, NORTE)
    destino = _almacen(dos, SUR)
    destino.parent.mkdir(parents=True)
    destino.write_bytes(_almacen(dos, NORTE).read_bytes())
    with pytest.raises(ErrorExpedienteDigital, match="incompatible"):
        _consulta(dos, SUR)


# ------------------------------------------------------------- documentos de fichas (sólo lectura)


def test_pendiente_de_extraccion_no_es_vigente_ni_cubre_obligatorio(dos):
    ruta = _ficha(dos["raiz"], NORTE, choferes=[_ficha_chofer([CLAVE], [
        {"documento_id": "p1", "tipo": "LICENCIA_CONDUCIR", "estado_revision": "PENDIENTE_EXTRACCION", "archivo": "archivos/c/p.png"}])])
    antes = ruta.read_bytes()
    consulta = _consulta(dos, entidad="CHOFER", referencia=RUT)
    assert [d["estado_vencimiento"] for d in consulta["documentos"]] == [PENDIENTE_REVISION]
    assert consulta["ausentes"] == [{"tipo": "LICENCIA_CONDUCIR", "nombre": "Licencia de conducir", "pendiente_revision": True}]
    assert preparar_alertas_vencimiento(dos["raiz"], empresa=NORTE, hoy=HOY, carpeta_catalogos=dos[NORTE]) == []
    assert ruta.read_bytes() == antes


def test_fecha_invalida_en_ficha_se_informa_sin_romper_la_vista(dos):
    _ficha(dos["raiz"], NORTE, vehiculos=[{"patente": PATENTE, "historial": [], "documentos": [
        {"documento_id": "mala", "tipo": "SOAP", "vencimiento": "31/12/2026", "archivo": "archivos/v/m.pdf"}]}])
    documento = _consulta(dos)["documentos"][0]
    assert (documento["estado_vencimiento"], documento["dias_para_vencer"]) == (FECHA_INVALIDA, None)
    assert [a["nivel"] for a in preparar_alertas_vencimiento(dos["raiz"], empresa=NORTE, hoy=HOY, carpeta_catalogos=dos[NORTE])] == [FECHA_INVALIDA]


def test_ficha_vehiculo_usa_el_vencimiento_mas_lejano_y_marca_ocr(dos):
    _ficha(dos["raiz"], NORTE, vehiculos=[{"patente": PATENTE, "historial": [], "documentos": [
        {"documento_id": "viejo", "tipo": "SOAP", "vencimiento": "2026-01-01", "archivo": "archivos/v/1.pdf"},
        {"documento_id": "nuevo", "tipo": "SOAP", "vencimiento": "2027-01-01", "archivo": "archivos/v/2.pdf",
         "estado_revision": "VENCIMIENTO_OCR_AUTOMATICO"}]}])
    documentos = _consulta(dos)["documentos"]
    assert [(d["documento_id"], d["confirmado_por_humano"]) for d in documentos] == [("nuevo", False)]


def test_ficha_ilegible_es_error_no_ausencia(dos):
    ruta = _ficha(dos["raiz"], NORTE)
    ruta.write_text("{no json", encoding="utf-8")
    with pytest.raises(ErrorExpedienteDigital, match="fichas ilegibles"):
        estado_expediente(dos["raiz"], empresa=NORTE, hoy=HOY, carpeta_catalogos=dos[NORTE])


def test_licencia_de_clave_vinculada_no_se_cuenta_dos_veces(dos):
    _chofer(dos, fecha_vencimiento="2030-01-01")
    (dos[NORTE] / "choferes.json").write_text(json.dumps({
        "NUEVA1": {"nombre": "A", "rut": RUT, "aliases": [], "activo": True}}), encoding="utf-8")
    _ficha(dos["raiz"], NORTE, choferes=[_ficha_chofer([CLAVE, "NUEVA1"], [
        {"documento_id": "f1", "tipo": "LICENCIA_CONDUCIR", "vencimiento": "2027-01-01", "archivo": "archivos/c/f.pdf"}])])
    consulta = _consulta(dos, entidad="CHOFER", referencia="NUEVA1")
    assert [(d["fuente"], d["fecha_vencimiento"]) for d in consulta["documentos"]] == [("EXPEDIENTE", "2030-01-01")]
    assert consulta["expediente_id"]


def test_licencia_de_ficha_cubierta_por_expediente_creado_con_la_clave_nueva(dos):
    (dos[NORTE] / "choferes.json").write_text(json.dumps({
        "NUEVA1": {"nombre": "A", "rut": RUT, "aliases": [], "activo": True}}), encoding="utf-8")
    ficha = _ficha_chofer([CLAVE, "NUEVA1"], [
        {"documento_id": "f1", "tipo": "LICENCIA_CONDUCIR", "vencimiento": "2027-01-01", "archivo": "archivos/c/f.pdf"}])
    _ficha(dos["raiz"], NORTE, choferes=[ficha])
    _chofer(dos, referencia="NUEVA1", fecha_vencimiento="2030-01-01")
    documentos = estado_expediente(dos["raiz"], empresa=NORTE, hoy=HOY, carpeta_catalogos=dos[NORTE])
    assert [d["fuente"] for d in documentos] == ["EXPEDIENTE"]


def test_almacen_v1_se_lee_y_se_conserva_al_escribir(dos):
    ruta = _almacen(dos)
    ruta.parent.mkdir(parents=True)
    ruta.write_text(json.dumps({"version": 1, "empresa": NORTE, "revision": 1, "documentos": [{
        "documento_id": "d1", "entidad": "VEHICULO", "referencia_catalogo": PATENTE, "tipo": "SOAP",
        "fecha_vencimiento": "2027-01-01", "archivo": "", "sha256": "", "registrado_en": "2026-01-01T00:00:00+00:00",
        "actor": "T", "reemplazado_por": ""}]}), encoding="utf-8")
    assert _consulta(dos)["documentos"][0]["documento_id"] == "d1"
    nuevo = _veh(dos)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos["version"] == 2 and len(datos["expedientes"]) == 1
    previo = next(d for d in datos["documentos"] if d["documento_id"] == "d1")
    assert (previo["estado"], previo["reemplazado_por"]) == (REEMPLAZADO, nuevo["documento_id"])
