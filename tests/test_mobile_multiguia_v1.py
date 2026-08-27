"""Bloque MOBILE MULTIGUÍA V1 -- una tanda Mobile (varias fotos
enviadas juntas) nunca equivale a un viaje. Cada documento se persiste
individualmente (servidor real, `crear_servidor`) y Atlas agrupa por
`numero_transporte` con el MISMO mecanismo ya existente
(`atlas_core.gestor_viajes.agrupar_viajes`) -- nunca una ruta de
consolidación paralela para Mobile, nunca por cercanía/`lote_id` dentro
de la tanda."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

from atlas_core.gestor_viajes import MotivoRevision, agrupar_viajes
from atlas_core.mobile import AutenticadorMobile, hash_password
from servidor_mobile import crear_servidor


def _auth() -> AutenticadorMobile:
    return AutenticadorMobile(
        {"javier": {"chofer_id": "chofer-1", "password_hash": hash_password("secreto")}},
        "secreto-de-prueba-multiguia-123456",
    )


def _multipart(campos: dict[str, str], imagen: bytes, mime: str = "image/jpeg") -> tuple[bytes, str]:
    boundary = "atlas-test-boundary"
    partes = []
    for nombre, valor in campos.items():
        partes.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{nombre}\"\r\n\r\n{valor}\r\n".encode())
    partes.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"imagen\"; filename=\"foto.jpg\"\r\nContent-Type: {mime}\r\n\r\n".encode()
        + imagen + b"\r\n"
    )
    partes.append(f"--{boundary}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={boundary}"


def _token(servidor) -> str:
    login = urllib.request.Request(
        f"http://127.0.0.1:{servidor.server_port}/api/mobile/login",
        data=json.dumps({"usuario": "javier", "password": "secreto"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    return json.load(urllib.request.urlopen(login))["token"]


def _subir(servidor, token, campos, imagen=b"contenido-jpeg-simulado"):
    cuerpo, tipo = _multipart(campos, imagen)
    solicitud = urllib.request.Request(
        f"http://127.0.0.1:{servidor.server_port}/api/mobile/envios",
        data=cuerpo, headers={"Content-Type": tipo, "Authorization": f"Bearer {token}"}, method="POST",
    )
    return json.load(urllib.request.urlopen(solicitud))


def _campos_base(envio_id, **overrides):
    base = {
        "envio_id": envio_id, "schema_version": "1", "capturado_en": "2026-08-27T18:00:00Z",
        "planta_origen_informada": "AZA_COLINA",
    }
    base.update(overrides)
    return base


# ============================================================
# Servidor real -- persistencia individual, idempotencia, lote_id
# ============================================================

def test_tanda_de_tres_fotos_persiste_tres_documentos_independientes(tmp_path: Path) -> None:
    """Sección 1/5 del ticket: una tanda con 3 fotos produce 3 envíos
    con identidad propia -- nunca un blob único ni una fusión previa."""
    servidor = crear_servidor("127.0.0.1", 0, raiz=tmp_path, autenticador=_auth(), procesar=False)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True); hilo.start()
    try:
        token = _token(servidor)
        lote_id = str(uuid.uuid4())
        ids = [str(uuid.uuid4()) for _ in range(3)]
        for envio_id in ids:
            respuesta = _subir(servidor, token, _campos_base(envio_id, lote_id=lote_id))
            assert respuesta["resultado"] == "ACEPTADO"
            assert not respuesta["duplicado"]
        for envio_id in ids:
            registro = json.loads((tmp_path / "operacion" / "mobile" / "envios" / envio_id / "envio.json").read_text())
            assert registro["lote_id"] == lote_id
            assert (tmp_path / "operacion" / "mobile" / "envios" / envio_id / "original.jpg").is_file()
        assert len(set(ids)) == 3  # tres identidades reales, nunca colapsadas
    finally:
        servidor.shutdown(); servidor.server_close()


def test_reintento_del_mismo_documento_es_idempotente(tmp_path: Path) -> None:
    """Sección 4 -- doble tap/mala red/reintento nunca duplica: mismo
    envio_id, misma foto, se reconoce como el mismo documento."""
    servidor = crear_servidor("127.0.0.1", 0, raiz=tmp_path, autenticador=_auth(), procesar=False)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True); hilo.start()
    try:
        token = _token(servidor)
        envio_id = str(uuid.uuid4())
        primera = _subir(servidor, token, _campos_base(envio_id))
        segunda = _subir(servidor, token, _campos_base(envio_id))
        assert primera["duplicado"] is False
        assert segunda["duplicado"] is True
        assert primera["envio_id"] == segunda["envio_id"]
    finally:
        servidor.shutdown(); servidor.server_close()


def test_tanda_parcialmente_enviada_puede_continuar_con_las_fotos_faltantes(tmp_path: Path) -> None:
    """Sección 4 -- cada documento reintenta con su propia identidad
    estable: subir sólo 2 de 3 fotos de una tanda, y luego la 3ra, deja
    los 3 documentos persistidos sin ningún efecto cruzado entre ellos."""
    servidor = crear_servidor("127.0.0.1", 0, raiz=tmp_path, autenticador=_auth(), procesar=False)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True); hilo.start()
    try:
        token = _token(servidor)
        lote_id = str(uuid.uuid4())
        ids = [str(uuid.uuid4()) for _ in range(3)]
        for envio_id in ids[:2]:
            _subir(servidor, token, _campos_base(envio_id, lote_id=lote_id))
        # "reconexión" -- llega la tercera foto de la misma tanda más tarde.
        respuesta = _subir(servidor, token, _campos_base(ids[2], lote_id=lote_id))
        assert respuesta["resultado"] == "ACEPTADO"
        for envio_id in ids:
            assert (tmp_path / "operacion" / "mobile" / "envios" / envio_id / "envio.json").is_file()
    finally:
        servidor.shutdown(); servidor.server_close()


def test_lote_id_es_opcional_compatibilidad_hacia_atras(tmp_path: Path) -> None:
    """Sección 16 -- un envío Mobile V1 histórico (una sola foto, sin
    lote_id) sigue funcionando exactamente igual."""
    servidor = crear_servidor("127.0.0.1", 0, raiz=tmp_path, autenticador=_auth(), procesar=False)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True); hilo.start()
    try:
        token = _token(servidor)
        envio_id = str(uuid.uuid4())
        respuesta = _subir(servidor, token, _campos_base(envio_id))  # sin lote_id
        assert respuesta["resultado"] == "ACEPTADO"
        registro = json.loads((tmp_path / "operacion" / "mobile" / "envios" / envio_id / "envio.json").read_text())
        assert registro["lote_id"] == ""
    finally:
        servidor.shutdown(); servidor.server_close()


# ============================================================
# Agrupación por transporte -- MISMO mecanismo ya existente, nunca por
# tanda (Sección 6/7/11/21 del ticket -- caso contrario obligatorio)
# ============================================================

def _fila(**overrides):
    base = {
        "archivo": "doc.jpg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "T1", "fecha": "27-08-2026", "chofer": "CHOFER PRUEBA",
        "cliente": "CLIENTE PRUEBA", "obra_destino": "OBRA PRUEBA",
        "patente_tracto": "AB1234", "patente_rampla": "",
        "descripcion_material": "MATERIAL", "tipo_carga": "OTRO",
        "planta_origen_id": "", "planta_origen_nombre": "", "origen_determinado_por": "", "evidencia_origen": "",
    }
    base.update(overrides)
    return base


def test_caso_contrario_obligatorio_tres_documentos_dos_transportes_dos_viajes():
    """Sección 11/21 -- fixture exacta del ticket: tanda T1 con 3
    documentos (A/B mismo transporte X, C transporte Y distinto) debe
    producir 2 viajes finales, nunca fusionar los 3."""
    filas = [
        _fila(archivo="A.jpg", numero_guia="A", numero_transporte="0000000001"),
        _fila(archivo="B.jpg", numero_guia="B", numero_transporte="0000000001"),
        _fila(archivo="C.jpg", numero_guia="C", numero_transporte="0000000002"),
    ]
    viajes, sin_transporte = agrupar_viajes(filas)
    assert sin_transporte == []
    assert len(viajes) == 2
    por_transporte = {v.numero_transporte: v for v in viajes}
    assert {"0000000001", "0000000002"} == set(por_transporte)
    assert sorted(d.numero_guia for d in por_transporte["0000000001"].documentos) == ["A", "B"]
    assert [d.numero_guia for d in por_transporte["0000000002"].documentos] == ["C"]


def test_documento_sin_transporte_no_se_agrupa_por_pertenecer_a_la_misma_tanda():
    """Sección 7/21, segundo E2E: un documento D sin transporte (OCR
    dudoso/ausente) NUNCA se fusiona con otros documentos de la MISMA
    tanda sólo por cercanía -- queda aparte, para revisión."""
    filas = [
        _fila(archivo="A.jpg", numero_guia="A", numero_transporte="0000000001"),
        _fila(archivo="D.jpg", numero_guia="D", numero_transporte=""),  # transporte ausente
    ]
    viajes, sin_transporte = agrupar_viajes(filas)
    assert len(viajes) == 1
    assert viajes[0].numero_transporte == "0000000001"
    assert [d.numero_guia for d in viajes[0].documentos] == ["A"]
    assert len(sin_transporte) == 1
    assert sin_transporte[0]["numero_guia"] == "D"


def test_transporte_ocr_dudoso_no_encontrado_tampoco_se_agrupa():
    filas = [
        _fila(archivo="A.jpg", numero_guia="A", numero_transporte="0000000001"),
        _fila(archivo="D.jpg", numero_guia="D", numero_transporte="No encontrado"),
    ]
    viajes, sin_transporte = agrupar_viajes(filas)
    assert len(viajes) == 1
    assert len(sin_transporte) == 1


def test_lote_id_presente_en_la_fila_nunca_influye_en_la_agrupacion():
    """Prueba estructural: aunque una fila trajera `lote_id` (no ocurre
    hoy -- `lote_id` nunca llega a las columnas del dataset, ver
    servidor_mobile.py), `agrupar_viajes` lo ignora por completo -- sólo
    `numero_transporte` decide."""
    filas = [
        _fila(archivo="A.jpg", numero_guia="A", numero_transporte="0000000001", lote_id="tanda-1"),
        _fila(archivo="B.jpg", numero_guia="B", numero_transporte="0000000002", lote_id="tanda-1"),  # misma tanda, transporte distinto
    ]
    viajes, sin_transporte = agrupar_viajes(filas)
    assert len(viajes) == 2  # nunca se fusionan por compartir lote_id


# ============================================================
# Multiorigen (Sección 8 del ticket) -- un viaje puede tener guías con
# evidencia de origen distinta; Atlas conserva ambas, nunca elige a
# ciegas cuando el nivel de confianza es el mismo.
# ============================================================

def test_mismo_transporte_dos_documentos_dos_origenes_conserva_ambas_evidencias():
    """Guía A -> origen planta 1 (documento), Guía B -> origen planta 2
    (documento) -- mismo transporte. Ningún origen se descarta: ambos
    quedan legibles en sus propios documentos, y como discrepan al
    mismo nivel de confianza (DOCUMENTO), el viaje señala
    CONFLICTO_ORIGEN en vez de elegir una a ciegas (mismo mecanismo ya
    validado en Origen Operacional V2 -- Bloque ORIGEN DE VIAJE)."""
    filas = [
        _fila(
            archivo="A.jpg", numero_guia="A", numero_transporte="0000000001",
            planta_origen_id="planta-1", planta_origen_nombre="PLANTA 1",
            origen_determinado_por="DOCUMENTO", evidencia_origen="ENCABEZADO_GUIA",
        ),
        _fila(
            archivo="B.jpg", numero_guia="B", numero_transporte="0000000001",
            planta_origen_id="planta-2", planta_origen_nombre="PLANTA 2",
            origen_determinado_por="DOCUMENTO", evidencia_origen="ENCABEZADO_GUIA",
        ),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert len(viajes) == 1
    viaje = viajes[0]
    # Ambas evidencias siguen siendo legibles en sus propios documentos.
    origenes_por_guia = {d.numero_guia: d.planta_origen_nombre for d in viaje.documentos}
    assert origenes_por_guia == {"A": "PLANTA 1", "B": "PLANTA 2"}
    assert MotivoRevision.CONFLICTO_ORIGEN in viaje.motivos_revision


def test_mismo_transporte_origen_mobile_gana_sobre_documento_sin_conflicto():
    """Guía A con origen MOBILE (mayor jerarquía) y guía B con origen
    DOCUMENTO -- el viaje usa MOBILE (mayor confianza), sin marcar
    conflicto (mismo criterio ya vigente para GPS>DOCUMENTO)."""
    filas = [
        _fila(
            archivo="A.jpg", numero_guia="A", numero_transporte="0000000001",
            planta_origen_id="planta-1", planta_origen_nombre="PLANTA 1",
            origen_determinado_por="MOBILE", evidencia_origen="MOBILE_INFORMADO",
        ),
        _fila(
            archivo="B.jpg", numero_guia="B", numero_transporte="0000000001",
            planta_origen_id="planta-2", planta_origen_nombre="PLANTA 2",
            origen_determinado_por="DOCUMENTO", evidencia_origen="ENCABEZADO_GUIA",
        ),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert len(viajes) == 1
    assert MotivoRevision.CONFLICTO_ORIGEN not in viajes[0].motivos_revision


# ============================================================
# Universalidad (Sección 19) -- otro rubro, mismo mecanismo, sin
# código nuevo.
# ============================================================

def test_otro_rubro_alimentos_cuatro_comprobantes_dos_servicios():
    filas = [
        _fila(archivo="C1.jpg", numero_guia="C1", numero_transporte="0000000101", cliente="SUPERMERCADO LIDER"),
        _fila(archivo="C2.jpg", numero_guia="C2", numero_transporte="0000000101", cliente="SUPERMERCADO LIDER"),
        _fila(archivo="C3.jpg", numero_guia="C3", numero_transporte="0000000102", cliente="SUPERMERCADO TOTTUS"),
        _fila(archivo="C4.jpg", numero_guia="C4", numero_transporte="0000000102", cliente="SUPERMERCADO TOTTUS"),
    ]
    viajes, sin_transporte = agrupar_viajes(filas)
    assert sin_transporte == []
    assert len(viajes) == 2
    por_transporte = {v.numero_transporte: sorted(d.numero_guia for d in v.documentos) for v in viajes}
    assert por_transporte == {"0000000101": ["C1", "C2"], "0000000102": ["C3", "C4"]}
