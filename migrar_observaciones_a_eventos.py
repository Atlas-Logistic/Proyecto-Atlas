"""Migración ÚNICA de las Observaciones de Atlas Desktop (electron-store,
`observaciones.json`: `datos[numero_transporte] = {tags, nota}`) a la
fuente canónica `operacion/actual/eventos_operacionales.json`.

Garantías (ver ticket, sección MIGRACIÓN DE DATOS REALES):

- respalda ANTES `observaciones.json` y el JSON canónico existente (si
  lo hay) bajo `<raiz>/respaldos/migracion_observaciones_<ts>/`, con un
  `manifiesto.json` (sha256 + conteos) suficiente para rollback;
- preserva la nota EXACTAMENTE (incluido un `\n` final);
- busca la asociación vigente por `numero_transporte` y completa
  viaje/guías/fecha/chofer/RUT/patentes SÓLO si es inequívoco;
- NO inventa datos: si no puede vincular, el evento se conserva con
  vínculo incompleto explícito;
- idempotente: una segunda ejecución no crea duplicados (la idempotencia
  la garantiza `registrar_evento` por `clave_idempotencia`);
- NUNCA modifica ni borra `observaciones.json` (sólo lo lee).

`estadia -> TIENE_ESTADIA`; también `devolucion_parcial ->
DEVOLUCION_PARCIAL`, `devolucion_total -> DEVOLUCION_TOTAL`,
`doble_vuelta -> DOBLE_VUELTA`. Un tag desconocido NO genera evento --
se reporta en `tags_no_mapeados`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from atlas_core.almacenamiento_portable import ruta_respaldos
from atlas_core.registro_eventos_operacionales import (
    CONTEXTO_EMPRESARIAL_SIN_ASIGNAR,
    ESTADO_ACTIVO,
    clave_idempotencia,
    leer_eventos_operacionales,
    registrar_evento,
    resolver_enriquecimiento_transporte,
    ruta_eventos_operacionales,
)

ORIGEN_MIGRACION = "MIGRACION_OBSERVACIONES_ELECTRON_STORE"

MAPEO_TAGS = {
    "estadia": "TIENE_ESTADIA",
    "devolucion_parcial": "DEVOLUCION_PARCIAL",
    "devolucion_total": "DEVOLUCION_TOTAL",
    "doble_vuelta": "DOBLE_VUELTA",
}


def _normalizar_tag(tag: str) -> str:
    texto = unicodedata.normalize("NFKD", str(tag or "").strip().casefold())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return "_".join(texto.split()).replace("-", "_")


def _sha256_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _cargar_observaciones(ruta: Path) -> dict[str, dict]:
    contenido = json.loads(ruta.read_text(encoding="utf-8"))
    if isinstance(contenido, dict) and isinstance(contenido.get("datos"), dict):
        datos = contenido["datos"]
    elif isinstance(contenido, dict):
        datos = contenido
    else:
        raise ValueError("observaciones.json no tiene la forma esperada.")
    salida: dict[str, dict] = {}
    for numero_transporte, registro in datos.items():
        if not isinstance(registro, dict):
            continue
        tags = registro.get("tags") or []
        salida[str(numero_transporte)] = {
            "tags": [str(t) for t in tags if str(t).strip()],
            "nota": str(registro.get("nota", "")),
        }
    return salida


def _respaldar(raiz: Path, ruta_observaciones: Path, marca: str) -> Path:
    destino = ruta_respaldos(raiz=raiz) / f"migracion_observaciones_{marca}"
    destino.mkdir(parents=True, exist_ok=True)

    texto_obs = ruta_observaciones.read_text(encoding="utf-8")
    (destino / "observaciones.json").write_text(texto_obs, encoding="utf-8")

    ruta_canonico = ruta_eventos_operacionales(raiz=raiz)
    canonico_sha = None
    if ruta_canonico.is_file():
        texto_canon = ruta_canonico.read_text(encoding="utf-8")
        (destino / "eventos_operacionales.json").write_text(texto_canon, encoding="utf-8")
        canonico_sha = _sha256_texto(texto_canon)

    manifiesto = {
        "generado_en": datetime.now(timezone.utc).isoformat(),
        "raiz_atlas": str(raiz),
        "origen_observaciones": str(ruta_observaciones),
        "observaciones_sha256": _sha256_texto(texto_obs),
        "eventos_operacionales_sha256": canonico_sha,
        "eventos_operacionales_presente": canonico_sha is not None,
    }
    (destino / "manifiesto.json").write_text(
        json.dumps(manifiesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return destino


def migrar(
    *,
    raiz_atlas: str | Path,
    ruta_observaciones: str | Path,
    contexto_empresarial: str = CONTEXTO_EMPRESARIAL_SIN_ASIGNAR,
    dry_run: bool = False,
) -> dict:
    raiz = Path(raiz_atlas)
    ruta_obs = Path(ruta_observaciones)
    if not ruta_obs.is_file():
        return {"ok": False, "error": f"No existe {ruta_obs}"}

    observaciones = _cargar_observaciones(ruta_obs)
    marca = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    respaldo = None
    if not dry_run:
        respaldo = _respaldar(raiz, ruta_obs, marca)

    tags_por_tipo: dict[str, int] = {}
    tags_no_mapeados: list[dict] = []
    incompletos: list[dict] = []
    creados = reactivados = ya_existentes = vinculados_completos = 0
    total_tags = 0

    # Para dry-run: predecir creado/ya_existente sin escribir.
    claves_existentes = {
        e.get("clave_idempotencia"): e.get("estado")
        for e in leer_eventos_operacionales(raiz=raiz).get("eventos", [])
    }

    for numero_transporte, registro in observaciones.items():
        nota = registro["nota"]
        for tag in registro["tags"]:
            total_tags += 1
            tipo_evento = MAPEO_TAGS.get(_normalizar_tag(tag))
            if tipo_evento is None:
                tags_no_mapeados.append({"numero_transporte": numero_transporte, "tag": tag})
                continue
            tags_por_tipo[tipo_evento] = tags_por_tipo.get(tipo_evento, 0) + 1
            enriquecimiento = resolver_enriquecimiento_transporte(
                raiz=raiz, numero_transporte=numero_transporte
            )

            if dry_run:
                clave = clave_idempotencia(
                    contexto_empresarial=contexto_empresarial,
                    tipo_evento=tipo_evento,
                    numero_transporte=numero_transporte,
                )
                if clave not in claves_existentes:
                    creados += 1
                elif claves_existentes[clave] != ESTADO_ACTIVO:
                    reactivados += 1
                else:
                    ya_existentes += 1
                if enriquecimiento.get("vinculo_completo"):
                    vinculados_completos += 1
                else:
                    incompletos.append({
                        "numero_transporte": numero_transporte,
                        "tipo_evento": tipo_evento,
                        "motivo": enriquecimiento.get("motivo_vinculo_incompleto", ""),
                    })
                continue

            resultado = registrar_evento(
                raiz=raiz,
                tipo_evento=tipo_evento,
                numero_transporte=numero_transporte,
                nota=nota,
                contexto_empresarial=contexto_empresarial,
                origen=ORIGEN_MIGRACION,
                referencia=numero_transporte,
                enriquecimiento=enriquecimiento,
            )
            evento = resultado.get("evento") or {}
            if resultado.get("creado"):
                creados += 1
            elif resultado.get("reactivado"):
                reactivados += 1
            else:
                ya_existentes += 1
            if evento.get("vinculo_completo"):
                vinculados_completos += 1
            else:
                incompletos.append({
                    "numero_transporte": numero_transporte,
                    "tipo_evento": tipo_evento,
                    "motivo": evento.get("motivo_vinculo_incompleto", ""),
                })

    # Conteo canónico REAL de TIENE_ESTADIA activos tras la migración.
    documento = leer_eventos_operacionales(raiz=raiz)
    tiene_estadia_activos = sum(
        1
        for e in documento.get("eventos", [])
        if e.get("tipo_evento") == "TIENE_ESTADIA" and e.get("estado") == ESTADO_ACTIVO
    )

    return {
        "ok": True,
        "dry_run": dry_run,
        "raiz_atlas": str(raiz),
        "contexto_empresarial": contexto_empresarial,
        "observaciones_encontradas": len(observaciones),
        "tags_encontrados": total_tags,
        "tags_por_tipo": tags_por_tipo,
        "eventos_creados": creados,
        "eventos_reactivados": reactivados,
        "eventos_ya_existentes": ya_existentes,
        "vinculados_completos": vinculados_completos,
        "incompletos": incompletos,
        "tiene_estadia_activos": tiene_estadia_activos,
        "tags_no_mapeados": tags_no_mapeados,
        "respaldo": str(respaldo) if respaldo else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raiz-atlas", dest="raiz_atlas", required=True)
    parser.add_argument("--observaciones", dest="observaciones", required=True)
    parser.add_argument(
        "--contexto-empresarial",
        dest="contexto_empresarial",
        default=CONTEXTO_EMPRESARIAL_SIN_ASIGNAR,
    )
    parser.add_argument("--dry-run", dest="dry_run", action="store_true")
    args = parser.parse_args()
    try:
        resultado = migrar(
            raiz_atlas=args.raiz_atlas,
            ruta_observaciones=args.observaciones,
            contexto_empresarial=args.contexto_empresarial,
            dry_run=args.dry_run,
        )
    except Exception as error:  # noqa: BLE001
        resultado = {"ok": False, "error": str(error)}
    print(json.dumps(resultado, ensure_ascii=True))


if __name__ == "__main__":
    main()
