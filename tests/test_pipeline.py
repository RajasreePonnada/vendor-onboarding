"""End-to-end checks for every demo scenario, on the rule path and with a mocked AI.

Run from the project root:   python tests/test_pipeline.py
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from onboarding.llm import LLM  # noqa: E402
from onboarding.models import APPROVED, PENDING, REJECTED, Submission  # noqa: E402
from onboarding.pipeline import run_to_completion  # noqa: E402
from onboarding.samples import SAMPLES, SEEDS, find_sample, to_submission  # noqa: E402
from onboarding.seed import seed_if_empty  # noqa: E402
from onboarding.store import Store  # noqa: E402
from onboarding import validators  # noqa: E402
from onboarding.names import compare_names, looks_like_person, MATCH, VARIANT, MISMATCH  # noqa: E402

failures = []


def check(label, condition, detail=""):
    mark = "PASS" if condition else "FAIL"
    print("  [%s] %s %s" % (mark, label, detail))
    if not condition:
        failures.append(label)


def fresh_store():
    folder = tempfile.mkdtemp()
    store = Store(os.path.join(folder, "test.db"))
    seed_if_empty(store)
    return store


def all_findings(run):
    found = []
    for stage in run.stages:
        for f in stage["findings"]:
            found.append(f)
    return found


def codes(run):
    return [f["code"] for f in all_findings(run)]


class MockLLM(LLM):
    """Stands in for a real model: answers by looking at the prompt."""

    def __init__(self, broken=False):
        LLM.__init__(self, api_key="test", base_url="http://mock", model="mock-model")
        self.broken = broken

    def chat_text(self, system, user):
        self.calls += 1
        if self.broken:
            self.failures += 1
            return None
        if "opening paragraph" in user:
            return "Thanks for sending your registration. We need a little more before we can approve it."
        if "Bank account holder" in user:
            if "ACME TECH" in user:
                return '{"same_entity": true, "holder_type": "organisation", "reason": "Tech abbreviates Technologies."}'
            if "Kestrel" in user:
                return '{"same_entity": true, "holder_type": "organisation", "reason": "Ltd and Limited are equivalent."}'
            if "Whitaker" in user or "Ellery" in user or "Sundar Rajan" in user:
                return '{"same_entity": false, "holder_type": "individual", "reason": "The holder is a personal name."}'
            return '{"same_entity": true, "holder_type": "organisation", "reason": "Mock says yes."}'
        if "DOCUMENT TEXT" in user:
            body = user.split("DOCUMENT TEXT:", 1)[1]
            if "INVOICE" in body:
                return '```json\n{"doc_type": "invoice", "entity_name": "", "tax_id": "", "account_holder": "", "account_number": ""}\n```'
            if "Account Confirmation Letter" in body:
                return '{"doc_type": "bank_proof", "entity_name": "", "tax_id": "", "account_holder": "", "account_number": ""}'
            return '{"doc_type": "tax_certificate", "entity_name": "", "tax_id": "", "account_holder": "", "account_number": ""}'
        return None


print("Validators")
check("GSTIN known-good checksum", validators.gstin_check_char("27AAPFU0939F1Z") == "V")
check("GSTIN with one wrong character fails", not validators.validate_tax_id("27AAPFU0939F1ZX", "IN")[0])
check("GSTIN detected as Indian when claimed GB",
      validators.validate_tax_id("07AABCH5678K1Z5", "GB")[2] == "IN")
check("EIN with hyphen passes", validators.validate_tax_id("47-2917364", "US")[0])
check("IBAN checksum passes", validators.iban_ok("DE89370400440532013000"))
check("IBAN with a changed digit fails", not validators.iban_ok("DE89370400440532013001"))
check("ABA routing checksum", validators.aba_routing_ok("021000021") and not validators.aba_routing_ok("021000022"))
check("Truncated email fails", not validators.validate_email("accounts@sundartextiles")[0])

print("Names")
check("Suffix-only difference is a match", compare_names("Kestrel Foods Ltd", "Kestrel Foods Limited")[0] == MATCH)
check("Abbreviation is a variant", compare_names("Acme Technologies Pvt Ltd", "ACME TECH PRIVATE LIMITED")[0] == VARIANT)
check("Person vs company is a mismatch", compare_names("Vertex Supplies LLC", "Daniel R Whitaker")[0] == MISMATCH)
check("Person detected", looks_like_person("Daniel R Whitaker") and not looks_like_person("Vertex Supplies LLC"))

print("Seed history")
store = fresh_store()
rows = store.list_runs()
by_name = {}
for row in rows:
    by_name[row["vendor_name"]] = row["status"]
for entry in SEEDS:
    name = entry["fields"]["legal_name"]
    check("seed %s -> %s" % (name, entry["expected"]), by_name.get(name) == entry["expected"],
          "(got %s)" % by_name.get(name))

for mode_label, make_llm in (("rule path (AI off)", LLM.disabled), ("mocked AI", MockLLM)):
    print("Scenarios, %s" % mode_label)
    for entry in SAMPLES:
        store = fresh_store()
        run = run_to_completion(to_submission(entry), store, make_llm())
        check("%s -> %s" % (entry["key"], entry["expected"]), run.status == entry["expected"],
              "(got %s: %s)" % (run.status, run.summary))

print("Scenario details (rule path)")
store = fresh_store()
run = run_to_completion(to_submission(find_sample("happy_path")), store, LLM.disabled())
check("happy path has no notes, fixes or blocks",
      all(f["severity"] == "ok" for f in all_findings(run)))
check("happy path email is an approval", "approved" in run.vendor_email.lower())

again = run_to_completion(to_submission(find_sample("happy_path")), store, LLM.disabled())
check("submitting the same vendor twice is rejected as a duplicate",
      again.status == REJECTED and "duplicate_vendor" in codes(again))

run = run_to_completion(to_submission(find_sample("name_variant")), fresh_store(), LLM.disabled())
check("name variant is approved with a note", "holder_variant" in codes(run))

run = run_to_completion(to_submission(find_sample("personal_account")), fresh_store(), LLM.disabled())
check("personal account: blocked as confidential", "holder_individual" in codes(run))
check("personal account: vendor email does not reveal the reason",
      "Whitaker" not in run.vendor_email.split("\n\n", 1)[1].replace("Hi Daniel", "")
      and "fraud" not in run.vendor_email.lower() and "individual" not in run.vendor_email.lower())
check("personal account: internal note explains it", "fraud" in run.internal_note.lower())

run = run_to_completion(to_submission(find_sample("wrong_country_tax_id")), fresh_store(), LLM.disabled())
check("wrong-country tax ID: exactly one fix", sum(1 for f in all_findings(run) if f["severity"] == "fix"
                                                   and f["code"] != "decision") == 1)
check("wrong-country tax ID: email names the UK VAT number",
      "UK VAT number" in run.vendor_email and "GSTIN" in run.vendor_email)

run = run_to_completion(to_submission(find_sample("wrong_document")), fresh_store(), LLM.disabled())
check("wrong document: flagged as an invoice", "tax_doc_wrong_type" in codes(run)
      and "invoice" in run.vendor_email)

run = run_to_completion(to_submission(find_sample("shared_bank_account")), fresh_store(), LLM.disabled())
check("shared bank account: blocked", "shared_bank_account" in codes(run))
check("shared bank account: vendor email does not name the other vendor",
      "Northwind" not in run.vendor_email)
check("shared bank account: internal note names the other vendor", "Northwind" in run.internal_note)

run = run_to_completion(to_submission(find_sample("incomplete")), fresh_store(), LLM.disabled())
fix_codes = [f["code"] for f in all_findings(run) if f["severity"] == "fix" and f["code"] != "decision"]
check("incomplete: three gaps reported together", sorted(fix_codes) == sorted(
    ["missing_bank_code", "missing_bank_doc", "email_format"]), "(got %s)" % fix_codes)
check("incomplete: sole proprietor's personal account is accepted with a note",
      "holder_proprietor" in codes(run))

print("Resubmission")
store = fresh_store()
entry = find_sample("wrong_document")
first = run_to_completion(to_submission(entry), store, LLM.disabled())
fixed = to_submission(entry)
# The vendor resends, this time with the right certificate.
from onboarding.samples import load_doc  # noqa: E402
fixed.tax_doc = load_doc("wrong_document_tax_corrected.pdf")
fixed.tax_doc_name = "wrong_document_tax_corrected.pdf"
second = run_to_completion(fixed, store, LLM.disabled())
check("pending vendor resubmits the right document and is approved",
      first.status == PENDING and second.status == APPROVED and second.resubmission_of == first.run_id,
      "(got %s then %s)" % (first.status, second.status))

print("AI failure handling")
store = fresh_store()
broken = MockLLM(broken=True)
run = run_to_completion(to_submission(find_sample("name_variant")), store, broken)
check("AI outage: run still completes with the right decision", run.status == APPROVED)
methods = [s["method"] for s in run.stages]
check("AI outage: trace records the fallback", "rules (AI unavailable)" in methods, "(methods: %s)" % methods)

class AlwaysYesLLM(MockLLM):
    """A model that wrongly insists every pair of names is the same company."""

    def chat_text(self, system, user):
        if "Bank account holder" in user:
            self.calls += 1
            return '{"same_entity": true, "holder_type": "organisation", "reason": "Looks fine to me."}'
        return MockLLM.chat_text(self, system, user)


store = fresh_store()
run = run_to_completion(to_submission(find_sample("personal_account")), store, AlwaysYesLLM())
check("AI wrongly saying 'same company, an organisation' cannot soften a clear mismatch",
      run.status == REJECTED, "(got %s)" % run.status)

print("Unreadable document")
store = fresh_store()
sub = to_submission(find_sample("happy_path"))
sub.tax_doc = b"not a pdf at all"
run = run_to_completion(sub, store, LLM.disabled())
check("garbage file -> pending, asks for a readable PDF",
      run.status == PENDING and "tax_doc_unreadable" in codes(run))

print("Empty submission")
run = run_to_completion(Submission(), fresh_store(), LLM.disabled())
check("empty form -> pending with every field listed", run.status == PENDING
      and sum(1 for c in codes(run) if c.startswith("missing_")) == 12)

print()
if failures:
    print("%d check(s) FAILED: %s" % (len(failures), failures))
    sys.exit(1)
print("All checks passed.")
