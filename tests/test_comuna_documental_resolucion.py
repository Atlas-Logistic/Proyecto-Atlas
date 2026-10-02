"""Bloque COMUNA DOCUMENTAL EN LA RESOLUCIÓN -- caso real 475208/475209
(transporte 0000361856). El documento dice "TENIENTE BERGMAN 4933 QUINTA
NORMAL"; Javier registró después dirección "TENIENTE BERGMAN 4933" + comuna
"QUINTA NORMAL". Candidatos reales (caché de geocodificación de G:):

- principal (ORS): 4 x "Pasaje Parque Quinta Normal, Puente bajo" + 1 x
  "Quinta Normal, Antofagasta" -> ninguno es la calle/número/comuna del
  documento, pero se contaban como MULTIPLES_UBICACIONES_DISPERSAS(5);
- respaldo (Nominatim): "Teniente Bergman, Quinta Normal" sin número.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_ruta_sin_destino_calculado_sin_ocr
from atlas_core.rutas.destino_entrega import (
    ESTADO_RESUELTO, METODO_CANDIDATOS_CONTRADICEN_DOCUMENTO, resolver_destino_entrega,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)

DOCUMENTAL = "TENIENTE BERGMAN 4933 QUINTA NORMAL"
REGISTRADA = "TENIENTE BERGMAN 4933"

ORS_REAL = ResultadoGeocodificacion(EstadoRuta.RESULTADO_AMBIGUO, tuple(
    CandidatoGeocodificacion(Coordenadas(-70.58 + i * 0.001, -33.61), f"{n} Pasaje Parque Quinta Normal, Puente bajo, RM, Chile",
                             1.0, "Puente bajo", "Metropolitana")
    for i, n in enumerate(("3797", "3705", "3704", "3796"))
) + (
    CandidatoGeocodificacion(Coordenadas(-70.39, -23.64), "Quinta Normal, Antofagasta, AN, Chile", 0.8,
                             "Antofagasta", "De Antofagasta", "CL", "02101", "02"),
))
CALLE_EN_QN = CandidatoGeocodificacion(Coordenadas(-70.7031, -33.4312), "Teniente Bergman", 0.2,
                                       "Quinta Normal", "Metropolitana", "CL", "13126", "13")
NOMINATIM_REAL = ResultadoGeocodificacion(EstadoRuta.RESULTADO_AMBIGUO, (CALLE_EN_QN, CALLE_EN_QN))


@dataclass
class Geocodificador:
    """Doble determinista: consulta exacta -> resultado; registra consultas."""

    respuestas: dict[str, ResultadoGeocodificacion] = field(default_factory=dict)
    consultas: list[str] = field(default_factory=list)
    nombre: str = "doble"
    version: str = "1"

    def geocodificar(self, direccion: str) -> ResultadoGeocodificacion:
        self.consultas.append(direccion)
        return self.respuestas.get(direccion, ResultadoGeocodificacion(EstadoRuta.DIRECCION_NO_ENCONTRADA))

    def geocodificar_estructurado(self, direccion, contexto=None):
        return self.geocodificar(direccion)

    def calcular_ruta(self, origen, destino, perfil):
        return ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 21.5, 30.0, "SINTETICO")


def _caso_real(texto_consulta_respaldo: str) -> tuple[Geocodificador, Geocodificador]:
    principal = Geocodificador({
        f"{DOCUMENTAL}, Chile": ORS_REAL,
        f"{REGISTRADA} QUINTA NORMAL, Chile": ORS_REAL,
    })
    respaldo = Geocodificador({f"{texto_consulta_respaldo}, Chile": NOMINATIM_REAL})
    return principal, respaldo


# --- resolución (unidad) ---

def test_475208_candidatos_que_contradicen_el_documento_no_son_ubicaciones_posibles():
    principal, respaldo = _caso_real(DOCUMENTAL)

    resultado = resolver_destino_entrega(DOCUMENTAL, principal, proveedor_geocodificacion_fallback=respaldo)

    assert not resultado.motivo.startswith("MULTIPLES_UBICACIONES_DISPERSAS")
    assert resultado.motivo == "CONFIANZA_INSUFICIENTE"  # calle en Quinta Normal, número sin confirmar
    assert resultado.estado != ESTADO_RESUELTO
    assert resultado.localidad == "Quinta Normal"
    assert resultado.metodo_confirmacion == METODO_CANDIDATOS_CONTRADICEN_DOCUMENTO
    assert resultado.despachar_a_crudo == DOCUMENTAL  # evidencia original intacta


def test_475208_el_respaldo_recibe_la_comuna_conocida_cuando_el_texto_no_la_trae():
    principal, respaldo = _caso_real(f"{REGISTRADA} QUINTA NORMAL")

    resultado = resolver_destino_entrega(
        REGISTRADA, principal, proveedor_geocodificacion_fallback=respaldo,
        comuna_territorial_conocida="QUINTA NORMAL",
    )

    assert respaldo.consultas and all("QUINTA NORMAL" in c for c in respaldo.consultas)
    assert resultado.motivo == "CONFIANZA_INSUFICIENTE"
    assert resultado.localidad == "Quinta Normal"


def test_numero_exacto_en_la_comuna_documental_resuelve_por_el_camino_normal():
    principal, _ = _caso_real(DOCUMENTAL)
    exacto = CandidatoGeocodificacion(Coordenadas(-70.7032, -33.4312), "4933 Teniente Bergman, Quinta Normal", 0.9,
                                      "Quinta Normal", "Metropolitana", "CL", "13126", "13")
    respaldo = Geocodificador({f"{DOCUMENTAL}, Chile": ResultadoGeocodificacion(EstadoRuta.REQUIERE_REVISION, (exacto,))})

    resultado = resolver_destino_entrega(DOCUMENTAL, principal, proveedor_geocodificacion_fallback=respaldo)

    assert resultado.estado == ESTADO_RESUELTO
    assert resultado.localidad == "Quinta Normal"
    assert resultado.coordenadas == exacto.coordenadas


def test_control_sin_comuna_documental_ni_conocida_comportamiento_identico():
    principal = Geocodificador({f"{REGISTRADA}, Chile": ORS_REAL})
    respaldo = Geocodificador({f"{REGISTRADA}, Chile": NOMINATIM_REAL})

    resultado = resolver_destino_entrega(REGISTRADA, principal, proveedor_geocodificacion_fallback=respaldo)

    assert resultado.motivo == "MULTIPLES_UBICACIONES_DISPERSAS(5)"
    assert resultado.metodo_confirmacion == ""


def test_control_ambiguedad_real_dentro_de_la_comuna_sigue_absteniendose():
    """Dos puntos lejanos, ambos coherentes con calle/número/comuna: es
    ambigüedad real -- nunca se elige uno."""
    a = CandidatoGeocodificacion(Coordenadas(-70.70, -33.43), "4933 Teniente Bergman, Quinta Normal", 0.9,
                                 "Quinta Normal", "Metropolitana", "CL", "13126", "13")
    b = CandidatoGeocodificacion(Coordenadas(-70.74, -33.45), "4933 Teniente Bergman Norte, Quinta Normal", 0.9,
                                 "Quinta Normal", "Metropolitana", "CL", "13126", "13")
    principal = Geocodificador({f"{DOCUMENTAL}, Chile": ResultadoGeocodificacion(EstadoRuta.RESULTADO_AMBIGUO, (a, b))})

    resultado = resolver_destino_entrega(DOCUMENTAL, principal, proveedor_geocodificacion_fallback=Geocodificador())

    assert resultado.motivo == "MULTIPLES_UBICACIONES_DISPERSAS(2)"
    assert resultado.estado != ESTADO_RESUELTO


def test_control_calle_en_otra_comuna_no_se_acepta_ni_se_oculta():
    """Si la calle sólo aparece en una comuna distinta de la documental,
    nunca se resuelve ahí: se abstiene sin exponer esa comuna."""
    principal, _ = _caso_real(DOCUMENTAL)
    otra = CandidatoGeocodificacion(Coordenadas(-70.72, -33.44), "Teniente Bergman", 0.2,
                                    "Lo Prado", "Metropolitana", "CL", "13117", "13")
    respaldo = Geocodificador({f"{DOCUMENTAL}, Chile": ResultadoGeocodificacion(EstadoRuta.RESULTADO_AMBIGUO, (otra, otra))})

    resultado = resolver_destino_entrega(DOCUMENTAL, principal, proveedor_geocodificacion_fallback=respaldo)

    assert resultado.estado != ESTADO_RESUELTO
    assert resultado.localidad != "Lo Prado"
    assert resultado.motivo == "GEOCODIFICACION_DIRECCION_NO_ENCONTRADA"


# --- revalidación (flujo normal) ---

def _operacion(tmp_path, *, direccion_ledger=REGISTRADA, motivo="MULTIPLES_UBICACIONES_DISPERSAS(5)"):
    carpeta = tmp_path / "catalogos"; carpeta.mkdir()
    planta = CatalogoPlantas(carpeta / "plantas.json").crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST", direccion="RUTA 5", comuna="COLINA", region="RM",
        latitud=-33.201, longitud=-70.669, estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    actual = tmp_path / "operacion" / "actual"; actual.mkdir(parents=True)
    filas = []
    for guia in ("475208", "475209"):
        fila = {c: "" for c in COLUMNAS}
        fila.update(
            archivo=f"mobile/{guia}/original.jpg", numero_guia=guia, numero_transporte="0000361856",
            estado_procesamiento="OK", despachar_a_crudo=REGISTRADA, localidad_entrega="QUINTA NORMAL",
            planta_origen_id=planta.planta_id, planta_origen_nombre=planta.nombre,
            origen_determinado_por="MOBILE", evidencia_origen="MOBILE_INFORMADO",
            estado_ruta="REQUIERE_REVISION", motivo_ruta=motivo, indicador_revision="OK",
            obra_destino="COM Y END DE ALAMBRES SPA",
        )
        filas.append(fila)
    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";"); escritor.writeheader(); escritor.writerows(filas)
    (actual / "decisiones_aplicadas.json").write_text(json.dumps({"aplicaciones": [
        {"tipo": "DESTINO_NO_RESUELTO", "accion": "REGISTRAR_DIRECCION", "actor": "JAVIER_DESKTOP",
         "direccion_manual": direccion_ledger, "comuna_manual": "QUINTA NORMAL",
         "valor_documental_anterior": DOCUMENTAL,
         "documento": {"archivo": f"mobile/{g}/original.jpg", "numero_guia": g, "numero_transporte": "0000361856"}}
        for g in ("475208", "475209")
    ]}), encoding="utf-8")
    return dataset, carpeta


def _leer(dataset):
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        return {f["numero_guia"]: f for f in csv.DictReader(archivo, delimiter=";")}


def test_475208_reintento_usa_la_comuna_humana_del_ledger_y_corrige_el_motivo(tmp_path):
    dataset, carpeta = _operacion(tmp_path)
    principal, respaldo = _caso_real(f"{REGISTRADA} QUINTA NORMAL")

    resultado = revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=principal, proveedor_rutas_fallback=respaldo,
    )

    assert sorted(resultado["guias_actualizadas"]) == ["475208", "475209"]
    assert any("QUINTA NORMAL" in c for c in principal.consultas)
    for fila in _leer(dataset).values():
        assert fila["motivo_ruta"] == "CONFIANZA_INSUFICIENTE"
        assert fila["localidad_entrega"] == "QUINTA NORMAL"  # la comuna humana nunca se borra
        assert fila["despachar_a_crudo"] == REGISTRADA
        assert fila["distancia_km"] == ""  # sin número confirmado no hay ruta inventada


def test_reintento_es_idempotente(tmp_path):
    dataset, carpeta = _operacion(tmp_path)
    principal, respaldo = _caso_real(f"{REGISTRADA} QUINTA NORMAL")
    revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=principal, proveedor_rutas_fallback=respaldo,
    )
    antes = dataset.read_bytes()

    segundo = revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=principal, proveedor_rutas_fallback=respaldo,
    )

    assert segundo["guias_actualizadas"] == []
    assert dataset.read_bytes() == antes


def test_comuna_del_ledger_no_acompana_si_la_direccion_cambio_despues(tmp_path):
    dataset, carpeta = _operacion(tmp_path, direccion_ledger="OTRA CALLE 100")
    principal = Geocodificador({f"{REGISTRADA}, Chile": ORS_REAL})

    revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=principal,
        proveedor_rutas_fallback=Geocodificador(),
    )

    assert all("QUINTA NORMAL" not in c for c in principal.consultas)
    assert {f["motivo_ruta"] for f in _leer(dataset).values()} == {"MULTIPLES_UBICACIONES_DISPERSAS(5)"}
