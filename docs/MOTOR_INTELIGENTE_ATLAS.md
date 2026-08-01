# Prototipo del motor inteligente de Atlas

## Alcance

Este paquete reúne evidencias estructuradas, detecta valores compatibles o
contradictorios y devuelve una propuesta reproducible. Conserva siempre el
valor original y, cuando el apoyo no es suficiente o existe contradicción,
devuelve `REVISAR`.

No es un chatbot, no modifica OCR ni fuzzy, no corrige datos operacionales y no
conecta todavía con Desktop, viajes o rutas. Tampoco usa internet, modelos
descargados, SDK de IA ni credenciales.

## Arquitectura

`Evidencia → normalización → deduplicación → agrupación → ponderación explícita
→ contradicciones → Propuesta`

Los contratos son inmutables:

- `Evidencia` conserva observación, normalización, fuente, confianza, fecha,
  documento, referencia, detalles y clasificación sensible.
- `Contradiccion` conserva todos los valores y evidencias enfrentados.
- `Propuesta` conserva original, propuesto, estado, confianza, apoyo, oposición,
  contradicciones, explicación, acción y trazabilidad.

## Confianza y políticas

Los pesos por tipo de fuente están centralizados en `PESOS_FUENTE`. Los
umbrales, margen, validador e inferencias prohibidas forman una
`PoliticaResolucion` configurable. No existen porcentajes ocultos.

Hay políticas separadas para chofer, RUT, cliente, destino, patentes, fecha,
transporte, guía, planta, comuna y región. Cliente no determina destino;
destino no determina cliente; chofer y patente no se fijan entre sí; cercanía
no determina planta.

Una respuesta de modelo IA aislada tiene peso insuficiente y nunca modifica un
valor directamente. Una verificación externa puede apoyar o contradecir, pero
no impone sola una decisión.

## Explicabilidad

La explicación se compone de frases deterministas basadas en campos
estructurados: original, valor con mayor apoyo, número de evidencias favorables
y contrarias, y estado. No contiene razonamiento interno oculto ni texto libre
generado por un modelo.

## Aprendizaje controlado

`RepositorioCorreccionesMemoria` registra correcciones `PENDIENTE`, `APROBADA`,
`RECHAZADA` o `INACTIVA`. Sólo una corrección aprobada puede ser consultada como
tal; registrarla nunca la transforma automáticamente en regla y puede
desactivarse.

## Proveedores reemplazables

Existen puertos para modelo inteligente y verificación externa. Los dobles
iniciales son deterministas y sólo registran el contexto explícitamente
autorizado. Un proveedor futuro deberá convertir su respuesta en evidencias;
nunca recibirá autoridad para escribir datos.

## Privacidad

`preparar_envio` aplica lista positiva, redacta RUT, nombres y direcciones,
bloquea imágenes completas y descarta campos con aspecto de clave o token. El
original queda local e intacto. El registro contiene únicamente campos
permitidos y bloqueados, no secretos.

## Ejemplo sintético

`python demostrar_motor_inteligente.py`

Combina un OCR sintético `CARLOS FIEBRI` con catálogo y relación de RUT
sintéticos para `CARLOS FIEBIG`, más una verificación externa simulada. Imprime
JSON en consola; no escribe archivos ni usa datos reales.

## Limitaciones e integración futura

El prototipo no calibra pesos con datos operacionales, no persiste decisiones,
no llama servicios y no está conectado a extractores. Antes de incorporar un
modelo o verificación real se requiere revisión independiente, política de
minimización por proveedor, timeouts, cuotas, consentimiento, evaluación ciega,
monitoreo de regresiones y un adaptador que sólo produzca `Evidencia`.
