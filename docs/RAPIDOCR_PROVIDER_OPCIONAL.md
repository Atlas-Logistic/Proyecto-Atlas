# RapidOCRProvider opcional

RapidOCR es un proveedor OCR opcional de CPU. No se activa por defecto: si
`ATLAS_OCR_PROVIDER` no existe, Atlas conserva `paddleocr`; `easyocr` y el
fallback actual no cambian.

## Preparación aislada

Crear un entorno virtual dedicado fuera del entorno principal de Atlas e
instalar `requirements-rapidocr-optional.txt`. Configurar su intérprete de
forma explícita junto con el proveedor:

```powershell
$env:ATLAS_OCR_PROVIDER = "rapidocr"
$env:ATLAS_RAPIDOCR_PYTHON = "C:\ruta\al\venv-rapidocr\Scripts\python.exe"
```

En la oficina el runtime dedicado está en
`%LOCALAPPDATA%\Atlas\runtime\rapidocr` (mismo criterio que
`runtime\paddleocr`).

`crear_proveedor_ocr()` sin argumento lee `ATLAS_OCR_PROVIDER`, así que la
selección vale igual para el PULL y para la ingesta de Desktop
(`analizar_guias_masivo.py`). Desktop hereda el entorno de su propio proceso:
para una prueba basta definir las variables sólo en la sesión desde la que se
lanza Desktop, nunca a nivel de usuario o máquina (la tarea PULL las heredaría).

Sin esa selección explícita, RapidOCR no se inicia. Si se selecciona pero el
worker o sus dependencias fallan, Atlas informa `ProveedorOCRNoDisponible`; no
modifica la preferencia ni cambia silenciosamente a otro proveedor.

## Contrato y evidencia

`RapidOCRProvider` implementa el `ProveedorOCR` existente y ejecuta ONNX
Runtime en `rapidocr_worker.py`, un proceso separado. El worker aplica
`ImageOps.exif_transpose` antes de inferir, por lo que texto y cajas se
entregan en la misma referencia documental. El adaptador conserva en memoria
el texto crudo, la caja, confianza y texto segmentado de la última lectura.

Sólo separa un delimitador inicial `:` o `：`; no corrige caracteres OCR ni
valores. Los resultados pasan luego por el extractor y los validadores
canónicos de Atlas. La traza está en memoria y no contiene escrituras
operacionales; quien habilite una persistencia de evidencia debe usar los
mecanismos opt-in existentes y sus políticas de privacidad.

## Estado

La implementación está disponible en la rama `feat/rapidocr-optional-provider`
para pruebas controladas. No constituye activación por defecto ni despliegue.
La rama `fix/rapidocr-operativa` añade la selección por entorno sin argumento
para el camino Desktop; sin `ATLAS_OCR_PROVIDER` el comportamiento es el mismo.
