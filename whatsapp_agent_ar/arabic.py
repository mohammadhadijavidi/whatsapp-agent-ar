"""Arabic text helpers: normalization, light stemming, Gulf dialect synonyms.

Everything here is deterministic and dependency-free so the knowledge-base
search works with no API key at all.
"""

from __future__ import annotations

import re
import unicodedata

_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭ]")
_TATWEEL = "ـ"
_INVISIBLE = re.compile(r"[​-‏‪-‮⁦-⁩﻿]")
_ARABIC_LETTER = re.compile(r"[؀-ۿ]")
_LATIN_LETTER = re.compile(r"[A-Za-z]")
_REPEATS = re.compile(r"(.)\1{2,}")
_TOKEN = re.compile(r"[\w؀-ۿ]+", re.UNICODE)

_CHAR_MAP = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ة": "ه",
        "ى": "ي",
        "ؤ": "و",
        "ئ": "ي",
        "ک": "ك",
        "ی": "ي",
        "ڤ": "ف",
        "گ": "ك",
        "چ": "ج",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
        "؟": "?",
        "،": ",",
        "؛": ";",
    }
)


def normalize(text: str) -> str:
    """Normalize Arabic (and English) text for matching, not for display."""
    text = unicodedata.normalize("NFKC", text or "")
    text = _INVISIBLE.sub("", text)
    text = _DIACRITICS.sub("", text).replace(_TATWEEL, "")
    text = text.translate(_CHAR_MAP).lower()
    text = _REPEATS.sub(r"\1", text)  # "وااايد" -> "وايد", "pleeease" -> "please"
    return re.sub(r"\s+", " ", text).strip()


def is_arabic(text: str) -> bool:
    """True when the message is mostly Arabic script (used to pick reply language)."""
    ar = len(_ARABIC_LETTER.findall(text or ""))
    en = len(_LATIN_LETTER.findall(text or ""))
    if ar == 0 and en == 0:
        return True  # digits/emoji only: default to the business language (Arabic)
    # Gulf customers often mix in English words ("ابي احجز cleaning"): lean Arabic.
    return ar * 2 >= en


# Function words and Gulf fillers that carry no topic signal.
STOPWORDS = {
    # MSA
    "في", "من", "على", "عن", "الى", "الي", "ان", "او", "ثم", "هل", "ما", "ماذا", "لماذا", "كيف",
    "هذا", "هذه", "ذلك", "تلك", "هو", "هي", "انا", "انت", "انتم", "نحن", "مع", "لا", "نعم", "لو",
    "قد", "كل", "اي", "التي", "الذي", "عند", "عندكم", "عندك", "لديكم", "يوجد", "هناك", "ممكن", "اريد",
    "اود", "اعرف", "معرفه", "سمحت", "فضلك", "رجاء", "مرحبا", "شكرا", "يا", "بعد", "قبل", "كان",
    # Gulf / Emirati fillers
    "شو", "ايش", "وش", "شنو", "ابي", "ابغي", "ابا", "بغيت", "ودي", "لو", "عادي", "يعني", "حق",
    "مال", "هاي", "هذي", "الحين", "اذا", "لين", "عشان", "علشان", "اخوي", "اختي", "طال", "عمرك",
    # Greetings / courtesy (never a topic)
    "السلام", "سلام", "عليكم", "عليكم", "وعليكم", "هلا", "اهلين", "صباح", "مساء", "الخير", "خير", "النور",
    "حياك", "تسلم", "مشكور", "يعطيك", "العافيه", "الله",
    # English
    "the", "a", "an", "is", "are", "do", "does", "you", "your", "i", "me", "my", "to", "of", "for",
    "and", "or", "in", "on", "at", "what", "how", "can", "please", "hi", "hello", "there", "have",
    "it", "we", "with", "any", "about", "want", "would", "like", "know",
}

# Gulf dialect / MSA / English synonyms mapped to one canonical token. Hand-written.
_SYNONYM_GROUPS = {
    "سعر": ["سعر", "اسعار", "الاسعار", "السعر", "تكلفه", "كلفه", "التكلفه", "بكم", "كم", "قيمه", "رسوم",
            "الرسوم", "فلوس", "price", "prices", "cost", "costs", "fee", "fees", "much"],
    "موقع": ["موقع", "الموقع", "مكان", "مكانكم", "وين", "اين", "عنوان", "العنوان", "لوكيشن", "location",
             "address", "where", "located", "map"],
    "دوام": ["دوام", "الدوام", "ساعات", "تفتحون", "تفتحوا", "مفتوح", "فاتحين", "تسكرون", "تغلقون", "يفتح",
             "اوقات", "مواعيد_العمل", "open", "opening", "hours", "close", "closing", "timings"],
    "طبيب": ["طبيب", "الطبيب", "دكتور", "الدكتور", "دختر", "الدختر", "دكتوره", "اطباء", "doctor",
             "dentist", "doctors"],
    "تامين": ["تامين", "التامين", "انشورنس", "insurance", "insured", "بطاقه_تامين", "ثقه", "daman", "ضمان"],
    "دفع": ["دفع", "الدفع", "ادفع", "كاش", "نقدا", "بطاقه", "فيزا", "تابي", "تمارا", "تقسيط", "pay",
            "payment", "card", "cash", "installments", "tabby", "tamara"],
    "موقف": ["موقف", "مواقف", "باركنج", "parking", "park", "سياره", "الموتر", "موتر"],
    "تنظيف": ["تنظيف", "تلميع", "جير", "الجير", "cleaning", "clean", "scaling", "polish"],
    "تبييض": ["تبييض", "تبيض", "ابيض", "whitening", "whiten", "bleaching"],
    "تقويم": ["تقويم", "التقويم", "شفاف", "braces", "aligners", "invisalign", "orthodontic"],
    "طوارئ": ["طوارئ", "الطوارئ", "طارئ", "طارئه", "الم", "يعورني", "يوجعني", "وجع", "emergency",
              "urgent", "pain", "hurts"],
    "اطفال": ["اطفال", "الاطفال", "طفل", "ولدي", "بنتي", "عيالي", "kids", "children", "child", "kid"],
    "الغاء": ["الغاء", "الغي", "كنسل", "اكنسل", "تاجيل", "اجل", "cancel", "reschedule", "postpone"],
}
SYNONYMS: dict[str, str] = {}
for canon, words in _SYNONYM_GROUPS.items():
    for w in words:
        SYNONYMS[normalize(w)] = canon

_PREFIXES = ("وبال", "وال", "بال", "فال", "كال", "لل", "ال")
_SUFFIXES = ("كم", "هم", "ها", "ات", "ين", "ون", "ه")


def stem(token: str) -> str:
    """Very light Arabic stemmer: strip common prefixes/suffixes, keep >= 3 letters."""
    if not _ARABIC_LETTER.search(token):
        return token[:-1] if len(token) > 4 and token.endswith("s") else token
    for p in _PREFIXES:
        if token.startswith(p) and len(token) - len(p) >= 3:
            token = token[len(p):]
            break
    else:
        if token[:1] in "وفب" and len(token) >= 5:
            token = token[1:]
    for s in _SUFFIXES:
        if token.endswith(s) and len(token) - len(s) >= 3:
            token = token[: -len(s)]
            break
    return token


def tokens(text: str) -> list[str]:
    """Normalized, synonym-canonicalized, stemmed content tokens."""
    out = []
    for raw in _TOKEN.findall(normalize(text)):
        if raw in SYNONYMS:
            out.append(SYNONYMS[raw])
            continue
        if raw in STOPWORDS or (len(raw) < 2 and not raw.isdigit()):
            continue
        st = stem(raw)
        out.append(SYNONYMS.get(st, st))
    return out


def contains_any(text: str, phrases: list[str] | tuple[str, ...] | set[str]) -> bool:
    """Whole-word/phrase match on normalized text."""
    norm = f" {' '.join(_TOKEN.findall(normalize(text)))} "
    return any(f" {normalize(p)} " in norm for p in phrases)
