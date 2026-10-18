"""The screen-to-Hebrew pipeline as small, separately testable steps.

    OCR lines --analyze_blocks--> blocks (+skipped)
              --translate_blocks--> kept blocks + Hebrew texts (+skipped)
              --sample_backgrounds--> background colours
              --plan--> draw items (needs a text-measure function; Qt in the app)

`run()` does all of it in one call; the Windows bench uses that to dump
JSON for every stage so improvements can be judged on real OCR data.
Every function is pure apart from `translator.translate` (network) and is
safe to call from a worker thread (nothing here touches Qt).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import colors
import fit
import layout

Skipped = List[Tuple[str, str]]          # [(text, reason)]


@dataclass
class Result:
    size: Tuple[int, int] = (0, 0)
    ocr_lines: list = field(default_factory=list)
    blocks: list = field(default_factory=list)
    texts: list = field(default_factory=list)
    bgs: list = field(default_factory=list)
    items: list = field(default_factory=list)
    skipped: Skipped = field(default_factory=list)
    timings: Dict[str, float] = field(default_factory=dict)

    def to_json(self) -> dict:
        """JSON-serialisable dump of every stage (used by the bench and for debugging)."""
        return {
            "size": list(self.size),
            "timings": {k: round(v, 4) for k, v in self.timings.items()},
            "ocr_lines": [[{"text": w.text, "x": w.x, "y": w.y, "w": w.w, "h": w.h} for w in line]
                          for line in self.ocr_lines],
            "blocks": [{"text": b.text, "x": b.x, "y": b.y, "w": b.w, "h": b.h,
                        "lines": b.lines, "lh": b.lh, "hebrew": t}
                       for b, t in zip(self.blocks, self.texts)],
            "items": [{"x": i.x, "y": i.y, "w": i.w, "h": i.h, "px": i.px, "pad": i.pad,
                       "align": i.align, "valign": i.valign, "bg": list(i.bg), "fg": list(i.fg),
                       "text": i.text} for i in self.items],
            "skipped": [{"text": t, "reason": r} for t, r in self.skipped],
        }


def analyze_blocks(ocr_lines) -> Tuple[list, Skipped]:
    """OCR lines -> (translatable blocks in reading order, skipped blocks with reasons)."""
    segments = []
    for line in ocr_lines:
        segments.extend(layout.split_line(line))
    blocks, skipped = [], []
    for block in layout.group_blocks(segments):
        reason = layout.skip_reason(block.text)
        if reason:
            skipped.append((block.text, reason))
        else:
            blocks.append(block)
    return blocks, skipped


def translate_blocks(blocks: Sequence, translator) -> Tuple[list, List[str], Skipped, list]:
    """Translate blocks. Returns (kept_blocks, hebrew_texts, skipped, raw_results)."""
    results = translator.translate([b.text for b in blocks])
    kept, texts, skipped = [], [], []
    for block, text in zip(blocks, results):
        if not text or not text.strip():
            skipped.append((block.text, "no_translation"))
        elif text.strip().lower() == block.text.strip().lower():
            skipped.append((block.text, "unchanged"))
        else:
            kept.append(block)
            texts.append(text.strip())
    return kept, texts, skipped, results


def sample_backgrounds(img, blocks: Sequence) -> list:
    return [colors.background_color(img, b.x, b.y, b.w, b.h) for b in blocks]


def plan(blocks, texts, bgs, size, measure) -> list:
    return fit.plan_items(blocks, texts, bgs, size[0], size[1], measure)


def summarize_skipped(skipped: Skipped) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for _text, reason in skipped:
        out[reason] = out.get(reason, 0) + 1
    return out


def run(img, ocr, translator, measure: Optional[Callable] = None) -> Result:
    """Whole pipeline on one PIL image. `ocr` needs .recognize(img); `translator` needs .translate(list)."""
    res = Result(size=img.size)
    t = time.monotonic()
    res.ocr_lines = ocr.recognize(img)
    res.timings["ocr"] = time.monotonic() - t

    t = time.monotonic()
    blocks, skipped = analyze_blocks(res.ocr_lines)
    res.timings["layout"] = time.monotonic() - t

    t = time.monotonic()
    if translator is not None and blocks:
        res.blocks, res.texts, skipped2, _raw = translate_blocks(blocks, translator)
        skipped = skipped + skipped2
    else:
        res.blocks, res.texts = blocks, ["" for _ in blocks]
    res.timings["translate"] = time.monotonic() - t
    res.skipped = skipped

    t = time.monotonic()
    res.bgs = sample_backgrounds(img, res.blocks)
    if measure is not None and translator is not None:
        res.items = plan(res.blocks, res.texts, res.bgs, img.size, measure)
    res.timings["plan"] = time.monotonic() - t
    res.timings["total"] = sum(v for k, v in res.timings.items() if k != "total")
    return res
