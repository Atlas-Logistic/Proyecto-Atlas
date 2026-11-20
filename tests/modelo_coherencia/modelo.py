"""Modelo ejecutable del diseño docs/DISENO_COHERENCIA_GENERACIONES.md.

**Sólo para pruebas.** No es una implementación del protocolo: modela en
memoria la raíz operacional de cada equipo (CASA/OFICINA) y su réplica Drive,
el lease Cloud y la custodia de generaciones (61c2872), más la extensión
propuesta (control durable PENDIENTE por empresa). Con él se reproducen los
escenarios de riesgo y se comprueba qué propiedades se sostienen **en este
modelo**. Una prueba sobre el modelo no demuestra la implementación real.

Usa el contrato real: `fuentes_generacion.FUENTES` (rutas y tipos),
`descriptor_generacion` v2 (descriptor) y `descriptor_custodia` (forma Cloud).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass, field

from atlas_core import descriptor_generacion as dg
from atlas_core import fuentes_generacion as fg
from atlas_core.descriptor_custodia import RUTA_DESCRIPTOR, proyectar_para_custodia, verificar_generacion_custodia

LEASE_SEGUNDOS = 120  # Worker: LEASE_ESCRITOR_SEGUNDOS
ENTRADAS = "operacion/entradas/"


def sha(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


# Fuentes de archivo fijo del contrato real (sin plantillas, sin la geografía del repositorio).
FUENTES_FIJAS = tuple(f for f in fg.FUENTES
                      if f.ruta and "<" not in f.ruta and "{" not in f.ruta and f.empresa == fg.PROPIA)
RUTA = {f.clave: f.ruta for f in FUENTES_FIJAS}
DERIVACION_ASIGNACIONES = {r: next(f.identidad for f in fg.FUENTES if f.clave == c)
                           for r, c in fg.RANURAS_ASIGNACIONES.items()}


def estado_inicial(empresa: str) -> dict[str, bytes]:
    """Raíz sintética mínima: todas las fuentes fijas con contenido vacío legítimo y una guía."""
    archivos: dict[str, bytes] = {}
    for f in FUENTES_FIJAS:
        if f.tipo == "IDENTIDAD_EMPRESA" and empresa in dg.EMPRESAS_SIN_MARCA:
            continue
        if f.clave == "dataset":
            archivos[f.ruta] = _csv([{"archivo": "Guia 900001.jpg", "numero_guia": "900001", "destino": "OBRA A",
                                      "estado": "PENDIENTE"}])
        elif f.clave == "bandeja":
            archivos[f.ruta] = _json({"decisiones": [{"decision_id": "D1", "archivo": "Guia 900001.jpg"}]})
        elif f.clave == "ledger":
            archivos[f.ruta] = _json({"aplicaciones": []})
        elif f.clave == "acciones_operacionales":
            archivos[f.ruta] = _json({"previews": {}})
        elif f.clave == "identidad_empresa":
            archivos[f.ruta] = _json({"cloud_id": empresa})
        else:
            archivos[f.ruta] = _json({})
    archivos[ENTRADAS + "lote-1/Guia 900001.jpg"] = b"foto-sintetica-900001"
    return archivos


def _json(valor) -> bytes:
    return json.dumps(valor, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _csv(filas: list[dict]) -> bytes:
    salida = io.StringIO()
    escritor = csv.DictWriter(salida, fieldnames=["archivo", "numero_guia", "destino", "estado"], delimiter=";",
                              lineterminator="\n")
    escritor.writeheader()
    escritor.writerows(filas)
    return salida.getvalue().encode("utf-8")


def leer_csv(datos: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(datos.decode("utf-8")), delimiter=";"))


# --------------------------------------------------------------------- Cloud
class ErrorProtocolo(RuntimeError):
    def __init__(self, codigo: str):
        super().__init__(codigo)
        self.codigo = codigo


@dataclass
class _EstadoEmpresa:
    titular: str | None = None
    token: str | None = None
    epoca: int = 0
    expira: float = 0.0
    control: dict | None = None             # {"estado": "PENDIENTE", "epoca": n} -- extensión propuesta
    puntero: str | None = None
    generaciones: dict = field(default_factory=dict)  # id -> {"cuerpo": dict, "sha": str, "epoca": int}
    objetos: dict = field(default_factory=dict)       # sha -> bytes (por empresa)


class NubeModelo:
    """Lease (120 s, época), objetos por empresa y SHA-256, generaciones con puntero (61c2872)
    y el control durable PENDIENTE propuesto, todo bajo CAS por empresa."""

    def __init__(self):
        self.reloj = 0.0
        self._e: dict[str, _EstadoEmpresa] = {}
        self._contador = 0

    def e(self, empresa) -> _EstadoEmpresa:
        return self._e.setdefault(empresa, _EstadoEmpresa())

    def avanzar(self, segundos: float) -> None:
        self.reloj += segundos

    # lease
    def adquirir(self, empresa, titular) -> tuple[str, int] | None:
        e = self.e(empresa)
        if e.token and e.expira > self.reloj:
            return None
        self._contador += 1
        e.titular, e.token, e.epoca, e.expira = titular, f"lease-{self._contador}", e.epoca + 1, self.reloj + LEASE_SEGUNDOS
        return e.token, e.epoca

    def vigente(self, empresa, token) -> bool:
        e = self.e(empresa)
        return bool(token) and e.token == token and e.expira > self.reloj

    def renovar(self, empresa, token) -> bool:
        if not self.vigente(empresa, token):
            return False
        self.e(empresa).expira = self.reloj + LEASE_SEGUNDOS
        return True

    def liberar(self, empresa, token) -> None:
        e = self.e(empresa)
        if e.token == token:
            e.token, e.titular, e.expira = None, None, 0.0

    # control PENDIENTE (extensión propuesta)
    def abrir_frontera(self, empresa, token) -> str:
        """PENDIENTE(época del lease). Si queda un PENDIENTE de otra época, la anterior se interrumpió."""
        e = self.e(empresa)
        if not self.vigente(empresa, token):
            raise ErrorProtocolo("ESCRITOR_NO_VIGENTE")
        if e.control and e.control["epoca"] != e.epoca:
            return "INTERRUMPIDA"
        e.control = {"estado": "PENDIENTE", "epoca": e.epoca, "titular": e.titular}
        return "PENDIENTE"

    def asumir_recuperacion(self, empresa, token) -> None:
        """Tras recuperar, la época vigente toma el PENDIENTE; nunca vuelve a COMPLETA sin publicar."""
        if not self.vigente(empresa, token):
            raise ErrorProtocolo("ESCRITOR_NO_VIGENTE")
        e = self.e(empresa)
        e.control = {"estado": "PENDIENTE", "epoca": e.epoca, "titular": e.titular}

    # objetos y generaciones (61c2872 + CAS con el control)
    def subir(self, empresa, token, datos: bytes) -> str:
        if not self.vigente(empresa, token):
            raise ErrorProtocolo("ESCRITOR_NO_VIGENTE")
        h = sha(datos)
        self.e(empresa).objetos[h] = bytes(datos)
        return h

    def publicar(self, empresa, token, cuerpo: dict, sha_cuerpo: str) -> None:
        """Una sola transición: control PENDIENTE(época) -> puntero nuevo y control vacío."""
        e = self.e(empresa)
        if not self.vigente(empresa, token):
            raise ErrorProtocolo("ESCRITOR_NO_VIGENTE")
        if not e.control or e.control["epoca"] != e.epoca:
            raise ErrorProtocolo("SIN_FRONTERA_DE_ESTA_EPOCA")
        if cuerpo["empresa_id"] != empresa:
            raise ErrorProtocolo("GENERACION_INVALIDA")
        if any(o["sha256"] not in e.objetos or sha(e.objetos[o["sha256"]]) != o["sha256"] for o in cuerpo["objetos"]):
            raise ErrorProtocolo("NO_CONFIABLE")
        e.generaciones[cuerpo["generacion_id"]] = {"cuerpo": cuerpo, "sha": sha_cuerpo, "epoca": e.epoca}
        e.puntero, e.control = cuerpo["generacion_id"], None

    def cerrar_sin_cambios(self, empresa, token) -> None:
        e = self.e(empresa)
        if not self.vigente(empresa, token) or not e.control or e.control["epoca"] != e.epoca:
            raise ErrorProtocolo("SIN_FRONTERA_DE_ESTA_EPOCA")
        e.control = None

    def actual(self, empresa) -> dict | None:
        e = self.e(empresa)
        if e.puntero is None:
            return None
        g = e.generaciones[e.puntero]
        return {"descriptor": g["cuerpo"], "descriptor_sha256": g["sha"], "control": e.control}

    def descargar(self, empresa, h: str) -> bytes | None:
        return self.e(empresa).objetos.get(h)


# ------------------------------------------------------------- equipos y Drive
class Equipo:
    """Una raíz operacional local (G:) con réplica Drive diferida hacia los demás equipos."""

    def __init__(self, nombre: str, drive: "DriveModelo"):
        self.nombre = nombre
        self.drive = drive
        self.archivos: dict[str, dict[str, bytes]] = {}   # empresa -> ruta -> bytes
        drive.equipos.append(self)

    def raiz(self, empresa) -> dict[str, bytes]:
        return self.archivos.setdefault(empresa, {})

    def escribir_sin_turno(self, empresa, ruta, datos: bytes | None) -> None:
        """Escritor NO gobernado (p. ej. Electron en modo legado, CLI manual): no pasa por el turno."""
        raiz = self.raiz(empresa)
        if datos is None:
            raiz.pop(ruta, None)
        else:
            raiz[ruta] = datos
        self.drive.encolar(self, empresa, ruta, datos)


class DriveModelo:
    """Réplica eventual y desordenable: cada cambio queda en cola por equipo destino."""

    def __init__(self):
        self.equipos: list[Equipo] = []
        self.pendientes: list[tuple[Equipo, str, str, bytes | None]] = []

    def encolar(self, origen, empresa, ruta, datos):
        for destino in self.equipos:
            if destino is not origen:
                self.pendientes.append((destino, empresa, ruta, datos))

    def sincronizar(self, destino: Equipo, *, solo=None) -> None:
        restantes = []
        for d, empresa, ruta, datos in self.pendientes:
            if d is destino and (solo is None or ruta in solo):
                if datos is None:
                    d.raiz(empresa).pop(ruta, None)
                else:
                    d.raiz(empresa)[ruta] = datos
            else:
                restantes.append((d, empresa, ruta, datos))
        self.pendientes = restantes


# --------------------------------------------------------------- turno escritor
class EscrituraSinTurno(ErrorProtocolo):
    pass


class TurnoEscritor:
    """Turno = turno local + lease Cloud (existentes) + frontera PENDIENTE y captura al cerrar (propuestas)."""

    def __init__(self, nube: NubeModelo, equipo: Equipo, empresa: str):
        self.nube, self.equipo, self.empresa = nube, equipo, empresa
        self.token: str | None = None
        self.epoca = 0
        self.estado_entrada = ""

    def adquirir(self) -> str:
        concedido = self.nube.adquirir(self.empresa, self.equipo.nombre)
        if concedido is None:
            return "OCUPADO"
        self.token, self.epoca = concedido
        control = self.nube.e(self.empresa).control
        if control and control["epoca"] != self.epoca:
            # Época anterior interrumpida. Sus escrituras parciales están en la raíz del equipo
            # titular; otro equipo sólo tiene lo que Drive haya replicado, quizá desordenado.
            if control.get("titular") != self.equipo.nombre:
                self.estado_entrada = "INTERRUMPIDA_EN_OTRO_EQUIPO"
                return self.estado_entrada
            self.estado_entrada = "INTERRUMPIDA"
            return self.estado_entrada
        # Protocolo 2 existente, sobre la generación publicada: la copia local debe coincidir.
        actual = self.nube.actual(self.empresa)
        if actual is not None:
            for o in actual["descriptor"]["objetos"]:
                ruta = _ruta_real(o["ruta"], actual, self.nube, self.empresa)
                if ruta is None:
                    continue
                datos = self.equipo.raiz(self.empresa).get(ruta)
                if datos is None or sha(datos) != o["sha256"]:
                    self.nube.liberar(self.empresa, self.token)
                    self.token = None
                    return "ESTADO_NO_VERIFICADO"
        self.estado_entrada = self.nube.abrir_frontera(self.empresa, self.token)
        return self.estado_entrada

    def vigente(self) -> bool:
        return self.token is not None and self.nube.vigente(self.empresa, self.token)

    def escribir(self, ruta: str, datos: bytes | None) -> None:
        """Escritura gobernada: exige turno vigente (guardia exclusion_local + comprobar())."""
        if not self.vigente():
            raise EscrituraSinTurno("ESCRITOR_NO_VIGENTE")
        self.equipo.escribir_sin_turno(self.empresa, ruta, datos)

    def cerrar(self, *, exito: bool, generacion_id: str, previa_id: str | None, secuencia: int,
               entre_pasadas=None, durante_pasada=None) -> str:
        """Cierre del turno. Sólo un turno terminado sin error captura y publica; si no, el
        PENDIENTE queda y la próxima época verá INTERRUMPIDA."""
        try:
            if not exito or not self.vigente():
                return "PENDIENTE_QUEDA"
            try:
                captura = capturar(self.equipo.raiz(self.empresa), self.empresa,
                                   entre_pasadas=entre_pasadas, durante_pasada=durante_pasada)
            except ErrorProtocolo as error:
                return f"PENDIENTE_QUEDA:{error.codigo}"
            actual = self.nube.actual(self.empresa)
            anterior = _objetos_fuente(actual) if actual else None
            if anterior is not None and anterior == {o.identidad: o.huella for o in captura["fuentes"]}:
                self.nube.cerrar_sin_cambios(self.empresa, self.token)
                return "SIN_CAMBIOS"
            d = dg.construir_descriptor(dg.Inventario(
                2, self.empresa, dg.GeneracionSolicitada(generacion_id, secuencia, previa_id),
                captura["declaracion"], tuple(captura["fuentes"]), {"ASIGNACIONES": DERIVACION_ASIGNACIONES}))
            p = proyectar_para_custodia(d, self.empresa)
            for datos in captura["bytes"].values():
                self.nube.subir(self.empresa, self.token, datos)
            self.nube.subir(self.empresa, self.token, p.objeto_descriptor)
            self.nube.publicar(self.empresa, self.token, p.descriptor(), p.descriptor_sha256)
            return "PUBLICADA"
        finally:
            if self.token:
                self.nube.liberar(self.empresa, self.token)
                self.token = None


def _objetos_fuente(actual: dict) -> dict[str, str]:
    return {o["ruta"]: "sha256:" + o["sha256"] for o in actual["descriptor"]["objetos"] if o["ruta"] != RUTA_DESCRIPTOR}


def _ruta_real(identidad, actual, nube, empresa) -> str | None:
    """Ruta local de un objeto publicado (identidad -> ruta del contrato; evidencia por documento)."""
    if identidad == RUTA_DESCRIPTOR:
        return None
    for f in FUENTES_FIJAS:
        if f.identidad == identidad:
            return f.ruta
    descriptor = _descriptor_motor(actual, nube, empresa)
    fuente = descriptor.fuente(identidad)
    return _resolver_evidencia_en(fuente.documento, fuente.metadatos.get("lote"))


def _descriptor_motor(actual, nube, empresa):
    sha_obj = next(o["sha256"] for o in actual["descriptor"]["objetos"] if o["ruta"] == RUTA_DESCRIPTOR)
    return dg.leer_descriptor(nube.descargar(empresa, sha_obj))


def _resolver_evidencia_en(documento: str, lote: str | None) -> str:
    return f"{ENTRADAS}{lote}/{documento}"


# ---------------------------------------------------------------- captura
def capturar(raiz: dict[str, bytes], empresa: str, *, entre_pasadas=None, durante_pasada=None) -> dict:
    """Captura bajo turno: inventario explícito desde el contrato + evidencia referida por el dataset.

    Dos pasadas de huella: detecta cambios ENTRE pasadas, no a un escritor no
    gobernado detenido a mitad de operación (ver prueba del límite).
    """
    rutas = [f.ruta for f in FUENTES_FIJAS
             if not (f.tipo == "IDENTIDAD_EMPRESA" and empresa in dg.EMPRESAS_SIN_MARCA)]

    def pasada(numero):
        leidos = {}
        for i, ruta in enumerate(rutas):
            if durante_pasada and numero == 1:
                durante_pasada(i, ruta)
            leidos[ruta] = raiz.get(ruta)
        dataset = leidos.get(RUTA["dataset"])
        evidencia = {}
        if dataset is not None:
            for fila in leer_csv(dataset):
                coincidencias = sorted(r for r in raiz if r.startswith(ENTRADAS) and r.endswith("/" + fila["archivo"]))
                if not coincidencias:
                    # Referida por el dataset y sin binario: nunca se omite en silencio. (La evidencia
                    # PURGADA con metadata es otro caso: requiere su propia regla, no modelada aquí.)
                    raise ErrorProtocolo("EVIDENCIA_NO_ENCONTRADA")
                for r in coincidencias:
                    evidencia[r] = raiz.get(r)
        return leidos, evidencia

    primera = pasada(1)
    if entre_pasadas:
        entre_pasadas()
    segunda = pasada(2)
    if primera != segunda:
        raise ErrorProtocolo("CAPTURA_INESTABLE")
    leidos, evidencia = primera
    fuentes, bytes_por_ruta = [], {}
    for f in FUENTES_FIJAS:
        if f.ruta not in rutas:
            continue
        datos = leidos[f.ruta]
        if datos is None:
            continue  # el descriptor lo rechazará como fuente obligatoria ausente: nunca vacío
        if clasificar(datos) == ILEGIBLE:
            raise ErrorProtocolo("FUENTE_ILEGIBLE")
        fuentes.append(dg.ObjetoFuente(f.identidad, f.tipo, dg.huella_contenido(datos), empresa,
                                       dg.TIPOS_V2[f.tipo].obligatorio, len(datos), rol=f.rol))
        bytes_por_ruta[f.ruta] = datos
    for ruta, datos in evidencia.items():
        documento = ruta.rsplit("/", 1)[1]
        lote = ruta[len(ENTRADAS):].split("/", 1)[0]
        huella = dg.huella_contenido(datos)
        fuentes.append(dg.ObjetoFuente(dg.identidad_evidencia(documento, "original", huella), "EVIDENCIA_DOCUMENTAL",
                                       huella, empresa, False, len(datos), {"lote": lote}, rol="original",
                                       documento=documento))
        bytes_por_ruta[ruta] = datos
    declaracion = {t: 0 for t in dg.TIPOS_V2}
    for o in fuentes:
        declaracion[o.tipo] += 1
    # Una fuente obligatoria ausente no se declara como vacía: el descriptor v2 la rechaza por
    # cardinalidad mínima (FUENTE_OBLIGATORIA_AUSENTE).
    try:
        dg.construir_descriptor(dg.Inventario(2, empresa, dg.GeneracionSolicitada("verificacion", 1), declaracion,
                                              tuple(fuentes), {"ASIGNACIONES": DERIVACION_ASIGNACIONES}))
    except dg.ErrorDescriptor as error:
        raise ErrorProtocolo(error.codigo) from error
    return {"fuentes": fuentes, "declaracion": declaracion, "bytes": bytes_por_ruta}


# ---------------------------------------------------------------- lectores
AUSENTE, ILEGIBLE, VACIA, CON_DATOS = "AUSENTE", "ILEGIBLE", "VACIA", "CON_DATOS"


def clasificar(datos: bytes | None) -> str:
    """Clasificación estricta de una fuente: nunca confunde ausente/ilegible con vacío."""
    if datos is None:
        return AUSENTE
    try:
        texto = datos.decode("utf-8")
        if texto.lstrip().startswith(("{", "[")):
            valor = json.loads(texto)
            colecciones = [v for v in (valor.values() if isinstance(valor, dict) else [valor]) if isinstance(v, (list, dict))]
            vacia = (not valor) or (bool(colecciones) and all(not c for c in colecciones))
            return VACIA if vacia else CON_DATOS
        filas = leer_csv(datos)
        return CON_DATOS if filas else VACIA
    except (UnicodeDecodeError, ValueError, csv.Error):
        return ILEGIBLE


def lector_ingenuo(raiz: dict[str, bytes], ruta: str):
    """Comportamiento actual de varios lectores: ausente o ilegible -> colección vacía."""
    datos = raiz.get(ruta)
    try:
        return json.loads(datos) if datos else {}
    except ValueError:
        return {}


@dataclass(frozen=True)
class Lectura:
    estado: str                         # CONFIABLE | NO_CONFIABLE
    codigo: str = ""
    generacion: str | None = None
    frescura: str = ""                  # ESTABLE | OPERACION_EN_CURSO | INTERRUMPIDA
    fuentes: dict = field(default_factory=dict)   # identidad -> (clase, bytes)


def leer_coherente(nube: NubeModelo, equipo: Equipo, empresa: str) -> Lectura:
    """Vista estable: la última generación publicada, verificada objeto por objeto.

    Nunca combina archivos vivos: usa la copia local sólo si su SHA coincide;
    si no, descarga por empresa y SHA. Cualquier falta es NO_CONFIABLE.
    """
    actual = nube.actual(empresa)
    if actual is None:
        return Lectura("NO_CONFIABLE", "SIN_GENERACION_PUBLICADA")
    try:
        obj = nube.descargar(empresa, next(o["sha256"] for o in actual["descriptor"]["objetos"]
                                           if o["ruta"] == RUTA_DESCRIPTOR))
        motor = verificar_generacion_custodia(actual["descriptor"], actual["descriptor_sha256"], obj or b"", empresa)
    except (dg.ErrorDescriptor, StopIteration) as error:
        return Lectura("NO_CONFIABLE", f"DESCRIPTOR_INVALIDO:{getattr(error, 'codigo', 'FALTA')}")
    local = equipo.raiz(empresa)
    fuentes = {}
    for f in motor.fuentes:
        ruta = _ruta_real(f.identidad, actual, nube, empresa)
        datos = local.get(ruta) if ruta else None
        if datos is None or dg.huella_contenido(datos) != f.huella:
            datos = nube.descargar(empresa, f.huella.removeprefix("sha256:"))
        if datos is None or dg.huella_contenido(datos) != f.huella:
            return Lectura("NO_CONFIABLE", "OBJETO_NO_DISPONIBLE", motor.generacion.generacion_id)
        clase = clasificar(datos) if f.tipo != "EVIDENCIA_DOCUMENTAL" else CON_DATOS
        if clase == ILEGIBLE:
            return Lectura("NO_CONFIABLE", "FUENTE_ILEGIBLE", motor.generacion.generacion_id)
        fuentes[f.identidad] = (clase, datos)
    control = actual["control"]
    e = nube.e(empresa)
    titular_activo = bool(e.token) and e.expira > nube.reloj and control is not None and control["epoca"] == e.epoca
    frescura = "ESTABLE" if control is None else ("OPERACION_EN_CURSO" if titular_activo else "INTERRUMPIDA")
    return Lectura("CONFIABLE", "", motor.generacion.generacion_id, frescura, fuentes)


# ------------------------------------------------------------ operaciones lógicas
def pasos_decision_humana(turno: TurnoEscritor, *, token: str, destino: str, confirmada: bool):
    """Decisión humana con varias escrituras (como aplicar_decision_obra / acciones con token).

    Paso 0: registro de acciones con la confirmación humana (o sólo el preview);
    pasos 1-3: ledger, dataset (dos ventanas de revalidacion_dataset) y bandeja.
    Es un generador: cada ``yield`` es un punto donde puede caer el proceso.
    """
    raiz = turno.equipo.raiz(turno.empresa)
    acciones = json.loads(raiz[RUTA["acciones_operacionales"]])
    acciones["previews"][token] = {"destino": destino, "estado": "CONFIRMADO" if confirmada else "PREVIEW",
                                   **({"confirmacion_recuperable": token} if confirmada else {})}
    turno.escribir(RUTA["acciones_operacionales"], _json(acciones))
    yield "acciones"
    if not confirmada:
        return
    ledger = json.loads(raiz[RUTA["ledger"]])
    if not any(a["token"] == token for a in ledger["aplicaciones"]):
        ledger["aplicaciones"].append({"token": token, "destino": destino, "actor": "HUMANO"})
    turno.escribir(RUTA["ledger"], _json(ledger))
    yield "ledger"
    filas = leer_csv(raiz[RUTA["dataset"]])
    filas[0]["destino"] = destino
    turno.escribir(RUTA["dataset"], _csv(filas))          # ventana 1 de revalidacion_dataset
    yield "dataset-ventana-1"
    filas = leer_csv(raiz[RUTA["dataset"]])
    filas[0]["estado"] = "RESUELTO"
    turno.escribir(RUTA["dataset"], _csv(filas))          # ventana 2
    yield "dataset-ventana-2"
    turno.escribir(RUTA["bandeja"], _json({"decisiones": []}))
    acciones = json.loads(raiz[RUTA["acciones_operacionales"]])
    acciones["previews"][token].pop("confirmacion_recuperable", None)
    acciones["previews"][token]["estado"] = "APLICADO"
    turno.escribir(RUTA["acciones_operacionales"], _json(acciones))
    yield "bandeja-y-cierre"


def ejecutar(pasos, *, caer_en: int | None = None) -> int:
    """Ejecuta un generador de pasos; ``caer_en=k`` simula la caída del proceso tras k pasos."""
    hechos = 0
    for _ in pasos:
        hechos += 1
        if caer_en is not None and hechos >= caer_en:
            return hechos
    return hechos


def recuperar(turno: TurnoEscritor) -> dict:
    """Recuperación tras INTERRUMPIDA (propuesta): reaplica SÓLO confirmaciones humanas ya
    registradas (``confirmacion_recuperable``), idempotente; un preview no confirmado nunca se
    aplica ni se confirma. Después la época vigente asume el PENDIENTE."""
    raiz = turno.equipo.raiz(turno.empresa)
    acciones = json.loads(raiz[RUTA["acciones_operacionales"]])
    reaplicadas, descartadas = [], []
    for token, preview in list(acciones["previews"].items()):
        if preview.get("confirmacion_recuperable") == token:
            ejecutar(pasos_decision_humana(turno, token=token, destino=preview["destino"], confirmada=True))
            reaplicadas.append(token)
        elif preview.get("estado") == "PREVIEW":
            descartadas.append(token)   # queda como preview: sin ledger, sin confirmación
    turno.nube.asumir_recuperacion(turno.empresa, turno.token)
    return {"reaplicadas": reaplicadas, "previews_sin_confirmar": descartadas}


def restaurar_ultima_completa(turno: TurnoEscritor, *, autorizado_por: str) -> list[str]:
    """Relevo tras una interrupción en OTRO equipo (propuesta): exige autorización humana
    explícita y restaura la última generación COMPLETA. Las escrituras parciales no publicadas
    de la época interrumpida se descartan; nunca se aplican ni se confirman."""
    if turno.estado_entrada != "INTERRUMPIDA_EN_OTRO_EQUIPO":
        raise ErrorProtocolo("RELEVO_NO_APLICA")
    if not autorizado_por.strip():
        raise ErrorProtocolo("RELEVO_SIN_AUTORIZACION")
    actual = turno.nube.actual(turno.empresa)
    restauradas = []
    for o in actual["descriptor"]["objetos"]:
        ruta = _ruta_real(o["ruta"], actual, turno.nube, turno.empresa)
        if ruta is None:
            continue
        datos = turno.nube.descargar(turno.empresa, o["sha256"])
        if turno.equipo.raiz(turno.empresa).get(ruta) != datos:
            turno.escribir(ruta, datos)
            restauradas.append(ruta)
    turno.nube.asumir_recuperacion(turno.empresa, turno.token)
    turno.estado_entrada = "RESTAURADA"
    return sorted(restauradas)
