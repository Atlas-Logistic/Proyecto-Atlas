import json
from unittest.mock import Mock

import pytest

from atlas_core import ocr_provider
from atlas_core.ocr import ALLOWLIST_FECHA, ALLOWLIST_TRANSPORTE, BloqueOCR
from atlas_core.ocr_provider import (
    EasyOCRProvider,
    PaddleOCRProvider,
    ProveedorOCR,
    ProveedorOCRNoDisponible,
    crear_proveedor_ocr,
)


# --- contrato EasyOCRProvider ---

def test_easyocr_provider_cumple_el_protocolo():
    assert isinstance(EasyOCRProvider(), ProveedorOCR)


def test_easyocr_provider_leer_texto_delega_en_funcion_existente(monkeypatch):
    mock_leer = Mock(return_value=["línea 1", "línea 2"])
    monkeypatch.setattr(ocr_provider, "leer_texto_imagen", mock_leer)
    lector = object()

    resultado = EasyOCRProvider(lector=lector).leer_texto("guia.jpg")

    assert resultado == ["línea 1", "línea 2"]
    mock_leer.assert_called_once_with("guia.jpg", lector=lector)


def test_easyocr_provider_leer_bloques_delega_en_funcion_existente(monkeypatch):
    bloque = BloqueOCR("FECHA", ((0, 0), (10, 0), (10, 10), (0, 10)), 0.9)
    mock_leer = Mock(return_value=[bloque])
    monkeypatch.setattr(ocr_provider, "leer_bloques_imagen", mock_leer)
    lector = object()

    resultado = EasyOCRProvider(lector=lector).leer_bloques("guia.jpg")

    assert resultado == [bloque]
    mock_leer.assert_called_once_with("guia.jpg", lector=lector)


def test_easyocr_provider_leer_focal_delega_en_helper_generico(monkeypatch):
    mock_focal = Mock(return_value={"recorte": (0, 0, 10, 10), "lecturas": []})
    monkeypatch.setattr(ocr_provider, "_leer_region_focal", mock_focal)
    lector = object()

    resultado = EasyOCRProvider(lector=lector).leer_focal("guia.jpg", (1, 2, 3, 4), ALLOWLIST_FECHA)

    assert resultado == {"recorte": (0, 0, 10, 10), "lecturas": []}
    mock_focal.assert_called_once_with("guia.jpg", (1, 2, 3, 4), lector=lector, allowlist=ALLOWLIST_FECHA)


def test_easyocr_provider_crea_lector_solo_una_vez(monkeypatch):
    crear = Mock(side_effect=lambda: object())
    monkeypatch.setattr(ocr_provider, "crear_lector_ocr", crear)
    monkeypatch.setattr(ocr_provider, "leer_texto_imagen", Mock(return_value=[]))

    proveedor = EasyOCRProvider()
    proveedor.leer_texto("a.jpg")
    proveedor.leer_texto("b.jpg")

    assert crear.call_count == 1


# --- contrato PaddleOCRProvider (proceso mockeado, sin instalar Paddle) ---

class _ProcesoFalso:
    """Simula un subprocess.Popen hablando el protocolo del worker."""

    def __init__(self, respuestas_init=None, respuestas=None, falla_al_iniciar=False):
        self.stdin = Mock()
        self._enviado = []
        self._respuestas = list(respuestas or [])
        self._respuesta_init = respuestas_init if respuestas_init is not None else json.dumps({"ok": True, "device": "cpu"}) + "\n"
        self._falla_al_iniciar = falla_al_iniciar
        self.stderr = Mock()
        self.stderr.read = Mock(return_value="")
        self._primera_lectura = True

    def poll(self):
        return None

    def _escribir(self, texto):
        self._enviado.append(texto)

    def _leer_linea(self):
        if self._primera_lectura:
            self._primera_lectura = False
            return "" if self._falla_al_iniciar else self._respuesta_init
        if not self._respuestas:
            return ""
        return self._respuestas.pop(0)

    def terminate(self):
        pass

    def kill(self):
        pass


def _preparar_proveedor_paddle(monkeypatch, respuestas=None, falla_al_iniciar=False):
    proveedor = PaddleOCRProvider(device="cpu")
    proceso = _ProcesoFalso(respuestas=respuestas, falla_al_iniciar=falla_al_iniciar)
    proceso.stdin.write = Mock(side_effect=proceso._escribir)
    proceso.stdin.flush = Mock()
    proceso.stdout = Mock()
    proceso.stdout.readline = Mock(side_effect=proceso._leer_linea)
    monkeypatch.setattr(ocr_provider.Path, "exists", lambda self: True)
    monkeypatch.setattr(ocr_provider.subprocess, "Popen", Mock(return_value=proceso))
    return proveedor, proceso


def test_paddleocr_provider_cumple_el_protocolo():
    assert isinstance(PaddleOCRProvider(device="cpu"), ProveedorOCR)


def test_paddleocr_provider_leer_texto_via_proceso_aislado(monkeypatch):
    respuesta = json.dumps({"ok": True, "resultado": "FECHA DE EMISION\n23-06-2025"}) + "\n"
    proveedor, proceso = _preparar_proveedor_paddle(monkeypatch, respuestas=[respuesta])

    resultado = proveedor.leer_texto("guia.jpg")

    assert resultado == ["FECHA DE EMISION", "23-06-2025"]
    assert any('"op": "texto"' in e for e in proceso._enviado)


def test_paddleocr_provider_leer_bloques_via_proceso_aislado(monkeypatch):
    crudos = [{"texto": "FECHA", "bbox": [[0, 0], [10, 0], [10, 10], [0, 10]], "confianza": 0.9}]
    respuesta = json.dumps({"ok": True, "resultado": crudos}) + "\n"
    proveedor, _ = _preparar_proveedor_paddle(monkeypatch, respuestas=[respuesta])

    resultado = proveedor.leer_bloques("guia.jpg")

    assert len(resultado) == 1
    assert resultado[0].texto == "FECHA"
    assert resultado[0].confianza == 0.9


def test_paddleocr_provider_leer_focal_via_proceso_aislado(monkeypatch):
    crudo = {"recorte": [0, 0, 10, 10], "lecturas": [{"variante": "original", "texto": "23-06-2025", "confianza": 0.9}]}
    respuesta = json.dumps({"ok": True, "resultado": crudo}) + "\n"
    proveedor, proceso = _preparar_proveedor_paddle(monkeypatch, respuestas=[respuesta])

    resultado = proveedor.leer_focal("guia.jpg", (1, 2, 3, 4), ALLOWLIST_TRANSPORTE)

    assert resultado == crudo
    assert any('"op": "focal"' in e for e in proceso._enviado)


def test_paddleocr_provider_error_de_imagen_no_mata_el_proceso(monkeypatch):
    respuesta = json.dumps({"ok": False, "error": "ValueError: recorte vacío"}) + "\n"
    proveedor, _ = _preparar_proveedor_paddle(monkeypatch, respuestas=[respuesta])

    with pytest.raises(RuntimeError, match="recorte vacío"):
        proveedor.leer_texto("guia.jpg")


def test_paddleocr_provider_no_disponible_si_worker_no_arranca(monkeypatch):
    proveedor, _ = _preparar_proveedor_paddle(monkeypatch, falla_al_iniciar=True)

    with pytest.raises(ProveedorOCRNoDisponible):
        proveedor.leer_texto("guia.jpg")


def test_paddleocr_provider_no_disponible_si_venv_no_existe(monkeypatch):
    monkeypatch.setattr(ocr_provider.Path, "exists", lambda self: False)
    proveedor = PaddleOCRProvider(device="cpu")

    with pytest.raises(ProveedorOCRNoDisponible):
        proveedor.leer_texto("guia.jpg")


# --- selección de proveedor y fallback ---

def test_crear_proveedor_ocr_easyocr_explicito_no_toca_paddle(monkeypatch):
    popen = Mock()
    monkeypatch.setattr(ocr_provider.subprocess, "Popen", popen)

    proveedor = crear_proveedor_ocr("easyocr")

    assert isinstance(proveedor, EasyOCRProvider)
    popen.assert_not_called()


def test_crear_proveedor_ocr_usa_paddle_cuando_esta_disponible(monkeypatch):
    monkeypatch.setattr(ocr_provider, "_gpu_nvidia_disponible", lambda: False)
    monkeypatch.setattr(ocr_provider.Path, "exists", lambda self: True)
    proceso = _ProcesoFalso()
    proceso.stdin.write = Mock(side_effect=proceso._escribir)
    proceso.stdin.flush = Mock()
    proceso.stdout = Mock()
    proceso.stdout.readline = Mock(side_effect=proceso._leer_linea)
    monkeypatch.setattr(ocr_provider.subprocess, "Popen", Mock(return_value=proceso))

    proveedor = crear_proveedor_ocr("paddleocr")

    assert isinstance(proveedor, PaddleOCRProvider)


def test_crear_proveedor_ocr_cae_a_easyocr_si_paddle_no_arranca(monkeypatch):
    monkeypatch.setattr(ocr_provider.Path, "exists", lambda self: False)

    proveedor = crear_proveedor_ocr("paddleocr")

    assert isinstance(proveedor, EasyOCRProvider)


def test_gpu_nvidia_disponible_sin_nvidia_smi_devuelve_false(monkeypatch):
    def _falla(*a, **k):
        raise FileNotFoundError("nvidia-smi no encontrado")

    monkeypatch.setattr(ocr_provider.subprocess, "run", _falla)

    assert ocr_provider._gpu_nvidia_disponible() is False
