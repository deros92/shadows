"""Genera le icone dell'estensione da shadows.jpg.

Ritaglia la cornice dorata arrotondata, rende trasparente lo sfondo attorno e la
centra su una tela quadrata (la cornice non è quadrata: non va deformata).

    python tools/make_icons.py
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "shadows.jpg"
OUT = ROOT / "extension" / "icons"
SIZES = [16, 32, 48, 128]
LOGO = ROOT / "asset" / "logo.png"
LOGO_SIZE = 512
SUPERSAMPLE = 4  # maschera disegnata in grande per bordi arrotondati puliti


def frame_box(img: Image.Image) -> tuple[int, int, int, int]:
    """Riquadro della cornice dorata."""
    a = np.asarray(img.convert("RGB")).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    gold = (r > 170) & (g > 110) & (b < 110) & (r - b > 80)
    ys, xs = np.nonzero(gold)
    pad = 3
    return xs.min() - pad, ys.min() - pad, xs.max() + pad + 1, ys.max() + pad + 1


def main() -> None:
    src = Image.open(SOURCE).convert("RGBA")
    left, top, right, bottom = frame_box(src)
    crop = src.crop((left, top, right, bottom))
    w, h = crop.size

    radius = int(min(w, h) * 0.13)
    mask = Image.new("L", (w * SUPERSAMPLE, h * SUPERSAMPLE), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, w * SUPERSAMPLE - 1, h * SUPERSAMPLE - 1), radius=radius * SUPERSAMPLE, fill=255)
    crop.putalpha(mask.resize((w, h), Image.LANCZOS))

    side = max(w, h)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(crop, ((side - w) // 2, (side - h) // 2), crop)

    OUT.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        square.resize((size, size), Image.LANCZOS).save(OUT / f"icon{size}.png")
    # Versione grande per il README: abbastanza definita anche su schermi ad alta densità.
    LOGO.parent.mkdir(parents=True, exist_ok=True)
    square.resize((LOGO_SIZE, LOGO_SIZE), Image.LANCZOS).save(LOGO, optimize=True)
    print(f"cornice {w}x{h} -> icone {SIZES} in {OUT}, logo {LOGO_SIZE}px in {LOGO}")


if __name__ == "__main__":
    main()
