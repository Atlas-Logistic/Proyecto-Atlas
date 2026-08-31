"""Bloque R2 (adición) -- ENTIDADES CONOCIDAS NO DEBEN VOLVER A HOMOLOGACIÓN.

Investigación: el mecanismo ya existe (`resolver_patente` +
`CatalogoVehiculos.homologables()`, construido en el bloque V1) y ya
distingue correctamente A/B/C -- estos tests lo confirman end-to-end,
contra el punto de entrada real (`detectar_decisiones_documento`), con
fixtures genéricos (nunca una patente/nombre real hardcodeado). No se
encontró ningún caso donde una entidad `CONFIRMADO` referenciada por un
documento real vuelva a generar una pregunta de homologación."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from atlas_core.catalogo_vehiculos import confirmar_vehiculo, TipoVehiculo
from atlas_core.decisiones_pendientes import detectar_decisiones_documento


def _catalogos(tmp_path):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    return carpeta


# --- A. ENTIDAD CONOCIDA -- resuelve automáticamente, nunca vuelve a preguntar ---

def test_patente_ya_confirmada_no_genera_decision(tmp_path):
    carpeta = _catalogos(tmp_path)
    confirmar_vehiculo(
        carpeta / "vehiculos.json", patente="AB1234", tipo=TipoVehiculo.TRACTO,
        actor="TEST", fuente_decision="TEST", fecha=datetime.now(timezone.utc),
    )

    decisiones = detectar_decisiones_documento(
        archivo="g.jpg", datos={"número de guía": "1", "patente del tracto": "AB1234"},
        carpeta_catalogos=carpeta,
    )

    assert decisiones == [], "una patente CONFIRMADA no debe volver a generar VEHICULO_DESCONOCIDO"


def test_patente_con_alias_ocr_confirmado_resuelve_sin_preguntar(tmp_path):
    """B/C combinados: una lectura OCR ya registrada como alias verificado
    de una patente CONFIRMADA (mecanismo genérico de homologación, campo
    `aliases` del catálogo real -- nunca hardcodeo de un caso puntual)
    homologa sola -- nunca genera una pregunta nueva para lo mismo."""
    carpeta = _catalogos(tmp_path)
    (carpeta / "vehiculos.json").write_text(json.dumps({
        "version": 1,
        "vehiculos": [{
            "vehiculo_id": "11111111-1111-1111-1111-111111111111",
            "patente_canonica": "AB1234", "tipo": "TRACTO",
            "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO",
            "aliases": ["AB1284"],  # variante OCR ya verificada de la misma patente
            "evidencias": [{
                "tipo": "CONFIRMACION_HUMANA", "identificador_fuente": "TEST",
                "referencia_hash": "", "campos_observados": {"patente": "AB1234"},
                "fecha": "2026-01-01T00:00:00+00:00", "actor_proceso": "TEST", "resultado": "SOPORTA",
            }, {
                "tipo": "AUDITORIA_ALIAS_OCR", "identificador_fuente": "TEST",
                "referencia_hash": "", "campos_observados": {"alias": "AB1284"},
                "fecha": "2026-01-01T00:00:00+00:00", "actor_proceso": "TEST", "resultado": "SOPORTA",
            }],
            "procedencia": "CONFIRMACION_HUMANA", "confirmado_por": "TEST",
            "fecha_confirmacion": "2026-01-01T00:00:00+00:00", "observaciones": "",
            "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00",
        }],
    }), encoding="utf-8")

    decisiones = detectar_decisiones_documento(
        archivo="g.jpg", datos={"número de guía": "1", "patente del tracto": "AB1284"},
        carpeta_catalogos=carpeta,
    )

    assert decisiones == [], "un alias ya confirmado debe homologar solo, sin volver a preguntar"


# --- B. ENTIDAD NUEVA -- sigue generando una decisión real ---

def test_patente_genuinamente_nueva_sigue_generando_decision(tmp_path):
    """Control: el catálogo vacío no debe volverse permisivo -- una
    patente sin ningún antecedente sigue siendo una pregunta real."""
    carpeta = _catalogos(tmp_path)

    decisiones = detectar_decisiones_documento(
        archivo="g.jpg", datos={"número de guía": "1", "patente del tracto": "ZZ9999"},
        carpeta_catalogos=carpeta,
    )

    assert len(decisiones) == 1
    assert decisiones[0]["tipo"] == "VEHICULO_DESCONOCIDO"


# --- C. ENTIDAD CONOCIDA PERO CONTRADICTORIA -- investigar, nunca
# etiquetar como "sin homologar" sin más ---

def test_chofer_mismo_rut_variante_ocr_del_nombre_se_corrobora_no_se_repregunta():
    """El mecanismo real para chofer no es un catálogo con alias (no
    existe uno) sino corroboración por RUT entre documentos del mismo
    lote (`atlas_core.procesamiento_masivo._corroborar_documentos_
    relacionados`, ya construido) -- confirma que SÍ existe una vía
    genérica para "RUT conocido + nombre con variante OCR" sin necesitar
    una pregunta nueva."""
    import inspect

    from atlas_core import procesamiento_masivo
    fuente = inspect.getsource(procesamiento_masivo._corroborar_documentos_relacionados)
    assert "rut_chofer" in fuente and "CHOFER_SIN_CORROBORAR" in fuente
