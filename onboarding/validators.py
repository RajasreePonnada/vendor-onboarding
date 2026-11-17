"""Format checks for tax IDs, bank details and email addresses.

Every function here is deterministic: same input, same answer, no AI involved.
"""

import re

GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

TAX_ID_NAMES = {
    "IN": "GSTIN",
    "GB": "UK VAT number",
    "US": "EIN",
    "DE": "German VAT ID (USt-IdNr.)",
}

TAX_ID_HINTS = {
    "IN": "15 characters, e.g. 29ABCDE1234F1Z5",
    "GB": "GB followed by 9 digits, e.g. GB123456789",
    "US": "9 digits, e.g. 12-3456789",
    "DE": "DE followed by 9 digits, e.g. DE123456789",
}

TAX_ID_PATTERNS = {
    "IN": re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"),
    "GB": re.compile(r"^GB\d{9}(\d{3})?$"),
    "US": re.compile(r"^\d{9}$"),
    "DE": re.compile(r"^DE\d{9}$"),
}

BANK_CODE_NAMES = {
    "IN": "IFSC code",
    "GB": "BIC / SWIFT code",
    "US": "ABA routing number",
    "DE": "BIC / SWIFT code",
}

FREE_MAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "rediffmail.com",
    "icloud.com", "proton.me", "protonmail.com", "aol.com", "gmx.de", "web.de",
}

EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
IFSC_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
BIC_PATTERN = re.compile(r"^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$")

IBAN_LENGTHS = {"GB": 22, "DE": 22}


def compact(value):
    """Upper-case and strip everything that is not a letter or digit."""
    return re.sub(r"[^A-Za-z0-9]", "", value or "").upper()


def gstin_check_char(first14):
    """Checksum character for the first 14 characters of a GSTIN (Luhn mod 36)."""
    total = 0
    factor = 2
    for ch in reversed(first14):
        digit = factor * GSTIN_CHARS.index(ch)
        digit = digit // 36 + digit % 36
        total += digit
        factor = 1 if factor == 2 else 2
    return GSTIN_CHARS[(36 - total % 36) % 36]


def gstin_state_code_ok(code):
    number = int(code)
    return 1 <= number <= 38 or number in (97, 99)


def matches_country_format(tax_id, country):
    pattern = TAX_ID_PATTERNS.get(country)
    if pattern is None:
        return False
    return bool(pattern.match(compact(tax_id)))


def guess_tax_id_country(tax_id):
    """Which supported country's format does this ID fit? Returns a code or ''."""
    for country in TAX_ID_PATTERNS:
        if matches_country_format(tax_id, country):
            return country
    return ""


def validate_tax_id(tax_id, country):
    """Returns (ok, problem, looks_like_country).

    problem is '' when ok. looks_like_country is set when the ID fails for the
    claimed country but fits another supported country's format.
    """
    value = compact(tax_id)
    if country not in TAX_ID_PATTERNS:
        return False, "Unsupported country '%s'." % country, ""
    if not value:
        return False, "Tax ID is empty.", ""
    if not TAX_ID_PATTERNS[country].match(value):
        other = guess_tax_id_country(value)
        if other and other != country:
            return False, "Format belongs to a different country.", other
        return False, "Does not match the %s format (%s)." % (
            TAX_ID_NAMES[country], TAX_ID_HINTS[country]), ""
    if country == "IN":
        if not gstin_state_code_ok(value[:2]):
            return False, "GSTIN state code '%s' is not a valid Indian state code." % value[:2], ""
        expected = gstin_check_char(value[:14])
        if value[14] != expected:
            return False, "GSTIN checksum character is wrong (a digit or letter was probably mistyped).", ""
    return True, "", ""


def iban_ok(iban):
    """ISO 13616 mod-97 check."""
    value = compact(iban)
    if len(value) < 15 or not re.match(r"^[A-Z]{2}\d{2}[A-Z0-9]+$", value):
        return False
    rearranged = value[4:] + value[:4]
    digits = ""
    for ch in rearranged:
        if ch.isdigit():
            digits += ch
        else:
            digits += str(ord(ch) - 55)
    return int(digits) % 97 == 1


def iban_check_digits(country, bban):
    """Check digits for a country code + BBAN. Used to build test data."""
    rearranged = compact(bban) + country + "00"
    digits = ""
    for ch in rearranged:
        if ch.isdigit():
            digits += ch
        else:
            digits += str(ord(ch) - 55)
    return "%02d" % (98 - int(digits) % 97)


def aba_routing_ok(routing):
    value = compact(routing)
    if not re.match(r"^\d{9}$", value):
        return False
    d = [int(ch) for ch in value]
    total = 3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5] + d[8])
    return total % 10 == 0


def validate_bank(bank_country, account, code):
    """Returns a list of problem strings (empty list = bank details are well-formed)."""
    problems = []
    acct = compact(account)
    bank_code = compact(code)
    if bank_country == "IN":
        if acct and not re.match(r"^\d{9,18}$", acct):
            problems.append("Indian account numbers are 9 to 18 digits.")
        if bank_code and not IFSC_PATTERN.match(bank_code):
            problems.append("IFSC code should be 11 characters: 4 letters, a zero, then 6 letters or digits.")
    elif bank_country == "US":
        if acct and not re.match(r"^\d{4,17}$", acct):
            problems.append("US account numbers are 4 to 17 digits.")
        if bank_code and not aba_routing_ok(bank_code):
            problems.append("ABA routing number fails its checksum (9 digits expected).")
    elif bank_country in ("GB", "DE"):
        if acct:
            if not acct.startswith(bank_country):
                problems.append("IBAN should start with %s for a bank account in %s." % (
                    bank_country, bank_country))
            elif len(acct) != IBAN_LENGTHS[bank_country]:
                problems.append("IBAN for %s should be %d characters; got %d." % (
                    bank_country, IBAN_LENGTHS[bank_country], len(acct)))
            elif not iban_ok(acct):
                problems.append("IBAN fails its checksum (a digit was probably mistyped).")
        if bank_code and not BIC_PATTERN.match(bank_code):
            problems.append("BIC / SWIFT code should be 8 or 11 characters.")
    elif bank_country:
        problems.append("Unsupported bank country '%s'." % bank_country)
    return problems


def validate_email(email):
    """Returns (ok, is_free_mail)."""
    value = (email or "").strip()
    if not EMAIL_PATTERN.match(value):
        return False, False
    domain = value.split("@", 1)[1].lower()
    return True, domain in FREE_MAIL_DOMAINS
