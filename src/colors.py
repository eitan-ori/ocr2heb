"""Background colour sampling so the translated box blends with what it covers."""
from __future__ import annotations

from typing import Tuple

RGB = Tuple[int, int, int]


def background_color(img, x: float, y: float, w: float, h: float) -> RGB:
    """Dominant colour of the region (text is the minority, background the majority)."""
    from PIL import Image  # local import keeps module importable without Pillow

    x0 = max(0, int(x) - 2)
    y0 = max(0, int(y) - 2)
    x1 = min(img.width, int(x + w) + 2)
    y1 = min(img.height, int(y + h) + 2)
    if x1 <= x0 or y1 <= y0:
        return (255, 255, 255)
    crop = img.crop((x0, y0, x1, y1)).convert("RGB")
    crop = crop.resize((min(crop.width, 64), min(crop.height, 64)), Image.NEAREST)
    data = crop.tobytes()

    buckets = {}
    for i in range(0, len(data), 3):
        r, g, b = data[i], data[i + 1], data[i + 2]
        key = (r >> 3, g >> 3, b >> 3)
        entry = buckets.get(key)
        if entry is None:
            buckets[key] = [1, r, g, b]
        else:
            entry[0] += 1
            entry[1] += r
            entry[2] += g
            entry[3] += b
    n, sr, sg, sb = max(buckets.values(), key=lambda e: e[0])
    return (sr // n, sg // n, sb // n)
