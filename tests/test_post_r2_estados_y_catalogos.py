import csv
from types import SimpleNamespace

from atlas_core.catalogo_fichas import construir_ficha_vehiculo
from atlas_core.gestor_viajes import EstadoViaje, agrupar_viajes
from atlas_core.procesamiento_masivo import COLUMNAS


def _fila(**cambios):
    fila = {
        "archivo": "1.jpeg", "numero_guia": "1", "numero_transporte": "100",
        "fecha": "31-08-2026", "indicador_revision": "OK",
        "estado_operacional": "OK", "estado_ruta": "RUTA_CALCULADA",
    }
    fila.update(cambios)
    return fila


def _vehiculo(*, calidad):
    return SimpleNamespace(
        vehiculo_id="v1", patente_canonica="AL1879", tipo="TRACTO",
        estado_calidad=calidad, estado_vigencia="ACTIVO", aliases=(),
        procedencia="CATALOGO_LEGACY", confirmado_por="",
    )


def test_catalogo_confirmado_sin_viajes_sigue_confirmado():
    vehiculo = _vehiculo(calidad="CONFIRMADO")
    ficha = construir_ficha_vehiculo(
        vehiculo=vehiculo, filas=[], vehiculos_por_patente={"AL1879": vehiculo},
    )
    assert ficha["guias_relacionadas"] == []
    assert ficha["clasificacion_visual"] == "CONFIRMADO"


def test_catalogo_observado_sin_viajes_sigue_por_verificar():
    vehiculo = _vehiculo(calidad="OBSERVADO")
    ficha = construir_ficha_vehiculo(
        vehiculo=vehiculo, filas=[], vehiculos_por_patente={"AL1879": vehiculo},
    )
    assert ficha["clasificacion_visual"] == "OBSERVADO"


def test_fallo_tecnico_sin_decision_no_es_ok_ni_revision_humana():
    viajes, _ = agrupar_viajes([
        _fila(estado_operacional="REQUIERE_REVISION", estado_ruta="REQUIERE_REVISION",
              motivo_ruta="MULTIPLES_UBICACIONES_DISPERSAS(5)"),
    ], guias_revision_humana=set())
    assert viajes[0].estado == EstadoViaje.INCOMPLETO_TECNICO


def test_problema_humano_con_decision_es_revision():
    viajes, _ = agrupar_viajes([
        _fila(estado_operacional="REQUIERE_REVISION", estado_ruta="REQUIERE_REVISION",
              motivo_ruta="DESTINO_SIN_DATO"),
    ], guias_revision_humana={"1"})
    assert viajes[0].estado == EstadoViaje.REQUIERE_REVISION


def test_resuelto_es_confirmado():
    viajes, _ = agrupar_viajes([_fila()], guias_revision_humana=set())
    assert viajes[0].estado == EstadoViaje.CONFIRMADO


def test_motivo_destino_confirmado_se_reconcilia(tmp_path, monkeypatch):
    from atlas_core import revalidacion_documental as modulo

    class CatalogoFalso:
        def __init__(self, **_kwargs):
            pass

        def listar_destinos_confirmados_para_obra(self, *, nombre_obra):
            assert nombre_obra == "OBRA CONFIRMADA"
            return [SimpleNamespace(direccion="URUGUAY 15, LA CISTERNA")]

    monkeypatch.setattr(modulo, "CatalogoObrasDestinos", CatalogoFalso)
    fila = {c: "" for c in COLUMNAS}
    fila.update(_fila(
        numero_guia="464491", obra_destino="OBRA CONFIRMADA",
        despachar_a_crudo="URUGUAY 15 SANTIAGO LA CISTERNA",
        motivos_revision_documento="DESTINO_CONTAMINADO_POR_OTRA_SECCION",
        indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION",
        estado_operacional="REQUIERE_REVISION",
    ))
    ruta = tmp_path / "dataset.csv"
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerow(fila)

    resultado = modulo.revalidar_motivo_destino_ya_confirmado_sin_ocr(
        ruta_dataset=ruta, carpeta_catalogos=tmp_path,
    )
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        final = next(csv.DictReader(archivo, delimiter=";"))
    assert resultado["guias_actualizadas"] == ["464491"]
    assert final["motivos_revision_documento"] == ""
    assert final["indicador_revision"] == "OK"
    assert final["estado_operacional"] == "OK"


def _entorno_catalogos_reales(tmp_path, *, obras=(), relaciones=(), destinos=()):
    """Catálogos REALES (nunca un doble simulado) -- para probar sin
    ambigüedad que la corroboración por ruta ya calculada NO depende de
    ningún registro en `obras_destinos.json`/`destinos_maestros.json`."""
    import json
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "clientes.json").write_text(json.dumps({"version_formato": 1, "clientes": []}), encoding="utf-8")
    (tmp_path / "destinos_maestros.json").write_text(json.dumps({"version_formato": 1, "destinos": list(destinos)}), encoding="utf-8")
    (tmp_path / "obras_destinos.json").write_text(
        json.dumps({"version_formato": 1, "obras": list(obras), "relaciones": list(relaciones)}), encoding="utf-8",
    )
    return tmp_path


def test_motivo_destino_se_retira_por_ruta_ya_calculada_sin_ningun_destino_en_catalogo(tmp_path):
    """Bloque RECONCILIACIÓN POST-DECISIÓN -- caso real 472640 (DSI
    UNDERGROUND CHILE SPA): Javier confirmó "LAS VIOLETAS 55" vía
    REGISTRAR_DIRECCION y el routing posterior fue exitoso
    (`estado_ruta=RUTA_CALCULADA`), pero `aplicar_decision_obra` sólo
    aprende un destino de catálogo reutilizable cuando la obra YA existía
    como registro previo -- para una obra vista por PRIMERA vez (sin
    ninguna obra/destino/relación en catálogo, verificado con catálogos
    REALES y vacíos), la vía de catálogo nunca puede corroborar nada. El
    motivo debe retirarse igual: la propia ruta ya calculada, para el
    `despachar_a_crudo` vigente, ya es evidencia suficiente de que la
    lectura documental no está contaminada."""
    from atlas_core import revalidacion_documental as modulo

    catalogos = _entorno_catalogos_reales(tmp_path / "catalogos")
    fila = {c: "" for c in COLUMNAS}
    fila.update(_fila(
        numero_guia="472640", cliente="DSI UNDERGROUND CHILE SPA", obra_destino="DSI UNDERGROUND CHILE SPA",
        despachar_a_crudo="LAS VIOLETAS 55", direccion_entrega="LAS VIOLETAS 55",
        estado_ruta="RUTA_CALCULADA", distancia_km="48.5764", duracion_min="62.425",
        motivos_revision_documento="DESTINO_CONTAMINADO_POR_OTRA_SECCION",
        indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION",
        estado_operacional="REQUIERE_REVISION",
    ))
    ruta = tmp_path / "dataset.csv"
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerow(fila)

    resultado = modulo.revalidar_motivo_destino_ya_confirmado_sin_ocr(
        ruta_dataset=ruta, carpeta_catalogos=catalogos,
    )
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        final = next(csv.DictReader(archivo, delimiter=";"))
    assert resultado["guias_actualizadas"] == ["472640"]
    assert final["motivos_revision_documento"] == ""
    assert final["indicador_revision"] == "OK"
    assert final["estado_documental"] == "OK"
    assert final["estado_operacional"] == "OK"
    # Nunca toca lo que ya estaba resuelto -- ruta/dirección intactas.
    assert final["estado_ruta"] == "RUTA_CALCULADA"
    assert final["despachar_a_crudo"] == "LAS VIOLETAS 55"


def test_motivo_destino_se_preserva_si_la_ruta_sigue_sin_calcular_y_sin_catalogo():
    """Control (criterio explícito: preservar el motivo cuando el destino
    REALMENTE siga sin resolver) -- misma obra nunca antes vista, mismo
    catálogo vacío, pero `estado_ruta` NO es `RUTA_CALCULADA` (el
    problema documental sigue sin corroborar por ninguna vía) -- el
    motivo NUNCA se retira a ciegas."""
    from atlas_core import revalidacion_documental as modulo

    fila = {c: "" for c in COLUMNAS}
    fila.update(_fila(
        numero_guia="472641", obra_destino="OBRA NUEVA NUNCA VISTA",
        despachar_a_crudo="CALLE AMBIGUA 100",
        estado_ruta="REQUIERE_REVISION", motivo_ruta="CONFIANZA_INSUFICIENTE",
        motivos_revision_documento="DESTINO_CONTAMINADO_POR_OTRA_SECCION",
        indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION",
        estado_operacional="REQUIERE_REVISION",
    ))
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        from pathlib import Path
        tmp_path = Path(tmp)
        catalogos = _entorno_catalogos_reales(tmp_path / "catalogos")
        ruta = tmp_path / "dataset.csv"
        with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
            escritor.writeheader(); escritor.writerow(fila)

        resultado = modulo.revalidar_motivo_destino_ya_confirmado_sin_ocr(
            ruta_dataset=ruta, carpeta_catalogos=catalogos,
        )
        with ruta.open(encoding="utf-8-sig", newline="") as archivo:
            final = next(csv.DictReader(archivo, delimiter=";"))
        assert resultado["guias_actualizadas"] == []
        assert final["motivos_revision_documento"] == "DESTINO_CONTAMINADO_POR_OTRA_SECCION"
        assert final["indicador_revision"] == "REVISAR"
