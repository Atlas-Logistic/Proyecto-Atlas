"""Bloque REVISIÓN DE ATLAS -- AUDITORÍA Y RESOLUCIÓN AUTÓNOMA V1.

Causa raíz real (472593): `CLIENTE_CANDIDATO` se genera SOLO por
coincidencia de nombre (`NOMBRE_SIN_RUT_CORROBORABLE`) cuando, al
momento de esa detección, no había RUT documental disponible/válido --
pero a diferencia de OBRA_DESCONOCIDA/DESTINO_SIN_CONFIRMAR, nunca se
reconciliaba después contra evidencia RUT que llegara más tarde. Para
472593 el RUT ("93.772.000-9") siempre existió, ya extraído por OCR,
en `envio.json` -- sólo nunca se propagó a la columna `rut_cliente`
del dataset (agregada DESPUÉS de que este documento se procesara,
Bloque RUT CLIENTE V1).

Dos piezas, cada una general (nunca ligada a esta guía):
1. `revalidar_rut_cliente_desde_mobile_sin_ocr`: sincroniza `rut_cliente`
   desde `envio.json` cuando el dataset lo trae vacío.
2. `regenerar_decisiones_persistidas`, nuevo bloque `tipo ==
   "CLIENTE_CANDIDATO"`: si el `rut_cliente` YA persistido resuelve al
   MISMO cliente que la decisión ya proponía, se retira (evidencia más
   fuerte que confirma); si resuelve a uno DISTINTO, es una
   contradicción real -- nunca se autoaplica, se conserva."""
from __future__ import annotations

import csv
import json

from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.decisiones_pendientes import crear_decision, regenerar_decisiones_persistidas
from atlas_core.mobile import RepositorioEnviosMobile
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_rut_cliente_desde_mobile_sin_ocr


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "mobile/envio-1/original.jpg", "estado_procesamiento": "OK",
        "numero_guia": "1", "numero_transporte": "T1", "fecha": "01-08-2026",
        "cliente": "CLIENTE GENERICO SA",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _leer(ruta):
    return list(csv.DictReader(ruta.open(encoding="utf-8-sig"), delimiter=";"))


def _crear_envio(repositorio, envio_id, *, rut_cliente):
    repositorio.guardar(envio_id, {
        "schema_version": 1, "envio_id": envio_id, "estado": "ASOCIADO_AUTOMATICAMENTE",
        "foto_original": "original.jpg", "datos_ocr": {"rut_cliente": rut_cliente},
    })


def _decision_cliente_candidato(*, numero_guia, entidad_id, valor_canonico, rut):
    return crear_decision(
        tipo="CLIENTE_CANDIDATO", entidad="CLIENTE", archivo="1.jpg",
        numero_guia=numero_guia, numero_transporte="T1", campo="cliente",
        valor_documental=valor_canonico, valor_normalizado=valor_canonico,
        identidad_resuelta={"entidad_id": entidad_id, "valor_canonico": valor_canonico, "rut": rut},
        candidatos=({"entidad_id": entidad_id, "valor_canonico": valor_canonico, "rut": rut},),
        motivos=("NOMBRE_SIN_RUT_CORROBORABLE",),
        evidencias=({"tipo": "NOMBRE_COINCIDENCIA_SEGURA", "campo": "cliente", "valor": valor_canonico},),
        acciones_permitidas=("CONFIRMAR", "NO_CONFIRMAR", "POSPONER"),
    )


# ============================================================
# 1/3. RUT válido en envio.json, ausente en el dataset -> sincroniza y resuelve
# ============================================================


def test_revalidar_rut_cliente_sincroniza_desde_envio_mobile(tmp_path):
    repo = RepositorioEnviosMobile(tmp_path)
    _crear_envio(repo, "envio-1", rut_cliente="93.772.000-9")
    fila = _fila(numero_guia="472593", cliente="PRODALAM SA", rut_cliente="")
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])

    resultado = revalidar_rut_cliente_desde_mobile_sin_ocr(ruta_dataset=dataset, repositorio=repo)
    assert resultado["guias_actualizadas"] == ["472593"]
    assert _leer(dataset)[0]["rut_cliente"] == "93772000-9"


def test_revalidar_rut_cliente_nunca_sobrescribe_uno_ya_persistido(tmp_path):
    repo = RepositorioEnviosMobile(tmp_path)
    _crear_envio(repo, "envio-1", rut_cliente="93.772.000-9")
    fila = _fila(numero_guia="1", rut_cliente="76.111.111-6")  # ya tiene un valor -- distinto a propósito
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])

    resultado = revalidar_rut_cliente_desde_mobile_sin_ocr(ruta_dataset=dataset, repositorio=repo)
    assert resultado["guias_actualizadas"] == []
    assert _leer(dataset)[0]["rut_cliente"] == "76.111.111-6"


def test_revalidar_rut_cliente_ignora_rut_documental_invalido(tmp_path):
    repo = RepositorioEnviosMobile(tmp_path)
    _crear_envio(repo, "envio-1", rut_cliente="11.111.111-2")  # DV inválido
    fila = _fila(numero_guia="1", rut_cliente="")
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])

    resultado = revalidar_rut_cliente_desde_mobile_sin_ocr(ruta_dataset=dataset, repositorio=repo)
    assert resultado["guias_actualizadas"] == []
    assert _leer(dataset)[0]["rut_cliente"] == ""


# ============================================================
# 1/3 (extremo a extremo, caso real): RUT sincronizado + CLIENTE_CANDIDATO se retira
# ============================================================


def test_cliente_candidato_se_retira_cuando_rut_ya_persistido_confirma_el_mismo_candidato(tmp_path):
    catalogos = tmp_path / "catalogos"
    catalogos.mkdir()
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []}, "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="CLIENTE GENERICO SA", rut="93.772.000-9", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    fila = _fila(numero_guia="472593", cliente="CLIENTE GENERICO SA", rut_cliente="93772000-9")
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])

    decision = _decision_cliente_candidato(
        numero_guia="472593", entidad_id=cliente.cliente_id,
        valor_canonico="CLIENTE GENERICO SA", rut=cliente.rut,
    )
    restantes = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert restantes == []


# ============================================================
# 4/10. Contradicción real RUT vs candidato propuesto -> nunca se autoaplica
# ============================================================


def test_cliente_candidato_se_conserva_si_rut_resuelve_a_otro_cliente_distinto(tmp_path):
    catalogos = tmp_path / "catalogos"
    catalogos.mkdir()
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []}, "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    catalogo_clientes = CatalogoClientes(catalogos / "clientes.json")
    candidato_propuesto = catalogo_clientes.crear(
        razon_social="CLIENTE PROPUESTO SA", rut="93.772.000-9", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    otro_cliente = catalogo_clientes.crear(
        razon_social="CLIENTE REAL DISTINTO SPA", rut="76.222.222-1", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    # El RUT que el documento realmente trae resuelve a OTRO cliente --
    # nunca al que la coincidencia de nombre había propuesto.
    fila = _fila(numero_guia="900001", cliente="CLIENTE PROPUESTO SA", rut_cliente="76222222-1")
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])

    decision = _decision_cliente_candidato(
        numero_guia="900001", entidad_id=candidato_propuesto.cliente_id,
        valor_canonico="CLIENTE PROPUESTO SA", rut=candidato_propuesto.rut,
    )
    restantes = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert len(restantes) == 1  # contradicción real -- se conserva, nunca se fuerza
    assert restantes[0]["tipo"] == "CLIENTE_CANDIDATO"


# ============================================================
# Sin RUT disponible -> se conserva igual que antes (ningún cambio de comportamiento)
# ============================================================


def test_cliente_candidato_se_conserva_sin_rut_disponible(tmp_path):
    catalogos = tmp_path / "catalogos"
    catalogos.mkdir()
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []}, "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="CLIENTE GENERICO SA", rut="93.772.000-9", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    fila = _fila(numero_guia="900002", cliente="CLIENTE GENERICO SA", rut_cliente="")
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])

    decision = _decision_cliente_candidato(
        numero_guia="900002", entidad_id=cliente.cliente_id,
        valor_canonico="CLIENTE GENERICO SA", rut=cliente.rut,
    )
    restantes = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert len(restantes) == 1


# ============================================================
# 11. Regeneración no duplica -- reconciliar dos veces produce el mismo resultado
# ============================================================


def test_regenerar_dos_veces_es_idempotente_para_cliente_candidato(tmp_path):
    catalogos = tmp_path / "catalogos"
    catalogos.mkdir()
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []}, "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="CLIENTE GENERICO SA", rut="93.772.000-9", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    fila = _fila(numero_guia="900003", cliente="CLIENTE GENERICO SA", rut_cliente="")
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    decision = _decision_cliente_candidato(
        numero_guia="900003", entidad_id=cliente.cliente_id,
        valor_canonico="CLIENTE GENERICO SA", rut=cliente.rut,
    )
    primera = regenerar_decisiones_persistidas(decisiones=[decision], carpeta_catalogos=catalogos, ruta_dataset=dataset)
    segunda = regenerar_decisiones_persistidas(decisiones=primera, carpeta_catalogos=catalogos, ruta_dataset=dataset)
    assert len(primera) == len(segunda) == 1


# ============================================================
# 12. Fixture universal -- otro rubro, nada relacionado con MBT/AZA/acero
# ============================================================


def test_fixture_universal_distribuidora_alimentos(tmp_path):
    repo = RepositorioEnviosMobile(tmp_path)
    _crear_envio(repo, "envio-2", rut_cliente="76.083.093-3")
    fila = _fila(
        archivo="mobile/envio-2/original.jpg", numero_guia="900004",
        cliente="DISTRIBUIDORA GENERICA SPA", rut_cliente="",
    )
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    resultado = revalidar_rut_cliente_desde_mobile_sin_ocr(ruta_dataset=dataset, repositorio=repo)
    assert resultado["guias_actualizadas"] == ["900004"]
    assert _leer(dataset)[0]["rut_cliente"] == "76083093-3"
