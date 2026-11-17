"""Reading uploaded documents: text extraction, type detection, field extraction.

AI path: the model reads the document text and returns its type and key fields.
Rule path (fallback): keyword scoring for the type, regexes for the fields.
"""

import io
import logging
import re

from pypdf import PdfReader

from .validators import TAX_ID_PATTERNS, compact

# pypdf logs a warning for every malformed file; a bad upload is an expected input here.
logging.getLogger("pypdf").setLevel(logging.CRITICAL)

DOC_TYPE_LABELS = {
    "tax_certificate": "tax registration certificate",
    "bank_proof": "bank account proof",
    "invoice": "invoice",
    "other": "document of another kind",
    "unreadable": "unreadable file",
}

KEYWORDS = {
    "tax_certificate": [
        "certificate of registration", "registration certificate", "gstin",
        "goods and services tax", "vat registration", "value added tax",
        "employer identification number", "ust-idnr", "tax authority",
        "internal revenue service", "hm revenue", "bundeszentralamt",
    ],
    "bank_proof": [
        "account holder", "account name", "ifsc", "iban", "routing number",
        "cancelled cheque", "bank letter", "account confirmation",
        "we confirm that", "maintains an account", "swift", "bic",
    ],
    "invoice": [
        "invoice", "bill to", "amount due", "subtotal", "payment terms",
        "due date", "unit price", "qty",
    ],
}

NAME_LABELS = re.compile(
    r"(?:legal name(?: of business)?|name of (?:the )?(?:business|taxpayer|company)|"
    r"registered name|trade name|business name)\s*[:\-]\s*(.+)", re.IGNORECASE)
HOLDER_LABELS = re.compile(
    r"(?:account holder(?: name)?|account name|name of account holder)\s*[:\-]\s*(.+)",
    re.IGNORECASE)
ACCOUNT_LABELS = re.compile(
    r"(?:account (?:number|no\.?)|a/c (?:number|no\.?)|iban)\s*[:\-]\s*([A-Za-z0-9 ]{6,40})",
    re.IGNORECASE)

TAX_LABELS = re.compile(
    r"(?:gstin|vat registration number|vat number|vat no\.?|employer identification number"
    r"(?: \(ein\))?|ein|ust-idnr\.?|tax id(?:entification number)?)\s*[:\-]\s*([A-Za-z0-9\- ]{8,20})",
    re.IGNORECASE)

AI_SYSTEM = (
    "You read business documents submitted during vendor onboarding. "
    "Reply with one JSON object and nothing else."
)

AI_PROMPT = """Classify this document and extract its key fields.

Return JSON with exactly these keys:
- "doc_type": one of "tax_certificate", "bank_proof", "invoice", "other"
- "entity_name": the business or person the document is issued to ("" if none)
- "tax_id": the tax registration number shown ("" if none)
- "account_holder": the bank account holder name ("" if not a bank document)
- "account_number": the account number or IBAN ("" if not a bank document)

Use only what is written in the document. Do not guess missing values.

DOCUMENT TEXT:
---
%s
---"""


def extract_text(pdf_bytes):
    """Text of a PDF, or '' when it cannot be read (scan, corrupt, not a PDF)."""
    if not pdf_bytes:
        return ""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        parts = []
        for page in reader.pages[:5]:
            parts.append(page.extract_text() or "")
        return "\n".join(parts).strip()
    except Exception:
        return ""


def classify_by_keywords(text):
    lowered = text.lower()
    best_type = "other"
    best_score = 0
    for doc_type, words in KEYWORDS.items():
        score = 0
        for word in words:
            if word in lowered:
                score += 1
        if score > best_score:
            best_type = doc_type
            best_score = score
    # An invoice often carries the seller's tax ID and bank details; the word
    # "invoice" in the first lines settles it.
    head = lowered[:200]
    if "invoice" in head and "certificate" not in head:
        return "invoice"
    return best_type


def first_group(pattern, text):
    match = pattern.search(text)
    if not match:
        return ""
    return match.group(1).strip().splitlines()[0].strip()


def find_tax_ids(text):
    """All substrings of the text that fit a supported tax-ID format."""
    found = []
    for raw in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{7,17}", text):
        candidate = compact(raw)
        for pattern in TAX_ID_PATTERNS.values():
            if pattern.match(candidate) and candidate not in found:
                found.append(candidate)
    return found


def read_by_rules(text):
    labelled = compact(first_group(TAX_LABELS, text))
    tax_ids = find_tax_ids(text)
    if not labelled and tax_ids:
        labelled = tax_ids[0]
    return {
        "doc_type": classify_by_keywords(text),
        "entity_name": first_group(NAME_LABELS, text),
        "tax_id": labelled,
        "account_holder": first_group(HOLDER_LABELS, text),
        "account_number": compact(first_group(ACCOUNT_LABELS, text)),
    }


def read_document(pdf_bytes, llm):
    """Returns a dict: doc_type, entity_name, tax_id, account_holder,
    account_number, text, method ('AI' / 'rules' / 'rules (AI unavailable)')."""
    text = extract_text(pdf_bytes)
    if not text:
        return {
            "doc_type": "unreadable", "entity_name": "", "tax_id": "",
            "account_holder": "", "account_number": "", "text": "", "method": "rules",
        }

    result = None
    method = "rules"
    if llm is not None and llm.enabled:
        reply = llm.chat_json(AI_SYSTEM, AI_PROMPT % text[:4000])
        if reply is not None and reply.get("doc_type") in DOC_TYPE_LABELS:
            result = {
                "doc_type": reply.get("doc_type"),
                "entity_name": str(reply.get("entity_name") or "").strip(),
                "tax_id": compact(str(reply.get("tax_id") or "")),
                "account_holder": str(reply.get("account_holder") or "").strip(),
                "account_number": compact(str(reply.get("account_number") or "")),
            }
            method = "AI"
        else:
            method = "rules (AI unavailable)"

    if result is None:
        result = read_by_rules(text)

    result["text"] = text
    result["method"] = method
    return result
