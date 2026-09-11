"""Bloque SEPARAR CONOCIMIENTO DE DESTINO DE RESOLUCIÓN TÉCNICA DE RUTA --
caso real 464746 (CAM. EL NOVICIADO LAMPA LAMPA, EMPRESA CONSTRUCTORA
MENA Y).

La obra ya tiene una relación obra<->destino CONFIRMADA (nivel
CONFIRMACION_HUMANA, vía `DESTINO_SIN_CONFIRMAR`/`CONFIRMAR`) que cita
esta misma guía y cuyo destino coincide LITERALMENTE con el propio
`despachar_a_crudo` -- la identidad del destino ya está respondida. El
único problema real es `GEOCODIFICACION_DEMASIADO_GENERICA`: un camino
rural sin numeración, nada que un humano pueda "corregir". La tarjeta
`DESTINO_NO_RESUELTO` que vuelve a preguntar "¿cuál es el destino?" es
una pregunta duplicada -- se retira; el motivo de ruta sigue vivo en el
dataset (nunca se inventa una coordenada).

Regresión explícita: 464170 (misma clase de confirmación previa vía
`DESTINO_SIN_CONFIRMAR`/`CONFIRMAR`, pero motivo `GEOCODIFICACION_
NUMERO_INCOMPATIBLE`) NUNCA debe suprimirse por este mecanismo -- ese
motivo sí puede esconder una contradicción real."""
from __future__ import annotations

import csv
import json

from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
from atlas_core.catalogo_obras_destinos import (
    CatalogoObrasDestinos, Evidencia, ResultadoEvidencia, TipoEvidencia,
)
from atlas_core.decisiones_pendientes import (
    detectar_decision_destino_no_resuelto,
    guias_destino_conocido_ruta_pendiente,
    regenerar_decisiones_persistidas,
)
from atlas_core.fuente_catalogos import ARCHIVOS_REQUERIDOS
from atlas_core.procesamiento_masivo import COLUMNAS

OBRA = "EMPRESA CONSTRUCTORA MENA Y"
DESTINO_TEXTO = "CAM. EL NOVICIADO LAMPA LAMPA"


def _catalogos_base(carpeta):
    contenidos = {
        "choferes.json": {},
        "clientes.json": {"version_formato": 1, "clientes": []},
        "empresas.json": {},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
        "vehiculos.json": {},
        "plantas.json": {"plantas": []},
        "rutas.json": {"rutas": []},
    }
    for nombre in ARCHIVOS_REQUERIDOS:
        (carpeta / nombre).write_text(json.dumps(contenidos[nombre]), encoding="utf-8")
    (carpeta / "obras_destinos.json").write_text(
        json.dumps({"version_formato": 1, "obras": [], "relaciones": []}), encoding="utf-8",
    )


def _obra_confirmada_para_guia(catalogos, *, cliente_id, nombre_obra, guia, destino_texto):
    destinos = CatalogoDestinos(catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json")
    obras = CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    )
    # Caso real: `DESTINO_SIN_CONFIRMAR`/`CONFIRMAR` (R3_4) deja el Destino
    # en `estado_calidad=PENDIENTE` (nunca `CONFIRMADO` -- esa calidad la
    # deja únicamente `REGISTRAR_DIRECCION`/R6, o una geocodificación
    # exitosa) -- sin coordenadas ni ruta calculada, la supresión R13 YA
    # existente (`estado_calidad==CONFIRMADO` / coords / ruta_calculada)
    # NUNCA se activa sola aquí; sólo el mecanismo NUEVO bajo prueba
    # (restringido a `GEOCODIFICACION_DEMASIADO_GENERICA`) puede retirar
    # la tarjeta en este escenario.
    destino = destinos.crear(
        cliente_id="", nombre_destino=destino_texto, direccion=destino_texto,
        pais="CHILE", fuente="TEST", estado_calidad=EstadoCalidadDestino.PENDIENTE,
    )
    obs = obras.registrar_observacion(
        cliente_id=cliente_id, nombre_obra=nombre_obra, destino_id=destino.destino_id,
        evidencia=Evidencia(
            tipo=TipoEvidencia.GUIA.value, identificador_fuente=guia, referencia_hash="a" * 64,
            campos_observados={"obra": nombre_obra, "numero_guia": guia},
            fecha="2026-08-18T00:00:00+00:00", actor_proceso="TEST",
            resultado=ResultadoEvidencia.SOPORTA.value,
        ),
    )
    obras.confirmar_relacion(obs.relacion.relacion_id, actor="JAVIER_DESKTOP", identificador_fuente=guia)
    return obs.obra.obra_id


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "464746.jpeg", "numero_guia": "464746", "numero_transporte": "0000353160",
        "cliente": "EASY RETAIL SA", "obra_destino": OBRA,
        "planta_origen_id": "planta-aza-colina", "planta_origen_nombre": "AZA COLINA",
        "despachar_a_crudo": DESTINO_TEXTO,
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "GEOCODIFICACION_DEMASIADO_GENERICA",
        "indicador_revision": "OK", "estado_documental": "OK", "estado_operacional": "REQUIERE_REVISION",
    })
    fila.update(overrides)
    return fila


def _dataset(actual, filas):
    ruta = actual / "analisis_completo_guias.csv"
    with ruta.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        w.writerows(filas)
    return ruta


def _setup(tmp_path, *, motivo_ruta="GEOCODIFICACION_DEMASIADO_GENERICA",
           despachar_a_crudo=DESTINO_TEXTO, citar_guia=True, guia="464746"):
    catalogos = tmp_path / "catalogos"; catalogos.mkdir(); _catalogos_base(catalogos)
    actual = tmp_path / "actual"; actual.mkdir()
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="EASY RETAIL SA", rut="76123456-0", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    _obra_confirmada_para_guia(
        catalogos, cliente_id=cliente.cliente_id, nombre_obra=OBRA,
        guia=(guia if citar_guia else "999999"), destino_texto=DESTINO_TEXTO,
    )
    fila = _fila(numero_guia=guia, motivo_ruta=motivo_ruta, despachar_a_crudo=despachar_a_crudo)
    dataset = _dataset(actual, [fila])
    decision = detectar_decision_destino_no_resuelto(
        archivo=fila["archivo"], fila=fila, carpeta_catalogos=catalogos,
    )
    assert decision is not None, "fixture inválida -- el detector no generó ninguna tarjeta"
    return catalogos, dataset, decision


def test_tarjeta_generica_se_retira_con_obra_confirmada_y_texto_literal(tmp_path):
    catalogos, dataset, decision = _setup(tmp_path)
    salida = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert salida == []


def test_no_se_retira_si_el_motivo_es_numero_incompatible_464170(tmp_path):
    """Regresión -- mismo tipo de confirmación previa, motivo distinto:
    NUNCA se suprime (puede esconder una contradicción real)."""
    catalogos, dataset, decision = _setup(
        tmp_path, motivo_ruta="GEOCODIFICACION_NUMERO_INCOMPATIBLE: 843 != 898",
    )
    salida = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert [d["decision_id"] for d in salida] == [decision["decision_id"]]


def test_no_se_retira_si_el_texto_documental_no_coincide_literal(tmp_path):
    catalogos, dataset, decision = _setup(tmp_path, despachar_a_crudo="CAM. EL NOVICIADO LAMPA LAMPA KM 5")
    salida = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert [d["decision_id"] for d in salida] == [decision["decision_id"]]


def test_no_se_retira_si_la_relacion_confirmada_no_cita_esta_guia(tmp_path):
    catalogos, dataset, decision = _setup(tmp_path, citar_guia=False)
    salida = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert [d["decision_id"] for d in salida] == [decision["decision_id"]]


def test_helper_guias_destino_conocido_ruta_pendiente(tmp_path):
    catalogos, dataset, _decision = _setup(tmp_path)
    assert guias_destino_conocido_ruta_pendiente(
        carpeta_catalogos=catalogos, ruta_dataset=dataset,
    ) == frozenset({"464746"})


def test_helper_no_incluye_guia_con_motivo_numero_incompatible(tmp_path):
    catalogos, dataset, _decision = _setup(
        tmp_path, motivo_ruta="GEOCODIFICACION_NUMERO_INCOMPATIBLE: 843 != 898",
    )
    assert guias_destino_conocido_ruta_pendiente(
        carpeta_catalogos=catalogos, ruta_dataset=dataset,
    ) == frozenset()
