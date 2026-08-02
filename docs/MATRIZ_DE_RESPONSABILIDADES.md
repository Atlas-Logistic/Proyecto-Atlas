# Matriz de Responsabilidades

## Objetivo
Definir de forma breve y formal el rol de cada herramienta que participa en el desarrollo de Atlas, para evitar solapamientos y mantener una coordinación clara.

## 1. ChatGPT
Responsable de:
- Arquitectura general del sistema.
- Dirección técnica del proyecto.
- Priorización de bloques y decisiones estratégicas.
- Aprobación técnica de cierres de bloque.
- Decisión final sobre la continuidad o cierre de una iteración.

## 2. GitHub Copilot Pro
Responsable de:
- Implementación de cambios autorizados.
- Refactorizaciones técnicas dentro del alcance aprobado.
- Ejecución de pruebas relevantes.
- Integración técnica local y manejo de Git.
- Actualización de bitácoras cuando el cierre de bloque lo requiera.

## 3. Claude Code
Responsable de:
- Auditorías independientes del trabajo realizado.
- Investigación de problemas complejos o riesgos técnicos.
- Validación de arquitectura y coherencia del diseño.
- Segunda opinión técnica antes de cerrar un bloque.

## Flujo oficial de trabajo
1. ChatGPT define la prioridad, la estrategia y la aprobación técnica.
2. GitHub Copilot Pro implementa, prueba e integra los cambios.
3. Claude Code revisa de forma independiente el resultado.
4. ChatGPT valida el cierre del bloque y decide si el estado es aceptable.

## Responsabilidades compartidas
- Mantener el estado del proyecto coherente y auditable.
- Respetar la política conservadora y evitar cambios no autorizados.
- Registrar decisiones y cierres en la documentación del proyecto.

## Decisiones que requieren coordinación entre herramientas
- Cambios de arquitectura.
- Cambios de política de decisión del motor.
- Cierres de bloque con impacto técnico relevante.
- Cambios que afecten la calidad de lectura, la trazabilidad o la seguridad del flujo.

## Tareas que puede ejecutar cada herramienta sin autorización adicional
- ChatGPT: definir estrategia, priorizar bloques y aprobar cierres técnicos.
- GitHub Copilot Pro: implementar cambios, correr pruebas, actualizar documentación técnica y gestionar Git local.
- Claude Code: auditar, investigar problemas y validar diseño.

## Situaciones que requieren aprobación explícita del usuario
- Cambios que modifiquen el alcance del proyecto.
- Cambios que afecten datos reales, flujos de producción o contratos externos.
- Integraciones, merges o publicaciones remotas.
- Cambios que alteren la política de decisión de forma no trivial.

## Referencia oficial del proyecto
- [docs/BITACORA_EJECUTIVA.md](docs/BITACORA_EJECUTIVA.md)
- [docs/BITACORA_TECNICA_CRONOLOGICA.md](docs/BITACORA_TECNICA_CRONOLOGICA.md)
