"""Interfaz de terminal para los Catálogos Maestros de Atlas."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from atlas_core.catalogo_clientes import (
    CatalogoClientes,
    ErrorCatalogoClientes,
    EstadoBusquedaCliente,
    EstadoCalidadCliente,
)
from atlas_core.catalogo_destinos import (
    CatalogoDestinos,
    ErrorCatalogoDestinos,
    EstadoBusquedaDestino,
    EstadoCalidadDestino,
)
from atlas_core.catalogo_plantas import CatalogoPlantas, ErrorCatalogoPlantas, EstadoCalidad


RUTA_PLANTAS_PREDETERMINADA = Path("catalogos/plantas.json")
RUTA_CLIENTES_PREDETERMINADA = Path("catalogos/clientes.json")
RUTA_DESTINOS_PREDETERMINADA = Path("catalogos/destinos.json")


def _agregar_campos_planta(parser: argparse.ArgumentParser, *, edicion: bool) -> None:
    requerido = not edicion
    parser.add_argument("--nombre", required=requerido, help="Nombre original de la planta")
    parser.add_argument("--direccion", help="Dirección confirmada; puede omitirse")
    parser.add_argument("--comuna", help="Comuna")
    parser.add_argument("--region", help="Región")
    parser.add_argument("--pais", required=requerido, help="País")
    parser.add_argument("--latitud", type=float, help="Latitud; requiere longitud")
    parser.add_argument("--longitud", type=float, help="Longitud; requiere latitud")
    parser.add_argument(
        "--estado-calidad",
        choices=[estado.value for estado in EstadoCalidad],
        default=None if edicion else EstadoCalidad.PENDIENTE.value,
    )
    parser.add_argument("--fuente", required=requerido, help="Origen de la información")
    parser.add_argument("--observacion", help="Observación manual")


def crear_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gestiona localmente el Catálogo Maestro de Plantas de Atlas."
    )
    parser.add_argument(
        "--archivo", type=Path, default=RUTA_PLANTAS_PREDETERMINADA,
        help="Archivo privado del catálogo (predeterminado: catalogos/plantas.json)",
    )
    subcomandos = parser.add_subparsers(dest="accion", required=True)
    subcomandos.add_parser("listar", help="Lista todas las plantas, incluidas las inactivas")
    agregar = subcomandos.add_parser("agregar", help="Agrega una planta")
    _agregar_campos_planta(agregar, edicion=False)
    mostrar = subcomandos.add_parser("mostrar", help="Muestra una planta por ID")
    mostrar.add_argument("planta_id")
    editar = subcomandos.add_parser("editar", help="Edita manualmente una planta")
    editar.add_argument("planta_id")
    _agregar_campos_planta(editar, edicion=True)
    editar.add_argument("--limpiar-coordenadas", action="store_true")
    editar.add_argument(
        "--confirmar-modificacion", action="store_true",
        help="Confirma explícitamente la modificación de una planta CONFIRMADA",
    )
    desactivar = subcomandos.add_parser("desactivar", help="Desactiva sin eliminar")
    desactivar.add_argument("planta_id")
    desactivar.add_argument(
        "--confirmar-modificacion", action="store_true",
        help="Confirma explícitamente la modificación de una planta CONFIRMADA",
    )
    return parser


def _agregar_campos_cliente(parser: argparse.ArgumentParser, *, edicion: bool) -> None:
    requerido = not edicion
    parser.add_argument("--razon-social", required=requerido, help="Razón social original")
    parser.add_argument("--nombre-comercial", help="Nombre comercial opcional")
    parser.add_argument("--rut", help="RUT opcional con dígito verificador")
    parser.add_argument(
        "--estado-calidad",
        choices=[estado.value for estado in EstadoCalidadCliente],
        default=None if edicion else EstadoCalidadCliente.PENDIENTE.value,
    )
    parser.add_argument("--fuente", required=requerido, help="Origen de la información")
    parser.add_argument("--observacion", help="Observación manual")


def crear_parser_clientes() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gestionar_catalogos.py clientes",
        description="Gestiona localmente el Catálogo Maestro de Clientes de Atlas.",
    )
    parser.add_argument(
        "--archivo",
        type=Path,
        default=RUTA_CLIENTES_PREDETERMINADA,
        help="Archivo privado (predeterminado: catalogos/clientes.json)",
    )
    subcomandos = parser.add_subparsers(dest="accion", required=True)
    subcomandos.add_parser("listar", help="Lista clientes, incluidos los inactivos")
    agregar = subcomandos.add_parser("agregar", help="Agrega un cliente")
    _agregar_campos_cliente(agregar, edicion=False)
    agregar.add_argument("--alias", action="append", default=[], help="Alias inicial; repetible")
    mostrar = subcomandos.add_parser("mostrar", help="Muestra un cliente por ID")
    mostrar.add_argument("cliente_id")
    editar = subcomandos.add_parser("editar", help="Edita manualmente un cliente")
    editar.add_argument("cliente_id")
    _agregar_campos_cliente(editar, edicion=True)
    editar.add_argument("--limpiar-rut", action="store_true", help="Elimina el RUT existente")
    editar.add_argument(
        "--confirmar-modificacion", action="store_true",
        help="Confirma explícitamente la modificación de un cliente CONFIRMADO",
    )
    desactivar = subcomandos.add_parser("desactivar", help="Desactiva sin eliminar")
    desactivar.add_argument("cliente_id")
    desactivar.add_argument("--confirmar-modificacion", action="store_true")
    alias = subcomandos.add_parser("agregar-alias", help="Añade un alias manual")
    alias.add_argument("cliente_id")
    alias.add_argument("--alias", required=True, help="Nombre alternativo original")
    alias.add_argument("--confirmar-modificacion", action="store_true")
    buscar = subcomandos.add_parser("buscar", help="Busca por nombre o alias normalizado")
    buscar.add_argument("--texto", required=True, help="Nombre o alias completo")
    return parser


def _agregar_campos_destino(parser: argparse.ArgumentParser, *, edicion: bool) -> None:
    requerido = not edicion
    parser.add_argument("--cliente-id", required=requerido, help="UUID de un cliente activo")
    parser.add_argument("--nombre", required=requerido, help="Nombre original del destino")
    parser.add_argument("--codigo-destino", help="Código opcional")
    parser.add_argument("--direccion", help="Dirección; puede quedar pendiente")
    parser.add_argument("--comuna", help="Comuna")
    parser.add_argument("--region", help="Región")
    parser.add_argument("--pais", required=requerido, help="País")
    parser.add_argument("--latitud", type=float, help="Latitud; requiere longitud")
    parser.add_argument("--longitud", type=float, help="Longitud; requiere latitud")
    parser.add_argument(
        "--estado-calidad",
        choices=[estado.value for estado in EstadoCalidadDestino],
        default=None if edicion else EstadoCalidadDestino.PENDIENTE.value,
    )
    parser.add_argument("--fuente", required=requerido, help="Origen de la información")
    parser.add_argument("--observacion", help="Observación manual")


def crear_parser_destinos() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gestionar_catalogos.py destinos",
        description="Gestiona localmente el Catálogo Maestro de Destinos de Atlas.",
    )
    parser.add_argument(
        "--archivo", type=Path, default=RUTA_DESTINOS_PREDETERMINADA,
        help="Archivo privado (predeterminado: catalogos/destinos.json)",
    )
    parser.add_argument(
        "--archivo-clientes", type=Path, default=RUTA_CLIENTES_PREDETERMINADA,
        help="Catálogo Maestro de Clientes usado para validar cliente_id",
    )
    subcomandos = parser.add_subparsers(dest="accion", required=True)
    listar = subcomandos.add_parser("listar", help="Lista destinos, incluidos los inactivos")
    listar.add_argument("--cliente-id", help="Filtra por UUID de cliente")
    agregar = subcomandos.add_parser("agregar", help="Agrega un destino")
    _agregar_campos_destino(agregar, edicion=False)
    agregar.add_argument("--alias", action="append", default=[], help="Alias inicial; repetible")
    mostrar = subcomandos.add_parser("mostrar", help="Muestra un destino por ID")
    mostrar.add_argument("destino_id")
    editar = subcomandos.add_parser("editar", help="Edita manualmente un destino")
    editar.add_argument("destino_id")
    _agregar_campos_destino(editar, edicion=True)
    editar.add_argument("--limpiar-coordenadas", action="store_true")
    editar.add_argument("--confirmar-modificacion", action="store_true")
    desactivar = subcomandos.add_parser("desactivar", help="Desactiva sin eliminar")
    desactivar.add_argument("destino_id")
    desactivar.add_argument("--confirmar-modificacion", action="store_true")
    alias = subcomandos.add_parser("agregar-alias", help="Añade un alias manual")
    alias.add_argument("destino_id")
    alias.add_argument("--alias", required=True)
    alias.add_argument("--confirmar-modificacion", action="store_true")
    buscar = subcomandos.add_parser("buscar", help="Busca por nombre o alias normalizado")
    buscar.add_argument("--texto", required=True)
    buscar.add_argument("--cliente-id", help="Limita la búsqueda a un cliente")
    return parser


def _imprimir_planta(planta: object) -> None:
    print(json.dumps(planta.a_dict(), ensure_ascii=False, indent=2))


def _imprimir_cliente(cliente: object) -> None:
    datos = cliente.a_dict()
    if datos.get("rut"):
        datos["rut"] = "PROTEGIDO"
    print(json.dumps(datos, ensure_ascii=False, indent=2))


def _imprimir_destino(destino: object) -> None:
    print(json.dumps(destino.a_dict(), ensure_ascii=False, indent=2))


def ejecutar(argumentos: argparse.Namespace) -> int:
    catalogo = CatalogoPlantas(argumentos.archivo)
    if argumentos.accion == "listar":
        plantas = catalogo.listar()
        if not plantas:
            print("El catálogo de plantas está vacío.")
            return 0
        for planta in plantas:
            print(f"{planta.planta_id} | {planta.nombre} | {planta.estado_calidad} | {planta.estado_vigencia}")
        return 0
    if argumentos.accion == "mostrar":
        _imprimir_planta(catalogo.obtener(argumentos.planta_id))
        return 0
    if argumentos.accion == "desactivar":
        planta = catalogo.desactivar(
            argumentos.planta_id, modificacion_manual=argumentos.confirmar_modificacion
        )
        print("Planta desactivada correctamente; el registro se conserva.")
        _imprimir_planta(planta)
        return 0
    campos = {
        "nombre": argumentos.nombre, "direccion": argumentos.direccion,
        "comuna": argumentos.comuna, "region": argumentos.region,
        "pais": argumentos.pais, "latitud": argumentos.latitud,
        "longitud": argumentos.longitud, "estado_calidad": argumentos.estado_calidad,
        "fuente": argumentos.fuente, "observacion": argumentos.observacion,
    }
    if argumentos.accion == "agregar":
        planta = catalogo.crear(**campos)
        print("Planta creada correctamente.")
    elif argumentos.accion == "editar":
        campos = {clave: valor for clave, valor in campos.items() if valor is not None}
        planta = catalogo.editar(
            argumentos.planta_id, modificacion_manual=argumentos.confirmar_modificacion,
            limpiar_coordenadas=argumentos.limpiar_coordenadas, **campos,
        )
        print("Planta actualizada correctamente.")
    _imprimir_planta(planta)
    return 0


def ejecutar_clientes(argumentos: argparse.Namespace) -> int:
    catalogo = CatalogoClientes(argumentos.archivo)
    if argumentos.accion == "listar":
        clientes = catalogo.listar()
        if not clientes:
            print("El catálogo de clientes está vacío.")
            return 0
        for cliente in clientes:
            print(
                f"{cliente.cliente_id} | {cliente.razon_social} | "
                f"{cliente.estado_calidad} | {cliente.estado_vigencia}"
            )
        return 0
    if argumentos.accion == "mostrar":
        _imprimir_cliente(catalogo.obtener(argumentos.cliente_id))
        return 0
    if argumentos.accion == "buscar":
        resultado = catalogo.buscar(argumentos.texto)
        if resultado.estado == EstadoBusquedaCliente.COINCIDENCIA:
            print("Coincidencia única encontrada.")
            _imprimir_cliente(resultado.cliente)
        elif resultado.estado == EstadoBusquedaCliente.AMBIGUA:
            print(
                "Coincidencia ambigua: Atlas se abstiene "
                f"({resultado.cantidad_coincidencias} candidatos)."
            )
        else:
            print("Sin coincidencia.")
        return 0
    if argumentos.accion == "desactivar":
        cliente = catalogo.desactivar(
            argumentos.cliente_id,
            modificacion_manual=argumentos.confirmar_modificacion,
        )
        print("Cliente desactivado correctamente; el registro se conserva.")
    elif argumentos.accion == "agregar-alias":
        cliente = catalogo.agregar_alias(
            argumentos.cliente_id,
            argumentos.alias,
            modificacion_manual=argumentos.confirmar_modificacion,
        )
        print("Alias agregado correctamente.")
    else:
        campos = {
            "razon_social": argumentos.razon_social,
            "nombre_comercial": argumentos.nombre_comercial,
            "rut": argumentos.rut,
            "estado_calidad": argumentos.estado_calidad,
            "fuente": argumentos.fuente,
            "observacion": argumentos.observacion,
        }
        if argumentos.accion == "agregar":
            cliente = catalogo.crear(**campos, aliases=argumentos.alias)
            print("Cliente creado correctamente.")
        else:
            campos = {clave: valor for clave, valor in campos.items() if valor is not None}
            cliente = catalogo.editar(
                argumentos.cliente_id,
                modificacion_manual=argumentos.confirmar_modificacion,
                limpiar_rut=argumentos.limpiar_rut,
                **campos,
            )
            print("Cliente actualizado correctamente.")
    _imprimir_cliente(cliente)
    return 0


def ejecutar_destinos(argumentos: argparse.Namespace) -> int:
    catalogo = CatalogoDestinos(
        argumentos.archivo, ruta_clientes=argumentos.archivo_clientes
    )
    if argumentos.accion == "listar":
        destinos = catalogo.listar(cliente_id=argumentos.cliente_id)
        if not destinos:
            print("El catálogo de destinos está vacío para el criterio solicitado.")
            return 0
        for destino in destinos:
            print(
                f"{destino.destino_id} | {destino.nombre_destino} | "
                f"cliente={destino.cliente_id} | {destino.estado_calidad} | "
                f"{destino.estado_vigencia}"
            )
        return 0
    if argumentos.accion == "mostrar":
        _imprimir_destino(catalogo.obtener(argumentos.destino_id))
        return 0
    if argumentos.accion == "buscar":
        resultado = catalogo.buscar(
            argumentos.texto, cliente_id=argumentos.cliente_id
        )
        if resultado.estado == EstadoBusquedaDestino.COINCIDENCIA:
            print("Coincidencia única encontrada.")
            _imprimir_destino(resultado.destino)
        elif resultado.estado == EstadoBusquedaDestino.AMBIGUA:
            print(
                "Coincidencia ambigua: Atlas se abstiene "
                f"({resultado.cantidad_coincidencias} candidatos)."
            )
        else:
            print("Sin coincidencia.")
        return 0
    if argumentos.accion == "desactivar":
        destino = catalogo.desactivar(
            argumentos.destino_id,
            modificacion_manual=argumentos.confirmar_modificacion,
        )
        print("Destino desactivado correctamente; el registro se conserva.")
    elif argumentos.accion == "agregar-alias":
        destino = catalogo.agregar_alias(
            argumentos.destino_id,
            argumentos.alias,
            modificacion_manual=argumentos.confirmar_modificacion,
        )
        print("Alias de destino agregado correctamente.")
    else:
        campos = {
            "cliente_id": argumentos.cliente_id,
            "nombre_destino": argumentos.nombre,
            "codigo_destino": argumentos.codigo_destino,
            "direccion": argumentos.direccion,
            "comuna": argumentos.comuna,
            "region": argumentos.region,
            "pais": argumentos.pais,
            "latitud": argumentos.latitud,
            "longitud": argumentos.longitud,
            "estado_calidad": argumentos.estado_calidad,
            "fuente": argumentos.fuente,
            "observacion": argumentos.observacion,
        }
        if argumentos.accion == "agregar":
            destino = catalogo.crear(**campos, aliases=argumentos.alias)
            print("Destino creado correctamente.")
        else:
            campos = {clave: valor for clave, valor in campos.items() if valor is not None}
            destino = catalogo.editar(
                argumentos.destino_id,
                modificacion_manual=argumentos.confirmar_modificacion,
                limpiar_coordenadas=argumentos.limpiar_coordenadas,
                **campos,
            )
            print("Destino actualizado correctamente.")
    _imprimir_destino(destino)
    return 0


def main(argv: list[str] | None = None) -> int:
    argumentos_crudos = list(sys.argv[1:] if argv is None else argv)
    try:
        if argumentos_crudos and argumentos_crudos[0] == "destinos":
            argumentos = crear_parser_destinos().parse_args(argumentos_crudos[1:])
            return ejecutar_destinos(argumentos)
        if argumentos_crudos and argumentos_crudos[0] == "clientes":
            argumentos = crear_parser_clientes().parse_args(argumentos_crudos[1:])
            return ejecutar_clientes(argumentos)
        if argumentos_crudos and argumentos_crudos[0] == "plantas":
            argumentos_crudos = argumentos_crudos[1:]
        argumentos = crear_parser().parse_args(argumentos_crudos)
        return ejecutar(argumentos)
    except (
        ErrorCatalogoPlantas,
        ErrorCatalogoClientes,
        ErrorCatalogoDestinos,
        OSError,
    ) as error:
        print(f"Error: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
