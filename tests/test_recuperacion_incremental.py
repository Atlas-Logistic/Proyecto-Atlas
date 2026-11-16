"""P0 recuperación incremental de campos ausentes (datos sintéticos)."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from atlas_core import recuperacion_incremental as ri
from atlas_core.procesamiento_masivo import COLUMNAS

RUT_LUIS = "14293816-2"
RUT_RODRIGO = "15454297-3"


def _vehiculo(patente, tipo="TRACTO"):
    evidencia = {"tipo": "CONFIRMACION_HUMANA", "identificador_fuente": "TEST", "referencia_hash": "",
                 "campos_observados": {"patente": patente, "tipo": tipo, "observacion": ""},
                 "fecha": "2026-01-01T00:00:00+00:00", "actor_proceso": "TEST", "resultado": "SOPORTA"}
    return {"vehiculo_id": patente, "patente_canonica": patente, "tipo": tipo, "estado_calidad": "CONFIRMADO",
            "estado_vigencia": "ACTIVO", "aliases": [], "evidencias": [evidencia],
            "procedencia": "CONFIRMACION_HUMANA", "confirmado_por": "TEST",
            "fecha_confirmacion": "2026-01-01T00:00:00+00:00", "observaciones": "",
            "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00"}


def _fila(envio, guia, **extra):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": f"mobile/{envio}/original.jpg", "estado_procesamiento": "OK", "numero_guia": guia,
        "numero_transporte": f"000037{guia[-4:]}", "fecha": "07-10-2026", "chofer": "LUIS VARAS",
        "rut_chofer": RUT_LUIS, "patente_tracto": "DD2494", "patente_rampla": "JB8529",
        "descripcion_material": "B HORMIGON 12MM 6M A630-420H (N)", "planta_origen_id": "planta-1",
        "estado_ruta": "RUTA_CALCULADA", "distancia_km": "34.8", "indicador_revision": "OK",
        "motivos_revision_documento": "", "metricas_procesamiento_json": "{}",
        "fecha_ingesta_utc": f"2026-11-0{guia[-1]}T10:00:00+00:00",
    })
    fila.update(extra)
    return fila


class LectorFalso:
    """Devuelve lecturas predefinidas por archivo y cuenta las llamadas."""

    def __init__(self, lecturas):
        self.lecturas = lecturas
        self.llamadas = []

    def leer(self, ruta, archivo, traza):
        self.llamadas.append(archivo)
        datos, lineas = self.lecturas[archivo]
        return ri.Lectura(datos, lineas, "OCR_COPIA", hashlib.sha256(Path(ruta).read_bytes()).hexdigest())

    def cerrar(self):
        pass


@pytest.fixture
def raiz(tmp_path, monkeypatch):
    monkeypatch.delenv(ri.VARIABLE_DESACTIVAR, raising=False)
    raiz = tmp_path / "Atlas"
    cat = raiz / "catalogos_privados"
    cat.mkdir(parents=True)
    (raiz / "operacion" / "actual").mkdir(parents=True)
    (cat / "choferes.json").write_text(json.dumps({
        "142938162": {"nombre": "LUIS VARAS", "rut": RUT_LUIS, "aliases": [], "activo": True},
        "154542973": {"nombre": "RODRIGO NAHUELÑIR", "rut": RUT_RODRIGO, "aliases": [], "activo": True},
    }), encoding="utf-8")
    vehiculos = [_vehiculo("DD2494"), _vehiculo("SB6486"), _vehiculo("JB8529", "CARRO"),
                 _vehiculo("JF4288", "CARRO"), _vehiculo("XF3629", "CAMION_RIGIDO"), _vehiculo("BPHR67"),
                 _vehiculo("BDFG50")]
    (cat / "vehiculos.json").write_text(json.dumps({"version": 1, "vehiculos": vehiculos}), encoding="utf-8")
    return raiz


def _escribir(raiz, filas, *, sha_distinto=()):
    for fila in filas:
        envio = fila["archivo"].split("/")[1]
        carpeta = raiz / "operacion" / "mobile" / "envios" / envio
        carpeta.mkdir(parents=True, exist_ok=True)
        contenido = f"imagen {envio}".encode()
        (carpeta / "original.jpg").write_bytes(contenido)
        sha = hashlib.sha256(b"otra" if envio in sha_distinto else contenido).hexdigest()
        (carpeta / "envio.json").write_text(json.dumps({"foto_original": "original.jpg", "imagen_sha256": sha}),
                                            encoding="utf-8")
    ruta = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)
    return ruta


def _leer(ruta):
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return {f["archivo"]: f for f in csv.DictReader(archivo, delimiter=";")}


def _correr(raiz, lector, tmp_path):
    return ri.recuperar_campos_ausentes(raiz_atlas=raiz, lector=lector, reconciliar=False,
                                        directorio_respaldo=tmp_path / "respaldo", limite_ocr=50)


def _datos(**extra):
    datos = {"numero_guia": "", "numero_transporte": "", "chofer": "No encontrado", "rut_chofer": "No encontrado",
             "patente_tracto": "No encontrado", "patente_rampla": "No encontrado", "descripcion_material": ""}
    datos.update(extra)
    return datos


LINEAS_BLOQUE = ["RETIRA", "LUIS VARAS", "RUT CHOFER", "14293816-2", "PATENTE", "DD2494", "CARRO:JB8529"]


def test_rampla_impresa_tras_carro_se_recupera_sin_tocar_lo_valido(raiz, tmp_path):
    fila = _fila("e1", "480001", patente_rampla="No encontrado")
    ruta = _escribir(raiz, [fila])
    lector = LectorFalso({fila["archivo"]: (_datos(patente_tracto="DD2494", patente_rampla="JB8529"), LINEAS_BLOQUE)})
    resumen = _correr(raiz, lector, tmp_path)
    despues = _leer(ruta)[fila["archivo"]]
    assert despues["patente_rampla"] == "JB8529"
    for columna in COLUMNAS:
        if columna not in {"patente_rampla", "metricas_procesamiento_json"}:
            assert despues[columna] == fila[columna], columna
    intento = ri.intentos_de_fila(despues)["patente_rampla"]
    assert intento["resultado"] == ri.RECUPERADO and intento["actor"] == ri.ACTOR
    assert intento["valor_anterior"] == {"patente_rampla": "No encontrado"}
    registro = json.loads((raiz / "operacion" / "actual" / ri.NOMBRE_REGISTRO).read_text(encoding="utf-8"))
    assert registro["lotes"][0]["cambios"][0]["nuevo"] == {"patente_rampla": "JB8529"}
    assert "confirmado_por" not in json.dumps(registro)
    assert resumen["guias_actualizadas"] == ["480001"]
    assert list((tmp_path / "respaldo").glob("*.csv"))


def test_480973_rampla_deducida_sin_carro_impreso_no_se_completa(raiz, tmp_path):
    # El extractor vigente deduce JF4288 por asignación, pero el papel sólo
    # imprime PATENTE SB6486; además su material vigente "empeora".
    fila = _fila("e2", "480973", chofer="RODRIGO NAHUELÑIR", rut_chofer=RUT_RODRIGO, patente_tracto="SB6486",
                 patente_rampla="No encontrado", descripcion_material="CHATARRA C PESADA PARA PROCESAR")
    ruta = _escribir(raiz, [fila])
    lineas = ["RETIRA", ": RODRIGO NAHUELNIR", "RUT CHOFER", "15454297-3", "PATENTE", "SB6486", "FECHA LLEGADA"]
    lector = LectorFalso({fila["archivo"]: (_datos(patente_tracto="SB6486", patente_rampla="JF4288"), lineas)})
    _correr(raiz, lector, tmp_path)
    despues = _leer(ruta)[fila["archivo"]]
    assert despues["patente_rampla"] == "No encontrado"
    assert despues["descripcion_material"] == "CHATARRA C PESADA PARA PROCESAR"
    assert ri.intentos_de_fila(despues)["patente_rampla"]["resultado"] == ri.SIN_CARRO_DOCUMENTAL
    assert not (raiz / "operacion" / "actual" / ri.NOMBRE_REGISTRO).exists()


def test_rampla_deducida_con_etiqueta_carro_ilegible_queda_no_encontrada(raiz, tmp_path):
    fila = _fila("e3", "480003", patente_rampla="No encontrado")
    ruta = _escribir(raiz, [fila])
    lineas = ["PATENTE", "DD2494", "CARRO: J?8???"]
    lector = LectorFalso({fila["archivo"]: (_datos(patente_rampla="JB8529"), lineas)})
    _correr(raiz, lector, tmp_path)
    despues = _leer(ruta)[fila["archivo"]]
    assert despues["patente_rampla"] == "No encontrado"
    assert ri.intentos_de_fila(despues)["patente_rampla"]["resultado"] == ri.SIN_EVIDENCIA_DOCUMENTAL


def test_camion_rigido_no_se_confunde_con_rampla_no_identificada_y_no_se_lee(raiz, tmp_path):
    rigido = _fila("e4", "480004", patente_tracto="XF3629", patente_rampla="No encontrado")
    local = _fila("e5", "480005", patente_tracto="BPHR67", patente_rampla="No encontrado")
    ruta = _escribir(raiz, [rigido, local])
    lector = LectorFalso({local["archivo"]: (_datos(patente_tracto="BPHR67"), ["PATENTE", "BPHR67 CARRO:LOCAL"])})
    _correr(raiz, lector, tmp_path)
    filas = _leer(ruta)
    assert lector.llamadas == [local["archivo"]]
    assert ri.intentos_de_fila(filas[rigido["archivo"]])["patente_rampla"]["resultado"] == ri.NO_APLICA_RIGIDO
    assert ri.intentos_de_fila(filas[local["archivo"]])["patente_rampla"]["resultado"] == ri.SIN_CARRO_DOCUMENTAL
    assert filas[rigido["archivo"]]["patente_rampla"] == "No encontrado"


def test_484096_chofer_no_extraido_y_material_valido_que_empeora(raiz, tmp_path):
    fila = _fila("e6", "484096", chofer="No encontrado", rut_chofer="No encontrado",
                 descripcion_material="HORMIGON 16MM 6M A630-420H (N)")
    ruta = _escribir(raiz, [fila])
    lineas = ["RETIRA", "JOSE LAZCANO", "PATENTE", "DD2494CARRO:JB8529", "TCHOFER", "10833150-K"]
    lector = LectorFalso({fila["archivo"]: (_datos(), lineas)})
    _correr(raiz, lector, tmp_path)
    despues = _leer(ruta)[fila["archivo"]]
    assert (despues["chofer"], despues["rut_chofer"]) == ("No encontrado", "No encontrado")
    assert despues["descripcion_material"] == "HORMIGON 16MM 6M A630-420H (N)"
    assert ri.intentos_de_fila(despues)["chofer"]["resultado"] == ri.SIN_MEJORA


def test_484002_rut_truncado_no_escribe_el_par(raiz, tmp_path):
    fila = _fila("e7", "484002", chofer="No encontrado", rut_chofer="No encontrado")
    ruta = _escribir(raiz, [fila])
    lineas = ["RETIRA", "DESPACHARA", "LUIS VARAS", "14293816-", "PATENTE", "RUT CHOFER", "DD2494"]
    lector = LectorFalso({fila["archivo"]: (_datos(chofer="LUIS VARAS", rut_chofer="14293816-"), lineas)})
    _correr(raiz, lector, tmp_path)
    despues = _leer(ruta)[fila["archivo"]]
    assert (despues["chofer"], despues["rut_chofer"]) == ("No encontrado", "No encontrado")


def test_chofer_y_rut_impresos_se_recuperan_juntos(raiz, tmp_path):
    fila = _fila("e8", "480008", chofer="No encontrado", rut_chofer="No encontrado")
    ruta = _escribir(raiz, [fila])
    lector = LectorFalso({fila["archivo"]: (_datos(chofer="LUIS VARAS", rut_chofer="14.293.816-2"), LINEAS_BLOQUE)})
    _correr(raiz, lector, tmp_path)
    despues = _leer(ruta)[fila["archivo"]]
    assert (despues["chofer"], despues["rut_chofer"]) == ("LUIS VARAS", "14.293.816-2")


def test_484396_correcciones_humanas_y_lectura_ilegible(raiz, tmp_path):
    fila = _fila("e9", "No encontrado", chofer="No encontrado", rut_chofer="No encontrado",
                 patente_tracto="No encontrado", patente_rampla="No encontrado", descripcion_material="")
    ruta = _escribir(raiz, [fila])
    (raiz / "operacion" / "actual" / "acciones_operacionales.json").write_text(json.dumps({"auditoria": [{
        "accion": "DOCUMENTO_CORREGIR_CAMPO", "confirmado_por": "JAVIER_DESKTOP",
        "entidad": {"tipo": "DOCUMENTO", "id": fila["archivo"], "campo": "patente_rampla"},
        "parametros": {"campo": "PATENTE_RAMPLA", "valor": "JF9575"}}]}), encoding="utf-8")
    lector = LectorFalso({fila["archivo"]: (_datos(), ["SANTIAGO", "GUIA"])})
    _correr(raiz, lector, tmp_path)
    despues = _leer(ruta)[fila["archivo"]]
    intentos = ri.intentos_de_fila(despues)
    assert "patente_rampla" not in intentos  # protegido por la acción humana
    assert {intentos[g]["resultado"] for g in ("chofer", "patente_tracto", "descripcion_material")} == {ri.SIN_MEJORA}
    for columna in ("chofer", "patente_tracto", "patente_rampla", "descripcion_material"):
        assert despues[columna] == fila[columna]


def test_decision_pendiente_bloquea_la_fila(raiz, tmp_path):
    fila = _fila("e10", "480010", patente_rampla="No encontrado")
    _escribir(raiz, [fila])
    (raiz / "operacion" / "actual" / "decisiones_pendientes.json").write_text(json.dumps(
        {"decisiones": [{"documento": {"archivo": fila["archivo"]}}]}), encoding="utf-8")
    lector = LectorFalso({fila["archivo"]: (_datos(patente_rampla="JB8529"), LINEAS_BLOQUE)})
    _correr(raiz, lector, tmp_path)
    assert lector.llamadas == []


def test_integridad_original_distinto_no_lee_ni_escribe_valores(raiz, tmp_path):
    fila = _fila("e11", "480011", patente_rampla="No encontrado")
    ruta = _escribir(raiz, [fila], sha_distinto={"e11"})
    lector = LectorFalso({fila["archivo"]: (_datos(patente_rampla="JB8529"), LINEAS_BLOQUE)})
    _correr(raiz, lector, tmp_path)
    despues = _leer(ruta)[fila["archivo"]]
    assert lector.llamadas == [] and despues["patente_rampla"] == "No encontrado"
    assert ri.intentos_de_fila(despues)["patente_rampla"]["resultado"] == ri.INTEGRIDAD


def test_un_intento_por_version_de_capacidad(raiz, tmp_path, monkeypatch):
    fila = _fila("e12", "480012", chofer="No encontrado", rut_chofer="No encontrado")
    _escribir(raiz, [fila])
    lector = LectorFalso({fila["archivo"]: (_datos(), LINEAS_BLOQUE)})
    _correr(raiz, lector, tmp_path)
    _correr(raiz, lector, tmp_path)
    assert len(lector.llamadas) == 1
    from atlas_core import capacidades_reevaluacion as cap
    reales = cap.versiones_actuales()
    monkeypatch.setattr(cap, "versiones_actuales", lambda: {**reales, cap.DOMINIO_CHOFER: reales[cap.DOMINIO_CHOFER] + 1})
    _correr(raiz, lector, tmp_path)
    assert len(lector.llamadas) == 2


def test_tracto_sin_planta_de_origen_se_abstiene_y_carro_no_cuenta_como_tracto(raiz, tmp_path):
    sin_planta = _fila("e13", "480013", patente_tracto="No encontrado", planta_origen_id="")
    solo_carro = _fila("e14", "480014", patente_tracto="No encontrado")
    ruta = _escribir(raiz, [sin_planta, solo_carro])
    lector = LectorFalso({
        sin_planta["archivo"]: (_datos(patente_tracto="DD2494"), LINEAS_BLOQUE),
        solo_carro["archivo"]: (_datos(patente_tracto="DD2494"), ["PATENTE", "CARRO:DD2494"]),
    })
    _correr(raiz, lector, tmp_path)
    filas = _leer(ruta)
    assert ri.intentos_de_fila(filas[sin_planta["archivo"]])["patente_tracto"]["resultado"] == ri.EFECTO_ORIGEN
    assert ri.intentos_de_fila(filas[solo_carro["archivo"]])["patente_tracto"]["resultado"] == ri.SIN_EVIDENCIA_DOCUMENTAL
    assert filas[sin_planta["archivo"]]["patente_tracto"] == filas[solo_carro["archivo"]]["patente_tracto"] == "No encontrado"


def test_tracto_ocr_deformado_homologado_se_recupera(raiz, tmp_path):
    fila = _fila("e15", "480015", patente_tracto="No encontrado", patente_rampla="No encontrado")
    ruta = _escribir(raiz, [fila])
    lector = LectorFalso({fila["archivo"]: (_datos(patente_tracto="BDFG50"), ["PATENTE", "BDFG5O", "FECHA"])})
    _correr(raiz, lector, tmp_path)
    despues = _leer(ruta)[fila["archivo"]]
    assert despues["patente_tracto"] == "BDFG50"
    assert ri.intentos_de_fila(despues)["patente_tracto"]["evidencia"] == "BDFG5O"
    # el mismo papel no imprime carro: la rampla queda declarada, no inventada
    assert despues["patente_rampla"] == "No encontrado"
    assert ri.intentos_de_fila(despues)["patente_rampla"]["resultado"] == ri.SIN_CARRO_DOCUMENTAL


def test_conflicto_con_otra_guia_del_transporte(raiz, tmp_path):
    fila = _fila("e16", "480016", patente_rampla="No encontrado", numero_transporte="0000999999")
    otra = _fila("e17", "480017", patente_rampla="JF4288", numero_transporte="0000999999")
    ruta = _escribir(raiz, [fila, otra])
    lector = LectorFalso({fila["archivo"]: (_datos(patente_rampla="JB8529"), LINEAS_BLOQUE)})
    _correr(raiz, lector, tmp_path)
    despues = _leer(ruta)[fila["archivo"]]
    assert despues["patente_rampla"] == "No encontrado"
    assert ri.intentos_de_fila(despues)["patente_rampla"]["resultado"] == ri.CONFLICTO_TRANSPORTE


def test_discrepancia_de_identidad_no_escribe(raiz, tmp_path):
    fila = _fila("e18", "480018", patente_rampla="No encontrado")
    ruta = _escribir(raiz, [fila])
    lector = LectorFalso({fila["archivo"]: (_datos(numero_guia="471111", patente_rampla="JB8529"), LINEAS_BLOQUE)})
    _correr(raiz, lector, tmp_path)
    despues = _leer(ruta)[fila["archivo"]]
    assert despues["patente_rampla"] == "No encontrado"
    assert ri.intentos_de_fila(despues)["patente_rampla"]["resultado"] == ri.DISCREPANCIA_IDENTIDAD


def test_material_impreso_se_recupera_y_material_ajeno_no(raiz, tmp_path):
    impreso = _fila("e19", "480019", descripcion_material="")
    ajeno = _fila("e20", "480020", descripcion_material="")
    ruta = _escribir(raiz, [impreso, ajeno])
    lector = LectorFalso({
        impreso["archivo"]: (_datos(descripcion_material="ROLLO HORMIGON 10MM A630-420H (N)"),
                             ["DESCRIPCION", "ROLLO HORMIGON 10MM A630-420H(N)"]),
        ajeno["archivo"]: (_datos(descripcion_material="ROLLO HORMIGON 10MM A630-420H (N)"),
                           ["DESCRIPCION", "SAFEROCK 25KG"]),
    })
    _correr(raiz, lector, tmp_path)
    filas = _leer(ruta)
    assert filas[impreso["archivo"]]["descripcion_material"] == "ROLLO HORMIGON 10MM A630-420H (N)"
    assert filas[ajeno["archivo"]]["descripcion_material"] == ""


def test_presupuesto_de_ocr_por_ciclo(raiz, tmp_path):
    filas = [_fila(f"p{i}", f"48100{i}", patente_rampla="No encontrado") for i in range(5)]
    _escribir(raiz, filas)
    lector = LectorFalso({f["archivo"]: (_datos(patente_rampla="JB8529"), LINEAS_BLOQUE) for f in filas})
    ri.recuperar_campos_ausentes(raiz_atlas=raiz, lector=lector, reconciliar=False,
                                 directorio_respaldo=tmp_path / "r", limite_ocr=2)
    assert len(lector.llamadas) == 2


def test_revertir_lote_restaura_y_no_pisa_cambios_posteriores(raiz, tmp_path):
    a = _fila("e21", "480021", patente_rampla="No encontrado")
    b = _fila("e22", "480022", patente_rampla="No encontrado")
    ruta = _escribir(raiz, [a, b])
    lector = LectorFalso({x["archivo"]: (_datos(patente_rampla="JB8529"), LINEAS_BLOQUE) for x in (a, b)})
    resumen = _correr(raiz, lector, tmp_path)
    filas = list(_leer(ruta).values())
    for fila in filas:
        if fila["archivo"] == b["archivo"]:
            fila["patente_rampla"] = "JF4288"  # un humano lo cambió después
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)
    resultado = ri.revertir_lote(raiz_atlas=raiz, lote=resumen["lote"], reconciliar=False)
    filas = _leer(ruta)
    assert filas[a["archivo"]]["patente_rampla"] == "No encontrado"
    assert filas[b["archivo"]]["patente_rampla"] == "JF4288"
    assert resultado["conservados"] == [b["archivo"]]
    assert ri.intentos_de_fila(filas[a["archivo"]])["patente_rampla"]["resultado"] == ri.REVERTIDO
    lector.llamadas.clear()
    _correr(raiz, lector, tmp_path)
    assert lector.llamadas == []  # revertido no se reintenta en la misma versión


def test_interruptor_desactiva(raiz, tmp_path, monkeypatch):
    fila = _fila("e23", "480023", patente_rampla="No encontrado")
    _escribir(raiz, [fila])
    monkeypatch.setenv(ri.VARIABLE_DESACTIVAR, "0")
    lector = LectorFalso({})
    assert _correr(raiz, lector, tmp_path)["omitido"] == "DESACTIVADO"
    assert lector.llamadas == []


def test_vista_previa_exige_marcador_de_copia(raiz):
    with pytest.raises(SystemExit):
        ri.main(["--raiz-atlas", str(raiz), "previsualizar", "--salida", str(raiz / "x.json")])


def _pull(tmp_path, envios, recuperar):
    from types import SimpleNamespace as NS
    from unittest.mock import patch
    from sincronizar_mobile_cloud import ejecutar_pull_con_escritor

    class Escritor:
        vigente = True
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def adquirir(self): return True

    argumentos = dict(base_url="https://cloud.test", token_motor="t", consumidor="JAVO",
                      repositorio=NS(raiz_atlas=tmp_path), timeout=1, procesar=False, dataset=None,
                      carpeta_catalogos=None, fabrica_escritor=lambda **_: Escritor())
    with patch("sincronizar_mobile_cloud.sincronizar_envios_cloud", return_value=dict(envios)), \
         patch("atlas_core.exclusividad_equipo.recuperar_bloqueos_huerfanos"), \
         patch("sincronizar_mobile_cloud.publicar_asignaciones_cloud", return_value={}), \
         patch("sincronizar_mobile_cloud.sincronizar_licencias_cloud", return_value={}), \
         patch("sincronizar_mobile_cloud.extraer_licencias_pendientes", return_value={}), \
         patch("sincronizar_mobile_cloud.identificar_patentes_documentos", return_value={}), \
         patch("sincronizar_mobile_cloud.extraer_vencimientos_vehiculos", return_value={}), \
         patch("atlas_core.recuperacion_incremental.ejecutar_en_ciclo_pull", side_effect=recuperar) as llamada:
        return ejecutar_pull_con_escritor(**argumentos), llamada


def test_pull_recupera_solo_en_ciclos_sin_envios_y_un_fallo_no_lo_corta(tmp_path):
    vista = {"lote": "L", "intentados": 2, "recuperados": [{"x": 1}], "guias_actualizadas": ["480001"],
             "dataset_escrito": True}
    resultado, llamada = _pull(tmp_path, {"encontrados": 0, "confirmados": []}, lambda **_: vista)
    assert resultado["recuperacion_campos_ausentes"] == {"lote": "L", "intentados": 2, "recuperados": 1,
                                                         "guias": ["480001"]}
    assert llamada.call_args.kwargs["raiz_atlas"] == tmp_path
    llamada.call_args.kwargs["comprobar"]()  # lease vigente: no lanza

    resultado, llamada = _pull(tmp_path, {"encontrados": 1, "confirmados": ["e1"]}, lambda **_: vista)
    assert llamada.call_count == 0 and "recuperacion_campos_ausentes" not in resultado

    def falla(**_):
        raise OSError("OCR caído")
    resultado, _ = _pull(tmp_path, {"encontrados": 0}, falla)
    assert resultado["recuperacion_campos_ausentes"] == {"error": "OCR caído"}
    assert resultado["encontrados"] == 0


@pytest.mark.parametrize("linea, esperado", [
    (": DD2494 CARR01JB8529", "JB8529"),       # 474265: "CARRO:" leído como CARR0 + 1
    ("DD2494 CARRD1JB8529", "JB8529"),         # 482308: CARRO leído como CARRD
])
def test_etiqueta_carro_deformada_por_ocr_se_reconoce(raiz, tmp_path, linea, esperado):
    fila = _fila("e30", "480030", patente_rampla="No encontrado")
    ruta = _escribir(raiz, [fila])
    lector = LectorFalso({fila["archivo"]: (_datos(patente_rampla=esperado), ["PATENTE", linea])})
    _correr(raiz, lector, tmp_path)
    assert _leer(ruta)[fila["archivo"]]["patente_rampla"] == esperado


def test_carro_ilegible_no_se_confunde_con_camion_sin_carro(raiz, tmp_path):
    # 473442: "Carao; J5o108" -- hay etiqueta deformada y un carro ilegible.
    deformada = _fila("e31", "480031", patente_rampla="No encontrado")
    # Etiqueta perdida pero la patente del carro sí aparece en otra línea.
    sin_etiqueta = _fila("e32", "480032", patente_rampla="No encontrado")
    ruta = _escribir(raiz, [deformada, sin_etiqueta])
    lector = LectorFalso({
        deformada["archivo"]: (_datos(), ["PATENTE", "LUIS VARAS DD2494 Carao; J5o108"]),
        sin_etiqueta["archivo"]: (_datos(), ["PATENTE", "DD2494", "JB8S29"]),
    })
    _correr(raiz, lector, tmp_path)
    filas = _leer(ruta)
    for fila in (deformada, sin_etiqueta):
        assert ri.intentos_de_fila(filas[fila["archivo"]])["patente_rampla"]["resultado"] == ri.SIN_MEJORA
        assert filas[fila["archivo"]]["patente_rampla"] == "No encontrado"


def test_presupuesto_de_tiempo_no_inicia_lecturas_ni_consume_intentos(raiz, tmp_path):
    filas = [_fila(f"t{i}", f"48200{i}", patente_rampla="No encontrado") for i in range(4)]
    ruta = _escribir(raiz, filas)
    reloj = iter([0.0, 0.0, 10.0, 31.0, 31.0, 31.0])
    lector = LectorFalso({f["archivo"]: (_datos(patente_rampla="JB8529"), LINEAS_BLOQUE) for f in filas})
    # Sin traza todas son OCR: la segunda empieza a los 10 s (< 15 = mitad); la tercera ya no.
    ri.recuperar_campos_ausentes(raiz_atlas=raiz, lector=lector, reconciliar=False, limite_ocr=50,
                                 directorio_respaldo=tmp_path / "r", presupuesto_segundos=30,
                                 cronometro=lambda: next(reloj))
    assert len(lector.llamadas) == 2
    sin_intento = [f for f in _leer(ruta).values() if "patente_rampla" not in ri.intentos_de_fila(f)]
    assert len(sin_intento) == 2


def test_ciclo_pull_respeta_intervalo_minimo(raiz, tmp_path, monkeypatch):
    llamadas = []
    monkeypatch.setattr(ri, "recuperar_campos_ausentes", lambda **k: llamadas.append(k) or {"intentados": 1})
    marca = tmp_path / "marca.json"
    reloj = iter([1000.0, 1000.0, 1300.0, 1700.0, 1700.0])
    argumentos = dict(raiz_atlas=raiz, comprobar=lambda: None, fabrica_ocr=lambda: None, marca=marca,
                      ahora=lambda: next(reloj))
    assert ri.ejecutar_en_ciclo_pull(**argumentos) == {"intentados": 1}
    assert ri.ejecutar_en_ciclo_pull(**argumentos) == {}  # 300 s después: no
    assert ri.ejecutar_en_ciclo_pull(**argumentos) == {"intentados": 1}  # 700 s: sí
    assert len(llamadas) == 2 and llamadas[0]["presupuesto_segundos"] == ri.PRESUPUESTO_PULL_SEGUNDOS
