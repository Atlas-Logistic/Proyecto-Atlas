# R4.7 — B1 operacional y reset preparado

## Integración

`procesar_carpeta` (Drag & Drop Desktop) ejecuta el escalamiento B1 después de
OCR, reglas, catálogos e interdocumentos. `procesar_envio_mobile` usa
`procesar_archivo` y luego `escalar_resultado_ia_en_memoria`, que reutiliza el
mismo escalador. No hay motores IA separados. B/C/D permanecen en revisión; A
sólo puede aplicarse a campos explícitos después de validación y nunca escribe
catálogos, ledger ni evidencia documental.

La causa de las cero llamadas de R4 era ambiental: la clave existía como
variable de usuario Windows, pero el proceso ya iniciado no la había heredado.
El proveedor consulta primero el proceso y, sólo en Windows, el perfil de usuario.
La credencial nunca se imprime ni persiste.

## E2E Groq real

Sobre copia aislada de 460807, el determinista dejó
`OBRA_DESTINO_SIN_CORROBORAR`. Evidencia: 472008, mismo día, chofer, tracto y
obra `AUSIN SAN BERNARDO`. El pipeline realizó una llamada a Groq
`openai/gpt-oss-120b`: PROPUESTA del mismo valor, validación Atlas aceptada,
clasificación B_ASISTENCIA, una ronda, 1,727 s, 1.863 tokens y costo no reportado
(no se inventa costo cero). No se aplicó el valor y la revisión permanece.
Traza: `C:\Users\Jjjc0508\Desktop\Atlas\R47_B1_E2E_AISLADO_20260820`.

## Reset controlado

Respaldo rollback preparado en
`G:\Mi unidad\Atlas\respaldos\20260820_R47_PRE_RESET`.
Prueba aislada en
`C:\Users\Jjjc0508\Desktop\Atlas\R47_RESET_AISLADO_20260820`: 0 documentos,
0 viajes y 0 revisiones. Hashes de vehículos y decisiones aplicadas permanecen
idénticos. La función exige el marcador `.atlas_reset_aislado_autorizado`; la
raíz real no tiene ese marcador y el reset real no fue ejecutado.

Preservar: `catalogos_privados`, `decisiones_aplicadas.json`, incidencias y
evidencia histórica, relaciones confirmadas, vehículos, choferes, configuración,
cache/telemetría útil, datos privados, históricos y respaldos.

Limpiar al autorizar: dataset de `operacion/actual`, decisiones pendientes,
estado transaccional vigente y archivos de `reportes/actual`. Las entradas
activas se retiran de la vista operacional sólo mediante el procedimiento de
reset autorizado; los históricos y el rollback nunca se eliminan.
