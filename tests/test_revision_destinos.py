from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

import revision_destinos as cli_revision
from atlas_core.inteligencia.revision_destinos import (
    ACCIONES_PERMITIDAS,
    ConfiguracionRevisionDestinos,
    DecisionHumanaDestino,
    DestinoEntrada,
    ErrorConfiguracionRevision,
    ErrorEntradaDestinos,
    EstadoRevisionDestino,
    ProveedorRespuestasCongeladas,
    cargar_destinos,
    ejecutar_archivo,
    procesar_destinos,
    sha256_archivo,
)
from atlas_core.inteligencia.verificacion_destinos import (
    RespuestaHTTPDestino,
    SolicitudVerificacionDestino,
    VerificadorDestinosOpenRouteService,
)


FECHA = datetime(2026, 7, 28, 23, 0, tzinfo=timezone.utc)
CAMPOS = [
    "direccion_original", "comuna_esperada", "region_esperada", "pais"
]


def fila(**cambios):
    base = {
        "destino_id": "DEST-001",
        "cliente_id": "CLI-001",
        "direccion": "AVENIDA CENTRAL 123",
        "comuna": "RENCA",
        "region": "REGIÓN METROPOLITANA",
        "pais": "CHILE",
        "latitud": "",
        "longitud": "",
        "estado_actual": "CONFIRMADO_DOCUMENTAL",
        "autorizacion_consulta_externa": True,
        "campos_autorizados": CAMPOS,
    }
    base.update(cambios)
    return base


def escribir_json(ruta, filas):
    ruta.write_text(json.dumps(filas, ensure_ascii=False), encoding="utf-8")


def escribir_csv(ruta, filas, *, bom=False, delimitador=";"):
    with ruta.open("w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=list(filas[0]), delimiter=delimitador)
        escritor.writeheader()
        for item in filas:
            datos = dict(item)
            if isinstance(datos["campos_autorizados"], list):
                datos["campos_autorizados"] = "|".join(datos["campos_autorizados"])
            escritor.writerow(datos)


def test_json_valido(tmp_path):
    ruta = tmp_path / "entrada.json"
    escribir_json(ruta, [fila()])
    assert cargar_destinos(ruta)[0].destino_id == "DEST-001"


@pytest.mark.parametrize(("bom", "delimitador"), [(False, ";"), (True, ";"), (True, ",")])
def test_csv_valido_incluido_bom(tmp_path, bom, delimitador):
    ruta = tmp_path / "entrada.csv"
    escribir_csv(ruta, [fila()], bom=bom, delimitador=delimitador)
    assert cargar_destinos(ruta)[0].direccion == "AVENIDA CENTRAL 123"


@pytest.mark.parametrize("campo", [
    "destino_id", "direccion", "comuna", "region", "pais", "estado_actual",
    "autorizacion_consulta_externa", "campos_autorizados",
])
def test_esquema_invalido_rechaza_campo_faltante(tmp_path, campo):
    datos = fila()
    datos.pop(campo)
    ruta = tmp_path / "entrada.json"
    escribir_json(ruta, [datos])
    with pytest.raises(ErrorEntradaDestinos):
        cargar_destinos(ruta)


def test_archivo_vacio(tmp_path):
    ruta = tmp_path / "vacio.json"
    ruta.write_bytes(b"")
    with pytest.raises(ErrorEntradaDestinos):
        cargar_destinos(ruta)


def test_entrada_inexistente(tmp_path):
    with pytest.raises(FileNotFoundError):
        cargar_destinos(tmp_path / "no-existe.json")


def test_registro_original_completo_e_inmutable(tmp_path):
    datos = fila(campo_adicional="CONSERVAR")
    ruta = tmp_path / "entrada.json"
    escribir_json(ruta, [datos])
    destino = cargar_destinos(ruta)[0]
    assert destino.registro_original["campo_adicional"] == "CONSERVAR"
    with pytest.raises(TypeError):
        destino.registro_original["x"] = "y"


def test_coordenadas_deben_coexistir(tmp_path):
    ruta = tmp_path / "entrada.json"
    escribir_json(ruta, [fila(latitud=-33.4, longitud="")])
    with pytest.raises(ErrorEntradaDestinos):
        cargar_destinos(ruta)


def test_consultas_desactivadas_por_defecto():
    resultado = procesar_destinos((destino(),), fecha_evaluacion=FECHA)
    assert resultado.revisiones[0].estado_revision == (
        EstadoRevisionDestino.CONSULTA_NO_AUTORIZADA
    )
    assert resultado.resumen["consultas_externas_consumidas"] == 0


def test_configuracion_insegura_es_rechazada():
    with pytest.raises(ErrorConfiguracionRevision):
        ConfiguracionRevisionDestinos(permitir_consultas=False, max_consultas=1)
    with pytest.raises(ErrorConfiguracionRevision):
        ConfiguracionRevisionDestinos(usar_cache=False, solo_cache=True)


def test_solo_cache_sin_cache_es_error():
    config = ConfiguracionRevisionDestinos(
        permitir_consultas=True, max_consultas=0, solo_cache=True
    )
    with pytest.raises(ErrorConfiguracionRevision):
        procesar_destinos((destino(),), configuracion=config, fecha_evaluacion=FECHA)


def destino(**cambios):
    datos = fila(**cambios)
    return DestinoEntrada(
        datos["destino_id"], datos["cliente_id"], datos["direccion"],
        datos["comuna"], datos["region"], datos["pais"],
        None if datos["latitud"] == "" else datos["latitud"],
        None if datos["longitud"] == "" else datos["longitud"],
        datos["estado_actual"], datos["autorizacion_consulta_externa"],
        frozenset(datos["campos_autorizados"]), datos,
    )


def feature(label="AVENIDA CENTRAL 123, RENCA, RM, CHILE", *,
            comuna="RENCA", region="METROPOLITANA", coords=(-70.7, -33.4)):
    return {
        "geometry": {"coordinates": list(coords)},
        "properties": {
            "label": label, "localadmin": comuna, "region": region,
            "country": "Chile", "confidence": 0.9,
        },
    }


class ProveedorSintetico:
    nombre = "sintetico"

    def __init__(self, respuestas):
        self.respuestas = respuestas
        self.consultas_externas = 0

    def verificar(self, solicitud: SolicitudVerificacionDestino):
        especificacion = self.respuestas[solicitud.identificador_interno]
        if isinstance(especificacion, Exception):
            raise especificacion
        if especificacion == "SIN_CREDENCIAL":
            return VerificadorDestinosOpenRouteService(
                api_key="", reloj=lambda: FECHA
            ).verificar(solicitud)
        self.consultas_externas += 1
        proveedor = VerificadorDestinosOpenRouteService(
            api_key="CLAVE_SINTETICA",
            usar_cache=False,
            limite_consultas=1,
            transporte=lambda *_: RespuestaHTTPDestino(
                200, json.dumps({"features": especificacion}).encode()
            ),
            reloj=lambda: FECHA,
            monotono=lambda: 1.0,
        )
        return proveedor.verificar(solicitud)


def config(max_consultas=20):
    return ConfiguracionRevisionDestinos(
        permitir_consultas=True, max_consultas=max_consultas,
        usar_cache=True, proveedor="sintetico",
    )


@pytest.mark.parametrize(
    ("features", "estado"),
    [
        ([feature()], EstadoRevisionDestino.CONFIRMACION_PROPUESTA),
        ([feature(label="AVENIDA CENTRAL, RENCA, RM, CHILE")],
         EstadoRevisionDestino.COINCIDENCIA_PARCIAL),
        ([feature(label="AVENIDA CENTRAL 999, RENCA, RM, CHILE")],
         EstadoRevisionDestino.CONTRADICCION_NUMERO),
        ([feature(comuna="QUILICURA")], EstadoRevisionDestino.CONTRADICCION_COMUNA),
        ([feature(region="VALPARAÍSO")], EstadoRevisionDestino.CONTRADICCION_REGION),
        ([feature(), feature()], EstadoRevisionDestino.RESPUESTA_AMBIGUA),
        ([], EstadoRevisionDestino.SIN_RESULTADOS),
    ],
)
def test_estados_de_revision(features, estado):
    proveedor = ProveedorSintetico({"DEST-001": features})
    resultado = procesar_destinos(
        (destino(),), configuracion=config(), proveedor=proveedor,
        fecha_evaluacion=FECHA,
    )
    assert resultado.revisiones[0].estado_revision == estado


def test_region_equivalente_no_es_contradiccion():
    proveedor = ProveedorSintetico({"DEST-001": [feature(region="RM")]})
    revision = procesar_destinos(
        (destino(),), configuracion=config(), proveedor=proveedor,
        fecha_evaluacion=FECHA,
    ).revisiones[0]
    assert revision.estado_revision == EstadoRevisionDestino.CONFIRMACION_PROPUESTA


def test_coordenadas_previas_iguales_sin_cambios():
    d = destino(latitud=-33.4, longitud=-70.7)
    proveedor = ProveedorSintetico({"DEST-001": [feature()]})
    revision = procesar_destinos(
        (d,), configuracion=config(), proveedor=proveedor, fecha_evaluacion=FECHA
    ).revisiones[0]
    assert revision.estado_revision == EstadoRevisionDestino.SIN_CAMBIOS
    assert revision.accion_recomendada == "MANTENER"


def test_coordenadas_previas_diferentes_se_proponen():
    d = destino(latitud=-33.5, longitud=-70.8)
    proveedor = ProveedorSintetico({"DEST-001": [feature()]})
    revision = procesar_destinos(
        (d,), configuracion=config(), proveedor=proveedor, fecha_evaluacion=FECHA
    ).revisiones[0]
    assert revision.estado_revision == EstadoRevisionDestino.COORDENADAS_PROPUESTAS
    assert revision.requiere_decision_humana


def test_registro_no_autorizado_no_consulta():
    proveedor = ProveedorSintetico({"DEST-001": [feature()]})
    revision = procesar_destinos(
        (destino(autorizacion_consulta_externa=False),),
        configuracion=config(), proveedor=proveedor, fecha_evaluacion=FECHA,
    ).revisiones[0]
    assert revision.estado_revision == EstadoRevisionDestino.CONSULTA_NO_AUTORIZADA
    assert proveedor.consultas_externas == 0


def test_maximo_consultas_y_cuota_local():
    destinos = tuple(destino(destino_id=f"DEST-{i:03d}") for i in range(3))
    proveedor = ProveedorSintetico({
        d.destino_id: [feature()] for d in destinos
    })
    resultado = procesar_destinos(
        destinos, configuracion=config(max_consultas=1), proveedor=proveedor,
        fecha_evaluacion=FECHA,
    )
    assert proveedor.consultas_externas == 1
    assert sum(r.estado_revision == EstadoRevisionDestino.ERROR_PROVEEDOR
               for r in resultado.revisiones) == 2


def test_error_individual_no_detiene_lote():
    destinos = (destino(destino_id="A"), destino(destino_id="B"))
    proveedor = ProveedorSintetico({"A": RuntimeError("fallo"), "B": [feature()]})
    resultado = procesar_destinos(
        destinos, configuracion=config(), proveedor=proveedor, fecha_evaluacion=FECHA
    )
    assert len(resultado.revisiones) == 2
    assert resultado.revisiones[0].estado_revision == EstadoRevisionDestino.ERROR_PROVEEDOR
    assert resultado.revisiones[1].estado_revision == EstadoRevisionDestino.CONFIRMACION_PROPUESTA


def test_orden_determinista():
    destinos = (destino(destino_id="Z"), destino(destino_id="A"))
    resultado = procesar_destinos(destinos, fecha_evaluacion=FECHA)
    assert [r.destino_id for r in resultado.revisiones] == ["A", "Z"]


def test_propuesta_separada_del_original():
    proveedor = ProveedorSintetico({"DEST-001": [feature()]})
    revision = procesar_destinos(
        (destino(),), configuracion=config(), proveedor=proveedor,
        fecha_evaluacion=FECHA,
    ).revisiones[0]
    assert revision.direccion_original == "AVENIDA CENTRAL 123"
    assert revision.requiere_decision_humana
    assert revision.accion_recomendada != "ACEPTAR_AUTOMATICAMENTE"


def test_acciones_y_decisiones_humanas_separadas():
    assert "ACEPTAR_AUTOMATICAMENTE" not in ACCIONES_PERMITIDAS
    assert {d.value for d in DecisionHumanaDestino} == {
        "CONFIRMAR_PROPUESTA", "RECHAZAR_PROPUESTA", "CORREGIR_MANUALMENTE",
        "POSPONER", "MARCAR_NO_RECONOCIDO",
    }


def test_datos_sensibles_no_aparecen_en_revision():
    d = destino(rut="12.345.678-5", patente="ABC123", chofer="PERSONA")
    revision = procesar_destinos((d,), fecha_evaluacion=FECHA).revisiones[0]
    texto = repr(revision)
    assert "12.345" not in texto and "ABC123" not in texto and "PERSONA" not in texto


def test_clave_no_aparece_en_salida():
    proveedor = ProveedorSintetico({"DEST-001": [feature()]})
    revision = procesar_destinos(
        (destino(),), configuracion=config(), proveedor=proveedor,
        fecha_evaluacion=FECHA,
    ).revisiones[0]
    assert "CLAVE_SINTETICA" not in repr(revision)


def test_salida_csv_json_resumen_manifiesto_y_bom(tmp_path):
    entrada = tmp_path / "entrada.json"
    salida = tmp_path / "salida"
    escribir_json(entrada, [fila()])
    ejecutar_archivo(entrada, salida, fecha_evaluacion=FECHA)
    esperados = {
        "revisiones_destinos.csv", "revisiones_destinos.json",
        "resumen_revision_destinos.json", "manifiesto_ejecucion.json",
    }
    assert {p.name for p in salida.iterdir()} == esperados
    assert (salida / "revisiones_destinos.csv").read_bytes()[:3] == b"\xef\xbb\xbf"
    assert b";" in (salida / "revisiones_destinos.csv").read_bytes()


def test_origen_no_modificado_y_hash_identico(tmp_path):
    entrada = tmp_path / "entrada.json"
    escribir_json(entrada, [fila()])
    antes = sha256_archivo(entrada)
    ejecutar_archivo(entrada, tmp_path / "salida", fecha_evaluacion=FECHA)
    assert sha256_archivo(entrada) == antes
    resumen = json.loads(
        (tmp_path / "salida/resumen_revision_destinos.json").read_text()
    )
    assert resumen["entrada_intacta"]


def test_fuente_solo_lectura_no_se_intenta_escribir(tmp_path):
    entrada = tmp_path / "entrada.json"
    escribir_json(entrada, [fila()])
    entrada.chmod(0o444)
    try:
        ejecutar_archivo(entrada, tmp_path / "salida", fecha_evaluacion=FECHA)
        assert sha256_archivo(entrada)
    finally:
        entrada.chmod(0o644)


def _entrada_piloto(tmp_path):
    gt = list(csv.DictReader(
        Path("validaciones/piloto_real_destinos_2026-07-28/"
             "ground_truth_congelado.csv").open(encoding="utf-8-sig")
    ))
    filas = [{
        "destino_id": r["identificador_interno"],
        "cliente_id": "",
        "direccion": r["direccion_confirmada"],
        "comuna": r["comuna_confirmada"],
        "region": r["region_confirmada"],
        "pais": r["pais"],
        "latitud": r["latitud_aprobada"],
        "longitud": r["longitud_aprobada"],
        "estado_actual": r["estado_confirmacion"],
        "autorizacion_consulta_externa": True,
        "campos_autorizados": CAMPOS,
    } for r in gt]
    ruta = tmp_path / "piloto.json"
    escribir_json(ruta, filas)
    return ruta


def test_12_respuestas_congeladas_la_union_y_torres(tmp_path):
    entrada = _entrada_piloto(tmp_path)
    proveedor = ProveedorRespuestasCongeladas(
        "validaciones/piloto_real_destinos_2026-07-28/"
        "respuestas_ors_congeladas.json"
    )
    configuracion = ConfiguracionRevisionDestinos(
        permitir_consultas=True, max_consultas=0, usar_cache=True,
        solo_cache=True, proveedor="respuestas-congeladas",
    )
    resultado = ejecutar_archivo(
        entrada, tmp_path / "salida", configuracion=configuracion,
        proveedor=proveedor, fecha_evaluacion=FECHA,
    )
    assert len(resultado.revisiones) == 12
    por_direccion = {r.direccion_original: r for r in resultado.revisiones}
    assert por_direccion["LA UNION 3070"].estado_revision == (
        EstadoRevisionDestino.CONFIRMACION_PROPUESTA
    )
    assert por_direccion["VISTA CLARA 2351"].estado_revision == (
        EstadoRevisionDestino.CONTRADICCION_COMUNA
    )
    assert resultado.resumen["resultados_desde_cache"] == 12
    assert resultado.resumen["consultas_externas_consumidas"] == 0
    assert all(r.huella_del_registro_original for r in resultado.revisiones)


def test_determinismo_bandeja_congelada(tmp_path):
    entrada = _entrada_piloto(tmp_path)
    configuracion = ConfiguracionRevisionDestinos(
        permitir_consultas=True, max_consultas=0, solo_cache=True,
        proveedor="respuestas-congeladas",
    )
    def ejecutar(nombre):
        proveedor = ProveedorRespuestasCongeladas(
            "validaciones/piloto_real_destinos_2026-07-28/"
            "respuestas_ors_congeladas.json"
        )
        ejecutar_archivo(
            entrada, tmp_path / nombre, configuracion=configuracion,
            proveedor=proveedor, fecha_evaluacion=FECHA,
        )
    ejecutar("a")
    ejecutar("b")
    for nombre in (
        "revisiones_destinos.csv", "revisiones_destinos.json",
        "resumen_revision_destinos.json", "manifiesto_ejecucion.json",
    ):
        assert (tmp_path / "a" / nombre).read_bytes() == (
            tmp_path / "b" / nombre
        ).read_bytes()


def test_registro_adicional_y_15_campos_oficiales_no_se_omiten(tmp_path):
    datos = fila(**{f"campo_oficial_{i}": f"valor_{i}" for i in range(15)})
    datos["destino_id"] = "DESCONOCIDO-999"
    ruta = tmp_path / "entrada.json"
    escribir_json(ruta, [datos])
    cargado = cargar_destinos(ruta)[0]
    assert cargado.destino_id == "DESCONOCIDO-999"
    assert sum(k.startswith("campo_oficial_") for k in cargado.registro_original) == 15


def test_caracteres_enie_y_tildes(tmp_path):
    ruta = tmp_path / "entrada.json"
    escribir_json(ruta, [fila(direccion="CAMIÑO UNIÓN 123")])
    assert cargar_destinos(ruta)[0].direccion == "CAMIÑO UNIÓN 123"


def test_lote_sintetico_de_15_casos_completo_y_tolerante():
    destinos = cargar_destinos(
        "validaciones/integracion_destinos_modo_revision_2026-07-28/"
        "lote_sintetico_revision.json"
    )
    def f(d, **cambios):
        label = cambios.pop(
            "label", f"{d.direccion}, {d.comuna}, {d.region}, CHILE"
        )
        comuna = cambios.pop("comuna", d.comuna)
        region = cambios.pop("region", d.region)
        return feature(
            label=label, comuna=comuna, region=region, **cambios,
        )
    por_id = {d.destino_id: d for d in destinos}
    respuestas = {
        "SYN-001": [f(por_id["SYN-001"])],
        "SYN-002": [f(por_id["SYN-002"], label="AVENIDA CENTRAL 123, RENCA, RM, CHILE")],
        "SYN-003": [f(por_id["SYN-003"], label="CALLE NÚMERO 999, RENCA, RM, CHILE")],
        "SYN-004": [f(por_id["SYN-004"], comuna="SANTIAGO")],
        "SYN-005": [f(por_id["SYN-005"], region="RM")],
        "SYN-006": [f(por_id["SYN-006"], region="METROPOLITANA")],
        "SYN-007": [f(por_id["SYN-007"]), f(por_id["SYN-007"])],
        "SYN-008": [],
        "SYN-009": [f(por_id["SYN-009"])],
        "SYN-010": RuntimeError("proveedor caído"),
        "SYN-011": "SIN_CREDENCIAL",
        "SYN-012": [f(por_id["SYN-012"], coords=(-70.7, -33.4))],
        "SYN-013": [f(por_id["SYN-013"])],
        "SYN-014": [f(por_id["SYN-014"])],
        "SYN-015": [f(por_id["SYN-015"])],
    }
    resultado = procesar_destinos(
        destinos, configuracion=config(max_consultas=20),
        proveedor=ProveedorSintetico(respuestas), fecha_evaluacion=FECHA,
    )
    assert len(resultado.revisiones) == 15
    assert {r.destino_id for r in resultado.revisiones} == set(por_id)
    estados = {r.destino_id: r.estado_revision for r in resultado.revisiones}
    assert estados["SYN-003"] == EstadoRevisionDestino.CONTRADICCION_NUMERO
    assert estados["SYN-004"] == EstadoRevisionDestino.CONTRADICCION_COMUNA
    assert estados["SYN-006"] == EstadoRevisionDestino.CONTRADICCION_REGION
    assert estados["SYN-007"] == EstadoRevisionDestino.RESPUESTA_AMBIGUA
    assert estados["SYN-008"] == EstadoRevisionDestino.SIN_RESULTADOS
    assert estados["SYN-009"] == EstadoRevisionDestino.CONSULTA_NO_AUTORIZADA
    assert estados["SYN-010"] == EstadoRevisionDestino.ERROR_PROVEEDOR
    assert estados["SYN-011"] == EstadoRevisionDestino.ERROR_PROVEEDOR
    assert estados["SYN-012"] == EstadoRevisionDestino.COORDENADAS_PROPUESTAS
    assert all(r.requiere_decision_humana for r in resultado.revisiones)


def test_importacion_no_hace_io(tmp_path):
    codigo = "import atlas_core.inteligencia.revision_destinos; import revision_destinos"
    antes = set(tmp_path.iterdir())
    subprocess.run(
        [sys.executable, "-c", codigo], cwd=tmp_path, check=True,
        env={**os.environ, "PYTHONPATH": str(Path.cwd())},
    )
    assert set(tmp_path.iterdir()) == antes


def test_cli_defaults_son_offline_y_sin_cupo():
    args = cli_revision.construir_parser().parse_args(
        ["--entrada", "entrada.json", "--salida", "salida"]
    )
    assert args.permitir_consultas is False
    assert args.max_consultas == 0
    assert args.usar_cache is True
    assert args.solo_cache is False
    assert args.proveedor == "ninguno"


def test_manifiesto_solo_cache_no_declara_consultas_reales():
    resultado = procesar_destinos(
        [],
        configuracion=ConfiguracionRevisionDestinos(
            permitir_consultas=True,
            max_consultas=0,
            solo_cache=True,
            proveedor="respuestas-congeladas",
        ),
        proveedor=ProveedorSintetico({}),
        fecha_evaluacion=FECHA,
    )
    assert resultado.manifiesto["consultas_reales_habilitadas"] is False


def test_cli_no_activa_ors_solo_por_existir_credencial(tmp_path, monkeypatch):
    entrada = tmp_path / "entrada.json"
    escribir_json(entrada, [fila()])
    monkeypatch.setenv("OPENROUTESERVICE_API_KEY", "credencial-ficticia")
    assert cli_revision.main([
        "--entrada", str(entrada),
        "--salida", str(tmp_path / "salida"),
        "--fecha-evaluacion", FECHA.isoformat(),
    ]) == 0
    salida = json.loads(
        (tmp_path / "salida" / "revisiones_destinos.json").read_text("utf-8")
    )
    assert salida[0]["estado_revision"] == "CONSULTA_NO_AUTORIZADA"
    assert salida[0]["consulta_realizada"] is False


def test_cli_ors_exige_autorizacion_y_cupo(tmp_path):
    with pytest.raises(SystemExit, match="ORS requiere"):
        cli_revision.main([
            "--entrada", str(tmp_path / "entrada.json"),
            "--salida", str(tmp_path / "salida"),
            "--proveedor", "ors",
        ])
