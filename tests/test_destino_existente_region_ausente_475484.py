"""Caso real 475484 (transporte 0000362633, obra SODIMAC SA RENCA BOD 209):
confirmar "CAMINO LO RUIZ 3099" / RENCA creaba un destino global SIN región
junto al ya existente (RENCA / Metropolitana); al geocodificarlo, completar
la región lo volvía duplicado y `DestinoDuplicadoError` tumbaba la decisión
con un traceback en Revisión de Atlas."""
import csv
import io
import json
import sys
from types import SimpleNamespace

import pytest

import atlas_core.aplicacion_multiple as modulo_multiple
from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.aplicacion_multiple import aplicar_decisiones_multiples
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_destinos import (
    CatalogoDestinos, DestinoDuplicadoError, ErrorCatalogoDestinos, EstadoCalidadDestino,
)
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, ResultadoEvidencia, TipoEvidencia
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_destinos_confirmados_sin_coordenadas_sin_ocr

OBRA = "SODIMAC SA RENCA BOD 209"
LEIDO = "CAMINO LO RUIZ 3099 SANTIAGO RENCA"


def _catalogos_vacios(tmp_path):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"; actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True); catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []}, "empresas.json": {}, "vehiculos.json": {},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    return raiz, catalogos, actual


def _destinos(catalogos):
    return CatalogoDestinos(catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json")


def _global(catalogos, direccion="CAMINO LO RUIZ 3099", comuna="RENCA", region="Metropolitana", **extra):
    return _destinos(catalogos).crear(
        cliente_id="", nombre_destino=direccion, direccion=direccion, comuna=comuna, region=region,
        pais="CHILE", fuente="TEST", estado_calidad=EstadoCalidadDestino.CONFIRMADO, **extra,
    )


def _entorno_475484(tmp_path):
    raiz, catalogos, actual = _catalogos_vacios(tmp_path)
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="SODIMAC SA", rut="96.792.430-K", fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    existente = _global(catalogos, latitud=-33.402531, longitud=-70.686461)
    obras = CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    )
    obra = obras.registrar_observacion(cliente_id=cliente.cliente_id, nombre_obra=OBRA, evidencia=Evidencia(
        tipo=TipoEvidencia.GUIA.value, identificador_fuente="475484", referencia_hash="a" * 64,
        campos_observados={"obra": OBRA}, fecha="2026-10-07T00:00:00+00:00",
        actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value,
    )).obra
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "original.jpg", "estado_procesamiento": "OK", "numero_guia": "475484",
        "numero_transporte": "0000362633", "fecha": "07-10-2026", "cliente": "SODIMAC SA",
        "obra_destino": OBRA, "despachar_a_crudo": LEIDO, "indicador_revision": "REVISAR",
        "motivos_revision_documento": "OBRA_DESTINO_SIN_CORROBORAR", "estado_entrega": "REVISAR",
    })
    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";"); escritor.writeheader(); escritor.writerow(fila)
    decision = crear_decision(
        tipo="DESTINO_SIN_CONFIRMAR", entidad="RELACION_OBRA_DESTINO", archivo="original.jpg",
        numero_guia="475484", numero_transporte="0000362633", campo="destino_entrega",
        valor_documental=LEIDO, valor_normalizado=LEIDO,
        identidad_resuelta={"entidad_id": obra.obra_id, "valor_canonico": OBRA},
        candidatos=(), motivos=("OBRA_SIN_RELACION_CONFIRMADA_UNICA",),
        evidencias=({"tipo": "OBRA_IDENTIFICADA", "entidad_id": obra.obra_id},),
        acciones_permitidas=("CONFIRMAR", "NO_CONFIRMAR", "POSPONER"),
        contexto={
            "cliente_id": cliente.cliente_id, "cliente_canonico": "SODIMAC SA",
            "obra_id": obra.obra_id, "obra_canonica": OBRA, "destino_documental": LEIDO,
        },
    )
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision],
                      ruta_salida=actual / "decisiones_pendientes.json")
    return raiz, catalogos, obras, obra, existente, decision


# --- A. Caso real equivalente ---

def test_a_confirmar_bod_209_reutiliza_el_destino_global_existente(tmp_path):
    raiz, catalogos, obras, obra, existente, decision = _entorno_475484(tmp_path)
    resultado = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR",
        direccion_manual="CAMINO LO RUIZ 3099", comuna_manual="RENCA",
    )
    assert resultado["ok"]
    destinos = _destinos(catalogos).listar()
    assert [d.destino_id for d in destinos] == [existente.destino_id]  # ningún segundo destino
    relaciones = [r for r in obras.listar_relaciones() if r.obra_id == obra.obra_id]
    assert [(r.destino_id, r.estado) for r in relaciones] == [(existente.destino_id, "CONFIRMADA")]


# --- B. Región ausente en crear_o_reutilizar_global ---

def test_b_region_ausente_con_un_compatible_lo_reutiliza(tmp_path):
    _, catalogos, _ = _catalogos_vacios(tmp_path)
    existente = _global(catalogos)
    reutilizado = _destinos(catalogos).crear_o_reutilizar_global(
        nombre_destino="CAMINO LO RUIZ 3099", direccion="CAMINO LO RUIZ 3099", comuna="RENCA", region="",
        fuente="TEST", estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    assert reutilizado.destino_id == existente.destino_id
    assert len(_destinos(catalogos).listar()) == 1


def test_b_region_ausente_con_varios_compatibles_es_ambigua_y_no_crea(tmp_path):
    _, catalogos, _ = _catalogos_vacios(tmp_path)
    _global(catalogos, region="Metropolitana")
    _global(catalogos, region="RM")
    with pytest.raises(ErrorCatalogoDestinos, match="ambigua"):
        _destinos(catalogos).crear_o_reutilizar_global(
            nombre_destino="CAMINO LO RUIZ 3099", direccion="CAMINO LO RUIZ 3099", comuna="RENCA",
            region="", fuente="TEST",
        )
    assert len(_destinos(catalogos).listar()) == 2


def test_b_region_ausente_sin_compatibles_crea_como_siempre(tmp_path):
    _, catalogos, _ = _catalogos_vacios(tmp_path)
    _global(catalogos, comuna="QUILICURA")  # misma calle, otra comuna: nunca compatible
    nuevo = _destinos(catalogos).crear_o_reutilizar_global(
        nombre_destino="CAMINO LO RUIZ 3099", direccion="CAMINO LO RUIZ 3099", comuna="RENCA",
        region="", fuente="TEST",
    )
    assert (nuevo.comuna, nuevo.region) == ("RENCA", "")
    assert len(_destinos(catalogos).listar()) == 2


# --- C. Revalidador: un duplicado latente no aborta el resto ---

def test_c_duplicado_latente_se_salta_y_los_demas_se_completan(tmp_path, monkeypatch):
    _, catalogos, _ = _catalogos_vacios(tmp_path)
    _global(catalogos, latitud=-33.402531, longitud=-70.686461)
    latente = _global(catalogos, region="")               # sin coords; al completar región = duplicado
    sano = _global(catalogos, direccion="GALVARINO 8501", comuna="QUILICURA", region="")

    def resolver_falso(texto, proveedor, contexto_territorial=None):
        return SimpleNamespace(
            estado="RESUELTO", coordenadas=SimpleNamespace(latitud=-33.36, longitud=-70.72),
            localidad="", region="Metropolitana",
        )

    monkeypatch.setattr("atlas_core.rutas.destino_entrega.resolver_destino_entrega_validado", resolver_falso)
    monkeypatch.setattr("atlas_core.rutas.destino_entrega.ESTADO_RESUELTO", "RESUELTO")
    resultado = revalidar_destinos_confirmados_sin_coordenadas_sin_ocr(
        carpeta_catalogos=catalogos, proveedor_rutas=object(),
    )
    assert resultado["destinos_duplicados"] == [latente.destino_id]
    assert resultado["destinos_actualizados"] == [sano.destino_id]
    por_id = {d.destino_id: d for d in _destinos(catalogos).listar()}
    assert por_id[latente.destino_id].latitud is None and por_id[latente.destino_id].region == ""
    assert por_id[sano.destino_id].latitud == -33.36


# --- D. CLI individual ---

def test_d_cli_individual_error_de_catalogo_sin_traceback(tmp_path, monkeypatch, capsys):
    import aplicar_decision_pendiente as cli

    def duplicado(**_kwargs):
        raise DestinoDuplicadoError("La dirección ya pertenece a otro destino global activo")

    monkeypatch.setattr(cli, "aplicar_decision_obra", duplicado)
    monkeypatch.setattr(sys, "argv", [
        "aplicar_decision_pendiente.py", "--raiz-atlas", str(tmp_path),
        "--decision-id", "6047505f", "--accion", "CONFIRMAR",
    ])
    cli.main()
    resultado = json.loads(capsys.readouterr().out.strip())
    assert resultado["ok"] is False
    assert "Traceback" not in resultado["error"] and "DestinoDuplicadoError" not in resultado["error"]
    assert "otro destino ya registrado" in resultado["error"]


# --- E. Multiselección ---

def test_e_lote_error_de_catalogo_es_aviso_por_item_y_el_lote_sigue(tmp_path, monkeypatch):
    llamadas_cierre = []
    monkeypatch.setattr(
        "atlas_core.reconciliacion_estado_derivado.reconciliar_estado_derivado",
        lambda **kw: llamadas_cierre.append(1) or {"reconciliado": True, "motivo": "TEST"},
    )
    vigentes = [
        {"decision_id": "dup", "tipo": "DESTINO_SIN_CONFIRMAR", "estado": "PENDIENTE",
         "documento": {"archivo": "a.jpg", "numero_guia": "475484"}},
        {"decision_id": "ok", "tipo": "DESTINO_SIN_CONFIRMAR", "estado": "PENDIENTE",
         "documento": {"archivo": "b.jpg", "numero_guia": "475485"}},
    ]
    monkeypatch.setattr(modulo_multiple, "_leer_decisiones_vigentes", lambda _raiz: {d["decision_id"]: d for d in vigentes})

    def aplicar_falso(*, decision_id, **_kwargs):
        if decision_id == "dup":
            raise DestinoDuplicadoError("La dirección ya pertenece a otro destino global activo")
        return {"ok": True, "mensaje": "aplicada"}

    monkeypatch.setattr(modulo_multiple, "aplicar_decision_obra", aplicar_falso)
    resultado = aplicar_decisiones_multiples(raiz_atlas=tmp_path, solicitudes=[
        {"decision_id": "dup", "accion": "CONFIRMAR"}, {"decision_id": "ok", "accion": "CONFIRMAR"},
    ])
    por_id = {r.decision_id: r for r in resultado.resultados}
    assert por_id["dup"].aplicada is False
    assert "otro destino ya registrado" in por_id["dup"].motivo
    assert "inesperado" not in por_id["dup"].motivo.lower()
    assert por_id["ok"].aplicada is True  # el lote no se detuvo
    assert len(llamadas_cierre) == 1


def test_e_cli_lote_emite_json_sin_traceback(tmp_path, monkeypatch, capsys):
    import aplicar_decisiones_multiples as cli

    monkeypatch.setattr(modulo_multiple, "_leer_decisiones_vigentes", lambda _raiz: {
        "dup": {"decision_id": "dup", "tipo": "DESTINO_SIN_CONFIRMAR", "estado": "PENDIENTE",
                "documento": {"archivo": "a.jpg", "numero_guia": "475484"}},
    })
    monkeypatch.setattr(modulo_multiple, "aplicar_decision_obra", lambda **_kw: (_ for _ in ()).throw(
        DestinoDuplicadoError("La dirección ya pertenece a otro destino global activo")))
    monkeypatch.setattr(sys, "argv", ["aplicar_decisiones_multiples.py", "--raiz-atlas", str(tmp_path)])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps([{"decision_id": "dup", "accion": "CONFIRMAR"}])))
    cli.main()
    resultado = json.loads(capsys.readouterr().out.strip())
    assert resultado["total_aplicadas"] == 0
    assert "Traceback" not in json.dumps(resultado)
    assert "otro destino ya registrado" in resultado["resultados"][0]["motivo"]
