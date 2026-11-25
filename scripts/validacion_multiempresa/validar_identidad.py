"""Validación de IDENTIDAD Y PERMISOS por empresa (25/11/2026).

Prepara el mundo sintético con el procedimiento de alta ya validado
(validar_alta.py: MBT ficticia + Transportes Andes ficticia, Worker real en
proceso) sin volver a evaluarlo, y prueba sólo lo nuevo: superadministrador,
administrador de empresa, supervisor y chofer; permisos aplicados por el Motor
y por Cloud; accesos cruzados, escalamiento de privilegios y revocación.

    python scripts/validacion_multiempresa/validar_identidad.py <mundo> <checkout cloud> <checkout desktop>

Nunca toca G:, el LOCALAPPDATA real, Cloudflare ni MBT real. Escribe
<mundo>/../evidencia/validacion_identidad.json; sale 1 si algo falla.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validar_alta as va  # noqa: E402  (lee <mundo> <cloud> <desktop> de sys.argv)

MBT, ANDES, LOCAL, PY = va.MBT, va.ANDES, va.LOCAL, va.PY
CLAVE = {"superadmin": "clave-superadmin-1", "mbt.admin": "clave-mbt-admin-1", "andes.admin": "clave-andes-admin-1",
         "andes.admin2": "clave-andes-admin2-1", "andes.sup": "clave-andes-sup-1"}
resultados: list[dict] = []
W: va.Worker | None = None


def registrar(etapa: str, prueba: str, ok: bool, detalle: object = "") -> None:
    resultados.append({"etapa": etapa, "prueba": prueba, "ok": bool(ok), "detalle": detalle})
    print(("OK   " if ok else "FALLA") + f" [{etapa}] {prueba}" + ("" if ok else f" :: {str(detalle)[:700]}"), flush=True)


def entorno(empresa: str, sesion: str | None) -> dict:
    env = va.env_mbt() if empresa == "mbt" else va.env_empresa(va.ANDES_ID, ANDES)
    env["ATLAS_CLOUD_MOBILE_URL"] = W.url
    env.pop("ATLAS_SESION", None)
    if sesion:
        env["ATLAS_SESION"] = sesion
    return env


def ua(empresa: str, *args: str, sesion: str | None = None, clave: str | None = None) -> tuple[int, dict]:
    r = va.correr([PY, "-B", str(va.MOTOR / "usuarios_atlas.py"), *args], entorno(empresa, sesion),
                  entrada=(clave + "\n") if clave is not None else "")
    try:
        return r.returncode, json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return r.returncode, {"_salida": (r.stdout + r.stderr)[-800:]}


def puerta(empresa: str, script: str, *args: str, sesion: str | None = None) -> tuple[int, str]:
    """Ejecuta un punto de entrada del Motor; 77 = la puerta de identidad lo negó."""
    cmd = [PY, "-B", "-c", args[0]] if script == "-c" else [PY, "-B", str(va.MOTOR / script), *(args or ("--help",))]
    r = va.correr(cmd, entorno(empresa, sesion))
    return r.returncode, (r.stderr or "")[-400:]


def denegado(resultado: tuple[int, str], codigo: str) -> bool:
    return resultado[0] == 77 and f'"error": "{codigo}"' in resultado[1]


def login(empresa: str, usuario: str, clave: str, plataforma: bool = False) -> str:
    rc, r = ua(empresa, "iniciar-sesion", "--usuario", usuario, *(["--plataforma"] if plataforma else []), clave=clave)
    return r.get("sesion", "") if rc == 0 else ""


def registro(raiz: Path) -> dict:
    return json.loads((raiz / "catalogos_privados" / "desktop_usuarios.json").read_text(encoding="utf-8"))


def zonas_mbt() -> dict:
    """Raíz y estado local de MBT, sin su carpeta de sesiones (la prueba inicia sesiones en MBT a propósito)."""
    local = LOCAL / "Atlas"
    return {"raiz": va.inventario(MBT), "local": va.inventario(local, (local / "empresas", local / "identidad"))}


def mobile_login(usuario: str, clave: str) -> tuple[int, str]:
    s, b = W.json("POST", "/api/mobile/login", cuerpo={"usuario": usuario, "password": clave})
    return s, (b.get("token", "") if isinstance(b, dict) else "")


# ------------------------------------------------------------- preparación
def preparar() -> None:
    global W
    va.preparar()
    W = va.Worker({})
    va.alta(W, va.MUNDO / "plan_andes.json", "--autorizar-pull-horas", "2")
    pendiente = json.loads((LOCAL / "Atlas" / "empresas" / va.ANDES_ID / "alta" / "cloud_motor_token.json").read_text(encoding="utf-8"))
    W.cerrar()
    W = va.Worker(pendiente["fragmento_CLOUD_MOTOR_TOKENS_JSON"])
    r = va.correr([PY, "-B", "-m", "atlas_core.estado_confirmado", "--raiz-atlas", str(MBT), "--sembrar"],
                  {**va.env_mbt(), "ATLAS_CLOUD_MOBILE_URL": W.url})
    rc, pasos, salida = va.alta(W, va.MUNDO / "plan_andes.json", "--autorizar-pull-horas", "2",
                                claves=[va.CLAVES["andes.luis"], va.CLAVES["andes.ana"]])
    registrar("preparacion", "mundo: MBT ficticia con custodia y Andes dada de alta con el procedimiento existente (sin reevaluarlo)",
              r.returncode == 0 and rc == 0, (r.stderr[-300:], rc, salida[-600:]))


# ------------------------------------------------------------------ fases
def fase_plataforma() -> str:
    rc, r = ua("mbt", "plataforma-inicializar", "--usuario", "superadmin", "--nombre", "Propietario Atlas", clave=CLAVE["superadmin"])
    rc2, r2 = ua("mbt", "plataforma-inicializar", "--usuario", "otro", "--nombre", "Otro", clave="clave-otro-123")
    registrar("plataforma", "primer superadministrador creado; una segunda inicialización se rechaza",
              rc == 0 and rc2 == 2 and r2.get("codigo") == "PLATAFORMA_YA_INICIALIZADA"
              and (MBT.parent / "Atlas_plataforma" / "usuarios_plataforma.json").is_file(), (r, r2))
    rc, r = ua("mbt", "iniciar-sesion", "--usuario", "superadmin", "--plataforma", clave="clave-erronea-1")
    registrar("plataforma", "contraseña errónea: CREDENCIALES_INVALIDAS", rc == 77 and r.get("codigo") == "CREDENCIALES_INVALIDAS", r)
    codigos = [ua("mbt", "iniciar-sesion", "--usuario", "intruso", "--plataforma", clave="clave-erronea-1")[1].get("codigo") for _ in range(6)]
    registrar("plataforma", "intentos repetidos: espera obligatoria tras 5 fallos", codigos[-1] == "DEMASIADOS_INTENTOS", codigos)
    sa = login("mbt", "superadmin", CLAVE["superadmin"], plataforma=True)
    registrar("plataforma", "superadministrador inicia sesión de plataforma", bool(sa))
    return sa


def fase_arranque(sa: str) -> dict:
    s = {"sa": sa}
    for empresa, admin in (("mbt", "mbt.admin"), ("andes", "andes.admin")):
        rc, r = ua(empresa, "crear", "--usuario", admin, "--nombre", f"Admin {empresa}", "--rol", "administrador_empresa",
                   sesion=sa, clave=CLAVE[admin])
        registrar("arranque", f"superadministrador crea el primer administrador de {empresa}", rc == 0 and r.get("resultado") == "CREADO", r)
    rc, r = ua("andes", "crear", "--usuario", "andes.otro", "--nombre", "Otro", "--rol", "administrador_empresa", sesion=sa, clave="clave-otro-123")
    registrar("superadmin", "con un administrador activo, el superadministrador ya no crea otro (lo gestiona la empresa)",
              rc == 77 and r.get("codigo") == "PERMISO_DENEGADO", r)
    rc, r = ua("andes", "crear", "--usuario", "andes.sup.sa", "--nombre", "Sup", "--rol", "supervisor", sesion=sa, clave="clave-sup-123")
    registrar("superadmin", "el superadministrador no crea supervisores", rc == 77, r)
    rc, r = ua("andes", "restablecer-contrasena", "--usuario", "andes.admin", sesion=sa, clave="clave-tomada-123")
    registrar("superadmin", "el superadministrador no restablece la contraseña de un administrador (no puede suplantarlo)", rc == 77, r)
    rc, r = ua("andes", "listar", sesion=sa)
    registrar("superadmin", "el superadministrador lista sólo administradores, sin hashes",
              rc == 0 and [u["usuario"] for u in r.get("usuarios", [])] == ["andes.admin"] and "pbkdf2" not in json.dumps(r), r)
    s["aa"] = login("andes", "andes.admin", CLAVE["andes.admin"])
    s["ma"] = login("mbt", "mbt.admin", CLAVE["mbt.admin"])
    registrar("arranque", "cada administrador inicia sesión en su empresa", bool(s["aa"] and s["ma"]))
    rc, _r = ua("andes", "exigir-identidad", "--activar", sesion=sa)
    registrar("superadmin", "el superadministrador no cambia la exigencia de identidad de una empresa", rc == 77)
    # MBT: sin activar, todo sigue como hoy.
    registrar("compatibilidad", "MBT sin exigencia activada: los procesos del Motor corren como hoy, sin sesión",
              puerta("mbt", "b1_consulta_cli.py")[0] == 0)
    for empresa, sesion in (("andes", s["aa"]), ("mbt", s["ma"])):
        rc, r = ua(empresa, "exigir-identidad", "--activar", sesion=sesion)
        registrar("arranque", f"administrador de {empresa} activa la exigencia de identidad", rc == 0 and r.get("exigir_identidad") is True, r)
    return s


def fase_admin(s: dict) -> None:
    for usuario, rol in (("andes.sup", "supervisor"), ("andes.admin2", "administrador_empresa")):
        rc, r = ua("andes", "crear", "--usuario", usuario, "--nombre", usuario.upper(), "--rol", rol, sesion=s["aa"], clave=CLAVE[usuario])
        registrar("admin", f"administrador de Andes crea {rol} {usuario} sin intervención del propietario", rc == 0, r)
    rc, r = ua("andes", "crear", "--usuario", "andes.root", "--nombre", "Root", "--rol", "superadministrador_atlas", sesion=s["aa"], clave="clave-root-123")
    registrar("escalamiento", "administrador no puede crear un superadministrador", rc == 2 and r.get("codigo") == "ROL_INVALIDO", r)
    rc, r = ua("andes", "crear", "--usuario", "andes.luis", "--nombre", "X", "--rol", "supervisor", sesion=s["aa"], clave="clave-x-12345")
    registrar("admin", "no se crea un usuario con el nombre de una cuenta existente (chofer)", rc == 2 and r.get("codigo") == "USUARIO_DUPLICADO", r)
    rc, r = ua("andes", "desactivar", "--usuario", "andes.admin", sesion=s["aa"])
    registrar("admin", "un administrador no se desactiva a sí mismo (la empresa no queda sin administrador)", rc == 77, r)
    rc, r = ua("andes", "listar", sesion=s["aa"])
    usuarios = {u["usuario"]: u for u in r.get("usuarios", [])}
    registrar("admin", "listar: usuarios de Andes y sus choferes Mobile, sin hashes ni datos de MBT",
              rc == 0 and {"andes.admin", "andes.sup", "andes.admin2", "andes.luis", "andes.ana"} <= set(usuarios)
              and not [u for u in usuarios if u.startswith("mbt")] and "pbkdf2" not in json.dumps(r), sorted(usuarios))
    s["sup"] = login("andes", "andes.sup", CLAVE["andes.sup"])
    s["aa2"] = login("andes", "andes.admin2", CLAVE["andes.admin2"])


def fase_permisos(s: dict) -> None:
    # Supervisor: opera, no administra.
    r = va.correr([PY, "-B", str(va.MOTOR / "b1_consulta_cli.py"), "--raiz-atlas", str(ANDES), "--texto", "¿Quiénes están inactivos?"],
                  entorno("andes", s["sup"]))
    registrar("supervisor", "supervisor consulta la operación de Andes por B1 (pasa la puerta y responde)",
              r.returncode == 0 and r.stdout.strip().startswith("{"), (r.returncode, r.stderr[-300:]))
    registrar("supervisor", "supervisor puede corregir (b1_operador_cli)", puerta("andes", "b1_operador_cli.py", sesion=s["sup"])[0] == 0)
    registrar("supervisor", "supervisor no ejecuta configuración (migrar_destinos_globales)",
              denegado(puerta("andes", "migrar_destinos_globales.py", sesion=s["sup"]), "PERMISO_DENEGADO"))
    for args, prueba in ((("crear", "--usuario", "andes.nuevo", "--nombre", "N", "--rol", "administrador_empresa"), "crear un administrador"),
                         (("cambiar-rol", "--usuario", "andes.sup", "--rol", "administrador_empresa"), "subirse a administrador"),
                         (("exigir-identidad", "--desactivar"), "desactivar la exigencia de identidad"),
                         (("desactivar-chofer", "--usuario", "andes.ana", "--d1", f"local:{W.url}", "--cloud-repo", str(va.CLOUD)), "desactivar un chofer")):
        rc, r = ua("andes", *args, sesion=s["sup"], clave="clave-escala-123")
        registrar("escalamiento", f"supervisor no puede {prueba}", rc == 77 and r.get("codigo") == "PERMISO_DENEGADO", r)
    registrar("escalamiento", "supervisor no da de alta choferes (alta_chofer_mobile)",
              denegado(puerta("andes", "alta_chofer_mobile.py", sesion=s["sup"]), "PERMISO_DENEGADO"))
    # Sin sesión o con una falsa.
    registrar("backend", "exigencia activa: sin sesión el Motor niega B1",
              denegado(puerta("andes", "b1_consulta_cli.py"), "SIN_SESION"))
    registrar("backend", "sesión inventada: SESION_INVALIDA",
              denegado(puerta("andes", "b1_consulta_cli.py", sesion="x" * 43), "SESION_INVALIDA"))
    registrar("backend", "punto de entrada no clasificado (python -c) se niega",
              denegado(puerta("andes", "-c", "import atlas_core"), "ENTRADA_NO_CLASIFICADA"))
    registrar("backend", "procesos de sistema (PULL) siguen sin sesión", puerta("andes", "sincronizar_mobile_cloud.py")[0] == 0)
    registrar("backend", "MBT con exigencia activa: sin sesión también se niega", denegado(puerta("mbt", "b1_consulta_cli.py"), "SIN_SESION"))
    # Superadministrador: sin acceso operacional.
    for script in ("b1_consulta_cli.py", "consultar_atlas.py", "b1_operador_cli.py", "generar_reporte_viajes.py"):
        registrar("superadmin", f"superadministrador sin acceso operacional: {script} denegado en Andes",
                  denegado(puerta("andes", script, sesion=s["sa"]), "PERMISO_DENEGADO"))
    # Chofer: su cuenta Mobile, ningún permiso en el Motor.
    s["chofer"] = login("andes", "andes.luis", va.CLAVES["andes.luis"])
    rc, r = ua("andes", "quien-soy", sesion=s["chofer"])
    registrar("chofer", "chofer inicia sesión con su cuenta Mobile y queda con rol chofer", r.get("rol") == "chofer", r)
    registrar("chofer", "chofer no consulta B1 en el Motor", denegado(puerta("andes", "b1_consulta_cli.py", sesion=s["chofer"]), "PERMISO_DENEGADO"))
    registrar("chofer", "chofer no lista usuarios", ua("andes", "listar", sesion=s["chofer"])[0] == 77)


def fase_cruces(s: dict) -> None:
    for empresa, sesion, origen in (("mbt", s["aa"], "admin de Andes"), ("andes", s["ma"], "admin de MBT")):
        registrar("acceso-cruzado", f"sesión del {origen} no vale en la otra empresa (B1)",
                  denegado(puerta(empresa, "b1_consulta_cli.py", sesion=sesion), "SESION_INVALIDA"))
        rc, r = ua(empresa, "listar", sesion=sesion)
        registrar("acceso-cruzado", f"sesión del {origen} no gestiona usuarios de la otra empresa", rc == 77 and r.get("codigo") == "SESION_INVALIDA", r)
    rc, r = ua("andes", "desactivar-chofer", "--usuario", "mbt.luis", "--d1", f"local:{W.url}", "--cloud-repo", str(va.CLOUD), sesion=s["aa"])
    registrar("acceso-cruzado", "admin de Andes no desactiva al chofer de MBT; su ingreso Mobile sigue funcionando",
              rc == 2 and r.get("codigo") == "USUARIO_INEXISTENTE" and mobile_login("mbt.luis", "clave-mbt-1")[0] == 200, r)
    rc, r = ua("andes", "crear", "--usuario", "mbt.admin", "--nombre", "Homonimo", "--rol", "supervisor", sesion=s["aa"], clave="clave-homo-123")
    homonimo = login("andes", "mbt.admin", "clave-homo-123")
    registrar("acceso-cruzado", "un usuario homónimo en Andes es otra cuenta: no abre MBT",
              rc == 0 and bool(homonimo) and denegado(puerta("mbt", "b1_consulta_cli.py", sesion=homonimo), "SESION_INVALIDA")
              and not login("mbt", "mbt.admin", "clave-homo-123"), r)


def fase_revocacion(s: dict) -> None:
    rc, _r = ua("andes", "desactivar", "--usuario", "andes.sup", sesion=s["aa"])
    registrar("revocacion", "desactivar al supervisor revoca al instante su sesión abierta",
              rc == 0 and denegado(puerta("andes", "b1_consulta_cli.py", sesion=s["sup"]), "SESION_REVOCADA"))
    registrar("revocacion", "supervisor desactivado no puede iniciar sesión", not login("andes", "andes.sup", CLAVE["andes.sup"]))
    ua("andes", "reactivar", "--usuario", "andes.sup", sesion=s["aa"])
    nueva = login("andes", "andes.sup", CLAVE["andes.sup"])
    registrar("revocacion", "reactivado: inicia sesión de nuevo; la sesión anterior sigue revocada",
              bool(nueva) and denegado(puerta("andes", "b1_consulta_cli.py", sesion=s["sup"]), "SESION_REVOCADA"))
    rc, _r = ua("andes", "restablecer-contrasena", "--usuario", "andes.admin2", sesion=s["aa"], clave="clave-nueva-admin2")
    registrar("revocacion", "restablecer la contraseña revoca las sesiones y la clave anterior deja de servir",
              rc == 0 and ua("andes", "listar", sesion=s["aa2"])[0] == 77 and not login("andes", "andes.admin2", CLAVE["andes.admin2"])
              and bool(login("andes", "andes.admin2", "clave-nueva-admin2")))
    aa2 = login("andes", "andes.admin2", "clave-nueva-admin2")
    ua("andes", "cambiar-rol", "--usuario", "andes.admin2", "--rol", "supervisor", sesion=s["aa"])
    rc, r = ua("andes", "crear", "--usuario", "andes.x", "--nombre", "X", "--rol", "supervisor", sesion=aa2, clave="clave-x-12345")
    degradado = login("andes", "andes.admin2", "clave-nueva-admin2")
    rc2, r2 = ua("andes", "crear", "--usuario", "andes.x", "--nombre", "X", "--rol", "supervisor", sesion=degradado, clave="clave-x-12345")
    registrar("revocacion", "bajar de rol a un administrador revoca su sesión y su nueva sesión ya no administra",
              rc == 77 and r.get("codigo") == "SESION_REVOCADA" and rc2 == 77 and r2.get("codigo") == "PERMISO_DENEGADO", (r, r2))
    # Chofer: revocación en Cloud (D1) y en el Motor.
    s_ok, token = mobile_login("andes.luis", va.CLAVES["andes.luis"])
    rc, r = ua("andes", "desactivar-chofer", "--usuario", "andes.luis", "--d1", f"local:{W.url}", "--cloud-repo", str(va.CLOUD), sesion=s["aa"])
    renovar, _ = W.json("POST", "/api/mobile/sesion/renovar", token, {})
    fila = next(u for u in W.tabla("mobile_usuarios_cloud") if u["nombre_usuario"] == "andes.luis")
    registrar("revocacion", "admin desactiva a un chofer: D1 inactivo, ingreso Mobile 401 y su sesión Mobile abierta rechazada",
              s_ok == 200 and rc == 0 and int(fila["activo"]) == 0 and mobile_login("andes.luis", va.CLAVES["andes.luis"])[0] == 401
              and renovar == 401, (r, renovar))
    registrar("revocacion", "chofer desactivado: su sesión del Motor queda revocada",
              ua("andes", "quien-soy", sesion=s["chofer"])[1].get("codigo") == "SESION_REVOCADA")
    registrar("revocacion", "el chofer de MBT no se ve afectado", mobile_login("mbt.luis", "clave-mbt-1")[0] == 200)
    rc, r = ua("andes", "reactivar-chofer", "--usuario", "andes.luis", "--d1", f"local:{W.url}", "--cloud-repo", str(va.CLOUD), sesion=s["aa"])
    registrar("revocacion", "admin reactiva al chofer: vuelve a ingresar en Mobile", rc == 0 and mobile_login("andes.luis", va.CLAVES["andes.luis"])[0] == 200, r)


def fase_auditoria_e_integridad(s: dict, mbt_antes: dict) -> None:
    reg = registro(ANDES)
    actores = {(a["actor"], a["accion"], a["usuario"]) for a in reg["auditoria"]}
    registrar("auditoria", "cada cambio queda auditado con su actor (plataforma o empresa)",
              ("plataforma:superadmin", "crear", "andes.admin") in actores and ("andes-prueba:andes.admin", "desactivar", "andes.sup") in actores
              and ("andes-prueba:andes.admin", "exigir_identidad", "*") in actores, sorted(actores)[:12])
    r = va.correr([PY, "-B", "-m", "atlas_core.estado_confirmado", "--raiz-atlas", str(ANDES), "--verificar"], entorno("andes", None))
    verificacion = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else r.stderr[-300:]
    registrar("integridad", "registro de usuarios de Andes escrito con el escritor oficial: custodia Cloud sin diferencias",
              isinstance(verificacion, dict) and verificacion.get("distintos") == 0, verificacion)
    sesiones = list((LOCAL / "Atlas" / "empresas" / va.ANDES_ID / "identidad" / "sesiones").glob("*.json"))
    secretos = [v for k, v in s.items() if v]
    registrar("integridad", "las sesiones se guardan por huella: ningún secreto de sesión ni contraseña en disco",
              sesiones and not any(va.buscar(va.MUNDO, x, (va.MUNDO / "evidencia",)) for x in secretos + list(CLAVE.values())), len(sesiones))
    registrar("aislamiento", "MBT ficticia sin cambios por toda la gestión de Andes", zonas_mbt() == mbt_antes)
    registrar("aislamiento", "registro de Andes sólo con usuarios de Andes y empresa_id propio",
              reg["empresa_id"] == va.ANDES_ID and not [u for u in reg["usuarios"] if u["usuario"].startswith("mbt.") and u["usuario"] != "mbt.admin"])


def main() -> int:
    va.EVIDENCIA.mkdir(parents=True, exist_ok=True)
    preparar()
    try:
        sa = fase_plataforma()
        s = fase_arranque(sa)
        mbt_antes = zonas_mbt()
        fase_admin(s)
        fase_permisos(s)
        fase_cruces(s)
        fase_revocacion(s)
        fase_auditoria_e_integridad(s, mbt_antes)
    finally:
        W.cerrar()
    fallas = [r for r in resultados if not r["ok"]]
    (va.EVIDENCIA / "validacion_identidad.json").write_text(json.dumps({
        "fecha": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "motor": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=va.MOTOR).stdout.strip(),
        "cloud": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=va.CLOUD).stdout.strip(),
        "total": len(resultados), "fallas": len(fallas), "resultados": resultados}, indent=1, ensure_ascii=False, default=str),
        encoding="utf-8")
    print(f"\n{len(resultados) - len(fallas)}/{len(resultados)} OK")
    return 1 if fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
