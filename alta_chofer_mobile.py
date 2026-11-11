"""Alta de un chofer MBT y de su credencial Mobile local, bajo el escritor oficial.

Uso (consola interactiva; la contraseña se pide con getpass, nunca por argumento):

  python alta_chofer_mobile.py --raiz-atlas "G:\\Mi unidad\\Atlas" \\
      --usuario raimundo.pineda --rut 11.640.500-8 --nombre "RAIMUNDO PINEDA" --solo-validar
  python alta_chofer_mobile.py ... (sin --solo-validar)        # pide contraseña y escribe

Escribe SOLO dos registros nuevos, nunca reemplaza uno existente:
  * catalogos_privados/choferes.json        <rut>     = {"nombre", "activo": true}
  * catalogos_privados/usuarios_mobile.json <usuario> = {"chofer_id", "password_hash"}
No asigna tracto ni rampla ni toca otras cuentas. La escritura ocurre con el mismo
escritor que PULL, Desktop y mantenimiento (lease Cloud o equipo único): turno
local + lease + custodia, que al cerrar confirma el estado en Cloud. La
publicación en D1 es un paso aparte (Atlas-Mobile-Cloud/scripts/
migrar_usuario_mobile_cloud.py), que vuelve a pedir la contraseña.

Salida: una línea JSON sin contraseña ni hash. Códigos: 0 alta aplicada o
validación correcta, 2 datos inválidos/duplicados, 3 escritor ocupado tras la
espera acotada, 4 sin escritor o estado no verificable (no se escribió nada).
"""
from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from atlas_core.aislamiento_empresas import CARPETA_EMPRESAS, CLOUD_MBT, EMPRESA_MBT, empresa_de_raiz  # noqa: F401
from atlas_core.almacenamiento_portable import escribir_json_atomico, resolver_raiz_atlas
from atlas_core.catalogos import normalizar_rut
from atlas_core.mobile import hash_password, verificar_password
from atlas_core.validadores import EstadoValidacion, validar_rut_chileno

SALIDA_OK, SALIDA_DATOS, SALIDA_OCUPADO, SALIDA_SIN_ESCRITOR = 0, 2, 3, 4
LARGO_MINIMO_PASSWORD = 8  # mismo mínimo que crear_usuario_mobile.py
LARGO_MAXIMO_PASSWORD = 128
# Mismo contrato que desktop_operacion._adquirir_con_espera (no se importa: ese
# módulo instala su propia guardia al cargarse). Sólo se reintenta mientras el
# árbitro responde "ocupado"; Cloud caído o credencial inválida no se reintentan.
ESPERA_ESCRITOR_OCUPADO_SEGUNDOS = 150
INTERVALO_ESCRITOR_OCUPADO_SEGUNDOS = 5
_USUARIO = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")  # subconjunto del SEGURO de Cloud
_NOMBRE = re.compile(r"^[A-ZÁÉÍÓÚÜÑ]+(?: [A-ZÁÉÍÓÚÜÑ]+)+$")


class ErrorAlta(Exception):
    def __init__(self, codigo: str, detalle: str, salida: int = SALIDA_DATOS) -> None:
        super().__init__(detalle)
        self.codigo, self.detalle, self.salida = codigo, detalle, salida


def _sin_acentos(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto)
    return " ".join("".join(c for c in base if not unicodedata.combining(c)).upper().split())


def _rutas(raiz: Path) -> tuple[Path, Path]:
    carpeta = raiz / "catalogos_privados"
    return carpeta / "choferes.json", carpeta / "usuarios_mobile.json"


def _leer(ruta: Path) -> dict:
    if not ruta.is_file():
        raise ErrorAlta("CATALOGO_AUSENTE", f"No existe {ruta.name} en la raíz indicada; no se crea uno nuevo.", SALIDA_SIN_ESCRITOR)
    contenido = json.loads(ruta.read_text(encoding="utf-8-sig"))
    if not isinstance(contenido, dict):
        raise ErrorAlta("CATALOGO_INVALIDO", f"{ruta.name} no es un objeto JSON.", SALIDA_SIN_ESCRITOR)
    return contenido


def normalizar_datos(*, usuario: str, rut: str, nombre: str) -> dict[str, str]:
    usuario = str(usuario or "").strip()
    if len(usuario) > 64 or not _USUARIO.fullmatch(usuario):
        raise ErrorAlta("USUARIO_INVALIDO", "Usuario inválido: minúsculas, números y . _ - (p. ej. raimundo.pineda).")
    texto_rut = str(rut or "").strip()
    if "-" not in texto_rut and len(texto_rut) > 1:
        texto_rut = f"{texto_rut[:-1]}-{texto_rut[-1]}"
    resultado = validar_rut_chileno(texto_rut)
    if resultado.estado != EstadoValidacion.VALIDO:
        raise ErrorAlta("RUT_INVALIDO", "RUT inválido o con dígito verificador incorrecto.")
    nombre = " ".join(str(nombre or "").split()).upper()
    if len(nombre) > 80 or not _NOMBRE.fullmatch(nombre):
        raise ErrorAlta("NOMBRE_INVALIDO", "Nombre inválido: al menos nombre y apellido, sólo letras.")
    return {"usuario": usuario, "rut": normalizar_rut(resultado.valor), "nombre": nombre}


def validar_empresa(raiz: Path, empresa: str) -> None:
    if empresa != CLOUD_MBT or empresa_de_raiz(raiz) != EMPRESA_MBT:
        raise ErrorAlta("EMPRESA_NO_SOPORTADA",
                        f"Este comando sólo da de alta choferes de MBT (empresa Cloud {CLOUD_MBT!r}) en la raíz de MBT.")


def comprobar_duplicados(datos: dict[str, str], choferes: dict, usuarios: dict) -> None:
    """Rechaza cualquier coincidencia: el alta nunca reemplaza ni fusiona."""
    rut, usuario, nombre = datos["rut"], datos["usuario"], _sin_acentos(datos["nombre"])
    for clave, registro in choferes.items():
        if normalizar_rut(clave) == rut:
            raise ErrorAlta("RUT_DUPLICADO", "El RUT ya existe en el catálogo de choferes.")
        registro = registro if isinstance(registro, dict) else {}
        nombres = [registro.get("nombre", "")] + list(registro.get("aliases") or [])
        if any(isinstance(n, str) and _sin_acentos(n) == nombre for n in nombres):
            raise ErrorAlta("NOMBRE_DUPLICADO", f"El nombre ya existe en el catálogo con otro identificador ({clave}).")
    cuentas = usuarios.get("usuarios")
    if not isinstance(cuentas, dict):
        raise ErrorAlta("CATALOGO_INVALIDO", "usuarios_mobile.json no tiene la sección 'usuarios'.", SALIDA_SIN_ESCRITOR)
    if any(u.casefold() == usuario.casefold() for u in cuentas):
        raise ErrorAlta("USUARIO_DUPLICADO", "El usuario Mobile ya existe.")
    for nombre_cuenta, cuenta in cuentas.items():
        if isinstance(cuenta, dict) and normalizar_rut(str(cuenta.get("chofer_id", ""))) == rut:
            raise ErrorAlta("CUENTA_DUPLICADA", f"El RUT ya tiene la cuenta Mobile {nombre_cuenta!r}.")


def pedir_password(usuario: str, pedir: Callable[[str], str] = getpass.getpass) -> str:
    password = pedir(f"Contraseña inicial de {usuario} (no se muestra): ")
    if not (LARGO_MINIMO_PASSWORD <= len(password) <= LARGO_MAXIMO_PASSWORD):
        raise ErrorAlta("PASSWORD_INVALIDA", f"La contraseña debe tener entre {LARGO_MINIMO_PASSWORD} y {LARGO_MAXIMO_PASSWORD} caracteres.")
    if password != password.strip():
        raise ErrorAlta("PASSWORD_INVALIDA", "La contraseña no puede empezar ni terminar con espacios.")
    if password.casefold() == usuario.casefold():
        raise ErrorAlta("PASSWORD_INVALIDA", "La contraseña no puede ser igual al usuario.")
    if pedir("Repita la contraseña: ") != password:
        raise ErrorAlta("PASSWORD_NO_COINCIDE", "Las contraseñas no coinciden. No se escribió nada.")
    return password


def escritor_oficial(raiz: Path):
    """El mismo escritor que PULL, Desktop y mantenimiento: equipo único o lease Cloud con custodia."""
    from atlas_core.escritor_operativo import lease_desde_entorno
    from atlas_core.exclusividad_equipo import EscritorEquipoUnico, politica_equipo_unico
    return EscritorEquipoUnico(raiz) if politica_equipo_unico(raiz) else lease_desde_entorno(raiz=raiz)


def adquirir_con_espera(escritor, *, espera=ESPERA_ESCRITOR_OCUPADO_SEGUNDOS, intervalo=INTERVALO_ESCRITOR_OCUPADO_SEGUNDOS,
                        reloj=time.monotonic, dormir=time.sleep) -> bool:
    limite = reloj() + espera
    while not escritor.adquirir():
        if not getattr(escritor, "ocupado", False) or reloj() >= limite:
            return False
        dormir(intervalo)
    return bool(escritor.vigente)


def _exigir_vigente(escritor) -> None:
    if not escritor.vigente:
        raise ErrorAlta("ESCRITOR_PERDIDO", "Se perdió la exclusividad del escritor antes de escribir.", SALIDA_SIN_ESCRITOR)


def aplicar_alta(raiz: Path, datos: dict[str, str], password_hash: str, escritor) -> None:
    """Con el escritor vigente: relee, revalida y agrega los dos registros.
    Si falla la credencial, el chofer recién agregado se retira (mismo turno)."""
    ruta_choferes, ruta_usuarios = _rutas(raiz)
    choferes, usuarios = _leer(ruta_choferes), _leer(ruta_usuarios)
    comprobar_duplicados(datos, choferes, usuarios)  # el estado pudo cambiar al alinear la custodia
    nuevos_choferes = {**choferes, datos["rut"]: {"nombre": datos["nombre"], "activo": True}}
    nuevos_usuarios = {**usuarios, "usuarios": {**usuarios["usuarios"],
                                               datos["usuario"]: {"chofer_id": datos["rut"], "password_hash": password_hash}}}
    _exigir_vigente(escritor)
    escribir_json_atomico(ruta_choferes, nuevos_choferes)
    try:
        _exigir_vigente(escritor)
        escribir_json_atomico(ruta_usuarios, nuevos_usuarios)
    except BaseException:
        if escritor.vigente:
            escribir_json_atomico(ruta_choferes, choferes)
        raise


def verificar_alta(raiz: Path, datos: dict[str, str], password: str | None,
                   choferes_antes: dict, usuarios_antes: dict) -> dict[str, bool]:
    ruta_choferes, ruta_usuarios = _rutas(raiz)
    choferes, usuarios = _leer(ruta_choferes), _leer(ruta_usuarios)
    cuentas = usuarios.get("usuarios", {})
    cuenta = cuentas.get(datos["usuario"], {})
    resultado = {
        "chofer_registrado": choferes.get(datos["rut"]) == {"nombre": datos["nombre"], "activo": True},
        "credencial_local": cuenta.get("chofer_id") == datos["rut"]
        and (password is None or verificar_password(password, str(cuenta.get("password_hash", "")))),
        "otros_choferes_intactos": {k: v for k, v in choferes.items() if k != datos["rut"]} == choferes_antes,
        "otras_cuentas_intactas": {k: v for k, v in cuentas.items() if k != datos["usuario"]} == usuarios_antes.get("usuarios")
        and {k: v for k, v in usuarios.items() if k != "usuarios"} == {k: v for k, v in usuarios_antes.items() if k != "usuarios"},
    }
    return resultado


def ejecutar(raiz: Path, *, usuario: str, rut: str, nombre: str, empresa: str = CLOUD_MBT, solo_validar: bool = False,
             pedir: Callable[[str], str] = getpass.getpass, fabrica_escritor=escritor_oficial,
             adquirir: Callable = adquirir_con_espera) -> dict:
    raiz = Path(raiz)
    datos = normalizar_datos(usuario=usuario, rut=rut, nombre=nombre)
    validar_empresa(raiz, empresa)
    ruta_choferes, ruta_usuarios = _rutas(raiz)
    choferes, usuarios = _leer(ruta_choferes), _leer(ruta_usuarios)
    comprobar_duplicados(datos, choferes, usuarios)
    resumen = {"usuario": datos["usuario"], "chofer_id": datos["rut"], "nombre": datos["nombre"], "empresa_cloud": empresa}
    if solo_validar:
        return {**resumen, "resultado": "VALIDO_SIN_ESCRIBIR"}
    password = pedir_password(datos["usuario"], pedir)
    try:
        password_hash = hash_password(password)
        escritor = fabrica_escritor(raiz)
        if escritor is None:
            raise ErrorAlta("SIN_ESCRITOR_CONFIGURADO", "No hay escritor configurado (falta ATLAS_CLOUD_MOTOR_TOKEN o política de equipo único).",
                            SALIDA_SIN_ESCRITOR)
        with escritor:
            if not adquirir(escritor):
                motivo = getattr(escritor, "motivo", "") or ("ESCRITOR_OCUPADO" if getattr(escritor, "ocupado", False) else "ESCRITOR_NO_ADQUIRIDO")
                ocupado = motivo in ("ESCRITOR_OCUPADO", "ESCRITOR_LOCAL_OCUPADO") or getattr(escritor, "ocupado", False)
                raise ErrorAlta(motivo, "No se obtuvo el escritor; no se escribió nada.", SALIDA_OCUPADO if ocupado else SALIDA_SIN_ESCRITOR)
            choferes, usuarios = _leer(ruta_choferes), _leer(ruta_usuarios)
            aplicar_alta(raiz, datos, password_hash, escritor)
            verificacion = verificar_alta(raiz, datos, password, choferes, usuarios)
        # El cierre del escritor (fin del with) confirma la custodia en Cloud.
        if not all(verificacion.values()):
            raise ErrorAlta("VERIFICACION_FALLIDA", f"Verificación posterior incompleta: {verificacion}", SALIDA_SIN_ESCRITOR)
        return {**resumen, "resultado": "ALTA_APLICADA", "verificacion": verificacion}
    finally:
        password = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raiz-atlas", required=True)
    parser.add_argument("--usuario", required=True)
    parser.add_argument("--rut", required=True, help="RUT con dígito verificador (11.640.500-8)")
    parser.add_argument("--nombre", required=True)
    parser.add_argument("--empresa", default=CLOUD_MBT, help=f"identificador Cloud de la empresa (sólo {CLOUD_MBT})")
    parser.add_argument("--solo-validar", action="store_true", help="valida datos y duplicados sin pedir contraseña ni escribir")
    args = parser.parse_args(argv)
    fecha = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        resultado = ejecutar(resolver_raiz_atlas(args.raiz_atlas), usuario=args.usuario, rut=args.rut, nombre=args.nombre,
                             empresa=args.empresa, solo_validar=args.solo_validar)
        salida = SALIDA_OK
    except ErrorAlta as error:
        resultado, salida = {"resultado": "RECHAZADO", "codigo": error.codigo, "detalle": error.detalle}, error.salida
    except KeyboardInterrupt:
        resultado, salida = {"resultado": "CANCELADO", "codigo": "CANCELADO"}, SALIDA_SIN_ESCRITOR
    except Exception as error:  # noqa: BLE001 - sin traza: sólo el tipo, nunca valores locales
        resultado = {"resultado": "ERROR", "codigo": "ERROR_INESPERADO", "detalle": f"{type(error).__name__}: {error}"}
        salida = SALIDA_SIN_ESCRITOR
    print(json.dumps({"fecha": fecha, **resultado}, ensure_ascii=False))
    return salida


if __name__ == "__main__":
    sys.exit(main())
