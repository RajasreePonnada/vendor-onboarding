"""Company-name normalisation and comparison.

"Acme Technologies Pvt Ltd" and "ACME TECH PRIVATE LIMITED" are the same
company. "Acme Technologies Pvt Ltd" and "Rohan Mehta" are not. This module
sorts name pairs into four buckets so the pipeline can treat each differently.
"""

import re
from difflib import SequenceMatcher

LEGAL_SUFFIXES = {
    "pvt", "private", "ltd", "limited", "llc", "llp", "inc", "incorporated",
    "corp", "corporation", "co", "company", "gmbh", "ag", "plc", "ug", "kg",
    "sa", "bv", "pte", "lp", "the",
}

BUSINESS_WORDS = {
    "technologies", "technology", "tech", "solutions", "logistics", "logistik",
    "services", "analytics", "systems", "trading", "trade", "enterprises",
    "industries", "consulting", "group", "labs", "foods", "freight", "supplies",
    "interiors", "partners", "holdings", "textiles", "works", "print", "office",
    "software", "global", "international", "associates", "ventures", "bank",
}

MATCH = "match"          # identical once case, punctuation and suffixes are ignored
VARIANT = "variant"      # same entity, written differently (abbreviation, typo)
AMBIGUOUS = "ambiguous"  # could go either way -> needs judgement
MISMATCH = "mismatch"    # clearly different


def tokens(name):
    cleaned = re.sub(r"[^a-z0-9& ]", " ", (name or "").lower())
    cleaned = cleaned.replace("&", " and ")
    return [t for t in cleaned.split() if t]


def core_tokens(name):
    """Tokens with legal suffixes removed."""
    return [t for t in tokens(name) if t not in LEGAL_SUFFIXES]


def has_legal_suffix(name):
    for t in tokens(name):
        if t in LEGAL_SUFFIXES and t != "the":
            return True
    return False


def looks_like_person(name):
    """Heuristic: 2-4 alphabetic words, no legal suffix, no business vocabulary."""
    toks = tokens(name)
    if len(toks) < 2 or len(toks) > 4:
        return False
    if has_legal_suffix(name):
        return False
    for t in toks:
        if t in BUSINESS_WORDS or t == "and":
            return False
        if not t.isalpha():
            return False
    return True


def is_abbreviation_pair(a_tokens, b_tokens):
    """True when the two token lists line up and each pair is equal or one
    token is a prefix (3+ letters) of the other: technologies / tech."""
    if len(a_tokens) != len(b_tokens) or not a_tokens:
        return False
    for a, b in zip(a_tokens, b_tokens):
        if a == b:
            continue
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        if len(shorter) < 3 or not longer.startswith(shorter):
            return False
    return True


def compare_names(a, b):
    """Returns (verdict, score) where score is a 0-1 similarity."""
    core_a = core_tokens(a)
    core_b = core_tokens(b)
    if not core_a or not core_b:
        return MISMATCH, 0.0
    if core_a == core_b:
        return MATCH, 1.0
    if is_abbreviation_pair(core_a, core_b):
        return VARIANT, 0.9
    score = SequenceMatcher(None, " ".join(core_a), " ".join(core_b)).ratio()
    if score >= 0.88:
        return VARIANT, score
    if score >= 0.55:
        return AMBIGUOUS, score
    return MISMATCH, score


def name_appears_in(name, text):
    """True when every core token of `name` occurs in `text` (used to check a
    name against the raw text of a document)."""
    wanted = core_tokens(name)
    if not wanted:
        return False
    haystack = set(tokens(text))
    for t in wanted:
        if t not in haystack:
            return False
    return True
