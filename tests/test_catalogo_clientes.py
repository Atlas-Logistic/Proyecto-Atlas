import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

import atlas_core.catalogo_clientes as modulo
from atlas_core.catalogo_clientes import (
    AliasDuplicadoError,
    CatalogoClientes,
    CatalogoClientesCorruptoError,
    ClienteDuplicadoError,
    ErrorCatalogoClientes,
    EstadoBusquedaCliente,
    EstadoCalidadCliente,
    ModificacionClienteProtegidaError,
    normalizar_nombre_cliente,
    normalizar_rut_cliente,
)
from atlas_core.catalogo_plantas import CatalogoPlantas
from gestionar_catalogos import crear_parser_clientes, ejecutar_clientes, main


class RelojSecuencial:
    def __init__(self):
        self.actual = datetime(2026, 2, 1, tzinfo=timezone.utc)

    def __call__(self):
        valor = self.actual
        self.actual += timedelta(seconds=1)
        return valor


def catalogo(tmp_path):
    return CatalogoClientes(tmp_path / "clientes.json", reloj=RelojSecuencial())


def crear_demo(servicio, **cambios):
    datos = {
        "razon_social": "EMPRESA DEMO ÁGUILA S.A.",
        "fuente": "PRUEBA_SINTETICA",
    }
    datos.update(cambios)
    return servicio.crear(**datos)


def rut_sintetico_valido():
    """Construye un identificador efímero para probar el algoritmo sin fixture real."""
    cuerpo = "".join(str(digito) for digito in (2, 4, 6, 8, 1, 3, 5, 7))
    suma = sum(
        int(digito) * factor
        for digito, factor in zip(reversed(cuerpo), (2, 3, 4, 5, 6, 7) * 2)
    )
    resultado = 11 - suma % 11
    verificador = "0" if resultado == 11 else "K" if resultado == 10 else str(resultado)
    return cuerpo, verificador


def test_creacion_y_consulta(tmp_path):
    servicio = catalogo(tmp_path)
    cliente = crear_demo(servicio)

    assert UUID(cliente.cliente_id)
    assert cliente.estado_calidad == "PENDIENTE"
    assert cliente.estado_vigencia == "ACTIVO"
    assert servicio.obtener(cliente.cliente_id) == cliente
    assert servicio.listar() == [cliente]


def test_uuid_permanece_estable_al_cambiar_razon_social(tmp_path):
    servicio = catalogo(tmp_path)
    original = crear_demo(servicio)

    editado = servicio.editar(original.cliente_id, razon_social="EMPRESA DEMO NUEVA S.A.")

    assert editado.cliente_id == original.cliente_id


@pytest.mark.parametrize(
    "valor", ["EMPRESA EJEMPLO", "EMPRESA EJEMPLO SA", "Empresa Ejemplo S.A."]
)
def test_normalizacion_unifica_variantes_societarias(valor):
    assert normalizar_nombre_cliente(valor) == "EMPRESA EJEMPLO"


def test_conserva_razon_social_original(tmp_path):
    cliente = crear_demo(catalogo(tmp_path), razon_social=" Empresa   Demo Ñandú S.A. ")

    assert cliente.razon_social == "Empresa   Demo Ñandú S.A."
    assert cliente.nombre_normalizado == "EMPRESA DEMO NANDU"


def test_previene_duplicado_por_razon_social_normalizada(tmp_path):
    servicio = catalogo(tmp_path)
    crear_demo(servicio, razon_social="EMPRESA DEMO CENTRAL")

    with pytest.raises(ClienteDuplicadoError):
        crear_demo(servicio, razon_social="Empresa Demo Central S.A.")


def test_alias_manual_y_busqueda_por_alias(tmp_path):
    servicio = catalogo(tmp_path)
    cliente = crear_demo(servicio)
    editado = servicio.agregar_alias(cliente.cliente_id, "MARCA ALTERNATIVA DEMO")

    resultado = servicio.buscar("marca alternativa demo")
    assert editado.aliases == ("MARCA ALTERNATIVA DEMO",)
    assert resultado.estado == EstadoBusquedaCliente.COINCIDENCIA
    assert resultado.cliente == editado


def test_alias_duplicado_en_otro_cliente_se_rechaza(tmp_path):
    servicio = catalogo(tmp_path)
    primero = crear_demo(servicio, razon_social="CLIENTE DEMO UNO")
    segundo = crear_demo(servicio, razon_social="CLIENTE DEMO DOS")
    servicio.agregar_alias(primero.cliente_id, "ALIAS DEMO COMPARTIDO")

    with pytest.raises(AliasDuplicadoError):
        servicio.agregar_alias(segundo.cliente_id, "Alias Demo Compartido S.A.")


def test_busqueda_ambigua_se_abstiene(tmp_path):
    servicio = catalogo(tmp_path)
    crear_demo(
        servicio,
        razon_social="CLIENTE DEMO ORIENTE",
        nombre_comercial="MARCA DEMO COMPARTIDA",
    )
    crear_demo(
        servicio,
        razon_social="CLIENTE DEMO PONIENTE",
        nombre_comercial="MARCA DEMO COMPARTIDA",
    )

    resultado = servicio.buscar("MARCA DEMO COMPARTIDA")
    assert resultado.estado == EstadoBusquedaCliente.AMBIGUA
    assert resultado.cliente is None
    assert resultado.cantidad_coincidencias == 2


def test_busqueda_no_usa_similitud_parcial(tmp_path):
    servicio = catalogo(tmp_path)
    crear_demo(servicio, razon_social="CLIENTE DEMO COMPLETO")

    assert servicio.buscar("CLIENTE DEMO").estado == EstadoBusquedaCliente.SIN_COINCIDENCIA


def test_rut_valido_se_canoniza(tmp_path):
    cuerpo, verificador = rut_sintetico_valido()
    rut_con_puntos = f"{cuerpo[:2]}.{cuerpo[2:5]}.{cuerpo[5:]}-{verificador}"
    rut_con_espacios = f"{' '.join(cuerpo)} {verificador}"
    rut_canonico = f"{cuerpo}-{verificador}"
    cliente = crear_demo(catalogo(tmp_path), rut=rut_con_puntos)

    assert cliente.rut == rut_canonico
    assert normalizar_rut_cliente(rut_con_espacios) == rut_canonico


@pytest.mark.parametrize("rut", ["ABC", "123-4"])
def test_rut_estructuralmente_invalido_se_rechaza(tmp_path, rut):
    with pytest.raises(ErrorCatalogoClientes, match="RUT inválido"):
        crear_demo(catalogo(tmp_path), rut=rut)


def test_rut_con_digito_verificador_invalido_se_rechaza(tmp_path):
    cuerpo, verificador = rut_sintetico_valido()
    verificador_incorrecto = "0" if verificador != "0" else "1"

    with pytest.raises(ErrorCatalogoClientes, match="RUT inválido"):
        crear_demo(catalogo(tmp_path), rut=f"{cuerpo}-{verificador_incorrecto}")


def test_rut_duplicado_se_rechaza(tmp_path):
    servicio = catalogo(tmp_path)
    cuerpo, verificador = rut_sintetico_valido()
    rut_canonico = f"{cuerpo}-{verificador}"
    rut_con_puntos = f"{cuerpo[:2]}.{cuerpo[2:5]}.{cuerpo[5:]}-{verificador}"
    crear_demo(servicio, razon_social="CLIENTE DEMO UNO", rut=rut_con_puntos)

    with pytest.raises(ClienteDuplicadoError):
        crear_demo(servicio, razon_social="CLIENTE DEMO DOS", rut=rut_canonico)


def test_edicion_explicita_actualiza_campos_y_fecha(tmp_path):
    servicio = catalogo(tmp_path)
    original = crear_demo(servicio)
    editado = servicio.editar(
        original.cliente_id,
        nombre_comercial="MARCA DEMO EDITADA",
        observacion="Corrección sintética",
    )

    assert editado.nombre_comercial == "MARCA DEMO EDITADA"
    assert editado.fecha_creacion == original.fecha_creacion
    assert editado.fecha_modificacion > original.fecha_modificacion


def test_confirmado_requiere_operacion_manual_explicita(tmp_path):
    servicio = catalogo(tmp_path)
    cliente = crear_demo(servicio, estado_calidad=EstadoCalidadCliente.CONFIRMADO)

    with pytest.raises(ModificacionClienteProtegidaError):
        servicio.editar(cliente.cliente_id, observacion="Intento automático")
    with pytest.raises(ModificacionClienteProtegidaError):
        servicio.agregar_alias(cliente.cliente_id, "ALIAS DEMO")

    editado = servicio.agregar_alias(
        cliente.cliente_id, "ALIAS DEMO", modificacion_manual=True
    )
    assert editado.aliases == ("ALIAS DEMO",)


def test_desactivacion_conserva_cliente(tmp_path):
    servicio = catalogo(tmp_path)
    cliente = crear_demo(servicio)

    inactivo = servicio.desactivar(cliente.cliente_id)

    assert inactivo.estado_vigencia == "INACTIVO"
    assert len(servicio.listar()) == 1
    assert servicio.obtener(cliente.cliente_id) == inactivo


def test_persistencia_json_validada(tmp_path):
    ruta = tmp_path / "privado" / "clientes.json"
    servicio = CatalogoClientes(ruta, reloj=RelojSecuencial())
    cliente = crear_demo(servicio, aliases=["ALIAS DEMO"])

    contenido = json.loads(ruta.read_text(encoding="utf-8"))
    assert contenido["version_formato"] == 1
    assert contenido["clientes"][0]["aliases"] == ["ALIAS DEMO"]
    assert CatalogoClientes(ruta).listar() == [cliente]


def test_escritura_atomica_usa_reemplazo(tmp_path, monkeypatch):
    servicio = catalogo(tmp_path)
    reemplazos = []
    reemplazo_real = modulo.os.replace

    def registrar(origen, destino):
        reemplazos.append((origen, destino))
        reemplazo_real(origen, destino)

    monkeypatch.setattr(modulo.os, "replace", registrar)
    crear_demo(servicio)

    assert len(reemplazos) == 1
    assert reemplazos[0][0] != reemplazos[0][1]
    assert reemplazos[0][1] == servicio.ruta


def test_fallo_de_reemplazo_conserva_archivo_anterior(tmp_path, monkeypatch):
    servicio = catalogo(tmp_path)
    cliente = crear_demo(servicio)
    original = servicio.ruta.read_bytes()

    def fallar(_origen, _destino):
        raise OSError("fallo sintético")

    monkeypatch.setattr(modulo.os, "replace", fallar)
    with pytest.raises(OSError, match="fallo sintético"):
        servicio.editar(cliente.cliente_id, observacion="no persistir")

    assert servicio.ruta.read_bytes() == original
    assert list(tmp_path.glob("*.tmp")) == []


def test_archivo_inexistente_es_catalogo_vacio(tmp_path):
    ruta = tmp_path / "inexistente" / "clientes.json"
    assert CatalogoClientes(ruta).listar() == []
    assert not ruta.exists()


@pytest.mark.parametrize("contenido", ["{", "[]", '{"version_formato": 2, "clientes": []}'])
def test_archivo_corrupto_genera_error_visible(tmp_path, contenido):
    ruta = tmp_path / "clientes.json"
    ruta.write_text(contenido, encoding="utf-8")

    with pytest.raises(CatalogoClientesCorruptoError):
        CatalogoClientes(ruta).listar()


def test_fechas_de_auditoria(tmp_path):
    servicio = catalogo(tmp_path)
    creado = crear_demo(servicio)
    editado = servicio.agregar_alias(creado.cliente_id, "ALIAS DEMO AUDITORIA")
    inactivo = servicio.desactivar(creado.cliente_id)

    assert creado.fecha_creacion == creado.fecha_modificacion
    assert editado.fecha_modificacion > creado.fecha_modificacion
    assert inactivo.fecha_modificacion > editado.fecha_modificacion


def test_cli_clientes_y_rut_protegido(tmp_path, capsys):
    ruta = tmp_path / "clientes.json"
    parser = crear_parser_clientes()
    base = ["--archivo", str(ruta)]
    cuerpo, verificador = rut_sintetico_valido()
    rut_canonico = f"{cuerpo}-{verificador}"
    rut_con_puntos = f"{cuerpo[:2]}.{cuerpo[2:5]}.{cuerpo[5:]}-{verificador}"
    assert ejecutar_clientes(parser.parse_args(base + [
        "agregar", "--razon-social", "CLIENTE DEMO CLI", "--rut", rut_con_puntos,
        "--fuente", "PRUEBA_SINTETICA",
    ])) == 0
    cliente_id = CatalogoClientes(ruta).listar()[0].cliente_id
    assert ejecutar_clientes(parser.parse_args(base + ["listar"])) == 0
    assert ejecutar_clientes(parser.parse_args(base + ["mostrar", cliente_id])) == 0
    assert ejecutar_clientes(parser.parse_args(base + [
        "agregar-alias", cliente_id, "--alias", "ALIAS DEMO CLI",
    ])) == 0
    assert ejecutar_clientes(parser.parse_args(base + [
        "buscar", "--texto", "ALIAS DEMO CLI",
    ])) == 0
    salida = capsys.readouterr().out
    assert "PROTEGIDO" in salida
    assert rut_canonico not in salida


def test_compatibilidad_cli_plantas_legacy_y_nueva(tmp_path):
    ruta_legacy = tmp_path / "plantas_legacy.json"
    ruta_nueva = tmp_path / "plantas_nueva.json"

    assert main([
        "--archivo", str(ruta_legacy), "agregar", "--nombre", "PLANTA DEMO LEGACY",
        "--pais", "PAÍS DEMO", "--fuente", "PRUEBA_SINTETICA",
    ]) == 0
    assert main([
        "plantas", "--archivo", str(ruta_nueva), "agregar", "--nombre",
        "PLANTA DEMO NUEVA", "--pais", "PAÍS DEMO", "--fuente", "PRUEBA_SINTETICA",
    ]) == 0
    assert len(CatalogoPlantas(ruta_legacy).listar()) == 1
    assert len(CatalogoPlantas(ruta_nueva).listar()) == 1


def test_cli_main_clientes(tmp_path):
    ruta = tmp_path / "clientes.json"
    assert main([
        "clientes", "--archivo", str(ruta), "agregar", "--razon-social",
        "CLIENTE DEMO MAIN", "--fuente", "PRUEBA_SINTETICA",
    ]) == 0
    assert main(["clientes", "--archivo", str(ruta), "listar"]) == 0


def test_plantilla_y_pruebas_no_contienen_datos_reales(tmp_path):
    ruta = modulo.Path("catalogos/templates/clientes_ejemplo.json")
    texto = ruta.read_text(encoding="utf-8")
    clientes = CatalogoClientes(ruta).listar()
    prueba = crear_demo(catalogo(tmp_path))
    todo = texto + json.dumps(prueba.a_dict(), ensure_ascii=False)

    assert len(clientes) == 1
    assert "DEMO" in todo or "DEMOSTRACIÓN" in todo
    assert "AZA" not in todo
    assert "COLINA" not in todo
    assert "RENCA" not in todo
