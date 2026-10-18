"""Central configuration and every user-facing (Hebrew) string.

Tune behaviour here; nothing else in the code base hard-codes these values.
"""

APP_NAME = "OCR2Heb"
APP_VERSION = "1.0.0"
TASK_NAME = "OCR2Heb"                       # Windows Task Scheduler entry name
MUTEX_NAME = "Global\\OCR2Heb_SingleInstance"

# ---------------------------------------------------------------- translation
TARGET_LANG = "iw"                          # Google's code for Hebrew
TRANSLATE_CHUNK_CHARS = 1400                # max characters per HTTP request
TRANSLATE_MAX_TEXT_CHARS = 1800             # a single block is truncated beyond this
TRANSLATE_WORKERS = 4                       # parallel HTTP requests

# ------------------------------------------------------------------------ OCR
OCR_LANG_PREFERENCE = ("en-US", "en-GB")    # then any other installed "en-*"
OCR_CAPABILITY = "Language.OCR~~~en-US~0.0.1.0"   # Windows feature to install if missing
OCR_UPSCALE = 2.0                           # small UI text reads far better when enlarged
OCR_UPSCALE_MAX_WIDTH = 2600                # do not upscale very large screens

# ------------------------------------------------------------------ behaviour
MIDDLE_CLICK_DEBOUNCE_SEC = 0.45            # ignore a second wheel-click within this time
JOB_TIMEOUT_SEC = 30                        # give up on a translation after this long
# The overlay is a still picture. If the screen changes underneath it, it is
# stale and misleading, so by default it disappears on scroll / left / right click.
DISMISS_ON_SCROLL = True
DISMISS_ON_LEFT_RIGHT_CLICK = True

# ----------------------------------------------------------------------- look
MIN_FONT_PX = 18                            # never render translated text smaller than this
MAX_FONT_PX = 60
FONT_FAMILIES = ("Segoe UI", "Arial", "Tahoma", "DejaVu Sans")
READY_BANNER_SEC = 7.0
ERROR_BANNER_SEC = 5.0
HINT_BANNER_SEC = 6.0


class T:
    """Hebrew UI strings. Short, calm and free of technical words."""

    READY = "התרגום מוכן. לחץ על גלגלת העכבר כדי לתרגם את המסך."
    WORKING = "מתרגם"
    HINT = "כדי לסגור – לחץ שוב על גלגלת העכבר"
    NO_TEXT = "לא מצאתי טקסט באנגלית במסך הזה."
    NO_INTERNET = "אין חיבור לאינטרנט. בדוק שהאינטרנט עובד ונסה שוב."
    TRANSLATE_FAIL = "התרגום לא הצליח כרגע. נסה שוב בעוד רגע."
    OCR_INSTALLING = "מכין את המחשב לקריאת טקסט. זה יכול לקחת כמה דקות, אפשר להמשיך כרגיל."
    OCR_BROKEN = "לא הצלחתי להכין את קריאת הטקסט. צריך עזרה מרחוק."
    GENERIC = "משהו לא הסתדר. נסה ללחוץ שוב."
    TIMEOUT = "זה לוקח יותר מדי זמן. נסה שוב."
    ALREADY_RUNNING = "התוכנה כבר פועלת. אפשר ללחוץ על גלגלת העכבר כדי לתרגם."
    TRAY_TOOLTIP = "מתרגם מסך לעברית – לחץ על גלגלת העכבר"
    TRAY_STATUS = "פעיל – לחץ על גלגלת העכבר לתרגום"
    TRAY_LOGS = "פתח תיקיית לוגים"
    TRAY_EXIT = "יציאה"
