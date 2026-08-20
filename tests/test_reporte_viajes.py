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


# --- Bloque RUTAS R1: columnas de ruta backward-compatible ---

_COLUMNAS_RUTA = (
    "planta_origen_id", "planta_origen_nombre", "destino_id", "destino_nombre",
    "distancia_km", "duracion_min", "proveedor_ruta", "estado_ruta",
    "motivo_ruta", "origen_determinado_por",
)


def test_columnas_ruta_vacias_sin_calculador_rutas_no_regresion(tmp_path):
    """Sin `calculador_rutas` (comportamiento por defecto), el reporte es
    idéntico al de antes de este bloque salvo por columnas nuevas vacías --
    no regresión del flujo OCR/reportes existente."""
    origen, salida, _ = _generar(tmp_path, [_fila()])
    filas = _leer_csv(salida / "viajes.csv")
    assert len(filas) == 1
    for columna in _COLUMNAS_RUTA:
        assert filas[0][columna] == ""
    # el resto de columnas y su contenido no cambian
    assert filas[0]["clientes"] == "CLIENTE ÑUBLE"
    assert filas[0]["obras_destino"] == "OBRA ÁGUILA"


def test_calculador_rutas_propaga_campos_al_csv(tmp_path):
    def calculador_falso(viaje):
        return {
            "planta_origen_id": "planta-1", "planta_origen_nombre": "AZA RENCA",
            "destino_id": "destino-1", "destino_nombre": "GALVARINO 8501",
            "distancia_km": "7.43", "duracion_min": "12.06",
            "proveedor_ruta": "openrouteservice", "estado_ruta": "RUTA_CALCULADA",
            "motivo_ruta": "", "origen_determinado_por": "ONELOGIS_GPS",
        }

    origen = tmp_path / "entrada.csv"
    salida = tmp_path / "reporte_con_rutas"
    _escribir_csv(origen, [_fila()])
    generar_reporte_viajes(
        origen, salida, carpeta_catalogos=tmp_path / "catálogos", reloj=RELOJ,
        calculador_rutas=calculador_falso,
    )
    filas = _leer_csv(salida / "viajes.csv")
    assert filas[0]["planta_origen_nombre"] == "AZA RENCA"
    assert filas[0]["distancia_km"] == "7.43"
    assert filas[0]["duracion_min"] == "12.06"
    assert filas[0]["estado_ruta"] == "RUTA_CALCULADA"
    assert filas[0]["origen_determinado_por"] == "ONELOGIS_GPS"
    # sin API key ni secretos en ningún campo persistido
    contenido = (salida / "viajes.csv").read_text(encoding="utf-8-sig")
    assert "api_key" not in contenido.lower() and "authorization" not in contenido.lower()


# --- Bloque O1: peso y horarios operacionales end-to-end hasta viajes.csv ---


def test_peso_horas_permanencia_llegan_a_viajes_csv(tmp_path):
    fila = _fila(peso_kg="6971", hora_entrada_aza="10:08", hora_salida_aza="12:27")
    _, salida, _ = _generar(tmp_path, [fila])
    viaje = _leer_csv(salida / "viajes.csv")[0]
    assert viaje["peso_total_viaje_kg"] == "6971"
    assert viaje["hora_entrada_aza"] == "10:08"
    assert viaje["hora_salida_aza"] == "12:27"
    assert viaje["permanencia_minutos"] == "139"


def test_peso_multiguia_real_suma_en_viajes_csv(tmp_path):
    # Caso real: transporte 0000297304, 3 documentos, pesos parciales
    # distintos (6.971 + 3.100 + 4.256 kg) -- ver bitácora técnica.
    filas = [
        _fila(archivo="a.jpg", numero_guia="410265", peso_kg="6971",
              hora_entrada_aza="10:08", hora_salida_aza="12:27"),
        _fila(archivo="b.jpg", numero_guia="410266", peso_kg="3100",
              hora_entrada_aza="10:08", hora_salida_aza="12:27"),
        _fila(archivo="c.jpg", numero_guia="410267", peso_kg="4256",
              hora_entrada_aza="10:08", hora_salida_aza="12:27"),
    ]
    _, salida, _ = _generar(tmp_path, filas)
    viaje = _leer_csv(salida / "viajes.csv")[0]
    assert viaje["peso_total_viaje_kg"] == "14327"
    assert viaje["hora_entrada_aza"] == "10:08"
    assert viaje["hora_salida_aza"] == "12:27"


def test_csv_sin_columnas_o1_exige_migracion_explicita(tmp_path):
    """Un CSV de entrada anterior a este bloque (sin peso_kg/hora_entrada_aza/
    hora_salida_aza/permanencia_minutos) no se acepta en silencio con
    columnas vacías -- el mismo contrato de esquema estricto que ya regía
    para cualquier otra columna oficial faltante (`_validar_esquema`)
    exige reprocesar con el pipeline actual antes de poder reportar."""
    columnas_antiguas = tuple(
        c for c in COLUMNAS_OFICIALES
        if c not in {"peso_kg", "hora_entrada_aza", "hora_salida_aza", "permanencia_minutos"}
    )
    origen = tmp_path / "entrada.csv"
    _escribir_csv(origen, [_fila()], columnas_antiguas)
    with pytest.raises(ValueError, match="peso_kg"):
        generar_reporte_viajes(
            origen, tmp_path / "salida", carpeta_catalogos=tmp_path / "catálogos", reloj=RELOJ
        )


# Bloque VEHÍCULO D1 (cierre, G1) -- `ruta_ledger` end-to-end: una decisión
# humana ya aplicada (`decisiones_aplicadas.json`) debe reflejarse como
# valor operacional en `viajes.csv`, sin tocar nunca el CSV de entrada.
# Caso real que motivó esto: transporte 0000351135 (464264/464265).

def _escribir_ledger(ruta, aplicaciones):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps({"schema_version": 1, "aplicaciones": aplicaciones}, ensure_ascii=False),
        encoding="utf-8",
    )


def _aplicacion_patente(numero_guia, campo, valor_documental, patente_canonica, accion="SELECCIONAR_OTRA_PATENTE"):
    return {
        "decision_id": f"dec-{numero_guia}-{campo}",
        "tipo": "VEHICULO_DESCONOCIDO",
        "accion": accion,
        "actor": "JAVIER_MBT",
        "fecha": "2026-08-19T20:41:55+00:00",
        "documento": {"numero_guia": numero_guia},
        "campo": campo,
        "valor_documental": valor_documental,
        "patente_canonica": patente_canonica,
    }


def test_ledger_propaga_patente_canonica_a_viajes_csv_sin_tocar_entrada(tmp_path):
    """T1 (integración): con `ruta_ledger`, `viajes.csv` publica la patente
    canónica ya decidida -- el CSV de entrada (evidencia documental)
    permanece byte a byte igual."""
    fila = _fila(patente_rampla="JD6659")
    origen = tmp_path / "entrada.csv"
    _escribir_csv(origen, [fila])
    contenido_antes = origen.read_bytes()

    ledger = tmp_path / "decisiones_aplicadas.json"
    _escribir_ledger(ledger, [
        _aplicacion_patente("000101", "patente_rampla", "JD6659", "JD8659"),
    ])

    salida = tmp_path / "reporte"
    generar_reporte_viajes(
        origen, salida, carpeta_catalogos=tmp_path / "catálogos",
        ruta_ledger=ledger, reloj=RELOJ,
    )
    assert origen.read_bytes() == contenido_antes
    viaje = _leer_csv(salida / "viajes.csv")[0]
    assert viaje["patentes_rampla"] == "JD8659"
    evidencias = json.loads(viaje["evidencias_documentos"])
    assert evidencias[0]["patente_rampla"] == "JD6659"


def test_ledger_resuelve_caso_real_0000351135(tmp_path):
    """T2 (integración) -- caso real: transporte 0000351135, guías
    464264/464265. Documentalmente traen variantes conflictivas de
    patente_rampla (JD6659/JD0659) y patente_tracto (VP8521/VP6521);
    Javier ya seleccionó JD8659/VP8521 como canónicas. `viajes.csv` debe
    publicar las canónicas -- nunca "JD0659 | JD6659" -- y el conflicto de
    patente correspondiente no debe seguir señalado como abierto."""
    filas = [
        _fila(
            archivo="464264.jpeg", numero_guia="464264", numero_transporte="0000351135",
            patente_tracto="VP8521", patente_rampla="JD6659",
        ),
        _fila(
            archivo="464265.jpeg", numero_guia="464265", numero_transporte="0000351135",
            patente_tracto="VP6521", patente_rampla="JD0659",
        ),
    ]
    origen = tmp_path / "entrada.csv"
    _escribir_csv(origen, filas)

    ledger = tmp_path / "decisiones_aplicadas.json"
    _escribir_ledger(ledger, [
        _aplicacion_patente("464264", "patente_rampla", "JD6659", "JD8659"),
        _aplicacion_patente("464265", "patente_rampla", "JD0659", "JD8659"),
        _aplicacion_patente(
            "464265", "patente_tracto", "VP6521", "VP8521", accion="USAR_PATENTE_EXISTENTE",
        ),
    ])

    salida = tmp_path / "reporte"
    generar_reporte_viajes(
        origen, salida, carpeta_catalogos=tmp_path / "catálogos",
        ruta_ledger=ledger, reloj=RELOJ,
    )
    viaje = _leer_csv(salida / "viajes.csv")[0]
    assert viaje["patentes_rampla"] == "JD8659"
    assert viaje["patentes_tracto"] == "VP8521"
    assert "CONFLICTO_PATENTE_RAMPLA" not in viaje["motivos_revision"]
    assert "CONFLICTO_PATENTE_TRACTO" not in viaje["motivos_revision"]


def test_sin_ruta_ledger_conserva_comportamiento_actual_t5(tmp_path):
    """T5: sin `ruta_ledger` (valor por defecto), el reporte es idéntico al
    de antes de este bloque -- ninguna regresión para quien no lo use."""
    filas = [
        _fila(archivo="464264.jpeg", numero_guia="464264", patente_rampla="JD6659"),
        _fila(archivo="464265.jpeg", numero_guia="464265", patente_rampla="JD0659"),
    ]
    _, salida, _ = _generar(tmp_path, filas)
    viaje = _leer_csv(salida / "viajes.csv")[0]
    assert viaje["patentes_rampla"] == "JD0659 | JD6659"
    assert "CONFLICTO_PATENTE_RAMPLA" in viaje["motivos_revision"]


def test_ledger_ausente_o_corrupto_no_bloquea_el_reporte(tmp_path):
    """Ausencia/corrupción del ledger se trata como "sin confirmaciones" --
    nunca bloquea ni cambia el resto del reporte."""
    _, salida, manifest = _generar(tmp_path, [_fila()])  # sin ruta_ledger
    assert manifest["totales"]["viajes"] == 1

    origen = tmp_path / "entrada2.csv"
    _escribir_csv(origen, [_fila()])
    ledger_corrupto = tmp_path / "decisiones_aplicadas_corrupto.json"
    ledger_corrupto.write_text("{ esto no es json", encoding="utf-8")
    manifest2 = generar_reporte_viajes(
        origen, tmp_path / "reporte2", carpeta_catalogos=tmp_path / "catálogos",
        ruta_ledger=ledger_corrupto, reloj=RELOJ,
    )
    assert manifest2["totales"]["viajes"] == 1
