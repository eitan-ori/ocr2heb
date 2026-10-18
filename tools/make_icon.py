"""Generate assets/app.ico (blue rounded square with the Hebrew letter alef)."""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(__file__), "..", "assets", "app.ico")
FONTS = [
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/tahomabd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def main() -> int:
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, size - 8, size - 8), radius=56, fill=(25, 90, 170, 255))
    font = None
    for path in FONTS:
        if os.path.exists(path):
            font = ImageFont.truetype(path, 170)
            break
    if font is not None:
        bbox = d.textbbox((0, 0), "א", font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        d.text(((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1]), "א", font=font, fill=(255, 255, 255, 255))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon written:", os.path.abspath(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
