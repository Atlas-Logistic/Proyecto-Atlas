"""Bloque BUG: PÉRDIDA DE DECISIÓN PENDIENTE AL AGREGAR OTRA GUÍA AL MISMO
VIAJE.

Causa raíz real: `analizar_guias_masivo.py` (el CLI que Desktop invoca al
arrastrar guías nuevas) publicaba `decisiones_pendientes.json` con
ÚNICAMENTE las decisiones detectadas en ESE lote (`resumen["decisiones_
pendientes"]`, sólo de los archivos NUEVOS que `procesar_carpeta` acaba
de procesar) -- nunca leía la bandeja YA PERSISTIDA antes de
sobrescribirla. Caso real: 472647 tenía 2 decisiones legítimas ya
auditadas (OBRA_DESCONOCIDA, DESTINO_NO_RESUELTO); al agregar 472648
(mismo transporte, cliente distinto), ambas desaparecieron en silencio
y sólo quedó la decisión nueva de 472648.

Se prueba ejecutando `analizar_guias_masivo.main()` real (mismo patrón
ya usado en test_generar_reporte_viajes_cli.py), con `procesar_carpeta`
sustituido por un doble de prueba que nunca hace OCR real -- el bug/fix
vive enteramente en cómo el CLI publica la bandeja, no en el
procesamiento documental en sí."""
from __future__ import annotations

import csv
import json
import sys

import analizar_guias_masivo
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, ResultadoEvidencia, TipoEvidencia
from atlas_core.decisiones_pendientes import crear_decision
from atlas_core.fuente_catalogos import ARCHIVOS_REQUERIDOS
from atlas_core.procesamiento_masivo import COLUMNAS


def _fuente_catalogos_valida(carpeta):
    """Mínimo exigido por `validar_fuente_catalogos` -- mismo contenido
    que ya usa `tests/test_fuente_catalogos.py`."""
    contenidos = {
        "choferes.json": {},
        "clientes.json": {"version_formato": 1, "clientes": []},
        "empresas.json": {},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
        "vehiculos.json": {},
        "plantas.json": {"plantas": []},
        "rutas.json": {"rutas": []},
    }
    for nombre in ARCHIVOS_REQUERIDOS:
        (carpeta / nombre).write_text(json.dumps(contenidos[nombre]), encoding="utf-8")
    # `obras_destinos.json` no es exigido por validar_fuente_catalogos, pero
    # sí lo usan generar_artefacto/regenerar_decisiones_persistidas.
    (carpeta / "obras_destinos.json").write_text(
        json.dumps({"version_formato": 1, "obras": [], "relaciones": []}), encoding="utf-8",
    )


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "472647.jpeg", "estado_procesamiento": "OK", "numero_guia": "472647",
        "numero_transporte": "0000355231", "fecha": "26-08-2026", "indicador_revision": "REVISAR",
        "motivos_revision_documento": "OBRA_DESTINO_SIN_CORROBORAR",
        "motivo_ruta": "MULTIPLES_UBICACIONES_DISPERSAS(3)", "estado_ruta": "REQUIERE_REVISION",
    })
    fila.update(overrides)
    return fila


def _escribir_dataset(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _decision_obra_desconocida(*, numero_guia, valor_documental, cliente_id):
    return crear_decision(
        tipo="OBRA_DESCONOCIDA", entidad="OBRA", archivo=f"{numero_guia}.jpeg",
        numero_guia=numero_guia, numero_transporte="0000355231", campo="obra_destino",
        valor_documental=valor_documental, valor_normalizado=valor_documental,
        identidad_resuelta=None, candidatos=(),
        motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),
        evidencias=({"tipo": "CLIENTE_RESUELTO", "entidad_id": cliente_id},),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        contexto={"cliente_id": cliente_id, "cliente_canonico": "CLIENTE GENERICO SA"},
    )


def _decision_destino_no_resuelto(*, numero_guia, valor_documental):
    return crear_decision(
        tipo="DESTINO_NO_RESUELTO", entidad="DESTINO", archivo=f"{numero_guia}.jpeg",
        numero_guia=numero_guia, numero_transporte="0000355231", campo="despachar_a_crudo",
        valor_documental=valor_documental, valor_normalizado="",
        identidad_resuelta=None, candidatos=(),
        motivos=("MULTIPLES_UBICACIONES_DISPERSAS",),
        evidencias=({"tipo": "RUTA_BLOQUEADA", "motivo_ruta": "MULTIPLES_UBICACIONES_DISPERSAS(3)"},),
        acciones_permitidas=("REGISTRAR_DIRECCION", "NO_PUEDO_DETERMINAR", "POSPONER"),
    )


def _preparar_entorno(tmp_path, *, decisiones_previas, filas_dataset):
    carpeta_guias = tmp_path / "guias"
    carpeta_guias.mkdir()
    catalogos = tmp_path / "catalogos"
    catalogos.mkdir()
    _fuente_catalogos_valida(catalogos)
    salida = tmp_path / "salida" / "analisis_completo_guias.csv"
    salida.parent.mkdir(parents=True)
    _escribir_dataset(salida, filas_dataset)
    ruta_artefacto = salida.parent / "decisiones_pendientes.json"
    ruta_artefacto.write_text(json.dumps({
        "schema_version": 1, "generado_en": "2026-08-26T00:00:00+00:00",
        "dataset_sha256": "", "catalogos_sha256": {}, "decisiones": decisiones_previas,
    }), encoding="utf-8")
    return carpeta_guias, catalogos, salida, ruta_artefacto


def _ejecutar_cli(monkeypatch, *, carpeta_guias, catalogos, salida, decisiones_nuevas):
    def _procesar_carpeta_falso(carpeta, ruta_salida, **kwargs):
        return {
            "encontrados": 1, "procesados": 1, "omitidos": 0, "errores": 0,
            "barras": 0, "rollos": 0, "mixtos": 0, "no_determinados": 0,
            "tiempo_total_segundos": 0.01, "promedio_segundos_archivo": 0.01,
            "decisiones_pendientes": decisiones_nuevas,
        }

    monkeypatch.setattr(analizar_guias_masivo, "procesar_carpeta", _procesar_carpeta_falso)
    monkeypatch.setattr(
        sys, "argv",
        ["analizar_guias_masivo.py", str(carpeta_guias), "--salida", str(salida), "--catalogos", str(catalogos)],
    )
    analizar_guias_masivo.main()


def _decisiones_publicadas(ruta_artefacto):
    return json.loads(ruta_artefacto.read_text(encoding="utf-8"))["decisiones"]


# ============================================================
# CASO A: guía B se agrega sin evidencia que resuelva A -> las 2 de A sobreviven
# ============================================================


def test_caso_a_decisiones_previas_sobreviven_sin_evidencia_nueva(tmp_path, monkeypatch):
    decision_1 = _decision_obra_desconocida(
        numero_guia="472647", valor_documental="SALOMON SACK SA LA CHIMBA", cliente_id="cliente-1",
    )
    decision_2 = _decision_destino_no_resuelto(
        numero_guia="472647", valor_documental="AGUAS VERDES 344 ANTOFAGASTA LA CHIMBA",
    )
    fila_472647 = _fila_csv()
    fila_472648 = _fila_csv(archivo="472648.jpeg", numero_guia="472648", motivos_revision_documento="")
    carpeta_guias, catalogos, salida, ruta_artefacto = _preparar_entorno(
        tmp_path, decisiones_previas=[decision_1, decision_2], filas_dataset=[fila_472647, fila_472648],
    )

    _ejecutar_cli(monkeypatch, carpeta_guias=carpeta_guias, catalogos=catalogos, salida=salida, decisiones_nuevas=[])

    ids = {d["decision_id"] for d in _decisiones_publicadas(ruta_artefacto)}
    assert decision_1["decision_id"] in ids
    assert decision_2["decision_id"] in ids


# ============================================================
# CASO B: guía B genera sus propias decisiones -- sobreviven las de A + las de B
# ============================================================


def test_caso_b_decisiones_de_a_y_b_conviven_sin_colisiones(tmp_path, monkeypatch):
    decision_1 = _decision_obra_desconocida(
        numero_guia="472647", valor_documental="SALOMON SACK SA LA CHIMBA", cliente_id="cliente-1",
    )
    decision_2 = _decision_destino_no_resuelto(
        numero_guia="472647", valor_documental="AGUAS VERDES 344 ANTOFAGASTA LA CHIMBA",
    )
    decision_b = _decision_obra_desconocida(
        numero_guia="472648", valor_documental="TORRES OCARANZA LTDA CALAMA", cliente_id="cliente-2",
    )
    fila_472647 = _fila_csv()
    fila_472648 = _fila_csv(archivo="472648.jpeg", numero_guia="472648", motivos_revision_documento="")
    carpeta_guias, catalogos, salida, ruta_artefacto = _preparar_entorno(
        tmp_path, decisiones_previas=[decision_1, decision_2], filas_dataset=[fila_472647, fila_472648],
    )

    _ejecutar_cli(
        monkeypatch, carpeta_guias=carpeta_guias, catalogos=catalogos, salida=salida, decisiones_nuevas=[decision_b],
    )

    publicadas = _decisiones_publicadas(ruta_artefacto)
    ids = [d["decision_id"] for d in publicadas]
    assert len(ids) == len(set(ids)) == 3  # sin colisiones, sin duplicados
    assert {decision_1["decision_id"], decision_2["decision_id"], decision_b["decision_id"]} == set(ids)


# ============================================================
# CASO C: evidencia real (obra ahora confirmada en catálogo) resuelve una de A
# ============================================================


def test_caso_c_evidencia_real_resuelve_solo_la_decision_correspondiente(tmp_path, monkeypatch):
    carpeta_guias = tmp_path / "guias"
    carpeta_guias.mkdir()
    catalogos = tmp_path / "catalogos"
    catalogos.mkdir()
    _fuente_catalogos_valida(catalogos)

    # La obra de la decisión 1 YA está confirmada en el catálogo -- evidencia
    # real que demuestra por qué esa decisión concreta puede cerrarse.
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="SALOMON SACK SA", rut="76.111.111-6", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    destino = CatalogoDestinos(
        catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json",
    ).crear(
        cliente_id="", nombre_destino="AGUAS VERDES 344 ANTOFAGASTA", direccion="AGUAS VERDES 344 ANTOFAGASTA",
        pais="CHILE", fuente="TEST", estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    catalogo_obras = CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    )
    resultado_obs = catalogo_obras.registrar_observacion(
        cliente_id=cliente.cliente_id, nombre_obra="SALOMON SACK SA LA CHIMBA", destino_id=destino.destino_id,
        evidencia=Evidencia(
            tipo=TipoEvidencia.GUIA.value, identificador_fuente="472647", referencia_hash="a" * 64,
            campos_observados={"obra": "SALOMON SACK SA LA CHIMBA"},
            fecha="2026-01-01T00:00:00+00:00", actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value,
        ),
    )
    catalogo_obras.confirmar_relacion(resultado_obs.relacion.relacion_id, actor="TEST", identificador_fuente="test")

    decision_1 = _decision_obra_desconocida(
        numero_guia="472647", valor_documental="SALOMON SACK SA LA CHIMBA", cliente_id=cliente.cliente_id,
    )
    decision_2 = _decision_destino_no_resuelto(
        numero_guia="472647", valor_documental="AGUAS VERDES 344 ANTOFAGASTA LA CHIMBA",
    )
    fila_472647 = _fila_csv(cliente="SALOMON SACK SA", obra_destino="SALOMON SACK SA LA CHIMBA")
    fila_472648 = _fila_csv(archivo="472648.jpeg", numero_guia="472648", motivos_revision_documento="")
    salida = tmp_path / "salida" / "analisis_completo_guias.csv"
    salida.parent.mkdir(parents=True)
    _escribir_dataset(salida, [fila_472647, fila_472648])
    ruta_artefacto = salida.parent / "decisiones_pendientes.json"
    ruta_artefacto.write_text(json.dumps({
        "schema_version": 1, "generado_en": "2026-08-26T00:00:00+00:00",
        "dataset_sha256": "", "catalogos_sha256": {}, "decisiones": [decision_1, decision_2],
    }), encoding="utf-8")

    _ejecutar_cli(monkeypatch, carpeta_guias=carpeta_guias, catalogos=catalogos, salida=salida, decisiones_nuevas=[])

    publicadas = _decisiones_publicadas(ruta_artefacto)
    ids = {d["decision_id"] for d in publicadas}
    # Sólo la decisión con evidencia real de resolución (obra ya confirmada)
    # se retira -- la otra, sin evidencia nueva, se conserva intacta.
    assert decision_1["decision_id"] not in ids
    assert decision_2["decision_id"] in ids


# ============================================================
# CASO D: reconciliar dos veces es idempotente -- sin duplicados, sin pérdidas
# ============================================================


def test_caso_d_ejecutar_el_cli_dos_veces_es_idempotente(tmp_path, monkeypatch):
    decision_1 = _decision_obra_desconocida(
        numero_guia="472647", valor_documental="SALOMON SACK SA LA CHIMBA", cliente_id="cliente-1",
    )
    decision_2 = _decision_destino_no_resuelto(
        numero_guia="472647", valor_documental="AGUAS VERDES 344 ANTOFAGASTA LA CHIMBA",
    )
    fila_472647 = _fila_csv()
    fila_472648 = _fila_csv(archivo="472648.jpeg", numero_guia="472648", motivos_revision_documento="")
    carpeta_guias, catalogos, salida, ruta_artefacto = _preparar_entorno(
        tmp_path, decisiones_previas=[decision_1, decision_2], filas_dataset=[fila_472647, fila_472648],
    )

    _ejecutar_cli(monkeypatch, carpeta_guias=carpeta_guias, catalogos=catalogos, salida=salida, decisiones_nuevas=[])
    primera = _decisiones_publicadas(ruta_artefacto)
    _ejecutar_cli(monkeypatch, carpeta_guias=carpeta_guias, catalogos=catalogos, salida=salida, decisiones_nuevas=[])
    segunda = _decisiones_publicadas(ruta_artefacto)

    assert len(primera) == len(segunda) == 2
    assert {d["decision_id"] for d in primera} == {d["decision_id"] for d in segunda}
