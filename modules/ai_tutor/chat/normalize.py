"""Arabic / Iraqi-dialect normalisation into canonical concept tokens (pure, deterministic)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

_DIACRITICS = re.compile("[ً-ٰٟـ]")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_CHARS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي", "ک": "ك", "ی": "ي", "گ": "ك", "چ": "ج"})

# word group -> canonical token. Words are written naturally and normalised at import time.
_GROUPS: dict[str, str] = {
    "c:doctor": "دكتور دكتوره دكاتره دكتر طبيب طبيبه اطباء دكتورنا طبيبنا",
    "c:specialty": "اختصاص اختصاصات تخصص تخصصات",
    "c:employee": "موظف موظفه موظفين موظفات مستخدم مستخدمين",
    "c:account": "حساب حسابات اكاونت",
    "c:patient": "مريض مريضه مرضى مراجع مراجعين زبون زباين عميل",
    "c:appointment": "موعد مواعيد حجز حجوزات",
    "c:schedule": "دوام جدول جداول",
    "c:permission": "صلاحيه صلاحيات صلاحياتي اذن اذونات",
    "c:page": "صفحه صفحات شاشه شاشات",
    "c:diagnosis": "تشخيص",
    "c:problem": "يكمل يشتغل وقف عالق مشكله خطا يتحرك يمشي",
    "v:add": "اضيف اضف اضافه ادخل ادخال اسوي سوي اعمل انشاء انشئ سجل اسجل تسجيل جديد جديده ضيف احجز اغير غير",
    "v:want": "اريد ابي ابغي احتاج اروم بدي",
    "v:teach": "علمني درسني تعلم اتعلم علم اشرح وضح خطوه خطوات تعليم",
    "v:show": "وريني ورني دلني اعرض",
    "v:use": "استخدم استعمل اشتغل",
    "q:how": "شلون شلوت كيف شلونها",
    "q:where": "وين فين اين",
    "q:what": "شنو شنوهي ايش شو شنهو ماهو",
    "q:why": "ليش ليه لماذا",
    "n:now": "هسه هسا الان حاليا",
    "g:hello": "هلا مرحبا السلام اهلا صباح مساء",
    "g:thanks": "شكرا مشكور يعطيك تسلم",
    "m:medical": "علاج دواء ادويه جرعه اعراض مرض وصفه علاجيه",
    # void an invoice / reverse or delete a recorded payment: no real workflow exists yet (no UI button, no
    # backend endpoint), so the chat refuses rather than inventing one. "استرداد" (refund) is a REAL, separate
    # feature (ClinicRefund) and is NOT in this group — it resolves as a normal alias against refund.record.
    "m:reversal": "عكس غاء الغي فسخ حذف",
}
_STOP = set("""في من الي الى علي لو او انا لي لك بس هذا هاي هذي هذه هو هي ذا شي شيء ممكن لطفا تكدر تقدر اكدر اقدر
عياده بالنظام نظام النظام البرنامج برنامج فنورا finora عن مع ال ب ك ما هل يا""".split())


def _norm_chars(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").translate(_DIGITS).lower()
    return _DIACRITICS.sub("", text).translate(_CHARS)


SYN: dict[str, str] = {}
for _token, _words in _GROUPS.items():
    for _word in _words.split():
        SYN[_norm_chars(_word)] = _token
_STOP = {_norm_chars(w) for w in _STOP}

_ARTICLES = ("وال", "بال", "لل", "ال")
_LETTERS = ("و", "ب", "ل", "ف")


def normalize(text: str) -> str:
    cleaned = _PUNCT.sub(" ", _norm_chars(text))
    return re.sub(r"\s+", " ", cleaned).strip()


def _strip_prefix(word: str, known: set[str]) -> str:
    """Drop the definite article always; drop a one-letter clitic only when the rest is a known word."""
    for article in _ARTICLES:
        if word.startswith(article) and len(word) - len(article) >= 3:
            return word[len(article):]
    if word in known:
        return word
    for letter in _LETTERS:
        if word.startswith(letter) and word[1:] in known:
            return word[1:]
    return word


def _fuzzy(word: str, vocabulary: set[str]) -> str:
    if len(word) < 4 or word in vocabulary:
        return word
    best, best_ratio = word, 0.0
    for candidate in vocabulary:
        if abs(len(candidate) - len(word)) > 1 or candidate[0] != word[0]:
            continue
        ratio = SequenceMatcher(None, word, candidate).ratio()
        if ratio > best_ratio:
            best, best_ratio = candidate, ratio
    return best if best_ratio >= 0.84 else word


@dataclass
class Analysis:
    text: str
    words: list[str]
    tokens: list[str]                       # canonical tokens (concepts + u:word), stop words removed
    flags: set[str] = field(default_factory=set)  # q:*, v:want, v:show, n:now, g:*, m:medical ...

    @property
    def content(self) -> set[str]:
        """Tokens that identify WHAT is asked (concepts, add-verb, unknown words); no question/filler tokens."""
        return {t for t in self.tokens if t.startswith(("c:", "u:")) or t == "v:add"}


_FLAG_PREFIXES = ("q:", "v:want", "v:show", "v:teach", "v:use", "n:now", "g:", "m:")


def analyze(text: str, vocabulary: set[str] | None = None) -> Analysis:
    """Normalise, strip fillers, map dialect synonyms (with typo tolerance) to canonical tokens."""
    vocab = (vocabulary or set()) | set(SYN)
    words = normalize(text).split()
    tokens: list[str] = []
    flags: set[str] = set()
    for raw in words:
        word = _strip_prefix(raw, vocab)
        if word in _STOP or raw in _STOP:
            continue
        word = _fuzzy(word, vocab)
        token = SYN.get(word, f"u:{word}")
        if token.startswith(_FLAG_PREFIXES):
            flags.add(token)
            continue
        if token not in tokens:
            tokens.append(token)
    return Analysis(text=" ".join(words), words=words, tokens=tokens, flags=flags)
