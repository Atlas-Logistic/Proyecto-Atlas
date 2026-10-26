# Carga de licencias desde Desktop

El operador abre la ficha de un chofer y usa **Adjuntar licencia** o
**Reemplazar licencia**. Indica clase y vencimiento; el selector nativo de
Desktop limita la selección a PDF, JPG, JPEG o PNG. El renderer nunca recibe
ni entrega la ruta del archivo seleccionado.

`registrar_licencia_chofer.py` se ejecuta dentro de la sesión oficial de
escritura. El Motor comprueba UUID de ficha y referencia vigente del catálogo,
sin modificar ese catálogo. Valida fecha, clase, extensión, tamaño máximo de
20 MB y firma binaria del archivo. Copia el archivo con un UUID nuevo a:

`fichas_digitales/<EMPRESA>/archivos/choferes/<FICHA_UUID>/<DOCUMENTO_UUID>.<ext>`

No conserva el nombre de origen y nunca reemplaza un adjunto existente. Guarda
hash SHA-256, tamaño, clase, vencimiento y fecha. Al renovar, marca los
documentos de licencia previos con `reemplazado_por`, conserva sus bytes y
registra `LICENCIA_REEMPLAZADA` en el historial de la ficha. Cada escritura
respalda el JSON previo y su manifiesto bajo `respaldos/fichas_choferes/`.

La empresa se fija en backend como `MBT`; el archivo y la ficha deben declarar
la misma empresa. Las rutas se validan al leer y abrir, por lo que un archivo
o junction fuera de la empresa no se expone.

No hay envío Mobile en este incremento. Para habilitarlo se necesita un canal
de captura Mobile separado que use el mismo escritor, identidad de ficha y
protocolo de carga reanudable; no debe aceptar ni publicar una ruta local.
