# Credenciales locales de Atlas

- Los secretos (API keys) son **locales por usuario de Windows / PC**.
- **Nunca** van en Git, en G: (Drive), en `config_usuario.json` ni en logs.
- Se registran **una vez por usuario/PC** (casa y oficina, cada uno una vez).
- Se guardan en `HKCU\Environment`. El Motor las resuelve con
  `atlas_core/atlas_ia/credenciales.py`: primero el entorno del proceso y,
  si falta, `HKCU\Environment` (así también las ve el Python que lanza Desktop).

## Registrar

Desde la carpeta `Proyecto-Atlas`, en una consola interactiva:

```
py -3 registrar_credencial.py TAVILY_API_KEY
```

El valor se pide sin mostrarlo; no se acepta como argumento. Después,
cerrar y volver a abrir Atlas Desktop.

Credenciales permitidas: `TAVILY_API_KEY`, `OPENROUTER_API_KEY`,
`GROQ_API_KEY` (`CREDENCIALES_PERMITIDAS` en `credenciales.py`).
