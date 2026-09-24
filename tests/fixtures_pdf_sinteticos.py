"""Constructor mínimo de PDFs SINTÉTICOS para las pruebas del soporte PDF.

Escribe la sintaxis PDF a mano (objetos + xref) para no depender de ninguna
librería que genere PDFs: Atlas sólo LEE PDFs (pypdfium2) y no debe arrastrar
un escritor de PDF sólo por las pruebas. Cubre exactamente lo que las pruebas
necesitan: texto Helvetica/WinAnsi (tildes, ñ, °), imagen JPEG a página
completa (página "escaneada", como un PDF armado desde fotos), texto
invisible (modo de render 3), rotación, tamaño de página, JavaScript de
apertura, adjunto, enlace, y cifrado estándar RC4 (R2) con contraseña de
usuario y/o de propietario. Nunca contiene datos reales.
"""
from __future__ import annotations

import hashlib
import io
import struct
from dataclasses import dataclass, field

from PIL import Image, ImageDraw

_RELLENO_CLAVE = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")


@dataclass
class PaginaSintetica:
    lineas: list[str] = field(default_factory=list)  # texto visible, 20 pt entre líneas desde (72, 72)
    invisibles: list[str] = field(default_factory=list)  # texto con modo de render 3
    imagen_jpeg: bytes | None = None  # imagen a página completa (debajo del texto)
    ancho: float = 595
    alto: float = 842
    rotacion: int = 0
    enlace_uri: str | None = None


def jpeg_escaneado(texto: str, tamano: tuple[int, int] = (800, 1000)) -> bytes:
    imagen = Image.new("RGB", tamano, "white")
    ImageDraw.Draw(imagen).text((60, 60), texto, fill="black")
    salida = io.BytesIO()
    imagen.save(salida, format="JPEG", quality=90)
    return salida.getvalue()


def pagina_texto(*lineas: str, **extra) -> PaginaSintetica:
    return PaginaSintetica(lineas=list(lineas), **extra)


def pagina_escaneada(texto: str = "GUIA ESCANEADA", *, capa_invisible: str | None = None) -> PaginaSintetica:
    return PaginaSintetica(
        imagen_jpeg=jpeg_escaneado(texto),
        invisibles=[capa_invisible] if capa_invisible else [],
    )


def _rc4(clave: bytes, datos: bytes) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + clave[i % len(clave)]) % 256
        s[i], s[j] = s[j], s[i]
    i = j = 0
    salida = bytearray()
    for byte in datos:
        i = (i + 1) % 256
        j = (j + s[i]) % 256
        s[i], s[j] = s[j], s[i]
        salida.append(byte ^ s[(s[i] + s[j]) % 256])
    return bytes(salida)


def _rellenar(clave: str) -> bytes:
    return (clave.encode("latin-1") + _RELLENO_CLAVE)[:32]


def _texto_hex(texto: str) -> str:
    return "<" + texto.encode("cp1252").hex() + ">"


def construir_pdf(
    paginas: list[PaginaSintetica],
    *,
    javascript_apertura: str | None = None,
    adjunto: tuple[str, bytes] | None = None,
    contrasena_usuario: str | None = None,
    contrasena_propietario: str | None = None,
    permisos: int = -4,
) -> bytes:
    """PDF válido con xref. Cifrado RC4-40 (R2) si se da alguna contraseña:
    con `contrasena_usuario` hace falta para abrirlo; sólo con
    `contrasena_propietario` se abre sin contraseña (sólo restringe permisos)."""
    objetos: list[bytes | None] = [None]  # índice = número de objeto
    flujos: set[int] = set()

    def nuevo(contenido: bytes = b"", *, flujo: bool = False) -> int:
        objetos.append(contenido)
        if flujo:
            flujos.add(len(objetos) - 1)
        return len(objetos) - 1

    catalogo = nuevo()
    arbol_paginas = nuevo()
    fuente = nuevo(b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>")
    hijos = []
    for pagina in paginas:
        ops = []
        recursos_img = b""
        if pagina.imagen_jpeg is not None:
            ancho_px, alto_px = Image.open(io.BytesIO(pagina.imagen_jpeg)).size
            imagen = nuevo(
                b"<</Type/XObject/Subtype/Image/Width %d/Height %d/ColorSpace/DeviceRGB/BitsPerComponent 8"
                b"/Filter/DCTDecode/Length %d>>stream\n" % (ancho_px, alto_px, len(pagina.imagen_jpeg))
                + pagina.imagen_jpeg + b"\nendstream",
                flujo=True,
            )
            recursos_img = b"/XObject<</Im0 %d 0 R>>" % imagen
            ops.append(f"q {pagina.ancho:g} 0 0 {pagina.alto:g} 0 0 cm /Im0 Do Q")
        for modo, lineas in ((0, pagina.lineas), (3, pagina.invisibles)):
            for indice, linea in enumerate(lineas):
                y = pagina.alto - 72 - 20 * indice
                ops.append(f"BT /F1 11 Tf {modo} Tr 72 {y:g} Td {_texto_hex(linea)} Tj ET")
        cuerpo = "\n".join(ops).encode("latin-1")
        contenido = nuevo(b"<</Length %d>>stream\n" % len(cuerpo) + cuerpo + b"\nendstream", flujo=True)
        anotaciones = b""
        if pagina.enlace_uri:
            enlace = nuevo(
                b"<</Type/Annot/Subtype/Link/Rect[0 0 50 50]/Border[0 0 0]/A<</S/URI/URI("
                + pagina.enlace_uri.encode("latin-1") + b")>>>>"
            )
            anotaciones = b"/Annots[%d 0 R]" % enlace
        rotacion = b"/Rotate %d" % pagina.rotacion if pagina.rotacion else b""
        hijos.append(nuevo(
            b"<</Type/Page/Parent %d 0 R/MediaBox[0 0 %s %s]%s/Resources<</Font<</F1 %d 0 R>>%s>>/Contents %d 0 R%s>>"
            % (arbol_paginas, f"{pagina.ancho:g}".encode(), f"{pagina.alto:g}".encode(), rotacion,
               fuente, recursos_img, contenido, anotaciones)
        ))
    objetos[arbol_paginas] = b"<</Type/Pages/Kids[%s]/Count %d>>" % (
        b" ".join(b"%d 0 R" % h for h in hijos), len(hijos),
    )
    extras = b""
    if javascript_apertura:
        extras += b"/OpenAction<</S/JavaScript/JS(" + javascript_apertura.encode("latin-1") + b")>>"
    if adjunto:
        nombre, datos = adjunto
        archivo = nuevo(b"<</Type/EmbeddedFile/Length %d>>stream\n" % len(datos) + datos + b"\nendstream", flujo=True)
        especificacion = nuevo(b"<</Type/Filespec/F(" + nombre.encode("latin-1") + b")/EF<</F %d 0 R>>>>" % archivo)
        extras += b"/Names<</EmbeddedFiles<</Names[(" + nombre.encode("latin-1") + b") %d 0 R]>>>>" % especificacion
    objetos[catalogo] = b"<</Type/Catalog/Pages %d 0 R%s>>" % (arbol_paginas, extras)

    identificador = hashlib.md5(b"atlas-sintetico" + bytes(len(objetos))).digest()
    trailer_extra = b""
    if contrasena_usuario is not None or contrasena_propietario is not None:
        usuario = contrasena_usuario or ""
        propietario = contrasena_propietario or usuario
        clave_o = hashlib.md5(_rellenar(propietario)).digest()[:5]
        valor_o = _rc4(clave_o, _rellenar(usuario))
        clave = hashlib.md5(_rellenar(usuario) + valor_o + struct.pack("<i", permisos) + identificador).digest()[:5]
        valor_u = _rc4(clave, _RELLENO_CLAVE)
        for numero in flujos:
            cabecera, _, resto = objetos[numero].partition(b"stream\n")
            datos = resto[: -len(b"\nendstream")]
            clave_obj = hashlib.md5(clave + numero.to_bytes(3, "little") + b"\x00\x00").digest()[:10]
            objetos[numero] = cabecera + b"stream\n" + _rc4(clave_obj, datos) + b"\nendstream"
        cifrado = nuevo(
            b"<</Filter/Standard/V 1/R 2/O<%s>/U<%s>/P %d>>" % (valor_o.hex().encode(), valor_u.hex().encode(), permisos)
        )
        trailer_extra = b"/Encrypt %d 0 R" % cifrado

    salida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    desplazamientos = [0]
    for numero in range(1, len(objetos)):
        desplazamientos.append(len(salida))
        salida += b"%d 0 obj\n" % numero + objetos[numero] + b"\nendobj\n"
    inicio_xref = len(salida)
    salida += b"xref\n0 %d\n0000000000 65535 f \n" % len(objetos)
    for desplazamiento in desplazamientos[1:]:
        salida += b"%010d 00000 n \n" % desplazamiento
    salida += (
        b"trailer\n<</Size %d/Root %d 0 R/ID[<%s><%s>]%s>>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objetos), catalogo, identificador.hex().encode(), identificador.hex().encode(), trailer_extra, inicio_xref)
    )
    return bytes(salida)
