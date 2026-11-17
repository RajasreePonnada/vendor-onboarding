"""Drafts the message back to the vendor and, where needed, an internal note.

Guardrail: the checklist of required items is assembled by rules from the
findings. The AI only writes the opening paragraph, so it cannot drop a
requirement, invent one, or leak a confidential fraud signal.

Nothing is sent. Every message is a draft for a human to review.
"""

from .models import APPROVED, PENDING, REJECTED, FIX, BLOCK, NOTE

INTRO_SYSTEM = "You write short, courteous, plain-English emails for a procurement team."

INTRO_PROMPT = """Write the opening paragraph of an email to a vendor contact.

Context: their company, {company}, applied to be registered as a vendor. The
registration is on hold until they send {count} item(s). The items are listed
separately below your paragraph, so do not name or describe any of them.

Rules: at most 2 sentences. No greeting, no sign-off, no bullet points, no
placeholders. Friendly and direct."""

FALLBACK_INTRO = (
    "Thank you for submitting your vendor registration for {company}. We've reviewed it "
    "and need {count_phrase} from you before we can complete the approval."
)


def first_name(contact_name):
    parts = (contact_name or "").strip().split()
    if not parts:
        return "there"
    return parts[0]


def unique_actions(findings, severity):
    actions = []
    for f in findings:
        if f.severity != severity or f.confidential or not f.vendor_action:
            continue
        if f.vendor_action not in actions:
            actions.append(f.vendor_action)
    return actions


def numbered(items):
    lines = []
    for i, item in enumerate(items, start=1):
        lines.append("%d. %s" % (i, item))
    return "\n".join(lines)


def write_intro(company, count, llm):
    """Returns (intro, method)."""
    count_phrase = "one more thing" if count == 1 else "%d more things" % count
    fallback = FALLBACK_INTRO.format(company=company, count_phrase=count_phrase)
    if llm is None or not llm.enabled:
        return fallback, "rules"
    reply = llm.chat_text(
        INTRO_SYSTEM, INTRO_PROMPT.format(company=company, count=count))
    if reply is None:
        return fallback, "rules (AI unavailable)"
    cleaned = " ".join(reply.split())
    # Reject anything that does not look like a short plain paragraph.
    if len(cleaned) < 20 or len(cleaned) > 450 or "[" in cleaned or "{" in cleaned:
        return fallback, "rules (AI unavailable)"
    return cleaned, "AI"


def build_vendor_email(sub, status, findings, llm, run_id):
    """Returns (email_text, method)."""
    name = first_name(sub.contact_name)
    company = sub.legal_name or "your company"

    if status == APPROVED:
        text = (
            "Subject: Vendor registration approved: %s (%s)\n\n"
            "Hi %s,\n\n"
            "Good news: %s is now approved as a vendor. Your company details, tax "
            "registration and bank account have all been verified.\n\n"
            "You can start submitting invoices using the bank details on file. If any "
            "of those details change, let us know before your next invoice so we can "
            "re-verify them.\n\n"
            "Thanks,\nVendor Onboarding Team"
        ) % (company, run_id, name, company)
        return text, "rules"

    if status == PENDING:
        actions = unique_actions(findings, FIX)
        intro, method = write_intro(company, len(actions), llm)
        text = (
            "Subject: Action needed to complete your vendor registration: %s (%s)\n\n"
            "Hi %s,\n\n"
            "%s\n\n"
            "What we need from you:\n%s\n\n"
            "Reply to this email with the updated details and documents and we'll "
            "re-run the review straight away. Everything else in your submission "
            "checked out, so you only need to send the items above.\n\n"
            "Thanks,\nVendor Onboarding Team"
        ) % (company, run_id, name, intro, numbered(actions))
        return text, method

    # Rejected. Only non-confidential reasons are shared.
    actions = unique_actions(findings, BLOCK)
    if actions:
        body = "The reason:\n%s" % numbered(actions)
    else:
        body = (
            "A member of our procurement team will contact you directly to discuss "
            "next steps. Please do not resubmit until you have heard from them."
        )
    text = (
        "Subject: Update on your vendor registration: %s (%s)\n\n"
        "Hi %s,\n\n"
        "Thank you for submitting your vendor registration for %s. We're unable to "
        "approve it at this time.\n\n"
        "%s\n\n"
        "Thanks,\nVendor Onboarding Team"
    ) % (company, run_id, name, company, body)
    return text, "rules"


def build_internal_note(sub, status, findings, run_id):
    """Internal escalation note; '' when there is nothing to escalate."""
    blocks = [f for f in findings if f.severity == BLOCK]
    confidential = [f for f in findings if f.confidential and f.severity != BLOCK]
    if status != REJECTED and not confidential:
        return ""

    lines = [
        "INTERNAL: do not forward to the vendor",
        "Run %s | %s | decision: %s" % (run_id, sub.legal_name or "(no name)", status.upper()),
        "",
        "Why:",
    ]
    for f in blocks + confidential:
        lines.append("- %s" % f.message)

    notes = [f for f in findings if f.severity == NOTE and not f.confidential]
    if notes:
        lines.append("")
        lines.append("Also noted:")
        for f in notes:
            lines.append("- %s" % f.message)

    has_fraud_signal = False
    for f in blocks + confidential:
        if f.confidential:
            has_fraud_signal = True
    lines.append("")
    if has_fraud_signal:
        lines.append(
            "Next step: route to fraud review. Verify by calling the vendor on a phone "
            "number obtained independently (not the one on this submission). The vendor "
            "has been told only that procurement will be in touch.")
    else:
        lines.append("Next step: no action needed unless the vendor disputes the decision.")
    return "\n".join(lines)
