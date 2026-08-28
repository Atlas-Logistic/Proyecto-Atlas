"""Bloque SIMPLIFICAR/AVANZAR A B1 -- vertical slice de B1 como
investigador operacional para ORIGEN, cuando la evidencia DIRECTA (GPS
contemporáneo, Mobile) no alcanzó (ver `resolver_planta_origen_gps` y
`atlas_core.rutas.origen_documental`, membrete inválido como evidencia).

Caso real motivador: 472647/472648 (transporte 0000355231) -- sin GPS
OneLogis útil, sin Mobile útil, membrete inválido. Estos tests verifican
la CAPA DE HERRAMIENTAS/CICLO ITERATIVO con un proveedor simulado
(determinista, nunca red real, nunca mide capacidad de razonamiento) --
la ejecución real contra Anthropic se reporta aparte, fuera de la suite."""
from __future__ import annotations

from atlas_core.atlas_ia.contratos import (
    ContextoRazonamiento,
    HipotesisIA,
    RESULTADO_HIPOTESIS_ABSTENCION,
    RESULTADO_HIPOTESIS_PROPUESTA,
    RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA,
    calcular_hipotesis_id,
)
from atlas_core.atlas_ia.herramientas import (
    herramienta_evidencia_catalogo_plantas,
    herramienta_evidencia_historial_origen,
)
from atlas_core.atlas_ia.orquestador import (
    ABSTENCION_IA,
    CLASIFICACION_B,
    CLASIFICACION_C,
    RESUELTO_POR_IA,
    OrquestadorAtlasIA,
)
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad


def _plantas(tmp_path):
    repo = CatalogoPlantas(tmp_path / "plantas.json")
    repo.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="TEST",
        estado_calidad=EstadoCalidad.CONFIRMADA, categorias_permitidas=("ANGULOS",),
    )
    repo.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        estado_calidad=EstadoCalidad.CONFIRMADA, categorias_permitidas=("BARRAS", "ROLLOS"),
    )
    return repo.listar()


def _filas_historial():
    """10 guías con origen ya confirmado de forma independiente (GPS/
    Mobile/humana) -- TODAS BARRAS a AZA COLINA -- nunca un patrón
    precalculado: es la materia prima cruda que B1 debe leer y comparar
    por sí mismo contra la guía en investigación."""
    return [
        {
            "numero_guia": str(472000 + i), "numero_transporte": f"000035{i:04d}",
            "fecha": "20-08-2026", "patente_tracto": "BDFG50", "chofer": "CHOFER PRUEBA",
            "cliente": "CLIENTE PRUEBA", "obra_destino": "OBRA PRUEBA",
            "tipo_carga": "BARRAS", "descripcion_material": "B HORMIGON 12MM",
            "origen_determinado_por": "TELEMETRIA_GPS", "planta_origen_nombre": "AZA COLINA",
        }
        for i in range(1, 11)
    ]


def _contexto_origen_472647(**cambios):
    datos: dict[str, object] = {
        "campo": "planta_origen", "valor_documental": "",
        "rut_chofer": "12.345.678-9", "numero_guia": "472647",
        "numero_transporte": "0000355231",
        "evidencias": (),
        "resultado_motor": "REQUIERE_REVISION", "explicacion_motor": "ENCABEZADO_GUIA_NO_CONFIABLE",
        "identidad_operacional": {
            "patente_tracto": "TVKT21", "chofer": "CARLOS FARIAS", "cliente": "SALOMON SACK SA",
            "obra_destino": "OBRA X", "tipo_carga": "BARRAS", "descripcion_material": "B ANGULO",
            "fecha": "26-08-2026",
        },
        "herramientas_disponibles": ("EVIDENCIA_HISTORIAL_ORIGEN", "EVIDENCIA_CATALOGO_PLANTAS"),
        "restricciones_dominio": ("NO_INVENTAR_DATOS", "NO_ESCRIBIR_CATALOGOS", "MAXIMO_RONDAS_B1"),
    }
    datos.update(cambios)
    return ContextoRazonamiento(**datos)


# ============================================================
# 1. La herramienta de historial expone hechos crudos, con procedencia
# ============================================================


def test_herramienta_historial_origen_expone_evidencia_con_procedencia():
    herramienta = herramienta_evidencia_historial_origen(_filas_historial())
    evidencias = herramienta.consultar(_contexto_origen_472647())
    assert len(evidencias) == 10
    for evidencia in evidencias:
        assert evidencia.valor == "AZA COLINA"  # única forma de poder proponerla (ver validadores)
        assert evidencia.tipo_fuente == "HISTORICO"
        assert evidencia.procedencia  # trazable a qué función la produjo
        # Datos crudos (guía, patente, tipo de carga) -- nunca una
        # conclusión de correlación ya calculada.
        assert any(r.startswith("tipo_carga=") for r in evidencia.referencias_fuente)
        assert any(r.startswith("guia=") for r in evidencia.referencias_fuente)


def test_herramienta_historial_origen_nunca_incluye_la_propia_guia_en_investigacion():
    filas = _filas_historial() + [{
        "numero_guia": "472647", "origen_determinado_por": "TELEMETRIA_GPS",
        "planta_origen_nombre": "AZA RENCA",
    }]
    herramienta = herramienta_evidencia_historial_origen(filas)
    evidencias = herramienta.consultar(_contexto_origen_472647())
    assert all(e.identificador != "historial_origen:472647" for e in evidencias)


def test_herramienta_catalogo_plantas_expone_categorias_como_hecho_no_como_regla_aplicada(tmp_path):
    herramienta = herramienta_evidencia_catalogo_plantas(_plantas(tmp_path))
    evidencias = herramienta.consultar(_contexto_origen_472647())
    valores = {e.valor: e for e in evidencias}
    assert set(valores) == {"AZA RENCA", "AZA COLINA"}
    assert "categoria_permitida=ANGULOS" in valores["AZA RENCA"].a_favor
    assert "categoria_permitida=BARRAS" in valores["AZA COLINA"].a_favor


# ============================================================
# 2. Ciclo iterativo real: B1 investiga historial, luego catálogo,
#    y concluye con evidencia convergente -- caso real 472647/472648
#    resuelto (BARRAS + historial 100% COLINA + RENCA excluida por
#    categoría) -- SIN que se le haya dicho la respuesta.
# ============================================================


class _ProveedorInvestigadorConvergente:
    """Guion determinista de 3 rondas -- nunca simula razonamiento real,
    sólo prueba que el ORQUESTADOR ejecuta el ciclo correctamente
    (herramienta -> evidencia -> herramienta -> evidencia -> conclusión)."""

    def __init__(self) -> None:
        self.ronda = 0

    def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:
        self.ronda += 1
        if self.ronda == 1:
            return HipotesisIA(
                hipotesis_id=calcular_hipotesis_id(contexto, ""), campo=contexto.campo,
                valor_observado=contexto.valor_documental, valor_propuesto="",
                resultado=RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA,
                herramienta_faltante="EVIDENCIA_HISTORIAL_ORIGEN",
                explicacion="Sin GPS ni Mobile útiles; reviso historial de origen confirmado.",
            )
        if self.ronda == 2:
            return HipotesisIA(
                hipotesis_id=calcular_hipotesis_id(contexto, ""), campo=contexto.campo,
                valor_observado=contexto.valor_documental, valor_propuesto="",
                resultado=RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA,
                herramienta_faltante="EVIDENCIA_CATALOGO_PLANTAS",
                explicacion="Historial converge en AZA COLINA para BARRAS; reviso catálogo para contrastar.",
            )
        return HipotesisIA(
            hipotesis_id=calcular_hipotesis_id(contexto, "AZA COLINA"), campo=contexto.campo,
            valor_observado=contexto.valor_documental, valor_propuesto="AZA COLINA",
            resultado=RESULTADO_HIPOTESIS_PROPUESTA,
            evidencia_usada=tuple(e.identificador for e in contexto.evidencias),
            explicacion=(
                "10/10 guías BARRAS con origen confirmado independientemente son AZA COLINA; "
                "AZA RENCA sólo admite ANGULOS según el catálogo -- incompatible con esta carga (BARRAS)."
            ),
        )


def test_b1_investiga_historial_y_catalogo_y_concluye_con_evidencia_convergente(tmp_path):
    herramientas = {
        "EVIDENCIA_HISTORIAL_ORIGEN": herramienta_evidencia_historial_origen(_filas_historial()),
        "EVIDENCIA_CATALOGO_PLANTAS": herramienta_evidencia_catalogo_plantas(_plantas(tmp_path)),
    }
    proveedor = _ProveedorInvestigadorConvergente()
    resultado = OrquestadorAtlasIA(proveedor=proveedor, herramientas=herramientas).resolver(
        _contexto_origen_472647()
    )
    assert resultado.estado == RESUELTO_POR_IA
    assert resultado.clasificacion == CLASIFICACION_B  # nunca autonomía A -- sólo asiste la decisión humana
    assert resultado.hipotesis and resultado.hipotesis.valor_propuesto == "AZA COLINA"
    assert resultado.herramientas_usadas == ("EVIDENCIA_HISTORIAL_ORIGEN", "EVIDENCIA_CATALOGO_PLANTAS")
    # Traza auditable: 3 rondas, cada una con su propia hipótesis
    # estructurada -- nunca sólo la conclusión final.
    assert resultado.rondas == 3
    assert len(resultado.traza) == 3
    assert resultado.traza[0]["hipotesis"]["herramienta_faltante"] == "EVIDENCIA_HISTORIAL_ORIGEN"
    assert resultado.traza[1]["hipotesis"]["herramienta_faltante"] == "EVIDENCIA_CATALOGO_PLANTAS"
    assert resultado.traza[2]["hipotesis"]["resultado"] == RESULTADO_HIPOTESIS_PROPUESTA
    assert len(resultado.traza[0]["evidencia_nueva"]) == 10
    assert len(resultado.traza[1]["evidencia_nueva"]) == 2


# ============================================================
# 3. Sin evidencia convergente -- B1 investiga en serio y concluye
#    EVIDENCIA_INSUFICIENTE, nunca inventa ni fuerza una respuesta.
# ============================================================


class _ProveedorInvestigadorSinConvergencia:
    def __init__(self) -> None:
        self.ronda = 0

    def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:
        self.ronda += 1
        if self.ronda == 1:
            return HipotesisIA(
                hipotesis_id=calcular_hipotesis_id(contexto, ""), campo=contexto.campo,
                valor_observado=contexto.valor_documental, valor_propuesto="",
                resultado=RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA,
                herramienta_faltante="EVIDENCIA_HISTORIAL_ORIGEN",
            )
        return HipotesisIA(
            hipotesis_id=calcular_hipotesis_id(contexto, ""), campo=contexto.campo,
            valor_observado=contexto.valor_documental, valor_propuesto="",
            resultado=RESULTADO_HIPOTESIS_ABSTENCION,
            explicacion="Historial disponible no menciona este material/chofer/vehículo; sin convergencia real.",
        )


def test_b1_sin_evidencia_convergente_concluye_abstencion_nunca_inventa(tmp_path):
    herramientas = {"EVIDENCIA_HISTORIAL_ORIGEN": herramienta_evidencia_historial_origen(())}
    resultado = OrquestadorAtlasIA(
        proveedor=_ProveedorInvestigadorSinConvergencia(), herramientas=herramientas,
    ).resolver(_contexto_origen_472647(herramientas_disponibles=("EVIDENCIA_HISTORIAL_ORIGEN",)))
    assert resultado.estado == ABSTENCION_IA
    assert resultado.clasificacion == CLASIFICACION_C
    assert resultado.hipotesis and resultado.hipotesis.valor_propuesto == ""
