"""CLI estrecho usado por Atlas Desktop -- sección Logística del viaje,
acción "Corregir destino" -- para publicar (o reutilizar, si ya existe)
una decisión DESTINO_NO_RESUELTO/REGISTRAR_DIRECCION para un documento
concreto, sin exigir que Atlas haya detectado antes ningún problema
técnico (Bloque CORRECCIÓN HUMANA DE DESTINO).

Sólo PUBLICA la decisión -- nunca la aplica. Desktop recibe el objeto
`decision` (con su `decision_id`) y abre el mismo formulario/flujo ya
existente de Revisión de Atlas (aplicar_decision_pendiente.py,
--accion REGISTRAR_DIRECCION) para que Javier escriba la dirección
corregida."""
import argparse
import json

from atlas_core.revalidacion_documental import forzar_decision_correccion_destino


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raiz-atlas", required=True)
    parser.add_argument("--numero-guia", required=True)
    args = parser.parse_args()
    try:
        resultado = forzar_decision_correccion_destino(raiz_atlas=args.raiz_atlas, numero_guia=args.numero_guia)
    except Exception as error:
        resultado = {"ok": False, "error": str(error)}
    # Salida ASCII JSON: evita que la consola Windows recodifique los
    # mensajes UTF-8 antes de que Desktop haga JSON.parse (mismo criterio
    # que aplicar_decision_pendiente.py).
    print(json.dumps(resultado, ensure_ascii=True))


if __name__ == "__main__":
    main()
