from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
FONT_DIR = ROOT / "assets" / "fonts"
OUT = ROOT / "assets" / "font-preview.png"

FONTS = [
    ("Inter", FONT_DIR / "Inter.ttf"),
    ("Nunito Sans", FONT_DIR / "NunitoSans.ttf"),
    ("Montserrat", FONT_DIR / "Montserrat.ttf"),
    ("Manrope", FONT_DIR / "Manrope.ttf"),
]


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size=size)


def rounded(draw: ImageDraw.ImageDraw, xy, radius: int, fill, outline=None, width=1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def draw_card(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, name: str, path: Path) -> None:
    rounded(draw, (x, y, x + w, y + h), 14, "#10141a", "#242b36", 2)
    draw.text((x + 28, y + 24), name, fill="#f4f6fa", font=font(path, 34))
    draw.text(
        (x + 28, y + 67),
        "Aerial PDF capture for New Castle County parcels",
        fill="#9aa3af",
        font=font(path, 17),
    )

    rounded(draw, (x + 28, y + 120, x + w - 28, y + 262), 8, "#151a22", "#29313d", 1)
    draw.text((x + 52, y + 144), "Parcel number", fill="#d9dee7", font=font(path, 16))
    rounded(draw, (x + 210, y + 134, x + w - 52, y + 178), 7, "#0b0e13", "#2b333f", 1)
    draw.text((x + 229, y + 145), "07-046.40-077", fill="#eef2f8", font=font(path, 17))
    draw.text(
        (x + 210, y + 190),
        "Punctuation is okay. The app cleans the number before searching.",
        fill="#828b98",
        font=font(path, 13),
    )
    draw.text((x + 52, y + 229), "Destination folder", fill="#d9dee7", font=font(path, 16))
    rounded(draw, (x + 210, y + 218, x + w - 170, y + 262), 7, "#0b0e13", "#2b333f", 1)
    draw.text((x + 229, y + 230), "D:/TEST/PARCEL PACKET", fill="#eef2f8", font=font(path, 16))
    rounded(draw, (x + w - 154, y + 218, x + w - 52, y + 262), 7, "#252b34", None, 1)
    draw.text((x + w - 132, y + 230), "Browse", fill="#edf1f7", font=font(path, 15))

    rounded(draw, (x + 28, y + 286, x + w - 28, y + 420), 8, "#11161d", "#252d38", 1)
    draw.text((x + 52, y + 310), "Turning on aerial image", fill="#edf0f5", font=font(path, 17))
    draw.text((x + 52, y + 348), "Opening parcel search", fill="#c7ced9", font=font(path, 14))
    draw.text((x + 52, y + 375), "Opening map", fill="#c7ced9", font=font(path, 14))

    rounded(draw, (x + w - 220, y + 446, x + w - 52, y + 492), 7, "#e8edf7", None, 1)
    draw.text((x + w - 194, y + 459), "Save Aerial PDF", fill="#0d1117", font=font(path, 15))


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1800, 1280), "#090b0f")
    draw = ImageDraw.Draw(image)
    draw.text((58, 42), "Font comparison", fill="#ffffff", font=font(FONTS[0][1], 44))
    draw.text(
        (60, 98),
        "Same app text rendered in each candidate font",
        fill="#9aa3af",
        font=font(FONTS[0][1], 22),
    )
    positions = [(60, 160), (930, 160), (60, 720), (930, 720)]
    for (name, path), (x, y) in zip(FONTS, positions):
        draw_card(draw, x, y, 810, 520, name, path)
    image.save(OUT, quality=95)
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
