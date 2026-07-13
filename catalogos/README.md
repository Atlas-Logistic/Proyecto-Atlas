# Catálogos maestros

Esta carpeta contiene plantillas ficticias para los catálogos locales usados por Atlas:

- `empresas.example.json`: relaciona el RUT de una empresa con su nombre y código de cliente.
- `destinos.example.json`: relaciona un código de destinatario con el nombre del destino y el RUT de su empresa.
- `choferes.example.json`: relaciona el RUT de un chofer con su nombre.
- `vehiculos.example.json`: relaciona una patente con el tipo de vehículo.

Para crear los catálogos locales, copie las plantillas y quite `.example` del nombre. Por ejemplo, copie `empresas.example.json` como `empresas.json`.

Los archivos sin `.example` contienen datos reales y privados. Deben mantenerse únicamente en el entorno local y no deben subirse a GitHub. `.gitignore` excluye específicamente esos cuatro archivos reales.

## Formato de claves

- Los RUT se guardan sin puntos, espacios ni guion, con el dígito verificador `K` en mayúscula. Ejemplo ficticio: `11111111K`.
- Las patentes se guardan sin espacios y en mayúsculas. Ejemplo ficticio: `ABCD12`.
- Los códigos de destinatario se guardan como las claves del catálogo de destinos.
