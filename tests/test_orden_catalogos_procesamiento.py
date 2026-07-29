from atlas_core.catalogos import enriquecer_datos_con_catalogos


def test_catalogo_se_aplica_despues_de_recuperar_nombre_geometrico(tmp_path):
    import json
    for nombre, contenido in {
        "empresas.json": {}, "destinos.json": {}, "vehiculos.json": {},
        "choferes.json": {
            "111111111": {"nombre": "ALFREDO MONTERO SUR", "activo": True},
            "PENDIENTE1": {
                "nombre": "ALFREDO MONTERO", "activo": True,
                "aliases": ["ALEREDO MONTERO"],
            },
        },
    }.items():
        (tmp_path / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    recuperado = {
        "chofer": "ALEREDO MONTERO", "RUT del chofer": "11.111.111-1",
        "cliente": "No encontrado", "RUT del cliente": "No encontrado",
    }
    final = enriquecer_datos_con_catalogos(recuperado, [], tmp_path)
    assert final["chofer"] == "ALFREDO MONTERO"
