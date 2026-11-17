"""Vendor onboarding: submission in, decision out, every step visible.

Run locally:   streamlit run app.py
"""

import html
import os
import time

import pandas as pd
import streamlit as st

from onboarding.llm import LLM
from onboarding.models import APPROVED, PENDING, REJECTED, COUNTRIES, ENTITY_TYPES, Submission
from onboarding.pipeline import STAGES, run_pipeline
from onboarding.samples import SAMPLES, doc_filename, find_sample, load_doc
from onboarding.seed import seed_if_empty
from onboarding.store import Store
from onboarding.validators import BANK_CODE_NAMES, TAX_ID_HINTS, TAX_ID_NAMES

DB_PATH = os.environ.get("VENDOR_DB", os.path.join("data", "onboarding.db"))

TEXT_FIELDS = [
    "legal_name", "tax_id", "address", "contact_name", "contact_email",
    "bank_account_holder", "bank_account", "bank_code",
]
SELECT_DEFAULTS = {"entity_type": "company", "country": "", "bank_country": ""}

STATUS_LABELS = {APPROVED: "Approved", PENDING: "Pending", REJECTED: "Rejected"}
STATUS_ICONS = {APPROVED: "✅", PENDING: "🟡", REJECTED: "⛔"}
SEVERITY_MARKS = {"ok": "✓", "note": "ℹ", "fix": "!", "block": "✕"}

CSS = """
<style>
.block-container { padding-top: 2.2rem; }
.stage { border: 1px solid #e3e6ea; border-left: 5px solid #c5cad1; border-radius: 8px;
         padding: 10px 14px; margin-bottom: 8px; background: #ffffff; }
.stage-queued  { border-left-color: #c5cad1; color: #8a929c; background: #fafbfc; }
.stage-running { border-left-color: #2f6fed; background: #f3f7ff; }
.stage-ok      { border-left-color: #1a7f4b; }
.stage-note    { border-left-color: #2f6fed; }
.stage-fix     { border-left-color: #c98a00; background: #fffaf0; }
.stage-block   { border-left-color: #c0392b; background: #fff5f4; }
.stage-head { display: flex; align-items: center; gap: 10px; font-weight: 600; }
.stage-title { flex: 1; }
.chip { font-size: 0.72rem; font-weight: 600; padding: 2px 8px; border-radius: 10px;
        background: #eef1f4; color: #47505b; white-space: nowrap; }
.chip-ai { background: #e8e4ff; color: #4a35b5; }
.chip-warn { background: #fff0cc; color: #8a5a00; }
.ms { font-size: 0.72rem; color: #8a929c; font-weight: 400; white-space: nowrap; }
.findings { margin: 6px 0 0 0; padding-left: 0; list-style: none; font-size: 0.9rem; }
.findings li { padding: 2px 0 2px 24px; position: relative; line-height: 1.4; }
.findings li .mark { position: absolute; left: 4px; font-weight: 700; }
.f-ok .mark { color: #1a7f4b; }  .f-ok { color: #3c4550; }
.f-note .mark { color: #2f6fed; }
.f-fix .mark { color: #c98a00; }
.f-block .mark { color: #c0392b; }
.lock { font-size: 0.72rem; color: #c0392b; font-weight: 600; margin-left: 6px; }
.verdict { border-radius: 10px; padding: 16px 20px; margin: 6px 0 14px 0; }
.verdict h3 { margin: 0 0 4px 0; padding: 0; font-size: 1.35rem; }
.verdict p { margin: 0; }
.verdict-approved { background: #e9f7ef; border: 1px solid #1a7f4b; }
.verdict-pending  { background: #fff7e0; border: 1px solid #c98a00; }
.verdict-rejected { background: #fdecea; border: 1px solid #c0392b; }
</style>
"""


# --------------------------------------------------------------------------
# Shared resources
# --------------------------------------------------------------------------

@st.cache_resource
def get_store():
    store = Store(DB_PATH)
    seed_if_empty(store)
    return store


def esc(value):
    return html.escape(str(value))


# --------------------------------------------------------------------------
# Rendering helpers
# --------------------------------------------------------------------------

def method_chip(method):
    if method == "AI":
        return '<span class="chip chip-ai">AI</span>'
    if method == "rules (AI unavailable)":
        return '<span class="chip chip-warn">rules · AI unavailable</span>'
    return '<span class="chip">rules</span>'


def stage_html(number, title, state, stage=None):
    """state: queued / running / done. stage: a StageResult dict when done."""
    if state == "queued":
        return ('<div class="stage stage-queued"><div class="stage-head">'
                '<span class="stage-title">%d. %s</span><span class="ms">queued</span>'
                '</div></div>' % (number, esc(title)))
    if state == "running":
        return ('<div class="stage stage-running"><div class="stage-head">'
                '<span class="stage-title">%d. %s</span><span class="ms">running…</span>'
                '</div></div>' % (number, esc(title)))

    items = []
    for f in stage["findings"]:
        lock = ""
        if f.get("confidential"):
            lock = '<span class="lock">CONFIDENTIAL · not shared with vendor</span>'
        items.append('<li class="f-%s"><span class="mark">%s</span>%s%s</li>' % (
            f["severity"], SEVERITY_MARKS[f["severity"]], esc(f["message"]), lock))
    return ('<div class="stage stage-%s"><div class="stage-head">'
            '<span class="stage-title">%d. %s</span>%s<span class="ms">%d ms</span></div>'
            '<ul class="findings">%s</ul></div>' % (
                stage["status"], number, esc(title), method_chip(stage["method"]),
                stage["duration_ms"], "".join(items)))


def render_trace(stages):
    for i, stage in enumerate(stages, start=1):
        st.markdown(stage_html(i, stage["title"], "done", stage), unsafe_allow_html=True)


def render_verdict(run):
    status = run["status"]
    extra = ""
    if run.get("resubmission_of"):
        extra = " Resubmission of %s." % esc(run["resubmission_of"])
    st.markdown(
        '<div class="verdict verdict-%s"><h3>%s %s · %s</h3><p>%s%s</p></div>' % (
            status, STATUS_ICONS[status], STATUS_LABELS[status], esc(run["run_id"]),
            esc(run["summary"]), extra),
        unsafe_allow_html=True)


def render_email(run, key_prefix):
    st.text_area(
        "Draft message to the vendor", value=run["vendor_email"], height=330,
        key="%s_email_%s" % (key_prefix, run["run_id"]), label_visibility="collapsed")
    st.caption("Draft only. Nothing is sent until a person reviews and approves it.")


def render_note(run, key_prefix):
    if run["internal_note"]:
        st.text_area(
            "Internal note", value=run["internal_note"], height=330,
            key="%s_note_%s" % (key_prefix, run["run_id"]), label_visibility="collapsed")
        st.caption("For the procurement team only. Contains reasons withheld from the vendor.")
    else:
        st.info("No internal escalation needed for this run.")


def render_outputs(run, key_prefix, stacked=False):
    """Vendor message and internal note for a finished run."""
    if stacked:
        note_title = "Internal note"
        if run["internal_note"]:
            note_title = "Internal note (1)"
        tab_email, tab_note = st.tabs(["Draft message to the vendor", note_title])
        with tab_email:
            render_email(run, key_prefix)
        with tab_note:
            render_note(run, key_prefix)
        return
    left, right = st.columns(2)
    with left:
        st.markdown("**Draft message to the vendor**")
        render_email(run, key_prefix)
    with right:
        st.markdown("**Internal note**")
        render_note(run, key_prefix)


def country_label(code):
    if not code:
        return "Select…"
    return "%s (%s)" % (COUNTRIES[code], code)


def entity_label(code):
    return ENTITY_TYPES[code]


def scenario_label(key):
    if key == "blank":
        return "Blank form (enter your own)"
    return find_sample(key)["label"]


def status_cell(status):
    return "%s %s" % (STATUS_ICONS[status], STATUS_LABELS[status])


RUN_LABELS = {}


def run_option_label(run_id):
    return RUN_LABELS.get(run_id, run_id)


# --------------------------------------------------------------------------
# Session state
# --------------------------------------------------------------------------

def init_state():
    for name in TEXT_FIELDS:
        st.session_state.setdefault("f_" + name, "")
    for name, default in SELECT_DEFAULTS.items():
        st.session_state.setdefault("f_" + name, default)
    st.session_state.setdefault("scenario_key", "blank")
    st.session_state.setdefault("sample_tax_doc", "")
    st.session_state.setdefault("sample_bank_doc", "")
    st.session_state.setdefault("form_version", 0)
    st.session_state.setdefault("last_run_id", "")


def apply_scenario():
    """Selectbox callback: fill the form from the chosen scenario."""
    entry = find_sample(st.session_state["scenario_key"])
    for name in TEXT_FIELDS:
        st.session_state["f_" + name] = entry["fields"].get(name, "") if entry else ""
    for name, default in SELECT_DEFAULTS.items():
        st.session_state["f_" + name] = entry["fields"].get(name, default) if entry else default
    st.session_state["sample_tax_doc"] = doc_filename(entry, "tax_doc") if entry else ""
    st.session_state["sample_bank_doc"] = doc_filename(entry, "bank_doc") if entry else ""
    st.session_state["form_version"] += 1      # clears any uploaded files
    st.session_state["last_run_id"] = ""


def reset_demo_data():
    store = get_store()
    store.reset()
    seed_if_empty(store)
    st.session_state["last_run_id"] = ""


def document_input(title, which, help_text):
    """Upload box plus the scenario's sample file. Returns (bytes, filename)."""
    st.markdown("**%s**" % title)
    uploaded = st.file_uploader(
        title, type=["pdf"], help=help_text, label_visibility="collapsed",
        key="up_%s_%d" % (which, st.session_state["form_version"]))
    if uploaded is not None:
        return uploaded.getvalue(), uploaded.name

    sample_name = st.session_state["sample_" + which]
    if sample_name:
        data = load_doc(sample_name)
        if data is not None:
            st.caption("Using the scenario's file: `%s`" % sample_name)
            st.download_button(
                "Open %s" % sample_name, data=data, file_name=sample_name, mime="application/pdf",
                key="dl_%s_%d" % (which, st.session_state["form_version"]))
            return data, sample_name
    st.caption("No file attached.")
    return None, ""


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

st.set_page_config(page_title="Vendor Onboarding", page_icon="🧾", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)
init_state()
store = get_store()
llm = LLM.from_settings()

with st.sidebar:
    st.header("Controls")
    if llm.enabled:
        st.success("AI: on · `%s`" % llm.model)
        if st.button("Test AI connection"):
            reply = llm.chat_text("You are a connection test.", "Reply with the single word OK.")
            if reply is None:
                st.error("AI call failed: %s" % llm.last_error)
            else:
                st.info("Model replied: %s" % reply[:80])
    else:
        st.warning("AI: off. Rule-based fallbacks are doing the judgement steps.")
        st.caption("To turn AI on, set `LLM_API_KEY`, `LLM_BASE_URL` and `LLM_MODEL` in the app's secrets.")
    pacing = st.toggle("Pace the live view", value=True,
                       help="Adds a short pause between stages so each one is visible as it runs.")
    st.divider()
    st.button("Reset demo data", on_click=reset_demo_data,
              help="Clears every run and restores the five seeded historical vendors.")
    st.caption("Use before a demo. A vendor that was already approved is rejected as a "
               "duplicate if submitted again, which is correct but surprising mid-demo.")

st.title("Vendor Onboarding")
st.caption("A vendor submission goes in. Eight checks run in order. Out comes approved, pending "
           "or rejected, with the reasoning and the message back to the vendor.")

tab_run, tab_dash, tab_how = st.tabs(["▶ New submission", "📊 Dashboard", "🧭 How it works"])

# ------------------------------- New submission ---------------------------

with tab_run:
    scenario_keys = ["blank"] + [entry["key"] for entry in SAMPLES]
    st.selectbox("Start from a scenario", scenario_keys, format_func=scenario_label,
                 key="scenario_key", on_change=apply_scenario)
    chosen = find_sample(st.session_state["scenario_key"])
    if chosen is not None:
        st.info("%s  \n**Expected outcome:** %s" % (chosen["description"], STATUS_LABELS[chosen["expected"]]))

    col_form, col_run = st.columns([1, 1.15], gap="large")
    country_codes = [""] + list(COUNTRIES.keys())

    with col_form:
        st.subheader("Submission")
        st.markdown("**Company**")
        st.text_input("Registered legal name", key="f_legal_name")
        c1, c2 = st.columns(2)
        with c1:
            st.selectbox("Entity type", list(ENTITY_TYPES.keys()), format_func=entity_label, key="f_entity_type")
        with c2:
            st.selectbox("Country of registration", country_codes, format_func=country_label, key="f_country")
        country = st.session_state["f_country"]
        tax_label = "Tax registration number"
        tax_help = "Pick a country to see the expected format."
        if country:
            tax_label = "Tax registration number (%s)" % TAX_ID_NAMES[country]
            tax_help = TAX_ID_HINTS[country]
        st.text_input(tax_label, key="f_tax_id", help=tax_help)
        st.text_input("Registered address", key="f_address")
        c1, c2 = st.columns(2)
        with c1:
            st.text_input("Contact name", key="f_contact_name")
        with c2:
            st.text_input("Contact email", key="f_contact_email")

        st.markdown("**Bank account**")
        st.text_input("Account holder name", key="f_bank_account_holder",
                      help="Exactly as it appears on the bank's records.")
        c1, c2 = st.columns(2)
        with c1:
            st.selectbox("Bank country", country_codes, format_func=country_label, key="f_bank_country")
        bank_country = st.session_state["f_bank_country"]
        with c2:
            st.text_input(BANK_CODE_NAMES.get(bank_country, "Bank code (IFSC / routing / BIC)"),
                          key="f_bank_code")
        account_label = "IBAN" if bank_country in ("GB", "DE") else "Account number"
        st.text_input(account_label, key="f_bank_account")

        c1, c2 = st.columns(2)
        with c1:
            tax_bytes, tax_name = document_input(
                "Tax registration certificate", "tax_doc",
                "The certificate issued by the tax authority, as a text PDF.")
        with c2:
            bank_bytes, bank_name = document_input(
                "Bank account proof", "bank_doc",
                "A bank letter or cancelled cheque showing the holder and account number.")

    with col_run:
        st.subheader("Live run")
        clicked = st.button("Run onboarding checks", type="primary", width="stretch")

        if clicked:
            submission = Submission(
                legal_name=st.session_state["f_legal_name"].strip(),
                entity_type=st.session_state["f_entity_type"],
                country=st.session_state["f_country"],
                tax_id=st.session_state["f_tax_id"].strip(),
                address=st.session_state["f_address"].strip(),
                contact_name=st.session_state["f_contact_name"].strip(),
                contact_email=st.session_state["f_contact_email"].strip(),
                bank_account_holder=st.session_state["f_bank_account_holder"].strip(),
                bank_country=st.session_state["f_bank_country"],
                bank_account=st.session_state["f_bank_account"].strip(),
                bank_code=st.session_state["f_bank_code"].strip(),
                tax_doc=tax_bytes, tax_doc_name=tax_name,
                bank_doc=bank_bytes, bank_doc_name=bank_name,
            )

            verdict_slot = st.empty()
            slots = []
            for i, (key, title) in enumerate(STAGES, start=1):
                slot = st.empty()
                slot.markdown(stage_html(i, title, "queued"), unsafe_allow_html=True)
                slots.append(slot)

            index_of = {}
            for i, (key, title) in enumerate(STAGES):
                index_of[key] = i

            finished = None
            for event, payload in run_pipeline(submission, store, llm):
                if event == "start":
                    i = index_of[payload]
                    slots[i].markdown(stage_html(i + 1, STAGES[i][1], "running"), unsafe_allow_html=True)
                    if pacing:
                        time.sleep(0.45)
                elif event == "done":
                    i = index_of[payload.key]
                    slots[i].markdown(stage_html(i + 1, payload.title, "done", payload.to_dict()),
                                      unsafe_allow_html=True)
                else:
                    finished = payload.to_dict()

            st.session_state["last_run_id"] = finished["run_id"]
            with verdict_slot.container():
                render_verdict(finished)
            if llm.enabled and llm.failures:
                st.warning("An AI call failed during this run, so that step used its rule-based "
                           "fallback. Last error: %s" % llm.last_error)
            render_outputs(finished, "live", stacked=True)

        elif st.session_state["last_run_id"]:
            previous = store.get(st.session_state["last_run_id"])
            if previous is not None:
                render_verdict(previous)
                render_trace(previous["stages"])
                render_outputs(previous, "last", stacked=True)
        else:
            for i, (key, title) in enumerate(STAGES, start=1):
                st.markdown(stage_html(i, title, "queued"), unsafe_allow_html=True)
            st.caption("Pick a scenario or fill in the form, then run the checks. "
                       "Each stage fills in here as it executes.")

# ------------------------------- Dashboard --------------------------------

with tab_dash:
    rows = store.list_runs()
    total = len(rows)
    counts = {APPROVED: 0, PENDING: 0, REJECTED: 0}
    for row in rows:
        counts[row["status"]] += 1

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total runs", total)
    m2.metric("Approved", counts[APPROVED])
    m3.metric("Pending on vendor", counts[PENDING])
    m4.metric("Rejected", counts[REJECTED])
    rate = "–"
    if total:
        rate = "%d%%" % round(100 * counts[APPROVED] / total)
    m5.metric("Approval rate", rate)

    f1, f2 = st.columns([1, 2])
    with f1:
        wanted = st.multiselect("Status", [APPROVED, PENDING, REJECTED],
                                default=[APPROVED, PENDING, REJECTED], format_func=STATUS_LABELS.get)
    with f2:
        search = st.text_input("Search vendor name", "")

    visible = []
    for row in rows:
        if row["status"] not in wanted:
            continue
        if search.strip() and search.strip().lower() not in (row["vendor_name"] or "").lower():
            continue
        visible.append(row)

    if not visible:
        st.info("No runs match these filters.")
    else:
        table = pd.DataFrame({
            "Run": [r["run_id"] for r in visible],
            "When (UTC)": [r["created_at"] for r in visible],
            "Vendor": [r["vendor_name"] or "(no name)" for r in visible],
            "Country": [r["country"] for r in visible],
            "Status": [status_cell(r["status"]) for r in visible],
            "Outcome": [r["summary"] for r in visible],
            "AI": [r["ai_mode"] for r in visible],
        })
        st.dataframe(table, hide_index=True, width="stretch")

        st.subheader("Run detail")
        for r in visible:
            RUN_LABELS[r["run_id"]] = "%s · %s · %s" % (
                r["run_id"], r["vendor_name"] or "(no name)", STATUS_LABELS[r["status"]])
        picked = st.selectbox("Open a run", [r["run_id"] for r in visible],
                              format_func=run_option_label, key="dash_pick")
        detail = store.get(picked)
        render_verdict(detail)

        d1, d2 = st.columns([1, 1.4])
        with d1:
            st.markdown("**What the vendor submitted**")
            sub = detail["submission"]
            shown = pd.DataFrame({
                "Field": [
                    "Legal name", "Entity type", "Country", "Tax ID", "Address", "Contact",
                    "Contact email", "Account holder", "Bank country", "Account / IBAN",
                    "Bank code", "Tax document", "Bank document",
                ],
                "Value": [
                    sub["legal_name"], ENTITY_TYPES.get(sub["entity_type"], sub["entity_type"]),
                    COUNTRIES.get(sub["country"], sub["country"]), sub["tax_id"], sub["address"],
                    sub["contact_name"], sub["contact_email"], sub["bank_account_holder"],
                    COUNTRIES.get(sub["bank_country"], sub["bank_country"]), sub["bank_account"],
                    sub["bank_code"], sub["tax_doc_name"] or "(none)", sub["bank_doc_name"] or "(none)",
                ],
            })
            st.dataframe(shown, hide_index=True, width="stretch", height=495)
            st.caption("Ran %s UTC · %d ms · AI %s" % (
                detail["created_at"], detail["duration_ms"], detail["ai_mode"]))
        with d2:
            st.markdown("**What happened at each stage**")
            render_trace(detail["stages"])

        render_outputs(detail, "dash")

# ------------------------------- How it works -----------------------------

with tab_how:
    left, right = st.columns([1, 1.2])
    with left:
        st.subheader("Process map")
        st.graphviz_chart("""
            digraph {
                rankdir=TB; node [shape=box, style="rounded,filled", fillcolor="#f3f5f8", fontname="Helvetica", fontsize=11];
                edge [fontname="Helvetica", fontsize=10];
                sub [label="Vendor submission\\n(form + 2 PDFs)", fillcolor="#e8e4ff"];
                s1 [label="1. Intake"]; s2 [label="2. Completeness"]; s3 [label="3. Format validation"];
                s4 [label="4. Cross-field consistency"]; s5 [label="5. Document verification"];
                s6 [label="6. Duplicate and risk checks"]; s7 [label="7. Decision", shape=diamond, fillcolor="#fff7e0"];
                ok [label="APPROVED\\nconfirmation drafted", fillcolor="#e9f7ef"];
                pend [label="PENDING\\nchecklist drafted for vendor", fillcolor="#fff7e0"];
                rej [label="REJECTED\\nneutral notice + internal note", fillcolor="#fdecea"];
                human [label="Human reviews drafts\\n(nothing is auto-sent)", fillcolor="#e8e4ff"];
                sub -> s1 -> s2 -> s3 -> s4 -> s5 -> s6 -> s7;
                s7 -> ok [label="nothing to fix"]; s7 -> pend [label="vendor can fix it"]; s7 -> rej [label="blocking finding"];
                ok -> human; pend -> human; rej -> human;
                pend -> sub [label="vendor resubmits", style=dashed, constraint=false];
            }
        """)
    with right:
        st.subheader("How decisions are made")
        st.markdown("""
Every check produces findings at one of four levels:

| Level | Meaning | Effect |
|---|---|---|
| ✓ ok | Check passed | none |
| ℹ note | Passed, but the reviewer should know | none |
| ! fix | The vendor can correct it | **Pending** |
| ✕ block | The vendor cannot correct it, or it signals fraud | **Rejected** |

**The rule:** any block rejects. Otherwise any fix makes it pending. Otherwise approved.

**All checks always run.** The process does not stop at the first problem, so the
vendor gets one complete list instead of several rounds of emails.

**Where AI is used, and its limits**
- *Judging names* (stage 4): are "Acme Technologies Pvt Ltd" and "ACME TECH PRIVATE LIMITED"
  the same company? AI gives a second opinion on anything short of an exact match.
  It can raise a concern but never lower one: it cannot turn a clear mismatch into an
  approval, and it cannot clear a personal-account flag the rules have raised.
- *Reading documents* (stage 5): what kind of document is this, and who is it issued to?
- *Wording* (stage 8): the opening line of the vendor message. The checklist itself is
  assembled by rules, so AI cannot drop a requirement or leak a confidential reason.
- If an AI call fails or AI is switched off, each step falls back to rules and the run
  trace says so. The decision never depends on AI being available.

**What stays confidential.** Fraud signals (a company paid into a personal account, a bank
account shared with another vendor) are never put in the vendor message. They go into an
internal note for the procurement team.

**Known limits of this build**
- Four countries: India, UK, US, Germany.
- Scanned or photographed documents are not read (no OCR); the vendor is asked for a text PDF.
- UK, US and German tax IDs are format-checked only. GSTINs, IBANs and US routing numbers
  are also checksum-checked. Nothing is verified against a government registry.
- Messages are drafts. Sending is left to a person.
""")
