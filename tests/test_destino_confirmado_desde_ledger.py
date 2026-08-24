"""Bloque CIERRE LOGÍSTICA RESIDUAL -- caso real 472044: un destino
CONFIRMADO por Javier (ledger `REGISTRAR_DIRECCION`, DESTINO_NO_RESUELTO)
quedó persistido en el catálogo con la etiqueta degradada a nivel comuna
("Las Condes, RM, Chile") en vez de la dirección específica que el propio
ledger ya registra ("PUERTA DEL SOL 83") -- residuo de un bug corregido
para la fila del dataset pero nunca aplicado retroactivamente al
catálogo. `revalidar_destino_confirmado_desde_ledger_sin_ocr` corrige eso,
usando el ledger como única fuente de verdad, sin red, sin OCR."""
import json

from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
from atlas_core.revalidacion_documental import revalidar_destino_confirmado_desde_ledger_sin_ocr


def _carpeta_catalogos(tmp_path):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    (carpeta / "clientes.json").write_text('{"version_formato": 1, "clientes": []}', encoding="utf-8")
    return carpeta


def _escribir_ledger(actual_o_tmp, aplicaciones):
    ruta = actual_o_tmp / "decisiones_aplicadas.json"
    ruta.write_text(json.dumps({"schema_version": 1, "aplicaciones": aplicaciones}), encoding="utf-8")
    return ruta


def _aplicacion_registrar_direccion(*, destino_id, direccion_manual, numero_guia="472044"):
    return {
        "decision_id": f"decision-{numero_guia}",
        "tipo": "DESTINO_NO_RESUELTO",
        "accion": "REGISTRAR_DIRECCION",
        "actor": "JAVIER_DESKTOP",
        "documento": {"archivo": f"{numero_guia}.jpeg", "numero_guia": numero_guia},
        "direccion_manual": direccion_manual,
        "destino_id": destino_id,
    }


def test_corrige_etiqueta_degradada_del_destino_confirmado(tmp_path):
    """Caso real 472044: el ledger trae la dirección específica que
    Javier confirmó; el catálogo quedó con la etiqueta genérica de
    comuna -- se corrige."""
    carpeta = _carpeta_catalogos(tmp_path)
    catalogo = CatalogoDestinos(carpeta / "destinos_maestros.json", ruta_clientes=carpeta / "clientes.json")
    destino = catalogo.crear(
        cliente_id="", nombre_destino="Las Condes, RM, Chile", direccion="Las Condes, RM, Chile",
        comuna="Las Condes", region="Metropolitana", pais="CHILE", fuente="TEST",
        estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    ruta_ledger = _escribir_ledger(tmp_path, [
        _aplicacion_registrar_direccion(destino_id=destino.destino_id, direccion_manual="PUERTA DEL SOL 83"),
    ])
    resultado = revalidar_destino_confirmado_desde_ledger_sin_ocr(
        carpeta_catalogos=carpeta, ruta_ledger=ruta_ledger,
    )
    assert resultado["destinos_corregidos"] == [destino.destino_id]
    corregido = catalogo.obtener(destino.destino_id)
    assert corregido.direccion == "PUERTA DEL SOL 83"
    assert corregido.nombre_destino == "PUERTA DEL SOL 83"
    # Nunca toca comuna/región/coordenadas -- sólo la etiqueta.
    assert corregido.comuna == "Las Condes"
    assert corregido.region == "Metropolitana"
    assert corregido.estado_calidad == EstadoCalidadDestino.CONFIRMADO.value


def test_destino_ya_especifico_no_se_toca(tmp_path):
    """Control -- un destino cuya dirección actual ya es igual o más
    específica que la del ledger (o coincide) nunca se reescribe sin
    motivo real."""
    carpeta = _carpeta_catalogos(tmp_path)
    catalogo = CatalogoDestinos(carpeta / "destinos_maestros.json", ruta_clientes=carpeta / "clientes.json")
    destino = catalogo.crear(
        cliente_id="", nombre_destino="PUERTA DEL SOL 83", direccion="PUERTA DEL SOL 83",
        pais="CHILE", fuente="TEST", estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    ruta_ledger = _escribir_ledger(tmp_path, [
        _aplicacion_registrar_direccion(destino_id=destino.destino_id, direccion_manual="Las Condes, RM, Chile"),
    ])
    resultado = revalidar_destino_confirmado_desde_ledger_sin_ocr(
        carpeta_catalogos=carpeta, ruta_ledger=ruta_ledger,
    )
    assert resultado["destinos_corregidos"] == []
    intacto = catalogo.obtener(destino.destino_id)
    assert intacto.direccion == "PUERTA DEL SOL 83"


def test_ignora_aplicaciones_de_otro_tipo_o_accion(tmp_path):
    """Sólo `DESTINO_NO_RESUELTO`/`REGISTRAR_DIRECCION` es una
    confirmación de dirección -- cualquier otra combinación se ignora,
    nunca se interpreta como evidencia de dirección."""
    carpeta = _carpeta_catalogos(tmp_path)
    catalogo = CatalogoDestinos(carpeta / "destinos_maestros.json", ruta_clientes=carpeta / "clientes.json")
    destino = catalogo.crear(
        cliente_id="", nombre_destino="Las Condes, RM, Chile", direccion="Las Condes, RM, Chile",
        pais="CHILE", fuente="TEST", estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    ruta_ledger = _escribir_ledger(tmp_path, [
        {
            "decision_id": "otra-decision", "tipo": "OBRA_DESCONOCIDA", "accion": "REGISTRAR",
            "documento": {"numero_guia": "1"}, "direccion_manual": "PUERTA DEL SOL 83",
            "destino_id": destino.destino_id,
        },
    ])
    resultado = revalidar_destino_confirmado_desde_ledger_sin_ocr(
        carpeta_catalogos=carpeta, ruta_ledger=ruta_ledger,
    )
    assert resultado["destinos_corregidos"] == []


def test_ledger_ausente_no_falla(tmp_path):
    """Sin ledger (aún no hay decisiones aplicadas) -- no falla, nunca
    inventa correcciones."""
    carpeta = _carpeta_catalogos(tmp_path)
    resultado = revalidar_destino_confirmado_desde_ledger_sin_ocr(
        carpeta_catalogos=carpeta, ruta_ledger=tmp_path / "no_existe.json",
    )
    assert resultado["destinos_corregidos"] == []


def test_destino_id_inexistente_en_catalogo_se_ignora(tmp_path):
    """Un `destino_id` del ledger que ya no existe en el catálogo (p. ej.
    fusionado/depurado en otra pasada) se ignora, nunca lanza."""
    carpeta = _carpeta_catalogos(tmp_path)
    CatalogoDestinos(carpeta / "destinos_maestros.json", ruta_clientes=carpeta / "clientes.json")
    ruta_ledger = _escribir_ledger(tmp_path, [
        _aplicacion_registrar_direccion(destino_id="no-existe", direccion_manual="PUERTA DEL SOL 83"),
    ])
    resultado = revalidar_destino_confirmado_desde_ledger_sin_ocr(
        carpeta_catalogos=carpeta, ruta_ledger=ruta_ledger,
    )
    assert resultado["destinos_corregidos"] == []
