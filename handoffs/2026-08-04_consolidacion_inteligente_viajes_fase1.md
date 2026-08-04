# Handoff — Consolidación Inteligente de Viajes, Fase 1

Estado: completada, publicada y desplegada.

Atlas Desktop representa cada número de transporte como un viaje consolidado y mantiene accesible el detalle de cada guía. La vista publica cantidad y números de guía, peso y cantidad total cuando existe evidencia completa, además de peso, cantidad, material y archivo origen por documento. Los faltantes se muestran como `No disponible`; no se infiere ni modifica evidencia.

Validaciones: 46/46 pruebas Desktop, prueba visual Electron y reportes históricos con 2, 3 y 5 documentos. Instalación activa: versión 1.2.0, commit `5acbed0e08e2a0547104c30c62b85fe0e5026e4e`, SHA-256 de `app.asar` `17ce3bb5e4cd257411fba7bcc817ee50016cc0602580e2995969c1428d3557e8`.

Siguiente bloque recomendado: calidad documental de peso y cantidad en la salida existente, preservando OCR y reglas congeladas, para ampliar los viajes cuyo total puede mostrarse sin inferencias.
