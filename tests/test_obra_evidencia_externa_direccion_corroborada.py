"""Bloque 472339/CASA HELSINSKI -- reconciliación de obra + evidencia
externa + promoción automática al catálogo.

Caso real que motivó este bloque -- guía 472339 (YOLITO BALART HNOS
LTDA): OCR leyó "INMOB CASA RELSINSKI SPA" como obra; el destino
documental ("HELSINSKI 5810 LA REINA SANTIAGO") ya estaba resuelto por
el pipeline determinista (RUTA_CALCULADA, 20.7 km); el viaje seguía
mostrando el motivo "OBRA_DESTINO_SIN_CORROBORAR", pero la tarjeta de
revisión de obra había desaparecido de la bandeja -- Javier no podía
confirmarla aunque quisiera. Investigación externa real (fuera del
proceso Python, guardada como fixture -- mismo patrón ya documentado en
`atlas_core.verificacion_externa`, caso SIGRO) confirmó que "Casa
Helsinski" es un proyecto real de Inmobiliaria IKNOW en Helsinski 5810,
La Reina -- corroborando exactamente la misma dirección que Atlas ya
había resuelto de forma independiente.

Causa real de la "revisión huérfana" (investigada contra los artefactos
reales persistidos, nunca supuesta): NO es un bug de clasificación --
llamar `_decisiones_obra_para_cliente` hoy, con los datos reales
exactos de la fila 472339 (cliente ya CONFIRMADO desde el 2026-07-27),
SÍ genera correctamente la decisión OBRA_DESCONOCIDA. La guía nunca
tuvo, en el ledger, ninguna aplicación terminal de obra/destino -- la
decisión simplemente nunca quedó persistida en la bandeja (no hay
ningún mecanismo, hasta este bloque, que la regenere retroactivamente
sin OCR si eso ocurre). B1 tampoco "ya sabía" Casa Helsinski: su único
intento sobre `obra_destino` abortó por falta de la herramienta
DOCUMENTOS_RELACIONADOS (`estado=REQUIERE_HERRAMIENTA`,
`evidencia_usada=[]`) -- la única mención real de RELSINSKI vs HELSINSKI
en la evidencia persistida es una nota de B1 sobre el dominio DESTINO,
rechazada por el validador ("no aparece en la evidencia del caso"), no
una confirmación.

`regenerar_decisiones_obra_faltantes_sin_ocr` (Sección 5 del bloque,
regla GENERAL) cierra ese hueco: cualquier fila con
OBRA_DESTINO_SIN_CORROBORAR vigente pero sin decisión pendiente
correspondiente, y sin resolución terminal en el ledger, recupera su
tarjeta -- nunca "motivo sin tarjeta".

Los tests de la Sección A-D (regla general en `motor_evidencia_obras`)
usan nombres/direcciones sintéticos para probar la regla GENERAL, nunca
hardcodeada a RELSINSKI/HELSINSKI. El test end-to-end final reproduce
la estructura exacta del caso real 472339 -- incluida la bandeja de
decisiones VACÍA, igual que el caso real -- con valores sintéticos
(mismo criterio ya usado en `test_vehiculo_autonomia_e2.py` para el
caso BPHF67->BPHR67)."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
from atlas_core.incidencias_documentales import AlmacenIncidenciasDocumentales, TIPO_OBRA_DOCUMENTAL_INCONSISTENTE
from atlas_core.motor_evidencia import RESULTADO_CONTRADICCION_DOCUMENTAL, RESULTADO_RESUELTO_AUTOMATICAMENTE, RESULTADO_SUGERENCIA_HUMANA
from atlas_core.motor_evidencia_obras import evaluar_evidencia_obra
from atlas_core.procesamiento_masivo import COLUMNAS, MotivoRevisionDocumento
from atlas_core.revalidacion_documental import reconciliar_bandeja_decisiones
from atlas_core.verificacion_externa import TIPO_FUENTE_CORPORATIVO, TIPO_FUENTE_DIRECTORIO, TIPO_FUENTE_OFICIAL, EvidenciaExterna

FECHA_CONSULTA = datetime(2026, 8, 26, tzinfo=timezone.utc).isoformat()


def _evidencia(*, tipo_fuente=TIPO_FUENTE_CORPORATIVO, direccion="Proyecto 100, La Reina", contradicciones=()):
    return EvidenciaExterna(
        fuente="desarrolladora.cl", tipo_fuente=tipo_fuente, url="https://desarrolladora.cl/proyecto-100",
        fecha_consulta=FECHA_CONSULTA, razon_social="PROYECTO CIEN", direccion=direccion, comuna="LA REINA",
        campos_corroborados=("nombre", "direccion"), contradicciones=contradicciones,
    )


# ============================================================
# A -- nombre OCR parecido + misma dirección + único proyecto -> auto-resuelve
# ============================================================


def test_a_direccion_documental_corroborada_por_fuente_oficial_unica_resuelve_automaticamente():
    resultado = evaluar_evidencia_obra(
        nombre_documental="INMOB PROYECTO CEN SPA",
        evidencia_externa=(_evidencia(tipo_fuente=TIPO_FUENTE_OFICIAL, direccion="Proyecto 100, La Reina"),),
        direccion_documental_resuelta="PROYECTO 100 LA REINA SANTIAGO",
    )
    assert resultado.resultado == RESULTADO_RESUELTO_AUTOMATICAMENTE
    assert resultado.candidatos[0].valor_canonico == "PROYECTO CIEN"


def test_a_tambien_resuelve_con_fuente_corporativa_no_solo_oficial():
    resultado = evaluar_evidencia_obra(
        nombre_documental="INMOB PROYECTO CEN SPA",
        evidencia_externa=(_evidencia(tipo_fuente=TIPO_FUENTE_CORPORATIVO, direccion="Proyecto 100, La Reina"),),
        direccion_documental_resuelta="PROYECTO 100 LA REINA SANTIAGO",
    )
    assert resultado.resultado == RESULTADO_RESUELTO_AUTOMATICAMENTE


# ============================================================
# B -- nombre parecido pero dirección distinta -> NO auto-resuelve
# ============================================================


def test_b_direccion_distinta_nunca_auto_resuelve_aunque_el_nombre_sea_parecido():
    resultado = evaluar_evidencia_obra(
        nombre_documental="INMOB PROYECTO CEN SPA",
        evidencia_externa=(_evidencia(tipo_fuente=TIPO_FUENTE_OFICIAL, direccion="Otra Calle 999, Ñuñoa"),),
        direccion_documental_resuelta="PROYECTO 100 LA REINA SANTIAGO",
    )
    assert resultado.resultado == RESULTADO_CONTRADICCION_DOCUMENTAL  # sigue siendo sugerencia fuerte, nunca se aplica sola
    assert resultado.candidatos[0].metadatos["direccion_corroborada"] is False


def test_b_sin_direccion_documental_resuelta_disponible_tampoco_auto_resuelve():
    resultado = evaluar_evidencia_obra(
        nombre_documental="INMOB PROYECTO CEN SPA",
        evidencia_externa=(_evidencia(tipo_fuente=TIPO_FUENTE_OFICIAL, direccion="Proyecto 100, La Reina"),),
        direccion_documental_resuelta="",
    )
    assert resultado.resultado == RESULTADO_CONTRADICCION_DOCUMENTAL


# ============================================================
# C -- dos proyectos compatibles -> humano/B1 se abstiene
# ============================================================


def test_c_dos_fuentes_oficiales_distintas_corroborando_la_misma_direccion_nunca_elige_una():
    evidencia_uno = _evidencia(tipo_fuente=TIPO_FUENTE_OFICIAL, direccion="Proyecto 100, La Reina")
    evidencia_dos = EvidenciaExterna(
        fuente="otra-desarrolladora.cl", tipo_fuente=TIPO_FUENTE_OFICIAL, url="https://otra-desarrolladora.cl/x",
        fecha_consulta=FECHA_CONSULTA, razon_social="OTRO PROYECTO DISTINTO", direccion="Proyecto 100, La Reina", comuna="LA REINA",
    )
    resultado = evaluar_evidencia_obra(
        nombre_documental="INMOB PROYECTO CEN SPA",
        evidencia_externa=(evidencia_uno, evidencia_dos),
        direccion_documental_resuelta="PROYECTO 100 LA REINA SANTIAGO",
    )
    assert resultado.resultado == RESULTADO_SUGERENCIA_HUMANA
    assert len(resultado.candidatos) == 2


# ============================================================
# D -- fuente externa débil/no corroborada -> no promueve
# ============================================================


def test_d_fuente_de_directorio_nunca_alcanza_auto_resolucion_aunque_la_direccion_coincida():
    resultado = evaluar_evidencia_obra(
        nombre_documental="INMOB PROYECTO CEN SPA",
        evidencia_externa=(_evidencia(tipo_fuente=TIPO_FUENTE_DIRECTORIO, direccion="Proyecto 100, La Reina"),),
        direccion_documental_resuelta="PROYECTO 100 LA REINA SANTIAGO",
    )
    assert resultado.resultado == RESULTADO_SUGERENCIA_HUMANA


def test_d_evidencia_con_contradicciones_declaradas_nunca_auto_resuelve():
    resultado = evaluar_evidencia_obra(
        nombre_documental="INMOB PROYECTO CEN SPA",
        evidencia_externa=(_evidencia(
            tipo_fuente=TIPO_FUENTE_OFICIAL, direccion="Proyecto 100, La Reina",
            contradicciones=("EL RUT NO COINCIDE CON EL DOCUMENTO",),
        ),),
        direccion_documental_resuelta="PROYECTO 100 LA REINA SANTIAGO",
    )
    assert resultado.resultado == RESULTADO_CONTRADICCION_DOCUMENTAL


# ============================================================
# No hardcode -- la regla es general, no está atada a un texto fijo
# ============================================================


def test_no_hardcode_funciona_igual_con_un_par_de_nombres_completamente_distinto():
    resultado = evaluar_evidencia_obra(
        nombre_documental="BODEGA ZORTEX LTDA",
        evidencia_externa=(EvidenciaExterna(
            fuente="zortex-oficial.cl", tipo_fuente=TIPO_FUENTE_OFICIAL, url="https://zortex-oficial.cl",
            fecha_consulta=FECHA_CONSULTA, razon_social="BODEGAS VORTEX SPA", direccion="Camino Rural 42, Melipilla", comuna="MELIPILLA",
        ),),
        direccion_documental_resuelta="CAMINO RURAL 42 MELIPILLA",
    )
    assert resultado.resultado == RESULTADO_RESUELTO_AUTOMATICAMENTE
    assert resultado.candidatos[0].valor_canonico == "BODEGAS VORTEX SPA"


# ============================================================
# E2E -- reproduce la estructura exacta del caso real 472339
# ============================================================


def _fila_472339(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "472339.jpeg", "estado_procesamiento": "OK", "numero_guia": "472339",
        "numero_transporte": "T-472339", "fecha": "26-08-2026", "chofer": "CHOFER PRUEBA",
        "cliente": "CLIENTE PRUEBA SPA", "obra_destino": "INMOB PROYECTO CEN SPA",
        "despachar_a_crudo": "PROYECTO 100 LA REINA SANTIAGO", "direccion_entrega": "PROYECTO 100 LA REINA SANTIAGO",
        "localidad_entrega": "La Reina", "region_entrega": "Metropolitana",
        "estado_entrega": "RESUELTO", "estado_ruta": "RUTA_CALCULADA",
        "distancia_km": "20.7", "duracion_min": "28.9", "proveedor_ruta": "openrouteservice",
        "indicador_revision": "REVISAR",
        "motivos_revision_documento": MotivoRevisionDocumento.OBRA_DESTINO_SIN_CORROBORAR.value,
    })
    fila.update(overrides)
    return fila


def _entorno_472339(tmp_path):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="CLIENTE PRUEBA SPA", rut="50.234.350-5", fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    for nombre, contenido in {
        "empresas.json": {}, "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")

    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerow(_fila_472339())

    # Reproduce el caso real: la bandeja está VACÍA -- ninguna decisión
    # de obra jamás quedó persistida para esta guía, pese al motivo
    # vigente. `regenerar_decisiones_obra_faltantes_sin_ocr` (invocado
    # dentro de `reconciliar_bandeja_decisiones`) es lo que debe
    # recuperarla, sin OCR.
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[],
        ruta_salida=actual / "decisiones_pendientes.json",
    )

    cache_externa = {
        "version": 1,
        "entradas": {
            "INMOB PROYECTO CEN SPA": {
                "fecha_guardado": FECHA_CONSULTA,
                "evidencias": [_evidencia(tipo_fuente=TIPO_FUENTE_OFICIAL, direccion="Proyecto 100, La Reina").a_dict()],
            },
        },
    }
    (catalogos / "verificacion_externa_cache.json").write_text(json.dumps(cache_externa), encoding="utf-8")
    return {"raiz": raiz, "catalogos": catalogos, "actual": actual, "dataset": dataset, "cliente": cliente}


# ============================================================
# Regla GENERAL: motivo sin tarjeta -- backfill sin OCR (Sección 5)
# ============================================================


def test_regenera_la_decision_faltante_cuando_hay_motivo_vigente_sin_tarjeta(tmp_path):
    from atlas_core.revalidacion_documental import regenerar_decisiones_obra_faltantes_sin_ocr

    entorno = _entorno_472339(tmp_path)
    regeneradas = regenerar_decisiones_obra_faltantes_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones_pendientes=[], ruta_ledger=entorno["actual"] / "decisiones_aplicadas.json",
    )
    assert len(regeneradas) == 1
    assert regeneradas[0]["tipo"] == "OBRA_DESCONOCIDA"
    assert regeneradas[0]["valor_documental"] == "INMOB PROYECTO CEN SPA"
    assert regeneradas[0]["documento"]["numero_guia"] == "472339"


def test_nunca_duplica_si_ya_existe_una_decision_pendiente_para_esa_guia(tmp_path):
    from atlas_core.revalidacion_documental import regenerar_decisiones_obra_faltantes_sin_ocr

    entorno = _entorno_472339(tmp_path)
    ya_pendiente = crear_decision(
        tipo="OBRA_DESCONOCIDA", entidad="OBRA", archivo="472339.jpeg", numero_guia="472339",
        numero_transporte="T-472339", campo="obra_destino",
        valor_documental="INMOB PROYECTO CEN SPA", valor_normalizado="INMOB PROYECTO CEN SPA",
        identidad_resuelta=None, candidatos=(), motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),
        evidencias=(), acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        contexto={"cliente_id": entorno["cliente"].cliente_id, "cliente_canonico": entorno["cliente"].razon_social},
    )
    regeneradas = regenerar_decisiones_obra_faltantes_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones_pendientes=[ya_pendiente], ruta_ledger=entorno["actual"] / "decisiones_aplicadas.json",
    )
    assert regeneradas == [ya_pendiente]  # ninguna decisión nueva agregada


def test_nunca_regenera_si_el_ledger_ya_tiene_una_resolucion_terminal_para_esa_guia(tmp_path):
    from atlas_core.revalidacion_documental import regenerar_decisiones_obra_faltantes_sin_ocr

    entorno = _entorno_472339(tmp_path)
    ledger = {
        "schema_version": 1,
        "aplicaciones": [{
            "tipo": "OBRA_DESCONOCIDA", "accion": "NO_REGISTRAR",
            "documento": {"numero_guia": "472339"},
        }],
    }
    (entorno["actual"] / "decisiones_aplicadas.json").write_text(json.dumps(ledger), encoding="utf-8")
    regeneradas = regenerar_decisiones_obra_faltantes_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones_pendientes=[], ruta_ledger=entorno["actual"] / "decisiones_aplicadas.json",
    )
    assert regeneradas == []  # un humano ya decidió NO_REGISTRAR -- nunca resucita


# ============================================================
# E2E -- reconciliar_bandeja_decisiones completo (backfill + auto-resolución)
# ============================================================


def test_e2e_472339_obra_se_auto_resuelve_promueve_al_catalogo_y_el_motivo_se_limpia(tmp_path):
    entorno = _entorno_472339(tmp_path)

    resultado = reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"])

    # La bandeja partía VACÍA (igual que el caso real) -- se recuperó la
    # decisión faltante sin OCR Y se aplicó sola, ambos en la misma
    # reconciliación. Javier nunca tuvo que hacer clic.
    aplicadas = resultado["decisiones_aplicadas_automaticamente"]
    assert len(aplicadas) == 1
    assert aplicadas[0]["documento"]["numero_guia"] == "472339"
    assert aplicadas[0]["valor_documental"] == "INMOB PROYECTO CEN SPA"
    assert resultado["bandeja"]["decisiones"] == []  # nunca queda una tarjeta huérfana

    # La obra queda promovida al catálogo con el nombre CANÓNICO real --
    # nunca el error OCR como entidad aparte.
    catalogo_obras = CatalogoObrasDestinos(
        ruta=entorno["catalogos"] / "obras_destinos.json", ruta_clientes=entorno["catalogos"] / "clientes.json",
        ruta_destinos=entorno["catalogos"] / "destinos_maestros.json",
    )
    obras = catalogo_obras.listar_obras()
    assert len(obras) == 1
    obra = obras[0]
    assert obra.nombre_canonico == "PROYECTO CIEN"
    assert "INMOB PROYECTO CEN SPA" in obra.aliases_documentales  # el OCR se conserva como alias, nunca como entidad aparte
    assert obra.estado == "CONFIRMADA"
    assert obra.estado_vigencia == "ACTIVO"

    # Destino/relación quedan confirmados, con dirección canónica.
    resuelto = catalogo_obras.resolver_obra_destino_confirmada_global(nombre_obra="INMOB PROYECTO CEN SPA")
    assert resuelto is not None  # se encuentra vía el alias, no sólo el nombre canónico
    assert resuelto.destino.direccion == "PROYECTO 100 LA REINA SANTIAGO"
    assert resuelto.destino.comuna == "LA REINA"
    assert resuelto.destino.estado_calidad == "CONFIRMADO"
    assert resuelto.relacion.estado == "CONFIRMADA"

    # El motivo de revisión de ESA guía se limpia (ya no huérfana:
    # ninguna tarjeta, ningún motivo pendiente).
    with entorno["dataset"].open(encoding="utf-8-sig", newline="") as archivo:
        fila = next(csv.DictReader(archivo, delimiter=";"))
    assert MotivoRevisionDocumento.OBRA_DESTINO_SIN_CORROBORAR.value not in fila["motivos_revision_documento"]
    assert fila["obra_destino"] == "INMOB PROYECTO CEN SPA"  # el valor documental nunca se reescribe

    # Incidencia Documental: el error OCR queda como evidencia auditable
    # (Dato emitido vs Dato usado por Atlas), nunca oculto.
    incidencias = AlmacenIncidenciasDocumentales(entorno["catalogos"] / "incidencias_documentales.json").listar()
    assert len(incidencias) == 1
    incidencia = incidencias[0]
    assert incidencia.tipo_incidencia == TIPO_OBRA_DOCUMENTAL_INCONSISTENTE
    assert incidencia.valor_documental == "INMOB PROYECTO CEN SPA"
    assert incidencia.valor_canonico == "PROYECTO CIEN"
    assert incidencia.numero_guia == "472339"

    # Idempotente: reconciliar de nuevo no aplica nada más ni duplica nada.
    segunda = reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"])
    assert segunda["decisiones_aplicadas_automaticamente"] == []
    assert len(catalogo_obras.listar_obras()) == 1


def test_e2e_472339_sin_cache_de_evidencia_externa_sigue_generando_la_tarjeta_normal(tmp_path):
    """Regla de seguridad general: si no hay evidencia externa
    corroborada disponible, la decisión se recupera (nunca queda
    huérfana) pero sigue pendiente para Javier -- nunca se auto-resuelve
    sin evidencia."""
    entorno = _entorno_472339(tmp_path)
    (entorno["catalogos"] / "verificacion_externa_cache.json").write_text(
        json.dumps({"version": 1, "entradas": {}}), encoding="utf-8",
    )

    resultado = reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"])
    assert resultado["decisiones_aplicadas_automaticamente"] == []
    tipos_pendientes = [(d["tipo"], d["documento"]["numero_guia"]) for d in resultado["bandeja"]["decisiones"]]
    assert ("OBRA_DESCONOCIDA", "472339") in tipos_pendientes  # visible para Javier -- nunca huérfana, nunca invisible
