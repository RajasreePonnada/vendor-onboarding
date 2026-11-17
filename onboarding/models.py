"""Data shapes shared by the pipeline, the store and the UI."""

from dataclasses import dataclass, field, asdict

# Final statuses
APPROVED = "approved"
PENDING = "pending"
REJECTED = "rejected"

# Finding severities, from harmless to blocking
OK = "ok"        # check passed
NOTE = "note"    # passed, but a reviewer should know about it
FIX = "fix"      # vendor can fix it -> pending
BLOCK = "block"  # cannot be fixed by the vendor / fraud risk -> rejected

SEVERITY_RANK = {OK: 0, NOTE: 1, FIX: 2, BLOCK: 3}

COUNTRIES = {
    "IN": "India",
    "GB": "United Kingdom",
    "US": "United States",
    "DE": "Germany",
}

ENTITY_TYPES = {
    "company": "Registered company",
    "sole_proprietor": "Sole proprietor / individual",
}


@dataclass
class Finding:
    severity: str
    code: str
    message: str                 # internal reasoning, shown to the reviewer
    vendor_action: str = ""      # what the vendor is asked to do (empty = nothing)
    confidential: bool = False   # never disclosed to the vendor

    def to_dict(self):
        return asdict(self)


@dataclass
class StageResult:
    key: str
    title: str
    status: str                  # ok / note / fix / block / skipped
    findings: list = field(default_factory=list)
    method: str = "rules"        # "rules", "AI", or "rules (AI unavailable)"
    duration_ms: int = 0

    def to_dict(self):
        return {
            "key": self.key,
            "title": self.title,
            "status": self.status,
            "findings": [f.to_dict() for f in self.findings],
            "method": self.method,
            "duration_ms": self.duration_ms,
        }


@dataclass
class Submission:
    legal_name: str = ""
    entity_type: str = "company"
    country: str = ""
    tax_id: str = ""
    address: str = ""
    contact_name: str = ""
    contact_email: str = ""
    bank_account_holder: str = ""
    bank_country: str = ""
    bank_account: str = ""       # account number, or IBAN for GB/DE
    bank_code: str = ""          # IFSC (IN), routing number (US), BIC (GB/DE)
    tax_doc: bytes = None
    tax_doc_name: str = ""
    bank_doc: bytes = None
    bank_doc_name: str = ""

    def public_fields(self):
        """Everything except the raw document bytes, for storage and display."""
        return {
            "legal_name": self.legal_name,
            "entity_type": self.entity_type,
            "country": self.country,
            "tax_id": self.tax_id,
            "address": self.address,
            "contact_name": self.contact_name,
            "contact_email": self.contact_email,
            "bank_account_holder": self.bank_account_holder,
            "bank_country": self.bank_country,
            "bank_account": self.bank_account,
            "bank_code": self.bank_code,
            "tax_doc_name": self.tax_doc_name,
            "bank_doc_name": self.bank_doc_name,
        }


@dataclass
class RunResult:
    run_id: str
    created_at: str
    status: str
    summary: str
    submission: dict
    stages: list                 # list of StageResult dicts
    vendor_email: str = ""
    internal_note: str = ""
    ai_mode: str = "off"
    duration_ms: int = 0
    resubmission_of: str = ""

    def to_dict(self):
        return asdict(self)
