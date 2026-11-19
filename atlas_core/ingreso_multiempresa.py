"""Contrato de ingreso Desktop con empresa y perfil documental explícitos."""
from __future__ import annotations

import json
from pathlib import Path

from atlas_core.aislamiento_empresas import EMPRESA_MBT, empresa_de_raiz, empresa_proceso
from atlas_core.perfiles_documentales import PERFIL_AZA, FormatoDocumentalDesconocido

NOMBRE_CONFIGURACION = "perfil_documental.json"
PERFIL_AZA_ID = "aza"


class ErrorIngresoMultiempresa(ValueError):
    """Solicitud Desktop incompatible con el contexto autorizado del Motor."""


def _configuracion(raiz: Path) -> dict:
    ruta = raiz / "catalogos_privados" / NOMBRE_CONFIGURACION
    if not ruta.is_file():
        # MBT conserva el contrato histórico; otra empresa jamás hereda AZA.
        return {"empresa_id": EMPRESA_MBT, "perfil_documental": PERFIL_AZA_ID} if empresa_de_raiz(raiz) == EMPRESA_MBT else {}
    try:
        valor = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ErrorIngresoMultiempresa("CONFIGURACION_PERFIL_INVALIDA") from error
    if not isinstance(valor, dict):
        raise ErrorIngresoMultiempresa("CONFIGURACION_PERFIL_INVALIDA")
    return valor


def perfil_configurado(raiz: str | Path) -> str | None:
    raiz = Path(raiz).resolve()
    configuracion = _configuracion(raiz)
    if configuracion.get("empresa_id") != empresa_de_raiz(raiz):
        return None
    perfil = configuracion.get("perfil_documental")
    return perfil if isinstance(perfil, str) and perfil.strip() else None


def resolver_perfil(raiz: str | Path, empresa_id: object, perfil_id: object) -> object:
    """Autoriza empresa/perfil contra raíz y proceso antes de leer originales."""
    raiz = Path(raiz).resolve()
    empresa = empresa_de_raiz(raiz)
    if not isinstance(empresa_id, str) or empresa_id != empresa or empresa_id != empresa_proceso():
        raise ErrorIngresoMultiempresa("EMPRESA_NO_AUTORIZADA")
    configurado = perfil_configurado(raiz)
    if not isinstance(perfil_id, str) or perfil_id != configurado:
        raise ErrorIngresoMultiempresa("PERFIL_NO_AUTORIZADO")
    if empresa == EMPRESA_MBT and perfil_id == PERFIL_AZA_ID:
        return PERFIL_AZA
    raise FormatoDocumentalDesconocido("FORMATO_DOCUMENTAL_DESCONOCIDO: perfil no procesable")


def capacidades(raiz: str | Path, empresa_id: object) -> dict[str, object]:
    """Consulta pura: no anuncia perfiles sin implementador ejecutable."""
    raiz = Path(raiz).resolve()
    empresa = empresa_de_raiz(raiz)
    if not isinstance(empresa_id, str) or empresa_id != empresa or empresa_id != empresa_proceso():
        raise ErrorIngresoMultiempresa("EMPRESA_NO_AUTORIZADA")
    perfil = perfil_configurado(raiz)
    procesable = empresa == EMPRESA_MBT and perfil == PERFIL_AZA_ID
    return {"empresa_id": empresa, "perfil_documental": perfil if procesable else None,
            "perfiles_documentales": [perfil] if procesable else []}
