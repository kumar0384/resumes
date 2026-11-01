"""Resume photo handling.

Photos are cropped to the standard 7:9 portrait ratio (35 x 45 mm, as used
for German Bewerbungsfotos and passport-style headshots), downsized, and
stored inside the resume JSON as base64 JPEG so the file stays portable.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

RATIO = 7 / 9                     # width / height
SIZE = (420, 540)                 # stored pixels; prints sharply at ~1 x 1.3 in
FACE_BIAS = 0.3                   # when trimming height, keep more of the top


def load(path: str | Path) -> str:
    """Read an image file and return a cropped, resized base64 JPEG."""
    from PIL import Image, ImageOps

    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, "white")
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        w, h = im.size
        if w / h > RATIO:                         # too wide: trim sides evenly
            new_w = round(h * RATIO)
            left = (w - new_w) // 2
            im = im.crop((left, 0, left + new_w, h))
        else:                                     # too tall: trim, favouring the top
            new_h = round(w / RATIO)
            top = round((h - new_h) * FACE_BIAS)
            im = im.crop((0, top, w, top + new_h))
        im = im.resize(SIZE, Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode("ascii")


SHOT_MAX = 1920                   # longest side kept for screenshots (sharp when enlarged)


def load_screenshot(path: str | Path, max_side: int = SHOT_MAX) -> str:
    """Read a project screenshot, keep its aspect ratio, return base64 PNG or JPEG.

    UI screenshots are mostly flat colour and text, which JPEG blurs, so PNG is
    kept when it isn't much bigger than a high-quality JPEG; photos and renders
    (where PNG is huge) are stored as JPEG.
    """
    from PIL import Image, ImageOps

    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, "white")
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        scale = max_side / max(im.size)
        if scale < 1:
            im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
        png, jpg = io.BytesIO(), io.BytesIO()
        im.save(png, "PNG", optimize=True)
        im.save(jpg, "JPEG", quality=90, subsampling=0)
    best = png if png.tell() <= 1.6 * jpg.tell() and png.tell() < 2_500_000 else jpg
    return base64.b64encode(best.getvalue()).decode("ascii")


def mime(data: str) -> str:
    """Image type of stored base64 data (or a data: URI)."""
    if data.startswith("data:"):
        return data[5:data.index(";")]
    head = data[:8]
    if head.startswith("iVBOR"):
        return "image/png"
    if head.startswith("R0lGOD"):
        return "image/gif"
    if head.startswith("UklGR"):
        return "image/webp"
    return "image/jpeg"


def extension(data: str) -> str:
    return {"image/png": "png", "image/gif": "gif", "image/webp": "webp"}.get(mime(data), "jpg")


def size_of(data: str) -> tuple[int, int]:
    return to_image(data).size


def to_bytes(data: str) -> bytes:
    """Decode a stored photo; accepts plain base64 or a data: URI."""
    if data.startswith("data:"):
        data = data.split(",", 1)[1]
    return base64.b64decode(data)


def to_image(data: str):
    from PIL import Image
    return Image.open(io.BytesIO(to_bytes(data)))


def data_uri(data: str) -> str:
    return data if data.startswith("data:") else f"data:{mime(data)};base64,{data}"


def is_valid(data: str) -> bool:
    if not data:
        return False
    try:
        to_image(data).verify()
        return True
    except Exception:  # noqa: BLE001 - any decode failure means "not usable"
        return False
