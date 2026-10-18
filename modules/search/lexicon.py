"""Arabic normalisation and the Iraqi shopping vocabulary (categories, brands, units, intents)."""
from __future__ import annotations

import re
import unicodedata

_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")  # harakat + tatweel
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_LETTERS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي", "گ": "ك",
                          "ڤ": "ف", "پ": "ب", "چ": "ج", "ژ": "ز", "ک": "ك", "ی": "ي", "ـ": ""})


def normalize(text: object) -> str:
    """Spelling-insensitive form: no diacritics, unified alef / ya / ta-marbuta / hamza, Latin digits, lowercase."""
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = _DIACRITICS.sub("", s).translate(_LETTERS).translate(_DIGITS).casefold()
    s = re.sub(r"[^\w\s.+%-]", " ", s)  # keep letters, digits, dot (1.5), plus, percent, dash
    return re.sub(r"\s+", " ", s).strip()


def compact(text: object) -> str:
    """Model / code key: «UA-55 CU7000» → «ua55cu7000»."""
    return re.sub(r"[\s\-_./]+", "", normalize(text))


# category → spellings / dialect words that mean it (all already normalised)
CATEGORY_WORDS: dict[str, tuple[str, ...]] = {
    "شاشات": ("شاشه", "شاشات", "تلفزيون", "تلفاز", "تلفزيونات", "تي في", "tv", "television", "screen", "سمارت تي في"),
    "سبالت": ("سبلت", "سبالت", "سبليت", "مكيف", "مكيفات", "مبرده سبلت", "split", "ac", "air conditioner"),
    "غسالات": ("غساله", "غسالات", "washer", "washing machine", "حوضين", "توب لود", "فرنت لود"),
    "ثلاجات": ("ثلاجه", "ثلاجات", "براد", "براده", "برادات", "fridge", "refrigerator", "مجمده", "فريزر", "freezer"),
    "طباخات": ("طباخ", "طباخه", "طباخات", "فرن", "cooker", "oven", "غاز طبخ"),
    "مبردات": ("مبرده", "مبردات", "cooler"),
    "مكانس": ("مكنسه", "مكانس", "vacuum"),
    "غسالات صحون": ("غساله صحون", "جلايه", "غساله اطباق", "dishwasher"),
}
# words mapped to a category only when nothing more specific is present
GENERIC_ONLY = {"حوضين"}

BRAND_WORDS: dict[str, tuple[str, ...]] = {
    "LG": ("lg", "ال جي", "الجي", "ال جى", "elgy"),
    "Samsung": ("samsung", "سامسونج", "سامسونك", "سمسونك", "سامسونگ", "سمسونج"),
    "TCL": ("tcl", "تي سي ال", "تى سى ال", "تيسيال"),
    "Gree": ("gree", "جري", "كري", "غري"),
    "Hisense": ("hisense", "هايسنس", "هايسنز"),
    "Haier": ("haier", "هاير"),
    "Midea": ("midea", "ميديا", "ميدیا"),
    "Sharp": ("sharp", "شارب"),
    "Toshiba": ("toshiba", "توشيبا"),
    "Beko": ("beko", "بيكو"),
    "Ariston": ("ariston", "اريستون"),
    "Denka": ("denka", "دنكا"),
    "Sony": ("sony", "سوني"),
    "Xiaomi": ("xiaomi", "شاومي", "mi"),
}

# spoken numbers used in the shop («الجي خمسين» = 50 inch LG)
NUMBER_WORDS = {"عشره": 10, "عشرين": 20, "ثلاثين": 30, "اربعين": 40, "خمسين": 50, "ستين": 60, "سبعين": 70,
                "خمسه وخمسين": 55, "خمسه و خمسين": 55, "اثنين واربعين": 42, "خمسه وستين": 65, "خمسه و ستين": 65,
                "خمسه وسبعين": 75, "اثنين وثلاثين": 32, "ثلاثه واربعين": 43}

FEATURE_WORDS: dict[str, tuple[str, ...]] = {
    "inverter": ("انفرتر", "انفيرتر", "inverter"),
    "smart": ("سمارت", "ذكيه", "smart", "اندرويد", "android", "webos", "google tv", "جوجل تي في"),
    "4k": ("4k", "فور كي", "uhd", "الترا"),
    "hot_cold": ("حار بارد", "حار و بارد", "تدفئه", "heat pump"),
    "twin_tub": ("حوضين", "twin tub"),
    "front_load": ("فرنت لود", "باب امامي", "front load"),
    "no_frost": ("نوفروست", "نو فروست", "no frost"),
    "gaming": ("ps5", "بلي ستيشن", "بلايستيشن", "playstation", "xbox", "العاب", "جيمنج", "gaming", "120hz", "144hz"),
    "efficient": ("ما تصرف", "وما تصرف", "ماتصرف", "قليله الصرف", "قليل الصرف", "توفير طاقه", "موفره", "اقتصاديه", "a+++", "inverter"),
    "large": ("كبيره", "كبير", "عائلي", "عائله"),
}

STOP_WORDS = {"اريد", "اريده", "ابي", "ابغى", "عندي", "شنو", "اكو", "بيه", "عدكم", "عدكم", "من", "على", "في", "الى",
              "مع", "و", "او", "بس", "هواي", "كلش", "جدا", "جيده", "زينه", "حلوه", "رخيص", "رخيصه", "سعر", "سعره",
              "بسعر", "شي", "شكد", "قديش", "لل", "للـ", "ال", "اقل", "اكثر", "تحت", "فوق", "ضمن", "حدود", "حدود",
              "الف", "الاف", "مليون", "دينار", "الف دينار", "ب", "لـ"}


# Every vocabulary entry goes through the same normalisation as the text it is matched against («إلى» → «الي»).
CATEGORY_WORDS = {k: tuple(dict.fromkeys(normalize(w) for w in v)) for k, v in CATEGORY_WORDS.items()}
GENERIC_ONLY = {normalize(w) for w in GENERIC_ONLY}
BRAND_WORDS = {k: tuple(dict.fromkeys(normalize(w) for w in v)) for k, v in BRAND_WORDS.items()}
NUMBER_WORDS = {normalize(k): v for k, v in NUMBER_WORDS.items()}
FEATURE_WORDS = {k: tuple(dict.fromkeys(normalize(w) for w in v)) for k, v in FEATURE_WORDS.items()}
STOP_WORDS = {normalize(w) for w in STOP_WORDS}
