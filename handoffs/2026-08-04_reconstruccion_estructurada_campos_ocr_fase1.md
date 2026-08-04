# Handoff — Reconstrucción Estructurada de Campos OCR, Fase 1

Atlas reconstruye ahora campos tipados cuando etiqueta y valor aparecen en
cajas OCR separadas. El mecanismo es geométrico, parametrizable y conservador:
proximidad, alineación, tipo exacto, unicidad y abstención ante conflicto o cruce
de otra etiqueta.

Código Cliente, código Destinatario, número SAP y número Transporte comparten el
contrato reutilizable. Sólo el código Destinatario se integra en este bloque y
únicamente contra un maestro exacto, activo y confirmado.

464106, 463528 y 464110 publican `VISTA CLARA 2351`. La ruta real 464106 queda
`CALCULADA`: 16,7 km y 25 min desde AZA RENCA; Desktop la formatea como
`Calculada`. 463528 sigue pendiente por origen
ausente. Regresión: 1160 Atlas y 49 Desktop.

Próximo bloque: recuperación estructurada del origen de 463528.
