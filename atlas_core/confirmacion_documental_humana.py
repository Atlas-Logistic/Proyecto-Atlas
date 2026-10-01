"""Ledger append-only de confirmaciones humanas sobre el documento original."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico
from atlas_core.incidencias_documentales import ClasificacionDocumental, IncidenciaDocumental


@dataclass(frozen=True)
class ConfirmacionDocumentalHumana:
    confirmacion_id: str
    incidencia_id: str
    numero_guia: str
    archivo: str
    campo: str
    valor_documental: str
    valor_canonico: str
    actor: str
    fecha: str
    clasificacion: str
    procedencia: tuple[str, ...]

    def a_dict(self):
        d = asdict(self); d["procedencia"] = list(self.procedencia); return d


def _id(incidencia: IncidenciaDocumental, archivo: str) -> str:
    base = "|".join((incidencia.incidencia_id, incidencia.numero_guia, archivo, incidencia.campo,
                     incidencia.valor_documental, incidencia.valor_canonico))
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


class AlmacenConfirmacionesDocumentales:
    """Sólo agrega confirmaciones; nunca elimina ni reescribe auditoría."""
    def __init__(self, ruta: str | Path): self.ruta = Path(ruta)

    def listar(self) -> list[ConfirmacionDocumentalHumana]:
        if not self.ruta.exists(): return []
        datos = json.loads(self.ruta.read_text(encoding="utf-8"))
        if datos.get("version_formato") != 1 or not isinstance(datos.get("confirmaciones"), list):
            raise ValueError("formato de confirmaciones documentales incompatible")
        return [ConfirmacionDocumentalHumana(**{**x, "procedencia": tuple(x.get("procedencia") or ())})
                for x in datos["confirmaciones"]]

    def confirmar(self, *, incidencia: IncidenciaDocumental, numero_guia: str, archivo: str, actor: str,
                  fecha: datetime, procedencia: Iterable[str] = ()) -> ConfirmacionDocumentalHumana:
        if numero_guia != incidencia.numero_guia:
            raise ValueError("la guía no coincide con el hallazgo; se abstiene")
        if not incidencia.numero_guia.isdigit() or not archivo.strip() or not actor.strip():
            raise ValueError("guía, archivo exacto y actor humano son obligatorios")
        if not incidencia.valor_documental.strip() or not incidencia.valor_canonico.strip():
            raise ValueError("faltan valores para comparar; no se puede confirmar emisión")
        if fecha.tzinfo is None: raise ValueError("fecha debe incluir zona horaria")
        confirmacion = ConfirmacionDocumentalHumana(
            confirmacion_id=_id(incidencia, archivo.strip()), incidencia_id=incidencia.incidencia_id,
            numero_guia=incidencia.numero_guia, archivo=archivo.strip(), campo=incidencia.campo,
            valor_documental=incidencia.valor_documental, valor_canonico=incidencia.valor_canonico,
            actor=actor.strip(), fecha=fecha.astimezone(timezone.utc).isoformat(),
            clasificacion=ClasificacionDocumental.DOCUMENTAL_CONFIRMADA.value,
            procedencia=tuple(str(x) for x in procedencia),
        )
        with bloqueo_sesion(self.ruta.parent, "confirmaciones_documentales"):
            existentes = self.listar()
            hallada = next((x for x in existentes if x.confirmacion_id == confirmacion.confirmacion_id), None)
            if hallada: return hallada
            existentes.append(confirmacion)
            escribir_json_atomico(self.ruta, {"version_formato": 1,
                                              "confirmaciones": [x.a_dict() for x in existentes]})
        return confirmacion
