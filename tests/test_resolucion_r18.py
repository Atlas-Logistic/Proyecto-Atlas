"""Bloque RESOLUCIÓN R18 -- causa raíz real de "requiere confirmación
humana + 0 decisiones en Revisión de Atlas" (casos 460807/472008/472037/
472044/472073/472163): `detectar_decisiones_origen_sin_ocr`/
`_destino_no_resuelto_sin_ocr`/`_cliente_ausente_sin_ocr` existían,
probadas, cada una con su propio `reconciliar_decisiones_*` -- pero
NINGUNA estaba conectada al auto-republicado de la bandeja que
`revalidar_y_regenerar_reporte` corre siempre. Sólo se podaban
decisiones ya publicadas; nunca se descubrían candidatas nuevas."""
from __future__ import annotations

import csv
import json

from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, ResultadoEvidencia, TipoEvidencia
from atlas_core.decisiones_pendientes import MOTIVOS_DESTINO_NO_RESUELTO, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    revalidar_destinos_confirmados_sin_coordenadas_sin_ocr, revalidar_y_regenerar_reporte,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado


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
        "indicador_revision": "OK", "planta_origen_id": "planta-1",
        "planta_origen_nombre": "AZA COLINA",
    })
    fila.update(overrides)
    return fila


def _raiz(tmp_path):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"; actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True); catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    return raiz, catalogos, actual


def _escribir_dataset(actual, filas):
    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerows(filas)
    return dataset


def _pendientes(actual):
    return json.loads((actual / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]


def test_geocodificacion_fuera_de_chile_es_motivo_destino_no_resuelto():
    """Bloque RESOLUCIÓN R18 -- caso real 472037: antes de este bloque el
    motivo no estaba en el conjunto reconocido, así que nunca podía
    generar una pregunta accionable."""
    assert "GEOCODIFICACION_FUERA_DE_CHILE" in MOTIVOS_DESTINO_NO_RESUELTO


def test_revalidar_descubre_decision_destino_no_resuelto_para_multiples_ubicaciones(tmp_path):
    """E2E -- caso real 460807/472008: una fila con `MULTIPLES_UBICACIONES_
    DISPERSAS` y origen ya resuelto, con una bandeja YA EXISTENTE (aunque
    vacía), debe terminar con una decisión `DESTINO_NO_RESUELTO`
    publicada -- sin ningún script manual, sólo por correr la
    reconciliación automática que ya corre después de cada revalidación."""
    raiz, catalogos, actual = _raiz(tmp_path)
    fila = _fila(
        numero_guia="460807", despachar_a_crudo="INTERIOR NUEVA O1148 SAN BERNARDO SAN BERNARDO",
        obra_destino="AUSIN SAN BERNARDO", cliente="MATERIALES Y SOLUCIONES SA",
        motivo_ruta="MULTIPLES_UBICACIONES_DISPERSAS(3)", estado_ruta="REQUIERE_REVISION",
    )
    dataset = _escribir_dataset(actual, [fila])
    # Bandeja YA existente (aunque vacía) -- el auto-republicado sólo corre
    # cuando el artefacto ya existe (ver `revalidar_y_regenerar_reporte`).
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[],
        ruta_salida=actual / "decisiones_pendientes.json",
    )

    resultado = revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_test")

    assert resultado.get("decisiones_candidatas_descubiertas", 0) >= 1
    pendientes = _pendientes(actual)
    tipos = [(d["tipo"], d["documento"]["numero_guia"]) for d in pendientes]
    assert ("DESTINO_NO_RESUELTO", "460807") in tipos


def test_revalidar_descubre_decision_para_geocodificacion_fuera_de_chile(tmp_path):
    """Caso real 472037."""
    raiz, catalogos, actual = _raiz(tmp_path)
    fila = _fila(
        numero_guia="472037", despachar_a_crudo="VICUÑA MACKENNA 655",
        obra_destino="ING Y CONST FUNDAMENTA SPA", cliente="COMERCIAL A Y B LTDA",
        motivo_ruta="GEOCODIFICACION_FUERA_DE_CHILE: Cordoba", estado_ruta="REQUIERE_REVISION",
    )
    dataset = _escribir_dataset(actual, [fila])
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[],
        ruta_salida=actual / "decisiones_pendientes.json",
    )

    revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_test")

    pendientes = _pendientes(actual)
    tipos = [(d["tipo"], d["documento"]["numero_guia"]) for d in pendientes]
    assert ("DESTINO_NO_RESUELTO", "472037") in tipos


def test_no_genera_decision_cuando_no_hay_evidencia_de_origen(tmp_path):
    """Control -- caso real 464981 (SIN_TRIPS_EN_VENTANA_TEMPORAL): sin
    ninguna planta candidata que ofrecer, la reconciliación NO debe
    inventar una pregunta -- causa técnica final, no decisión humana."""
    raiz, catalogos, actual = _raiz(tmp_path)
    fila = _fila(
        numero_guia="464981", planta_origen_id="", planta_origen_nombre="",
        estado_ruta="ORIGEN_NO_DETERMINADO", motivo_ruta="SIN_EVIDENCIA_GPS",
        motivo_origen_gps="SIN_TRIPS_EN_VENTANA_TEMPORAL",
    )
    dataset = _escribir_dataset(actual, [fila])
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[],
        ruta_salida=actual / "decisiones_pendientes.json",
    )

    resultado = revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_test")

    assert resultado.get("decisiones_candidatas_descubiertas", 0) == 0
    assert _pendientes(actual) == []


def test_decision_hermana_desaparece_sola_tras_confirmar_una_familia(tmp_path):
    """Propagación -- caso real 460807/472008 (misma obra, misma
    dirección OCR): una vez que la obra tiene una relación CONFIRMADA
    (vía `aplicar_decision_obra` sobre CUALQUIERA de las guías
    hermanas), la reconciliación automática ya no vuelve a descubrir una
    decisión `DESTINO_NO_RESUELTO` para la otra -- sin responder por
    Javier, sólo dejando de preguntar lo ya contestado."""
    raiz, catalogos, actual = _raiz(tmp_path)
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="AUSIN HNOS LTDA", rut="76.111.111-6", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    ).registrar_observacion(
        cliente_id=cliente.cliente_id, nombre_obra="AUSIN SAN BERNARDO",
        evidencia=Evidencia(
            tipo=TipoEvidencia.GUIA.value, identificador_fuente="472008", referencia_hash="a" * 64,
            campos_observados={"obra": "AUSIN SAN BERNARDO"}, fecha="2026-01-01T00:00:00+00:00",
            actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value,
        ),
    )
    fila_confirmada = _fila(
        archivo="472008.jpeg", numero_guia="472008", numero_transporte="T-472008",
        cliente="AUSIN HNOS LTDA", obra_destino="AUSIN SAN BERNARDO",
        despachar_a_crudo="INTERIOR NUEVA O1148 SAN BERNARDO",
        motivo_ruta="MULTIPLES_UBICACIONES_DISPERSAS(3)", estado_ruta="REQUIERE_REVISION",
    )
    fila_hermana = _fila(
        archivo="460807.jpeg", numero_guia="460807", numero_transporte="T-460807",
        cliente="MATERIALES Y SOLUCIONES SA", obra_destino="AUSIN SAN BERNARDO",
        despachar_a_crudo="INTERIOR NUEVA O1148 SAN BERNARDO SAN BERNARDO",
        motivo_ruta="MULTIPLES_UBICACIONES_DISPERSAS(3)", estado_ruta="REQUIERE_REVISION",
    )
    dataset = _escribir_dataset(actual, [fila_confirmada, fila_hermana])
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[],
        ruta_salida=actual / "decisiones_pendientes.json",
    )
    revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_test")
    pendientes = _pendientes(actual)
    tipos = [(d["tipo"], d["documento"]["numero_guia"]) for d in pendientes]
    assert ("DESTINO_NO_RESUELTO", "472008") in tipos
    assert ("DESTINO_NO_RESUELTO", "460807") in tipos

    from atlas_core.aplicacion_decisiones import aplicar_decision_obra
    decision_id = next(
        d["decision_id"] for d in pendientes if d["documento"]["numero_guia"] == "472008"
    )
    resultado = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision_id, accion="REGISTRAR_DIRECCION",
        direccion_manual="INTERIOR NUEVA O1148 SAN BERNARDO",
    )
    assert resultado["ok"] is True

    pendientes_tras = _pendientes(actual)
    tipos_tras = [(d["tipo"], d["documento"]["numero_guia"]) for d in pendientes_tras]
    assert ("DESTINO_NO_RESUELTO", "460807") not in tipos_tras


def test_no_suprime_decision_cuando_la_obra_confirmo_otro_destino_distinto(tmp_path):
    """Caso real 472044 (EMPRESA CONSTRUCTORA MENA Y): la misma obra ya
    tiene un destino CONFIRMADO para OTRA guía, pero es una dirección
    completamente distinta ("CAM. EL NOVICIADO LAMPA LAMPA" vs "PUERTA
    DEL SOL 83 LAS CONDES") -- suprimir la pregunta de ESTA guía sólo
    porque la obra tiene ALGUNA relación confirmada silenciaría una
    pregunta genuina que Javier nunca contestó."""
    raiz, catalogos, actual = _raiz(tmp_path)
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="EASY RETAIL SA", rut="76.111.111-6", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    ).registrar_observacion(
        cliente_id=cliente.cliente_id, nombre_obra="EMPRESA CONSTRUCTORA MENA Y",
        destino_id=CatalogoDestinos(
            catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json",
        ).crear(
            cliente_id="", nombre_destino="CAM. EL NOVICIADO LAMPA LAMPA",
            direccion="CAM. EL NOVICIADO LAMPA LAMPA", pais="CHILE", fuente="TEST",
            estado_calidad=EstadoCalidadDestino.CONFIRMADO,
        ).destino_id,
        evidencia=Evidencia(
            tipo=TipoEvidencia.GUIA.value, identificador_fuente="464746", referencia_hash="a" * 64,
            campos_observados={"obra": "EMPRESA CONSTRUCTORA MENA Y", "destino": "CAM. EL NOVICIADO LAMPA LAMPA"},
            fecha="2026-01-01T00:00:00+00:00", actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value,
        ),
    )
    catalogo_obras = CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    )
    relacion = catalogo_obras.listar_relaciones()[0]
    catalogo_obras.confirmar_relacion(relacion.relacion_id, actor="TEST", identificador_fuente="test")

    fila = _fila(
        archivo="472044.jpeg", numero_guia="472044", cliente="EASY RETAIL SA",
        obra_destino="EMPRESA CONSTRUCTORA MENA Y", despachar_a_crudo="PUERTA DEL SOL 83 LAS CONDES",
        motivo_ruta="SIN_ACCESO_VIAL", estado_ruta="SIN_ACCESO_VIAL",
    )
    dataset = _escribir_dataset(actual, [fila])
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[],
        ruta_salida=actual / "decisiones_pendientes.json",
    )

    revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_test")

    pendientes = _pendientes(actual)
    tipos = [(d["tipo"], d["documento"]["numero_guia"]) for d in pendientes]
    assert ("DESTINO_NO_RESUELTO", "472044") in tipos


def test_geocodifica_destino_confirmado_sin_coordenadas(tmp_path):
    """Parte "post-decisión": un destino ya CONFIRMADO (evidencia humana
    real) pero sin coordenadas se geocodifica solo, sin volver a
    preguntar nada."""
    carpeta = tmp_path / "catalogos"; carpeta.mkdir()
    (carpeta / "clientes.json").write_text('{"version_formato": 1, "clientes": []}', encoding="utf-8")
    catalogo = CatalogoDestinos(carpeta / "destinos_maestros.json", ruta_clientes=carpeta / "clientes.json")
    resuelto = catalogo.crear(
        cliente_id="", nombre_destino="CALLE RESOLUBLE 100", direccion="CALLE RESOLUBLE 100",
        pais="CHILE", fuente="TEST", estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    sin_resolver = catalogo.crear(
        cliente_id="", nombre_destino="CALLE IMPOSIBLE 200", direccion="CALLE IMPOSIBLE 200",
        pais="CHILE", fuente="TEST", estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        "CALLE RESOLUBLE 100, Chile": ResultadoGeocodificacion(
            EstadoRuta.REQUIERE_REVISION,
            (CandidatoGeocodificacion(Coordenadas(-70.6, -33.4), "Calle Resoluble 100, Chile", 0.9, "Santiago", "Metropolitana"),),
            "RESUELTO",
        ),
    })
    resultado = revalidar_destinos_confirmados_sin_coordenadas_sin_ocr(
        carpeta_catalogos=carpeta, proveedor_rutas=proveedor,
    )
    assert resuelto.destino_id in resultado["destinos_actualizados"]
    assert sin_resolver.destino_id not in resultado["destinos_actualizados"]
    actualizado = catalogo.obtener(resuelto.destino_id)
    assert actualizado.latitud == -33.4 and actualizado.longitud == -70.6
    intacto = catalogo.obtener(sin_resolver.destino_id)
    assert intacto.latitud is None and intacto.longitud is None
