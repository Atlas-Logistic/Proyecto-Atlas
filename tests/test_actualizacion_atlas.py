"""P0.5: actualización automática de Motor y Desktop con vuelta atrás.

Motor = repositorio git real de prueba (origin bare + instalación clonada);
Desktop = carpeta resources con un app.asar sintético válido; Cloud = una
custodia mínima en memoria (manifiesto + objetos por huella). La salud del
Motor nuevo se sustituye donde la prueba lo indica (el Motor de prueba no
es Atlas); la integración real está en scripts/validacion_diario_remoto.
"""
from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas_core import actualizacion_atlas as aa
from atlas_core import estado_confirmado as ec
from tests.test_estado_confirmado import CloudFalsa, Equipo


def asar(contenido: dict[str, bytes]) -> bytes:
    """app.asar mínimo válido (cabecera pickle + índice JSON + datos)."""
    archivos, offset, datos = {}, 0, b""
    for nombre, cuerpo in contenido.items():
        archivos[nombre] = {"size": len(cuerpo), "offset": str(offset)}
        offset += len(cuerpo)
        datos += cuerpo
    indice = json.dumps({"files": archivos}).encode()
    relleno = indice + b"\0" * (-len(indice) % 4)
    payload = 4 + len(relleno)
    return struct.pack("<4I", 4, payload + 4, payload, len(indice)) + relleno + datos


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", "-c", "user.name=prueba", "-c", "user.email=prueba@example.invalid", *args], cwd=cwd,
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


class Cliente:
    def __init__(self):
        self.archivos: dict[str, str] = {}
        self.objetos: dict[str, bytes] = {}

    def manifiesto(self):
        return {"version": 1, "archivos": [[r, s, 1] for r, s in self.archivos.items()]}

    def descargar(self, sha):
        return self.objetos[sha]

    def publicar(self, version, commit, *, paquete=None, nivel=1, rama="rel"):
        desktop = None
        if paquete is not None:
            desktop = {"paquete_sha256": hashlib.sha256(paquete).hexdigest(), "bytes": len(paquete)}
            self.objetos[desktop["paquete_sha256"]] = paquete
        d = aa.validar_descriptor({"tipo": aa.TIPO_DESCRIPTOR, "formato": 1, "version": version,
                                   "nivel_custodia_minimo": nivel, "motor": {"rama": rama, "commit": commit},
                                   "desktop": desktop})
        datos = aa._serializar(d)
        self.objetos[hashlib.sha256(datos).hexdigest()] = datos
        self.archivos[aa.RUTA_DESCRIPTOR] = hashlib.sha256(datos).hexdigest()


class Actualizacion(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        origen, taller = base / "origin.git", base / "taller"
        git(base, "init", "--bare", "-q", str(origen))
        git(base, "init", "-q", "-b", "rel", str(taller))
        (taller / "version.txt").write_text("1", encoding="utf-8")
        git(taller, "add", "-A")
        git(taller, "commit", "-q", "-m", "v1")
        self.c1 = git(taller, "rev-parse", "HEAD")
        (taller / "version.txt").write_text("2", encoding="utf-8")
        git(taller, "commit", "-q", "-am", "v2")
        self.c2 = git(taller, "rev-parse", "HEAD")
        git(taller, "remote", "add", "origin", str(origen))
        git(taller, "push", "-q", "origin", "rel")
        (taller / "version.txt").write_text("sin publicar", encoding="utf-8")
        git(taller, "commit", "-q", "-am", "local")
        self.no_publicado = git(taller, "rev-parse", "HEAD")
        self.motor = base / "motor"
        git(base, "clone", "-q", str(origen), str(self.motor))
        git(self.motor, "reset", "-q", "--hard", self.c1)
        git(self.motor, "fetch", "-q", str(taller), "rel")  # el commit local existe pero no en origin
        self.recursos = base / "resources"
        (self.recursos / "app.asar.unpacked" / "src").mkdir(parents=True)
        (self.recursos / "app.asar").write_bytes(asar({"main.js": b"v1"}))
        (self.recursos / "app.asar.unpacked" / "src" / "consulta_python.py").write_text("v1", encoding="utf-8")
        nuevos = base / "nuevos"
        (nuevos / "app.asar.unpacked" / "src").mkdir(parents=True)
        (nuevos / "app.asar").write_bytes(asar({"main.js": b"v2", "otro.js": b"x"}))
        (nuevos / "app.asar.unpacked" / "src" / "consulta_python.py").write_text("v2", encoding="utf-8")
        self.paquete = aa.empaquetar_desktop(nuevos)
        self.asar_v1 = hashlib.sha256((self.recursos / "app.asar").read_bytes()).hexdigest()
        self.asar_v2 = hashlib.sha256((nuevos / "app.asar").read_bytes()).hexdigest()
        self.cliente = Cliente()
        self.estado = base / "estado"
        self._salud = patch.object(aa.Actualizador, "_salud", return_value={"motor_nivel": 1})
        self._salud.start()

    def tearDown(self):
        self._salud.stop()
        self._tmp.cleanup()

    def actualizador(self) -> aa.Actualizador:
        return aa.Actualizador(motor=self.motor, recursos=self.recursos, estado=self.estado, cliente=self.cliente,
                               proceso_desktop="")

    def instalado(self) -> tuple[str, str, str]:
        return (aa.commit_actual(self.motor),
                hashlib.sha256((self.recursos / "app.asar").read_bytes()).hexdigest(),
                (self.recursos / "app.asar.unpacked" / "src" / "consulta_python.py").read_text(encoding="utf-8"))

    # ------------------------------------------------------------ básicos
    def test_asar_y_paquete(self):
        self.assertEqual(aa.verificar_asar(self.recursos / "app.asar"), 1)
        (self.recursos / "malo.asar").write_bytes(b"no es asar")
        with self.assertRaises(aa.ErrorActualizacion):
            aa.verificar_asar(self.recursos / "malo.asar")
        self.assertEqual(aa.empaquetar_desktop(self.recursos), aa.empaquetar_desktop(self.recursos))  # reproducible
        import io
        import zipfile
        malo = io.BytesIO()
        with zipfile.ZipFile(malo, "w") as zf:
            zf.writestr("app.asar", asar({"a": b"1"}))
            zf.writestr("../fuera.txt", "x")
        with self.assertRaises(aa.ErrorActualizacion):
            aa._extraer_paquete(malo.getvalue(), Path(self._tmp.name) / "x")

    def test_sin_version_publicada_o_al_dia(self):
        self.assertEqual(self.actualizador().actualizar()["estado"], "SIN_VERSION_PUBLICADA")
        self.cliente.publicar("v1", self.c1)
        self.assertEqual(aa.Actualizador(motor=self.motor, recursos=None, estado=self.estado, cliente=self.cliente)
                         .actualizar()["estado"], "AL_DIA")

    # ----------------------------------------------------------- actualizar
    def test_actualiza_motor_y_desktop_con_respaldo(self):
        self.cliente.publicar("v2", self.c2, paquete=self.paquete)
        r = self.actualizador().actualizar()
        self.assertEqual(r["estado"], "ACTUALIZADA", r)
        self.assertEqual(self.instalado(), (self.c2, self.asar_v2, "v2"))
        self.assertEqual(hashlib.sha256((self.recursos / "app.asar.antes-v2").read_bytes()).hexdigest(), self.asar_v1)
        self.assertFalse((self.estado / "actualizacion_en_curso.json").exists())
        self.assertEqual(self.actualizador().actualizar()["estado"], "AL_DIA")
        self.assertEqual([p.name for p in self.recursos.iterdir() if p.name.startswith(".atlas_actualizar")], [])

    def test_salud_fallida_vuelve_atras_y_no_reintenta_sin_fin(self):
        self.cliente.publicar("v2", self.c2, paquete=self.paquete)
        with patch.object(aa.Actualizador, "_salud", side_effect=aa.ErrorActualizacion("Motor nuevo no arranca")):
            for intento in range(aa.MAX_INTENTOS):
                r = self.actualizador().actualizar()
                self.assertEqual(r["estado"], "REVERTIDA", r)
                self.assertEqual(self.instalado(), (self.c1, self.asar_v1, "v1"))
            self.assertEqual(self.actualizador().actualizar()["estado"], "VERSION_FALLIDA_OMITIDA")
        self.assertEqual(self.instalado(), (self.c1, self.asar_v1, "v1"))
        # Otra versión publicada sí se intenta.
        self.cliente.publicar("v2b", self.c2, paquete=self.paquete)
        self.assertEqual(self.actualizador().actualizar()["estado"], "ACTUALIZADA")

    def test_corte_a_mitad_se_revierte_y_completa_en_el_siguiente_inicio(self):
        self.cliente.publicar("v2", self.c2, paquete=self.paquete)
        for fase in ("respaldo", "motor", "desktop"):
            with self.subTest(fase=fase):
                git(self.motor, "reset", "-q", "--keep", self.c1)
                (self.estado / "version_instalada.json").unlink(missing_ok=True)
                (self.estado / "versiones_fallidas.json").unlink(missing_ok=True)
                (self.recursos / "app.asar").write_bytes(asar({"main.js": b"v1"}))

                def corte(_self, f, fase=fase):
                    if f == fase:
                        raise SystemExit("corte de energía")  # sin finally útil: como un apagado

                with patch.object(aa.Actualizador, "_corte", corte):
                    with self.assertRaises(SystemExit):
                        self.actualizador().actualizar()
                self.assertTrue((self.estado / "actualizacion_en_curso.json").exists())
                r = self.actualizador().actualizar()
                self.assertEqual(r["recuperacion"]["estado"], "REVERTIDA_TRAS_CORTE", r)
                self.assertEqual(r["recuperacion"]["reversion"]["motor"], self.c1)
                self.assertEqual(r["recuperacion"]["reversion"]["desktop_asar_sha256"], self.asar_v1)
                self.assertEqual(r["estado"], "ACTUALIZADA", r)
                self.assertEqual(self.instalado(), (self.c2, self.asar_v2, "v2"))

    def test_nada_se_toca_si_algo_no_se_verifica(self):
        casos = {
            "commit no publicado": lambda: self.cliente.publicar("v3", self.no_publicado, paquete=self.paquete),
            "paquete alterado": lambda: (self.cliente.publicar("v4", self.c2, paquete=self.paquete),
                                         self.cliente.objetos.__setitem__(hashlib.sha256(self.paquete).hexdigest(), b"x")),
        }
        for nombre, preparar in casos.items():
            with self.subTest(nombre):
                preparar()
                r = self.actualizador().actualizar()
                self.assertEqual(r["estado"], "NO_APLICADA", r)
                self.assertEqual(self.instalado(), (self.c1, self.asar_v1, "v1"))
                self.assertFalse((self.estado / "actualizacion_en_curso.json").exists())

    def test_desktop_abierto_o_motor_con_cambios_no_se_actualiza(self):
        self.cliente.publicar("v2", self.c2, paquete=self.paquete)
        with patch.object(aa.Actualizador, "_desktop_en_uso", return_value=True):
            self.assertEqual(self.actualizador().actualizar()["estado"], "NO_APLICADA")
        (self.motor / "version.txt").write_text("cambio local", encoding="utf-8")
        r = self.actualizador().actualizar()
        self.assertEqual(r["estado"], "NO_APLICADA")
        self.assertIn("cambios sin commit", r["detalle"])
        self.assertEqual(aa.commit_actual(self.motor), self.c1)


class CompuertaDeVersion(unittest.TestCase):
    """Un Motor bajo el nivel publicado no escribe (Cloud simulada real)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cloud = CloudFalsa()
        self.casa = Equipo(Path(self._tmp.name), "casa", self.cloud)
        self._parches = [patch("atlas_core.escritor_operativo._json", side_effect=self.cloud.json),
                         patch.object(ec.ClienteEstado, "_crudo", lambda c, h, **kw: self.cloud.crudo(c, h, **kw)),
                         patch.object(aa, "verificar_commit_publicado", return_value=None)]
        for p in self._parches:
            p.start()

    def tearDown(self):
        for p in self._parches:
            p.stop()
        ec._activas.clear()
        self._tmp.cleanup()

    def publicar(self, version: str, nivel: int):
        with self.casa.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            return aa.publicar_version(lease, version=version, rama="rel", commit="a" * 40, motor=Path("."),
                                       paquete_desktop=None, nivel_minimo=nivel)

    def test_motor_bajo_el_nivel_publicado_no_obtiene_turno_de_escritura(self):
        self.publicar("v1", 1)
        self.cloud.avanzar(3)
        with patch.object(aa, "NIVEL_CUSTODIA", 2):
            self.publicar("v2", 2)
        self.cloud.avanzar(3)
        version = self.cloud.marca["version"]
        lease = self.casa.lease()
        self.assertFalse(lease.adquirir())
        self.assertEqual(lease.motivo, "MOTOR_INCOMPATIBLE")
        self.assertEqual(self.cloud.marca["version"], version)

    def test_publicacion_no_baja_el_nivel_ni_repite_version_ni_excede_el_propio(self):
        with self.assertRaises(aa.ErrorActualizacion):
            self.publicar("v4", 3)  # este Motor es nivel 1
        self.cloud.avanzar(3)
        with patch.object(aa, "NIVEL_CUSTODIA", 2):
            self.publicar("v2", 2)
            self.cloud.avanzar(3)
            for version, nivel in (("v3", 1), ("v2", 2)):
                with self.assertRaises(aa.ErrorActualizacion):
                    self.publicar(version, nivel)
                self.cloud.avanzar(3)

    def test_cliente_con_protocolo_anterior_queda_fuera_cuando_el_worker_lo_exige(self):
        self.cloud.marca["protocolo_minimo"] = ec.PROTOCOLO
        with patch.object(ec, "PROTOCOLO", 2):
            antiguo = self.casa.lease()
            self.assertFalse(antiguo.adquirir())
            self.assertEqual(antiguo.motivo, "ESCRITOR_PROTOCOLO_OBSOLETO")
        actual = self.casa.lease()
        self.assertTrue(actual.adquirir(), actual.motivo)
        actual.cerrar()


if __name__ == "__main__":
    unittest.main()
