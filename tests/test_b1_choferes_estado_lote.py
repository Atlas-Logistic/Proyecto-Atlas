"""B1 -- cambio de estado de VARIOS choferes con un único preview y una
única confirmación ("pon inactivos a estos choferes: A, B y C", "pon los
choferes sin viajes como inactivos"). Fixtures sintéticas: nunca G:."""
from __future__ import annotations

import csv
import hashlib
import json

import pytest

from atlas_core import catalogos
from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.b1_operador import OperadorB1, interpretar_determinista
from atlas_core.procesamiento_masivo import COLUMNAS

CHOFERES = {
    # clave: (nombre, rut, activo, con viajes)
    "123456785": ("ANA ROJAS", "12345678-5", True, True),
    "154328769": ("BRUNO DIAZ", "15432876-9", True, False),
    "167890121": ("CARLA SOTO", "16789012-1", True, False),
    "173456786": ("DIEGO PAZ", "17345678-6", False, False),
    "144444442": ("ERWIN FIEBIG", "14444444-2", True, False),
    "PENDIENTE00000001": ("CARLOS FIEBIG", "", True, False),
    "PENDIENTE00000002": ("FELIPE LARA", "", False, True),
}


@pytest.fixture
def raiz(tmp_path):
    raiz = tmp_path / "AtlasCopia"
    cat, actual = raiz / "catalogos_privados", raiz / "operacion" / "actual"
    cat.mkdir(parents=True)
    actual.mkdir(parents=True)
    (cat / "choferes.json").write_text(json.dumps({
        clave: {"nombre": nombre, **({"rut": rut} if rut else {}), "aliases": [], "activo": activo}
        for clave, (nombre, rut, activo, _) in CHOFERES.items()
    }), encoding="utf-8")
    (cat / "vehiculos.json").write_text(json.dumps({"version": 1, "vehiculos": []}), encoding="utf-8")
    with (actual / "analisis_completo_guias.csv").open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        guia = 700000
        for nombre, rut, _, con_viajes in CHOFERES.values():
            if con_viajes:
                guia += 1
                fila = {c: "" for c in COLUMNAS}
                fila.update(archivo=f"{guia}.jpeg", numero_guia=str(guia), fecha="01-10-2026", chofer=nombre,
                            rut_chofer=rut, estado_procesamiento="OK")
                escritor.writerow(fila)
    return raiz


def _catalogo(raiz):
    return json.loads((raiz / "catalogos_privados" / "choferes.json").read_text(encoding="utf-8"))


def _activos(raiz):
    return {r["nombre"]: r["activo"] for r in _catalogo(raiz).values()}


def _huella(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _dataset(raiz):
    return raiz / "operacion" / "actual" / "analisis_completo_guias.csv"


def _filas(r, tipo="choferes_cambio_estado"):
    return next((t["filas"] for t in r.get("tablas") or [] if t["tipo"] == tipo), [])


def _aplicadas(raiz):
    return [a for a in CapaAccionesOperacionales(raiz).auditoria() if a["resultado"] == "APLICADA"]


# 1 / 4 / 10
def test_lista_explicita_de_tres_un_solo_preview(raiz):
    b1 = OperadorB1(raiz)
    r = b1.atender("c", "Pon inactivos a estos choferes: Bruno Diaz, Carla Soto y Erwin Fiebig.")
    assert r["estado"] == "PREVIEW_PENDIENTE" and r["accion"] == "CHOFER_CAMBIAR_ESTADO_LOTE"
    assert _filas(r) == [["BRUNO DIAZ", "ACTIVO", "INACTIVO"], ["CARLA SOTO", "ACTIVO", "INACTIVO"],
                         ["ERWIN FIEBIG", "ACTIVO", "INACTIVO"]]
    assert r["mensaje"].startswith("Se cambiarán 3 choferes de ACTIVO a INACTIVO.")
    assert "No se borrarán los choferes ni se modificarán sus viajes históricos, RUT, alias ni vehículos." in r["mensaje"]
    assert _activos(raiz)["BRUNO DIAZ"] is True                   # el preview no escribe
    e = b1.atender("c", "sí")                                      # UNA confirmación para todo
    assert e["estado"] == "EJECUTADA" and e["mensaje"].startswith("Listo: 3 choferes quedaron INACTIVOS.")
    assert _filas(e, "choferes_estado_aplicado") == [["BRUNO DIAZ", "ACTIVO", "INACTIVO"],
                                                    ["CARLA SOTO", "ACTIVO", "INACTIVO"],
                                                    ["ERWIN FIEBIG", "ACTIVO", "INACTIVO"]]
    assert len(_aplicadas(raiz)) == 1 and b1.pendiente("c") is None
    assert b1.atender("c", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"


def test_formas_de_lista_se_interpretan_como_lote():
    for texto, activo in (("Pon como inactivos a Bruno Diaz, Carla Soto y Erwin Fiebig", False),
                          ("Activa a Bruno Diaz, Carla Soto y Erwin Fiebig", True),
                          ("Pon a Bruno Diaz y Carla Soto como inactivos", False)):
        i = interpretar_determinista(texto)
        assert i.accion == "CHOFER_CAMBIAR_ESTADO_LOTE" and i.parametros == {"activo": activo}, texto
        assert i.lote["nombres"][:2] == ["BRUNO DIAZ", "CARLA SOTO"]
    for texto in ("Pon los choferes sin viajes como inactivos", "Pon los 4 choferes sin viajes como inactivos"):
        assert interpretar_determinista(texto).lote["grupo"] == "SIN_VIAJES"
    # un solo chofer sigue por el camino individual de siempre
    assert interpretar_determinista("Pon inactivo a Bruno Diaz").accion == "CHOFER_CAMBIAR_ESTADO"
    assert interpretar_determinista("Inactiva a Bruno Diaz").accion == "CHOFER_CAMBIAR_ESTADO"


# 2 / 5 / 11 / 12
def test_choferes_sin_viajes_conjunto_correcto_y_aplicacion_exacta(raiz):
    catalogo, dataset = _catalogo(raiz), _huella(_dataset(raiz))
    b1 = OperadorB1(raiz)
    r = b1.atender("c", "Pon los 4 choferes sin viajes como inactivos")
    assert r["estado"] == "PREVIEW_PENDIENTE"
    assert sorted(f[0] for f in _filas(r)) == ["BRUNO DIAZ", "CARLA SOTO", "CARLOS FIEBIG", "ERWIN FIEBIG"]
    assert _filas(r, "choferes_ya_en_estado") == [["DIEGO PAZ"]]      # ya inactivo: aparte, no es cambio
    assert "ANA ROJAS" not in json.dumps(r, ensure_ascii=False)      # con viajes
    assert "FELIPE LARA" not in json.dumps(r, ensure_ascii=False)    # con viajes (aunque inactivo)
    assert r["preview"]["choferes_a_cambiar"] == 4 and r["preview"]["choferes_sin_cambio"] == 1
    assert b1.atender("c", "sí")["estado"] == "EJECUTADA"
    despues = _catalogo(raiz)
    cambiados = sorted(despues[k]["nombre"] for k in catalogo if catalogo[k] != despues[k])
    assert cambiados == ["BRUNO DIAZ", "CARLA SOTO", "CARLOS FIEBIG", "ERWIN FIEBIG"]
    assert all(despues[k] == {**catalogo[k], "activo": despues[k]["activo"]} for k in catalogo)  # sólo `activo`
    assert set(despues) == set(catalogo)                              # nadie borrado
    assert _huella(_dataset(raiz)) == dataset                         # viajes históricos intactos


# 3
def test_activar_multiples(raiz):
    b1 = OperadorB1(raiz)
    r = b1.atender("c", "Activa a Diego Paz y Felipe Lara")
    assert _filas(r) == [["DIEGO PAZ", "INACTIVO", "ACTIVO"], ["FELIPE LARA", "INACTIVO", "ACTIVO"]]
    assert r["mensaje"].startswith("Se cambiarán 2 choferes de INACTIVO a ACTIVO.")
    assert b1.atender("c", "sí")["estado"] == "EJECUTADA"
    assert _activos(raiz)["DIEGO PAZ"] is True and _activos(raiz)["FELIPE LARA"] is True


# 5 / 8
def test_ya_en_estado_y_repetidos(raiz):
    r = OperadorB1(raiz).atender("c", "Pon inactivos a Bruno Diaz, Diego Paz, Bruno Diaz y bruno diaz")
    assert _filas(r) == [["BRUNO DIAZ", "ACTIVO", "INACTIVO"]]        # un solo cambio por chofer
    assert _filas(r, "choferes_ya_en_estado") == [["DIEGO PAZ"]]
    assert r["mensaje"].startswith("Se cambiará 1 chofer de ACTIVO a INACTIVO. 1 ya estaba INACTIVO y no cambia.")


# 6 / 7
@pytest.mark.parametrize("texto, fragmento", [
    ("Pon inactivos a Bruno Diaz, Carla Soto y Zacarias Inexistente", "«ZACARIAS INEXISTENTE»: no encontré"),
    ("Pon inactivos a Bruno Diaz, Carla Soto y Fiebig", "«FIEBIG» coincide con más de un chofer"),
])
def test_nombre_inexistente_o_ambiguo_no_prepara_nada(raiz, texto, fragmento):
    catalogo = _huella(raiz / "catalogos_privados" / "choferes.json")
    b1 = OperadorB1(raiz)
    r = b1.atender("c", texto)
    assert r["estado"] == "ACLARACION_REQUERIDA" and fragmento in r["mensaje"]
    assert "No preparé ningún cambio" in r["mensaje"]
    assert b1.pendiente("c") is None and b1.atender("c", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert _huella(raiz / "catalogos_privados" / "choferes.json") == catalogo
    assert CapaAccionesOperacionales(raiz).auditoria() == []
    assert "PENDIENTE0000" not in json.dumps(r)


def test_cantidad_declarada_distinta_pide_aclaracion(raiz):
    b1 = OperadorB1(raiz)
    r = b1.atender("c", "Pon los 11 choferes sin viajes como inactivos")
    assert r["estado"] == "ACLARACION_REQUERIDA" and "Dijiste 11 choferes, pero encontré 5" in r["mensaje"]
    assert b1.pendiente("c") is None


def test_criterio_no_soportado_no_se_infiere(raiz):
    r = OperadorB1(raiz).atender("c", "Pon inactivos a los choferes con más de 45 días sin cargar")
    assert r["estado"] == "ACLARACION_REQUERIDA" and "No infiero otros criterios" in r["mensaje"]


# 9
def test_ningun_id_interno_visible(raiz):
    b1 = OperadorB1(raiz)
    salidas = [b1.atender("c", "Pon los choferes sin viajes como inactivos"), b1.atender("c", "sí")]
    texto = json.dumps(salidas, ensure_ascii=False)
    for interno in ("PENDIENTE0000", "154328769", "144444442", "token", "chofer_id", "auditoria_id", "clave"):
        assert interno not in texto, interno


# 13
def test_repetir_la_operacion_no_genera_cambios(raiz):
    b1 = OperadorB1(raiz)
    b1.atender("c", "Pon inactivos a Bruno Diaz y Carla Soto")
    b1.atender("c", "sí")
    antes = _huella(raiz / "catalogos_privados" / "choferes.json")
    r = b1.atender("c", "Pon inactivos a Bruno Diaz y Carla Soto")
    assert r["estado"] == "SIN_CAMBIOS" and r["mensaje"].startswith("Los 2 choferes ya estaban INACTIVOS")
    assert b1.pendiente("c") is None
    assert _huella(raiz / "catalogos_privados" / "choferes.json") == antes and len(_aplicadas(raiz)) == 1


def test_fallo_a_mitad_del_lote_restaura_todo(raiz, monkeypatch):
    original, llamadas = catalogos.cambiar_estado_chofer, []

    def falla_en_la_segunda(ruta, clave, activo):
        llamadas.append(clave)
        if len(llamadas) == 2:
            raise OSError("disco lleno")
        return original(ruta, clave, activo)

    monkeypatch.setattr(catalogos, "cambiar_estado_chofer", falla_en_la_segunda)
    antes = _huella(raiz / "catalogos_privados" / "choferes.json")
    b1 = OperadorB1(raiz)
    b1.atender("c", "Pon inactivos a Bruno Diaz, Carla Soto y Erwin Fiebig")
    r = b1.atender("c", "sí")
    assert len(llamadas) == 2                                         # el primero sí llegó a escribirse
    assert r["estado"] == "FALLIDA" and "ningún chofer cambió de estado" in r["mensaje"]
    assert _huella(raiz / "catalogos_privados" / "choferes.json") == antes
    assert [a["resultado"] for a in CapaAccionesOperacionales(raiz).auditoria()] == ["FALLIDA"]


def test_bandeja_se_reconcilia_una_sola_vez(raiz, monkeypatch):
    llamadas = []
    monkeypatch.setattr(CapaAccionesOperacionales, "_reconciliar", lambda self: llamadas.append(1) or {"ejecutado": True})
    b1 = OperadorB1(raiz)
    b1.atender("c", "Pon los choferes sin viajes como inactivos")
    assert b1.atender("c", "sí")["estado"] == "EJECUTADA" and llamadas == [1]


# 14 / 15
def test_lecturas_no_cambian(raiz):
    r = OperadorB1(raiz).atender("c", "¿Cuántos choferes no tienen viajes?")
    assert r["estado"] == "RESULTADO_LECTURA" and r["accion"] == "CHOFER_CONSULTAR"
    assert interpretar_determinista("¿Cuántos choferes trabajaron?") is None
    assert OperadorB1(raiz).atender("c", "¿Cuántos choferes trabajaron?")["estado"] == "NO_INTERPRETADA"
