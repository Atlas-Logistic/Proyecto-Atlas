import argparse
import csv
import json
from datetime import datetime, timezone

import pytest

from atlas_core.reporte_viajes import (
    ARCHIVOS_SALIDA,
    COLUMNAS_HISTORICAS,
    COLUMNAS_OFICIALES,
    COLUMNAS_VIAJES,
    generar_reporte_viajes,
)
from resumen_procesamiento_desktop import comando_resumen, comando_snapshot


RELOJ = lambda: datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def _fila(**cambios):
    fila = {columna: "" for columna in COLUMNAS_OFICIALES}
    fila.update(
        archivo="guía ñ.jpg",
        estado_procesamiento="OK",
        numero_guia="000101",
        numero_transporte="00002001",
        fecha="2026-07-28",
        chofer="JOSÉ PÉREZ",
        rut_chofer="12.345.678-5",
        cliente="CLIENTE ÑUBLE",
        obra_destino="OBRA ÁGUILA",
        patente_tracto="ABCD12",
        patente_rampla="EFGH34",
        descripcion_material="BARRAS",
        tipo_carga="BARRAS",
        indicador_revision="OK",
    )
    fila.update(cambios)
    return fila


def _escribir_csv(ruta, filas, columnas=COLUMNAS_OFICIALES):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(
            archivo,
            fieldnames=list(columnas),
            delimiter=";",
            extrasaction="ignore",
        )
        escritor.writeheader()
        escritor.writerows(filas)


def _leer_csv(ruta):
    with ruta.open(newline="", encoding="utf-8-sig") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _generar(tmp_path, filas, columnas=COLUMNAS_OFICIALES, nombre="reporte"):
    origen = tmp_path / "entrada con espacios.csv"
    salida = tmp_path / nombre
    _escribir_csv(origen, filas, columnas)
    manifest = generar_reporte_viajes(
        origen, salida, carpeta_catalogos=tmp_path / "catálogos", reloj=RELOJ
    )
    return origen, salida, manifest


def test_csv_oficial_15_columnas_genera_contrato_desktop(tmp_path):
    origen, salida, manifest = _generar(tmp_path, [_fila()])
    assert origen.exists()
    assert set(p.name for p in salida.iterdir()) == set(ARCHIVOS_SALIDA)
    assert manifest["esquema_entrada"]["tipo"] == "OFICIAL_15"
    viaje = _leer_csv(salida / "viajes.csv")[0]
    assert list(viaje) == list(COLUMNAS_VIAJES)
    assert viaje["numero_transporte"] == "00002001"
    assert viaje["numeros_guia"] == "000101"
    assert viaje["fecha"] == "28-07-2026"


def test_csv_historico_21_preserva_columnas_en_pendientes(tmp_path):
    columnas = COLUMNAS_OFICIALES + COLUMNAS_HISTORICAS
    fila = _fila(numero_transporte="No encontrado")
    fila.update({columna: f"valor-{columna}" for columna in COLUMNAS_HISTORICAS})
    _, salida, manifest = _generar(tmp_path, [fila], columnas)
    assert manifest["esquema_entrada"]["tipo"] == "HISTORICO_21"
    pendiente = _leer_csv(salida / "documentos_sin_transporte.csv")[0]
    assert list(pendiente) == list(columnas)
    assert pendiente["chofer_fuente"] == "valor-chofer_fuente"


def test_columnas_adicionales_se_aceptan_y_preservan(tmp_path):
    columnas = COLUMNAS_OFICIALES + ("origen", "campo_futuro")
    fila = _fila(numero_transporte="REVISAR", origen="PLANTA NORTE")
    fila["campo_futuro"] = "evidencia"
    _, salida, _ = _generar(tmp_path, [fila], columnas)
    pendiente = _leer_csv(salida / "documentos_sin_transporte.csv")[0]
    assert pendiente["origen"] == "PLANTA NORTE"
    assert pendiente["campo_futuro"] == "evidencia"


def test_falta_columna_obligatoria_da_error_claro(tmp_path):
    columnas = tuple(c for c in COLUMNAS_OFICIALES if c != "numero_transporte")
    origen = tmp_path / "entrada.csv"
    _escribir_csv(origen, [_fila()], columnas)
    with pytest.raises(ValueError, match="numero_transporte"):
        generar_reporte_viajes(origen, tmp_path / "salida")


def test_archivo_vacio_da_error_comprensible(tmp_path):
    origen = tmp_path / "vacío.csv"
    origen.write_bytes(b"")
    with pytest.raises(ValueError, match="vacío"):
        generar_reporte_viajes(origen, tmp_path / "salida")


def test_columnas_repetidas_se_rechazan(tmp_path):
    origen = tmp_path / "entrada.csv"
    encabezado = list(COLUMNAS_OFICIALES) + ["archivo"]
    origen.write_text(";".join(encabezado) + "\n", encoding="utf-8-sig")
    with pytest.raises(ValueError, match="repetidas"):
        generar_reporte_viajes(origen, tmp_path / "salida")


def test_conflictos_y_evidencias_aparecen_en_viajes_csv(tmp_path):
    filas = [
        _fila(archivo="a.jpg", cliente="UNO", obra_destino="NORTE"),
        _fila(archivo="b.jpg", numero_guia="000102", cliente="DOS", obra_destino="SUR"),
    ]
    _, salida, manifest = _generar(tmp_path, filas)
    viaje = _leer_csv(salida / "viajes.csv")[0]
    assert manifest["totales"]["viajes_requieren_revision"] == 1
    assert "CONFLICTO_CLIENTE" in viaje["motivos_revision"]
    assert "CONFLICTO_OBRA_DESTINO" in viaje["motivos_revision"]
    evidencias = json.loads(viaje["evidencias_documentos"])
    assert [e["numero_guia"] for e in evidencias] == ["000101", "000102"]


def test_fuzzy_oficial_conserva_nombre_canonico_sin_cambiar_umbral(tmp_path):
    catalogos = tmp_path / "catálogos"
    catalogos.mkdir()
    (catalogos / "choferes.json").write_text(
        json.dumps(
            {"1": {"nombre": "SALOMÓN PIZARRO", "activo": True}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    origen = tmp_path / "entrada.csv"
    salida = tmp_path / "reporte"
    _escribir_csv(origen, [_fila(chofer="SALOMON PIZARR0")])
    generar_reporte_viajes(origen, salida, carpeta_catalogos=catalogos, reloj=RELOJ)
    assert _leer_csv(salida / "viajes.csv")[0]["choferes"] == "SALOMÓN PIZARRO"


def test_entrada_no_se_modifica_y_reporte_existente_no_se_sobrescribe(tmp_path):
    origen, salida, _ = _generar(tmp_path, [_fila()])
    previo = origen.read_bytes()
    with pytest.raises(FileExistsError):
        generar_reporte_viajes(origen, salida)
    assert origen.read_bytes() == previo


def test_reejecucion_en_otro_destino_es_determinista_y_sin_duplicados(tmp_path):
    filas = [_fila(), _fila()]
    origen = tmp_path / "entrada.csv"
    _escribir_csv(origen, filas)
    salidas = [tmp_path / "reporte uno", tmp_path / "reporte dos"]
    for salida in salidas:
        generar_reporte_viajes(
            origen, salida, carpeta_catalogos=tmp_path / "cats", reloj=RELOJ
        )
    assert (salidas[0] / "viajes.csv").read_bytes() == (
        salidas[1] / "viajes.csv"
    ).read_bytes()
    assert _leer_csv(salidas[0] / "viajes.csv")[0]["cantidad_documentos"] == "1"


def test_orden_invertido_conserva_salida_determinista(tmp_path):
    filas = [
        _fila(archivo="b.jpg", numero_guia="000102", cliente="CLIENTE DOS"),
        _fila(archivo="a.jpg", numero_guia="000101", cliente="CLIENTE UNO"),
    ]
    rutas = []
    for indice, orden in enumerate((filas, list(reversed(filas))), start=1):
        origen = tmp_path / f"entrada {indice}.csv"
        salida = tmp_path / f"reporte {indice}"
        _escribir_csv(origen, orden)
        generar_reporte_viajes(
            origen, salida, carpeta_catalogos=tmp_path / "cats", reloj=RELOJ
        )
        rutas.append(salida / "viajes.csv")
    assert rutas[0].read_bytes() == rutas[1].read_bytes()


def test_caracteres_csv_y_columnas_adicionales_quedan_en_evidencia(tmp_path):
    columnas = COLUMNAS_OFICIALES + ("campo_futuro",)
    valor = 'Ñuble, región; "línea uno"\nlínea dos'
    fila = _fila(campo_futuro=valor, cliente=valor)
    _, salida, _ = _generar(tmp_path, [fila], columnas)
    viaje = _leer_csv(salida / "viajes.csv")[0]
    evidencias = json.loads(viaje["evidencias_documentos"])
    assert evidencias[0]["campo_futuro"] == valor
    assert viaje["clientes"] == valor


def test_resumen_desktop_snapshot_y_resultado(tmp_path, capsys):
    origen, reporte, _ = _generar(
        tmp_path,
        [
            _fila(archivo="a.jpg"),
            _fila(
                archivo="b.jpg",
                numero_guia="000102",
                numero_transporte="No encontrado",
            ),
        ],
    )
    snapshot = tmp_path / "snapshot con espacios.json"
    comando_snapshot(argparse.Namespace(csv_masivo=origen, salida=snapshot))
    comando_resumen(
        argparse.Namespace(
            csv_masivo=origen,
            reporte=reporte,
            snapshot=snapshot,
            archivo=["a.jpg", "b.jpg", "a.jpg"],
        )
    )
    resultado = json.loads(capsys.readouterr().out)
    assert len(resultado) == 2
    assert resultado[0]["numero_transporte"] == "00002001"
    assert resultado[1]["sin_transporte"] is True


def test_resumen_prefiere_fila_posterior_con_transporte_sin_depender_del_orden(
    tmp_path, capsys
):
    sin_transporte = _fila(archivo="mismo.jpg", numero_transporte="")
    con_transporte = _fila(archivo="mismo.jpg", numero_transporte="0000349935")
    for indice, filas in enumerate(
        ([sin_transporte, con_transporte], [con_transporte, sin_transporte]), start=1
    ):
        origen, reporte, _ = _generar(
            tmp_path, filas, nombre=f"reporte resumen {indice}"
        )
        snapshot = tmp_path / f"snapshot {indice}.json"
        comando_snapshot(argparse.Namespace(csv_masivo=origen, salida=snapshot))
        comando_resumen(
            argparse.Namespace(
                csv_masivo=origen,
                reporte=reporte,
                snapshot=snapshot,
                archivo=["mismo.jpg"],
            )
        )
        resultado = json.loads(capsys.readouterr().out)
        assert resultado[0]["numero_transporte"] == "0000349935"
        assert resultado[0]["sin_transporte"] is False


def test_documentos_sin_transporte_conserva_todas_las_filas_distintas(tmp_path):
    filas = [
        _fila(archivo="a.jpg", numero_transporte=""),
        _fila(archivo="b.jpg", numero_transporte=""),
    ]
    _, salida, _ = _generar(tmp_path, filas)
    assert [f["archivo"] for f in _leer_csv(salida / "documentos_sin_transporte.csv")] == [
        "a.jpg",
        "b.jpg",
    ]


def test_encabezado_sin_filas_genera_reporte_vacio(tmp_path):
    _, salida, manifest = _generar(tmp_path, [])
    assert manifest["totales"]["filas_leidas"] == 0
    assert _leer_csv(salida / "viajes.csv") == []
