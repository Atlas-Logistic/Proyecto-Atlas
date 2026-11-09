"""La custodia detecta por contenido, aunque tamaño y fecha coincidan.

Cloud simulada con la semántica del Worker (la de test_estado_confirmado). La
fecha se fija con os.utime: el resultado no depende del reloj de Windows."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas_core import estado_confirmado as ec
from tests.test_estado_confirmado import CATALOGO, CloudFalsa, Equipo

V1, V2 = '{"chofer": "AAAA"}', '{"chofer": "BBBB"}'
FECHA = 1_780_000_000_000_000_000


def sellar(equipo: Equipo, rel: str, texto: str) -> None:
    """Escribe y deja exactamente el mismo instante de modificación."""
    equipo.escribir(rel, texto)
    os.utime(equipo.archivo(rel), ns=(FECHA, FECHA))


class Deteccion(unittest.TestCase):
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

    def turno(self, equipo, accion=None):
        with equipo.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            if accion:
                accion()
        return lease

    def contenido_cloud(self, rel=CATALOGO) -> str:
        return self.cloud.objetos[self.cloud._vigentes()[rel][0]].decode("utf-8")

    def version(self) -> int:
        return self.cloud.marca["version"]

    def base_confirmada(self):
        self.turno(self.casa, lambda: sellar(self.casa, CATALOGO, V1))
        self.assertEqual(self.contenido_cloud(), V1)
        self.turno(self.casa)  # alinea: una caché por tamaño y fecha quedaría poblada

    # ----------------------------------------------------- modificación
    def test_cambio_con_igual_tamano_y_fecha_se_publica(self):
        self.base_confirmada()
        self.assertEqual(len(V1), len(V2))
        self.turno(self.casa, lambda: sellar(self.casa, CATALOGO, V2))
        self.assertEqual(self.contenido_cloud(), V2)

    def test_cambio_en_escrituras_consecutivas_sin_sellar(self):
        """El caso real: dentro del mismo tic del reloj de Windows."""
        self.base_confirmada()
        for i in range(30):
            texto = '{"chofer": "%04d"}' % i
            self.turno(self.casa, lambda: self.casa.escribir(CATALOGO, texto))
            self.assertEqual(self.contenido_cloud(), texto)

    def test_dos_escrituras_en_el_mismo_turno_publican_la_ultima(self):
        self.base_confirmada()
        def accion():
            sellar(self.casa, CATALOGO, V2)
            sellar(self.casa, CATALOGO, '{"chofer": "CCCC"}')
        self.turno(self.casa, accion)
        self.assertEqual(self.contenido_cloud(), '{"chofer": "CCCC"}')

    # ------------------------------------------------- sin redundancias
    def test_reescribir_igual_contenido_no_publica(self):
        self.base_confirmada()
        version, objetos = self.version(), len(self.cloud.objetos)
        self.turno(self.casa, lambda: self.casa.escribir(CATALOGO, V1))
        self.assertEqual((self.version(), len(self.cloud.objetos)), (version, objetos))

    def test_turnos_sin_cambios_no_publican(self):
        self.base_confirmada()
        version = self.version()
        for _ in range(3):
            self.turno(self.casa)
        self.assertEqual(self.version(), version)

    def test_tocar_solo_la_fecha_no_publica_ni_restaura(self):
        self.base_confirmada()
        version = self.version()
        os.utime(self.casa.archivo(CATALOGO), ns=(FECHA + 10**12, FECHA + 10**12))
        lease = self.turno(self.casa)
        self.assertEqual(self.version(), version)
        self.assertEqual(lease.custodia.resumen["restaurados"], [])

    # --------------------------------------------------- sincronización
    def test_alineacion_detecta_alteracion_fuera_de_protocolo(self):
        self.base_confirmada()
        sellar(self.casa, CATALOGO, V2)  # sin turno: Cloud sigue siendo la verdad
        lease = self.turno(self.casa)
        self.assertEqual(lease.custodia.resumen["restaurados"], [CATALOGO])
        self.assertEqual(lease.custodia.resumen["cuarentena"], [CATALOGO])
        self.assertEqual(self.casa.leer(CATALOGO), V1)
        copias = list((self.casa.local / "cuarentena").rglob("vehiculos.json"))
        self.assertEqual([c.read_text(encoding="utf-8") for c in copias], [V2])

    def test_relevo_recibe_el_cambio_de_igual_tamano_y_fecha(self):
        self.base_confirmada()
        self.cloud.avanzar(11)
        self.turno(self.oficina)
        self.assertEqual(self.oficina.leer(CATALOGO), V1)
        self.cloud.avanzar(11)
        self.turno(self.casa, lambda: sellar(self.casa, CATALOGO, V2))
        self.cloud.avanzar(11)
        os.utime(self.oficina.archivo(CATALOGO), ns=(FECHA, FECHA))
        self.turno(self.oficina)
        self.assertEqual(self.oficina.leer(CATALOGO), V2)

    def test_copia_atrasada_con_igual_tamano_y_fecha_se_actualiza(self):
        self.base_confirmada()
        self.cloud.avanzar(11)
        self.turno(self.oficina, lambda: sellar(self.oficina, CATALOGO, V2))
        self.cloud.avanzar(11)
        os.utime(self.casa.archivo(CATALOGO), ns=(FECHA, FECHA))
        self.turno(self.casa)
        self.assertEqual(self.casa.leer(CATALOGO), V2)

    # ------------------------------------------------------ recuperación
    def test_turno_caido_recupera_el_cambio_de_igual_tamano_y_fecha(self):
        self.base_confirmada()
        lease = self.casa.lease()
        self.assertTrue(lease.adquirir(), lease.motivo)
        sellar(self.casa, CATALOGO, V2)
        # Corte de luz: sin confirmar y sin liberar.
        lease.custodia.detener()
        lease._soltar_turno()
        self.cloud.avanzar(3)
        self.turno(self.casa)
        self.assertEqual(self.contenido_cloud(), V2)
        self.assertEqual(self.casa.leer(CATALOGO), V2)

    def test_equipo_nuevo_recupera_el_ultimo_contenido(self):
        self.base_confirmada()
        self.turno(self.casa, lambda: sellar(self.casa, CATALOGO, V2))
        self.cloud.avanzar(11)
        self.turno(self.oficina)
        self.assertEqual(self.oficina.leer(CATALOGO), V2)

    def test_archivo_borrado_se_recupera_aunque_hubiera_datos_previos(self):
        self.base_confirmada()
        self.casa.archivo(CATALOGO).unlink()
        self.turno(self.casa)
        self.assertEqual(self.casa.leer(CATALOGO), V1)

    # ------------------------------------------------- compatibilidad
    def test_una_cache_antigua_no_oculta_un_cambio(self):
        """Actualización desde la versión anterior: huellas.json ya existente."""
        self.base_confirmada()
        sellar(self.casa, CATALOGO, V2)
        estado = self.casa.archivo(CATALOGO).stat()
        self.casa.local.mkdir(parents=True, exist_ok=True)
        manifiesto = self.cloud._vigentes()[CATALOGO][0]
        (self.casa.local / "huellas.json").write_text(json.dumps({CATALOGO: [estado.st_size, estado.st_mtime_ns, manifiesto]}), encoding="utf-8")
        lease = self.turno(self.casa)
        self.assertEqual(lease.custodia.resumen["restaurados"], [CATALOGO])

    def test_protocolo_sin_cambios_en_lo_que_se_envia(self):
        """Mismos endpoints y forma de confirmación que usa el Worker."""
        self.base_confirmada()
        llamadas = []
        real = self.cloud.json
        def espia(base, ruta, token, **kw):
            llamadas.append(ruta)
            return real(base, ruta, token, **kw)
        with patch("atlas_core.escritor_operativo._json", side_effect=espia):
            self.turno(self.casa, lambda: sellar(self.casa, CATALOGO, V2))
        self.assertTrue(set(llamadas) <= {"/api/motor/escritor/estado", "/api/motor/escritor/adquirir", "/api/motor/escritor/renovar",
                                          "/api/motor/escritor/liberar", "/api/motor/estado/manifiesto", "/api/motor/estado/conocidos",
                                          "/api/motor/estado/faltantes", "/api/motor/estado/confirmar"}, llamadas)
        fila = self.cloud.archivos[-1]
        self.assertEqual((fila[0], len(fila[2])), (CATALOGO, 64))


if __name__ == "__main__":
    unittest.main()
