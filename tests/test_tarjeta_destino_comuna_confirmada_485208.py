import json
from types import SimpleNamespace

import pytest

from atlas_core import decisiones_pendientes as decisiones
from atlas_core.catalogo_destinos import consolidar_destinos_equivalentes


@pytest.fixture
def caso(tmp_path, monkeypatch):
    obra = SimpleNamespace(obra_id="obra", nombre_canonico="ARMACERO MATCO SA", aliases_documentales=(), estado_vigencia="ACTIVO")
    destinos = [
        SimpleNamespace(destino_id="a", direccion="SANTA ISABEL 585, LAMPA, CHILE", comuna="LAMPA", latitud=-33.310665, longitud=-70.737609),
        SimpleNamespace(destino_id="b", direccion="SANTA ISABEL 585", comuna="LAMPA", latitud=-33.307635, longitud=-70.733135),
    ]
    class Catalogo:
        def __init__(self, **kwargs): pass
        def listar_obras(self): return [obra]
        def resolver_obra_destino_confirmada(self, **kwargs): return None
        def listar_destinos_confirmados_para_obra(self, **kwargs): return destinos
    monkeypatch.setattr(decisiones, "CatalogoObrasDestinos", Catalogo)
    def ejecutar(texto):
        return decisiones._decisiones_obra_para_cliente(
            carpeta=tmp_path, cliente_id="cliente", cliente_razon_social="ARMACERO MATCO SA",
            cliente_aliases=(), obra_texto="ARMACERO MATCO SA", despachar_a_documental=texto,
            comunes={"archivo":"485208.jpeg", "numero_guia":"485208", "numero_transporte":"0000371560"},
        )
    return destinos, ejecutar


def test_no_pregunta_por_ocr_confirmado_pero_conserva_ambiguedad_geografica(caso):
    destinos, ejecutar = caso
    antes = [(d.destino_id, d.direccion, d.comuna, d.latitud, d.longitud) for d in destinos]
    assert ejecutar("SANTA ISABEL S85 SANTIAGO LAMPA") == []
    assert consolidar_destinos_equivalentes(destinos) == destinos
    assert [(d.destino_id, d.direccion, d.comuna, d.latitud, d.longitud) for d in destinos] == antes


@pytest.mark.parametrize("texto", [
    "SANTA ISABEL S85 SANTIAGO", "SANTA ISABEL S85 COLINA", "SANTA LUISA S85 LAMPA",
    "SANTA ISABEL S95 LAMPA", "SANTA ISABEL S850 LAMPA", "SANTA ISABEL S85 700 LAMPA",
])
def test_ocr_sin_anclas_suficientes_mantiene_tarjeta(caso, texto):
    _, ejecutar = caso
    assert [d["tipo"] for d in ejecutar(texto)] == ["DESTINO_SIN_CONFIRMAR"]


def test_no_presta_comuna_de_otro_destino(caso):
    destinos, ejecutar = caso
    destinos[0].comuna = ""
    destinos[1].direccion = "OTRA CALLE 999"
    destinos[1].comuna = "LAMPA"
    assert [d["tipo"] for d in ejecutar("SANTA ISABEL S85 LAMPA")] == ["DESTINO_SIN_CONFIRMAR"]


def test_deteccion_y_regeneracion_con_catalogo_real_sintetico(tmp_path):
    from test_regeneracion_b1 import _catalogos_base, _confirmar_destino_para_obra
    from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
    from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos
    carpeta = tmp_path / "catalogos_privados"
    carpeta.mkdir()
    _catalogos_base(carpeta)
    cliente = CatalogoClientes(carpeta / "clientes.json").crear(razon_social="ARMACERO MATCO SA", rut="76.111.111-6", fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO)
    catalogo = CatalogoObrasDestinos(ruta=carpeta / "obras_destinos.json", ruta_clientes=carpeta / "clientes.json", ruta_destinos=carpeta / "destinos_maestros.json")
    for i, direccion in enumerate(("SANTA ISABEL 585, LAMPA, CHILE", "SANTA ISABEL 585")):
        _confirmar_destino_para_obra(catalogo, carpeta, cliente_id=cliente.cliente_id, obra="ARMACERO MATCO SA", texto_destino=direccion, guia=str(i))
    archivo = carpeta / "destinos_maestros.json"
    contenido = json.loads(archivo.read_text(encoding="utf-8"))
    for destino, lat, lon in zip(contenido["destinos"], (-33.310665, -33.307635), (-70.737609, -70.733135)):
        destino.update(comuna="LAMPA", latitud=lat, longitud=lon)
    archivo.write_text(json.dumps(contenido), encoding="utf-8")
    ds = catalogo.listar_destinos_confirmados_para_obra(nombre_obra="ARMACERO MATCO SA")
    assert len(ds) == 2 and len(consolidar_destinos_equivalentes(ds)) == 2
    obra = catalogo.listar_obras()[0]
    texto = "SANTA ISABEL S85 SANTIAGO LAMPA"
    argumentos = dict(carpeta=carpeta, cliente_id=cliente.cliente_id, cliente_razon_social=cliente.razon_social, cliente_aliases=(), obra_texto=obra.nombre_canonico, despachar_a_documental=texto, comunes={"archivo":"485208.jpeg", "numero_guia":"485208", "numero_transporte":"0000371560"})
    antes = {p.name: p.read_bytes() for p in carpeta.iterdir() if p.is_file()}
    assert decisiones._decisiones_obra_para_cliente(**argumentos) == []
    pendiente = decisiones.crear_decision(tipo="DESTINO_SIN_CONFIRMAR", entidad="RELACION_OBRA_DESTINO", archivo="485208.jpeg", numero_guia="485208", numero_transporte="0000371560", campo="destino_entrega", valor_documental=texto, valor_normalizado=texto, identidad_resuelta={"entidad_id":obra.obra_id, "valor_canonico":obra.nombre_canonico}, candidatos=(), motivos=("OBRA_SIN_RELACION_CONFIRMADA_UNICA",), evidencias=(), acciones_permitidas=("CONFIRMAR", "NO_CONFIRMAR", "POSPONER"), contexto={"obra_canonica":obra.nombre_canonico,"destino_documental":texto})
    assert decisiones.regenerar_decisiones_persistidas(decisiones=[pendiente], carpeta_catalogos=carpeta) == []
    assert antes == {p.name: p.read_bytes() for p in carpeta.iterdir() if p.is_file()}
    assert len(consolidar_destinos_equivalentes(catalogo.listar_destinos_confirmados_para_obra(nombre_obra=obra.nombre_canonico))) == 2


def test_ruteo_convergente_sigue_sin_elegir_entre_coordenadas_distintas(caso, monkeypatch):
    from atlas_core import convergencia_destino_confirmado as modulo
    destinos, ejecutar = caso
    cliente = SimpleNamespace(cliente_id="cliente", razon_social="ARMACERO MATCO SA", rut="76111111-6", aliases=(), estado_calidad="CONFIRMADO", estado_vigencia="ACTIVO")
    obra = SimpleNamespace(obra_id="obra", cliente_id="cliente", nombre_canonico=cliente.razon_social, aliases_documentales=(), estado="CONFIRMADA", estado_vigencia="ACTIVO", evidencias=[])
    monkeypatch.setattr(modulo, "CatalogoClientes", lambda *a, **k: SimpleNamespace(listar=lambda: [cliente]))
    monkeypatch.setattr(modulo, "CatalogoObrasDestinos", lambda *a, **k: SimpleNamespace(listar_obras=lambda: [obra], listar_destinos_confirmados_para_obra=lambda **k: destinos))
    assert ejecutar("SANTA ISABEL S85 SANTIAGO LAMPA") == []
    fila = {"cliente": cliente.razon_social, "rut_cliente":cliente.rut, "obra_destino":obra.nombre_canonico, "despachar_a_crudo":"SANTA ISABEL 585 SANTIAGO LAMPA"}
    assert modulo.resolver_destino_confirmado(fila, carpeta_catalogos="catalogos") is None
