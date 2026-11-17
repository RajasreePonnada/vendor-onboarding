"""The onboarding pipeline: eight stages, run in order, every result recorded.

run_pipeline() is a generator so a UI can show each stage as it executes:
    ("start", stage_key)        just before a stage runs
    ("done", StageResult)       when it finishes
    ("result", RunResult)       once, at the end

Design choices worth knowing:
- Stages do not stop at the first problem. The vendor gets one complete list of
  what to fix, not five rounds of back-and-forth.
- Decision rule is fixed and simple: any blocking finding -> rejected;
  otherwise any fixable finding -> pending; otherwise approved.
- AI is used for judgement (is this the same company? what is this document?)
  and wording. Rules own the decision. AI can never turn a clear name mismatch
  into an approval.
"""

import time
from datetime import datetime, timezone

from . import comms
from .documents import DOC_TYPE_LABELS, read_document
from .models import (
    APPROVED, PENDING, REJECTED, OK, NOTE, FIX, BLOCK, SEVERITY_RANK, COUNTRIES,
    Finding, StageResult, RunResult,
)
from .names import (
    MATCH, VARIANT, AMBIGUOUS, MISMATCH, compare_names, looks_like_person,
    name_appears_in,
)
from .validators import (
    TAX_ID_NAMES, TAX_ID_HINTS, BANK_CODE_NAMES, compact, validate_tax_id,
    validate_bank, validate_email,
)

STAGES = [
    ("intake", "Intake"),
    ("completeness", "Completeness check"),
    ("format", "Format validation"),
    ("consistency", "Cross-field consistency"),
    ("documents", "Document verification"),
    ("risk", "Duplicate and risk checks"),
    ("decision", "Decision"),
    ("comms", "Vendor communication"),
]

NAME_SYSTEM = (
    "You help a procurement team verify vendor bank accounts. "
    "Reply with one JSON object and nothing else."
)

NAME_PROMPT = """A vendor registered under one name and gave a bank account held under another.

Vendor legal name: "%s"
Bank account holder: "%s"

Return JSON with exactly these keys:
- "same_entity": true if the two names plainly refer to the same legal entity
  (abbreviations, legal-suffix variations, spelling or word-order differences),
  otherwise false. If unsure, false.
- "holder_type": "individual" if the account holder is a person's name,
  "organisation" otherwise.
- "reason": one short sentence."""


class Context:
    def __init__(self, sub, store, llm):
        self.sub = sub
        self.store = store
        self.llm = llm
        self.findings = []
        self.previous = None
        self.status = ""
        self.summary = ""
        self.vendor_email = ""
        self.internal_note = ""
        self.run_id = ""


COUNTRY_PHRASES = {"GB": "the United Kingdom", "US": "the United States"}


def country_name(code):
    """Country name as it reads mid-sentence ('the United Kingdom', 'India')."""
    if code in COUNTRY_PHRASES:
        return COUNTRY_PHRASES[code]
    return COUNTRIES.get(code, code or "an unspecified country")


def plural(count, word):
    if count == 1:
        return "1 %s" % word
    return "%d %ss" % (count, word)


def with_article(label):
    if label[:1].lower() in "aeiou":
        return "an " + label
    return "a " + label


def worst(findings):
    level = OK
    for f in findings:
        if SEVERITY_RANK[f.severity] > SEVERITY_RANK[level]:
            level = f.severity
    return level


# --------------------------------------------------------------------------
# Stage 1: intake
# --------------------------------------------------------------------------

def stage_intake(ctx):
    sub = ctx.sub
    findings = []
    doc_count = 0
    if sub.tax_doc:
        doc_count += 1
    if sub.bank_doc:
        doc_count += 1
    findings.append(Finding(OK, "received", "Received submission for '%s' (%s) with %s." % (
        sub.legal_name or "(no name given)", COUNTRIES.get(sub.country, sub.country or "no country"),
        plural(doc_count, "document"))))

    previous = ctx.store.latest_with_tax_id(sub.tax_id)
    if previous is not None and previous["status"] in (PENDING, REJECTED):
        ctx.previous = previous
        findings.append(Finding(NOTE, "resubmission",
            "Resubmission: the previous attempt for this tax ID (%s) was %s." % (
                previous["run_id"], previous["status"])))
    return findings, "rules"


# --------------------------------------------------------------------------
# Stage 2: completeness
# --------------------------------------------------------------------------

def stage_completeness(ctx):
    sub = ctx.sub
    findings = []
    code_label = BANK_CODE_NAMES.get(sub.bank_country, "bank code (IFSC, routing number or BIC)")
    account_label = "IBAN" if sub.bank_country in ("GB", "DE") else "bank account number"
    required = [
        ("legal_name", "your company's registered legal name"),
        ("country", "your country of registration"),
        ("tax_id", "your tax registration number"),
        ("address", "your registered address"),
        ("contact_name", "a contact person's name"),
        ("contact_email", "a contact email address"),
        ("bank_account_holder", "the name the bank account is held in"),
        ("bank_country", "the country of your bank account"),
        ("bank_account", "your " + account_label),
        ("bank_code", "your bank's " + code_label),
    ]
    for attr, label in required:
        if not (getattr(sub, attr) or "").strip():
            findings.append(Finding(FIX, "missing_" + attr,
                "Required field is empty: %s." % attr.replace("_", " "),
                vendor_action="Provide %s." % label))
    if not sub.tax_doc:
        findings.append(Finding(FIX, "missing_tax_doc",
            "No tax registration certificate uploaded.",
            vendor_action="Upload your tax registration certificate (PDF)."))
    if not sub.bank_doc:
        findings.append(Finding(FIX, "missing_bank_doc",
            "No bank account proof uploaded.",
            vendor_action="Upload proof of your bank account: a bank letter or a cancelled cheque (PDF)."))
    if not findings:
        findings.append(Finding(OK, "complete", "All 10 required fields and both documents are present."))
    return findings, "rules"


# --------------------------------------------------------------------------
# Stage 3: format validation
# --------------------------------------------------------------------------

def stage_format(ctx):
    sub = ctx.sub
    findings = []

    if sub.tax_id.strip() and sub.country:
        ok, problem, looks_like = validate_tax_id(sub.tax_id, sub.country)
        if ok:
            findings.append(Finding(OK, "tax_id_format",
                "Tax ID is a well-formed %s." % TAX_ID_NAMES[sub.country]))
        elif looks_like:
            findings.append(Finding(FIX, "tax_id_wrong_country",
                "Tax ID '%s' is in the format of %s (%s), but the vendor says it is registered in %s." % (
                    sub.tax_id, with_article(TAX_ID_NAMES[looks_like]), country_name(looks_like),
                    country_name(sub.country)),
                vendor_action=(
                    "The tax number you gave (%s) is %s, which is issued in %s. Because your "
                    "company is registered in %s, please send your %s (%s) and the matching "
                    "registration certificate. If the company is actually registered in %s, "
                    "correct the country instead." % (
                        sub.tax_id, with_article(TAX_ID_NAMES[looks_like]), country_name(looks_like),
                        country_name(sub.country), TAX_ID_NAMES[sub.country],
                        TAX_ID_HINTS[sub.country], country_name(looks_like)))))
        else:
            findings.append(Finding(FIX, "tax_id_format",
                "Tax ID '%s' is not valid for %s. %s" % (sub.tax_id, country_name(sub.country), problem),
                vendor_action="Re-check your %s (%s). The number '%s' is not valid: %s" % (
                    TAX_ID_NAMES.get(sub.country, "tax ID"), TAX_ID_HINTS.get(sub.country, ""),
                    sub.tax_id, problem)))

    if sub.bank_country and (sub.bank_account.strip() or sub.bank_code.strip()):
        problems = validate_bank(sub.bank_country, sub.bank_account, sub.bank_code)
        if problems:
            for problem in problems:
                findings.append(Finding(FIX, "bank_format",
                    "Bank details are malformed. %s" % problem,
                    vendor_action="Re-check your bank details. %s" % problem))
        else:
            findings.append(Finding(OK, "bank_format",
                "Bank details are well-formed for %s (checksums pass where one exists)." % (
                    country_name(sub.bank_country))))

    if sub.contact_email.strip():
        ok, free_mail = validate_email(sub.contact_email)
        if not ok:
            findings.append(Finding(FIX, "email_format",
                "Contact email '%s' is not a valid address." % sub.contact_email,
                vendor_action="Provide a valid contact email address ('%s' is not complete)." % (
                    sub.contact_email)))
        elif free_mail and sub.entity_type == "company":
            findings.append(Finding(NOTE, "email_free_mail",
                "Contact email uses a free webmail domain rather than a company domain."))
        else:
            findings.append(Finding(OK, "email_format", "Contact email is well-formed."))

    if not findings:
        findings.append(Finding(OK, "nothing_to_check", "No fields available to format-check."))
    return findings, "rules"


# --------------------------------------------------------------------------
# Stage 4: cross-field consistency
# --------------------------------------------------------------------------

def judge_holder_name(sub, llm):
    """Compare legal name with bank account holder. Returns (finding, method)."""
    legal = sub.legal_name.strip()
    holder = sub.bank_account_holder.strip()
    verdict, score = compare_names(legal, holder)

    if verdict == MATCH:
        return Finding(OK, "holder_match",
            "Bank account holder matches the legal name."), "rules"

    # Anything short of an exact match gets a second opinion when AI is available.
    method = "rules"
    ai = None
    if llm is not None and llm.enabled:
        ai = llm.chat_json(NAME_SYSTEM, NAME_PROMPT % (legal, holder))
        method = "AI" if ai is not None else "rules (AI unavailable)"

    ai_same = None
    ai_reason = ""
    holder_is_person = looks_like_person(holder)
    if ai is not None:
        if isinstance(ai.get("same_entity"), bool):
            ai_same = ai["same_entity"]
        ai_reason = str(ai.get("reason") or "").strip()
        # One-way only: AI may flag a holder as an individual, but it cannot
        # clear a holder the rules already flagged. AI can raise a concern,
        # never lower one.
        if ai.get("holder_type") == "individual":
            holder_is_person = True

    reason_suffix = ""
    if ai_reason:
        reason_suffix = " AI assessment: %s" % ai_reason

    # Same entity, written differently. Rules must agree it is at least
    # plausible (VARIANT or AMBIGUOUS); AI alone cannot rescue a clear mismatch.
    same = False
    if verdict == VARIANT and ai_same is not False:
        same = True
    if verdict == AMBIGUOUS and ai_same is True:
        same = True
    if same:
        return Finding(NOTE, "holder_variant",
            "Bank account holder '%s' is written differently from the legal name '%s' but is "
            "treated as the same entity (similarity %d%%).%s" % (
                holder, legal, round(score * 100), reason_suffix)), method

    if verdict == AMBIGUOUS and ai_same is None:
        return Finding(FIX, "holder_unclear",
            "Bank account holder '%s' is similar to, but not clearly the same as, the legal "
            "name '%s' (similarity %d%%)." % (holder, legal, round(score * 100)),
            vendor_action=(
                "The bank account is held in the name '%s', which differs from your legal name "
                "'%s'. Please send a bank letter confirming that the account belongs to %s." % (
                    holder, legal, legal))), method

    # From here on the names are treated as different.
    if holder_is_person and sub.entity_type == "sole_proprietor":
        return Finding(NOTE, "holder_proprietor",
            "Bank account is in an individual's name ('%s'). Accepted because the vendor is "
            "registered as a sole proprietor.%s" % (holder, reason_suffix)), method

    if holder_is_person:
        return Finding(BLOCK, "holder_individual",
            "Bank account is held by an individual ('%s'), not by the company '%s'. Paying a "
            "company's invoices into a personal account is a known payment-fraud pattern.%s" % (
                holder, legal, reason_suffix),
            confidential=True), method

    return Finding(FIX, "holder_other_org",
        "Bank account is held by a different organisation ('%s') from the vendor ('%s').%s" % (
            holder, legal, reason_suffix),
        vendor_action=(
            "The bank account is held in the name '%s', which does not match your legal name "
            "'%s'. Please provide an account held in the company's own legal name, or a bank "
            "letter confirming that %s owns this account." % (holder, legal, legal))), method


def stage_consistency(ctx):
    sub = ctx.sub
    findings = []
    method = "rules"

    if sub.legal_name.strip() and sub.bank_account_holder.strip():
        finding, method = judge_holder_name(sub, ctx.llm)
        findings.append(finding)

    if sub.country and sub.bank_country:
        if sub.country != sub.bank_country:
            findings.append(Finding(NOTE, "bank_country_differs",
                "Bank account is in %s but the vendor is registered in %s." % (
                    country_name(sub.bank_country), country_name(sub.country))))
        else:
            findings.append(Finding(OK, "bank_country_same",
                "Bank account country matches the country of registration."))

    if not findings:
        findings.append(Finding(OK, "nothing_to_check", "Not enough fields to cross-check."))
    return findings, method


# --------------------------------------------------------------------------
# Stage 5: document verification
# --------------------------------------------------------------------------

def check_tax_document(sub, read):
    findings = []
    file_name = sub.tax_doc_name or "the uploaded file"
    if read["doc_type"] == "unreadable":
        findings.append(Finding(FIX, "tax_doc_unreadable",
            "Tax certificate file '%s' contains no readable text (probably a scan or photo)." % file_name,
            vendor_action="Upload a text-based PDF of your tax registration certificate. The file "
                          "'%s' could not be read (it may be a scan or photo)." % file_name))
        return findings
    if read["doc_type"] != "tax_certificate":
        label = DOC_TYPE_LABELS.get(read["doc_type"], "different document")
        findings.append(Finding(FIX, "tax_doc_wrong_type",
            "The file uploaded as the tax certificate ('%s') is %s." % (file_name, with_article(label)),
            vendor_action="The file you uploaded as your tax registration certificate ('%s') appears "
                          "to be %s. Please upload the registration certificate issued by your tax "
                          "authority." % (file_name, with_article(label))))
        return findings

    findings.append(Finding(OK, "tax_doc_type", "Tax document is a tax registration certificate."))

    form_id = compact(sub.tax_id)
    if form_id:
        if form_id in compact(read["text"]):
            findings.append(Finding(OK, "tax_doc_id", "Tax ID on the certificate matches the form."))
        else:
            shown = read["tax_id"] or "a different number"
            findings.append(Finding(FIX, "tax_doc_id_mismatch",
                "Tax ID on the certificate (%s) does not match the form (%s)." % (shown, sub.tax_id),
                vendor_action="The tax ID on your certificate (%s) does not match the one you "
                              "entered (%s). Correct the number or upload the right certificate." % (
                                  shown, sub.tax_id)))

    if sub.legal_name.strip():
        name_ok = name_appears_in(sub.legal_name, read["text"])
        if not name_ok and read["entity_name"]:
            verdict, _ = compare_names(sub.legal_name, read["entity_name"])
            name_ok = verdict in (MATCH, VARIANT)
        if name_ok:
            findings.append(Finding(OK, "tax_doc_name", "Certificate is issued to the vendor's legal name."))
        else:
            shown = read["entity_name"] or "a different name"
            findings.append(Finding(FIX, "tax_doc_name_mismatch",
                "Certificate is issued to '%s', not to '%s'." % (shown, sub.legal_name),
                vendor_action="Your tax certificate is issued to '%s', but you registered as '%s'. "
                              "Upload the certificate for the registering company, or correct the "
                              "legal name." % (shown, sub.legal_name)))
    return findings


def check_bank_document(sub, read):
    findings = []
    file_name = sub.bank_doc_name or "the uploaded file"
    if read["doc_type"] == "unreadable":
        findings.append(Finding(FIX, "bank_doc_unreadable",
            "Bank proof file '%s' contains no readable text (probably a scan or photo)." % file_name,
            vendor_action="Upload a text-based PDF of your bank letter or cancelled cheque. The file "
                          "'%s' could not be read (it may be a scan or photo)." % file_name))
        return findings
    if read["doc_type"] != "bank_proof":
        label = DOC_TYPE_LABELS.get(read["doc_type"], "different document")
        findings.append(Finding(FIX, "bank_doc_wrong_type",
            "The file uploaded as bank proof ('%s') is %s." % (file_name, with_article(label)),
            vendor_action="The file you uploaded as proof of your bank account ('%s') appears to be "
                          "%s. Please upload a bank letter or cancelled cheque showing the account "
                          "holder and account number." % (file_name, with_article(label))))
        return findings

    findings.append(Finding(OK, "bank_doc_type", "Bank document is a bank account proof."))

    form_account = compact(sub.bank_account)
    if form_account:
        if form_account in compact(read["text"]):
            findings.append(Finding(OK, "bank_doc_account", "Account number on the bank proof matches the form."))
        else:
            shown = read["account_number"] or "a different account"
            findings.append(Finding(FIX, "bank_doc_account_mismatch",
                "Account number on the bank proof (%s) does not match the form (%s)." % (
                    shown, sub.bank_account),
                vendor_action="The account number on your bank proof (%s) does not match the one "
                              "you entered (%s). Correct the number or upload the right document." % (
                                  shown, sub.bank_account)))

    if sub.bank_account_holder.strip():
        holder_ok = name_appears_in(sub.bank_account_holder, read["text"])
        if not holder_ok and read["account_holder"]:
            verdict, _ = compare_names(sub.bank_account_holder, read["account_holder"])
            holder_ok = verdict in (MATCH, VARIANT)
        if holder_ok:
            findings.append(Finding(OK, "bank_doc_holder", "Account holder on the bank proof matches the form."))
        else:
            shown = read["account_holder"] or "a different name"
            findings.append(Finding(FIX, "bank_doc_holder_mismatch",
                "Bank proof shows the account holder as '%s', but the form says '%s'." % (
                    shown, sub.bank_account_holder),
                vendor_action="Your bank proof shows the account holder as '%s', but you entered "
                              "'%s'. Correct the name or upload the right document." % (
                                  shown, sub.bank_account_holder)))
    return findings


def stage_documents(ctx):
    sub = ctx.sub
    findings = []
    methods = []

    if sub.tax_doc:
        read = read_document(sub.tax_doc, ctx.llm)
        methods.append(read["method"])
        findings.extend(check_tax_document(sub, read))
    if sub.bank_doc:
        read = read_document(sub.bank_doc, ctx.llm)
        methods.append(read["method"])
        findings.extend(check_bank_document(sub, read))

    if not findings:
        findings.append(Finding(OK, "no_documents",
            "No documents to verify (already reported as missing)."))
        return findings, "rules"

    method = "rules"
    if "AI" in methods:
        method = "AI"
    elif "rules (AI unavailable)" in methods:
        method = "rules (AI unavailable)"
    return findings, method


# --------------------------------------------------------------------------
# Stage 6: duplicates and risk
# --------------------------------------------------------------------------

def stage_risk(ctx):
    sub = ctx.sub
    findings = []
    tax_key = compact(sub.tax_id)

    existing = ctx.store.approved_with_tax_id(sub.tax_id)
    if existing is not None:
        findings.append(Finding(BLOCK, "duplicate_vendor",
            "A vendor with this tax ID is already approved (%s, '%s')." % (
                existing["run_id"], existing["vendor_name"]),
            vendor_action="Your company is already registered as a vendor with us (reference %s). "
                          "To change any details on file, please contact your procurement contact "
                          "rather than registering again." % existing["run_id"]))
        if compact(sub.bank_account) and existing["bank_key"] != compact(sub.bank_account):
            findings.append(Finding(BLOCK, "bank_change_attempt",
                "The bank account on this submission differs from the one on file for %s. Bank "
                "changes for an approved vendor must go through call-back verification, not "
                "re-registration." % existing["run_id"],
                confidential=True))

    sharing = []
    for row in ctx.store.approved_with_bank(sub.bank_account):
        if row["tax_key"] != tax_key:
            sharing.append(row)
    if sharing:
        other = sharing[0]
        findings.append(Finding(BLOCK, "shared_bank_account",
            "This bank account already belongs to a different approved vendor: '%s' (%s). Two "
            "unrelated vendors paying into one account is a strong fraud signal." % (
                other["vendor_name"], other["run_id"]),
            confidential=True))

    if not findings:
        findings.append(Finding(OK, "no_duplicates",
            "No existing vendor shares this tax ID or bank account."))
    return findings, "rules"


# --------------------------------------------------------------------------
# Stage 7: decision
# --------------------------------------------------------------------------

def count_severity(findings, severity):
    total = 0
    for f in findings:
        if f.severity == severity:
            total += 1
    return total


def stage_decision(ctx):
    blocks = count_severity(ctx.findings, BLOCK)
    fixes = count_severity(ctx.findings, FIX)
    notes = count_severity(ctx.findings, NOTE)

    if blocks:
        ctx.status = REJECTED
        first = ""
        for f in ctx.findings:
            if f.severity == BLOCK:
                first = f.message
                break
        ctx.summary = first.split(". ")[0].rstrip(".") + "."
        finding = Finding(BLOCK, "decision",
            "REJECTED: %s. Rule: any blocking finding rejects the "
            "submission, whatever else passed." % plural(blocks, "blocking finding"))
    elif fixes:
        ctx.status = PENDING
        ctx.summary = "%s needed from the vendor before approval." % plural(fixes, "item")
        finding = Finding(FIX, "decision",
            "PENDING: no blocking findings, but %s for the vendor to fix. Rule: "
            "anything fixable holds the submission until the vendor responds." % plural(fixes, "item"))
    else:
        ctx.status = APPROVED
        if notes:
            ctx.summary = "All checks passed, with %s for the reviewer." % plural(notes, "note")
        else:
            ctx.summary = "All checks passed."
        finding = Finding(OK, "decision",
            "APPROVED: every check passed (%s recorded). Rule: approve only when "
            "there is nothing blocking and nothing for the vendor to fix." % plural(notes, "note"))
    return [finding], "rules"


# --------------------------------------------------------------------------
# Stage 8: communication
# --------------------------------------------------------------------------

def stage_comms(ctx):
    email, method = comms.build_vendor_email(ctx.sub, ctx.status, ctx.findings, ctx.llm, ctx.run_id)
    ctx.vendor_email = email
    ctx.internal_note = comms.build_internal_note(ctx.sub, ctx.status, ctx.findings, ctx.run_id)

    findings = []
    if ctx.status == APPROVED:
        findings.append(Finding(OK, "email_drafted", "Approval confirmation drafted for the vendor."))
    elif ctx.status == PENDING:
        findings.append(Finding(OK, "email_drafted",
            "Follow-up drafted listing exactly what the vendor needs to send."))
    else:
        findings.append(Finding(OK, "email_drafted",
            "Rejection notice drafted. Confidential reasons are left out of the vendor message."))
    if ctx.internal_note:
        findings.append(Finding(OK, "internal_note", "Internal note drafted for the procurement team."))
    if ctx.sub.contact_email.strip() and not validate_email(ctx.sub.contact_email)[0]:
        findings.append(Finding(NOTE, "email_undeliverable",
            "The contact email on file is invalid, so this draft cannot be emailed as-is. "
            "Reach the vendor through the channel the submission came in on."))
    elif not ctx.sub.contact_email.strip():
        findings.append(Finding(NOTE, "email_undeliverable",
            "No contact email on file. Reach the vendor through the channel the submission came in on."))
    findings.append(Finding(OK, "not_sent", "Nothing has been sent. Drafts wait for human review."))
    return findings, method


STAGE_FUNCTIONS = {
    "intake": stage_intake,
    "completeness": stage_completeness,
    "format": stage_format,
    "consistency": stage_consistency,
    "documents": stage_documents,
    "risk": stage_risk,
    "decision": stage_decision,
    "comms": stage_comms,
}


def run_pipeline(sub, store, llm, created_at=None, save=True):
    """Generator. See the module docstring for the events it yields."""
    ctx = Context(sub, store, llm)
    ctx.run_id = store.next_run_id()
    started = time.perf_counter()
    stage_dicts = []

    for key, title in STAGES:
        yield ("start", key)
        t0 = time.perf_counter()
        findings, method = STAGE_FUNCTIONS[key](ctx)
        elapsed = int((time.perf_counter() - t0) * 1000)
        if key not in ("decision", "comms"):
            ctx.findings.extend(findings)
        result = StageResult(key=key, title=title, status=worst(findings),
                             findings=findings, method=method, duration_ms=elapsed)
        stage_dicts.append(result.to_dict())
        yield ("done", result)

    if created_at is None:
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    run = RunResult(
        run_id=ctx.run_id,
        created_at=created_at,
        status=ctx.status,
        summary=ctx.summary,
        submission=sub.public_fields(),
        stages=stage_dicts,
        vendor_email=ctx.vendor_email,
        internal_note=ctx.internal_note,
        ai_mode=llm.describe() if llm is not None else "off",
        duration_ms=int((time.perf_counter() - started) * 1000),
        resubmission_of=ctx.previous["run_id"] if ctx.previous else "",
    )
    if save:
        store.save(run)
    yield ("result", run)


def run_to_completion(sub, store, llm, created_at=None, save=True):
    """Convenience wrapper for scripts and tests: returns the RunResult."""
    final = None
    for event, payload in run_pipeline(sub, store, llm, created_at=created_at, save=save):
        if event == "result":
            final = payload
    return final
