"""Consolidación explícita de destinos duplicados (caso real VISTA CLARA 2351).

34b754bc (Cerrillos, confirmado en agosto) y 9a8f052e (comuna Santiago,
creado por la decisión R6 de 483267 con dirección "VISTA CLARA 2351,
CERRILLOS") son el mismo punto físico (a ~18 m). La consolidación retira el
duplicado sin borrar historial y deja una identidad canónica única; destinos
legítimamente distintos nunca se consolidan. Copias sintéticas."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.catalogo_destinos import (
    CatalogoDestinos, ErrorCatalogoDestinos, EstadoCalidadDestino, MARCA_CONSOLIDACION_DESTINO,
    destino_consolidado_en, motivo_destinos_no_consolidables,
)
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos
from atlas_core.convergencia_destino_confirmado import resolver_destino_confirmado
from atlas_core.procesamiento_masivo import COLUMNAS

from tests.test_acciones_operacionales import _EscritorDisponible, _registrar_obra, _sha, entorno  # noqa: F401

CANONICO = dict(nombre_destino="VISTA CLARA 2351", direccion="VISTA CLARA 2351, CERRILLOS, REGIÓN METROPOLITANA, CHILE",
                comuna="CERRILLOS", region="REGIÓN METROPOLITANA", latitud=-33.524258, longitud=-70.7149958,
                fuente="DECISION_OPERACIONAL_ATLAS_2026-08-04+GOOGLE_MAPS_PLACE")
DUPLICADO = dict(nombre_destino="VISTA CLARA 2351, CERRILLOS", direccion="VISTA CLARA 2351, CERRILLOS",
                 comuna="Santiago", region="Metropolitana", latitud=-33.524092, longitud=-70.715003,
                 fuente="DECISION_HUMANA_R6:2f65604b")


def _catalogo(tmp_path):
    (tmp_path / "clientes.json").write_text(json.dumps({"version_formato": 1, "clientes": []}), encoding="utf-8")
    return CatalogoDestinos(tmp_path / "destinos_maestros.json", ruta_clientes=tmp_path / "clientes.json")


def _crear(catalogo, **campos):
    return catalogo.crear(cliente_id="", pais="CHILE", estado_calidad=EstadoCalidadDestino.CONFIRMADO, **campos)


# ------------------------------------------------------------ servicio de catálogo


def test_consolida_el_mismo_punto_fisico_preservando_historial(tmp_path):
    catalogo = _catalogo(tmp_path)
    canonico, duplicado = _crear(catalogo, **CANONICO), _crear(catalogo, **DUPLICADO)
    assert motivo_destinos_no_consolidables(canonico, duplicado) == ""

    resultado = catalogo.consolidar_destino_duplicado(
        canonico.destino_id, duplicado.destino_id, actor="CLAUDE/JAVIER", referencia="P0 VISTA CLARA")
    assert resultado["idempotente"] is False
    vigentes = {d.destino_id: d for d in catalogo.listar()}
    assert len(vigentes) == 2  # nunca se borra
    assert vigentes[canonico.destino_id] == canonico  # canónico intacto
    retirado = vigentes[duplicado.destino_id]
    assert retirado.estado_vigencia == "INACTIVO" and retirado.estado_calidad == "CONFIRMADO"
    assert (retirado.fuente, retirado.fecha_creacion, retirado.comuna, retirado.latitud, retirado.direccion) == (
        duplicado.fuente, duplicado.fecha_creacion, duplicado.comuna, duplicado.latitud, duplicado.direccion)
    assert MARCA_CONSOLIDACION_DESTINO in retirado.observacion and "P0 VISTA CLARA" in retirado.observacion
    assert destino_consolidado_en(retirado) == canonico.destino_id
    assert destino_consolidado_en(canonico) == ""

    antes = (tmp_path / "destinos_maestros.json").read_bytes()
    again = catalogo.consolidar_destino_duplicado(
        canonico.destino_id, duplicado.destino_id, actor="CLAUDE/JAVIER", referencia="otra")
    assert again["idempotente"] is True
    assert (tmp_path / "destinos_maestros.json").read_bytes() == antes


@pytest.mark.parametrize("comuna", ["Santiago", "CERRILLOS", ""])
def test_direccion_del_duplicado_se_reutiliza_en_el_canonico(tmp_path, comuna):
    catalogo = _catalogo(tmp_path)
    canonico, duplicado = _crear(catalogo, **CANONICO), _crear(catalogo, **DUPLICADO)
    catalogo.consolidar_destino_duplicado(canonico.destino_id, duplicado.destino_id, actor="T", referencia="R")
    reutilizado = catalogo.crear_o_reutilizar_global(
        nombre_destino="VISTA CLARA 2351, CERRILLOS", direccion="VISTA CLARA 2351, CERRILLOS",
        comuna=comuna, fuente="DECISION_HUMANA_R6:nueva", estado_calidad=EstadoCalidadDestino.CONFIRMADO)
    assert reutilizado == canonico
    assert len(catalogo.listar()) == 2


def test_reutilizacion_por_sucesor_no_cruza_comunas_distintas(tmp_path):
    catalogo = _catalogo(tmp_path)
    canonico, duplicado = _crear(catalogo, **CANONICO), _crear(catalogo, **DUPLICADO)
    catalogo.consolidar_destino_duplicado(canonico.destino_id, duplicado.destino_id, actor="T", referencia="R")
    # La dirección nombra Cerrillos y el campo dice Maipú: evidencia
    # contradictoria. Nunca se redirige a la identidad de Cerrillos; desde el
    # bloque P0 DESTINO EQUIVALENTE tampoco se crea un tercer destino: abstención.
    with pytest.raises(ErrorCatalogoDestinos, match="ambigua"):
        catalogo.crear_o_reutilizar_global(
            nombre_destino="VISTA CLARA 2351, CERRILLOS", direccion="VISTA CLARA 2351, CERRILLOS", comuna="MAIPU",
            fuente="T", estado_calidad=EstadoCalidadDestino.CONFIRMADO)
    assert {d.destino_id for d in catalogo.listar()} == {canonico.destino_id, duplicado.destino_id}
    # Con una comuna real distinta y sin contradicción, es otro lugar: se crea.
    otro = catalogo.crear_o_reutilizar_global(
        nombre_destino="VISTA CLARA 2351", direccion="VISTA CLARA 2351", comuna="MAIPU",
        fuente="T", estado_calidad=EstadoCalidadDestino.CONFIRMADO)
    assert otro.destino_id not in {canonico.destino_id, duplicado.destino_id}


def test_sin_consolidacion_un_destino_inactivo_no_redirige(tmp_path):
    catalogo = _catalogo(tmp_path)
    _crear(catalogo, **CANONICO)
    inactivo = catalogo.desactivar(_crear(catalogo, **DUPLICADO).destino_id, modificacion_manual=True)
    assert destino_consolidado_en(inactivo) == ""
    nuevo = catalogo.crear_o_reutilizar_global(
        nombre_destino="X", direccion="VISTA CLARA 2351, CERRILLOS", comuna="Santiago", fuente="T")
    # El inactivo no redirige; desde el bloque P0 DESTINO EQUIVALENTE la misma
    # dirección se reutiliza en el único destino ACTIVO equivalente (Cerrillos)
    # en vez de crear un tercero.
    assert nuevo.destino_id != inactivo.destino_id and len(catalogo.listar()) == 2
    assert nuevo.comuna == "CERRILLOS"


@pytest.mark.parametrize("cambios, motivo", [
    # Misma calle, otro número: lugares distintos.
    (dict(direccion="VISTA CLARA 2353, CERRILLOS", nombre_destino="VC 2353"), "DIRECCION_DISTINTA"),
    # Mismo texto, otra comuna real (sin comuna explícita que la contradiga).
    (dict(direccion="VISTA CLARA 2351", comuna="MAIPU", nombre_destino="VC MAIPU"), "COMUNA_DISTINTA"),
    # La propia dirección nombra otra comuna.
    (dict(direccion="VISTA CLARA 2351, MAIPU", comuna="Santiago", nombre_destino="VC M"), "COMUNA_DISTINTA"),
    # Mismo texto, pero a más de 150 m (caso SANTA ISABEL 585 a 535 m).
    (dict(latitud=-33.5290, longitud=-70.7150, nombre_destino="VC LEJOS"), "COORDENADAS_DISTANTES"),
    (dict(latitud=None, longitud=None, nombre_destino="VC SIN"), "SIN_COORDENADAS"),
])
def test_destinos_legitimamente_distintos_no_se_consolidan(tmp_path, cambios, motivo):
    catalogo = _catalogo(tmp_path)
    canonico = _crear(catalogo, **CANONICO)
    otro = _crear(catalogo, **{**DUPLICADO, **cambios})
    assert motivo_destinos_no_consolidables(canonico, otro) == motivo
    antes = (tmp_path / "destinos_maestros.json").read_bytes()
    with pytest.raises(ErrorCatalogoDestinos, match=motivo):
        catalogo.consolidar_destino_duplicado(canonico.destino_id, otro.destino_id, actor="T", referencia="R")
    assert (tmp_path / "destinos_maestros.json").read_bytes() == antes


def test_canonico_debe_estar_confirmado_y_no_se_consolida_consigo_mismo(tmp_path):
    catalogo = _catalogo(tmp_path)
    pendiente = catalogo.crear(cliente_id="", pais="CHILE", **CANONICO)
    duplicado = _crear(catalogo, **DUPLICADO)
    assert motivo_destinos_no_consolidables(pendiente, duplicado) == "CANONICO_NO_CONFIRMADO_ACTIVO"
    assert motivo_destinos_no_consolidables(duplicado, duplicado) == "MISMO_DESTINO"
    # Un duplicado ya inactivo por otra razón no se reasigna.
    retirado = catalogo.desactivar(duplicado.destino_id, modificacion_manual=True)
    canonico = _crear(catalogo, **{**CANONICO, "nombre_destino": "VC2", "direccion": "VISTA CLARA 2351 CERRILLOS"})
    assert motivo_destinos_no_consolidables(canonico, retirado) == "DUPLICADO_NO_ACTIVO"


# ------------------------------------------------------------ acción oficial y convergencia


def _preparar_caso_real(entorno):
    escritor = _EscritorDisponible()
    capa = CapaAccionesOperacionales(entorno["raiz"], fabrica_escritor=lambda: escritor)
    catalogo = CatalogoDestinos(entorno["cat"] / "destinos_maestros.json", ruta_clientes=entorno["cat"] / "clientes.json")
    canonico, duplicado = _crear(catalogo, **CANONICO), _crear(catalogo, **DUPLICADO)
    obra_id = _registrar_obra(capa, entorno["cliente"].cliente_id, "TORRES OCARANZA LTDA")
    for destino in (canonico, duplicado):
        vinculo = capa.previsualizar("OBRA_VINCULAR_DESTINO", {"obra_id": obra_id, "destino_id": destino.destino_id},
                                     actor="JAVIER")
        assert capa.ejecutar(vinculo["token"], actor="JAVIER", confirmado_por="JAVIER")["estado"] == "APLICADA"
    # Decisión histórica (R6) que cita el duplicado.
    ledger = entorno["actual"] / "decisiones_aplicadas.json"
    ledger.write_text(json.dumps({"schema_version": 1, "aplicaciones": [{
        "decision_id": "2f65604b", "tipo": "DESTINO_NO_RESUELTO", "accion": "REGISTRAR_DIRECCION", "actor": "B1",
        "documento": {"archivo": "500003.jpeg", "numero_guia": "500003", "numero_transporte": "0000900003"},
        "direccion_manual": "VISTA CLARA 2351, CERRILLOS", "destino_id": duplicado.destino_id}]}), encoding="utf-8")
    fila = {c: "" for c in COLUMNAS}
    fila.update({"archivo": "500004.jpeg", "numero_guia": "500004", "numero_transporte": "0000900004",
                 "cliente": "CLIENTE UNO SA", "rut_cliente": "76.111.111-6", "obra_destino": "TORRES OCARANZA LTDA",
                 "despachar_a_crudo": CANONICO["direccion"], "estado_ruta": "RUTA_CALCULADA"})
    return capa, escritor, canonico, duplicado, obra_id, fila


def test_accion_consolida_conserva_relaciones_decisiones_y_dataset(entorno):
    capa, escritor, canonico, duplicado, obra_id, fila = _preparar_caso_real(entorno)
    cat = entorno["cat"]
    # Antes: dos destinos confirmados compatibles -> la convergencia se abstiene (483552/483830/484123/484907).
    assert resolver_destino_confirmado(fila, carpeta_catalogos=cat) is None
    huellas = {n: _sha(r) for n, r in {"dataset": entorno["dataset"], "obras": cat / "obras_destinos.json",
                                        "ledger": entorno["actual"] / "decisiones_aplicadas.json"}.items()}
    parametros = {"destino_canonico_id": canonico.destino_id, "destino_duplicado_id": duplicado.destino_id,
                  "referencia": "P0 VISTA CLARA"}

    preview = capa.previsualizar("DESTINO_CONSOLIDAR_DUPLICADO", parametros, actor="CLAUDE")
    assert preview["estado"] == "PREVIEW", preview
    assert preview["valor_propuesto"]["inactivar_destino_id"] == duplicado.destino_id
    assert preview["valor_propuesto"]["decisiones_conservadas"] == ["2f65604b"]
    assert len(preview["valor_propuesto"]["relaciones_conservadas"]) == 2
    assert preview["afectados"]["guias"] == ["500003"]
    sin_confirmar = capa.ejecutar(preview["token"], actor="CLAUDE")
    assert sin_confirmar["codigo"] == "CONFIRMACION_REQUERIDA"

    resultado = capa.ejecutar(preview["token"], actor="CLAUDE", confirmado_por="JAVIER")
    assert resultado["estado"] == "APLICADA", resultado
    assert escritor.adquisiciones == 1
    assert (entorno["raiz"] / resultado["respaldo"] / "destinos_maestros.json").is_file()
    assert {n: _sha(r) for n, r in {"dataset": entorno["dataset"], "obras": cat / "obras_destinos.json",
                                     "ledger": entorno["actual"] / "decisiones_aplicadas.json"}.items()} == huellas
    catalogo_obras = CatalogoObrasDestinos(ruta=cat / "obras_destinos.json", ruta_clientes=cat / "clientes.json",
                                           ruta_destinos=cat / "destinos_maestros.json")
    relaciones = [r for r in catalogo_obras.listar_relaciones() if r.obra_id == obra_id]
    assert {r.destino_id: r.estado for r in relaciones} == {canonico.destino_id: "CONFIRMADA",
                                                           duplicado.destino_id: "CONFIRMADA"}
    assert [d.destino_id for d in catalogo_obras.listar_destinos_confirmados_para_obra(
        nombre_obra="TORRES OCARANZA LTDA")] == [canonico.destino_id]
    # Después: identidad canónica única para la convergencia.
    resuelto = resolver_destino_confirmado(fila, carpeta_catalogos=cat)
    assert resuelto is not None and resuelto[1].destino_id == canonico.destino_id
    assert capa.previsualizar("DESTINO_CONSOLIDAR_DUPLICADO", parametros, actor="CLAUDE")["estado"] == "SIN_CAMBIOS"


def test_accion_rechaza_destinos_distintos_sin_escribir(entorno):
    capa = CapaAccionesOperacionales(entorno["raiz"], fabrica_escritor=lambda: _EscritorDisponible())
    catalogo = CatalogoDestinos(entorno["cat"] / "destinos_maestros.json", ruta_clientes=entorno["cat"] / "clientes.json")
    canonico = _crear(catalogo, **CANONICO)
    otro = _crear(catalogo, **{**DUPLICADO, "direccion": "VISTA CLARA 2351", "comuna": "MAIPU"})
    antes = _sha(entorno["cat"] / "destinos_maestros.json")
    preview = capa.previsualizar("DESTINO_CONSOLIDAR_DUPLICADO", {
        "destino_canonico_id": canonico.destino_id, "destino_duplicado_id": otro.destino_id}, actor="CLAUDE")
    assert preview["estado"] == "RECHAZADA" and preview["codigo"] == "AMBIGUEDAD_REQUIERE_HUMANO"
    invertido = capa.previsualizar("DESTINO_CONSOLIDAR_DUPLICADO", {
        "destino_canonico_id": otro.destino_id, "destino_duplicado_id": canonico.destino_id}, actor="CLAUDE")
    assert invertido["estado"] == "RECHAZADA"
    assert _sha(entorno["cat"] / "destinos_maestros.json") == antes


# ------------------------------------------------------------ ciudad + comuna (caso CAMINO A MELIPILLA 10800)

MELIPILLA_CANONICO = dict(nombre_destino="CAMINO A MELIPILLA 10800 SANTIAGO MAIPU",
                          direccion="CAMINO A MELIPILLA 10800 SANTIAGO MAIPU", comuna="MAIPU", region="RM",
                          latitud=-33.522737, longitud=-70.742443, fuente="COORDENADA_CANONICA_CONFIRMADA")
MELIPILLA_DUPLICADO = dict(nombre_destino="CAMINO A MELIPILLA 10800, MAIPU", direccion="CAMINO A MELIPILLA 10800, MAIPU",
                           comuna="Maipú", region="Metropolitana", latitud=-33.523082, longitud=-70.740823,
                           fuente="DECISION_HUMANA_R6:da643aa3")


def test_santiago_como_ciudad_mas_comuna_no_es_contradiccion(tmp_path):
    catalogo = _catalogo(tmp_path)
    canonico = _crear(catalogo, **MELIPILLA_CANONICO)
    # A <=150 m (sintético): ciudad + comuna basta para el criterio de comuna.
    cercano = _crear(catalogo, **{**MELIPILLA_DUPLICADO, "latitud": -33.522800, "longitud": -70.742000})
    assert motivo_destinos_no_consolidables(canonico, cercano) == ""
    # Simétrico: el canónico sin ciudad y el duplicado con "SANTIAGO MAIPU".
    assert motivo_destinos_no_consolidables(cercano, canonico) == ""


def test_caso_real_melipilla_sigue_bloqueado_por_distancia(tmp_path):
    """El ajuste de comuna no relaja la distancia: 154,995 m > 150 m."""
    catalogo = _catalogo(tmp_path)
    canonico, duplicado = _crear(catalogo, **MELIPILLA_CANONICO), _crear(catalogo, **MELIPILLA_DUPLICADO)
    assert motivo_destinos_no_consolidables(canonico, duplicado) == "COORDENADAS_DISTANTES"
    with pytest.raises(ErrorCatalogoDestinos, match="COORDENADAS_DISTANTES"):
        catalogo.consolidar_destino_duplicado(canonico.destino_id, duplicado.destino_id, actor="T", referencia="R")


@pytest.mark.parametrize("canonico_dir, duplicado_dir, duplicado_comuna, motivo", [
    # Ciudad + comuna en ambos, mismo lugar.
    ("CAMINO A MELIPILLA 10800 SANTIAGO MAIPU", "CAMINO A MELIPILLA 10800 SANTIAGO MAIPU", "MAIPU", ""),
    # Campo comuna erróneo en el duplicado, corregido por su dirección (ciudad + comuna).
    ("CAMINO A MELIPILLA 10800 SANTIAGO MAIPU", "CAMINO A MELIPILLA 10800, SANTIAGO MAIPU", "Santiago", ""),
    # Dos comunas específicas en la dirección canónica: incierta.
    ("CAMINO A MELIPILLA 10800, CERRILLOS MAIPU", "CAMINO A MELIPILLA 10800, MAIPU", "Maipú", "COMUNA_CANONICA_INCIERTA"),
    # Santiago + comuna de OTRA región: contradicción real.
    ("CAMINO A MELIPILLA 10800, SANTIAGO TEMUCO", "CAMINO A MELIPILLA 10800, MAIPU", "Maipú", "COMUNA_CANONICA_INCIERTA"),
    # El duplicado nombra otra comuna aunque su campo diga Maipú.
    ("CAMINO A MELIPILLA 10800 SANTIAGO MAIPU", "CAMINO A MELIPILLA 10800, SANTIAGO CERRILLOS", "Maipú", "COMUNA_DISTINTA"),
    # El duplicado sólo dice "SANTIAGO" (posible comuna real) y su campo es Santiago.
    ("CAMINO A MELIPILLA 10800 SANTIAGO MAIPU", "CAMINO A MELIPILLA 10800 SANTIAGO", "Santiago", "COMUNA_DISTINTA"),
    # Sin comuna en la dirección y campo distinto.
    ("CAMINO A MELIPILLA 10800 SANTIAGO MAIPU", "CAMINO A MELIPILLA 10800", "Cerrillos", "COMUNA_DISTINTA"),
])
def test_ciudad_comuna_y_comunas_contradictorias(tmp_path, canonico_dir, duplicado_dir, duplicado_comuna, motivo):
    catalogo = _catalogo(tmp_path)
    canonico = _crear(catalogo, **{**MELIPILLA_CANONICO, "direccion": canonico_dir, "nombre_destino": "C"})
    otro = _crear(catalogo, **{**MELIPILLA_DUPLICADO, "direccion": duplicado_dir, "nombre_destino": "D",
                                "comuna": duplicado_comuna, "latitud": -33.522800, "longitud": -70.742000})
    assert motivo_destinos_no_consolidables(canonico, otro) == motivo


def test_ciudad_comuna_no_relaja_direccion_ni_coordenadas(tmp_path):
    catalogo = _catalogo(tmp_path)
    canonico = _crear(catalogo, **MELIPILLA_CANONICO)
    otro_numero = _crear(catalogo, **{**MELIPILLA_DUPLICADO, "direccion": "CAMINO A MELIPILLA 10900 SANTIAGO MAIPU",
                                      "nombre_destino": "N", "latitud": -33.522800, "longitud": -70.742000})
    sin_coord = _crear(catalogo, **{**MELIPILLA_DUPLICADO, "nombre_destino": "S", "direccion": "CAMINO A MELIPILLA 10800 MAIPU",
                                    "latitud": None, "longitud": None})
    assert motivo_destinos_no_consolidables(canonico, otro_numero) == "DIRECCION_DISTINTA"
    # La clave de dirección no cambia: "SANTIAGO MAIPU" sin coma con campo Santiago conserva MAIPU en la calle.
    clave_intacta = _crear(catalogo, **{**MELIPILLA_DUPLICADO, "direccion": "CAMINO A MELIPILLA 10800 SANTIAGO MAIPU",
                                        "nombre_destino": "K", "comuna": "Santiago", "latitud": -33.522800,
                                        "longitud": -70.742000})
    assert motivo_destinos_no_consolidables(canonico, clave_intacta) == "DIRECCION_DISTINTA"
    assert motivo_destinos_no_consolidables(canonico, sin_coord) == "SIN_COORDENADAS"
