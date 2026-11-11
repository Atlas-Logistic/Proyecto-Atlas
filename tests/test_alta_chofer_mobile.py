"""Alta de chofer + credencial Mobile bajo el escritor oficial (datos sintéticos).

La raíz temporal se protege con la guardia real (ATLAS_EXCLUSION_RAICES, modo
exigir); el escritor falso toma un TurnoEscritura real, igual que los
escritores oficiales, salvo cuando la prueba exige lo contrario.
"""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

import alta_chofer_mobile as alta
from atlas_core.exclusion_local import EscrituraSinTurno, TurnoEscritura
from atlas_core.mobile import hash_password, verificar_password

PASSWORD = "clave-sintetica-9"
CHOFERES = {
    "10833150K": {"nombre": "JOSE LAZCANO", "activo": True},
    "180915885": {"nombre": "SALOMÓN PIZARRO", "activo": True, "aliases": ["SALOMON PISARRO"]},
    "PENDIENTE00000001": {"nombre": "FERNANDO ACUÑA", "activo": True},
}


@pytest.fixture
def raiz(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    carpeta = raiz / "catalogos_privados"
    carpeta.mkdir(parents=True)
    local = tmp_path / "local"
    local.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv("ATLAS_OPERACION_CONFIG", raising=False)
    monkeypatch.setenv("ATLAS_EXCLUSION_RAICES", str(raiz))
    monkeypatch.setenv("ATLAS_EXCLUSION_LOCAL", "exigir")
    usuarios = {"schema_version": 1, "usuarios": {
        "jose.lazcano": {"chofer_id": "10833150K", "password_hash": hash_password("otra-clave-1")},
        "salomon.pizarro": {"chofer_id": "180915885", "password_hash": hash_password("otra-clave-2")},
    }}
    # Escritura de preparación con turno real (la guardia ya protege la raíz).
    with TurnoEscritura(raiz) as turno:
        assert turno.vigente
        (carpeta / "choferes.json").write_text(json.dumps(CHOFERES, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (carpeta / "usuarios_mobile.json").write_text(json.dumps(usuarios, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return raiz


def leer(raiz: Path, nombre: str) -> dict:
    return json.loads((raiz / "catalogos_privados" / nombre).read_text(encoding="utf-8"))


def bytes_catalogos(raiz: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in (raiz / "catalogos_privados").iterdir()}


class EscritorFalso:
    """Mismo contrato que LeaseEscritorOperativo/EscritorEquipoUnico."""

    def __init__(self, raiz, *, tomar_turno=True, ocupado=False, motivo="", al_adquirir=None):
        self.raiz, self.tomar_turno, self._ocupado, self.motivo = Path(raiz), tomar_turno, ocupado, motivo
        self.al_adquirir, self.turno, self.lease, self.ocupado = al_adquirir, None, False, False
        self.intentos, self.cerrado = 0, False

    @property
    def vigente(self):
        return self.lease and (self.turno.vigente if self.turno is not None else not self.tomar_turno)

    def adquirir(self):
        self.intentos += 1
        if self._ocupado:
            self.ocupado = True
            return False
        if self.tomar_turno:
            self.turno = TurnoEscritura(self.raiz)
            assert self.turno.adquirir()
        self.lease = True
        if self.al_adquirir:
            self.al_adquirir(self)
        return True

    def cerrar(self):
        self.cerrado, self.lease = True, False
        if self.turno is not None:
            self.turno.soltar()
            self.turno = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cerrar()


def pedir_fijo(*respuestas):
    pendientes = list(respuestas) or [PASSWORD, PASSWORD]
    pedidas = []

    def pedir(prompt):
        pedidas.append(prompt)
        return pendientes.pop(0)
    pedir.pedidas = pedidas
    return pedir


def ejecutar(raiz, *, escritores=None, pedir=None, **datos):
    escritores = [] if escritores is None else escritores
    parametros = {"usuario": "raimundo.pineda", "rut": "11.640.500-8", "nombre": "Raimundo  Pineda", **datos}

    def fabrica(r):
        escritor = EscritorFalso(r)
        escritores.append(escritor)
        return escritor
    return alta.ejecutar(raiz, pedir=pedir or pedir_fijo(), fabrica_escritor=datos.pop("fabrica", None) or fabrica,
                         **{k: v for k, v in parametros.items() if k != "fabrica"})


# --- alta correcta -----------------------------------------------------------

def test_alta_agrega_solo_los_dos_registros_y_conserva_los_demas(raiz):
    choferes_antes, usuarios_antes = leer(raiz, "choferes.json"), leer(raiz, "usuarios_mobile.json")
    escritores = []
    resultado = ejecutar(raiz, escritores=escritores)
    assert resultado["resultado"] == "ALTA_APLICADA"
    assert resultado["chofer_id"] == "116405008" and resultado["nombre"] == "RAIMUNDO PINEDA"
    assert all(resultado["verificacion"].values())
    choferes, usuarios = leer(raiz, "choferes.json"), leer(raiz, "usuarios_mobile.json")
    assert choferes == {**choferes_antes, "116405008": {"nombre": "RAIMUNDO PINEDA", "activo": True}}
    assert {k: v for k, v in usuarios["usuarios"].items() if k != "raimundo.pineda"} == usuarios_antes["usuarios"]
    assert usuarios["schema_version"] == 1
    cuenta = usuarios["usuarios"]["raimundo.pineda"]
    assert set(cuenta) == {"chofer_id", "password_hash"} and cuenta["chofer_id"] == "116405008"
    assert cuenta["password_hash"].startswith("pbkdf2_sha256$200000$") and verificar_password(PASSWORD, cuenta["password_hash"])
    assert escritores[0].cerrado and escritores[0].turno is None  # turno soltado al cerrar


def test_contrasena_nunca_en_salida_ni_en_archivos(raiz, monkeypatch):
    monkeypatch.setattr(alta.ejecutar, "__kwdefaults__", {**alta.ejecutar.__kwdefaults__,
                                                          "pedir": pedir_fijo(), "fabrica_escritor": lambda r: EscritorFalso(r)})
    salida = io.StringIO()
    with redirect_stdout(salida):
        codigo = alta.main(["--raiz-atlas", str(raiz), "--usuario", "raimundo.pineda", "--rut", "11640500-8",
                            "--nombre", "RAIMUNDO PINEDA"])
    texto = salida.getvalue()
    assert codigo == alta.SALIDA_OK and json.loads(texto)["resultado"] == "ALTA_APLICADA"
    assert PASSWORD not in texto and "pbkdf2" not in texto
    for contenido in bytes_catalogos(raiz).values():
        assert PASSWORD.encode() not in contenido


def test_cli_no_acepta_contrasena_por_argumento(raiz):
    with pytest.raises(SystemExit):
        alta.main(["--raiz-atlas", str(raiz), "--usuario", "x.y", "--rut", "11640500-8", "--nombre", "A B",
                   "--password", PASSWORD])


def test_solo_validar_no_pide_contrasena_ni_toma_escritor_ni_escribe(raiz):
    antes, pedir, escritores = bytes_catalogos(raiz), pedir_fijo(), []
    resultado = ejecutar(raiz, escritores=escritores, pedir=pedir, solo_validar=True)
    assert resultado["resultado"] == "VALIDO_SIN_ESCRIBIR"
    assert pedir.pedidas == [] and escritores == [] and bytes_catalogos(raiz) == antes


# --- protecciones de escritura -------------------------------------------------

def test_sin_turno_la_guardia_rechaza_y_no_cambia_nada(raiz):
    antes = bytes_catalogos(raiz)
    with pytest.raises(EscrituraSinTurno):
        ejecutar(raiz, fabrica=lambda r: EscritorFalso(r, tomar_turno=False))
    assert bytes_catalogos(raiz) == antes


def test_escritor_ocupado_espera_acotada_y_no_escribe(raiz):
    antes, reloj, esperas = bytes_catalogos(raiz), [0.0], []
    escritor = EscritorFalso(raiz, ocupado=True)

    def adquirir(e):
        return alta.adquirir_con_espera(e, espera=12, intervalo=5, reloj=lambda: reloj[0],
                                        dormir=lambda s: (esperas.append(s), reloj.__setitem__(0, reloj[0] + s)))
    with pytest.raises(alta.ErrorAlta) as error:
        alta.ejecutar(raiz, usuario="raimundo.pineda", rut="11640500-8", nombre="RAIMUNDO PINEDA",
                      pedir=pedir_fijo(), fabrica_escritor=lambda r: escritor, adquirir=adquirir)
    assert error.value.salida == alta.SALIDA_OCUPADO
    assert escritor.intentos == 4 and esperas == [5, 5, 5] and escritor.cerrado
    assert bytes_catalogos(raiz) == antes


def test_estado_no_verificado_no_se_reintenta(raiz):
    escritor = EscritorFalso(raiz, ocupado=False)
    escritor.adquirir = lambda: (setattr(escritor, "motivo", "ESTADO_NO_VERIFICADO"), False)[1]
    with pytest.raises(alta.ErrorAlta) as error:
        alta.ejecutar(raiz, usuario="raimundo.pineda", rut="11640500-8", nombre="RAIMUNDO PINEDA",
                      pedir=pedir_fijo(), fabrica_escritor=lambda r: escritor)
    assert error.value.codigo == "ESTADO_NO_VERIFICADO" and error.value.salida == alta.SALIDA_SIN_ESCRITOR


def test_sin_escritor_configurado_no_escribe(raiz):
    antes = bytes_catalogos(raiz)
    with pytest.raises(alta.ErrorAlta) as error:
        ejecutar(raiz, fabrica=lambda r: None)
    assert error.value.codigo == "SIN_ESCRITOR_CONFIGURADO" and bytes_catalogos(raiz) == antes


def test_duplicado_aparecido_al_alinear_se_rechaza_bajo_el_escritor(raiz):
    def aparece(escritor):
        ruta = raiz / "catalogos_privados" / "choferes.json"
        ruta.write_text(json.dumps({**CHOFERES, "116405008": {"nombre": "OTRO", "activo": True}}), encoding="utf-8")
    with pytest.raises(alta.ErrorAlta) as error:
        ejecutar(raiz, fabrica=lambda r: EscritorFalso(r, al_adquirir=aparece))
    assert error.value.codigo == "RUT_DUPLICADO"
    assert leer(raiz, "choferes.json")["116405008"]["nombre"] == "OTRO"
    assert "raimundo.pineda" not in leer(raiz, "usuarios_mobile.json")["usuarios"]


def test_fallo_al_guardar_credencial_retira_el_chofer(raiz, monkeypatch):
    antes = leer(raiz, "choferes.json")
    original = alta.escribir_json_atomico

    def fallar_en_usuarios(ruta, contenido):
        if Path(ruta).name == "usuarios_mobile.json":
            raise OSError("disco lleno simulado")
        return original(ruta, contenido)
    monkeypatch.setattr(alta, "escribir_json_atomico", fallar_en_usuarios)
    with pytest.raises(OSError):
        ejecutar(raiz)
    assert leer(raiz, "choferes.json") == antes


# --- validaciones y duplicados (nunca piden contraseña ni toman escritor) ------

@pytest.mark.parametrize("datos, codigo", [
    ({"rut": "11.640.500-9"}, "RUT_INVALIDO"),
    ({"rut": "116405009"}, "RUT_INVALIDO"),
    ({"rut": ""}, "RUT_INVALIDO"),
    ({"usuario": "Raimundo Pineda"}, "USUARIO_INVALIDO"),
    ({"usuario": "raimundo.pineda'; --"}, "USUARIO_INVALIDO"),
    ({"nombre": "RAIMUNDO"}, "NOMBRE_INVALIDO"),
    ({"nombre": "RAIMUNDO P1NEDA"}, "NOMBRE_INVALIDO"),
    ({"rut": "10.833.150-k"}, "RUT_DUPLICADO"),
    ({"nombre": "salomon pizarro"}, "NOMBRE_DUPLICADO"),
    ({"nombre": "Salomon Pisarro"}, "NOMBRE_DUPLICADO"),
    ({"nombre": "FERNANDO ACUNA"}, "NOMBRE_DUPLICADO"),
    ({"usuario": "jose.lazcano"}, "USUARIO_DUPLICADO"),
    ({"usuario": "Jose.Lazcano"}, "USUARIO_INVALIDO"),
    ({"empresa": "otra-empresa"}, "EMPRESA_NO_SOPORTADA"),
])
def test_validaciones_y_duplicados(raiz, datos, codigo):
    antes, pedir, escritores = bytes_catalogos(raiz), pedir_fijo(), []
    with pytest.raises(alta.ErrorAlta) as error:
        ejecutar(raiz, escritores=escritores, pedir=pedir, **datos)
    assert error.value.codigo == codigo and error.value.salida == alta.SALIDA_DATOS
    assert pedir.pedidas == [] and escritores == [] and bytes_catalogos(raiz) == antes


def test_rut_con_cuenta_mobile_sin_catalogo_es_duplicado(raiz):
    with TurnoEscritura(raiz):
        ruta = raiz / "catalogos_privados" / "usuarios_mobile.json"
        usuarios = json.loads(ruta.read_text(encoding="utf-8"))
        usuarios["usuarios"]["huerfana"] = {"chofer_id": "11.640.500-8", "password_hash": "x"}
        ruta.write_text(json.dumps(usuarios), encoding="utf-8")
    with pytest.raises(alta.ErrorAlta) as error:
        ejecutar(raiz)
    assert error.value.codigo == "CUENTA_DUPLICADA"


def test_raiz_de_otra_empresa_rechazada(tmp_path):
    with pytest.raises(alta.ErrorAlta) as error:
        alta.ejecutar(tmp_path / alta.CARPETA_EMPRESAS / "otra", usuario="a.b", rut="11640500-8", nombre="A B",
                      solo_validar=True)
    assert error.value.codigo == "EMPRESA_NO_SOPORTADA"


@pytest.mark.parametrize("respuestas, codigo", [
    (("corta1", "corta1"), "PASSWORD_INVALIDA"),
    ((" " + PASSWORD, " " + PASSWORD), "PASSWORD_INVALIDA"),
    (("raimundo.pineda", "raimundo.pineda"), "PASSWORD_INVALIDA"),
    ((PASSWORD, PASSWORD + "x"), "PASSWORD_NO_COINCIDE"),
])
def test_contrasena_invalida_no_toma_escritor(raiz, respuestas, codigo):
    antes, escritores = bytes_catalogos(raiz), []
    with pytest.raises(alta.ErrorAlta) as error:
        ejecutar(raiz, escritores=escritores, pedir=pedir_fijo(*respuestas))
    assert error.value.codigo == codigo and escritores == [] and bytes_catalogos(raiz) == antes
    assert PASSWORD not in error.value.detalle


def test_segunda_alta_del_mismo_chofer_se_rechaza(raiz):
    ejecutar(raiz)
    with pytest.raises(alta.ErrorAlta) as error:
        ejecutar(raiz, usuario="raimundo.pineda2")
    assert error.value.codigo == "RUT_DUPLICADO"


def test_procedimiento_interactivo_no_pasa_contrasena_por_argumento():
    repo = Path(alta.__file__).parent
    ps1 = (repo / "alta_chofer_mobile.ps1").read_text(encoding="ascii")  # ASCII: PowerShell 5.1 sin BOM
    assert "--password" not in ps1 and "-Password" not in ps1
    assert "Read-Host -AsSecureString" in ps1 and "ZeroFreeBSTR" in ps1
    assert "--empresa-id $empresaCloud" in ps1 and f"'{alta.CLOUD_MBT}'" in ps1
    assert "Enable-ScheduledTask" in ps1.split("} finally {")[1]  # PULL se reactiva siempre
    cmd = (repo / "alta_chofer_mobile.cmd").read_bytes()
    assert b"alta_chofer_mobile.ps1" in cmd and b"\r\n" in cmd
