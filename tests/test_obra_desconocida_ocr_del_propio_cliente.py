"""Bloque REVISIONES ESTANCADAS -- caso real 473309: la guía trae
"AGP ACEROS DE CHILS SPA" en `obra_destino`, y el cliente de la guía ya
resolvió, con evidencia independiente (RUT documental contra catálogo),
como "AGF ACEROS DE CHILE SPA". No existe ninguna obra (de este cliente
ni de ningún otro) parecida a ese texto -- por eso `OBRA_DESCONOCIDA`
proponía "REGISTRAR" el texto OCR erróneo como obra nueva.

El texto documental es, con alta probabilidad, una lectura OCR
levemente degradada del propio nombre del cliente (2 caracteres
distintos en todo un nombre de 23), no una obra real distinta -- Atlas
nunca debe registrar ese texto como obra nueva. Deliberadamente
diferente del mecanismo obra-vs-obra (`coincide_salvo_variacion_
ortografica_menor`, un único token distinto): acá no hay dos entidades
reales entre las que elegir, sólo el cliente ya resuelto por RUT."""
from __future__ import annotations

import json

from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.decisiones_pendientes import regenerar_decisiones_persistidas

CLIENTE_CANONICO = "AGF ACEROS DE CHILE SPA"
OBRA_OCR_DEGRADADA = "AGP ACEROS DE CHILS SPA"


def _carpeta_catalogos(tmp_path):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    return carpeta


def _cliente_confirmado(carpeta, *, nombre=CLIENTE_CANONICO, rut="77.410.131-4", aliases=()):
    return CatalogoClientes(carpeta / "clientes.json").crear(
        razon_social=nombre, rut=rut, fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO,
        aliases=aliases,
    )


def _decision_obra_desconocida(*, decision_id, numero_guia, valor_documental, cliente_id, cliente_canonico):
    return {
        "decision_id": decision_id, "estado": "PENDIENTE", "tipo": "OBRA_DESCONOCIDA",
        "entidad": "OBRA", "documento": {"archivo": f"{numero_guia}.jpeg", "numero_guia": numero_guia},
        "campo": "obra_destino", "valor_documental": valor_documental, "valor_normalizado": valor_documental,
        "identidad_resuelta": None,
        "contexto": {
            "cliente_id": cliente_id, "cliente_canonico": cliente_canonico,
            "destino_documental": "PANAMERICANA NORTE 22650 SANTIAGO LAMPA",
        },
        "candidatos": [], "motivos": ["OBRA_NO_EXISTE_PARA_CLIENTE"],
        "evidencias": [{"tipo": "CLIENTE_RESUELTO", "entidad_id": cliente_id}],
        "acciones_permitidas": ["REGISTRAR", "NO_REGISTRAR", "POSPONER"],
    }


def test_caso_real_473309_no_registra_texto_ocr_del_propio_cliente_como_obra(tmp_path):
    carpeta = _carpeta_catalogos(tmp_path)
    cliente = _cliente_confirmado(carpeta)
    decision = _decision_obra_desconocida(
        decision_id="dec-473309", numero_guia="473309", valor_documental=OBRA_OCR_DEGRADADA,
        cliente_id=cliente.cliente_id, cliente_canonico=CLIENTE_CANONICO,
    )
    salida = regenerar_decisiones_persistidas(decisiones=[decision], carpeta_catalogos=carpeta)
    assert salida == []  # nunca queda pendiente "¿registro esta obra nueva?"


def test_coincidencia_por_alias_del_cliente_tambien_suprime(tmp_path):
    carpeta = _carpeta_catalogos(tmp_path)
    cliente = _cliente_confirmado(carpeta, aliases=("ACEROS DE CHILE SPA AGF",))
    decision = _decision_obra_desconocida(
        decision_id="dec-alias", numero_guia="1", valor_documental="ACEROS DE CHILE SPA AGX",
        cliente_id=cliente.cliente_id, cliente_canonico=CLIENTE_CANONICO,
    )
    salida = regenerar_decisiones_persistidas(decisiones=[decision], carpeta_catalogos=carpeta)
    assert salida == []


def test_obra_realmente_distinta_del_cliente_sigue_pendiente(tmp_path):
    """Regresión -- un nombre de obra genuinamente distinto (no un eco
    OCR del cliente) nunca se suprime por este mecanismo; sigue siendo
    terreno legítimo de OBRA_DESCONOCIDA."""
    carpeta = _carpeta_catalogos(tmp_path)
    cliente = _cliente_confirmado(carpeta)
    decision = _decision_obra_desconocida(
        decision_id="dec-nueva", numero_guia="2", valor_documental="CONSTRUCTORA IGNACIO HURTADO LIMITADA",
        cliente_id=cliente.cliente_id, cliente_canonico=CLIENTE_CANONICO,
    )
    salida = regenerar_decisiones_persistidas(decisiones=[decision], carpeta_catalogos=carpeta)
    assert [d["decision_id"] for d in salida] == ["dec-nueva"]


def test_distancia_de_edicion_demasiado_grande_no_suprime(tmp_path):
    """Regresión -- más de 2 caracteres de diferencia total ya no cuenta
    como "error OCR pequeño"; se abstiene (nunca inventa la fusión)."""
    carpeta = _carpeta_catalogos(tmp_path)
    cliente = _cliente_confirmado(carpeta)
    decision = _decision_obra_desconocida(
        decision_id="dec-lejos", numero_guia="3", valor_documental="AGX ACERQS XE CHILX SPX",
        cliente_id=cliente.cliente_id, cliente_canonico=CLIENTE_CANONICO,
    )
    salida = regenerar_decisiones_persistidas(decisiones=[decision], carpeta_catalogos=carpeta)
    assert [d["decision_id"] for d in salida] == ["dec-lejos"]


def test_nombre_corto_no_suprime_por_prudencia(tmp_path):
    """Regresión -- nombres de cliente cortos (< 15 caracteres
    normalizados) nunca activan esta tolerancia; el piso de longitud
    evita falsos positivos sobre razones sociales breves."""
    carpeta = _carpeta_catalogos(tmp_path)
    cliente = _cliente_confirmado(carpeta, nombre="EASY RETAIL SA", rut="76.123.456-0")
    decision = _decision_obra_desconocida(
        decision_id="dec-corto", numero_guia="4", valor_documental="EASY RETAIL SB",
        cliente_id=cliente.cliente_id, cliente_canonico="EASY RETAIL SA",
    )
    salida = regenerar_decisiones_persistidas(decisiones=[decision], carpeta_catalogos=carpeta)
    assert [d["decision_id"] for d in salida] == ["dec-corto"]
