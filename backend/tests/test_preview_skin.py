import base64
import struct
import zlib

from tools.preview_skin import CLEAR, EYE, FACE, HAIR, SHIRT, TROUSERS, skin_pixel, synthetic_skin


def test_skin_pixels_follow_the_skin_layout():
    assert skin_pixel(0, 0) == HAIR
    assert skin_pixel(40, 4) == CLEAR
    assert skin_pixel(5, 11) == FACE
    assert skin_pixel(10, 11) == EYE
    assert skin_pixel(13, 11) == EYE
    assert skin_pixel(40, 12) == CLEAR
    assert skin_pixel(8, 20) == TROUSERS
    assert skin_pixel(20, 20) == SHIRT
    assert skin_pixel(20, 40) == CLEAR
    assert skin_pixel(20, 50) == TROUSERS
    assert skin_pixel(40, 50) == SHIRT
    assert skin_pixel(60, 50) == CLEAR


def test_synthetic_skin_is_a_64_pixel_png_of_those_pixels():
    prefix = "data:image/png;base64,"
    url = synthetic_skin()
    assert url.startswith(prefix)
    image = base64.b64decode(url.removeprefix(prefix))
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", image[16:24])
    assert (width, height) == (64, 64)
    start = image.index(b"IDAT") + 4
    length = struct.unpack(">I", image[start - 8 : start - 4])[0]
    rows = zlib.decompress(image[start : start + length])
    row = 1 + 64 * 4
    assert len(rows) == 64 * row
    assert rows[11 * row + 1 + 10 * 4 : 11 * row + 1 + 11 * 4] == bytes(EYE)
