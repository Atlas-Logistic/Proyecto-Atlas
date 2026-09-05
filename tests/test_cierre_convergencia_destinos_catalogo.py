"""ATLAS -- Cierre real de convergencia de destinos.

`destinos_confirmados` (parámetro ya existente en `resolver_destino_
entrega`) sólo servía para CORROBORAR un candidato que el proveedor de
geocodificación YA devolvía -- nunca como fuente autoritativa que
reemplace la geocodificación cuando el proveedor directamente falla (0
candidatos, o ninguno cae cerca del punto ya confirmado). Esto dejaba
casos reales (464588: coordenadas ya confirmadas por Javier; 464395/
464740: destino ya confirmado pero sin coordenadas propias) sin ninguna
vía automática de convergencia, aunque Atlas ya tuviera toda la evidencia
necesaria.

`revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr` cierra esa
brecha: obra inequívocamente identificada + destino CONFIRMADO cuya calle
corrobora el texto documental + sin evidencia nueva contradictoria =>
usa las coordenadas ya confirmadas (si existen) o reintenta geocodificar
la dirección CANÓNICA (si no) -- nunca inventa nada, nunca toca
`despachar_a_crudo`. Una contradicción real (ningún destino confirmado
corrobora el texto) se marca explícitamente, nunca se oculta."""
from __future__ import annotations

import csv
import json

from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.decisiones_pendientes import detectar_decision_destino_no_resuelto, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    forzar_decision_correccion_destino,
    revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

COORD_AZA_COLINA = Coordenadas(-70.665977, -33.137558)
FECHA = "05-09-2026"


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "1.jpeg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "0000360001", "fecha": FECHA, "chofer": "CHOFER TEST",
        "cliente": "CLIENTE TEST", "obra_destino": "OBRA TEST",
        "patente_tracto": "AATT11", "indicador_revision": "OK",
        "planta_origen_id": "planta-colina", "planta_origen_nombre": "AZA COLINA",
        "origen_determinado_por": "CONFIRMACION_HUMANA", "evidencia_origen": "DECISION_HUMANA:x",
        "despachar_a_crudo": "", "direccion_entrega": "", "estado_entrega": "SIN_DATO",
        "distancia_km": "", "duracion_min": "", "proveedor_ruta": "",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "DESTINO_SIN_DATO",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _leer_csv(ruta):
    with ruta.open("r", newline="", encoding="utf-8-sig") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _cliente_dict(cliente_id="cliente-test", razon_social="CLIENTE TEST"):
    return {
        "cliente_id": cliente_id, "razon_social": razon_social,
        "nombre_normalizado": razon_social, "nombre_comercial": "", "rut": "76086428-5",
        "aliases": [], "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO", "fuente": "TEST",
        "observacion": "", "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00",
    }


def _obra_dict(obra_id="obra-test", cliente_id="cliente-test", nombre="OBRA TEST"):
    return {
        "obra_id": obra_id, "cliente_id": cliente_id, "nombre_canonico": nombre,
        "nombre_normalizado": nombre, "aliases_documentales": [],
        "estado": "OBSERVADA", "estado_vigencia": "ACTIVO", "evidencias": [],
        "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00",
    }


def _entorno(tmp_path, *, filas_csv, clientes=None, obras=None):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": clientes if clientes is not None else [_cliente_dict()]},
        "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {
            "version_formato": 1, "obras": obras if obras is not None else [_obra_dict()], "relaciones": [],
        },
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    planta = CatalogoPlantas(catalogos / "plantas.json").crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="AV EJEMPLO 1", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    for fila in filas_csv:
        if fila.get("planta_origen_id") == "planta-colina":
            fila["planta_origen_id"] = planta.planta_id
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, filas_csv)
    return {"raiz": raiz, "catalogos": catalogos, "actual": actual, "dataset": dataset, "planta_id": planta.planta_id}


def _publicar_y_aplicar(entorno, *, fila_semilla, direccion_manual, proveedor_rutas):
    """Reutiliza el flujo REGISTRAR_DIRECCION ya probado (test_destino_no_
    resuelto_r6.py) para sembrar en catálogo un destino CONFIRMADO real --
    misma vía que usaría Javier, nunca una fixture paralela a mano."""
    decision = detectar_decision_destino_no_resuelto(archivo=fila_semilla["archivo"], fila=fila_semilla)
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    return aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion_manual,
        proveedor_rutas=proveedor_rutas,
    )


def _proveedor_direccion_valida(direccion, *, distancia=25.4, tiempo=38.2):
    consulta = f"{direccion}, Chile"
    return ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(
                    Coordenadas(-70.634933, -33.436723), direccion + ", Santiago, RM, Chile", 1.0,
                    "Santiago", "Metropolitana",
                ),),
                "",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, distancia, tiempo, "SINTETICO"),
    )


def _proveedor_siempre_ambiguo(direccion):
    consulta = f"{direccion}, Chile"
    return ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.RESULTADO_AMBIGUO,
                (
                    CandidatoGeocodificacion(Coordenadas(-70.6, -33.4), "A", 0.5, "Santiago", "Metropolitana"),
                    CandidatoGeocodificacion(Coordenadas(-70.5, -33.3), "B", 0.5, "Providencia", "Metropolitana"),
                ),
                "MULTIPLES_CANDIDATOS",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 1.0, 1.0, "SINTETICO"),
    )


# ============================================================
# Caso 464588 -- destino confirmado CON coordenadas propias
# ============================================================


def test_destino_confirmado_con_coordenadas_calcula_ruta_directo_sin_geocodificar(tmp_path):
    """Caso real 464588: la obra ya tiene un destino CONFIRMADO con
    coordenadas reales -- la fila objetivo trae una variante con ruido
    OCR de esa MISMA calle. Nunca se geocodifica de nuevo: se usa la
    coordenada ya confirmada directo."""
    direccion = "POETA PEDRO PRADO 1548"
    fila_semilla = _fila_csv(numero_guia="1", archivo="1.jpeg")
    entorno = _entorno(tmp_path, filas_csv=[
        fila_semilla,
        _fila_csv(
            numero_guia="2", archivo="2.jpeg", numero_transporte="0000360002",
            despachar_a_crudo=f"{direccion} METROPOLITANA METROPO",
            estado_ruta="REQUIERE_REVISION", motivo_ruta="COORDENADA_NO_CONFIRMADA(5)",
        ),
    ])
    sembrado = _publicar_y_aplicar(
        entorno, fila_semilla={**fila_semilla, "planta_origen_id": entorno["planta_id"]},
        direccion_manual=direccion, proveedor_rutas=_proveedor_direccion_valida(direccion),
    )
    assert sembrado["ok"] is True and sembrado["ruta_resuelta"] is True

    resultado = revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        proveedor_rutas=_proveedor_direccion_valida("NUNCA_DEBERIA_CONSULTARSE"),
    )
    assert "2" in resultado["guias_actualizadas"]
    assert resultado["guias_contradiccion"] == []

    filas = {f["numero_guia"]: f for f in _leer_csv(entorno["dataset"])}
    fila2 = filas["2"]
    assert fila2["estado_ruta"] == "RUTA_CALCULADA"
    assert float(fila2["distancia_km"]) > 0
    assert float(fila2["duracion_min"]) > 0
    assert fila2["motivo_ruta"] == ""
    # Nunca se reescribe la verdad documental.
    assert fila2["despachar_a_crudo"] == f"{direccion} METROPOLITANA METROPO"
    assert fila2["direccion_entrega"].upper() == direccion.upper()


def test_no_geocodifica_de_nuevo_cuando_ya_tiene_coordenadas_confirmadas(tmp_path):
    """El proveedor de rutas recibe una geocodificación que SIEMPRE falla
    para el texto documental -- si la función intentara geocodificar en
    vez de usar la coordenada ya confirmada, esta prueba fallaría."""
    direccion = "POETA PEDRO PRADO 1548"
    fila_semilla = _fila_csv(numero_guia="1", archivo="1.jpeg")
    entorno = _entorno(tmp_path, filas_csv=[
        fila_semilla,
        _fila_csv(
            numero_guia="2", archivo="2.jpeg", numero_transporte="0000360002",
            despachar_a_crudo=f"{direccion} METROPOLITANA METROPO",
            estado_ruta="REQUIERE_REVISION", motivo_ruta="COORDENADA_NO_CONFIRMADA(5)",
        ),
    ])
    _publicar_y_aplicar(
        entorno, fila_semilla={**fila_semilla, "planta_origen_id": entorno["planta_id"]},
        direccion_manual=direccion, proveedor_rutas=_proveedor_direccion_valida(direccion),
    )
    proveedor_sin_geocodificaciones = ProveedorRutasSimulado(
        geocodificaciones={}, resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 25.4, 38.2, "SINTETICO"),
    )
    resultado = revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        proveedor_rutas=proveedor_sin_geocodificaciones,
    )
    assert "2" in resultado["guias_actualizadas"]
    filas = {f["numero_guia"]: f for f in _leer_csv(entorno["dataset"])}
    assert filas["2"]["estado_ruta"] == "RUTA_CALCULADA"


# ============================================================
# Caso 464395/464740 -- destino confirmado SIN coordenadas propias
# ============================================================


def test_destino_confirmado_sin_coordenadas_reintenta_geocodificar_direccion_canonica(tmp_path):
    """Caso real 464395/464740: la confirmación humana previa nunca llegó
    a geocodificar (destino CONFIRMADO sin lat/lon). Si el proveedor real
    SÍ puede ubicar la dirección canónica, la ruta converge."""
    direccion = "DIRECCION AMBIGUA 1"
    fila_semilla = _fila_csv(numero_guia="1", archivo="1.jpeg")
    entorno = _entorno(tmp_path, filas_csv=[
        fila_semilla,
        _fila_csv(
            numero_guia="2", archivo="2.jpeg", numero_transporte="0000360002",
            despachar_a_crudo=direccion,
            estado_ruta="REQUIERE_REVISION", motivo_ruta="MULTIPLES_UBICACIONES_DISPERSAS(2)",
        ),
    ])
    sembrado = _publicar_y_aplicar(
        entorno, fila_semilla={**fila_semilla, "planta_origen_id": entorno["planta_id"]},
        direccion_manual=direccion, proveedor_rutas=_proveedor_siempre_ambiguo(direccion),
    )
    assert sembrado["ok"] is True and sembrado["ruta_resuelta"] is False
    catalogo_obras = CatalogoObrasDestinos(
        ruta=entorno["catalogos"] / "obras_destinos.json", ruta_clientes=entorno["catalogos"] / "clientes.json",
        ruta_destinos=entorno["catalogos"] / "destinos_maestros.json",
    )
    destinos = catalogo_obras.listar_destinos_confirmados_para_obra(nombre_obra="OBRA TEST")
    assert len(destinos) == 1 and destinos[0].latitud is None

    resultado = revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        proveedor_rutas=_proveedor_direccion_valida(direccion),
    )
    assert "2" in resultado["guias_actualizadas"]
    filas = {f["numero_guia"]: f for f in _leer_csv(entorno["dataset"])}
    assert filas["2"]["estado_ruta"] == "RUTA_CALCULADA"
    assert filas["2"]["despachar_a_crudo"] == direccion


def test_destino_confirmado_sin_coordenadas_y_proveedor_sigue_sin_ubicarla_no_inventa_nada(tmp_path):
    """Si el proveedor real sigue sin poder geocodificar la dirección
    canónica (idéntico al caso real 464395/464740), la fila queda
    intacta -- nunca se fabrica una coordenada."""
    direccion = "DIRECCION AMBIGUA 1"
    fila_semilla = _fila_csv(numero_guia="1", archivo="1.jpeg")
    entorno = _entorno(tmp_path, filas_csv=[
        fila_semilla,
        _fila_csv(
            numero_guia="2", archivo="2.jpeg", numero_transporte="0000360002",
            despachar_a_crudo=direccion,
            estado_ruta="REQUIERE_REVISION", motivo_ruta="MULTIPLES_UBICACIONES_DISPERSAS(2)",
        ),
    ])
    _publicar_y_aplicar(
        entorno, fila_semilla={**fila_semilla, "planta_origen_id": entorno["planta_id"]},
        direccion_manual=direccion, proveedor_rutas=_proveedor_siempre_ambiguo(direccion),
    )
    antes = {f["numero_guia"]: dict(f) for f in _leer_csv(entorno["dataset"])}

    resultado = revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        proveedor_rutas=_proveedor_siempre_ambiguo(direccion),
    )
    assert "2" not in resultado["guias_actualizadas"]
    despues = {f["numero_guia"]: dict(f) for f in _leer_csv(entorno["dataset"])}
    assert despues["2"] == antes["2"]


# ============================================================
# Contradicción real -- nunca se oculta
# ============================================================


def test_direccion_documental_distinta_a_la_confirmada_marca_contradiccion_nunca_la_oculta(tmp_path):
    direccion_confirmada = "CALLE CONFIRMADA 100"
    fila_semilla = _fila_csv(numero_guia="1", archivo="1.jpeg")
    entorno = _entorno(tmp_path, filas_csv=[
        fila_semilla,
        _fila_csv(
            numero_guia="2", archivo="2.jpeg", numero_transporte="0000360002",
            despachar_a_crudo="AVENIDA TOTALMENTE DISTINTA 999",
            estado_ruta="REQUIERE_REVISION", motivo_ruta="GEOCODIFICACION_DIRECCION_NO_ENCONTRADA",
        ),
    ])
    _publicar_y_aplicar(
        entorno, fila_semilla={**fila_semilla, "planta_origen_id": entorno["planta_id"]},
        direccion_manual=direccion_confirmada, proveedor_rutas=_proveedor_direccion_valida(direccion_confirmada),
    )
    resultado = revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        proveedor_rutas=_proveedor_direccion_valida(direccion_confirmada),
    )
    assert "2" in resultado["guias_contradiccion"]
    filas = {f["numero_guia"]: f for f in _leer_csv(entorno["dataset"])}
    assert filas["2"]["motivo_ruta"] == "DESTINO_CONTRADICE_CATALOGO_CONFIRMADO"
    assert filas["2"]["estado_ruta"] == "REQUIERE_REVISION"
    assert filas["2"]["distancia_km"] == ""
    # Nunca se toca la evidencia documental real.
    assert filas["2"]["despachar_a_crudo"] == "AVENIDA TOTALMENTE DISTINTA 999"


def test_contradiccion_produce_decision_accionable_nunca_queda_atrapada(tmp_path):
    """Caso real 464265: sin esto, el motivo nuevo `DESTINO_CONTRADICE_
    CATALOGO_CONFIRMADO` no pertenecía a `MOTIVOS_DESTINO_NO_RESUELTO` --
    la guía perdía su tarjeta `DESTINO_NO_RESUELTO` (R19 la descarta por
    motivo obsoleto) y no ganaba ninguna nueva, quedando atrapada como
    INCOMPLETO_TECNICO -- exactamente lo que este bloque prohíbe
    ("tampoco pueden quedar sin ruta ni pregunta")."""
    direccion_confirmada = "CALLE CONFIRMADA 100"
    fila_semilla = _fila_csv(numero_guia="1", archivo="1.jpeg")
    fila_objetivo = _fila_csv(
        numero_guia="2", archivo="2.jpeg", numero_transporte="0000360002",
        despachar_a_crudo="AVENIDA TOTALMENTE DISTINTA 999",
        estado_ruta="REQUIERE_REVISION", motivo_ruta="GEOCODIFICACION_DIRECCION_NO_ENCONTRADA",
    )
    entorno = _entorno(tmp_path, filas_csv=[fila_semilla, fila_objetivo])
    _publicar_y_aplicar(
        entorno, fila_semilla={**fila_semilla, "planta_origen_id": entorno["planta_id"]},
        direccion_manual=direccion_confirmada, proveedor_rutas=_proveedor_direccion_valida(direccion_confirmada),
    )
    revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        proveedor_rutas=_proveedor_direccion_valida(direccion_confirmada),
    )
    fila_actual = {f["numero_guia"]: f for f in _leer_csv(entorno["dataset"])}["2"]
    decision = detectar_decision_destino_no_resuelto(
        archivo="2.jpeg", fila={**fila_actual, "planta_origen_id": entorno["planta_id"]},
        carpeta_catalogos=entorno["catalogos"],
    )
    assert decision is not None
    assert decision["motivos"] == ["DESTINO_CONTRADICE_CATALOGO_CONFIRMADO"]
    assert "REGISTRAR_DIRECCION" in decision["acciones_permitidas"]


def test_contradiccion_es_idempotente_no_reescribe_en_cada_pasada(tmp_path):
    direccion_confirmada = "CALLE CONFIRMADA 100"
    fila_semilla = _fila_csv(numero_guia="1", archivo="1.jpeg")
    entorno = _entorno(tmp_path, filas_csv=[
        fila_semilla,
        _fila_csv(
            numero_guia="2", archivo="2.jpeg", numero_transporte="0000360002",
            despachar_a_crudo="AVENIDA TOTALMENTE DISTINTA 999",
            estado_ruta="REQUIERE_REVISION", motivo_ruta="GEOCODIFICACION_DIRECCION_NO_ENCONTRADA",
        ),
    ])
    _publicar_y_aplicar(
        entorno, fila_semilla={**fila_semilla, "planta_origen_id": entorno["planta_id"]},
        direccion_manual=direccion_confirmada, proveedor_rutas=_proveedor_direccion_valida(direccion_confirmada),
    )
    revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        proveedor_rutas=_proveedor_direccion_valida(direccion_confirmada),
    )
    segunda = revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        proveedor_rutas=_proveedor_direccion_valida(direccion_confirmada),
    )
    assert segunda["guias_actualizadas"] == []
    assert segunda["guias_contradiccion"] == []


# ============================================================
# Abstenciones
# ============================================================


def test_dos_destinos_confirmados_coinciden_se_abstiene(tmp_path):
    """Ambigüedad real (dos destinos confirmados, ambos corroboran el
    texto documental) -- nunca 'el primero'."""
    direccion_a = "CALLE UNO 100"
    direccion_b = "CALLE DOS 200"
    fila_1 = _fila_csv(numero_guia="1", archivo="1.jpeg")
    fila_2 = _fila_csv(numero_guia="2", archivo="2.jpeg", numero_transporte="0000360003")
    entorno = _entorno(tmp_path, filas_csv=[
        fila_1, fila_2,
        _fila_csv(
            numero_guia="3", archivo="3.jpeg", numero_transporte="0000360002",
            # Texto documental construido para mencionar AMBAS calles
            # confirmadas -- el escenario real (R18) es una obra con dos
            # confirmaciones legítimas y distintas; aquí se fuerza a
            # propósito para probar la abstención.
            despachar_a_crudo=f"{direccion_a} {direccion_b}",
            estado_ruta="REQUIERE_REVISION", motivo_ruta="GEOCODIFICACION_DIRECCION_NO_ENCONTRADA",
        ),
    ])
    _publicar_y_aplicar(
        entorno, fila_semilla={**fila_1, "planta_origen_id": entorno["planta_id"]},
        direccion_manual=direccion_a, proveedor_rutas=_proveedor_direccion_valida(direccion_a),
    )
    # Segunda dirección confirmada, MISMA obra, texto documental que
    # también corrobora "CALLE UNO 100" (subcadena).
    decision_2 = detectar_decision_destino_no_resuelto(
        archivo="2.jpeg", fila={**fila_2, "planta_origen_id": entorno["planta_id"]},
    )
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision_2], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision_2["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion_b,
        proveedor_rutas=_proveedor_direccion_valida(direccion_b),
    )
    resultado = revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        proveedor_rutas=_proveedor_direccion_valida("NUNCA"),
    )
    assert "3" not in resultado["guias_actualizadas"]
    assert "3" not in resultado["guias_contradiccion"]


def test_no_toca_filas_ya_con_ruta_calculada(tmp_path):
    fila_semilla = _fila_csv(numero_guia="1", archivo="1.jpeg")
    entorno = _entorno(tmp_path, filas_csv=[
        fila_semilla,
        _fila_csv(
            numero_guia="2", archivo="2.jpeg", numero_transporte="0000360002",
            despachar_a_crudo="YA RESUELTA 1", estado_ruta="RUTA_CALCULADA", motivo_ruta="",
            distancia_km="10.0", duracion_min="15",
        ),
    ])
    resultado = revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
    )
    assert resultado["guias_actualizadas"] == []


def test_respeta_guias_objetivo(tmp_path):
    direccion = "POETA PEDRO PRADO 1548"
    fila_semilla = _fila_csv(numero_guia="1", archivo="1.jpeg")
    entorno = _entorno(tmp_path, filas_csv=[
        fila_semilla,
        _fila_csv(
            numero_guia="2", archivo="2.jpeg", numero_transporte="0000360002",
            despachar_a_crudo=f"{direccion} RUIDO", estado_ruta="REQUIERE_REVISION",
            motivo_ruta="COORDENADA_NO_CONFIRMADA(5)",
        ),
    ])
    _publicar_y_aplicar(
        entorno, fila_semilla={**fila_semilla, "planta_origen_id": entorno["planta_id"]},
        direccion_manual=direccion, proveedor_rutas=_proveedor_direccion_valida(direccion),
    )
    resultado = revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        proveedor_rutas=_proveedor_direccion_valida("NUNCA"), guias_objetivo={"999"},
    )
    assert resultado["guias_actualizadas"] == []


# ============================================================
# "Corregir destino" reabierta sobre un destino recién reconfirmado --
# regresión real detectada en la demostración visual (464367)
# ============================================================


def test_forzar_correccion_destino_reabierta_sin_texto_nuevo_nunca_devuelve_decision_fantasma(tmp_path):
    """Regresión real detectada en vivo (464367, demostración visual del
    flujo "Corregir destino"): tras aplicar REGISTRAR_DIRECCION, R13
    aprende esa dirección como destino CONFIRMADO de la obra -- volver a
    abrir "Corregir destino" para la MISMA guía, sin que el texto
    documental haya cambiado, hace que la reconciliación canónica (R13/
    R18: "esta obra ya tiene una pregunta de destino respondida")
    suprima la tarjeta recién forzada. Antes de este fix,
    `forzar_decision_correccion_destino` devolvía igual `ok: True` con
    una decisión que en realidad NUNCA se publicó -- Desktop la mostraba
    aplicable, y `aplicar_decision_obra` la rechazaba después como "ya no
    está pendiente", una falla confusa y tardía. Ahora se informa aquí
    mismo, de inmediato, con una razón real -- nunca una decisión
    fantasma."""
    direccion = "CALLE CONFIRMADA 100"
    fila_semilla = _fila_csv(numero_guia="1", archivo="1.jpeg")
    entorno = _entorno(tmp_path, filas_csv=[fila_semilla])
    primera = _publicar_y_aplicar(
        entorno, fila_semilla={**fila_semilla, "planta_origen_id": entorno["planta_id"]},
        direccion_manual=direccion, proveedor_rutas=_proveedor_direccion_valida(direccion),
    )
    assert primera["ok"] is True

    reabierta = forzar_decision_correccion_destino(raiz_atlas=entorno["raiz"], numero_guia="1")
    assert reabierta["ok"] is False
    assert "error" in reabierta and reabierta["error"]
    # Nunca deja un artefacto fantasma en la bandeja publicada.
    bandeja = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    assert bandeja["decisiones"] == []
