"""Vista por guía de la vista previa de adicionales (P1.3: una fila por viaje).

Reconstruye [guía, viaje, resultado, observación vigente, resultante] desde la
tabla por viaje y la de lo no encontrado, para las aserciones por guía."""


def por_guia(respuesta):
    filas = {}
    for tabla in respuesta.get("tablas") or []:
        if tabla.get("tipo") == "observacion_viaje_preview":
            for viaje, guias, resultado, vigente, resultante in tabla["filas"]:
                for guia in [g.strip() for g in guias.split(",") if g.strip()]:
                    filas[guia] = [guia, viaje, resultado, vigente, resultante]
        elif tabla.get("tipo") == "observacion_viaje_no_encontradas":
            for indicado, motivo in tabla["filas"]:
                numero = indicado.split()[-1]
                filas[numero] = [numero, "", motivo, "", ""]
    return filas
