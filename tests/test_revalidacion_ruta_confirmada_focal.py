"""Revalidación focal de una ruta con destino humano ya confirmado.

Todo el entorno es temporal y los proveedores son simulados: no hay OCR,
geocodificación real, reconciliación global ni datos operacionales.
"""
from __future__ import annotations

import csv
import json

from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
from atlas_core.catalogo_obras_destinos import (
    CatalogoObrasDestinos, Evidencia, ResultadoEvidencia, TipoEvidencia,
)
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core import mantenimiento_pendientes_tecnicos as mantenimiento
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado


def _fila(guia: str, direccion: str) -> dict[str, str]:
    fila = {columna: "" for columna in COLUMNAS}
    fila.update({
        "archivo": f"{guia}.png", "numero_guia": guia, "numero_transporte": f"T-{guia}",
        "cliente": "CLIENTE TEST", "obra_destino": "OBRA QUILICURA",
        "indicador_revision": "OK", "estado_documental": "OK",
        "planta_origen_nombre": "PLANTA TEST", "origen_determinado_por": "TEST",
        "evidencia_origen": "TEST", "despachar_a_crudo": direccion,
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "COORDENADA_NO_CONFIRMADA(5)",
        "estado_operacional": "REQUIERE_REVISION",
    })
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _leer_csv(ruta):
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return {fila["numero_guia"]: fila for fila in csv.DictReader(archivo, delimiter=";")}


def _entorno(tmp_path):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    cliente = {
        "cliente_id": "cliente-test", "razon_social": "CLIENTE TEST",
        "nombre_normalizado": "CLIENTE TEST", "nombre_comercial": "", "rut": "76086428-5",
        "aliases": [], "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO",
        "fuente": "TEST", "observacion": "",
        "fecha_creacion": "2026-01-01T00:00:00+00:00",
        "fecha_modificacion": "2026-01-01T00:00:00+00:00",
    }
    (catalogos / "clientes.json").write_text(json.dumps({"version_formato": 1, "clientes": [cliente]}), encoding="utf-8")
    (catalogos / "destinos_maestros.json").write_text(json.dumps({"version_formato": 1, "destinos": []}), encoding="utf-8")
    (catalogos / "obras_destinos.json").write_text(json.dumps({"version_formato": 1, "obras": [], "relaciones": []}), encoding="utf-8")
    (catalogos / "empresas.json").write_text("{}", encoding="utf-8")
    (catalogos / "vehiculos.json").write_text(json.dumps({"version": 1, "vehiculos": []}), encoding="utf-8")
    planta = CatalogoPlantas(catalogos / "plantas.json").crear(
        nombre="PLANTA TEST", pais="CHILE", fuente="TEST", direccion="PLANTA 1",
        comuna="COLINA", region="RM", latitud=-33.13, longitud=-70.66,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    destino = CatalogoDestinos(catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json").crear(
        cliente_id="cliente-test", nombre_destino="SAN LUIS 1201", direccion="SAN LUIS 1201, QUILICURA",
        comuna="QUILICURA", region="RM", pais="CHILE", fuente="TEST",
        estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    obras = CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    )
    observacion = obras.registrar_observacion(
        cliente_id="cliente-test", nombre_obra="OBRA QUILICURA", destino_id=destino.destino_id,
        evidencia=Evidencia(
            tipo=TipoEvidencia.GUIA.value, identificador_fuente="semilla", referencia_hash="h",
            campos_observados={"obra": "OBRA QUILICURA"}, fecha="2026-01-01T00:00:00+00:00",
            actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value,
        ),
    )
    obras.confirmar_relacion(observacion.relacion.relacion_id, actor="TEST")
    return raiz, catalogos, actual, planta.planta_id


def _proveedor_simulado():
    return ProveedorRutasSimulado(
        geocodificaciones={
            "SAN LUIS 1201, QUILICURA, Chile": ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(
                    Coordenadas(-70.72, -33.36), "SAN LUIS 1201, QUILICURA, RM, Chile", 1.0,
                    "QUILICURA", "RM",
                ),), "",
            ),
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 20.5, 31.0, "SIMULADO"),
    )


def test_revalidacion_focal_resuelve_solo_482461_y_preserva_registros_ajenos(tmp_path, monkeypatch):
    raiz, catalogos, actual, planta_id = _entorno(tmp_path)
    objetivo = _fila("482461", "SAN LUIS 1201, QUILICURA")
    ajena = _fila("999999", "OTRA DIRECCION 99")
    objetivo["planta_origen_id"] = ajena["planta_origen_id"] = planta_id
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [objetivo, ajena])
    (actual / "pendientes_tecnicos.json").write_text(json.dumps({
        "schema_version": 1,
        "pendientes": [{"numero_guia": "482461", "marca": "objetivo"}, {"numero_guia": "999999", "marca": "ajena"}],
    }), encoding="utf-8")
    tarjeta_ajena_antes = [{"decision_id": "ajena", "documento": {"numero_guia": "999999"}}]
    (actual / "decisiones_pendientes.json").write_text(
        json.dumps({"decisiones": tarjeta_ajena_antes}), encoding="utf-8"
    )
    llamadas_tarjeta = []

    def _publicar_solo_objetivo(*, guias_objetivo, **_):
        llamadas_tarjeta.append(guias_objetivo)
        # Doble de la publicación focal: no recibe autorización para tocar
        # una tarjeta ajena y deja el artefacto exactamente como estaba.
        return {"decisiones_publicadas": 1}

    monkeypatch.setattr(mantenimiento, "reconciliar_decisiones_destino_no_resuelto", _publicar_solo_objetivo)

    resultado = mantenimiento.revalidar_ruta_confirmada_focal(
        raiz_atlas=raiz, numero_guia="482461", proveedor_rutas=_proveedor_simulado(),
        proveedor_rutas_fallback=_proveedor_simulado(),
    )

    assert resultado["ejecutado"] is True
    assert resultado["ruta_resuelta"] is True
    assert resultado["pendiente_tecnico_retirado"] is True
    filas = _leer_csv(dataset)
    assert filas["482461"]["estado_ruta"] == "RUTA_CALCULADA"
    assert filas["482461"]["motivo_ruta"] == ""
    assert filas["482461"]["despachar_a_crudo"] == "SAN LUIS 1201, QUILICURA"
    assert filas["999999"] == ajena
    pendientes = json.loads((actual / "pendientes_tecnicos.json").read_text(encoding="utf-8"))["pendientes"]
    assert pendientes == [{"numero_guia": "999999", "marca": "ajena"}]
    tarjeta_ajena_despues = json.loads((actual / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]
    assert tarjeta_ajena_despues == tarjeta_ajena_antes
    assert llamadas_tarjeta == [{"482461"}]
