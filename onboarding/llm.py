"""Thin client for any OpenAI-compatible chat-completions endpoint.

Works with OpenAI, Gemini (OpenAI-compatible endpoint), Groq, OpenRouter and
others: set LLM_API_KEY, LLM_BASE_URL and LLM_MODEL. LLM_REASONING_EFFORT is
optional (for example "low") and is only sent when set.

Design rule: the AI is never a single point of failure. Every call returns
None on any problem (no key, timeout, bad JSON) and the caller falls back to a
rule-based path. The run trace records which path was used.
"""

import json
import os

import requests

TIMEOUT_SECONDS = 25


def read_setting(name):
    """Environment variable first, then Streamlit secrets if available."""
    value = os.environ.get(name, "")
    if value:
        return value.strip()
    try:
        import streamlit as st
        if name in st.secrets:
            return str(st.secrets[name]).strip()
    except Exception:
        pass
    return ""


def extract_json(text):
    """Pull the first JSON object out of a model reply (handles code fences)."""
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start:end + 1])
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


class LLM:
    def __init__(self, api_key="", base_url="", model=""):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.last_error = ""
        self.calls = 0
        self.failures = 0

    @classmethod
    def from_settings(cls):
        return cls(
            api_key=read_setting("LLM_API_KEY"),
            base_url=read_setting("LLM_BASE_URL"),
            model=read_setting("LLM_MODEL"),
        )

    @classmethod
    def disabled(cls):
        return cls()

    @property
    def enabled(self):
        return bool(self.api_key and self.base_url and self.model)

    def describe(self):
        if self.enabled:
            return "on (%s)" % self.model
        return "off"

    def chat_text(self, system, user):
        """Returns the reply text, or None on any failure."""
        if not self.enabled:
            return None
        self.calls += 1
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        # No token cap is sent: caps are named differently across providers, and
        # reasoning models can spend a small cap before writing any answer.
        effort = read_setting("LLM_REASONING_EFFORT")
        if effort:
            payload["reasoning_effort"] = effort
        headers = {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(
                self.base_url + "/chat/completions",
                headers=headers, json=payload, timeout=TIMEOUT_SECONDS,
            )
            if response.status_code != 200:
                self.failures += 1
                self.last_error = "HTTP %d: %s" % (response.status_code, response.text[:200])
                return None
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                self.failures += 1
                self.last_error = "Empty reply from model."
                return None
            return content.strip()
        except Exception as exc:
            self.failures += 1
            self.last_error = "%s: %s" % (type(exc).__name__, str(exc)[:200])
            return None

    def chat_json(self, system, user):
        """Returns a dict parsed from the reply, or None on any failure."""
        text = self.chat_text(system, user)
        if text is None:
            return None
        parsed = extract_json(text)
        if parsed is None:
            self.failures += 1
            self.last_error = "Model reply was not valid JSON."
        return parsed
