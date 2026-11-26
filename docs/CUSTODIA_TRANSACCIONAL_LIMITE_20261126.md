# Custodia transaccional: hallazgo de expiración

Prueba aislada sobre b0b42e4. El objeto LeaseEscritorOperativo puede seguir indicando `vigente` cuando Cloud ya ha vencido el token y antes de que el heartbeat observe el fallo. El Worker simulado rechaza la confirmación con token vencido; renovar marca la pérdida local. La prueba documenta el límite existente, no demuestra una solución.

Cualquier recuperación que modifique Drive antes de una publicación Cloud cercada por token y versión conserva una ventana frente a un escritor posterior. La confirmación Cloud de un lote valida token y versión, pero confirmar varios lotes no constituye una transacción conjunta. Se debe verificar el Worker efectivamente desplegado, preservar un estado durable de recuperación y probar cortes, competidores y cambios externos antes de instalar. La posibilidad de publicar una sola marca para los seis objetos sin modificar la copia activa merece validación, no autoriza confirmar diferencias desconocidas ni ignorar el diario pendiente de OFICINA. El estado de ese diario y la copia remota Drive aún no se han verificado independientemente.

No se implementó una solución, no instalar esta rama.
