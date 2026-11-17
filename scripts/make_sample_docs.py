"""Generates the PDFs in sample_docs/ from the scenarios in onboarding/samples.py.

Run from the project root:   python scripts/make_sample_docs.py
Needs reportlab (pip install reportlab). The app itself does not need it; the
generated PDFs are committed to the repo.

Every PDF carries a footer saying it is generated test data.
"""

import os
import sys

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from onboarding.samples import SAMPLES, SEEDS, DOCS_DIR, doc_filename  # noqa: E402

FOOTER = "SAMPLE DOCUMENT: generated test data for a software demo. Not issued by any authority or bank."

TAX_HEADERS = {
    "IN": ("Government of India", "Goods and Services Tax",
           "Certificate of Registration (Form GST REG-06)", "GSTIN"),
    "GB": ("HM Revenue and Customs", "Value Added Tax",
           "VAT Registration Certificate", "VAT Registration Number"),
    "US": ("Department of the Treasury", "Internal Revenue Service",
           "Employer Identification Number Confirmation", "Employer Identification Number (EIN)"),
    "DE": ("Bundeszentralamt fuer Steuern", "Federal Central Tax Office",
           "Confirmation of VAT Registration", "USt-IdNr."),
}

BANK_CODE_LABELS = {"IN": "IFSC", "US": "Routing Number", "GB": "BIC", "DE": "BIC"}


def draw_lines(pdf, lines, start_y):
    """lines: list of (text, font, size, gap_after)."""
    y = start_y
    for text, font, size, gap in lines:
        pdf.setFont(font, size)
        pdf.drawString(60, y, text)
        y -= gap
    return y


def finish(pdf):
    pdf.setFont("Helvetica-Oblique", 8)
    pdf.drawString(60, 40, FOOTER)
    pdf.showPage()
    pdf.save()


def make_tax_certificate(path, fields, tax_country):
    issuer, sub_issuer, title, id_label = TAX_HEADERS[tax_country]
    pdf = canvas.Canvas(path, pagesize=A4)
    lines = [
        (issuer, "Helvetica-Bold", 16, 22),
        (sub_issuer, "Helvetica", 12, 34),
        (title, "Helvetica-Bold", 14, 34),
        ("%s: %s" % (id_label, fields["tax_id"]), "Helvetica", 11, 20),
        ("Legal Name of Business: %s" % fields["legal_name"], "Helvetica", 11, 20),
        ("Registered Address: %s" % fields["address"], "Helvetica", 11, 20),
        ("Date of Registration: 14 March 2021", "Helvetica", 11, 20),
        ("Status: Active", "Helvetica", 11, 34),
        ("This certificate confirms that the business named above is registered", "Helvetica", 10, 14),
        ("with the tax authority under the registration number shown.", "Helvetica", 10, 14),
    ]
    draw_lines(pdf, lines, 770)
    finish(pdf)


def make_bank_letter(path, fields, bank_name):
    country = fields["bank_country"]
    account_label = "IBAN" if country in ("GB", "DE") else "Account Number"
    pdf = canvas.Canvas(path, pagesize=A4)
    lines = [
        (bank_name, "Helvetica-Bold", 16, 34),
        ("Account Confirmation Letter", "Helvetica-Bold", 14, 30),
        ("Date: 3 November 2026", "Helvetica", 11, 28),
        ("To whom it may concern,", "Helvetica", 11, 22),
        ("We confirm that the customer named below maintains an account with us.", "Helvetica", 11, 30),
        ("Account Holder: %s" % fields["bank_account_holder"], "Helvetica", 11, 20),
        ("%s: %s" % (account_label, fields["bank_account"]), "Helvetica", 11, 20),
    ]
    if fields["bank_code"]:
        lines.append(("%s: %s" % (BANK_CODE_LABELS[country], fields["bank_code"]), "Helvetica", 11, 20))
    lines.extend([
        ("Account Type: Business Current Account", "Helvetica", 11, 20),
        ("Account Status: Active", "Helvetica", 11, 34),
        ("This letter is issued at the request of the account holder.", "Helvetica", 10, 30),
        ("Authorised Signatory, Branch Operations", "Helvetica", 10, 14),
    ])
    draw_lines(pdf, lines, 770)
    finish(pdf)


def make_invoice(path, fields):
    pdf = canvas.Canvas(path, pagesize=A4)
    lines = [
        ("INVOICE", "Helvetica-Bold", 20, 34),
        ("From: %s" % fields["legal_name"], "Helvetica", 11, 16),
        (fields["address"], "Helvetica", 11, 26),
        ("Invoice No: INV-2026-0412", "Helvetica", 11, 16),
        ("Invoice Date: 28 October 2026", "Helvetica", 11, 16),
        ("Due Date: 27 November 2026", "Helvetica", 11, 26),
        ("Bill To: Castellan Retail Group, 300 Harbor Way, Seattle, WA 98101", "Helvetica", 11, 30),
        ("Description                               Qty      Unit Price      Amount", "Helvetica-Bold", 10, 18),
        ("Sit-stand desk, 160 cm                     12        640.00       7,680.00", "Helvetica", 10, 16),
        ("Task chair, mesh back                      12        310.00       3,720.00", "Helvetica", 10, 16),
        ("Delivery and installation                   1        950.00         950.00", "Helvetica", 10, 26),
        ("Subtotal: 12,350.00", "Helvetica", 11, 16),
        ("Sales Tax (0%): 0.00", "Helvetica", 11, 16),
        ("Amount Due: USD 12,350.00", "Helvetica-Bold", 12, 28),
        ("Payment Terms: Net 30", "Helvetica", 11, 16),
    ]
    draw_lines(pdf, lines, 770)
    finish(pdf)


def build(entry):
    made = []
    fields = entry["fields"]
    tax_spec = entry.get("tax_doc")
    if tax_spec is not None:
        path = os.path.join(DOCS_DIR, doc_filename(entry, "tax_doc"))
        if tax_spec["kind"] == "invoice":
            make_invoice(path, fields)
        else:
            make_tax_certificate(path, fields, tax_spec.get("tax_country", fields["country"]))
        made.append(path)
    bank_spec = entry.get("bank_doc")
    if bank_spec is not None:
        path = os.path.join(DOCS_DIR, doc_filename(entry, "bank_doc"))
        make_bank_letter(path, fields, bank_spec["bank_name"])
        made.append(path)
    return made


def main():
    os.makedirs(DOCS_DIR, exist_ok=True)
    total = 0
    for entry in SAMPLES + SEEDS:
        total += len(build(entry))
        # For the wrong-document scenario, also write the certificate the vendor
        # should have sent, so a resubmission can be demonstrated.
        if entry["key"] == "wrong_document":
            fixed = os.path.join(DOCS_DIR, "wrong_document_tax_corrected.pdf")
            make_tax_certificate(fixed, entry["fields"], entry["fields"]["country"])
            total += 1
    print("Wrote %d PDFs to %s" % (total, DOCS_DIR))


if __name__ == "__main__":
    main()
