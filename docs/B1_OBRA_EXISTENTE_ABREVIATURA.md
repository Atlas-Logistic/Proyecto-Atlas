# B1: obra existente escrita con otra abreviatura (caso 492040)

## Síntoma
Guía 492040, cliente SODIMAC SA. Javier escribe en la tarjeta OBRA_DESCONOCIDA
«la obra es SODIMAC SA RENCA BODEGA 721». B1 responde que la obra no está
registrada y ofrece crearla. Si se acepta, la oferta crea un duplicado.

## Causa raíz
- La obra existe en `catalogos_privados/obras_destinos.json` como
  «SODIMAC SA RENCA BOD 721» (obra_id 4e8fd4b6, CONFIRMADA, ACTIVA, cliente SODIMAC SA).
- `resolver_obra` (b1_operador) solo aceptaba coincidencia exacta normalizada,
  sin abreviaturas. Tampoco usaba el cliente de la guía.
- `OBRA_REGISTRAR` solo detecta duplicados exactos. Por eso la oferta de
  registro habría creado «... BODEGA 721» junto a «... BOD 721».
- El catálogo era el correcto: B1 y Desktop leen el mismo archivo de la raíz
  configurada (verificado sobre una copia con hash idéntico al de G:).

## Corrección (general, sin excepciones por cliente)
- `obra_equivale_por_abreviatura(a, b)`: las dos obras tienen la misma cantidad
  de palabras. Cada palabra distinta es una abreviatura por prefijo de la otra,
  con al menos 3 letras (BOD/BODEGA, EDIF/EDIFICIO). Las palabras con dígitos
  deben ser idénticas. No es fuzzy: no tolera letras cambiadas, palabras
  faltantes ni números distintos.
- `resolver_obra(obras, mencion, cliente_id)`: la regla exacta no cambia. Solo
  si no hay ninguna coincidencia exacta y se conoce el cliente de la guía, B1
  busca equivalentes entre las obras vigentes de ESE cliente: con una sola, la
  resuelve; con varias, la marca como AMBIGUO; con ninguna, la trata como
  DESCONOCIDO, como antes. Nunca cruza clientes.
- El cliente de la guía se toma de su fila vigente, resuelta contra el catálogo
  de clientes. Si la fila no lo resuelve, se usa el `contexto.cliente_id` de la
  tarjeta.
- `OBRA_REGISTRAR` desde B1: si la obra pedida equivale a una ya registrada del
  mismo cliente, B1 rechaza el registro y orienta a «la obra es <canónica>».

La guía recibe el nombre canónico del catálogo. No se crean obras ni alias, ni
se modifican registros existentes.

## Evidencia
- Catálogo real (103 obras vigentes): ninguna pareja de obras distintas del
  mismo cliente resulta equivalente con esta regla.
- Vista previa real (copia local, cancelada, sin confirmar):
  - Antes de la corrección: «no está registrada» y oferta de crear el duplicado.
  - Después: DOCUMENTO_ASIGNAR_OBRA `1SODIMAC SA RZNCA BOD 121` → `SODIMAC SA RENCA BOD 721`
    (obra_id 4e8fd4b6), que retira solo la tarjeta de 492040. El registro del
    duplicado queda rechazado.
- Pruebas: `tests/test_b1_obra_existente_abreviatura.py` (19).
