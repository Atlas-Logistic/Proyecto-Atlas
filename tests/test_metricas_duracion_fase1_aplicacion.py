"""PERFIL FOCAL DE LATENCIA -- métricas de duración en la Fase 1 (clic
"Aplicar decisión" -> `aplicar_decision_obra` -> `revalidar_y_regenerar_
reporte`, el tramo de ~40s medido en Desktop antes de que la tarjeta
cambie). Instrumentación pura (`time.perf_counter`), nunca decide nada ni
cambia ningún resultado -- ver `tests/test_metricas_duracion_
reconciliacion.py` para el tramo equivalente de la Fase 2
("Actualizando operación", ~70s)."""
import csv
import json

from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_y_regenerar_reporte


def _catalogos_base(carpeta):
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []}, "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "x.jpeg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "T1", "fecha": "01-08-2026",
        "indicador_revision": "REVISAR", "planta_origen_id": "planta-1",
    })
    fila.update(overrides)
    return fila


def _entorno_con_decision_cliente_ausente(tmp_path):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True)
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="TORRES OCARANZA LTDA", rut="50.234.350-5", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    dataset = actual / "analisis_completo_guias.csv"
    fila = _fila(
        archivo="472238.jpeg", numero_guia="472238", numero_transporte="T-472238",
        cliente="No encontrado", obra_destino="TORRES OCARANZA LTDA",
        motivos_revision_documento="CLIENTE_AUSENTE",
    )
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerow(fila)
    decision = crear_decision(
        tipo="CLIENTE_AUSENTE", entidad="CLIENTE", archivo="472238.jpeg", numero_guia="472238",
        numero_transporte="T-472238", campo="cliente", valor_documental="", valor_normalizado="",
        identidad_resuelta=None, candidatos=(), motivos=("CLIENTE_AUSENTE",),
        evidencias=(), acciones_permitidas=("REGISTRAR_CLIENTE_MANUAL", "NO_PUEDO_DETERMINAR", "POSPONER"),
    )
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision],
        ruta_salida=actual / "decisiones_pendientes.json",
    )
    return raiz


def test_revalidar_y_regenerar_reporte_expone_tiempos_ms_cuando_regenera(tmp_path):
    raiz = _entorno_con_decision_cliente_ausente(tmp_path)

    resultado = revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_metricas")

    assert resultado["reporte_regenerado"] is True
    assert "tiempos_ms" in resultado
    tiempos = resultado["tiempos_ms"]
    assert set(tiempos) == {"bateria_revalidadores_ms", "generar_reporte_ms", "total_ms"}
    for valor in tiempos.values():
        assert valor >= 0
    # El total debe ser al menos la suma de sus dos partes medidas (puede
    # haber overhead de I/O entre las dos marcas, nunca menos).
    assert tiempos["total_ms"] >= tiempos["bateria_revalidadores_ms"] + tiempos["generar_reporte_ms"] - 1


def test_revalidar_y_regenerar_reporte_segunda_corrida_idempotente_expone_solo_bateria_ms(tmp_path):
    """Segunda corrida sobre el MISMO estado ya reconciliado (idempotente
    -- nada cambió esta vez): `bateria_revalidadores_ms` sigue presente
    (la batería igual corrió, para concluir que no había nada que hacer),
    pero `generar_reporte_ms`/`total_ms` no existen (el reporte no se
    regeneró una segunda vez)."""
    raiz = _entorno_con_decision_cliente_ausente(tmp_path)
    primero = revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_metricas_2a")
    assert primero["reporte_regenerado"] is True

    segundo = revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_metricas_2b")

    assert segundo["reporte_regenerado"] is False
    assert "tiempos_ms" in segundo
    assert "bateria_revalidadores_ms" in segundo["tiempos_ms"]
    assert segundo["tiempos_ms"]["bateria_revalidadores_ms"] >= 0
    assert "generar_reporte_ms" not in segundo["tiempos_ms"]
