"""Generates build/icon.ico (+ icon.png) from the FINORA mark used in the app header.

Run: python scripts/make-icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build"
SIZE = 1024
MAROON = (122, 31, 61)
VIOLET = (96, 52, 214)


def gradient(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(MAROON, VIOLET))
    return img


def main() -> None:
    OUT.mkdir(exist_ok=True)
    base = gradient(SIZE).convert("RGBA")
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((24, 24, SIZE - 24, SIZE - 24), radius=270, fill=255)
    icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    icon.paste(base, (0, 0), mask)

    # The "F" from the header logo (40×40 viewBox scaled to 1024).
    draw = ImageDraw.Draw(icon)
    s = SIZE / 40
    width = round(4.4 * s)
    draw.line([(14 * s, 29 * s), (14 * s, 12.5 * s), (27.5 * s, 12.5 * s)], fill="white", width=width, joint="curve")
    draw.line([(14 * s, 20.5 * s), (23.5 * s, 20.5 * s)], fill=(255, 255, 255, 215), width=width)
    for cx, cy in [(14 * s, 29 * s), (27.5 * s, 12.5 * s), (23.5 * s, 20.5 * s)]:
        r = width / 2
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill="white")

    icon.save(OUT / "icon.png")
    icon.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote build/icon.ico")


if __name__ == "__main__":
    main()
