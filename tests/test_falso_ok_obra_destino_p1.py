"""P1 -- lote controlado de 15 guías (20260818): dos documentos quedaban
`OK` aunque Atlas nunca había corroborado su `obra_destino` contra el
catálogo real (guías 464395 y 464479, ver bitácoras).

Causa raíz común: el bloque "OPERACION REAL R2" en `procesar_archivo`
(`atlas_core/procesamiento_masivo.py`) consulta
`_corroborar_obra_destino_confirmada` (que SÍ es la fuente de verdad --
lee `obras_destinos.json` real, read-only) para una `obra_destino` que se
extrajo limpiamente (sin fallback geométrico, sin que el catálogo la
reescribiera) -- pero sólo usaba una respuesta POSITIVA (retirar la
sospecha de `campos_geometricos_sin_corroborar`). Una respuesta negativa
(obra no confirmada) no tenía ningún efecto: como el campo nunca había
entrado a `campos_geometricos_sin_corroborar` por ninguna otra vía, el
motivo `OBRA_DESTINO_SIN_CORROBORAR` nunca se generaba y el documento
terminaba `OK`.

Principio (ver Sección 3 del bloque): un campo correctamente LEÍDO no
implica que esté CORROBORADO contra catálogo -- son preguntas distintas.
`detectar_decisiones_documento` (que sí evalúa el catálogo real de forma
independiente) ya reflejaba esto correctamente en 464395 (decisión
OBRA_DESCONOCIDA generada) pero no en 464479 (donde la regla R3.2 --
"si `obra_destino` es, normalizado, el propio cliente ya reconocido, no
hay entidad nueva que preguntar" -- correctamente NO genera una decisión
de registro; ver test_cliente_igual_obra_no_genera_obra_desconocida en
test_decisiones_pendientes.py). En ningún caso `indicador_revision`
dependía de si detectar_decisiones_documento generó algo: son dos rutas
completamente desacopladas por diseño (`requiere_revision` se calcula
ANTES de invocar `detectar_decisiones_documento`), así que el fix no
podía ser "¿hay una decisión pendiente? -> REVISAR" (acoplamiento
circular) -- tenía que corregirse la evaluación de corroboración de
`obra_destino` en sí misma, independiente de si además corresponde o no
una decisión de registro.
"""
import json

from unittest.mock import Mock

from atlas_core import procesamiento_masivo
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_destinos import CatalogoDestinos
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, TipoEvidencia
from atlas_core.decisiones_pendientes import detectar_decisiones_documento
from atlas_core.procesamiento_masivo import procesar_archivo


def _evidencia(identificador="guia-1"):
    return Evidencia(
        tipo=TipoEvidencia.GUIA.value, identificador_fuente=identificador,
        referencia_hash="a" * 64, campos_observados={"obra": "OBRA"},
        fecha="2026-01-01T00:00:00+00:00", actor_proceso="test", resultado="SOPORTA",
    )


def _cliente(carpeta, *, nombre, rut):
    return CatalogoClientes(carpeta / "clientes.json").crear(
        razon_social=nombre, rut=rut, fuente="PRUEBA",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )


def _catalogos_con_cliente(tmp_path, *, nombre_cliente, rut_cliente):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    cliente = _cliente(carpeta, nombre=nombre_cliente, rut=rut_cliente)
    return carpeta, cliente


def _confirmar_obra(carpeta, cliente, *, nombre_obra, confirmar=True):
    """Registra (y opcionalmente confirma) una obra/relación real en
    `obras_destinos.json`, igual que dejaría un REGISTRAR humano."""
    destino = CatalogoDestinos(carpeta / "destinos_maestros.json", ruta_clientes=carpeta / "clientes.json").crear(
        cliente_id=cliente.cliente_id, nombre_destino=f"DESTINO {nombre_obra}",
        direccion="CALLE 1", pais="CHILE", fuente="PRUEBA",
    )
    catalogo = CatalogoObrasDestinos(
        carpeta / "obras_destinos.json",
        ruta_clientes=carpeta / "clientes.json",
        ruta_destinos=carpeta / "destinos_maestros.json",
    )
    resultado = catalogo.registrar_observacion(
        cliente_id=cliente.cliente_id, nombre_obra=nombre_obra,
        destino_id=destino.destino_id, evidencia=_evidencia(),
    )
    catalogo.registrar_observacion(
        cliente_id=cliente.cliente_id, nombre_obra=nombre_obra,
        destino_id=destino.destino_id, evidencia=_evidencia("guia-2"),
    )
    if confirmar:
        catalogo.confirmar_relacion(resultado.relacion.relacion_id, actor="JAVIER_MBT")
    return catalogo, resultado.relacion.relacion_id


def _procesar(tmp_path, carpeta_catalogos, datos, *, texto_lineal="FECHA DE EMISION 01-01-2026"):
    monkeypatch_targets = {
        "leer_texto_imagen": Mock(return_value=[texto_lineal]),
        "leer_bloques_imagen": Mock(return_value=[]),
        "extraer_datos": Mock(return_value=dict(datos)),
    }
    originales = {nombre: getattr(procesamiento_masivo, nombre) for nombre in monkeypatch_targets}
    for nombre, mock in monkeypatch_targets.items():
        setattr(procesamiento_masivo, nombre, mock)
    try:
        decisiones = []
        resultado = procesar_archivo(
            tmp_path / "guia.jpg", carpeta_catalogos=carpeta_catalogos,
            recolector_decisiones=decisiones.extend, proveedor_rutas=object(),
        )
    finally:
        for nombre, original in originales.items():
            setattr(procesamiento_masivo, nombre, original)
    return resultado, decisiones


def _datos(**overrides):
    datos = {
        "número de guía": "900001", "número de transporte": "0000900001",
        "cliente": "No encontrado", "obra destino": "No encontrado",
        "chofer": "UN CHOFER", "RUT del cliente": "No encontrado",
        "RUT del chofer": "50.234.350-5",
        "patente del tracto": "AB1234", "patente del carro": "CD5678",
    }
    datos.update(overrides)
    return datos


# --- equivalente funcional 464395: obra sin sufijo societario, distinta
#     del cliente, nunca corroborada -- decisión OBRA_DESCONOCIDA correcta,
#     pero el documento quedaba OK (bug real) ---

def test_equivalente_464395_obra_no_corroborada_ya_no_queda_ok(tmp_path):
    carpeta, cliente = _catalogos_con_cliente(
        tmp_path, nombre_cliente="ING Y METALURGICA INGEMETA SPA", rut_cliente="50.234.350-5",
    )
    datos = _datos(
        cliente="ING Y METALURGICA INGEMETA SPA", **{"RUT del cliente": "50.234.350-5"},
        **{"obra destino": "ING Y METALURGICA INGEMETA"},
    )
    resultado, decisiones = _procesar(tmp_path, carpeta, datos)

    # extracción intacta: ni el cliente ni la obra se inventan ni se tocan
    assert resultado["cliente"] == "ING Y METALURGICA INGEMETA SPA"
    assert resultado["obra_destino"] == "ING Y METALURGICA INGEMETA"

    assert resultado["indicador_revision"] == "REVISAR"
    assert "OBRA_DESTINO_SIN_CORROBORAR" in resultado["motivos_revision_documento"]

    decisiones_obra = [d for d in detectar_decisiones_documento(
        archivo="464395.jpeg", datos={
            "número de guía": datos["número de guía"], "cliente": resultado["cliente"],
            "RUT del cliente": datos["RUT del cliente"], "obra destino": resultado["obra_destino"],
        }, carpeta_catalogos=carpeta,
    ) if d["entidad"] == "OBRA"]
    assert [d["tipo"] for d in decisiones_obra] == ["OBRA_DESCONOCIDA"]
    assert decisiones_obra[0]["motivos"] == ["OBRA_NO_EXISTE_PARA_CLIENTE"]


# --- equivalente funcional 464479: obra_destino idéntica al cliente ya
#     reconocido -- R3.2 correctamente NO pide registrar una entidad nueva
#     (mismo hecho dos veces), pero eso no equivale a "corroborado": el
#     documento debía quedar REVISAR igual, con una causa DISTINTA a
#     OBRA_DESCONOCIDA (no hay decisión de registro pendiente) ---

def test_equivalente_464479_obra_igual_a_cliente_ya_no_queda_ok(tmp_path):
    carpeta, cliente = _catalogos_con_cliente(
        tmp_path, nombre_cliente="AMERICAN SCREW CHILE SPA", rut_cliente="90.970.000-0",
    )
    datos = _datos(
        cliente="AMERICAN SCREW CHILE SPA", **{"RUT del cliente": "90.970.000-0"},
        **{"obra destino": "AMERICAN SCREW CHILE SPA"},
    )
    resultado, decisiones = _procesar(tmp_path, carpeta, datos)

    assert resultado["cliente"] == "AMERICAN SCREW CHILE SPA"
    assert resultado["obra_destino"] == "AMERICAN SCREW CHILE SPA"

    assert resultado["indicador_revision"] == "REVISAR"
    assert "OBRA_DESTINO_SIN_CORROBORAR" in resultado["motivos_revision_documento"]

    # causa distinta documentada: R3.2 (regla de Javier) se preserva -- no
    # hay una obra NUEVA que registrar porque es el mismo cliente dos
    # veces, así que no corresponde OBRA_DESCONOCIDA ni DESTINO_SIN_CONFIRMAR.
    decisiones_obra = [d for d in detectar_decisiones_documento(
        archivo="464479.jpeg", datos={
            "número de guía": datos["número de guía"], "cliente": resultado["cliente"],
            "RUT del cliente": datos["RUT del cliente"], "obra destino": resultado["obra_destino"],
        }, carpeta_catalogos=carpeta,
    ) if d["entidad"] in {"OBRA", "RELACION_OBRA_DESTINO"}]
    assert decisiones_obra == []


# --- obra conocida (confirmada + relación confirmada): sigue OK, sin
#     motivo ni decisiones redundantes ---

def test_obra_conocida_confirmada_sigue_ok_sin_decisiones_redundantes(tmp_path):
    carpeta, cliente = _catalogos_con_cliente(
        tmp_path, nombre_cliente="ARMACERO MATCO SA", rut_cliente="76.123.987-2",
    )
    _confirmar_obra(carpeta, cliente, nombre_obra="ARMACERO MATCO SA", confirmar=True)
    datos = _datos(
        cliente="ARMACERO MATCO SA", **{"RUT del cliente": "76.123.987-2"},
        **{"obra destino": "ARMACERO MATCO SA"},
    )
    resultado, _ = _procesar(tmp_path, carpeta, datos)

    assert resultado["indicador_revision"] == "OK"
    assert "OBRA_DESTINO_SIN_CORROBORAR" not in resultado["motivos_revision_documento"]
    assert "CATALOGO_OBRA_DESTINO" in resultado["metodos_recuperacion_documento"]

    decisiones_obra = [d for d in detectar_decisiones_documento(
        archivo="464511.jpeg", datos={
            "número de guía": datos["número de guía"], "cliente": resultado["cliente"],
            "RUT del cliente": datos["RUT del cliente"], "obra destino": resultado["obra_destino"],
        }, carpeta_catalogos=carpeta,
    ) if d["entidad"] in {"OBRA", "RELACION_OBRA_DESTINO"}]
    assert decisiones_obra == []


# --- obra nueva (genérica, distinta del cliente): REVISAR + motivo +
#     decisión OBRA_DESCONOCIDA coherentes entre sí ---

def test_obra_nueva_genera_motivo_y_decision_coherentes(tmp_path):
    carpeta, cliente = _catalogos_con_cliente(
        tmp_path, nombre_cliente="CONSTRUMART SA", rut_cliente="50.234.350-5",
    )
    datos = _datos(
        cliente="CONSTRUMART SA", **{"RUT del cliente": "50.234.350-5"},
        **{"obra destino": "CONSTRUCTORA INMOBILIARIA NUEVA"},
    )
    resultado, _ = _procesar(tmp_path, carpeta, datos)

    assert resultado["obra_destino"] == "CONSTRUCTORA INMOBILIARIA NUEVA"
    assert resultado["indicador_revision"] == "REVISAR"
    assert "OBRA_DESTINO_SIN_CORROBORAR" in resultado["motivos_revision_documento"]

    decisiones_obra = [d for d in detectar_decisiones_documento(
        archivo="900001.jpeg", datos={
            "número de guía": datos["número de guía"], "cliente": resultado["cliente"],
            "RUT del cliente": datos["RUT del cliente"], "obra destino": resultado["obra_destino"],
        }, carpeta_catalogos=carpeta,
    ) if d["entidad"] == "OBRA"]
    assert [d["tipo"] for d in decisiones_obra] == ["OBRA_DESCONOCIDA"]
    assert decisiones_obra[0]["motivos"] == ["OBRA_NO_EXISTE_PARA_CLIENTE"]


# --- destino pendiente (R3.4): la obra ya se conoce (CANDIDATA/vigente),
#     pero la relación con ESTE destino aún no está confirmada -- sigue
#     generando DESTINO_SIN_CONFIRMAR (nunca OBRA_DESCONOCIDA), y ahora el
#     documento tampoco queda OK silencioso (mismo principio: sigue
#     pendiente una decisión humana) ---

def test_destino_pendiente_mantiene_destino_sin_confirmar_y_pide_revision(tmp_path):
    carpeta, cliente = _catalogos_con_cliente(
        tmp_path, nombre_cliente="CONSTRUMART SA", rut_cliente="50.234.350-5",
    )
    _confirmar_obra(carpeta, cliente, nombre_obra="OBRA UNO", confirmar=False)
    datos = _datos(
        cliente="CONSTRUMART SA", **{"RUT del cliente": "50.234.350-5"},
        **{"obra destino": "OBRA UNO"},
    )
    resultado, _ = _procesar(tmp_path, carpeta, datos)

    assert resultado["indicador_revision"] == "REVISAR"
    assert "OBRA_DESTINO_SIN_CORROBORAR" in resultado["motivos_revision_documento"]

    decisiones_obra = [d for d in detectar_decisiones_documento(
        archivo="900001.jpeg", datos={
            "número de guía": datos["número de guía"], "cliente": resultado["cliente"],
            "RUT del cliente": datos["RUT del cliente"], "obra destino": resultado["obra_destino"],
        }, carpeta_catalogos=carpeta,
    ) if d["entidad"] in {"OBRA", "RELACION_OBRA_DESTINO"}]
    assert [d["tipo"] for d in decisiones_obra] == ["DESTINO_SIN_CONFIRMAR"]


# --- cliente no resoluble: sin identidad maestra contra la cual juzgar la
#     obra, Atlas se abstiene (conservador) -- no inventa un motivo sin base ---

def test_cliente_no_resoluble_no_fuerza_motivo_de_obra(tmp_path):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    (carpeta / "clientes.json").write_text(
        json.dumps({"version_formato": 1, "clientes": []}), encoding="utf-8",
    )
    datos = _datos(
        cliente="CLIENTE JAMAS VISTO SPA", **{"obra destino": "OBRA CUALQUIERA"},
    )
    resultado, _ = _procesar(tmp_path, carpeta, datos)

    assert "OBRA_DESTINO_SIN_CORROBORAR" not in resultado["motivos_revision_documento"]


# --- idempotencia y no-duplicados: procesar dos veces el mismo documento
#     (catálogos read-only) produce el mismo resultado, sin duplicar
#     motivos ni decisiones, y otros motivos independientes (patente sin
#     homologar) siguen coexistiendo sin interferencia ---

def test_idempotencia_no_duplica_motivos_ni_decisiones_y_preserva_motivos_independientes(tmp_path):
    carpeta, cliente = _catalogos_con_cliente(
        tmp_path, nombre_cliente="ING Y METALURGICA INGEMETA SPA", rut_cliente="50.234.350-5",
    )
    antes = {p.name: p.read_bytes() for p in carpeta.iterdir()}
    # sin "descripcion material" -> MATERIAL_AUSENTE (motivo independiente,
    # no bloqueante) debe coexistir con OBRA_DESTINO_SIN_CORROBORAR sin que
    # ninguno de los dos se duplique ni se pisen entre sí.
    datos = _datos(
        cliente="ING Y METALURGICA INGEMETA SPA", **{"RUT del cliente": "50.234.350-5"},
        **{"obra destino": "ING Y METALURGICA INGEMETA"},
    )

    resultado_1, decisiones_1 = _procesar(tmp_path, carpeta, datos)
    resultado_2, decisiones_2 = _procesar(tmp_path, carpeta, datos)

    for resultado in (resultado_1, resultado_2):
        motivos = resultado["motivos_revision_documento"].split(" | ")
        assert motivos.count("OBRA_DESTINO_SIN_CORROBORAR") == 1
        assert motivos.count("MATERIAL_AUSENTE") == 1
        assert resultado["indicador_revision"] == "REVISAR"

    assert resultado_1 == resultado_2
    assert [d["decision_id"] for d in decisiones_1] == [d["decision_id"] for d in decisiones_2]
    assert len(decisiones_1) == len(set(d["decision_id"] for d in decisiones_1))
    # read-only: los catálogos reales nunca se tocan al procesar
    assert {p.name: p.read_bytes() for p in carpeta.iterdir()} == antes
