"""Contrato del expediente B1: evidencia antes que similitud o historial."""
import csv
import hashlib
from types import SimpleNamespace

from atlas_core.atlas_ia.investigacion_revision import _evaluar_propuesta, investigar_revision


def _resultado(valor="", aceptada=True):
    return SimpleNamespace(
        estado="RESUELTO_POR_IA" if valor else "ABSTENCION_IA",
        validacion=SimpleNamespace(aceptada=aceptada),
        hipotesis=SimpleNamespace(valor_propuesto=valor, a_dict=lambda: {"valor_propuesto": valor}) if valor else None,
    )


def _historico(valor, identificador="h1"):
    return {"identificador": identificador, "valor": valor, "tipo_fuente": "HISTORICO"}


def test_evidencia_convergente_y_trazable():
    r = _evaluar_propuesta(_resultado("Av. Norte 123"), "AV NORTE 123", [_historico("Av. Norte 123")])
    assert r["propuesta"] == "Av. Norte 123"
    assert r["nivel"] == "DOCUMENTAL_CONVERGENTE"
    assert r["contradicciones"] == []
    assert r["inferencia"]["valor_propuesto"] == "Av. Norte 123"


def test_historial_contradictorio_no_anula_documento():
    r = _evaluar_propuesta(_resultado("Sur 100"), "Norte 123", [_historico("Sur 100")])
    assert r["propuesta"] == ""
    assert r["nivel"] == "CONTRADICCION_DOCUMENTAL"
    assert r["contradicciones"][0]["evidencia_historica"] == "h1"


def test_dos_candidatos_y_ausencia_de_evidencia_abstienen():
    dos = _evaluar_propuesta(_resultado("A"), "", [_historico("A"), _historico("B", "h2")])
    vacio = _evaluar_propuesta(None, "", [])
    assert dos["propuesta"] == vacio["propuesta"] == ""
    assert "Dos o más" in dos["razon"]
    assert dos["razon"] and vacio["razon"]


def test_ocr_contaminado_repetido_no_es_solucion():
    r = _evaluar_propuesta(_resultado("J61 TALCAHUANO"), "J61 TALCAHUANO", [],
                          "J61 TALCAHUANO", "DESTINO_CONTAMINADO_POR_OTRA_SECCION")
    assert r["propuesta"] == ""


def test_propuesta_no_validada_abstiene():
    r = _evaluar_propuesta(_resultado("A", aceptada=False), "", [_historico("A")])
    assert r["propuesta"] == ""


def test_investigacion_idempotente_sin_escrituras_productivas(tmp_path, monkeypatch):
    actual = tmp_path / "operacion" / "actual"
    actual.mkdir(parents=True)
    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open("w", encoding="utf-8-sig", newline="") as flujo:
        escritor = csv.DictWriter(flujo, fieldnames=["numero_guia", "numero_transporte", "archivo",
            "motivos_revision_documento", "despachar_a_crudo", "obra_destino", "cliente", "metodos_recuperacion_documento"], delimiter=";")
        escritor.writeheader()
        escritor.writerow({"numero_guia": "1", "numero_transporte": "2", "archivo": "prueba.jpg",
            "motivos_revision_documento": "DESTINO_CONTAMINADO_POR_OTRA_SECCION",
            "despachar_a_crudo": "OCR MALO", "obra_destino": "OBRA", "cliente": "CLIENTE",
            "metodos_recuperacion_documento": "GEOMETRICO"})
    catalogo = tmp_path / "catalogos_privados" / "obras_destinos.json"
    catalogo.parent.mkdir()
    catalogo.write_text("{}", encoding="utf-8")
    ledger = actual / "decisiones_aplicadas.json"
    ledger.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("atlas_core.atlas_ia.investigacion_revision._lectura_original",
        lambda *args: {"ruta": "original.jpg", "sha256": "abc", "lineas": ["DESPACHAR A", "CALLE REAL 1"],
                      "destino_geometrico": "CALLE REAL 1", "fuente": "test", "error": ""})

    class B1:
        def resolver(self, contexto):
            return SimpleNamespace(contexto_final=contexto, hipotesis=None, estado="ABSTENCION_IA",
                validacion=None, a_dict=lambda: {"estado": "ABSTENCION_IA"})

    antes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (dataset, catalogo, ledger)}
    primero = investigar_revision("1", raiz_atlas=tmp_path, orquestador=B1(), investigar_externo=False)
    segundo = investigar_revision("1", raiz_atlas=tmp_path, orquestador=B1(), investigar_externo=False)
    assert primero == segundo
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in antes} == antes
    assert primero["escrituras_productivas"] == 0
    assert primero["expedientes"][0]["HECHOS_DOCUMENTALES"]["destino_original"] == "CALLE REAL 1"
