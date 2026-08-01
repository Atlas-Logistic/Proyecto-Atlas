# Contrato de conteos de identidad de choferes

El manifiesto `atlas-catalogos-manifiesto-v2` separa estas métricas:

- `nombres_canonicos`: valores no vacíos del campo `nombre`; uno por identidad.
- `aliases_explicitos_total`: valores no vacíos realmente almacenados en las
  listas `aliases`, antes de deduplicar.
- `aliases_explicitos_unicos_literal`: alias explícitos distintos byte a byte.
- `aliases_explicitos_unicos_normalizados`: alias explícitos distintos después
  de aplicar la misma normalización de acentos, mayúsculas y espacios del fuzzy.
- `aliases_explicitos_colisiones_normalizadas`: repeticiones que sólo aparecen
  después de normalizar.
- `aliases_normalizados_que_coinciden_con_canonico_activo`: alias cuya forma
  normalizada ya es el nombre canónico de alguna identidad activa.
- `variantes_normalizadas_generadas`: valores canónicos o alias cuya forma
  normalizada difiere de la forma almacenada. No son alias nuevos.
- `variantes_fuzzy_activas_total`: nombres canónicos y alias explícitos de
  choferes activos que el fuzzy recorre.
- `variantes_fuzzy_activas_unicas_normalizadas`: espacio efectivo de variantes
  activas después de normalizar y deduplicar.
- `aliases_utilizables_fuzzy_unicos_normalizados`: alias activos normalizados
  que añaden una variante distinta de todos los nombres canónicos activos.

Un nombre canónico nunca se cuenta como alias. La ausencia de alias tampoco
genera un alias implícito. Los registros inactivos permanecen auditables, pero
sus nombres y alias no forman parte del espacio fuzzy activo.

La cifra histórica 54 mezcló categorías: 41 alias explícitos más los 13 nombres
canónicos de registros que no tenían alias. Esa suma híbrida no representa
alias almacenados ni variantes fuzzy y queda eliminada del contrato.

La auditoría nominal con identificadores y nombres reales se conserva fuera de
Git dentro de la carpeta privada de preparación de Atlas.
