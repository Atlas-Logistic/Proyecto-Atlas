import json
from pathlib import Path
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


RUTA_PYTHON_FALSA = Path("C:/runtime-falso-para-tests/Scripts/python.exe")


def _prohibir_bootstrap_real(monkeypatch):
    """Ningún test de este archivo debe disparar una instalación real: si algo
    llega a llamar asegurar_runtime_paddle() sin haberlo mockeado, que falle
    ruidosamente en vez de crear un venv de verdad."""
    def _explota(*a, **k):
        raise AssertionError("asegurar_runtime_paddle() no debe llamarse de verdad en tests")

    monkeypatch.setattr(ocr_provider, "asegurar_runtime_paddle", _explota)


def _preparar_proveedor_paddle(monkeypatch, respuestas=None, falla_al_iniciar=False):
    _prohibir_bootstrap_real(monkeypatch)
    proveedor = PaddleOCRProvider(device="cpu", ruta_python=RUTA_PYTHON_FALSA)
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


def test_paddleocr_provider_no_disponible_si_runtime_no_se_pudo_preparar(monkeypatch):
    monkeypatch.setattr(ocr_provider, "asegurar_runtime_paddle", lambda: None)
    proveedor = PaddleOCRProvider(device="cpu")  # sin ruta_python: usa asegurar_runtime_paddle()

    with pytest.raises(ProveedorOCRNoDisponible):
        proveedor.leer_texto("guia.jpg")


def test_paddleocr_provider_no_disponible_si_python_del_runtime_no_existe(monkeypatch):
    _prohibir_bootstrap_real(monkeypatch)
    monkeypatch.setattr(ocr_provider.Path, "exists", lambda self: False)
    proveedor = PaddleOCRProvider(device="cpu", ruta_python=RUTA_PYTHON_FALSA)

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
    monkeypatch.setattr(ocr_provider, "asegurar_runtime_paddle", lambda: RUTA_PYTHON_FALSA)
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
    monkeypatch.setattr(ocr_provider, "asegurar_runtime_paddle", lambda: None)

    proveedor = crear_proveedor_ocr("paddleocr")

    assert isinstance(proveedor, EasyOCRProvider)


def test_gpu_nvidia_disponible_sin_nvidia_smi_devuelve_false(monkeypatch):
    def _falla(*a, **k):
        raise FileNotFoundError("nvidia-smi no encontrado")

    monkeypatch.setattr(ocr_provider.subprocess, "run", _falla)

    assert ocr_provider._gpu_nvidia_disponible() is False


def test_paddleocr_provider_selecciona_gpu_si_hay_nvidia(monkeypatch):
    monkeypatch.setattr(ocr_provider, "_gpu_nvidia_disponible", lambda: True)

    assert PaddleOCRProvider().device == "gpu"


def test_paddleocr_provider_selecciona_cpu_si_no_hay_nvidia(monkeypatch):
    monkeypatch.setattr(ocr_provider, "_gpu_nvidia_disponible", lambda: False)

    assert PaddleOCRProvider().device == "cpu"


def test_paddleocr_provider_device_explicito_no_consulta_gpu(monkeypatch):
    llamado = Mock(side_effect=AssertionError("no debería consultar GPU si device viene explícito"))
    monkeypatch.setattr(ocr_provider, "_gpu_nvidia_disponible", llamado)

    assert PaddleOCRProvider(device="cpu").device == "cpu"
    llamado.assert_not_called()


# --- visibilidad de logs/estado (no fallback silencioso) ---

def test_crear_proveedor_ocr_fallback_deja_mensaje_visible(monkeypatch, capsys):
    monkeypatch.setattr(ocr_provider, "asegurar_runtime_paddle", lambda: None)

    crear_proveedor_ocr("paddleocr")

    salida = capsys.readouterr().out
    assert "EasyOCR" in salida
    assert "no disponible" in salida.lower() or "fallback" in salida.lower()


def test_crear_proveedor_ocr_exito_deja_mensaje_visible_con_device(monkeypatch, capsys):
    monkeypatch.setattr(ocr_provider, "_gpu_nvidia_disponible", lambda: False)
    monkeypatch.setattr(ocr_provider, "asegurar_runtime_paddle", lambda: RUTA_PYTHON_FALSA)
    monkeypatch.setattr(ocr_provider.Path, "exists", lambda self: True)
    proceso = _ProcesoFalso()
    proceso.stdin.write = Mock(side_effect=proceso._escribir)
    proceso.stdin.flush = Mock()
    proceso.stdout = Mock()
    proceso.stdout.readline = Mock(side_effect=proceso._leer_linea)
    monkeypatch.setattr(ocr_provider.subprocess, "Popen", Mock(return_value=proceso))

    crear_proveedor_ocr("paddleocr")

    salida = capsys.readouterr().out
    assert "PaddleOCR" in salida
    assert "cpu" in salida.lower()


# --- sin ruta/usuario/venv de desarrollo hardcodeados ---

def test_ocr_provider_no_depende_de_ocr_eval_gpu_env():
    import inspect

    fuente = inspect.getsource(ocr_provider)
    assert "ocr_eval_gpu_env" not in fuente
    assert "Jjjc0508" not in fuente


# --- Bloque P2 -- BLOQUEO REAL DE PROCESAMIENTO DESKTOP ---
# Reproduce (sin depender de PaddleOCR real ni de Windows Code Integrity)
# el mecanismo exacto observado en el incidente en vivo: un worker cuyo
# subproceso interno queda sin responder nunca, y confirma que ahora el
# proveedor OCR se cae con ProveedorOCRNoDisponible en vez de bloquear el
# hilo llamador para siempre.

import subprocess as _subprocess_real
import sys as _sys
import time as _time


def test_leer_linea_con_timeout_devuelve_la_linea_si_llega_a_tiempo():
    stream = Mock()
    stream.readline = Mock(return_value="hola\n")

    assert ocr_provider._leer_linea_con_timeout(stream, 5) == "hola\n"


def test_leer_linea_con_timeout_devuelve_none_si_el_stream_nunca_responde():
    stream = Mock()
    stream.readline = Mock(side_effect=lambda: _time.sleep(999))  # nunca vuelve

    inicio = _time.perf_counter()
    resultado = ocr_provider._leer_linea_con_timeout(stream, 0.2)
    duracion = _time.perf_counter() - inicio

    assert resultado is None
    assert duracion < 2  # no esperó los 999s del stream colgado


def test_asegurar_proceso_no_disponible_si_el_worker_nunca_manda_listo(monkeypatch):
    """Reproduce el incidente real: el proceso worker queda vivo pero jamás
    imprime la línea de arranque (equivalente a `PaddleOCR(...)` bloqueado
    esperando un subproceso interno que Code Integrity nunca deja
    continuar) -- debe fallar acotado por TIMEOUT_INICIO_SEG, no colgarse."""
    _prohibir_bootstrap_real(monkeypatch)
    monkeypatch.setattr(ocr_provider, "TIMEOUT_INICIO_SEG", 0.2)
    proveedor = PaddleOCRProvider(device="cpu", ruta_python=RUTA_PYTHON_FALSA)
    proceso = _ProcesoFalso()
    proceso.pid = 999999  # PID inexistente a propósito
    proceso.stdin.write = Mock(side_effect=proceso._escribir)
    proceso.stdin.flush = Mock()
    proceso.stdout = Mock()
    proceso.stdout.readline = Mock(side_effect=lambda: _time.sleep(999))
    monkeypatch.setattr(ocr_provider.Path, "exists", lambda self: True)
    monkeypatch.setattr(ocr_provider.subprocess, "Popen", Mock(return_value=proceso))
    matar = Mock()
    monkeypatch.setattr(ocr_provider, "_matar_arbol_proceso", matar)

    inicio = _time.perf_counter()
    with pytest.raises(ProveedorOCRNoDisponible, match="no respondió en 0.2s al iniciar"):
        proveedor.leer_texto("guia.jpg")
    duracion = _time.perf_counter() - inicio

    assert duracion < 3
    matar.assert_called_once_with(proceso)


def test_comando_no_disponible_si_el_worker_deja_de_responder_a_mitad_de_lote(monkeypatch):
    """El worker respondió bien al iniciar, pero se cuelga procesando una
    imagen concreta (ej. el subproceso interno de PaddlePaddle se traba
    recién ahí) -- una imagen no debe congelar el resto del lote."""
    _prohibir_bootstrap_real(monkeypatch)
    proveedor, proceso = _preparar_proveedor_paddle(monkeypatch, respuestas=[])
    proceso.pid = 999999
    proveedor._asegurar_proceso()  # handshake de arranque, normal (proceso vivo)
    monkeypatch.setattr(ocr_provider, "TIMEOUT_COMANDO_SEG", 0.2)
    matar = Mock()
    monkeypatch.setattr(ocr_provider, "_matar_arbol_proceso", matar)
    # Recién ahora, procesando una imagen concreta, el worker se cuelga.
    proceso.stdout.readline = Mock(side_effect=lambda: _time.sleep(999))

    with pytest.raises(ProveedorOCRNoDisponible, match="no respondió en 0.2s procesando"):
        proveedor.leer_texto("464170.jpeg")

    matar.assert_called_once_with(proceso)
    assert proveedor._proceso is None  # se puede reintentar con un proceso nuevo


def test_comando_colgado_no_deja_el_proveedor_inutilizable_para_el_resto_del_lote(monkeypatch):
    """Tras el timeout de un documento, el SIGUIENTE documento debe poder
    usar un proceso worker nuevo con normalidad -- nunca queda el
    proveedor entero inutilizado por una sola imagen problemática."""
    _prohibir_bootstrap_real(monkeypatch)
    proveedor, proceso_colgado = _preparar_proveedor_paddle(monkeypatch, respuestas=[])
    proceso_colgado.pid = 999999
    proveedor._asegurar_proceso()  # handshake de arranque, normal
    monkeypatch.setattr(ocr_provider, "TIMEOUT_COMANDO_SEG", 0.2)
    monkeypatch.setattr(ocr_provider, "_matar_arbol_proceso", Mock())
    proceso_colgado.stdout.readline = Mock(side_effect=lambda: _time.sleep(999))
    with pytest.raises(ProveedorOCRNoDisponible):
        proveedor.leer_texto("464170.jpeg")

    # Documento siguiente: nuevo Popen, responde con normalidad.
    respuesta = json.dumps({"ok": True, "resultado": "OK"}) + "\n"
    proceso_nuevo = _ProcesoFalso(respuestas=[respuesta])
    proceso_nuevo.stdin.write = Mock(side_effect=proceso_nuevo._escribir)
    proceso_nuevo.stdin.flush = Mock()
    proceso_nuevo.stdout = Mock()
    proceso_nuevo.stdout.readline = Mock(side_effect=proceso_nuevo._leer_linea)
    ocr_provider.subprocess.Popen.return_value = proceso_nuevo

    resultado = proveedor.leer_texto("464264.jpeg")

    assert resultado == ["OK"]


def test_matar_arbol_proceso_termina_un_proceso_real_colgado():
    """Sin mocks: confirma que taskkill /T /F realmente termina un proceso
    Windows real que está en medio de un sleep -- el mecanismo que en el
    incidente real debía liberar al worker de PaddleOCR atascado."""
    proceso = _subprocess_real.Popen(
        [_sys.executable, "-c", "import time; time.sleep(120)"],
        stdout=_subprocess_real.DEVNULL, stderr=_subprocess_real.DEVNULL,
    )
    try:
        assert proceso.poll() is None  # sigue vivo antes de matarlo

        ocr_provider._matar_arbol_proceso(proceso)

        for _ in range(50):
            if proceso.poll() is not None:
                break
            _time.sleep(0.1)
        assert proceso.poll() is not None  # terminó
    finally:
        if proceso.poll() is None:
            proceso.kill()

    import inspect
    fuente = inspect.getsource(ocr_provider)
    assert r"C:\Users" not in fuente
