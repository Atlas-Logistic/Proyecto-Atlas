import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from atlas_core import almacenamiento_portable
from atlas_core.catalogo_clientes import CatalogoClientes
from atlas_core.catalogo_destinos import CatalogoDestinos
from atlas_core.catalogo_obras_destinos import (
    CatalogoObrasDestinos,
    CatalogoObrasDestinosCorruptoError,
    ErrorCatalogoObrasDestinos,
    EstadoObra,
    EstadoRelacion,
    Evidencia,
    ResultadoEvidencia,
    TipoEvidencia,
    normalizar_nombre_obra,
)


class Reloj:
    def __init__(self):
        self.actual = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self):
        valor = self.actual
        self.actual += timedelta(seconds=1)
        return valor


class Identificadores:
    def __init__(self):
        self.valor = 0

    def __call__(self):
        self.valor += 1
        return f"id-{self.valor}"


def _entorno(tmp_path: Path):
    carpeta = tmp_path / "catalogos_privados"
    clientes = carpeta / "clientes.json"
    destinos = carpeta / "destinos_maestros.json"
    reloj = Reloj()
    cliente = CatalogoClientes(clientes, reloj=reloj, generador_id=Identificadores()).crear(
        razon_social="CLIENTE SINTETICO SA", fuente="PRUEBA"
    )
    destino = CatalogoDestinos(
        destinos,
        ruta_clientes=clientes,
        reloj=reloj,
        generador_id=Identificadores(),
    ).crear(
        cliente_id=cliente.cliente_id,
        nombre_destino="DESTINO SINTETICO",
        direccion="CALLE PRUEBA 123",
        pais="CHILE",
        fuente="PRUEBA",
    )
    catalogo = CatalogoObrasDestinos(
        carpeta / "obras_destinos.json",
        ruta_clientes=clientes,
        ruta_destinos=destinos,
        reloj=reloj,
        generador_id=Identificadores(),
    )
    return catalogo, cliente, destino


def _evidencia(identificador="guia-sintetica-1", *, resultado="SOPORTA"):
    return Evidencia(
        tipo=TipoEvidencia.GUIA.value,
        identificador_fuente=identificador,
        referencia_hash="a" * 64,
        campos_observados={"obra": "OBRA SINTETICA", "direccion": "CALLE PRUEBA 123"},
        fecha="2026-01-01T00:00:00+00:00",
        actor_proceso="test",
        resultado=resultado,
    )


def _evidencia_externa():
    return Evidencia(
        tipo=TipoEvidencia.FUENTE_EXTERNA.value,
        identificador_fuente="fuente-oficial-sintetica",
        referencia_hash="b" * 64,
        campos_observados={"razon_social": "OBRA CANONICA LIMITADA"},
        fecha="2026-01-01T00:00:00+00:00",
        actor_proceso="test-identidad",
        resultado=ResultadoEvidencia.SOPORTA.value,
    )


def _observar(catalogo, cliente, destino, evidencia=None):
    return catalogo.registrar_observacion(
        cliente_id=cliente.cliente_id,
        nombre_obra="OBRA SINTETICA",
        destino_id=destino.destino_id,
        evidencia=evidencia or _evidencia(),
    )


def test_catalogo_ausente_y_vacio_versionado_son_validos(tmp_path):
    catalogo, _, _ = _entorno(tmp_path)
    assert catalogo.listar_obras() == []
    catalogo.ruta.write_text(
        json.dumps({"version_formato": 1, "obras": [], "relaciones": []}),
        encoding="utf-8",
    )
    assert catalogo.listar_relaciones() == []


def test_inicializar_vacio_es_atomico_y_no_sobrescribe(tmp_path):
    catalogo, _, _ = _entorno(tmp_path)
    assert catalogo.inicializar_vacio() == catalogo.ruta
    assert json.loads(catalogo.ruta.read_text(encoding="utf-8")) == {
        "version_formato": 1,
        "obras": [],
        "relaciones": [],
    }
    contenido = catalogo.ruta.read_bytes()
    with pytest.raises(ErrorCatalogoObrasDestinos, match="ya existe"):
        catalogo.inicializar_vacio()
    assert catalogo.ruta.read_bytes() == contenido


@pytest.mark.parametrize("version", [0, 2, "1"])
def test_version_desconocida_se_rechaza(tmp_path, version):
    catalogo, _, _ = _entorno(tmp_path)
    catalogo.ruta.write_text(
        json.dumps({"version_formato": version, "obras": [], "relaciones": []}),
        encoding="utf-8",
    )
    with pytest.raises(CatalogoObrasDestinosCorruptoError, match="versión"):
        catalogo.listar_obras()


def test_json_y_esquema_invalidos_se_rechazan(tmp_path):
    catalogo, _, _ = _entorno(tmp_path)
    catalogo.ruta.write_text("{", encoding="utf-8")
    with pytest.raises(CatalogoObrasDestinosCorruptoError):
        catalogo.listar_obras()
    catalogo.ruta.write_text(
        json.dumps({"version_formato": 1, "obras": {}}), encoding="utf-8"
    )
    with pytest.raises(CatalogoObrasDestinosCorruptoError, match="raíz"):
        catalogo.listar_obras()


def test_estado_invalido_e_ids_duplicados_se_rechazan(tmp_path):
    catalogo, cliente, destino = _entorno(tmp_path)
    _observar(catalogo, cliente, destino)
    contenido = json.loads(catalogo.ruta.read_text(encoding="utf-8"))
    contenido["obras"][0]["estado"] = "INVENTADO"
    catalogo.ruta.write_text(json.dumps(contenido), encoding="utf-8")
    with pytest.raises(CatalogoObrasDestinosCorruptoError, match="estado"):
        catalogo.listar_obras()

    contenido["obras"][0]["estado"] = "OBSERVADA"
    contenido["obras"].append(dict(contenido["obras"][0]))
    catalogo.ruta.write_text(json.dumps(contenido), encoding="utf-8")
    with pytest.raises(CatalogoObrasDestinosCorruptoError, match="duplicados"):
        catalogo.listar_obras()


def test_integridad_rechaza_cliente_obra_y_destino_huerfanos(tmp_path):
    catalogo, cliente, destino = _entorno(tmp_path)
    _observar(catalogo, cliente, destino)
    original = json.loads(catalogo.ruta.read_text(encoding="utf-8"))

    casos = [
        ("obras", "cliente_id", "cliente-ausente", "cliente"),
        ("relaciones", "obra_id", "obra-ausente", "obra"),
        ("relaciones", "destino_id", "destino-ausente", "destino"),
    ]
    for coleccion, campo, valor, patron in casos:
        contenido = json.loads(json.dumps(original))
        contenido[coleccion][0][campo] = valor
        catalogo.ruta.write_text(json.dumps(contenido), encoding="utf-8")
        with pytest.raises(CatalogoObrasDestinosCorruptoError, match=patron):
            catalogo.listar_obras()


def test_relacion_rechaza_destino_de_otro_cliente(tmp_path):
    catalogo, cliente, _ = _entorno(tmp_path)
    otro = CatalogoClientes(catalogo.ruta_clientes, reloj=Reloj()).crear(
        razon_social="OTRO CLIENTE SINTETICO", fuente="PRUEBA"
    )
    destino_otro = CatalogoDestinos(
        catalogo.ruta_destinos,
        ruta_clientes=catalogo.ruta_clientes,
        reloj=Reloj(),
    ).crear(
        cliente_id=otro.cliente_id,
        nombre_destino="DESTINO DE OTRO CLIENTE",
        pais="CHILE",
        fuente="PRUEBA",
    )
    with pytest.raises(ErrorCatalogoObrasDestinos, match="otro cliente"):
        catalogo.registrar_observacion(
            cliente_id=cliente.cliente_id,
            nombre_obra="OBRA SINTETICA",
            destino_id=destino_otro.destino_id,
            evidencia=_evidencia(),
        )


def test_relacion_activa_duplicada_se_rechaza(tmp_path):
    catalogo, cliente, destino = _entorno(tmp_path)
    _observar(catalogo, cliente, destino)
    contenido = json.loads(catalogo.ruta.read_text(encoding="utf-8"))
    duplicada = dict(contenido["relaciones"][0])
    duplicada["relacion_id"] = "otra"
    contenido["relaciones"].append(duplicada)
    catalogo.ruta.write_text(json.dumps(contenido), encoding="utf-8")
    with pytest.raises(CatalogoObrasDestinosCorruptoError, match="activa duplicada"):
        catalogo.listar_relaciones()


def test_observacion_crea_candidato_y_relacion_pendiente(tmp_path):
    catalogo, cliente, destino = _entorno(tmp_path)
    resultado = _observar(catalogo, cliente, destino)
    assert resultado.obra.estado == EstadoObra.OBSERVADA.value
    assert resultado.relacion.estado == EstadoRelacion.PENDIENTE.value
    assert catalogo.resolver_obra_destino_confirmada(
        cliente_id=cliente.cliente_id, nombre_obra="OBRA SINTETICA"
    ) is None


def test_actualizar_identidad_preserva_id_cliente_estado_e_historial(tmp_path):
    catalogo, cliente, destino = _entorno(tmp_path)
    observada = _observar(catalogo, cliente, destino).obra
    actualizada = catalogo.actualizar_identidad_obra(
        observada.obra_id,
        nombre_canonico="OBRA CANONICA LIMITADA",
        aliases_documentales=("OBRA SINTETICA",),
        evidencia=_evidencia_externa(),
    )
    assert actualizada.obra_id == observada.obra_id
    assert actualizada.cliente_id == observada.cliente_id
    assert actualizada.estado == observada.estado
    assert actualizada.fecha_creacion == observada.fecha_creacion
    assert actualizada.nombre_canonico == "OBRA CANONICA LIMITADA"
    assert actualizada.aliases_documentales == ("OBRA SINTETICA",)
    assert len(actualizada.evidencias) == len(observada.evidencias) + 1


def test_actualizar_identidad_no_agrega_alias_equivalente_al_canonico(tmp_path):
    catalogo, cliente, destino = _entorno(tmp_path)
    observada = _observar(catalogo, cliente, destino).obra
    actualizada = catalogo.actualizar_identidad_obra(
        observada.obra_id,
        nombre_canonico="OBRA SINTETICA S.A.",
        aliases_documentales=("OBRA SINTETICA SA",),
        evidencia=_evidencia_externa(),
    )
    assert actualizada.aliases_documentales == ()


def test_normalizacion_distingue_sigla_puntuada_de_letras_independientes():
    assert normalizar_nombre_obra("EMPRESA S.A.") == "EMPRESA SA"
    assert normalizar_nombre_obra("SECTOR S A NORTE") == "SECTOR S A NORTE"


def test_actualizar_identidad_rechaza_confirmacion_humana_sin_escribir(tmp_path):
    catalogo, cliente, destino = _entorno(tmp_path)
    observada = _observar(catalogo, cliente, destino).obra
    antes = catalogo.ruta.read_bytes()
    evidencia = Evidencia(
        **{
            **_evidencia_externa().a_dict(),
            "tipo": TipoEvidencia.CONFIRMACION_HUMANA.value,
        }
    )
    with pytest.raises(ErrorCatalogoObrasDestinos, match="no decisional"):
        catalogo.actualizar_identidad_obra(
            observada.obra_id,
            nombre_canonico="OBRA CANONICA LIMITADA",
            evidencia=evidencia,
        )
    assert catalogo.ruta.read_bytes() == antes


def test_actualizar_identidad_preserva_aliases_y_deduplica_normalizados(tmp_path):
    catalogo, cliente, destino = _entorno(tmp_path)
    observada = _observar(catalogo, cliente, destino).obra
    primera = catalogo.actualizar_identidad_obra(
        observada.obra_id,
        nombre_canonico="OBRA CANONICA LIMITADA",
        aliases_documentales=("ALIAS UNO",),
        evidencia=_evidencia_externa(),
    )
    segunda = catalogo.actualizar_identidad_obra(
        primera.obra_id,
        nombre_canonico=primera.nombre_canonico,
        aliases_documentales=("ALIAS DOS", "alias dos"),
        evidencia=Evidencia(
            **{
                **_evidencia_externa().a_dict(),
                "identificador_fuente": "otra-fuente-oficial-sintetica",
            }
        ),
    )
    assert segunda.aliases_documentales == ("ALIAS UNO", "ALIAS DOS")


@pytest.mark.parametrize(
    ("nombre_canonico", "aliases_documentales", "patron"),
    [("", (), "nombre_canonico"), ("OBRA CANONICA", ("",), "alias_documental")],
)
def test_actualizar_identidad_rechaza_identidad_o_alias_vacio_sin_escribir(
    tmp_path, nombre_canonico, aliases_documentales, patron
):
    catalogo, cliente, destino = _entorno(tmp_path)
    observada = _observar(catalogo, cliente, destino).obra
    antes = catalogo.ruta.read_bytes()
    with pytest.raises(ErrorCatalogoObrasDestinos, match=patron):
        catalogo.actualizar_identidad_obra(
            observada.obra_id,
            nombre_canonico=nombre_canonico,
            aliases_documentales=aliases_documentales,
            evidencia=_evidencia_externa(),
        )
    assert catalogo.ruta.read_bytes() == antes


def test_actualizar_identidad_rechaza_colision_del_mismo_cliente(tmp_path):
    catalogo, cliente, destino = _entorno(tmp_path)
    primera = _observar(catalogo, cliente, destino).obra
    segunda = catalogo.registrar_observacion(
        cliente_id=cliente.cliente_id,
        nombre_obra="OTRA OBRA",
        evidencia=_evidencia("guia-sintetica-2"),
    ).obra
    antes = catalogo.ruta.read_bytes()
    with pytest.raises(ErrorCatalogoObrasDestinos, match="colisiona"):
        catalogo.actualizar_identidad_obra(
            primera.obra_id,
            nombre_canonico="OBRA CANONICA LIMITADA",
            aliases_documentales=(segunda.nombre_canonico,),
            evidencia=_evidencia_externa(),
        )
    assert catalogo.ruta.read_bytes() == antes


def test_segunda_observacion_deduplica_y_agrega_evidencia_sin_confirmar(tmp_path):
    catalogo, cliente, destino = _entorno(tmp_path)
    primero = _observar(catalogo, cliente, destino)
    segundo = _observar(catalogo, cliente, destino, _evidencia("guia-sintetica-2"))
    assert segundo.obra.obra_id == primero.obra.obra_id
    assert segundo.relacion.relacion_id == primero.relacion.relacion_id
    assert len(catalogo.listar_obras()) == len(catalogo.listar_relaciones()) == 1
    assert len(segundo.obra.evidencias) == len(segundo.relacion.evidencias) == 2
    assert segundo.obra.estado == EstadoObra.CANDIDATA.value
    assert segundo.relacion.estado == EstadoRelacion.PENDIENTE.value


def test_observacion_repetida_identica_no_duplica_evidencia(tmp_path):
    catalogo, cliente, destino = _entorno(tmp_path)
    _observar(catalogo, cliente, destino)
    resultado = _observar(catalogo, cliente, destino)
    assert len(resultado.obra.evidencias) == len(resultado.relacion.evidencias) == 1
    assert resultado.obra.estado == EstadoObra.OBSERVADA.value


def test_observacion_ocr_no_puede_disfrazarse_de_confirmacion_humana(tmp_path):
    catalogo, cliente, destino = _entorno(tmp_path)
    evidencia = Evidencia(
        **{**_evidencia().a_dict(), "tipo": TipoEvidencia.CONFIRMACION_HUMANA.value}
    )
    with pytest.raises(ErrorCatalogoObrasDestinos, match="confirmar_relacion"):
        _observar(catalogo, cliente, destino, evidencia)


def test_confirmacion_humana_registra_actor_fecha_y_evidencia_y_resuelve(tmp_path):
    catalogo, cliente, destino = _entorno(tmp_path)
    pendiente = _observar(catalogo, cliente, destino).relacion
    confirmada = catalogo.confirmar_relacion(
        pendiente.relacion_id,
        actor="operador-sintetico",
        identificador_fuente="decision-1",
        observaciones="Verificado en prueba",
    )
    assert confirmada.estado == EstadoRelacion.CONFIRMADA.value
    assert confirmada.confirmado_por == "operador-sintetico"
    assert confirmada.fecha_confirmacion.endswith("+00:00")
    assert confirmada.evidencias[-1].tipo == TipoEvidencia.CONFIRMACION_HUMANA.value
    assert confirmada.evidencias[-1].resultado == ResultadoEvidencia.SOPORTA.value
    obra = catalogo.listar_obras()[0]
    assert obra.estado == EstadoObra.CONFIRMADA.value
    assert obra.evidencias[-1].tipo == TipoEvidencia.CONFIRMACION_HUMANA.value
    assert obra.evidencias[-1].resultado == ResultadoEvidencia.SOPORTA.value
    assert obra.evidencias[-1].actor_proceso == "operador-sintetico"
    resolucion = catalogo.resolver_obra_destino_confirmada(
        cliente_id=cliente.cliente_id, nombre_obra="OBRA SINTETICA"
    )
    assert resolucion is not None
    assert resolucion.destino.destino_id == destino.destino_id


@pytest.mark.parametrize("decision", ["rechazar", "pendiente"])
def test_relacion_rechazada_o_pendiente_no_resuelve(tmp_path, decision):
    catalogo, cliente, destino = _entorno(tmp_path)
    relacion = _observar(catalogo, cliente, destino).relacion
    if decision == "rechazar":
        catalogo.rechazar_relacion(relacion.relacion_id, actor="humano")
    else:
        catalogo.mantener_pendiente(relacion.relacion_id, actor="humano")
    assert catalogo.resolver_obra_destino_confirmada(
        cliente_id=cliente.cliente_id, nombre_obra="OBRA SINTETICA"
    ) is None


def test_relacion_rechazada_no_puede_confirmarse_y_conserva_historia(tmp_path):
    catalogo, cliente, destino = _entorno(tmp_path)
    relacion = _observar(catalogo, cliente, destino).relacion
    catalogo.rechazar_relacion(relacion.relacion_id, actor="revisor")
    antes = catalogo.ruta.read_bytes()
    with pytest.raises(ErrorCatalogoObrasDestinos, match="PENDIENTE"):
        catalogo.confirmar_relacion(relacion.relacion_id, actor="otro-revisor")
    assert catalogo.ruta.read_bytes() == antes
    guardada = catalogo.listar_relaciones()[0]
    assert guardada.estado == EstadoRelacion.RECHAZADA.value
    assert guardada.evidencias[-1].resultado == ResultadoEvidencia.CONTRADICE.value


def test_relacion_inactiva_no_puede_confirmarse(tmp_path):
    catalogo, cliente, destino = _entorno(tmp_path)
    relacion = _observar(catalogo, cliente, destino).relacion
    contenido = json.loads(catalogo.ruta.read_text(encoding="utf-8"))
    contenido["relaciones"][0]["estado"] = EstadoRelacion.INACTIVA.value
    catalogo.ruta.write_text(json.dumps(contenido), encoding="utf-8")
    antes = catalogo.ruta.read_bytes()
    with pytest.raises(ErrorCatalogoObrasDestinos, match="PENDIENTE"):
        catalogo.confirmar_relacion(relacion.relacion_id, actor="revisor")
    assert catalogo.ruta.read_bytes() == antes


def test_relacion_confirmada_no_se_reconfirma_silenciosamente(tmp_path):
    catalogo, cliente, destino = _entorno(tmp_path)
    relacion = _observar(catalogo, cliente, destino).relacion
    catalogo.confirmar_relacion(relacion.relacion_id, actor="revisor")
    antes = catalogo.ruta.read_bytes()
    with pytest.raises(ErrorCatalogoObrasDestinos, match="PENDIENTE"):
        catalogo.confirmar_relacion(relacion.relacion_id, actor="revisor")
    assert catalogo.ruta.read_bytes() == antes


@pytest.mark.parametrize(
    ("estado", "vigencia"),
    [(EstadoObra.RECHAZADA.value, "ACTIVO"), (EstadoObra.INACTIVA.value, "INACTIVO")],
)
def test_obra_rechazada_o_inactiva_no_se_confirma_desde_relacion_pendiente(
    tmp_path, estado, vigencia
):
    catalogo, cliente, destino = _entorno(tmp_path)
    relacion = _observar(catalogo, cliente, destino).relacion
    contenido = json.loads(catalogo.ruta.read_text(encoding="utf-8"))
    contenido["obras"][0]["estado"] = estado
    contenido["obras"][0]["estado_vigencia"] = vigencia
    catalogo.ruta.write_text(json.dumps(contenido), encoding="utf-8")
    antes = catalogo.ruta.read_bytes()
    with pytest.raises(ErrorCatalogoObrasDestinos, match="rechazada o inactiva"):
        catalogo.confirmar_relacion(relacion.relacion_id, actor="revisor")
    assert catalogo.ruta.read_bytes() == antes


def test_obra_confirmada_sin_evidencia_humana_es_catalogo_corrupto(tmp_path):
    catalogo, cliente, destino = _entorno(tmp_path)
    relacion = _observar(catalogo, cliente, destino).relacion
    catalogo.confirmar_relacion(relacion.relacion_id, actor="revisor")
    contenido = json.loads(catalogo.ruta.read_text(encoding="utf-8"))
    contenido["obras"][0]["evidencias"] = [
        evidencia
        for evidencia in contenido["obras"][0]["evidencias"]
        if evidencia["tipo"] != TipoEvidencia.CONFIRMACION_HUMANA.value
    ]
    catalogo.ruta.write_text(json.dumps(contenido), encoding="utf-8")
    with pytest.raises(CatalogoObrasDestinosCorruptoError, match="evidencia humana"):
        catalogo.listar_obras()


def test_contradiccion_en_obra_confirmada_obliga_abstencion(tmp_path):
    catalogo, cliente, destino = _entorno(tmp_path)
    relacion = _observar(catalogo, cliente, destino).relacion
    catalogo.confirmar_relacion(relacion.relacion_id, actor="revisor")
    contenido = json.loads(catalogo.ruta.read_text(encoding="utf-8"))
    contradiccion = _evidencia(
        "fuente-contradictoria", resultado=ResultadoEvidencia.CONTRADICE.value
    ).a_dict()
    contenido["obras"][0]["evidencias"].append(contradiccion)
    catalogo.ruta.write_text(json.dumps(contenido), encoding="utf-8")
    assert catalogo.resolver_obra_destino_confirmada(
        cliente_id=cliente.cliente_id, nombre_obra="OBRA SINTETICA"
    ) is None


def test_reobservacion_tras_rechazo_conserva_estado_y_agrega_evidencia(tmp_path):
    catalogo, cliente, destino = _entorno(tmp_path)
    relacion = _observar(catalogo, cliente, destino).relacion
    rechazada = catalogo.rechazar_relacion(relacion.relacion_id, actor="revisor")
    resultado = _observar(
        catalogo, cliente, destino, _evidencia("guia-sintetica-posterior")
    )
    assert resultado.relacion.relacion_id == rechazada.relacion_id
    assert resultado.relacion.estado == EstadoRelacion.RECHAZADA.value
    assert len(catalogo.listar_relaciones()) == 1
    assert resultado.relacion.evidencias[-1].identificador_fuente == "guia-sintetica-posterior"


def test_relacion_inactiva_no_resuelve(tmp_path):
    catalogo, cliente, destino = _entorno(tmp_path)
    relacion = _observar(catalogo, cliente, destino).relacion
    catalogo.confirmar_relacion(relacion.relacion_id, actor="humano")
    contenido = json.loads(catalogo.ruta.read_text(encoding="utf-8"))
    guardada = contenido["relaciones"][0]
    guardada["estado"] = EstadoRelacion.INACTIVA.value
    guardada["fuente_confirmacion"] = ""
    guardada["confirmado_por"] = ""
    guardada["fecha_confirmacion"] = ""
    catalogo.ruta.write_text(json.dumps(contenido), encoding="utf-8")
    assert catalogo.resolver_obra_destino_confirmada(
        cliente_id=cliente.cliente_id, nombre_obra="OBRA SINTETICA"
    ) is None


def test_evidencia_contraria_impide_resolver_relacion_confirmada(tmp_path):
    catalogo, cliente, destino = _entorno(tmp_path)
    relacion = _observar(
        catalogo,
        cliente,
        destino,
        _evidencia(resultado=ResultadoEvidencia.CONTRADICE.value),
    ).relacion
    catalogo.confirmar_relacion(relacion.relacion_id, actor="humano")
    assert catalogo.resolver_obra_destino_confirmada(
        cliente_id=cliente.cliente_id, nombre_obra="OBRA SINTETICA"
    ) is None


def test_ruta_predeterminada_deriva_de_atlas_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path / "raiz-portable"))
    catalogo = CatalogoObrasDestinos()
    assert catalogo.ruta == tmp_path / "raiz-portable/catalogos_privados/obras_destinos.json"
    assert catalogo.ruta_clientes.parent == catalogo.ruta_destinos.parent == catalogo.ruta.parent


def test_fallo_atomico_no_deja_catalogo_parcial(tmp_path, monkeypatch):
    catalogo, cliente, destino = _entorno(tmp_path)

    def fallar(*_args):
        raise OSError("fallo sintético")

    monkeypatch.setattr(almacenamiento_portable.os, "replace", fallar)
    with pytest.raises(OSError, match="fallo sintético"):
        _observar(catalogo, cliente, destino)
    assert not catalogo.ruta.exists()
    assert list(catalogo.ruta.parent.glob(".obras_destinos.json.*.tmp")) == []
