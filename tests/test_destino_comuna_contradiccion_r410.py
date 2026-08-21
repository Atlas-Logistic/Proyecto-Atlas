"""Bloque F (R4.10): destinos degradados/absurdos -- un resultado
geocodificado que contradice la comuna documental (o quedó a confianza
insuficiente) nunca debe exponerse como si fuera el destino operacional
resuelto. Casos reales que motivaron esto:
- 460807: DESPACHAR A menciona "SAN BERNARDO" dos veces, pero un único
  candidato geocodificado (confianza 0.8) cayó en Angol, La Araucanía.
- 472008: misma obra (AUSIN SAN BERNARDO), el geocodificador degradó el
  resultado a la etiqueta genérica "Chile" (confianza 0.1).
Ambos quedaron correctamente marcados `estado_ruta=REQUIERE_REVISION` sin
km/tiempo, pero la etiqueta rechazada seguía visible en
`direccion_entrega` -- lo que Desktop muestra como "Destino operacional".
"""
import csv

from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_destino_contra_comuna_documental_sin_ocr


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "460807.jpeg", "estado_procesamiento": "OK", "numero_guia": "460807",
        "numero_transporte": "T1", "fecha": "18/08/2026",
        "despachar_a_crudo": "INTERIOR NUEVA O1148 SAN BERNARDO SAN BERNAR",
        "direccion_entrega": "Nueva Rancagua Interior, Angol, AR, Chile",
        "localidad_entrega": "Angol", "region_entrega": "De La Araucania",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "",
        "indicador_revision": "OK",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _leer(ruta):
    with ruta.open(encoding="utf-8-sig") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def test_retira_etiqueta_degradada_que_contradice_la_comuna_documental(tmp_path):
    """Caso real 460807."""
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_csv()])
    resultado = revalidar_destino_contra_comuna_documental_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == ["460807"]
    fila = _leer(dataset)[0]
    assert fila["direccion_entrega"] == ""
    assert fila["localidad_entrega"] == ""
    assert fila["region_entrega"] == ""
    assert fila["distancia_km"] == ""
    assert fila["duracion_min"] == ""
    assert "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL" in fila["motivo_ruta"]
    # Evidencia documental cruda -- nunca se toca.
    assert "SAN BERNARDO" in fila["despachar_a_crudo"]


def test_retira_etiqueta_generica_de_una_ruta_ya_calculada_por_error(tmp_path):
    """Caso más severo aún: una corrida ANTERIOR a este fix llegó a
    calcular una ruta completa hacia el destino contradicho -- también se
    retira, nunca se deja un km/tiempo apuntando a un lugar ya demostrado
    incorrecto."""
    fila = _fila_csv(estado_ruta="RUTA_CALCULADA", distancia_km="650.0", duracion_min="480.0")
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    revalidar_destino_contra_comuna_documental_sin_ocr(ruta_dataset=dataset)
    fila_final = _leer(dataset)[0]
    assert fila_final["estado_ruta"] == "REQUIERE_REVISION"
    assert fila_final["distancia_km"] == ""
    assert fila_final["duracion_min"] == ""


def test_no_toca_fila_sin_contradiccion_demostrable(tmp_path):
    """Control -- destino/localidad ya coherentes con la comuna documental
    (caso real 464959/464960): nunca se toca."""
    fila = _fila_csv(
        numero_guia="464959",
        despachar_a_crudo="MAESTRA LIDIA TORRES 92 SANTIAGO RECOLETA",
        direccion_entrega="Maestra Lidia Torres, Santiago, RM, Chile",
        localidad_entrega="Santiago", region_entrega="Metropolitana",
        estado_ruta="RUTA_CALCULADA", distancia_km="22.9378", duracion_min="32.955",
    )
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    resultado = revalidar_destino_contra_comuna_documental_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == []
    fila_final = _leer(dataset)[0]
    assert fila_final["distancia_km"] == "22.9378"
    assert fila_final["direccion_entrega"] == "Maestra Lidia Torres, Santiago, RM, Chile"


def test_no_toca_fila_sin_localidad_persistida(tmp_path):
    """Control -- sin localidad_entrega persistida (nunca se llegó a
    geocodificar, p. ej. 472037/472018), no hay nada que contrastar."""
    fila = _fila_csv(
        numero_guia="472037", despachar_a_crudo="", direccion_entrega="",
        localidad_entrega="", region_entrega="",
    )
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    resultado = revalidar_destino_contra_comuna_documental_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == []


def test_retira_etiqueta_demasiado_generica_sin_localidad_ni_region(tmp_path):
    """Caso real 472008: el candidato degradado a "Chile" no trae
    localidad ni región (coincidencia a nivel país) -- nunca un destino
    operacional útil, sin importar que tuviera alguna confianza informada."""
    fila = _fila_csv(
        numero_guia="472008", despachar_a_crudo="INTERIOR NUEVA 0114B SAN BERNARDO SAN BERMAR",
        direccion_entrega="Chile", localidad_entrega="", region_entrega="",
    )
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    resultado = revalidar_destino_contra_comuna_documental_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == ["472008"]
    fila_final = _leer(dataset)[0]
    assert fila_final["direccion_entrega"] == ""
    assert fila_final["motivo_ruta"] == "GEOCODIFICACION_DEMASIADO_GENERICA"
    assert fila_final["estado_ruta"] == "REQUIERE_REVISION"


def test_no_rechaza_por_ambiguedad_lexica_del_catalogo_territorial(tmp_path):
    """Control crítico -- caso real 472002: DESPACHAR A "GALVARINO 8501
    QUILICURA" ya estaba correctamente geocodificado a Quilicura (ruta
    real vigente, 13,18 km / 19 min). "Galvarino" es aquí el nombre de la
    CALLE, pero también existe una comuna real llamada Galvarino (La
    Araucanía) -- con DOS comunas reales mencionadas en el mismo texto
    (Galvarino, Quilicura), la evidencia documental es ambigua y NUNCA
    debe usarse para rechazar un destino ya correcto."""
    fila = _fila_csv(
        numero_guia="472002", despachar_a_crudo="GALVARINO 8501 QUILICURA",
        direccion_entrega="Galvarino, Quilicura, RM, Chile",
        localidad_entrega="Quilicura", region_entrega="Metropolitana",
        estado_ruta="RUTA_CALCULADA", distancia_km="13.1788", duracion_min="19.058",
    )
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    resultado = revalidar_destino_contra_comuna_documental_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == []
    fila_final = _leer(dataset)[0]
    assert fila_final["distancia_km"] == "13.1788"
    assert fila_final["direccion_entrega"] == "Galvarino, Quilicura, RM, Chile"


def test_no_retira_generico_si_la_ruta_ya_quedo_calculada(tmp_path):
    """Control -- nunca toca una fila ya `RUTA_CALCULADA`, ni siquiera sin
    localidad/región persistida (puede ser un punto real sin metadata
    administrativa devuelta por el proveedor, no necesariamente degradado)."""
    fila = _fila_csv(
        numero_guia="1", despachar_a_crudo="ALGUN PUNTO REAL SIN COMUNA ETIQUETADA",
        direccion_entrega="Algún Punto Real", localidad_entrega="", region_entrega="",
        estado_ruta="RUTA_CALCULADA", distancia_km="5.0", duracion_min="10.0",
    )
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    resultado = revalidar_destino_contra_comuna_documental_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == []
