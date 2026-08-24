"""Bloque FIX DE ACEPTACION -- caso real 460861: una decisión
OBRA_DESCONOCIDA YA PERSISTIDA (de una corrida anterior a este fix), cuya
única causa era una variación ortográfica/OCR menor de un solo token
contra una obra ya CONFIRMADA del mismo cliente ("SALOMON SACK SA SAN
BERNGARDO" vs "SALOMON SACK SA SAN BERNARDO"), se retira sola --
aprendiendo el texto documental como alias reutilizable de esa obra."""
import json

from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, EstadoObra, Evidencia, TipoEvidencia
from atlas_core.revalidacion_documental import revalidar_obra_desconocida_por_variacion_ortografica_sin_ocr


def _carpeta_catalogos(tmp_path):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    return carpeta


def _cliente_confirmado(carpeta, *, nombre="SALOMON SACK SA", rut="50.234.350-5"):
    """La obra referencia un `cliente_id` real (validado por el
    catálogo) -- nunca un string sintético suelto. Cada test usa su
    propio `tmp_path`/catálogo aislado, así que reutilizar el mismo RUT
    válido entre tests no colisiona."""
    return CatalogoClientes(carpeta / "clientes.json").crear(
        razon_social=nombre, rut=rut, fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )


def _escribir_obra_confirmada(carpeta, *, cliente_id, nombre_canonico, obra_id="obra-confirmada"):
    catalogo = CatalogoObrasDestinos(
        ruta=carpeta / "obras_destinos.json", ruta_clientes=carpeta / "clientes.json",
        ruta_destinos=carpeta / "destinos_maestros.json",
    )
    ruta = carpeta / "obras_destinos.json"
    contenido = json.loads(ruta.read_text(encoding="utf-8"))
    contenido["obras"].append({
        "obra_id": obra_id, "cliente_id": cliente_id, "nombre_canonico": nombre_canonico,
        "nombre_normalizado": nombre_canonico, "aliases_documentales": [],
        "estado": EstadoObra.CONFIRMADA.value, "estado_vigencia": "ACTIVO",
        "evidencias": [{
            "tipo": TipoEvidencia.CONFIRMACION_HUMANA.value, "identificador_fuente": obra_id,
            "referencia_hash": "", "campos_observados": {"decision": "CONFIRMADA"},
            "fecha": "2026-01-01T00:00:00+00:00", "actor_proceso": "test", "resultado": "SOPORTA",
        }],
        "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00",
    })
    ruta.write_text(json.dumps(contenido), encoding="utf-8")
    return catalogo


def _decision_obra_desconocida(*, decision_id, numero_guia, valor_documental, cliente_id):
    return {
        "decision_id": decision_id, "estado": "PENDIENTE", "tipo": "OBRA_DESCONOCIDA",
        "entidad": "OBRA", "documento": {"archivo": f"{numero_guia}.jpeg", "numero_guia": numero_guia},
        "campo": "obra_destino", "valor_documental": valor_documental, "valor_normalizado": valor_documental,
        "identidad_resuelta": None, "contexto": {"cliente_id": cliente_id, "cliente_canonico": "SALOMON SACK SA"},
        "candidatos": [], "motivos": ["OBRA_NO_EXISTE_PARA_CLIENTE"],
        "evidencias": [{"tipo": "CLIENTE_RESUELTO", "entidad_id": cliente_id}],
        "acciones_permitidas": ["REGISTRAR", "NO_REGISTRAR", "POSPONER"],
    }


def _escribir_decisiones(tmp_path, decisiones):
    ruta = tmp_path / "decisiones_pendientes.json"
    ruta.write_text(json.dumps({
        "schema_version": 1, "generado_en": "2026-01-01T00:00:00+00:00",
        "dataset_sha256": "X", "catalogos_sha256": {}, "decisiones": decisiones,
    }), encoding="utf-8")
    return ruta


def _dataset_vacio(tmp_path):
    ruta = tmp_path / "dataset.csv"
    ruta.write_text("numero_guia;obra_destino\n", encoding="utf-8")
    return ruta


def test_caso_real_460861_retira_la_decision_y_aprende_el_alias(tmp_path):
    carpeta = _carpeta_catalogos(tmp_path)
    cliente = _cliente_confirmado(carpeta)
    catalogo = _escribir_obra_confirmada(
        carpeta, cliente_id=cliente.cliente_id, nombre_canonico="SALOMON SACK SA SAN BERNARDO",
    )
    ruta_decisiones = _escribir_decisiones(tmp_path, [
        _decision_obra_desconocida(
            decision_id="dec-460861", numero_guia="460861",
            valor_documental="SALOMON SACK SA SAN BERNGARDO", cliente_id=cliente.cliente_id,
        ),
    ])
    resultado = revalidar_obra_desconocida_por_variacion_ortografica_sin_ocr(
        ruta_decisiones=ruta_decisiones, carpeta_catalogos=carpeta, ruta_dataset=_dataset_vacio(tmp_path),
    )
    assert len(resultado["decisiones_resueltas"]) == 1
    assert resultado["decisiones_resueltas"][0]["numero_guia"] == "460861"
    bandeja = json.loads(ruta_decisiones.read_text(encoding="utf-8"))
    assert bandeja["decisiones"] == []
    # Aprendizaje: el texto documental exacto queda como alias reutilizable.
    obra = next(o for o in catalogo.listar_obras() if o.obra_id == "obra-confirmada")
    assert "SALOMON SACK SA SAN BERNGARDO" in obra.aliases_documentales
    # No es una regla global de texto -- el alias está atado a ESTA obra.
    assert obra.nombre_canonico == "SALOMON SACK SA SAN BERNARDO"


def test_decision_ambigua_entre_dos_obras_no_se_retira(tmp_path):
    carpeta = _carpeta_catalogos(tmp_path)
    cliente = _cliente_confirmado(carpeta)
    _escribir_obra_confirmada(
        carpeta, cliente_id=cliente.cliente_id, obra_id="obra-bernardo",
        nombre_canonico="SALOMON SACK SA SAN BERNARDO",
    )
    _escribir_obra_confirmada(
        carpeta, cliente_id=cliente.cliente_id, obra_id="obra-bernardq",
        nombre_canonico="SALOMON SACK SA SAN BERNARDQ",
    )
    ruta_decisiones = _escribir_decisiones(tmp_path, [
        _decision_obra_desconocida(
            decision_id="dec-ambigua", numero_guia="1",
            valor_documental="SALOMON SACK SA SAN BERNARDX", cliente_id=cliente.cliente_id,
        ),
    ])
    resultado = revalidar_obra_desconocida_por_variacion_ortografica_sin_ocr(
        ruta_decisiones=ruta_decisiones, carpeta_catalogos=carpeta, ruta_dataset=_dataset_vacio(tmp_path),
    )
    assert resultado["decisiones_resueltas"] == []
    bandeja = json.loads(ruta_decisiones.read_text(encoding="utf-8"))
    assert len(bandeja["decisiones"]) == 1


def test_decision_de_obra_realmente_nueva_no_se_retira(tmp_path):
    carpeta = _carpeta_catalogos(tmp_path)
    cliente = _cliente_confirmado(carpeta)
    _escribir_obra_confirmada(
        carpeta, cliente_id=cliente.cliente_id, nombre_canonico="SALOMON SACK SA SAN BERNARDO",
    )
    ruta_decisiones = _escribir_decisiones(tmp_path, [
        _decision_obra_desconocida(
            decision_id="dec-nueva", numero_guia="2",
            valor_documental="CONSTRUCTORA TOTALMENTE DISTINTA LTDA", cliente_id=cliente.cliente_id,
        ),
    ])
    resultado = revalidar_obra_desconocida_por_variacion_ortografica_sin_ocr(
        ruta_decisiones=ruta_decisiones, carpeta_catalogos=carpeta, ruta_dataset=_dataset_vacio(tmp_path),
    )
    assert resultado["decisiones_resueltas"] == []
    bandeja = json.loads(ruta_decisiones.read_text(encoding="utf-8"))
    assert len(bandeja["decisiones"]) == 1


def test_otros_tipos_de_decision_se_conservan_intactos(tmp_path):
    carpeta = _carpeta_catalogos(tmp_path)
    cliente = _cliente_confirmado(carpeta)
    _escribir_obra_confirmada(carpeta, cliente_id=cliente.cliente_id, nombre_canonico="SALOMON SACK SA SAN BERNARDO")
    otra_decision = {
        "decision_id": "dec-otra", "estado": "PENDIENTE", "tipo": "VEHICULO_DESCONOCIDO",
        "entidad": "VEHICULO", "documento": {"archivo": "3.jpeg", "numero_guia": "3"},
        "campo": "patente_tracto", "valor_documental": "AB1234", "valor_normalizado": "AB1234",
        "identidad_resuelta": None, "contexto": {}, "candidatos": [], "motivos": ["SIN_CANDIDATO"],
        "evidencias": [], "acciones_permitidas": ["REGISTRAR", "NO_REGISTRAR", "POSPONER"],
    }
    ruta_decisiones = _escribir_decisiones(tmp_path, [otra_decision])
    resultado = revalidar_obra_desconocida_por_variacion_ortografica_sin_ocr(
        ruta_decisiones=ruta_decisiones, carpeta_catalogos=carpeta, ruta_dataset=_dataset_vacio(tmp_path),
    )
    assert resultado["decisiones_resueltas"] == []
    bandeja = json.loads(ruta_decisiones.read_text(encoding="utf-8"))
    assert len(bandeja["decisiones"]) == 1
    assert bandeja["decisiones"][0]["decision_id"] == "dec-otra"


def test_sin_decisiones_pendientes_no_falla(tmp_path):
    carpeta = _carpeta_catalogos(tmp_path)
    resultado = revalidar_obra_desconocida_por_variacion_ortografica_sin_ocr(
        ruta_decisiones=tmp_path / "no_existe.json", carpeta_catalogos=carpeta,
        ruta_dataset=_dataset_vacio(tmp_path),
    )
    assert resultado["decisiones_resueltas"] == []
