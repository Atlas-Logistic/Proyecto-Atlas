import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

import atlas_core.catalogo_destinos as modulo
from atlas_core.catalogo_clientes import CatalogoClientes
from atlas_core.catalogo_destinos import (
    AliasDestinoDuplicadoError,
    CatalogoDestinos,
    CatalogoDestinosCorruptoError,
    ClienteDestinoInvalidoError,
    DestinoDuplicadoError,
    ErrorCatalogoDestinos,
    EstadoBusquedaDestino,
    EstadoCalidadDestino,
    ModificacionDestinoProtegidaError,
    normalizar_nombre_destino,
)
from atlas_core.catalogo_plantas import CatalogoPlantas
from gestionar_catalogos import crear_parser_destinos, ejecutar_destinos, main


class RelojSecuencial:
    def __init__(self):
        self.actual = datetime(2026, 3, 1, tzinfo=timezone.utc)

    def __call__(self):
        valor = self.actual
        self.actual += timedelta(seconds=1)
        return valor


@pytest.fixture
def entorno(tmp_path):
    ruta_clientes = tmp_path / "clientes.json"
    clientes = CatalogoClientes(ruta_clientes, reloj=RelojSecuencial())
    cliente_uno = clientes.crear(
        razon_social="CLIENTE DEMO UNO S.A.", fuente="PRUEBA_SINTETICA"
    )
    cliente_dos = clientes.crear(
        razon_social="CLIENTE DEMO DOS S.A.", fuente="PRUEBA_SINTETICA"
    )
    destinos = CatalogoDestinos(
        tmp_path / "destinos.json",
        ruta_clientes=ruta_clientes,
        reloj=RelojSecuencial(),
    )
    return destinos, clientes, cliente_uno, cliente_dos


def crear_demo(servicio, cliente_id, **cambios):
    datos = {
        "cliente_id": cliente_id,
        "nombre_destino": "CENTRO DEMO ÁGUILA",
        "direccion": "AVENIDA FICTICIA 200",
        "comuna": "COMUNA DEMO",
        "region": "REGIÓN DEMO",
        "pais": "PAÍS DEMO",
        "fuente": "PRUEBA_SINTETICA",
    }
    datos.update(cambios)
    return servicio.crear(**datos)


def test_creacion_y_asociacion_con_cliente_existente(entorno):
    destinos, _, cliente, _ = entorno
    destino = crear_demo(destinos, cliente.cliente_id)

    assert UUID(destino.destino_id)
    assert destino.cliente_id == cliente.cliente_id
    assert destino.estado_calidad == "PENDIENTE"
    assert destino.estado_vigencia == "ACTIVO"
    assert destinos.obtener(destino.destino_id) == destino


def test_uuid_estable_al_cambiar_nombre(entorno):
    destinos, _, cliente, _ = entorno
    original = crear_demo(destinos, cliente.cliente_id)

    editado = destinos.editar(original.destino_id, nombre_destino="BODEGA DEMO NUEVA")

    assert editado.destino_id == original.destino_id


def test_rechaza_cliente_inexistente(entorno):
    destinos, _, _, _ = entorno
    with pytest.raises(ClienteDestinoInvalidoError, match="no existe"):
        crear_demo(destinos, "00000000-0000-4000-8000-999999999999")


def test_rechaza_cliente_inactivo(entorno):
    destinos, clientes, cliente, _ = entorno
    clientes.desactivar(cliente.cliente_id)

    with pytest.raises(ClienteDestinoInvalidoError, match="inactivo"):
        crear_demo(destinos, cliente.cliente_id)


def test_normalizacion_conserva_original(entorno):
    destinos, _, cliente, _ = entorno
    destino = crear_demo(
        destinos, cliente.cliente_id, nombre_destino=" Centro   Demo Ñandú "
    )

    assert destino.nombre_destino == "Centro   Demo Ñandú"
    assert destino.nombre_normalizado == "CENTRO DEMO NANDU"
    assert normalizar_nombre_destino("centro demo ñandú") == destino.nombre_normalizado


def test_previene_nombre_duplicado_dentro_del_cliente(entorno):
    destinos, _, cliente, _ = entorno
    crear_demo(destinos, cliente.cliente_id, nombre_destino="BODEGA DEMO CENTRAL")

    with pytest.raises(DestinoDuplicadoError):
        crear_demo(
            destinos,
            cliente.cliente_id,
            nombre_destino="Bodega Demo Central",
            direccion="OTRA DIRECCIÓN FICTICIA",
        )


def test_mismo_nombre_es_permitido_en_clientes_distintos(entorno):
    destinos, _, cliente_uno, cliente_dos = entorno
    primero = crear_demo(destinos, cliente_uno.cliente_id)
    segundo = crear_demo(destinos, cliente_dos.cliente_id)

    assert primero.nombre_normalizado == segundo.nombre_normalizado


def test_direccion_duplicada_dentro_del_cliente_se_rechaza(entorno):
    destinos, _, cliente, _ = entorno
    crear_demo(destinos, cliente.cliente_id, nombre_destino="DESTINO DEMO UNO")

    with pytest.raises(DestinoDuplicadoError, match="dirección"):
        crear_demo(destinos, cliente.cliente_id, nombre_destino="DESTINO DEMO DOS")


def test_alias_y_busqueda_por_alias(entorno):
    destinos, _, cliente, _ = entorno
    destino = crear_demo(destinos, cliente.cliente_id)
    editado = destinos.agregar_alias(destino.destino_id, "BODEGA ALTERNATIVA DEMO")

    resultado = destinos.buscar("bodega alternativa demo")
    assert editado.aliases == ("BODEGA ALTERNATIVA DEMO",)
    assert resultado.estado == EstadoBusquedaDestino.COINCIDENCIA
    assert resultado.destino == editado


def test_alias_duplicado_dentro_del_cliente_se_rechaza(entorno):
    destinos, _, cliente, _ = entorno
    primero = crear_demo(destinos, cliente.cliente_id, nombre_destino="DESTINO DEMO UNO")
    segundo = crear_demo(
        destinos,
        cliente.cliente_id,
        nombre_destino="DESTINO DEMO DOS",
        direccion="CALLE FICTICIA 300",
    )
    destinos.agregar_alias(primero.destino_id, "ALIAS DESTINO DEMO")

    with pytest.raises(AliasDestinoDuplicadoError):
        destinos.agregar_alias(segundo.destino_id, "Alias Destino Demo")


def test_busqueda_ambigua_global_se_abstiene(entorno):
    destinos, _, cliente_uno, cliente_dos = entorno
    crear_demo(destinos, cliente_uno.cliente_id, nombre_destino="DESTINO DEMO COMÚN")
    crear_demo(destinos, cliente_dos.cliente_id, nombre_destino="DESTINO DEMO COMÚN")

    resultado = destinos.buscar("DESTINO DEMO COMUN")
    assert resultado.estado == EstadoBusquedaDestino.AMBIGUA
    assert resultado.destino is None
    assert resultado.cantidad_coincidencias == 2


def test_busqueda_filtrada_resuelve_nombre_compartido(entorno):
    destinos, _, cliente_uno, cliente_dos = entorno
    primero = crear_demo(destinos, cliente_uno.cliente_id, nombre_destino="DESTINO DEMO COMÚN")
    crear_demo(destinos, cliente_dos.cliente_id, nombre_destino="DESTINO DEMO COMÚN")

    resultado = destinos.buscar("DESTINO DEMO COMUN", cliente_id=cliente_uno.cliente_id)
    assert resultado.estado == EstadoBusquedaDestino.COINCIDENCIA
    assert resultado.destino == primero


def test_edicion_explicita_y_fechas(entorno):
    destinos, _, cliente, _ = entorno
    original = crear_demo(destinos, cliente.cliente_id)
    editado = destinos.editar(
        original.destino_id,
        comuna="OTRA COMUNA DEMO",
        observacion="Corrección sintética",
    )

    assert editado.comuna == "OTRA COMUNA DEMO"
    assert editado.fecha_creacion == original.fecha_creacion
    assert editado.fecha_modificacion > original.fecha_modificacion


def test_confirmado_requiere_operacion_manual_explicita(entorno):
    destinos, _, cliente, _ = entorno
    destino = crear_demo(
        destinos, cliente.cliente_id, estado_calidad=EstadoCalidadDestino.CONFIRMADO
    )

    with pytest.raises(ModificacionDestinoProtegidaError):
        destinos.editar(destino.destino_id, observacion="Intento automático")
    with pytest.raises(ModificacionDestinoProtegidaError):
        destinos.agregar_alias(destino.destino_id, "ALIAS DEMO")

    editado = destinos.editar(
        destino.destino_id,
        modificacion_manual=True,
        observacion="Cambio manual sintético",
    )
    assert editado.observacion == "Cambio manual sintético"


def test_desactivacion_no_elimina(entorno):
    destinos, _, cliente, _ = entorno
    destino = crear_demo(destinos, cliente.cliente_id)

    inactivo = destinos.desactivar(destino.destino_id)

    assert inactivo.estado_vigencia == "INACTIVO"
    assert destinos.obtener(destino.destino_id) == inactivo
    assert len(destinos.listar()) == 1


@pytest.mark.parametrize(("latitud", "longitud"), [(None, -70.0), (-33.0, None)])
def test_coordenadas_incompletas_rechazadas(entorno, latitud, longitud):
    destinos, _, cliente, _ = entorno
    with pytest.raises(ErrorCatalogoDestinos, match="informarse juntas"):
        crear_demo(
            destinos, cliente.cliente_id, latitud=latitud, longitud=longitud
        )


def test_persistencia_json(entorno):
    destinos, _, cliente, _ = entorno
    destino = crear_demo(destinos, cliente.cliente_id, aliases=["ALIAS DEMO"])
    contenido = json.loads(destinos.ruta.read_text(encoding="utf-8"))

    assert contenido["version_formato"] == 1
    assert contenido["destinos"][0]["aliases"] == ["ALIAS DEMO"]
    assert CatalogoDestinos(
        destinos.ruta, ruta_clientes=destinos.ruta_clientes
    ).listar() == [destino]


def test_escritura_atomica_usa_reemplazo(entorno, monkeypatch):
    destinos, _, cliente, _ = entorno
    reemplazos = []
    reemplazo_real = modulo.os.replace

    def registrar(origen, destino):
        reemplazos.append((origen, destino))
        reemplazo_real(origen, destino)

    monkeypatch.setattr(modulo.os, "replace", registrar)
    crear_demo(destinos, cliente.cliente_id)

    assert len(reemplazos) == 1
    assert reemplazos[0][0] != reemplazos[0][1]
    assert reemplazos[0][1] == destinos.ruta


def test_fallo_reemplazo_conserva_archivo(entorno, monkeypatch):
    destinos, _, cliente, _ = entorno
    destino = crear_demo(destinos, cliente.cliente_id)
    original = destinos.ruta.read_bytes()

    def fallar(_origen, _destino):
        raise OSError("fallo sintético")

    monkeypatch.setattr(modulo.os, "replace", fallar)
    with pytest.raises(OSError, match="fallo sintético"):
        destinos.editar(destino.destino_id, observacion="no persistir")

    assert destinos.ruta.read_bytes() == original
    assert list(destinos.ruta.parent.glob("*.tmp")) == []


def test_archivo_inexistente_es_catalogo_vacio(tmp_path):
    ruta = tmp_path / "inexistente" / "destinos.json"
    assert CatalogoDestinos(ruta, ruta_clientes=tmp_path / "clientes.json").listar() == []
    assert not ruta.exists()


@pytest.mark.parametrize("contenido", ["{", "[]", '{"version_formato": 2, "destinos": []}'])
def test_archivo_corrupto_genera_error(tmp_path, contenido):
    ruta = tmp_path / "destinos.json"
    ruta.write_text(contenido, encoding="utf-8")

    with pytest.raises(CatalogoDestinosCorruptoError):
        CatalogoDestinos(ruta, ruta_clientes=tmp_path / "clientes.json").listar()


def test_filtro_por_cliente(entorno):
    destinos, _, cliente_uno, cliente_dos = entorno
    primero = crear_demo(destinos, cliente_uno.cliente_id)
    crear_demo(destinos, cliente_dos.cliente_id)

    assert destinos.listar(cliente_id=cliente_uno.cliente_id) == [primero]


def test_cli_destinos_completa(entorno, capsys):
    destinos, _, cliente, _ = entorno
    parser = crear_parser_destinos()
    base = [
        "--archivo", str(destinos.ruta),
        "--archivo-clientes", str(destinos.ruta_clientes),
    ]
    assert ejecutar_destinos(parser.parse_args(base + [
        "agregar", "--cliente-id", cliente.cliente_id, "--nombre", "DESTINO DEMO CLI",
        "--pais", "PAÍS DEMO", "--fuente", "PRUEBA_SINTETICA",
    ])) == 0
    destino_id = destinos.listar()[0].destino_id
    assert ejecutar_destinos(parser.parse_args(base + ["mostrar", destino_id])) == 0
    assert ejecutar_destinos(parser.parse_args(base + [
        "agregar-alias", destino_id, "--alias", "ALIAS DEMO CLI",
    ])) == 0
    assert ejecutar_destinos(parser.parse_args(base + [
        "buscar", "--texto", "ALIAS DEMO CLI",
    ])) == 0
    assert ejecutar_destinos(parser.parse_args(base + [
        "listar", "--cliente-id", cliente.cliente_id,
    ])) == 0
    assert "Coincidencia única encontrada" in capsys.readouterr().out


def test_compatibilidad_cli_plantas_y_clientes(tmp_path):
    plantas = tmp_path / "plantas.json"
    clientes = tmp_path / "clientes.json"
    assert main([
        "--archivo", str(plantas), "agregar", "--nombre", "PLANTA DEMO",
        "--pais", "PAÍS DEMO", "--fuente", "PRUEBA_SINTETICA",
    ]) == 0
    assert main(["plantas", "--archivo", str(plantas), "listar"]) == 0
    assert main([
        "clientes", "--archivo", str(clientes), "agregar", "--razon-social",
        "CLIENTE DEMO CLI", "--fuente", "PRUEBA_SINTETICA",
    ]) == 0
    assert main(["clientes", "--archivo", str(clientes), "listar"]) == 0
    assert len(CatalogoPlantas(plantas).listar()) == 1
    assert len(CatalogoClientes(clientes).listar()) == 1


def test_main_destinos(tmp_path):
    clientes_ruta = tmp_path / "clientes.json"
    cliente = CatalogoClientes(clientes_ruta).crear(
        razon_social="CLIENTE DEMO MAIN", fuente="PRUEBA_SINTETICA"
    )
    destinos_ruta = tmp_path / "destinos.json"
    base = [
        "destinos", "--archivo", str(destinos_ruta),
        "--archivo-clientes", str(clientes_ruta),
    ]
    assert main(base + [
        "agregar", "--cliente-id", cliente.cliente_id, "--nombre", "DESTINO DEMO MAIN",
        "--pais", "PAÍS DEMO", "--fuente", "PRUEBA_SINTETICA",
    ]) == 0
    assert main(base + ["listar"]) == 0


def test_plantilla_y_pruebas_son_sinteticas(entorno):
    ruta = modulo.Path("catalogos/templates/destinos_ejemplo.json")
    contenido = json.loads(ruta.read_text(encoding="utf-8"))
    destinos, _, cliente, _ = entorno
    prueba = crear_demo(destinos, cliente.cliente_id)
    texto = json.dumps(contenido, ensure_ascii=False) + json.dumps(
        prueba.a_dict(), ensure_ascii=False
    )

    assert contenido["version_formato"] == 1
    assert len(contenido["destinos"]) == 1
    assert "DEMO" in texto or "DEMOSTRACIÓN" in texto
    assert "INGRESO_MANUAL" not in texto
