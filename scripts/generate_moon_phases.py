"""Generate a smooth 33-frame lunar phase sequence from the supplied moon photo."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "assets" / "moon-reference.png"
OUTPUT_DIR = ROOT / "assets" / "moon-phases"
FRAME_COUNT = 33
SIZE = 512


def phase_mask(size: int, ratio: float) -> Image.Image:
    """Create a feathered illumination mask without cropping the lunar surface."""

    center = (size - 1) / 2.0
    radius = size * 0.47
    feather = max(2.0, size * 0.014)
    terminator = math.cos(math.pi * max(0.02, min(1.0, ratio)))
    values = []

    for y in range(size):
        normalized_y = (y - center) / radius
        half_width = math.sqrt(max(0.0, 1.0 - normalized_y * normalized_y)) * radius
        threshold = center + terminator * half_width
        for x in range(size):
            distance = math.sqrt((x - center) ** 2 + (y - center) ** 2)
            if distance > radius:
                values.append(0)
                continue
            if ratio >= 0.999:
                illumination = 1.0
            else:
                transition = 0.5 + 0.5 * math.tanh((x - threshold) / feather)
                # A very faint earthshine keeps the dark side subtly present.
                illumination = 0.08 + 0.92 * transition
            values.append(int(255 * illumination))

    mask = Image.new("L", (size, size), 0)
    mask.putdata(values)
    return mask


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    source = Image.open(SOURCE_PATH).convert("RGB")
    source = ImageOps.contain(source, (SIZE, SIZE), method=Image.Resampling.LANCZOS)
    source = ImageEnhance.Contrast(source).enhance(1.12)
    source = ImageEnhance.Brightness(source).enhance(1.05)

    source_alpha = ImageOps.grayscale(source).point(
        lambda value: 0 if value < 10 else min(255, (value - 10) * 10)
    )
    source_alpha = source_alpha.filter(ImageFilter.GaussianBlur(1.2))

    for index in range(FRAME_COUNT):
        ratio = max(0.02, index / (FRAME_COUNT - 1))
        alpha = ImageChops.multiply(source_alpha, phase_mask(SIZE, ratio))
        frame = source.convert("RGBA")
        frame.putalpha(alpha)
        frame.save(OUTPUT_DIR / "moon-{:02d}.png".format(index), optimize=True)

    print("generated {} moon frames in {}".format(FRAME_COUNT, OUTPUT_DIR))


if __name__ == "__main__":
    main()
