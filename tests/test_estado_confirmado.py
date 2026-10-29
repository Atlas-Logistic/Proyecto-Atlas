"""Relevo automático CASA <-> OFICINA con marca de estado confirmado (protocolo 2).

Cloud se simula con la misma semántica del Worker (lease con prioridad del
último escritor, marca versionada, historial de huellas y objetos por huella).
Cada equipo tiene su propia raíz: la "copia de Drive" de cada PC, que se
desfasa a voluntad para reproducir retrasos y archivos pendientes de subir.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from atlas_core import escritor_operativo as eo
from atlas_core import estado_confirmado as ec


def sha(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


class CloudFalsa:
    def __init__(self, *, protocolo_minimo: int = 1, con_marca: bool = True):
        self.ahora = datetime(2026, 10, 29, 18, 0, tzinfo=timezone.utc)
        self.lease = {"token": None, "escritor": None, "expira": self.ahora, "epoca": 0, "ultimo": None, "actividad": None}
        self.marca = {"version": 0, "protocolo_minimo": protocolo_minimo}
        self.archivos: list[tuple[str, int, str | None]] = []
        self.objetos: dict[str, bytes] = {}
        self.con_marca = con_marca
        self.descarga_falla = False

    def avanzar(self, minutos: float) -> None:
        self.ahora += timedelta(minutes=minutos)

    def _vigente(self, token) -> bool:
        return bool(token) and token == self.lease["token"] and self.lease["expira"] > self.ahora

    def json(self, _base, ruta, _token, *, method="GET", body=None, timeout=0):
        l = self.lease
        if ruta.endswith("/escritor/estado"):
            vigente = self._vigente(l["token"])
            return {"vigente": vigente, "escritor_id": l["escritor"] if vigente else None, "epoca": l["epoca"]}
        if ruta.endswith("/escritor/adquirir"):
            if int(body.get("protocolo", 1)) < self.marca["protocolo_minimo"]:
                raise eo.EscritorOcupado("409", "ESCRITOR_PROTOCOLO_OBSOLETO")
            if self._vigente(l["token"]):
                raise eo.EscritorOcupado("409", "ESCRITOR_OCUPADO")
            yo = body["escritor_id"]
            if l["ultimo"] not in (None, yo) and l["actividad"] > self.ahora - timedelta(minutes=10):
                raise eo.EscritorOcupado("409", "ESCRITOR_PRIORIDAD")
            l.update(token=str(uuid.uuid4()), escritor=yo, expira=self.ahora + timedelta(seconds=120),
                     epoca=l["epoca"] + 1, ultimo=yo, actividad=self.ahora)
            r = {"estado": "ADQUIRIDO", "lease_token": l["token"], "epoca": l["epoca"]}
            if body.get("protocolo", 1) >= 2 and self.con_marca:
                r["marca"] = {"version": self.marca["version"]}
            return r
        if ruta.endswith("/escritor/renovar"):
            if not self._vigente(body["lease_token"]):
                raise eo.ErrorEscritorOperativo("409")
            l.update(expira=self.ahora + timedelta(seconds=120), actividad=self.ahora)
            return {"estado": "RENOVADO"}
        if ruta.endswith("/escritor/liberar"):
            if body["lease_token"] != l["token"]:
                raise eo.ErrorEscritorOperativo("409")
            l.update(token=None, escritor=None, expira=self.ahora, actividad=self.ahora)
            return {"estado": "LIBERADO"}
        if ruta.endswith("/estado/manifiesto"):
            return {"version": self.marca["version"], "archivos": [[r, s, v] for r, (s, v) in self._vigentes().items()]}
        if ruta.endswith("/estado/conocidos"):
            return {"conocidos": [any(r == c[0] and s == c[1] for r, _v, s in self.archivos) for c in body["consultas"]]}
        if ruta.endswith("/estado/faltantes"):
            return {"faltantes": [h for h in body["sha256"] if h not in self.objetos]}
        if ruta.endswith("/estado/confirmar"):
            if not self._vigente(body["lease_token"]):
                raise eo.ErrorEscritorOperativo("409 ESCRITOR_NO_VIGENTE")
            if body["version_base"] != self.marca["version"]:
                raise eo.ErrorEscritorOperativo("409 VERSION_ESTADO_SUPERADA")
            for _r, s in body["archivos"]:
                if s and s not in self.objetos:
                    raise eo.ErrorEscritorOperativo("409 OBJETO_AUSENTE")
            self.marca["version"] += 1
            self.archivos += [(r, self.marca["version"], s) for r, s in body["archivos"]]
            return {"estado": "CONFIRMADO", "version": self.marca["version"]}
        raise AssertionError(ruta)

    def _vigentes(self):
        salida = {}
        for r, v, s in self.archivos:
            if r not in salida or v > salida[r][1]:
                salida[r] = (s, v)
        return salida

    def crudo(self, _cliente, huella, *, method, data=None, lease_token=""):
        if method == "PUT":
            assert self._vigente(lease_token) and sha(data) == huella
            self.objetos[huella] = bytes(data)
            return b"{}"
        if self.descarga_falla:
            raise eo.ErrorEscritorOperativo("Cloud caído")
        return self.objetos[huella]


class Equipo:
    """Un PC: identidad propia, su copia de Drive y su LOCALAPPDATA."""

    def __init__(self, base: Path, nombre: str, cloud: CloudFalsa):
        self.raiz = base / nombre / "Atlas"
        self.local = base / nombre / "local"
        (self.raiz / "operacion" / "actual").mkdir(parents=True)
        self.id = f"pc-{nombre}"
        self.cloud = cloud

    def lease(self, *, protocolo2: bool = True) -> eo.LeaseEscritorOperativo:
        lease = eo.LeaseEscritorOperativo(base_url="https://cloud.test", token_motor="t", escritor_id=self.id,
                                          heartbeat_segundos=0, margen_relevo_segundos=0,
                                          ruta_relevo=self.local / "relevo.json")
        if protocolo2:
            lease.custodia = ec.CustodiaEstado(self.raiz, ec.ClienteEstado("https://cloud.test", "t", 5), carpeta_local=self.local)
        return lease

    def archivo(self, rel: str) -> Path:
        return self.raiz.joinpath(*rel.split("/"))

    def escribir(self, rel: str, texto: str) -> None:
        ruta = self.archivo(rel)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal = ruta.with_name(f".{ruta.name}.x1.tmp")
        temporal.write_text(texto, encoding="utf-8")
        os.replace(temporal, ruta)

    def leer(self, rel: str) -> str:
        return self.archivo(rel).read_text(encoding="utf-8")


DATASET = "operacion/actual/analisis_completo_guias.csv"
CATALOGO = "catalogos_privados/vehiculos.json"


class RelevoEstadoConfirmado(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.cloud = CloudFalsa()
        self.casa = Equipo(base, "casa", self.cloud)
        self.oficina = Equipo(base, "oficina", self.cloud)
        self._parches = [patch("atlas_core.escritor_operativo._json", side_effect=self.cloud.json),
                         patch.object(ec.ClienteEstado, "_crudo", lambda c, h, **kw: self.cloud.crudo(c, h, **kw))]
        for p in self._parches:
            p.start()

    def tearDown(self):
        for p in self._parches:
            p.stop()
        ec._activas.clear()
        self._tmp.cleanup()

    def turno(self, equipo: Equipo, escrituras: dict[str, str]):
        with equipo.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            for rel, texto in escrituras.items():
                equipo.escribir(rel, texto)
        return lease

    def test_relevo_restaura_la_copia_atrasada_antes_de_escribir(self):
        self.oficina.escribir(DATASET, "v0")  # Drive de OFICINA aún no recibe v1
        self.turno(self.casa, {DATASET: "v1", CATALOGO: "cat-1"})
        self.assertEqual(self.cloud.marca["version"], 1)
        self.cloud.avanzar(11)
        with self.oficina.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            self.assertEqual(self.oficina.leer(DATASET), "v1")
            self.assertEqual(self.oficina.leer(CATALOGO), "cat-1")
            # v0 es contenido nunca confirmado: se conserva fuera de Drive.
            self.assertEqual(lease.custodia.resumen["cuarentena"], [DATASET])
            self.oficina.escribir(DATASET, "v2")
        self.assertEqual(self.cloud._vigentes()[DATASET][0], sha(b"v2"))

    def test_sin_coincidencia_verificable_se_libera_el_lease_sin_escribir(self):
        self.turno(self.casa, {DATASET: "v1"})
        self.cloud.avanzar(11)
        self.cloud.descarga_falla = True
        lease = self.oficina.lease()
        self.assertFalse(lease.adquirir())
        self.assertEqual(lease.motivo, "ESTADO_NO_VERIFICADO")
        self.assertIsNone(self.cloud.lease["token"])
        self.assertFalse(self.oficina.archivo(DATASET).exists())
        self.assertEqual(ec._activas, [])

    def test_pull_no_consume_envios_si_el_estado_no_se_verifica(self):
        import sincronizar_mobile_cloud as smc
        self.turno(self.casa, {DATASET: "v1"})
        self.cloud.avanzar(11)
        self.cloud.descarga_falla = True

        class Repo:
            raiz_atlas = self.oficina.raiz

        fabrica = lambda **kw: self.oficina.lease(protocolo2=False)
        with patch("atlas_core.cloud_mobile_sync_cliente.sincronizar_envios_cloud") as sincronizar, \
                patch.object(smc, "sincronizar_envios_cloud") as sincronizar_local, \
                patch.object(ec, "ruta_local", return_value=self.oficina.local):
            resultado = smc.ejecutar_pull_con_escritor(
                base_url="https://cloud.test", token_motor="t", consumidor="oficina", repositorio=Repo(),
                timeout=5, procesar=True, dataset=None, carpeta_catalogos=None, fabrica_escritor=fabrica)
        self.assertEqual(resultado["escritor_operativo"], "NO_ADQUIRIDO")
        self.assertEqual(resultado["motivo"], "ESTADO_NO_VERIFICADO")
        sincronizar.assert_not_called()
        sincronizar_local.assert_not_called()

    def test_apagado_inesperado_se_confirma_al_volver_si_nadie_confirmo(self):
        self.turno(self.casa, {DATASET: "v1"})
        lease = self.casa.lease()
        self.assertTrue(lease.adquirir())
        self.casa.escribir(DATASET, "v2-sin-confirmar")
        lease.custodia.detener()  # corte de luz: sin confirmar ni liberar
        self.cloud.avanzar(3)
        with self.casa.lease() as vuelta:
            self.assertTrue(vuelta.adquirir(), vuelta.motivo)
            self.assertEqual(vuelta.custodia.resumen["pendiente_confirmado"], 1)
        self.assertEqual(self.casa.leer(DATASET), "v2-sin-confirmar")
        self.assertEqual(self.cloud._vigentes()[DATASET][0], sha(b"v2-sin-confirmar"))

    def test_apagado_superado_por_otro_equipo_va_a_cuarentena(self):
        self.turno(self.casa, {DATASET: "v1"})
        lease = self.casa.lease()
        self.assertTrue(lease.adquirir())
        self.casa.escribir(DATASET, "casa-sin-confirmar")
        lease.custodia.detener()
        self.cloud.avanzar(11)
        self.oficina.escribir(DATASET, "v1")
        self.turno(self.oficina, {DATASET: "oficina-v2"})
        self.cloud.avanzar(11)
        with self.casa.lease() as vuelta:
            self.assertTrue(vuelta.adquirir(), vuelta.motivo)
            self.assertEqual(vuelta.custodia.resumen["cuarentena"], [DATASET])
        self.assertEqual(self.casa.leer(DATASET), "oficina-v2")
        copias = list((self.casa.local / "cuarentena").rglob("analisis_completo_guias.csv"))
        self.assertEqual([c.read_text(encoding="utf-8") for c in copias], ["casa-sin-confirmar"])

    def test_equipo_que_vuelve_con_archivos_viejos_no_sobrescribe_lo_nuevo(self):
        self.turno(self.casa, {DATASET: "v1", CATALOGO: "cat-1"})
        self.cloud.avanzar(11)
        self.turno(self.oficina, {DATASET: "v2"})
        # CASA se enciende y Drive sube su v1 viejo encima de la copia de OFICINA.
        self.oficina.escribir(DATASET, "v1")
        self.cloud.avanzar(2)
        with self.oficina.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            self.assertEqual(lease.custodia.resumen["restaurados"], [DATASET])
            self.assertEqual(lease.custodia.resumen["cuarentena"], [])  # v1 era una versión conocida
        self.assertEqual(self.oficina.leer(DATASET), "v2")
        # Y CASA, en espera, no puede tomar el lease mientras OFICINA esté activa.
        espera = self.casa.lease()
        self.assertFalse(espera.adquirir())
        self.assertEqual(espera.motivo, "PRIORIDAD_OTRO_EQUIPO")
        self.assertFalse(espera.ocupado)

    def test_borrado_confirmado_se_replica(self):
        self.turno(self.casa, {"operacion/actual/temporal.json": "x"})
        with self.casa.lease() as lease:
            self.assertTrue(lease.adquirir())
            self.casa.archivo("operacion/actual/temporal.json").unlink()
        self.assertIsNone(self.cloud._vigentes()["operacion/actual/temporal.json"][0])
        self.cloud.avanzar(11)
        self.oficina.escribir("operacion/actual/temporal.json", "x")  # Drive no replicó el borrado
        with self.oficina.lease() as lease:
            self.assertTrue(lease.adquirir())
        self.assertFalse(self.oficina.archivo("operacion/actual/temporal.json").exists())

    def test_registro_omite_temporales_locks_y_carpetas_inmutables(self):
        with self.casa.lease() as lease:
            self.assertTrue(lease.adquirir())
            self.casa.escribir("reportes/r1/reporte.xlsx", "r")
            self.casa.escribir("operacion/actual/.atlas_lock_x", "l")
            self.casa.escribir(DATASET, "v1")
            registradas = set(lease.custodia.modificadas)
        self.assertEqual(registradas, {DATASET})
        self.assertEqual(set(self.cloud._vigentes()), {DATASET})

    def test_cliente_antiguo_no_obtiene_lease_tras_activar(self):
        self.cloud.marca["protocolo_minimo"] = 2
        antiguo = self.oficina.lease(protocolo2=False)
        self.assertFalse(antiguo.adquirir())
        self.assertEqual(antiguo.motivo, "ESCRITOR_PROTOCOLO_OBSOLETO")
        self.assertFalse(antiguo.ocupado)
        self.assertTrue(self.casa.lease().adquirir())

    def test_worker_sin_protocolo_2_no_permite_escribir(self):
        self.cloud.con_marca = False
        lease = self.casa.lease()
        self.assertFalse(lease.adquirir())
        self.assertEqual(lease.motivo, "CLOUD_SIN_ESTADO_CONFIRMADO")
        self.assertIsNone(self.cloud.lease["token"])

    def test_semilla_publica_archivos_mutables(self):
        self.casa.escribir(DATASET, "v1")
        self.casa.escribir("operacion/mobile/envios/e1/envio.json", "{}")
        self.casa.escribir("operacion/mobile/envios/e1/original.jpg", "img")
        self.casa.escribir("reportes/r/x.xlsx", "r")
        with self.casa.lease() as lease:
            self.assertTrue(lease.adquirir())
            lease.custodia.sembrar(lease)
        self.assertEqual(set(self.cloud._vigentes()), {DATASET, "operacion/mobile/envios/e1/envio.json"})


if __name__ == "__main__":
    unittest.main()
