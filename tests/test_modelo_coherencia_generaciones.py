"""Escenarios del diseño de coherencia (docs/DISENO_COHERENCIA_GENERACIONES.md) sobre el modelo sintético.

Demuestran propiedades DEL MODELO, no de la implementación real (que no existe todavía).
Sin datos reales, sin disco, sin red.
"""
from __future__ import annotations

import json
import sys

import pytest

from atlas_core import descriptor_generacion as dg
from modelo_coherencia import modelo as m

EMP = "empresa-sintetica"
MBT = "empresa-prueba-javier"
TOKEN = "tok-decision-1"


class Mundo:
    def __init__(self, empresas=(EMP,)):
        self.nube = m.NubeModelo()
        self.drive = m.DriveModelo()
        self.casa = m.Equipo("CASA", self.drive)
        self.oficina = m.Equipo("OFICINA", self.drive)
        self.secuencia = {}
        for empresa in empresas:
            inicial = m.estado_inicial(empresa)
            self.casa.raiz(empresa).update(inicial)
            self.oficina.raiz(empresa).update(inicial)
            turno = self.turno(self.casa, empresa)
            assert turno.adquirir() == "PENDIENTE"
            assert self.cerrar(turno) == "PUBLICADA"

    def turno(self, equipo, empresa=EMP):
        return m.TurnoEscritor(self.nube, equipo, empresa)

    def cerrar(self, turno, *, exito=True, **kw):
        n = self.secuencia.get(turno.empresa, 0) + 1
        previa = f"gen-{n - 1:04d}" if n > 1 else None
        resultado = turno.cerrar(exito=exito, generacion_id=f"gen-{n:04d}", previa_id=previa, secuencia=n, **kw)
        if resultado == "PUBLICADA":
            self.secuencia[turno.empresa] = n
        return resultado

    def lectura(self, equipo=None, empresa=EMP):
        return m.leer_coherente(self.nube, equipo or self.casa, empresa)


def contenido(lectura, clave):
    identidad = next(f.identidad for f in m.FUENTES_FIJAS if f.clave == clave)
    return lectura.fuentes[identidad][1]


def coherente(dataset: bytes, ledger: bytes, bandeja: bytes) -> bool:
    """Invariante de la decisión: o no aplicada en ninguna fuente, o aplicada en todas."""
    fila = m.leer_csv(dataset)[0]
    aplicaciones = json.loads(ledger)["aplicaciones"]
    tarjetas = json.loads(bandeja)["decisiones"]
    if not aplicaciones:
        return fila["destino"] == "OBRA A" and fila["estado"] == "PENDIENTE" and len(tarjetas) == 1
    ultima = aplicaciones[-1]
    return fila["destino"] == ultima["destino"] and fila["estado"] == "RESUELTO" and not tarjetas


def coherente_lectura(lectura) -> bool:
    return coherente(contenido(lectura, "dataset"), contenido(lectura, "ledger"), contenido(lectura, "bandeja"))


def coherente_vivo(raiz) -> bool:
    return coherente(raiz[m.RUTA["dataset"]], raiz[m.RUTA["ledger"]], raiz[m.RUTA["bandeja"]])


# 1 ---------------------------------------------------------------- decisión humana entre escrituras
def test_decision_humana_entre_escrituras():
    w = Mundo()
    turno = w.turno(w.casa)
    assert turno.adquirir() == "PENDIENTE"
    pasos = m.pasos_decision_humana(turno, token=TOKEN, destino="OBRA B", confirmada=True)
    next(pasos), next(pasos)                      # acciones + ledger escritos; dataset todavía no
    assert not coherente_vivo(w.casa.raiz(EMP))   # el lector vivo ve una mezcla
    lectura = w.lectura()
    assert lectura.estado == "CONFIABLE" and lectura.generacion == "gen-0001"
    assert lectura.frescura == "OPERACION_EN_CURSO" and coherente_lectura(lectura)
    for _ in pasos:
        pass
    assert w.cerrar(turno) == "PUBLICADA"
    lectura = w.lectura()
    assert lectura.generacion == "gen-0002" and lectura.frescura == "ESTABLE" and coherente_lectura(lectura)
    assert m.leer_csv(contenido(lectura, "dataset"))[0]["destino"] == "OBRA B"


# 2 ---------------------------------------------------------------- dos escritores con locks independientes
def test_dos_escritores_con_locks_independientes():
    w = Mundo()
    raiz = w.casa.raiz(EMP)
    # Mundo actual: dos procesos con locks distintos (revalidacion_dataset, agrupaciones_viaje)
    # y un lector que copia archivo por archivo.
    instantanea = {}
    instantanea["dataset"] = raiz[m.RUTA["dataset"]]
    w.casa.escribir_sin_turno(EMP, m.RUTA["agrupaciones"], m._json({"agrupaciones": [{"id": "A1"}]}))
    w.casa.escribir_sin_turno(EMP, m.RUTA["dataset"], m._csv([{"archivo": "Guia 900001.jpg", "numero_guia": "900001",
                                                              "destino": "OBRA A", "estado": "AGRUPADO"}]))
    instantanea["agrupaciones"] = raiz[m.RUTA["agrupaciones"]]
    assert m.clasificar(instantanea["agrupaciones"]) == m.CON_DATOS
    assert m.leer_csv(instantanea["dataset"])[0]["estado"] == "PENDIENTE"   # mezcla: agrupación nueva, dataset viejo
    # El turno siguiente detecta las escrituras no gobernadas (copia local != generación publicada),
    # como el protocolo 2 de custodia: no escribe sobre ellas.
    assert w.turno(w.casa).adquirir() == "ESTADO_NO_VERIFICADO"
    # Protocolo: el turno es único por empresa; un segundo escritor no obtiene lease ni escribe.
    w = Mundo()
    primero, segundo = w.turno(w.casa), w.turno(w.casa)
    assert primero.adquirir() == "PENDIENTE"
    assert segundo.adquirir() == "OCUPADO"
    with pytest.raises(m.EscrituraSinTurno):
        segundo.escribir(m.RUTA["agrupaciones"], m._json({}))


# 3 ---------------------------------------------------------------- reproceso de cuarentena no gobernado
def test_reproceso_cuarentena_sin_turno_durante_captura_aborta():
    w = Mundo()
    turno = w.turno(w.casa)
    assert turno.adquirir() == "PENDIENTE"

    def promover():  # reproceso_cuarentena.promover_candidato: dataset + bandeja con su propio lock
        w.casa.escribir_sin_turno(EMP, m.RUTA["dataset"], m._csv([{"archivo": "Guia 900001.jpg", "numero_guia": "900001",
                                                                  "destino": "OBRA C", "estado": "PENDIENTE"}]))
        w.casa.escribir_sin_turno(EMP, m.RUTA["bandeja"], m._json({"decisiones": []}))
    assert w.cerrar(turno, entre_pasadas=promover) == "PENDIENTE_QUEDA:CAPTURA_INESTABLE"
    assert w.lectura().generacion == "gen-0001"


def test_limite_escritor_no_gobernado_detenido_no_se_detecta():
    """La doble pasada NO detecta a un escritor no gobernado detenido a mitad de operación.

    Por eso el diseño exige que todo escritor participe del turno: no se puede
    compensar con detección. La prueba fija el límite, no una garantía.
    """
    w = Mundo()
    turno = w.turno(w.casa)
    assert turno.adquirir() == "PENDIENTE"
    orden = [f.ruta for f in m.FUENTES_FIJAS]
    assert orden.index(m.RUTA["dataset"]) < orden.index(m.RUTA["ledger"])

    def durante(i, ruta):
        if ruta == m.RUTA["ledger"]:   # el dataset ya se leyó; el escritor no gobernado escribe sólo el ledger
            ledger = json.loads(w.casa.raiz(EMP)[m.RUTA["ledger"]])
            ledger["aplicaciones"].append({"token": "x", "destino": "OBRA Z", "actor": "HUMANO"})
            w.casa.escribir_sin_turno(EMP, m.RUTA["ledger"], m._json(ledger))
    assert w.cerrar(turno, durante_pasada=durante) == "PUBLICADA"
    assert not coherente_lectura(w.lectura())   # mezcla publicada: el límite queda demostrado


# 4 ---------------------------------------------------------------- evidencia Desktop durante la captura
def test_evidencia_desktop_fuera_del_turno_durante_captura_aborta():
    w = Mundo()
    turno = w.turno(w.casa)
    assert turno.adquirir() == "PENDIENTE"
    electron = lambda: w.casa.escribir_sin_turno(EMP, m.ENTRADAS + "lote-2/Guia 900001.jpg", b"foto-nueva")  # noqa: E731
    assert w.cerrar(turno, entre_pasadas=electron) == "PENDIENTE_QUEDA:CAPTURA_INESTABLE"


def test_evidencia_dentro_del_turno_queda_representada():
    w = Mundo()
    turno = w.turno(w.casa)
    assert turno.adquirir() == "PENDIENTE"
    turno.escribir(m.ENTRADAS + "lote-2/Guia 900001.jpg", b"foto-relectura")   # ingreso vía desktop_operacion
    assert w.cerrar(turno) == "PUBLICADA"
    lectura = w.lectura()
    evidencias = [i for i in lectura.fuentes if i.startswith("evidencia/") and i.count("/") == 3]
    assert len(evidencias) == 2  # original y relectura del mismo documento, sin colisión
    assert {lectura.fuentes[i][1] for i in evidencias} == {b"foto-sintetica-900001", b"foto-relectura"}


# 5 ---------------------------------------------------------------- ausente frente a vacío
def test_ausente_ilegible_y_vacio_se_distinguen():
    raiz = {"a": None}
    assert m.lector_ingenuo({}, "x") == m.lector_ingenuo({"x": b"{}"}, "x") == m.lector_ingenuo({"x": b"{"}, "x") == {}
    assert m.clasificar(raiz.get("x")) == m.AUSENTE
    assert m.clasificar(b"{") == m.ILEGIBLE and m.clasificar(b"\xff\xfe") == m.ILEGIBLE
    assert m.clasificar(b'{"decisiones":[]}') == m.VACIA and m.clasificar(b"archivo;numero_guia\n") == m.VACIA
    assert m.clasificar(b'{"decisiones":[{"d":1}]}') == m.CON_DATOS


@pytest.mark.parametrize("estado,resultado", [
    (None, "PENDIENTE_QUEDA:FUENTE_OBLIGATORIA_AUSENTE"),
    (b"{no-es-json", "PENDIENTE_QUEDA:FUENTE_ILEGIBLE"),
    (b'{"decisiones": []}', "PUBLICADA"),
])
def test_captura_no_confunde_ausente_con_vacio(estado, resultado):
    w = Mundo()
    turno = w.turno(w.casa)
    assert turno.adquirir() == "PENDIENTE"
    turno.escribir(m.RUTA["bandeja"], estado)
    assert w.cerrar(turno) == resultado
    if resultado == "PUBLICADA":
        identidad = next(f.identidad for f in m.FUENTES_FIJAS if f.clave == "bandeja")
        assert w.lectura().fuentes[identidad][0] == m.VACIA
    else:
        assert w.lectura().generacion == "gen-0001"


def test_evidencia_referida_ausente_no_se_omite():
    w = Mundo()
    turno = w.turno(w.casa)
    turno.adquirir()
    turno.escribir(m.ENTRADAS + "lote-1/Guia 900001.jpg", None)
    assert w.cerrar(turno) == "PENDIENTE_QUEDA:EVIDENCIA_NO_ENCONTRADA"
    assert w.lectura().generacion == "gen-0001"


def test_lector_no_confiable_si_falta_un_objeto():
    w = Mundo()
    lectura = w.lectura(w.oficina)
    assert lectura.estado == "CONFIABLE"
    w.oficina.raiz(EMP)[m.RUTA["ledger"]] = b"alterado-localmente"
    victima = next(f for f in m.FUENTES_FIJAS if f.clave == "ledger")
    h = dg.huella_contenido(m.estado_inicial(EMP)[victima.ruta]).removeprefix("sha256:")
    del w.nube.e(EMP).objetos[h]
    assert w.lectura(w.oficina) == m.Lectura("NO_CONFIABLE", "OBJETO_NO_DISPONIBLE", "gen-0001")


# 6-7 -------------------------------------------------------------- caídas y recuperación
PASOS_DECISION = 5


@pytest.mark.parametrize("caer_en", range(0, PASOS_DECISION + 1))
def test_caida_en_cada_punto_y_recuperacion(caer_en):
    w = Mundo()
    turno = w.turno(w.casa)
    assert turno.adquirir() == "PENDIENTE"
    if caer_en:
        m.ejecutar(m.pasos_decision_humana(turno, token=TOKEN, destino="OBRA B", confirmada=True), caer_en=caer_en)
    # El proceso cae: no hay cierre. Los lectores siguen viendo la última COMPLETA, nunca una mezcla.
    lectura = w.lectura()
    assert lectura.generacion == "gen-0001" and coherente_lectura(lectura)
    assert lectura.frescura == "OPERACION_EN_CURSO"
    w.nube.avanzar(m.LEASE_SEGUNDOS + 1)
    assert w.lectura().frescura == "INTERRUMPIDA"
    nuevo = w.turno(w.casa)
    assert nuevo.adquirir() == "INTERRUMPIDA"
    informe = m.recuperar(nuevo)
    # caer_en == PASOS_DECISION: todas las escrituras hechas, caída antes de cerrar: nada que reaplicar.
    assert informe["reaplicadas"] == ([TOKEN] if 1 <= caer_en < PASOS_DECISION else [])
    assert w.cerrar(nuevo) in {"PUBLICADA", "SIN_CAMBIOS"}
    final = w.lectura()
    assert final.frescura == "ESTABLE" and coherente_lectura(final)
    aplicaciones = json.loads(contenido(final, "ledger"))["aplicaciones"]
    assert [a["token"] for a in aplicaciones] == ([TOKEN] if caer_en >= 1 else [])


def test_error_a_mitad_de_operacion_no_publica():
    """El proceso sigue vivo pero la operación falló: el cierre no captura una mezcla."""
    w = Mundo()
    turno = w.turno(w.casa)
    turno.adquirir()
    m.ejecutar(m.pasos_decision_humana(turno, token=TOKEN, destino="OBRA B", confirmada=True), caer_en=3)
    assert w.cerrar(turno, exito=False) == "PENDIENTE_QUEDA"
    assert w.lectura().generacion == "gen-0001" and w.lectura().frescura == "INTERRUMPIDA"
    nuevo = w.turno(w.casa)
    assert nuevo.adquirir() == "INTERRUMPIDA"


def test_no_se_publica_sobre_una_interrupcion_sin_recuperar():
    w = Mundo()
    turno = w.turno(w.casa)
    turno.adquirir()
    m.ejecutar(m.pasos_decision_humana(turno, token=TOKEN, destino="OBRA B", confirmada=True), caer_en=2)
    w.nube.avanzar(m.LEASE_SEGUNDOS + 1)
    nuevo = w.turno(w.casa)
    assert nuevo.adquirir() == "INTERRUMPIDA"
    with pytest.raises(m.ErrorProtocolo) as exc:     # sin recuperar(): ni publicar ni cerrar sin cambios
        w.cerrar(nuevo)
    assert exc.value.codigo == "SIN_FRONTERA_DE_ESTA_EPOCA"
    assert w.lectura().generacion == "gen-0001"


def test_nube_conserva_el_pendiente_de_la_epoca_interrumpida():
    """Defensa del lado Cloud: aunque un cliente no compruebe, abrir frontera no borra la interrupción."""
    nube = m.NubeModelo()
    token, _ = nube.adquirir(EMP, "CASA")
    assert nube.abrir_frontera(EMP, token) == "PENDIENTE"
    nube.avanzar(m.LEASE_SEGUNDOS + 1)
    token2, epoca2 = nube.adquirir(EMP, "CASA")
    assert nube.abrir_frontera(EMP, token2) == "INTERRUMPIDA"
    assert nube.e(EMP).control["epoca"] == epoca2 - 1


def test_caida_antes_de_marcar_pendiente():
    w = Mundo()
    assert w.nube.adquirir(EMP, "CASA") is not None   # lease tomado, frontera nunca abierta
    w.nube.avanzar(m.LEASE_SEGUNDOS + 1)
    assert w.lectura().frescura == "ESTABLE"
    assert w.turno(w.casa).adquirir() == "PENDIENTE"   # nada que recuperar


def test_caida_antes_de_completa():
    w = Mundo()
    turno = w.turno(w.casa)
    turno.adquirir()
    m.ejecutar(m.pasos_decision_humana(turno, token=TOKEN, destino="OBRA B", confirmada=True))
    original = w.nube.publicar

    def cae(*a, **k):
        raise m.ErrorProtocolo("PROCESO_TERMINADO")
    w.nube.publicar = cae
    with pytest.raises(m.ErrorProtocolo):
        w.cerrar(turno)            # objetos subidos, puntero sin cambiar
    w.nube.publicar = original
    assert w.lectura().generacion == "gen-0001"
    w.nube.avanzar(m.LEASE_SEGUNDOS + 1)
    nuevo = w.turno(w.casa)
    assert nuevo.adquirir() == "INTERRUMPIDA"
    m.recuperar(nuevo)
    assert w.cerrar(nuevo) == "PUBLICADA" and coherente_lectura(w.lectura())


def test_caida_inmediatamente_despues_de_completa():
    w = Mundo()
    turno = w.turno(w.casa)
    turno.adquirir()
    m.ejecutar(m.pasos_decision_humana(turno, token=TOKEN, destino="OBRA B", confirmada=True))
    liberar = w.nube.liberar
    w.nube.liberar = lambda *a, **k: None        # cae antes de liberar el lease
    assert w.cerrar(turno) == "PUBLICADA"
    w.nube.liberar = liberar
    assert w.lectura().frescura == "ESTABLE" and w.lectura().generacion == "gen-0002"
    w.nube.avanzar(m.LEASE_SEGUNDOS + 1)
    assert w.turno(w.casa).adquirir() == "PENDIENTE"   # la publicación cerró el PENDIENTE en el mismo CAS


def test_preview_no_confirmado_nunca_se_confirma_al_recuperar():
    w = Mundo()
    turno = w.turno(w.casa)
    turno.adquirir()
    m.ejecutar(m.pasos_decision_humana(turno, token="tok-preview", destino="OBRA X", confirmada=False))
    w.nube.avanzar(m.LEASE_SEGUNDOS + 1)
    nuevo = w.turno(w.casa)
    assert nuevo.adquirir() == "INTERRUMPIDA"
    assert m.recuperar(nuevo) == {"reaplicadas": [], "previews_sin_confirmar": ["tok-preview"]}
    assert w.cerrar(nuevo) == "PUBLICADA"
    final = w.lectura()
    assert json.loads(contenido(final, "ledger"))["aplicaciones"] == []
    assert json.loads(contenido(final, "acciones_operacionales"))["previews"]["tok-preview"]["estado"] == "PREVIEW"


def test_perdida_de_lease_durante_operacion():
    w = Mundo()
    turno = w.turno(w.casa)
    turno.adquirir()
    pasos = m.pasos_decision_humana(turno, token=TOKEN, destino="OBRA B", confirmada=True)
    next(pasos), next(pasos)
    w.nube.avanzar(m.LEASE_SEGUNDOS + 1)                    # heartbeat perdido
    otro = w.turno(w.oficina)
    w.drive.sincronizar(w.oficina)                           # Drive llevó escrituras parciales de CASA
    assert otro.adquirir() == "INTERRUMPIDA_EN_OTRO_EQUIPO"  # la época nueva ve el PENDIENTE de CASA
    with pytest.raises(m.EscrituraSinTurno):
        next(pasos)                                          # CASA ya no puede escribir
    assert w.cerrar(turno) == "PENDIENTE_QUEDA"
    with pytest.raises(m.ErrorProtocolo):
        w.nube.publicar(EMP, turno.token or "lease-viejo", {"empresa_id": EMP, "generacion_id": "x", "objetos": []}, "0")
    assert w.lectura().generacion == "gen-0001"
    # OFICINA no recupera sola: sin autorización no hay relevo; con ella, vuelve a la última COMPLETA.
    with pytest.raises(m.ErrorProtocolo):
        m.restaurar_ultima_completa(otro, autorizado_por=" ")
    restauradas = m.restaurar_ultima_completa(otro, autorizado_por="Javier")
    assert m.RUTA["ledger"] in restauradas and coherente_vivo(w.oficina.raiz(EMP))
    assert w.cerrar(otro) == "SIN_CAMBIOS"
    assert w.lectura().frescura == "ESTABLE" and coherente_lectura(w.lectura())
    assert json.loads(contenido(w.lectura(), "ledger"))["aplicaciones"] == []   # nada parcial se publicó


# 8 ---------------------------------------------------------------- CASA / OFICINA
def test_competencia_casa_oficina_y_replica_desfasada():
    w = Mundo()
    casa = w.turno(w.casa)
    assert casa.adquirir() == "PENDIENTE"
    assert w.turno(w.oficina).adquirir() == "OCUPADO"
    m.ejecutar(m.pasos_decision_humana(casa, token=TOKEN, destino="OBRA B", confirmada=True))
    assert w.cerrar(casa) == "PUBLICADA"
    # Drive todavía no llevó los cambios a OFICINA.
    oficina = w.turno(w.oficina)
    assert oficina.adquirir() == "ESTADO_NO_VERIFICADO"
    lectura = w.lectura(w.oficina)                           # el lector no usa la copia desfasada
    assert lectura.generacion == "gen-0002" and coherente_lectura(lectura)
    assert m.leer_csv(contenido(lectura, "dataset"))[0]["destino"] == "OBRA B"
    assert not coherente_vivo(w.oficina.raiz(EMP)) or m.leer_csv(w.oficina.raiz(EMP)[m.RUTA["dataset"]])[0]["destino"] == "OBRA A"
    w.drive.sincronizar(w.oficina)
    assert w.turno(w.oficina).adquirir() == "PENDIENTE"     # sin intervención manual tras sincronizar


def test_replica_parcial_desordenada_no_se_publica_como_coherente():
    w = Mundo()
    casa = w.turno(w.casa)
    casa.adquirir()
    m.ejecutar(m.pasos_decision_humana(casa, token=TOKEN, destino="OBRA B", confirmada=True))
    w.cerrar(casa)
    w.drive.sincronizar(w.oficina, solo={m.RUTA["ledger"]})  # llega el ledger, no el dataset
    assert not coherente_vivo(w.oficina.raiz(EMP))           # el archivo vivo en OFICINA está mezclado
    assert w.turno(w.oficina).adquirir() == "ESTADO_NO_VERIFICADO"
    assert coherente_lectura(w.lectura(w.oficina))


# 9 ---------------------------------------------------------------- empresas
def test_separacion_entre_empresas():
    w = Mundo(empresas=(EMP, MBT))
    a, b = w.turno(w.casa, EMP), w.turno(w.casa, MBT)
    assert a.adquirir() == "PENDIENTE" and b.adquirir() == "PENDIENTE"   # leases independientes
    m.ejecutar(m.pasos_decision_humana(a, token=TOKEN, destino="OBRA B", confirmada=True))
    assert w.cerrar(a) == "PUBLICADA" and w.cerrar(b) == "SIN_CAMBIOS"
    assert w.lectura(empresa=EMP).generacion == "gen-0002" and w.lectura(empresa=MBT).generacion == "gen-0001"
    assert not any(f.startswith("empresa/") for f in w.lectura(empresa=MBT).fuentes)   # MBT sin marca
    h = next(iter(w.nube.e(EMP).objetos))
    assert w.nube.descargar(MBT, h) is None or w.nube.descargar(MBT, h) == w.nube.descargar(EMP, h)
    otro = w.turno(w.casa, MBT)
    otro.adquirir()
    cuerpo = dict(w.nube.actual(EMP)["descriptor"])
    with pytest.raises(m.ErrorProtocolo) as exc:
        w.nube.publicar(MBT, otro.token, cuerpo, "0")
    assert exc.value.codigo == "GENERACION_INVALIDA"


def test_turno_sin_cambios_no_crea_generacion():
    w = Mundo()
    turno = w.turno(w.casa)
    assert turno.adquirir() == "PENDIENTE"
    assert w.cerrar(turno) == "SIN_CAMBIOS"
    assert w.lectura().generacion == "gen-0001" and w.lectura().frescura == "ESTABLE"


# ------------------------------------------------------------------ modelo atado al contrato real
def test_modelo_usa_el_contrato_real():
    tipos = {f.tipo for f in m.FUENTES_FIJAS}
    obligatorios = {t for t, r in dg.TIPOS_V2.items() if r.obligatorio}
    assert obligatorios <= tipos
    assert {f.rol for f in m.FUENTES_FIJAS if f.tipo == "DECISIONES_HUMANAS"} == dg.ROLES_DECISIONES_HUMANAS


_vigilancia = {"activa": False, "eventos": []}


def _auditor(evento, args):
    if _vigilancia["activa"] and evento in {"open", "os.remove", "os.rename", "os.replace", "os.mkdir",
                                            "socket.connect", "subprocess.Popen"}:
        _vigilancia["eventos"].append((evento, repr(args)[:100]))


sys.addaudithook(_auditor)


def test_modelo_sin_disco_ni_red():
    Mundo()  # calienta importaciones
    _vigilancia["eventos"].clear()
    _vigilancia["activa"] = True
    try:
        w = Mundo()
        turno = w.turno(w.casa)
        turno.adquirir()
        m.ejecutar(m.pasos_decision_humana(turno, token=TOKEN, destino="OBRA B", confirmada=True))
        w.cerrar(turno)
        w.lectura(w.oficina)
    finally:
        _vigilancia["activa"] = False
    assert _vigilancia["eventos"] == []
