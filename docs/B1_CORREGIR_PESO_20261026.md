# B1 — Corrección de peso de una guía (26/10/2026)

Javier corrige el peso de una guía desde Desktop (B1 · Atlas), sin intervención técnica:

> En la guía 482816 el peso correcto es 12.450 kg

## Flujo

1. **Interpretación determinista** (`b1_operador._PESO_GUIA`). Frases aceptadas:
   «en la guía N el peso (correcto|real) es X», «el peso (correcto) de la guía N es (de) X»,
   «peso de la guía N: X», «corrige/cambia/fija el peso de la guía N a/por X»,
   «la guía N pesa X», «la guía N tiene un peso de X». Las preguntas nunca son correcciones.
2. **Valor** (`_peso_kg_declarado`): sólo kilos enteros, con punto de miles en grupos de 3
   y unidad opcional kg/kilos/kilogramos (`12.450 kg`, `12450`). Se rechaza sin preview
   lo ambiguo o inválido: coma, decimales, toneladas, ceros, texto, > 100.000 kg.
3. **Preview** con la acción existente `DOCUMENTO_CORREGIR_CAMPO` (`campo=peso_kg`):
   guía, transporte, peso actual y propuesto. La entidad identifica el documento exacto
   (`entidad.id` = archivo) y Desktop ofrece «Ver guía N» con el visor existente.
   La guía ambigua (más de un documento) o inexistente se rechaza.
4. **Confirmación explícita** («sí» / botón): sin ella no se escribe nada; «no» descarta.
5. **Escritura** por `reparar_documento_focal_con_valores_conocidos` (respaldo focal,
   lock, huella del preview): sólo `peso_kg` y los motivos del peso anterior
   (`PESO_OPERACIONALMENTE_ATIPICO`, `PESO_CORREGIDO_POR_BAJA_CONFIANZA_OCR`). Si el peso
   nuevo también es atípico (< 150 o > 45.000 kg) la advertencia se mantiene.
   Material, chofer, RUT, patentes, cliente, destino, ruta, kilómetros y agrupaciones no cambian.
6. **Decisión humana**: ledger `decisiones_aplicadas.json`, tipo
   `CORRECCION_DOCUMENTAL_OPERADOR`, con valor documental, valor corregido,
   `confirmado_por` (operador de Desktop) y la instrucción literal. Auditoría en
   `acciones_operacionales.json`.
7. **Tarjetas**: se retiran sólo las que preguntaban por el peso anterior de esa guía;
   se reconcilia la bandeja y se regenera el reporte. Las demás decisiones siguen.

## Persistencia

Reproceso por lote, reexamen de peso, relectura OCR de la guía y el reparador consultan
el ledger (`_hay_decision_humana_para_campo`), por lo que el peso confirmado no se
reemplaza. Una nueva corrección humana sí lo reemplaza y queda también registrada.
Una decisión de Revisión que ya fijó el peso bloquea la corrección por B1
(`CAMPO_FIJADO_POR_DECISION_HUMANA`): se corrige desde esa decisión.

Pruebas: `tests/test_b1_corregir_peso.py` (sintéticas) y
`Atlas-Viajes-Desktop/test/b1_corregir_peso.test.js` (render del preview).
