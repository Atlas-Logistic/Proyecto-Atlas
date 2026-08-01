import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

import atlas_core.catalogo_plantas as modulo
from atlas_core.catalogo_plantas import (
    CatalogoCorruptoError,
    CatalogoPlantas,
    ErrorCatalogoPlantas,
    EstadoCalidad,
    ModificacionProtegidaError,
    PlantaDuplicadaError,
    normalizar_nombre_planta,
)
from gestionar_catalogos import crear_parser, ejecutar


class RelojSecuencial:
    def __init__(self):
        self.actual = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self):
        resultado = self.actual
        self.actual += timedelta(seconds=1)
        return resultado


def catalogo(tmp_path):
    return CatalogoPlantas(tmp_path / "plantas.json", reloj=RelojSecuencial())


def crear_demo(servicio, **cambios):
    datos = {
        "nombre": "PLANTA DEMO ÁGUILA",
        "direccion": "CALLE FICTICIA 100",
        "comuna": "COMUNA DEMO",
        "region": "REGIÓN DEMO",
        "pais": "PAÍS DEMO",
        "fuente": "PRUEBA_SINTETICA",
    }
    datos.update(cambios)
    return servicio.crear(**datos)


def test_creacion_correcta_y_lectura(tmp_path):
    servicio = catalogo(tmp_path)
    creada = crear_demo(servicio)

    assert UUID(creada.planta_id)
    assert servicio.listar() == [creada]
    assert servicio.obtener(creada.planta_id) == creada
    assert creada.estado_calidad == "PENDIENTE"
    assert creada.estado_vigencia == "ACTIVA"


def test_id_es_estable_al_editar_nombre(tmp_path):
    servicio = catalogo(tmp_path)
    original = crear_demo(servicio)

    editada = servicio.editar(original.planta_id, nombre="PLANTA DEMO RENOMBRADA")

    assert editada.planta_id == original.planta_id
    assert editada.nombre == "PLANTA DEMO RENOMBRADA"


@pytest.mark.parametrize("campo", ["nombre", "pais", "fuente"])
def test_rechaza_campos_obligatorios_vacios(tmp_path, campo):
    servicio = catalogo(tmp_path)
    datos = {
        "nombre": "PLANTA DEMO",
        "pais": "PAÍS DEMO",
        "fuente": "PRUEBA_SINTETICA",
    }
    datos[campo] = "   "

    with pytest.raises(ErrorCatalogoPlantas, match="obligatorio"):
        servicio.crear(**datos)


def test_previene_duplicados_por_nombre_normalizado(tmp_path):
    servicio = catalogo(tmp_path)
    crear_demo(servicio, nombre="  Planta   Demo Águila ")

    with pytest.raises(PlantaDuplicadaError):
        crear_demo(servicio, nombre="PLANTA DEMO AGUILA")


def test_normalizacion_conserva_original_y_normaliza_comparacion(tmp_path):
    servicio = catalogo(tmp_path)
    planta = crear_demo(servicio, nombre=" Planta   Ñandú Central ")

    assert planta.nombre == "Planta   Ñandú Central"
    assert planta.nombre_normalizado == "PLANTA NANDU CENTRAL"
    assert normalizar_nombre_planta("planta ñandú central") == planta.nombre_normalizado


def test_edicion_explicita_actualiza_campos_y_fecha(tmp_path):
    servicio = catalogo(tmp_path)
    original = crear_demo(servicio)

    editada = servicio.editar(
        original.planta_id,
        direccion="NUEVA DIRECCIÓN FICTICIA 200",
        observacion="Corrección manual sintética",
    )

    assert editada.direccion == "NUEVA DIRECCIÓN FICTICIA 200"
    assert editada.fecha_creacion == original.fecha_creacion
    assert editada.fecha_modificacion > original.fecha_modificacion


def test_planta_confirmada_requiere_modificacion_manual_explicita(tmp_path):
    servicio = catalogo(tmp_path)
    planta = crear_demo(servicio, estado_calidad=EstadoCalidad.CONFIRMADA)

    with pytest.raises(ModificacionProtegidaError):
        servicio.editar(planta.planta_id, observacion="Intento automático")

    editada = servicio.editar(
        planta.planta_id,
        modificacion_manual=True,
        observacion="Cambio manual confirmado",
    )
    assert editada.observacion == "Cambio manual confirmado"


def test_desactivacion_no_elimina_registro(tmp_path):
    servicio = catalogo(tmp_path)
    planta = crear_demo(servicio)

    inactiva = servicio.desactivar(planta.planta_id)

    assert inactiva.estado_vigencia == "INACTIVA"
    assert servicio.obtener(planta.planta_id) == inactiva
    assert len(servicio.listar()) == 1


@pytest.mark.parametrize(
    ("latitud", "longitud"), [(None, -70.0), (-33.0, None)]
)
def test_rechaza_coordenadas_incompletas(tmp_path, latitud, longitud):
    with pytest.raises(ErrorCatalogoPlantas, match="informarse juntas"):
        crear_demo(catalogo(tmp_path), latitud=latitud, longitud=longitud)


def test_lectura_y_escritura_json_validado(tmp_path):
    ruta = tmp_path / "subdirectorio" / "plantas.json"
    servicio = CatalogoPlantas(ruta, reloj=RelojSecuencial())
    planta = crear_demo(servicio)

    contenido = json.loads(ruta.read_text(encoding="utf-8"))
    assert contenido["version_formato"] == 1
    assert contenido["plantas"][0]["planta_id"] == planta.planta_id
    assert CatalogoPlantas(ruta).listar() == [planta]


def test_escritura_atomica_usa_reemplazo(tmp_path, monkeypatch):
    servicio = catalogo(tmp_path)
    reemplazos = []
    reemplazo_real = modulo.os.replace

    def registrar_reemplazo(origen, destino):
        reemplazos.append((origen, destino))
        reemplazo_real(origen, destino)

    monkeypatch.setattr(modulo.os, "replace", registrar_reemplazo)
    crear_demo(servicio)

    assert len(reemplazos) == 1
    assert reemplazos[0][0] != reemplazos[0][1]
    assert reemplazos[0][1] == servicio.ruta


def test_interrupcion_no_corrompe_archivo_existente(tmp_path, monkeypatch):
    servicio = catalogo(tmp_path)
    planta = crear_demo(servicio)
    contenido_original = servicio.ruta.read_bytes()

    def fallar_reemplazo(_origen, _destino):
        raise OSError("interrupción sintética")

    monkeypatch.setattr(modulo.os, "replace", fallar_reemplazo)
    with pytest.raises(OSError, match="interrupción sintética"):
        servicio.editar(planta.planta_id, observacion="no debe persistir")

    assert servicio.ruta.read_bytes() == contenido_original
    assert list(tmp_path.glob("*.tmp")) == []


def test_archivo_inexistente_representa_catalogo_vacio(tmp_path):
    ruta = tmp_path / "no_existe" / "plantas.json"
    servicio = CatalogoPlantas(ruta)

    assert servicio.listar() == []
    assert not ruta.exists()


@pytest.mark.parametrize("contenido", ["{", "[]", '{"version_formato": 99, "plantas": []}'])
def test_archivo_corrupto_o_incompatible_se_reporta(tmp_path, contenido):
    ruta = tmp_path / "plantas.json"
    ruta.write_text(contenido, encoding="utf-8")

    with pytest.raises(CatalogoCorruptoError):
        CatalogoPlantas(ruta).listar()


def test_fechas_de_auditoria_se_conservan_y_actualizan(tmp_path):
    servicio = catalogo(tmp_path)
    creada = crear_demo(servicio)
    editada = servicio.editar(creada.planta_id, comuna="OTRA COMUNA DEMO")
    inactiva = servicio.desactivar(creada.planta_id)

    assert creada.fecha_creacion == creada.fecha_modificacion
    assert editada.fecha_creacion == creada.fecha_creacion
    assert editada.fecha_modificacion > creada.fecha_modificacion
    assert inactiva.fecha_modificacion > editada.fecha_modificacion


def test_datos_y_archivo_de_prueba_son_sinteticos(tmp_path):
    planta = crear_demo(catalogo(tmp_path))
    serializado = json.dumps(planta.a_dict(), ensure_ascii=False)

    assert "DEMO" in serializado
    assert "AZA" not in serializado
    assert "COLINA" not in serializado
    assert "RENCA" not in serializado


def test_cli_permite_agregar_listar_mostrar_editar_y_desactivar(tmp_path, capsys):
    ruta = tmp_path / "plantas.json"
    parser = crear_parser()
    base = ["--archivo", str(ruta)]
    agregar = parser.parse_args(base + [
        "agregar", "--nombre", "PLANTA DEMO CLI", "--pais", "PAÍS DEMO",
        "--fuente", "PRUEBA_SINTETICA",
    ])
    assert ejecutar(agregar) == 0
    planta_id = CatalogoPlantas(ruta).listar()[0].planta_id
    assert ejecutar(parser.parse_args(base + ["listar"])) == 0
    assert ejecutar(parser.parse_args(base + ["mostrar", planta_id])) == 0
    assert ejecutar(parser.parse_args(base + [
        "editar", planta_id, "--comuna", "COMUNA DEMO CLI",
    ])) == 0
    assert ejecutar(parser.parse_args(base + ["desactivar", planta_id])) == 0
    assert "Planta desactivada correctamente" in capsys.readouterr().out


def test_plantilla_publica_es_sintetica_y_valida():
    ruta = modulo.Path("catalogos/templates/plantas_ejemplo.json")
    texto = ruta.read_text(encoding="utf-8")
    plantas = CatalogoPlantas(ruta).listar()

    assert len(plantas) == 1
    assert "DEMOSTRACIÓN" in texto
    assert "AZA" not in texto
    assert "COLINA" not in texto
    assert "RENCA" not in texto
