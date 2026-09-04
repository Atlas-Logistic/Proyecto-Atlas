"""Bloque CONVERGENCIA DE ESTADO -- caso real: viaje 0000355433, guías
472623+472624 (SODIMAC SA, tracto ND6443, rampla JB6878, destino SAN LUIS
1201 QUILICURA ya con ruta calculada 16,4 km / 22 min).

Causa raíz sistémica (no tres bugs de UI sueltos): varios `revalidar_*_
sin_ocr` retiran motivos de `motivos_revision_documento` y CADA UNO
reimplementaba por su cuenta el cálculo de `indicador_revision`/
`estado_documental`/`estado_operacional` -- algunos de forma incompleta
(`revalidar_patente_sin_homologar_sin_ocr` sólo actualizaba
`indicador_revision`). Por separado, la reevaluación de `estado` de un
envío Mobile sólo se disparaba cuando la ASOCIACIÓN en sí seguía sin
resolver -- un envío con asociación YA determinística pero `estado`
obsoleto por OTRA razón (la misma patente sin homologar) nunca se volvía
a mirar.

Esta prueba demuestra que, con las decisiones humanas YA resueltas
(`motivos_revision_documento` vacío + catálogo de vehículos CONFIRMADO,
exactamente el estado que deja `aplicar_decision_obra` tras los clics
reales de Javier) pero los campos DERIVADOS todavía obsoletos (el estado
real observado en producción), UNA sola reconciliación
(`reconciliar_estado_derivado`) converge TODOS los consumidores: el
dataset documental, el viaje (`gestor_viajes.agrupar_viajes`), y los DOS
envíos Mobile -- en un solo ciclo, sin edición manual, sin OCR."""
from __future__ import annotations

import csv
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from atlas_core.almacenamiento_portable import escribir_estado_operacion
from atlas_core.catalogo_vehiculos import TipoVehiculo, confirmar_vehiculo
from atlas_core.gestor_viajes import EstadoViaje, agrupar_viajes
from atlas_core.mobile import RepositorioEnviosMobile
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.reconciliacion_estado_derivado import reconciliar_estado_derivado

RELOJ = lambda: datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)
TRANSPORTE = "0000355433"


def _fila(numero_guia: str, archivo: str) -> dict[str, str]:
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": archivo, "estado_procesamiento": "OK", "numero_guia": numero_guia,
        "numero_transporte": TRANSPORTE, "fecha": "26-08-2026", "chofer": "LUIS REYES",
        "cliente": "SODIMAC SA", "obra_destino": "No encontrado",
        "patente_tracto": "ND6443", "patente_rampla": "JB6878",
        "despachar_a_crudo": "SAN LUIS 1201 QUILICURA", "direccion_entrega": "SAN LUIS 1201 QUILICURA",
        "localidad_entrega": "Quilicura", "region_entrega": "Metropolitana",
        "estado_ruta": "RUTA_CALCULADA", "motivo_ruta": "",
        "distancia_km": "16.3682", "duracion_min": "22.438333333333333",
        "proveedor_ruta": "openrouteservice",
        "planta_origen_id": "planta-colina", "planta_origen_nombre": "AZA COLINA",
        "origen_determinado_por": "MOBILE", "evidencia_origen": "MOBILE_INFORMADO",
        # Bloque CONVERGENCIA DE ESTADO -- estado REAL observado: la
        # decisión humana YA resolvió la patente (ningún motivo real
        # queda en la columna), pero los tres campos derivados quedaron
        # obsoletos -- exactamente el estado real de 472623/472624 antes
        # de este fix.
        "motivos_revision_documento": "", "indicador_revision": "REVISAR",
        "estado_documental": "REQUIERE_REVISION", "estado_operacional": "REQUIERE_REVISION",
    })
    return fila


def _recibir_envio(repo: RepositorioEnviosMobile) -> str:
    envio_id = str(uuid.uuid4())
    repo.recibir(
        envio_id=envio_id, imagen=b"foto", mime="image/jpeg",
        metadata={"chofer_id": "JAVIER_MBT", "tipo_novedad": "", "guia_firmada_correo": False, "planta_origen_informada": "AZA_COLINA"},
    )
    return envio_id


def _dejar_envio_asociado_pero_obsoleto(repo: RepositorioEnviosMobile, envio_id: str, *, numero_guia: str, archivo: str) -> None:
    """Deja el envío EXACTAMENTE como quedó el real tras la asociación
    determinística automática -- `resultado_asociacion` ya resuelto
    ("coincidencia exacta determinista"), pero `estado` todavía
    `REQUIERE_REVISION` porque `datos_ocr.indicador_revision` es la foto
    FIJA tomada al procesar (antes de que la decisión humana retirara el
    motivo de patente) -- nunca se vuelve a tocar sola."""
    registro = repo.cargar(envio_id)
    registro["foto_original"] = "original.jpg"
    registro["datos_ocr"] = {
        "numero_guia": numero_guia, "numero_transporte": TRANSPORTE,
        "indicador_revision": "REVISAR",  # foto fija -- nunca se actualiza sola
    }
    registro["resultado_asociacion"] = {
        "estado": "ASOCIADO_AUTOMATICAMENTE", "numero_transporte": TRANSPORTE,
        "numero_guia": numero_guia, "candidatos": [TRANSPORTE],
        "motivo": "Coincidencia exacta determinista de guía/transporte.",
        "documento_ya_existe": False,
    }
    registro["estado"] = "REQUIERE_REVISION"
    repo.guardar(envio_id, registro)
    return archivo


def test_dos_guias_mobile_mismo_viaje_decisiones_resueltas_convergen_en_un_solo_ciclo(tmp_path):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "empresas.json": {}, "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")

    # Catálogo de vehículos: las decisiones humanas de Javier YA quedaron
    # persistidas -- ambas patentes CONFIRMADAS, una sola vez cada una
    # (nunca se reprocesa ni se edita a mano en esta prueba).
    confirmar_vehiculo(
        catalogos / "vehiculos.json", patente="ND6443", tipo=TipoVehiculo.TRACTO,
        actor="JAVIER_MBT", fuente_decision="DECISION_HUMANA_R3_6:d1", fecha=RELOJ(),
    )
    confirmar_vehiculo(
        catalogos / "vehiculos.json", patente="JB6878", tipo=TipoVehiculo.CARRO,
        actor="JAVIER_MBT", fuente_decision="DECISION_HUMANA_R3_6:d2", fecha=RELOJ(),
    )

    repo = RepositorioEnviosMobile(raiz)
    envio_a = _recibir_envio(repo)
    envio_b = _recibir_envio(repo)
    archivo_a = f"mobile/{envio_a}/original.jpg"
    archivo_b = f"mobile/{envio_b}/original.jpg"
    _dejar_envio_asociado_pero_obsoleto(repo, envio_a, numero_guia="472623", archivo=archivo_a)
    _dejar_envio_asociado_pero_obsoleto(repo, envio_b, numero_guia="472624", archivo=archivo_b)

    dataset = actual / "analisis_completo_guias.csv"
    filas = [_fila("472623", archivo_a), _fila("472624", archivo_b)]
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)

    decisiones = actual / "decisiones_pendientes.json"
    decisiones.write_text(json.dumps({"schema_version": 1, "decisiones": []}), encoding="utf-8")

    reporte_previo = raiz / "reportes" / "previo"
    reporte_previo.mkdir(parents=True)
    escribir_estado_operacion(
        reporte_vigente=reporte_previo, dataset_operacional=dataset,
        decisiones_pendientes=decisiones, raiz=raiz, reloj=RELOJ,
    )

    # ============================================================
    # UNA sola reconciliación natural -- nada de edición manual, nada de OCR.
    # ============================================================
    resultado = reconciliar_estado_derivado(raiz_atlas=raiz, reloj=RELOJ)
    assert resultado["reconciliado"] is True

    # -- 1. Dataset documental: los tres campos derivados convergen a OK,
    #    y lo que ya estaba resuelto se PRESERVA intacto.
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        filas_finales = {f["numero_guia"]: f for f in csv.DictReader(archivo, delimiter=";")}
    for guia in ("472623", "472624"):
        fila = filas_finales[guia]
        assert fila["indicador_revision"] == "OK"
        assert fila["estado_documental"] == "OK"
        assert fila["estado_operacional"] == "OK"
        assert fila["estado_ruta"] == "RUTA_CALCULADA"
        assert fila["distancia_km"] == "16.3682"
        assert fila["duracion_min"] == "22.438333333333333"
        assert fila["patente_tracto"] == "ND6443"
        assert fila["patente_rampla"] == "JB6878"

    # -- 2. Viaje: CONFIRMADO, nunca "Pendiente técnico" -- la ruta YA
    #    está calculada y ningún motivo real sigue pendiente.
    viajes, _ = agrupar_viajes(list(filas_finales.values()), guias_revision_humana=set())
    assert len(viajes) == 1
    assert viajes[0].estado == EstadoViaje.CONFIRMADO

    # -- 3. Mobile: los DOS envíos convergen a ASOCIADO -- la asociación
    #    determinística NUNCA se reinventa (sigue ASOCIADO_AUTOMATICAMENTE,
    #    mismo transporte, nunca "Confirmar viaje" innecesario).
    for envio_id in (envio_a, envio_b):
        registro = repo.cargar(envio_id)
        assert registro["estado"] == "ASOCIADO"
        assert registro["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"
        assert registro["resultado_asociacion"]["numero_transporte"] == TRANSPORTE

    # -- 4. 0 decisiones pendientes -- coherente con el badge de Revisión
    #    de Atlas (que sólo cuenta pendientes reales + envíos Mobile
    #    REQUIERE_REVISION, ambos ya en cero).
    bandeja = json.loads(decisiones.read_text(encoding="utf-8"))
    assert bandeja["decisiones"] == []
