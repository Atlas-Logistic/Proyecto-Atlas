# Handoff — Auditoría de Cliente canónico 464089

## Resultado

No existe una regresión de publicación. La imagen dice `COMERCIAL A Y B LTDA`,
pero el OCR completo observa `COMERCIAL B LIDA`; la extracción entrega
`COMERCIAL` y no recupera el RUT `78.634.910-9`.

El Resolver recibe `COMERCIAL`/`No encontrado` y responde `NO_RESUELTO`, sin
valor canónico y con confianza 0,0. El catálogo activo tampoco contiene la
entidad documental. La Política PRODUCTIVO publica correctamente `COMERCIAL`,
que permanece idéntico en CSV, evidencia JSON y Desktop.

La publicación canónica correcta debe originarse en una confirmación trazable
del Resolver. Desktop debe continuar consumiendo el valor publicado, sin
consultar catálogos ni reconstruir identidad por su cuenta.
