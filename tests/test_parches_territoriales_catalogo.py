"""Parches territoriales en `revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr` (25/11/2026).

1) Caso real 484099 ("SAN MARTIN 262", CONCEPCION): la comuna del destino
   CONFIRMADO de la obra viaja al cálculo de ruta; sin ella el respaldo ubicó
   la calle homónima de Santiago.
2) Caso real 77a085b2 (HELSINSKI 5810 / LA REINA): coordenadas de un destino
   confirmado que la base territorial sitúa fuera de su propia comuna no se
   usan; la fila sigue pendiente.

Reutiliza el entorno y el flujo REGISTRAR_DIRECCION de
test_cierre_convergencia_destinos_catalogo (misma vía que usa Javier).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import atlas_core.rutas.destino_entrega as de
from atlas_core.catalogo_destinos import CatalogoDestinos
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos
from atlas_core.revalidacion_documental import revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr

_spec = importlib.util.spec_from_file_location(
    "base_convergencia", Path(__file__).with_name("test_cierre_convergencia_destinos_catalogo.py"))
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)


def _sembrar(tmp_path, direccion, proveedor, *, coordenadas=None):
    semilla = base._fila_csv(numero_guia="1", archivo="1.jpeg")
    entorno = base._entorno(tmp_path, filas_csv=[
        semilla,
        base._fila_csv(numero_guia="2", archivo="2.jpeg", numero_transporte="0000360002",
                       despachar_a_crudo=f"{direccion} CONCEPCION", estado_ruta="REQUIERE_REVISION",
                       motivo_ruta="MULTIPLES_UBICACIONES_DISPERSAS(2)"),
    ])
    sembrado = base._publicar_y_aplicar(entorno, fila_semilla={**semilla, "planta_origen_id": entorno["planta_id"]},
                                        direccion_manual=direccion, proveedor_rutas=proveedor)
    assert sembrado["ok"] is True
    catalogos = entorno["catalogos"]
    destinos = CatalogoObrasDestinos(ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
                                     ruta_destinos=catalogos / "destinos_maestros.json",
                                     ).listar_destinos_confirmados_para_obra(nombre_obra="OBRA TEST")
    assert len(destinos) == 1
    catalogo = CatalogoDestinos(catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json")
    cambios = {"comuna": "CONCEPCION"}
    if coordenadas:
        cambios.update(latitud=coordenadas[0], longitud=coordenadas[1])
    catalogo.editar(destinos[0].destino_id, modificacion_manual=True, **cambios)
    # La edición del catálogo dispara la revalidación reactiva; la fila 2
    # vuelve a su estado pendiente para ejercitar sólo la función parchada.
    filas = base._leer_csv(entorno["dataset"])
    for fila in filas:
        if fila["numero_guia"] == "2":
            fila.update(estado_ruta="REQUIERE_REVISION", motivo_ruta="MULTIPLES_UBICACIONES_DISPERSAS(2)",
                        distancia_km="", duracion_min="", proveedor_ruta="", direccion_entrega="")
    base._escribir_csv(entorno["dataset"], filas)
    return entorno


def test_parche_1_la_comuna_del_destino_confirmado_viaja_al_calculo(tmp_path, monkeypatch):
    direccion = "DIRECCION AMBIGUA 1"
    entorno = _sembrar(tmp_path, direccion, base._proveedor_siempre_ambiguo(direccion))
    llamadas = []
    original = de.calcular_ruta_con_planta_conocida

    def espia(**kw):
        llamadas.append((kw.get("comuna_territorial_conocida"), kw.get("comuna_confirmada_humano")))
        return original(**kw)

    monkeypatch.setattr(de, "calcular_ruta_con_planta_conocida", espia)
    revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        proveedor_rutas=base._proveedor_direccion_valida(direccion))
    assert llamadas and llamadas[-1] == ("CONCEPCION", "CONCEPCION")


def test_parche_2_coordenadas_fuera_de_su_comuna_no_se_usan(tmp_path, monkeypatch):
    direccion = "POETA PEDRO PRADO 1548"
    entorno = _sembrar(tmp_path, direccion, base._proveedor_direccion_valida(direccion),
                       coordenadas=(-33.436723, -70.634933))
    monkeypatch.setattr(de, "coordenada_de_destino_fuera_de_su_comuna",
                        lambda destino, base_local: "GEOCODIFICACION_FUERA_DE_COMUNA_CONOCIDA: Concepción (punto en X)")
    antes = base._leer_csv(entorno["dataset"])
    resultado = revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        proveedor_rutas=base._proveedor_direccion_valida("NUNCA_DEBERIA_CONSULTARSE"),
        proveedor_rutas_fallback=base._proveedor_direccion_valida("NUNCA_DEBERIA_CONSULTARSE"))
    assert "2" not in resultado["guias_actualizadas"]
    assert base._leer_csv(entorno["dataset"]) == antes


def test_parche_2_coordenadas_coherentes_se_siguen_usando(tmp_path, monkeypatch):
    direccion = "POETA PEDRO PRADO 1548"
    entorno = _sembrar(tmp_path, direccion, base._proveedor_direccion_valida(direccion),
                       coordenadas=(-33.436723, -70.634933))
    monkeypatch.setattr(de, "coordenada_de_destino_fuera_de_su_comuna", lambda destino, base_local: "")
    resultado = revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        proveedor_rutas=base._proveedor_direccion_valida("NUNCA_DEBERIA_CONSULTARSE"),
        proveedor_rutas_fallback=base._proveedor_direccion_valida("NUNCA_DEBERIA_CONSULTARSE"))
    assert "2" in resultado["guias_actualizadas"]
