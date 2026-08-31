"""Bloque CATALOGOS V2 -- fichas completas de entidades, READ-ONLY.
Caso real que motivó el bloque: al buscar WLADIMIR AGUILAR, Javier no
podía ver su RUT ni el resto de la información operacional que Atlas
ya conocía (la pestaña Catálogos sólo mostraba nombres). Cubre la
construcción de fichas de chofer/cliente/obra/vehículo a partir de
catálogos + histórico documental ya persistido -- nunca inventa,
nunca elige en silencio entre valores conflictivos, nunca llama a B1."""
from __future__ import annotations

from datetime import datetime, timezone

from atlas_core.catalogo_clientes import Cliente
from atlas_core.catalogo_destinos import Destino
from atlas_core.catalogo_fichas import (
    _resumen_rut_historico,
    _vehiculos_plegables_por_confusion_ocr,
    construir_ficha_chofer,
    construir_ficha_cliente,
    construir_ficha_obra,
    construir_ficha_vehiculo,
    construir_snapshot_fichas,
)
from atlas_core.catalogo_obras_destinos import Obra
from atlas_core.catalogo_vehiculos import EvidenciaVehiculo, Vehiculo
from atlas_core.procesamiento_masivo import COLUMNAS

FECHA = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()


def _fila(**cambios):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "1.jpeg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "T-1", "fecha": "18-08-2026", "chofer": "PERSONA EJEMPLO",
        "rut_chofer": "12.345.678-5", "cliente": "CLIENTE EJEMPLO", "obra_destino": "OBRA EJEMPLO",
        "patente_tracto": "AB1234", "patente_rampla": "CD5678",
        "planta_origen_nombre": "AZA COLINA",
    })
    fila.update(cambios)
    return fila


def _vehiculo(patente="AB1234", tipo="TRACTO", estado_calidad="CONFIRMADO", procedencia="TEST", confirmado_por=""):
    return Vehiculo(
        vehiculo_id=f"v-{patente}", patente_canonica=patente, tipo=tipo,
        estado_calidad=estado_calidad, estado_vigencia="ACTIVO", aliases=(), evidencias=(),
        procedencia=procedencia, confirmado_por=confirmado_por, fecha_confirmacion="",
        observaciones="", fecha_creacion=FECHA, fecha_modificacion=FECHA,
    )


# ============================================================
# RUT observado vs confirmado vs conflicto (Sección 3/11)
# ============================================================


def test_rut_sin_ningun_dato_valido_en_el_historico():
    resumen = _resumen_rut_historico([_fila(rut_chofer="No encontrado")], campo_rut="rut_chofer")
    assert resumen["estado"] == "SIN_DATO"
    assert resumen["valor"] is None


def test_rut_observado_historico_cuando_es_consistente():
    filas = [_fila(rut_chofer="55.555.555-5"), _fila(rut_chofer="55.555.555-5")]
    # RUT documentalmente inválido (cuerpo repetido) -- nunca cuenta como válido.
    resumen = _resumen_rut_historico(filas, campo_rut="rut_chofer")
    assert resumen["estado"] == "SIN_DATO"

    filas_validas = [_fila(rut_chofer="26.646.499-1"), _fila(rut_chofer="26.646.499-1")]
    resumen_valido = _resumen_rut_historico(filas_validas, campo_rut="rut_chofer")
    assert resumen_valido["estado"] == "OBSERVADO_HISTORICO"
    assert resumen_valido["valor"] == "26.646.499-1"
    assert resumen_valido["candidatos"][0]["apariciones"] == 2


def test_conflicto_nunca_elige_en_silencio_entre_dos_ruts_validos_distintos():
    filas = [_fila(rut_chofer="26.646.499-1"), _fila(rut_chofer="12.345.678-5")]
    resumen = _resumen_rut_historico(filas, campo_rut="rut_chofer")
    assert resumen["estado"] == "CONFLICTO"
    assert resumen["valor"] is None
    valores = {c["valor"] for c in resumen["candidatos"]}
    assert valores == {"26.646.499-1", "12.345.678-5"}


def test_ficha_chofer_con_rut_confirmado_en_catalogo_no_depende_del_historico():
    ficha = construir_ficha_chofer(
        identificador="123456785",  # RUT confirmado como identificador (no PENDIENTE)
        registro_catalogo={"nombre": "PERSONA EJEMPLO", "activo": True, "aliases": []},
        filas=[_fila(rut_chofer="55.555.555-5")],  # histórico inválido -- irrelevante, ya está confirmado
        vehiculos_por_patente={},
    )
    assert ficha["rut"]["estado"] == "CONFIRMADO"
    assert ficha["rut"]["valor"] == "12.345.678-5"


def test_ficha_chofer_pendiente_muestra_observado_historico_nunca_finge_confirmado():
    """Caso real Wladimir Aguilar: catálogo sin RUT confirmado, pero el
    dataset tiene un RUT operacional consistente -- se muestra como
    OBSERVADO_HISTORICO, nunca oculto ni fingido como CONFIRMADO."""
    filas = [_fila(chofer="WLADIMIR AGUILAR", rut_chofer="26.646.499-1", numero_guia="1")] * 3
    ficha = construir_ficha_chofer(
        identificador="PENDIENTE00000006",
        registro_catalogo={"nombre": "WLADIMIR AGUILAR", "activo": True, "aliases": ["WLADIKIR AGUILAR"]},
        filas=filas, vehiculos_por_patente={},
    )
    assert ficha["rut"]["estado"] == "OBSERVADO_HISTORICO"
    assert ficha["rut"]["valor"] == "26.646.499-1"


# ============================================================
# Múltiples vehículos (Sección 4) -- nunca "una patente fija"
# ============================================================


def test_chofer_con_multiples_vehiculos_muestra_todos_sin_borrar_historico():
    filas = [
        _fila(numero_guia="1", numero_transporte="T-1", patente_tracto="AB1234", patente_rampla=""),
        _fila(numero_guia="2", numero_transporte="T-2", patente_tracto="AB1234", patente_rampla=""),
        _fila(numero_guia="3", numero_transporte="T-3", patente_tracto="ZZ9999", patente_rampla=""),
    ]
    vehiculos_por_patente = {"AB1234": _vehiculo("AB1234"), "ZZ9999": _vehiculo("ZZ9999")}
    ficha = construir_ficha_chofer(
        identificador="PENDIENTE00000001",
        registro_catalogo={"nombre": "PERSONA EJEMPLO", "activo": True, "aliases": []},
        filas=filas, vehiculos_por_patente=vehiculos_por_patente,
    )
    patentes = {v["patente"] for v in ficha["vehiculos"]}
    assert patentes == {"AB1234", "ZZ9999"}
    ab1234 = next(v for v in ficha["vehiculos"] if v["patente"] == "AB1234")
    assert ab1234["apariciones"] == 2
    assert ab1234["estado_catalogo"] == "CONFIRMADO"
    zz9999 = next(v for v in ficha["vehiculos"] if v["patente"] == "ZZ9999")
    assert zz9999["apariciones"] == 1
    # El más frecuente aparece primero -- pero ninguno se oculta.
    assert ficha["vehiculos"][0]["patente"] == "AB1234"


def test_patente_confusion_ocr_de_una_canonica_confirmada_se_pliega_nunca_es_un_segundo_vehiculo():
    # Caso real 472339, Cristopher Retamal: BPHF67 es BPHR67 mal leído
    # por OCR (F/R), no un segundo tracto real.
    filas = [
        _fila(numero_guia="1", numero_transporte="T-1", chofer="CRISTOPHER RETAMAL", patente_tracto="BPHR67", patente_rampla=""),
        _fila(numero_guia="2", numero_transporte="T-2", chofer="CRISTOPHER RETAMAL", patente_tracto="BPHR67", patente_rampla=""),
        _fila(numero_guia="3", numero_transporte="T-3", chofer="CRISTOPHER RETAMAL", patente_tracto="BPHF67", patente_rampla=""),
    ]
    vehiculos_por_patente = {"BPHR67": _vehiculo("BPHR67")}
    ficha = construir_ficha_chofer(
        identificador="175761349",
        registro_catalogo={"nombre": "CRISTOPHER RETAMAL", "activo": True, "aliases": []},
        filas=filas, vehiculos_por_patente=vehiculos_por_patente,
    )
    assert len(ficha["vehiculos"]) == 1
    assert ficha["vehiculos"][0]["patente"] == "BPHR67"
    assert ficha["vehiculos"][0]["apariciones"] == 3
    assert ficha["vehiculos"][0]["estado_catalogo"] == "CONFIRMADO"


def test_patente_confusion_ocr_ambigua_entre_dos_canonicas_nunca_se_pliega_en_silencio():
    # Si BPHF67 pudiera confundirse con dos patentes canónicas distintas,
    # nunca se elige una -- se muestra tal cual, sin catalogar.
    filas = [_fila(numero_guia="1", patente_tracto="BPHF67", patente_rampla="")]
    vehiculos_por_patente = {"BPHR67": _vehiculo("BPHR67"), "BPHE67": _vehiculo("BPHE67")}
    ficha = construir_ficha_chofer(
        identificador="PENDIENTE00000003",
        registro_catalogo={"nombre": "PERSONA EJEMPLO", "activo": True, "aliases": []},
        filas=filas, vehiculos_por_patente=vehiculos_por_patente,
    )
    assert len(ficha["vehiculos"]) == 1
    assert ficha["vehiculos"][0]["patente"] == "BPHF67"
    assert ficha["vehiculos"][0]["estado_catalogo"] == "SIN_CATALOGAR"


def test_vehiculo_canonico_sin_evidencia_vigente_que_es_ocr_de_otro_con_evidencia_se_pliega():
    # Caso real: "BKYX63" existe como vehículo CONFIRMADO/ACTIVO en el
    # catálogo (migración legacy) pero ninguna guía del histórico
    # vigente lo documenta; "BKYK63" sí tiene evidencia real (LEANDRO
    # TOLEDO) y es su única confusión OCR posible (K/X) -- se pliega,
    # nunca se lista como vehículo aparte.
    filas = [
        _fila(numero_guia="1", chofer="LEANDRO TOLEDO", patente_tracto="BKYK63", patente_rampla=""),
        _fila(numero_guia="2", chofer="LEANDRO TOLEDO", patente_tracto="BKYK63", patente_rampla=""),
    ]
    vehiculos_por_patente = {"BKYK63": _vehiculo("BKYK63"), "BKYX63": _vehiculo("BKYX63")}
    plegables = _vehiculos_plegables_por_confusion_ocr(vehiculos_por_patente, filas)
    assert plegables == {"BKYX63"}


def test_vehiculo_canonico_ambiguo_nunca_se_pliega_en_silencio():
    # "BPHF67" (sin evidencia vigente propia) es una confusión OCR válida
    # de DOS canónicas distintas con evidencia real -- "BPHR67" (F/R) y
    # "BPHE67" (F/E) -- nunca se pliega ninguna ante esa ambigüedad.
    filas = [
        _fila(numero_guia="1", chofer="A", patente_tracto="BPHR67", patente_rampla=""),
        _fila(numero_guia="2", chofer="B", patente_tracto="BPHE67", patente_rampla=""),
    ]
    vehiculos_por_patente = {
        "BPHR67": _vehiculo("BPHR67"), "BPHE67": _vehiculo("BPHE67"), "BPHF67": _vehiculo("BPHF67"),
    }
    plegables = _vehiculos_plegables_por_confusion_ocr(vehiculos_por_patente, filas)
    assert plegables == set()


def test_vehiculo_canonico_con_evidencia_vigente_propia_nunca_se_pliega_aunque_se_parezca_a_otro():
    # Si "BKYX63" SÍ tuviera su propia evidencia real en el vigente,
    # nunca se pliega -- podría ser un vehículo real distinto.
    filas = [
        _fila(numero_guia="1", chofer="LEANDRO TOLEDO", patente_tracto="BKYK63", patente_rampla=""),
        _fila(numero_guia="2", chofer="OTRO CHOFER", patente_tracto="BKYX63", patente_rampla=""),
    ]
    vehiculos_por_patente = {"BKYK63": _vehiculo("BKYK63"), "BKYX63": _vehiculo("BKYX63")}
    plegables = _vehiculos_plegables_por_confusion_ocr(vehiculos_por_patente, filas)
    assert plegables == set()


def test_snapshot_de_vehiculos_excluye_los_plegados_pero_mantiene_la_canonica():
    from atlas_core.catalogo_fichas import construir_snapshot_fichas
    import json
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        raiz = Path(tmp)
        (raiz / "operacion" / "actual").mkdir(parents=True)
        (raiz / "catalogos_privados").mkdir(parents=True)
        filas = [
            _fila(numero_guia="1", chofer="LEANDRO TOLEDO", rut_chofer="18.611.137-0", patente_tracto="BKYK63", patente_rampla=""),
            _fila(numero_guia="2", chofer="LEANDRO TOLEDO", rut_chofer="18.611.137-0", patente_tracto="BKYK63", patente_rampla=""),
        ]
        import csv
        with (raiz / "operacion" / "actual" / "analisis_completo_guias.csv").open("w", newline="", encoding="utf-8-sig") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
            escritor.writeheader()
            escritor.writerows(filas)
        (raiz / "catalogos_privados" / "choferes.json").write_text("{}", encoding="utf-8")

        def _vehiculo_legacy(patente):
            # Mismo formato que la migración legacy real (CONFIRMADO sin
            # confirmación humana puntual -- ver `procedencia`/evidencia
            # de migración, igual que catalogos_privados/vehiculos.json
            # real).
            return {
                "vehiculo_id": f"v-{patente}", "patente_canonica": patente, "tipo": "TRACTO",
                "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO", "aliases": [],
                "evidencias": [{
                    "tipo": "MIGRACION_LEGACY", "identificador_fuente": "vehiculos.json",
                    "referencia_hash": "x", "campos_observados": {"patente": patente, "tipo": "TRACTO"},
                    "fecha": FECHA, "actor_proceso": "PROCESO_MIGRACION", "resultado": "SOPORTA",
                }],
                "procedencia": "CATALOGO_LEGACY", "confirmado_por": "", "fecha_confirmacion": "",
                "observaciones": "", "fecha_creacion": FECHA, "fecha_modificacion": FECHA,
            }
        (raiz / "catalogos_privados" / "vehiculos.json").write_text(json.dumps({
            "version": 1,
            "vehiculos": [_vehiculo_legacy("BKYK63"), _vehiculo_legacy("BKYX63")],
        }), encoding="utf-8")
        snapshot = construir_snapshot_fichas(raiz_atlas=raiz)
        patentes = {v["patente"] for v in snapshot["vehiculos"]}
        assert patentes == {"BKYK63"}


def test_ficha_de_vehiculo_incluye_guias_cuya_patente_es_una_confusion_ocr_resuelta():
    vehiculo = _vehiculo("BPHR67")
    filas = [
        _fila(numero_guia="472037", patente_tracto="BPHR67", patente_rampla=""),
        _fila(numero_guia="472227", patente_tracto="BPHR67", patente_rampla=""),
        _fila(numero_guia="472339", patente_tracto="BPHF67", patente_rampla=""),
    ]
    ficha = construir_ficha_vehiculo(vehiculo=vehiculo, filas=filas, vehiculos_por_patente={"BPHR67": vehiculo})
    assert ficha["guias_relacionadas"] == ["472037", "472227", "472339"]


# ============================================================
# Bloque CATÁLOGOS VEHÍCULOS -- SEPARAR CONFIRMADOS: clasificacion_visual
# ============================================================


def test_vehiculo_con_confirmacion_humana_es_confirmado_aunque_no_tenga_guias_vigentes():
    vehiculo = _vehiculo("JD8659", procedencia="CONFIRMACION_HUMANA", confirmado_por="JAVIER_MBT")
    ficha = construir_ficha_vehiculo(vehiculo=vehiculo, filas=[], vehiculos_por_patente={"JD8659": vehiculo})
    assert ficha["clasificacion_visual"] == "CONFIRMADO"
    assert ficha["procedencia"] == "CONFIRMACION_HUMANA"


def test_vehiculo_legacy_con_evidencia_operacional_real_es_confirmado():
    # BPHR67 real: procedencia CATALOGO_LEGACY, sin confirmado_por, pero
    # con guías reales -- "evidencia equivalente fuerte" (Sección 1 del
    # bloque), no queda relegado a "Observado".
    vehiculo = _vehiculo("BPHR67", procedencia="CATALOGO_LEGACY")
    filas = [_fila(numero_guia="1", patente_tracto="BPHR67", patente_rampla="")]
    ficha = construir_ficha_vehiculo(vehiculo=vehiculo, filas=filas, vehiculos_por_patente={"BPHR67": vehiculo})
    assert ficha["clasificacion_visual"] == "CONFIRMADO"


def test_vehiculo_confirmado_persistente_sin_evidencia_vigente_sigue_confirmado():
    vehiculo = _vehiculo("ZZ0000", procedencia="CATALOGO_LEGACY")
    ficha = construir_ficha_vehiculo(vehiculo=vehiculo, filas=[], vehiculos_por_patente={"ZZ0000": vehiculo})
    assert ficha["clasificacion_visual"] == "CONFIRMADO"


def test_vehiculo_marcado_ambiguo_por_el_barrido_nunca_aparece_como_confirmado():
    vehiculo = _vehiculo("JF9565", procedencia="CATALOGO_LEGACY")
    ficha = construir_ficha_vehiculo(
        vehiculo=vehiculo, filas=[], vehiculos_por_patente={"JF9565": vehiculo},
        patentes_ambiguas=frozenset({"JF9565", "JF9575"}),
    )
    assert ficha["clasificacion_visual"] == "AMBIGUO"


def test_snapshot_marca_ambiguo_solo_al_lado_sin_confirmacion_ni_evidencia():
    """Caso real JF9565/JF9575: ambas patentes son estructuralmente
    sospechosas entre sí (comparten catálogo, sin confusión OCR
    calibrada entre "6"/"7"), pero JF9575 tiene confirmación humana
    explícita -- sólo JF9565 queda "Por verificar"."""
    import csv
    import json
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        raiz = Path(tmp)
        (raiz / "operacion" / "actual").mkdir(parents=True)
        (raiz / "catalogos_privados").mkdir(parents=True)
        with (raiz / "operacion" / "actual" / "analisis_completo_guias.csv").open("w", newline="", encoding="utf-8-sig") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
            escritor.writeheader()
        (raiz / "catalogos_privados" / "choferes.json").write_text("{}", encoding="utf-8")
        (raiz / "catalogos_privados" / "vehiculos.json").write_text(json.dumps({
            "version": 1,
            "vehiculos": [
                {
                    "vehiculo_id": "v-JF9565", "patente_canonica": "JF9565", "tipo": "CARRO",
                    "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO", "aliases": [],
                    "evidencias": [{
                        "tipo": "MIGRACION_LEGACY", "identificador_fuente": "vehiculos.json",
                        "referencia_hash": "x", "campos_observados": {"patente": "JF9565", "tipo": "CARRO"},
                        "fecha": FECHA, "actor_proceso": "PROCESO_MIGRACION", "resultado": "SOPORTA",
                    }],
                    "procedencia": "CATALOGO_LEGACY", "confirmado_por": "", "fecha_confirmacion": "",
                    "observaciones": "", "fecha_creacion": FECHA, "fecha_modificacion": FECHA,
                },
                {
                    "vehiculo_id": "v-JF9575", "patente_canonica": "JF9575", "tipo": "CARRO",
                    "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO", "aliases": [], "evidencias": [],
                    "procedencia": "CONFIRMACION_HUMANA", "confirmado_por": "JAVIER_MBT", "fecha_confirmacion": FECHA,
                    "observaciones": "", "fecha_creacion": FECHA, "fecha_modificacion": FECHA,
                },
            ],
        }), encoding="utf-8")
        snapshot = construir_snapshot_fichas(raiz_atlas=raiz)
        por_patente = {v["patente"]: v for v in snapshot["vehiculos"]}
        assert por_patente["JF9565"]["clasificacion_visual"] == "AMBIGUO"
        assert por_patente["JF9575"]["clasificacion_visual"] == "CONFIRMADO"


def test_patente_documental_sin_catalogar_igual_se_muestra_nunca_se_oculta():
    filas = [_fila(numero_guia="1", patente_tracto="XX0000", patente_rampla="")]
    ficha = construir_ficha_chofer(
        identificador="PENDIENTE00000002",
        registro_catalogo={"nombre": "PERSONA EJEMPLO", "activo": True, "aliases": []},
        filas=filas, vehiculos_por_patente={},  # catálogo vacío -- XX0000 no está confirmada
    )
    assert len(ficha["vehiculos"]) == 1
    assert ficha["vehiculos"][0]["patente"] == "XX0000"
    assert ficha["vehiculos"][0]["estado_catalogo"] == "SIN_CATALOGAR"


# ============================================================
# Histórico operacional -- número de viajes, primera/última, frecuentes
# ============================================================


def test_historico_operacional_cuenta_guias_y_rango_de_fechas():
    filas = [
        _fila(numero_guia="1", fecha="18-08-2026", cliente="CLIENTE A"),
        _fila(numero_guia="2", fecha="20-08-2026", cliente="CLIENTE A"),
        _fila(numero_guia="3", fecha="15-08-2026", cliente="CLIENTE B"),
    ]
    ficha = construir_ficha_chofer(
        identificador="PENDIENTE00000003",
        registro_catalogo={"nombre": "PERSONA EJEMPLO", "activo": True, "aliases": []},
        filas=filas, vehiculos_por_patente={},
    )
    assert ficha["historico"]["numero_guias"] == 3
    assert ficha["historico"]["primera_aparicion"] == "2026-08-15"
    assert ficha["historico"]["ultima_aparicion"] == "2026-08-20"
    assert ficha["historico"]["frecuentes"][0]["nombre"] == "CLIENTE A"
    assert ficha["historico"]["frecuentes"][0]["apariciones"] == 2


# ============================================================
# Ficha cliente / obra / vehículo (Secciones 5, 6, 7)
# ============================================================


def test_ficha_cliente_incluye_rut_aliases_y_obras_frecuentes():
    cliente = Cliente(
        cliente_id="c-1", razon_social="SALOMON SACK SA", nombre_normalizado="SALOMON SACK",
        nombre_comercial="", rut="90970000-0", aliases=("SALOMON SACK",),
        estado_calidad="CONFIRMADO", estado_vigencia="ACTIVO", fuente="TEST", observacion="",
        fecha_creacion=FECHA, fecha_modificacion=FECHA,
    )
    filas = [
        _fila(numero_guia="1", cliente="SALOMON SACK SA", obra_destino="OBRA X"),
        _fila(numero_guia="2", cliente="SALOMON SACK SA", obra_destino="OBRA X"),
    ]
    ficha = construir_ficha_cliente(cliente=cliente, filas=filas)
    assert ficha["rut"] == {"estado": "CONFIRMADO", "valor": "90970000-0"}
    assert ficha["aliases"] == ["SALOMON SACK"]
    assert ficha["historico"]["numero_guias"] == 2
    assert ficha["historico"]["frecuentes"][0]["nombre"] == "OBRA X"


class _CatalogoObrasFake:
    """Fake mínimo -- construir_ficha_obra sólo llama a este único
    método; evita construir un CatalogoObrasDestinos real desde
    archivo sólo para probar la agregación."""

    def __init__(self, destinos):
        self._destinos = destinos

    def listar_destinos_confirmados_para_obra(self, *, nombre_obra):
        return self._destinos


def test_ficha_obra_incluye_direccion_comuna_y_coordenadas_de_destinos_confirmados():
    obra = Obra(
        obra_id="o-1", cliente_id="c-1", nombre_canonico="AUSIN SAN BERNARDO",
        nombre_normalizado="AUSIN SAN BERNARDO", aliases_documentales=(),
        estado="CONFIRMADA", estado_vigencia="ACTIVO", evidencias=(),
        fecha_creacion=FECHA, fecha_modificacion=FECHA,
    )
    destino = Destino(
        destino_id="d-1", cliente_id="c-1", nombre_destino="INTERIOR NUEVA O1148 SAN BERNARDO",
        nombre_normalizado="INTERIOR NUEVA O1148 SAN BERNARDO", codigo_destino="",
        direccion="INTERIOR NUEVA O1148 SAN BERNARDO", comuna="SAN BERNARDO", region="RM", pais="CHILE",
        latitud=-33.54, longitud=-70.70, aliases=(), estado_calidad="CONFIRMADO", estado_vigencia="ACTIVO",
        fuente="TEST", observacion="", fecha_creacion=FECHA, fecha_modificacion=FECHA,
    )
    cliente = Cliente(
        cliente_id="c-1", razon_social="MATERIALES Y SOLUCIONES SA", nombre_normalizado="MATERIALES",
        nombre_comercial="", rut="", aliases=(), estado_calidad="CONFIRMADO", estado_vigencia="ACTIVO",
        fuente="TEST", observacion="", fecha_creacion=FECHA, fecha_modificacion=FECHA,
    )
    filas = [_fila(numero_guia="1", obra_destino="AUSIN SAN BERNARDO")]
    ficha = construir_ficha_obra(
        obra=obra, catalogo_obras=_CatalogoObrasFake([destino]),
        clientes_por_id={"c-1": cliente}, filas=filas,
    )
    assert ficha["cliente"] == "MATERIALES Y SOLUCIONES SA"
    assert len(ficha["destinos"]) == 1
    assert ficha["destinos"][0]["comuna"] == "SAN BERNARDO"
    assert ficha["destinos"][0]["latitud"] == -33.54
    assert ficha["historico"]["numero_guias"] == 1


def test_ficha_vehiculo_incluye_tipo_choferes_asociados_y_apariciones():
    vehiculo = Vehiculo(
        vehiculo_id="v-1", patente_canonica="BPHR67", tipo="TRACTO",
        estado_calidad="CONFIRMADO", estado_vigencia="ACTIVO", aliases=(), evidencias=(),
        procedencia="TEST", confirmado_por="", fecha_confirmacion="", observaciones="",
        fecha_creacion=FECHA, fecha_modificacion=FECHA,
    )
    filas = [
        _fila(numero_guia="1", chofer="CRISTOPHER RETAMAL", patente_tracto="BPHR67", patente_rampla=""),
        _fila(numero_guia="2", chofer="CRISTOPHER RETAMAL", patente_tracto="BPHR67", patente_rampla=""),
        _fila(numero_guia="3", chofer="OTRA PERSONA", patente_tracto="ZZ0000", patente_rampla=""),
    ]
    ficha = construir_ficha_vehiculo(vehiculo=vehiculo, filas=filas, vehiculos_por_patente={"BPHR67": vehiculo})
    assert ficha["tipo_vehiculo"] == "TRACTO"
    assert ficha["choferes_asociados"] == [{"nombre": "CRISTOPHER RETAMAL", "apariciones": 2}]
    assert ficha["guias_relacionadas"] == ["1", "2"]
