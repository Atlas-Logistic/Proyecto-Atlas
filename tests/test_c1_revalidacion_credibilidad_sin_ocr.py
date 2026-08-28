"""Bloque C1 -- `revalidar_credibilidad_campos_sin_ocr`: resincroniza
credibilidad de material/obra_destino/cliente/despachar_a/peso YA
persistidos contra `atlas_core.credibilidad_campos`, sin OCR. Permite
re-evaluar filas procesadas ANTES de que esta capa existiera -- caso
real motivador: 472623/472624 (prueba real Mobile)."""
from __future__ import annotations

import csv

from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_credibilidad_campos_sin_ocr

_MATERIAL_CONTAMINADO_472624 = (
    "Codigo Cliente 0001004274 FECHA DE EMISION 26-08-2026 SODIMAC SA "
    "SENOR(ES) 96.792.430-K RUT VIA AL X MENOR MAI C GIRO AV PDIE "
    "EDUARDO FREI 3092 DIRECCION COMUNA RENCA CIUDAD SANTIAGO "
    "Operacion constituye Venta INDICADOR TRASLADO TRANSPORTE "
    "TRANSPORTES MBI SPA EMPRESA DESCRIPCION CANTIDAD Codigo "
    "HORMIGON 8MM 12M A630-420H (N) 3.025/110002847 B Coladas: 2617677302"
)


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "1.jpeg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "T1", "fecha": "01-08-2026", "indicador_revision": "OK",
        "estado_documental": "OK", "motivos_revision_documento": "",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _leer(ruta):
    return list(csv.DictReader(ruta.open(encoding="utf-8-sig"), delimiter=";"))


def test_fila_ya_ok_con_campos_confiables_no_se_toca():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        dataset = Path(tmp) / "dataset.csv"
        _escribir_csv(dataset, [_fila(
            descripcion_material="HORMIGON 8MM", obra_destino="OBRA CENTRAL",
            cliente="EMPRESA REAL SPA", despachar_a_crudo="AV LIBERTADOR 1000", peso_kg="3025",
        )])
        resultado = revalidar_credibilidad_campos_sin_ocr(ruta_dataset=dataset)
        assert resultado["guias_actualizadas"] == []


def test_material_contaminado_persistido_antes_de_c1_se_marca_ahora():
    """Reconstrucción real 472624: fila ya persistida, procesada ANTES
    de que la capa de credibilidad existiera -- indicador_revision=OK,
    sin ningún motivo. La revalidación la marca sin tocar el valor."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        dataset = Path(tmp) / "dataset.csv"
        _escribir_csv(dataset, [_fila(
            numero_guia="472624", descripcion_material=_MATERIAL_CONTAMINADO_472624,
            obra_destino="TRANSPORTES", cliente="96.792.430-K",
            despachar_a_crudo="SAN", peso_kg="3025",
        )])
        resultado = revalidar_credibilidad_campos_sin_ocr(ruta_dataset=dataset)
        assert resultado["guias_actualizadas"] == ["472624"]

        fila_final = _leer(dataset)[0]
        # Nunca se reemplaza ningún valor documental.
        assert fila_final["descripcion_material"] == _MATERIAL_CONTAMINADO_472624
        assert fila_final["obra_destino"] == "TRANSPORTES"
        assert fila_final["cliente"] == "96.792.430-K"
        assert fila_final["despachar_a_crudo"] == "SAN"
        assert fila_final["peso_kg"] == "3025"
        # Pero sí queda marcada -- nunca "OK" silencioso.
        motivos = fila_final["motivos_revision_documento"]
        assert "MATERIAL_POSIBLEMENTE_CONTAMINADO" in motivos
        assert "OBRA_DESTINO_POSIBLEMENTE_INVALIDA" in motivos
        assert "CLIENTE_POSIBLEMENTE_INVALIDO" in motivos
        assert "DESTINO_FRAGMENTO_TRUNCADO" in motivos
        assert fila_final["indicador_revision"] == "REVISAR"
        assert fila_final["estado_documental"] == "REQUIERE_REVISION"


def test_peso_atipico_persistido_se_marca_pero_nunca_bloquea():
    """Reconstrucción real 472623: 87 kg -- legible, sólo atípico. Se
    conserva el peso, se marca informativo, nunca fuerza revisión por
    sí solo (mismo criterio ya usado para peso/horas, Bloque O1)."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        dataset = Path(tmp) / "dataset.csv"
        _escribir_csv(dataset, [_fila(
            numero_guia="472623", descripcion_material="HORMIGON 1OMM 12M A630-42OH (N)",
            obra_destino="OBRA CENTRAL", cliente="EMPRESA REAL SPA",
            despachar_a_crudo="SAN LUIS 1201 QUILICURA", peso_kg="87",
        )])
        resultado = revalidar_credibilidad_campos_sin_ocr(ruta_dataset=dataset)
        assert resultado["guias_actualizadas"] == ["472623"]

        fila_final = _leer(dataset)[0]
        assert fila_final["peso_kg"] == "87"  # nunca se reemplaza
        assert "PESO_OPERACIONALMENTE_ATIPICO" in fila_final["motivos_revision_documento"]
        assert fila_final["indicador_revision"] == "OK"  # informativo, no bloquea
        assert fila_final["estado_documental"] == "OK"


def test_motivo_ya_presente_no_se_duplica():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        dataset = Path(tmp) / "dataset.csv"
        _escribir_csv(dataset, [_fila(
            descripcion_material=_MATERIAL_CONTAMINADO_472624,
            motivos_revision_documento="MATERIAL_POSIBLEMENTE_CONTAMINADO",
            indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION",
        )])
        resultado = revalidar_credibilidad_campos_sin_ocr(ruta_dataset=dataset)
        assert resultado["guias_actualizadas"] == []
