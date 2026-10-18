"""Pure-logic text layout: OCR words -> segments -> paragraph-like blocks.

No Windows / Qt dependencies, so it is unit-testable anywhere.

Windows OCR returns "lines" of words with pixel boxes. Translating line by line
gives poor Hebrew, so consecutive lines that look like one paragraph are merged
into a single block and translated together. Menus, buttons and column gutters
are deliberately kept apart.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from typing import List, Optional, Sequence

MAX_LINES_PER_BLOCK = 20


@dataclass
class Word:
    text: str
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


def _letters(s: str) -> int:
    return sum(1 for c in s if c.isalpha())


class Segment:
    """A run of words on one visual line with no big horizontal gap."""

    __slots__ = ("words", "x", "y", "right", "bottom", "lh")

    def __init__(self, words: Sequence[Word]):
        self.words = list(words)
        self.x = min(w.x for w in self.words)
        self.y = min(w.y for w in self.words)
        self.right = max(w.right for w in self.words)
        self.bottom = max(w.bottom for w in self.words)
        heights = [w.h for w in self.words if _letters(w.text) >= 1] or [w.h for w in self.words]
        self.lh = max(max(heights), 1.0)

    @property
    def w(self) -> float:
        return self.right - self.x

    @property
    def h(self) -> float:
        return self.bottom - self.y

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def split_line(words: Sequence[Word], gap_factor: float = 1.6) -> List[Segment]:
    """Split one OCR line into segments wherever there is a wide gap (columns, table cells)."""
    words = [w for w in words if w.text.strip()]
    if not words:
        return []
    words = sorted(words, key=lambda w: w.x)
    lh = max(w.h for w in words)
    threshold = max(gap_factor * lh, 20.0)
    segments: List[Segment] = []
    current = [words[0]]
    for prev, word in zip(words, words[1:]):
        if word.x - prev.right > threshold:
            segments.append(Segment(current))
            current = [word]
        else:
            current.append(word)
    segments.append(Segment(current))
    return segments


def _join_lines(texts: Sequence[str]) -> str:
    out = texts[0]
    for t in texts[1:]:
        if len(out) > 2 and out.endswith("-") and t[:1].islower():
            out = out[:-1] + t          # "trans-" + "lation"
        else:
            out = out + " " + t
    return re.sub(r"\s+", " ", out).strip()


class Block:
    def __init__(self, seg: Segment):
        self.segs: List[Segment] = [seg]

    @property
    def last(self) -> Segment:
        return self.segs[-1]

    def add(self, seg: Segment) -> None:
        self.segs.append(seg)

    @property
    def x(self) -> float:
        return min(s.x for s in self.segs)

    @property
    def y(self) -> float:
        return min(s.y for s in self.segs)

    @property
    def right(self) -> float:
        return max(s.right for s in self.segs)

    @property
    def bottom(self) -> float:
        return max(s.bottom for s in self.segs)

    @property
    def w(self) -> float:
        return self.right - self.x

    @property
    def h(self) -> float:
        return self.bottom - self.y

    @property
    def lines(self) -> int:
        return len(self.segs)

    @property
    def lh(self) -> float:
        return float(statistics.median(s.lh for s in self.segs))

    @property
    def text(self) -> str:
        return _join_lines([s.text for s in self.segs])


def _can_follow(prev: Segment, seg: Segment, nlines: int) -> bool:
    """Would `seg` be the next line of the paragraph whose last line is `prev`?"""
    if nlines >= MAX_LINES_PER_BLOCK:
        return False
    lh = prev.lh
    gap = seg.y - prev.bottom
    if gap < -0.45 * lh or gap > 0.65 * lh:        # same row (column) or too far apart
        return False
    ratio = seg.lh / lh
    if ratio < 0.65 or ratio > 1.55:               # different font size -> different element
        return False
    if abs(seg.x - prev.x) > 2.2 * lh:             # not left-aligned (allows an indent)
        return False
    if prev.right < seg.right - 2.0 * lh:          # previous line much shorter => menu / list
        return False
    overlap = min(prev.right, seg.right) - max(prev.x, seg.x)
    if overlap < 0.3 * min(prev.w, seg.w):
        return False
    return True


def group_blocks(segments: Sequence[Segment]) -> List[Block]:
    blocks: List[Block] = []
    for seg in sorted(segments, key=lambda s: (s.y, s.x)):
        best = None
        best_gap = 0.0
        for block in blocks:
            if _can_follow(block.last, seg, block.lines):
                gap = seg.y - block.last.bottom
                if best is None or gap < best_gap:
                    best, best_gap = block, gap
        if best is not None:
            best.add(seg)
        else:
            blocks.append(Block(seg))
    return blocks


_URLISH = re.compile(r"https?://|www\.|@|\\|/")


def skip_reason(text: str) -> Optional[str]:
    """Why this block must NOT be translated (None = translate it)."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 2:
        return "too_short"
    hebrew = sum(1 for c in letters if "֐" <= c <= "׿")
    if hebrew / len(letters) > 0.5:
        return "hebrew"
    stripped = text.strip()
    if " " not in stripped and _URLISH.search(stripped):
        return "technical"
    return None


def is_translatable(text: str) -> bool:
    return skip_reason(text) is None


def build_blocks(ocr_lines: Sequence[Sequence[Word]]) -> List[Block]:
    """OCR lines -> translatable blocks, in reading order."""
    segments: List[Segment] = []
    for line in ocr_lines:
        segments.extend(split_line(line))
    return [b for b in group_blocks(segments) if is_translatable(b.text)]
