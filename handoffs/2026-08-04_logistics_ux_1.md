# Handoff — Logistics UX 1.0

## Estado

La mejora visual está implementada y cubierta por 39 pruebas Desktop y una
prueba Electron con cuatro estados. No se modificó el motor de rutas.

## Despliegue

El comando oficial construyó y copió `app.asar` versión 1.2.0, commit
`9b67abb7a2b3d6a9ecc98bdf2a644cbdb168eb43`, SHA-256
`03f0bcddc1e8b3299f31cf973c1fea4266a2fa256706c9b070c1aaefcb5e3892`.

Smart App Control bloqueó el arranque del `Atlas Viajes.exe` no firmado. La
evidencia es Code Integrity evento 3077, política
`{0283ac0f-fff1-49ae-ada1-8a933130cad6}`. Se requiere resolver la confianza o
firma del ejecutable antes de certificar la instalación activa.
