"""P0.2: recuperación, desde otro escritor, de un turno que nunca confirmó.

El equipo original se elimina por completo (raíz y LOCALAPPDATA): todo lo
necesario sale de Cloud (diario + contenido custodiado antes de escribir).
Misma Cloud simulada que tests/test_estado_confirmado.py.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas_core import estado_confirmado as ec
from tests.test_estado_confirmado import CATALOGO, CloudFalsa, Equipo, sha

DATASET = ec.RUTA_DATASET
ENVIO = "operacion/mobile/envios/env-1/envio.json"


def huella(texto: str) -> str:
    """Huella del archivo que deja Equipo.escribir (write_text traduce saltos)."""
    return sha(texto.replace("\n", os.linesep).encode())


def dataset(*ids: str) -> str:
    return "archivo;numero_guia\n" + "".join(f"{i};{i[1:]}\n" for i in ids)


class RecuperacionTurnoRemoto(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.cloud = CloudFalsa()
        self.casa = Equipo(self.base, "casa", self.cloud)
        self.oficina = Equipo(self.base, "oficina", self.cloud)
        self._parches = [patch("atlas_core.escritor_operativo._json", side_effect=self.cloud.json),
                         patch.object(ec.ClienteEstado, "_crudo", lambda c, h, **kw: self.cloud.crudo(c, h, **kw))]
        for p in self._parches:
            p.start()
        # Base confirmada por CASA y ya replicada por Drive en OFICINA.
        self.turno(self.casa, {DATASET: dataset("g1", "g2"), CATALOGO: "cat-1"})
        for rel in (DATASET, CATALOGO):
            self.oficina.escribir(rel, self.casa.leer(rel))
        self.version_base = self.cloud.marca["version"]

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

    def casa_cae(self, escrituras: dict[str, str], *, directas: dict[str, str] | None = None,
                 control: bool = False, borrar: bool = True) -> str:
        """CASA abre turno, escribe y se pierde sin confirmar ni liberar."""
        self.cloud.avanzar(3)
        lease = self.casa.lease()
        self.assertTrue(lease.adquirir(), lease.motivo)
        for rel, texto in escrituras.items():
            self.casa.escribir(rel, texto)
        for rel, texto in (directas or {}).items():
            with open(self.casa.archivo(rel), "a", encoding="utf-8") as archivo:
                archivo.write(texto)
            if control:
                ec.punto_de_control(self.casa.archivo(rel))
        diario = ec.ruta_diario("pc-casa", lease.epoca)
        lease.custodia.detener()
        lease._soltar_turno()
        if borrar:
            shutil.rmtree(self.casa.raiz.parent)
        self.cloud.avanzar(11)
        return diario

    def vigentes(self) -> dict:
        return {r: s for r, (s, _v) in self.cloud._vigentes().items()}

    # ------------------------------------------------------------ éxito
    def test_otro_equipo_recupera_el_turno_del_equipo_eliminado(self):
        escrito = {DATASET: dataset("g1", "g2", "g3"), CATALOGO: "cat-2", ENVIO: '{"envio_id": "env-1"}'}
        diario = self.casa_cae(escrito)
        self.assertFalse(self.casa.raiz.exists())
        with self.oficina.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            previa = lease.custodia.recuperar_turno(lease, diario)
            self.assertEqual(previa["estado"], "RECUPERABLE", previa)
            self.assertEqual(previa["documentos_recuperados"], ["g3"])
            self.assertEqual(self.oficina.leer(DATASET), dataset("g1", "g2"))  # la previa no escribe
            hecho = lease.custodia.recuperar_turno(lease, diario, aplicar=True)
            self.assertEqual(hecho["estado"], "RECUPERADO", hecho)
        for rel, texto in escrito.items():
            self.assertEqual(self.oficina.leer(rel), texto)
            self.assertEqual(self.vigentes()[rel], huella(texto))
        self.assertIsNone(self.vigentes()[diario])
        auditoria = f"{ec.CARPETA_RECUPERACIONES}/pc-casa__{json.loads(json.dumps(hecho))['epoca']}.json"
        self.assertIsNotNone(self.vigentes()[auditoria])
        self.assertEqual(json.loads(self.oficina.leer(auditoria))["recuperado_por"], "pc-oficina")
        self.assertEqual(ec.leer_diarios_remotos(ec.ClienteEstado("https://cloud.test", "t", 5))["diarios"], [])
        # Un segundo intento no duplica nada.
        version = self.cloud.marca["version"]
        self.cloud.avanzar(3)
        with self.oficina.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            self.assertEqual(lease.custodia.recuperar_turno(lease, diario, aplicar=True)["estado"], "YA_CERRADO")
        self.assertEqual(self.cloud.marca["version"], version)
        self.assertEqual(self.oficina.leer(DATASET), dataset("g1", "g2", "g3"))

    def test_drive_que_trajo_el_trabajo_no_bloquea_y_se_recupera_desde_cloud(self):
        # Antes de perderse, Drive alcanzó a copiar el dataset de CASA a OFICINA.
        nuevo = dataset("g1", "g2", "g3")
        self.oficina.escribir(DATASET, nuevo)
        diario = self.casa_cae({DATASET: nuevo})
        with self.oficina.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)  # antes: ESTADO_NO_VERIFICADO
            self.assertEqual(lease.custodia.resumen["cuarentena"], [DATASET])
            self.assertEqual(lease.custodia.recuperar_turno(lease, diario, aplicar=True)["estado"], "RECUPERADO")
        self.assertEqual(self.vigentes()[DATASET], huella(nuevo))

    def test_escritura_directa_exige_punto_de_control(self):
        diario = self.casa_cae({}, directas={DATASET: "g3;3\n"}, borrar=False)
        self.oficina.escribir(DATASET, dataset("g1", "g2"))
        with self.oficina.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            r = lease.custodia.recuperar_turno(lease, diario, aplicar=True)
        self.assertEqual(r["estado"], "BLOQUEADO")
        self.assertEqual(r["bloqueos"][0], {"codigo": "CONTENIDO_NO_CUSTODIADO", "rutas": [DATASET]})
        self.assertEqual(self.oficina.leer(DATASET), dataset("g1", "g2"))

    def test_escritura_directa_con_punto_de_control_se_recupera(self):
        diario = self.casa_cae({}, directas={DATASET: "g3;3\n"}, control=True)
        with self.oficina.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            self.assertEqual(lease.custodia.recuperar_turno(lease, diario, aplicar=True)["estado"], "RECUPERADO")
        self.assertEqual(self.oficina.leer(DATASET), dataset("g1", "g2", "g3"))

    def test_escritor_masivo_del_dataset_hace_punto_de_control(self):
        from atlas_core.procesamiento_masivo import COLUMNAS, _escribir_filas
        fila = dict.fromkeys(COLUMNAS, "")
        fila.update(archivo="mobile/x/original.jpg", numero_guia="900001")
        self.cloud.avanzar(3)
        with self.casa.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            ruta = self.casa.raiz / "operacion" / "actual" / "otro.csv"
            _escribir_filas(ruta, [fila])
            rel = "operacion/actual/otro.csv"
            self.assertEqual(lease.custodia.pendientes, set())
            self.assertEqual(lease.custodia.contenido[rel], ec.sha256_archivo(ruta))
            self.assertIn(lease.custodia.contenido[rel], self.cloud.objetos)

    # ----------------------------------------------------------- bloqueos
    def test_version_posterior_no_se_sobrescribe(self):
        diario = self.casa_cae({DATASET: dataset("g1", "g2", "g3")})
        self.turno(self.oficina, {DATASET: dataset("g1", "g2", "g4")})
        posterior = self.vigentes()[DATASET]
        self.cloud.avanzar(3)
        with self.oficina.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            r = lease.custodia.recuperar_turno(lease, diario, aplicar=True)
        self.assertEqual(r["estado"], "BLOQUEADO")
        self.assertEqual(r["bloqueos"], [{"codigo": "VERSION_POSTERIOR", "rutas": [DATASET]}])
        self.assertEqual(self.vigentes()[DATASET], posterior)
        self.assertIsNotNone(self.vigentes()[diario])  # sigue disponible para revisión

    def test_perder_documentos_bloquea(self):
        diario = self.casa_cae({DATASET: dataset("g1", "g3")})
        with self.oficina.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            r = lease.custodia.recuperar_turno(lease, diario, aplicar=True)
        self.assertEqual(r["bloqueos"], [{"codigo": "PERDERIA_DOCUMENTOS", "documentos": ["g2"]}])
        self.assertEqual(self.oficina.leer(DATASET), dataset("g1", "g2"))

    def test_documento_duplicado_no_se_aplica(self):
        diario = self.casa_cae({DATASET: dataset("g1", "g2", "g2")})
        with self.oficina.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            with self.assertRaises(ec.EstadoNoVerificado):
                lease.custodia.recuperar_turno(lease, diario, aplicar=True)
        self.assertEqual(self.oficina.leer(DATASET), dataset("g1", "g2"))
        self.assertIsNotNone(self.vigentes()[diario])

    def test_contenido_alterado_en_cloud_no_se_aplica(self):
        nuevo = dataset("g1", "g2", "g3")
        diario = self.casa_cae({DATASET: nuevo})
        self.cloud.objetos[huella(nuevo)] = b"alterado"
        with self.oficina.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            with self.assertRaises(ec.EstadoNoVerificado):
                lease.custodia.recuperar_turno(lease, diario, aplicar=True)
        self.assertEqual(self.oficina.leer(DATASET), dataset("g1", "g2"))
        self.assertIsNotNone(self.vigentes()[diario])

    def test_diario_sin_contenido_formato_1_no_se_recupera(self):
        diario = self.casa_cae({CATALOGO: "cat-2"})
        actual = json.loads(self.cloud.objetos[self.vigentes()[diario]])
        for campo in ("contenido", "pendientes", "cierra", "recuperacion"):
            actual.pop(campo)
        actual["formato"] = 1
        datos = ec.serializar_diario(actual)
        self.cloud.objetos[sha(datos)] = datos
        self.cloud.marca["version"] += 1
        self.cloud.archivos.append((diario, self.cloud.marca["version"], sha(datos)))
        with self.oficina.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            r = lease.custodia.recuperar_turno(lease, diario, aplicar=True)
        self.assertEqual(r["bloqueos"], [{"codigo": "DIARIO_SIN_CONTENIDO", "formato": 1}])

    def test_sin_lease_vigente_no_se_recupera(self):
        diario = self.casa_cae({CATALOGO: "cat-2"})
        lease = self.oficina.lease()
        self.assertTrue(lease.adquirir(), lease.motivo)
        lease.cerrar()
        with self.assertRaises(ec.EstadoNoVerificado):
            lease.custodia.recuperar_turno(lease, diario, aplicar=True)
        self.assertEqual(self.oficina.leer(CATALOGO), "cat-1")

    # ------------------------------------------------------------- cortes
    def test_fallo_a_mitad_deshace_y_no_cierra_el_diario(self):
        diario = self.casa_cae({CATALOGO: "cat-2", DATASET: dataset("g1", "g2", "g3")})
        real = ec.CustodiaEstado._escribir_desde_nube
        llamadas = []

        def falla_segunda(custodia, rel, datos):
            llamadas.append(rel)
            if len(llamadas) == 2:
                raise OSError("disco lleno")
            return real(custodia, rel, datos)

        with self.oficina.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            with patch.object(ec.CustodiaEstado, "_escribir_desde_nube", falla_segunda):
                with self.assertRaises(OSError):
                    lease.custodia.recuperar_turno(lease, diario, aplicar=True)
        self.assertEqual(self.oficina.leer(CATALOGO), "cat-1")
        self.assertEqual(self.oficina.leer(DATASET), dataset("g1", "g2"))
        self.assertEqual(self.vigentes()[CATALOGO], huella("cat-1"))
        self.assertIsNotNone(self.vigentes()[diario])

    def test_recuperador_que_muere_a_mitad_no_deja_recuperacion_parcial(self):
        escrito = {CATALOGO: "cat-2", DATASET: dataset("g1", "g2", "g3")}
        diario = self.casa_cae(escrito)
        # OFICINA empieza a aplicar y se apaga tras la primera ruta.
        lease = self.oficina.lease()
        self.assertTrue(lease.adquirir(), lease.motivo)
        real = ec.CustodiaEstado._escribir_desde_nube

        muerto = []

        def muere_en_la_segunda(custodia, rel, datos):
            # Corte de luz: después no corre nada más (ni el deshacer).
            if muerto or rel == DATASET:
                if not muerto:
                    custodia.detener()
                    lease._soltar_turno()
                muerto.append(rel)
                raise SystemExit("corte de luz")
            return real(custodia, rel, datos)

        with patch.object(ec.CustodiaEstado, "_escribir_desde_nube", muere_en_la_segunda):
            try:
                lease.custodia.recuperar_turno(lease, diario, aplicar=True)
            except SystemExit:
                pass
        diario_oficina = ec.ruta_diario("pc-oficina", lease.epoca)
        # Otro equipo no cierra el diario de CASA por la vía del de OFICINA.
        tercero = Equipo(self.base, "tercero", self.cloud)
        for rel in (DATASET, CATALOGO):
            tercero.escribir(rel, {DATASET: dataset("g1", "g2"), CATALOGO: "cat-1"}[rel])
        self.cloud.avanzar(11)
        with tercero.lease() as otro:
            self.assertTrue(otro.adquirir(), otro.motivo)
            r = otro.custodia.recuperar_turno(otro, diario_oficina)
            self.assertEqual(r["estado"], "BLOQUEADO", r)
            self.assertEqual(r["bloqueos"][0]["codigo"], "RECUPERACION_INTERRUMPIDA")
            self.assertEqual(otro.custodia.recuperar_turno(otro, diario, aplicar=True)["estado"], "RECUPERADO")
            self.assertEqual(otro.custodia.recuperar_turno(otro, diario_oficina, aplicar=True)["estado"], "RECUPERADO")
        for rel, texto in escrito.items():
            self.assertEqual(self.vigentes()[rel], huella(texto))
        self.assertIsNone(self.vigentes()[diario])
        self.assertIsNone(self.vigentes()[diario_oficina])

    def test_mismo_recuperador_vuelve_y_no_confirma_la_mitad(self):
        diario = self.casa_cae({CATALOGO: "cat-2", DATASET: dataset("g1", "g2", "g3")})
        lease = self.oficina.lease()
        self.assertTrue(lease.adquirir(), lease.motivo)
        real = ec.CustodiaEstado._escribir_desde_nube

        muerto = []

        def muere_en_la_segunda(custodia, rel, datos):
            # Corte de luz: después no corre nada más (ni el deshacer).
            if muerto or rel == DATASET:
                if not muerto:
                    custodia.detener()
                    lease._soltar_turno()
                muerto.append(rel)
                raise SystemExit("corte de luz")
            return real(custodia, rel, datos)

        with patch.object(ec.CustodiaEstado, "_escribir_desde_nube", muere_en_la_segunda):
            try:
                lease.custodia.recuperar_turno(lease, diario, aplicar=True)
            except SystemExit:
                pass
        self.assertEqual(self.oficina.leer(CATALOGO), "cat-2")  # media recuperación en disco
        self.cloud.avanzar(3)
        with self.oficina.lease() as vuelta:
            self.assertTrue(vuelta.adquirir(), vuelta.motivo)
            self.assertEqual(self.vigentes()[CATALOGO], huella("cat-1"))  # la mitad no se confirmó
            self.assertIsNotNone(self.vigentes()[diario])
            self.assertEqual(self.oficina.leer(CATALOGO), "cat-1")
            self.assertEqual(vuelta.custodia.recuperar_turno(vuelta, diario, aplicar=True)["estado"], "RECUPERADO")
        self.assertEqual(self.vigentes()[CATALOGO], huella("cat-2"))


if __name__ == "__main__":
    unittest.main()
