# Ciclo de vida de pendientes y tarjetas (26/10/2026)

Diagnóstico: `C:\Atlas\pruebas\pendientes-diagnostico-20261026\DIAGNOSTICO.md`.

## Cambios

1. **Ejecutor de la cola técnica en este PC.** Tarea `Atlas Mantenimiento tecnico` cada 10 min con
   `ejecutar_mantenimiento_pendientes_tecnicos.ps1` (Motor de `C:\Atlas\Proyecto-Atlas`, su `.venv`, árbol limpio).
   `mantener_pendientes_tecnicos.py --tarea-programada`: plan sin escritor; sin elegibles no escribe; con una acción
   de B1 o decisión humana en curso, o el escritor ocupado (PULL), omite la pasada sin esperar. Máx. 10 guías por
   pasada. Log: `%LOCALAPPDATA%\AtlasMantenimientoTecnico\mantenimiento.log` (rota a 5 MB).
2. **Motivo vacío** (`clasificar_pendiente_tecnico`): el ruteo nunca se intentó → AGOTABLE (3 intentos, 30 min) y su
   primer intento puede consultar al proveedor; si los agota sin motivo, espera evidencia nueva (no anuncia una
   acción humana sin tarjeta). La obra ausente que bloquea el ruteo sigue esperando al humano.
3. **Motivo técnico obsoleto:** todo fallo transitorio del proveedor (también con prefijo
   `GEOCODIFICACION_SIN_CREDENCIAL`) se reemplaza por la respuesta real del reintento.
4. **Huellas del mantenimiento:** sólo se sellan en guías intentadas, con su estado posterior al intento; un cambio
   de conocimiento que no cupo en la pasada sigue elegible.
5. **Identidad documental de tarjetas** (`normalizar_identidad_documental`, al regenerar y en toda publicación):
   tarjetas Mobile publicadas como "original.jpg" toman `mobile/<envío>/<foto>` (si guía y transporte apuntan a una
   sola fila); tarjetas de una guía recuperada toman su número. Si la pregunta ya existe o ya fue respondida en el
   ledger, la antigua se retira. Mobile publica desde ya con el identificador canónico.
6. **Publicación focal:** con alcance causal, la regeneración sólo detecta preguntas nuevas de esas guías.
7. **Guía recuperada:** `DOCUMENTO_RECUPERAR_NUMERO_GUIA` reconcilia la bandeja de la guía.
8. **Capacidad GEOGRAFIA v5:** declara la convergencia de destinos confirmados (41f9d1b). Medido en copia: reactiva
   una vez los pendientes de ese dominio (10 por pasada); igual costo en PULL (13 s, 1 consulta) y en la
   reconciliación global.

Pruebas: `tests/test_pendientes_ciclo_vida.py`; ajustes en `test_ciclo_pendientes_tecnicos_simulado.py` (6b simula un
proveedor caído de verdad) y `test_b1_revision_tarjetas.py`.
