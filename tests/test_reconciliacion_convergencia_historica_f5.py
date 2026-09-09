"""Bloque AUTORIDAD OPERACIONAL -- Fase 5: la convergencia y la segunda
pasada universal se aplican también a una operación HISTÓRICA en la
reconciliación (`reconciliar_estado_derivado`), SIN OCR y SIN red -- no
sólo durante la ingesta de un lote nuevo.

Causa raíz real: la 19 sólo cableó esas reglas en `procesar_carpeta`.
Al abrir Desktop, `reconciliar_estado_derivado` NO las invocaba (y además
`reconciliar_bandeja_decisiones` abortaba TODA la reconciliación al
intentar auto-aplicar `USAR_PATENTE_EXISTENTE` sobre una decisión con dos
candidatos -- caso real 472477: JD8659 confirmada + JE8659 con transporte
independiente real).
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.procesamiento_masivo import COLUMNAS, revalidar_convergencia_identidad_sin_ocr


def _rut(cuerpo: str) -> str:
    suma = sum(int(d) * f for d, f in zip(reversed(cuerpo), (2, 3, 4, 5, 6, 7) * 3))
    resto = 11 - suma % 11
    dv = "0" if resto == 11 else "K" if resto == 10 else str(resto)
    return f"{cuerpo}-{dv}"


def _cat(tmp_path):
    c = tmp_path / "catalogos"
    c.mkdir()
    return c


def _cliente(cat, *, razon_social, rut, fuente="CONFIRMACION_USUARIO"):
    return CatalogoClientes(cat / "clientes.json").crear(
        razon_social=razon_social, rut=rut, fuente=fuente,
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )


def _fila(**ov):
    fila = {c: "" for c in COLUMNAS}
    fila.update({"archivo": "g1.jpeg", "estado_procesamiento": "OK", "numero_guia": "900001",
                 "numero_transporte": "T-1", "indicador_revision": "REVISAR",
                 "estado_documental": "REQUIERE_REVISION"})
    fila.update(ov)
    return fila


def _csv(tmp_path, filas):
    ruta = tmp_path / "analisis_completo_guias.csv"
    with ruta.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)
    return ruta


# ==========================================================================
# revalidar_convergencia_identidad_sin_ocr
# ==========================================================================


def test_convergencia_sin_ocr_resuelve_cliente_en_fila_en_revision(tmp_path):
    cat = _cat(tmp_path)
    _cliente(cat, razon_social="PRODALAM SA", rut="93.772.000-9")
    ruta = _csv(tmp_path, [_fila(cliente="PRODALAM SA", rut_cliente="No encontrado",
                                 motivos_revision_documento="CLIENTE_SIN_CORROBORAR")])
    r = revalidar_convergencia_identidad_sin_ocr(ruta_dataset=ruta, carpeta_catalogos=cat)
    assert r["filas_convergidas"] == 1
    with ruta.open(encoding="utf-8-sig") as f:
        fila = next(csv.DictReader(f, delimiter=";"))
    assert fila["rut_cliente"] == "93772000-9"  # RUT canónico materializado
    assert "CLIENTE_SIN_CORROBORAR" not in fila["motivos_revision_documento"]
    assert fila["indicador_revision"] == "OK"
    # OCR original conservado en la auditoría
    met = json.loads(fila["metricas_procesamiento_json"])
    assert any(x["campo"] == "cliente" for x in met["resoluciones_convergentes"])


def test_convergencia_sin_ocr_no_toca_filas_ok(tmp_path):
    cat = _cat(tmp_path)
    _cliente(cat, razon_social="TERRATEC LIMITADA", rut=_rut("76543210"))
    # Fila OK con un alias ya reconocido -> NUNCA se reescribe a canónico.
    ruta = _csv(tmp_path, [_fila(cliente="TERRATEC LTDA", rut_cliente=_rut("76543210"),
                                 indicador_revision="OK", estado_documental="OK",
                                 motivos_revision_documento="")])
    antes = ruta.read_text(encoding="utf-8-sig")
    r = revalidar_convergencia_identidad_sin_ocr(ruta_dataset=ruta, carpeta_catalogos=cat)
    assert r["filas_convergidas"] == 0
    assert ruta.read_text(encoding="utf-8-sig") == antes


def test_convergencia_sin_ocr_es_idempotente(tmp_path):
    cat = _cat(tmp_path)
    _cliente(cat, razon_social="PRODALAM SA", rut="93.772.000-9")
    ruta = _csv(tmp_path, [_fila(cliente="PRODALAM SA", rut_cliente="No encontrado",
                                 motivos_revision_documento="CLIENTE_SIN_CORROBORAR")])
    revalidar_convergencia_identidad_sin_ocr(ruta_dataset=ruta, carpeta_catalogos=cat)
    tras_uno = ruta.read_text(encoding="utf-8-sig")
    r2 = revalidar_convergencia_identidad_sin_ocr(ruta_dataset=ruta, carpeta_catalogos=cat)
    assert r2["filas_convergidas"] == 0
    assert ruta.read_text(encoding="utf-8-sig") == tras_uno


def test_convergencia_sin_ocr_ignora_esquema_incompatible(tmp_path):
    cat = _cat(tmp_path)
    ruta = tmp_path / "analisis_completo_guias.csv"
    ruta.write_text("otra;cosa\n1;2\n", encoding="utf-8-sig")
    r = revalidar_convergencia_identidad_sin_ocr(ruta_dataset=ruta, carpeta_catalogos=cat)
    assert r["filas_convergidas"] == 0  # nunca lanza


def test_convergencia_sin_ocr_no_resuelve_nombre_ambiguo(tmp_path):
    cat = _cat(tmp_path)
    _cliente(cat, razon_social="COMERCIAL ANDES SPA", rut=_rut("76222222"))
    _cliente(cat, razon_social="COMERCIAL ANDES LIMITADA", rut=_rut("77333333"))
    ruta = _csv(tmp_path, [_fila(cliente="COMERCIAL ANDE", rut_cliente="No encontrado",
                                 motivos_revision_documento="CLIENTE_SIN_CORROBORAR")])
    r = revalidar_convergencia_identidad_sin_ocr(ruta_dataset=ruta, carpeta_catalogos=cat)
    assert r["filas_convergidas"] == 0  # nunca "cualquier nombre parecido"


# ==========================================================================
# reconciliar_bandeja_decisiones -- guarda contra el crash de multi-candidato
# ==========================================================================


def test_reconciliar_bandeja_autoaplica_vehiculo_con_ganadora_unica_de_nivel(tmp_path):
    """El crash real: `USAR_PATENTE_EXISTENTE` sobre una decisión con dos
    candidatos abortaba toda la reconciliación. Nunca vuelve a lanzar.

    Bloque VEHÍCULO E3 -- además, cuando hay un ÚNICO candidato en el
    NIVEL MÁS ALTO (JD8659 con confirmación humana asociada al RUT) y el
    resto queda un tier por debajo (JE8659, un transporte independiente),
    la reconciliación auto-aplica la ganadora vía `SELECCIONAR_OTRA_
    PATENTE` -- ya no se conserva la tarjeta para Javier. Dos candidatos
    EMPATADOS en el nivel más alto sí se conservarían (ver
    `test_..._empate_en_nivel_conserva_tarjeta`)."""
    from atlas_core.catalogo_vehiculos import TipoVehiculo, confirmar_vehiculo
    from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
    from atlas_core.revalidacion_documental import reconciliar_bandeja_decisiones

    raiz = tmp_path
    cat = raiz / "catalogos_privados"
    cat.mkdir()
    actual = raiz / "operacion" / "actual"
    actual.mkdir(parents=True)
    for nombre in ("empresas.json", "choferes.json", "rutas.json"):
        (cat / nombre).write_text("{}", encoding="utf-8")
    (cat / "vehiculos.json").write_text(json.dumps({"version": 1, "vehiculos": []}), encoding="utf-8")
    confirmar_vehiculo(cat / "vehiculos.json", patente="JD8659", tipo=TipoVehiculo.CARRO,
                       actor="JAVIER", fuente_decision="T", fecha=datetime.now(timezone.utc),
                       rut_chofer_asociado="15489424-1")
    confirmar_vehiculo(cat / "vehiculos.json", patente="JE8659", tipo=TipoVehiculo.CARRO,
                       actor="JAVIER", fuente_decision="T", fecha=datetime.now(timezone.utc))
    CatalogoClientes(cat / "clientes.json")  # archivo se crea al escribir; basta ruta

    filas = [
        _fila(rut_chofer="15489424-1", chofer="CARLOS SIMON", patente_rampla="JD8629",
              archivo="472477.jpeg", numero_guia="472477", numero_transporte="0000354870",
              fecha="05-08-2026", estado_procesamiento="OK", indicador_revision="REVISAR"),
        # historial real del mismo chofer con JE8659 (transporte independiente)
        # -> dos candidatos plausibles para `evaluar_evidencia_patente`.
        _fila(rut_chofer="15489424-1", chofer="CARLOS SIMON", patente_rampla="JE8659",
              archivo="464698.jpeg", numero_guia="464698", numero_transporte="0000352376",
              fecha="20-07-2026", estado_procesamiento="OK", indicador_revision="OK"),
        _fila(rut_chofer="15489424-1", chofer="CARLOS SIMON", patente_rampla="JE8659",
              archivo="464700.jpeg", numero_guia="464700", numero_transporte="0000352376",
              fecha="20-07-2026", estado_procesamiento="OK", indicador_revision="OK"),
    ]
    _csv_ruta = actual / "analisis_completo_guias.csv"
    with _csv_ruta.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";", extrasaction="ignore")
        w.writeheader(); w.writerows(filas)

    decision = crear_decision(
        tipo="VEHICULO_DESCONOCIDO", entidad="VEHICULO", archivo="g1.jpeg",
        numero_guia="472477", numero_transporte="0000354870", campo="patente_rampla",
        valor_documental="JD8629", valor_normalizado="JD8629", identidad_resuelta=None,
        candidatos=(
            {"patente": "JD8659", "nivel": "CONFIRMACION_HUMANA"},
            {"patente": "JE8659", "nivel": "DOCUMENTAL_INDEPENDIENTE"},
        ),
        motivos=("SIN_VEHICULO_CONFIRMADO_COMPATIBLE",), evidencias=(),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        tipo_resolucion="REQUIERE_CONFIRMACION_HUMANA", tipo_vehiculo_propuesto=None,
    )
    generar_artefacto(
        ruta_dataset=_csv_ruta, carpeta_catalogos=cat, decisiones=[decision],
        ruta_salida=actual / "decisiones_pendientes.json",
        reloj=lambda: datetime.now(timezone.utc),
    )

    # No debe lanzar (antes: ErrorAplicacionDecision -> aborta todo).
    r = reconciliar_bandeja_decisiones(raiz_atlas=raiz)
    aplicadas = r["decisiones_aplicadas_automaticamente"]
    assert len(aplicadas) == 1
    assert aplicadas[0]["patente_canonica"] == "JD8659"
    tipos = {d["tipo"] for d in r["bandeja"]["decisiones"]}
    assert "VEHICULO_DESCONOCIDO" not in tipos  # ganadora única de nivel -> resuelta

    ledger = json.loads((actual / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    ap = ledger["aplicaciones"][-1]
    assert ap["accion"] == "SELECCIONAR_OTRA_PATENTE"
    assert ap["patente_canonica"] == "JD8659"
    assert ap["actor"] == "ATLAS_AUTOMATICO"  # auditable / distinguible de un humano


def test_reconciliar_bandeja_conserva_tarjeta_con_empate_en_nivel_mas_alto(tmp_path):
    """Bloque VEHÍCULO E3 -- dos candidatos EMPATADOS en el nivel más alto
    (ambas confirmadas por un humano para el mismo RUT) -> no hay ganadora
    única -> la tarjeta se conserva para Javier ("dos plausibles ->
    preguntar"). La reconciliación tampoco lanza."""
    from atlas_core.catalogo_vehiculos import TipoVehiculo, confirmar_vehiculo
    from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
    from atlas_core.revalidacion_documental import reconciliar_bandeja_decisiones

    raiz = tmp_path
    cat = raiz / "catalogos_privados"
    cat.mkdir()
    actual = raiz / "operacion" / "actual"
    actual.mkdir(parents=True)
    for nombre in ("empresas.json", "choferes.json", "rutas.json"):
        (cat / nombre).write_text("{}", encoding="utf-8")
    (cat / "vehiculos.json").write_text(json.dumps({"version": 1, "vehiculos": []}), encoding="utf-8")
    for patente in ("JD8659", "JD8658"):
        confirmar_vehiculo(cat / "vehiculos.json", patente=patente, tipo=TipoVehiculo.CARRO,
                           actor="JAVIER", fuente_decision="T", fecha=datetime.now(timezone.utc),
                           rut_chofer_asociado="15489424-1")
    CatalogoClientes(cat / "clientes.json")

    filas = [
        _fila(rut_chofer="15489424-1", chofer="CARLOS SIMON", patente_rampla="JD8629",
              archivo="472477.jpeg", numero_guia="472477", numero_transporte="0000354870",
              fecha="05-08-2026", estado_procesamiento="OK", indicador_revision="REVISAR"),
    ]
    _csv_ruta = actual / "analisis_completo_guias.csv"
    with _csv_ruta.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";", extrasaction="ignore")
        w.writeheader(); w.writerows(filas)

    decision = crear_decision(
        tipo="VEHICULO_DESCONOCIDO", entidad="VEHICULO", archivo="g1.jpeg",
        numero_guia="472477", numero_transporte="0000354870", campo="patente_rampla",
        valor_documental="JD8629", valor_normalizado="JD8629", identidad_resuelta=None,
        candidatos=(
            {"patente": "JD8659", "nivel": "CONFIRMACION_HUMANA"},
            {"patente": "JD8658", "nivel": "CONFIRMACION_HUMANA"},
        ),
        motivos=("SIN_VEHICULO_CONFIRMADO_COMPATIBLE",), evidencias=(),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        tipo_resolucion="REQUIERE_CONFIRMACION_HUMANA", tipo_vehiculo_propuesto="CARRO",
    )
    generar_artefacto(
        ruta_dataset=_csv_ruta, carpeta_catalogos=cat, decisiones=[decision],
        ruta_salida=actual / "decisiones_pendientes.json",
        reloj=lambda: datetime.now(timezone.utc),
    )

    r = reconciliar_bandeja_decisiones(raiz_atlas=raiz)
    assert not r["decisiones_aplicadas_automaticamente"]
    tipos = {d["tipo"] for d in r["bandeja"]["decisiones"]}
    assert "VEHICULO_DESCONOCIDO" in tipos  # empate -> se conserva
