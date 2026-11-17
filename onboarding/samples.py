"""Demo scenarios (one happy path, edge cases) and seed history for the dashboard.

All companies, people, tax IDs and bank accounts here are invented test data.
The IDs are built with the real checksum algorithms so they pass format checks.
"""

import os

from .models import APPROVED, PENDING, REJECTED, Submission
from .validators import gstin_check_char, iban_check_digits

DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sample_docs")


def gstin(first14):
    return first14 + gstin_check_char(first14)


def iban(country, bban):
    return country + iban_check_digits(country, bban) + bban


NORTHWIND_IBAN = iban("DE", "500105175407324931")

SAMPLES = [
    {
        "key": "happy_path",
        "label": "Happy path: clean submission",
        "description": "Everything is present, well-formed and consistent. Both documents match the form.",
        "expected": APPROVED,
        "fields": {
            "legal_name": "Meridian Analytics Pvt Ltd",
            "entity_type": "company",
            "country": "IN",
            "tax_id": gstin("29AAECM1234F1Z"),
            "address": "4th Floor, Prestige Tech Park, Outer Ring Road, Bengaluru 560103",
            "contact_name": "Ananya Rao",
            "contact_email": "ananya.rao@meridiananalytics.in",
            "bank_account_holder": "Meridian Analytics Pvt Ltd",
            "bank_country": "IN",
            "bank_account": "50200012345678",
            "bank_code": "HDFC0001234",
        },
        "tax_doc": {"kind": "tax_certificate"},
        "bank_doc": {"kind": "bank_letter", "bank_name": "HDFC Bank Ltd"},
    },
    {
        "key": "name_variant",
        "label": "Edge 1a: same company, name written differently",
        "description": "Legal name is 'Acme Technologies Pvt Ltd'; the bank account is held as "
                       "'ACME TECH PRIVATE LIMITED'. Same entity, so it should pass with a note, "
                       "not bounce back to the vendor.",
        "expected": APPROVED,
        "fields": {
            "legal_name": "Acme Technologies Pvt Ltd",
            "entity_type": "company",
            "country": "IN",
            "tax_id": gstin("27AAACA1111A1Z"),
            "address": "Unit 12, Mindspace Business Park, Airoli, Navi Mumbai 400708",
            "contact_name": "Vikram Shah",
            "contact_email": "vikram@acmetech.co.in",
            "bank_account_holder": "ACME TECH PRIVATE LIMITED",
            "bank_country": "IN",
            "bank_account": "001205001234",
            "bank_code": "ICIC0000012",
        },
        "tax_doc": {"kind": "tax_certificate"},
        "bank_doc": {"kind": "bank_letter", "bank_name": "ICICI Bank Ltd"},
    },
    {
        "key": "personal_account",
        "label": "Edge 1b: company paid into a personal account",
        "description": "A registered LLC gives a bank account held by an individual. Every field "
                       "is well-formed, so only a cross-check catches it. Rejected, with the "
                       "reason kept out of the vendor message.",
        "expected": REJECTED,
        "fields": {
            "legal_name": "Vertex Supplies LLC",
            "entity_type": "company",
            "country": "US",
            "tax_id": "47-2917364",
            "address": "2200 Commerce Street, Suite 410, Dallas, TX 75201",
            "contact_name": "Daniel Whitaker",
            "contact_email": "daniel@vertexsupplies.com",
            "bank_account_holder": "Daniel R Whitaker",
            "bank_country": "US",
            "bank_account": "483920175",
            "bank_code": "021000021",
        },
        "tax_doc": {"kind": "tax_certificate"},
        "bank_doc": {"kind": "bank_letter", "bank_name": "First Meridian Bank"},
    },
    {
        "key": "wrong_country_tax_id",
        "label": "Edge 2: tax ID from the wrong country",
        "description": "Vendor says it is registered in the UK but supplies an Indian GSTIN (a "
                       "valid one). Pending, with a message that names the exact number needed.",
        "expected": PENDING,
        "fields": {
            "legal_name": "Harlow & Finch Ltd",
            "entity_type": "company",
            "country": "GB",
            "tax_id": gstin("07AABCH5678K1Z"),
            "address": "18 Carver Street, Sheffield S1 4FS",
            "contact_name": "Priya Menon",
            "contact_email": "priya.menon@harlowfinch.co.uk",
            "bank_account_holder": "Harlow & Finch Ltd",
            "bank_country": "GB",
            "bank_account": iban("GB", "BARC20714583920147"),
            "bank_code": "BARCGB22",
        },
        "tax_doc": {"kind": "tax_certificate", "tax_country": "IN"},
        "bank_doc": {"kind": "bank_letter", "bank_name": "Barclays Bank UK PLC"},
    },
    {
        "key": "wrong_document",
        "label": "Edge 3: wrong document attached",
        "description": "The file uploaded as the tax certificate is actually one of the vendor's "
                       "own invoices. The form is fine. Pending, asking for the right document.",
        "expected": PENDING,
        "fields": {
            "legal_name": "Lumen Office Interiors Inc",
            "entity_type": "company",
            "country": "US",
            "tax_id": "83-1904276",
            "address": "915 Wharf Avenue, Portland, OR 97209",
            "contact_name": "Grace Lin",
            "contact_email": "grace.lin@lumeninteriors.com",
            "bank_account_holder": "Lumen Office Interiors Inc",
            "bank_country": "US",
            "bank_account": "7730018842",
            "bank_code": "011000015",
        },
        "tax_doc": {"kind": "invoice"},
        "bank_doc": {"kind": "bank_letter", "bank_name": "Cascade Federal Bank"},
    },
    {
        "key": "shared_bank_account",
        "label": "Edge 4: bank account already used by another vendor",
        "description": "A new vendor, clean on every individual check, gives the same IBAN as "
                       "Northwind Logistics GmbH, which is already approved. Rejected and routed "
                       "to fraud review; the vendor is not told why.",
        "expected": REJECTED,
        "fields": {
            "legal_name": "Baltic Freight Partners GmbH",
            "entity_type": "company",
            "country": "DE",
            "tax_id": "DE298471650",
            "address": "Am Sandtorkai 41, 20457 Hamburg",
            "contact_name": "Jonas Becker",
            "contact_email": "j.becker@balticfreight.de",
            "bank_account_holder": "Baltic Freight Partners GmbH",
            "bank_country": "DE",
            "bank_account": NORTHWIND_IBAN,
            "bank_code": "INGDDEFFXXX",
        },
        "tax_doc": {"kind": "tax_certificate"},
        "bank_doc": {"kind": "bank_letter", "bank_name": "ING-DiBa AG"},
    },
    {
        "key": "incomplete",
        "label": "Extra: incomplete submission",
        "description": "Sole proprietor with no IFSC code, no bank proof and a truncated email "
                       "address. Pending, with all three gaps listed in one message.",
        "expected": PENDING,
        "fields": {
            "legal_name": "Sundar Textiles",
            "entity_type": "sole_proprietor",
            "country": "IN",
            "tax_id": gstin("33AKXPR4821M1Z"),
            "address": "27 Avinashi Road, Tiruppur 641603",
            "contact_name": "Sundar Rajan",
            "contact_email": "accounts@sundartextiles",
            "bank_account_holder": "Sundar Rajan",
            "bank_country": "IN",
            "bank_account": "918010045672310",
            "bank_code": "",
        },
        "tax_doc": {"kind": "tax_certificate"},
        "bank_doc": None,
    },
]

# History that exists before the demo starts, so the dashboard is not empty and
# the duplicate-bank-account check has something to find.
SEEDS = [
    {
        "key": "seed_northwind",
        "days_ago": 12,
        "expected": APPROVED,
        "fields": {
            "legal_name": "Northwind Logistics GmbH",
            "entity_type": "company",
            "country": "DE",
            "tax_id": "DE811234567",
            "address": "Hanauer Landstrasse 126, 60314 Frankfurt am Main",
            "contact_name": "Katrin Vogel",
            "contact_email": "k.vogel@northwind-logistics.de",
            "bank_account_holder": "Northwind Logistics GmbH",
            "bank_country": "DE",
            "bank_account": NORTHWIND_IBAN,
            "bank_code": "INGDDEFFXXX",
        },
        "tax_doc": {"kind": "tax_certificate"},
        "bank_doc": {"kind": "bank_letter", "bank_name": "ING-DiBa AG"},
    },
    {
        "key": "seed_brightpath",
        "days_ago": 9,
        "expected": APPROVED,
        "fields": {
            "legal_name": "Brightpath Consulting LLC",
            "entity_type": "company",
            "country": "US",
            "tax_id": "36-4821975",
            "address": "640 North Wells Street, Chicago, IL 60654",
            "contact_name": "Marisol Ortega",
            "contact_email": "marisol@brightpathconsulting.com",
            "bank_account_holder": "Brightpath Consulting LLC",
            "bank_country": "US",
            "bank_account": "441720985",
            "bank_code": "026009593",
        },
        "tax_doc": {"kind": "tax_certificate"},
        "bank_doc": {"kind": "bank_letter", "bank_name": "Lakeshore National Bank"},
    },
    {
        "key": "seed_orchid",
        "days_ago": 6,
        "expected": PENDING,
        "fields": {
            "legal_name": "Orchid Print Works Pvt Ltd",
            "entity_type": "company",
            "country": "IN",
            "tax_id": gstin("24AAFCO4821M1Z"),
            "address": "Plot 88, GIDC Estate, Vatva, Ahmedabad 382445",
            "contact_name": "Hetal Desai",
            "contact_email": "hetal@orchidprintworks.in",
            "bank_account_holder": "Orchid Print Works Pvt Ltd",
            "bank_country": "IN",
            "bank_account": "39847201156",
            "bank_code": "SBIN0005943",
        },
        "tax_doc": {"kind": "tax_certificate"},
        "bank_doc": None,
    },
    {
        "key": "seed_kestrel",
        "days_ago": 4,
        "expected": APPROVED,
        "fields": {
            "legal_name": "Kestrel Foods Ltd",
            "entity_type": "company",
            "country": "GB",
            "tax_id": "GB284915637",
            "address": "Unit 5, Riverside Trading Estate, Leeds LS10 1AB",
            "contact_name": "Tom Ashworth",
            "contact_email": "tom.ashworth@kestrelfoods.co.uk",
            "bank_account_holder": "Kestrel Foods Limited",
            "bank_country": "GB",
            "bank_account": iban("GB", "LOYD30926541873302"),
            "bank_code": "LOYDGB2L",
        },
        "tax_doc": {"kind": "tax_certificate"},
        "bank_doc": {"kind": "bank_letter", "bank_name": "Lloyds Bank plc"},
    },
    {
        "key": "seed_zenith",
        "days_ago": 2,
        "expected": REJECTED,
        "fields": {
            "legal_name": "Zenith Trade Corp",
            "entity_type": "company",
            "country": "US",
            "tax_id": "59-2087341",
            "address": "1180 Biscayne Boulevard, Miami, FL 33132",
            "contact_name": "Marcus Ellery",
            "contact_email": "marcus@zenithtrade.com",
            "bank_account_holder": "Marcus Ellery",
            "bank_country": "US",
            "bank_account": "6620914473",
            "bank_code": "121000248",
        },
        "tax_doc": {"kind": "tax_certificate"},
        "bank_doc": {"kind": "bank_letter", "bank_name": "Pacific Coast Bank"},
    },
]


def doc_filename(entry, which):
    """File name of a sample document, or '' when the scenario has none."""
    if entry.get(which) is None:
        return ""
    suffix = "tax" if which == "tax_doc" else "bank"
    return "%s_%s.pdf" % (entry["key"], suffix)


def load_doc(filename):
    if not filename:
        return None
    path = os.path.join(DOCS_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as handle:
        return handle.read()


def find_sample(key):
    for entry in SAMPLES:
        if entry["key"] == key:
            return entry
    return None


def to_submission(entry):
    """Build a Submission (with document bytes) from a sample or seed entry."""
    tax_name = doc_filename(entry, "tax_doc")
    bank_name = doc_filename(entry, "bank_doc")
    return Submission(
        tax_doc=load_doc(tax_name), tax_doc_name=tax_name,
        bank_doc=load_doc(bank_name), bank_doc_name=bank_name,
        **entry["fields"]
    )
