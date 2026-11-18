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
    otro = catalogo.crear_o_reutilizar_global(
        nombre_destino="VISTA CLARA 2351, CERRILLOS", direccion="VISTA CLARA 2351, CERRILLOS", comuna="MAIPU",
        fuente="T", estado_calidad=EstadoCalidadDestino.CONFIRMADO)
    assert otro.destino_id not in {canonico.destino_id, duplicado.destino_id}


def test_sin_consolidacion_un_destino_inactivo_no_redirige(tmp_path):
    catalogo = _catalogo(tmp_path)
    _crear(catalogo, **CANONICO)
    inactivo = catalogo.desactivar(_crear(catalogo, **DUPLICADO).destino_id, modificacion_manual=True)
    assert destino_consolidado_en(inactivo) == ""
    nuevo = catalogo.crear_o_reutilizar_global(
        nombre_destino="X", direccion="VISTA CLARA 2351, CERRILLOS", comuna="Santiago", fuente="T")
    assert nuevo.destino_id != inactivo.destino_id and len(catalogo.listar()) == 3


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
