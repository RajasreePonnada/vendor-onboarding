"""Fills an empty store with a few historical runs.

Seeds go through the real pipeline (rule path, no AI) so the history shown on
the dashboard is produced by the same logic as live runs.
"""

from datetime import datetime, timedelta, timezone

from .llm import LLM
from .pipeline import run_to_completion
from .samples import SEEDS, to_submission


def seed_if_empty(store):
    """Returns the number of runs added."""
    if store.count() > 0:
        return 0
    now = datetime.now(timezone.utc)
    added = 0
    for entry in SEEDS:
        when = now - timedelta(days=entry["days_ago"], hours=added * 3 + 1)
        run_to_completion(
            to_submission(entry), store, LLM.disabled(),
            created_at=when.strftime("%Y-%m-%d %H:%M:%S"),
        )
        added += 1
    return added
