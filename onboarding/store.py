"""SQLite store for runs. One row per pipeline run; approved rows double as the
vendor master used for duplicate checks."""

import json
import os
import sqlite3

from .models import APPROVED
from .validators import compact

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    seq           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT UNIQUE,
    created_at    TEXT,
    vendor_name   TEXT,
    country       TEXT,
    status        TEXT,
    summary       TEXT,
    tax_key       TEXT,
    bank_key      TEXT,
    ai_mode       TEXT,
    duration_ms   INTEGER,
    result_json   TEXT
)
"""


class Store:
    def __init__(self, path):
        self.path = path
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(SCHEMA)
        self.conn.commit()

    def reset(self):
        self.conn.execute("DROP TABLE IF EXISTS runs")
        self.conn.execute(SCHEMA)
        self.conn.commit()

    def count(self):
        return self.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]

    def next_run_id(self):
        row = self.conn.execute("SELECT MAX(seq) FROM runs").fetchone()
        number = (row[0] or 0) + 1
        return "VND-%04d" % number

    def save(self, result):
        sub = result.submission
        self.conn.execute(
            "INSERT INTO runs (run_id, created_at, vendor_name, country, status, summary, "
            "tax_key, bank_key, ai_mode, duration_ms, result_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                result.run_id, result.created_at, sub.get("legal_name", ""),
                sub.get("country", ""), result.status, result.summary,
                compact(sub.get("tax_id", "")), compact(sub.get("bank_account", "")),
                result.ai_mode, result.duration_ms, json.dumps(result.to_dict()),
            ),
        )
        self.conn.commit()

    def list_runs(self):
        rows = self.conn.execute(
            "SELECT run_id, created_at, vendor_name, country, status, summary, ai_mode, "
            "duration_ms FROM runs ORDER BY seq DESC").fetchall()
        return [dict(r) for r in rows]

    def get(self, run_id):
        row = self.conn.execute(
            "SELECT result_json FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return json.loads(row["result_json"])

    def approved_with_bank(self, bank_account):
        """Approved vendors already using this bank account."""
        key = compact(bank_account)
        if not key:
            return []
        rows = self.conn.execute(
            "SELECT run_id, vendor_name, tax_key FROM runs WHERE bank_key = ? AND status = ? "
            "ORDER BY seq", (key, APPROVED)).fetchall()
        return [dict(r) for r in rows]

    def latest_with_tax_id(self, tax_id):
        """Most recent run for this tax ID, or None."""
        key = compact(tax_id)
        if not key:
            return None
        row = self.conn.execute(
            "SELECT run_id, vendor_name, status, bank_key FROM runs WHERE tax_key = ? "
            "ORDER BY seq DESC LIMIT 1", (key,)).fetchone()
        if row is None:
            return None
        return dict(row)

    def approved_with_tax_id(self, tax_id):
        key = compact(tax_id)
        if not key:
            return None
        row = self.conn.execute(
            "SELECT run_id, vendor_name, status, bank_key FROM runs WHERE tax_key = ? "
            "AND status = ? ORDER BY seq DESC LIMIT 1", (key, APPROVED)).fetchone()
        if row is None:
            return None
        return dict(row)
