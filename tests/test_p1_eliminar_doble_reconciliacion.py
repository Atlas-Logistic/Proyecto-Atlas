"""ATLAS — RENDIMIENTO DECISIONES P1: ELIMINAR DOBLE RECONCILIACIÓN.

Verifica, sobre el flujo REAL (Fase 1 `revalidar_y_regenerar_reporte`
seguida de Fase 2 `reconciliar_estado_derivado`, nunca stubs puros), que
Fase 2 se abstiene de repetir las 18 funciones de `FUNCIONES_BATERIA_
COMPARTIDA` SÓLO cuando la firma de frescura demuestra que Fase 1 ya las
corrió contra el mismo estado exacto -- y que CUALQUIER duda (catálogo
cambiado, dataset cambiado, versión de reglas/capacidades cambiada, o
firma ausente) hace que la batería completa corra, sin excepción.

El fixture de los escenarios A-E es una fila YA completamente resuelta
(`indicador_revision=OK`, sin motivos, ruta calculada) -- nada que
converger para NINGUNA función, ni las 18 compartidas ni las exclusivas
de Fase 2 (replay P0, convergencia de identidad, etc.). Se fuerza la
entrada a Fase 1/Fase 2 invalidando el hash publicado en `estado_
operacion.json` (exactamente lo que hace, en producción, que el dataset
avance por CUALQUIER otra vía -- una decisión aplicada en otra fila, un
envío Mobile) -- nunca por tener un motivo genuinamente pendiente, que
sería un escenario distinto (Fase 2 SÍ debe encontrar trabajo real, y el
mecanismo debe -- y en un test aparte, se prueba que lo hace --
detectarlo y dejar de omitir).

Escenarios A-F del pedido P1."""
import csv
import json

from atlas_core.almacenamiento_portable import leer_estado_operacion
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.reconciliacion_estado_derivado import reconciliar_estado_derivado
from atlas_core import reconciliacion_estado_derivado as modulo_fase2
from atlas_core.revalidacion_documental import revalidar_y_regenerar_reporte
from atlas_core import revalidacion_documental as modulo_fase1

FUNCION_SONDA = "revalidar_obra_destino_sin_ocr"


def _catalogos_base(carpeta):
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []}, "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")


def _fila_ya_resuelta(**overrides):
    """Fila estable: nada pendiente para ninguna función de la batería
    (compartida o exclusiva) -- ver docstring del módulo."""
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "x.jpeg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "T1", "fecha": "01-08-2026",
        "indicador_revision": "OK", "estado_documental": "OK", "estado_operacional": "OK",
        "planta_origen_id": "planta-1", "planta_origen_nombre": "PLANTA 1",
        "cliente": "CLIENTE ESTABLE SA", "obra_destino": "OBRA ESTABLE",
        "despachar_a_crudo": "CALLE FALSA 123", "direccion_entrega": "CALLE FALSA 123",
        "estado_ruta": "RUTA_CALCULADA", "motivo_ruta": "",
        "distancia_km": "12", "duracion_min": "20", "proveedor_ruta": "TEST",
        "motivos_revision_documento": "",
    })
    fila.update(overrides)
    return fila


def _fila_otro_viaje_atascado():
    """Viaje AJENO, permanentemente pendiente (destino disperso, sin
    relación con lo que Fase 1 resuelve) -- representa, de forma
    realista, que una operación real casi siempre tiene ALGO más
    pendiente en otro lado. Es justamente ese "algo más" el que hoy
    fuerza a `reconciliar_estado_derivado` a entrar a la batería completa
    (vía `por_reintentar`) incluso cuando el viaje que Fase 1 acaba de
    tocar ya quedó perfecto -- el escenario real que P1 ataca."""
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "atascado.jpeg", "estado_procesamiento": "OK", "numero_guia": "999",
        "numero_transporte": "T999", "fecha": "01-08-2026",
        "indicador_revision": "REVISAR", "estado_documental": "REQUIERE_REVISION",
        "estado_operacional": "REQUIERE_REVISION", "planta_origen_id": "planta-1",
        "cliente": "CLIENTE ATASCADO SA", "obra_destino": "OBRA ATASCADA",
        "despachar_a_crudo": "MULTIPLES DIRECCIONES", "estado_ruta": "REQUIERE_REVISION",
        "motivo_ruta": "MULTIPLES_UBICACIONES_DISPERSAS(5)",
    })
    return fila


def _entorno_estable(tmp_path, *, numero_guia="1"):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    dataset = actual / "analisis_completo_guias.csv"
    primera_vez = not raiz.exists()
    if primera_vez:
        (raiz / "reportes").mkdir(parents=True)
        catalogos.mkdir(parents=True)
        actual.mkdir(parents=True)
        _catalogos_base(catalogos)
    filas_previas = []
    if dataset.is_file():
        with dataset.open("r", newline="", encoding="utf-8-sig") as archivo:
            filas_previas = list(csv.DictReader(archivo, delimiter=";"))
    fila = _fila_ya_resuelta(
        archivo=f"{numero_guia}.jpeg", numero_guia=numero_guia, numero_transporte=f"T{numero_guia}",
    )
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        for f in filas_previas:
            escritor.writerow(f)
        escritor.writerow(fila)
        if primera_vez:
            escritor.writerow(_fila_otro_viaje_atascado())
    ruta_decisiones = actual / "decisiones_pendientes.json"
    if not ruta_decisiones.is_file():
        ruta_decisiones.write_text(json.dumps({"decisiones": []}), encoding="utf-8")
    return raiz


def _forzar_reentrada(raiz):
    """Simula "algo más movió el dataset" (cualquier otra decisión, un
    envío Mobile) SIN tocar el contenido real de la fila -- invalida sólo
    el hash publicado, para que Fase 1/Fase 2 decidan reconciliar de
    nuevo pese a que, semánticamente, no hay nada pendiente.

    Requiere una publicación previa REAL (`reporte_vigente` apuntando a
    una carpeta que de verdad existe, con `huella_filas_dataset` ya
    presente) -- de lo contrario `revalidar_y_regenerar_reporte` trata el
    manifiesto como inválido y NUNCA llega a publicar una firma, lo que
    invalidaría cualquier escenario que dependa de que Fase 1 sí la
    escribió. Si todavía no hay manifiesto, se establece uno genuino
    corriendo `reconciliar_estado_derivado` una vez (equivalente real:
    toda operación pasó por al menos una reconciliación -- `migracion`
    (versión 0 -> vigente) es siempre True en esa primera corrida, así
    que publica un manifiesto real sin necesitar ningún motivo
    pendiente). Nunca un manifiesto fabricado a mano."""
    actual = raiz / "operacion" / "actual"
    estado_ruta = actual / "estado_operacion.json"
    if not estado_ruta.is_file():
        base = reconciliar_estado_derivado(raiz_atlas=raiz)
        assert base["reconciliado"] is True, "no se pudo establecer una publicación base real"
    estado = json.loads(estado_ruta.read_text(encoding="utf-8"))
    estado["dataset_sha256"] = "0" * 64
    # Fuerza que `reconciliar_estado_derivado` entre SIEMPRE a la batería
    # (no sólo la primera vez) -- se rebaja artificialmente una
    # capacidad en el manifiesto PUBLICADO (nunca en la registrada, que
    # es la que ambas fases usan para calcular la firma real) para que
    # `capacidades_a_reevaluar` nunca quede vacío. Representa, de forma
    # determinística y sin depender de cooldowns, el caso real: siempre
    # hay ALGO en la operación (otro viaje, otra capacidad) que fuerza la
    # entrada al bloque completo, incluso cuando el viaje que Fase 1
    # acaba de tocar ya no tiene nada pendiente.
    capacidades = dict(estado.get("versiones_capacidades") or {})
    if capacidades:
        clave = next(iter(capacidades))
        capacidades[clave] = max(0, int(capacidades[clave]) - 1)
        estado["versiones_capacidades"] = capacidades
    estado_ruta.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")


def _contador(monkeypatch, nombre):
    """Envuelve la función REAL (nunca la reemplaza) en ambos módulos --
    Fase 1 y Fase 2 tienen cada uno su propio `from ... import`, así que
    parchear un solo namespace no basta. Cuenta llamadas sin cambiar
    comportamiento."""
    original = getattr(modulo_fase1, nombre)
    llamadas = {"fase1": 0, "fase2": 0}

    def envoltura_fase1(*args, **kwargs):
        llamadas["fase1"] += 1
        return original(*args, **kwargs)

    def envoltura_fase2(*args, **kwargs):
        llamadas["fase2"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(modulo_fase1, nombre, envoltura_fase1)
    monkeypatch.setattr(modulo_fase2, nombre, envoltura_fase2)
    return llamadas


def test_A_sin_cambios_externos_fase2_omite_bateria_compartida(tmp_path, monkeypatch):
    raiz = _entorno_estable(tmp_path)
    _forzar_reentrada(raiz)
    llamadas = _contador(monkeypatch, FUNCION_SONDA)

    r1 = revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_a")
    assert r1["reporte_regenerado"] is True
    assert llamadas["fase1"] == 1
    assert bool(leer_estado_operacion(raiz=raiz).get("firma_bateria_compartida")) is True

    r2 = reconciliar_estado_derivado(raiz_atlas=raiz)
    assert r2["reconciliado"] is True
    assert llamadas["fase2"] == 0, "Fase 2 debía omitir la función compartida -- nada cambió desde Fase 1"


def test_B_catalogo_cambia_entre_fases_fuerza_bateria_completa(tmp_path, monkeypatch):
    raiz = _entorno_estable(tmp_path)
    _forzar_reentrada(raiz)
    llamadas = _contador(monkeypatch, FUNCION_SONDA)
    revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_b")
    assert llamadas["fase1"] == 1

    # Un catálogo cambia por una vía AJENA a Fase 1 entre que Fase 1
    # termina y Fase 2 arranca.
    from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
    CatalogoClientes((raiz / "catalogos_privados" / "clientes.json")).crear(
        razon_social="OTRO CLIENTE SA", rut="76.083.093-3", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )

    reconciliar_estado_derivado(raiz_atlas=raiz)
    assert llamadas["fase2"] == 1, "un catálogo distinto debía invalidar la firma -- batería completa"


def test_C_dataset_cambia_entre_fases_fuerza_bateria_completa(tmp_path, monkeypatch):
    raiz = _entorno_estable(tmp_path)
    _forzar_reentrada(raiz)
    llamadas = _contador(monkeypatch, FUNCION_SONDA)
    revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_c")
    assert llamadas["fase1"] == 1

    # El dataset avanza por una vía AJENA a Fase 1 (p. ej. un envío Mobile
    # o un segundo lote) entre que Fase 1 termina y Fase 2 arranca.
    _entorno_estable(tmp_path, numero_guia="2")

    reconciliar_estado_derivado(raiz_atlas=raiz)
    assert llamadas["fase2"] == 1, "el dataset cambió -- batería completa"


def test_D_version_capacidades_cambia_fuerza_bateria_completa(tmp_path, monkeypatch):
    raiz = _entorno_estable(tmp_path)
    _forzar_reentrada(raiz)
    llamadas = _contador(monkeypatch, FUNCION_SONDA)
    revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_d")
    assert llamadas["fase1"] == 1

    # Simula que una capacidad avanzó de versión ENTRE que Fase 1 firmó y
    # Fase 2 recalcula -- la firma de Fase 2 ya no puede coincidir.
    from atlas_core.capacidades_reevaluacion import versiones_actuales

    def _versiones_bump():
        actuales = dict(versiones_actuales())
        clave = next(iter(actuales))
        actuales[clave] = actuales[clave] + 1
        return actuales

    monkeypatch.setattr("atlas_core.capacidades_reevaluacion.versiones_actuales", _versiones_bump)

    reconciliar_estado_derivado(raiz_atlas=raiz)
    assert llamadas["fase2"] == 1, "versión de capacidades distinta -- batería completa"


def test_E_firma_ausente_fuerza_bateria_completa(tmp_path, monkeypatch):
    """Fase 2 corre SIN que Fase 1 haya corrido nunca (o su firma se
    perdió/no se escribió) -- fallback conservador de siempre."""
    raiz = _entorno_estable(tmp_path)
    _forzar_reentrada(raiz)
    llamadas = _contador(monkeypatch, FUNCION_SONDA)

    reconciliar_estado_derivado(raiz_atlas=raiz)
    assert llamadas["fase2"] == 1, "sin firma previa, Fase 2 nunca debe omitir nada"


def test_E_firma_corrupta_fuerza_bateria_completa(tmp_path, monkeypatch):
    raiz = _entorno_estable(tmp_path)
    _forzar_reentrada(raiz)
    llamadas = _contador(monkeypatch, FUNCION_SONDA)
    revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_e2")
    assert llamadas["fase1"] == 1

    manifiesto = raiz / "operacion" / "actual" / "estado_operacion.json"
    contenido = json.loads(manifiesto.read_text(encoding="utf-8"))
    contenido["firma_bateria_compartida"] = "no-es-una-firma-real"
    manifiesto.write_text(json.dumps(contenido, ensure_ascii=False), encoding="utf-8")

    reconciliar_estado_derivado(raiz_atlas=raiz)
    assert llamadas["fase2"] == 1, "una firma que no coincide debe caer al comportamiento de siempre"


def test_trabajo_real_exclusivo_de_fase2_invalida_la_omision_a_mitad_de_pasada(tmp_path, monkeypatch):
    """Contraprueba de seguridad: si una función EXCLUSIVA de Fase 2 (no
    compartida, corre ANTES o ENTREMEDIO de las 18) encuentra trabajo
    real que Fase 1 nunca pudo haber hecho (Fase 1 no la ejecuta), la
    omisión debe desactivarse desde ese punto en adelante -- nunca un
    falso positivo. Se fuerza con una fila CLIENTE_AUSENTE cuya obra
    coincide con un cliente confirmado: `revalidar_convergencia_
    identidad_sin_ocr` (exclusiva de Fase 2) la resuelve; las llamadas
    compartidas posteriores a ese punto deben volver a correr de verdad."""
    from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
    from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto

    llamadas = _contador(monkeypatch, FUNCION_SONDA)
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True)
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="TORRES OCARANZA LTDA", rut="50.234.350-5", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    dataset = actual / "analisis_completo_guias.csv"
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "472238.jpeg", "estado_procesamiento": "OK", "numero_guia": "472238",
        "numero_transporte": "T-472238", "fecha": "01-08-2026",
        "indicador_revision": "REVISAR", "planta_origen_id": "planta-1",
        "cliente": "No encontrado", "obra_destino": "TORRES OCARANZA LTDA",
        "motivos_revision_documento": "CLIENTE_AUSENTE",
    })
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerow(fila)
    decision = crear_decision(
        tipo="CLIENTE_AUSENTE", entidad="CLIENTE", archivo="472238.jpeg", numero_guia="472238",
        numero_transporte="T-472238", campo="cliente", valor_documental="", valor_normalizado="",
        identidad_resuelta=None, candidatos=(), motivos=("CLIENTE_AUSENTE",),
        evidencias=(), acciones_permitidas=("REGISTRAR_CLIENTE_MANUAL", "NO_PUEDO_DETERMINAR", "POSPONER"),
    )
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision], ruta_salida=actual / "decisiones_pendientes.json")

    r1 = revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_seguridad")
    assert r1["reporte_regenerado"] is True
    assert bool(leer_estado_operacion(raiz=raiz).get("firma_bateria_compartida")) is True

    r2 = reconciliar_estado_derivado(raiz_atlas=raiz)
    assert r2["reconciliado"] is True
    # Si Fase 1 no dejó `cliente` ya resuelto y una función exclusiva de
    # Fase 2 encontró y aplicó la convergencia, la sonda compartida
    # (posterior en el orden real de la batería) tuvo que volver a
    # correr -- NUNCA quedarse omitida por una firma que ya no describe
    # el estado actual.
    dataset_final = dataset.read_text(encoding="utf-8")
    if "No encontrado" not in dataset_final.split("\n", 1)[1]:
        assert llamadas["fase2"] >= 1, (
            "el dataset cambió durante Fase 2 (fuera de las 18 compartidas) "
            "pero la sonda compartida posterior no se re-ejecutó -- falso positivo"
        )


def test_F_varias_decisiones_antes_de_una_sola_reconciliacion(tmp_path, monkeypatch):
    """Dos aplicaciones de Fase 1 (dos "decisiones", cada una agregando
    un viaje nuevo) antes de UNA sola Fase 2 -- el resultado debe
    reflejar AMBAS de forma coherente (nunca una reconciliación a
    medias). NO se exige que Fase 2 omita la batería compartida aquí:
    la SEGUNDA fila es enteramente nueva para Fase 2 (nunca pasó por
    convergencia de identidad / recuperación P0 -- funciones exclusivas
    de Fase 2 que Fase 1 no corre), así que es correcto -- y seguro --
    que la firma no coincida y la batería corra completa. Ver el test de
    la firma fija (A) para el caso "nada nuevo en absoluto"; este test
    cubre la coherencia del resultado con múltiples aplicaciones."""
    raiz = _entorno_estable(tmp_path, numero_guia="1")
    _forzar_reentrada(raiz)
    llamadas = _contador(monkeypatch, FUNCION_SONDA)
    r1 = revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_f1")
    assert r1["reporte_regenerado"] is True
    assert llamadas["fase1"] == 1

    _entorno_estable(tmp_path, numero_guia="2")
    r1b = revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_f2")
    assert r1b["reporte_regenerado"] is True
    assert llamadas["fase1"] == 2

    r2 = reconciliar_estado_derivado(raiz_atlas=raiz)
    assert r2["reconciliado"] is True

    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    with dataset.open("r", newline="", encoding="utf-8-sig") as archivo:
        guias = {f["numero_guia"] for f in csv.DictReader(archivo, delimiter=";")}
    assert {"1", "2"} <= guias, "ambas guías deben seguir presentes tras la reconciliación única"


def test_bateria_omitida_produce_resultado_equivalente_a_bateria_completa(tmp_path, monkeypatch):
    """Comparación funcional antes/después (no sólo conteo de llamadas):
    el CSV final y `decisiones_pendientes.json` deben ser equivalentes si
    Fase 2 omite la batería compartida o si la corre completa -- porque,
    por construcción, cuando la omite es porque ya es un no-op."""
    raiz_a = _entorno_estable(tmp_path / "con_omision")
    _forzar_reentrada(raiz_a)
    revalidar_y_regenerar_reporte(raiz_atlas=raiz_a, nombre_carpeta_reporte="reporte_omitido")
    r2_omitido = reconciliar_estado_derivado(raiz_atlas=raiz_a)

    raiz_b = _entorno_estable(tmp_path / "sin_omision")
    _forzar_reentrada(raiz_b)
    revalidar_y_regenerar_reporte(raiz_atlas=raiz_b, nombre_carpeta_reporte="reporte_control")
    # Se invalida deliberadamente la firma para forzar la batería
    # completa en el control, y así comparar contra el camino corto.
    manifiesto_b = raiz_b / "operacion" / "actual" / "estado_operacion.json"
    contenido_b = json.loads(manifiesto_b.read_text(encoding="utf-8"))
    contenido_b.pop("firma_bateria_compartida", None)
    manifiesto_b.write_text(json.dumps(contenido_b, ensure_ascii=False), encoding="utf-8")
    r2_completo = reconciliar_estado_derivado(raiz_atlas=raiz_b)

    assert r2_omitido["reconciliado"] == r2_completo["reconciliado"]
    assert r2_omitido["pendientes_tecnicos"] == r2_completo["pendientes_tecnicos"]
    assert r2_omitido["totales"] == r2_completo["totales"]

    dataset_a = (raiz_a / "operacion" / "actual" / "analisis_completo_guias.csv").read_text(encoding="utf-8")
    dataset_b = (raiz_b / "operacion" / "actual" / "analisis_completo_guias.csv").read_text(encoding="utf-8")
    assert dataset_a == dataset_b

    decisiones_a = json.loads((raiz_a / "operacion" / "actual" / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    decisiones_b = json.loads((raiz_b / "operacion" / "actual" / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    assert decisiones_a["decisiones"] == decisiones_b["decisiones"]
