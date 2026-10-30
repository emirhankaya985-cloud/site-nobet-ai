"""LeadPilot v0.1.8 offline intent routing; no AI/network provider."""
import re
import unicodedata

def normal(text: str) -> str:
    text = text.translate(str.maketrans("İIıŞşĞğÜüÖöÇç", "iiiSsgguuoocc"))
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def has_word(text: str, words: tuple[str, ...]) -> bool:
    return any(re.search(r"\b" + re.escape(word) + r"\b", text) for word in words)


def has_stem(text: str, stems: tuple[str, ...]) -> bool:
    """Recognize inflected Turkish words, not substrings within unrelated words."""
    return any(re.search(r"\b" + re.escape(stem) + r"[a-z]*\b", text) for stem in stems)


def rule_intent(text: str) -> str:
    n = normal(text)
    if has_stem(n, ("insan", "yetkili", "temsilci", "sikayet", "iade", "iptal")):
        return "human"
    if has_stem(n, ("randevu", "rezervasyon", "musait", "yarin", "bugun")):
        return "appointment"
    # Asking opening hours is not a price quote; avoid the ambiguous "kaç" case.
    if "saat kac" in n or "kacta" in n:
        return "other"
    if has_stem(n, ("fiyat", "ucret", "indirim", "teklif", "maliyet", "tutar", "lira", "kac")) or has_word(n, ("tl",)):
        return "price"
    if has_stem(n, ("saat",)):
        return "appointment"
    if has_word(n, ("merhaba", "selam", "hello")) and len(n.split()) <= 4:
        return "greeting"
    return "other"


