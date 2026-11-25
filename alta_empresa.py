"""Alta integral de una empresa nueva en Atlas: procedimiento único, seguro e idempotente.

    python alta_empresa.py --plan empresa.json --raiz-mbt "G:\\Mi unidad\\Atlas" --revisar
    python alta_empresa.py --plan empresa.json --raiz-mbt "G:\\Mi unidad\\Atlas"

``empresa.json`` (sin secretos)::

    {"version": 1, "empresa_id": "transportes-andes", "nombre": "Transportes Andes",
     "cloud_id": "cloud-transportes-andes",
     "catalogos_iniciales": "C:\\\\ruta\\\\opcional",   (choferes.json, vehiculos.json, ...)
     "choferes_mobile": [{"usuario": "luis.reyes", "rut": "12.345.678-5", "nombre": "LUIS REYES"}]}

Pasos, en orden y con los mecanismos existentes (ver docs/ALTA_EMPRESA.md):

  1. registro     marca de la empresa (aislamiento_empresas.inicializar_empresa)
  2. estructura   carpetas y catálogos base/iniciales que falten (turno local)
  3. credencial   token Motor propio ATLAS_CLOUD_MOTOR_TOKEN__<ID> (perfil Windows);
                  deja el fragmento de CLOUD_MOTOR_TOKENS_JSON para el Worker
  4. pull         desktop_operacion.json + (opcional) autorización y tarea PULL de la empresa
  5. cloud        ¿el Worker reconoce el token? Si no: PENDIENTE (secreto del Worker, paso humano)
  6. custodia     línea base Cloud (estado_confirmado --sembrar) bajo el lease de la empresa
  7. mobile       por chofer: alta_chofer_mobile.py + migrar_usuario_mobile_cloud.py (D1) + login
  8. verificar    marca visible para Desktop, catálogos, custodia sin diferencias

Cada paso comprueba el estado real antes de escribir y nunca reemplaza lo
existente: repetir el procedimiento completa lo que falte y no cambia lo hecho.
Este archivo NO importa atlas_core: cada paso corre en un proceso con el
entorno de la empresa (como Desktop y el PULL), con su guarda de aislamiento.
Nunca toca MBT ni otra empresa.

Salida: 0 alta completa, 3 alta pendiente de un paso humano (p. ej. secreto del
Worker), 2 error (lo hecho queda; se puede repetir tras corregir).
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

MOTOR = Path(__file__).resolve().parent
CARPETA_EMPRESAS = "Atlas_empresas"
RUTA_MARCA = ("catalogos_privados", "empresa_identidad.json")
PATRON_ID = re.compile(r"^[a-z][a-z0-9-]{1,38}[a-z0-9]$")
# Variables del entorno padre que un paso de la empresa puede heredar (el resto
# de ATLAS_* es de MBT u otra empresa y nunca pasa).
# ATLAS_SESION: con la identidad exigida, el alta de choferes requiere la sesión
# de un administrador de la empresa (docs/IDENTIDAD_PERMISOS.md).
HEREDABLES = ("ATLAS_CLOUD_MOBILE_URL", "ATLAS_EXCLUSION_LOCAL", "ATLAS_EXCLUSION_RAICES", "ATLAS_SESION")
SALIDA_OK, SALIDA_ERROR, SALIDA_PENDIENTE = 0, 2, 3
ESTADOS_LISTOS = ("HECHO", "YA_ESTABA")


class Detener(Exception):
    pass


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sufijo(empresa_id: str) -> str:
    return empresa_id.upper().replace("-", "_")


# --------------------------------------------------------------- credencial
class AlmacenCredencial:
    """Dónde vive el token Motor de la empresa: perfil Windows (HKCU\\Environment,
    igual que registrar_credencial.py y lo que lee Desktop/PULL) o, sólo para
    pruebas sintéticas, un archivo JSON local."""

    def __init__(self, especificacion: str, raiz_mbt: Path) -> None:
        self.archivo = None
        if especificacion.startswith("archivo:"):
            self.archivo = Path(especificacion[len("archivo:"):]).resolve()
            drive = raiz_mbt.resolve().parent
            if self.archivo.is_relative_to(drive):
                raise SystemExit("El almacén de credenciales no puede estar junto a las raíces sincronizadas.")
        elif especificacion != "registro":
            raise SystemExit("--credenciales: 'registro' o 'archivo:<ruta>'")

    def leer(self, variable: str) -> str:
        if self.archivo is not None:
            datos = json.loads(self.archivo.read_text(encoding="utf-8")) if self.archivo.is_file() else {}
            return str(datos.get(variable) or "")
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as clave:
                return str(winreg.QueryValueEx(clave, variable)[0] or "").strip()
        except OSError:
            return ""

    def guardar(self, variable: str, valor: str) -> None:
        if self.archivo is not None:
            datos = json.loads(self.archivo.read_text(encoding="utf-8")) if self.archivo.is_file() else {}
            datos[variable] = valor
            self.archivo.parent.mkdir(parents=True, exist_ok=True)
            self.archivo.write_text(json.dumps(datos), encoding="utf-8")
            return
        import ctypes
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as clave:
            winreg.SetValueEx(clave, variable, 0, winreg.REG_SZ, valor)
        # Avisa a Explorer: Desktop abierto desde el escritorio verá la variable.
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, None)


# ------------------------------------------------------------------- alta
class Alta:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.plan = json.loads(Path(args.plan).read_text(encoding="utf-8-sig"))
        if self.plan.get("version") != 1:
            raise SystemExit("Plan con versión desconocida (se espera 1).")
        self.id = str(self.plan.get("empresa_id", ""))
        if not PATRON_ID.fullmatch(self.id) or self.id == "mbt":
            raise SystemExit(f"empresa_id inválido: {self.id!r}")
        for campo in ("nombre", "cloud_id"):
            if not isinstance(self.plan.get(campo), str) or not self.plan[campo].strip():
                raise SystemExit(f"Falta {campo} en el plan.")
        self.raiz_mbt = Path(args.raiz_mbt)
        if not (self.raiz_mbt / "catalogos_privados").is_dir():
            raise SystemExit(f"Raíz MBT no disponible: {self.raiz_mbt}")
        self.raiz = self.raiz_mbt.parent / CARPETA_EMPRESAS / self.id
        self.local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local") / "Atlas" / "empresas" / self.id
        self.variable_token = f"ATLAS_CLOUD_MOTOR_TOKEN__{sufijo(self.id)}"
        self.almacen = AlmacenCredencial(args.credenciales, self.raiz_mbt)
        self.revisar = args.revisar
        self.pasos: list[dict] = []
        self.ledger_ruta = self.local / "alta" / "alta_empresa.json"
        self.ledger = json.loads(self.ledger_ruta.read_text(encoding="utf-8")) if self.ledger_ruta.is_file() else {}
        self._passwords = None

    # ---- procesos de la empresa
    def entorno(self, *, alta: bool = False) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("ATLAS_") or k in HEREDABLES}
        env.update(ATLAS_EMPRESA_ID=self.id, ATLAS_RAIZ_MBT=str(self.raiz_mbt), ATLAS_DATA_DIR=str(self.raiz),
                   PYTHONPATH=str(MOTOR), PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        if self.args.cloud_url:
            env["ATLAS_CLOUD_MOBILE_URL"] = self.args.cloud_url
        token = self.almacen.leer(self.variable_token)
        if token:
            env[self.variable_token] = token
        if alta:
            env["ATLAS_EMPRESA_ALTA"] = self.id
        return env

    def ejecutar(self, comando: list[str], *, alta: bool = False, entrada: str | None = None,
                 extra: dict | None = None) -> tuple[int, dict, str]:
        env = self.entorno(alta=alta)
        env.update(extra or {})
        r = subprocess.run(comando, input=entrada, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=env, cwd=MOTOR, timeout=900)
        for linea in reversed(r.stdout.strip().splitlines()):
            try:
                return r.returncode, json.loads(linea), r.stderr
            except ValueError:
                continue
        return r.returncode, {}, (r.stderr or r.stdout)[-1500:]

    def paso_motor(self, paso: str, params: dict | None = None, *, alta: bool = False) -> dict:
        base = {"empresa_id": self.id, "nombre": self.plan["nombre"], "cloud_id": self.plan["cloud_id"], **(params or {})}
        comando = [self.args.python, "-B", "-m", "atlas_core.alta_empresa", paso, json.dumps(base, ensure_ascii=False)]
        if self.revisar:
            comando.append("--revisar")
        codigo, salida, error = self.ejecutar(comando, alta=alta)
        if not salida:
            salida = {"estado": "ERROR", "codigo": "SALIDA_ILEGIBLE", "detalle": error[-800:]}
        return salida

    # ---- registro de resultados
    def anotar(self, paso: str, resultado: dict) -> dict:
        resultado = {"paso": paso, **{k: v for k, v in resultado.items() if k != "paso"}}
        self.pasos.append(resultado)
        estado = resultado.get("estado")
        print(f"[{estado:<10}] {paso}" + (f" :: {resultado.get('codigo', '')} {resultado.get('detalle', '')}".rstrip()
                                          if estado not in ESTADOS_LISTOS else ""), flush=True)
        if not self.revisar and estado in ESTADOS_LISTOS:
            self.ledger.setdefault("pasos", {})[paso] = {"estado": estado, "fecha": ahora()}
        if estado == "ERROR":
            raise Detener(paso)
        return resultado

    def guardar_ledger(self) -> None:
        if self.revisar or not self.ledger.get("pasos"):
            return
        self.ledger.update(empresa_id=self.id, cloud_id=self.plan["cloud_id"], actualizado=ahora())
        self.ledger_ruta.parent.mkdir(parents=True, exist_ok=True)
        self.ledger_ruta.write_text(json.dumps(self.ledger, ensure_ascii=False, indent=1), encoding="utf-8")

    def listo(self, paso: str) -> bool:
        return self.ledger.get("pasos", {}).get(paso, {}).get("estado") in ESTADOS_LISTOS

    # ---- pasos
    def credencial(self) -> dict:
        token = self.almacen.leer(self.variable_token)
        estado = "YA_ESTABA"
        if not token:
            if self.revisar:
                return {"estado": "SE_HARIA", "variable": self.variable_token}
            token = secrets.token_urlsafe(32)
            self.almacen.guardar(self.variable_token, token)
            if self.almacen.leer(self.variable_token) != token:
                return {"estado": "ERROR", "codigo": "CREDENCIAL_NO_GUARDADA"}
            estado = "HECHO"
        huella = hashlib.sha256(token.encode("utf-8")).hexdigest()
        token = None
        fragmento = {huella: self.plan["cloud_id"]}
        if not self.revisar:
            ruta = self.local / "alta" / "cloud_motor_token.json"
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(json.dumps({"cloud_id": self.plan["cloud_id"], "variable": self.variable_token,
                                        "fragmento_CLOUD_MOTOR_TOKENS_JSON": fragmento}, indent=1), encoding="utf-8")
        return {"estado": estado, "variable": self.variable_token, "fragmento_CLOUD_MOTOR_TOKENS_JSON": fragmento}

    def pull(self) -> list[dict]:
        resultados = []
        config_ruta = self.local / "desktop_operacion.json"
        config = {"modo_escritor": "lease_cloud", "autorizada": True, "habilitada": True, "raiz": str(self.raiz),
                  "raiz_mbt": str(self.raiz_mbt), "proyecto": str(MOTOR)}
        if config_ruta.is_file():
            actual = json.loads(config_ruta.read_text(encoding="utf-8-sig"))
            iguales = all(os.path.normcase(os.path.abspath(str(actual.get(k, "")))) == os.path.normcase(os.path.abspath(config[k]))
                          for k in ("raiz", "raiz_mbt")) and actual.get("modo_escritor") == "lease_cloud"
            resultados.append(("pull-config", {"estado": "YA_ESTABA"} if iguales else
                               {"estado": "ERROR", "codigo": "CONFIG_PULL_DISTINTA", "detalle": str(config_ruta)}))
        elif self.revisar:
            resultados.append(("pull-config", {"estado": "SE_HARIA", "ruta": str(config_ruta)}))
        else:
            config_ruta.parent.mkdir(parents=True, exist_ok=True)
            config_ruta.write_text(json.dumps(config, ensure_ascii=False, indent=1), encoding="utf-8")
            resultados.append(("pull-config", {"estado": "HECHO", "ruta": str(config_ruta)}))

        autorizacion = self.local / "pull_autorizacion.json"
        vigente = autorizacion.is_file() and config_ruta.is_file() and self.ejecutar(
            [self.args.python, "-B", str(MOTOR / "atlas_core" / "autorizacion_pull.py"), "--autorizacion", str(autorizacion),
             "--config", str(config_ruta)])[0] == 0
        if vigente:
            resultados.append(("pull-autorizacion", {"estado": "YA_ESTABA"}))
        elif not self.args.autorizar_pull_horas:
            resultados.append(("pull-autorizacion", {"estado": "OMITIDO",
                                                      "detalle": "decisión humana: repetir con --autorizar-pull-horas N"}))
        elif self.revisar:
            resultados.append(("pull-autorizacion", {"estado": "SE_HARIA", "horas": self.args.autorizar_pull_horas}))
        else:
            vence = (datetime.now(timezone.utc) + timedelta(hours=self.args.autorizar_pull_horas)).isoformat()
            autorizacion.write_text(json.dumps({"autor": "Javier", "exclusividad_verificada": True, "modo": "temporal",
                                                "habilitada": True, "revocada": False, "vence_utc": vence}), encoding="utf-8")
            resultados.append(("pull-autorizacion", {"estado": "HECHO", "vence_utc": vence}))

        if config_ruta.is_file():
            tarea = [os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
                     "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(MOTOR / "scripts" / "instalar_tarea_pull.ps1"),
                     "-Empresa", self.id]
            instalar = self.args.instalar_tarea_pull and not self.revisar and autorizacion.is_file()
            r = subprocess.run(tarea if instalar else tarea + ["-Plan"], capture_output=True, text=True, encoding="utf-8",
                               errors="replace", cwd=MOTOR, timeout=300)
            if r.returncode != 0:
                resultados.append(("pull-tarea", {"estado": "ERROR", "codigo": "TAREA_PULL", "detalle": (r.stderr or r.stdout)[-600:]}))
            elif instalar:
                resultados.append(("pull-tarea", {"estado": "HECHO", "detalle": "registrada DESHABILITADA"}))
            else:
                plan = json.loads(r.stdout) if r.stdout.strip().startswith("{") else r.stdout.strip()
                resultados.append(("pull-tarea", {"estado": "OMITIDO", "plan": plan,
                                                  "detalle": "repetir con --instalar-tarea-pull (queda deshabilitada)"}))
        return resultados

    def password(self, usuario: str) -> str:
        if self.args.password_stdin:
            if self._passwords is None:
                self._passwords = iter(sys.stdin.read().splitlines())
            return next(self._passwords, "")
        primera = getpass.getpass(f"Contraseña inicial de {usuario} (no se muestra): ")
        if getpass.getpass("Repita la contraseña: ") != primera:
            raise Detener("las contraseñas no coinciden")
        return primera

    def d1(self, usuario: str, *opciones: str, entrada: str | None = None) -> tuple[int, dict, str]:
        catalogos = self.raiz / "catalogos_privados"
        comando = [self.args.python, "-B", str(Path(self.args.cloud_repo) / "scripts" / "migrar_usuario_mobile_cloud.py"),
                   "--usuario", usuario, "--empresa-id", self.plan["cloud_id"],
                   "--usuarios-json", str(catalogos / "usuarios_mobile.json"), "--choferes-json", str(catalogos / "choferes.json"),
                   *opciones]
        if self.args.d1.startswith("local:"):
            comando += ["--d1-local", self.args.d1[len("local:"):]]
        elif self.args.d1 != "produccion":
            raise SystemExit("--d1: 'produccion' o 'local:<url del Worker de prueba>'")
        if self.args.url_login:
            comando += ["--url-login", self.args.url_login]
        return self.ejecutar(comando, entrada=entrada, extra={"ATLAS_MOTOR_DIR": str(MOTOR)})

    def mobile(self, chofer: dict) -> dict:
        estado = self.paso_motor("mobile-estado", dict(chofer))
        if estado.get("estado") == "ERROR":
            return estado
        usuario, local = estado["usuario"], estado["usuario_local"]
        if local == "DE_OTRO_CHOFER":
            return {"estado": "ERROR", "codigo": "USUARIO_DE_OTRO_CHOFER", "detalle": usuario}
        codigo, d1, error = self.d1(usuario, "--comprobar")
        if codigo != 0 or "d1" not in d1:
            return {"estado": "ERROR", "codigo": "D1_NO_DISPONIBLE", "detalle": error[-600:]}
        if d1["d1"] in ("DE_OTRA_EMPRESA", "CHOFER_DISTINTO"):
            return {"estado": "ERROR", "codigo": "USUARIO_" + d1["d1"], "detalle": f"{usuario}: nada se escribió"}
        if local == "PROPIO" and d1["d1"] == "PROPIO":
            return {"estado": "YA_ESTABA", "usuario": usuario}
        if self.revisar:
            return {"estado": "SE_HARIA", "usuario": usuario, "local": "crear" if local is None else "existe",
                    "d1": "publicar" if d1["d1"] != "PROPIO" else "existe"}
        clave = self.password(usuario)
        try:
            if local is None:
                comando = [self.args.python, "-B", str(MOTOR / "alta_chofer_mobile.py"), "--raiz-atlas", str(self.raiz),
                           "--usuario", chofer["usuario"], "--rut", chofer["rut"], "--nombre", chofer["nombre"],
                           "--empresa", self.plan["cloud_id"], "--password-stdin"]
                if estado["chofer_en_catalogo"]:
                    comando.append("--chofer-existente")
                codigo, salida, error = self.ejecutar(comando, entrada=clave + "\n")
                if codigo != 0 or salida.get("resultado") != "ALTA_APLICADA":
                    return {"estado": "ERROR", "codigo": salida.get("codigo", "ALTA_LOCAL"), "detalle": salida.get("detalle") or error[-600:]}
            codigo, salida, error = self.d1(usuario, "--aplicar", "--probar-login", "--password-stdin", entrada=clave + "\n")
        finally:
            clave = None
        login = salida.get("login_cloud") or {}
        if codigo != 0 or login.get("http") != 200 or not login.get("token"):
            return {"estado": "ERROR", "codigo": "D1_O_LOGIN", "detalle": (error or json.dumps(salida))[-600:]}
        return {"estado": "HECHO", "usuario": usuario, "local": "creado" if local is None else "existía",
                "d1": salida.get("d1"), "login_cloud": login.get("http")}

    def registro_visible(self) -> dict:
        """Lo que Desktop muestra en su menú de empresas (src/empresa_desktop.js lee la marca)."""
        marca_ruta = self.raiz.joinpath(*RUTA_MARCA)
        if not marca_ruta.is_file():
            return {"estado": "ERROR", "codigo": "SIN_MARCA"}
        marca = json.loads(marca_ruta.read_text(encoding="utf-8"))
        ok = marca.get("empresa_id") == self.id and marca.get("cloud_id") == self.plan["cloud_id"]
        return {"estado": "YA_ESTABA" if ok else "ERROR", "nombre_en_desktop": marca.get("nombre"),
                **({} if ok else {"codigo": "MARCA_DISTINTA"})}

    # ---- flujo
    def correr(self) -> int:
        print(f"Alta de empresa {self.id} ({self.plan['nombre']}, Cloud {self.plan['cloud_id']})"
              + (" — REVISIÓN, no escribe" if self.revisar else ""), flush=True)
        pendiente = False
        try:
            self.anotar("registro", self.paso_motor("registro", alta=True))
            if self.revisar and self.pasos[-1]["estado"] == "SE_HARIA":
                print("La empresa aún no existe: los demás pasos se revisan después del registro.")
                return SALIDA_OK
            self.anotar("estructura", self.paso_motor("estructura", {
                "catalogos_iniciales": self.plan.get("catalogos_iniciales"), "custodia_sembrada": self.listo("custodia")}))
            self.anotar("credencial", self.credencial())
            for nombre, resultado in self.pull():
                self.anotar(nombre, resultado)
            nube = self.anotar("cloud", self.paso_motor("cloud"))
            if nube["estado"] == "PENDIENTE":
                pendiente = True
                fragmento = next((p["fragmento_CLOUD_MOTOR_TOKENS_JSON"] for p in self.pasos if p["paso"] == "credencial"), {})
                print("\nPASO HUMANO: agregar al secreto CLOUD_MOTOR_TOKENS_JSON del Worker la entrada\n  "
                      + json.dumps(fragmento) + "\n(conservar las existentes) y repetir este procedimiento.")
                for paso in ("custodia", "mobile", "verificar"):
                    self.anotar(paso, {"estado": "BLOQUEADO", "detalle": "espera el paso cloud"})
                return SALIDA_PENDIENTE
            self.anotar("custodia", self.paso_motor("custodia"))
            for chofer in self.plan.get("choferes_mobile", []):
                self.anotar(f"mobile:{chofer.get('usuario')}", self.mobile(chofer))
            self.anotar("registro-desktop", self.registro_visible())
            if not self.revisar:
                self.anotar("verificar", self.paso_motor("verificar"))
            return SALIDA_PENDIENTE if pendiente else SALIDA_OK
        except Detener:
            return SALIDA_ERROR
        finally:
            self.guardar_ledger()
            if self.args.informe:
                Path(self.args.informe).write_text(json.dumps({
                    "fecha": ahora(), "empresa_id": self.id, "revisar": self.revisar, "pasos": self.pasos},
                    ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--plan", required=True, help="JSON de la empresa (sin secretos)")
    p.add_argument("--raiz-mbt", required=True, help="raíz de MBT; la empresa vive en ../Atlas_empresas/<id>")
    p.add_argument("--revisar", action="store_true", help="sólo informa qué haría; no escribe nada")
    p.add_argument("--credenciales", default="registro", help="'registro' (perfil Windows) o 'archivo:<ruta>' (sólo pruebas)")
    p.add_argument("--cloud-url", help="URL del Worker (por defecto la del Motor)")
    p.add_argument("--cloud-repo", default=str(MOTOR.parent / "Atlas-Mobile-Cloud"))
    p.add_argument("--d1", default="produccion", help="'produccion' (wrangler) o 'local:<url>' (Worker de prueba)")
    p.add_argument("--url-login", help="login Mobile para la prueba de ingreso (por defecto el del script Cloud)")
    p.add_argument("--autorizar-pull-horas", type=int, help="autorización PULL temporal de la empresa (decisión de Javier)")
    p.add_argument("--instalar-tarea-pull", action="store_true", help="registra la tarea PULL de la empresa, DESHABILITADA")
    p.add_argument("--password-stdin", action="store_true", help="contraseñas de los choferes, una por línea, en orden")
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--informe", help="escribe el resultado JSON en esta ruta")
    return Alta(p.parse_args(argv)).correr()


if __name__ == "__main__":
    raise SystemExit(main())
