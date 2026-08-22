"""Bloque R7 -- B1 universal: reemplaza la whitelist cerrada de 4 motivos
por un registro por contrato/tipo de problema
(`atlas_core.atlas_ia.registro_problemas`). Cubre: estructura del
registro, la puerta de entrada generalizada (ya no sólo
`indicador_revision == REVISAR`), los 4 dominios documentales de siempre
(comportamiento preservado), los 2 dominios nuevos (destino/planta
origen, nunca auto-aplicados), NO_ELEGIBLE_IA explícito (técnico y por
evidencia insuficiente) y que Mobile/Desktop comparten el mismo
`_ejecutar_ia_operacional` (ningún escalamiento paralelo)."""
from __future__ import annotations

import csv
import json

from atlas_core.atlas_ia.contratos import (
    RESULTADO_HIPOTESIS_ABSTENCION,
    RESULTADO_HIPOTESIS_PROPUESTA,
)
from atlas_core.atlas_ia.orquestador import OrquestadorAtlasIA
from atlas_core.atlas_ia.proveedor import ProveedorModeloIASimulado, RespuestaSimulada
from atlas_core.atlas_ia.registro_problemas import (
    MOTIVOS_DOCUMENTALES_TECNICOS_NO_ELEGIBLES,
    MOTIVOS_RUTA_TECNICOS_NO_ELEGIBLES,
    REGISTRO_PROBLEMAS_IA,
    codigos_residuales_no_registrados,
    detectar_problemas_elegibles,
    motivo_ruta_base,
)
from atlas_core.procesamiento_masivo import (
    COLUMNAS,
    _ejecutar_ia_operacional,
    _fila_requiere_atencion_operacional,
    escalar_resultado_ia_en_memoria,
)


def _fila(**cambios):
    fila = {columna: "" for columna in COLUMNAS}
    fila.update({
        "estado_procesamiento": "OK", "fecha": "18-08-2026",
        "chofer": "PERSONA EJEMPLO", "patente_tracto": "AB1234",
        "obra_destino": "OBRA NORTE", "indicador_revision": "REVISAR",
    })
    fila.update(cambios)
    return fila


def _escribir(ruta, filas):
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerows(filas)


def _leer(ruta):
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return {f["archivo"]: f for f in csv.DictReader(archivo, delimiter=";")}


# ============================================================
# Registro -- estructura y genericidad
# ============================================================


def _todos_los_tipos():
    """Bloque R12: `REGISTRO_PROBLEMAS_IA` ahora guarda una TUPLA de
    entradas por clave (varios campos pueden compartir un mismo código,
    p. ej. PATENTE_SIN_HOMOLOGAR en tracto y rampla) -- aplanar antes de
    inspeccionar."""
    return [tipo for entradas in REGISTRO_PROBLEMAS_IA.values() for tipo in entradas]


def test_registro_cubre_los_4_dominios_documentales_de_siempre_mas_2_nuevos():
    dominios = {tipo.dominio for tipo in _todos_los_tipos()}
    assert {"OBRA_DESTINO", "CHOFER", "PATENTE", "CLIENTE"} <= dominios
    assert "DESTINO" in dominios and "PLANTA_ORIGEN" in dominios


def test_registro_cubre_los_dominios_agregados_en_bloque_r12():
    """Bloque R12 -- cierre del bypass real: CLIENTE_AUSENTE (con decisión
    humana accionable desde R9) y FECHA_SIN_CORROBORAR/MATERIAL_AUSENTE
    nunca tuvieron entrada en el registro; ahora sí."""
    dominios = {tipo.dominio for tipo in _todos_los_tipos()}
    assert {"FECHA", "MATERIAL"} <= dominios
    todos_los_codigos = {codigo for tipo in _todos_los_tipos() for codigo in tipo.codigos}
    assert {
        "CLIENTE_AUSENTE", "CHOFER_AUSENTE", "FECHA_SIN_CORROBORAR",
        "MATERIAL_AUSENTE", "PATENTE_AMBIGUA", "CLIENTE_NUEVA_ENTIDAD_NO_CATALOGADA",
    } <= todos_los_codigos


def test_patente_sin_homologar_cubre_tracto_y_rampla_sin_colision():
    """Caso real 472247: antes, dos entradas con el mismo (fuente, código)
    colisionaban en la misma clave -- sólo la última sobrevivía y B1
    nunca evaluaba patente_rampla. Ahora ambas coexisten."""
    entradas = REGISTRO_PROBLEMAS_IA[("MOTIVO_DOCUMENTAL", "PATENTE_SIN_HOMOLOGAR")]
    campos = {tipo.campo for tipo in entradas}
    assert campos == {"patente_tracto", "patente_rampla"}


def test_solo_los_dominios_curados_se_auto_aplican():
    aplicables = {tipo.dominio for tipo in _todos_los_tipos() if tipo.aplicable_automaticamente}
    # OBRA_DESTINO/CHOFER/PATENTE/CLIENTE (de siempre) + FECHA/MATERIAL
    # (Bloque R12, mismo patrón "documentos relacionados").
    assert aplicables == {"OBRA_DESTINO", "CHOFER", "PATENTE", "CLIENTE", "FECHA", "MATERIAL"}
    no_aplicables = {tipo.dominio for tipo in _todos_los_tipos() if not tipo.aplicable_automaticamente}
    # DESTINO/PLANTA_ORIGEN (de siempre, R7) -- nunca auto-aplican una
    # dirección o planta sin confirmación humana.
    assert {"DESTINO", "PLANTA_ORIGEN"} <= no_aplicables


def test_motivo_ruta_base_ignora_detalle_parentetico_y_de_dos_puntos():
    assert motivo_ruta_base("MULTIPLES_UBICACIONES_DISPERSAS(5)") == "MULTIPLES_UBICACIONES_DISPERSAS"
    assert motivo_ruta_base("GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL: San != Angol") == "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL"
    assert motivo_ruta_base("") == ""


def test_detectar_problemas_elegibles_combina_las_3_fuentes_de_una_fila():
    fila = {
        "motivos_revision_documento": "CLIENTE_SIN_CORROBORAR | CHOFER_SIN_CORROBORAR",
        "motivo_ruta": "DESTINO_SIN_DATO",
        "motivo_origen_gps": "CONFLICTO_REAL_EN_VENTANA(AZA_COLINA:score=0.5,solape=10.0%)",
    }
    encontrados = {(tipo.dominio, codigo) for tipo, codigo in detectar_problemas_elegibles(fila)}
    assert encontrados == {
        ("CLIENTE", "CLIENTE_SIN_CORROBORAR"), ("CHOFER", "CHOFER_SIN_CORROBORAR"),
        ("DESTINO", "DESTINO_SIN_DATO"), ("PLANTA_ORIGEN", "CONFLICTO_REAL_EN_VENTANA"),
    }


def test_un_motivo_no_registrado_no_produce_ningun_match_pero_queda_marcado_residual():
    """Bloque R12: MATERIAL_AUSENTE ya está registrado (ver bloque de
    arriba) -- el ejemplo de "no registrado" pasa a ser un código
    inventado, que jamás podrá tener entrada real. `detectar_problemas_
    elegibles` sigue sin producir ningún match para él (nunca inventa una
    evaluación), pero `codigos_residuales_no_registrados` -- el
    complemento exacto que ahora usa el dispatcher -- SÍ lo marca, así
    que nunca desaparece en silencio."""
    fila = {
        "motivos_revision_documento": "PESO_DUDOSO_NUEVO",
        "motivo_ruta": "SIN_EVIDENCIA_GPS", "motivo_origen_gps": "",
    }
    assert detectar_problemas_elegibles(fila) == []
    assert codigos_residuales_no_registrados(fila) == [
        ("MOTIVO_DOCUMENTAL", "PESO_DUDOSO_NUEVO"), ("MOTIVO_RUTA", "SIN_EVIDENCIA_GPS"),
    ]


# ============================================================
# Puerta de entrada -- ya no depende sólo de indicador_revision
# ============================================================


def test_fila_requiere_atencion_ve_motivo_ruta_aunque_indicador_este_ok():
    fila = _fila(indicador_revision="OK", motivos_revision_documento="", estado_ruta="REQUIERE_REVISION")
    assert _fila_requiere_atencion_operacional(fila) is True


def test_fila_sin_ningun_problema_no_requiere_atencion():
    fila = _fila(indicador_revision="OK", motivos_revision_documento="", estado_ruta="RUTA_CALCULADA")
    assert _fila_requiere_atencion_operacional(fila) is False


# ============================================================
# Dominios documentales de siempre -- comportamiento preservado
# ============================================================


def test_dominio_documental_de_siempre_sigue_llamando_y_trazando_igual_que_antes(tmp_path):
    """Evidencia por documentos relacionados (nivel DOCUMENTO_RELACIONADO)
    nunca alcanza, por sí sola, la clase A (`_clasificar_propuesta` exige
    CONFIRMACION_HUMANA/EXTERNO_OFICIAL) -- mismo límite ya vigente antes
    de este bloque (ver caso real 460807/472008, ambos B_ASISTENCIA en
    producción). Lo que este bloque cambia es SÓLO el despacho (registro
    universal en vez de diccionario fijo); la clasificación resultante es
    idéntica a la que ya daba el código anterior con la misma evidencia."""
    ruta = tmp_path / "datos.csv"
    filas = [
        _fila(archivo="fuente.jpg", obra_destino="OBRA NORTE", indicador_revision="OK"),
        _fila(archivo="objetivo.jpg", obra_destino="No encontrado",
              motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR"),
    ]
    _escribir(ruta, filas)
    proveedor = ProveedorModeloIASimulado(respuestas_por_valor_documental={
        "No encontrado": RespuestaSimulada(resultado=RESULTADO_HIPOTESIS_PROPUESTA, valor_propuesto="OBRA NORTE"),
    })
    resumen = _ejecutar_ia_operacional(ruta, {"objetivo.jpg"}, OrquestadorAtlasIA(proveedor=proveedor))
    assert resumen["llamadas"] == 1 and resumen["B"] == 1
    salida = _leer(ruta)
    assert salida["objetivo.jpg"]["obra_destino"] == "No encontrado"  # clase B: nunca se auto-aplica
    traza = json.loads(salida["objetivo.jpg"]["resultado_atlas_ia_json"])[0]
    assert traza["dominio"] == "OBRA_DESTINO" and traza["campo"] == "obra_destino"
    assert traza["clasificacion"] == "B_ASISTENCIA"
    assert traza["aplicado_operacionalmente"] is False


def test_dominio_documental_de_siempre_SI_auto_aplica_ante_evidencia_de_clase_a(tmp_path, monkeypatch):
    """Verifica el mecanismo de auto-aplicación en sí (independiente de
    qué tan buena sea la evidencia por documentos relacionados): con
    evidencia de nivel CONFIRMACION_HUMANA (clase A real), la propuesta sí
    se escribe -- mismo comportamiento exacto que el diccionario fijo
    anterior tenía para estos 4 campos."""
    import dataclasses

    import atlas_core.atlas_ia.registro_problemas as registro_mod
    from atlas_core.atlas_ia.contratos import EvidenciaIA

    def evidencia_fuerte(fila, filas, *, carpeta_catalogos=None):
        return (EvidenciaIA(
            identificador="ledger:decision-1", campo="obra_destino", valor="OBRA NORTE",
            tipo_fuente="DECISION_HUMANA", nivel="CONFIRMACION_HUMANA", es_decision_humana=True,
            procedencia="test",
        ),)
    clave = ("MOTIVO_DOCUMENTAL", "OBRA_DESTINO_SIN_CORROBORAR")
    # Bloque R12: el registro guarda una TUPLA por clave -- OBRA_DESTINO_
    # SIN_CORROBORAR sigue teniendo una única entrada, así que se
    # reemplaza esa y se vuelve a envolver en una tupla de 1.
    (entrada_original,) = registro_mod.REGISTRO_PROBLEMAS_IA[clave]
    tipo_modificado = dataclasses.replace(entrada_original, recopilar_evidencia=evidencia_fuerte)
    monkeypatch.setitem(registro_mod.REGISTRO_PROBLEMAS_IA, clave, (tipo_modificado,))
    ruta = tmp_path / "datos.csv"
    filas = [_fila(archivo="objetivo.jpg", obra_destino="No encontrado", motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR")]
    _escribir(ruta, filas)
    proveedor = ProveedorModeloIASimulado(respuestas_por_valor_documental={
        "No encontrado": RespuestaSimulada(resultado=RESULTADO_HIPOTESIS_PROPUESTA, valor_propuesto="OBRA NORTE"),
    })
    resumen = _ejecutar_ia_operacional(ruta, {"objetivo.jpg"}, OrquestadorAtlasIA(proveedor=proveedor))
    assert resumen["A"] == 1
    salida = _leer(ruta)
    assert salida["objetivo.jpg"]["obra_destino"] == "OBRA NORTE"
    assert "OBRA_DESTINO_SIN_CORROBORAR" not in salida["objetivo.jpg"]["motivos_revision_documento"]
    assert salida["objetivo.jpg"]["indicador_revision"] == "OK"


# ============================================================
# Dominios nuevos -- destino / planta origen: elegibles, nunca auto-aplicados
# ============================================================


def test_destino_con_evidencia_de_obra_relacionada_escala_a_b1_y_nunca_se_auto_aplica(tmp_path):
    ruta = tmp_path / "datos.csv"
    filas = [
        _fila(
            archivo="resuelto.jpg", obra_destino="OBRA NORTE", indicador_revision="OK",
            estado_ruta="RUTA_CALCULADA", direccion_entrega="Avenida Norte 100, Santiago, RM, Chile",
        ),
        _fila(
            archivo="objetivo.jpg", obra_destino="OBRA NORTE", indicador_revision="OK",
            planta_origen_id="planta-1", estado_ruta="REQUIERE_REVISION", motivo_ruta="DESTINO_SIN_DATO",
        ),
    ]
    _escribir(ruta, filas)
    proveedor = ProveedorModeloIASimulado(respuestas_por_valor_documental={
        "": RespuestaSimulada(
            resultado=RESULTADO_HIPOTESIS_PROPUESTA, valor_propuesto="Avenida Norte 100, Santiago, RM, Chile",
        ),
    })
    resumen = _ejecutar_ia_operacional(ruta, {"objetivo.jpg"}, OrquestadorAtlasIA(proveedor=proveedor))
    assert resumen["llamadas"] == 1
    salida = _leer(ruta)
    # Nunca se auto-aplica -- despachar_a_crudo sigue vacío, la decisión
    # DESTINO_NO_RESUELTO (Bloque R6) sigue siendo la única vía de escritura.
    assert salida["objetivo.jpg"]["despachar_a_crudo"] == ""
    traza = json.loads(salida["objetivo.jpg"]["resultado_atlas_ia_json"])[0]
    assert traza["dominio"] == "DESTINO"
    assert traza["aplicado_operacionalmente"] is False


def test_destino_sin_ninguna_obra_relacionada_resuelta_no_llama_a_b1(tmp_path):
    ruta = tmp_path / "datos.csv"
    filas = [_fila(
        archivo="472037.jpg", obra_destino="ING Y CONST FUNDAMENTA SPA", indicador_revision="OK",
        planta_origen_id="planta-1", estado_ruta="REQUIERE_REVISION", motivo_ruta="DESTINO_SIN_DATO",
    )]
    _escribir(ruta, filas)
    proveedor = ProveedorModeloIASimulado(respuestas_por_valor_documental={})
    resumen = _ejecutar_ia_operacional(ruta, {"472037.jpg"}, OrquestadorAtlasIA(proveedor=proveedor))
    assert resumen["llamadas"] == 0  # sin evidencia, nunca se llama a B1 para nada
    salida = _leer(ruta)
    traza = json.loads(salida["472037.jpg"]["resultado_atlas_ia_json"])[0]
    assert traza == {
        "problema": "DESTINO_SIN_DATO", "dominio": "DESTINO", "campo": "despachar_a_crudo",
        "elegible_ia": True, "llamada_realizada": False, "razon_no_elegible": "SIN_EVIDENCIA_PARA_RAZONAR",
    }


def test_planta_origen_con_conflicto_gps_escala_a_b1(tmp_path):
    from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad

    catalogos = tmp_path / "catalogos"; catalogos.mkdir()
    plantas = CatalogoPlantas(catalogos / "plantas.json")
    plantas.crear(nombre="AZA COLINA", pais="CHILE", fuente="TEST", estado_calidad=EstadoCalidad.CONFIRMADA)
    plantas.crear(nombre="AZA RENCA", pais="CHILE", fuente="TEST", estado_calidad=EstadoCalidad.CONFIRMADA)

    ruta = tmp_path / "datos.csv"
    filas = [_fila(
        archivo="conflicto.jpg", indicador_revision="OK", estado_ruta="ORIGEN_NO_DETERMINADO",
        motivo_origen_gps="CONFLICTO_REAL_EN_VENTANA(AZA_COLINA:score=0.5,solape=10.0%;AZA_RENCA:score=0.3,solape=5.0%)",
    )]
    _escribir(ruta, filas)
    proveedor = ProveedorModeloIASimulado(respuestas_por_valor_documental={})
    resumen = _ejecutar_ia_operacional(
        ruta, {"conflicto.jpg"}, OrquestadorAtlasIA(proveedor=proveedor), carpeta_catalogos=catalogos,
    )
    assert resumen["llamadas"] == 1  # 2 candidatos == evidencia real, se llama (y se abstiene, sin propuesta configurada)
    salida = _leer(ruta)
    traza = json.loads(salida["conflicto.jpg"]["resultado_atlas_ia_json"])[0]
    assert traza["dominio"] == "PLANTA_ORIGEN"
    assert traza["aplicado_operacionalmente"] is False
    assert salida["conflicto.jpg"]["planta_origen_id"] == ""  # nunca se auto-aplica


def test_planta_origen_sin_catalogo_de_plantas_no_llama_a_b1(tmp_path):
    ruta = tmp_path / "datos.csv"
    filas = [_fila(
        archivo="conflicto.jpg", indicador_revision="OK", estado_ruta="ORIGEN_NO_DETERMINADO",
        motivo_origen_gps="CONFLICTO_REAL_EN_VENTANA(AZA_COLINA:score=0.5,solape=10.0%;AZA_RENCA:score=0.3,solape=5.0%)",
    )]
    _escribir(ruta, filas)
    resumen = _ejecutar_ia_operacional(ruta, {"conflicto.jpg"}, OrquestadorAtlasIA(proveedor=ProveedorModeloIASimulado(respuestas_por_valor_documental={})))
    assert resumen["llamadas"] == 0
    traza = json.loads(_leer(ruta)["conflicto.jpg"]["resultado_atlas_ia_json"])[0]
    assert traza["razon_no_elegible"] == "SIN_EVIDENCIA_PARA_RAZONAR"


# ============================================================
# NO_ELEGIBLE_IA -- nunca un silencio de "0 llamadas" sin explicación
# ============================================================


def test_motivo_ruta_tecnico_se_registra_como_no_elegible_sin_llamar(tmp_path):
    for motivo_tecnico in MOTIVOS_RUTA_TECNICOS_NO_ELEGIBLES:
        ruta = tmp_path / f"datos_{motivo_tecnico}.csv"
        filas = [_fila(archivo="x.jpg", indicador_revision="OK", estado_ruta="REQUIERE_REVISION", motivo_ruta=motivo_tecnico)]
        _escribir(ruta, filas)
        resumen = _ejecutar_ia_operacional(ruta, {"x.jpg"}, OrquestadorAtlasIA(proveedor=ProveedorModeloIASimulado(respuestas_por_valor_documental={})))
        assert resumen["llamadas"] == 0
        traza = json.loads(_leer(ruta)["x.jpg"]["resultado_atlas_ia_json"])[0]
        assert traza["elegible_ia"] is False
        assert traza["razon_no_elegible"] == "FALLA_TECNICA_EXTERNA_SIN_RAZONAMIENTO_POSIBLE"


def test_motivo_ruta_no_registrado_ni_tecnico_se_registra_como_evidencia_insuficiente(tmp_path):
    ruta = tmp_path / "datos.csv"
    filas = [_fila(archivo="464981.jpg", indicador_revision="OK", estado_ruta="ORIGEN_NO_DETERMINADO", motivo_ruta="SIN_EVIDENCIA_GPS")]
    _escribir(ruta, filas)
    resumen = _ejecutar_ia_operacional(ruta, {"464981.jpg"}, OrquestadorAtlasIA(proveedor=ProveedorModeloIASimulado(respuestas_por_valor_documental={})))
    assert resumen["llamadas"] == 0
    traza = json.loads(_leer(ruta)["464981.jpg"]["resultado_atlas_ia_json"])[0]
    assert traza["elegible_ia"] is False
    assert traza["razon_no_elegible"] == "EVIDENCIA_INSUFICIENTE_PARA_FORMULAR_PREGUNTA"


def test_motivo_documental_estructural_se_registra_como_no_elegible_sin_llamar(tmp_path):
    """Bloque R12 -- bypass real cerrado: GUIA_AUSENTE/TRANSPORTE_AUSENTE/
    DOCUMENTO_DEGRADADO (documento sin sustrato para razonar) antes NUNCA
    producían ninguna traza -- ni evaluados ni explicados. Ahora usan el
    mismo mecanismo de dos niveles que ya existía sólo para motivo_ruta."""
    for motivo_tecnico in MOTIVOS_DOCUMENTALES_TECNICOS_NO_ELEGIBLES:
        ruta = tmp_path / f"datos_{motivo_tecnico}.csv"
        filas = [_fila(archivo="x.jpg", indicador_revision="REVISAR", motivos_revision_documento=motivo_tecnico)]
        _escribir(ruta, filas)
        resumen = _ejecutar_ia_operacional(ruta, {"x.jpg"}, OrquestadorAtlasIA(proveedor=ProveedorModeloIASimulado(respuestas_por_valor_documental={})))
        assert resumen["llamadas"] == 0
        traza = json.loads(_leer(ruta)["x.jpg"]["resultado_atlas_ia_json"])[0]
        assert traza["problema"] == motivo_tecnico
        assert traza["elegible_ia"] is False
        assert traza["razon_no_elegible"] == "FALLA_ESTRUCTURAL_SIN_RAZONAMIENTO_POSIBLE"


def test_motivo_origen_gps_no_registrado_tambien_deja_constancia(tmp_path):
    """Bloque R12: antes, un `motivo_origen_gps` sin entrada registrada
    (a diferencia de `motivo_ruta`) desaparecía en silencio -- las tres
    fuentes ahora comparten el mismo mecanismo."""
    ruta = tmp_path / "datos.csv"
    filas = [_fila(archivo="x.jpg", indicador_revision="OK", estado_ruta="ORIGEN_NO_DETERMINADO", motivo_origen_gps="MOTIVO_GPS_FUTURO_INVENTADO")]
    _escribir(ruta, filas)
    resumen = _ejecutar_ia_operacional(ruta, {"x.jpg"}, OrquestadorAtlasIA(proveedor=ProveedorModeloIASimulado(respuestas_por_valor_documental={})))
    assert resumen["llamadas"] == 0
    traza = json.loads(_leer(ruta)["x.jpg"]["resultado_atlas_ia_json"])[0]
    assert traza["problema"] == "MOTIVO_GPS_FUTURO_INVENTADO"
    assert traza["dominio"] == "PLANTA_ORIGEN"
    assert traza["elegible_ia"] is False
    assert traza["razon_no_elegible"] == "EVIDENCIA_INSUFICIENTE_PARA_FORMULAR_PREGUNTA"


def test_cliente_ausente_ahora_escala_a_b1_caso_real_472238(tmp_path):
    """Bloque R12 -- caso real 472238/472239: CLIENTE_AUSENTE tiene
    decisión humana accionable (REGISTRAR_CLIENTE_MANUAL, Bloque R9)
    desde hace varios bloques, pero nunca tuvo entrada en el registro --
    B1 nunca lo evaluaba pese a ser plenamente accionable."""
    ruta = tmp_path / "datos.csv"
    filas = [
        _fila(archivo="fuente.jpg", cliente="CLIENTE REAL SA", indicador_revision="OK", numero_transporte="T1"),
        _fila(archivo="objetivo.jpg", cliente="No encontrado", motivos_revision_documento="CLIENTE_AUSENTE", numero_transporte="T1"),
    ]
    _escribir(ruta, filas)
    proveedor = ProveedorModeloIASimulado(respuestas_por_valor_documental={
        "No encontrado": RespuestaSimulada(resultado=RESULTADO_HIPOTESIS_PROPUESTA, valor_propuesto="CLIENTE REAL SA"),
    })
    resumen = _ejecutar_ia_operacional(ruta, {"objetivo.jpg"}, OrquestadorAtlasIA(proveedor=proveedor))
    assert resumen["llamadas"] == 1
    traza = json.loads(_leer(ruta)["objetivo.jpg"]["resultado_atlas_ia_json"])[0]
    assert traza["dominio"] == "CLIENTE" and traza["problema"] == "CLIENTE_AUSENTE"


def test_sin_proveedor_configurado_sigue_dejando_constancia_de_elegibilidad(tmp_path):
    ruta = tmp_path / "datos.csv"
    filas = [
        _fila(archivo="fuente.jpg", obra_destino="OBRA NORTE", indicador_revision="OK"),
        _fila(archivo="objetivo.jpg", obra_destino="No encontrado", motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR"),
    ]
    _escribir(ruta, filas)
    resumen = _ejecutar_ia_operacional(ruta, {"objetivo.jpg"}, None)
    assert resumen["llamadas"] == 0
    traza = json.loads(_leer(ruta)["objetivo.jpg"]["resultado_atlas_ia_json"])[0]
    assert traza["elegible_ia"] is True
    assert traza["llamada_realizada"] is False
    assert traza["razon_no_elegible"] == "SIN_PROVEEDOR_IA_CONFIGURADO"


# ============================================================
# Bloque R12 -- prueba de cobertura arquitectónica: TODOS los motivos
# documentales conocidos por Atlas quedan explícitamente clasificados.
# Protege contra el bypass real de este bloque (10 de 14 motivos sin
# ninguna entrada ni fallback) Y contra el que describe la Parte D del
# ticket: si mañana alguien agrega PESO_DUDOSO_NUEVO al enum y olvida
# integrarlo cognitivamente, este test debe fallar.
# ============================================================


def test_todo_motivo_documental_conocido_tiene_clasificacion_explicita():
    from atlas_core.atlas_ia.registro_problemas import MOTIVOS_DOCUMENTALES_TECNICOS_NO_ELEGIBLES
    from atlas_core.procesamiento_masivo import MOTIVOS_NO_BLOQUEANTES, MotivoRevisionDocumento

    codigos_registrados = {
        codigo for tipo in _todos_los_tipos() for codigo in tipo.codigos
    }
    sin_clasificar = []
    for motivo in MotivoRevisionDocumento:
        codigo = motivo.value
        clasificado = (
            codigo in codigos_registrados
            or codigo in MOTIVOS_DOCUMENTALES_TECNICOS_NO_ELEGIBLES
            # Los no bloqueantes puros que además quedaron registrados
            # arriba (MATERIAL_AUSENTE) ya cuentan por la primera
            # condición; los que no tienen registro real (por ahora
            # ninguno) también deben quedar explícitos aquí.
            or codigo in MOTIVOS_NO_BLOQUEANTES
        )
        if not clasificado:
            sin_clasificar.append(codigo)
    assert sin_clasificar == [], (
        f"Motivo(s) sin clasificación de elegibilidad IA: {sin_clasificar} -- "
        "deben quedar registrados en REGISTRO_PROBLEMAS_IA, en "
        "MOTIVOS_DOCUMENTALES_TECNICOS_NO_ELEGIBLES, o justificar por qué "
        "no aplica ninguno de los dos."
    )


def test_todo_motivo_documental_bloqueante_produce_traza_end_to_end(tmp_path):
    """Complemento del test anterior, pero end-to-end real: para cada
    motivo BLOQUEANTE (los no bloqueantes nunca entran a Revisión de
    Atlas, ver `_fila_requiere_atencion_operacional`/`MOTIVOS_NO_
    BLOQUEANTES`), correr `_ejecutar_ia_operacional` y exigir que
    `resultado_atlas_ia_json` tenga al menos una entrada con ese código
    -- nunca una fila REVISAR sin ningún rastro de evaluación IA."""
    from atlas_core.procesamiento_masivo import MOTIVOS_NO_BLOQUEANTES, MotivoRevisionDocumento

    for motivo in MotivoRevisionDocumento:
        codigo = motivo.value
        if codigo in MOTIVOS_NO_BLOQUEANTES:
            continue
        ruta = tmp_path / f"cobertura_{codigo}.csv"
        _escribir(ruta, [_fila(archivo="x.jpg", indicador_revision="REVISAR", motivos_revision_documento=codigo)])
        resumen = _ejecutar_ia_operacional(
            ruta, {"x.jpg"}, OrquestadorAtlasIA(proveedor=ProveedorModeloIASimulado(respuestas_por_valor_documental={})),
        )
        salida = _leer(ruta)["x.jpg"]
        assert salida.get("resultado_atlas_ia_json"), f"{codigo}: fila REVISAR sin ningún rastro de evaluación IA"
        codigos_en_traza = {r["problema"] for r in json.loads(salida["resultado_atlas_ia_json"])}
        assert codigo in codigos_en_traza, f"{codigo}: no aparece en su propia traza ({codigos_en_traza})"


# ============================================================
# Mobile y Desktop comparten el mismo escalamiento -- nunca dos flujos
# ============================================================


def test_escalar_resultado_ia_en_memoria_mobile_usa_el_mismo_registro_universal():
    """`escalar_resultado_ia_en_memoria` es la entrada de Mobile -- delega
    en el MISMO `_ejecutar_ia_operacional` (y por lo tanto en el mismo
    registro universal) que usa el lote de Desktop, nunca un segundo
    camino de escalamiento."""
    historial = [_fila(archivo="fuente.jpg", obra_destino="OBRA NORTE", indicador_revision="OK")]
    datos = _fila(archivo="", obra_destino="No encontrado", motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR")
    proveedor = ProveedorModeloIASimulado(respuestas_por_valor_documental={
        "No encontrado": RespuestaSimulada(resultado=RESULTADO_HIPOTESIS_ABSTENCION),
    })
    salida, resumen = escalar_resultado_ia_en_memoria(
        datos, historial, orquestador_ia=OrquestadorAtlasIA(proveedor=proveedor),
    )
    assert resumen["llamadas"] == 1
    traza = json.loads(salida["resultado_atlas_ia_json"])[0]
    assert traza["dominio"] == "OBRA_DESTINO"
