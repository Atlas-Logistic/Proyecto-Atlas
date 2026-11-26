"""Identidad y permisos por empresa, aplicados en el Motor (backend).

Roles:

* ``superadministrador_atlas`` -- propietario de la plataforma. Registro propio
  fuera de toda empresa (``<carpeta de Atlas>/../Atlas_plataforma``). Dentro de
  una empresa sólo gestiona su ADMINISTRADOR, y sólo para arranque o
  recuperación (cuando la empresa no tiene un administrador activo) o para
  desactivarlo. Nunca consulta ni corrige datos operacionales.
* ``administrador_empresa`` -- crea, desactiva, reactiva, cambia rol y
  restablece contraseñas de usuarios de SU empresa (incluidas las cuentas
  Mobile de choferes), activa la exigencia de identidad y opera.
* ``supervisor`` -- consulta y corrige la operación. No gestiona usuarios.
* ``chofer`` -- su cuenta Mobile existente (``usuarios_mobile.json`` + D1). Su
  único permiso, enviar sus propias guías, lo aplica Cloud a su sesión Mobile;
  en el Motor no tiene ninguno.

Registro de cada empresa: ``catalogos_privados/desktop_usuarios.json``, el
mismo archivo y formato (versión 1, ``empresa_id``, hash
``pbkdf2_sha256``) de la rama de acceso de Desktop, con estos roles. Los roles
heredados ``operacion``/``consulta`` de esa rama se respetan.

Aplicación: ``entrar_proceso`` corre al importar ``atlas_core`` (después de la
guarda de aislamiento). Si el registro de la empresa tiene
``exigir_identidad: true``, cada proceso del Motor clasifica su punto de
entrada (``CAPACIDADES``) y exige una sesión (``ATLAS_SESION``) vigente cuyo
rol tenga ese permiso; un punto de entrada no clasificado se niega. Sin esa
marca nada cambia (MBT hoy). Las sesiones se revalidan contra el registro en
cada uso: desactivar, cambiar rol o restablecer contraseña las revoca al
instante.

Límite declarado: protege la frontera de la aplicación (procesos del Motor,
API de Cloud). Quien administra la cuenta de Windows o el equipo puede leer o
editar archivos directamente; eso lo cubren el sistema operativo y la custodia.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from atlas_core import aislamiento_empresas as ae

ROL_SUPERADMIN = "superadministrador_atlas"
ROL_ADMIN = "administrador_empresa"
ROL_SUPERVISOR = "supervisor"
ROL_CHOFER = "chofer"
ROLES_EMPRESA = (ROL_ADMIN, ROL_SUPERVISOR)

CONSULTAR, CORREGIR, CONFIGURAR = "operacion.consultar", "operacion.corregir", "operacion.configurar"
GESTIONAR, ADMINISTRADORES, IDENTIDAD = "usuarios.gestionar", "usuarios.administradores", "identidad.configurar"
PERMISOS: dict[str, frozenset[str]] = {
    ROL_SUPERADMIN: frozenset({ADMINISTRADORES}),
    ROL_ADMIN: frozenset({GESTIONAR, ADMINISTRADORES, IDENTIDAD, CONSULTAR, CORREGIR, CONFIGURAR}),
    ROL_SUPERVISOR: frozenset({CONSULTAR, CORREGIR}),
    ROL_CHOFER: frozenset(),
    # Roles de la rama de acceso Desktop (feat/multiempresa-acceso-desktop-20261118).
    "operacion": frozenset({CONSULTAR, CORREGIR}),
    "consulta": frozenset({CONSULTAR}),
}

SISTEMA, SESION = "sistema", "sesion"
# Punto de entrada -> permiso. "sistema": procesos desatendidos sin usuario (PULL,
# mantenimiento, custodia, alta); "sesion": el propio comando decide por acción.
_GRUPOS = {
    CONSULTAR: "b1_consulta_cli consultar_atlas consultar_incidencias_operacionales resumen_procesamiento_desktop "
               "previsualizar_registro_obra investigar_revision_b1 investigacion_documental perfilar_aplicacion_decision "
               "verificar_mobile_lote",
    CORREGIR: "b1_operador_cli acciones_operacionales_cli aplicar_decision_pendiente aplicar_decisiones_multiples "
              "asociar_evidencia_mobile asociar_evidencias_pdf_existentes confirmar_incidencias_operacionales "
              "confirmar_licencia_chofer construir_fichas_catalogos corregir_fechas_documento desktop_operacion_cli "
              "eventos_operacionales_cli forzar_correccion_destino generar_reporte_viajes gestionar_catalogos "
              "operaciones_conversacionales_cli proponer_incidencias_operacionales publicacion_reportes "
              "registrar_expediente_digital registrar_licencia_chofer resolver_documento_expediente resolver_envio_mobile "
              "retomar_entradas_desktop revalidar_transporte revision_mobile_cli analizar_guias_masivo "
              "clasificar_anverso_licencia inicializar_fichas_choferes recuperar_envio_mobile_error reproceso_cuarentena "
              "reprocesar_lote_reparador atlas",
    CONFIGURAR: "migrar_destinos_globales migrar_observaciones_a_eventos migrar_relaciones_operacionales "
                "importar_base_local_osm reconciliar_estado_derivado",
    GESTIONAR: "alta_chofer_mobile alta_mobile_lote crear_usuario_mobile migrar_usuario_mobile_cloud",
    SISTEMA: "sincronizar_mobile_cloud sincronizar_mobile servidor_mobile mantener_pendientes_tecnicos registrar_credencial "
             "alta_empresa atlas_core.alta_empresa atlas_core.estado_confirmado atlas_core.autorizacion_pull usuarios_atlas",
}
CAPACIDADES: dict[str, str] = {
    (nombre if "." in nombre else nombre + ".py"): permiso
    for permiso, nombres in _GRUPOS.items() for nombre in nombres.split()
}
ENVOLTORIOS = {"consulta_python.py"}  # Desktop: ejecuta otro script con runpy

VARIABLE_SESION = "ATLAS_SESION"
RUTA_REGISTRO = ("catalogos_privados", "desktop_usuarios.json")
CARPETA_PLATAFORMA = "Atlas_plataforma"
ARCHIVO_PLATAFORMA = "usuarios_plataforma.json"
VIGENCIA = {"empresa": 8 * 3600, "plataforma": 3600}
INTENTOS_ANTES_DE_ESPERA, ESPERA_SEGUNDOS = 5, 30
PATRON_USUARIO = re.compile(r"^[a-z0-9][a-z0-9._-]{1,38}[a-z0-9]$")
SALIDA_DENEGADO = 77


class ErrorIdentidad(RuntimeError):
    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(f"{codigo}: {detalle}" if detalle else codigo)
        self.codigo, self.detalle = codigo, detalle


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------- rutas
def contexto() -> ae.ContextoEmpresa:
    return ae.contexto_desde_entorno()


def ruta_registro(ctx: ae.ContextoEmpresa) -> Path:
    return ctx.raiz.joinpath(*RUTA_REGISTRO)


def ruta_plataforma(ctx: ae.ContextoEmpresa) -> Path:
    return Path(ctx.raiz_mbt).parent / CARPETA_PLATAFORMA / ARCHIVO_PLATAFORMA


def _local_plataforma() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local") / CARPETA_PLATAFORMA


def _dir_sesiones(tipo: str, ctx: ae.ContextoEmpresa) -> Path:
    return (_local_plataforma() if tipo == "plataforma" else ae.base_local(ctx.empresa_id) / "identidad") / "sesiones"


# --------------------------------------------------------------- registros
def _vacio(ctx: ae.ContextoEmpresa) -> dict:
    return {"version": 1, "empresa_id": ctx.empresa_id, "exigir_identidad": False, "usuarios": [], "auditoria": []}


def leer_registro(ctx: ae.ContextoEmpresa) -> dict:
    """Registro de ESTA empresa. Ilegible o de otra empresa: error (nunca "vacío")."""
    ruta = ruta_registro(ctx)
    try:
        registro = json.loads(ruta.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return _vacio(ctx)
    except (OSError, ValueError) as error:
        raise ErrorIdentidad("REGISTRO_ILEGIBLE", str(error)) from error
    if (not isinstance(registro, dict) or registro.get("version") != 1 or not isinstance(registro.get("usuarios"), list)):
        raise ErrorIdentidad("REGISTRO_ILEGIBLE", "estructura desconocida")
    if registro.get("empresa_id") != ctx.empresa_id:
        raise ErrorIdentidad("REGISTRO_DE_OTRA_EMPRESA", str(registro.get("empresa_id")))
    registro.setdefault("auditoria", [])
    return registro


def leer_plataforma(ctx: ae.ContextoEmpresa) -> dict | None:
    ruta = ruta_plataforma(ctx)
    try:
        registro = json.loads(ruta.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        raise ErrorIdentidad("REGISTRO_PLATAFORMA_ILEGIBLE", str(error)) from error
    if not isinstance(registro, dict) or registro.get("version") != 1 or registro.get("plataforma") != "atlas":
        raise ErrorIdentidad("REGISTRO_PLATAFORMA_ILEGIBLE", "estructura desconocida")
    return registro


def _cuenta(registro: dict, usuario: str) -> dict | None:
    usuario = str(usuario or "").strip().lower()
    return next((u for u in registro.get("usuarios", []) if isinstance(u, dict) and str(u.get("usuario", "")).lower() == usuario), None)


def _cuenta_chofer(ctx: ae.ContextoEmpresa, usuario: str) -> dict | None:
    try:
        cuentas = json.loads(ctx.catalogos().joinpath("usuarios_mobile.json").read_text(encoding="utf-8-sig")).get("usuarios", {})
    except (OSError, ValueError):
        return None
    cuenta = cuentas.get(str(usuario or "").strip())
    return cuenta if isinstance(cuenta, dict) else None


def _huella(cuenta: dict) -> str:
    return hashlib.sha256(str(cuenta.get("password_hash", "")).encode()).hexdigest()[:16]


def _publica(cuenta: dict) -> dict:
    return {k: cuenta.get(k) for k in ("usuario", "nombre", "rol", "activo", "creado_por", "creado_en",
                                         "actualizado_por", "actualizado_en") if k in cuenta}


# ----------------------------------------------------------------- sesiones
def _ruta_sesion(directorio: Path, secreto: str) -> Path:
    return directorio / f"{hashlib.sha256(secreto.encode()).hexdigest()}.json"


def _fallos(directorio: Path) -> Path:
    return directorio.parent / "intentos_fallidos.json"


def _registrar_fallo(directorio: Path, clave: str) -> None:
    ruta = _fallos(directorio)
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        datos = {}
    previo = datos.get(clave, {"n": 0})
    n = int(previo.get("n", 0)) + 1
    datos[clave] = {"n": n, "hasta": time.time() + ESPERA_SEGUNDOS if n >= INTENTOS_ANTES_DE_ESPERA else 0}
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos), encoding="utf-8")


def _bloqueado(directorio: Path, clave: str) -> bool:
    try:
        return float(json.loads(_fallos(directorio).read_text(encoding="utf-8")).get(clave, {}).get("hasta", 0)) > time.time()
    except (OSError, ValueError, AttributeError):
        return False


def _limpiar_fallo(directorio: Path, clave: str) -> None:
    ruta = _fallos(directorio)
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if datos.pop(clave, None) is not None:
        ruta.write_text(json.dumps(datos), encoding="utf-8")


_SEÑUELO = None


def _verificar(password: str, codificado: str | None) -> bool:
    """Siempre calcula un hash (cuenta inexistente incluida): mismo tiempo de respuesta."""
    global _SEÑUELO
    from atlas_core.mobile import hash_password, verificar_password
    if _SEÑUELO is None:
        _SEÑUELO = hash_password(secrets.token_urlsafe(16))
    try:
        valido = verificar_password(password, codificado or _SEÑUELO)
    except Exception:  # noqa: BLE001 - hash dañado = credencial inválida
        valido = False
    return bool(valido and codificado)


def iniciar_sesion(usuario: str, password: str, *, plataforma: bool = False) -> dict:
    """Verifica la contraseña y emite una sesión. Devuelve el secreto UNA vez (sólo
    su sha256 queda en disco). El mismo mensaje para usuario inexistente o clave errónea."""
    ctx = contexto()
    tipo = "plataforma" if plataforma else "empresa"
    directorio = _dir_sesiones(tipo, ctx)
    usuario = str(usuario or "").strip().lower() if plataforma else str(usuario or "").strip()
    clave = f"{tipo}:{ctx.empresa_id if not plataforma else '*'}:{usuario.lower()}"
    if _bloqueado(directorio, clave):
        raise ErrorIdentidad("DEMASIADOS_INTENTOS", f"espere {ESPERA_SEGUNDOS} segundos")
    if plataforma:
        registro = leer_plataforma(ctx) or {"usuarios": []}
        cuenta = _cuenta(registro, usuario)
        rol = ROL_SUPERADMIN
    else:
        cuenta = _cuenta(leer_registro(ctx), usuario)
        rol = cuenta.get("rol") if cuenta else None
        if cuenta is None:
            cuenta = _cuenta_chofer(ctx, usuario)
            rol = ROL_CHOFER if cuenta else None
    activa = bool(cuenta) and cuenta.get("activo", True) is not False and rol in PERMISOS
    if plataforma:
        activa = activa and cuenta.get("rol") == ROL_SUPERADMIN
    if not _verificar(str(password or ""), cuenta.get("password_hash") if cuenta else None) or not activa:
        _registrar_fallo(directorio, clave)
        raise ErrorIdentidad("CREDENCIALES_INVALIDAS", "usuario o contraseña incorrectos")
    _limpiar_fallo(directorio, clave)
    secreto = secrets.token_urlsafe(32)
    emitida = time.time()
    sesion = {"version": 1, "tipo": tipo, "empresa_id": None if plataforma else ctx.empresa_id,
              "usuario": str(cuenta.get("usuario") or usuario).lower() if rol != ROL_CHOFER else usuario,
              "rol": rol, "credencial": cuenta.get("credencial_version", 1) if rol != ROL_CHOFER else _huella(cuenta),
              "emitida": emitida, "expira": emitida + VIGENCIA[tipo]}
    directorio.mkdir(parents=True, exist_ok=True)
    ruta = _ruta_sesion(directorio, secreto)
    ruta.write_text(json.dumps(sesion), encoding="utf-8")
    return {"sesion": secreto, "tipo": tipo, "empresa_id": sesion["empresa_id"], "usuario": sesion["usuario"],
            "rol": rol, "expira": datetime.fromtimestamp(sesion["expira"], timezone.utc).isoformat(timespec="seconds")}


def validar_sesion(secreto: str | None = None) -> dict:
    """Sesión vigente de este proceso. Se busca sólo en la carpeta local de ESTA
    empresa (una sesión de otra empresa no existe aquí) o en la de plataforma."""
    secreto = secreto if secreto is not None else os.environ.get(VARIABLE_SESION, "")
    if not secreto or len(secreto) < 30:
        raise ErrorIdentidad("SIN_SESION", "inicie sesión")
    ctx = contexto()
    for tipo in ("empresa", "plataforma"):
        ruta = _ruta_sesion(_dir_sesiones(tipo, ctx), secreto)
        try:
            sesion = json.loads(ruta.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as error:
            raise ErrorIdentidad("SESION_INVALIDA", str(error)) from error
        break
    else:
        raise ErrorIdentidad("SESION_INVALIDA", "sesión inexistente, cerrada o de otra empresa")
    if sesion.get("tipo") != tipo or time.time() >= float(sesion.get("expira", 0)):
        raise ErrorIdentidad("SESION_EXPIRADA", "vuelva a iniciar sesión")
    if tipo == "empresa" and sesion.get("empresa_id") != ctx.empresa_id:
        raise ErrorIdentidad("SESION_DE_OTRA_EMPRESA", str(sesion.get("empresa_id")))
    # Revalidación: la cuenta sigue activa, con el mismo rol y la misma credencial.
    if tipo == "plataforma":
        cuenta = _cuenta(leer_plataforma(ctx) or {"usuarios": []}, sesion["usuario"])
        vigente = cuenta and cuenta.get("rol") == ROL_SUPERADMIN and cuenta.get("credencial_version", 1) == sesion["credencial"]
    elif sesion.get("rol") == ROL_CHOFER:
        cuenta = _cuenta_chofer(ctx, sesion["usuario"])
        vigente = cuenta and _huella(cuenta) == sesion["credencial"]
    else:
        cuenta = _cuenta(leer_registro(ctx), sesion["usuario"])
        vigente = cuenta and cuenta.get("rol") == sesion["rol"] and cuenta.get("credencial_version", 1) == sesion["credencial"]
    if not vigente or cuenta.get("activo", True) is False:
        raise ErrorIdentidad("SESION_REVOCADA", "la cuenta fue desactivada o modificada")
    return {**sesion, "nombre": cuenta.get("nombre", "")}


def cerrar_sesion(secreto: str | None = None) -> bool:
    secreto = secreto if secreto is not None else os.environ.get(VARIABLE_SESION, "")
    ctx = contexto()
    borradas = False
    for tipo in ("empresa", "plataforma"):
        ruta = _ruta_sesion(_dir_sesiones(tipo, ctx), secreto) if secreto else None
        if ruta and ruta.is_file():
            ruta.unlink()
            borradas = True
    return borradas


def tiene(sesion: dict, permiso: str) -> bool:
    return permiso in PERMISOS.get(str(sesion.get("rol")), frozenset())


def exigir(permiso: str, sesion: dict | None = None) -> dict:
    sesion = sesion or validar_sesion()
    if not tiene(sesion, permiso):
        raise ErrorIdentidad("PERMISO_DENEGADO", f"{sesion.get('rol')} no tiene {permiso}")
    return sesion


# ------------------------------------------------------------- escrituras
def _escritor(raiz: Path):
    from atlas_core.escritor_operativo import lease_desde_entorno
    from atlas_core.exclusividad_equipo import EscritorEquipoUnico, politica_equipo_unico
    return EscritorEquipoUnico(raiz) if politica_equipo_unico(raiz) else lease_desde_entorno(raiz=raiz)


def _con_escritor(ctx: ae.ContextoEmpresa, cambio, *, espera: float = 150.0, intervalo: float = 5.0):
    """El mismo escritor oficial que PULL, Desktop y alta_chofer_mobile: turno local +
    lease Cloud + custodia (que confirma el registro al cerrar). ``cambio`` recibe el
    registro releído bajo el escritor y devuelve (nuevo, resultado)."""
    from atlas_core.almacenamiento_portable import escribir_json_atomico
    escritor = _escritor(ctx.raiz)
    if escritor is None:
        raise ErrorIdentidad("SIN_ESCRITOR", "falta la credencial Motor de la empresa")
    limite = time.monotonic() + espera
    with escritor:
        while not escritor.adquirir():
            if not getattr(escritor, "ocupado", False) or time.monotonic() >= limite:
                raise ErrorIdentidad(getattr(escritor, "motivo", "") or "ESCRITOR_OCUPADO", "no se escribió nada")
            time.sleep(intervalo)
        nuevo, resultado = cambio(leer_registro(ctx))
        if not escritor.vigente:
            raise ErrorIdentidad("ESCRITOR_PERDIDO", "no se escribió nada")
        escribir_json_atomico(ruta_registro(ctx), nuevo)
    return resultado


def _auditar(registro: dict, sesion: dict, accion: str, usuario: str, **extra) -> None:
    actor = f"{'plataforma' if sesion.get('tipo') == 'plataforma' else sesion.get('empresa_id')}:{sesion.get('usuario')}"
    registro["auditoria"] = (registro.get("auditoria", []) + [{"fecha": ahora_iso(), "actor": actor, "rol_actor": sesion.get("rol"),
                                                               "accion": accion, "usuario": usuario, **extra}])[-500:]


def _activos(registro: dict, rol: str) -> list[dict]:
    return [u for u in registro["usuarios"] if isinstance(u, dict) and u.get("rol") == rol and u.get("activo") is True]


def _autorizar_sobre(sesion: dict, registro: dict, *, rol_objetivo: str, accion: str, usuario: str | None = None) -> None:
    """Quién puede gestionar a quién. Lanza PERMISO_DENEGADO."""
    rol = sesion.get("rol")
    if rol == ROL_ADMIN and tiene(sesion, GESTIONAR):
        if rol_objetivo not in ROLES_EMPRESA and rol_objetivo not in ("operacion", "consulta"):
            raise ErrorIdentidad("ROL_INVALIDO", f"un administrador no asigna {rol_objetivo!r}")
        if usuario and usuario.lower() == str(sesion.get("usuario")).lower() and accion != "restablecer":
            raise ErrorIdentidad("PERMISO_DENEGADO", "un administrador no se desactiva ni cambia su propio rol")
        return
    if rol == ROL_SUPERADMIN:
        if rol_objetivo != ROL_ADMIN:
            raise ErrorIdentidad("PERMISO_DENEGADO", "el superadministrador sólo gestiona administradores de empresa")
        if accion in ("crear", "reactivar") and _activos(registro, ROL_ADMIN):
            raise ErrorIdentidad("PERMISO_DENEGADO", "la empresa ya tiene un administrador activo: lo gestiona ella")
        if accion not in ("crear", "reactivar", "desactivar"):
            raise ErrorIdentidad("PERMISO_DENEGADO", f"el superadministrador no puede {accion}")
        return
    raise ErrorIdentidad("PERMISO_DENEGADO", f"{rol} no gestiona usuarios")


def _validar_password(password: str, usuario: str) -> str:
    if not (8 <= len(password or "") <= 128) or password != password.strip() or password.casefold() == usuario.casefold():
        raise ErrorIdentidad("PASSWORD_INVALIDA", "entre 8 y 128 caracteres, sin espacios al borde y distinta del usuario")
    return password


def crear_usuario(usuario: str, nombre: str, rol: str, password: str, *, sesion: dict | None = None) -> dict:
    from atlas_core.mobile import hash_password
    sesion = sesion or validar_sesion()
    ctx = contexto()
    usuario = str(usuario or "").strip().lower()
    if not PATRON_USUARIO.fullmatch(usuario):
        raise ErrorIdentidad("USUARIO_INVALIDO", "minúsculas, números y . _ -")
    if rol not in ROLES_EMPRESA:
        raise ErrorIdentidad("ROL_INVALIDO", rol)
    nombre = " ".join(str(nombre or "").split())
    if not nombre or len(nombre) > 80:
        raise ErrorIdentidad("NOMBRE_INVALIDO", "nombre obligatorio, hasta 80 caracteres")
    hash_ = hash_password(_validar_password(password, usuario))

    def cambio(registro):
        _autorizar_sobre(sesion, registro, rol_objetivo=rol, accion="crear", usuario=usuario)
        if _cuenta(registro, usuario) is not None or _cuenta_chofer(ctx, usuario) is not None:
            raise ErrorIdentidad("USUARIO_DUPLICADO", usuario)
        cuenta = {"usuario": usuario, "nombre": nombre, "rol": rol, "activo": True, "password_hash": hash_,
                  "credencial_version": 1, "creado_por": sesion["usuario"], "creado_en": ahora_iso()}
        registro["usuarios"].append(cuenta)
        _auditar(registro, sesion, "crear", usuario, rol=rol)
        return registro, _publica(cuenta)
    return _con_escritor(ctx, cambio)


def modificar_usuario(usuario: str, accion: str, *, rol: str | None = None, password: str | None = None,
                      sesion: dict | None = None) -> dict:
    """accion: desactivar | reactivar | cambiar_rol | restablecer. Toda modificación
    sube ``credencial_version`` y con ello revoca las sesiones abiertas."""
    from atlas_core.mobile import hash_password
    sesion = sesion or validar_sesion()
    ctx = contexto()
    usuario = str(usuario or "").strip().lower()
    if accion == "cambiar_rol" and rol not in ROLES_EMPRESA:
        raise ErrorIdentidad("ROL_INVALIDO", str(rol))
    hash_ = hash_password(_validar_password(password or "", usuario)) if accion == "restablecer" else None

    def cambio(registro):
        cuenta = _cuenta(registro, usuario)
        if cuenta is None:
            raise ErrorIdentidad("USUARIO_INEXISTENTE", usuario)
        _autorizar_sobre(sesion, registro, rol_objetivo=cuenta.get("rol"), accion=accion, usuario=usuario)
        if accion == "cambiar_rol":
            _autorizar_sobre(sesion, registro, rol_objetivo=rol, accion=accion, usuario=usuario)
            cuenta["rol"] = rol
        elif accion == "desactivar":
            cuenta["activo"] = False
        elif accion == "reactivar":
            cuenta["activo"] = True
        elif accion == "restablecer":
            cuenta["password_hash"] = hash_
        else:
            raise ErrorIdentidad("ACCION_INVALIDA", accion)
        cuenta["credencial_version"] = int(cuenta.get("credencial_version", 1)) + 1
        cuenta.update(actualizado_por=sesion["usuario"], actualizado_en=ahora_iso())
        _auditar(registro, sesion, accion, usuario, **({"rol": rol} if rol else {}))
        return registro, _publica(cuenta)
    return _con_escritor(ctx, cambio)


def listar_usuarios(*, sesion: dict | None = None) -> list[dict]:
    """Cuentas (sin hashes). Administrador: las de su empresa y los choferes Mobile.
    Superadministrador: sólo los administradores."""
    sesion = sesion or validar_sesion()
    ctx = contexto()
    registro = leer_registro(ctx)
    if tiene(sesion, GESTIONAR):
        choferes = []
        try:
            cuentas = json.loads(ctx.catalogos().joinpath("usuarios_mobile.json").read_text(encoding="utf-8-sig")).get("usuarios", {})
            choferes = [{"usuario": u, "rol": ROL_CHOFER, "activo": c.get("activo", True) is not False}
                        for u, c in sorted(cuentas.items()) if isinstance(c, dict)]
        except (OSError, ValueError):
            pass
        return [_publica(u) for u in registro["usuarios"]] + choferes
    if sesion.get("rol") == ROL_SUPERADMIN:
        return [_publica(u) for u in registro["usuarios"] if u.get("rol") == ROL_ADMIN]
    raise ErrorIdentidad("PERMISO_DENEGADO", f"{sesion.get('rol')} no lista usuarios")


def fijar_exigencia(activar: bool, *, sesion: dict | None = None) -> dict:
    sesion = exigir(IDENTIDAD, sesion)
    ctx = contexto()

    def cambio(registro):
        if activar and not _activos(registro, ROL_ADMIN):
            raise ErrorIdentidad("SIN_ADMINISTRADOR", "activar sin un administrador activo dejaría la empresa sin acceso")
        registro["exigir_identidad"] = bool(activar)
        _auditar(registro, sesion, "exigir_identidad", "*", valor=bool(activar))
        return registro, {"exigir_identidad": bool(activar)}
    return _con_escritor(ctx, cambio)


def fijar_chofer_activo(usuario: str, activo: bool, *, sesion: dict | None = None) -> dict:
    """Cuenta Mobile de un chofer de ESTA empresa (la revocación efectiva en Cloud la
    hace el llamador antes, en D1: el Worker valida ``activo`` en cada petición)."""
    sesion = exigir(GESTIONAR, sesion)
    ctx = contexto()
    from atlas_core.almacenamiento_portable import escribir_json_atomico
    ruta = ctx.catalogos() / "usuarios_mobile.json"
    escritor = _escritor(ctx.raiz)
    if escritor is None:
        raise ErrorIdentidad("SIN_ESCRITOR", "falta la credencial Motor de la empresa")
    with escritor:
        if not escritor.adquirir():
            raise ErrorIdentidad(getattr(escritor, "motivo", "") or "ESCRITOR_OCUPADO", "no se escribió nada")
        datos = json.loads(ruta.read_text(encoding="utf-8-sig"))
        cuenta = datos.get("usuarios", {}).get(usuario)
        if not isinstance(cuenta, dict):
            raise ErrorIdentidad("USUARIO_INEXISTENTE", usuario)
        cuenta["activo"] = bool(activo)
        cuenta.update(actualizado_por=sesion["usuario"], actualizado_en=ahora_iso())
        escribir_json_atomico(ruta, datos)
    return {"usuario": usuario, "rol": ROL_CHOFER, "activo": bool(activo)}


# --------------------------------------------------------------- plataforma
def inicializar_plataforma(usuario: str, nombre: str, password: str) -> dict:
    """Primer superadministrador. Sólo si el registro de plataforma no existe."""
    from atlas_core.exclusion_local import TurnoEscritura
    from atlas_core.mobile import hash_password
    ctx = contexto()
    usuario = str(usuario or "").strip().lower()
    if not PATRON_USUARIO.fullmatch(usuario):
        raise ErrorIdentidad("USUARIO_INVALIDO", usuario)
    ruta = ruta_plataforma(ctx)
    hash_ = hash_password(_validar_password(password, usuario))
    with TurnoEscritura(ruta.parent):
        if ruta.exists():
            raise ErrorIdentidad("PLATAFORMA_YA_INICIALIZADA", "use una sesión de superadministrador")
        ruta.parent.mkdir(parents=True, exist_ok=True)
        cuenta = {"usuario": usuario, "nombre": " ".join(str(nombre).split()), "rol": ROL_SUPERADMIN, "activo": True,
                  "password_hash": hash_, "credencial_version": 1, "creado_en": ahora_iso()}
        temporal = ruta.with_name(ruta.name + ".tmp")
        temporal.write_text(json.dumps({"version": 1, "plataforma": "atlas", "usuarios": [cuenta]}, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        os.replace(temporal, ruta)
    return _publica(cuenta)


# ----------------------------------------------------------------- puerta
def entrada_proceso() -> str:
    """Punto de entrada del proceso: script, ``-m módulo`` o ``-c``."""
    argumentos = list(getattr(sys, "orig_argv", sys.argv))[1:]
    i = 0
    while i < len(argumentos):
        a = argumentos[i]
        if a == "-m":
            return argumentos[i + 1] if i + 1 < len(argumentos) else "-m"
        if a.startswith("-m") and len(a) > 2:
            return a[2:]
        if a == "-c" or a.startswith("-c"):
            return "-c"
        if a in ("-W", "-X"):
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        nombre = os.path.basename(a)
        if nombre in ENVOLTORIOS and i + 1 < len(argumentos):
            return os.path.basename(argumentos[i + 1])
        return nombre
    return "-"


_sesion_proceso: dict | None = None


def sesion_proceso() -> dict | None:
    """Sesión validada por la puerta (``None`` si la empresa no exige identidad)."""
    return _sesion_proceso


def actor_operacion(declarado: str) -> str:
    """Actor auditable de una acción del proceso.

    Con identidad exigida, la puerta ya validó la sesión: el actor es la persona
    identificada (``<empresa>:<usuario>``, mismo formato que la auditoría del
    registro), no la etiqueta fija que envía el llamador (Desktop manda
    ``JAVIER_DESKTOP`` para cualquier usuario). Sin exigencia (MBT hoy), el
    declarado, como siempre."""
    sesion = _sesion_proceso
    if not sesion or not sesion.get("usuario") or not sesion.get("empresa_id"):
        return declarado
    return f"{sesion['empresa_id']}:{sesion['usuario']}"


def entrar_proceso(ctx: ae.ContextoEmpresa | None = None) -> None:
    """Puerta del proceso (al importar ``atlas_core``). Falla cerrado si el
    registro existe pero es ilegible o ajeno."""
    global _sesion_proceso
    if ctx is None:  # MBT sin otras empresas: sólo un stat del registro, como hoy la guarda
        from atlas_core.almacenamiento_portable import resolver_raiz_atlas
        if not Path(resolver_raiz_atlas()).joinpath(*RUTA_REGISTRO).is_file():
            return
    try:
        ctx = ctx or contexto()
    except ae.ErrorAislamiento:
        return  # la guarda de aislamiento ya decidió (p. ej. raíz aún no creada en el alta)
    if not ruta_registro(ctx).is_file():
        return
    try:
        registro = leer_registro(ctx)
        if registro.get("exigir_identidad") is not True:
            return
        entrada = entrada_proceso()
        capacidad = CAPACIDADES.get(entrada)
        if capacidad == SISTEMA:
            return
        if capacidad is None:
            raise ErrorIdentidad("ENTRADA_NO_CLASIFICADA", entrada)
        _sesion_proceso = exigir(capacidad) if capacidad != SESION else validar_sesion()
    except ErrorIdentidad as error:
        print(json.dumps({"error": error.codigo, "detalle": error.detalle, "empresa": ctx.empresa_id},
                         ensure_ascii=False), file=sys.stderr, flush=True)
        raise SystemExit(SALIDA_DENEGADO) from None
