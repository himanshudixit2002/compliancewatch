"""Which language a regulator text is in: English, Hindi or both.

Regulator documents are English, Hindi or both (a Hindi gazette text followed by the English one).
A clause's reference names its language (``en.p3``, ``hi.p1``), so an English and a Hindi
rendering of the same document never collide, and a text with both is ``mul``.
"""

import re
from typing import Final

LANGUAGE_ENGLISH: Final = "en"
LANGUAGE_HINDI: Final = "hi"
LANGUAGE_BILINGUAL: Final = "mul"
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_LATIN = re.compile(r"[A-Za-z]")


def detect_language(text: str, *, bilingual_threshold: float = 0.15) -> str:
    """``hi``, ``en`` or ``mul`` from the share of Devanagari and Latin letters."""
    devanagari = len(_DEVANAGARI.findall(text))
    latin = len(_LATIN.findall(text))
    total = devanagari + latin
    if total == 0:
        return LANGUAGE_ENGLISH
    hindi_share = devanagari / total
    if hindi_share >= 1 - bilingual_threshold:
        return LANGUAGE_HINDI
    if hindi_share <= bilingual_threshold:
        return LANGUAGE_ENGLISH
    return LANGUAGE_BILINGUAL
