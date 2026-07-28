# Piloto real controlado de destinos

Este directorio contiene una muestra de 12 destinos confirmados documentalmente,
congelada antes de consultar OpenRouteService.

## Orden seguro

1. `python piloto_real_destinos.py preparar`
2. Verificar `hashes_preconsulta.json`.
3. Con credencial presente y autorización explícita:
   `python piloto_real_destinos.py ejecutar`
4. Para reproducir sin red:
   `python piloto_real_destinos.py reproducir`

La reproducción usa exclusivamente `respuestas_ors_congeladas.json`. La segunda
pasada usa el caché en memoria y debe registrar cero consultas nuevas.

## Privacidad

Las consultas contienen únicamente dirección, comuna, región y país. No contienen
cliente, RUT, chofer, patente, guía, transporte, imagen ni clave. Las respuestas
congeladas no incluyen cabeceras HTTP ni credenciales.

## Interpretación

La verificación externa es evidencia y nunca sobrescribe el Ground Truth. Las
coordenadas no se incorporan a catálogos. El resultado `APTO PARA INTEGRACIÓN
OPCIONAL EN MODO REVISIÓN` no autoriza modificaciones automáticas.

El caso `REAL-004` usa `VISTA CLARA 2351`. El valor 2401 está documentado como
incorrecto. Una respuesta sin el número 2351 o con otra numeración debe revisarse.

Los casos sintéticos `DEST-059`–`DEST-064` y la precedencia
`CONSULTA_NO_AUTORIZADA`/`DATOS_INSUFICIENTES` permanecen separados y no afectan
las métricas de este piloto real.

## Reprocesamiento con normalización geográfica

La rama `mejora-normalizacion-geografica-destinos` vuelve a procesar exactamente
las mismas respuestas congeladas. `comparacion_antes_despues.csv` y
`metricas_antes_despues.json` documentan el cambio sin consultas externas.

La capa reconoce únicamente alias controlados de Región Metropolitana, separa
calle, número y geografía, y mantiene en revisión calles sin número, comunas
contradictorias y respuestas con varios candidatos.
