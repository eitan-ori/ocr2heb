"""Free English -> Hebrew translation via Google's public web endpoint.

No API key. Text is sent in a few parallel requests, one block per line, and
the answer is split back by line. If Google merges or splits lines (the count
no longer matches) that chunk is retried block by block, so a block is never
shown next to the wrong translation.
"""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Sequence

import requests

import config

log = logging.getLogger("ocr2heb.translate")

ENDPOINT = "https://translate.googleapis.com/translate_a/single"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


class NoInternet(Exception):
    """Could not reach the translation service at all."""


class TranslateError(Exception):
    """The service was reachable but did not give a usable answer."""


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > config.TRANSLATE_MAX_TEXT_CHARS:
        cut = text.rfind(" ", 0, config.TRANSLATE_MAX_TEXT_CHARS)
        text = text[: cut if cut > 0 else config.TRANSLATE_MAX_TEXT_CHARS]
    return text


def _parse(payload) -> str:
    """Google returns [[[translated, original, ...], ...], ...]."""
    try:
        return "".join(part[0] for part in payload[0] if part and part[0])
    except (TypeError, IndexError, KeyError) as exc:
        raise TranslateError(f"unexpected response shape: {exc}") from exc


class Translator:
    def __init__(self, target: str = config.TARGET_LANG, session: Optional[requests.Session] = None):
        self.target = target
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._cache: Dict[str, str] = {}

    # ------------------------------------------------------------ one request
    def _request(self, text: str) -> str:
        params = {"client": "gtx", "sl": "auto", "tl": self.target, "dt": "t", "q": text}
        last: Exception = TranslateError("no attempt made")
        for attempt in range(3):
            try:
                resp = self.session.get(ENDPOINT, params=params, timeout=(4, 10))
                if resp.status_code == 200:
                    return _parse(resp.json())
                last = TranslateError(f"HTTP {resp.status_code}")
                if resp.status_code in (429, 500, 502, 503, 504):
                    time.sleep(0.8 * (attempt + 1))
                    continue
                break                                   # other 4xx: retrying will not help
            except requests.ConnectionError as exc:      # includes connect timeouts, DNS failures
                last = NoInternet(str(exc))
                time.sleep(0.4)
            except requests.Timeout as exc:              # connected but slow
                last = TranslateError(f"timeout: {exc}")
            except ValueError as exc:                    # bad JSON
                last = TranslateError(f"bad json: {exc}")
        log.warning("translation request failed: %s", last)
        raise last

    # ------------------------------------------------------------- one chunk
    def _translate_chunk(self, items: List[tuple]) -> Dict[int, str]:
        """items: [(index, text)] -> {index: translation}"""
        joined = "\n".join(text for _, text in items)
        try:
            out = self._request(joined)
            parts = out.split("\n")
            if len(parts) == len(items):
                return {idx: part.strip() for (idx, _), part in zip(items, parts)}
            log.info("line count mismatch (%d vs %d); retrying block by block", len(parts), len(items))
        except NoInternet:
            raise
        except TranslateError:
            if len(items) == 1:
                raise
        result: Dict[int, str] = {}
        for idx, text in items:
            try:
                result[idx] = self._request(text).strip()
            except NoInternet:
                raise
            except TranslateError as exc:
                log.warning("block %d failed: %s", idx, exc)
        return result

    # ---------------------------------------------------------------- public
    def translate(self, texts: Sequence[str]) -> List[Optional[str]]:
        """Translate each text. Failed items are None. Raises only if everything failed."""
        cleaned = [_clean(t) for t in texts]
        results: List[Optional[str]] = [None] * len(cleaned)

        pending: Dict[str, List[int]] = {}               # de-duplicate identical texts
        for i, t in enumerate(cleaned):
            if not t:
                continue
            if t in self._cache:
                results[i] = self._cache[t]
            else:
                pending.setdefault(t, []).append(i)

        if not pending:
            return results

        # Pack unique texts into chunks.
        chunks: List[List[tuple]] = []
        current: List[tuple] = []
        size = 0
        for key, (text, _idxs) in enumerate(pending.items()):
            if current and size + len(text) + 1 > config.TRANSLATE_CHUNK_CHARS:
                chunks.append(current)
                current, size = [], 0
            current.append((key, text))
            size += len(text) + 1
        if current:
            chunks.append(current)

        keys = list(pending.keys())
        translated: Dict[int, str] = {}
        errors: List[Exception] = []

        def run(chunk):
            try:
                return self._translate_chunk(chunk)
            except (NoInternet, TranslateError) as exc:
                errors.append(exc)
                return {}

        with ThreadPoolExecutor(max_workers=min(config.TRANSLATE_WORKERS, len(chunks))) as pool:
            for part in pool.map(run, chunks):
                translated.update(part)

        for key, text in enumerate(keys):
            value = translated.get(key)
            if value:
                self._cache[text] = value
                if len(self._cache) > 2000:
                    self._cache.pop(next(iter(self._cache)))
                for i in pending[text]:
                    results[i] = value

        if not any(results) and errors:
            for exc in errors:                           # prefer reporting "no internet"
                if isinstance(exc, NoInternet):
                    raise exc
            raise errors[0]
        return results
