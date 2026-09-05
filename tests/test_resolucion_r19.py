"""Bloque RESOLUCIÓN R19 -- evidencia externa (Google Maps/SII) valida
las 3 revisiones de destino restantes.

Caso real 472037 (VICUÑA MACKENNA 655): antes de este bloque una fila
ya persistida con `GEOCODIFICACION_FUERA_DE_CHILE: Cordoba` (motivo
obsoleto desde que Bloque RESOLUCIÓN R16 restringió la consulta a
`pais=CL`) nunca se reintentaba -- `GEOCODIFICACION_FUERA_DE_CHILE` no
estaba en el conjunto de motivos reevaluables, sólo
`GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL`."""
from __future__ import annotations

import csv

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_ruta_sin_destino_calculado_sin_ocr
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

COORD_AZA_COLINA = Coordenadas(-70.669, -33.201)


def _catalogos(tmp_path):
    carpeta = tmp_path / "catalogos"; carpeta.mkdir()
    plantas = CatalogoPlantas(carpeta / "plantas.json")
    planta = plantas.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="RUTA 5", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    return carpeta, planta


def _fila_csv(planta, **overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "472037.jpeg", "estado_procesamiento": "OK", "numero_guia": "472037",
        "numero_transporte": "T1", "fecha": "22/08/2026",
        "despachar_a_crudo": "VICUÑA MACKENNA 655",
        "planta_origen_id": planta.planta_id, "planta_origen_nombre": planta.nombre,
        "origen_determinado_por": "TELEMETRIA_GPS", "evidencia_origen": "GEOCERCA_PLANTA",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "GEOCODIFICACION_FUERA_DE_CHILE: Cordoba",
        "distancia_km": "", "duracion_min": "", "indicador_revision": "OK",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerows(filas)


def _leer(ruta):
    with ruta.open(encoding="utf-8-sig") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def test_registrar_direccion_con_evidencia_externa_queda_trazable(tmp_path):
    """Caso real 472008 (AUSIN SAN BERNARDO): la dirección documental
    ("INTERIOR NUEVA O1148 SAN BERNARDO") se confirma con evidencia
    externa (SII + verificación manual de mapa, nunca "adivinada") --
    `aplicar_decision_obra` (mecanismo ya existente, Bloque R6/R13)
    persiste el destino CONFIRMADO con un `actor` distinto de una
    confirmación humana directa, dejando trazabilidad de que la
    resolución vino de evidencia externa, no de un clic de Javier."""
    import json as _json

    from atlas_core.aplicacion_decisiones import aplicar_decision_obra
    from atlas_core.decisiones_pendientes import detectar_decision_destino_no_resuelto, generar_artefacto

    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"; actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True); catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    planta = CatalogoPlantas(catalogos / "plantas.json").crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="RUTA 5", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []}, "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(_json.dumps(contenido), encoding="utf-8")
    fila = _fila_csv(
        planta, numero_guia="472008", archivo="472008.jpeg",
        despachar_a_crudo="INTERIOR NUEVA O1148 SAN BERNARDO",
        obra_destino="AUSIN SAN BERNARDO", cliente="AUSIN HNOS LTDA",
        motivo_ruta="MULTIPLES_UBICACIONES_DISPERSAS(3)",
    )
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [fila])
    decision = detectar_decision_destino_no_resuelto(archivo="472008.jpeg", fila=fila)
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision],
        ruta_salida=actual / "decisiones_pendientes.json",
    )

    resultado = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR_DIRECCION",
        direccion_manual="INTERIOR NUEVA O1148 SAN BERNARDO",
        actor="ATLAS_EVIDENCIA_EXTERNA_R19",
    )
    assert resultado["ok"] is True
    ledger = _json.loads((actual / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    assert ledger["aplicaciones"][-1]["actor"] == "ATLAS_EVIDENCIA_EXTERNA_R19"
    pendientes = _json.loads((actual / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    # Bloque CIERRE REAL DE CONVERGENCIA DE DESTINOS -- el proveedor real
    # puede devolver, para esta dirección concreta, un candidato en una
    # comuna distinta a la documental (evidencia real y fresca, nunca el
    # motivo VIEJO `MULTIPLES_UBICACIONES_DISPERSAS` con el que arrancó
    # esta prueba) -- nunca debe sobrevivir una tarjeta FANTASMA con el
    # motivo obsoleto, ni tampoco debe desaparecer en silencio un
    # problema real todavía sin resolver (regresión real: antes de este
    # bloque, la tarjeta vieja bloqueaba -- vía `tipos_ya_presentes` --
    # que el barrido generara la fresca, dejando la guía sin NINGUNA
    # tarjeta pese a tener un motivo técnico real vigente).
    motivos_presentes = [tuple(d.get("motivos") or ()) for d in pendientes["decisiones"]]
    assert ("MULTIPLES_UBICACIONES_DISPERSAS",) not in motivos_presentes
    assert len(pendientes["decisiones"]) <= 1


def test_decision_destino_con_motivo_obsoleto_se_descarta(tmp_path):
    """Caso real 472037: una decisión `DESTINO_NO_RESUELTO` publicada con
    el motivo VIEJO ("GEOCODIFICACION_FUERA_DE_CHILE", evidencia
    obsoleta) debe descartarse cuando la fila ya se refrescó a un motivo
    distinto -- nunca queda una tarjeta fantasma junto a la fresca.

    Bloque CIERRE REAL DE CONVERGENCIA DE DESTINOS -- la fila de esta
    prueba tiene, además, un motivo NUEVO real y vigente
    (`MULTIPLES_UBICACIONES_DISPERSAS`) -- el barrido debe reemplazar la
    tarjeta vieja por una fresca con el motivo correcto, nunca dejar la
    guía sin ninguna tarjeta (regresión real: `tipos_ya_presentes` se
    construía ANTES de descartar la vieja, bloqueando la generación de
    la fresca -- la guía quedaba sin ninguna, un problema real oculto)."""
    from atlas_core.decisiones_pendientes import crear_decision, regenerar_decisiones_persistidas

    carpeta, planta = _catalogos(tmp_path)
    (carpeta / "clientes.json").write_text('{"version_formato": 1, "clientes": []}', encoding="utf-8")
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_csv(planta, motivo_ruta="MULTIPLES_UBICACIONES_DISPERSAS(5)")])
    decision_obsoleta = crear_decision(
        tipo="DESTINO_NO_RESUELTO", entidad="DESTINO", archivo="472037.jpeg",
        numero_guia="472037", numero_transporte="T1", campo="despachar_a_crudo",
        valor_documental="VICUÑA MACKENNA 655", valor_normalizado="", identidad_resuelta=None,
        candidatos=(), motivos=["GEOCODIFICACION_FUERA_DE_CHILE"],
        evidencias=[{"tipo": "RUTA_BLOQUEADA", "motivo_ruta": "GEOCODIFICACION_FUERA_DE_CHILE: Cordoba"}],
        acciones_permitidas=("REGISTRAR_DIRECCION", "NO_PUEDO_DETERMINAR", "POSPONER"),
        contexto={},
    )
    restantes = regenerar_decisiones_persistidas(
        decisiones=[decision_obsoleta], carpeta_catalogos=carpeta, ruta_dataset=dataset,
    )
    assert len(restantes) == 1
    assert restantes[0]["motivos"] == ["MULTIPLES_UBICACIONES_DISPERSAS"]
    assert restantes[0]["decision_id"] != decision_obsoleta["decision_id"]


def test_geocodificacion_fuera_de_chile_se_reintenta_y_refresca(tmp_path):
    """Con la consulta ya restringida a Chile (Bloque R16), el proveedor
    ya NO devuelve el candidato extranjero -- la fila obsoleta se
    refresca al motivo fresco y real (dispersión genuina entre comunas
    chilenas), nunca se queda con la causa vieja/engañosa."""
    carpeta, planta = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_csv(planta)])
    consulta = "VICUÑA MACKENNA 655, Chile"
    proveedor = ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.RESULTADO_AMBIGUO,
                (
                    CandidatoGeocodificacion(Coordenadas(-70.6, -33.5), "Vicuña Mackenna, La Florida, RM, Chile", 0.8, "La Florida", "Metropolitana"),
                    CandidatoGeocodificacion(Coordenadas(-70.6, -33.44), "Vicuña Mackenna, Santiago, RM, Chile", 0.8, "Santiago", "Metropolitana"),
                ),
                "MULTIPLES_CANDIDATOS",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 10.0, 15.0, "SINTETICO"),
    )
    resultado = revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor,
    )
    assert resultado["guias_actualizadas"] == ["472037"]
    fila = _leer(dataset)[0]
    assert fila["motivo_ruta"].startswith("MULTIPLES_UBICACIONES_DISPERSAS")
    assert "Cordoba" not in fila["motivo_ruta"]
    assert fila["distancia_km"] == ""  # nunca inventa una ruta entre 2 comunas reales distintas
