"""Bloque REGENERACIÓN B1 -- dos causas raíz reales encontradas al
investigar por qué AUSIN SAN BERNARDO revivía y 472037/472044 perdían
el contexto B1 enriquecido:

1. `aplicar_decision_obra` regeneraba la bandeja sobre `artefacto`, la
   copia en memoria leída al PRINCIPIO de la función -- si una rama
   anterior de la misma llamada ya había republicado
   `decisiones_pendientes.json` en disco (vía `revalidar_y_regenerar_
   reporte`, que puede refrescar el contexto B1 de OTRAS decisiones),
   regenerar sobre esa copia vieja y reescribir el archivo descartaba
   silenciosamente lo que el disco ya tenía.
2. `resolver_obra_destino_confirmada_global` exige EXACTAMENTE una
   relación obra<->destino confirmada -- ante dos confirmaciones
   humanas/de evidencia DISTINTAS sobre variantes de texto OCR de la
   MISMA dirección real (evidencia redundante, nunca una contradicción),
   empezó a devolver `None`, y la supresión de `DESTINO_NO_RESUELTO`
   que depende de él dejó de funcionar."""
from __future__ import annotations

import csv
import json

from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, ResultadoEvidencia, TipoEvidencia
from atlas_core.decisiones_pendientes import (
    _decisiones_obra_para_cliente, crear_decision, detectar_decision_destino_no_resuelto,
    generar_artefacto, regenerar_decisiones_persistidas,
)
from atlas_core.procesamiento_masivo import COLUMNAS


def _catalogos_base(carpeta):
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []}, "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "x.jpeg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "T1", "fecha": "01-08-2026",
        "indicador_revision": "OK", "planta_origen_id": "planta-1",
    })
    fila.update(overrides)
    return fila


def _escribir_dataset(actual, filas):
    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerows(filas)
    return dataset


def _pendientes(actual):
    return json.loads((actual / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]


def _traza_b1(explicacion):
    return json.dumps([{
        "dominio": "DESTINO", "campo": "despachar_a_crudo", "llamada_realizada": True,
        "estado": "ABSTENCION_IA", "clasificacion": "C_ABSTENCION",
        "hipotesis": {"explicacion": explicacion, "valor_propuesto": ""},
        "contexto_final": {"evidencias": [{"tipo_fuente": "EXTERNO", "referencias_fuente": ["Fuente <https://x.cl>"]}]},
    }])


# --- Invariante 3: la regeneración disparada por aplicar OTRA decisión
# nunca descarta el contexto B1 de una decisión distinta. ---

def test_aplicar_otra_decision_no_pierde_contexto_b1_de_decision_distinta(tmp_path):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"; actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True); catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="CLIENTE CANONICO SA", rut="50.234.350-5", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    fila_obra_desconocida = _fila(
        archivo="100.jpeg", numero_guia="100", cliente="CLIENTE CANONICO SA", obra_destino="OBRA NUEVA",
        indicador_revision="REVISAR", motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR",
    )
    fila_destino = _fila(
        archivo="472037.jpeg", numero_guia="472037", despachar_a_crudo="VICUÑA MACKENNA 655",
        obra_destino="ING Y CONST FUNDAMENTA SPA", cliente="COMERCIAL A Y B LTDA",
        motivo_ruta="MULTIPLES_UBICACIONES_DISPERSAS(5)", estado_ruta="REQUIERE_REVISION",
        resultado_atlas_ia_json=_traza_b1("Evidencia real que vincula la obra con Vicuña Mackenna 655."),
    )
    dataset = _escribir_dataset(actual, [fila_obra_desconocida, fila_destino])

    decision_obra = crear_decision(
        tipo="OBRA_DESCONOCIDA", entidad="OBRA", archivo="100.jpeg",
        numero_guia="100", numero_transporte="T1", campo="obra_destino",
        valor_documental="OBRA NUEVA", valor_normalizado="OBRA NUEVA", identidad_resuelta=None,
        candidatos=(), motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),
        evidencias=({"tipo": "CLIENTE_RESUELTO", "entidad_id": cliente.cliente_id},),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        contexto={"cliente_id": cliente.cliente_id, "cliente_canonico": cliente.razon_social},
    )
    # `decision_destino` se publica SIN contexto B1 -- simula que B1
    # investigó DESPUÉS de que la tarjeta ya existiera (exactamente el
    # escenario real).
    decision_destino = detectar_decision_destino_no_resuelto(archivo="472037.jpeg", fila={**fila_destino, "resultado_atlas_ia_json": ""})
    assert "b1_resumen_hallazgo" not in decision_destino["contexto"]
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision_obra, decision_destino],
        ruta_salida=actual / "decisiones_pendientes.json",
    )

    # Aplicar la decisión de OBRA (acción "REGISTRAR", fuera de
    # TIPOS_CON_REGENERACION_DIRECTA) dispara `revalidar_y_regenerar_
    # reporte` internamente -- que SÍ ve la fila 472037 con
    # `resultado_atlas_ia_json` ya poblado y refresca su contexto B1.
    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision_obra["decision_id"], accion="REGISTRAR")
    assert resultado["ok"] is True

    pendientes = _pendientes(actual)
    destino_final = next(d for d in pendientes if d["documento"]["numero_guia"] == "472037")
    assert destino_final["contexto"].get("b1_resumen_hallazgo") == "Evidencia real que vincula la obra con Vicuña Mackenna 655."


# --- Invariantes 1 y 2: AUSIN -- decisión resuelta no revive, familia
# hermana reutiliza el aprendizaje, incluso con DOS relaciones
# confirmadas redundantes (nunca una contradicción real). ---

def test_dos_relaciones_confirmadas_redundantes_suprimen_ambas_guias_hermanas(tmp_path):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"; actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True); catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="AUSIN HNOS LTDA", rut="76.111.111-6", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    catalogo_obras = CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    )

    def _confirmar(texto_destino, guia):
        resultado_obs = catalogo_obras.registrar_observacion(
            cliente_id=cliente.cliente_id, nombre_obra="AUSIN SAN BERNARDO",
            destino_id=CatalogoDestinos(
                catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json",
            ).crear(
                cliente_id="", nombre_destino=texto_destino, direccion=texto_destino,
                pais="CHILE", fuente="TEST", estado_calidad=EstadoCalidadDestino.CONFIRMADO,
            ).destino_id,
            evidencia=Evidencia(
                tipo=TipoEvidencia.GUIA.value, identificador_fuente=guia, referencia_hash="a" * 64,
                campos_observados={"obra": "AUSIN SAN BERNARDO", "destino": texto_destino},
                fecha="2026-01-01T00:00:00+00:00", actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value,
            ),
        )
        relacion = resultado_obs.relacion
        if relacion.estado == "PENDIENTE":
            catalogo_obras.confirmar_relacion(relacion.relacion_id, actor="TEST", identificador_fuente="test")

    # Dos confirmaciones reales, DISTINTAS, sobre variantes de texto OCR
    # de la misma dirección -- caso real 460807 (R13) y 472008 (R19).
    _confirmar("INTERIOR NUEVA O1148 SAN BERNARDO SAN BERNAR", "460807")
    _confirmar("INTERIOR NUEVA O1148 SAN BERNARDO", "472008")

    fila_460807 = _fila(
        archivo="460807.jpeg", numero_guia="460807", cliente="MATERIALES Y SOLUCIONES SA",
        obra_destino="AUSIN SAN BERNARDO", despachar_a_crudo="INTERIOR NUEVA O1148 SAN BERNARDO SAN BERNARDO",
        motivo_ruta="MULTIPLES_UBICACIONES_DISPERSAS(3)", estado_ruta="REQUIERE_REVISION",
    )
    fila_472008 = _fila(
        archivo="472008.jpeg", numero_guia="472008", cliente="AUSIN HNOS LTDA",
        obra_destino="AUSIN SAN BERNARDO", despachar_a_crudo="INTERIOR NUEVA O1148 SAN BERNARDO",
        motivo_ruta="MULTIPLES_UBICACIONES_DISPERSAS(3)", estado_ruta="REQUIERE_REVISION",
    )
    dataset = _escribir_dataset(actual, [fila_460807, fila_472008])
    decision_460807 = detectar_decision_destino_no_resuelto(archivo="460807.jpeg", fila=fila_460807)
    decision_472008 = detectar_decision_destino_no_resuelto(archivo="472008.jpeg", fila=fila_472008)

    restantes = regenerar_decisiones_persistidas(
        decisiones=[decision_460807, decision_472008], carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert restantes == []  # ambas suprimidas -- el aprendizaje ya resuelve la relación


def test_relacion_confirmada_de_otro_lugar_real_no_suprime(tmp_path):
    """Control -- la obra tiene una relación confirmada, pero para un
    lugar REALMENTE distinto (nunca una variante de texto del mismo) --
    sigue siendo una pregunta real. Caso real 472044."""
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"; actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True); catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="EASY RETAIL SA", rut="76.111.111-6", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    catalogo_obras = CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    )
    destino = CatalogoDestinos(
        catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json",
    ).crear(
        cliente_id="", nombre_destino="CAM. EL NOVICIADO LAMPA LAMPA", direccion="CAM. EL NOVICIADO LAMPA LAMPA",
        pais="CHILE", fuente="TEST", estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    resultado_obs = catalogo_obras.registrar_observacion(
        cliente_id=cliente.cliente_id, nombre_obra="EMPRESA CONSTRUCTORA MENA Y", destino_id=destino.destino_id,
        evidencia=Evidencia(
            tipo=TipoEvidencia.GUIA.value, identificador_fuente="464746", referencia_hash="a" * 64,
            campos_observados={"obra": "EMPRESA CONSTRUCTORA MENA Y", "destino": destino.direccion},
            fecha="2026-01-01T00:00:00+00:00", actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value,
        ),
    )
    catalogo_obras.confirmar_relacion(resultado_obs.relacion.relacion_id, actor="TEST", identificador_fuente="test")

    fila = _fila(
        archivo="472044.jpeg", numero_guia="472044", cliente="EASY RETAIL SA",
        obra_destino="EMPRESA CONSTRUCTORA MENA Y", despachar_a_crudo="PUERTA DEL SOL 83 LAS CONDES",
        motivo_ruta="SIN_ACCESO_VIAL", estado_ruta="SIN_ACCESO_VIAL",
    )
    dataset = _escribir_dataset(actual, [fila])
    decision = detectar_decision_destino_no_resuelto(archivo="472044.jpeg", fila=fila)
    restantes = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert len(restantes) == 1


# --- SINCRONIZACIÓN OPERACIONAL 472593: el mismo patrón de redundancia
# de AUSIN (arriba) también afectaba a DESTINO_SIN_CONFIRMAR -- tanto en
# la DETECCIÓN (`_decisiones_obra_para_cliente`) como en la
# RECONCILIACIÓN (`regenerar_decisiones_persistidas`) -- caso real: guía
# 472593 (PRODALAM SA / EMPRESA CONST SIGRO / Avda Irarrázaval 5497). ---

def _confirmar_destino_para_obra(catalogo_obras, catalogos, *, cliente_id, obra, texto_destino, guia):
    resultado_obs = catalogo_obras.registrar_observacion(
        cliente_id=cliente_id, nombre_obra=obra,
        destino_id=CatalogoDestinos(
            catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json",
        ).crear(
            cliente_id="", nombre_destino=texto_destino, direccion=texto_destino,
            pais="CHILE", fuente="TEST", estado_calidad=EstadoCalidadDestino.CONFIRMADO,
        ).destino_id,
        evidencia=Evidencia(
            tipo=TipoEvidencia.GUIA.value, identificador_fuente=guia, referencia_hash="b" * 64,
            campos_observados={"obra": obra, "destino": texto_destino},
            fecha="2026-01-01T00:00:00+00:00", actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value,
        ),
    )
    relacion = resultado_obs.relacion
    if relacion.estado == "PENDIENTE":
        catalogo_obras.confirmar_relacion(relacion.relacion_id, actor="TEST", identificador_fuente="test")


def test_destino_sin_confirmar_no_se_genera_con_dos_relaciones_redundantes_equivalentes(tmp_path):
    """Detección: `_decisiones_obra_para_cliente` no debe generar
    DESTINO_SIN_CONFIRMAR cuando la dirección documental coincide
    literalmente con CUALQUIERA de los destinos ya confirmados para la
    obra, aunque haya más de una relación confirmada (redundancia, nunca
    contradicción real)."""
    catalogos = tmp_path / "catalogos_privados"
    catalogos.mkdir(parents=True)
    _catalogos_base(catalogos)
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="CLIENTE GENERICO SA", rut="76.111.111-6", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    catalogo_obras = CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    )
    _confirmar_destino_para_obra(
        catalogo_obras, catalogos, cliente_id=cliente.cliente_id, obra="OBRA GENERICA",
        texto_destino="CALLE UNO 100 SANTIAGO", guia="1",
    )
    _confirmar_destino_para_obra(
        catalogo_obras, catalogos, cliente_id=cliente.cliente_id, obra="OBRA GENERICA",
        texto_destino="Calle Uno 100, Santiago Centro", guia="2",
    )

    decisiones = _decisiones_obra_para_cliente(
        carpeta=catalogos, cliente_id=cliente.cliente_id, cliente_razon_social=cliente.razon_social,
        cliente_aliases=(), obra_texto="OBRA GENERICA", despachar_a_documental="CALLE UNO 100 SANTIAGO",
        comunes={"archivo": "3.jpeg", "numero_guia": "3", "numero_transporte": "T3"},
    )
    assert decisiones == []


def test_destino_sin_confirmar_sigue_generandose_con_direcciones_realmente_distintas(tmp_path):
    """Control -- la obra tiene DOS relaciones confirmadas (por eso el
    resolver estricto ya se abstiene, igual que en el caso real), pero
    para lugares REALMENTE distintos entre sí y del documental: sigue
    siendo una pregunta real, no se oculta una ambigüedad genuina sólo
    porque exista ALGUNA relación confirmada."""
    catalogos = tmp_path / "catalogos_privados"
    catalogos.mkdir(parents=True)
    _catalogos_base(catalogos)
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="CLIENTE GENERICO SA", rut="76.111.111-6", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    catalogo_obras = CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    )
    _confirmar_destino_para_obra(
        catalogo_obras, catalogos, cliente_id=cliente.cliente_id, obra="OBRA GENERICA",
        texto_destino="CALLE UNO 100 SANTIAGO", guia="1",
    )
    _confirmar_destino_para_obra(
        catalogo_obras, catalogos, cliente_id=cliente.cliente_id, obra="OBRA GENERICA",
        texto_destino="CALLE DOS 200 SANTIAGO", guia="2",
    )

    decisiones = _decisiones_obra_para_cliente(
        carpeta=catalogos, cliente_id=cliente.cliente_id, cliente_razon_social=cliente.razon_social,
        cliente_aliases=(), obra_texto="OBRA GENERICA", despachar_a_documental="AVENIDA DOS 999 SANTIAGO",
        comunes={"archivo": "3.jpeg", "numero_guia": "3", "numero_transporte": "T3"},
    )
    assert len(decisiones) == 1
    assert decisiones[0]["tipo"] == "DESTINO_SIN_CONFIRMAR"


def test_regenerar_suprime_destino_sin_confirmar_por_redundancia_equivalente(tmp_path):
    """Reconciliación: una tarjeta DESTINO_SIN_CONFIRMAR YA PERSISTIDA se
    suprime si, con el catálogo vigente, la dirección documental coincide
    literalmente con cualquiera de los destinos confirmados -- caso real
    472593 (verificado también contra los catálogos reales de producción,
    sólo lectura, fuera de esta suite)."""
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"; actual = raiz / "operacion" / "actual"
    catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="CLIENTE GENERICO SA", rut="76.111.111-6", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    catalogo_obras = CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    )
    obra = catalogo_obras.registrar_observacion(
        cliente_id=cliente.cliente_id, nombre_obra="OBRA GENERICA",
        evidencia=Evidencia(
            tipo=TipoEvidencia.GUIA.value, identificador_fuente="0", referencia_hash="c" * 64,
            campos_observados={"obra": "OBRA GENERICA"}, fecha="2026-01-01T00:00:00+00:00",
            actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value,
        ),
    ).obra
    _confirmar_destino_para_obra(
        catalogo_obras, catalogos, cliente_id=cliente.cliente_id, obra="OBRA GENERICA",
        texto_destino="CALLE UNO 100 SANTIAGO", guia="1",
    )
    _confirmar_destino_para_obra(
        catalogo_obras, catalogos, cliente_id=cliente.cliente_id, obra="OBRA GENERICA",
        texto_destino="Calle Uno 100, Santiago Centro", guia="2",
    )

    decision = crear_decision(
        tipo="DESTINO_SIN_CONFIRMAR", entidad="RELACION_OBRA_DESTINO", archivo="3.jpeg",
        numero_guia="3", numero_transporte="T3", campo="destino_entrega",
        valor_documental="CALLE UNO 100 SANTIAGO", valor_normalizado="CALLE UNO 100 SANTIAGO",
        identidad_resuelta={"entidad_id": obra.obra_id, "valor_canonico": "OBRA GENERICA"},
        candidatos=(), motivos=("OBRA_SIN_RELACION_CONFIRMADA_UNICA",),
        evidencias=({"tipo": "OBRA_IDENTIFICADA", "entidad_id": obra.obra_id},),
        acciones_permitidas=("CONFIRMAR", "NO_CONFIRMAR", "POSPONER"),
        contexto={
            "cliente_id": cliente.cliente_id, "cliente_canonico": cliente.razon_social,
            "obra_id": obra.obra_id, "obra_canonica": "OBRA GENERICA",
            "destino_documental": "CALLE UNO 100 SANTIAGO",
        },
    )
    fila = _fila(archivo="3.jpeg", numero_guia="3", cliente="CLIENTE GENERICO SA", obra_destino="OBRA GENERICA")
    dataset = _escribir_dataset(actual, [fila])
    restantes = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert restantes == []


# --- Invariante 4: regenerar dos veces sin cambios produce el mismo
# conjunto semántico, sin duplicados ni pérdida de contexto. ---

def test_regenerar_dos_veces_es_idempotente(tmp_path):
    carpeta = tmp_path / "catalogos"; carpeta.mkdir()
    _catalogos_base(carpeta)
    fila = _fila(
        numero_guia="472037", despachar_a_crudo="VICUÑA MACKENNA 655",
        obra_destino="ING Y CONST FUNDAMENTA SPA", motivo_ruta="MULTIPLES_UBICACIONES_DISPERSAS(5)",
        estado_ruta="REQUIERE_REVISION",
        resultado_atlas_ia_json=_traza_b1("Hallazgo real de prueba."),
    )
    dataset = tmp_path / "dataset.csv"
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerow(fila)
    decision = detectar_decision_destino_no_resuelto(archivo="472037.jpeg", fila=fila)

    primera_pasada = regenerar_decisiones_persistidas(decisiones=[decision], carpeta_catalogos=carpeta, ruta_dataset=dataset)
    segunda_pasada = regenerar_decisiones_persistidas(decisiones=primera_pasada, carpeta_catalogos=carpeta, ruta_dataset=dataset)
    assert len(primera_pasada) == len(segunda_pasada) == 1
    assert primera_pasada[0]["decision_id"] == segunda_pasada[0]["decision_id"]
    assert primera_pasada[0]["contexto"]["b1_resumen_hallazgo"] == segunda_pasada[0]["contexto"]["b1_resumen_hallazgo"]
