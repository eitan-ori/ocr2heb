"""Platform-independent tests: layout grouping, translation plumbing, box fitting.

Run:  python tests/test_pipeline.py            (no pytest needed; also pytest-compatible)
Optional env PREVIEW_OUT=/path/preview.png writes a visual preview of the overlay.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import requests  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import colors  # noqa: E402
import fit  # noqa: E402
import layout  # noqa: E402
import translate  # noqa: E402
from layout import Word  # noqa: E402

FONT_PATHS = [
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def font(px):
    for p in FONT_PATHS:
        if os.path.exists(p):
            return ImageFont.truetype(p, px)
    return ImageFont.load_default()


# ------------------------------------------------------------ fake "screen"
def fake_screen():
    """Draw English text on an image and emulate what Windows OCR would return."""
    img = Image.new("RGB", (1280, 720), (255, 255, 255))
    d = ImageDraw.Draw(img)
    ocr_lines = []

    def draw_line(text, x, y, px, fill=(20, 20, 20)):
        f = font(px)
        d.text((x, y), text, font=f, fill=fill)
        words, cx = [], x
        for token in text.split(" "):
            bb = f.getbbox(token)
            wlen = f.getlength(token)
            words.append(Word(token, cx, y + bb[1], wlen, bb[3] - bb[1]))
            cx += wlen + f.getlength(" ")
        ocr_lines.append(words)

    draw_line("Welcome to the Photo Gallery", 100, 50, 38)

    para = [
        "This application helps you organise your photos and",
        "share them with family and friends. You can create",
        "albums, add captions, and send a link by email to",
        "anyone you like.",
    ]
    for i, line in enumerate(para):
        draw_line(line, 100, 130 + i * 34, 22)

    menu = ["Home", "Albums and collections", "Shared with me", "Settings", "Help"]
    for i, item in enumerate(menu):
        draw_line(item, 900, 130 + i * 44, 20)

    # two columns sitting on the SAME OCR line (Windows often joins them)
    f = font(20)
    left, right = "Left column news", "Right column weather"
    d.text((100, 400), left, font=f, fill=(20, 20, 20))
    d.text((700, 400), right, font=f, fill=(20, 20, 20))
    words, cx = [], 100
    for t in left.split(" "):
        bb = f.getbbox(t); words.append(Word(t, cx, 400 + bb[1], f.getlength(t), bb[3] - bb[1])); cx += f.getlength(t + " ")
    cx = 700
    for t in right.split(" "):
        bb = f.getbbox(t); words.append(Word(t, cx, 400 + bb[1], f.getlength(t), bb[3] - bb[1])); cx += f.getlength(t + " ")
    ocr_lines.append(words)

    # a dark button
    d.rectangle((520, 560, 760, 620), fill=(30, 60, 140))
    draw_line("Sign in", 590, 573, 28, fill=(255, 255, 255))

    # noise that must be ignored
    draw_line("12:45", 1180, 10, 18)
    draw_line("https://example.com/page", 100, 680, 16)
    return img, ocr_lines


# ----------------------------------------------------------------- layout
def test_layout_grouping():
    img, lines = fake_screen()
    blocks = layout.build_blocks(lines)
    texts = [b.text for b in blocks]
    print("blocks:", *texts, sep="\n  ")

    paragraph = [b for b in blocks if b.text.startswith("This application")]
    assert len(paragraph) == 1 and paragraph[0].lines == 4, "paragraph must be one 4-line block"
    assert "anyone you like." in paragraph[0].text

    assert any(t == "Welcome to the Photo Gallery" for t in texts), "heading stays separate"
    for item in ["Home", "Albums and collections", "Shared with me", "Settings", "Help"]:
        assert item in texts, f"menu item {item!r} must be its own block"
    assert "Left column news" in texts and "Right column weather" in texts, "columns must split"
    assert "Sign in" in texts
    assert "12:45" not in texts, "numbers ignored"
    assert not any("example.com" in t for t in texts), "urls ignored"


def test_is_translatable():
    assert layout.is_translatable("Hello world")
    assert not layout.is_translatable("12:45")
    assert not layout.is_translatable("שלום עולם")
    assert not layout.is_translatable("C:\\Users\\me")
    assert not layout.is_translatable("a")


# ------------------------------------------------------------- translation
class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    """Behaves like Google: returns one segment per input line, prefixed with Hebrew."""

    def __init__(self, mode="ok"):
        self.headers = {}
        self.mode = mode
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        if self.mode == "offline":
            raise requests.ConnectionError("no network")
        if self.mode == "http429":
            return FakeResponse(429)
        text = params["q"]
        lines = text.split("\n")
        if self.mode == "merge" and len(lines) > 1:
            lines = [" ".join(lines)]                       # Google merged our lines
        segs = [[f"תרגום: {ln}" + ("\n" if i < len(lines) - 1 else ""), ln, None, None, 1]
                for i, ln in enumerate(lines)]
        return FakeResponse(200, [segs, None, "en"])


def test_translate_batches_and_order():
    s = FakeSession()
    t = translate.Translator(session=s)
    out = t.translate(["Hello", "Good morning", "Hello", "  ", "Save file"])
    assert out[0] == "תרגום: Hello" and out[2] == "תרגום: Hello"
    assert out[1] == "תרגום: Good morning" and out[4] == "תרגום: Save file"
    assert out[3] is None
    assert s.calls == 1, "everything fits one request"
    t.translate(["Hello"])
    assert s.calls == 1, "cached"


def test_translate_line_mismatch_falls_back():
    s = FakeSession("merge")
    t = translate.Translator(session=s)
    out = t.translate(["One", "Two", "Three"])
    assert out == ["תרגום: One", "תרגום: Two", "תרגום: Three"], out


def test_translate_offline():
    t = translate.Translator(session=FakeSession("offline"))
    try:
        t.translate(["Hello"])
    except translate.NoInternet:
        return
    raise AssertionError("expected NoInternet")


def test_translate_rate_limited():
    import time
    orig = time.sleep
    translate.time.sleep = lambda s: None
    try:
        t = translate.Translator(session=FakeSession("http429"))
        try:
            t.translate(["Hello"])
        except translate.TranslateError:
            return
        raise AssertionError("expected TranslateError")
    finally:
        translate.time.sleep = orig


# ------------------------------------------------------------ colours / fit
def test_background_and_contrast():
    img = Image.new("RGB", (200, 100), (30, 60, 140))
    ImageDraw.Draw(img).text((20, 30), "Sign in", fill=(255, 255, 255), font=font(24))
    bg = colors.background_color(img, 10, 20, 150, 50)
    assert abs(bg[0] - 30) < 10 and abs(bg[2] - 140) < 10, bg
    assert fit.pick_fg(bg) == (255, 255, 255)
    assert fit.pick_fg((250, 250, 250)) == (0, 0, 0)


def pil_measure(text, px, max_width):
    f = font(px)
    if max_width is None:
        return int(f.getlength(text)), int(px * 1.3)
    lines, cur = 1, ""
    for word in text.split(" "):
        trial = (cur + " " + word).strip()
        if f.getlength(trial) <= max_width or not cur:
            cur = trial
        else:
            lines += 1
            cur = word
    return int(max_width if lines > 1 else f.getlength(text)), int(lines * px * 1.3)


FAKE_HEBREW = {
    "Welcome to the Photo Gallery": "ברוכים הבאים לגלריית התמונות",
    "This application helps you organise your photos and share them with family and friends. You can create albums, add captions, and send a link by email to anyone you like.":
        "אפליקציה זו עוזרת לך לארגן את התמונות שלך ולשתף אותן עם המשפחה והחברים. אפשר ליצור אלבומים, להוסיף כיתובים ולשלוח קישור בדוא\"ל לכל מי שתרצה.",
    "Home": "בית", "Albums and collections": "אלבומים ואוספים", "Shared with me": "שותף איתי",
    "Settings": "הגדרות", "Help": "עזרה", "Left column news": "חדשות העמודה השמאלית",
    "Right column weather": "מזג האוויר בעמודה הימנית", "Sign in": "התחברות",
}


def test_fit_and_preview():
    img, lines = fake_screen()
    blocks = layout.build_blocks(lines)
    texts = [FAKE_HEBREW.get(b.text, "תרגום " + b.text) for b in blocks]
    bgs = [colors.background_color(img, b.x, b.y, b.w, b.h) for b in blocks]
    items = fit.plan_items(blocks, texts, bgs, img.width, img.height, pil_measure)
    assert len(items) == len(blocks)
    for it in items:
        assert 0 <= it.x and it.x + it.w <= img.width, it
        assert 0 <= it.y and it.y + it.h <= img.height, it
        assert it.px >= 18

    out = os.environ.get("PREVIEW_OUT")
    if out:
        render_preview(img, items, out)


def render_preview(img, items, out):
    """Rough Pillow rendering (no RTL shaping unless libraqm is present)."""
    from PIL import features
    raqm = features.check("raqm")
    canvas = img.copy()
    d = ImageDraw.Draw(canvas)
    for it in items:
        d.rectangle((it.x, it.y, it.x + it.w, it.y + it.h), fill=it.bg, outline=(120, 120, 120))
        f = font(it.px)
        words = it.text.split(" ")
        lines, cur = [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if f.getlength(trial) <= it.w - 2 * it.pad or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        text_h = len(lines) * it.px * 1.3
        top = it.y + it.pad if it.valign == "top" else it.y + (it.h - text_h) / 2
        for i, ln in enumerate(lines):
            shown = ln if raqm else ln[::-1]
            tw = f.getlength(shown)
            tx = it.x + it.w - it.pad - tw if it.align == "right" else it.x + (it.w - tw) / 2
            kw = {"direction": "rtl"} if raqm else {}
            d.text((tx, top + i * it.px * 1.3), shown, font=f, fill=it.fg, **kw)
    canvas.save(out)
    print("preview written:", out)


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as exc:  # noqa: BLE001
                failures += 1
                import traceback
                traceback.print_exc()
                print("FAIL", name, exc)
    sys.exit(1 if failures else 0)
