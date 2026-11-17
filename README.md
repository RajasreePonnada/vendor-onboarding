# Vendor Onboarding: from submission to approval

ASA case study, PS-2. A vendor submission (a form plus two PDFs) goes in. Eight
checks run in order. Out comes **approved**, **pending** or **rejected**, with
the reasoning visible at every stage and a drafted message back to the vendor.

- **Live run view:** each stage shows queued, running, then its findings.
- **Dashboard:** every run, its status, and a full trace of what happened.
- **How it works:** process map and decision rules, inside the app.

## Deploy it (Streamlit Community Cloud, free)

1. Create an empty **public** repository on GitHub, for example `vendor-onboarding`.
2. Push this folder to it:

   ```bash
   cd vendor-onboarding
   git init -b main
   git add .
   git commit -m "Vendor onboarding pipeline with live run view and dashboard"
   git remote add origin https://github.com/<your-username>/vendor-onboarding.git
   git push -u origin main
   ```

3. Go to <https://share.streamlit.io>, sign in with GitHub, and choose **Create app**.
4. Pick the repository, branch `main`, main file `app.py`.
5. To turn AI on, open **Advanced settings** and paste the three lines from
   `.streamlit/secrets.toml.example` into **Secrets**, with your own key and
   model name. Skip this step to deploy with AI off.
6. Click **Deploy**. You get a public `https://<name>.streamlit.app` link.

Things to know about the free tier:

- **The app goes to sleep when nobody has visited for a while.** Open the link
  a few minutes before a demo so it is awake.
- **Run history is stored in a local SQLite file, which is wiped whenever the
  app restarts.** The five seeded vendors are recreated automatically. For a
  demo this is fine; a real deployment would use a hosted database.

## Turning AI on

The app talks to any OpenAI-compatible chat endpoint. Set three secrets:

| Secret | Example |
|---|---|
| `LLM_API_KEY` | your provider's API key |
| `LLM_BASE_URL` | Gemini: `https://generativelanguage.googleapis.com/v1beta/openai`  ·  OpenAI: `https://api.openai.com/v1` |
| `LLM_MODEL` | a current model name from your provider's documentation |

After deploying, press **Test AI connection** in the sidebar. It makes one small
call and shows either the model's reply or the exact error.

With AI off, or if a call fails mid-run, each AI step falls back to rules and
the run trace says which path was used. The decision never depends on AI being
reachable.

**Tested status:** every scenario passes on the rule path and with a simulated
model, and the HTTP client was exercised against a local stand-in server. It
has **not** been run against a real provider, so run **Test AI connection** and
one scenario with AI on before recording.

## Run it locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Demo scenarios

Pick one from **Start from a scenario**; the form and documents fill in.

| Scenario | What is wrong | Outcome |
|---|---|---|
| Happy path | Nothing | Approved |
| Edge 1a: name written differently | Bank account held as "ACME TECH PRIVATE LIMITED" for "Acme Technologies Pvt Ltd" | Approved, with a note |
| Edge 1b: personal account | An LLC's bank account is held by an individual | Rejected, reason withheld from the vendor |
| Edge 2: wrong-country tax ID | UK company supplies a (valid) Indian GSTIN | Pending, message names the exact number needed |
| Edge 3: wrong document | An invoice uploaded as the tax certificate | Pending, asks for the right document |
| Edge 4: shared bank account | New vendor uses the IBAN of an already-approved vendor | Rejected, routed to fraud review |
| Extra: incomplete | Missing IFSC, missing bank proof, truncated email | Pending, all three listed in one message |

Two behaviours that are not in the list but are worth showing:

- **Resubmission.** Run Edge 3 (pending). Then, without changing the form,
  upload `sample_docs/wrong_document_tax_corrected.pdf` as the tax certificate
  and run again. It is approved, and the new run is linked to the earlier one.
- **Duplicate vendor.** Run the happy path twice. The second run is rejected
  because that vendor is already approved. Press **Reset demo data** before a
  demo so this does not happen by accident.

## How the process works

| # | Stage | What it does | Method |
|---|---|---|---|
| 1 | Intake | Registers the submission; spots resubmissions | rules |
| 2 | Completeness | 10 required fields and 2 documents present? | rules |
| 3 | Format validation | Tax ID valid for the claimed country (GSTIN checksum; detects IDs from another country); bank details (IBAN mod-97, ABA routing checksum, IFSC and BIC format); email | rules |
| 4 | Cross-field consistency | Does the bank account holder match the legal name? Bank country vs registration country | rules, AI second opinion |
| 5 | Document verification | Is each PDF the right kind of document, and do its name and numbers match the form? | AI, rule fallback |
| 6 | Duplicate and risk checks | Tax ID already approved? Bank account already used by a different vendor? | rules |
| 7 | Decision | Any block rejects; otherwise any fix makes it pending; otherwise approved | rules |
| 8 | Vendor communication | Drafts the vendor message and, if needed, an internal note | rules for the checklist, AI for the opening line |

Design decisions:

- **All checks always run.** The vendor gets one complete list, not several
  rounds of emails.
- **Rules own the decision; AI advises.** AI can raise a concern but not lower
  one. It cannot turn a clear name mismatch into an approval or clear a
  personal-account flag.
- **The vendor checklist is built by rules.** AI only writes the opening line,
  so it cannot drop a requirement or leak a confidential reason.
- **Fraud signals stay internal.** The vendor gets a neutral notice; the
  procurement team gets an internal note with the reason and next step.
- **Nothing is sent automatically.** Every message is a draft for a person.

## Assumptions and limits

- Four countries are supported: India, UK, US, Germany.
- Documents must be text PDFs. Scans and photos are not read (no OCR); the
  vendor is asked for a text PDF instead.
- UK, US and German tax IDs are checked for format only. Nothing is verified
  against a government registry or a bank.
- Company policy assumed: payments go only to an account held in the vendor's
  own legal name. A sole proprietor may use a personal account.
- All companies, people, tax IDs and bank accounts in the samples are invented.
  Every sample PDF is marked as generated test data.

## Tests

```bash
pip install -r requirements-dev.txt
python tests/test_pipeline.py   # validators, every scenario, AI-failure handling
python tests/test_app.py        # drives the real UI headlessly through every scenario
python scripts/make_sample_docs.py   # regenerates sample_docs/
```

## Layout

```
app.py                  Streamlit UI: form, live run, dashboard, explainer
onboarding/
  pipeline.py           the eight stages and the decision rule
  validators.py         tax ID, bank and email format checks
  names.py              company-name comparison
  documents.py          PDF reading and document-type detection
  comms.py              vendor message and internal note
  llm.py                OpenAI-compatible client with silent fallback
  store.py              SQLite run history and vendor master
  samples.py, seed.py   demo scenarios and seeded history
sample_docs/            generated test PDFs
tests/                  pipeline and UI tests
```
