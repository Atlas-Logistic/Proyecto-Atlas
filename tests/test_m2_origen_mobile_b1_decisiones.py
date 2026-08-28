"""Bloque M2 -- integración Mobile -> origen -> B1 -> decisiones.

Causa raíz real (472623/472624, prueba operacional real end-to-end vía
Atlas Mobile):
- M2-A/B ya cubiertos en `test_origen_evidencia.py` (ausencia de
  material NO es incompatibilidad; Mobile resuelve directo con
  evidencia suficiente).
- M2-C: `EVIDENCIA_HISTORIAL_ORIGEN`/`EVIDENCIA_CATALOGO_PLANTAS`
  declaradas como disponibles para B1 (`registro_problemas.py`) pero
  nunca conectadas en `_herramientas_b1_disponibles` -- B1 las pedía y
  siempre chocaba con "herramienta no disponible".
- M2-D: `procesar_envio_mobile` nunca invocaba `detectar_decision_
  origen_no_confirmado` (a diferencia del lote Desktop) -- una
  contradicción/ambigüedad real de origen producida desde Mobile podía
  quedar invisible en Revisión de Atlas."""
from __future__ import annotations

import csv
import json
import uuid
from pathlib import Path

from atlas_core.atlas_ia.contratos import (
    ContextoRazonamiento, RESULTADO_HIPOTESIS_PROPUESTA, RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA,
    HipotesisIA, calcular_hipotesis_id,
)
from atlas_core.atlas_ia.orquestador import RESUELTO_POR_IA, OrquestadorAtlasIA
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.mobile import RepositorioEnviosMobile, procesar_envio_mobile
from atlas_core.procesamiento_masivo import COLUMNAS, _herramientas_b1_disponibles


# ============================================================
# 4. Herramientas de origen declaradas para B1 -- realmente ejecutables
# ============================================================


def test_herramientas_b1_disponibles_registra_evidencia_historial_y_catalogo_cuando_hay_datos(tmp_path):
    carpeta_catalogos = tmp_path / "catalogos"
    CatalogoPlantas(carpeta_catalogos / "plantas.json").crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST", estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    filas = [{"numero_guia": "1", "origen_determinado_por": "TELEMETRIA_GPS", "planta_origen_nombre": "AZA COLINA"}]
    herramientas = _herramientas_b1_disponibles(filas=filas, carpeta_catalogos=carpeta_catalogos)
    assert set(herramientas) >= {"EVIDENCIA_HISTORIAL_ORIGEN", "EVIDENCIA_CATALOGO_PLANTAS"}


def test_herramientas_b1_disponibles_sin_datos_no_registra_nada_nuevo():
    """Ausentes (valor por defecto): comportamiento idéntico al de
    siempre, nunca un error -- ver bloque de comentario en la función.
    (VERIFICACION_EXTERNA puede o no aparecer según credencial del
    entorno -- eso ya es comportamiento previo, sin cambios; lo que
    importa aquí es que las 2 herramientas nuevas nunca aparecen sin
    `filas`/`carpeta_catalogos`.)"""
    assert set(_herramientas_b1_disponibles()) & {"EVIDENCIA_HISTORIAL_ORIGEN", "EVIDENCIA_CATALOGO_PLANTAS"} == set()


def test_b1_puede_invocar_realmente_evidencia_historial_origen_end_to_end(tmp_path):
    """Prueba real/shadow: un proveedor simulado pide EVIDENCIA_HISTORIAL_
    ORIGEN y el orquestador YA CONECTADO (vía `_herramientas_b1_
    disponibles`, la misma fuente que usa producción) la ejecuta de
    verdad -- nunca "herramienta no disponible" (bug real confirmado con
    472624 antes de este fix)."""
    carpeta_catalogos = tmp_path / "catalogos"
    CatalogoPlantas(carpeta_catalogos / "plantas.json").crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST", estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    filas = [{
        "numero_guia": "1", "numero_transporte": "0000000001",
        "origen_determinado_por": "TELEMETRIA_GPS", "planta_origen_nombre": "AZA COLINA",
        "fecha": "01-01-2026", "patente_tracto": "AA1111", "chofer": "X", "cliente": "Y",
        "obra_destino": "Z", "tipo_carga": "BARRAS", "descripcion_material": "M",
    }]
    herramientas = _herramientas_b1_disponibles(filas=filas, carpeta_catalogos=carpeta_catalogos)

    class _ProveedorPideHistorial:
        def __init__(self):
            self.ronda = 0

        def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:
            self.ronda += 1
            if self.ronda == 1:
                return HipotesisIA(
                    hipotesis_id=calcular_hipotesis_id(contexto, ""), campo=contexto.campo,
                    valor_observado=contexto.valor_documental, valor_propuesto="",
                    resultado=RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA,
                    herramienta_faltante="EVIDENCIA_HISTORIAL_ORIGEN",
                )
            return HipotesisIA(
                hipotesis_id=calcular_hipotesis_id(contexto, "AZA COLINA"), campo=contexto.campo,
                valor_observado=contexto.valor_documental, valor_propuesto="AZA COLINA",
                resultado=RESULTADO_HIPOTESIS_PROPUESTA,
                evidencia_usada=tuple(e.identificador for e in contexto.evidencias),
            )

    contexto = ContextoRazonamiento(
        campo="planta_origen", valor_documental="", rut_chofer="", numero_guia="2",
        numero_transporte="0000000002", evidencias=(), resultado_motor="REQUIERE_REVISION",
        herramientas_disponibles=("EVIDENCIA_HISTORIAL_ORIGEN", "EVIDENCIA_CATALOGO_PLANTAS"),
    )
    resultado = OrquestadorAtlasIA(proveedor=_ProveedorPideHistorial(), herramientas=herramientas).resolver(contexto)
    assert resultado.estado == RESUELTO_POR_IA
    assert resultado.herramientas_usadas == ("EVIDENCIA_HISTORIAL_ORIGEN",)
    assert resultado.hipotesis.valor_propuesto == "AZA COLINA"


# ============================================================
# 5/6. Paridad Mobile/Desktop -- decisión ORIGEN_NO_CONFIRMADO visible
#      cuando hace falta, nunca fabricada cuando el origen ya resolvió.
# ============================================================


def _dataset_vacio(ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";").writeheader()


def _recibir(tmp_path: Path) -> tuple[RepositorioEnviosMobile, str]:
    repo = RepositorioEnviosMobile(tmp_path)
    envio_id = str(uuid.uuid4())
    repo.recibir(
        envio_id=envio_id, imagen=b"foto", mime="image/jpeg",
        metadata={"chofer_id": "c1", "tipo_novedad": "", "guia_firmada_correo": False, "planta_origen_informada": "AZA_COLINA"},
    )
    return repo, envio_id


def _carpeta_catalogos(tmp_path: Path) -> Path:
    carpeta = tmp_path / "catalogos"
    CatalogoPlantas(carpeta / "plantas.json").crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST", estado_calidad=EstadoCalidad.CONFIRMADA,
        categorias_permitidas=("BARRAS",),
    )
    return carpeta


def test_ambiguedad_real_de_origen_desde_mobile_genera_decision_visible(tmp_path: Path, monkeypatch):
    """Caso real 472624: contradicción operacional real de origen
    producida desde Mobile -- debe aparecer en Revisión de Atlas, igual
    que ya pasa para Desktop."""
    monkeypatch.setenv("ATLAS_IA_B1_OPERACIONAL", "0")  # foco en M2-D (deterministico), sin red real a B1.
    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    carpeta_catalogos = _carpeta_catalogos(tmp_path)

    procesar_envio_mobile(
        repo, envio_id, dataset=dataset, carpeta_catalogos=carpeta_catalogos,
        procesador=lambda ruta: {
            "numero_guia": "700001", "numero_transporte": "0000700000",
            "indicador_revision": "REVISAR", "tipo_carga": "NO DETERMINADO",
            "estado_ruta": "ORIGEN_NO_DETERMINADO",
            "motivo_ruta": "CONTRADICCION_OPERACIONAL_ORIGEN[MOBILE=AZA_COLINA:INCOMPATIBLE]",
            "planta_origen_id": "", "planta_origen_nombre": "",
        },
    )

    artefacto = json.loads((dataset.parent / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    decisiones_origen = [
        d for d in artefacto["decisiones"]
        if d["tipo"] == "ORIGEN_NO_CONFIRMADO" and d["documento"]["numero_guia"] == "700001"
    ]
    assert len(decisiones_origen) == 1
    assert decisiones_origen[0]["candidatos"] == []  # nunca sugiere la planta ya descartada


def test_origen_ya_resuelto_desde_mobile_no_fabrica_decision_redundante(tmp_path: Path, monkeypatch):
    """Caso real 472623: Mobile + material compatible ya resolvió el
    origen -- nunca debe aparecer una pregunta redundante."""
    monkeypatch.setenv("ATLAS_IA_B1_OPERACIONAL", "0")  # foco en M2-D (deterministico), sin red real a B1.
    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    carpeta_catalogos = _carpeta_catalogos(tmp_path)
    planta_id = CatalogoPlantas(carpeta_catalogos / "plantas.json").listar()[0].planta_id

    procesar_envio_mobile(
        repo, envio_id, dataset=dataset, carpeta_catalogos=carpeta_catalogos,
        procesador=lambda ruta: {
            "numero_guia": "700002", "numero_transporte": "0000700002",
            "indicador_revision": "OK", "tipo_carga": "BARRAS",
            "estado_ruta": "RUTA_CALCULADA", "motivo_ruta": "",
            "planta_origen_id": planta_id, "planta_origen_nombre": "AZA COLINA",
            "origen_determinado_por": "MOBILE",
        },
    )

    ruta_artefacto = dataset.parent / "decisiones_pendientes.json"
    if ruta_artefacto.is_file():
        artefacto = json.loads(ruta_artefacto.read_text(encoding="utf-8"))
        decisiones_origen = [
            d for d in artefacto["decisiones"]
            if d["tipo"] == "ORIGEN_NO_CONFIRMADO" and d["documento"]["numero_guia"] == "700002"
        ]
        assert decisiones_origen == []
