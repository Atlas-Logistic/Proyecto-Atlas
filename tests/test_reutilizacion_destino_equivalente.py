"""P0 -- no crear un destino nuevo cuando ya existe uno equivalente.

Casos reales de la auditoría del catálogo de destinos (CASA, 18/11/2026):
R6/R3_4/registro conjunto creaban otro destino cada vez que la dirección
confirmada no coincidía LITERALMENTE con una existente (CAMINO LO RUIZ 2901
x3, VISTA CLARA 2351 x2, PDTE. RIESCO 5903, AV GOLFO DE ARAUCO 3536...).
Ahora, antes de crear, se busca un destino del mismo punto en todo el
catálogo: uno -> se reutiliza; varios / comuna incierta / coordenada no
verificable o contradictoria -> abstención (nunca se elige ni se crea).
Los 35 pares legítimamente distintos del catálogo real nunca se igualan.
Copias sintéticas; ningún dato operacional."""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import pytest

from atlas_core.aplicacion_decisiones import ErrorAplicacionDecision, aplicar_decision_obra
from atlas_core.catalogo_destinos import (
    MOTIVO_EQUIVALENTE_COMUNA_INCIERTA, MOTIVO_EQUIVALENTE_COORDENADA_CONTRADICTORIA,
    MOTIVO_EQUIVALENTE_COORDENADA_FUERA_DE_COMUNA, MOTIVO_EQUIVALENTE_COORDENADA_NO_VERIFICABLE,
    MOTIVO_EQUIVALENTE_DE_LA_OBRA, MOTIVO_EQUIVALENTE_UNICO, MOTIVO_EQUIVALENTES_MULTIPLES,
    CatalogoDestinos, ErrorCatalogoDestinos, EstadoBusquedaDestino, EstadoCalidadDestino,
    nucleo_direccion_equivalente,
)
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, ResultadoEvidencia, TipoEvidencia
from atlas_core.decisiones_pendientes import generar_artefacto
from atlas_core.geografia.base_local import NOMBRE_ARCHIVO_PREDETERMINADO

from tests.test_destinos_confirmacion_r34 import _entorno, _pendientes

DATOS = Path(__file__).parent / "datos" / "destinos_pares_legitimamente_distintos_20261118.json"


def _catalogo(tmp_path):
    carpeta = tmp_path / "Atlas" / "catalogos_privados"
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "clientes.json").write_text(json.dumps({"version_formato": 1, "clientes": []}), encoding="utf-8")
    return CatalogoDestinos(carpeta / "destinos_maestros.json", ruta_clientes=carpeta / "clientes.json")


def _crear(catalogo, direccion, comuna="", region="", *, calidad=EstadoCalidadDestino.CONFIRMADO,
           latitud=None, longitud=None, fuente="PRUEBA"):
    return catalogo.crear(cliente_id="", nombre_destino=direccion, direccion=direccion, comuna=comuna,
                          region=region, pais="CHILE", fuente=fuente, latitud=latitud, longitud=longitud,
                          estado_calidad=calidad)


def _base_territorial(catalogo, puntos):
    """Base local mínima junto a la raíz del catálogo: (codigo_comuna, lat, lon)."""
    ruta = catalogo.ruta.parent.parent / "datos_privados" / "geografia" / NOMBRE_ARCHIVO_PREDETERMINADO
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta)
    con.execute("CREATE TABLE direcciones (codigo_comuna TEXT, calle_normalizada TEXT, numero TEXT, "
                "calle_canonica TEXT, comuna_canonica TEXT, lon REAL, lat REAL, fuente TEXT)")
    con.executemany("INSERT INTO direcciones VALUES (?, 'X', '1', 'X', '', ?, ?, 'TEST')",
                    [(codigo, lon, lat) for codigo, lat, lon in puntos])
    con.commit(); con.close()


def _crear_o_reutilizar(catalogo, direccion, comuna="", region="", **extra):
    return catalogo.crear_o_reutilizar_global(
        nombre_destino=direccion, direccion=direccion, comuna=comuna, region=region,
        fuente="DECISION_HUMANA_R6:prueba", estado_calidad=EstadoCalidadDestino.CONFIRMADO, **extra)


def _instantanea(catalogo):
    return {d.destino_id: d.a_dict() for d in catalogo.listar()}


# --------------------------------------------------------------- núcleo

@pytest.mark.parametrize("direccion, nucleo", [
    ("CAMINO LO RUIZ 2901, RENCA, CHILE", "CAMINO LO RUIZ 2901"),
    ("CAMINO LO RUIZ 2901, RENCA", "CAMINO LO RUIZ 2901"),
    ("VISTA CLARA 2351, CERRILLOS, REGIÓN METROPOLITANA, CHILE", "VISTA CLARA 2351"),
    ("AVDA IRARRAZAVAL 5497 SANTIAGO NUNOA", "AVENIDA IRARRAZAVAL 5497"),
    ("MURCIA 4650 SAN MIGUEL SAN MIGUEL", "MURCIA 4650"),
    ("AV. 4 NORTE 1565, SAN PEDRO DE LA PAZ, CHILE", "AVENIDA 4 NORTE 1565"),
    ("VISTA CLARA 2351CERRILLOS", "VISTA CLARA 2351"),
    # Un calificador tras la numeración puede ser otro punto: no se iguala.
    ("CERRO SAN LUIS 9890 B SANTIAGO", ""),
    ("LAS VIOLETAS 55 SECTOR LA ESPERANZA, PADRE HURTADO, CHILE", ""),
    ("CALLE COQUIMBO S/N", ""),
    ("CAMINO LO AGUIRRE SUR", ""),
])
def test_nucleo_direccion_equivalente(direccion, nucleo):
    assert nucleo_direccion_equivalente(direccion) == nucleo


# --------------------------------------------- reutilización: casos reales

@pytest.mark.parametrize("existente, nuevo", [
    # 472710 (R3_4, 15/09): existía 7df58eec confirmado.
    (("CAMINO LO RUIZ 2901, RENCA, CHILE", "RENCA", "RM"), ("CAMINO LO RUIZ 2901", "RENCA", "")),
    # 483208 (R6, 27/10): existía ccfda74d confirmado.
    (("CAMINO LO RUIZ 2901", "RENCA", ""), ("CAMINO LO RUIZ 2901, RENCA", "Renca", "")),
    # 483267 (R6, 27/10): comuna "Santiago" (ciudad) y la dirección nombra Cerrillos.
    (("VISTA CLARA 2351, CERRILLOS, REGIÓN METROPOLITANA, CHILE", "CERRILLOS", "REGIÓN METROPOLITANA"),
     ("VISTA CLARA 2351, CERRILLOS", "Santiago", "Metropolitana")),
    # 482378 (R6, 19/10).
    (("PDTE. RIESCO 5903, LAS CONDES, CHILE", "LAS CONDES", "RM"), ("PDTE. RIESCO 5903", "LAS CONDES", "")),
    # 83277 (R3_4, 28/10): la copia nueva quedó con una coordenada en Conchalí.
    (("HELSINSKI 5810 LA REINA SANTIAGO", "LA REINA", ""), ("HELSINSKI 5810", "LA REINA", "")),
    # 4a04fa3f (R6, 22/08): comuna dentro de la dirección, abreviatura de vía.
    (("AVDA IRARRAZAVAL 5497 SANTIAGO NUNOA", "", ""), ("Av. Irarrazaval 5497 ñuñoa", "Ñuñoa", "")),
])
def test_reutiliza_el_unico_destino_equivalente(tmp_path, existente, nuevo):
    catalogo = _catalogo(tmp_path)
    previo = _crear(catalogo, *existente)
    antes = _instantanea(catalogo)
    resultado = _crear_o_reutilizar(catalogo, *nuevo)
    assert resultado.destino_id == previo.destino_id
    # Nada más cambia: mismo registro, misma dirección/fuente/coordenadas.
    assert _instantanea(catalogo) == antes
    busqueda = catalogo.buscar_reutilizable_global(nuevo[0], comuna=nuevo[1], region=nuevo[2])
    assert busqueda.motivo == MOTIVO_EQUIVALENTE_UNICO


def test_la_via_exacta_no_cambia(tmp_path):
    catalogo = _catalogo(tmp_path)
    previo = _crear(catalogo, "CAMINO LO RUIZ 2901, RENCA, CHILE", "RENCA", "RM")
    busqueda = catalogo.buscar_reutilizable_global("CAMINO LO RUIZ 2901, RENCA, CHILE", comuna="RENCA", region="RM")
    assert busqueda.destino.destino_id == previo.destino_id and busqueda.motivo == ""


def test_varios_equivalentes_se_abstiene_y_no_crea(tmp_path):
    # CAMINO LO RUIZ 2901: 7df58eec y ccfda74d ya eran dos confirmados.
    catalogo = _catalogo(tmp_path)
    _crear(catalogo, "CAMINO LO RUIZ 2901, RENCA, CHILE", "RENCA", "RM")
    _crear(catalogo, "CAMINO LO RUIZ 2901", "RENCA", "")
    antes = _instantanea(catalogo)
    busqueda = catalogo.buscar_reutilizable_global("CAMINO LO RUIZ 2901, RENCA", comuna="Renca")
    assert busqueda.estado == EstadoBusquedaDestino.AMBIGUA and busqueda.motivo == MOTIVO_EQUIVALENTES_MULTIPLES
    with pytest.raises(ErrorCatalogoDestinos, match="ambigua"):
        _crear_o_reutilizar(catalogo, "CAMINO LO RUIZ 2901, RENCA", "Renca")
    assert _instantanea(catalogo) == antes


def test_la_relacion_confirmada_de_la_obra_desempata(tmp_path):
    # 483208: ccfda74d era el destino CONFIRMADO de la obra ACEROS COX.
    catalogo = _catalogo(tmp_path)
    _crear(catalogo, "CAMINO LO RUIZ 2901, RENCA, CHILE", "RENCA", "RM")
    de_la_obra = _crear(catalogo, "CAMINO LO RUIZ 2901", "RENCA", "")
    resultado = _crear_o_reutilizar(catalogo, "CAMINO LO RUIZ 2901, RENCA", "Renca",
                                    destinos_obra=[de_la_obra.destino_id])
    assert resultado.destino_id == de_la_obra.destino_id and len(catalogo.listar()) == 2
    assert catalogo.buscar_reutilizable_global(
        "CAMINO LO RUIZ 2901, RENCA", comuna="Renca", destinos_obra=[de_la_obra.destino_id],
    ).motivo == MOTIVO_EQUIVALENTE_DE_LA_OBRA


def test_comuna_incierta_se_abstiene_salvo_relacion_de_la_obra(tmp_path):
    # 464265 (R6, 07/09): AV GOLFO DE ARAUCO 3536 existía sin comuna (06b79e25).
    catalogo = _catalogo(tmp_path)
    sin_comuna = _crear(catalogo, "AV GOLFO DE ARAUCO 3536")
    busqueda = catalogo.buscar_reutilizable_global("AV GOLFO DE ARAUCO 3536", comuna="Coronel")
    assert busqueda.estado == EstadoBusquedaDestino.AMBIGUA and busqueda.motivo == MOTIVO_EQUIVALENTE_COMUNA_INCIERTA
    resultado = _crear_o_reutilizar(catalogo, "AV GOLFO DE ARAUCO 3536", "Coronel",
                                    destinos_obra=[sin_comuna.destino_id])
    assert resultado.destino_id == sin_comuna.destino_id and len(catalogo.listar()) == 1


def test_un_equivalente_nunca_recibe_coordenadas_y_solo_se_promueve(tmp_path):
    catalogo = _catalogo(tmp_path)
    pendiente = _crear(catalogo, "PEDRO RIVEROS 1411, QUILICURA, CHILE", "QUILICURA", "RM",
                       calidad=EstadoCalidadDestino.PENDIENTE)
    resultado = _crear_o_reutilizar(catalogo, "PEDRO RIVEROS 1411", "QUILICURA",
                                    latitud=-33.36, longitud=-70.73)
    assert resultado.destino_id == pendiente.destino_id
    assert resultado.estado_calidad == "CONFIRMADO"
    assert resultado.latitud is None and resultado.longitud is None
    assert resultado.direccion == pendiente.direccion and resultado.fuente == pendiente.fuente


def test_coordenada_del_llamador_contradictoria_se_abstiene(tmp_path):
    catalogo = _catalogo(tmp_path)
    _crear(catalogo, "SANTA ISABEL 585, LAMPA, CHILE", "LAMPA", "RM", latitud=-33.310665, longitud=-70.737609)
    busqueda = catalogo.buscar_reutilizable_global("SANTA ISABEL 585", comuna="LAMPA",
                                                   latitud=-33.307635, longitud=-70.733135)  # 535 m
    assert busqueda.estado == EstadoBusquedaDestino.AMBIGUA
    assert busqueda.motivo == MOTIVO_EQUIVALENTE_COORDENADA_CONTRADICTORIA


# ------------------- PENDIENTE con coordenada (decisión de Javier 18/11/2026)

RENCA, SAN_MIGUEL = "13128", "13130"


def test_pendiente_con_coordenada_en_su_comuna_se_reutiliza_sin_tocarla(tmp_path):
    # 472148 (R3_4, 10/09): CAMINO LO RUIZ 3099 existía como PENDIENTE de la migración.
    catalogo = _catalogo(tmp_path)
    _base_territorial(catalogo, [(RENCA, -33.4030, -70.6870)])
    pendiente = _crear(catalogo, "CAMINO LO RUIZ 3099, RENCA, CHILE", "RENCA", "RM",
                       calidad=EstadoCalidadDestino.PENDIENTE, latitud=-33.402531, longitud=-70.686461)
    resultado = _crear_o_reutilizar(catalogo, "CAMINO LO RUIZ 3099", "RENCA")
    assert resultado.destino_id == pendiente.destino_id and resultado.estado_calidad == "CONFIRMADO"
    assert (resultado.latitud, resultado.longitud) == (-33.402531, -70.686461)


def test_pendiente_con_coordenada_fuera_de_su_comuna_se_abstiene(tmp_path):
    # 475629 (R3_4, 09/10): CARLOS VALDOVINOS 1553 PENDIENTE con coordenada en
    # la región de Coquimbo (-30,81): nunca se confirma esa coordenada.
    catalogo = _catalogo(tmp_path)
    _base_territorial(catalogo, [(SAN_MIGUEL, -33.4960, -70.6510)])
    _crear(catalogo, "CARLOS VALDOVINOS 1553, SAN MIGUEL, CHILE", "SAN MIGUEL", "RM",
           calidad=EstadoCalidadDestino.PENDIENTE, latitud=-30.81432, longitud=-70.60342)
    antes = _instantanea(catalogo)
    busqueda = catalogo.buscar_reutilizable_global("CARLOS VALDOVINOS 1553", comuna="SAN MIGUEL")
    assert busqueda.motivo == MOTIVO_EQUIVALENTE_COORDENADA_FUERA_DE_COMUNA
    with pytest.raises(ErrorCatalogoDestinos, match="ambigua"):
        _crear_o_reutilizar(catalogo, "CARLOS VALDOVINOS 1553", "SAN MIGUEL")
    assert _instantanea(catalogo) == antes


def test_pendiente_con_coordenada_sin_base_territorial_se_abstiene(tmp_path):
    catalogo = _catalogo(tmp_path)
    _crear(catalogo, "LAUTARO 9202, QUILICURA, CHILE", "QUILICURA", "RM",
           calidad=EstadoCalidadDestino.PENDIENTE, latitud=-33.35, longitud=-70.73)
    busqueda = catalogo.buscar_reutilizable_global("LAUTARO 9202", comuna="QUILICURA")
    assert busqueda.motivo == MOTIVO_EQUIVALENTE_COORDENADA_NO_VERIFICABLE


def test_pendiente_sin_coordenada_se_reutiliza(tmp_path):
    catalogo = _catalogo(tmp_path)
    pendiente = _crear(catalogo, "VIA MORADA 6480 VITACURA", "VITACURA", calidad=EstadoCalidadDestino.PENDIENTE)
    assert _crear_o_reutilizar(catalogo, "VIA MORADA 6480", "VITACURA").destino_id == pendiente.destino_id


# --------------------------------------------- nunca iguala lugares distintos

@pytest.mark.parametrize("existente, nuevo", [
    (("SANTA ISABEL 585, LAMPA, CHILE", "LAMPA", "RM"), ("SANTA ISABEL 585", "COLINA", "")),
    (("CERRO SAN LUIS 9890, QUILICURA, CHILE", "QUILICURA", "RM"), ("CERRO SAN LUIS 9890 B SANTIAGO", "QUILICURA", "")),
    (("MARURI 1492, RENCA, CHILE", "RENCA", "RM"), ("MARURI 1942", "RENCA", "")),
    (("CAMINO LOS PINOS 3394, SAN BERNARDO, CHILE", "SAN BERNARDO", "RM"), ("CAMINO LOS PINOS 3396", "SAN BERNARDO", "")),
    (("CLAUDIO ARRAU 6810", "PUDAHUEL", ""), ("CLAUDIO ARRAU 9440", "PUDAHUEL", "")),
    (("CAMINO LO RUIZ 2901", "RENCA", ""), ("CAMINO LO RUIZ 3099", "RENCA", "")),
    (("CALLE COQUIMBO S/N", "COLINA", ""), ("CALLE COQUIMBO S/N", "COLINA", "RM")),
    (("CAMINO A MELIPILLA 10800", "MAIPU", ""), ("CAMINO A MELIPILLA 10338", "MAIPU", "")),
    (("LO RUIZ 2901", "RENCA", ""), ("CAMINO LO RUIZ 2901", "RENCA", "")),
])
def test_no_iguala_lugares_distintos(tmp_path, existente, nuevo):
    catalogo = _catalogo(tmp_path)
    previo = _crear(catalogo, *existente)
    resultado = _crear_o_reutilizar(catalogo, *nuevo)
    assert resultado.destino_id != previo.destino_id and len(catalogo.listar()) == 2


def _pares_reales():
    datos = json.loads(DATOS.read_text(encoding="utf-8"))
    assert len(datos["pares"]) == 35
    for indice, par in enumerate(datos["pares"]):
        yield pytest.param(par["a"], par["b"], id=f"par{indice:02d}-a-existe")
        yield pytest.param(par["b"], par["a"], id=f"par{indice:02d}-b-existe")


@pytest.mark.parametrize("existente, nuevo", list(_pares_reales()))
def test_los_35_pares_legitimamente_distintos_del_catalogo_real_no_se_igualan(tmp_path, existente, nuevo):
    catalogo = _catalogo(tmp_path)
    _crear(catalogo, existente["direccion"], existente["comuna"], existente["region"],
           calidad=existente["estado_calidad"], latitud=existente["latitud"], longitud=existente["longitud"])
    busqueda = catalogo.buscar_reutilizable_global(nuevo["direccion"], comuna=nuevo["comuna"], region=nuevo["region"])
    assert busqueda.estado == EstadoBusquedaDestino.SIN_COINCIDENCIA


# ----------------------------------- R3_4 extremo a extremo: sin escritura parcial

def _destino_previo(catalogos, direccion, comuna=""):
    return CatalogoDestinos(catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json").crear(
        cliente_id="", nombre_destino=direccion, direccion=direccion, comuna=comuna, pais="CHILE",
        fuente="PRUEBA", estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )


def _regenerar(actual, catalogos, decision):
    generar_artefacto(ruta_dataset=actual / "analisis_completo_guias.csv", carpeta_catalogos=catalogos,
                      decisiones=[decision], ruta_salida=actual / "decisiones_pendientes.json")


def test_r34_reutiliza_el_destino_equivalente_sin_crear_otro(tmp_path):
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path)  # "AV. VICUNA MACKENNA 3451 SAN JOAQUIN"
    previo = _destino_previo(catalogos, "AV. VICUNA MACKENNA 3451, SAN JOAQUIN, CHILE", "SAN JOAQUIN")
    _regenerar(actual, catalogos, decision)
    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR")
    assert resultado["destino_id"] == previo.destino_id
    destinos = CatalogoDestinos(catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json").listar()
    assert len(destinos) == 1 and destinos[0].direccion == previo.direccion
    relaciones = CatalogoObrasDestinos(ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
                                       ruta_destinos=catalogos / "destinos_maestros.json").listar_relaciones()
    assert [(r.destino_id, r.estado) for r in relaciones] == [(previo.destino_id, "CONFIRMADA")]


def test_r34_ambiguo_rechaza_antes_de_escribir_y_conserva_la_tarjeta(tmp_path):
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path)
    _destino_previo(catalogos, "AV. VICUNA MACKENNA 3451, SAN JOAQUIN, CHILE", "SAN JOAQUIN")
    _destino_previo(catalogos, "AV. VICUNA MACKENNA 3451", "SAN JOAQUIN")
    _regenerar(actual, catalogos, decision)
    dataset = actual / "analisis_completo_guias.csv"
    antes = {p.name: p.read_bytes() for p in (dataset, catalogos / "destinos_maestros.json", catalogos / "obras_destinos.json")}
    with pytest.raises(ErrorAplicacionDecision, match="más de un destino"):
        # Con corrección de texto: la fila NO debe quedar corregida a medias.
        aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR",
                              direccion_manual="AV. VICUNA MACKENNA 3451", comuna_manual="San Joaquín")
    despues = {p.name: p.read_bytes() for p in (dataset, catalogos / "destinos_maestros.json", catalogos / "obras_destinos.json")}
    assert despues == antes
    assert [d["decision_id"] for d in _pendientes(actual)] == [decision["decision_id"]]
    ledger = actual / "decisiones_aplicadas.json"
    assert not ledger.exists() or decision["decision_id"] not in ledger.read_text(encoding="utf-8")


def test_r34_relacion_de_la_obra_resuelve_la_ambiguedad(tmp_path):
    raiz, catalogos, actual, cliente, obra, decision = _entorno(tmp_path)
    _destino_previo(catalogos, "AV. VICUNA MACKENNA 3451, SAN JOAQUIN, CHILE", "SAN JOAQUIN")
    de_la_obra = _destino_previo(catalogos, "AV. VICUNA MACKENNA 3451", "SAN JOAQUIN")
    obras = CatalogoObrasDestinos(ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
                                  ruta_destinos=catalogos / "destinos_maestros.json")
    evidencia = Evidencia(tipo=TipoEvidencia.GUIA.value, identificador_fuente="previa", referencia_hash="c" * 64,
                          campos_observados={"obra": obra.nombre_canonico}, fecha="2026-01-01T00:00:00+00:00",
                          actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value)
    relacion = obras.registrar_observacion(cliente_id=cliente.cliente_id, nombre_obra=obra.nombre_canonico,
                                           destino_id=de_la_obra.destino_id, evidencia=evidencia).relacion
    obras.confirmar_relacion(relacion.relacion_id, actor="test")
    _regenerar(actual, catalogos, decision)
    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR")
    assert resultado["destino_id"] == de_la_obra.destino_id
    assert len(CatalogoDestinos(catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json").listar()) == 2
