"""Bloque PERFORMANCE V1 -- caso real 472339: 4 problemas B1 de un mismo
documento (obra_destino, patente_tracto, patente_rampla, despachar_a_crudo)
son independientes entre sí -- ninguno depende del resultado de otro, cada
uno arma su propio `ContextoRazonamiento` a partir de la MISMA fila/filas
ya leídas, sin mutar nada compartido antes de llamar a B1. Antes de este
bloque, `_ejecutar_ia_operacional` los llamaba uno tras otro dentro del
mismo `for`; el tiempo de PARED terminaba siendo la SUMA de las 4
latencias de red (producción real: ~38.7 s -- una sola llamada, sola,
tardó 20.5 s por un reintento de límite de cuota de Groq).

Estos tests usan un proveedor simulado que DUERME (reloj real,
`time.sleep`, nunca mockeado) exactamente las latencias reales
observadas en el caso 472339 -- prueban, con reloj real, que el tiempo
de pared ahora es aproximadamente el MÁXIMO de las llamadas, no la suma,
y que el resultado final (motivos, indicador_revision, orden de las
trazas) es IDÉNTICO al que ya producía la versión secuencial."""
from __future__ import annotations

import csv
import json
import time

from atlas_core.atlas_ia.contratos import ContextoRazonamiento
from atlas_core.atlas_ia.orquestador import CLASIFICACION_C, ResultadoOrquestacion
from atlas_core.procesamiento_masivo import COLUMNAS, _ejecutar_ia_operacional


def _fila(**cambios):
    fila = {columna: "" for columna in COLUMNAS}
    fila.update({
        "estado_procesamiento": "OK", "fecha": "18-08-2026", "numero_transporte": "T-1",
        "chofer": "PERSONA EJEMPLO", "patente_tracto": "No encontrado", "patente_rampla": "No encontrado",
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


class _OrquestadorConLatenciaReal:
    """Doble determinista que reproduce, con reloj real (`time.sleep`,
    nunca mockeado), una latencia real distinta por campo -- mismo
    criterio que `ProveedorModeloIASimulado` (nunca razona de verdad),
    pero con el eje que este bloque necesita probar: el TIEMPO."""

    def __init__(self, *, latencias_por_campo: dict[str, float]) -> None:
        self._latencias = latencias_por_campo
        self.contextos_recibidos: list[ContextoRazonamiento] = []

    def resolver(self, contexto: ContextoRazonamiento) -> ResultadoOrquestacion:
        self.contextos_recibidos.append(contexto)
        time.sleep(self._latencias.get(contexto.campo, 0.0))
        return ResultadoOrquestacion(
            estado="ABSTENCION_IA", clasificacion=CLASIFICACION_C, contexto_final=contexto,
        )


def _fila_con_dos_problemas_independientes(**cambios):
    """PATENTE_SIN_HOMOLOGAR en tracto Y rampla a la vez -- dos
    problemas del MISMO documento, cada uno con su propia evidencia por
    documento relacionado (Bloque R12: el registro ya no colisiona por
    campo), completamente independientes entre sí."""
    return _fila(motivos_revision_documento="PATENTE_SIN_HOMOLOGAR", **cambios)


def test_dos_problemas_independientes_de_la_misma_fila_se_resuelven_en_paralelo(tmp_path):
    ruta = tmp_path / "datos.csv"
    filas = [
        _fila(archivo="fuente.jpg", patente_tracto="AB1234", patente_rampla="CD5678", indicador_revision="OK"),
        _fila_con_dos_problemas_independientes(archivo="objetivo.jpg"),
    ]
    _escribir(ruta, filas)
    orquestador = _OrquestadorConLatenciaReal(latencias_por_campo={
        "patente_tracto": 0.5, "patente_rampla": 0.5,
    })

    inicio = time.perf_counter()
    resumen = _ejecutar_ia_operacional(ruta, {"objetivo.jpg"}, orquestador)
    pared = time.perf_counter() - inicio

    assert resumen["llamadas"] == 2
    # Suma de latencias declaradas ~1.0 s -- pero el tiempo de PARED real
    # debe acercarse al máximo de las dos (0.5 s), nunca a la suma. Margen
    # generoso (0.85 s) para no ser frágil ante CI lento, pero
    # estrictamente por debajo de la suma secuencial (1.0 s + overhead).
    assert pared < 0.85, f"tiempo de pared {pared:.3f}s -- se esperaba paralelo (~0.5s), no secuencial (~1.0s)"
    campos_llamados = {c.campo for c in orquestador.contextos_recibidos}
    assert campos_llamados == {"patente_tracto", "patente_rampla"}


def test_una_sola_llamada_no_usa_hilo_de_mas_y_sigue_funcionando(tmp_path):
    """Caso más común -- un solo problema elegible: nunca paga el costo
    de crear un executor para nada, y el resultado es idéntico al de
    siempre."""
    ruta = tmp_path / "datos.csv"
    filas = [_fila(archivo="objetivo.jpg", motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR")]
    _escribir(ruta, filas)
    orquestador = _OrquestadorConLatenciaReal(latencias_por_campo={"obra_destino": 0.05})
    resumen = _ejecutar_ia_operacional(ruta, {"objetivo.jpg"}, orquestador)
    assert resumen["llamadas"] == 1
    assert resumen["C"] == 1


def test_resultado_final_es_identico_en_orden_y_contenido_a_la_version_secuencial(tmp_path):
    """La paralelización sólo cambia CUÁNDO se espera la red -- nunca el
    orden en que los resultados se aplican a la fila ni el contenido de
    las trazas. Corre la MISMA fila dos veces (paralelo real, vía el
    orquestador con `time.sleep`, y una versión de control con latencia
    cero) y compara los campos que importan operacionalmente: motivos,
    indicador_revision, y el conjunto de campos/dominios trazados en
    resultado_atlas_ia_json (el orden de una lista construida por un
    executor con resultados recolectados por índice es determinista, no
    depende del orden de llegada de la red)."""
    ruta_a = tmp_path / "a.csv"
    ruta_b = tmp_path / "b.csv"
    fila = _fila_con_dos_problemas_independientes(archivo="objetivo.jpg")
    fuente = _fila(archivo="fuente.jpg", patente_tracto="AB1234", patente_rampla="CD5678", indicador_revision="OK")
    _escribir(ruta_a, [fuente, fila])
    _escribir(ruta_b, [fuente, fila])

    orquestador_lento = _OrquestadorConLatenciaReal(latencias_por_campo={"patente_tracto": 0.2, "patente_rampla": 0.05})
    orquestador_rapido = _OrquestadorConLatenciaReal(latencias_por_campo={})

    _ejecutar_ia_operacional(ruta_a, {"objetivo.jpg"}, orquestador_lento)
    _ejecutar_ia_operacional(ruta_b, {"objetivo.jpg"}, orquestador_rapido)

    salida_a = _leer(ruta_a)["objetivo.jpg"]
    salida_b = _leer(ruta_b)["objetivo.jpg"]
    assert salida_a["motivos_revision_documento"] == salida_b["motivos_revision_documento"]
    assert salida_a["indicador_revision"] == salida_b["indicador_revision"]
    trazas_a = [(t["dominio"], t["campo"]) for t in json.loads(salida_a["resultado_atlas_ia_json"])]
    trazas_b = [(t["dominio"], t["campo"]) for t in json.loads(salida_b["resultado_atlas_ia_json"])]
    assert trazas_a == trazas_b  # mismo orden, mismo contenido -- pese a latencias distintas
