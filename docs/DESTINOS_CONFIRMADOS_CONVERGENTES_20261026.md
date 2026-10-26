# Obras y destinos confirmados antes de preguntar

## Causa

El replay sólo corregía ausencias, no campos ocupados por RUT o texto
contaminado. La resolución de obra y dirección se hacía por separado:
una obra ausente impedía consultar su destino, y una variante de espacios
creaba una obra desconocida aunque cliente, dirección y catálogo coincidieran.
Los motivos persistidos podían sobrevivir aunque se recuperara el dato.

## Cambio

`convergencia_destino_confirmado.py` cruza nombre y RUT del cliente confirmado,
obra documental compatible y número/dirección del documento o su traza propia
con una relación obra-destino confirmada y activa. Exige un único candidato.
Un nombre aislado, otra numeración, comuna contradictoria, relación ambigua,
decisión humana, cuarentena o evidencia B1 rechazada impiden la promoción.
Una comuna impresa distinta sólo se admite si una confirmación previa del
catálogo documenta esa equivalencia operacional.

Para texto de calle fuertemente degradado exige además nombre de obra legible
en otra sección y dos códigos documentales (cliente/destinatario) corroborados
por una fila cuyo cliente, RUT, obra y dirección ya coinciden con el catálogo.
La tolerancia numérica I/O sólo funciona dentro de un número iniciado por un
dígito; nunca equipara números legítimos distintos.

No crea obras, direcciones, alias ni coordenadas. Conserva el texto anterior y
la evidencia usada en `metricas_procesamiento_json.convergencia_destino_confirmado`.
Completa campos canónicos de destino; no declara kilómetros ni una ruta calculada.
La cola técnica habitual conserva el cálculo de ruta pendiente.

Se conecta antes de las preguntas en el cierre de lote Desktop, la fase de
revalidación/reporte Mobile y la reconciliación de estado derivado. El filtro
final revalida el catálogo vivo y sólo retira decisiones OBRA/DESTINO con
convergencia aún válida; preserva correcciones manuales y otros dominios.
El caché es local a una llamada, sin persistencia ni reutilización entre ciclos.

## Validación y alcance productivo

Pruebas focalizadas: `test_destinos_confirmados_convergentes.py`,
`test_mobile_convergencia_post_reporte.py`,
`test_cierre_convergencia_destinos_catalogo.py` y
`test_destino_ocr_catalogo_confirmado_482402_482106.py`. Sin suite completa.

Ensayo en copia local del dataset de 604 filas, catálogos y trazas persistidas:

| Guía | Resolución |
|---|---|
| 482771 | Camino Lo Ruiz 2901, Renca; 290I corregido con numeración corroborada |
| 482772 | Misma obra/destino; RUT descartado como dirección y corroboración con traza propia |
| 483017 | American Screw, Camino a Melipilla 10800, Maipú; traza y códigos convergentes |
| 483138 | COMERCIAL A Y B LTDA, La Estera 525, Lampa; equivalencia impresa Santiago documentada |

Cambian exclusivamente cuatro filas y se retiran cinco decisiones. Las otras
600 filas, catálogos, ledger y eventos conservan su contenido. Segunda pasada
idempotente; detección y regeneración no reabren esas preguntas.

La intervención productiva debe limitarse a esas cuatro guías usando sesión de
escritor oficial, respaldo previo, validación de columnas y huellas de los
artefactos protegidos. No debe ejecutar la batería global, registrar respuestas
humanas ficticias ni modificar envíos Mobile. Permanecen seis decisiones de
482740, 482908 y 482816; incluye el duplicado de vehículo fuera de este alcance.
El envío 0f59c9c7 y la observación de 483025 están excluidos.

Evidencia local: `C:/Atlas/pruebas/destinos-confirmados-20261026/`.
