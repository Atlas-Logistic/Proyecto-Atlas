"""Caso real 480676 (AUSIN SAN BERNARDO / MATERIALES Y SOLUCIONES SA).

La obra tiene el mismo lugar confirmado dos veces, ambos con la numeración
leída "O1148" (letra O). La guía 480676 trae "01148" (cero) y generaba un
DESTINO_SIN_CONFIRMAR falso. Sólo un token completo "O<dígitos>" puede
leerse como "0<dígitos>", y sólo si la calle confirmada completa coincide.
"""
import json

from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_destinos import CatalogoDestinos, direccion_confirmada_coincide
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, ResultadoEvidencia, TipoEvidencia
from atlas_core.decisiones_pendientes import crear_decision, detectar_decisiones_documento, regenerar_decisiones_persistidas

CONFIRMADO_LARGO = "INTERIOR NUEVA O1148 SAN BERNARDO SAN BERNAR"
CONFIRMADO_CORTO = "INTERIOR NUEVA O1148 SAN BERNARDO"
DOCUMENTAL_480676 = "INTERIOR NUEVA 01148 SAN BERNARDO SAN BERNAR"
OBRA = "AUSIN SAN BERNARDO"
CLIENTE = "MATERIALES Y SOLUCIONES SA"
RUT = "96.692.790-9"


# --- 1. O1148 <-> 01148 con el resto de la dirección idéntico ---

def test_o_inicial_de_numeracion_coincide_con_cero_bajo_calle_completa():
    assert direccion_confirmada_coincide(CONFIRMADO_LARGO, DOCUMENTAL_480676)
    assert direccion_confirmada_coincide(CONFIRMADO_CORTO, DOCUMENTAL_480676)
    # Simétrico: maestro con cero, documento con O.
    assert direccion_confirmada_coincide("INTERIOR NUEVA 01148 SAN BERNARDO", CONFIRMADO_LARGO)


# --- 2. O1148 no coincide con otros números ni otras calles ---

def test_o1148_no_coincide_con_otros_numeros_ni_otra_calle():
    for documental in (
        "INTERIOR NUEVA 1148 SAN BERNARDO SAN BERNAR",    # sin el cero inicial
        "INTERIOR NUEVA 01149 SAN BERNARDO SAN BERNAR",
        "INTERIOR NUEVA 11148 SAN BERNARDO SAN BERNAR",
        "INTERIOR NUEVA 011489 SAN BERNARDO SAN BERNAR",  # contiene 01148 pero es otro número
        "INTERIOR NUEVA 01148 SAN BERNARDA",              # palabra final distinta
        "INTERIOR VIEJA 01148 SAN BERNARDO SAN BERNAR",   # otra calle, mismo número
        "NUEVA 01148 SAN BERNARDO",                       # calle incompleta
        "INTERIOR NUEVA D1148 SAN BERNARDO SAN BERNAR",   # otra letra: no se tolera
    ):
        assert not direccion_confirmada_coincide(CONFIRMADO_LARGO, documental), documental


def test_o_suelta_o_dentro_de_palabra_no_se_convierte():
    # "O 1148" (O separada, p. ej. Oriente) y "SANTO1148" no son una
    # numeración con O inicial.
    assert not direccion_confirmada_coincide("PASAJE LOS ALAMOS O 1148", "PASAJE LOS ALAMOS 01148")
    assert not direccion_confirmada_coincide("CALLE SANTO1148", "CALLE SANT01148")


def test_sin_nombre_de_via_no_basta_el_numero():
    assert not direccion_confirmada_coincide("O1148", "01148 SAN BERNARDO")


# --- 3. diferencia numérica real sigue rechazándose ---

def test_diferencia_numerica_real_sigue_rechazandose():
    assert not direccion_confirmada_coincide("AVENIDA ALFA 01148", "AVENIDA ALFA 01184 COMUNA")
    assert not direccion_confirmada_coincide("CALLE ALFA LOTE 17 PARQUE TECNICO", "CALLE ALFA LOTE 18 PARQUE TECNICO")


# --- 4. la variante histórica exacta sigue funcionando ---

def test_variante_historica_exacta_o1148_sigue_coincidiendo():
    assert direccion_confirmada_coincide(CONFIRMADO_LARGO, CONFIRMADO_LARGO)
    assert direccion_confirmada_coincide(CONFIRMADO_CORTO, CONFIRMADO_LARGO)
    assert not direccion_confirmada_coincide(CONFIRMADO_LARGO, CONFIRMADO_CORTO)


# --- 5. 480676 deja de generar DESTINO_SIN_CONFIRMAR (fixture) ---

def _catalogos_ausin(tmp_path):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    for carpeta in (catalogos, actual, raiz / "reportes"):
        carpeta.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []}, "empresas.json": {}, "vehiculos.json": {},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social=CLIENTE, rut=RUT, fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    destinos = CatalogoDestinos(catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json")
    obras = CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    )
    # Mismo patrón real: dos confirmaciones del mismo lugar (460807, 472008).
    for guia, texto in (("460807", CONFIRMADO_LARGO), ("472008", CONFIRMADO_CORTO)):
        destino = destinos.crear(
            cliente_id=cliente.cliente_id, nombre_destino=texto, direccion=texto, pais="CHILE", fuente=f"TEST_{guia}",
        )
        evidencia = Evidencia(
            tipo=TipoEvidencia.GUIA.value, identificador_fuente=guia, referencia_hash=guia[-1] * 64,
            campos_observados={"obra": OBRA, "destino": texto}, fecha="2026-08-21T00:00:00+00:00",
            actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value,
        )
        relacion = obras.registrar_observacion(
            cliente_id=cliente.cliente_id, nombre_obra=OBRA, destino_id=destino.destino_id, evidencia=evidencia,
        ).relacion
        obras.confirmar_relacion(relacion.relacion_id, actor="test")
    return raiz, catalogos, actual, cliente, obras


def _datos(guia):
    return {"número de guía": guia, "cliente": CLIENTE, "RUT del cliente": RUT, "obra destino": OBRA}


def test_480676_ya_no_genera_destino_sin_confirmar(tmp_path):
    raiz, catalogos, actual, cliente, obras = _catalogos_ausin(tmp_path)
    assert obras.resolver_obra_destino_confirmada_global(nombre_obra=OBRA) is None  # redundancia real
    nuevas = detectar_decisiones_documento(
        archivo="480676.jpeg", datos=_datos("480676"),
        carpeta_catalogos=catalogos, despachar_a_documental=DOCUMENTAL_480676,
    )
    assert not any(d["tipo"] == "DESTINO_SIN_CONFIRMAR" for d in nuevas)
    # Control: una numeración realmente distinta sigue preguntando.
    distintas = detectar_decisiones_documento(
        archivo="999.jpeg", datos=_datos("999"),
        carpeta_catalogos=catalogos, despachar_a_documental="INTERIOR NUEVA 01149 SAN BERNARDO SAN BERNAR",
    )
    assert any(d["tipo"] == "DESTINO_SIN_CONFIRMAR" for d in distintas)


def test_tarjeta_persistida_de_480676_se_retira_al_regenerar(tmp_path):
    raiz, catalogos, actual, cliente, obras = _catalogos_ausin(tmp_path)
    obra = next(o for o in obras.listar_obras() if o.nombre_canonico == OBRA)
    decision = crear_decision(
        tipo="DESTINO_SIN_CONFIRMAR", entidad="RELACION_OBRA_DESTINO", archivo="480676.jpeg",
        numero_guia="480676", numero_transporte="0000360701", campo="destino_entrega",
        valor_documental=DOCUMENTAL_480676, valor_normalizado=DOCUMENTAL_480676,
        identidad_resuelta={"entidad_id": obra.obra_id, "valor_canonico": OBRA},
        candidatos=(), motivos=("OBRA_SIN_RELACION_CONFIRMADA_UNICA",),
        evidencias=({"tipo": "OBRA_IDENTIFICADA", "entidad_id": obra.obra_id},),
        acciones_permitidas=("CONFIRMAR", "NO_CONFIRMAR", "POSPONER"),
        contexto={
            "cliente_id": cliente.cliente_id, "cliente_canonico": CLIENTE, "obra_id": obra.obra_id,
            "obra_canonica": OBRA, "destino_documental": DOCUMENTAL_480676,
        },
    )
    assert regenerar_decisiones_persistidas(decisiones=[decision], carpeta_catalogos=catalogos) == []
    # Control: la misma tarjeta con una numeración realmente distinta se conserva.
    distinta = dict(decision, valor_documental="INTERIOR NUEVA 01149 SAN BERNARDO SAN BERNAR",
                    contexto=dict(decision["contexto"], destino_documental="INTERIOR NUEVA 01149 SAN BERNARDO SAN BERNAR"))
    conservadas = regenerar_decisiones_persistidas(decisiones=[distinta], carpeta_catalogos=catalogos)
    assert [d["tipo"] for d in conservadas] == ["DESTINO_SIN_CONFIRMAR"]


# --- 6. Caso real 475036/475040: O final de numeración ("73O" <-> "730") ---

CONFIRMADO_475040 = "AMERICO VESPUCIO 73O"
DOCUMENTAL_475036 = "AMERICO VESPUCIO 730 TALCAHUANO TALCAHUANO"


def test_o_final_de_numeracion_coincide_con_cero_bajo_calle_completa():
    assert direccion_confirmada_coincide(CONFIRMADO_475040, DOCUMENTAL_475036, comuna_confirmada="TALCAHUANO")
    # Simétrico: maestro con cero, documento con O final.
    assert direccion_confirmada_coincide("AMERICO VESPUCIO 730", "AMERICO VESPUCIO 73O TALCAHUANO")
    # O intermedia también.
    assert direccion_confirmada_coincide("AMERICO VESPUCIO 7O5", "AMERICO VESPUCIO 705 TALCAHUANO")


def test_73o_no_coincide_con_otros_numeros_ni_otra_calle():
    for documental in (
        "AMERICO VESPUCIO 73 TALCAHUANO",        # sin el cero
        "AMERICO VESPUCIO 731 TALCAHUANO",
        "AMERICO VESPUCIO 7300 TALCAHUANO",
        "AMERICO VESPUCIO 703 TALCAHUANO",
        "AMERICO VESPUCI 730 TALCAHUANO",        # calle incompleta/distinta
        "VESPUCIO 730 TALCAHUANO",
    ):
        assert not direccion_confirmada_coincide(CONFIRMADO_475040, documental), documental


def test_o_final_suelta_o_en_palabra_no_se_convierte():
    assert not direccion_confirmada_coincide("PASAJE LOS ALAMOS 73 O", "PASAJE LOS ALAMOS 730")
    assert not direccion_confirmada_coincide("CALLE 2DO 73", "CALLE 2D0 73")
    assert not direccion_confirmada_coincide("73O", "730 TALCAHUANO")  # sin nombre de vía
