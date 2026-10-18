"""Decide where and how large each translated box is drawn.

Pure logic: text measuring is injected (`measure`) so Qt supplies it in the app
and Pillow supplies it in tests.

measure(text, px, max_width_or_None) -> (width, height) in pixels of the text
laid out with word-wrap at max_width (or on one line when max_width is None).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple

import config

RGB = Tuple[int, int, int]
Measure = Callable[[str, int, Optional[int]], Tuple[int, int]]


@dataclass
class Item:
    x: int
    y: int
    w: int
    h: int
    text: str
    px: int
    pad: int
    align: str          # "right" or "center"
    valign: str         # "top" (paragraphs) or "middle" (single lines)
    bg: RGB
    fg: RGB


def _lin(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: RGB) -> float:
    r, g, b = rgb
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def pick_fg(bg: RGB) -> RGB:
    """Black or white, whichever has the higher WCAG contrast against bg."""
    lum = luminance(bg)
    contrast_black = (lum + 0.05) / 0.05
    contrast_white = 1.05 / (lum + 0.05)
    return (0, 0, 0) if contrast_black >= contrast_white else (255, 255, 255)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def plan_items(blocks: Sequence, texts: Sequence[str], bgs: Sequence[RGB],
               screen_w: int, screen_h: int, measure: Measure,
               min_px: int = config.MIN_FONT_PX, max_px: int = config.MAX_FONT_PX) -> List[Item]:
    items: List[Item] = []
    max_w = int(screen_w * 0.94)

    for block, text, bg in zip(blocks, texts, bgs):
        if not text:
            continue
        px = int(_clamp(round(block.lh * 0.80), min_px, max_px))
        single = block.lines == 1

        if single:
            # Keep the font size; widen the box if Hebrew is longer than the English.
            pad = max(3, round(px * 0.2))
            full_w, _ = measure(text, px, None)
            box_w = int(min(max_w, max(block.w + 2 * pad, full_w + 2 * pad + 2)))
            tw, th = measure(text, px, box_w - 2 * pad)
        else:
            # Paragraph: keep the original width, shrink the font a little if the
            # text would otherwise grow much taller than the original paragraph.
            box_w = int(min(max_w, block.w + 2 * max(3, round(px * 0.2))))
            p = px
            while True:
                pad = max(3, round(p * 0.2))
                tw, th = measure(text, p, box_w - 2 * pad)
                if th + 2 * pad <= (block.h + 2 * pad) * 1.25 or p <= min_px:
                    break
                p -= 2
            px = p

        # The box must always hide the ENTIRE original text, even when the Hebrew is shorter.
        box_h = int(max(th + 2 * pad, block.h + 2 * pad))
        original_pad_w = block.w + 2 * pad
        if box_w > original_pad_w + 1:          # widened -> grow around the centre
            x = block.x + block.w / 2 - box_w / 2
        else:
            x = block.x - pad
        y = block.y - pad
        x = int(_clamp(x, 0, max(0, screen_w - box_w)))
        y = int(_clamp(y, 0, max(0, screen_h - box_h)))

        align = "center" if single and box_w <= screen_w * 0.30 else "right"
        valign = "middle" if single else "top"
        items.append(Item(x=x, y=y, w=int(box_w), h=int(box_h), text=text, px=px, pad=pad,
                          align=align, valign=valign, bg=bg, fg=pick_fg(bg)))
    return items
