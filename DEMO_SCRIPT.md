# Demo script: 5-minute video and live interview

## Before you record

1. Open the app link a few minutes early so it is awake.
2. Press **Reset demo data** in the sidebar.
3. If AI is on, press **Test AI connection** and confirm it replies.
4. Leave **Pace the live view** on, so each stage is visible as it runs.
5. Close other tabs. Record the browser window only.

## Run order and what to say (about 5 minutes)

**0:00 to 0:35. The problem.**
"Before a company can pay a vendor, someone has to check the vendor is real: the
details, the tax registration, the bank account. Today that is manual, it takes
several rounds of email, and the audit trail is someone's inbox. A mistake here
is how payment fraud happens. This process takes a vendor submission and returns
approved, pending or rejected, and shows its reasoning at every step."

**0:35 to 1:30. Happy path.** Choose *Happy path*. Click **Run onboarding checks**.
"Eight stages run in order. Completeness, then format checks: this GSTIN is
checked against its real checksum, not just its length. Then cross-checks
between fields, then the two documents are read and compared with the form,
then a duplicate check against vendors we already have. Everything passes, so
it is approved and a confirmation is drafted. Nothing is sent: a person
reviews every message."

**1:30 to 2:20. Edge 1: the same check, two outcomes.** Choose *Edge 1a*, run.
"The bank account is in the name ACME TECH PRIVATE LIMITED; the company is Acme
Technologies Pvt Ltd. A strict match would bounce this back and annoy a
legitimate vendor. The process recognises it as the same company and approves
with a note." Then choose *Edge 1b*, run. "Same check, different answer. This
LLC wants to be paid into a personal account. Every field is valid on its own;
only the cross-check catches it. It is rejected. Look at the two outputs: the
vendor gets a neutral notice, and the reason goes to an internal note. We do
not tell a possible fraudster what tripped the alarm."

**2:20 to 3:05. Edge 2: wrong-country tax ID.** Choose *Edge 2*, run.
"The vendor says it is a UK company but gave an Indian GSTIN, and a valid one.
A simple validator would say 'invalid tax ID'. This one says what the number
actually is and asks for exactly what is needed: a UK VAT number in this
format. One clear request instead of a back-and-forth."

**3:05 to 3:45. Edge 3: wrong document.** Choose *Edge 3*, run.
"The form is perfect. But the file uploaded as the tax certificate is one of
their own invoices. The document is read, recognised as an invoice, and the
vendor is asked for the right one."

**3:45 to 4:25. Edge 4: shared bank account.** Choose *Edge 4*, run.
"This is the one that matters most. A new vendor that passes every individual
check, including a matching bank letter. But its bank account already belongs
to Northwind Logistics, a vendor we approved earlier. No check on this
submission alone could find that. It is rejected and routed to fraud review,
with a call-back on an independently sourced phone number."

**4:25 to 5:00. Dashboard and close.** Open **Dashboard**.
"Every run is recorded with its status and outcome. Opening one shows what was
submitted, what each stage found, and what was drafted: the audit trail that
used to live in an inbox. AI is used for judgement and wording; rules own the
decision, and if the AI is unavailable the process still runs. Thanks."

## If something goes wrong live

- **Happy path comes back rejected as a duplicate:** you ran it earlier. Say
  "that is the duplicate-vendor check doing its job", press **Reset demo data**,
  run again.
- **A stage shows "rules · AI unavailable":** the AI call failed and the
  fallback took over. Point at it: this is the designed behaviour.
- **The app is asleep or restarted:** it reloads with the five seeded vendors;
  nothing needs setting up again.

## Questions to expect in the interview

**Why these edge cases?** Each one breaks a different stage, and each needs a
different response: approve with a note (1a), reject quietly (1b), ask for one
specific thing (2), ask for a different document (3), escalate internally (4).
Trivial cases like "field missing" only exercise one path.

**Where is the AI, and why not everywhere?** Three places: judging whether two
names are the same company, reading documents, and wording the message. Format
checks, duplicate checks and the decision are rules, because they need the same
answer every time and must be explainable to an auditor.

**What stops the AI getting it wrong?** It can raise a concern but not lower
one. It cannot approve a clear name mismatch or clear a personal-account flag.
The checklist sent to the vendor is built by rules, so the AI cannot drop or
invent a requirement, and it never sees confidential findings when wording the
message.

**Why reject the personal account instead of asking for a fix?** A fix request
tells a fraudster exactly what to change. Rejecting and routing to a human
costs a legitimate vendor a phone call; getting it wrong the other way costs a
payment. Sole proprietors are treated differently: a personal account is normal
for them and is accepted with a note.

**Why run every check instead of stopping at the first failure?** The slow part
of onboarding is waiting for the vendor. One complete list means one round trip.

**What would you build next?** OCR for scanned documents; registry look-ups
(GSTN, Companies House, IRS TIN matching) so IDs are verified and not only
format-checked; a penny-drop or bank API check on account ownership; sanctions
screening; a reviewer queue with approve and send buttons; a hosted database.

**What are the limits today?** Four countries, text PDFs only, format checks
without registry verification, drafts not sent, history that resets when the
free host restarts. All listed in the README and on the How it works tab.
