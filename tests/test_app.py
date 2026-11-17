"""Drives the Streamlit app headlessly: loads it, runs every scenario through
the UI, and checks the verdict shown on screen.

Run from the project root:   python tests/test_app.py
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ["VENDOR_DB"] = os.path.join(tempfile.mkdtemp(), "app_test.db")
for name in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
    os.environ.pop(name, None)

from streamlit.testing.v1 import AppTest  # noqa: E402

from onboarding.models import APPROVED, PENDING, REJECTED  # noqa: E402
from onboarding.samples import SAMPLES  # noqa: E402

WORDS = {APPROVED: "Approved", PENDING: "Pending", REJECTED: "Rejected"}
failures = []


def check(label, condition, detail=""):
    print("  [%s] %s %s" % ("PASS" if condition else "FAIL", label, detail))
    if not condition:
        failures.append(label)


def page_text(at):
    parts = []
    for element in at.markdown:
        parts.append(element.value)
    return "\n".join(parts)


def find_button(at, label):
    for button in at.button:
        if button.label == label:
            return button
    return None


def find_selectbox(at, label):
    for box in at.selectbox:
        if box.label == label:
            return box
    return None


at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=60)
at.run()
check("app loads without an exception", not at.exception, str(at.exception))
check("dashboard shows the 5 seeded runs", at.metric[0].value == "5", "(got %s)" % at.metric[0].value)

at.toggle[0].set_value(False).run()   # no pauses while testing

for entry in SAMPLES:
    find_button(at, "Reset demo data").click().run()
    find_selectbox(at, "Start from a scenario").set_value(entry["key"]).run()
    find_button(at, "Run onboarding checks").click().run()
    text = page_text(at)
    verdict = ""
    for line in text.split("\n"):
        if 'class="verdict' in line:
            verdict = line
            break
    check("UI run: %s -> %s" % (entry["key"], WORDS[entry["expected"]]),
          not at.exception and ("verdict-%s" % entry["expected"]) in verdict,
          str(at.exception) if at.exception else "")
    check("  live view rendered all 8 stages", text.count('class="stage stage-') >= 8)

# Blank form
find_button(at, "Reset demo data").click().run()
find_selectbox(at, "Start from a scenario").set_value("blank").run()
find_button(at, "Run onboarding checks").click().run()
check("UI run: blank form -> Pending, no crash",
      not at.exception and "verdict-pending" in page_text(at), str(at.exception) if at.exception else "")

# Duplicate: happy path twice without a reset
find_button(at, "Reset demo data").click().run()
find_selectbox(at, "Start from a scenario").set_value("happy_path").run()
find_button(at, "Run onboarding checks").click().run()
find_button(at, "Run onboarding checks").click().run()
check("UI run: happy path a second time -> Rejected as duplicate",
      not at.exception and "verdict-rejected" in page_text(at))
check("dashboard count grew to 7", at.metric[0].value == "7", "(got %s)" % at.metric[0].value)

print()
if failures:
    print("%d check(s) FAILED: %s" % (len(failures), failures))
    sys.exit(1)
print("All UI checks passed.")
